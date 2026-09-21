"""
项目全局配置（重构版）
支持多种翻译引擎和 OCR 引擎的配置。

设计原则：
  - 全平台可用（不再依赖 os.uname()，Windows 也能正常启动）
  - 所有可调参数集中在这里，各模块只读不写
  - 分区清晰：路径 / 翻译 / OCR / 渲染 / 调试
"""

import os
import platform

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_SYSTEM = platform.system().lower()  # darwin / windows / linux


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _default_tesseract() -> str:
    """按平台给出 tesseract 默认路径（找不到就交给 PATH）"""
    candidates = {
        "darwin": [
            "/opt/homebrew/bin/tesseract",
            "/usr/local/bin/tesseract",
        ],
        "windows": [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ],
        "linux": ["/usr/bin/tesseract", "/usr/local/bin/tesseract"],
    }.get(_SYSTEM, [])
    for path in candidates:
        if os.path.exists(path):
            return path
    return "tesseract"


class Config:
    """全局配置类"""

    # ========== 路径配置 ==========
    BASE_DIR = BASE_DIR
    INPUT_DIR = os.path.join(BASE_DIR, "input")
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")
    TEMP_DIR = os.path.join(BASE_DIR, "temp")
    CACHE_DIR = os.path.join(BASE_DIR, ".cache")

    # ========== 翻译配置 ==========
    # 翻译引擎: "deepseek" | "google" | "openai" | "deepl" | "dummy"（离线测试用）
    TRANSLATION_ENGINE = os.getenv("TRANSLATION_ENGINE", "deepseek")

    SOURCE_LANG = "ja"       # 日语
    TARGET_LANG = "zh-CN"    # 简体中文

    # DeepSeek
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    # OpenAI
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

    # 批量翻译：一次 API 请求翻译多条文本，显著减少调用次数和等待时间
    TRANSLATION_BATCH_SIZE = int(os.getenv("TRANSLATION_BATCH_SIZE", "12"))
    # 批量请求的总字符上限（超过就拆成多批）
    TRANSLATION_BATCH_MAX_CHARS = int(os.getenv("TRANSLATION_BATCH_MAX_CHARS", "1500"))
    # 单条文本超过该长度时单独翻译（避免上下文互相干扰）
    TRANSLATION_SINGLE_MAX_CHARS = int(os.getenv("TRANSLATION_SINGLE_MAX_CHARS", "800"))
    TRANSLATION_TIMEOUT = float(os.getenv("TRANSLATION_TIMEOUT", "120"))
    TRANSLATION_MAX_RETRIES = int(os.getenv("TRANSLATION_MAX_RETRIES", "3"))
    # 翻译缓存：相同原文不重复调用 API，可断点续跑
    TRANSLATION_CACHE = _env_bool("TRANSLATION_CACHE", True)

    # ========== OCR 配置 ==========
    # OCR 引擎: "easyocr" | "tesseract"
    OCR_ENGINE = os.getenv("OCR_ENGINE", "easyocr")

    # EasyOCR 语言列表 — 只设日文（EasyOCR 不支持 ja + ch_sim 混用）
    OCR_LANGUAGES = ["ja"]

    # 置信度下限：**只用来过滤极短噪声**，不是「低于它就丢弃」。
    # EasyOCR 对复杂汉字的置信度天然偏低（实测大量完全正确的文本只有 0.0~0.3），
    # 早先按 0.30 一刀切，会丢掉 20% 的正文，导致译图里残留大片日文。
    OCR_MIN_CONFIDENCE = float(os.getenv("OCR_MIN_CONFIDENCE", "0.15"))
    # 低于该置信度时，只有「短到没有信息量」的区域才丢弃
    OCR_SHORT_TEXT_MAX_LEN = int(os.getenv("OCR_SHORT_TEXT_MAX_LEN", "3"))
    # 识别区域过小（面积小于该值，单位 pt²）直接忽略
    OCR_MIN_AREA_PT = float(os.getenv("OCR_MIN_AREA_PT", "10.0"))

    # GPU: "auto" | "on" | "off"
    OCR_GPU = os.getenv("OCR_GPU", "auto")

    # 页面由多个小图拼成时，把整页渲染成图片再做 OCR 的 DPI
    PDF_RENDER_DPI = int(os.getenv("PDF_RENDER_DPI", "200"))
    # OCR 前的图像放大倍数（小字模糊时可调到 1.5）
    OCR_UPSCALE = float(os.getenv("OCR_UPSCALE", "1.0"))
    # OCR 缓存：同一张图片不重复识别
    OCR_CACHE = _env_bool("OCR_CACHE", True)

    # Tesseract 路径（Windows/macOS 自适应）
    TESSERACT_CMD = os.getenv("TESSERACT_CMD", _default_tesseract())

    # ========== PDF 输出配置 ==========
    # 中文字体路径（留空则自动检测）
    FONT_PATH = os.getenv("FONT_PATH", "")
    FONT_PATH_FALLBACK = ""
    # 自动选择字体时的风格偏好: serif（宋体/明朝体，贴近日文印刷品）| sans（黑体）
    FONT_STYLE = os.getenv("FONT_STYLE", "serif")

    # 覆盖原文字时的底色: "sample"（取自原图，推荐）| "white"
    OVERLAY_FILL_MODE = os.getenv("OVERLAY_FILL_MODE", "sample")
    # 译文颜色: "auto"（按底色自动取黑/白）| "black" | "white"
    OVERLAY_TEXT_COLOR = os.getenv("OVERLAY_TEXT_COLOR", "auto")
    # 译文允许的字号范围（pt）
    # 日文 PDF 页面本身可能很小（例如 4.6 英寸阅读器页面），原文只有 3~4pt，
    # 所以下限要给到位，否则大量区域会因为「放不下」而保留原文。
    OVERLAY_MIN_FONT = float(os.getenv("OVERLAY_MIN_FONT", "3.0"))
    OVERLAY_MAX_FONT = float(os.getenv("OVERLAY_MAX_FONT", "16.0"))
    # 文字放不下时，是否允许把文本框向「空白处」扩展。
    # 默认关闭：密集表格/漫画里扩展会盖到相邻行，宁可把字号缩小一点。
    OVERLAY_EXPAND = _env_bool("OVERLAY_EXPAND", False)

    # DOCX 内嵌图片是否做 OCR + 重绘（默认关闭：会改动文档内的图片资源）
    OVERLAY_TRANSLATE_DOCX_IMAGES = _env_bool("DOCX_TRANSLATE_IMAGES", False)

    # 页面大小 (A4) — 仅用于从零重建页面的兜底路径
    PAGE_WIDTH = 595
    PAGE_HEIGHT = 842

    # ========== 调试配置 ==========
    DEBUG = _env_bool("DEBUG", False)
    SAVE_INTERMEDIATE = _env_bool("SAVE_INTERMEDIATE", True)


config = Config()
