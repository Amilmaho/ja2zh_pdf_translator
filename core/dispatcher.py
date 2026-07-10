"""
Document Dispatcher - 文档格式分派器（Phase 2 Step 2）

职责：
  根据文件类型自动选择对应的 Parser。
  目前只支持 PDF，DOCX/Image/PPTX/EPUB 仅保留接口。

调用链：
  TaskManager → DocumentDispatcher.dispatch(task) → PDFTranslator (未来: DOCX...)
"""

import os
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Callable
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config


# ── 数据结构 ──────────────────────────────────────────────

@dataclass
class DispatchResult:
    """分派执行结果"""
    task_id: str
    file_path: str
    file_format: str
    success: bool
    output_path: str = ""
    error: str = ""
    stats: dict = field(default_factory=dict)  # 统计信息


# ── Translator 抽象基类（未来所有格式 Translator 的接口）────

class DocumentTranslator(ABC):
    """
    文档翻译器抽象基类。
    
    所有格式的 Translator 必须实现此接口：
      - PDFTranslator (已有，需适配)
      - DOCXTranslator (未来)
      - ImageTranslator (未来)
      - PPTXTranslator (未来)
      - EPUBTranslator (未来)
    """

    @abstractmethod
    def translate(
        self,
        file_path: str,
        output_path: str,
        translation_engine: str = None,
        ocr_engine: str = None,
        page_range: str = None,
        log_callback: Callable = None,
        progress_callback: Callable = None,
        **kwargs,
    ) -> DispatchResult:
        """
        执行翻译。

        Args:
            file_path: 输入文件路径
            output_path: 输出文件路径
            translation_engine: 翻译引擎名称
            ocr_engine: OCR 引擎名称
            page_range: 页码范围
            log_callback: 日志回调 fn(message, level, progress)
            progress_callback: 进度回调 fn(percent)

        Returns:
            DispatchResult: 翻译结果
        """
        ...


# ── PDF Translator 适配器 ────────────────────────────────

class PDFTranslator(DocumentTranslator):
    """
    PDF 翻译器 — 适配现有的 JapanesePDFTranslator。

    注意：这是一个适配器层，不修改 JapanesePDFTranslator 的核心逻辑。
    """

    def translate(
        self,
        file_path: str,
        output_path: str,
        translation_engine: str = None,
        ocr_engine: str = None,
        page_range: str = None,
        log_callback: Callable = None,
        progress_callback: Callable = None,
        **kwargs,
    ) -> DispatchResult:
        from main import JapanesePDFTranslator

        def log(msg, level="info", progress=0):
            if log_callback:
                log_callback(msg, level, progress)

        try:
            log(f"开始处理 PDF: {os.path.basename(file_path)}", "info", 1)

            translator = JapanesePDFTranslator(
                pdf_path=file_path,
                output_path=output_path,
                translation_engine=translation_engine,
                ocr_engine=ocr_engine,
                page_range=page_range,
            )

            # 注入进度和日志回调到 translator
            # 注意：这里通过 monkey-patch 方式为 JapanesePDFTranslator 添加回调，
            # 而不是修改其内部代码。未来重构 JapanesePDFTranslator 时再改为正式接口。
            translator._log_callback = log
            translator._progress_callback = progress_callback

            log("初始化引擎...", "info", 2)
            translator.translator = self._create_translator(translation_engine)
            translator.ocr = self._create_ocr(ocr_engine)

            log("提取 PDF 文字和图片...", "info", 10)
            pages_content = translator._extract_content()
            log(f"提取完成: {len(pages_content)} 页", "success", 40)

            log("翻译文字内容...", "info", 50)
            translated_texts = translator._translate_text(pages_content)

            log("OCR 识别并翻译图片文字...", "info", 65)
            ocr_results_per_page = translator._ocr_and_translate_images(pages_content)

            log("生成翻译后 PDF...", "info", 85)
            translator._generate_pdf(pages_content, translated_texts, ocr_results_per_page)

            log(f"✅ 翻译完成！输出: {output_path}", "success", 100)

            return DispatchResult(
                task_id="",
                file_path=file_path,
                file_format="pdf",
                success=True,
                output_path=output_path,
                stats={
                    "pages": len(pages_content),
                    "text_blocks": sum(len(t) for t in translated_texts),
                    "ocr_regions": sum(len(r) for r in ocr_results_per_page),
                },
            )

        except Exception as e:
            log(f"❌ 翻译失败: {e}", "error")
            import traceback
            traceback.print_exc()
            return DispatchResult(
                task_id="",
                file_path=file_path,
                file_format="pdf",
                success=False,
                error=str(e),
            )

    def _create_translator(self, engine_name: str = None):
        from modules.translator import create_translation_engine
        if engine_name:
            config.TRANSLATION_ENGINE = engine_name
        return create_translation_engine()

    def _create_ocr(self, engine_name: str = None):
        from modules.ocr_engine import create_ocr_engine
        if engine_name:
            config.OCR_ENGINE = engine_name
        return create_ocr_engine()


