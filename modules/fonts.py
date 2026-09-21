"""
字体发现与校验模块。

用于找到一款真正能渲染「简体中文 + 日文假名」的字体，并在使用前校验字形覆盖率。

历史问题：旧代码只在常见路径里挑第一个存在的字体，没有校验字形，
遇到不含 CJK 的字体时会渲染出空白。
"""

import os
import sys
import glob
import platform
from functools import lru_cache
from typing import List, Tuple

import fitz  # PyMuPDF

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config


# 必须覆盖的字形：简体中文 + 平假名 + 片假名
_REQUIRED_GLYPHS = ["中", "文", "日", "本", "あ", "ア", "、", "。"]


def _candidate_fonts() -> List[str]:
    """按平台列出候选字体（越靠前越优先）"""
    system = platform.system().lower()
    serif_first = (os.getenv("FONT_STYLE", config.FONT_STYLE).lower() != "sans")

    # 日文印刷品（小说 / 规则书）正文基本都是明朝体，
    # 因此中文也用「宋体」系字体，观感最接近原版。
    macos_serif = [
        _asset_font("SimSong.ttc", "SimSong-Regular.ttc"),          # 宋体（明朝体风格）
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/Songti.ttc",
    ]
    macos_sans = [
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        _asset_font("PingFang.ttc"),
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
    ]
    macos = (macos_serif + macos_sans) if serif_first else (macos_sans + macos_serif)
    macos.append("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")

    windows = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyh.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\Deng.ttf",
        r"C:\Windows\Fonts\meiryo.ttc",
    ]
    linux = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/wenquanyi/wqy-zenhei/wqy-zenhei.ttc",
    ]

    table = {"darwin": macos, "windows": windows, "linux": linux}
    ordered = list(table.get(system, []))

    # 用户显式指定优先
    user_font = os.getenv("FONT_PATH", "") or config.FONT_PATH
    if user_font:
        ordered.insert(0, user_font)

    # 其余平台的候选也兜底尝试（例如 WSL / 容器）
    for key, fonts in table.items():
        if key != system:
            ordered.extend(fonts)
    return ordered


# macOS 的系统字体有些放在 AssetsV2 的哈希目录里，只能按文件名去找
_ASSET_GLOB = "/System/Library/AssetsV2/com_apple_MobileAsset_Font7/*.asset/AssetData"


@lru_cache(maxsize=32)
def _asset_font(*filenames: str) -> str:
    """在系统字体资源目录中按文件名查找（找不到返回空串）"""
    if platform.system().lower() != "darwin":
        return ""
    for name in filenames:
        hits = glob.glob(os.path.join(_ASSET_GLOB, name))
        if hits:
            return hits[0]
    return ""


def _font_covers_cjk(font: fitz.Font) -> bool:
    """校验字体是否覆盖中文字形"""
    try:
        return all(font.has_glyph(ord(ch)) for ch in _REQUIRED_GLYPHS)
    except Exception:
        return False


@lru_cache(maxsize=1)
def find_cjk_font() -> Tuple[str, fitz.Font]:
    """
    找到一款可用的中文字体。

    Returns:
        (font_path, fitz.Font 对象)

    Raises:
        FileNotFoundError: 找不到任何可用字体
    """
    tried = []
    for path in _candidate_fonts():
        if not path or not os.path.exists(path):
            continue
        try:
            font = fitz.Font(fontfile=path)
        except Exception as exc:  # 字体损坏 / 格式不支持
            tried.append(f"{path} ({exc})")
            continue
        if not _font_covers_cjk(font):
            tried.append(f"{path} (缺少中日文字形)")
            continue
        if not _font_can_render(font):
            tried.append(f"{path} (渲染测试失败)")
            continue
        return path, font

    detail = "\n".join(f"  - {t}" for t in tried) or "  (没有任何候选字体文件存在)"
    raise FileNotFoundError(
        "未找到可渲染中文的字体。\n"
        f"已尝试:\n{detail}\n\n"
        "请安装中文字体，或在 .env 中指定:\n"
        "  FONT_PATH=/path/to/your/chinese-font.ttf\n"
        "macOS: brew install --cask font-noto-sans-cjk-sc\n"
        "Linux: sudo apt install fonts-noto-cjk"
    )


def get_font_path() -> str:
    """只取字体路径"""
    return find_cjk_font()[0]


def get_font() -> fitz.Font:
    """只取 fitz.Font 对象（用于测宽、排版）"""
    return find_cjk_font()[1]


def describe_font() -> str:
    """一行描述当前使用的字体，便于日志排查"""
    try:
        path, font = find_cjk_font()
        return f"{os.path.basename(path)} ({font.name})"
    except FileNotFoundError as exc:
        return f"未找到中文字体: {str(exc).splitlines()[0]}"


def _font_can_render(font: fitz.Font) -> bool:
    """
    真正画一遍试试。

    只检查字形覆盖是不够的：有些 .ttc（例如 macOS 的 Songti）在
    MuPDF 里会抛 "substitute font creation is not implemented"，
    必须在选用前排掉，否则生成阶段直接崩。
    """
    try:
        doc = fitz.open()
        page = doc.new_page(width=200, height=80)
        writer = fitz.TextWriter(page.rect)
        writer.append((10, 40), "中文日あ", font=font, fontsize=12)
        writer.write_text(page)
        pix = page.get_pixmap(dpi=72)
        ok = pix.width > 0 and pix.height > 0
        doc.close()
        return ok
    except Exception:
        return False


@lru_cache(maxsize=4)
def glyph_ink_ratio(font_path: str) -> float:
    """
    测量「字形墨迹高度 / 字号」的比值（CJK 字体通常在 0.85~0.95）。

    用途：把 OCR 量出来的原文字形高度换算成应该用的字号。
    """
    try:
        font = fitz.Font(fontfile=font_path)
        size = 200.0
        doc = fitz.open()
        page = doc.new_page(width=600, height=400)
        writer = fitz.TextWriter(page.rect)
        writer.append((40, 300), "国国国", font=font, fontsize=size)
        writer.write_text(page)
        pix = page.get_pixmap(dpi=72, alpha=False)
        arr = _pix_to_array(pix)
        rows = (arr < 128).any(axis=1)
        idx = rows.nonzero()[0]
        ratio = (idx[-1] - idx[0] + 1) / size if len(idx) else 0.88
        doc.close()
        return float(min(1.0, max(0.5, ratio)))
    except Exception:
        return 0.88


def _pix_to_array(pix):
    import numpy as np

    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n
    )[:, :, :3].mean(axis=2)
