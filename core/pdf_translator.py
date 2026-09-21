"""
PDF 翻译流水线（重构版）

流程：
  1. 打开 PDF，解析页码范围
  2. 逐页提取内容（文字型页面取文字行 / 图片型页面渲染成图准备 OCR）
  3. OCR（图片型页面）
  4. 批量翻译（一次请求翻译多条，带缓存）
  5. 在原 PDF 副本上写入译文
  6. 自检：回读输出，确认每个区域真的写进了文字

逐页处理，内存占用与页数无关；任何一页出错都不会中断整个任务。
"""

import os
import sys
import time
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import fitz  # PyMuPDF

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config
from modules.ocr_engine import OCREngine, OCRResult, create_ocr_engine
from modules.pdf_extractor import PDFExtractor, PageContent
from modules.pdf_generator import (
    GenerateStats, OverlayItem, PagePlan, PDFGenerator, TextItem,
)
from modules.translator import TranslationEngine, create_translation_engine
from modules.utils import (
    PageRangeError, ProgressReporter, format_duration, format_page_selection,
    parse_page_range,
)


class PDFTranslator:
    """PDF 翻译编排器"""

    def __init__(
        self,
        pdf_path: str,
        output_path: str = None,
        translation_engine: str = None,
        ocr_engine: str = None,
        page_range: str = None,
        temp_dir: str = None,
        log_callback: Callable = None,
        progress_callback: Callable = None,
        translate_images: bool = False,
        max_pages: int = None,
        verbose: bool = True,
    ):
        self.pdf_path = pdf_path
        self.pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
        self.page_range = page_range
        self.max_pages = max_pages
        self.translate_images = translate_images
        self.verbose = verbose
        self.log_callback = log_callback
        self.progress_callback = progress_callback

        if output_path:
            self.output_path = output_path
        else:
            self.output_path = os.path.join(
                config.OUTPUT_DIR, f"{self.pdf_name}_translated.pdf"
            )

        self.temp_dir = temp_dir or os.path.join(config.TEMP_DIR, self.pdf_name)
        os.makedirs(self.temp_dir, exist_ok=True)

        if translation_engine:
            config.TRANSLATION_ENGINE = translation_engine
        if ocr_engine:
            config.OCR_ENGINE = ocr_engine

        self.reporter = ProgressReporter(
            callback=log_callback, verbose=verbose, prefix=""
        )

        self.extractor: Optional[PDFExtractor] = None
        self.ocr: Optional[OCREngine] = None
        self.translator: Optional[TranslationEngine] = None
        self.stats: Dict = {}

    # ── 对外入口 ─────────────────────────────────────────

    def run(self) -> Dict:
        started = time.time()
        rep = self.reporter

        rep.log("=" * 58, progress=0)
        rep.log("日文 PDF 翻译", progress=0)
        rep.log(f"源文件: {self.pdf_path}", progress=0)
        rep.log(f"输出  : {self.output_path}", progress=0)
        rep.log(f"引擎  : 翻译={config.TRANSLATION_ENGINE} / OCR={config.OCR_ENGINE}", progress=0)
        rep.log("=" * 58, progress=0)

        # [1/5] 打开文档
        rep.log("[1/5] 打开 PDF...", progress=2)
        self.extractor = PDFExtractor(
            self.pdf_path, temp_dir=self.temp_dir, render_dpi=config.PDF_RENDER_DPI
        )
        total_pages = self.extractor.get_page_count()

        try:
            pages = parse_page_range(self.page_range, total_pages)
        except PageRangeError as exc:
            rep.log(f"页码范围错误: {exc}", "error", 0)
            raise

        if self.max_pages:
            pages = pages[: self.max_pages]
        if not pages:
            raise ValueError("没有需要翻译的页面")

        rep.log(
            f"共 {total_pages} 页，本次处理 {len(pages)} 页: {format_page_selection(pages)}",
            progress=3,
        )

        # [2/5] 初始化引擎（懒加载：先看是否真的需要 OCR）
        rep.log("[2/5] 初始化翻译引擎...", progress=5)
        self.translator = create_translation_engine(verbose=self.verbose)

        # [3/5] 逐页提取 + OCR + 翻译
        rep.log("[3/5] 提取内容 / OCR / 翻译...", progress=8)
        plans, page_stats = self._process_pages(pages)

        if self.translator:
            self.translator.save_cache()

        # [4/5] 生成 PDF
        rep.log("[4/5] 在原 PDF 副本上写入译文...", progress=75)
        generator = PDFGenerator(
            self.output_path,
            source_pdf=self.pdf_path,
            verbose=self.verbose,
        )
        gen_stats = generator.apply(plans, progress=self._progress_fn(75, 95))

        # [5/5] 自检
        rep.log("[5/5] 自检输出...", progress=96)
        verify = self._verify_output(plans)

        elapsed = time.time() - started
        self.stats = {
            "pages_total": total_pages,
            "pages_processed": len(pages),
            "text_lines": page_stats["text_lines"],
            "ocr_regions": page_stats["ocr_regions"],
            "ocr_filtered": page_stats["ocr_filtered"],
            "drawn": gen_stats.items_drawn,
            "kept_original": gen_stats.items_kept_original,
            "failed": gen_stats.items_failed,
            "verify": verify,
            "output_path": self.output_path,
            "elapsed": elapsed,
        }
        self._print_summary(gen_stats, verify, elapsed)
        return self.stats

    # ── 逐页处理 ─────────────────────────────────────────

    def _process_pages(self, pages: Sequence[int]) -> Tuple[List[PagePlan], Dict[str, int]]:
        rep = self.reporter
        plans: List[PagePlan] = []
        stats = {"text_lines": 0, "ocr_regions": 0, "ocr_filtered": 0}
        total = len(pages)
        progress_span = (8, 74)

        for i, page_num in enumerate(pages):
            if self._cancelled():
                rep.log("任务已取消", "warning")
                break

            content = self.extractor.extract_page(page_num, with_images=False)
            plan = PagePlan(
                page_num=page_num,
                page_width=content.width,
                page_height=content.height,
            )

            try:
                if content.is_scan or not content.has_text:
                    # 扫描件 / 带隐藏 OCR 文字层的图片型页面 / 无文字页面
                    # → OCR（或复用文字层）+ 覆盖叠加
                    self._plan_image_page(content, plan, stats)
                else:
                    # 真正的文字型页面 → redaction 替换
                    self._plan_text_page(content, plan, stats)
                    if self.translate_images:
                        self._plan_image_page(content, plan, stats)
            except Exception as exc:
                rep.log(f"第 {page_num + 1} 页处理失败（保持原样）: {str(exc)[:120]}", "warning")

            if not plan.is_empty:
                plans.append(plan)

            done = i + 1
            percent = progress_span[0] + int(
                (progress_span[1] - progress_span[0]) * done / max(1, total)
            )
            if done == total or done % 10 == 0:
                rep.log(f"[{done}/{total}] 第 {page_num + 1} 页完成", "info", percent)
            self._emit_progress(percent)

        return plans, stats

    def _plan_text_page(self, content: PageContent, plan: PagePlan, stats: Dict):
        """文字型页面：翻译每一行"""
        blocks = [b for b in content.text_blocks if b.text.strip()]
        if not blocks:
            return
        translated = self.translator.translate_many([b.text for b in blocks])
        for block, text in zip(blocks, translated):
            if text and text.strip():
                plan.text_items.append(TextItem(
                    rect=fitz.Rect(*block.bbox),
                    translated=text.strip(),
                    original=block.text,
                    font_size=block.font_size or 10.0,
                ))
        stats["text_lines"] += len(plan.text_items)

    def _plan_image_page(self, content: PageContent, plan: PagePlan, stats: Dict):
        """
        图片型 / 扫描型页面：文字区域 → 批量翻译 → 覆盖叠加。

        优先使用页面自带的（隐藏）OCR 文字层：又快又准，不用跑 EasyOCR。
        没有文字层时才真正调用 OCR 引擎。
        """
        # 路径 A：页面已有文字层（扫描件常见），直接用它作为识别结果
        if content.has_text and content.text_char_count >= 20:
            regions = [r for r in content.text_blocks if r.text.strip()]
            plan.redact_text_layer = not content.text_visible
            # 文字层自带字号信息，直接用它当目标字号最准
            plan.box_height_factor = 0.72
            self._add_overlay_items(
                plan, stats,
                regions=[(r.text, r.confidence_hint, r.bbox) for r in regions],
                image_rect=(0.0, 0.0, content.width, content.height),
                image_size=(content.width, content.height),
                source="文字层",
                target_sizes=[r.font_size for r in regions],
            )
            return

        self._ensure_ocr()
        image_content = self.extractor.extract_page(content.page_num, with_images=True)
        ocr_source = self.extractor.best_ocr_image(image_content)
        if not ocr_source:
            return

        image_rect, image_size = self._ocr_source_geometry(image_content, ocr_source)
        results = self.ocr.recognize_file(ocr_source)
        if not results:
            return

        kept, dropped = self._filter_ocr(results, image_rect, image_size)
        stats["ocr_filtered"] += dropped

        # 查漏：第一遍 OCR 偶尔会整行漏检（实测能漏掉 2~3% 的正文墨迹），
        # 这里把「原图有墨、但没有任何识别区域覆盖」的行找出来补识别一次，
        # 否则这些日文会原样留在译文页上。
        recovered = self._recover_missed_regions(
            ocr_source, image_rect, image_size, kept
        )
        if recovered:
            stats["ocr_recovered"] = stats.get("ocr_recovered", 0) + len(recovered)
            kept = kept + recovered

        if not kept:
            return

        self._add_overlay_items(
            plan, stats,
            regions=[(r.text, r.confidence, r.bbox) for r in kept],
            image_rect=image_rect,
            image_size=image_size,
            source="OCR",
            target_sizes=self._measure_glyph_sizes(ocr_source, kept, image_rect, image_size),
        )
        self.ocr.save_cache()

    # ── 字号标定 ─────────────────────────────────────────

    def _recover_missed_regions(
        self,
        image_path: str,
        image_rect: Tuple[float, float, float, float],
        image_size: Tuple[int, int],
        kept: Sequence[OCRResult],
    ) -> List[OCRResult]:
        """
        找出「原图上有文字、但没被任何识别区域覆盖」的地方，补做一次 OCR。

        做法（不依赖连通域库，只做投影）：
          1. 生成墨迹掩码（自动判断深底浅字 / 浅底深字）
          2. 行投影切出行带，列投影把行带切成文字块
          3. 丢掉已被 kept 覆盖的块
          4. 对剩下的块裁剪 + 放大 2 倍重新识别，并用重叠度校验结果
             （避免识别到相邻行）
        """
        import numpy as np
        from PIL import Image

        img_w, img_h = image_size
        if img_w <= 0 or img_h <= 0:
            return []
        pt_per_px = (image_rect[2] - image_rect[0]) / img_w

        try:
            with Image.open(image_path) as im:
                gray = np.asarray(im.convert("L")).astype(np.int16)
        except Exception:
            return []

        # 1) 墨迹掩码：按整页亮度判断是「浅底深字」还是「深底浅字」
        median = float(np.median(gray))
        if median > 128:
            ink = gray < max(90.0, median * 0.62)
        else:
            ink = gray > min(190.0, median * 1.55)
        if ink.sum() == 0:
            return []

        # 2) 已覆盖区域
        covered = np.zeros_like(ink)
        for r in kept:
            x0, y0, x1, y1 = (int(round(v)) for v in r.bbox)
            pad = int(max(2, (y1 - y0) * 0.18))
            covered[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad] = True
        residual = ink & ~covered
        if residual.sum() < 60:
            return []

        candidates: List[Tuple[int, int, int, int]] = []
        row_ink = residual.any(axis=1)
        for y0, y1 in _runs(row_ink, gap=2):
            band = residual[y0:y1]
            col_ink = band.any(axis=0)
            for x0, x1 in _runs(col_ink, gap=max(2, int((y1 - y0) * 0.8))):
                bw, bh = x1 - x0, y1 - y0
                # 尺寸合理性：太小是噪点，太高多半是把整块图当成了文字
                if bw * pt_per_px < 4 or bh * pt_per_px < 3 or bh * pt_per_px > 40:
                    continue
                # 页边的细长竖条（页码标记）跳过
                if bh / max(1, bw) >= 3.0 and bw <= img_w * 0.06:
                    continue
                if (residual[y0:y1, x0:x1].sum()) < bw * bh * 0.02:
                    continue
                candidates.append((x0, y0, x1, y1))

        if not candidates:
            return []

        # 3) 裁剪 + 放大 + 重新识别
        recovered: List[OCRResult] = []
        try:
            with Image.open(image_path) as im:
                rgb = im.convert("RGB")
        except Exception:
            return []

        for (x0, y0, x1, y1) in candidates[:24]:
            pad = int(max(4, (y1 - y0) * 0.35))
            box = (max(0, x0 - pad), max(0, y0 - pad), min(img_w, x1 + pad), min(img_h, y1 + pad))
            crop = rgb.crop(box)
            if crop.width < 4 or crop.height < 4:
                continue
            crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
            try:
                got = self.ocr.recognize(crop, cache_key=None)
            except Exception:
                continue

            target = fitz.Rect(x0, y0, x1, y1)
            for item in got:
                # 结果映射回整页坐标（裁剪 + 2 倍放大）
                bx0 = box[0] + item.bbox[0] / 2
                by0 = box[1] + item.bbox[1] / 2
                bx1 = box[0] + item.bbox[2] / 2
                by1 = box[1] + item.bbox[3] / 2
                rect = fitz.Rect(bx0, by0, bx1, by1)
                # 重叠校验：结果必须主要落在这个候选块里（避免识别到邻行）
                inter = rect & target
                if inter.is_empty or inter.get_area() < 0.45 * max(1e-6, rect.get_area()):
                    continue
                text = (item.text or "").strip()
                if not text or not any(ch.isalnum() or _is_cjk_char(ch) for ch in text):
                    continue
                # 与首轮一致：极短 + 极低置信度 → 当噪声丢掉
                if (
                    len(text.replace(" ", "")) <= config.OCR_SHORT_TEXT_MAX_LEN
                    and item.confidence < config.OCR_MIN_CONFIDENCE
                ):
                    continue
                # 与已有区域（或本次已补区域）重合 → 跳过，避免同一行画两遍
                if _overlaps_any(rect, kept, recovered):
                    continue
                recovered.append(OCRResult(
                    text=text,
                    confidence=item.confidence,
                    bbox=(bx0, by0, bx1, by1),
                ))

        if recovered and self.verbose:
            self.reporter.log(f"  查漏补识别: {len(recovered)} 处漏检文字", "info")
        return recovered

    def _measure_glyph_sizes(
        self,
        image_path: str,
        regions: Sequence[OCRResult],
        image_rect: Tuple[float, float, float, float],
        image_size: Tuple[int, int],
    ) -> List[float]:
        """
        量出每个区域里「原文实际画了多少 pt 高的字」，换算成译文该用的字号。

        为什么要这么做：
          OCR 返回的框比字形本身高约 30%（含上下留白），直接按框高定字号，
          译文会比原文大 30% 左右 —— 行距没变，看起来就又挤又黑。
        """
        from modules.fonts import glyph_ink_ratio, get_font_path

        img_w, img_h = image_size
        if img_w <= 0 or img_h <= 0:
            return [0.0] * len(regions)
        scale = (image_rect[2] - image_rect[0]) / img_w      # 图片像素 → pt
        ratio = glyph_ink_ratio(get_font_path())

        ink_heights: List[float] = []
        try:
            from PIL import Image
            import numpy as np

            with Image.open(image_path) as im:
                gray = np.asarray(im.convert("L"))
        except Exception:
            return [0.0] * len(regions)

        per_region: List[float] = []
        for r in regions:
            x0, y0, x1, y1 = (int(round(v)) for v in r.bbox)
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(gray.shape[1], x1), min(gray.shape[0], y1)
            if x1 - x0 < 2 or y1 - y0 < 2:
                per_region.append(0.0)
                continue
            patch = gray[y0:y1, x0:x1]
            threshold = max(80, int(patch.min()) + int(0.35 * (int(patch.max()) - int(patch.min()))))
            ink_rows = (patch < threshold).any(axis=1)
            idx = ink_rows.nonzero()[0]
            if len(idx) < 2:
                per_region.append(0.0)
                continue
            ink_px = float(idx[-1] - idx[0] + 1)
            pt = ink_px * scale / ratio
            per_region.append(pt)
            ink_heights.append(pt)

        if not ink_heights:
            return [0.0] * len(regions)

        median = float(np.median(ink_heights))
        # 平滑：允许标题比正文大一些，但不允许离群值把版面撑乱
        return [
            min(max(v, median * 0.70), median * 1.60) if v > 0 else median
            for v in per_region
        ]

    def _add_overlay_items(
        self,
        plan: PagePlan,
        stats: Dict,
        regions: Sequence[Tuple[str, float, Tuple[float, float, float, float]]],
        image_rect: Tuple[float, float, float, float],
        image_size: Tuple[float, int],
        source: str,
        target_sizes: Optional[Sequence[float]] = None,
    ):
        """把文字区域批量翻译后加入改写计划"""
        if not regions:
            return
        translations = self.translator.translate_many([text for text, _, _ in regions])
        for i, ((text, confidence, bbox), translated) in enumerate(zip(regions, translations)):
            translated = (translated or "").strip()
            if not translated:
                continue
            plan.overlay_items.append(OverlayItem(
                image_bbox=tuple(float(v) for v in bbox),
                translated=translated,
                original=text,
                confidence=float(confidence),
                image_size=(int(image_size[0]), int(image_size[1])),
                image_rect=tuple(float(v) for v in image_rect),
                target_size=(target_sizes[i] if target_sizes and i < len(target_sizes) else 0.0),
            ))
        stats["ocr_regions"] += len(plan.overlay_items)
        if self.verbose:
            self.reporter.log(f"  第 {plan.page_num + 1} 页: {source} 文字区域 {len(regions)} 个", "info")

    # ── OCR 辅助 ─────────────────────────────────────────

    def _ensure_ocr(self) -> OCREngine:
        if self.ocr is None:
            self.reporter.log(
                f"检测到图片型页面，加载 OCR 引擎（{config.OCR_ENGINE}）...", "info", 10
            )
            self.ocr = create_ocr_engine(verbose=self.verbose)
        return self.ocr

    def _ocr_source_geometry(
        self, content: PageContent, ocr_source: str
    ) -> Tuple[Tuple[float, float, float, float], Tuple[int, int]]:
        """返回 OCR 图源覆盖的页面区域 和 图片像素尺寸"""
        largest = content.largest_image()
        if largest and largest.image_path == ocr_source and largest.image is not None:
            return tuple(largest.bbox), tuple(largest.image.size)

        from PIL import Image

        try:
            with Image.open(ocr_source) as img:
                size = img.size
        except Exception:
            size = (0, 0)
        return (0.0, 0.0, content.width, content.height), size

    def _filter_ocr(
        self,
        results: List[OCRResult],
        image_rect: Tuple[float, float, float, float],
        image_size: Tuple[int, int],
    ) -> Tuple[List[OCRResult], int]:
        """
        过滤明显无效的 OCR 区域。

        设计原则：**只丢弃「确定是垃圾」的区域，不按置信度一刀切**。
        EasyOCR 对复杂汉字的置信度普遍偏低（大量完全正确的文本只有 0.0~0.3），
        用阈值硬筛会丢掉整段正文，译文里就会残留日文。

        真正要丢的是：
          - 空文本 / 纯符号
          - 细长的竖条（扫描页边缘的页码标记，识别结果就是 "!" "1"）
          - 极短且极低置信度的碎片
        面积过小的区域同样忽略。
        """
        ix0, iy0, ix1, iy1 = image_rect
        img_w, img_h = image_size
        if img_w <= 0 or img_h <= 0:
            return [], len(results)

        scale_x = (ix1 - ix0) / img_w
        scale_y = (iy1 - iy0) / img_h

        kept: List[OCRResult] = []
        dropped = 0
        for r in results:
            text = r.text.strip()
            if not text:
                dropped += 1
                continue
            if not any(ch.isalnum() or _is_cjk_char(ch) for ch in text):
                dropped += 1
                continue

            bx0, by0, bx1, by1 = r.bbox
            bw = abs(bx1 - bx0)
            bh = abs(by1 - by0)

            # 细长竖条 = 页边页码/装饰条，识别出来基本是 "!" "1" 之类
            if bw > 0 and bh / bw >= 3.0 and bw <= img_w * 0.06:
                dropped += 1
                continue

            # 极短 + 极低置信度 = 噪声
            compact = text.replace(" ", "")
            if (
                len(compact) <= config.OCR_SHORT_TEXT_MAX_LEN
                and r.confidence < config.OCR_MIN_CONFIDENCE
            ):
                dropped += 1
                continue

            area = bw * scale_x * bh * scale_y
            if area < config.OCR_MIN_AREA_PT:
                dropped += 1
                continue
            kept.append(r)
        return kept, dropped

    # ── 自检 ─────────────────────────────────────────────

    def _verify_output(self, plans: Sequence[PagePlan]) -> Dict:
        """回读输出文件，确认每个计划区域里真的有文字"""
        checked = 0
        missing = 0
        per_page_missing: List[int] = []
        try:
            doc = fitz.open(self.output_path)
        except Exception as exc:
            return {"error": str(exc), "checked": 0, "missing": 0}

        for plan in plans:
            if plan.is_empty:
                continue
            page = doc[plan.page_num]
            spans = _page_span_rects(page)

            rects = [i.rect for i in plan.text_items]
            for item in plan.overlay_items:
                rect = _overlay_rect(item, plan)
                if rect is not None:
                    rects.append(rect)

            page_missing = 0
            for rect in rects:
                checked += 1
                if not any(rect.intersects(span) for span in spans):
                    missing += 1
                    page_missing += 1
            if page_missing:
                per_page_missing.append(plan.page_num + 1)

        doc.close()
        return {
            "checked": checked,
            "missing": missing,
            "missing_pages": per_page_missing[:20],
        }

    # ── 输出 ─────────────────────────────────────────────

    def _print_summary(self, gen_stats: GenerateStats, verify: Dict, elapsed: float):
        rep = self.reporter
        rep.log("", progress=100)
        rep.log(gen_stats.summary(), "success", 100)
        if verify.get("checked"):
            rep.log(
                f"自检: 检查 {verify['checked']} 处，未写入 {verify['missing']} 处",
                "success" if not verify.get("missing") else "warning",
                100,
            )
        if self.translator:
            st = self.translator.stats
            rep.log(
                f"翻译统计: API 请求 {st['api_calls']} 次 / 缓存命中 {st['cache_hit']} 条 / "
                f"失败 {st['failed']} 条 / 拒答 {st['refused']} 条",
                "info", 100,
            )
        rep.log(f"耗时: {format_duration(elapsed)}", "info", 100)
        rep.log(f"输出文件: {self.output_path}", "success", 100)

    def _progress_fn(self, low: int, high: int):
        def fn(done, total, desc):
            percent = low + int((high - low) * done / max(1, total))
            self._emit_progress(percent)
        return fn

    def _emit_progress(self, percent: int):
        if self.progress_callback:
            try:
                self.progress_callback(percent)
            except Exception:
                pass

    def _cancelled(self) -> bool:
        """留给 Web 层的取消钩子"""
        flag = getattr(self, "cancel_flag", None)
        return bool(flag and flag())


