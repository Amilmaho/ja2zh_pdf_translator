# 日文文档翻译工具 🇯🇵 → 🇨🇳

把日文 **PDF / DOCX** 翻译成简体中文。文字型文档原位替换，扫描件/图片型文档
走 OCR 后在原图上叠加中文，尽量保留原始版面。

🖥️ **macOS** · **Windows** · **Linux**

---

## ✨ 功能

| 特性 | 说明 |
|---|---|
| 🔤 **文字型 PDF** | 精确删除原文（redaction）→ 写入译文，图片和矢量图形完整保留 |
| 🖼️ **图片型 PDF** | OCR 识别 → 按区域底色覆盖 → 写入译文，**深色页面也不会被涂白** |
| 📄 **DOCX** | 段落/标题/表格/页眉页脚翻译，保持原样式；可选用译文重绘内嵌图片 |
| 🌐 **五种翻译引擎** | DeepSeek（推荐）/ Google（免费）/ OpenAI / DeepL / Dummy（离线自测） |
| 🔍 **两种 OCR** | EasyOCR（句子级，推荐）/ Tesseract（字级） |
| ⚡ **批量翻译** | 一页 200+ 个文本块合并成十几次 API 请求（旧版是 200+ 次） |
| 💾 **断点续跑** | OCR 结果与译文都带缓存，重跑同一页几乎不耗时 |
| 📖 **页码范围** | `1-5`、`1,3,5`、`1-5,10-20`，只处理需要的页 |
| 🧪 **自检** | 生成后回读输出，逐区域确认「真的写进了文字」，不留空白色块 |
| 📐 **字号自动标定** | 从原图量出字形实际大小，译文与原文等大（而不是被 OCR 框撑大 30%） |
| 🖋️ **字体风格可选** | 默认宋体（贴近日文印刷品的明朝体），可切黑体 |

---

## 🚀 快速开始

```bash
git clone https://github.com/Amilmaho/ja2zh_pdf_translator.git
cd ja2zh_pdf_translator
pip install -r requirements.txt

cp .env.example .env      # 填入 DEEPSEEK_API_KEY

python main.py input/your_file.pdf
```

> 🔑 DeepSeek Key 申请：https://platform.deepseek.com/api_keys

---

## 🖥️ CLI 命令

```bash
# 翻译整个 PDF
python main.py input/book.pdf

# 只翻译第 1-5 页（推荐的试跑方式）
python main.py input/book.pdf --pages 1-5

# 多段页码范围
python main.py input/book.pdf --pages 1-5,10-20

# 只处理前 2 页，快速验证
python main.py input/book.pdf --max-pages 2

# 离线伪翻译：不调用 API，专门用来看排版效果
python main.py input/book.pdf --pages 100-101 --translator dummy

# 换 OCR 引擎
python main.py input/book.pdf --ocr tesseract

# 文字型页面里的插图也翻译（更慢）
python main.py input/book.pdf --translate-images

# DOCX
python main.py input/doc.docx --translator deepseek
python main.py input/doc.docx --translate-images      # 连内嵌图片一起翻译

# 查看当前可用引擎 / 自动检测到的中文字体
python main.py --list-engines
```

**常用参数**

| 参数 | 说明 |
|---|---|
| `--pages 1-5,10` | 页码范围（1 起始），只对 PDF 生效 |
| `--max-pages N` | 最多处理 N 页，用于试跑 |
| `--translator` | `deepseek` / `google` / `openai` / `deepl` / `dummy` |
| `--ocr` | `easyocr` / `tesseract` |
| `--translate-images` | 也翻译图片里的文字 |
| `--dpi` | 整页渲染给 OCR 用的 DPI（默认 200） |
| `--font` | 指定中文字体文件 |
| `-q` | 安静模式 |

---

## 🌐 Web UI

```bash
uvicorn web.app:app --reload --port 8000
# 打开 http://127.0.0.1:8000
```

支持拖拽上传、页码范围、引擎选择、SSE 实时日志、完成后自动下载。

---

## 🔧 翻译引擎

| 引擎 | 费用 | 说明 |
|---|---|---|
| **DeepSeek** | ≈ ¥0.5~1 / 300 页 | 国内直连，支持批量，默认推荐 |
| **Google** | 免费 | 通过 deep-translator，可能需代理 |
| **OpenAI** | 较贵 | 质量高，需代理 |
| **DeepL** | 按量付费 | 需另装 `deepl` 包 |
| **Dummy** | 免费 | 离线伪翻译，只用于验证排版链路 |

---

## 🔍 OCR 引擎

| | EasyOCR | Tesseract |
|---|---|---|
| 粒度 | 句子级 | 单字级 |
| 日文效果 | 好（推荐） | 一般 |
| 速度 | CPU ≈ 10~15s/页 | ≈ 3s/页 |
| 依赖 | torch（首次需下载模型） | 需安装 tesseract + jpn 语言包 |

低置信度的识别区域**不会被翻译，也不会被覆盖**，原图文字保持原样。

---

## 📁 项目结构

