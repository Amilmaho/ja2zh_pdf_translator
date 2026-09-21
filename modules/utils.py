"""
通用小工具：页码范围解析、缓存键、耗时格式化、进度回调封装。
"""

import hashlib
import os
import re
import time
from typing import Iterable, List, Optional


class PageRangeError(ValueError):
    """页码范围格式错误"""


def parse_page_range(spec: Optional[str], total_pages: int) -> List[int]:
    """
    解析页码范围（1 基，用户视角），返回 0 基下标列表。

    支持:
        "1-5"        -> [0,1,2,3,4]
        "1,3,5"      -> [0,2,4]
        "1-5,10-20"  -> ...
        "5-"         -> 第 5 页到最后一页
        "-10"        -> 第 1 页到第 10 页
        None / ""    -> 全部页面

    Raises:
        PageRangeError: 语法错误或页码越界
    """
    if not spec or not str(spec).strip():
        return list(range(total_pages))

    pages: List[int] = []
    for chunk in re.split(r"[,，;；\s]+", str(spec).strip()):
        if not chunk:
            continue

        if "-" in chunk:
            start_s, _, end_s = chunk.partition("-")
            try:
                start = int(start_s) if start_s.strip() else 1
                end = int(end_s) if end_s.strip() else total_pages
            except ValueError:
                raise PageRangeError(f"无法解析页码范围: {chunk}")
        else:
            try:
                start = end = int(chunk)
            except ValueError:
                raise PageRangeError(f"无法解析页码: {chunk}")

        if start > end:
            start, end = end, start
        if start < 1 or end > total_pages:
            raise PageRangeError(
                f"页码范围 {chunk} 超出文档范围（共 {total_pages} 页，页码从 1 开始）"
            )
        pages.extend(range(start - 1, end))

    # 去重且保持顺序
    seen = set()
    ordered = []
    for p in pages:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


def format_page_selection(pages: Iterable[int]) -> str:
    """把 0 基下标列表压成 "1-5,10-20" 形式，便于打印"""
    ordered = sorted(set(pages))
    if not ordered:
        return "(无)"
    parts = []
    start = prev = ordered[0]
    for p in ordered[1:]:
        if p == prev + 1:
            prev = p
            continue
        parts.append(str(start + 1) if start == prev else f"{start + 1}-{prev + 1}")
        start = prev = p
    parts.append(str(start + 1) if start == prev else f"{start + 1}-{prev + 1}")
    return ",".join(parts)


def file_fingerprint(path: str, extra: str = "") -> str:
    """根据文件内容（采样）+ 额外标记生成缓存键"""
    h = hashlib.sha1()
    h.update(os.path.basename(path).encode("utf-8", "ignore"))
    try:
        size = os.path.getsize(path)
        h.update(str(size).encode())
        with open(path, "rb") as f:
            head = f.read(65536)
            h.update(head)
            if size > 65536:
                f.seek(max(0, size - 65536))
                h.update(f.read(65536))
    except OSError:
        pass
    h.update(extra.encode("utf-8", "ignore"))
    return h.hexdigest()


def short_hash(text: str, length: int = 16) -> str:
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()[:length]


def format_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.1f} 秒"
    minutes, sec = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes} 分 {sec} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes} 分"


class ProgressReporter:
    """
    统一的进度回调封装。

    兼容两种回调签名（自动适配）：
        fn(message, level, progress)
        fn(progress)
    """

    def __init__(self, callback=None, verbose: bool = True, prefix: str = ""):
        self.callback = callback
        self.verbose = verbose
        self.prefix = prefix
        self._start = time.time()

    def log(self, message: str, level: str = "info", progress: int = 0):
        line = f"{self.prefix}{message}" if self.prefix else message
        if self.verbose:
            print(f"  {line}", flush=True)
        if not self.callback:
            return
        try:
            self.callback(line, level, progress)
        except TypeError:
            try:
                self.callback(progress)
            except Exception:
                pass
        except Exception:
            pass

    @property
    def elapsed(self) -> float:
        return time.time() - self._start
