"""
PDF 生成模块（重构版）

核心思路：**在原 PDF 的副本上原地改写**，而不是从零新建空白页。
  1. 打开源 PDF 副本 → 原图、矢量、版式 100% 保留
  2. 文字型页面：用 redaction 精确删除原文 → 再写入译文
  3. 图片型页面：按区域底色覆盖 → 再写入译文
  4. 写之前先用 TextFitter 算清楚「放不放得下」，放不下就不覆盖

这直接修掉了旧版「翻译后的图片大部分都是空白」的问题：
旧版先画白底再用 insert_textbox 试写，写不进去就留下白块；
新版先排版后绘制，永远不会出现「有白块没文字」的情况。
"""

import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import fitz  # PyMuPDF
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config
from modules.fonts import get_font, get_font_path
from modules.text_layout import TextFitter
from modules.utils import ProgressReporter


FONT_NAME = "cjk"


class _PageDrawer:
    """
    一页的绘制缓冲。

    用 fitz.TextWriter 而不是 page.insert_text：
      - insert_text 每次都要重新解析字体文件，速度慢且在部分字体上会报
        "need font file or buffer"
      - TextWriter 直接使用已加载的 fitz.Font 对象，并支持按颜色分批写入
    """

    def __init__(self, page: fitz.Page, font: fitz.Font):
        self.page = page
        self.font = font
        self._writers: Dict[tuple, fitz.TextWriter] = {}

    def write_line(self, point, text: str, font_size: float, color):
        key = (round(color[0], 3), round(color[1], 3), round(color[2], 3))
        writer = self._writers.get(key)
        if writer is None:
            writer = fitz.TextWriter(self.page.rect)
            self._writers[key] = writer
        writer.append(point, text, font=self.font, fontsize=font_size)

    def flush(self):
        for color, writer in self._writers.items():
            if writer.text_rect is None:
                continue
            writer.write_text(self.page, color=color, overlay=True)
        self._writers.clear()


# ── 输入计划的数据结构 ────────────────────────────────────

@dataclass
class TextItem:
    """文字型页面里的一行：原文 + 译文"""
    rect: fitz.Rect
    translated: str
    original: str = ""
    font_size: float = 10.0


@dataclass
class OverlayItem:
    """图片型页面里的一个 OCR 区域：图片像素坐标 + 译文"""
    image_bbox: Tuple[float, float, float, float]
    translated: str
    original: str = ""
    confidence: float = 1.0
    image_size: Tuple[int, int] = (0, 0)
    image_rect: Tuple[float, float, float, float] = (0, 0, 0, 0)
    # 目标字号：按原文字形的实际大小标定（0 表示按框高估算）
    target_size: float = 0.0


@dataclass
class PagePlan:
    """一页的改写计划"""
    page_num: int
    text_items: List[TextItem] = field(default_factory=list)
    overlay_items: List[OverlayItem] = field(default_factory=list)
    page_width: float = 0.0
    page_height: float = 0.0
    # 用页面自带的隐藏 OCR 文字层做识别时置 True：
    # 绘制前先把整页文字层删掉（保留图片），避免译文底下压着一层日文
    redact_text_layer: bool = False
    # 目标字号 = 区域高度 × 该系数。
    # OCR 的框是紧贴字形的「墨迹框」(0.85)；
    # PDF 文字层的框是字体度量框（更高），所以系数要小一些。
    box_height_factor: float = 0.85

    @property
    def is_empty(self) -> bool:
        return not self.text_items and not self.overlay_items


@dataclass
class PageResult:
    """一页的渲染结果（用于汇总/自检）"""
    page_num: int
    mode: str = "skip"
    drawn: int = 0
    kept_original: int = 0
    failed: int = 0


@dataclass
class GenerateStats:
    pages_total: int = 0
    pages_text: int = 0
    pages_overlay: int = 0
    items_drawn: int = 0
    items_kept_original: int = 0
    items_failed: int = 0
    page_results: List[PageResult] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        """是否存在需要人工确认的页面（有区域放不下译文）"""
        return self.items_failed > 0

    def summary(self) -> str:
        return (
            f"共 {self.pages_total} 页"
            f"（文字页 {self.pages_text} / 图片页 {self.pages_overlay}），"
            f"写入译文 {self.items_drawn} 处，"
            f"保留原文 {self.items_kept_original} 处，"
            f"放不下 {self.items_failed} 处"
        )


