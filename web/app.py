"""
Web UI — FastAPI 应用
文件上传 / 参数设置 / SSE 实时日志 / 任务下载

调用链：浏览器 → web/app.py → core.TaskManager → core.DocumentDispatcher
"""

import asyncio
import json
import os
import sys
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from config import config
from core.task_manager import TaskConfig, TaskLog, TaskStatus, get_task_manager
from modules.fonts import describe_font
from modules.translator import available_engines


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(config.INPUT_DIR, "web_uploads")

SUPPORTED_EXTENSIONS = {".pdf": "pdf", ".docx": "docx"}

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

app = FastAPI(title="日文文档翻译工具", version="0.3.0")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

os.makedirs(UPLOAD_DIR, exist_ok=True)

task_manager = get_task_manager()
uploaded_files: Dict[str, dict] = {}


def detect_format(filename: str) -> str:
    return SUPPORTED_EXTENSIONS.get(Path(filename).suffix.lower(), "unknown")


def _public_file_info(file_id: str, info: dict) -> dict:
    return {
        "id": file_id,
        "name": info["name"],
        "size": info["size"],
        "format": info["format"],
        "uploaded_at": info["uploaded_at"],
    }


# ── 页面 ──────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = os.path.join(BASE_DIR, "templates", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# ── 文件管理 ──────────────────────────────────────────────

@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...)):
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
                "format": "unknown",
                "error": f"不支持的文件格式（支持: {', '.join(SUPPORTED_EXTENSIONS)}）",
            })
            continue

        safe_name = f"{file_id}_{os.path.basename(file.filename)}"
        file_path = os.path.join(UPLOAD_DIR, safe_name)
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)

        uploaded_files[file_id] = {
            "name": file.filename,
            "path": file_path,
            "size": len(content),
            "format": fmt,
            "uploaded_at": datetime.now().isoformat(),
        }
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
    info = uploaded_files.pop(file_id, None)
    if not info:
        raise HTTPException(status_code=404, detail="文件不存在")
    try:
        if os.path.exists(info["path"]):
            os.remove(info["path"])
    except OSError:
        pass
    return JSONResponse({"status": "ok"})


@app.get("/api/files")
async def list_files():
    return JSONResponse({
        "files": [_public_file_info(fid, info) for fid, info in uploaded_files.items()]
    })


# ── 设置 ──────────────────────────────────────────────────

@app.get("/api/settings")
async def get_settings():
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
        "available_translators": available_engines(),
        "available_ocr": ["easyocr", "tesseract"],
        "font": describe_font(),
    })


# ── SSE 实时日志 ──────────────────────────────────────────

@app.get("/api/logs/{task_id}")
async def stream_logs(task_id: str):
    if not task_manager.get_task(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")

    async def event_generator():
        sent = 0
        idle_start = time.time()
        max_idle = 900  # 15 分钟无输出则断开

        while True:
            logs = task_manager.get_task_logs(task_id)
            while sent < len(logs):
                log = logs[sent]
                sent += 1
                idle_start = time.time()
                yield {
                    "event": "log",
                    "data": json.dumps(asdict(log), ensure_ascii=False),
                }

            task = task_manager.get_task(task_id)
            if task and task.status in (
                TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED
            ):
                if sent >= len(task_manager.get_task_logs(task_id)):
                    yield {"event": "done", "data": task.status.value}
                    return

            await asyncio.sleep(0.4)

            if time.time() - idle_start > max_idle:
                yield {
                    "event": "log",
                    "data": json.dumps(asdict(TaskLog(
                        timestamp=datetime.now().strftime("%H:%M:%S"),
                        level="warning",
                        message="日志流已关闭（长时间无输出）",
                    )), ensure_ascii=False),
                }
                return

    return EventSourceResponse(event_generator())


# ── 翻译任务 ──────────────────────────────────────────────

@app.post("/api/translate")
async def start_translation(
    file_id: str = Form(...),
    translator: str = Form(None),
    ocr: str = Form(None),
    page_range: str = Form(None),
    translate_images: str = Form(None),
):
    info = uploaded_files.get(file_id)
    if not info:
        raise HTTPException(status_code=404, detail="文件不存在，请先上传")

    task_config = TaskConfig(
        translation_engine=translator or config.TRANSLATION_ENGINE,
        ocr_engine=ocr or config.OCR_ENGINE,
        page_range=(page_range or "").strip() or None,
    )
    if translate_images is not None:
        flag = str(translate_images).lower() in ("1", "true", "on", "yes")
        task_config.translate_images = flag
        task_config.docx_translate_images = flag

    task = task_manager.create_task(
        file_path=info["path"],
        task_config=task_config,
    )

    threading.Thread(target=task_manager.execute, args=(task,), daemon=True).start()
    return JSONResponse({
        "task_id": task.id,
        "status": task.status.value,
        "output_path": task.output_path,
    })


@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
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
        "stats": (task.result.stats if task.result else {}),
    })


@app.get("/api/tasks")
async def list_tasks():
    return JSONResponse(task_manager.to_dict())


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    if task_manager.cancel(task_id):
        return JSONResponse({"status": "ok"})
    raise HTTPException(status_code=400, detail="无法取消（任务可能已完成）")


@app.post("/api/tasks/clear")
async def clear_tasks():
    removed = task_manager.clear_finished()
    return JSONResponse({"status": "ok", "removed": removed})


@app.get("/api/download/{task_id}")
async def download_result(task_id: str):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != TaskStatus.SUCCESS:
        raise HTTPException(status_code=400, detail="任务未完成或失败")
    if not task.output_path or not os.path.exists(task.output_path):
        raise HTTPException(status_code=404, detail="输出文件不存在")

    ext = os.path.splitext(task.output_path)[1].lower().lstrip(".")
    media_type = MEDIA_TYPES.get(ext, "application/octet-stream")
    return FileResponse(
        task.output_path,
        filename=os.path.basename(task.output_path),
        media_type=media_type,
    )


@app.post("/api/test-log")
async def test_log():
    """生成模拟日志，用于测试 SSE 流"""
    task = task_manager.create_task(file_path="/tmp/__demo__.pdf", task_config=TaskConfig())

    async def generate_fake_logs():
        steps = [
            ("初始化引擎...", "info", 5),
            ("读取文件信息...", "info", 10),
            ("正在提取文字和图片...", "info", 25),
            ("提取完成：共 20 页，45 个文字块，3 张图片", "info", 40),
            ("OCR 识别中...", "info", 55),
            ("翻译文字内容中...", "info", 70),
            ("生成 PDF 中...", "info", 85),
            ("翻译完成（演示）", "success", 100),
        ]
        for msg, level, progress in steps:
            task_manager._add_log(task, msg, level, progress)
            await asyncio.sleep(0.6)
        task.status = TaskStatus.SUCCESS

    asyncio.create_task(generate_fake_logs())
    return JSONResponse({"task_id": task.id})


@app.get("/api/health")
async def health():
    return JSONResponse({"status": "ok", "version": "0.3.0"})
