"""
PDF 内容提取模块
负责从 PDF 中提取文字块和图片，保留位置信息以便重建
"""

import os
import fitz  # PyMuPDF
from PIL import Image
import io
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field


@dataclass
class TextBlock:
    """文字块数据结构"""
    text: str
    bbox: Tuple[float, float, float, float]  # (x0, y0, x1, y1)
    page_num: int
    font_size: float = 10.0
    font_name: str = ""
    color: int = 0  # 文字颜色


@dataclass
class ImageBlock:
    """图片块数据结构"""
    image: Image.Image
    bbox: Tuple[float, float, float, float]
    page_num: int
    ext: str = "png"
    image_path: str = ""  # 保存到磁盘的路径


@dataclass
class PageContent:
    """单页内容"""
    page_num: int
    width: float
    height: float
    text_blocks: List[TextBlock] = field(default_factory=list)
    image_blocks: List[ImageBlock] = field(default_factory=list)


class PDFExtractor:
    """PDF 提取器 - 提取文字和图片"""

    def __init__(self, pdf_path: str, temp_dir: str = "./temp"):
        self.pdf_path = pdf_path
        self.temp_dir = temp_dir
        os.makedirs(temp_dir, exist_ok=True)

        self.doc = fitz.open(pdf_path)
        self.total_pages = len(self.doc)

    def extract_all(self) -> List[PageContent]:
        """提取所有页面的内容"""
        pages_content = []
        for page_num in range(self.total_pages):
            page_content = self.extract_page(page_num)
            pages_content.append(page_content)
        return pages_content

    def extract_page(self, page_num: int) -> PageContent:
        """提取单页内容（文字 + 图片）"""
        page = self.doc[page_num]
        page_rect = page.rect

        content = PageContent(
            page_num=page_num,
            width=page_rect.width,
            height=page_rect.height
        )

        # 1. 提取文字块（保留位置信息）
        text_blocks = self._extract_text_blocks(page, page_num)
        content.text_blocks = text_blocks

        # 2. 提取图片
        image_blocks = self._extract_images(page, page_num)
        content.image_blocks = image_blocks

        return content

    def _extract_text_blocks(self, page: fitz.Page, page_num: int) -> List[TextBlock]:
        """提取文字块，保留精确位置"""
        blocks = []

        # 使用 dict 模式获取详细文字信息
        text_dict = page.get_text("dict")

        for block in text_dict.get("blocks", []):
            if block["type"] == 0:  # 文字块
                for line in block.get("lines", []):
                    line_text = ""
                    font_size = 0
                    font_name = ""
                    color = 0

                    for span in line.get("spans", []):
                        line_text += span["text"]
                        if font_size == 0:
                            font_size = span["size"]
                            font_name = span["font"]
                            color = span["color"]

                    line_text = line_text.strip()
                    if line_text:
                        blocks.append(TextBlock(
                            text=line_text,
                            bbox=block["bbox"],
                            page_num=page_num,
                            font_size=font_size,
                            font_name=font_name,
                            color=color
                        ))

        return blocks

    def _extract_images(self, page: fitz.Page, page_num: int) -> List[ImageBlock]:
        """提取页面中的图片"""
        image_blocks = []
        image_list = page.get_images(full=True)

        for img_idx, img_info in enumerate(image_list):
            xref = img_info[0]
            base_image = self.doc.extract_image(xref)
            image_bytes = base_image["image"]
            ext = base_image["ext"]

            # 转换为 PIL Image
            pil_image = Image.open(io.BytesIO(image_bytes))

            # 获取图片在页面中的位置
            img_rects = page.get_image_rects(xref)
            bbox = img_rects[0] if img_rects else (0, 0, pil_image.width, pil_image.height)

            # 保存到临时目录
            img_filename = f"page{page_num + 1}_img{img_idx + 1}.{ext}"
            img_path = os.path.join(self.temp_dir, img_filename)
            pil_image.save(img_path)

            image_blocks.append(ImageBlock(
                image=pil_image,
                bbox=bbox,
                page_num=page_num,
                ext=ext,
                image_path=img_path
            ))

        return image_blocks

    def get_page_count(self) -> int:
        return self.total_pages

    def close(self):
        self.doc.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
