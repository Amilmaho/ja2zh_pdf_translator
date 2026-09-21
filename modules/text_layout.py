"""
文本排版模块（纯计算，不依赖 PyMuPDF 页面对象）。

职责：在一个矩形框内，为一段中日文混排文本找到「最大且完整放得下」的字号。

为什么需要它：
  旧代码把文本直接丢给 insert_textbox，靠返回值的正负判断是否成功。
  一旦放不下就什么都不画，但前面已经画了白色矩形 —— 结果就是
  「翻译后的图片大部分都是空白」。这里先算清楚能不能放、放几行、
  每行多宽，再决定是否覆盖原图，从根上避免空白色块。
"""

from dataclasses import dataclass
from typing import List, Optional, Sequence

import fitz  # PyMuPDF


# 不能出现在行首的标点（日文/中文避头尾）
_NO_LINE_START = set("、。，．,.;:!?！？：；）)]}」』】〕〉》”’ー～ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ")
# 不能出现在行尾的标点
_NO_LINE_END = set("（([{「『【〔〈《“‘")


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3040 <= code <= 0x30FF      # 假名
        or 0x3400 <= code <= 0x4DBF   # CJK 扩展 A
        or 0x4E00 <= code <= 0x9FFF   # CJK 基本区
        or 0xF900 <= code <= 0xFAFF   # 兼容表意
        or 0xFF00 <= code <= 0xFF60   # 全角
        or 0x3000 <= code <= 0x303F   # CJK 标点
    )


def tokenize(text: str) -> List[str]:
    """
    把文本切成排版单位：
      - 拉丁字母/数字连续串视为一个整体（不在单词中间断行）
      - 中日文按字切分
      - 空格单独成 token
    """
    tokens: List[str] = []
    buf = ""
    for ch in text:
        if ch in (" ", "\t"):
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(" ")
        elif _is_cjk(ch):
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
        else:
            buf += ch
    if buf:
        tokens.append(buf)
    return tokens


@dataclass
class TextLayout:
    """一段文本的排版结果"""
    lines: List[str]
    font_size: float
    line_height: float
    width: float = 0.0
    height: float = 0.0
    truncated: bool = False

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class TextFitter:
    """基于 fitz.Font 的测宽 / 换行 / 自适应字号"""

    def __init__(self, font: fitz.Font, line_height_ratio: float = 1.18):
        self.font = font
        self.line_height_ratio = line_height_ratio

    # ── 基础测量 ─────────────────────────────────────────

    def width(self, text: str, size: float) -> float:
        if not text:
            return 0.0
        try:
            return float(self.font.text_length(text, fontsize=size))
        except Exception:
            # 极端情况下退化为按字符数估算（CJK 约 1em，拉丁约 0.5em）
            return sum(size if _is_cjk(c) else size * 0.5 for c in text)

    def wrap(self, text: str, size: float, max_width: float) -> List[str]:
        """按最大宽度换行，返回行列表"""
        if max_width <= 0:
            return [text]

        lines: List[str] = []
        for para in text.split("\n"):
            if not para.strip():
                lines.append("")
                continue

            current = ""
            for token in tokenize(para):
                candidate = current + token
                if self.width(candidate, size) <= max_width or not current:
                    current = candidate
                    continue

                # 避头尾：标点不落行首
                if token.strip() and token.strip()[0] in _NO_LINE_START:
                    current += token
                    continue

                # 避头尾：左括号不落行尾
                if current and current[-1] in _NO_LINE_END:
                    moved = current[-1]
                    lines.append(current[:-1])
                    current = moved + token
                else:
                    lines.append(current.rstrip())
                    current = "" if token == " " else token

            if current.strip():
                lines.append(current.rstrip())

        return lines or [text]

    def measure(self, lines: Sequence[str], size: float) -> tuple:
        """返回 (最大行宽, 总高度)"""
        max_w = max((self.width(ln, size) for ln in lines), default=0.0)
        height = max(1, len(lines)) * size * self.line_height_ratio
        return max_w, height

    # ── 自适应字号 ───────────────────────────────────────

    def fit(
        self,
        text: str,
        box_w: float,
        box_h: float,
        max_size: float = 16.0,
        min_size: float = 5.0,
    ) -> Optional[TextLayout]:
        """
        找出能完整放进 box 的最大字号。

        Returns:
            TextLayout，或 None（连最小字号都放不下）
        """
        text = (text or "").strip()
        if not text or box_w <= 0 or box_h <= 0:
            return None

        max_size = max(min_size, max_size)
        best: Optional[TextLayout] = None

        # 二分搜索：找最大可用字号（约 14 次迭代，精度足够）
        lo, hi = min_size, max_size
        for _ in range(14):
            mid = (lo + hi) / 2
            lines = self.wrap(text, mid, box_w)
            width, height = self.measure(lines, mid)
            if height <= box_h and width <= box_w:
                best = TextLayout(lines, mid, mid * self.line_height_ratio, width, height)
                lo = mid
            else:
                hi = mid

        return best

    def fit_truncated(
        self,
        text: str,
        box_w: float,
        box_h: float,
        size: float,
    ) -> Optional[TextLayout]:
        """在固定字号下尽量多放几行，放不下的部分用省略号表示"""
        text = (text or "").strip()
        if not text:
            return None
        lines = self.wrap(text, size, box_w)
        max_lines = max(1, int(box_h // (size * self.line_height_ratio)))
        if len(lines) <= max_lines:
            width, height = self.measure(lines, size)
            return TextLayout(lines, size, size * self.line_height_ratio, width, height)

        kept = lines[:max_lines]
        overflow = "".join(lines[max_lines:])
        last = kept[-1]
        while last and self.width(last + "…", size) > box_w:
            last = last[:-1]
        kept[-1] = (last or "") + "…"
        width, height = self.measure(kept, size)
        return TextLayout(kept, size, size * self.line_height_ratio,
                          width, height, truncated=bool(overflow))
