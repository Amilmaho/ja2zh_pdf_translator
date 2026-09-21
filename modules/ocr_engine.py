"""
OCR 模块（重构版）
识别图片中的日文文字，支持 EasyOCR / Tesseract 两种引擎。

相比旧版的改进：
  1. GPU 自动探测：没有 CUDA 时不再报错，直接退回 CPU（并打印提示）
  2. 密集文本调参：表格/漫画页断行更少，识别更完整
  3. 结果缓存：同一张图片不重复识别，支持断点续跑
  4. 统一 recognize_file / recognize 接口，返回带置信度的区域列表
"""

import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config
from modules.utils import file_fingerprint


# ── 数据结构 ──────────────────────────────────────────────

@dataclass
class OCRResult:
    """OCR 识别结果"""
    text: str
    confidence: float
    bbox: Tuple[float, float, float, float]  # 图片像素坐标 (x0, y0, x1, y1)

    def to_dict(self) -> dict:
        return {"text": self.text, "confidence": self.confidence, "bbox": list(self.bbox)}

    @classmethod
    def from_dict(cls, data: dict) -> "OCRResult":
        bbox = data.get("bbox") or (0, 0, 0, 0)
        return cls(
            text=data.get("text", ""),
            confidence=float(data.get("confidence", 0.0)),
            bbox=tuple(float(v) for v in bbox),
        )


def _preprocess(image: Image.Image, upscale: float = 1.0) -> Image.Image:
    """OCR 前的轻量预处理：统一 RGB，可选放大"""
    if image.mode != "RGB":
        image = image.convert("RGB")
    if upscale and upscale > 1.01:
        new_size = (max(1, int(image.width * upscale)), max(1, int(image.height * upscale)))
        image = image.resize(new_size, Image.LANCZOS)
    return image


def _resolve_gpu(setting: str) -> bool:
    """把 auto/on/off 解析成是否使用 GPU"""
    setting = (setting or "auto").strip().lower()
    if setting in ("on", "true", "1", "yes"):
        return True
    if setting in ("off", "false", "0", "no"):
        return False
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


# ── 引擎基类 ──────────────────────────────────────────────

class OCREngine:
    """OCR 引擎基类：负责缓存与统一入口"""

    name = "base"

    def __init__(self, use_cache: bool = None):
        self.use_cache = config.OCR_CACHE if use_cache is None else use_cache
        self._cache_dir = os.path.join(config.CACHE_DIR, "ocr")
        self._cache: Dict[str, List[OCRResult]] = {}
        self._cache_dirty = False
        if self.use_cache:
            os.makedirs(self._cache_dir, exist_ok=True)
            self._load_cache()

    # -- 缓存 --

    def _cache_file(self) -> str:
        return os.path.join(self._cache_dir, f"{self.name}.json")

    def _load_cache(self):
        path = self._cache_file()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self._cache = {
                key: [OCRResult.from_dict(d) for d in items] for key, items in raw.items()
            }
        except Exception:
            self._cache = {}

    def save_cache(self):
        if not (self.use_cache and self._cache_dirty):
            return
        try:
            os.makedirs(self._cache_dir, exist_ok=True)
            with open(self._cache_file(), "w", encoding="utf-8") as f:
                json.dump(
                    {k: [r.to_dict() for r in v] for k, v in self._cache.items()},
                    f, ensure_ascii=False,
                )
            self._cache_dirty = False
        except Exception:
            pass

    # -- 子类实现 --

    def _recognize_image(self, image: Image.Image) -> List[OCRResult]:
        raise NotImplementedError

    # -- 对外接口 --

    def recognize(self, image: Image.Image, cache_key: str = None) -> List[OCRResult]:
        """识别一张 PIL 图片"""
        if cache_key and self.use_cache and cache_key in self._cache:
            return self._cache[cache_key]

        results = self._recognize_image(_preprocess(image, config.OCR_UPSCALE))

        if cache_key and self.use_cache:
            self._cache[cache_key] = results
            self._cache_dirty = True
        return results

    def recognize_file(self, image_path: str) -> List[OCRResult]:
        """识别一个图片文件（带缓存）"""
        cache_key = None
        if self.use_cache:
            cache_key = file_fingerprint(image_path, extra=f"{self.name}:{'+'.join(config.OCR_LANGUAGES)}")
            if cache_key in self._cache:
                return self._cache[cache_key]

        with Image.open(image_path) as img:
            results = self._recognize_image(_preprocess(img, config.OCR_UPSCALE))

        if cache_key:
            self._cache[cache_key] = results
            self._cache_dirty = True
        return results


