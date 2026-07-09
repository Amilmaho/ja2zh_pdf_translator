# TASKS.md — 当前任务与状态

> ⚠️ **Agent 每次开发前必须读取此文件**

---

## 🟢 当前执行中的任务

| # | 任务 | 状态 | 负责人 | 备注 |
|---|------|------|--------|------|
| 1 | 项目初始化（Project Bootstrap） | 🔄 进行中 | AI Agent | 建立文档、设计架构、制定路线图 |

---

## 📋 待执行任务（按优先级）

### Phase 2: Web UI

| # | 任务 | 预计文件/修改 | 阻塞 |
|---|------|---------------|------|
| 2.1 | 设计 Web UI 架构 | `DESIGN.md` | 无 |
| 2.2 | 创建 `web/app.py`（FastAPI） | `web/app.py`（新增）| 无 |
| 2.3 | 创建 HTML 前端 | `web/templates/`, `web/static/`（新增）| 无 |
| 2.4 | 拖拽上传 | `web/static/upload.js`（新增）| 无 |
| 2.5 | 实时日志 SSE 推送 | `web/app.py` | 无 |
| 2.6 | 翻译进度 WebSocket | `web/app.py` | 无 |

### Phase 3: PDF 页码范围增强

| # | 任务 | 预计文件/修改 | 阻塞 |
|---|------|---------------|------|
| 3.1 | （已完成）页码范围解析 | `main.py:_parse_page_range` | - |

### Phase 4: DOCX Reader

| # | 任务 | 预计文件/修改 | 阻塞 |
|---|------|---------------|------|
| 4.1 | DOCX 文字提取器 | `modules/docx_reader.py`（新增）| Web UI 完成 |
| 4.2 | DOCX 图片提取 | `modules/docx_reader.py` | 无 |

### Phase 5: DOCX Writer

| # | 任务 | 预计文件/修改 | 阻塞 |
|---|------|---------------|------|
| 5.1 | DOCX 生成器 | `modules/docx_writer.py`（新增）| DOCX Reader 完成 |

---

## 🚧 阻塞问题

| # | 问题 | 影响 | 解决方案 |
|---|------|------|----------|
| B1 | 无日志系统（用 print） | 难以调试、Web UI 无法获取实时日志 | Phase 2 统一迁移到 logging |

---

## ⏳ 等待确认的事项

| # | 事项 | 提出时间 |
|---|------|----------|
| C1 | 新架构设计确认（DESIGN.md 中的统一 Parser/Writer 方案） | 2026-07-09 |
| C2 | Web UI 技术栈确认（FastAPI + Jinja2 vs Flask vs Streamlit） | 2026-07-09 |
| C3 | Phase 2 开发启动确认 | 2026-07-09 |

---

## 📝 最近完成

| # | 任务 | 完成时间 |
|---|------|----------|
| - | 无（项目初始化中） | - |
