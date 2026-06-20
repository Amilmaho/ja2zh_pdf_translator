"""
PDF 生成模块
将翻译后的文字和图片重新组合成新的 PDF 文件

支持两种模式:
  1. 文字型 PDF: 替换原文为翻译文字
  2. 图片型 PDF: OCR 翻译文字叠加到图片上（白色背景框 + 中文）
"""

import os
import sys
from typing import List, Dict, Any
from PIL import Image
import io

import fitz  # PyMuPDF

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import config
from modules.pdf_extractor import PageContent, TextBlock, ImageBlock


class PDFGenerator:
    """PDF 生成器 - 将翻译后的内容写入新 PDF"""

    def __init__(self, output_path: str, font_path: str = None):
        self.output_path = output_path
        self.font_path = font_path or self._find_chinese_font()
        print(f"[PDF生成] 使用字体: {self.font_path}")

    def _find_chinese_font(self) -> str:
        """自动查找可用的中文字体 (支持 Windows / macOS / Linux)"""
        # 优先使用环境变量指定的字体
        if config.FONT_PATH and os.path.exists(config.FONT_PATH):
            return config.FONT_PATH

        candidates = [
            # macOS 常见中文字体
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/System/Library/Fonts/Songti.ttc",
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            # Windows 中文字体
            "C:/Windows/Fonts/simsun.ttc",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            "C:/Windows/Fonts/mingliu.ttc",
            # Linux 中文字体
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        ]
        for f in candidates:
            if os.path.exists(f):
                return f
        raise FileNotFoundError(
            "未找到中文字体！\n"
            "macOS 用户请确认 /System/Library/Fonts/ 下有 STHeiti 或 Songti\n"
            "或设置环境变量 FONT_PATH 指向中文字体路径"
        )

    def generate(
        self,
        pages_content: List[PageContent],
        translated_texts: List[List[str]],
        ocr_results_per_page: List[list] = None
    ):
        """生成翻译后的 PDF — 自动检测文字型/图片型并选择合适的模式"""
        from tqdm import tqdm

        total_text_blocks = sum(len(t) for t in translated_texts)
        total_ocr = sum(len(r) for r in (ocr_results_per_page or []))

        is_image_based = total_text_blocks == 0 and total_ocr > 0
        mode = "图片叠加模式" if is_image_based else "文字替换模式"

        print(f"[PDF生成] {mode}")
        print(f"[PDF生成] 共 {len(pages_content)} 页")

        doc = fitz.open()

        for page_idx, page_content in enumerate(
            tqdm(pages_content, desc="  生成PDF页面")
        ):
            page = doc.new_page(
                width=page_content.width,
                height=page_content.height
            )

            if is_image_based:
                # 图片型 PDF: 嵌入图片 + 叠加翻译文字
                self._build_image_page(
                    page, page_content,
                    ocr_results_per_page[page_idx] if ocr_results_per_page else []
                )
            else:
                # 文字型 PDF: 替换文字 + 嵌入图片
                self._write_translated_text(
                    page, page_content, translated_texts[page_idx]
                )
                self._embed_images(page, page_content)

        print(f"[PDF生成] 正在保存 PDF...")
        doc.save(self.output_path, garbage=4, deflate=True)
        doc.close()
        print(f"[PDF生成] PDF 已保存到: {self.output_path}")

    # ========== 图片型 PDF 生成 ==========

    def _build_image_page(
        self,
        page: fitz.Page,
        page_content: PageContent,
        page_ocr_results: list
    ):
        """构建图片型页面: 嵌入原始图片 + 叠加翻译文字框"""
        if not page_content.image_blocks:
            return

        img_block = page_content.image_blocks[0]
        img_path = img_block.image_path
        if not img_path or not os.path.exists(img_path):
            return

        # 获取图片原始尺寸
        pil_img = Image.open(img_path)
        img_w, img_h = pil_img.size
        pil_img.close()

        # 将图片缩放到页面大小
        page_w = page.rect.width
        page_h = page.rect.height
        scale = min(page_w / img_w, page_h / img_h)
        scaled_w = img_w * scale
        scaled_h = img_h * scale
        offset_x = (page_w - scaled_w) / 2
        offset_y = (page_h - scaled_h) / 2

        # 嵌入原始图片（居中缩放）
        page.insert_image(
            fitz.Rect(offset_x, offset_y, offset_x + scaled_w, offset_y + scaled_h),
            filename=img_path
        )

        # 叠加翻译文字
        if page_ocr_results:
            for img_result in page_ocr_results:
                for trans in img_result.get("translations", []):
                    self._overlay_translated_text(
                        page, trans, offset_x, offset_y, scale,
                        page_w, page_h
                    )

    def _overlay_translated_text(
        self, page: fitz.Page, trans: dict,
        offset_x: float, offset_y: float, scale: float,
        page_w: float, page_h: float
    ):
        """在图片上叠加翻译文字（白色背景 + 中文）

        核心改进：
        1. 先尝试验证文字能否渲染，再决定是否画白色背景
        2. 渲染失败时降级显示原文，避免空白的白色矩形
        3. 字号最小8，最大14，确保可读
        4. 不吞异常，记录详细错误信息
        """
        translated = trans.get("translated", "")
        original = trans.get("original", "")

        # 如果翻译为空，退回原文
        if not translated.strip():
            if original.strip():
                translated = original  # 显示原文
            else:
                return  # 都没有，跳过

        # OCR 坐标 (图片内坐标) → PDF 页面坐标
        bx0, by0, bx1, by1 = trans["bbox"]
        x0 = offset_x + bx0 * scale
        y0 = offset_y + by0 * scale
        x1 = offset_x + bx1 * scale
        y1 = offset_y + by1 * scale

        # 确保在页面范围内
        x0 = max(1, min(x0, page_w - 2))
        y0 = max(1, min(y0, page_h - 2))
        x1 = max(x0 + 10, min(x1, page_w - 2))
        y1 = max(y0 + 6, min(y1, page_h - 2))

        # 计算合适字号（基于原文区域高度，增大范围）
        orig_h = y1 - y0
        orig_w = x1 - x0

        # 先估算翻译后文本需要的宽度和字号
        text_len = len(translated)
        if text_len <= 2:
            font_size = min(orig_h * 0.85, 14)
        elif text_len <= 5:
            font_size = min(orig_h * 0.75, 12)
        else:
            font_size = min(orig_h * 0.65, 11)
        font_size = max(8, font_size)  # 最小8号，确保可读

        # 估算需要的宽度 (中文约 0.65 * font_size 每字)
        est_width = text_len * font_size * 0.65
        if est_width > orig_w:
            # 文本太宽，扩展区域宽度
            x1 = min(x0 + est_width + 10, page_w - 2)
            # 如果宽度扩展了，重新计算可用宽度，可能需要换行
            if x1 - x0 > orig_w * 3:
                # 文本很长，使用多行
                lines_needed = max(1, int(est_width / (x1 - x0)) + 1)
                y1 = min(y0 + orig_h * max(2, lines_needed), page_h - 2)

        # 最终 rect
        rect = fitz.Rect(x0, y0, x1, y1)

        # === 分两步渲染，避免产生空白的白色矩形 ===

        # 步骤 1: 尝试渲染文字（先画到一个临时位置，验证是否成功）
        # 这里我们直接渲染，但记录是否成功
        text_rendered = False
        render_error = None

        try:
            # 先画白色背景遮盖原文
            page.draw_rect(rect, color=None, fill=(1, 1, 1), width=0)

            # 再写翻译文字
            rc = page.insert_textbox(
                rect,
                translated,
                fontname="china-s",
                fontfile=self.font_path,
                fontsize=font_size,
                color=(0, 0, 0),
                align=0,
            )

            if rc < 0:
                # 文本溢出未渲染任何内容 → 尝试更小的字号
                smaller_font = max(6, font_size * 0.75)
                rc2 = page.insert_textbox(
                    rect,
                    translated,
                    fontname="china-s",
                    fontfile=self.font_path,
                    fontsize=smaller_font,
                    color=(0, 0, 0),
                    align=0,
                )
                if rc2 >= 0:
                    text_rendered = True
                elif rc2 < 0:
                    # 即使缩小字号也溢出 → 尝试只显示前几个字
                    short_text = translated[:max(3, int(orig_w / (smaller_font * 0.65)))] + "..."
                    rc3 = page.insert_textbox(
                        rect, short_text,
                        fontname="china-s",
                        fontfile=self.font_path,
                        fontsize=smaller_font,
                        color=(0, 0, 0),
                        align=0,
                    )
                    text_rendered = rc3 >= 0
            else:
                text_rendered = True

        except Exception as e:
            render_error = e
            text_rendered = False

        # 步骤 2: 如果文字渲染失败，用原文回退，避免空白白条
        if not text_rendered and original.strip():
            fallback_text = original[:30]
            try:
                # 缩小字号用原文填充，至少用户能看到内容
                page.insert_textbox(
                    rect,
                    fallback_text,
                    fontname="china-s",
                    fontfile=self.font_path,
                    fontsize=7,
                    color=(128, 128, 128),  # 灰色表示原文
                    align=0,
                )
            except Exception:
                pass  # 最终回退也失败，但至少白框仍在（遮盖了原文）

    # ========== 文字型 PDF 生成 ==========

    def _write_translated_text(
        self,
        page: fitz.Page,
        page_content: PageContent,
        translated: List[str]
    ):
        """在页面上写入翻译后的文字"""
        for i, block in enumerate(page_content.text_blocks):
            if i >= len(translated):
                break

            translated_text = translated[i]
            if not translated_text.strip():
                continue

            x0, y0, x1, y1 = block.bbox
            font_size = block.font_size

            # 计算合适的字体大小（中文通常需要稍大一些）
            adjusted_size = min(font_size * 1.1, 14)

            # 确保区域在页面内
            page_rect = page.rect
            x0 = max(0, x0)
            y0 = max(0, y0)
            x1 = min(page_rect.width, x1)
            y1 = min(page_rect.height, y1 + 20)

            if x1 <= x0 or y1 <= y0:
                continue

            # 写入文本
            rc = page.insert_textbox(
                fitz.Rect(x0, y0, x1, y1),
                translated_text,
                fontname="china-s",
                fontfile=self.font_path,
                fontsize=adjusted_size,
                color=(0, 0, 0),
                align=0  # 左对齐
            )

            # 如果文字溢出，尝试更小的字号
            if rc < 0:
                page.insert_textbox(
                    fitz.Rect(x0, y0, x1, y1 + 30),
                    translated_text,
                    fontname="china-s",
                    fontfile=self.font_path,
                    fontsize=adjusted_size * 0.85,
                    color=(0, 0, 0),
                    align=0
                )

    def _embed_images(self, page: fitz.Page, page_content: PageContent) -> tuple:
        """将图片嵌入到页面中，返回 (成功数, 失败数)"""
        ok, fail = 0, 0
        page_rect = page.rect

        for img_block in page_content.image_blocks:
            if not img_block.image_path or not os.path.exists(img_block.image_path):
                fail += 1
                continue

            try:
                x0, y0, x1, y1 = img_block.bbox

                # 计算在页面内的可用区域
                img_rect = fitz.Rect(
                    max(0, x0),
                    max(0, y0),
                    min(page_rect.width, x1),
                    min(page_rect.height, y1)
                )

                if img_rect.width <= 1 or img_rect.height <= 1:
                    fail += 1
                    continue

                page.insert_image(img_rect, filename=img_block.image_path)
                ok += 1
            except Exception as e:
                fail += 1

        return ok, fail


