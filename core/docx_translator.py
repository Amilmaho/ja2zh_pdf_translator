"""
DOCX 翻译流水线（重构版）

流程：读取 → 构建条目 → 批量翻译 → （可选）图片 OCR+重绘 → 写回

修复了旧版的两处硬伤：
  1. 未翻译的段落会被写成空串，导致原文被抹掉（现在保留原文）
  2. 图片只做 OCR 不重绘，译文无处落地（现在可把译文画回图片）
"""

import os
import sys
import time
from typing import Callable, Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config
from modules.docx_reader import DocxContent, DocxReader
from modules.docx_writer import DocxWriter
from modules.image_overlay import render_regions
from modules.ocr_engine import create_ocr_engine
from modules.translator import create_translation_engine
from modules.utils import ProgressReporter, format_duration, short_hash


class DOCXTranslator:
    """DOCX 翻译编排器"""

    def __init__(
        self,
        file_path: str,
        output_path: str = None,
        translation_engine: str = None,
        ocr_engine: str = None,
        translate_images: bool = None,
        log_callback: Callable = None,
        progress_callback: Callable = None,
        verbose: bool = True,
    ):
        self.file_path = file_path
        self.base_name = os.path.splitext(os.path.basename(file_path))[0]
        self.output_path = output_path or os.path.join(
            config.OUTPUT_DIR, f"{self.base_name}_translated.docx"
        )
        self.verbose = verbose
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.translate_images = (
            config.OVERLAY_TRANSLATE_DOCX_IMAGES
            if translate_images is None else translate_images
        )
        self.temp_dir = os.path.join(config.TEMP_DIR, "docx", self.base_name)
        os.makedirs(self.temp_dir, exist_ok=True)

        if translation_engine:
            config.TRANSLATION_ENGINE = translation_engine
        if ocr_engine:
            config.OCR_ENGINE = ocr_engine

        self.reporter = ProgressReporter(callback=log_callback, verbose=verbose)
        self.stats: Dict = {}

    # ── 主流程 ───────────────────────────────────────────

    def run(self) -> Dict:
        started = time.time()
        rep = self.reporter

        rep.log("=" * 58, progress=0)
        rep.log("日文 DOCX 翻译", progress=0)
        rep.log(f"源文件: {self.file_path}", progress=0)
        rep.log(f"输出  : {self.output_path}", progress=0)
        rep.log("=" * 58, progress=0)

        rep.log("[1/4] 读取 DOCX...", progress=3)
        reader = DocxReader(self.file_path, temp_dir=self.temp_dir)
        content = reader.extract()
        rep.log(
            f"段落 {len(content.paragraphs)} / 标题 {len(content.headings)} / "
            f"表格 {len(content.tables)} / 图片 {len(content.images)}",
            progress=8,
        )

        rep.log("[2/4] 批量翻译文字...", progress=12)
        translator = create_translation_engine(verbose=self.verbose)
        translated_list, n_translated = self._translate_text(content, translator)

        image_stats = {"images": 0, "regions": 0, "drawn": 0, "failed": 0}
        if self.translate_images and content.images:
            rep.log("[3/4] 图片 OCR + 重绘...", progress=60)
            image_stats = self._translate_images(content, translator)
        else:
            rep.log("[3/4] 跳过图片翻译（可用 --translate-images 开启）", progress=60)

        rep.log("[4/4] 写回 DOCX...", progress=85)
        writer = DocxWriter(self.file_path)
        writer.write_translated(content, translated_list, self.output_path)

        if image_stats.get("replacements"):
            replaced = writer.replace_images(image_stats["replacements"])
            # 图片是在写回之后替换的，需要重新保存
            if replaced:
                writer.doc.save(self.output_path)
            image_stats["replaced"] = replaced

        elapsed = time.time() - started
        self.stats = {
            "texts_translated": n_translated,
            "images": image_stats,
            "output_path": self.output_path,
            "elapsed": elapsed,
        }

        rep.log("", progress=100)
        rep.log(
            f"翻译完成: 文字 {n_translated} 条"
            + (f"，图片 {image_stats['images']} 张 / {image_stats['drawn']} 处译文"
               if image_stats["images"] else ""),
            "success", 100,
        )
        rep.log(f"耗时: {format_duration(elapsed)}", "info", 100)
        rep.log(f"输出文件: {self.output_path}", "success", 100)
        return self.stats

    # ── 文字 ─────────────────────────────────────────────

    def _translate_text(self, content: DocxContent, translator) -> Tuple[List[str], int]:
        """
        构建与 DocxWriter 一致的条目顺序，逐条翻译。
        空条目/过短条目保留原文占位，保证索引对齐。
        """
        items: List[str] = []
        for para in sorted(content.paragraphs, key=lambda p: p.index):
            items.append(para.text)
        for heading in sorted(content.headings, key=lambda h: h.index):
            items.append(heading.text)
        for table in content.tables:
            for row in range(table.rows):
                for col in range(table.cols):
                    cell = table.get_cell(row, col)
                    items.append(cell.text if cell else "")
        items.extend(content.headers)
        items.extend(content.footers)

        # 只翻译「有实际内容」的条目；其余原样保留（修复旧版清空问题）
        translatable_idx = [
            i for i, text in enumerate(items)
            if text and len(text.strip()) > 1
        ]
        result = list(items)

        if translatable_idx:
            texts = [items[i] for i in translatable_idx]
            translated = translator.translate_many(
                texts, progress=self._progress_fn(12, 58)
            )
            for i, value in zip(translatable_idx, translated):
                result[i] = value if (value and value.strip()) else items[i]

        translator.save_cache()
        return result, len(translatable_idx)

    # ── 图片 ─────────────────────────────────────────────

    def _translate_images(self, content: DocxContent, translator) -> Dict:
        ocr = create_ocr_engine(verbose=self.verbose)
        replacements: Dict[str, str] = {}
        total_regions = drawn = failed = 0

        for img in content.images:
            if not img.image_path or not os.path.exists(img.image_path):
                continue
            if not img.width_px or not img.height_px:
                continue
            try:
                results = ocr.recognize_file(img.image_path)
            except Exception as exc:
                self.reporter.log(f"图片[{img.index}] OCR 失败: {str(exc)[:80]}", "warning")
                continue

            kept = [
                r for r in results
                if r.text.strip() and r.confidence >= config.OCR_MIN_CONFIDENCE
            ]
            if not kept:
                continue

            texts = translator.translate_many([r.text for r in kept])
            regions = []
            for result, text in zip(kept, texts):
                if not text or not text.strip():
                    continue
                regions.append({
                    "bbox": result.bbox,
                    "translated": text.strip(),
                    "original": result.text,
                })
            if not regions:
                continue

            total_regions += len(regions)
            out_path = os.path.join(
                self.temp_dir,
                f"translated_{short_hash(img.image_path, 8)}_{img.index}.{img.ext}",
            )
            stats = render_regions(
                img.image_path, regions, out_path, verbose=self.verbose
            )
            drawn += stats["drawn"]
            failed += stats["failed"]
            if stats["drawn"]:
                key = img.part_name or os.path.basename(img.image_path)
                replacements[key] = out_path

        ocr.save_cache()
        translator.save_cache()
        return {
            "images": len(replacements),
            "regions": total_regions,
            "drawn": drawn,
            "failed": failed,
            "replacements": replacements,
        }

    # ── 工具 ─────────────────────────────────────────────

    def _progress_fn(self, low: int, high: int):
        def fn(done, total, desc="翻译"):
            percent = low + int((high - low) * done / max(1, total))
            if self.verbose and (done == total or done % 20 == 0):
                self.reporter.log(f"{desc} {done}/{total}", "info", percent)
            if self.progress_callback:
                try:
                    self.progress_callback(percent)
                except Exception:
                    pass
        return fn
