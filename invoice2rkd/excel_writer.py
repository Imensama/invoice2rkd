from __future__ import annotations

import math
import os
import shutil
import time
from pathlib import Path
from typing import Iterable, Optional

import xlrd
import xlwt

from .core import Invoice, amount_to_text, get_company


def _company_title() -> str:
    return str(get_company().get("title") or "入库单")
HEADERS = [
    "序号",
    "材料名称",
    "规格型号",
    "单位",
    "数量",
    "单价",
    "单价含税",
    "金额",
    "税金",
    "含税价",
    "到货时间",
    "入库时间",
    "备注",
]
BASE_WIDTHS = [1695, 5952, 6912, 3600, 2719, 2880, 2080, 2880, 2880, 2880, 3616, 3551, 4384]
FMT_NUM2 = "0.00_ "
FMT_NUM2_RED = r"0.00_);[Red]\(0.00\)"
FMT_PRICE = "0.0000_ "


def _align(horz: str, wrap: bool) -> xlwt.Alignment:
    al = xlwt.Alignment()
    al.horz = xlwt.Alignment.HORZ_CENTER if horz == "center" else xlwt.Alignment.HORZ_LEFT
    al.vert = xlwt.Alignment.VERT_CENTER
    al.wrap = 1 if wrap else 0
    return al


def _border() -> xlwt.Borders:
    b = xlwt.Borders()
    b.left = xlwt.Borders.THIN
    b.right = xlwt.Borders.THIN
    b.top = xlwt.Borders.THIN
    b.bottom = xlwt.Borders.THIN
    return b


def _style(height: int, horz: str = "center", wrap: bool = False, border: bool = True, num_format: str = "General", bold: bool = False):
    st = xlwt.XFStyle()
    font = xlwt.Font()
    font.name = "宋体"
    font.height = height * 20
    font.bold = bold
    st.font = font
    st.alignment = _align(horz, wrap)
    if border:
        st.borders = _border()
    st.num_format_str = num_format
    return st


TITLE_STYLE = _style(24, "center", False, False)
A2_STYLE = _style(14, "left", True, False)
HEADER_STYLE = _style(12, "center", False, True)
DETAIL_STYLES = {
    0: _style(12, "center", False, True),
    1: _style(12, "center", True, True),
    2: _style(12, "center", True, True),
    3: _style(12, "center", True, True),
    4: _style(12, "center", False, True),
    5: _style(12, "center", False, True, FMT_NUM2),
    6: _style(12, "center", False, True, FMT_NUM2),
    7: _style(12, "center", False, True, FMT_NUM2),
    8: _style(12, "center", False, True, FMT_NUM2),
    9: _style(12, "center", False, True, FMT_NUM2),
    10: _style(12, "center", False, True),
    11: _style(12, "center", False, True),
    12: _style(12, "center", True, True),
}
TOTAL_STYLES = {
    0: _style(12, "center", False, True),
    1: _style(12, "center", False, True),
    2: _style(12, "center", False, True),
    3: _style(12, "center", False, True),
    4: _style(12, "center", False, True),
    5: _style(12, "center", False, True),
    6: _style(12, "center", False, True),
    7: _style(12, "center", False, True, FMT_NUM2_RED),
    8: _style(12, "center", False, True, FMT_NUM2_RED),
    9: _style(12, "center", False, True, FMT_NUM2),
    10: _style(12, "center", False, True),
    11: _style(12, "center", False, True),
    12: _style(12, "center", False, True),
}
FOOTER_STYLE = _style(14, "left", False, False)
BLANK_STYLE = _style(12, "center", False, False)


def _display_units(text: str) -> int:
    return sum(2 if ord(ch) > 127 else 1 for ch in (text or ""))


def _calc_widths(items) -> list[int]:
    widths = list(BASE_WIDTHS)
    max_name = max([_display_units(i.name) for i in items] + [0])
    max_spec = max([_display_units(i.spec) for i in items] + [0])
    widths[1] = max(widths[1], min(14000, max_name * 256 + 512))
    widths[2] = max(widths[2], min(14000, max_spec * 256 + 512))
    return widths


