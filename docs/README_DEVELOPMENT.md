# README_DEVELOPMENT.md — 开发者指南

## 🚀 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key
cp .env.example .env   # 然后编辑填入你的 Key

# 3. 运行
python main.py input/your_file.pdf
```

---

## 📂 项目结构

```
ja2zh_pdf_translator/
├── main.py                 # CLI 入口，流程编排
├── config.py               # 全局配置（Config 类）
├── modules/
│   ├── pdf_extractor.py    # PDF 解析器
│   ├── ocr_engine.py       # OCR 引擎
│   ├── translator.py       # 翻译引擎
│   └── pdf_generator.py    # PDF 生成器
├── docs/                   # 所有文档
│   ├── PROJECT_SPEC.md     # 项目规格
│   ├── ARCHITECTURE.md     # 架构（含 Mermaid 图）
│   ├── ROADMAP.md          # 路线图
│   ├── TASKS.md            # 当前任务（必读！）
│   ├── DESIGN.md           # 设计决策
│   └── CHANGELOG.md        # 变更日志
```

---

## 🔌 如何新增 Parser（如 DOCX Reader）

### 步骤

1. 创建 `modules/docx_reader.py`
2. 定义数据类（复用 `PageContent` / `TextBlock` / `ImageBlock`）
3. 实现 `DOCXReader` 类，提供 `extract_all()` 方法
4. 在 `main.py` 中添加格式检测和路由

### 接口约定

```python
class DOCXReader:
    def extract_all(self) -> List[PageContent]:
        """提取 DOCX 中所有页面的内容（文字块 + 图片块）"""
        ...

    def extract_text_only(self) -> List[str]:
        """仅提取纯文本（不含图片）"""
        ...
```

### 必须遵循的规则
- ✅ 返回 `List[PageContent]`，与 PDF 提取器一致
- ✅ 图片块使用 `ImageBlock` 数据结构
- ❌ 不要在 Reader 中直接调用 OCR 或 Translation

---

## 📝 如何新增 Writer（如 DOCX Writer）

### 步骤

1. 创建 `modules/docx_writer.py`
2. 实现 `DOCXWriter` 类

### 接口约定

```python
class DOCXWriter:
    def generate(
        self,
        original_docx_path: str,
        pages_content: List[PageContent],
        translated_texts: List[List[str]],
        ocr_results_per_page: List[list]
    ) -> str:
        """生成翻译后的 DOCX，返回输出路径"""
        ...
```

---

## 🔍 如何新增 OCR Provider

### 步骤

1. 在 `modules/ocr_engine.py` 中新增一个继承 `OCREngine` 的类
2. 实现 `recognize(image: Image) -> List[OCRResult]`
3. 在 `config.py` 中 `OCR_ENGINE` 选项添加新引擎名
4. 在 `create_ocr_engine()` 工厂函数中添加 `elif`

### 示例：添加 PaddleOCR

```python
class PaddleOCREngine(OCREngine):
    def __init__(self):
        from paddleocr import PaddleOCR
        self.ocr = PaddleOCR(lang='japan')

    def recognize(self, image: Image.Image) -> List[OCRResult]:
        import numpy as np
        result = self.ocr.ocr(np.array(image))
        # 转换为 OCRResult 列表...
```

---

## 🌐 如何新增 Translation Provider

### 步骤

1. 在 `modules/translator.py` 中新增一个继承 `TranslationEngine` 的类
2. 实现 `translate(text: str) -> str`
3. 在 `config.py` 添加配置项
4. 在 `create_translation_engine()` 工厂函数中添加 `elif`

### 示例：添加 Claude 翻译

```python
class ClaudeTranslateEngine(TranslationEngine):
    def __init__(self, api_key: str = None):
        from anthropic import Anthropic
        self.client = Anthropic(api_key=api_key)

    def translate(self, text: str) -> str:
        response = self.client.messages.create(
            model="claude-3-opus-20240229",
            messages=[{"role": "user", "content": f"翻译成中文：{text}"}]
        )
        return response.content[0].text
```

---

## 🧪 运行测试

```bash
# （未来）单元测试
python -m pytest tests/

# （未来）集成测试
python -m pytest tests/integration/
```

---

## 📋 开发流程

1. 从 `TASKS.md` 选取一个任务
2. 读取 `DESIGN.md` 确认设计决策
3. 在对应模块中实现
4. 更新 `TASKS.md` 标记完成
5. 更新 `CHANGELOG.md` 记录变更
6. 如有架构变化，更新 `ARCHITECTURE.md`
7. 如有设计决策，记录到 `DESIGN.md`

---

## ⚠️ 禁止操作

- ❌ 跨模块直接调用（如 OCR 模块调用翻译模块）
- ❌ 硬编码配置（必须通过 `config.py`）
- ❌ 删除现有功能再重建
- ❌ 在 `main.py` 中写具体业务逻辑
