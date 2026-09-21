"""
图片文字覆盖模块（用于 DOCX 内嵌图片的翻译）

与 PDF 生成器同样的原则：先排版确认放得下，再决定是否覆盖原文字；
放不下就保留原图文字，绝不留下空白色块。
"""

import os
import sys
from collections import Counter
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config
from modules.fonts import get_font_path
from modules.text_layout import tokenize


@lru_cache(maxsize=64)
def _load_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(get_font_path(), size)


def _measure(text: str, font: ImageFont.FreeTypeFont) -> float:
    try:
        return float(font.getlength(text))
    except Exception:
        return float(font.getsize(text)[0])


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: float) -> List[str]:
    if max_width <= 0:
        return [text]
    lines: List[str] = []
    for para in text.split("\n"):
        if not para.strip():
            lines.append("")
            continue
        current = ""
        for token in tokenize(para):
            if _measure(current + token, font) <= max_width or not current:
                current += token
            else:
                lines.append(current.rstrip())
                current = "" if token == " " else token
        if current.strip():
            lines.append(current.rstrip())
    return lines or [text]


def _fit(text: str, box_w: float, box_h: float,
         max_size: float, min_size: float) -> Optional[Dict]:
    """二分搜索最大可用字号"""
    if box_w <= 1 or box_h <= 1 or not text.strip():
        return None
    lo, hi = min_size, max(min_size, max_size)
    best = None
    for _ in range(12):
        mid = (lo + hi) / 2
        font = _load_font(max(1, int(round(mid))))
        lines = _wrap(text, font, box_w)
        height = len(lines) * mid * 1.18
        width = max((_measure(ln, font) for ln in lines), default=0.0)
        if height <= box_h and width <= box_w:
            best = {"lines": lines, "size": mid, "font": font,
                    "height": height, "width": width}
            lo = mid
        else:
            hi = mid
    return best


def _background_color(img: np.ndarray, rect: Tuple[float, float, float, float]):
    """取区域主色（向外扩一圈，避开文字本身）"""
    x0, y0, x1, y1 = rect
    pad = max(3, int((y1 - y0) * 0.6))
    ix0 = max(0, int(x0) - pad)
    iy0 = max(0, int(y0) - pad)
    ix1 = min(img.shape[1], int(x1) + pad)
    iy1 = min(img.shape[0], int(y1) + pad)
    if ix1 - ix0 < 2 or iy1 - iy0 < 2:
        return (255, 255, 255)
    patch = img[iy0:iy1, ix0:ix1].reshape(-1, 3)
    quant = (patch // 24).astype(np.int32)
    keys = quant[:, 0] * 10000 + quant[:, 1] * 100 + quant[:, 2]
    counter = Counter(keys.tolist())
    dominant = counter.most_common(1)[0][0]
    mean = patch[keys == dominant].mean(axis=0)
    return tuple(int(max(0, min(255, v))) for v in mean)


def render_regions(
    image_path: str,
    regions: Sequence[Dict],
    output_path: str = None,
    min_font: float = None,
    max_font: float = None,
    verbose: bool = False,
) -> Dict:
    """
    把译文画到图片上。

    Args:
        regions: [{"bbox": (x0,y0,x1,y1), "translated": str, "original": str}, ...]

    Returns:
        {"drawn": n, "kept": n, "failed": n, "output": path}
    """
    min_font = config.OVERLAY_MIN_FONT if min_font is None else min_font
    max_font = config.OVERLAY_MAX_FONT if max_font is None else max_font

    img = Image.open(image_path).convert("RGB")
    arr = np.array(img)
    draw = ImageDraw.Draw(img)
    drawn = kept = failed = 0

    for region in regions:
        text = (region.get("translated") or "").strip()
        if not text:
            kept += 1
            continue
        x0, y0, x1, y1 = [float(v) for v in region["bbox"]]
        pad = 1.0
        layout = _fit(text, (x1 - x0) - 2 * pad, (y1 - y0) - 2 * pad, max_font, min_font)
        if layout is None:
            failed += 1
            continue

        fill = _background_color(arr, (x0, y0, x1, y1))
        luminance = 0.299 * fill[0] + 0.587 * fill[1] + 0.114 * fill[2]
        text_color = (0, 0, 0) if luminance > 128 else (255, 255, 255)

        draw.rectangle([x0, y0, x1, y1], fill=fill)
        baseline = y0 + pad
        for line in layout["lines"]:
            if line.strip():
                draw.text((x0 + pad, baseline), line, font=layout["font"], fill=text_color)
            baseline += layout["size"] * 1.18
        drawn += 1

    output_path = output_path or image_path
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    _save_image(img, output_path)
    if verbose:
        print(f"[图片覆盖] {os.path.basename(image_path)}: "
              f"写入 {drawn} 处，保留 {kept} 处，放不下 {failed} 处", flush=True)
    return {"drawn": drawn, "kept": kept, "failed": failed, "output": output_path}


def _save_image(img: Image.Image, path: str):
    """按扩展名保存，JPEG 用高质量参数避免二次压缩糊掉"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        img.save(path, format="JPEG", quality=95, subsampling=0, optimize=True)
    elif ext == ".webp":
        img.save(path, format="WEBP", quality=95)
    else:
        img.save(path)