def _calc_row_height(name: str, spec: str, widths: list[int]) -> int:
    lines = 1
    if name:
        chars = max(1.0, widths[1] / 256.0)
        lines = max(lines, math.ceil(_display_units(name) / chars))
    if spec:
        chars = max(1.0, widths[2] / 256.0)
        lines = max(lines, math.ceil(_display_units(spec) / chars))
    lines = max(1, min(lines, 4))
    return 360 + (lines - 1) * 300


def _write_blank_row(ws, row: int, style, ncols: int = 13):
    for c in range(ncols):
        ws.write(row, c, "", style)


def write_workbook(invoices: list[Invoice], out_path: str, backup: bool = True) -> dict:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and backup:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        bak = out.with_name(out.stem + f".bak-{stamp}" + out.suffix)
        try:
            shutil.copy2(out, bak)
        except Exception:
            pass
    wb = xlwt.Workbook(encoding="utf-8")
    used_sheets = set()
    for inv in invoices:
        sheet_name = inv.sheet_name or (inv.seller_alias + amount_to_text(inv.total or 0))
        base = sheet_name[:31] or "Sheet"
        candidate = base
        n = 2
        while candidate in used_sheets:
            suffix = f"-{n}"
            candidate = base[: 31 - len(suffix)] + suffix
            n += 1
        used_sheets.add(candidate)
        ws = wb.add_sheet(candidate)

        widths = _calc_widths(inv.items)
        for i, width in enumerate(widths):
            ws.col(i).width = width
        ws.col(6).hidden = 1
        ws.col(6).width = 2080

        detail_rows = max(13, len(inv.items))
        total_row = 3 + detail_rows
        blank_row = total_row + 1
        footer_row = total_row + 2
        nrows = footer_row + 1

        ws.write_merge(0, 0, 0, 12, _company_title(), TITLE_STYLE)
        ws.write_merge(1, 1, 0, 12, "收到：" + (inv.seller or ""), A2_STYLE)
        ws.row(0).height = 679
        ws.row(1).height = 679
        ws.row(2).height = 319
        for r in (0, 1, 2):
            ws.row(r).height_mismatch = 1

        for c, label in enumerate(HEADERS):
            ws.write(2, c, label, HEADER_STYLE)

        for i in range(detail_rows):
            r = 3 + i
            serial = i + 1
            if i < len(inv.items):
                item = inv.items[i]
                ws.write(r, 0, serial, DETAIL_STYLES[0])
                ws.write(r, 1, item.name or "", DETAIL_STYLES[1])
                ws.write(r, 2, item.spec or "", DETAIL_STYLES[2])
                ws.write(r, 3, item.unit or "", DETAIL_STYLES[3])
                if item.qty is not None:
                    ws.write(r, 4, float(item.qty), DETAIL_STYLES[4])
                else:
                    ws.write(r, 4, "", DETAIL_STYLES[4])
                if item.price is not None:
                    ws.write(r, 5, float(item.price), DETAIL_STYLES[5])
                else:
                    ws.write(r, 5, "", DETAIL_STYLES[5])
                if item.price_with_tax is not None:
                    ws.write(r, 6, float(item.price_with_tax), DETAIL_STYLES[6])
                else:
                    ws.write(r, 6, "", DETAIL_STYLES[6])
                if item.amount is not None:
                    ws.write(r, 7, round(item.amount, 2), DETAIL_STYLES[7])
                else:
                    ws.write(r, 7, "", DETAIL_STYLES[7])
                if item.tax is not None:
                    ws.write(r, 8, round(item.tax, 2), DETAIL_STYLES[8])
                else:
                    ws.write(r, 8, "", DETAIL_STYLES[8])
                if item.total is not None:
                    ws.write(r, 9, round(item.total, 2), DETAIL_STYLES[9])
                else:
                    ws.write(r, 9, "", DETAIL_STYLES[9])
                ws.write(r, 10, inv.arrival_date or inv.invoice_date or "", DETAIL_STYLES[10])
                ws.write(r, 11, inv.stock_date or inv.invoice_date or "", DETAIL_STYLES[11])
                ws.write(r, 12, item.remark or "", DETAIL_STYLES[12])
            else:
                for c in range(13):
                    ws.write(r, c, serial if c == 0 else "", DETAIL_STYLES[c])
            ws.row(r).height = _calc_row_height(
                inv.items[i].name if i < len(inv.items) else "",
                inv.items[i].spec if i < len(inv.items) else "",
                widths,
            )
            ws.row(r).height_mismatch = 1

        ws.write(total_row, 0, len(inv.items) + 1, TOTAL_STYLES[0])
        ws.write(total_row, 1, "", TOTAL_STYLES[1])
        ws.write(total_row, 2, "合计", TOTAL_STYLES[2])
        ws.write(total_row, 3, "", TOTAL_STYLES[3])
        ws.write(total_row, 4, "", TOTAL_STYLES[4])
        ws.write(total_row, 5, "", TOTAL_STYLES[5])
        ws.write(total_row, 6, "", TOTAL_STYLES[6])
        if inv.amount_total is not None:
            ws.write(total_row, 7, round(inv.amount_total, 2), TOTAL_STYLES[7])
        else:
            ws.write(total_row, 7, "", TOTAL_STYLES[7])
        if inv.tax_total is not None:
            ws.write(total_row, 8, round(inv.tax_total, 2), TOTAL_STYLES[8])
        else:
            ws.write(total_row, 8, "", TOTAL_STYLES[8])
        if inv.total is not None:
            ws.write(total_row, 9, round(inv.total, 2), TOTAL_STYLES[9])
        else:
            ws.write(total_row, 9, "", TOTAL_STYLES[9])
        ws.write(total_row, 10, "", TOTAL_STYLES[10])
        ws.write(total_row, 11, "", TOTAL_STYLES[11])
        ws.write(total_row, 12, "", TOTAL_STYLES[12])
        ws.row(total_row).height = 360
        ws.row(total_row).height_mismatch = 1

        _write_blank_row(ws, blank_row, BLANK_STYLE)
        ws.row(blank_row).height = 585
        ws.row(blank_row).height_mismatch = 1

        ws.write(footer_row, 0, "检验人：", FOOTER_STYLE)
        ws.write_merge(footer_row, footer_row, 3, 4, "仓库负责人：", FOOTER_STYLE)
        ws.write_merge(footer_row, footer_row, 11, 12, "入库经手人：", FOOTER_STYLE)
        ws.row(footer_row).height = 585
        ws.row(footer_row).height_mismatch = 1

        ws.paper_size_code = 286
        ws.portrait = 1
        ws.fit_num_pages = 1
        ws.fit_width_to_pages = 1
        ws.fit_height_to_pages = 1
        ws.left_margin = 0.2
        ws.right_margin = 0.2
        ws.top_margin = 0.4
        ws.bottom_margin = 0.4
        ws.header_str = b""
        ws.footer_str = b""
        ws.print_centered_horz = True
        ws.print_centered_vert = False
        ws.print_headers = False
        ws.print_grid = False
        ws.print_scaling = 100

    wb.save(str(out))
    return {"path": str(out), "sheets": len(invoices)}


