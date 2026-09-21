# 日文文档翻译工具 🇯🇵 → 🇨🇳

把日文 **PDF / DOCX** 翻译成简体中文，尽量保留原始版面。

| 输入 | 处理方式 | 输出 |
|---|---|---|
| 文字型 PDF | 精确删除原文（redaction）→ 写入译文 | 同版式 PDF |
| 扫描件 / 图片型 PDF | OCR 识别 → 按原图底色覆盖 → 写入译文 | 同版式 PDF |
| 带隐藏 OCR 文字层的扫描件 | 直接复用文字层，不跑 OCR（快且准） | 同版式 PDF |
| DOCX | 段落 / 标题 / 表格 / 页眉页脚替换，保留样式 | DOCX |

## 1. 安装

```bash
git clone https://github.com/Amilmaho/ja2zh_pdf_translator.git
cd ja2zh_pdf_translator
pip3 install -r requirements.txt
```

首次使用 EasyOCR 会自动下载日文模型到 `~/.EasyOCR/model`（约 100MB）。

## 2. 配置

```bash
cp .env.example .env
```

编辑 `.env`，至少填一个翻译引擎的 Key（推荐 DeepSeek，国内可直连）：

```env
DEEPSEEK_API_KEY=sk-xxxxxxxx
```

检查环境（会打印可用引擎和自动选中的中文字体）：

```bash
python3 main.py --list-engines
```

```
可用翻译引擎: deepseek, openai, google, deepl, dummy
可用 OCR 引擎: easyocr, tesseract
当前中文字体: SimSong.ttc (SimSong Regular)
```

---

## 3. 命令速查

### 3.1 PDF 翻译

```bash
# 翻译整个 PDF
python3 main.py input/book.pdf

# 只翻译指定页（推荐先用小范围试跑）
python3 main.py input/book.pdf --pages 20-30

# 多段页码范围
python3 main.py input/book.pdf --pages 1-5,10-20

# 只处理前 N 页
python3 main.py input/book.pdf --max-pages 2

# 指定输出路径
python3 main.py input/book.pdf --pages 20-30 -o output/result.pdf

# 文字页里嵌的图片也一起翻译
python3 main.py input/book.pdf --translate-images

# 换 OCR 引擎（更快，但日文识别率低于 EasyOCR）
python3 main.py input/book.pdf --ocr tesseract

# 离线伪翻译：不调用任何 API，专门用来看排版效果
python3 main.py input/book.pdf --pages 20-30 --translator dummy

# 小字扫描件提高渲染精度
python3 main.py input/book.pdf --pages 20-30 --dpi 300

# 指定中文字体
python3 main.py input/book.pdf --font "/System/Library/Fonts/Hiragino Sans GB.ttc"

# 安静模式
python3 main.py input/book.pdf --pages 20-30 -q
```

> **`--pages` 只改选定页，输出仍是完整文档**，未选中的页原样保留。
> 想只保留选中的几页，见 3.3 的摘取命令。

### 3.2 DOCX 翻译

```bash
# 翻译文字（段落 / 标题 / 表格 / 页眉页脚）
python3 main.py input/doc.docx

# 连文档内嵌图片一起翻译：OCR 后重绘图片并替换回文档
python3 main.py input/doc.docx --translate-images

# 指定输出
python3 main.py input/doc.docx -o output/result.docx
```

### 3.3 结果自检

换新文档或改完代码后先跑这个。它逐页检查**空白色块 / 底色一致性 / 放不下 / 墨量**：

```bash
# 默认用 dummy 引擎，不花 API 额度
python3 tools/verify_pipeline.py input/book.pdf --pages 100-102

# 额外导出前后对比 PNG，方便肉眼比对
python3 tools/verify_pipeline.py input/book.pdf --pages 100-102 --visual

# 指定输出目录
python3 tools/verify_pipeline.py input/book.pdf --pages 1-3 --out temp/mycheck
```

输出示例：

```
  第  100 页: 色块  203 / 空白色块 0 / 底色不符 0 / 墨量 0.0866 -> 0.1015
  第  101 页: 色块  257 / 空白色块 0 / 底色不符 0 / 墨量 0.0502 -> 0.0731

  空白色块合计: 0
  底色不符合计: 0
  放不下被跳过的区域: 0
  ✅ 通过：没有空白色块，底色一致
```

只想要选中的那几页（从完整输出里摘出来，体积更小、打开更快）：

```bash
python3 -c "import fitz; s=fitz.open('output/result.pdf'); d=fitz.open(); d.insert_pdf(s, from_page=19, to_page=29); d.save('output/excerpt.pdf')"
```

### 3.4 Web UI

```bash
uvicorn web.app:app --host 127.0.0.1 --port 8000
```

浏览器打开 http://127.0.0.1:8000 ：支持拖拽上传、页码范围、引擎选择、SSE 实时日志、完成后下载。

后端接口：`/api/health`、`/api/upload`、`/api/translate`、
`/api/tasks/{id}`、`/api/download/{id}`、`/api/logs/{id}`（SSE）。

---

## 4. 参数说明

`main.py`：

| 参数 | 说明 | 默认 |
|---|---|---|
| `--pages 1-5,10` | 页码范围（从 1 开始），仅 PDF | 全部页 |
| `--max-pages N` | 最多处理 N 页 | 不限 |
| `--translator` | `deepseek` / `google` / `openai` / `deepl` / `dummy` | 取 `.env` |
| `--ocr` | `easyocr` / `tesseract` | `easyocr` |
| `--translate-images` | 文字页里的图片也翻译；DOCX 表示重绘内嵌图片 | 关闭 |
| `--dpi N` | 整页渲染给 OCR 用的 DPI | 200 |
| `--font PATH` | 指定中文字体 | 自动检测 |
| `-o, --output` | 输出路径 | `output/<原名>_translated.<ext>` |
| `-q, --quiet` | 减少输出 | 关闭 |
| `--list-engines` | 列出可用引擎与当前字体后退出 | — |

