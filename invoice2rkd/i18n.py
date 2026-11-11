from __future__ import annotations

import json
import locale
import os
import re
from pathlib import Path
from typing import Optional

from .core import USER_DIR, save_json

SETTINGS_FILE = USER_DIR / "settings.json"
VALID_LANGUAGES = ("zh", "en")


def _read_settings() -> dict:
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def system_language() -> str:
    if os.name == "nt":
        try:
            import ctypes

            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            if (int(lcid) & 0x3FF) == 0x04:
                return "zh"
            return "en"
        except Exception:
            pass
    try:
        lang = locale.getlocale()[0] or locale.getdefaultlocale()[0] or ""
    except Exception:
        lang = ""
    return "zh" if str(lang).lower().startswith("zh") else "en"


def get_language() -> str:
    lang = str(_read_settings().get("language") or "").strip().lower()
    return lang if lang in VALID_LANGUAGES else system_language()


def set_language(lang: str):
    lang = (lang or "").strip().lower()
    if lang not in VALID_LANGUAGES:
        return
    data = _read_settings()
    data["language"] = lang
    save_json(SETTINGS_FILE, data)


EN = {
    "扫描发票 → 入库单生成器": "Invoice → Receipt Generator",
    "添加 PDF/图片": "Add PDF/Images",
    "添加文件夹": "Add Folder",
    "清空": "Clear",
    "开始识别": "Start",
    "停止": "Stop",
    "学习历史入库单": "Learn History",
    "使用说明": "Help",
    "输出:": "Output:",
    "浏览": "Browse",
    "默认路径": "Default Path",
    "年": "Year",
    "月": "Month",
    "到货日期": "Arrival Date",
    "入库日期": "Stock Date",
    "应用到全部": "Apply to All",
    "留空 = 开票日期": "Blank = Invoice Date",
    "生成 Excel": "Generate Excel",
    "打开输出": "Open Output",
    "公司设置": "Company Settings",
    "识别模式:": "Mode:",
    "语言/Language:": "Language:",
    "手动新增一张发票": "Add Invoice Manually",
    "自动（推荐）": "Auto (recommended)",
    "仅文字层（电子票）": "Text layer only (e-invoice)",
    "仅OCR（扫描件）": "OCR only (scan)",
    "就绪": "Ready",
    "正在识别...": "Recognizing...",
    "正在识别，请稍候...": "Recognizing, please wait...",
    "识别中...": "Recognizing...",
    "已清空": "Cleared",
    "把 PDF/图片/文件夹拖到这里": "Drop PDF/images/folder here",
    "点上方添加 PDF/图片/文件夹": "Use the Add buttons above",
    "发票预览": "Invoice Preview",
    "明细与字段": "Details & Fields",
    "发票字段": "Invoice Fields",
    "日志/警告": "Log / Warnings",
    "明细行（双击选择，编辑后点“应用行修改”）": "Line items (select a row, edit, then click Apply Row)",
    "（无预览）": "(No preview)",
    "销售方": "Seller",
    "发票号": "Invoice No.",
    "价税合计": "Total (incl. tax)",
    "项数": "Items",
    "状态": "Status",
    "来源": "Source",
    "序号": "No.",
    "材料名称": "Item",
    "规格型号": "Spec",
    "单位": "Unit",
    "数量": "Qty",
    "单价": "Unit Price",
    "金额": "Amount",
    "税率": "Tax Rate",
    "税金": "Tax",
    "含税价": "Total",
    "名称": "Name",
    "规格": "Spec",
    "税率%": "Tax Rate %",
    "备注": "Remark",
    "应用行修改": "Apply Row",
    "添加行": "Add Row",
    "删除行": "Delete Row",
    "发票号码": "Invoice No.",
    "开票日期": "Invoice Date",
    "金额合计": "Amount",
    "税金合计": "Tax",
    "表名简写": "Sheet Name",
    "到货时间": "Arrival",
    "入库时间": "Stock",
    "应用发票修改": "Apply Invoice Changes",
    "按明细重算合计": "Recalculate Totals",
    "入库单标题:": "Receipt title:",
    "购买方公司名称:": "Buyer company name:",
    "标题显示在每张入库单顶部；购买方用于识别时排除买方，不会把本公司当成销售方。\n保存后立即生效，不需要重新打包或改文件。": (
        "The title is printed at the top of each receipt. The buyer name is used to exclude "
        "your own company from seller detection.\nChanges take effect immediately; no rebuild or "
        "file editing needed."
    ),
    "保存": "Save",
    "取消": "Cancel",
    "提示": "Notice",
    "添加": "Add",
    "拖拽": "Drag & Drop",
    "核对提醒": "Review Warnings",
    "找到以下警告：\n\n": "Warnings:\n\n",
    "发现以下警告：\n\n": "Warnings:\n\n",
    "仍然生成吗？": "Generate anyway?",
    "正在识别，请先停止": "Recognition is running; stop it first",
    "正在识别中": "Recognition in progress",
    "请先添加 PDF/图片或文件夹": "Add PDF/images or a folder first",
    "正在停止...": "Stopping...",
    "正在停止，当前页处理完后停止": "Stopping after the current page",
    "已请求停止，当前页处理完后停止": "Stop requested; will stop after the current page",
    "没有识别到可用发票。若是扫描件，请确认页面清晰；也可手动新增发票。": (
        "No usable invoices were recognized. For scans, check image quality; you can also add one manually."
    ),
    "注意": "Check",
    "请先选择一行明细": "Select a row first",
    "没有可生成的发票": "No invoices to generate",
    "请先设置输出路径": "Set the output path first",
    "自检发现问题:": "Self-check issues:",
    "自检: 金额/税金/价税合计核对通过": "Self-check: amount/tax/total OK",
    "输出文件还不存在": "Output file does not exist",
    "退出": "Exit",
    "正在识别，确定退出吗？": "Recognition is running. Exit anyway?",
    "保存入库单": "Save receipt",
    "选择发票 PDF 或图片": "Select invoice PDF or image",
    "添加文件": "Add Files",
    "发票文件": "Invoice files",
    "所有文件": "All files",
    "选择发票文件夹": "Select invoice folder",
    "选择历史入库单所在文件夹": "Select folder with previous receipts",
    "程序出错": "Program Error",
    "界面异常: ": "UI error: ",
    "已写入日志: ": "Written to log: ",
    "生成完成": "Generation Complete",
    "完成": "Done",
    "是否打开生成的 Excel？": "Open the generated Excel?",
    "生成失败": "Generation Failed",
    "打开失败": "Open Failed",
    "PDF 检查通过": "PDF Check Passed",
    "PDF 检查: ": "PDF check: ",
    "PDF 检查失败: ": "PDF check failed: ",
    "是否导出 PDF 做版式检查？": "Export PDF for layout check?",
    "是否打开 PDF？": "Open the PDF?",
    "学习失败": "Learning Failed",
    "（约 ": " (~",
    " 页）": " pages)",
    " 张发票": " invoice(s)",
    " — 可在左侧核对后生成 Excel": " — review on the left, then generate Excel",
    " 页 — 请查看日志或手动新增": " page(s) skipped — see log or add manually",
    "使用步骤：": "How to use:",
    "使用步骤：添加/拖拽 PDF/图片 → 点“开始识别” → 在“明细与字段”里校对 → 生成 Excel。": (
        "How to use: add/drag PDF/images → click Start → review under Details & Fields → Generate Excel."
    ),
    "尚未添加文件。点“添加 PDF/图片”，或把文件拖到左侧列表。": (
        "No files added yet. Click Add PDF/Images, or drag files to the list on the left."
    ),
    " 首次使用请先点右上角“公司设置”，填写公司名。": (
        " First-time users: open Company Settings and fill in your company name."
    ),
    "跳过 ": "Skipped ",
    " 第": " page ",
    "页: ": ": ",
    "已添加 ": "Added ",
    " 个输入": " input(s)",
    ": 新增 ": ": ",
    " 项，等待识别": " new item(s), waiting to recognize",
    ": 没有新增（可能已在列表里）": ": nothing new (already in the list)",
    "不支持的文件，已忽略: ": "Unsupported files ignored: ",
    "松开鼠标即可添加": "Release to add",
    "松开鼠标即可添加文件/文件夹": "Release to add files/folders",
    "已添加 1 个文件：": "Added 1 file: ",
    " — 点上方“开始识别”": " — click Start above",
    "已添加 1 个文件夹：": "Added 1 folder: ",
    " 个文件）": " file(s))",
    " 个文件": " file(s)",
    " 个文件夹": " folder(s)",
    "识别完成: ": "Done: ",
    " 张发票，跳过 ": " invoice(s), ",
    " 页": " page(s) skipped",
    "识别完成：": "Done: ",
    "识别完成：没有可用发票，跳过 ": "Done: no usable invoices, ",
    "已应用发票修改: ": "Invoice changes applied: ",
    "已应用第": "Row ",
    "行修改": " applied",
    "已应用日期: 到货=": "Dates applied: arrival=",
    ", 入库=": ", stock=",
    "已删除第": "Deleted row ",
    "行": "",
    "学习完成: ": "Learned ",
    " 条项目记录, ": " item record(s), ",
    " 个供应商别名": " supplier alias(es)",
    "\n... 共 ": "\n... total ",
    " 条": " item(s)",
    "已生成：": "Generated: ",
    "已生成 ": "Generated ",
    " 张工作表：\n": " sheet(s):\n",
    "\n\n是否导出 PDF 做版式检查？": "\n\nExport PDF for layout check?",
    "已保存公司设置：标题=": "Company settings saved: title=",
    "，购买方=": ", buyer=",
    "公司设置已保存：之后生成的入库单会使用新的标题和购买方": (
        "Company settings saved. New receipts will use the new title and buyer name."
    ),
    "识别失败: ": "Recognition failed: ",
    "正在识别，请稍候": "Recognition in progress, please wait",
    "已添加一行明细": "Row added",
    "已按明细重算合计": "Totals recalculated from line items",
    "已手动新增一张空白发票，请填写销售方、发票号、日期和明细": (
        "Added a blank invoice. Fill in seller, invoice number, date and line items."
    ),
    "没有可生成的发票": "No invoices to generate",
    "还没有添加文件。点“添加 PDF/图片”，或把文件拖到左侧列表。": (
        "No files added yet. Click Add PDF/Images, or drag files to the left list."
    ),
    "（约 ": " (~",
    " 页）": " pages)",
}