def verify_workbook(path: str, invoices: list[Invoice]) -> list[str]:
    issues = []
    try:
        book = xlrd.open_workbook(path, formatting_info=False)
    except Exception as e:
        return [f"无法读回文件: {e}"]
    names = book.sheet_names()
    if len(names) != len(invoices):
        issues.append(f"工作表数量 {len(names)} 与发票数量 {len(invoices)} 不一致")
    for idx, inv in enumerate(invoices):
        if idx >= len(names):
            break
        sheet = book.sheet_by_index(idx)
        total_row = None
        for r in range(3, min(sheet.nrows, 80)):
            try:
                if str(sheet.cell_value(r, 2)).strip() == "合计":
                    total_row = r
                    break
            except Exception:
                pass
        if total_row is None:
            issues.append(f"{names[idx]}: 未找到合计行")
            continue
        try:
            amount = float(sheet.cell_value(total_row, 7) or 0)
            tax = float(sheet.cell_value(total_row, 8) or 0)
            total = float(sheet.cell_value(total_row, 9) or 0)
        except Exception:
            issues.append(f"{names[idx]}: 合计行金额无法读取")
            continue
        if abs(amount + tax - total) > 0.011:
            issues.append(f"{names[idx]}: 金额+税金({amount:.2f}+{tax:.2f})≠含税价({total:.2f})")
        if inv.total is not None and abs(total - inv.total) > 0.011:
            issues.append(f"{names[idx]}: 合计 {total:.2f} ≠ 发票价税合计 {inv.total:.2f}")
        if inv.amount_total is not None and abs(amount - inv.amount_total) > 0.011:
            issues.append(f"{names[idx]}: 金额合计 {amount:.2f} ≠ 发票金额 {inv.amount_total:.2f}")
        if inv.tax_total is not None and abs(tax - inv.tax_total) > 0.011:
            issues.append(f"{names[idx]}: 税金合计 {tax:.2f} ≠ 发票税额 {inv.tax_total:.2f}")
        if sheet.ncols < 13:
            issues.append(f"{names[idx]}: 列数不足 13")
        if sheet.nrows < 19:
            issues.append(f"{names[idx]}: 行数不足 19")
    return issues


