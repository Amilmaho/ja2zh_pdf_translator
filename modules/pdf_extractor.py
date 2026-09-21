"""
PDF 内容提取模块（重构版）
提取文字块（按行）与图片，并保留位置信息以便重建。

相比旧版的改进：
  1. 文字块粒度改为「行」，并且使用行自身的 bbox。
     旧版按 block 取 bbox 却按行生成多条记录，导致同一块内多行文字
     全部叠在同一个矩形里，输出必然重叠/丢失。
  2. 新增整页渲染（page image）能力：页面由多个小图拼成时，
     拿整页渲染图做 OCR 比拿单个内嵌图可靠得多。
  3. 支持指定页码范围，避免为了 5 页去解析 500 页。
"""

import io
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import fitz  # PyMuPDF
from PIL import Image

from modules.utils import parse_page_range


# ── 数据结构 ──────────────────────────────────────────────

@dataclass
class TextBlock:
    """一行文字"""
    text: str
    bbox: Tuple[float, float, float, float]  # (x0, y0, x1, y1)
    page_num: int
    font_size: float = 10.0
    font_name: str = ""
    color: int = 0
    # 文字层没有置信度概念，默认 1.0；OCR 结果会带真实置信度
    confidence_hint: float = 1.0

    @property
    def width(self) -> float:
        return max(0.0, self.bbox[2] - self.bbox[0])

    @property
    def height(self) -> float:
        return max(0.0, self.bbox[3] - self.bbox[1])


@dataclass
class ImageBlock:
    """页面中的一张图片"""
    image: Optional[Image.Image]
    bbox: Tuple[float, float, float, float]
    page_num: int
    ext: str = "png"
    image_path: str = ""
    xref: int = 0

    @property
    def area(self) -> float:
        return max(0.0, self.bbox[2] - self.bbox[0]) * max(0.0, self.bbox[3] - self.bbox[1])


@dataclass
class PageContent:
    """单页内容"""
    page_num: int
    width: float
    height: float
    text_blocks: List[TextBlock] = field(default_factory=list)
    image_blocks: List[ImageBlock] = field(default_factory=list)
    page_image_path: str = ""
    render_dpi: int = 0
    # 页面上是否有「肉眼可见」的文字（扫描件的 OCR 文字层是不可见的）
    text_visible: bool = True
    # 单张图片对页面的覆盖率（>= 0.85 基本可以认定是整页扫描图）
    image_coverage: float = 0.0

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def has_text(self) -> bool:
        return any(b.text.strip() for b in self.text_blocks)

    @property
    def text_char_count(self) -> int:
        return sum(len(b.text.strip()) for b in self.text_blocks)

    @property
    def is_scan(self) -> bool:
        """
        是否是「扫描件」页面：
          - 整页就是一张图，或
          - 页面文字是隐藏的 OCR 文字层
        这类页面必须走「覆盖 + 叠加」而不是 redaction，
        否则原图里印刷的日文会留在译文下面。
        """
        return self.image_coverage >= 0.85 or not self.text_visible

    def largest_image(self) -> Optional[ImageBlock]:
        if not self.image_blocks:
            return None
        return max(self.image_blocks, key=lambda b: b.area)


# ── 提取器 ────────────────────────────────────────────────

