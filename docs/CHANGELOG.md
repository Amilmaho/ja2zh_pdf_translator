# CHANGELOG.md — 变更日志

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，本项目遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

## [Unreleased]

### Fixed (v0.3.2 消除译文里的日文残留)

反馈：翻译后的页面里还能看到一部分日文。逐项量过之后，是三个独立原因：

1. **置信度一刀切，丢掉了 21% 的正文**
   EasyOCR 对复杂汉字的置信度天然偏低 —— 实测大量**完全读对**的文本只有
   0.0~0.3（例如标题「イラの歴史」0.22、「真如」0.27、
   「む必要があるだろう」0.19）。旧阈值 0.30 直接把它们当噪声丢掉，
   而这些区域按设计又不覆盖，于是原图日文原样留在译文页上。
   现在改为「只丢确定是垃圾的」：空文本、纯符号、页边细长竖条
   （页码标记）、极短且极低置信度的碎片，其余一律翻译。
   实测第 26 页保留数 74 → 84（丢弃 17 → 7，且丢的全是页码标记）。

2. **第一遍 OCR 会整块漏检**
   实测每页有 2~5 处正文行完全没被检出（例如小标题
   「サンサーラとイラでの生活」「サンサーラの社会的地位」），
   这些位置没有识别框 → 不会覆盖 → 日文原样可见。
   新增**查漏补识别**（`core/pdf_translator._recover_missed_regions`）：
   自动判断深底/浅底生成墨迹掩码 → 行/列投影找出「有墨但无识别框」的行
   → 裁剪放大 2 倍重新识别 → 用重叠度校验结果（防止串到邻行）→ 补进计划。
   同时按「交集/较小者面积」去重，避免同一行画两遍。

3. **模型在译文里保留了假名**
   例如「サンサーラ」被译成「萨ンサーラ」。现在提示词明确禁止输出假名，
   并在翻译后加一道检测：译文里仍有假名 → 用带硬约束的提示词自动重译
   （`modules/translator.contains_kana` / `translate_strict`）。

顺带修复：相邻区域（大标题 + 副标题这类交叠的框）原来会「后画的底色盖住
先画的文字」，现在改为**先铺完所有底色、再统一写文字**。

验证（`異世界転生RPG.pdf` 第 20~30 页，11 页）：

| 指标 | 结果 |
|---|---|
| 译文里的假名字符 | 16 → **0** |
| 输出图上仍能读出日文的区域 | 8 → **0**（唯一 1 处是日语 OCR 误读我们的中文） |
| 空白色块 / 底色不符 | 0 / 0 |
| 墨量比（译文/原文） | 0.80 ~ 1.11 |

### Improved (v0.3.1 排版质量：字号标定 + 字体风格)

反馈：翻译后排版偏"挤/重"，观感与原版差距明显。
量出来的原因是两件事，都已修正：

1. **译文字号比原文大 32%**
   OCR 返回的框比字形本身高约 30%（含上下留白），旧逻辑直接按框高定字号，
   于是译文比原文大一大圈，而行距没变 → 又挤又黑。
   现在改成：从原图量出**字形墨迹的真实高度**，再按字体的「墨迹/字号」比例
   换算成目标字号（`core/pdf_translator._measure_glyph_sizes`）。
   文字层页面则直接使用 PDF 自带的字号。

2. **字体风格不匹配**
   日文小说/规则书正文基本都是**明朝体（衬线）**，而之前用的是黑体。
   现在默认按「宋体优先」挑选字体（macOS 上会命中 SimSong），
   可用 `.env` 的 `FONT_STYLE=sans` 切回黑体。

实测效果（`異世界転生RPG.pdf` 第 20~30 页，译文墨量与原文之比）：

| 版本 | 字号比 | 整页墨量比 |
|---|---|---|
| 改版前 | 1.32× | 1.65× |
| 仅校准字号 | 1.00× | 1.35× |
| + 宋体 | 1.00× | **1.02×** |

