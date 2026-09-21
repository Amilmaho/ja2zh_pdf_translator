"""
翻译模块（重构版）
支持 DeepSeek / Google / OpenAI / DeepL / Dummy(离线测试)。

相比旧版的改进：
  1. 批量翻译：一次 API 请求翻译多条文本（OCR 一页可能有 200+ 条），
     调用次数和总耗时下降一个数量级。
  2. 翻译缓存：相同原文只调用一次 API，中断后可续跑，重复运行几乎零成本。
  3. 失败重试 + 单条兜底：批量解析失败会自动退回逐条翻译。
  4. 拒答检测：模型说「请提供需要翻译的内容」时自动换 prompt 重试，
     仍失败则保留原文，绝不写入空洞译文。
"""

import json
import os
import re
import sys
import time
from typing import Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config
from modules.utils import short_hash


# ── Prompt ────────────────────────────────────────────────

JP_TO_CN_SYSTEM_PROMPT = (
    "你是一个专业的日语翻译引擎。请把用户给出的日语文本翻译成简体中文。\n"
    "要求：\n"
    "1. 译文准确、流畅、自然\n"
    "2. 保留原文的换行和数字/符号\n"
    "3. 人名、地名等专有名词按中文习惯音译或保留原汉字\n"
    "4. 只输出译文本身，不要添加任何解释、引号或前后缀\n"
    "5. 译文必须是简体中文，绝对不能出现平假名或片假名；"
    "片假名外来语要音译成中文（例如 サンサーラ→娑婆罗、チート→作弊能力）"
)

BATCH_SYSTEM_PROMPT = (
    "你是一个日语→简体中文的批量翻译引擎。用户会给出若干条带编号的日语文本，"
    "请逐条翻译成简体中文。\n"
    "输出格式必须严格遵守：每条一行，写作 <<<编号>>>译文\n"
    "规则：\n"
    "1. 编号必须与输入一一对应，不能合并、不能遗漏、不能新增\n"
    "2. 只输出 <<<编号>>>译文，不要输出原文、序号说明或任何解释\n"
    "3. 即使是表格单元格、标题、页码等碎片，也要给出对应中文\n"
    "4. 数字、符号、单位、换行保持原样\n"
    "5. 译文必须是简体中文，绝对不能混入平假名或片假名；"
    "外来语要音译（例如 サンサーラ→娑婆罗、チート→作弊能力）\n"
    "示例输入：\n<<<0>>>こんにちは\n<<<1>>>名前決定表\n"
    "示例输出：\n<<<0>>>你好\n<<<1>>>姓名决定表"
)

# 需要重译的「残留假名」：排除 ・（间隔号）这类中文里也能用的符号
_KANA_RE = re.compile(r"[\u3041-\u309f\u30a1-\u30fa]")


def contains_kana(text: str) -> bool:
    """译文里是否还残留日文假名"""
    return bool(text) and bool(_KANA_RE.search(text))

# 模型「拒答」时出现的说法（说明它没把内容当成待翻译文本）
_REFUSAL_MARKERS = (
    "您似乎没有提供",
    "你似乎没有提供",
    "请提供需要翻译",
    "请提供具体的",
    "您没有提供任何",
    "你没有提供任何",
    "没有提供需要翻译",
    "请提供要翻译",
)

_MARKER_RE = re.compile(r"<<<\s*(\d+)\s*>>>")


def _is_refusal(text: str) -> bool:
    if not text:
        return False
    return any(marker in text for marker in _REFUSAL_MARKERS)


# ── 基类 ──────────────────────────────────────────────────

NO_KANA_INSTRUCTION = (
    "\n\n【硬性约束】上一次的译文里残留了日文假名，这次请务必改写：\n"
    "译文中不得出现任何平假名或片假名，外来语一律音译成中文。\n"
    "例如：サンサーラ→娑婆罗、チート→作弊能力、カルマ→业力、イラ→伊拉。\n"
    "只输出改写后的简体中文译文。"
)