```
ja2zh_pdf_translator/
├── main.py                      # CLI 入口
├── config.py                    # 全局配置（路径/翻译/OCR/渲染 分区）
├── core/
│   ├── pdf_translator.py        # PDF 编排：提取 → OCR → 翻译 → 生成 → 自检
│   ├── docx_translator.py       # DOCX 编排
│   ├── dispatcher.py            # 按扩展名分派
│   └── task_manager.py          # Web 任务与 SSE 日志
├── modules/
│   ├── pdf_extractor.py         # 逐行提取文字 + 图片 + 整页渲染
│   ├── ocr_engine.py            # EasyOCR / Tesseract（GPU 自动探测 + 缓存）
│   ├── translator.py            # 五种引擎（批量 + 缓存 + 重试）
│   ├── text_layout.py           # 文本测宽/换行/自适应字号（防空白的关键）
│   ├── pdf_generator.py         # 在原 PDF 副本上写入译文
│   ├── image_overlay.py         # DOCX 内嵌图片的译文重绘
│   ├── fonts.py                 # 中文字体发现与字形校验
│   ├── docx_reader.py           # DOCX 提取
│   └── docx_writer.py           # DOCX 写回（保留样式）
├── tools/verify_pipeline.py     # 端到端自检脚本
├── web/                         # FastAPI Web UI
├── input/  output/  temp/       # 输入 / 输出 / 中间文件
└── .cache/                      # OCR 与翻译缓存（可安全删除）
```

---

## 🧪 自检脚本

改完代码或换文档后，先跑这个：

```bash
python tools/verify_pipeline.py input/book.pdf --pages 100-102 --visual
```

它会翻译指定页面，然后逐项检查并输出报告：

1. **空白色块**：有没有「涂了底色却没有文字」的区域
2. **底色一致性**：覆盖色是否与原图底色一致（深色栏位不能被涂白）
3. **放不下的区域**：有多少区域因排版失败而保留原文
4. **墨量对比**：输出页与源页的墨量是否量级相当

`--visual` 会额外导出 `before/after` PNG 方便肉眼比对。

---

## 🐛 常见问题

### Q: 为什么以前翻译出来的图片大部分是空白？

旧版是「先画白底 → 再用 `insert_textbox` 试写」，写不进去就什么都不画，
于是留下一堆白块；遇到深色页面（漫画、深色表格栏）尤其明显。

现在改成「先排版确认放得下 → 再覆盖 + 写入」：

- 放不下就不覆盖，保留原图文字
- 覆盖色取自原图底色，深色栏位填深色
- 生成后回读输出逐区域自检

### Q: 有些文字没有翻译？

优先看日志里的「保留原文 / 放不下 / 查漏补识别」数量。常见原因：

- 识别结果被判定为噪声（空文本、纯符号、页边页码条、极短碎片）→ 保持原样
- 区域太小放不下译文 → 可调小 `OVERLAY_MIN_FONT`（如 2.5）
- 翻译接口失败 → 保留原文并在日志中提示

### Q: 译文里还混着日文（假名 / 未翻译的整行）？

程序已经内置三道防线，正常情况下不会出现：

1. **不按置信度一刀切**：EasyOCR 对复杂汉字的置信度普遍偏低（很多完全读对的
   文本只有 0.0~0.3），所以只用置信度筛「极短噪声」，其余都翻译。
2. **查漏补识别**：第一遍 OCR 偶尔整行漏检，程序会自动找出「原图有墨、
   但没有识别框」的行，裁剪放大后重新识别并补翻译。
3. **假名检测**：译文里若残留假名（例如 サンサーラ→萨ンサーラ），
   会用「禁止假名」的提示词自动重译一次。

如果仍然看到日文，把那一页的日志发我 —— 日志里会写明是「保留原文」
还是「放不下」。

### Q: 首次运行卡在下载 EasyOCR 模型？

模型会下载到 `~/.EasyOCR/model`（约 100MB）。网络不畅时：

```bash
python main.py input/book.pdf --ocr tesseract     # 换 Tesseract
```

macOS 补语言包：`brew install tesseract-lang`

### Q: 中文显示成方块 / 报「未找到可渲染中文的字体」？

程序会自动检测并**校验字形覆盖**（只认真的包含中日文字的字体）。
也可以手动指定：

```env
FONT_PATH=/System/Library/Fonts/Hiragino Sans GB.ttc
```

### Q: 太慢了怎么办？

- 用 `--pages` / `--max-pages` 缩小范围
- 没有 GPU 时 EasyOCR 走 CPU，约 10~15 秒/页；`--ocr tesseract` 更快
- 重跑同一批页面会命中缓存，几乎不耗时

### Q: 翻译缓存放在哪里？可以删吗？

`.cache/ocr` 与 `.cache/translate`。可以直接删除，删掉后只会重新花钱/耗时。

### Q: 想换字体风格？

```env
FONT_STYLE=sans                              # 黑体（技术手册、漫画更合适）
FONT_PATH=/Library/Fonts/xxx.ttc             # 直接指定字体文件
```

程序会自动跳过「缺字形」或「无法渲染」的字体，不会出现方块或崩溃。

---

## 📄 License

MIT