HELP_ZH = (
    "使用步骤：\n"
    "1. 添加 PDF/图片，或直接把文件/文件夹拖到左侧列表区域。\n"
    "2. 点“开始识别”。电子票会直接读文字层，扫描件自动旋转、OCR，并读取发票二维码核对号码/金额/日期。\n"
    "3. 在左侧选择发票，在“明细与字段”里核对；双击明细行可编辑。\n"
    "4. 设置年份/月份/输出路径，点“生成 Excel”。\n"
    "5. 生成后可选导出 PDF 检查版式（需要电脑安装 Excel）。\n\n"
    "说明：\n"
    "- 费用报销单等非发票页会自动跳过。\n"
    "- 供应商简写默认去掉“有限公司/个体工商户”等后缀，可在“表名简写”里改。\n"
    "- 材料名称/规格会尽量保留发票全文；如有识别错字，请在此处修正。\n"
    "- 可用“学习历史入库单”导入旧表，提高项目/单位/规格匹配。\n"
    "- 输出为 .xls；入库单/打印模板保持中文，符合国内财务/税务使用习惯。\n"
)

HELP_EN = (
    "How to use:\n"
    "1. Add PDF/images, or drag files/folders into the list on the left.\n"
    "2. Click Start. Electronic invoices are read from the PDF text layer; scans are rotated and OCR'd. "
    "The QR code is used to verify number/amount/date.\n"
    "3. Select an invoice on the left and review it under Details & Fields. Double-click a line item to edit.\n"
    "4. Set year/month/output path, then click Generate Excel.\n"
    "5. Optionally export a PDF to check the layout (requires Excel).\n\n"
    "Notes:\n"
    "- Non-invoice pages such as expense forms are skipped automatically.\n"
    "- Supplier aliases drop suffixes like Co., Ltd. / sole proprietorship by default; edit Sheet Name if needed.\n"
    "- Item names/specs keep the invoice text as much as possible; fix OCR errors here.\n"
    "- Learn History imports previous receipts to improve item/unit/spec matching.\n"
    "- Output is .xls. The receipt/print template stays in Chinese for domestic finance and tax use.\n"
)

