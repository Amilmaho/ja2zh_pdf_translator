"""
Document Dispatcher — 文档格式分派器（重构版）

调用链：
  Web UI → TaskManager → DocumentDispatcher → PDFTranslator / DOCXTranslator

修复点：
  旧版 PDF 适配器把 page_range 传给了不接受该参数的构造函数，
  任何一次 Web UI 的 PDF 翻译都会直接抛 TypeError。现在统一走
  core.pdf_translator.PDFTranslator，页码范围、进度、日志都正确透传。
"""

import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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
    stats: dict = field(default_factory=dict)


# ── 抽象基类 ──────────────────────────────────────────────

class DocumentTranslator(ABC):
    """所有格式翻译器的统一接口"""

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
        ...


# ── PDF ───────────────────────────────────────────────────

class PDFFormatTranslator(DocumentTranslator):
    """PDF 翻译器：直接委托给 core.pdf_translator.PDFTranslator"""

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
        from core.pdf_translator import PDFTranslator

        def log(msg, level="info", progress=0):
            if log_callback:
                log_callback(msg, level, progress)

        try:
            pipeline = PDFTranslator(
                pdf_path=file_path,
                output_path=output_path,
                translation_engine=translation_engine,
                ocr_engine=ocr_engine,
                page_range=page_range,
                translate_images=kwargs.get("translate_images", False),
                log_callback=log_callback,
                progress_callback=progress_callback,
                verbose=False,
            )
            stats = pipeline.run()
            return DispatchResult(
                task_id="",
                file_path=file_path,
                file_format="pdf",
                success=True,
                output_path=output_path,
                stats=stats,
            )
        except Exception as exc:
            import traceback
            traceback.print_exc()
            log(f"翻译失败: {exc}", "error")
            return DispatchResult(
                task_id="", file_path=file_path, file_format="pdf",
                success=False, error=str(exc),
            )


# ── DOCX ──────────────────────────────────────────────────

class DOCXFormatTranslator(DocumentTranslator):
    """DOCX 翻译器：直接委托给 core.docx_translator.DOCXTranslator"""

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
        from core.docx_translator import DOCXTranslator

        def log(msg, level="info", progress=0):
            if log_callback:
                log_callback(msg, level, progress)

        try:
            pipeline = DOCXTranslator(
                file_path=file_path,
                output_path=output_path,
                translation_engine=translation_engine,
                ocr_engine=ocr_engine,
                translate_images=kwargs.get("docx_translate_images"),
                log_callback=log_callback,
                progress_callback=progress_callback,
                verbose=False,
            )
            stats = pipeline.run()
            return DispatchResult(
                task_id="",
                file_path=file_path,
                file_format="docx",
                success=True,
                output_path=output_path,
                stats=stats,
            )
        except Exception as exc:
            import traceback
            traceback.print_exc()
            log(f"翻译失败: {exc}", "error")
            return DispatchResult(
                task_id="", file_path=file_path, file_format="docx",
                success=False, error=str(exc),
            )


class ImageTranslator(DocumentTranslator):
    """图片翻译器（预留接口）"""

    def translate(self, file_path, output_path, **kwargs):
        raise NotImplementedError("图片文件翻译尚未实现")


class PPTXTranslator(DocumentTranslator):
    """PPTX 翻译器（预留接口）"""

    def translate(self, file_path, output_path, **kwargs):
        raise NotImplementedError("PPTX 翻译尚未实现")


class EPUBTranslator(DocumentTranslator):
    """EPUB 翻译器（预留接口）"""

    def translate(self, file_path, output_path, **kwargs):
        raise NotImplementedError("EPUB 翻译尚未实现")


# ── 分派器 ────────────────────────────────────────────────

class DocumentDispatcher:
    """根据文件扩展名选择翻译器"""

    _TRANSLATOR_MAP = {
        "pdf": PDFFormatTranslator,
        "docx": DOCXFormatTranslator,
        "pptx": PPTXTranslator,
        "epub": EPUBTranslator,
        "png": ImageTranslator,
        "jpg": ImageTranslator,
        "jpeg": ImageTranslator,
    }

    def __init__(self, log_callback: Callable = None, progress_callback: Callable = None):
        self._log = log_callback or (lambda msg, level, p: None)
        self._progress = progress_callback or (lambda p: None)

    def dispatch(self, task) -> DispatchResult:
        fmt = (task.file_format or "").lower()
        translator_cls = self._TRANSLATOR_MAP.get(fmt)
        if translator_cls is None:
            return DispatchResult(
                task_id=task.id,
                file_path=task.file_path,
                file_format=fmt,
                success=False,
                error=f"不支持的文件格式: {fmt}（支持: {', '.join(self._TRANSLATOR_MAP)}）",
            )

        translator = translator_cls()
        translate_images = getattr(task.config, "translate_images", False)
        legacy_images = getattr(task.config, "docx_translate_images", None)
        if legacy_images is not None:
            translate_images = translate_images or bool(legacy_images)

        result = translator.translate(
            file_path=task.file_path,
            output_path=task.output_path,
            translation_engine=task.config.translation_engine,
            ocr_engine=task.config.ocr_engine,
            page_range=task.config.page_range,
            log_callback=self._log,
            progress_callback=self._progress,
            translate_images=translate_images,
            docx_translate_images=translate_images,
        )
        result.task_id = task.id
        return result


# ── 兼容旧名字 ────────────────────────────────────────────
PDFTranslator = PDFFormatTranslator
DOCXTranslator = DOCXFormatTranslator
