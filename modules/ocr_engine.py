"""
OCR 光学字符识别模块
用于识别图片中的日文文字，支持 EasyOCR 和 Tesseract 两种引擎

EasyOCR 模型下载问题解决：
  1. 自动重试（最多 5 次，指数退避）
  2. 支持设置镜像源 / 本地模型目录
  3. 手动下载指引
"""

import os
import sys
import time
import shutil
from PIL import Image
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import config


@dataclass
class OCRResult:
    """OCR 识别结果"""
    text: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # 图片内的坐标


class OCREngine:
    """OCR 引擎基类"""

    def recognize(self, image: Image.Image) -> List[OCRResult]:
        raise NotImplementedError

    def recognize_file(self, image_path: str) -> List[OCRResult]:
        image = Image.open(image_path)
        return self.recognize(image)


class EasyOCREngine(OCREngine):
    """EasyOCR 引擎 - 对日文识别效果好，支持自动重试下载"""

    # 模型下载镜像（国内用户可替换为加速地址）
    # 默认从官方 GitHub 下载，网络不好时会自动重试
    MODEL_STORAGE_DIR = os.path.join(
        os.path.expanduser("~"), ".EasyOCR", "model"
    )

    def __init__(
        self,
        languages: List[str] = None,
        gpu: bool = True,
        max_retries: int = 5,
        retry_delay: float = 3.0
    ):
        import easyocr
        self.languages = languages or config.OCR_LANGUAGES

        print(f"[OCR] 正在加载 EasyOCR 模型 (语言: {self.languages})...")
        print(f"[OCR] 模型存储目录: {self.MODEL_STORAGE_DIR}")
        print(f"[OCR] 如网络不畅，可手动下载模型放到上述目录")

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                self.reader = easyocr.Reader(
                    self.languages,
                    gpu=gpu,
                    model_storage_directory=self.MODEL_STORAGE_DIR,
                    download_enabled=True,
                )
                print("[OCR] EasyOCR 模型加载完成")
                return  # 成功，退出
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    wait = retry_delay * (2 ** (attempt - 1))  # 指数退避
                    print(f"\n[OCR] 模型下载失败 (第 {attempt}/{max_retries} 次): {e}")
                    print(f"[OCR] {wait:.0f} 秒后重试...")
                    self._clean_partial_downloads()
                    time.sleep(wait)
                else:
                    print(f"\n[OCR] 模型下载 {max_retries} 次均失败")

        # 所有重试都失败，给出帮助信息
        raise RuntimeError(
            f"EasyOCR 模型下载失败，已重试 {max_retries} 次。\n"
            f"错误原因: {last_error}\n\n"
            "请尝试以下方法:\n"
            "  1. 检查网络连接，重试运行\n"
            f"  2. 手动下载模型文件放到: {self.MODEL_STORAGE_DIR}\n"
            "     下载地址见: https://github.com/JaidedAI/EasyOCR/blob/master/easyocr/reader.py\n"
            "  3. 切换到 Tesseract OCR: 先安装 Tesseract，再运行\n"
            "     python main.py input.pdf --ocr tesseract\n"
        )

    def _clean_partial_downloads(self):
        """清理未下载完成的临时文件，避免下次下载冲突"""
        if not os.path.exists(self.MODEL_STORAGE_DIR):
            return
        for fname in os.listdir(self.MODEL_STORAGE_DIR):
            # EasyOCR 下载时会生成 .zip 和 .temp 文件
            if fname.endswith((".zip", ".temp", ".pth")):
                fpath = os.path.join(self.MODEL_STORAGE_DIR, fname)
                # 检查文件大小是否异常（小于 1MB 的 .pth 可能是损坏的）
                try:
                    size = os.path.getsize(fpath)
                    if size < 1024 * 1024:  # < 1MB
                        os.remove(fpath)
                        print(f"[OCR] 已清理损坏文件: {fname}")
                except OSError:
                    pass

    def recognize(self, image: Image.Image) -> List[OCRResult]:
        """识别图片中的文字"""
        import numpy as np

        img_array = np.array(image)
        raw_results = self.reader.readtext(img_array)

        results = []
        for bbox, text, confidence in raw_results:
            # bbox 是四个角的坐标 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            x_min = min(p[0] for p in bbox)
            y_min = min(p[1] for p in bbox)
            x_max = max(p[0] for p in bbox)
            y_max = max(p[1] for p in bbox)

            results.append(OCRResult(
                text=text,
                confidence=confidence,
                bbox=(int(x_min), int(y_min), int(x_max), int(y_max))
            ))

        return results


