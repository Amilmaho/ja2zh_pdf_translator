# DEVELOPMENT_PLAN.md — 详细开发计划

> ⚠️ 本文档为实施计划，**不做任何代码修改**，等待确认后执行。

---

## 总体策略

采用**渐进式演进**策略：
1. 每个 Phase 独立完成、独立可用
2. 新代码不破坏已有功能
3. 先加接口，后重构实现
4. 每次只改最小必要的文件

---

## Phase 2: Web UI（预计 3-5 天）

### 目标
本地 Web 界面，替代 CLI，成为主要交互方式。

### 技术选型确认
| 技术 | 说明 |
|------|------|
| **FastAPI** | Web 框架（异步、WebSocket/SSE 原生支持） |
| **Jinja2** | 模板引擎（FastAPI 内置） |
| **原生 HTML/CSS/JS** | 前端（无需 React/Vue，降低复杂度） |
| **SSE** | 服务端推送日志和进度（优于轮询） |
| **uvicorn** | ASGI 服务器 |

### 预计文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `web/app.py` | **新增** | FastAPI 应用、路由、SSE、文件上传 |
| `web/templates/index.html` | **新增** | 主页面（拖拽上传、设置、进度） |
| `web/static/style.css` | **新增** | 样式（现代简洁 UI） |
| `web/static/app.js` | **新增** | 前端交互（拖拽、SSE 监听、进度条） |
| `requirements.txt` | **修改** | 添加 `fastapi`, `uvicorn`, `python-multipart` |
| `main.py` | **不修改** | Web UI 通过 import 调用核心类 |

### 代码复用

| 核心模块 | 复用方式 |
|----------|----------|
| `JapanesePDFTranslator` | `from main import JapanesePDFTranslator` 直接调用 |
| `config.py` | Web UI 设置页面读写 Config |
| `ocr_engine.py` | 零修改 |
| `translator.py` | 零修改 |
| `pdf_generator.py` | 零修改 |

### 接口抽象

```python
# web/app.py 核心设计

# SSE 进度推送
async def event_generator(task_id: str):
    """从 TaskManager 获取进度，通过 SSE 推送到前端"""
    while True:
        progress = task_manager.get_progress(task_id)
        yield f"data: {json.dumps(progress)}\n\n"
        if progress.status in ("completed", "failed"):
            break

# 文件上传
@app.post("/api/upload")
async def upload_file(file: UploadFile):
    """保存文件，检测格式，返回 file_id"""
    ...

# 启动翻译
@app.post("/api/translate")
async def start_translation(file_id: str, options: TranslateOptions):
    """创建后台任务，返回 task_id"""
    ...

# 下载结果
@app.get("/api/download/{task_id}")
async def download_result(task_id: str):
    """返回翻译后的文件"""
    ...
```

### 风险
| 风险 | 级别 | 缓解措施 |
|------|------|----------|
| 大文件上传超时 | 🟡 中 | chunked upload + 进度反馈 |
| 翻译任务阻塞 Web 请求 | 🔴 高 | 使用 `BackgroundTasks` 异步执行 |
| SSE 断连 | 🟢 低 | 前端自动重连 |
| macOS 本地端口冲突 | 🟢 低 | 默认 8000，可配置 |

---

## Phase 3: PDF 页码范围增强（已完成 ✅）

### 状态
页码范围解析和指定页处理已经在 `main.py` 中实现并测试通过。
- `_parse_page_range("1-10")` → `[1,2,3,4,5,6,7,8,9,10]`
- `_parse_page_range("1,5,8,20-30")` → `[1,5,8,20,21,...,30]`
- OCR 只处理指定页 ✅
- 翻译只处理指定页 ✅

### Web UI 集成
- 设置面板添加页码范围输入框
- 前端验证格式
- 传给 `/api/translate` 的 `page_range` 参数

---

## Phase 4: DOCX Reader（预计 2-3 天）

### 目标
读取 DOCX 文件，提取文字、表格、图片，转为统一 `Document` 数据结构。

### 预计文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `modules/docx_reader.py` | **新增** | DOCXReader 类 |
| `requirements.txt` | **修改** | 添加 `python-docx` |
| `main.py` | **修改** | 格式检测 + DOCX 路由（约 20 行）|
| `modules/__init__.py` | 不修改 | - |

### 代码复用

| 核心模块 | 复用方式 |
|----------|----------|
| `OCREngine` | DOCX 图片 → `ocr.recognize(image)` |
| `TranslationEngine` | DOCX 文字 → `translator.translate(text)` |
| `PageContent` / `TextBlock` / `ImageBlock` | 直接复用数据结构 |

### 接口设计

```python
# modules/docx_reader.py

class DOCXReader:
    """DOCX 读取器"""
    
    def __init__(self, file_path: str, temp_dir: str):
        self.file_path = file_path
        self.temp_dir = temp_dir
    
    def extract_all(self) -> Document:
        """提取 DOCX 全部内容"""
        pages = []
        # 1. 解析段落（保持样式信息）
        # 2. 解析表格（单元格逐行处理）
        # 3. 提取内嵌图片 → 保存到 temp_dir
        # 4. 解析页眉页脚
        return Document(source_path=self.file_path, pages=pages)
    
    def extract_text_only(self) -> List[str]:
        """仅提取纯文本（用于全文翻译）"""
        ...
```