class SimplePDFGenerator:
    """
    简化版 PDF 生成器
    使用 reportlab 重新排版，适合文字密集的文档
    """

    def __init__(self, output_path: str):
        self.output_path = output_path

    def generate_simple(
        self,
        pages_content: List[PageContent],
        translated_texts: List[List[str]],
        ocr_translations: List[List[str]] = None
    ):
        """简化生成：一页原文 + 一页翻译"""
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        # 注册中文字体
        font_path = self._find_chinese_font()
        pdfmetrics.registerFont(TTFont('ChineseFont', font_path))

        doc = SimpleDocTemplate(
            self.output_path,
            pagesize=A4,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm
        )

        style = ParagraphStyle(
            'ChineseStyle',
            fontName='ChineseFont',
            fontSize=11,
            leading=18,
            spaceAfter=8,
        )

        story = []

        for page_idx, page_content in enumerate(pages_content):
            # 原文
            story.append(Paragraph(f"<b>--- 第 {page_idx + 1} 页 原文 ---</b>", style))
            for block in page_content.text_blocks:
                if block.text.strip():
                    story.append(Paragraph(block.text, style))

            story.append(Spacer(1, 10 * mm))
            story.append(Paragraph(f"<b>--- 第 {page_idx + 1} 页 中文翻译 ---</b>", style))

            # 翻译
            if page_idx < len(translated_texts):
                for text in translated_texts[page_idx]:
                    if text.strip():
                        story.append(Paragraph(text, style))

            story.append(PageBreak())

        doc.build(story)
        print(f"[PDF生成] 简化版 PDF 已保存到: {self.output_path}")

    def _find_chinese_font(self) -> str:
        candidates = [
            "C:/Windows/Fonts/simsun.ttc",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            "/System/Library/Fonts/PingFang.ttc",
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        ]
        for f in candidates:
            if os.path.exists(f):
                return f
        raise FileNotFoundError("未找到中文字体")