# ── 生成器 ────────────────────────────────────────────────

class PDFGenerator:
    """在原 PDF 副本上写入译文"""

    def __init__(
        self,
        output_path: str,
        font_path: str = None,
        source_pdf: str = None,
        fill_mode: str = None,
        text_color: str = None,
        min_font: float = None,
        max_font: float = None,
        expand: bool = None,
        sample_dpi: int = 150,
        verbose: bool = True,
    ):
        self.output_path = output_path
        self.source_pdf = source_pdf
        self.fill_mode = fill_mode or config.OVERLAY_FILL_MODE
        self.text_color_mode = text_color or config.OVERLAY_TEXT_COLOR
        self.min_font = min_font if min_font is not None else config.OVERLAY_MIN_FONT
        self.max_font = max_font if max_font is not None else config.OVERLAY_MAX_FONT
        self.expand = config.OVERLAY_EXPAND if expand is None else expand
        self.sample_dpi = sample_dpi
        self.verbose = verbose

        self.font_path = font_path or get_font_path()
        self.font = get_font()
        # 行距取得比默认更紧凑：OCR 文本框通常只比字形高一点点，
        # 行距太大会让两行译文放不进去。
        self.fitter = TextFitter(self.font, line_height_ratio=1.12)
        self._pixmap_cache: Dict[int, np.ndarray] = {}

        if self.verbose:
            print(f"[PDF生成] 字体: {os.path.basename(self.font_path)}", flush=True)

    # ── 主入口 ───────────────────────────────────────────

    def apply(
        self,
        plans: Sequence[PagePlan],
        progress=None,
    ) -> GenerateStats:
        """
        在源 PDF 副本上执行改写计划并保存。

        Args:
            plans: 每页的改写计划（只包含需要改写的页）
            progress: 可选回调 fn(done, total, desc)
        """
        if not self.source_pdf:
            raise ValueError("PDFGenerator 需要 source_pdf（在原文件副本上改写）")

        doc = fitz.open(self.source_pdf)
        stats = GenerateStats(pages_total=len(doc))
        reporter = ProgressReporter(verbose=self.verbose)

        for i, plan in enumerate(plans):
            page = doc[plan.page_num]
            result = self._apply_page(doc, page, plan)
            stats.page_results.append(result)
            stats.items_drawn += result.drawn
            stats.items_kept_original += result.kept_original
            stats.items_failed += result.failed
            if result.mode == "text":
                stats.pages_text += 1
            elif result.mode == "overlay":
                stats.pages_overlay += 1

            if progress and (i % 5 == 0 or i == len(plans) - 1):
                try:
                    progress(i + 1, len(plans), "生成 PDF")
                except TypeError:
                    pass
            if self.verbose and (i % 20 == 0 or i == len(plans) - 1):
                reporter.log(f"已处理 {i + 1}/{len(plans)} 页", "info")

        os.makedirs(os.path.dirname(self.output_path) or ".", exist_ok=True)
        doc.save(self.output_path, garbage=3, deflate=True)
        doc.close()

        if self.verbose:
            size_mb = os.path.getsize(self.output_path) / 1024 / 1024
            print(f"[PDF生成] 已保存: {self.output_path} ({size_mb:.1f} MB)", flush=True)
        return stats

    # ── 单页处理 ─────────────────────────────────────────

    def _apply_page(self, doc: fitz.Document, page: fitz.Page, plan: PagePlan) -> PageResult:
        result = PageResult(page_num=plan.page_num)
        if plan.is_empty:
            return result

        drawer = _PageDrawer(page, self.font)

        # 扫描件若自带隐藏文字层，先把这层删掉（图片/矢量保留），
        # 否则输出里会残留一层看不见的日文（复制粘贴时会跑出来）
        if plan.redact_text_layer and not plan.text_items:
            try:
                page.add_redact_annot(page.rect, fill=False)
                page.apply_redactions(
                    images=fitz.PDF_REDACT_IMAGE_NONE,
                    graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                    text=fitz.PDF_REDACT_TEXT_REMOVE,
                )
            except Exception:
                pass

        drawn = kept = failed = 0
        if plan.text_items:
            result.mode = "text"
            d, k, f = self._apply_text_items(page, plan, drawer)
            drawn, kept, failed = drawn + d, kept + k, failed + f
        if plan.overlay_items:
            if not plan.text_items:
                result.mode = "overlay"
            d, k, f = self._apply_overlay_items(page, plan, drawer)
            drawn, kept, failed = drawn + d, kept + k, failed + f

        drawer.flush()

        result.drawn, result.kept_original, result.failed = drawn, kept, failed
        return result

    # ── 文字型页面：redaction + 写入 ──────────────────────

    def _apply_text_items(
        self, page: fitz.Page, plan: PagePlan, drawer: _PageDrawer
    ) -> Tuple[int, int, int]:
        drawn = kept = failed = 0
        layouts = []

        # 1) 先排版，决定哪些能写
        for item in plan.text_items:
            text = (item.translated or "").strip()
            if not text:
                kept += 1
                continue
            layout, rect = self._layout_for(
                text, item.rect, item.font_size,
                page.rect, max_size=self.max_font,
            )
            if layout is None:
                failed += 1
                continue
            layouts.append((layout, rect))
            # 2) 删掉这一行的原文（不填充颜色，保留背景图案）
            page.add_redact_annot(item.rect)

        if not layouts:
            return drawn, kept, failed

        try:
            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_NONE,
                graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                text=fitz.PDF_REDACT_TEXT_REMOVE,
            )
        except TypeError:
            page.apply_redactions()

        # 3) 写入译文
        for layout, rect in layouts:
            self._draw_lines(drawer, layout, rect, color=(0, 0, 0))
            drawn += 1
        return drawn, kept, failed

    # ── 图片型页面：取底色覆盖 + 写入 ─────────────────────

    def _apply_overlay_items(
        self, page: fitz.Page, plan: PagePlan, drawer: _PageDrawer
    ) -> Tuple[int, int, int]:
        drawn = kept = failed = 0
        pending: List[Tuple[object, fitz.Rect, tuple, tuple]] = []

        # 先把本页所有待绘制的原始区域算出来，用于判断「扩展框会不会压到邻居」
        others: List[fitz.Rect] = []
        resolved: List[Tuple[OverlayItem, Optional[fitz.Rect]]] = []
        for item in plan.overlay_items:
            rect = self._image_bbox_to_page_rect(item, plan)
            resolved.append((item, rect))
            if rect is not None and (item.translated or "").strip():
                others.append(rect)

        for item, rect in resolved:
            text = (item.translated or "").strip()
            if not text:
                kept += 1
                continue

            if rect is None or rect.is_empty:
                failed += 1
                continue

            # 底色必须取自「原文所在的这块区域」，否则深色表格栏会被填成白块
            base_fill = self._fill_color(page, rect)
            layout, used_rect, fill = self._layout_with_background(
                page, text, rect, page.rect, base_fill, others,
                height_factor=plan.box_height_factor,
                target_size=item.target_size,
            )
            if layout is None:
                # 放不下 → 保持原图不动，绝不画空白色块
                failed += 1
                continue

            text_color = self._text_color(fill)
            pending.append((layout, used_rect, fill, text_color))
            drawn += 1

        # 两阶段绘制：先把所有底色铺完，再统一写文字。
        # 否则相邻区域（大标题 + 副标题这类交叠的框）后画的底色
        # 会把先画好的译文文字盖掉一截。
        for _, used_rect, fill, _ in pending:
            page.draw_rect(used_rect, color=None, fill=fill, width=0, overlay=True)
        for layout, used_rect, _, text_color in pending:
            self._draw_lines(drawer, layout, used_rect, color=text_color)
        return drawn, kept, failed

    def _layout_with_background(
        self,
        page: fitz.Page,
        text: str,
        rect: fitz.Rect,
        page_rect: fitz.Rect,
        base_fill,
        others: Optional[List[fitz.Rect]] = None,
        height_factor: float = 0.85,
        target_size: float = 0.0,
    ):
        """
        在候选框中排版，但只接受「底色与原文区域一致」的扩展框。

        这样既能让小格子里的译文放大空间，又不会把深色栏位涂成白色。

        Returns: (layout, 使用的矩形, 使用的底色) 或 (None, None, None)
        """
        candidates = [(rect, base_fill, 0.0)]
        if self.expand:
            for cand in self._expanded_candidates(rect, page_rect):
                # 不能压到同一页其他 OCR 区域（否则会盖掉邻居的文字）
                if others and self._overlaps_any(cand, rect, others):
                    continue
                cand_fill = self._fill_color(page, cand)
                if not self._color_close(cand_fill, base_fill):
                    continue
                candidates.append((cand, cand_fill, 0.0))

        # 字号上限：
        #   1) 优先用「原文实际字形大小」标定出来的目标字号（视觉最接近原文）
        #   2) 没有标定值时退化为按框高估算
        if target_size and target_size > 0:
            upper = min(self.max_font, max(self.min_font, target_size))
        else:
            upper = min(self.max_font, max(self.min_font, rect.height * height_factor))
        # 内边距按比例取，小格子不能被固定的 padding 吃掉太多宽度
        pad = min(0.6, rect.width * 0.03, rect.height * 0.10)
        for cand, fill, _ in candidates:
            layout = self.fitter.fit(
                text,
                max(1.0, cand.width - pad * 2),
                max(1.0, cand.height - pad * 2),
                max_size=upper,
                min_size=self.min_font,
            )
            if layout is not None:
                return layout, cand, fill
        return None, None, None

    @staticmethod
    def _overlaps_any(cand: fitz.Rect, self_rect: fitz.Rect, others: List[fitz.Rect]) -> bool:
        """候选框是否与「其他区域」相交（自己的原框不算）"""
        probe = fitz.Rect(cand.x0 + 0.3, cand.y0 + 0.3, cand.x1 - 0.3, cand.y1 - 0.3)
        for other in others:
            if other == self_rect or other.intersects(self_rect):
                continue
            if probe.intersects(other):
                return True
        return False

    @staticmethod
    def _color_close(a, b, tolerance: float = 0.16) -> bool:
        """两个颜色是否足够接近（防止扩展框跨到别的色块）"""
        return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2])) <= tolerance

    def _image_bbox_to_page_rect(self, item: OverlayItem, plan: PagePlan) -> Optional[fitz.Rect]:
        """把 OCR 的图片像素坐标映射成页面坐标"""
        ix0, iy0, ix1, iy1 = item.image_rect
        img_w, img_h = item.image_size
        if img_w <= 0 or img_h <= 0 or (ix1 - ix0) <= 0 or (iy1 - iy0) <= 0:
            return None

        sx = (ix1 - ix0) / img_w
        sy = (iy1 - iy0) / img_h
        bx0, by0, bx1, by1 = item.image_bbox

        x0 = ix0 + bx0 * sx
        y0 = iy0 + by0 * sy
        x1 = ix0 + bx1 * sx
        y1 = iy0 + by1 * sy

        # 略微软化边界，避免切掉字形上下沿
        pad_y = min(1.5, (y1 - y0) * 0.12)
        y0 -= pad_y
        y1 += pad_y

        page_w = plan.page_width or 0
        page_h = plan.page_height or 0
        rect = fitz.Rect(
            max(0.5, x0), max(0.5, y0),
            min(page_w - 0.5, x1) if page_w else x1,
            min(page_h - 0.5, y1) if page_h else y1,
        )
        if rect.width <= 1 or rect.height <= 1:
            return None
        return rect

    # ── 排版 ─────────────────────────────────────────────

    def _layout_for(
        self,
        text: str,
        rect: fitz.Rect,
        original_font_size: float,
        page_rect: fitz.Rect,
        max_size: float = 16.0,
    ):
        """
        在 rect（必要时扩展到候选矩形）里排版 text。

        Returns: (TextLayout, 实际使用的矩形) 或 (None, None)
        """
        candidates = [rect]
        if self.expand:
            candidates.extend(self._expanded_candidates(rect, page_rect))

        upper = min(max_size, max(self.min_font, original_font_size * 1.15))
        for cand in candidates:
            pad = 0.6
            layout = self.fitter.fit(
                text,
                max(1.0, cand.width - pad * 2),
                max(1.0, cand.height - pad * 2),
                max_size=upper,
                min_size=self.min_font,
            )
            if layout is not None:
                return layout, cand
        return None, None

    def _expanded_candidates(self, rect: fitz.Rect, page_rect: fitz.Rect) -> List[fitz.Rect]:
        """生成若干个「向空白处扩展」的候选框（尺寸递增，尽量贴近原文位置）"""
        h = rect.height
        w = rect.width
        out = []
        # 只允许「轻微」扩展：密集版面里扩太多会盖到相邻行
        for grow_w, grow_h in ((0.10, 0.15), (0.20, 0.30)):
            nw = w * (1 + grow_w)
            nh = h * (1 + grow_h)
            x1 = min(page_rect.width - 1, rect.x0 + nw)
            y1 = min(page_rect.height - 1, rect.y0 + nh)
            cand = fitz.Rect(rect.x0, rect.y0, x1, y1)
            if cand.width > rect.width + 0.5 or cand.height > rect.height + 0.5:
                out.append(cand)
        return out

    # ── 绘制 ─────────────────────────────────────────────

    def _draw_lines(self, drawer: _PageDrawer, layout, rect: fitz.Rect, color):
        # 与排版阶段保持一致的内边距
        pad = min(0.6, rect.width * 0.03, rect.height * 0.10)
        baseline = rect.y0 + pad + layout.font_size * 0.86
        for line in layout.lines:
            if line.strip():
                drawer.write_line(
                    (rect.x0 + pad, baseline), line, layout.font_size, color
                )
            baseline += layout.line_height

    # ── 底色 / 文字颜色 ───────────────────────────────────

    def _page_pixmap_array(self, page: fitz.Page) -> Optional[np.ndarray]:
        key = page.number
        if key in self._pixmap_cache:
            return self._pixmap_cache[key]
        try:
            pix = page.get_pixmap(dpi=self.sample_dpi, alpha=False)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )[:, :, :3]
        except Exception:
            arr = None
        self._pixmap_cache[key] = arr
        return arr

    def _fill_color(self, page: fitz.Page, rect: fitz.Rect, pad: float = None):
        """取区域底色：默认用原图在该区域的主色，保证深色页面也是深色底"""
        if self.fill_mode == "white":
            return (1, 1, 1)

        arr = self._page_pixmap_array(page)
        if arr is None:
            return (1, 1, 1)

        scale = self.sample_dpi / 72.0
        # 取样范围要贴着原文区域：扩太大会把旁边的白底也统计进来，
        # 深色表格栏里的单元格就会被误判成白底。
        if pad is None:
            pad = min(2.0, max(0.5, rect.height * 0.3))
        x0 = max(0, int((rect.x0 - pad) * scale))
        y0 = max(0, int((rect.y0 - pad) * scale))
        x1 = min(arr.shape[1], int((rect.x1 + pad) * scale))
        y1 = min(arr.shape[0], int((rect.y1 + pad) * scale))
        if x1 - x0 < 1 or y1 - y0 < 1:
            # 区域像素太少，取该点最亮的邻域近似纸色
            px = min(max(0, int((rect.x0 + rect.x1) / 2 * scale)), arr.shape[1] - 1)
            py = min(max(0, int((rect.y0 + rect.y1) / 2 * scale)), arr.shape[0] - 1)
            patch = arr[max(0, py - 2):py + 3, max(0, px - 2):px + 3].reshape(-1, 3)
            if not len(patch):
                return (1, 1, 1)
            color = np.percentile(patch, 75, axis=0) / 255.0
            return tuple(float(c) for c in color)

        patch = arr[y0:y1, x0:x1].reshape(-1, 3)
        quant = (patch // 24).astype(np.int32)
        keys = quant[:, 0] * 10000 + quant[:, 1] * 100 + quant[:, 2]
        values, counts = np.unique(keys, return_counts=True)
        dominant = values[counts.argmax()]
        mean = patch[keys == dominant].mean(axis=0) / 255.0
        return tuple(float(min(1.0, max(0.0, c))) for c in mean)

    def _text_color(self, fill) -> Tuple[float, float, float]:
        if self.text_color_mode == "black":
            return (0, 0, 0)
        if self.text_color_mode == "white":
            return (1, 1, 1)
        luminance = 0.299 * fill[0] + 0.587 * fill[1] + 0.114 * fill[2]
        return (0, 0, 0) if luminance > 0.5 else (1, 1, 1)
