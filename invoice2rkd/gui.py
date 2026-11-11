from __future__ import annotations

import os
import queue
import threading
import time
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False

from .core import (
    IMAGE_EXTS,
    PDF_EXTS,
    USER_DIR,
    Invoice,
    LineItem,
    ProcessResult,
    alias_for,
    amount_to_text,
    assign_sheet_names,
    collect_input_files,
    company_needs_setup,
    get_company,
    infer_unit,
    learn_from_folder,
    process_inputs,
    save_company,
)
from .excel_writer import export_pdf_and_check, verify_workbook, write_workbook
from .i18n import EN, get_language, help_text, set_language, tr, tr_runtime


def _float_or_none(text: str) -> Optional[float]:
    text = (text or "").strip().replace(",", "").replace("，", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _rate_or_none(text: str) -> Optional[float]:
    text = (text or "").strip().replace("%", "")
    if not text:
        return None
    try:
        return float(text) / 100.0
    except ValueError:
        return None


class PreviewPane(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.canvas = tk.Canvas(self, background="#f7f7f7", highlightthickness=0)
        self.hbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self.hbar.set, yscrollcommand=self.vbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.photo = None
        self.image = None
        self.path = ""
        self.canvas.bind("<Configure>", lambda e: self.render())

    def show(self, path: str):
        self.path = path or ""
        self.image = None
        if path and os.path.exists(path):
            try:
                self.image = Image.open(path)
            except Exception:
                self.image = None
        self.render()

    def render(self):
        self.canvas.delete("all")
        if self.image is None:
            self.canvas.create_text(20, 20, anchor="nw", text=tr("（无预览）"), fill="#777")
            return
        w = max(200, self.canvas.winfo_width() - 10)
        h = max(200, self.canvas.winfo_height() - 10)
        img = self.image.copy()
        img.thumbnail((w, h), Image.LANCZOS)
        self.photo = ImageTk.PhotoImage(img)
        self.canvas.create_image(w // 2, h // 2, image=self.photo, anchor="center")
        self.canvas.configure(scrollregion=(0, 0, w, h))


if DND_AVAILABLE:

    class _AppBase(TkinterDnD.Tk):
        pass

else:

    class _AppBase(tk.Tk):
        pass


class App(_AppBase):
    def __init__(self, initial_inputs=None):
        super().__init__()
        self.title("扫描发票 → 入库单生成器")
        self.geometry("1420x900")
        self.minsize(1100, 700)
        self.result = ProcessResult()
        self.invoices: list[Invoice] = []
        self.current_index = -1
        self.inputs: list[str] = []
        self.worker: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.msg_queue = queue.Queue()
        self._polling = False
        self.output_path = tk.StringVar()
        self.year_var = tk.StringVar(value=str(time.localtime().tm_year))
        self.month_var = tk.StringVar(value=str(time.localtime().tm_mon))
        self.arrival_var = tk.StringVar()
        self.stock_var = tk.StringVar()
        self.progress_var = tk.DoubleVar(value=0)
        self.status_var = tk.StringVar(value=tr("就绪"))
        self.mode_var = tk.StringVar(value=tr("自动（推荐）"))
        self.language_var = tk.StringVar(value="中文" if get_language() == "zh" else "English")
        self.banner_var = tk.StringVar(value="")
        self.seller_var = tk.StringVar()
        self.number_var = tk.StringVar()
        self.date_var = tk.StringVar()
        self.total_var = tk.StringVar()
        self.amount_var = tk.StringVar()
        self.tax_var = tk.StringVar()
        self.alias_var = tk.StringVar()
        self.inv_arrival_var = tk.StringVar()
        self.inv_stock_var = tk.StringVar()
        self.item_name_var = tk.StringVar()
        self.item_spec_var = tk.StringVar()
        self.item_unit_var = tk.StringVar()
        self.item_qty_var = tk.StringVar()
        self.item_amount_var = tk.StringVar()
        self.item_rate_var = tk.StringVar()
        self.item_tax_var = tk.StringVar()
        self.item_remark_var = tk.StringVar()
        self._build_style()
        self._build_ui()
        self._apply_language()
        if initial_inputs:
            self.inputs = list(initial_inputs)
            self._guess_output()
        self.report_callback_exception = self._report_callback_exception
        self.bind_all("<Control-r>", lambda event: self.start_process())
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Treeview", rowheight=26, font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("TButton", font=("Microsoft YaHei UI", 9))
        style.configure("TLabel", font=("Microsoft YaHei UI", 9))
        style.configure("TEntry", font=("Microsoft YaHei UI", 9))

    def _build_ui(self):
        toolbar = ttk.Frame(self, padding=(8, 6))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(20, weight=1)

        ttk.Button(toolbar, text="添加 PDF/图片", command=self.add_files).grid(row=0, column=0, padx=(0, 4))
        ttk.Button(toolbar, text="添加文件夹", command=self.add_folder).grid(row=0, column=1, padx=4)
        ttk.Button(toolbar, text="清空", command=self.clear_inputs).grid(row=0, column=2, padx=4)
        self.recognize_button = tk.Button(
            toolbar,
            text="开始识别",
            command=self.start_process,
            bg="#2E7D32",
            fg="white",
            activebackground="#1B5E20",
            activeforeground="white",
            font=("Microsoft YaHei UI", 12, "bold"),
            padx=18,
            pady=6,
            relief="raised",
            bd=2,
            cursor="hand2",
        )
        self.recognize_button.grid(row=0, column=3, padx=(12, 6), sticky="ns")
        ttk.Button(toolbar, text="停止", command=self.stop_process).grid(row=0, column=4, padx=4)
        ttk.Button(toolbar, text="学习历史入库单", command=self.learn_history).grid(row=0, column=6, padx=(12, 4))
        ttk.Button(toolbar, text="使用说明", command=self.show_help).grid(row=0, column=5, padx=4)

        ttk.Label(toolbar, text="输出:").grid(row=0, column=7, padx=(16, 2))
        ttk.Entry(toolbar, textvariable=self.output_path, width=52).grid(row=0, column=8, columnspan=4, sticky="ew")
        ttk.Button(toolbar, text="浏览", command=self.browse_output).grid(row=0, column=12, padx=4)
        ttk.Button(toolbar, text="默认路径", command=self._guess_output).grid(row=0, column=13, padx=4)

        ttk.Label(toolbar, text="年").grid(row=1, column=0, pady=(6, 0))
        ttk.Entry(toolbar, textvariable=self.year_var, width=6).grid(row=1, column=1, sticky="w", pady=(6, 0))
        ttk.Label(toolbar, text="月").grid(row=1, column=2, pady=(6, 0))
        ttk.Entry(toolbar, textvariable=self.month_var, width=4).grid(row=1, column=3, sticky="w", pady=(6, 0))
        ttk.Label(toolbar, text="到货日期").grid(row=1, column=4, padx=(16, 2), pady=(6, 0))
        ttk.Entry(toolbar, textvariable=self.arrival_var, width=13).grid(row=1, column=5, pady=(6, 0))
        ttk.Label(toolbar, text="入库日期").grid(row=1, column=6, padx=(12, 2), pady=(6, 0))
        ttk.Entry(toolbar, textvariable=self.stock_var, width=13).grid(row=1, column=7, pady=(6, 0))
        ttk.Button(toolbar, text="应用到全部", command=self.apply_dates_all).grid(row=1, column=8, padx=4, pady=(6, 0))
        ttk.Label(toolbar, text="留空 = 开票日期").grid(row=1, column=9, columnspan=3, padx=4, pady=(6, 0))
        ttk.Button(toolbar, text="生成 Excel", command=self.generate_excel).grid(row=1, column=12, padx=4, pady=(6, 0))
        ttk.Button(toolbar, text="打开输出", command=self.open_output).grid(row=1, column=13, padx=4, pady=(6, 0))
        ttk.Button(toolbar, text="公司设置", command=self.edit_company).grid(row=1, column=14, padx=(12, 4), pady=(6, 0))

        progress_frame = ttk.Frame(self, padding=(8, 0))
        progress_frame.grid(row=1, column=0, sticky="ew")
        progress_frame.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress.grid(row=0, column=0, sticky="ew")
        ttk.Label(progress_frame, textvariable=self.status_var, width=34).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(progress_frame, text="识别模式:").grid(row=0, column=2, padx=(10, 2))
        self.mode_combo = ttk.Combobox(
            progress_frame,
            textvariable=self.mode_var,
            values=tuple(tr(k) for k in ("自动（推荐）", "仅文字层（电子票）", "仅OCR（扫描件）")),
            state="readonly",
            width=18,
        )
        self.mode_combo.grid(row=0, column=3)
        ttk.Label(progress_frame, text="语言/Language:").grid(row=0, column=4, padx=(14, 2))
        self.lang_combo = ttk.Combobox(
            progress_frame,
            textvariable=self.language_var,
            values=("中文", "English"),
            state="readonly",
            width=9,
        )
        self.lang_combo.grid(row=0, column=5)
        self.lang_combo.bind("<<ComboboxSelected>>", self.on_language_change)

        main = ttk.PanedWindow(self, orient="horizontal")
        main.grid(row=2, column=0, sticky="nsew", padx=8, pady=6)
        self.rowconfigure(2, weight=1)
        self.columnconfigure(0, weight=1)

        left = ttk.Frame(main)
        main.add(left, weight=1)
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)
        self.drop_hint = tk.Label(
            left,
            text=("把 PDF/图片/文件夹拖到这里" if DND_AVAILABLE else "点上方添加 PDF/图片/文件夹"),
            bg="#F0F0F0",
            fg="#666666",
            font=("Microsoft YaHei UI", 9),
            anchor="center",
            padx=6,
            pady=6,
            relief="groove",
            bd=1,
        )
        self.drop_hint.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        columns = ("idx", "seller", "number", "total", "items", "status", "source")
        self.invoice_tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        headings = {
            "idx": "#",
            "seller": "销售方",
            "number": "发票号",
            "total": "价税合计",
            "items": "项数",
            "status": "状态",
            "source": "来源",
        }
        widths = {"idx": 40, "seller": 180, "number": 150, "total": 90, "items": 50, "status": 60, "source": 130}
        for c in columns:
            self.invoice_tree.heading(c, text=headings[c])
            self.invoice_tree.column(c, width=widths[c], anchor="center" if c not in ("seller", "source") else "w")
        self.invoice_tree.grid(row=1, column=0, sticky="nsew")
        self.invoice_tree.tag_configure("warn", foreground="#b35c00")
        self.invoice_tree.bind("<<TreeviewSelect>>", self.on_select_invoice)
        yscroll = ttk.Scrollbar(left, orient="vertical", command=self.invoice_tree.yview)
        yscroll.grid(row=1, column=1, sticky="ns")
        self.invoice_tree.configure(yscrollcommand=yscroll.set)
        ttk.Button(left, text="手动新增一张发票", command=self.add_manual_invoice).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        if DND_AVAILABLE:
            for target in (left, self.invoice_tree, self.drop_hint):
                try:
                    target.drop_target_register(DND_FILES)
                    target.dnd_bind("<<Drop>>", self.on_drop)
                    target.dnd_bind("<<DropEnter>>", self.on_drag_enter)
                    target.dnd_bind("<<DropLeave>>", self.on_drag_leave)
                except Exception:
                    pass

        right = ttk.Notebook(main)
        main.add(right, weight=3)

        preview_tab = ttk.Frame(right)
        right.add(preview_tab, text="发票预览")
        preview_tab.rowconfigure(0, weight=1)
        preview_tab.columnconfigure(0, weight=1)
        self.preview = PreviewPane(preview_tab)
        self.preview.grid(row=0, column=0, sticky="nsew")

        detail_tab = ttk.Frame(right, padding=6)
        right.add(detail_tab, text="明细与字段")
        detail_tab.columnconfigure(0, weight=1)
        detail_tab.rowconfigure(3, weight=1)

        fields = ttk.LabelFrame(detail_tab, text="发票字段", padding=6)
        fields.grid(row=0, column=0, sticky="ew")
        for i in range(6):
            fields.columnconfigure(i, weight=1 if i in (1, 3, 5) else 0)
        ttk.Label(fields, text="销售方").grid(row=0, column=0, sticky="e", padx=4, pady=2)
        ttk.Entry(fields, textvariable=self.seller_var).grid(row=0, column=1, sticky="ew", padx=4, pady=2)
        ttk.Label(fields, text="发票号码").grid(row=0, column=2, sticky="e", padx=4, pady=2)
        ttk.Entry(fields, textvariable=self.number_var).grid(row=0, column=3, sticky="ew", padx=4, pady=2)
        ttk.Label(fields, text="开票日期").grid(row=0, column=4, sticky="e", padx=4, pady=2)
        ttk.Entry(fields, textvariable=self.date_var, width=14).grid(row=0, column=5, sticky="ew", padx=4, pady=2)
        ttk.Label(fields, text="价税合计").grid(row=1, column=0, sticky="e", padx=4, pady=2)
        ttk.Entry(fields, textvariable=self.total_var, width=14).grid(row=1, column=1, sticky="w", padx=4, pady=2)
        ttk.Label(fields, text="金额合计").grid(row=1, column=2, sticky="e", padx=4, pady=2)
        ttk.Entry(fields, textvariable=self.amount_var, width=14).grid(row=1, column=3, sticky="w", padx=4, pady=2)
        ttk.Label(fields, text="税金合计").grid(row=1, column=4, sticky="e", padx=4, pady=2)
        ttk.Entry(fields, textvariable=self.tax_var, width=14).grid(row=1, column=5, sticky="w", padx=4, pady=2)
        ttk.Label(fields, text="表名简写").grid(row=2, column=0, sticky="e", padx=4, pady=2)
        ttk.Entry(fields, textvariable=self.alias_var).grid(row=2, column=1, sticky="ew", padx=4, pady=2)
        ttk.Label(fields, text="到货时间").grid(row=2, column=2, sticky="e", padx=4, pady=2)
        ttk.Entry(fields, textvariable=self.inv_arrival_var, width=14).grid(row=2, column=3, sticky="w", padx=4, pady=2)
        ttk.Label(fields, text="入库时间").grid(row=2, column=4, sticky="e", padx=4, pady=2)
        ttk.Entry(fields, textvariable=self.inv_stock_var, width=14).grid(row=2, column=5, sticky="w", padx=4, pady=2)
        ttk.Button(fields, text="应用发票修改", command=self.apply_invoice_edits).grid(row=0, column=6, padx=4)
        ttk.Button(fields, text="按明细重算合计", command=self.recalc_invoice).grid(row=1, column=6, padx=4)
        fields.columnconfigure(6, weight=0)

        item_frame = ttk.LabelFrame(detail_tab, text="明细行（双击选择，编辑后点“应用行修改”）", padding=4)
        item_frame.grid(row=3, column=0, sticky="nsew", pady=(6, 0))
        item_frame.rowconfigure(0, weight=1)
        item_frame.columnconfigure(0, weight=1)
        icols = ("idx", "name", "spec", "unit", "qty", "price", "amount", "rate", "tax", "total")
        self.item_tree = ttk.Treeview(item_frame, columns=icols, show="headings", selectmode="browse", height=8)
        iheads = {
            "idx": "序号",
            "name": "材料名称",
            "spec": "规格型号",
            "unit": "单位",
            "qty": "数量",
            "price": "单价",
            "amount": "金额",
            "rate": "税率",
            "tax": "税金",
            "total": "含税价",
        }
        iwidths = {"idx": 40, "name": 260, "spec": 170, "unit": 48, "qty": 70, "price": 90, "amount": 90, "rate": 55, "tax": 85, "total": 90}
        for c in icols:
            self.item_tree.heading(c, text=iheads[c])
            self.item_tree.column(c, width=iwidths[c], anchor="center" if c not in ("name", "spec") else "w")
        self.item_tree.grid(row=0, column=0, sticky="nsew")
        self.item_tree.bind("<<TreeviewSelect>>", self.on_item_select)
        self.item_tree.bind("<Double-1>", self.on_item_select)
        iy = ttk.Scrollbar(item_frame, orient="vertical", command=self.item_tree.yview)
        iy.grid(row=0, column=1, sticky="ns")
        self.item_tree.configure(yscrollcommand=iy.set)

        edit = ttk.Frame(detail_tab)
        edit.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        for i in range(10):
            edit.columnconfigure(i, weight=1 if i in (1, 4, 7) else 0)
        ttk.Label(edit, text="名称").grid(row=0, column=0, sticky="e", padx=2)
        ttk.Entry(edit, textvariable=self.item_name_var).grid(row=0, column=1, sticky="ew", padx=2)
        ttk.Label(edit, text="规格").grid(row=0, column=2, sticky="e", padx=2)
        ttk.Entry(edit, textvariable=self.item_spec_var).grid(row=0, column=3, sticky="ew", padx=2)
        ttk.Label(edit, text="单位").grid(row=0, column=4, sticky="e", padx=2)
        ttk.Entry(edit, textvariable=self.item_unit_var, width=8).grid(row=0, column=5, sticky="w", padx=2)
        ttk.Label(edit, text="数量").grid(row=0, column=6, sticky="e", padx=2)
        ttk.Entry(edit, textvariable=self.item_qty_var, width=10).grid(row=0, column=7, sticky="w", padx=2)
        ttk.Label(edit, text="金额").grid(row=0, column=8, sticky="e", padx=2)
        ttk.Entry(edit, textvariable=self.item_amount_var, width=10).grid(row=0, column=9, sticky="w", padx=2)
        ttk.Label(edit, text="税率%").grid(row=1, column=0, sticky="e", padx=2)
        ttk.Entry(edit, textvariable=self.item_rate_var, width=10).grid(row=1, column=1, sticky="w", padx=2)
        ttk.Label(edit, text="税金").grid(row=1, column=2, sticky="e", padx=2)
        ttk.Entry(edit, textvariable=self.item_tax_var, width=10).grid(row=1, column=3, sticky="w", padx=2)
        ttk.Label(edit, text="备注").grid(row=1, column=4, sticky="e", padx=2)
        ttk.Entry(edit, textvariable=self.item_remark_var).grid(row=1, column=5, columnspan=2, sticky="ew", padx=2)
        ttk.Button(edit, text="应用行修改", command=self.apply_item_edits).grid(row=1, column=7, padx=4)
        ttk.Button(edit, text="添加行", command=self.add_item).grid(row=1, column=8, padx=4)
        ttk.Button(edit, text="删除行", command=self.delete_item).grid(row=1, column=9, padx=4)

        log_tab = ttk.Frame(right, padding=6)
        right.add(log_tab, text="日志/警告")
        log_tab.rowconfigure(0, weight=1)
        log_tab.columnconfigure(0, weight=1)
        self.log_text = tk.Text(log_tab, wrap="word", height=10, font=("Microsoft YaHei UI", 9))
        self.log_text.grid(row=0, column=0, sticky="nsew")
        ly = ttk.Scrollbar(log_tab, orient="vertical", command=self.log_text.yview)
        ly.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=ly.set)

        status = ttk.Frame(self, padding=(8, 2))
        status.grid(row=3, column=0, sticky="ew")
        ttk.Label(status, textvariable=self.status_var).pack(side="left")
        self.append_log("使用步骤：添加/拖拽 PDF/图片 → 点“开始识别” → 在“明细与字段”里校对 → 生成 Excel。")
        self.banner = tk.Label(
            toolbar,
            textvariable=self.banner_var,
            bg="#FFF3CD",
            fg="#7A4F00",
            font=("Microsoft YaHei UI", 10, "bold"),
            anchor="w",
            padx=10,
            pady=6,
            relief="solid",
            bd=1,
        )
        self.banner.grid(row=2, column=0, columnspan=21, sticky="ew", pady=(8, 0))
        self.update_banner(self._input_summary())

    def _translate_widget_tree(self, widget):
        for child in widget.winfo_children():
            try:
                text = child.cget("text")
                if isinstance(text, str) and text:
                    if not hasattr(child, "_i18n_src"):
                        child._i18n_src = text
                    child.configure(text=tr(child._i18n_src))
            except Exception:
                pass
            if isinstance(child, ttk.Notebook):
                try:
                    if not hasattr(child, "_i18n_tabs"):
                        child._i18n_tabs = {tab: child.tab(tab, "text") for tab in child.tabs()}
                    for tab, src in child._i18n_tabs.items():
                        child.tab(tab, text=tr(src))
                except Exception:
                    pass
            if isinstance(child, ttk.Treeview):
                try:
                    if not hasattr(child, "_i18n_headings"):
                        child._i18n_headings = {
                            col: child.heading(col, "text") for col in child["columns"]
                        }
                    for col, src in child._i18n_headings.items():
                        child.heading(col, text=tr(src))
                except Exception:
                    pass
            self._translate_widget_tree(child)

    def _apply_language(self):
        self.language_var.set("中文" if get_language() == "zh" else "English")
        self.title(tr("扫描发票 → 入库单生成器"))
        self._translate_widget_tree(self)
        mode_keys = ("自动（推荐）", "仅文字层（电子票）", "仅OCR（扫描件）")
        current = self.mode_var.get()
        idx = 0
        for i, key in enumerate(mode_keys):
            if current in (key, EN.get(key), tr(key)):
                idx = i
                break
        self.mode_combo["values"] = tuple(tr(k) for k in mode_keys)
        self.mode_var.set(tr(mode_keys[idx]))
        try:
            if self.worker and self.worker.is_alive():
                self.recognize_button.configure(text=tr("识别中..."))
                self.status_var.set(tr("正在识别..."))
            else:
                self.recognize_button.configure(text=tr("开始识别"))
                self.status_var.set(tr("就绪"))
        except Exception:
            pass
        self.update_banner(self._input_summary())

    def on_language_change(self, event=None):
        lang = "zh" if self.language_var.get() == "中文" else "en"
        if lang == get_language():
            return
        set_language(lang)
        self._apply_language()
        self.append_log("界面语言已切换 / UI language changed")

    def _report_callback_exception(self, exc, val, tb):
        import traceback

        text = "".join(traceback.format_exception(exc, val, tb))
        try:
            with open(USER_DIR / "error.log", "a", encoding="utf-8") as f:
                f.write(text)
                f.write("\n" + "=" * 80 + "\n")
        except Exception:
            pass
        self.append_log(tr("界面异常: ") + text)
        try:
            messagebox.showerror(
                tr("程序出错"),
                tr("已写入日志: ") + str(USER_DIR / "error.log") + "\n\n" + text[-1500:],
            )
        except Exception:
            pass

    def append_log(self, text: str):
        self.log_text.insert("end", tr_runtime(text).rstrip() + "\n")
        self.log_text.see("end")

    def update_banner(self, text: str, kind: str = "info"):
        colors = {
            "info": ("#FFF3CD", "#7A4F00"),
            "warn": ("#FFE0B2", "#8A4B00"),
            "success": ("#D9EAD3", "#274E13"),
            "error": ("#F4CCCC", "#7F0000"),
        }
        bg, fg = colors.get(kind, colors["info"])
        self.banner_var.set(tr_runtime(text))
        try:
            self.banner.configure(bg=bg, fg=fg)
        except Exception:
            pass

    def _input_summary(self) -> str:
        en = get_language() == "en"
        if not self.inputs:
            if en:
                text = "No files added yet. Click Add PDF/Images, or drag files to the list on the left."
                if company_needs_setup():
                    text += " First-time users: open Company Settings and fill in your company name."
                return text
            text = "尚未添加文件。点“添加 PDF/图片”，或把文件拖到左侧列表。"
            if company_needs_setup():
                text += " 首次使用请先点右上角“公司设置”，填写公司名。"
            return text
        files = [Path(p) for p in self.inputs if Path(p).is_file()]
        folders = [Path(p) for p in self.inputs if Path(p).is_dir()]
        pages = 0
        page_known = True
        for p in files:
            if p.suffix.lower() == ".pdf":
                try:
                    import pypdfium2 as pdfium

                    doc = pdfium.PdfDocument(str(p))
                    try:
                        pages += len(doc)
                    finally:
                        doc.close()
                except Exception:
                    page_known = False
            else:
                pages += 1
        folder_files = 0
        for d in folders:
            try:
                folder_files += len(collect_input_files([str(d)], recursive=False))
            except Exception:
                pass
        if en:
            if len(files) == 1 and not folders:
                suffix = f" (~{pages} pages)" if page_known else ""
                return f"Added 1 file: {files[0].name}{suffix} — click Start above"
            if len(folders) == 1 and not files:
                suffix = f" ({folder_files} files)" if folder_files else ""
                return f"Added 1 folder: {folders[0].name}{suffix} — click Start above"
            parts = []
            if files:
                parts.append(f"{len(files)} files" + (f" (~{pages} pages)" if page_known else ""))
            if folders:
                parts.append(f"{len(folders)} folders" + (f" ({folder_files} files)" if folder_files else ""))
            return "Added " + " + ".join(parts) + " — click Start above"
        if len(files) == 1 and not folders:
            suffix = f"（约 {pages} 页）" if page_known else ""
            return f"已添加 1 个文件：{files[0].name}{suffix} — 点上方“开始识别”"
        if len(folders) == 1 and not files:
            suffix = f"（{folder_files} 个文件）" if folder_files else ""
            return f"已添加 1 个文件夹：{folders[0].name}{suffix} — 点上方“开始识别”"
        parts = []
        if files:
            parts.append(f"{len(files)} 个文件" + (f"（约 {pages} 页）" if page_known else ""))
        if folders:
            parts.append(f"{len(folders)} 个文件夹" + (f"（{folder_files} 个文件）" if folder_files else ""))
        return "已添加 " + " + ".join(parts) + " — 点上方“开始识别”"

    def _add_paths(self, paths, source: str = "添加") -> int:
        added = 0
        unsupported = []
        for raw in paths:
            p = Path(raw)
            if not p.exists():
                continue
            if p.is_dir():
                if str(p) not in self.inputs:
                    self.inputs.append(str(p))
                    added += 1
            elif p.suffix.lower() in (IMAGE_EXTS | PDF_EXTS):
                if str(p) not in self.inputs:
                    self.inputs.append(str(p))
                    added += 1
            else:
                unsupported.append(p.name)
        en = get_language() == "en"
        if added:
            self._guess_output()
            self.status_var.set(
                f"Added {len(self.inputs)} input(s)" if en else f"已添加 {len(self.inputs)} 个输入"
            )
            self.update_banner(self._input_summary())
            if en:
                self.append_log(f"{tr(source)}: {added} new item(s), waiting to recognize")
            else:
                self.append_log(f"{source}: 新增 {added} 项，等待识别")
        elif self.inputs:
            self.update_banner(self._input_summary())
            if en:
                self.append_log(f"{tr(source)}: nothing new (already in the list)")
            else:
                self.append_log(f"{source}: 没有新增（可能已在列表里）")
        for name in unsupported:
            self.append_log(f"不支持的文件，已忽略: {name}")
        return added

    def on_drag_enter(self, event=None):
        try:
            self.drop_hint.configure(text=tr("松开鼠标即可添加"), bg="#D9EAD3", fg="#274E13")
        except Exception:
            pass
        self.update_banner(tr("松开鼠标即可添加文件/文件夹"), "warn")
        return getattr(event, "action", None) if event is not None else None

    def on_drag_leave(self, event=None):
        try:
            self.drop_hint.configure(
                text=tr("把 PDF/图片/文件夹拖到这里" if DND_AVAILABLE else "点上方添加 PDF/图片/文件夹"),
                bg="#F0F0F0",
                fg="#666666",
            )
        except Exception:
            pass
        self.update_banner(self._input_summary())
        return getattr(event, "action", None) if event is not None else None

    def on_drop(self, event):
        try:
            paths = list(self.tk.splitlist(event.data))
        except Exception:
            paths = [event.data]
        self._add_paths(paths, "拖拽")
        self.on_drag_leave()
        return getattr(event, "action", None) or "copy"

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title=tr("选择发票 PDF 或图片"),
            filetypes=[
                (tr("发票文件"), "*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
                (tr("所有文件"), "*.*"),
            ],
        )
        if paths:
            self._add_paths(paths, "添加文件")

    def add_folder(self):
        folder = filedialog.askdirectory(title=tr("选择发票文件夹"))
        if folder:
            self._add_paths([folder], "添加文件夹")

    def clear_inputs(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning(tr("提示"), tr("正在识别，请先停止"))
            return
        self.inputs = []
        self.result = ProcessResult()
        self.invoices = []
        self.current_index = -1
        self.invoice_tree.delete(*self.invoice_tree.get_children())
        self.item_tree.delete(*self.item_tree.get_children())
        self.preview.show("")
        self.progress_var.set(0)
        self.status_var.set(tr("已清空"))
        self.update_banner(self._input_summary())

    def _guess_output(self):
        if not self.inputs:
            return
        p = Path(self.inputs[0])
        base = p if p.is_dir() else p.parent
        try:
            year = int(self.year_var.get())
            month = int(self.month_var.get())
        except ValueError:
            year, month = time.localtime().tm_year, time.localtime().tm_mon
        self.output_path.set(str(base / f"{year}年{month}月份入库单.xls"))

    def browse_output(self):
        path = filedialog.asksaveasfilename(
            title=tr("保存入库单"),
            defaultextension=".xls",
            filetypes=[("Excel 97-2003", "*.xls")],
            initialfile=Path(self.output_path.get()).name if self.output_path.get() else "入库单.xls",
        )
        if path:
            self.output_path.set(path)

    def edit_company(self):
        company = get_company()
        dialog = tk.Toplevel(self)
        dialog.title(tr("公司设置"))
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")

        title_var = tk.StringVar(value=str(company.get("title") or "入库单"))
        buyer = str(company.get("buyer") or "").strip()
        if buyer == "购买方公司名称":
            buyer = ""
        buyer_var = tk.StringVar(value=buyer)

        ttk.Label(frame, text="入库单标题:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=title_var, width=42).grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=4)
        ttk.Label(frame, text="购买方公司名称:").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=buyer_var, width=42).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=4)
        ttk.Label(
            frame,
            text="标题显示在每张入库单顶部；购买方用于识别时排除买方，不会把本公司当成销售方。\n保存后立即生效，不需要重新打包或改文件。",
            foreground="#666666",
            wraplength=430,
            justify="left",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        def on_save():
            buyer_text = buyer_var.get().strip()
            if not buyer_text:
                messagebox.showwarning(tr("提示"), tr("请填写购买方公司名称"), parent=dialog)
                return
            save_company(title_var.get(), buyer_text)
            self.append_log(f"已保存公司设置：标题={title_var.get().strip() or '入库单'}，购买方={buyer_text}")
            self.update_banner(tr("公司设置已保存：之后生成的入库单会使用新的标题和购买方"), "success")
            dialog.destroy()

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="保存", command=on_save).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(buttons, text="取消", command=dialog.destroy).grid(row=0, column=1)
        self._translate_widget_tree(dialog)
        dialog.wait_window()

    def start_process(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning(tr("提示"), tr("正在识别中"))
            return
        if not self.inputs:
            messagebox.showwarning(tr("提示"), tr("请先添加 PDF/图片或文件夹"))
            return
        self.stop_event.clear()
        self.msg_queue = queue.Queue()
        self.result = ProcessResult()
        self.invoices = []
        self.current_index = -1
        self.invoice_tree.delete(*self.invoice_tree.get_children())
        self.item_tree.delete(*self.item_tree.get_children())
        self.preview.show("")
        self.progress_var.set(0)
        self.status_var.set(tr("正在识别..."))
        self.update_banner(tr("正在识别，请稍候..."), "info")
        try:
            self.recognize_button.configure(state="disabled", text=tr("识别中..."), bg="#6A6A6A")
        except Exception:
            pass
        self.append_log(f"开始识别（{self.mode_var.get()}）: " + "；".join(self.inputs))

        def progress(msg, cur, total):
            self.msg_queue.put(("progress", msg, cur, total))

        mode_map = {
            tr("自动（推荐）"): "auto",
            tr("仅文字层（电子票）"): "text",
            tr("仅OCR（扫描件）"): "ocr",
        }
        mode = mode_map.get(self.mode_var.get(), "auto")

        def work():
            try:
                res = process_inputs(
                    self.inputs,
                    recursive=False,
                    dpi=300,
                    mode=mode,
                    progress=progress,
                    stop_flag=lambda: self.stop_event.is_set(),
                )
            except Exception as e:
                res = ProcessResult(logs=[f"识别失败: {e}"])
            self.msg_queue.put(("done", res))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()
        if not self._polling:
            self._polling = True
            self.after(100, self._poll_queue)

    def _poll_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                if msg[0] == "progress":
                    self._on_progress(msg[1], msg[2], msg[3])
                elif msg[0] == "done":
                    self._polling = False
                    self._on_process_done(msg[1])
                    return
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def stop_process(self):
        if self.worker and self.worker.is_alive():
            self.stop_event.set()
            self.status_var.set(tr("正在停止..."))
            self.update_banner(tr("正在停止，当前页处理完后停止"), "warn")
            self.append_log(tr("已请求停止，当前页处理完后停止"))

    def _on_progress(self, msg, cur, total):
        self.status_var.set(tr_runtime(msg))
        if total:
            self.progress_var.set(cur * 100.0 / total)

    def _on_process_done(self, res: ProcessResult):
        self.result = res
        self.invoices = res.invoices
        self.progress_var.set(100 if res.invoices else 0)
        self.status_var.set(
            tr_runtime(f"识别完成: {len(res.invoices)} 张发票，跳过 {len(res.skipped)} 页")
        )
        for line in res.logs:
            self.append_log(line)
        for s in res.skipped:
            reason = tr_runtime(str(s["reason"]))
            self.append_log(f"跳过 {Path(s['file']).name} 第{s['page']}页: {reason}")
        try:
            self.recognize_button.configure(state="normal", text=tr("开始识别"), bg="#2E7D32")
        except Exception:
            pass
        self.refresh_invoice_list()
        if self.invoices:
            kind = "warn" if res.skipped else "success"
            extra = f"，跳过 {len(res.skipped)} 页" if res.skipped else ""
            self.update_banner(
                tr_runtime(f"识别完成：{len(res.invoices)} 张发票{extra} — 可在左侧核对后生成 Excel"),
                kind,
            )
            self.select_invoice(0)
            if not self.output_path.get():
                self._guess_output()
        else:
            self.update_banner(
                tr_runtime(f"识别完成：没有可用发票，跳过 {len(res.skipped)} 页 — 请查看日志或手动新增"),
                "error",
            )
            self.append_log(tr("没有识别到可用发票。若是扫描件，请确认页面清晰；也可手动新增发票。"))

    def refresh_invoice_list(self):
        self.invoice_tree.delete(*self.invoice_tree.get_children())
        for i, inv in enumerate(self.invoices):
            warnings = inv.validate()
            status = tr("注意") if warnings else "OK"
            if get_language() == "en":
                source = f"{Path(inv.source_file).name} page {inv.page}"
            else:
                source = Path(inv.source_file).name + f" 第{inv.page}页"
            self.invoice_tree.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    i + 1,
                    inv.seller,
                    inv.invoice_number,
                    f"{inv.total:.2f}" if inv.total is not None else "",
                    len(inv.items),
                    status,
                    source,
                ),
                tags=("warn",) if warnings else (),
            )

    def select_invoice(self, index: int, from_event: bool = False):
        if not (0 <= index < len(self.invoices)):
            return
        self.current_index = index
        if not from_event:
            self.invoice_tree.selection_set(str(index))
            self.invoice_tree.focus(str(index))
        self.invoice_tree.see(str(index))
        inv = self.invoices[index]
        self.seller_var.set(inv.seller)
        self.number_var.set(inv.invoice_number)
        self.date_var.set(inv.invoice_date)
        self.total_var.set("" if inv.total is None else f"{inv.total:.2f}")
        self.amount_var.set("" if inv.amount_total is None else f"{inv.amount_total:.2f}")
        self.tax_var.set("" if inv.tax_total is None else f"{inv.tax_total:.2f}")
        self.alias_var.set(inv.seller_alias)
        self.inv_arrival_var.set(inv.arrival_date or inv.invoice_date)
        self.inv_stock_var.set(inv.stock_date or inv.invoice_date)
        self.preview.show(inv.image_path)
        self.refresh_items()

    def on_select_invoice(self, event=None):
        sel = self.invoice_tree.selection()
        if not sel:
            return
        try:
            self.select_invoice(int(sel[0]), from_event=True)
        except Exception:
            pass

    def refresh_items(self):
        self.item_tree.delete(*self.item_tree.get_children())
        if not (0 <= self.current_index < len(self.invoices)):
            return
        inv = self.invoices[self.current_index]
        for i, it in enumerate(inv.items):
            self.item_tree.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    it.index,
                    it.name,
                    it.spec,
                    it.unit,
                    "" if it.qty is None else f"{it.qty:g}",
                    "" if it.price is None else f"{it.price:.6g}",
                    "" if it.amount is None else f"{it.amount:.2f}",
                    "" if it.rate is None else f"{it.rate * 100:g}%",
                    "" if it.tax is None else f"{it.tax:.2f}",
                    "" if it.total is None else f"{it.total:.2f}",
                ),
            )

    def current_invoice(self) -> Optional[Invoice]:
        if 0 <= self.current_index < len(self.invoices):
            return self.invoices[self.current_index]
        return None

    def apply_invoice_edits(self):
        inv = self.current_invoice()
        if not inv:
            return
        inv.seller = self.seller_var.get().strip()
        inv.invoice_number = self.number_var.get().strip()
        inv.invoice_date = self.date_var.get().strip().replace("-", ".").replace("/", ".")
        inv.total = _float_or_none(self.total_var.get())
        inv.amount_total = _float_or_none(self.amount_var.get())
        inv.tax_total = _float_or_none(self.tax_var.get())
        inv.seller_alias = self.alias_var.get().strip() or alias_for(inv.seller)
        inv.arrival_date = self.inv_arrival_var.get().strip() or inv.invoice_date
        inv.stock_date = self.inv_stock_var.get().strip() or inv.invoice_date
        if inv.total is not None and inv.amount_total is not None and inv.tax_total is None:
            inv.tax_total = round(inv.total - inv.amount_total, 2)
        if inv.total is not None and inv.tax_total is not None and inv.amount_total is None:
            inv.amount_total = round(inv.total - inv.tax_total, 2)
        assign_sheet_names(self.invoices)
        self.refresh_invoice_list()
        self.select_invoice(self.current_index)
        self.append_log(f"已应用发票修改: {inv.seller} {inv.invoice_number}")

    def recalc_invoice(self):
        inv = self.current_invoice()
        if not inv:
            return
        inv.amount_total = inv.sum_amount()
        inv.tax_total = inv.sum_tax()
        inv.total = round(inv.amount_total + inv.tax_total, 2)
        self.amount_var.set(f"{inv.amount_total:.2f}")
        self.tax_var.set(f"{inv.tax_total:.2f}")
        self.total_var.set(f"{inv.total:.2f}")
        self.append_log("已按明细重算合计")

    def on_item_select(self, event=None):
        sel = self.item_tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
        except Exception:
            return
        inv = self.current_invoice()
        if not inv or not (0 <= idx < len(inv.items)):
            return
        it = inv.items[idx]
        self.item_name_var.set(it.name)
        self.item_spec_var.set(it.spec)
        self.item_unit_var.set(it.unit)
        self.item_qty_var.set("" if it.qty is None else f"{it.qty:g}")
        self.item_amount_var.set("" if it.amount is None else f"{it.amount:.2f}")
        self.item_rate_var.set("" if it.rate is None else f"{it.rate * 100:g}")
        self.item_tax_var.set("" if it.tax is None else f"{it.tax:.2f}")
        self.item_remark_var.set(it.remark)

    def apply_item_edits(self):
        inv = self.current_invoice()
        sel = self.item_tree.selection()
        if not inv or not sel:
            messagebox.showwarning(tr("提示"), tr("请先选择一行明细"))
            return
        try:
            idx = int(sel[0])
        except Exception:
            return
        if not (0 <= idx < len(inv.items)):
            return
        it = inv.items[idx]
        it.name = self.item_name_var.get().strip()
        it.spec = self.item_spec_var.get().strip()
        it.unit = self.item_unit_var.get().strip() or infer_unit(inv.seller, it.name, it.spec, it.unit)
        it.qty = _float_or_none(self.item_qty_var.get())
        it.amount = _float_or_none(self.item_amount_var.get())
        it.rate = _rate_or_none(self.item_rate_var.get())
        it.tax = _float_or_none(self.item_tax_var.get())
        it.unit_price = None
        it.remark = self.item_remark_var.get().strip()
        if it.tax is None and it.amount is not None and it.rate is not None:
            it.tax = round(it.amount * it.rate, 2)
        if it.rate is None and it.amount and it.tax is not None:
            r = it.tax / it.amount
            for cand in (0.13, 0.09, 0.06, 0.05, 0.03, 0.01, 0.0):
                if abs(r - cand) < 0.01:
                    it.rate = cand
                    break
        for j, other in enumerate(inv.items):
            other.index = j + 1
        inv.finalize_totals()
        self.amount_var.set(f"{inv.amount_total:.2f}" if inv.amount_total is not None else "")
        self.tax_var.set(f"{inv.tax_total:.2f}" if inv.tax_total is not None else "")
        self.total_var.set(f"{inv.total:.2f}" if inv.total is not None else "")
        self.refresh_items()
        self.item_tree.selection_set(str(idx))
        self.refresh_invoice_list()
        self.append_log(f"已应用第{idx + 1}行修改")

    def add_item(self):
        inv = self.current_invoice()
        if not inv:
            return
        inv.items.append(LineItem(index=len(inv.items) + 1))
        self.refresh_items()
        self.append_log("已添加一行明细")

    def delete_item(self):
        inv = self.current_invoice()
        sel = self.item_tree.selection()
        if not inv or not sel:
            return
        try:
            idx = int(sel[0])
        except Exception:
            return
        if 0 <= idx < len(inv.items):
            inv.items.pop(idx)
            for j, other in enumerate(inv.items):
                other.index = j + 1
            inv.finalize_totals()
            self.refresh_items()
            self.refresh_invoice_list()
            self.append_log(f"已删除第{idx + 1}行")

    def apply_dates_all(self):
        arrival = self.arrival_var.get().strip()
        stock = self.stock_var.get().strip()
        for inv in self.invoices:
            inv.arrival_date = arrival or inv.invoice_date
            inv.stock_date = stock or inv.invoice_date
        if self.current_invoice():
            self.inv_arrival_var.set(self.current_invoice().arrival_date)
            self.inv_stock_var.set(self.current_invoice().stock_date)
        if get_language() == "en":
            self.append_log(f"Dates applied: arrival={arrival or 'invoice date'}, stock={stock or 'invoice date'}")
        else:
            self.append_log(f"已应用日期: 到货={arrival or '开票日期'}, 入库={stock or '开票日期'}")

    def add_manual_invoice(self):
        inv = Invoice(source_file="", page=0, seller="", invoice_date="", total=None)
        inv.items = [LineItem(index=1)]
        inv.arrival_date = self.arrival_var.get().strip()
        inv.stock_date = self.stock_var.get().strip()
        self.invoices.append(inv)
        assign_sheet_names(self.invoices)
        self.refresh_invoice_list()
        self.select_invoice(len(self.invoices) - 1)
        self.append_log("已手动新增一张空白发票，请填写销售方、发票号、日期和明细")

    def show_help(self):
        messagebox.showinfo(tr("使用说明"), help_text())

    def learn_history(self):
        folder = filedialog.askdirectory(title=tr("选择历史入库单所在文件夹"))
        if not folder:
            return
        try:
            rows, aliases, logs = learn_from_folder(folder)
            for line in logs:
                self.append_log(line)
            self.append_log(f"学习完成: {rows} 条项目记录, {aliases} 个供应商别名")
        except Exception as e:
            messagebox.showerror(tr("学习失败"), str(e))

    def generate_excel(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning(tr("提示"), tr("正在识别，请稍候"))
            return
        if not self.invoices:
            messagebox.showwarning(tr("提示"), tr("没有可生成的发票"))
            return
        self.apply_invoice_edits()
        for inv in self.invoices:
            if not inv.arrival_date:
                inv.arrival_date = self.arrival_var.get().strip() or inv.invoice_date
            if not inv.stock_date:
                inv.stock_date = self.stock_var.get().strip() or inv.invoice_date
        assign_sheet_names(self.invoices)
        all_warnings = []
        for inv in self.invoices:
            inv.finalize_totals()
            all_warnings.extend(f"{inv.sheet_name}: {tr_runtime(w)}" for w in inv.validate())
        if all_warnings:
            if get_language() == "en":
                text = "Warnings:\n\n" + "\n".join(all_warnings[:20])
                if len(all_warnings) > 20:
                    text += f"\n... total {len(all_warnings)} item(s)"
                text += "\n\nGenerate anyway?"
            else:
                text = "发现以下警告：\n\n" + "\n".join(all_warnings[:20])
                if len(all_warnings) > 20:
                    text += f"\n... 共 {len(all_warnings)} 条"
                text += "\n\n仍然生成吗？"
            if not messagebox.askyesno(tr("核对提醒"), text):
                return
        out = self.output_path.get().strip()
        if not out:
            self._guess_output()
            out = self.output_path.get().strip()
        if not out:
            messagebox.showwarning(tr("提示"), tr("请先设置输出路径"))
            return
        if not out.lower().endswith(".xls"):
            out += ".xls"
            self.output_path.set(out)
        try:
            info = write_workbook(self.invoices, out)
        except Exception as e:
            messagebox.showerror(tr("生成失败"), str(e))
            return
        self.update_banner(f"已生成：{out}", "success")
        issues = verify_workbook(out, self.invoices)
        if issues:
            self.append_log(tr("自检发现问题:"))
            for issue in issues:
                self.append_log("  - " + issue)
        else:
            self.append_log(tr("自检: 金额/税金/价税合计核对通过"))
        if get_language() == "en":
            ask = f"Generated {info['sheets']} sheet(s):\n{out}\n\nExport PDF for layout check?"
        else:
            ask = f"已生成 {info['sheets']} 张工作表：\n{out}\n\n是否导出 PDF 做版式检查？"
        if messagebox.askyesno(tr("生成完成"), ask):
            pdf = str(Path(out).with_name(Path(out).stem + "-打印.pdf"))
            ok, msg = export_pdf_and_check(out, pdf)
            self.append_log((tr("PDF 检查: ") if ok else tr("PDF 检查失败: ")) + msg)
            if ok:
                open_pdf = "Open the PDF?" if get_language() == "en" else "是否打开 PDF？"
                if messagebox.askyesno(tr("PDF 检查通过"), msg + "\n\n" + open_pdf):
                    try:
                        os.startfile(pdf)
                    except Exception:
                        pass
        if messagebox.askyesno(tr("完成"), tr("是否打开生成的 Excel？")):
            try:
                os.startfile(out)
            except Exception:
                pass

    def open_output(self):
        path = self.output_path.get().strip()
        if path and os.path.exists(path):
            try:
                os.startfile(path)
            except Exception as e:
                messagebox.showerror(tr("打开失败"), str(e))
        else:
            messagebox.showinfo(tr("提示"), tr("输出文件还不存在"))

    def on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(tr("退出"), tr("正在识别，确定退出吗？")):
                return
            self.stop_event.set()
        self.destroy()


def launch(initial_inputs=None):
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = App(initial_inputs=initial_inputs)
    app.mainloop()
