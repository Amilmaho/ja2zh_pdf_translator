# TASKS.md — 当前任务与状态

> ⚠️ **Agent 每次开发前必须读取此文件**

---

## 🟢 当前执行中的任务

| # | 任务 | 状态 | 负责人 | 备注 |
|---|------|------|--------|------|
| - | 暂无进行中任务 | - | - | 等待用户确认 Phase 4 Step 1 |

---

## ✅ Phase 4 Step 1: DOCX Reader — 已完成

### 新增文件
| 文件 | 行数 | 说明 |
|------|------|------|
| `modules/docx_reader.py` | ~360 | DocxReader — 段落/标题/表格/图片/页眉页脚提取 |

### 修改文件
| 文件 | 修改 |
|------|------|
| `requirements.txt` | +python-docx |
| `docs/ARCHITECTURE.md` | 添加 docx_reader.py |
| `docs/TASKS.md` | 更新任务状态 |
| `docs/CHANGELOG.md` | 记录变更 |

### 数据结构
| 类 | 说明 |
|------|------|
| `DocxContent` | DOCX 完整提取结果容器 |
| `DocxParagraph` | 普通段落（文字 + 样式） |
| `DocxHeading` | 标题（级别 1-9 + 文字） |
| `DocxTable` | 表格（二维单元格） |
| `DocxTableCell` | 表格单元格（行列坐标 + 文字） |
| `DocxImage` | 图片（保存到磁盘 + 映射关系） |

### 能力矩阵
| 功能 | 状态 |
|------|------|
| 读取 .docx | ✅ |
| 提取段落（含样式） | ✅ |
| 提取标题（H1-H9） | ✅ |
| 提取表格（行列+样式） | ✅ |
| 识别并保存图片 | ✅ |
| 提取页眉页脚 | ✅ |
| summary() 结构摘要 | ✅ |
| OCR | ❌ 不在此阶段 |
| 翻译 | ❌ 不在此阶段 |
| 生成 DOCX | ❌ 不在此阶段 |

### 设计原则遵守
- ✅ 完全独立，不依赖 PDF 模块
- ✅ 不调用 OCR（图片只保存和建立映射）
- ✅ 不调用翻译
- ✅ 不修改任何 PDF 功能
- ✅ 复用现有项目结构（modules/ 目录）

### 新增文件
| 文件 | 说明 |
|------|------|
| `core/__init__.py` | 核心调度层包 |
| `core/task_manager.py` | TaskManager — 任务创建/执行/状态/日志/SSE回调 |
| `core/dispatcher.py` | DocumentDispatcher — 格式分派 + PDF 适配器 + 预留接口 |

### 修改文件
| 文件 | 修改 |
|------|------|
| `web/app.py` | 重构：所有翻译请求通过 TaskManager（不再直连 JapanesePDFTranslator） |
| `docs/ARCHITECTURE.md` | 添加 core/ 层、新模块关系图 |
| `docs/TASKS.md` | 更新任务状态 |
| `docs/CHANGELOG.md` | 记录变更 |

### 调用链
```
Web UI → TaskManager → DocumentDispatcher → PDFTranslator(适配器) → JapanesePDFTranslator
              ↑                                    ↑
         CLI 也可调用                        未来: DOCX/Image/PPTX/EPUB
```

### 关键设计决策
| 决策 | 说明 |
|------|------|
| DocumentTranslator 抽象基类 | 所有格式 Translator 的统一接口 |
| PDFTranslator 是适配器 | 封装 JapanesePDFTranslator，不修改其代码 |
| TaskManager 全局单例 | Web UI 和 CLI 共享同一个实例 |
| SSE 回调机制 | TaskManager._log_callbacks 注册模式，完全解耦 |
| 预留接口不实现 | DOCX/Image/PPTX/EPUB Translator 只有接口签名 + NotImplementedError |

---

## ✅ Phase 2 Step 1: Web UI 基础框架 — 已完成

### 新增文件
| 文件 | 说明 |
|------|------|
| `web/app.py` | FastAPI 应用：文件上传/设置管理/SSE日志/模拟日志 |
| `web/templates/index.html` | 主页面：拖拽上传区 + 设置面板 + 日志区 |
| `web/static/style.css` | 样式：暗色日志/响应式/拖拽动画 |
| `web/static/app.js` | 前端：拖拽上传/SSE日志流/文件管理 |

### 修改文件
| 文件 | 修改 |
|------|------|
| `requirements.txt` | +fastapi, uvicorn, python-multipart, sse-starlette |
| `CHANGELOG.md` | 记录变更 |
| `TASKS.md` | 更新任务状态 |

### ⚠️ 已知问题
| # | 问题 | 说明 |
|---|------|------|
| W1 | Jinja2 500错误 | `Jinja2Templates` 的 `env.globals` 与 Starlette 兼容性问题，已通过移除 `request` 参数修复 |
| W2 | 模板 500 | 问题在 FastAPI + Jinja2Templates 的 `url_for` 注入机制，当前通过简化模板变量绕过 |

### 如何启动
```bash
cd /Users/qwe123/Desktop/work/ja2zh_pdf_translator
python3 -m uvicorn web.app:app --host 0.0.0.0 --port 8000
# 浏览器: http://127.0.0.1:8000
```

### 可用 API
| Method | Path | 说明 |
|--------|------|------|
| GET | `/` | 主页面 |
| GET | `/api/health` | 健康检查 |
| POST | `/api/upload` | 批量上传文件 |
| DELETE | `/api/upload/{id}` | 删除文件 |
| GET | `/api/files` | 文件列表 |
| GET | `/api/settings` | 获取设置 |
| POST | `/api/settings` | 更新设置（预留） |
| GET | `/api/logs/{task_id}` | SSE 日志流 |
| POST | `/api/test-log` | 模拟日志（测试用） |

### 下一步（等待确认）
| # | 任务 | 修改文件 |
|---|------|----------|
| 2.2 | 接入翻译逻辑 | `web/app.py` + `main.py` |
| 2.3 | 设置持久化（.env读写） | `web/app.py` + `config.py` |

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