密集表格页同样受益：第 100~102 页墨量比从 1.17/1.46/1.26 降到 0.96/1.03/0.99。

### Fixed

- `modules/fonts.py` 新增**渲染探针**：有些 `.ttc`（如 macOS Songti）能通过
  字形覆盖检查，但 MuPDF 实际渲染时会抛
  `substitute font creation is not implemented`，现在会在选用前直接排掉，
  避免生成阶段崩溃。

### Fixed (v0.3 重构：修复「OCR/翻译跑不动 + 译图大量空白」)

用户反馈：原本 OCR 和翻译无法正常进行，翻译后的图片大部分都是空白。
定位到下面 5 个根因并全部修复：

1. **Web UI 的 PDF 翻译必定报错**（致命）
   `core/dispatcher.py` 把 `page_range` 传给了不接受该参数的构造函数 →
   每次 Web 端 PDF 翻译都 `TypeError`。现在统一委托给
   `core/pdf_translator.PDFTranslator`，页码/进度/日志都正确透传。

2. **译图大面积空白**（核心投诉）
   旧逻辑「先画白底 → `insert_textbox` 试写 → 写不进就算了」，
   于是留下大量没有文字的白色矩形；深色页面（漫画、深色表格栏）尤其刺眼。
   新逻辑：先用 `modules/text_layout.TextFitter` 算清楚「能不能放下、
   放几行、多大字号」，确认能放下才覆盖，放不下就**保留原图文字**。

3. **覆盖色与底色不符**
   旧版一律填白色；深色表格栏被涂成白块。
   现在按区域取原图主色（`sample` 模式），并自动选黑字/白字保证对比度，
   底色与原图不一致时还会拒绝扩框。

4. **文字块提取错位**
   `_extract_text_blocks` 按行生成记录却用 block 的 bbox → 同一块内多行
   文字全部叠在同一矩形里。现在使用行自身的 bbox。

5. **DOCX 译文为空时把原文清空**
   `translated_list` 初始为 `''`，未翻译的段落被整段抹掉。
   现在缺译文一律回退原文。

### Added (v0.3)

- `modules/text_layout.py` — 中日文混排测宽/换行/自适应字号（防空白的关键）
- `modules/fonts.py` — 中文字体发现 + **字形覆盖校验**（避免选到没有中日文的字体后渲染出空白）
- `modules/image_overlay.py` — DOCX 内嵌图片的译文重绘
- `modules/utils.py` — 页码范围解析、缓存键、进度回调封装
- `core/pdf_translator.py` — PDF 编排（逐页处理，内存与页数无关）
- `core/docx_translator.py` — DOCX 编排
- `tools/verify_pipeline.py` — 端到端自检：空白色块 / 底色一致性 / 溢出 / 墨量
- 翻译引擎 `dummy` — 离线伪翻译，用于不花 API 额度验证排版链路
- 翻译与 OCR 缓存（`.cache/`），支持断点续跑
- 批量翻译：一页 200+ 条文本合并为十几次请求
- CLI 新增 `--pages` / `--max-pages` / `--list-engines` / `--translate-images` / `--dpi` / `--font`

### Changed (v0.3)

- PDF 生成改为**在源 PDF 副本上原地改写**（文字页用 redaction 删除原文），
  不再从零新建空白页 → 图片、矢量、版式 100% 保留
- 目录结构：PDF/DOCX 编排逻辑从 `main.py` / `dispatcher.py` 迁到
  `core/pdf_translator.py` / `core/docx_translator.py`
- `config.py` 不再使用 `os.uname()`（Windows 也能启动），配置分区重排
- `requirements.txt` 补上 `python-docx`，移除未使用的 `reportlab` / `fpdf2` / `pymupdf4llm`

### Removed (v0.3)

- `SimplePDFGenerator`（依赖 reportlab 的备选方案，未被任何代码调用）
- `docx_writer.py` 中未使用的 `_build_translation_map` / `_replace_*` 死代码

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
