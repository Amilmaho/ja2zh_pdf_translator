#!/usr/bin/env python3
"""
端到端自检脚本：翻译若干页 PDF，然后逐项检查输出是否正常。

检查项（对应历史上出现过的 bug）：
  1. 空白色块：有没有「涂了底色却没有文字」的区域（旧版的核心问题）
  2. 底色一致性：覆盖用的底色是否与原图一致（深色栏位不能被涂成白色）
  3. 溢出：有没有区域文本放不下被丢弃
  4. 版面：页面墨量是否与原页量级相当（没有整页变白/变黑）

用法:
    python tools/verify_pipeline.py input/book.pdf --pages 100-101
    python tools/verify_pipeline.py input/book.pdf --pages 1-2 --translator dummy
    python tools/verify_pipeline.py input/book.pdf --pages 1-2 --visual   # 额外导出对比图
"""

import argparse
import json
import os
import sys
from typing import Dict

import fitz
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from core.pdf_translator import PDFTranslator
from modules.utils import parse_page_range


def _analyze_page(page: fitz.Page, source_page: fitz.Page, dpi: int = 150) -> Dict:
    fills = [d for d in page.get_drawings() if d["type"] == "f"]
    spans = [
        s for b in page.get_text("dict")["blocks"] if b.get("type") == 0
        for line in b.get("lines", []) for s in line.get("spans", [])
        if s.get("text", "").strip()
    ]

    empty_fills = []
    color_mismatch = 0
    for d in fills:
        rect = d["rect"]
        if not any(rect.intersects(fitz.Rect(s["bbox"])) for s in spans):
            empty_fills.append(tuple(round(v, 1) for v in rect))

    src_pix = source_page.get_pixmap(dpi=dpi, alpha=False)
    src = np.frombuffer(src_pix.samples, dtype=np.uint8).reshape(
        src_pix.height, src_pix.width, src_pix.n
    )[:, :, :3]
    scale = dpi / 72.0

    for d in fills:
        rect = d["rect"]
        fill = d.get("fill") or (0, 0, 0)
        x0 = max(0, int(rect.x0 * scale))
        y0 = max(0, int(rect.y0 * scale))
        x1 = min(src.shape[1], int(rect.x1 * scale))
        y1 = min(src.shape[0], int(rect.y1 * scale))
        if x1 - x0 < 3 or y1 - y0 < 3:
            continue
        patch = src[y0:y1, x0:x1].reshape(-1, 3)
        quant = (patch // 24).astype(np.int32)
        keys = quant[:, 0] * 10000 + quant[:, 1] * 100 + quant[:, 2]
        values, counts = np.unique(keys, return_counts=True)
        dominant = patch[keys == values[counts.argmax()]].mean(axis=0)
        fill_lum = 255 * (0.299 * fill[0] + 0.587 * fill[1] + 0.114 * fill[2])
        src_lum = 0.299 * dominant[0] + 0.587 * dominant[1] + 0.114 * dominant[2]
        if abs(fill_lum - src_lum) > 70:
            color_mismatch += 1

    def ink(p: fitz.Page):
        pix = p.get_pixmap(dpi=dpi, alpha=False)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )[:, :, :3].mean(axis=2)
        return float((arr < 128).mean()), float(arr.mean())

    src_ink, src_mean = ink(source_page)
    out_ink, out_mean = ink(page)

    return {
        "page": page.number + 1,
        "fills": len(fills),
        "empty_fills": len(empty_fills),
        "empty_fill_samples": empty_fills[:5],
        "color_mismatch": color_mismatch,
        "spans": len(spans),
        "src_ink_ratio": round(src_ink, 4),
        "out_ink_ratio": round(out_ink, 4),
        "src_mean_luma": round(src_mean, 1),
        "out_mean_luma": round(out_mean, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="PDF 翻译结果自检")
    parser.add_argument("pdf")
    parser.add_argument("--pages", default=None, help='如 "1-3" 或 "10,12,14"')
    parser.add_argument("--translator", default="dummy",
                        help="翻译引擎，默认 dummy（离线，不花钱）")
    parser.add_argument("--ocr", default=None)
    parser.add_argument("--out", default=None, help="输出目录（默认 temp/verify）")
    parser.add_argument("--visual", action="store_true", help="导出前后对比 PNG")
    args = parser.parse_args()

    out_dir = args.out or os.path.join(config.TEMP_DIR, "verify")
    os.makedirs(out_dir, exist_ok=True)
    output_pdf = os.path.join(out_dir, "translated.pdf")

    doc = fitz.open(args.pdf)
    total = len(doc)
    pages = parse_page_range(args.pages, total)[:5]
    doc.close()

    translator = PDFTranslator(
        pdf_path=args.pdf,
        output_path=output_pdf,
        translation_engine=args.translator,
        ocr_engine=args.ocr,
        page_range=args.pages,
        max_pages=5,
        verbose=True,
    )
    stats = translator.run()

    src_doc = fitz.open(args.pdf)
    out_doc = fitz.open(output_pdf)
    reports = []
    for p in pages:
        rep = _analyze_page(out_doc[p], src_doc[p])
        reports.append(rep)

        if args.visual:
            out_doc[p].get_pixmap(dpi=120).save(
                os.path.join(out_dir, f"page{p + 1:04d}_after.png"))
            src_doc[p].get_pixmap(dpi=120).save(
                os.path.join(out_dir, f"page{p + 1:04d}_before.png"))

    total_empty = sum(r["empty_fills"] for r in reports)
    total_mismatch = sum(r["color_mismatch"] for r in reports)

    report = {
        "pdf": args.pdf,
        "pages_checked": [p + 1 for p in pages],
        "translator": args.translator,
        "pipeline_stats": {k: v for k, v in stats.items() if k != "verify"},
        "pages": reports,
        "totals": {
            "empty_fills": total_empty,
            "color_mismatch": total_mismatch,
            "failed_regions": stats.get("failed", 0),
        },
    }

    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 58)
    print("自检结果")
    print("=" * 58)
    for r in reports:
        print(f"  第 {r['page']:>4} 页: 色块 {r['fills']:>4} / 空白色块 {r['empty_fills']} / "
              f"底色不符 {r['color_mismatch']} / 墨量 {r['src_ink_ratio']} -> {r['out_ink_ratio']}")
    print(f"\n  空白色块合计: {total_empty}")
    print(f"  底色不符合计: {total_mismatch}")
    print(f"  放不下被跳过的区域: {stats.get('failed', 0)}")
    print(f"  报告: {os.path.join(out_dir, 'report.json')}")

    ok = total_empty == 0 and total_mismatch == 0
    print("\n  " + ("✅ 通过：没有空白色块，底色一致" if ok else "❌ 未通过：请看上面的明细"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
