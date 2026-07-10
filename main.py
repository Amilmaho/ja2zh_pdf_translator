"""
日文 PDF 翻译工具 - 主程序入口
支持多页 PDF 的文字提取、OCR 识别和翻译
"""

import os
import sys
import argparse
from pathlib import Path
from tqdm import tqdm

# 将项目根目录加入 path
sys.path.insert(0, os.path.dirname(__file__))

from config import config
from modules.pdf_extractor import PDFExtractor, PageContent
from modules.ocr_engine import create_ocr_engine, OCREngine
from modules.translator import create_translation_engine, TranslationEngine
from modules.pdf_generator import PDFGenerator


class JapanesePDFTranslator:
    """日文 PDF 翻译器主类"""

    def __init__(
        self,
        pdf_path: str,
        output_path: str = None,
        translation_engine: str = None,
        ocr_engine: str = None
    ):
        self.pdf_path = pdf_path
        self.pdf_name = Path(pdf_path).stem

        # 设置输出路径
        if output_path is None:
            self.output_path = os.path.join(
                config.OUTPUT_DIR,
                f"{self.pdf_name}_translated.pdf"
            )
        else:
            self.output_path = output_path

        # 临时目录
        self.temp_dir = os.path.join(config.TEMP_DIR, self.pdf_name)
        os.makedirs(self.temp_dir, exist_ok=True)

        # 引擎配置
        if translation_engine:
            config.TRANSLATION_ENGINE = translation_engine
        if ocr_engine:
            config.OCR_ENGINE = ocr_engine

        # 延迟初始化
        self.extractor: PDFExtractor = None
        self.ocr: OCREngine = None
        self.translator: TranslationEngine = None

    def run(self):
        """主流程"""
        print("=" * 60)
        print(f"  日文 PDF 翻译工具")
        print(f"  源文件: {self.pdf_path}")
        print(f"  输出: {self.output_path}")
        print(f"  翻译引擎: {config.TRANSLATION_ENGINE}")
        print(f"  OCR引擎: {config.OCR_ENGINE}")
        print("=" * 60)

        # 步骤 1: 初始化引擎
        print("\n[1/5] 初始化引擎...")
        self.translator = create_translation_engine()
        self.ocr = create_ocr_engine()

        # 步骤 2: 提取 PDF 内容
        print("\n[2/5] 提取 PDF 文字和图片...")
        pages_content = self._extract_content()

        # 步骤 3: 翻译文字块
        print("\n[3/5] 翻译文字内容...")
        translated_texts = self._translate_text(pages_content)

        # 步骤 4: OCR 识别图片文字并翻译（保留位置信息）
        print("\n[4/5] OCR 识别并翻译图片中的文字...")
        ocr_results_per_page = self._ocr_and_translate_images(pages_content)

        # 步骤 5: 生成翻译后的 PDF
        print("\n[5/5] 生成翻译后的 PDF...")
        self._generate_pdf(pages_content, translated_texts, ocr_results_per_page)

        # 汇总报告
        self._print_summary(pages_content, translated_texts, ocr_results_per_page)

        print("\n" + "=" * 60)
        print(f"  ✅ 翻译完成！")
        print(f"  输出文件: {self.output_path}")
        print("=" * 60)

    def _extract_content(self) -> list:
        """提取 PDF 中的所有内容"""
        self.extractor = PDFExtractor(
            self.pdf_path,
            temp_dir=self.temp_dir
        )
        pages_content = self.extractor.extract_all()

        total_text_blocks = sum(len(p.text_blocks) for p in pages_content)
        total_images = sum(len(p.image_blocks) for p in pages_content)

        print(f"  共 {len(pages_content)} 页")
        print(f"  文字块: {total_text_blocks} 个")
        print(f"  图片: {total_images} 张")

        return pages_content

    def _translate_text(self, pages_content: list) -> list:
        """翻译所有文字块，错误信息不会被进度条覆盖"""
        translated_texts = []
        errors = []

        for page in tqdm(pages_content, desc="  翻译文字"):
            page_texts = []
            for block in page.text_blocks:
                if block.text.strip():
                    try:
                        translated = self.translator.translate(block.text)
                        page_texts.append(translated)
                    except Exception as e:
                        msg = f"翻译失败 [{block.text[:20]}...]: {e}"
                        errors.append(msg)
                        tqdm.write(f"  [警告] {msg}")
                        page_texts.append(block.text)  # 失败保留原文
                else:
                    page_texts.append(block.text)
            translated_texts.append(page_texts)

        if errors:
            tqdm.write(f"\n  ⚠ 文字翻译有 {len(errors)} 条失败")
        return translated_texts

    def _ocr_and_translate_images(self, pages_content: list) -> list:
        """OCR 识别图片文字并翻译，保留完整位置信息"""
        ocr_results_per_page = []
        ocr_errors = 0
        translate_errors = 0
        skipped_low_conf = 0
        skipped_refusal = 0

        # OCR 置信度阈值：低于此值的短文本直接丢弃
        MIN_OCR_CONFIDENCE = 0.15

        # 翻译引擎拒绝翻译的关键词
        REFUSAL_KEYWORDS = [
            "您似乎没有提供",
            "请提供具体的",
            "请提供需要翻译",
            "您没有提供任何",
            "你似乎没有提供",
        ]

        for page in tqdm(pages_content, desc="  处理图片"):
            page_results = []

            for img_block in page.image_blocks:
                if not img_block.image_path or not os.path.exists(img_block.image_path):
                    continue

                try:
                    # OCR 识别
                    ocr_results = self.ocr.recognize_file(img_block.image_path)
                    if not ocr_results:
                        continue

                    # 翻译每个识别出的文字块
                    img_translations = []
                    for ocr_r in ocr_results:
                        if not ocr_r.text.strip():
                            continue
                        # 低置信度短文本跳过
                        if ocr_r.confidence < MIN_OCR_CONFIDENCE and len(ocr_r.text.strip()) <= 3:
                            skipped_low_conf += 1
                            continue
                        try:
                            translated = self.translator.translate(ocr_r.text)

                            # 检测翻译引擎拒绝响应
                            is_refusal = any(kw in translated for kw in REFUSAL_KEYWORDS)
                            if is_refusal:
                                skipped_refusal += 1
                                # 拒绝时用原文，避免空白
                                img_translations.append({
                                    "original": ocr_r.text,
                                    "translated": ocr_r.text,
                                    "bbox": ocr_r.bbox,
                                    "confidence": ocr_r.confidence,
                                })
                                continue

                            img_translations.append({
                                "original": ocr_r.text,
                                "translated": translated,
                                "bbox": ocr_r.bbox,
                                "confidence": ocr_r.confidence,
                            })
                        except Exception as e:
                            translate_errors += 1
                            if translate_errors <= 5:
                                tqdm.write(f"  [警告] 翻译OCR文字失败: {ocr_r.text[:20]}... - {e}")
                            # 失败时保留原文
                            img_translations.append({
                                "original": ocr_r.text,
                                "translated": ocr_r.text,
                                "bbox": ocr_r.bbox,
                                "confidence": ocr_r.confidence,
                            })

                    if img_translations:
                        page_results.append({
                            "image_path": img_block.image_path,
                            "image_bbox": img_block.bbox,
                            "translations": img_translations,
                        })

                except Exception as e:
                    ocr_errors += 1
                    if ocr_errors <= 5:
                        tqdm.write(f"  [警告] OCR失败: {str(e)[:80]}")

            ocr_results_per_page.append(page_results)

        # 汇总
        total_ocr = sum(len(r) for r in ocr_results_per_page)
        if ocr_errors or translate_errors or skipped_low_conf or skipped_refusal:
            parts = []
            if ocr_errors:
                parts.append(f"OCR失败: {ocr_errors}")
            if translate_errors:
                parts.append(f"翻译失败: {translate_errors}")
            if skipped_low_conf:
                parts.append(f"跳过低质量: {skipped_low_conf}")
            if skipped_refusal:
                parts.append(f"翻译拒绝: {skipped_refusal}")
            tqdm.write(f"\n  ⚠ {' | '.join(parts)}")

        return ocr_results_per_page

    def _print_summary(self, pages_content, translated_texts, ocr_results_per_page):
        """打印翻译汇总"""
        total_text = sum(len(t) for t in translated_texts)
        total_img_text = sum(
            len(img["translations"])
            for page_results in ocr_results_per_page
            for img in page_results
        )
        has_text = total_text > 0
        has_img_text = total_img_text > 0

        print()
        if has_text and has_img_text:
            print(f"  📊 翻译了 {total_text} 个文字块 + {total_img_text} 个图片文字区域")
        elif has_text:
            print(f"  📊 翻译了 {total_text} 个文字块（图片型PDF，文字在图片中）")
        elif has_img_text:
            print(f"  📊 翻译了 {total_img_text} 个图片文字区域（纯图片型PDF）")
        else:
            print(f"  ⚠ 未翻译任何内容 — PDF 可能没有可提取的文字或图片")

    def _generate_pdf(
        self,
        pages_content: list,
        translated_texts: list,
        ocr_results_per_page: list
    ):
        """生成翻译后的 PDF"""
        generator = PDFGenerator(self.output_path)
        generator.generate(pages_content, translated_texts, ocr_results_per_page)