# ── 预留 Translator（接口占位，不实现逻辑）─────────────────

class DOCXTranslator(DocumentTranslator):
    """DOCX 翻译器 — 读 DOCX → 翻译文字+OCR图片 → 写 DOCX"""

    def translate(
        self,
        file_path: str,
        output_path: str,
        translation_engine: str = None,
        ocr_engine: str = None,
        page_range: str = None,
        log_callback: Callable = None,
        progress_callback: Callable = None,
        **kwargs,
    ) -> DispatchResult:
        from modules.docx_reader import DocxReader
        from modules.ocr_engine import create_ocr_engine
        from modules.translator import create_translation_engine
        from modules.docx_writer import DocxWriter

        def log(msg, level="info", progress=0):
            if log_callback:
                log_callback(msg, level, progress)

        try:
            log(f"开始处理 DOCX: {os.path.basename(file_path)}", "info", 1)

            # 步骤1: 读取 DOCX
            log("读取 DOCX 文档结构...", "info", 5)
            reader = DocxReader(file_path)
            content = reader.extract()
            log(f"提取完成: {len(content.paragraphs)}段落, {len(content.headings)}标题, {len(content.tables)}表格, {len(content.images)}图片", "success", 15)

            # 构建翻译列表（顺序：段落(index排序)→标题(index排序)→表格(行列)→页眉→页脚）
            all_items = []
            for p in sorted(content.paragraphs, key=lambda x: x.index):
                all_items.append(p.text)
            for h in sorted(content.headings, key=lambda x: x.index):
                all_items.append(h.text)
            for t in content.tables:
                for row in range(t.rows):
                    for col in range(t.cols):
                        cell = t.get_cell(row, col)
                        if cell:
                            all_items.append(cell.text)
            for hdr in content.headers:
                all_items.append(hdr)
            for ftr in content.footers:
                all_items.append(ftr)

            # 过滤空文本
            texts_to_translate = [t for t in all_items if t.strip() and len(t.strip()) > 1]
            log(f"待翻译文本: {len(texts_to_translate)} 条", "info", 20)

            if not texts_to_translate:
                # 没有文字可翻译，直接复制原文件
                import shutil
                shutil.copy(file_path, output_path)
                log("文档无文字内容，已复制原文件", "success", 100)
                return DispatchResult(
                    task_id="",
                    file_path=file_path,
                    file_format="docx",
                    success=True,
                    output_path=output_path,
                    stats={"texts_translated": 0},
                )

            # 步骤2: 初始化引擎
            log("初始化翻译引擎...", "info", 25)
            translator = create_translation_engine()
            if translation_engine:
                config.TRANSLATION_ENGINE = translation_engine

            # 步骤3: 翻译文字
            translated = []
            total = len(texts_to_translate)
            for i, text in enumerate(texts_to_translate):
                try:
                    result = translator.translate(text)
                    translated.append(result)
                except Exception as e:
                    log(f"翻译失败 [{text[:30]}...]: {e}", "warning")
                    translated.append(text)  # 回退原文
                if i % max(1, total // 5) == 0:
                    log(f"翻译进度: {i+1}/{total}", "info", 25 + int(50 * (i+1) / total))

            log(f"翻译完成: {total} 条", "success", 75)

            # 步骤4: OCR 图片（可选）
            if content.images:
                do_ocr = kwargs.get("docx_translate_images", True)
                if do_ocr:
                    log(f"OCR 识别图片: {len(content.images)} 张...", "info", 80)
                    ocr = create_ocr_engine()
                    if ocr_engine:
                        config.OCR_ENGINE = ocr_engine
                    DocxReader.ocr_images(content, ocr)
                    ocr_total = sum(len(img.ocr_results) for img in content.images)
                    log(f"OCR 完成: {ocr_total} 个文字区域", "success", 85)

            # 步骤5: 写回 DOCX
            log("生成翻译后 DOCX...", "info", 90)
            writer = DocxWriter(file_path)

            # 构建完整翻译结果（保持与原文相同顺序）
            all_translated = []
            trans_idx = 0
            for item in all_items:
                if item.strip() and len(item.strip()) > 1 and trans_idx < len(translated):
                    all_translated.append(translated[trans_idx])
                    trans_idx += 1
                else:
                    all_translated.append(item)  # 保留原文

            writer.write_translated(content, all_translated, output_path)
            log(f"✅ DOCX 翻译完成！输出: {output_path}", "success", 100)

            return DispatchResult(
                task_id="",
                file_path=file_path,
                file_format="docx",
                success=True,
                output_path=output_path,
                stats={
                    "texts_translated": total,
                    "images_ocr": sum(1 for img in content.images if img.has_ocr),
                    "ocr_regions": sum(len(img.ocr_results) for img in content.images),
                },
            )

        except Exception as e:
            log(f"❌ DOCX 翻译失败: {e}", "error")
            import traceback
            traceback.print_exc()
            return DispatchResult(
                task_id="",
                file_path=file_path,
                file_format="docx",
                success=False,
                error=str(e),
            )


class ImageTranslator(DocumentTranslator):
    """图片翻译器（预留接口，未来实现）"""
    def translate(self, file_path, output_path, **kwargs):
        raise NotImplementedError("图片翻译将在 Phase 6 实现")


class PPTXTranslator(DocumentTranslator):
    """PPTX 翻译器（预留接口，未来实现）"""
    def translate(self, file_path, output_path, **kwargs):
        raise NotImplementedError("PPTX 翻译将在 Phase 7 实现")


class EPUBTranslator(DocumentTranslator):
    """EPUB 翻译器（预留接口，未来实现）"""
    def translate(self, file_path, output_path, **kwargs):
        raise NotImplementedError("EPUB 翻译将在 Phase 8 实现")


# ── Dispatcher ────────────────────────────────────────────

class DocumentDispatcher:
    """
    文档格式分派器。

    根据文件扩展名自动选择对应的 Translator。
    目前只支持 PDF，其他格式保留接口。

    使用方式:
        dispatcher = DocumentDispatcher()
        result = dispatcher.dispatch(task)
    """

    # 格式 → Translator 类映射
    _TRANSLATOR_MAP = {
        "pdf": PDFTranslator,
        "docx": DOCXTranslator,       # 预留
        "pptx": PPTXTranslator,       # 预留
        "epub": EPUBTranslator,       # 预留
        "png": ImageTranslator,       # 预留
        "jpg": ImageTranslator,       # 预留
        "jpeg": ImageTranslator,      # 预留
    }

    def __init__(
        self,
        log_callback: Callable = None,
        progress_callback: Callable = None,
    ):
        self._log = log_callback or (lambda msg, level, p: None)
        self._progress = progress_callback or (lambda p: None)

    def dispatch(self, task) -> DispatchResult:
        """
        分派翻译任务。

        Args:
            task: Task 对象（来自 TaskManager）

        Returns:
            DispatchResult: 翻译结果
        """
        fmt = task.file_format.lower()

        translator_cls = self._TRANSLATOR_MAP.get(fmt)
        if translator_cls is None:
            return DispatchResult(
                task_id=task.id,
                file_path=task.file_path,
                file_format=fmt,
                success=False,
                error=f"不支持的文件格式: {fmt}（支持: {', '.join(self._TRANSLATOR_MAP.keys())}）",
            )

        translator = translator_cls()
        result = translator.translate(
            file_path=task.file_path,
            output_path=task.output_path,
            translation_engine=task.config.translation_engine,
            ocr_engine=task.config.ocr_engine,
            page_range=task.config.page_range,
            log_callback=self._log,
            progress_callback=self._progress,
        )

        result.task_id = task.id
        return result