`.env` 常用开关：

| 变量 | 说明 | 默认 |
|---|---|---|
| `TRANSLATION_ENGINE` | 默认翻译引擎 | `deepseek` |
| `OCR_ENGINE` | 默认 OCR 引擎 | `easyocr` |
| `FONT_STYLE` | 自动选字体的风格：`serif`（宋体）/ `sans`（黑体） | `serif` |
| `FONT_PATH` | 直接指定字体文件 | — |
| `TRANSLATION_BATCH_SIZE` | 单次 API 请求翻译多少条 | 12 |
| `TRANSLATION_CACHE` | 译文缓存（相同原文不重复调用 API） | 开启 |
| `OCR_CACHE` | OCR 结果缓存 | 开启 |
| `OCR_MIN_CONFIDENCE` | 只用于过滤**极短**噪声，不是"低于就丢" | 0.15 |
| `OVERLAY_MIN_FONT` | 译文允许的最小字号 | 3.0 |
| `DOCX_TRANSLATE_IMAGES` | DOCX 是否翻译内嵌图片 | 关闭 |

---

## 5. 实测效果与耗时

样本：一本 391 页的日文扫描 PDF（A5 开本，整页扫描图，无文字层），机器无 GPU。

| 项目 | 实测值 |
|---|---|
| OCR 速度 | EasyOCR **≈14 秒/页**；Tesseract **≈2 秒/页**（都是 CPU） |
| 翻译 11 页（第 20–30 页，853 个文字区域） | 首次 **约 4 分钟**；命中缓存后 **约 30 秒** |
| DeepSeek 请求次数 | 257 个区域 → **22 次请求**（批量翻译） |
| 空白色块 / 底色不符 | **0 / 0** |
| 译文字形大小 vs 原文 | **1.00×**（按原文字形墨迹高度标定） |
| 整页墨量 vs 原文 | **0.80 ~ 1.11×** |
| 译文里的日文假名残留 | **0** |

---

## 6. 常见问题

### Q: 太慢怎么办？

- 用 `--pages` / `--max-pages` 缩小范围
- 重跑同一批页面会命中缓存，几乎不耗时（缓存目录 `.cache/`，可安全删除）
- `--ocr tesseract` 约快 7 倍，代价是日文识别率下降
- 无 GPU 时 EasyOCR 走 CPU，页数多时建议分批跑

### Q: 有些文字没翻译 / 还留着日文？

程序内置三道防线：不按置信度一刀切丢弃正文、对第一遍 OCR 整块漏检的行做
「查漏补识别」、译文残留假名自动重译。若仍出现，看日志里的计数：

- `放不下` → 调小 `OVERLAY_MIN_FONT`（例如 2.5）
- `保留原文` → 该区域被判为噪声（页边页码条、纯符号等），属预期行为

### Q: 译文比原文大/小、看着别扭？

译文字号按**原文字形实际高度**自动标定，字体默认宋体（贴近日文印刷品的明朝体）。
要换黑体：`.env` 里设 `FONT_STYLE=sans`。

### Q: 中文显示成方块 / 提示找不到字体？

程序会自动检测并**校验字形覆盖 + 实际渲染**，跳过缺字形或无法渲染的字体。
也可手动指定：`.env` 里 `FONT_PATH=/path/to/font.ttf`。

### Q: 首次运行卡在下载 EasyOCR 模型？

模型保存在 `~/.EasyOCR/model`。网络不畅时改用 `--ocr tesseract`
（macOS 需先 `brew install tesseract-lang`）。

---

## 7. 项目结构

```
ja2zh_pdf_translator/
├── main.py                    # CLI 入口
├── config.py                  # 全局配置
├── core/
│   ├── pdf_translator.py      # PDF 编排：提取 → OCR → 翻译 → 生成 → 自检
│   ├── docx_translator.py     # DOCX 编排
│   ├── dispatcher.py          # 按扩展名分派
│   └── task_manager.py        # Web 任务与日志
├── modules/
│   ├── pdf_extractor.py       # 逐行提取文字 + 图片 + 整页渲染
│   ├── ocr_engine.py          # EasyOCR / Tesseract（含字符级结果合并成行）
│   ├── translator.py          # 五种引擎（批量 + 缓存 + 重试 + 假名检测）
│   ├── text_layout.py         # 测宽 / 换行 / 自适应字号
│   ├── pdf_generator.py       # 在原 PDF 副本上写入译文
│   ├── image_overlay.py       # DOCX 内嵌图片译文重绘
│   ├── fonts.py               # 字体发现 + 字形覆盖 + 渲染探针
│   ├── docx_reader.py / docx_writer.py
│   └── utils.py               # 页码范围解析 / 缓存键 / 进度回调
├── tools/verify_pipeline.py   # 端到端自检
├── web/                       # FastAPI Web UI
└── input/  output/  temp/  .cache/
```

---

## 8. 注意

`input/` 与 `output/` 是用户资料目录，已在 `.gitignore` 中整体排除
（`*.pdf`、`*.docx`、`*.epub` 等文档格式也全局排除），待翻译原文和翻译结果
都不会被提交到仓库。`.env`、`.cache/`（含译文缓存）、`temp/` 同样不入库。

---

## License

MIT
