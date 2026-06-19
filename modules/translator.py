"""
翻译模块
支持多种翻译引擎：Google Translate、DeepSeek、OpenAI GPT、DeepL
"""

import os
import sys
import time
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import config


# ========== 日译中 通用 System Prompt ==========
JP_TO_CN_SYSTEM_PROMPT = """你是一个专业的日语翻译助手。请将以下日语文本翻译成简体中文。
要求：
1. 翻译准确、流畅、自然
2. 保留原文的格式和换行
3. 专业术语翻译准确
4. 只返回翻译结果，不要添加任何解释"""


class TranslationEngine:
    """翻译引擎基类"""

    def translate(self, text: str) -> str:
        raise NotImplementedError

    def translate_batch(self, texts: List[str], delay: float = 0.5) -> List[str]:
        """批量翻译，带延迟防止 API 限流"""
        results = []
        for i, text in enumerate(texts):
            if not text.strip():
                results.append(text)
                continue
            try:
                translated = self.translate(text)
                results.append(translated)
                if i < len(texts) - 1:
                    time.sleep(delay)
            except Exception as e:
                print(f"[翻译] 翻译失败: {text[:30]}... 错误: {e}")
                results.append(text)  # 失败时保留原文
        return results


class GoogleTranslateEngine(TranslationEngine):
    """Google 翻译引擎（免费）"""

    def __init__(self, source: str = "ja", target: str = "zh-CN"):
        from deep_translator import GoogleTranslator
        self.source = source
        self.target = target
        self.translator = GoogleTranslator(source=source, target=target)
        print(f"[翻译] 使用 Google 翻译 ({source} -> {target})")

    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        # deep_translator 对长文本会自动处理
        return self.translator.translate(text)


class DeepSeekTranslateEngine(TranslationEngine):
    """DeepSeek 翻译引擎（需要 API Key）
    
    API Key 获取: https://platform.deepseek.com/api_keys
    兼容 OpenAI SDK，只需修改 base_url 即可
    """

    def __init__(self, api_key: str = None, model: str = None):
        from openai import OpenAI
        self.api_key = api_key or config.DEEPSEEK_API_KEY
        if not self.api_key:
            raise ValueError(
                "请设置 DEEPSEEK_API_KEY 环境变量或在 .env 文件中配置\n"
                "获取 Key: https://platform.deepseek.com/api_keys"
            )
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.deepseek.com"  # DeepSeek API 地址
        )
        self.model = model or config.DEEPSEEK_MODEL
        print(f"[翻译] 使用 DeepSeek 翻译 (模型: {self.model})")

    def translate(self, text: str) -> str:
        if not text.strip():
            return text

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": JP_TO_CN_SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            temperature=0.3,
            max_tokens=4096
        )
        return response.choices[0].message.content.strip()


class OpenAITranslateEngine(TranslationEngine):
    """OpenAI GPT 翻译引擎（需要 API Key）"""

    def __init__(self, api_key: str = None, model: str = None):
        from openai import OpenAI
        self.api_key = api_key or config.OPENAI_API_KEY
        if not self.api_key:
            raise ValueError("请设置 OPENAI_API_KEY 环境变量或在 .env 文件中配置")
        self.client = OpenAI(api_key=self.api_key)
        self.model = model or config.OPENAI_MODEL
        print(f"[翻译] 使用 OpenAI GPT 翻译 (模型: {self.model})")

    def translate(self, text: str) -> str:
        if not text.strip():
            return text

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": JP_TO_CN_SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content.strip()


class DeepLTranslateEngine(TranslationEngine):
    """DeepL 翻译引擎（需要 API Key）"""

    def __init__(self, api_key: str = None, source: str = "JA", target: str = "ZH"):
        import deepl
        self.api_key = api_key or os.getenv("DEEPL_API_KEY", "")
        if not self.api_key:
            raise ValueError("请设置 DEEPL_API_KEY 环境变量或在 .env 文件中配置")
        self.translator = deepl.Translator(self.api_key)
        self.source = source
        self.target = target
        print(f"[翻译] 使用 DeepL 翻译 ({source} -> {target})")

    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        result = self.translator.translate_text(
            text,
            source_lang=self.source,
            target_lang=self.target
        )
        return result.text


def create_translation_engine() -> TranslationEngine:
    """工厂函数：根据配置创建翻译引擎"""
    engine_name = config.TRANSLATION_ENGINE.lower()

    if engine_name == "google":
        return GoogleTranslateEngine(
            source=config.SOURCE_LANG,
            target=config.TARGET_LANG
        )
    elif engine_name == "deepseek":
        return DeepSeekTranslateEngine()
    elif engine_name == "openai":
        return OpenAITranslateEngine()
    elif engine_name == "deepl":
        return DeepLTranslateEngine()
    else:
        raise ValueError(f"不支持的翻译引擎: {engine_name}")