def export_pdf_and_check(xls_path: str, pdf_path: str) -> tuple[bool, str]:
    try:
        import win32com.client as win32
    except Exception as e:
        return False, f"未安装 pywin32，跳过 PDF 检查 ({e})"
    xls_abs = os.path.abspath(xls_path)
    pdf_abs = os.path.abspath(pdf_path)
    app = None
    wb = None
    try:
        app = win32.DispatchEx("Excel.Application")
        app.Visible = False
        app.DisplayAlerts = False
        wb = app.Workbooks.Open(xls_abs, ReadOnly=True)
        wb.ExportAsFixedFormat(0, pdf_abs)
        wb.Close(False)
        wb = None
        app.Quit()
        app = None
    except Exception as e:
        try:
            if wb is not None:
                wb.Close(False)
            if app is not None:
                app.Quit()
        except Exception:
            pass
        return False, f"Excel 导出 PDF 失败: {e}"
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(pdf_abs)
        pages = len(doc)
        sizes = []
        bad_page = None
        for i in range(pages):
            page = doc[i]
            try:
                w, h = page.get_size()
                sizes.append((w, h))
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_range() or ""
                finally:
                    textpage.close()
                if "##" in text:
                    bad_page = i + 1
                    break
            finally:
                page.close()
        doc.close()
        if bad_page is not None:
            return False, (
                f"第{bad_page}页出现 ##/####。通常是当前默认打印机不支持 286 纸型；"
                "请把默认打印机切换为 EPSON LQ-730K 后再检查（xls 已生成，不影响打印设置）"
            )
    except Exception as e:
        return False, f"PDF 检查失败: {e}"
    try:
        book = xlrd.open_workbook(xls_path)
        sheet_count = len(book.sheet_names())
    except Exception:
        sheet_count = None
    if sheet_count is not None and pages != sheet_count:
        return False, f"PDF 页数 {pages} 与工作表数 {sheet_count} 不一致"
    for i, (w, h) in enumerate(sizes):
        if not (670 <= w <= 695 and 388 <= h <= 405):
            return False, f"第{i + 1}页尺寸异常: {w:.1f}×{h:.1f} pt"
    return True, f"PDF {pages} 页，页面 {sizes[0][0]:.1f}×{sizes[0][1]:.1f} pt，单页一表"


def workbook_summary(path: str) -> dict:
    book = xlrd.open_workbook(path, formatting_info=False)
    return {"path": path, "sheets": book.sheet_names()}
