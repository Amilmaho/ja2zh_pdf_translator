#!/usr/bin/env python3
"""
日文文档翻译工具 — 命令行入口

用法:
    python main.py input/doc.pdf
    python main.py input/doc.pdf --pages 1-5
    python main.py input/doc.pdf --translator dummy          # 离线链路自测
    python main.py input/doc.docx --translator deepseek
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from modules.fonts import describe_font
from modules.translator import available_engines


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="日文文档翻译工具 — 把日文 PDF / DOCX 翻译为简体中文",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python main.py input/book.pdf                      # 翻译整个 PDF
  python main.py input/book.pdf --pages 1-5          # 只翻译第 1-5 页
  python main.py input/book.pdf --pages 1-5,10-20    # 多段页码范围
  python main.py input/book.pdf --max-pages 2        # 只处理前 2 页（试跑）
  python main.py input/book.pdf --translator dummy   # 离线伪翻译，验证排版
  python main.py input/book.pdf --ocr tesseract      # 换 OCR 引擎
  python main.py input/book.docx -o output/out.docx  # 指定输出路径
  python main.py --list-engines                      # 查看可用引擎
""",
    )

    parser.add_argument("input", nargs="?", help="输入的日文 PDF 或 DOCX 文件路径")
    parser.add_argument("-o", "--output", default=None, help="输出文件路径")
    parser.add_argument(
        "--pages", default=None,
        help='页码范围，例如 "1-5"、"1,3,5"、"1-5,10-20"（仅 PDF）',
    )
    parser.add_argument(
        "--translator", default=None,
        choices=available_engines(),
        help="翻译引擎（默认取 .env 中的 TRANSLATION_ENGINE）",
    )
    parser.add_argument(
        "--ocr", default=None, choices=["easyocr", "tesseract"],
        help="OCR 引擎（默认 easyocr）",
    )
    parser.add_argument(
        "--translate-images", action="store_true",
        help="文字型页面里的图片也做 OCR 翻译；DOCX 模式下表示重绘内嵌图片",
    )
    parser.add_argument(
        "--max-pages", type=int, default=None,
        help="最多处理多少页（用于快速试跑）",
    )
    parser.add_argument(
        "--dpi", type=int, default=None,
        help=f"整页渲染给 OCR 用的 DPI（默认 {config.PDF_RENDER_DPI}）",
    )
    parser.add_argument(
        "--font", default=None, help="中文字体路径（默认自动检测）",
    )
    parser.add_argument(
        "--list-engines", action="store_true", help="列出可用的翻译引擎后退出",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="减少输出")
    return parser


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.list_engines:
        print("可用翻译引擎:", ", ".join(available_engines()))
        print("可用 OCR 引擎: easyocr, tesseract")
        print("当前中文字体:", describe_font())
        return 0

    if not args.input:
        parser.print_help()
        return 2

    if not os.path.exists(args.input):
        print(f"错误: 文件不存在 - {args.input}")
        return 1

    if args.font:
        config.FONT_PATH = args.font
    if args.dpi:
        config.PDF_RENDER_DPI = args.dpi
    if args.translator:
        config.TRANSLATION_ENGINE = args.translator
    if args.ocr:
        config.OCR_ENGINE = args.ocr

    ext = os.path.splitext(args.input)[1].lower()
    try:
        if ext == ".docx":
            return _run_docx(args)
        if ext == ".pdf":
            return _run_pdf(args)
        print(f"错误: 不支持的格式 {ext}（支持 .pdf / .docx）")
        return 1
    except KeyboardInterrupt:
        print("\n已中断")
        return 130
    except Exception as exc:
        print(f"\n错误: {exc}")
        if config.DEBUG:
            raise
        return 1


def _run_pdf(args) -> int:
    from core.pdf_translator import PDFTranslator

    pipeline = PDFTranslator(
        pdf_path=args.input,
        output_path=args.output,
        translation_engine=args.translator,
        ocr_engine=args.ocr,
        page_range=args.pages,
        translate_images=args.translate_images,
        max_pages=args.max_pages,
        verbose=not args.quiet,
    )
    stats = pipeline.run()
    return 0 if stats.get("drawn", 0) > 0 or stats.get("kept_original", 0) == 0 else 0


def _run_docx(args) -> int:
    from core.docx_translator import DOCXTranslator

    pipeline = DOCXTranslator(
        file_path=args.input,
        output_path=args.output,
        translation_engine=args.translator,
        ocr_engine=args.ocr,
        translate_images=args.translate_images,
        verbose=not args.quiet,
    )
    pipeline.run()
    return 0


# 向后兼容：老代码里的 `from main import JapanesePDFTranslator`
from core.pdf_translator import PDFTranslator as JapanesePDFTranslator  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