def main():
    parser = argparse.ArgumentParser(
        description="日文 PDF 翻译工具 - 将日文 PDF 翻译为中文",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python main.py input.pdf
  python main.py input.pdf -o output.pdf
  python main.py input.pdf --translator deepseek
  python main.py input.pdf --translator openai
  python main.py input.pdf --ocr tesseract
  python main.py input.pdf --translator google --ocr easyocr
        """
    )

    parser.add_argument("pdf", help="输入的日文 PDF 或 DOCX 文件路径")
    parser.add_argument("-o", "--output", help="输出文件路径", default=None)
    parser.add_argument(
        "--translator",
        choices=["google", "deepseek", "openai", "deepl"],
        default=None,
        help="翻译引擎 (默认: deepseek)"
    )
    parser.add_argument(
        "--ocr",
        choices=["easyocr", "tesseract"],
        default=None,
        help="OCR 引擎 (默认: easyocr)"
    )

    args = parser.parse_args()

    if not os.path.exists(args.pdf):
        print(f"错误: 文件不存在 - {args.pdf}")
        sys.exit(1)

    ext = os.path.splitext(args.pdf)[1].lower()

    if ext == ".docx":
        _translate_docx(args)
    else:
        _translate_pdf(args)


def _translate_pdf(args):
    """PDF 翻译（原有逻辑）"""
    translator = JapanesePDFTranslator(
        pdf_path=args.pdf,
        output_path=args.output,
        translation_engine=args.translator,
        ocr_engine=args.ocr,
    )
    translator.run()


def _translate_docx(args):
    """DOCX 翻译（带进度条）"""
    from core.dispatcher import DocumentDispatcher
    from types import SimpleNamespace
    from tqdm import tqdm

    if args.translator:
        config.TRANSLATION_ENGINE = args.translator
    if args.ocr:
        config.OCR_ENGINE = args.ocr

    if args.output is None:
        base = os.path.splitext(args.pdf)[0]
        args.output = f"{base}_translated.docx"

    print("=" * 60)
    print(f"  日文 DOCX 翻译工具")
    print(f"  源文件: {args.pdf}")
    print(f"  输出: {args.output}")
    print(f"  翻译引擎: {config.TRANSLATION_ENGINE}")
    print(f"  OCR引擎: {config.OCR_ENGINE}")
    print("=" * 60)

    # 步骤1: 读取
    print("\n[1/3] 读取 DOCX...")
    from modules.docx_reader import DocxReader
    reader = DocxReader(args.pdf)
    content = reader.extract()
    print(f"  段落: {len(content.paragraphs)}, 标题: {len(content.headings)}")
    print(f"  表格: {len(content.tables)}, 图片: {len(content.images)}")

    # 步骤2: 翻译
    from modules.translator import create_translation_engine
    translator = create_translation_engine()

    all_items = []
    for p in sorted(content.paragraphs, key=lambda x: x.index):
        all_items.append(p.text)
    for h in sorted(content.headings, key=lambda x: x.index):
        all_items.append(h.text)
    for t in content.tables:
        for row in range(t.rows):
            for col in range(t.cols):
                c = t.get_cell(row, col)
                if c:
                    all_items.append(c.text)

    to_translate = [(i, t) for i, t in enumerate(all_items) if len(t.strip()) > 1]
    print(f"\n[2/3] 翻译文字: {len(to_translate)} 条...")

    translated_list = [''] * len(all_items)
    for i, text in tqdm(to_translate, desc="  翻译中"):
        try:
            translated_list[i] = translator.translate(text)
        except Exception:
            translated_list[i] = text

    # 步骤3: 写回
    print(f"\n[3/3] 生成翻译后 DOCX...")
    from modules.docx_writer import DocxWriter
    writer = DocxWriter(args.pdf)
    writer.write_translated(content, translated_list, args.output)

    print(f"\n{'=' * 60}")
    print(f"  ✅ 翻译完成！")
    print(f"  输出文件: {args.output}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
