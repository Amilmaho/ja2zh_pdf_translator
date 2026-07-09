"""
Web UI - FastAPI 应用（Phase 2 Step 2：接入 TaskManager）
功能：文件上传 / 设置管理 / SSE 日志推送 / 通过 TaskManager 管理翻译任务
"""

import os
import sys
import json
import uuid
import asyncio
import time
import threading
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime

# 将项目根目录加入 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from config import config
from core.task_manager import (
    TaskManager, TaskConfig, TaskStatus, TaskLog,
    get_task_manager,
)
from core.dispatcher import DispatchResult

# ── 应用初始化 ──────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(config.INPUT_DIR, "web_uploads")

app = FastAPI(title="日文 PDF 翻译工具", version="0.2.0")

# 静态文件 & 模板
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# 确保上传目录存在
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ── 全局 TaskManager 实例 ──────────────────────────────────

task_manager = get_task_manager()

# ── 内存存储（Web 层文件缓存）──────────────────────────────

uploaded_files: Dict[str, dict] = {}

# ── 工具函数 ────────────────────────────────────────────────

SUPPORTED_EXTENSIONS = {
    ".pdf": "pdf",
    ".docx": "docx",
}

def detect_format(filename: str) -> str:
    """根据扩展名检测文件格式"""
    ext = Path(filename).suffix.lower()
    return SUPPORTED_EXTENSIONS.get(ext, "unknown")

# ── 路由：页面 ──────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    """主页面"""
    return templates.TemplateResponse("index.html", {})

# ── 路由：文件上传 ──────────────────────────────────────────

@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    """批量上传文件，返回文件信息列表"""
    results = []

    for file in files:
        if not file.filename:
            continue

        file_id = uuid.uuid4().hex[:12]
        fmt = detect_format(file.filename)

        if fmt == "unknown":
            results.append({
                "id": file_id,
                "name": file.filename,
                "error": f"不支持的文件格式（支持: {', '.join(SUPPORTED_EXTENSIONS.keys())}）",
                "format": "unknown",
            })
            continue

        # 保存文件
        safe_name = f"{file_id}_{file.filename}"
        file_path = os.path.join(UPLOAD_DIR, safe_name)
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)

        uploaded = UploadedFile(
            id=file_id,
            name=file.filename,
            path=file_path,
            size=len(content),
            format=fmt,
            uploaded_at=datetime.now().isoformat(),
        )
        uploaded_files[file_id] = uploaded
        results.append({
            "id": file_id,
            "name": file.filename,
            "size": len(content),
            "format": fmt,
            "status": "ok",
        })

    return JSONResponse({"files": results})

@app.delete("/api/upload/{file_id}")
async def remove_file(file_id: str):
    """删除已上传的文件"""
    if file_id in uploaded_files:
        f = uploaded_files.pop(file_id)
        if os.path.exists(f.path):
            os.remove(f.path)
        return JSONResponse({"status": "ok"})
    raise HTTPException(status_code=404, detail="文件不存在")

# ── 路由：文件列表 ──────────────────────────────────────────

@app.get("/api/files")
async def list_files():
    """列出所有已上传的文件"""
    files = []
    for f in uploaded_files.values():
        files.append({
            "id": f.id,
            "name": f.name,
            "size": f.size,
            "format": f.format,
            "uploaded_at": f.uploaded_at,
        })
    return JSONResponse({"files": files})

# ── 路由：设置 ──────────────────────────────────────────────

@app.get("/api/settings")
async def get_settings():
    """获取当前设置"""
    return JSONResponse({
        "translation_engine": config.TRANSLATION_ENGINE,
        "ocr_engine": config.OCR_ENGINE,
        "source_lang": config.SOURCE_LANG,
        "target_lang": config.TARGET_LANG,
        "deepseek_model": config.DEEPSEEK_MODEL,
        "openai_model": config.OPENAI_MODEL,
        "output_dir": config.OUTPUT_DIR,
        "has_deepseek_key": bool(config.DEEPSEEK_API_KEY),
        "has_openai_key": bool(config.OPENAI_API_KEY),
        "has_deepl_key": bool(os.getenv("DEEPL_API_KEY", "")),
    })

@app.post("/api/settings")
async def update_settings(settings: dict = None):
    """更新设置（写回 .env）"""
    # 🔒 Phase 2 Step 1: 暂不实现持久化写入
    # 后续 Step 会实现 .env 写入
    return JSONResponse({
        "status": "not_implemented",
        "message": "设置持久化将在下一阶段实现"
    })

# ── 路由：SSE 日志流（通过 TaskManager）─────────────────────