class TranslationEngine:
    """翻译引擎基类：提供缓存、批量调度、重试与兜底"""

    name = "base"
    supports_batch = False

    def __init__(self, use_cache: bool = None, verbose: bool = True):
        self.verbose = verbose
        self.use_cache = config.TRANSLATION_CACHE if use_cache is None else use_cache
        self._cache: Dict[str, str] = {}
        self._cache_dirty = False
        self._cache_path = os.path.join(config.CACHE_DIR, "translate", f"{self.name}.json")
        self.stats = {"cache_hit": 0, "api_calls": 0, "failed": 0, "refused": 0}
        if self.use_cache:
            self._load_cache()

    def _say(self, message: str):
        if self.verbose:
            print(f"  {message}", flush=True)

    # -- 缓存 --

    def _cache_key(self, text: str) -> str:
        return short_hash(f"{self.name}|{config.SOURCE_LANG}|{config.TARGET_LANG}|{text}", 24)

    def _load_cache(self):
        if not os.path.exists(self._cache_path):
            return
        try:
            with open(self._cache_path, "r", encoding="utf-8") as f:
                self._cache = json.load(f)
        except Exception:
            self._cache = {}

    def save_cache(self):
        if not (self.use_cache and self._cache_dirty):
            return
        try:
            os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
            tmp = self._cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False)
            os.replace(tmp, self._cache_path)
            self._cache_dirty = False
        except Exception:
            pass

    # -- 子类实现 --

    def translate(self, text: str) -> str:
        raise NotImplementedError

    def translate_batch(self, texts: List[str]) -> List[str]:
        """默认实现：逐条翻译（支持批量的引擎会覆盖它）"""
        return [self.translate(t) if t.strip() else t for t in texts]

    # -- 对外主接口 --

    def translate_many(
        self,
        texts: List[str],
        progress: Callable = None,
        desc: str = "翻译",
    ) -> List[str]:
        """
        翻译一批文本，返回值与输入等长、顺序一致。
        空文本原样返回；失败/拒答的条目保留原文（绝不返回空串）。
        """
        results: List[str] = [""] * len(texts)

        # 1) 空文本直接透传，去重后收集需要翻译的
        pending: List[str] = []
        for i, text in enumerate(texts):
            if not text or not text.strip():
                results[i] = text
                continue
            results[i] = None  # 占位，稍后填充
            if text not in pending:
                pending.append(text)

        if not pending:
            return results

        # 2) 查缓存
        resolved: Dict[str, str] = {}
        to_translate: List[str] = []
        for text in pending:
            if self.use_cache:
                key = self._cache_key(text)
                cached = self._cache.get(key)
                if cached:
                    resolved[text] = cached
                    self.stats["cache_hit"] += 1
                    continue
            to_translate.append(text)

        if resolved:
            self._say(f"复用已有译文 {len(resolved)} 条")

        # 3) 分批翻译
        if to_translate:
            batches = self._build_batches(to_translate)
            self._say(f"待翻译 {len(to_translate)} 条 → {len(batches)} 个批次")
            done = 0
            for batch in batches:
                translated = self._translate_batch_with_fallback(batch)
                for src, dst in zip(batch, translated):
                    resolved[src] = dst
                    if self.use_cache:
                        self._cache[self._cache_key(src)] = dst
                        self._cache_dirty = True
                done += len(batch)
                if progress:
                    try:
                        progress(done, len(to_translate), desc)
                    except TypeError:
                        progress(done / max(1, len(to_translate)))
                self.save_cache()

        # 4) 回填
        for i, text in enumerate(texts):
            if results[i] is None:
                results[i] = resolved.get(text) or text

        # 5) 译文里仍残留假名 → 用更严格的提示词重译
        kana_items = [t for t in pending if contains_kana(resolved.get(t, ""))]
        if kana_items:
            self._say(f"检出残留假名 {len(kana_items)} 条，正在重译")
            for src in kana_items:
                try:
                    fixed = self.translate_strict(src).strip()
                except Exception as exc:
                    self._say(f"重译失败，保留原译文 [{src[:20]}...]: {str(exc)[:60]}")
                    continue
                if fixed and not contains_kana(fixed):
                    resolved[src] = fixed
                    if self.use_cache:
                        self._cache[self._cache_key(src)] = fixed
                        self._cache_dirty = True
            self.save_cache()
            # 重译后统一回填（非空文本一律以 resolved 为准）
            for i, text in enumerate(texts):
                if text and text.strip():
                    results[i] = resolved.get(text) or text
        return results

    # -- 批处理 --

    def _build_batches(self, texts: List[str]) -> List[List[str]]:
        batches: List[List[str]] = []
        current: List[str] = []
        current_chars = 0

        for text in texts:
            if len(text) > config.TRANSLATION_SINGLE_MAX_CHARS:
                if current:
                    batches.append(current)
                    current, current_chars = [], 0
                batches.append([text])
                continue

            if not self.supports_batch:
                batches.append([text])
                continue

            if current and (
                len(current) >= config.TRANSLATION_BATCH_SIZE
                or current_chars + len(text) > config.TRANSLATION_BATCH_MAX_CHARS
            ):
                batches.append(current)
                current, current_chars = [], 0

            current.append(text)
            current_chars += len(text)

        if current:
            batches.append(current)
        return batches

    def _translate_batch_with_fallback(self, batch: List[str]) -> List[str]:
        """批量翻译；失败则退回逐条翻译"""
        if len(batch) == 1:
            return [self._translate_single_with_retry(batch[0])]

        try:
            out = self.translate_batch(batch)
            if len(out) == len(batch) and all(x is not None for x in out):
                return [o if o and o.strip() else src for o, src in zip(out, batch)]
        except Exception as exc:
            self._say(f"批量翻译失败，改为逐条翻译: {str(exc)[:120]}")

        return [self._translate_single_with_retry(t) for t in batch]

    def _translate_single_with_retry(self, text: str) -> str:
        last_error = None
        for attempt in range(1, config.TRANSLATION_MAX_RETRIES + 1):
            try:
                result = self.translate(text)
                if result and result.strip() and not _is_refusal(result):
                    return result.strip()
                if result and _is_refusal(result):
                    self.stats["refused"] += 1
                    last_error = "模型拒答"
            except Exception as exc:
                last_error = exc
            if attempt < config.TRANSLATION_MAX_RETRIES:
                time.sleep(min(8.0, 1.5 * attempt))

        self.stats["failed"] += 1
        if last_error:
            self._say(f"翻译失败，保留原文 [{text[:24]}...]: {str(last_error)[:80]}")
        return text

    def translate_strict(self, text: str) -> str:
        """
        带「禁止假名」硬约束的重译。

        子类（LLM 引擎）可以覆盖；默认退化为普通翻译。
        """
        return self.translate(text)