# ── EasyOCR ───────────────────────────────────────────────

class EasyOCREngine(OCREngine):
    """EasyOCR — 日文句子级识别，效果优于 Tesseract"""

    name = "easyocr"

    MODEL_STORAGE_DIR = os.path.join(os.path.expanduser("~"), ".EasyOCR", "model")

    def __init__(
        self,
        languages: List[str] = None,
        gpu: str = None,
        max_retries: int = 3,
        retry_delay: float = 3.0,
        use_cache: bool = None,
        verbose: bool = True,
    ):
        super().__init__(use_cache=use_cache)
        import easyocr

        self.languages = languages or config.OCR_LANGUAGES
        self.use_gpu = _resolve_gpu(gpu if gpu is not None else config.OCR_GPU)
        self.verbose = verbose

        def say(msg: str):
            if self.verbose:
                print(msg, flush=True)

        say(f"[OCR] 加载 EasyOCR 模型 (语言: {self.languages}, "
            f"设备: {'GPU' if self.use_gpu else 'CPU'})")
        if not self.use_gpu:
            say("[OCR] 未检测到可用 CUDA GPU，使用 CPU（速度较慢，可用 --pages 缩小范围）")

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                self.reader = easyocr.Reader(
                    self.languages,
                    gpu=self.use_gpu,
                    model_storage_directory=self.MODEL_STORAGE_DIR,
                    download_enabled=True,
                    verbose=False,
                )
                break
            except Exception as exc:
                last_error = exc
                if attempt >= max_retries:
                    raise RuntimeError(
                        f"EasyOCR 模型加载失败（已重试 {max_retries} 次）: {exc}\n"
                        f"请检查网络，或手动把模型放到: {self.MODEL_STORAGE_DIR}\n"
                        "也可改用 Tesseract: python main.py <file> --ocr tesseract"
                    ) from exc
                wait = retry_delay * (2 ** (attempt - 1))
                say(f"[OCR] 模型加载失败 (第 {attempt}/{max_retries} 次): {exc}，{wait:.0f} 秒后重试")
                self._clean_partial_downloads()
                time.sleep(wait)

        say("[OCR] EasyOCR 就绪")

    def _clean_partial_downloads(self):
        """清理未下载完成的临时文件，避免下次下载冲突"""
        if not os.path.exists(self.MODEL_STORAGE_DIR):
            return
        for fname in os.listdir(self.MODEL_STORAGE_DIR):
            if not fname.endswith((".zip", ".temp")):
                continue
            fpath = os.path.join(self.MODEL_STORAGE_DIR, fname)
            try:
                if os.path.getsize(fpath) < 1024 * 1024:
                    os.remove(fpath)
            except OSError:
                pass

    def _recognize_image(self, image: Image.Image) -> List[OCRResult]:
        import numpy as np

        raw = self.reader.readtext(
            np.array(image),
            detail=1,
            paragraph=False,
            # 密集排版（表格 / 漫画）调参：提高召回、减少断行
            text_threshold=0.6,
            low_text=0.3,
            link_threshold=0.4,
            canvas_size=2560,
            mag_ratio=1.0,
            width_ths=0.6,
            add_margin=0.05,
        )

        results: List[OCRResult] = []
        for bbox, text, confidence in raw:
            text = (text or "").strip()
            if not text:
                continue
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            results.append(OCRResult(
                text=text,
                confidence=float(confidence),
                bbox=(float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))),
            ))
        return results


# ── Tesseract ─────────────────────────────────────────────

