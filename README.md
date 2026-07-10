# 日文文档翻译工具 🇯🇵 → 🇨🇳
（测试中）

将日文 PDF 和 DOCX 自动翻译为简体中文。支持文字型文档和图片型扫描件。

🖥️ **macOS** · **Windows** · **Linux** 全平台可用

---

## ✨ 功能列表

| 特性 | 说明 |
|---|---|
| 🔤 **PDF 翻译** | 文字型原位替换 · 图片型 OCR + 白底中文叠加 |
| 📄 **DOCX 翻译** | 提取段落/标题/表格 → AI 翻译 → 保持样式写回 |
| 🌐 **四种翻译引擎** | DeepSeek（推荐）/ Google（免费）/ OpenAI / DeepL |
| 🔍 **双 OCR 引擎** | EasyOCR（句子级，GPU 加速）/ Tesseract（字级，CPU） |
| 📖 **页码范围** | `1-5`、`1,3,5`、`1-5,10-20` 灵活指定 |

---

## 🖥️ 系统要求

- **Python**：3.9+
- **操作系统**：macOS / Windows / Linux
- **内存**：≥ 4 GB（EasyOCR 约需 2 GB）

---

## 📦 安装

```bash
git clone https://github.com/Amilmaho/ja2zh_pdf_translator.git
cd ja2zh_pdf_translator
pip install -r requirements.txt
```

## ⚙️ 配置

创建 `.env` 文件：

```env
DEEPSEEK_API_KEY=sk-your-key     # 推荐，约 ¥0.5~1/300页
```

> 🔑 [免费注册 DeepSeek](https://platform.deepseek.com/api_keys)

---

## 🚀 CLI 命令

```bash
# PDF 翻译
python main.py input/your_file.pdf

# DOCX 翻译
python main.py input/your_file.docx

# 页码范围（PDF）
python main.py input/your_file.pdf --pages 1-5
python main.py input/your_file.pdf --pages 1-5,10-20

# 引擎选择（PDF + DOCX 通用）
python main.py input/your_file.docx --translator google
python main.py input/your_file.docx --ocr tesseract

# 指定输出路径
python main.py input/your_file.docx -o output/result.docx

# 完整帮助
python main.py --help
```

---

## 📋 支持格式

| 格式 | 读取 | OCR | 翻译 | 输出 |
|------|------|-----|------|------|
| **PDF** | ✅ | ✅ | ✅ | ✅ PDF |
| **DOCX** | ✅ | ✅ | ✅ | ✅ DOCX |

---

## 🔧 翻译引擎

| 引擎 | 费用 | 质量 | 网络 |
|------|------|------|------|
| **DeepSeek** | ≈ ¥0.5~1/300页 | ⭐⭐⭐⭐ | 国内直连 |
| **Google** | 免费 | ⭐⭐⭐ | 可能需代理 |
| **OpenAI** | ≈ ¥3~5/300页 | ⭐⭐⭐⭐⭐ | 需代理 |
| **DeepL** | 按量付费 | ⭐⭐⭐⭐ | 需代理 |

---

## 🔍 OCR 引擎

| | EasyOCR | Tesseract |
|------|---------|------------|
| **粒度** | 句子级 | 单字级 |
| **可用率** | ≈ 59% | ≈ 12% |
| **速度** | ≈ 12s/页(GPU) | ≈ 3s/页 |
| **GPU** | ✅ MPS/CUDA | ❌ |

> 💡 轻小说/漫画类 PDF 推荐 EasyOCR。Tesseract 适合纯文字扫描件。

---

## 📁 项目结构

```
ja2zh_pdf_translator/
├── main.py                     # CLI 入口
├── config.py                   # 全局配置
├── core/                       # 核心调度层
│   ├── task_manager.py         # 任务管理
│   └── dispatcher.py           # 格式分派
├── modules/                    # 业务模块
│   ├── pdf_extractor.py        # PDF 提取
│   ├── ocr_engine.py           # OCR 引擎
│   ├── translator.py           # 翻译引擎
│   ├── pdf_generator.py        # PDF 生成
│   ├── docx_reader.py          # DOCX 读取
│   └── docx_writer.py          # DOCX 写入
├── docs/                       # 开发文档
├── input/                      # ← 待翻译文件
├── output/                     # ← 翻译结果
└── temp/                       # 临时文件
```

---

## 🐛 常见问题

### Q: EasyOCR 下载模型失败？

macOS：`/Applications/Python\ 3.12/Install\ Certificates.command`  
备选：`--ocr tesseract`  
手动：下载模型到 `~/.EasyOCR/model/`

### Q: 翻译后只有白色方块？

已修复。渲染失败自动缩字号重试，仍失败则灰度显示原文。

### Q: 中文显示为方块？

自动检测系统字体。手动指定：`.env` 中 `FONT_PATH=/path/to/font.ttc`

### Q: Tesseract 缺少日语语言包？

macOS：`brew install tesseract-lang`  
手动：[jpn.traineddata](https://github.com/tesseract-ocr/tessdata/raw/main/jpn.traineddata)

---

## 📄 License

MIT