# ── DeepSeek ──────────────────────────────────────────────

class DeepSeekTranslateEngine(TranslationEngine):
    """DeepSeek（OpenAI 兼容接口）"""

    name = "deepseek"
    supports_batch = True

    def __init__(self, api_key: str = None, model: str = None, verbose: bool = True, **kwargs):
        super().__init__(verbose=verbose)
        from openai import OpenAI

        self.api_key = api_key or config.DEEPSEEK_API_KEY
        if not self.api_key:
            raise ValueError(
                "未配置 DEEPSEEK_API_KEY。\n"
                "获取地址: https://platform.deepseek.com/api_keys\n"
                "请写入项目根目录的 .env 文件：DEEPSEEK_API_KEY=sk-xxxx"
            )
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=config.DEEPSEEK_BASE_URL,
            timeout=config.TRANSLATION_TIMEOUT,
        )
        self.model = model or config.DEEPSEEK_MODEL
        self._say(f"翻译引擎: DeepSeek ({self.model})")

    def _chat(self, system: str, user: str, max_tokens: int = 4096) -> str:
        self.stats["api_calls"] += 1
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            max_tokens=max_tokens,
        )
        return (response.choices[0].message.content or "").strip()

    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        max_tokens = min(8192, max(512, len(text) * 2 + 256))
        return self._chat(JP_TO_CN_SYSTEM_PROMPT, text, max_tokens)

    def translate_batch(self, texts: List[str]) -> List[str]:
        payload = "\n".join(f"<<<{i}>>>{t}" for i, t in enumerate(texts))
        raw = self._chat(
            BATCH_SYSTEM_PROMPT, payload,
            max_tokens=min(8192, max(1024, sum(len(t) for t in texts) * 2 + 512)),
        )
        parsed = _parse_marked_output(raw, len(texts))
        if parsed is None:
            raise ValueError("批量翻译输出无法解析为编号格式")
        return parsed

    def translate_strict(self, text: str) -> str:
        """禁用假名的重译"""
        if not text.strip():
            return text
        return self._chat(
            JP_TO_CN_SYSTEM_PROMPT + NO_KANA_INSTRUCTION,
            text,
            min(4096, max(512, len(text) * 2 + 256)),
        )


def _parse_marked_output(raw: str, expected: int) -> Optional[List[str]]:
    """解析 <<<n>>>译文 格式"""
    matches = list(_MARKER_RE.finditer(raw))
    if not matches:
        return None

    out: List[str] = [""] * expected
    for idx, match in enumerate(matches):
        number = int(match.group(1))
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw)
        body = raw[match.end():end].strip()
        if 0 <= number < expected:
            out[number] = body

    # 允许模型在最后一行后面少一个换行等情况
    return out if all(out) else None


# ── OpenAI ────────────────────────────────────────────────

class OpenAITranslateEngine(DeepSeekTranslateEngine):
    """OpenAI GPT"""

    name = "openai"

    def __init__(self, api_key: str = None, model: str = None, verbose: bool = True, **kwargs):
        TranslationEngine.__init__(self, verbose=verbose)
        from openai import OpenAI

        self.api_key = api_key or config.OPENAI_API_KEY
        if not self.api_key:
            raise ValueError("未配置 OPENAI_API_KEY，请写入 .env 文件")
        self.client = OpenAI(api_key=self.api_key, timeout=config.TRANSLATION_TIMEOUT)
        self.model = model or config.OPENAI_MODEL
        self._say(f"翻译引擎: OpenAI ({self.model})")