class TesseractEngine(OCREngine):
    """Tesseract — 单字级识别，CPU 速度快，适合纯文字扫描件"""

    name = "tesseract"

    _COMMON_TESSDATA_PATHS = [
        "/opt/homebrew/share/tessdata",
        "/usr/local/share/tessdata",
        r"C:\Program Files\Tesseract-OCR\tessdata",
        r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "Programs",
                     "Tesseract-OCR", "tessdata"),
        "/usr/share/tesseract-ocr/5/tessdata",
        "/usr/share/tesseract-ocr/4.00/tessdata",
        "/usr/share/tessdata",
    ]

    def __init__(self, lang: str = "jpn", use_cache: bool = None, verbose: bool = True):
        super().__init__(use_cache=use_cache)
        import pytesseract

        self.verbose = verbose

        def say(msg: str):
            if verbose:
                print(msg, flush=True)

        if config.TESSERACT_CMD:
            if os.path.exists(config.TESSERACT_CMD) or shutil.which(config.TESSERACT_CMD):
                pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD

        tessdata_dir = self._find_tessdata()
        if tessdata_dir:
            os.environ["TESSDATA_PREFIX"] = tessdata_dir

        if not self._find_lang_file(f"{lang}.traineddata", tessdata_dir):
            if self._find_lang_file("jpn_vert.traineddata", tessdata_dir):
                say("[OCR] 未找到 jpn.traineddata，回退使用 jpn_vert")
                lang = "jpn_vert"
            else:
                raise RuntimeError(
                    "Tesseract 缺少日语语言包 (jpn.traineddata)。\n"
                    "  macOS: brew install tesseract-lang\n"
                    "  或手动下载放到: "
                    f"{tessdata_dir or '/opt/homebrew/share/tessdata'}\n"
                    "  下载地址: https://github.com/tesseract-ocr/tessdata/raw/main/jpn.traineddata"
                )

        self.lang = lang
        say(f"[OCR] 使用 Tesseract (语言: {self.lang})")

    def _find_tessdata(self) -> Optional[str]:
        env_prefix = os.environ.get("TESSDATA_PREFIX", "")
        if env_prefix and os.path.isdir(env_prefix):
            return env_prefix
        if config.TESSERACT_CMD and os.path.exists(config.TESSERACT_CMD):
            candidate = os.path.join(os.path.dirname(config.TESSERACT_CMD), "tessdata")
            if os.path.isdir(candidate):
                return candidate
        for path in self._COMMON_TESSDATA_PATHS:
            if os.path.isdir(path):
                return path
        return None

    def _find_lang_file(self, filename: str, tessdata_dir: Optional[str] = None) -> Optional[str]:
        search_dirs = [tessdata_dir] if tessdata_dir else []
        search_dirs.extend(self._COMMON_TESSDATA_PATHS)
        for d in search_dirs:
            if d and os.path.exists(os.path.join(d, filename)):
                return os.path.join(d, filename)
        return None

    def _recognize_image(self, image: Image.Image) -> List[OCRResult]:
        import pytesseract

        data = pytesseract.image_to_data(
            image, lang=self.lang, output_type=pytesseract.Output.DICT
        )
        results: List[OCRResult] = []
        for i in range(len(data["text"])):
            text = (data["text"][i] or "").strip()
            if not text:
                continue
            try:
                conf = float(data["conf"][i]) / 100.0
            except (TypeError, ValueError):
                conf = 0.0
            if conf < 0:
                continue
            x, y, w, h = (data["left"][i], data["top"][i], data["width"][i], data["height"][i])
            results.append(OCRResult(
                text=text, confidence=conf, bbox=(float(x), float(y), float(x + w), float(y + h))
            ))
        return results


def create_ocr_engine(engine_name: str = None, verbose: bool = True) -> OCREngine:
    """工厂函数：根据配置创建 OCR 引擎"""
    name = (engine_name or config.OCR_ENGINE).lower()
    if name == "easyocr":
        return EasyOCREngine(verbose=verbose)
    if name == "tesseract":
        return TesseractEngine(verbose=verbose)
    raise ValueError(f"不支持的 OCR 引擎: {name}（可选: easyocr | tesseract）")