class PDFExtractor:
    """PDF 提取器"""

    def __init__(self, pdf_path: str, temp_dir: str = "./temp", render_dpi: int = None):
        from config import config

        self.pdf_path = pdf_path
        self.temp_dir = temp_dir
        self.render_dpi = render_dpi or config.PDF_RENDER_DPI
        os.makedirs(temp_dir, exist_ok=True)

        self.doc = fitz.open(pdf_path)
        self.total_pages = len(self.doc)
        self._page_image_cache: Dict[int, str] = {}

    # -- 提取 --

    def extract_all(
        self,
        pages: Optional[Sequence[int]] = None,
        page_range: Optional[str] = None,
        with_images: bool = True,
    ) -> List[PageContent]:
        """
        Args:
            pages: 0 基页下标列表（优先）
            page_range: 形如 "1-5,10" 的字符串（1 基）
            with_images: 是否提取内嵌图片
        """
        if pages is None:
            pages = parse_page_range(page_range, self.total_pages)
        return [self.extract_page(p, with_images=with_images) for p in pages]

    def extract_page(self, page_num: int, with_images: bool = True) -> PageContent:
        page = self.doc[page_num]
        rect = page.rect
        content = PageContent(page_num=page_num, width=rect.width, height=rect.height)
        content.text_blocks = self._extract_text_blocks(page, page_num)
        content.text_visible = self._page_text_is_visible(page)
        content.image_coverage = self.page_image_coverage(page_num)
        if with_images:
            content.image_blocks = self._extract_images(page, page_num)
        return content

    def _page_text_is_visible(self, page: fitz.Page) -> bool:
        """
        判断页面的文字是否可见。

        扫描件常带一层「不可见 OCR 文字」（render mode 3），
        get_texttrace() 里表现为 type == 3。
        """
        try:
            trace = page.get_texttrace()
        except Exception:
            return True
        total = invisible = 0
        for span in trace:
            count = len(span.get("chars", ()))
            total += count
            if span.get("type", 0) == 3:
                invisible += count
        if total == 0:
            return True
        return (invisible / total) < 0.5

    def page_image_coverage(self, page_num: int) -> float:
        """页面上最大一张图片占页面面积的比例（0~1）"""
        try:
            page = self.doc[page_num]
            page_area = abs(page.rect.width * page.rect.height)
            if page_area <= 0:
                return 0.0
            best = 0.0
            for info in page.get_images(full=True):
                for rect in page.get_image_rects(info[0]):
                    best = max(best, abs(rect.width * rect.height) / page_area)
            return min(1.0, best)
        except Exception:
            return 0.0

    def _extract_text_blocks(self, page: fitz.Page, page_num: int) -> List[TextBlock]:
        """提取文字，**按行**保留精确位置"""
        blocks: List[TextBlock] = []
        try:
            raw = page.get_text("dict")
        except Exception:
            return blocks

        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                text = "".join(s.get("text", "") for s in spans).strip()
                if not text:
                    continue

                # 行 bbox：优先用行自身，缺失时用 span 合并
                bbox = line.get("bbox")
                if not bbox:
                    xs0 = [s["bbox"][0] for s in spans if s.get("bbox")]
                    ys0 = [s["bbox"][1] for s in spans if s.get("bbox")]
                    xs1 = [s["bbox"][2] for s in spans if s.get("bbox")]
                    ys1 = [s["bbox"][3] for s in spans if s.get("bbox")]
                    if not xs0:
                        continue
                    bbox = (min(xs0), min(ys0), max(xs1), max(ys1))

                sizes = [s.get("size", 0) for s in spans if s.get("size")]
                blocks.append(TextBlock(
                    text=text,
                    bbox=tuple(float(v) for v in bbox),
                    page_num=page_num,
                    font_size=float(max(sizes)) if sizes else 10.0,
                    font_name=spans[0].get("font", "") if spans else "",
                    color=int(spans[0].get("color", 0)) if spans else 0,
                ))
        return blocks

    def _extract_images(self, page: fitz.Page, page_num: int) -> List[ImageBlock]:
        """提取页面内嵌图片（按出现位置去重）"""
        out: List[ImageBlock] = []
        try:
            image_list = page.get_images(full=True)
        except Exception:
            return out

        for img_idx, img_info in enumerate(image_list):
            xref = img_info[0]
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                rects = []
            if not rects:
                continue

            try:
                base = self.doc.extract_image(xref)
                image_bytes = base["image"]
                ext = base.get("ext", "png")
                pil_image = Image.open(io.BytesIO(image_bytes))
                pil_image.load()
            except Exception:
                continue

            bbox = tuple(float(v) for v in rects[0])
            img_path = os.path.join(self.temp_dir, f"p{page_num + 1}_img{img_idx + 1}.{ext}")
            try:
                pil_image.save(img_path)
            except Exception:
                img_path = ""

            out.append(ImageBlock(
                image=pil_image, bbox=bbox, page_num=page_num,
                ext=ext, image_path=img_path, xref=xref,
            ))
        return out

    # -- 整页渲染 --

    def render_page(self, page_num: int, dpi: int = None) -> str:
        """把整页渲染成 PNG 并返回路径（带缓存）"""
        dpi = dpi or self.render_dpi
        cached = self._page_image_cache.get(page_num)
        if cached and os.path.exists(cached):
            return cached

        path = os.path.join(self.temp_dir, f"page{page_num + 1}_{dpi}dpi.png")
        page = self.doc[page_num]
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        pix.save(path)
        self._page_image_cache[page_num] = path
        return path

    def render_pixmap(self, page_num: int, dpi: int = None):
        """返回 fitz.Pixmap（用于取底色等像素级操作）"""
        dpi = dpi or self.render_dpi
        return self.doc[page_num].get_pixmap(dpi=dpi, alpha=False)

    # -- OCR 图源选择 --

    def best_ocr_image(self, content: PageContent) -> Optional[str]:
        """
        选择最适合做 OCR 的图源。

        - 如果页面就是一张整页扫描图（覆盖 >= 90% 面积），直接用原图（保留原生分辨率）
        - 否则渲染整页（避免遗漏矢量文字和拼贴的小图）
        """
        largest = content.largest_image()
        if largest and largest.image_path and content.area > 0:
            coverage = largest.area / content.area
            if coverage >= 0.9:
                return largest.image_path
        try:
            return self.render_page(content.page_num)
        except Exception:
            return largest.image_path if largest else None

    # -- 杂项 --

    def get_page_count(self) -> int:
        return self.total_pages

    def close(self):
        try:
            self.doc.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
