from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .core import (
    Invoice,
    ProcessResult,
    amount_to_text,
    learn_from_folder,
    process_inputs,
)
from .excel_writer import export_pdf_and_check, verify_workbook, write_workbook


def default_output(inputs: list[str], year: int, month: int) -> str:
    if not inputs:
        base = Path.cwd()
    else:
        p = Path(inputs[0])
        base = p if p.is_dir() else p.parent
    return str(base / f"{year}年{month}月份入库单.xls")


def apply_dates(invoices: list[Invoice], arrival: str, stock: str):
    for inv in invoices:
        inv.arrival_date = arrival or inv.invoice_date
        inv.stock_date = stock or inv.invoice_date


def invoice_to_dict(inv: Invoice) -> dict:
    return {
        "source_file": inv.source_file,
        "page": inv.page,
        "seller": inv.seller,
        "seller_alias": inv.seller_alias,
        "invoice_number": inv.invoice_number,
        "invoice_date": inv.invoice_date,
        "amount_total": inv.amount_total,
        "tax_total": inv.tax_total,
        "total": inv.total,
        "sheet_name": inv.sheet_name,
        "arrival_date": inv.arrival_date,
        "stock_date": inv.stock_date,
        "warnings": inv.warnings,
        "items": [
            {
                "index": it.index,
                "name": it.name,
                "spec": it.spec,
                "unit": it.unit,
                "qty": it.qty,
                "price": it.price,
                "price_with_tax": it.price_with_tax,
                "amount": it.amount,
                "tax": it.tax,
                "total": it.total,
                "rate": it.rate,
            }
            for it in inv.items
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="invoice2rkd",
        description="扫描发票 PDF/图片 -> 入库单 Excel",
    )
    p.add_argument("--input", "-i", nargs="*", default=[], help="PDF/图片文件或文件夹")
    p.add_argument("--out", "-o", default="", help="输出 .xls 路径")
    p.add_argument("--year", type=int, default=time.localtime().tm_year)
    p.add_argument("--month", type=int, default=time.localtime().tm_mon)
    p.add_argument("--arrival-date", default="", help="到货时间 YYYY.MM.DD，默认开票日期")
    p.add_argument("--stock-date", default="", help="入库时间 YYYY.MM.DD，默认开票日期")
    p.add_argument("--recursive", "-r", action="store_true", help="递归扫描子目录")
    p.add_argument("--dpi", type=int, default=300)
    p.add_argument(
        "--mode",
        choices=("auto", "text", "ocr"),
        default="auto",
        help="识别模式：auto=电子票优先文字层、失败回退OCR（默认）；text=强制文字层；ocr=强制OCR",
    )
    p.add_argument("--json", default="", help="同时输出识别结果 JSON")
    p.add_argument("--learn", default="", help="从历史入库单文件夹学习供应商/项目/单位")
    p.add_argument("--verify-pdf", action="store_true", help="用 Excel 导出 PDF 并检查版式")
    p.add_argument("--quiet", "-q", action="store_true")
    p.add_argument("--gui", action="store_true", help="启动图形界面")
    p.add_argument("--version", action="version", version="invoice2rkd 1.3.0")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.learn:
        rows, aliases, logs = learn_from_folder(args.learn)
        for line in logs:
            print(line)
        print(f"已学习 {rows} 条项目记录、{aliases} 个供应商别名")
        return 0
    if args.gui or not args.input:
        from .gui import launch

        launch(initial_inputs=args.input)
        return 0

    result = process_inputs(
        args.input,
        recursive=args.recursive,
        dpi=args.dpi,
        mode=args.mode,
        progress=None if args.quiet else (lambda msg, cur, total: print(f"[{cur}/{total}] {msg}")),
    )
    if not result.invoices:
        print("没有识别到可用发票")
        for s in result.skipped:
            print(f"  跳过 {Path(s['file']).name} 第{s['page']}页: {s['reason']}")
        return 1

    apply_dates(result.invoices, args.arrival_date, args.stock_date)
    out = args.out or default_output(args.input, args.year, args.month)
    info = write_workbook(result.invoices, out)
    issues = verify_workbook(out, result.invoices)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "invoices": [invoice_to_dict(i) for i in result.invoices],
                    "skipped": result.skipped,
                    "logs": result.logs,
                },
                f,
                ensure_ascii=False,
                indent=1,
            )

    print(f"输出文件: {info['path']}")
    print(f"工作表: {info['sheets']} 张")
    for inv in result.invoices:
        print(
            f"  {inv.sheet_name} | {inv.seller} | {inv.invoice_number} | "
            f"{inv.total:.2f} | {len(inv.items)} 项"
        )
        for w in inv.warnings:
            print(f"    警告: {w}")
    for s in result.skipped:
        print(f"  跳过 {Path(s['file']).name} 第{s['page']}页: {s['reason']}")
    if issues:
        print("自检发现问题:")
        for issue in issues:
            print("  - " + issue)
    else:
        print("自检: 金额/税金/价税合计核对通过")

    if args.verify_pdf:
        pdf = str(Path(out).with_name(Path(out).stem + "-打印.pdf"))
        ok, msg = export_pdf_and_check(out, pdf)
        print(("PDF 检查: " if ok else "PDF 检查失败: ") + msg)
        if not ok:
            issues.append(msg)
    return 0 if not issues and not result.skipped else 1