# ── Google ────────────────────────────────────────────────

class GoogleTranslateEngine(TranslationEngine):
    """Google 翻译（deep-translator，免费）"""

    name = "google"
    supports_batch = False

    def __init__(self, source: str = None, target: str = None, verbose: bool = True, **kwargs):
        super().__init__(verbose=verbose)
        from deep_translator import GoogleTranslator

        self.source = source or config.SOURCE_LANG
        self.target = target or config.TARGET_LANG
        self._translator = GoogleTranslator(source=self.source, target=self.target)
        self._say(f"翻译引擎: Google ({self.source} -> {self.target})")

    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        self.stats["api_calls"] += 1
        result = self._translator.translate(text)
        return (result or "").strip()


# ── DeepL ─────────────────────────────────────────────────

class DeepLTranslateEngine(TranslationEngine):
    """DeepL"""

    name = "deepl"
    supports_batch = False

    def __init__(self, api_key: str = None, source: str = "JA", target: str = "ZH",
                 verbose: bool = True, **kwargs):
        super().__init__(verbose=verbose)
        import deepl

        self.api_key = api_key or os.getenv("DEEPL_API_KEY", "")
        if not self.api_key:
            raise ValueError("未配置 DEEPL_API_KEY，请写入 .env 文件")
        self._translator = deepl.Translator(self.api_key)
        self.source = source
        self.target = target
        self._say(f"翻译引擎: DeepL ({source} -> {target})")

    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        self.stats["api_calls"] += 1
        result = self._translator.translate_text(
            text, source_lang=self.source, target_lang=self.target
        )
        return (result.text or "").strip()


# ── Dummy（离线测试用）─────────────────────────────────────

class DummyTranslateEngine(TranslationEngine):
    """
    离线伪翻译：把日文假名/汉字替换成等长的中文字符。

    用途：在没有网络 / 不想消耗 API 额度的情况下，验证 OCR → 排版 → 渲染
    整条链路是否正常（尤其是「译文放不下导致空白」这类问题）。
    译文长度与原文基本一致，正好可以压测排版逻辑。
    """

    name = "dummy"
    supports_batch = True

    _POOL = "中文测试译文示例内容说明数据表现结果表格姓名决定角色数值技能属性等级"
    _KANA = set("ぁあぃいぅうぇえぉおかがきぎくぐけげこごさざしじすずせぜそぞただちぢっつづてでとどなにぬねのはばぱひびぴふぶぷへべぺほぼぽまみむめもゃやゅゆょよらりるれろゎわゐゑをんゔ"
                "ァアィイゥウェエォオカガキギクグケゲコゴサザシジスズセゼソゾタダチヂッツヅテデトドナニヌネノハバパヒビピフブプヘベペホボポマミムメモャヤュユョヨラリルレロヮワヰヱヲンヴー")

    def __init__(self, verbose: bool = True, **kwargs):
        super().__init__(use_cache=False, verbose=verbose)
        self._say("翻译引擎: Dummy（离线伪翻译，仅用于链路测试）")

    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        chars = []
        for ch in text:
            if ch.isascii() or ch.isspace():
                chars.append(ch)
            elif ch in self._KANA:
                # 假名 → 中文字，长度保持 1:1
                chars.append(self._POOL[ord(ch) % len(self._POOL)])
            else:
                chars.append(ch)  # 汉字直接保留（日文汉字多数可读）
        return "".join(chars)

    def translate_batch(self, texts: List[str]) -> List[str]:
        return [self.translate(t) for t in texts]


# ── 工厂 ──────────────────────────────────────────────────

_ENGINES = {
    "deepseek": DeepSeekTranslateEngine,
    "openai": OpenAITranslateEngine,
    "google": GoogleTranslateEngine,
    "deepl": DeepLTranslateEngine,
    "dummy": DummyTranslateEngine,
}


def create_translation_engine(engine_name: str = None, verbose: bool = True) -> TranslationEngine:
    """工厂函数：根据配置创建翻译引擎"""
    name = (engine_name or config.TRANSLATION_ENGINE).lower()
    cls = _ENGINES.get(name)
    if cls is None:
        raise ValueError(
            f"不支持的翻译引擎: {name}（可选: {', '.join(_ENGINES)}）"
        )
    return cls(verbose=verbose)


def available_engines() -> List[str]:
    return list(_ENGINES)
