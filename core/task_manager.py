"""
Task Manager - 统一任务管理层（Phase 2 Step 2）
Web UI 与所有翻译逻辑之间的唯一入口。

职责：
  - 创建任务（分配 task_id）
  - 管理状态（Waiting、Running、Success、Failed、Cancelled）
  - 保存任务日志
  - 保存任务配置
  - 保存输出目录
  - 统一返回结果
  - SSE 日志推送
  - 批量文件 / 多任务队列（串行执行，预留并发）

调用链：
  Web UI → TaskManager → DocumentDispatcher → PDFTranslator (未来: DOCX, Image...)
"""

import os
import sys
import json
import uuid
import time
import threading
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any, Callable
from enum import Enum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config as app_config
from core.dispatcher import DocumentDispatcher, DispatchResult


# ── 枚举 ──────────────────────────────────────────────────

class TaskStatus(str, Enum):
    WAITING = "waiting"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ── 数据结构 ──────────────────────────────────────────────

@dataclass
class TaskLog:
    """单条日志"""
    timestamp: str
    level: str       # "info" | "warning" | "error" | "success"
    message: str
    progress: int = 0  # 0-100


@dataclass
class TaskConfig:
    """任务配置"""
    translation_engine: str = "deepseek"
    ocr_engine: str = "easyocr"
    source_lang: str = "ja"
    target_lang: str = "zh-CN"
    page_range: Optional[str] = None       # PDF 页码范围
    docx_translate_images: bool = True      # DOCX 图片 OCR
    docx_translate_headers: bool = True     # DOCX 页眉页脚
    docx_translate_tables: bool = True      # DOCX 表格


@dataclass
class Task:
    """单个翻译任务"""
    id: str
    file_path: str
    file_name: str
    file_format: str          # "pdf" | "docx" | "png" | "jpg"
    status: TaskStatus = TaskStatus.WAITING
    config: TaskConfig = field(default_factory=TaskConfig)
    output_path: str = ""
    logs: List[TaskLog] = field(default_factory=list)
    result: Optional[DispatchResult] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_message: str = ""


# ── SSE 回调类型 ──────────────────────────────────────────

LogCallback = Callable[[TaskLog], None]


# ── TaskManager ───────────────────────────────────────────

