# CHANGELOG.md — 变更日志

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，本项目遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

## [Unreleased]

### Added (Phase 5: DOCX Writer)
- `modules/docx_writer.py` — DOCX 写入器
  - 基于原始 DOCX 模板保持样式
  - 段落/标题/表格文字替换
  - 与 DocxReader 共享索引体系
- `core/dispatcher.py` — `DOCXTranslator` 完整实现
  - 读 DOCX → 翻译文字 → OCR 图片 → 写 DOCX
  - 完全复用现有 Translation Engine 和 OCR Engine
  - 支持跳过图片 OCR 选项
- `core/task_manager.py` — 修复 DOCX 输出扩展名 `.docx`

### Added (Phase 4 - Step 2: DOCX 图片 OCR)
- `modules/docx_reader.py` — 新增 `ocr_images()` 静态方法和 `get_ocr_summary()`
  - `DocxImage` 新增 `ocr_results` 字段和 `has_ocr` 属性
  - 复用现有 `OCREngine.recognize_file()`，零修改 OCR 模块
  - 置信度过滤（min_confidence 可配置）
  - tqdm 进度条 + 异常容错
  - 测试验证：从真实 PDF 日文图片中识别到 6 个日文区域

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
- `main.py` 同时支持 PDF 和 DOCX，自动检测文件格式
- DOCX 翻译带 tqdm 进度条
- 移除冗余参数 `--source-lang` / `--target-lang`