EN["使用步骤：\n1. 添加 PDF/图片，或直接把文件/文件夹拖到左侧列表区域。\n2. 点“识别”。扫描件会自动旋转、OCR，并读取发票二维码核对号码/金额/日期。\n3. 在左侧选择发票，在“明细与字段”里核对；双击明细行可编辑。\n4. 设置年份/月份/输出路径，点“生成 Excel”。\n5. 生成后可选导出 PDF 检查版式（需要电脑安装 Excel）。\n\n说明：\n- 费用报销单等非发票页会自动跳过。\n- 供应商简写默认去掉“有限公司/个体工商户”等后缀，可在“表名简写”里改。\n- 材料名称/规格会尽量保留发票全文；如有 OCR 错字，请在此处修正。\n- 可用“学习历史入库单”导入旧表，提高项目/单位/规格匹配。\n- 输出为 .xls，打印设置已按 Epson LQ-730K 三联复写纸配置。\n"] = HELP_EN


PATTERNS = [
    (r"^正在识别 (.+)$", r"Recognizing \1"),
    (r"^识别完成$", "Done"),
    (r"^已完成$", "Completed"),
    (r"^已停止$", "Stopped"),
    (r"^识别完成: (\d+) 张发票，跳过 (\d+) 页$", r"Done: \1 invoice(s), \2 page(s) skipped"),
    (r"^识别完成：(\d+) 张发票，跳过 (\d+) 页 — 可在左侧核对后生成 Excel$", r"Done: \1 invoice(s), \2 page(s) skipped — review on the left, then generate Excel"),
    (r"^(.+?) 第(\d+)页$", r"\1 page \2"),
    (r"^跳过 (.+?) 第(\d+)页: (.+)$", r"Skipped \1 page \2: \3"),
    (r"^(.+?) 第(\d+)页: (.*?) (\d+(?:\.\d+)?) 元, (\d+) 项 \[(.*?)\]$", r"\1 page \2: \3 \4 CNY, \5 item(s) [\6]"),
    (r"^(.+?) 第(\d+)页: (.+)$", r"\1 page \2: \3"),
    (r"^第(\d+)行缺少单位$", r"Line \1: missing unit"),
    (r"^第(\d+)行缺少材料名称$", r"Line \1: missing item name"),
    (r"^第(\d+)行缺少数量$", r"Line \1: missing quantity"),
    (r"^第(\d+)行缺少金额$", r"Line \1: missing amount"),
    (r"^第(\d+)行为负数，请核对是否为优惠行$", r"Line \1: negative amount; check if it is a discount"),
    (r"^第(\d+)行金额×税率与税额不一致$", r"Line \1: amount × tax rate does not match tax"),
    (r"^第(\d+)行优惠已合并到第(\d+)行$", r"Line \1: discount merged into line \2"),
    (r"^第(\d+)行优惠合并后金额仍为负数，已忽略该商品行$", r"Line \1: discount still negative after merge; item ignored"),
    (r"^第(\d+)行是负数优惠，但前面没有可合并的商品行，已忽略$", r"Line \1: negative discount without a matching item; ignored"),
    (r"^明细合计\((.+?)\)与发票合计不一致$", r"Line totals (\1) do not match invoice total"),
    (r"^未识别到销售方名称$", "Seller not recognized"),
    (r"^未识别到发票号码$", "Invoice number not recognized"),
    (r"^未识别到开票日期$", "Invoice date not recognized"),
    (r"^未识别到明细$", "No line items recognized"),
    (r"^未识别到价税合计$", "Invoice total not recognized"),
    (r"^金额合计\+税金合计不等于价税合计$", "Amount + tax does not equal invoice total"),
    (r"^明细金额之和与金额合计不一致$", "Sum of line amounts does not match invoice amount"),
    (r"^明细税额之和与税金合计不一致$", "Sum of line taxes does not match invoice tax"),
    (r"^不是发票页（可能是费用报销单）$", "Not an invoice page (maybe an expense form)"),
    (r"^一页识别到多张发票，请拆分为单页后处理$", "Multiple invoices on one page; split the page first"),
    (r"^重复发票 (.+)$", r"Duplicate invoice \1"),
    (r"^疑似重复发票$", "Possible duplicate invoice"),
    (r"^强制文字层模式：该页没有可用文字层（可能是扫描件/图片）$", "Text mode: no text layer on this page (scan/image)"),
    (r"^强制文字层模式：(.+)$", r"Text mode: \1"),
    (r"^已识别到发票 (.*?)（(.*?)），但(.+?)，请手动新增或校对$", r"Found invoice \1 (\2), but \3; add manually or review"),
    (r"^读取失败: (.+)$", r"Read failed: \1"),
    (r"^OCR失败: (.+)$", r"OCR failed: \1"),
    (r"^解析失败: (.+)$", r"Parse failed: \1"),
    (r"^文字层解析失败: (.+)$", r"Text-layer parsing failed: \1"),
    (r"^文字层校验未通过，已OCR交叉校验：(.+)$", r"Text-layer check failed; OCR cross-check: \1"),
    (r"^文字层校验未通过且OCR回退失败：(.+)$", r"Text-layer check failed and OCR fallback failed: \1"),
    (r"^(.+?): 未安装/无法加载 pdfplumber.*，文字层不可用，将使用 OCR$", r"\1: pdfplumber unavailable; using OCR"),
    (r"^(.+?): 文字层为旋转页，按扫描件走 OCR$", r"\1: rotated page; using OCR"),
    (r"^(.+?): 文字层读取失败，改用 OCR（(.+?)）$", r"\1: text layer read failed; using OCR (\2)"),
    (r"^没有找到 PDF 或图片文件$", "No PDF or image files found"),
    (r"^无法打开 PDF \((.+)\)$", r"Cannot open PDF (\1)"),
    (r"^已添加 1 个文件：(.+?)（约 (\d+) 页） — 点上方“开始识别”$", r"Added 1 file: \1 (~\2 pages) — click Start above"),
    (r"^已添加 1 个文件夹：(\d+) 个文件） — 点上方“开始识别”$", r"Added 1 folder: \1 file(s) — click Start above"),
    (r"^已添加 (\d+) 个文件（约 (\d+) 页） — 点上方“开始识别”$", r"Added \1 file(s) (~\2 pages) — click Start above"),
    (r"^已添加 (\d+) 个输入：新增 (\d+) 项，等待识别$", r"Added \1 input(s): \2 new, waiting to recognize"),
    (r"^已添加 (\d+) 个输入: 没有新增（可能已在列表里）$", r"Added \1 input(s): nothing new (already in the list)"),
    (r"^不支持的文件，已忽略: (.+)$", r"Unsupported files ignored: \1"),
    (r"^开始识别（(.*?)）: (.+)$", r"Start (\1): \2"),
    (r"^已应用发票修改: (.+)$", r"Invoice changes applied: \1"),
    (r"^已应用第(\d+)行修改$", r"Row \1 applied"),
    (r"^已应用日期: 到货=(.*), 入库=(.*)$", r"Dates applied: arrival=\1, stock=\2"),
    (r"^已删除第(\d+)行$", r"Deleted row \1"),
    (r"^学习完成: (\d+) 条项目记录, (\d+) 个供应商别名$", r"Learned \1 item record(s), \2 supplier alias(es)"),
    (r"^识别完成：(\d+) 张发票(.*?) — 可在左侧核对后生成 Excel$", r"Done: \1 invoice(s)\2 — review on the left, then generate Excel"),
    (r"^识别完成：没有可用发票，跳过 (\d+) 页 — 请查看日志或手动新增$", r"Done: no usable invoices, \1 page(s) skipped — see log or add manually"),
    (r"^发现以下警告：$", "Warnings:"),
    (r"^\.\.\. 共 (\d+) 条$", r"... total \1 item(s)"),
    (r"^已保存公司设置：标题=(.*)，购买方=(.*)$", r"Company settings saved: title=\1, buyer=\2"),
]


def tr(text: str) -> str:
    if not text:
        return text
    if get_language() != "en":
        return text
    return EN.get(text, text)


def tr_runtime(text: str) -> str:
    if not text or get_language() != "en":
        return text
    out = EN.get(text, text)
    for _ in range(5):
        prev = out
        for pattern, repl in PATTERNS:
            try:
                out = re.sub(pattern, repl, out)
            except re.error:
                continue
        if out == prev:
            break
    return out


def help_text() -> str:
    return HELP_EN if get_language() == "en" else HELP_ZH
