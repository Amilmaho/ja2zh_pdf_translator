# PROJECT_SPEC.md — 项目规格说明

## 📌 项目目标

将 ja2zh_pdf_translator 从"单文件 PDF 翻译工具"演进为**可维护、可扩展的本地文档翻译平台**。

最终支持格式：PDF / DOCX / PPTX / EPUB / PNG / JPG
核心子系统：OCR、Translation、Parser、Writer、WebUI — 完全解耦。

---

## 🧭 开发规范

### 编码规范
1. Python 3.9+，使用类型提示（Type Hints）
2. 文件名: `snake_case.py`；类名: `PascalCase`；函数名: `snake_case`
3. 所有公开方法必须有 docstring
4. 使用 `dataclass` 定义数据传输对象
5. 配置集中在 `config.py`，禁止硬编码
6. 使用 `logging` 模块替代 `print()`（逐步迁移）
7. import 顺序：标准库 → 第三方库 → 本项目模块

### Git 规范
1. 每个 commit 只做一件事
2. commit message 格式: `type(scope): description`
   - type: feat / fix / refactor / docs / test / chore
3. 不提交 `.env`、`temp/`、`output/` 中的大文件

### 测试规范
1. 核心模块（OCR、Translation）必须有单元测试
2. 集成测试放在 `tests/` 目录
3. 测试命名: `test_<模块名>.py`

---

## 📦 模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| CLI 入口 | `main.py` | 参数解析、流程编排、进度报告 |
| 配置系统 | `config.py` | 集中管理所有配置项、环境变量 |
| PDF 提取器 | `modules/pdf_extractor.py` | PDF → TextBlock + ImageBlock（保留位置） |
| OCR 引擎 | `modules/ocr_engine.py` | Image → OCRResult（EasyOCR / Tesseract） |
| 翻译引擎 | `modules/translator.py` | 日文 Text → 中文 Text（4种引擎） |
| PDF 生成器 | `modules/pdf_generator.py` | 翻译结果 → 新 PDF（文字替换 / 图片叠加） |

---

## 🤖 Agent 工作流程

每个 AI Agent 在接到任务时必须：
1. 读取 `TASKS.md` — 了解当前任务状态
2. 读取 `ARCHITECTURE.md` — 理解模块关系
3. 读取 `DESIGN.md` — 理解设计决策
4. 完成后更新 `TASKS.md` 和 `CHANGELOG.md`
5. 如有架构决策，记录到 `DESIGN.md`

---

## 🚫 禁止事项

⚠️ 以下操作在任何阶段都禁止：
1. **直接修改业务逻辑而不先提出设计文档**
2. **跨模块耦合**（如 OCR 模块直接调用翻译模块）
3. **删除现有功能再重建**（必须渐进式演进）
4. **修改 `config.py` 中已有配置项的默认值而不更新文档**
5. **引入不必要的大型依赖**

---

## 🔮 未来扩展方向

1. Web UI（拖拽上传、实时日志）
2. DOCX Reader/Writer（文字、表格、页眉页脚、图片OCR）
3. PPTX Reader/Writer
4. EPUB Reader/Writer
5. 图片文件直接翻译（PNG/JPG）
6. 批量翻译队列
7. 翻译记忆库（TMX）
8. 术语表管理
9. 插件系统（自定义 Parser / Writer / OCR Provider）