class TesseractEngine(OCREngine):
    """Tesseract OCR 引擎 — 自动检测语言包，缺失时给出清晰指引"""

    # 常见 tessdata 路径 (跨平台)
    _COMMON_TESSDATA_PATHS = [
        # macOS (Homebrew)
        "/opt/homebrew/share/tessdata",
        "/usr/local/share/tessdata",
        "/opt/homebrew/Cellar/tesseract",
        # Windows
        r"C:\Program Files\Tesseract-OCR\tessdata",
        r"C:\Program Files (x86)\Tesseract-OCR\tessdata",
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "Programs", "Tesseract-OCR", "tessdata"),
        # Linux
        "/usr/share/tesseract-ocr/4.00/tessdata",
        "/usr/share/tesseract-ocr/5/tessdata",
        "/usr/share/tessdata",
    ]

    def __init__(self, lang: str = "jpn"):
        import pytesseract

        # 设置 tesseract 可执行文件路径
        if config.TESSERACT_CMD and os.path.exists(config.TESSERACT_CMD):
            pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD

        # 自动检测并设置 TESSDATA_PREFIX
        tessdata_dir = self._find_tessdata()
        if tessdata_dir:
            os.environ["TESSDATA_PREFIX"] = tessdata_dir
            print(f"[OCR] TESSDATA_PREFIX = {tessdata_dir}")

        # 检测语言包是否存在
        lang_file = f"{lang}.traineddata"
        lang_path = self._find_lang_file(lang_file, tessdata_dir)
        if not lang_path:
            # 尝试回退到日语垂直排版
            alt_lang = "jpn_vert"
            alt_path = self._find_lang_file(f"{alt_lang}.traineddata", tessdata_dir)
            if alt_path:
                lang = alt_lang
                print(f"[OCR] jpn.traineddata 未找到，回退使用 {alt_lang}")
            else:
                raise RuntimeError(
                    f"Tesseract 缺少日语语言包 ({lang_file})。\n\n"
                    "请执行以下步骤:\n"
                    "  macOS: brew install tesseract-lang\n"
                    "  或手动下载:\n"
                    f"    1. 下载: https://github.com/tesseract-ocr/tessdata/raw/main/jpn.traineddata\n"
                    f"    2. 放到: {tessdata_dir or '/opt/homebrew/share/tessdata'}\n"
                    "    3. 重新运行程序\n\n"
                    "或切换到 EasyOCR:\n"
                    "  python main.py input.pdf --ocr easyocr"
                )

        self.lang = lang
        print(f"[OCR] 使用 Tesseract 引擎 (语言: {self.lang})")

    def _find_tessdata(self) -> str:
        """查找 tessdata 目录"""
        # 1. 检查环境变量
        env_prefix = os.environ.get("TESSDATA_PREFIX", "")
        if env_prefix and os.path.isdir(env_prefix):
            return env_prefix

        # 2. 从 tesseract 路径推导
        if config.TESSERACT_CMD and os.path.exists(config.TESSERACT_CMD):
            parent = os.path.dirname(config.TESSERACT_CMD)
            candidate = os.path.join(parent, "tessdata")
            if os.path.isdir(candidate):
                return candidate

        # 3. 检查常见安装路径
        for p in self._COMMON_TESSDATA_PATHS:
            if os.path.isdir(p):
                return p

        return None

    def _find_lang_file(self, filename: str, tessdata_dir: str = None) -> str:
        """查找语言文件"""
        search_dirs = [tessdata_dir] if tessdata_dir else []
        search_dirs.extend(self._COMMON_TESSDATA_PATHS)

        for d in search_dirs:
            full = os.path.join(d, filename)
            if os.path.exists(full):
                return full
        return None

    def recognize(self, image: Image.Image) -> List[OCRResult]:
        import pytesseract

        # 获取详细 OCR 数据
        data = pytesseract.image_to_data(
            image,
            lang=self.lang,
            output_type=pytesseract.Output.DICT
        )

        results = []
        for i in range(len(data["text"])):
            text = data["text"][i].strip()
            if text:
                conf = int(data["conf"][i]) / 100.0
                x, y, w, h = (
                    data["left"][i],
                    data["top"][i],
                    data["width"][i],
                    data["height"][i]
                )
                results.append(OCRResult(
                    text=text,
                    confidence=conf,
                    bbox=(x, y, x + w, y + h)
                ))

        return results


def create_ocr_engine() -> OCREngine:
    """工厂函数：根据配置创建 OCR 引擎"""
    engine_name = config.OCR_ENGINE.lower()

    if engine_name == "easyocr":
        return EasyOCREngine()
    elif engine_name == "tesseract":
        return TesseractEngine()
    else:
        raise ValueError(f"不支持的 OCR 引擎: {engine_name}")