@app.get("/api/logs/{task_id}")
async def stream_logs(task_id: str):
    """SSE 日志推送 — 实时从 TaskManager 获取日志"""
    task = task_manager.get_task(task_id)

    async def event_generator():
        # 先发送已有的日志
        existing_logs = task_manager.get_task_logs(task_id)
        sent_count = len(existing_logs)

        # 使用队列收集新日志
        new_logs = []

        def on_log(log: TaskLog):
            new_logs.append(log)

        task_manager.register_log_callback(task_id, on_log)

        try:
            # 发送已有日志
            for log in existing_logs:
                yield {
                    "event": "log",
                    "data": json.dumps(asdict(log), ensure_ascii=False),
                }

            max_idle = 60  # 空闲超时
            idle_start = time.time()

            while True:
                while new_logs:
                    log = new_logs.pop(0)
                    idle_start = time.time()
                    yield {
                        "event": "log",
                        "data": json.dumps(asdict(log), ensure_ascii=False),
                    }

                    # 任务完成时断开
                    if log.level in ("success", "error") and log.progress >= 100:
                        yield {"event": "done", "data": "completed"}
                        return

                # 检查任务是否已结束
                task = task_manager.get_task(task_id)
                if task and task.status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    yield {"event": "done", "data": task.status.value}
                    return

                await asyncio.sleep(0.5)

                if time.time() - idle_start > max_idle:
                    yield {
                        "event": "log",
                        "data": json.dumps(asdict(TaskLog(
                            timestamp=datetime.now().strftime("%H:%M:%S"),
                            level="info",
                            message="日志流已关闭（空闲超时）",
                            progress=0,
                        )), ensure_ascii=False),
                    }
                    return
        finally:
            task_manager.unregister_log_callback(task_id, on_log)

    return EventSourceResponse(event_generator())

# ── 路由：开始翻译（通过 TaskManager）─────────────────────────

@app.post("/api/translate")
async def start_translation(file_id: str = Form(...)):
    """
    开始翻译任务（异步执行，通过 SSE 返回进度）。

    请求：file_id（已上传文件 ID）
    返回：task_id（用于 SSE 日志流）
    """
    upload_info = uploaded_files.get(file_id)
    if not upload_info:
        raise HTTPException(status_code=404, detail="文件不存在，请先上传")

    task = task_manager.create_task(
        file_path=upload_info["path"],
        task_config=TaskConfig(
            translation_engine=config.TRANSLATION_ENGINE,
            ocr_engine=config.OCR_ENGINE,
        ),
    )

    # 异步执行翻译（后台线程，不阻塞请求）
    def run_in_background():
        task_manager.execute(task)

    thread = threading.Thread(target=run_in_background, daemon=True)
    thread.start()

    return JSONResponse({"task_id": task.id, "status": task.status.value})

# ── 路由：获取任务状态 ──────────────────────────────────────

@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    """获取任务状态和结果"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return JSONResponse({
        "id": task.id,
        "file_name": task.file_name,
        "status": task.status.value,
        "output_path": task.output_path,
        "error_message": task.error_message,
        "log_count": len(task.logs),
    })

# ── 路由：下载结果 ──────────────────────────────────────────

@app.get("/api/download/{task_id}")
async def download_result(task_id: str):
    """下载翻译后的文件"""
    from fastapi.responses import FileResponse

    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != TaskStatus.SUCCESS:
        raise HTTPException(status_code=400, detail="任务未完成或失败")
    if not os.path.exists(task.output_path):
        raise HTTPException(status_code=404, detail="输出文件不存在")

    return FileResponse(
        task.output_path,
        filename=os.path.basename(task.output_path),
        media_type="application/pdf",
    )

# ── 路由：任务列表 ──────────────────────────────────────────

@app.get("/api/tasks")
async def list_tasks():
    """列出所有任务"""
    return JSONResponse(task_manager.to_dict())

# ── 路由：取消任务 ──────────────────────────────────────────

@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """取消正在执行的任务"""
    if task_manager.cancel(task_id):
        return JSONResponse({"status": "ok"})
    raise HTTPException(status_code=400, detail="无法取消（任务可能已完成）")

# ── 路由：模拟任务（测试 SSE 日志流，通过 TaskManager）─────────

@app.post("/api/test-log")
async def test_log():
    """生成模拟日志，用于测试 SSE 流"""
    # 创建一个虚拟任务
    task = task_manager.create_task(
        file_path="/tmp/test.pdf",
        task_config=TaskConfig(),
    )

    async def generate_fake_logs():
        steps = [
            ("初始化引擎...", "info", 5),
            ("读取文件信息...", "info", 10),
            ("正在提取文字和图片...", "info", 25),
            ("提取完成：共 20 页，45 个文字块，3 张图片", "success", 40),
            ("OCR 识别中...", "info", 55),
            ("翻译文字内容中...", "info", 70),
            ("生成 PDF 中...", "info", 85),
            ("✅ 翻译完成！输出文件已保存", "success", 100),
        ]
        for msg, level, progress in steps:
            task_manager._add_log(task, msg, level, progress)
            await asyncio.sleep(0.8)
        # 模拟完成
        task.status = TaskStatus.SUCCESS

    asyncio.create_task(generate_fake_logs())
    return JSONResponse({"task_id": task.id})

# ── 路由：清空任务历史 ──────────────────────────────────────

@app.post("/api/tasks/clear")
async def clear_tasks():
    """清空所有已完成的任务"""
    with task_manager._lock:
        to_remove = [
            tid for tid, t in task_manager._tasks.items()
            if t.status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED)
        ]
        for tid in to_remove:
            del task_manager._tasks[tid]
    return JSONResponse({"status": "ok", "removed": len(to_remove)})

# ── 健康检查 ─────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return JSONResponse({"status": "ok", "version": "0.2.0"})
