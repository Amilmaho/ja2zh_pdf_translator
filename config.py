"""
项目配置文件
支持多种翻译引擎和 OCR 引擎的配置
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """全局配置类"""

    # ========== 路径配置 ==========
    INPUT_DIR = os.path.join(os.path.dirname(__file__), "input")
    OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
    TEMP_DIR = os.path.join(os.path.dirname(__file__), "temp")

    # ========== 翻译配置 ==========
    # 翻译引擎: "google" | "deepseek" | "openai" | "deepl"
    TRANSLATION_ENGINE = "deepseek"

    # 源语言 & 目标语言
    SOURCE_LANG = "ja"       # 日语
    TARGET_LANG = "zh-CN"    # 简体中文

    # DeepSeek 配置 (当 TRANSLATION_ENGINE="deepseek" 时使用)
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_MODEL = "deepseek-chat"  # 或 deepseek-reasoner

    # OpenAI 配置 (当 TRANSLATION_ENGINE="openai" 时使用)
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL = "gpt-4o"

    # ========== OCR 配置 ==========
    # OCR 引擎: "easyocr" | "tesseract"
    OCR_ENGINE = "easyocr"

    # Tesseract 路径 (Windows/macOS 自适应)
    _TESSERACT_DEFAULT = {
        "darwin": "/opt/homebrew/bin/tesseract",  # Apple Silicon Mac
        "win32": r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        "linux": "/usr/bin/tesseract",
    }.get(os.uname().sysname.lower(), "tesseract")
    TESSERACT_CMD = os.getenv("TESSERACT_CMD", _TESSERACT_DEFAULT)

    # EasyOCR 语言列表 — 只设日文 (日文 PDF 只需识别日文)
    # 注意: EasyOCR 不支持 ja+ch_sim 混合使用，需单一语言
    OCR_LANGUAGES = ["ja"]

    # ========== PDF 输出配置 ==========
    # 中文字体路径 (跨平台自动检测)
    FONT_PATH = os.getenv("FONT_PATH", "")
    # 备用字体
    FONT_PATH_FALLBACK = ""

    # 页面大小 (A4)
    PAGE_WIDTH = 595
    PAGE_HEIGHT = 842

    # ========== 调试配置 ==========
    DEBUG = False
    SAVE_INTERMEDIATE = True  # 是否保存中间结果（提取的图片等）


config = Config()