class TaskManager:
    """
    统一任务管理器。

    使用方式:
        tm = TaskManager()

        # 创建任务
        task = tm.create_task(
            file_path="/path/to/file.pdf",
            config=TaskConfig(translation_engine="deepseek", page_range="1-5"),
        )

        # 执行（串行，预留并发接口）
        result = tm.execute(task)

        # 获取状态
        status = tm.get_task(task.id)

        # 取消任务
        tm.cancel(task.id)
    """

    def __init__(self):
        self._tasks: Dict[str, Task] = {}
        self._lock = threading.Lock()

        # SSE 回调列表（可注册多个监听者）
        self._log_callbacks: Dict[str, List[LogCallback]] = {}

    # ── 任务创建 ──────────────────────────────────────────

    def create_task(
        self,
        file_path: str,
        task_config: TaskConfig = None,
        output_dir: str = None,
    ) -> Task:
        """
        创建翻译任务。

        Args:
            file_path: 输入文件路径
            config: 任务配置（可选，默认使用全局 config）
            output_dir: 输出目录（可选，默认使用 config.OUTPUT_DIR）

        Returns:
            Task: 新创建的任务对象
        """
        task_id = uuid.uuid4().hex[:12]
        file_name = os.path.basename(file_path)

        # 检测格式
        ext = os.path.splitext(file_path)[1].lower()
        format_map = {".pdf": "pdf", ".docx": "docx", ".png": "png",
                      ".jpg": "jpg", ".jpeg": "jpg", ".pptx": "pptx", ".epub": "epub"}
        file_format = format_map.get(ext, "unknown")

        if task_config is None:
            task_config = TaskConfig()

        # 生成输出路径
        if output_dir is None:
            output_dir = app_config.OUTPUT_DIR
        os.makedirs(output_dir, exist_ok=True)

        base_name = os.path.splitext(file_name)[0]
        output_path = os.path.join(output_dir, f"{base_name}_translated.pdf")

        task = Task(
            id=task_id,
            file_path=file_path,
            file_name=file_name,
            file_format=file_format,
            config=task_config,
            output_path=output_path,
        )

        with self._lock:
            self._tasks[task_id] = task

        self._add_log(task, f"任务已创建: {file_name} ({file_format})", "info")
        return task

    def create_batch(
        self,
        file_paths: List[str],
        config: TaskConfig = None,
        output_dir: str = None,
    ) -> List[Task]:
        """批量创建任务"""
        return [self.create_task(p, config, output_dir) for p in file_paths]

    # ── 任务执行 ──────────────────────────────────────────

    def execute(self, task: Task) -> DispatchResult:
        """
        执行单个翻译任务（串行）。

        内部调用 DocumentDispatcher 进行格式分派。

        Args:
            task: Task 对象

        Returns:
            DispatchResult: 翻译结果
        """
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now().isoformat()

        self._add_log(task, f"开始翻译: {task.file_name}", "info")
        self._add_log(task, f"翻译引擎: {task.config.translation_engine}, OCR: {task.config.ocr_engine}", "info")

        try:
            dispatcher = DocumentDispatcher(
                log_callback=lambda log: self._add_log(task, log.message, log.level, log.progress),
                progress_callback=lambda p: self._update_progress(task, p),
            )

            result = dispatcher.dispatch(task)

            task.result = result
            task.output_path = result.output_path

            if result.success:
                task.status = TaskStatus.SUCCESS
                self._add_log(task, f"✅ 翻译完成！输出: {result.output_path}", "success", 100)
            else:
                task.status = TaskStatus.FAILED
                task.error_message = result.error or "未知错误"
                self._add_log(task, f"❌ 翻译失败: {task.error_message}", "error")

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
            self._add_log(task, f"❌ 致命错误: {e}", "error")

        finally:
            task.finished_at = datetime.now().isoformat()

        return task.result

    def execute_all(self, tasks: List[Task]) -> List[DispatchResult]:
        """
        批量执行任务（当前为串行，预留并发接口）。

        Args:
            tasks: Task 列表

        Returns:
            List[DispatchResult]: 结果列表
        """
        results = []
        for i, task in enumerate(tasks):
            self._add_log(task, f"队列 [{i+1}/{len(tasks)}] 开始执行", "info")
            result = self.execute(task)
            results.append(result)
        return results

    # ── 任务查询 ──────────────────────────────────────────

    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> List[Task]:
        """获取所有任务"""
        with self._lock:
            return list(self._tasks.values())

    def get_task_logs(self, task_id: str) -> List[TaskLog]:
        """获取任务日志"""
        task = self._tasks.get(task_id)
        if task:
            return task.logs
        return []

    # ── 任务控制 ──────────────────────────────────────────

    def cancel(self, task_id: str) -> bool:
        """取消任务"""
        task = self._tasks.get(task_id)
        if task and task.status in (TaskStatus.WAITING, TaskStatus.RUNNING):
            task.status = TaskStatus.CANCELLED
            task.finished_at = datetime.now().isoformat()
            self._add_log(task, "任务已取消", "warning")
            return True
        return False

    # ── 日志与进度 ────────────────────────────────────────

    def _add_log(self, task: Task, message: str, level: str = "info", progress: int = 0):
        """添加任务日志并触发 SSE 回调"""
        entry = TaskLog(
            timestamp=datetime.now().strftime("%H:%M:%S"),
            level=level,
            message=message,
            progress=progress,
        )
        task.logs.append(entry)

        # 触发 SSE 回调
        callbacks = self._log_callbacks.get(task.id, [])
        for cb in callbacks:
            try:
                cb(entry)
            except Exception:
                pass

    def _update_progress(self, task: Task, progress: int):
        """更新进度（通过日志）"""
        task.logs[-1].progress = progress if task.logs else 0

    def register_log_callback(self, task_id: str, callback: LogCallback):
        """注册 SSE 日志回调"""
        if task_id not in self._log_callbacks:
            self._log_callbacks[task_id] = []
        self._log_callbacks[task_id].append(callback)

    def unregister_log_callback(self, task_id: str, callback: LogCallback):
        """取消注册 SSE 日志回调"""
        if task_id in self._log_callbacks:
            self._log_callbacks[task_id] = [
                cb for cb in self._log_callbacks[task_id] if cb is not callback
            ]

    # ── 任务摘要 ──────────────────────────────────────────

    def to_dict(self) -> dict:
        """序列化为 JSON 安全字典"""
        return {
            "tasks": [
                {
                    "id": t.id,
                    "file_name": t.file_name,
                    "file_format": t.file_format,
                    "status": t.status.value,
                    "output_path": t.output_path,
                    "error_message": t.error_message,
                    "created_at": t.created_at,
                    "started_at": t.started_at,
                    "finished_at": t.finished_at,
                    "log_count": len(t.logs),
                }
                for t in self._tasks.values()
            ]
        }


# ── 全局单例（供 Web UI 使用）────────────────────────────

_task_manager_instance: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    """获取全局 TaskManager 单例"""
    global _task_manager_instance
    if _task_manager_instance is None:
        _task_manager_instance = TaskManager()
    return _task_manager_instance
