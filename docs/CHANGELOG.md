# CHANGELOG.md — 变更日志

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，本项目遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

## [Unreleased]

### Added (Phase 4 - Step 1: DOCX Reader)
- `modules/docx_reader.py` — DOCX 读取器（完全独立，不影响 PDF 功能）
  - `DocxReader` 类 — 支持段落/标题/表格/图片/页眉页脚提取
  - `DocxContent` — DOCX 文档完整中间表示
  - `DocxParagraph` / `DocxHeading` / `DocxTable` / `DocxTableCell` / `DocxImage` — 专用数据结构
  - 图片只保存和建立映射，不 OCR、不翻译
  - `summary()` 方法生成结构摘要
- `requirements.txt` — 添加 `python-docx`

### Added (Phase 2 - Step 2: Task Manager)
- `core/__init__.py` — 核心调度层包
- `core/task_manager.py` — TaskManager 统一任务管理器
  - 创建/查询/取消任务
  - 状态机：Waiting → Running → Success/Failed/Cancelled
  - 任务日志 + SSE 回调 + 进度推送
  - 批量任务 + 多任务队列（串行执行，预留并发接口）
  - 全局单例 `get_task_manager()`
- `core/dispatcher.py` — DocumentDispatcher 格式分派器
  - `DocumentTranslator` 抽象基类（定义统一接口）
  - `PDFTranslator` 适配器（封装 `JapanesePDFTranslator`）
  - `DOCXTranslator` / `ImageTranslator` / `PPTXTranslator` / `EPUBTranslator`（预留接口）
  - `DispatchResult` 统一返回结构
- `web/app.py` — 重构接入 TaskManager
  - 所有翻译请求通过 TaskManager
  - SSE 日志通过 TaskManager 回调推送
  - 新增 `/api/translate`（正式翻译）、`/api/tasks`（任务列表）、`/api/download/{id}`（下载）
  - Web UI 不再直接调用 `JapanesePDFTranslator`

### Added (Phase 2 - Step 1)
- `web/app.py` — FastAPI 应用（文件上传、设置管理、SSE 日志推送）
- `web/templates/index.html` — 主页面（拖拽上传 + 设置面板 + 日志）
- `web/static/style.css` — 完整样式（暗色日志 / 拖拽动画 / 响应式）
- `web/static/app.js` — 前端交互（拖拽上传 / SSE / 文件管理）
- `requirements.txt` — 添加 `fastapi`, `uvicorn`, `python-multipart`, `sse-starlette`

### Planned
- Phase 2 Step 2: 接入翻译逻辑
- Phase 2 Step 3: 设置持久化（`.env` 读写）
- Phase 3: PDF 页码范围增强（已完成）
- Phase 4: DOCX Reader
- Phase 5: DOCX Writer

---

## [0.1.0] — 2026-07-09

### Added
- `docs/PROJECT_SPEC.md` — 项目规格说明
- `docs/ARCHITECTURE.md` — 架构文档（含 Mermaid 图）
- `docs/ROADMAP.md` — 开发路线图
- `docs/TASKS.md` — 任务跟踪
- `docs/DESIGN.md` — 设计决策记录
- `docs/CHANGELOG.md` — 本文件
- `docs/README_DEVELOPMENT.md` — 开发者指南

### Infrastructure
- 建立 `docs/` 目录
- 确立项目初始化文档体系

---

## [0.0.0] — 项目初始版本（已有功能）

### Core
- PDF 文字提取（PyMuPDF）
- PDF 图片提取（PyMuPDF）
- EasyOCR 日文 OCR（GPU/MPS 加速）
- Tesseract OCR（CPU）
- Google Translate 引擎
- DeepSeek 翻译引擎（OpenAI SDK 兼容）
- OpenAI GPT 翻译引擎
- DeepL 翻译引擎

### PDF Output
- 文字型 PDF：原位替换翻译
- 图片型 PDF：OCR + 白底中文叠加
- 三级回退渲染（缩小字号 → 截断 → 原文回退）
- 置信度过滤（< 0.15 跳过）
- API 拒绝检测

### CLI
- `--translator` 引擎切换
- `--ocr` OCR 引擎切换
- `--pages` 页码范围（1-5, 1-5/10-20, 1/3/5）
- `--source-lang` / `--target-lang` 语言设置
- `-o` 输出路径
- tqdm 进度可视化
