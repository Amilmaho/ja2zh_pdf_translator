# CHANGELOG.md — 变更日志

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，本项目遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

---

## [Unreleased]

### Planned
- Phase 2: Web UI
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