### 风险
| 风险 | 级别 | 缓解措施 |
|------|------|----------|
| DOCX 复杂排版（多栏）| 🟡 中 | 先支持单栏，多栏标记 TODO |
| 表格嵌套 | 🟢 低 | 递归处理 |
| 内嵌图片格式多样 | 🟡 中 | PIL 转换统一格式 |
| 页眉页脚样式丢失 | 🟡 中 | 记录样式，Writer 阶段恢复 |

---

## Phase 5: DOCX Writer（预计 2-3 天）

### 目标
将翻译后的内容写回 DOCX，保持原始格式。

### 预计文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `modules/docx_writer.py` | **新增** | DOCXWriter 类 |
| `main.py` | **修改** | 添加 DOCX 输出路由（约 15 行）|
| `modules/docx_reader.py` | 不修改 | - |

### 代码复用

| 核心模块 | 复用方式 |
|----------|----------|
| `OCREngine` | 不需要（OCR 已在 Reader 阶段完成） |
| `TranslationEngine` | 不需要（翻译已在流程中完成） |
| `PDFGenerator` | 不修改 |

### 接口设计

```python
# modules/docx_writer.py

class DOCXWriter:
    """DOCX 生成器"""
    
    def write(
        self,
        document: Document,              # 翻译后的 Document
        template_path: str,              # 原始 DOCX（作为样式模板）
        output_path: str
    ) -> str:
        """生成翻译后的 DOCX"""
        # 1. 基于 template 复制文档结构
        # 2. 逐段落替换翻译文字（保持格式）
        # 3. 表格逐单元格替换
        # 4. 图片区域嵌入 OCR 翻译结果
        # 5. 页眉页脚替换
        return output_path
```

### 保持的内容
- ✅ 字体、字号、颜色
- ✅ 段落对齐、缩进、行距
- ✅ 表格结构、边框、合并单元格
- ✅ 页眉页脚
- ✅ 分页符

### 风险
| 风险 | 级别 | 缓解措施 |
|------|------|----------|
| 中文字体在 DOCX 中不显示 | 🔴 高 | 嵌入字体或降级为系统字体 |
| 翻译后文字长度变化破坏排版 | 🟡 中 | 允许区域扩展，限制表格单元格 |
| 图片 OCR 翻译叠加 | 🟡 中 | 图片旁添加文字框（不修改原图） |

---

## Phase 6: 统一 Parser（预计 2-3 天）

### 目标
创建统一的 `DocumentParser` 抽象基类，重构 PDF/DOCX Reader。

### 预计文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `modules/parser.py` | **新增** | DocumentParser 基类 + 数据模型 |
| `modules/pdf_extractor.py` | **重构** | 改为 PDFParser(DocumentParser) |
| `modules/docx_reader.py` | **重构** | 改为 DOCXParser(DocumentParser) |
| `main.py` | **修改** | 使用统一 Parser 接口 |
| `config.py` | **修改** | 添加 Parser 注册表 |

### 接口抽象

```python
# modules/parser.py

from abc import ABC, abstractmethod

class DocumentParser(ABC):
    """文档解析器基类"""
    
    @abstractmethod
    def parse(self, file_path: str, options: ParseOptions = None) -> Document:
        """解析文件 → 统一 Document"""
        ...

def create_parser(file_path: str) -> DocumentParser:
    """工厂函数：根据文件扩展名创建 Parser"""
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return PDFParser()
    elif ext == ".docx":
        return DOCXParser()
    ...
```

---

## Phase 7: 统一 Translation Engine（预计 1-2 天）

### 目标
标准化 Translation Engine 接口，支持批量翻译、缓存、术语表。

### 预计文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `modules/translator.py` | **重构** | 标准化接口，添加缓存 |
| `modules/translation_cache.py` | **新增** | 翻译缓存（SQLite/JSON） |
| `modules/glossary.py` | **新增** | 术语表管理 |

### 风险
| 风险 | 级别 | 缓解措施 |
|------|------|----------|
| 缓存一致性 | 🟢 低 | 基于原文 hash 做 key |
| 术语表匹配性能 | 🟢 低 | 加载到内存 dict |

---

## Phase 8: 统一 OCR Engine（预计 1-2 天）

### 目标
标准化 OCR Engine 接口，支持更多 Provider。

### 预计文件变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `modules/ocr_engine.py` | **重构** | 标准化接口，添加 PaddleOCR |
| `modules/ocr_cache.py` | **新增** | OCR 结果缓存（避免重复识别） |

---

## 总结：各 Phase 影响范围

```
Phase 2 (Web UI):      新增 web/ 目录, 修改 requirements.txt, main.py 不修改
Phase 3 (页码范围):    已完成 ✅
Phase 4 (DOCX Reader): 新增 modules/docx_reader.py, 修改 main.py（20行）
Phase 5 (DOCX Writer): 新增 modules/docx_writer.py, 修改 main.py（15行）
Phase 6 (统一Parser):   新增 modules/parser.py, 重构 pdf_extractor + docx_reader
Phase 7 (统一Trans):    重构 modules/translator.py, 新增 cache
Phase 8 (统一OCR):      重构 modules/ocr_engine.py, 新增 cache
```

**核心原则**：OCR、Translation 从 Phase 2 到 Phase 8 **零修改**（只需扩展，不需改动）。