# ── 工具函数 ──────────────────────────────────────────────

def _is_cjk_char(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3040 <= code <= 0x30FF
        or 0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
    )


def _runs(flags, gap: int = 1):
    """把布尔序列切成连续 True 的区间，间隔小于 gap 的区间合并"""
    runs = []
    start = None
    last = None
    for i, v in enumerate(flags):
        if v:
            if start is None:
                start = i
            last = i
        elif start is not None and i - last > gap:
            runs.append((start, last + 1))
            start = None
    if start is not None:
        runs.append((start, last + 1))
    return runs


def _overlaps_any(
    rect: fitz.Rect,
    *groups: Sequence[OCRResult],
    threshold: float = 0.5,
) -> bool:
    """
    新区域是否与已有区域明显重合。

    用「交集 / 较小者面积」而不是 IoU：只要有一半以上被盖住就算重复，
    否则同一行的宽窄两次识别（例如 OCR 一次读到整行、一次只读到前半行）
    会被当成两个区域，译文重叠画两遍。
    """
    own_area = max(1e-6, rect.get_area())
    for group in groups:
        for item in group:
            other = fitz.Rect(*item.bbox)
            if not rect.intersects(other):
                continue
            inter = rect & other
            smaller = min(own_area, max(1e-6, other.get_area()))
            if inter.get_area() >= threshold * smaller:
                return True
    return False


def _page_span_rects(page: fitz.Page) -> List[fitz.Rect]:
    rects: List[fitz.Rect] = []
    try:
        data = page.get_text("dict")
    except Exception:
        return rects
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip() and span.get("bbox"):
                    rects.append(fitz.Rect(*span["bbox"]))
    return rects


def _overlay_rect(item: OverlayItem, plan: PagePlan) -> Optional[fitz.Rect]:
    ix0, iy0, ix1, iy1 = item.image_rect
    img_w, img_h = item.image_size
    if img_w <= 0 or img_h <= 0:
        return None
    sx = (ix1 - ix0) / img_w
    sy = (iy1 - iy0) / img_h
    bx0, by0, bx1, by1 = item.image_bbox
    return fitz.Rect(ix0 + bx0 * sx, iy0 + by0 * sy, ix0 + bx1 * sx, iy0 + by1 * sy)


# 兼容旧名字
JapanesePDFTranslator = PDFTranslator
