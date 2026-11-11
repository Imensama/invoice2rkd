<h2 align="center">⚠️ Scan at 600 DPI! Low resolution causes errors</h2>
<h3 align="center">⚠️ 扫描请用 600dpi！低分辨率会出错</h3>

**Electronic invoices with a PDF text layer are not affected. 电子发票有文字层，不受影响。**

[中文](README.zh-CN.md) | English

# Invoice → Receipt Generator (Invoice2RKD) / 中国发票 → 入库单

**Chinese invoice PDF/image → printable Excel receipt (入库单). 电子发票文字层 + 扫描件 OCR，本地离线。**

**Scope: invoices issued within the territory of the People's Republic of China** — VAT special invoices (增值税专用发票), VAT ordinary invoices (增值税普通发票), electronic invoices (电子发票), fully digitalized electronic invoices / digitalized e-invoices (全面数字化电子发票 / 数电发票), and scanned copies. It does not process English/foreign invoices.

If you have to copy item names, specs, quantities, unit prices and tax into a fixed receipt template every month, this tool removes most of the manual work. It generates `.xls` receipts with print settings prepared for the Epson LQ-730K 3-ply paper.

> **Strong recommendation: scan at 600 dpi.** Low-resolution scans (150/200 dpi) significantly increase OCR errors in table lines, small text, numbers and discount lines. Electronic invoices with a PDF text layer are not affected.

![screenshot](docs/screenshot.png)

> Windows 10/11 · fully offline · MIT License  
> Current v1.3: Chinese/English UI, PDF text layer + OCR for scans, discount-line merging, company settings.

---

## What it does

1. **Read** seller, invoice number, date, line items, amount and tax from invoice PDFs/images.
2. **Review** fields and line items in the UI; fix names, units, quantities or add missing lines.
3. **Export** one `.xls` worksheet per invoice, ready to print or archive.

Built for procurement, finance, warehouse and admin staff who process invoices in batches. It is not a fully unattended system, but it automates the slow copy-and-format work.

---

## Features

- PDF, PNG, JPG, BMP, TIFF, WEBP; add files or drag files/folders into the window.
- **Electronic invoices**: parse the PDF text layer first (fast and accurate).
- **Scans/images**: local RapidOCR; mixed PDFs are decided page by page.
- If the text layer is insufficient or fails validation, fall back to OCR automatically.
- QR code is used to verify invoice number, date and total.
- Discount lines (negative amounts) are merged into the previous positive line; no negative amount or negative unit price in the output.
- Seller is taken from the right-side “Seller” block; a buyer named “个人” (individual) is never treated as the seller.
- Non-invoice pages (e.g. expense claim forms) are skipped; duplicate invoices are de-duplicated.
- **Company Settings** in the app: receipt title and buyer company name. Takes effect immediately.
- **Chinese/English UI switch**; Excel and printed receipts remain in Chinese.
- Review and edit invoice fields and line items before exporting.
- One worksheet per invoice; sheet name = seller alias + total (with `-MMDD` if duplicated).
- Print layout: 286 paper (9.5×5.5 in), portrait, fit 1×1, margins 0.2/0.4 in, empty header/footer.
- “Learn History” imports previous receipts to improve item/unit/spec matching; stored locally only.

---

## Quick start (portable)

1. Download `入库单生成器-便携版.zip` from **Releases**.
2. Extract it and run `入库单生成器\入库单生成器.exe` (keep the `_internal` folder next to the exe).
3. Click **Company Settings** (top right), fill in the receipt title and buyer company name, save.
4. Drag invoice PDFs/images into the left list, or click **Add PDF/Images**.
5. Leave the mode at **Auto (recommended)**: electronic invoices use the text layer; scans use OCR.
6. Click **Start**.
7. Select an invoice on the left and review it under **Details & Fields**.
8. Set year/month and output path, then click **Generate Excel**.

No Python is required. Excel is only needed for the optional “export PDF to check layout” step.

---

## English UI

Use the **Language** dropdown on the right side of the progress bar:

- Chinese Windows defaults to Chinese.
- Other system languages default to English.
- You can switch manually at any time; it takes effect immediately.

The English UI covers the main window, invoice fields, line items, company settings, file dialogs, logs/warnings and common errors. Invoice data (seller/item names) remains as printed on the Chinese invoice.

**Excel and printed receipts stay in Chinese.** According to Article 22 of the Accounting Law of the People's Republic of China, accounting records must be in Chinese; foreign-invested enterprises and foreign organizations may use a foreign language *in addition to* Chinese. An English-only receipt is not compliant.

---

## Company settings

Click **Company Settings** in the app:

- **Receipt title**: printed at the top of each receipt, e.g. `XX Company Receipt`.
- **Buyer company name**: used to exclude your own company from seller detection.

Settings are saved locally in:

```
%LOCALAPPDATA%\Invoice2RKD\company_public.json
```

No need to edit `data/company.json` or rebuild the app.

---

## Output

- One worksheet per invoice.
- Sheet name = seller alias + total; duplicates get `-MMDD`.
- Columns: No. / Item / Spec / Unit / Qty / Unit Price / Unit Price incl. tax (hidden) / Amount / Tax / Total / Arrival Date / Stock Date / Remark.
- Total row: amount + tax = total = invoice total.
- Print: 286 paper, portrait, 1×1, 0.2/0.4 in margins.
- Example: [examples/示例-入库单.xls](examples/示例-入库单.xls) (fictional data only).

---

## Why use the text layer?

- Electronic PDFs already contain exact text for number, names and amounts.
- Rendering them to images and running OCR is a lossy round trip: column merging, missed vertical labels, decimal/negative errors.
- Scans have no text layer, so OCR is the only option.

v1.3 therefore uses both paths:

```
Electronic page → PDF text layer (pdfplumber)
Scanned page    → OCR (RapidOCR)
Text layer failed/invalid → OCR fallback
Both available → cross-check, text layer wins
Mixed PDF → decided per page
```

When the text layer passes validation, OCR is skipped for speed. QR data is always used as an independent check.

---

## Build from source

Windows 10/11, Python 3.10+ (3.12 recommended):

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Build the portable package:

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

Output: `dist\入库单生成器\`. Zip the folder for distribution.

---

## Privacy

- Everything runs locally; no cloud API, no API key.
- OCR cache, previews, language setting, company setting and learning data live in `%LOCALAPPDATA%\Invoice2RKD\`.
- **Do not commit real invoices, generated `.xls`, `data/catalog.json`, `示例输出/` or `dist/` to GitHub.**
- `examples/示例-入库单.xls` contains fictional data only.

---

## Known limitations

- OCR is not 100%; stamps, folds, low resolution and unusual layouts may need manual review.
- One invoice per page by default; multiple invoices on one page are skipped with a prompt to split.
- Non-invoice pages are skipped.
- Only Chinese invoices are supported. English/foreign invoices are not.
- Results are for data entry only, not financial/tax advice; please verify amounts.

---

## Keywords / 关键词

Chinese invoice, China invoice OCR, VAT invoice, VAT special invoice, VAT ordinary invoice, e-invoice, fully digitalized electronic invoice, digitalized e-invoice, fapiao, shudian fapiao, invoice to Excel, invoice recognition, receipt generator, inventory receipt, offline OCR, Windows, Python, Tkinter.

发票识别, 发票 OCR, 电子发票, 增值税发票, 增值税专用发票, 增值税普通发票, 全面数字化电子发票, 数电发票, 中国发票, 发票转 Excel, 发票录入, 入库单, 采购入库, 报销, 发票批量识别, 离线 OCR, 本地识别, fapiao, shudian fapiao, rukudan.

## Dependencies and licenses

Project code: MIT License, see [LICENSE](LICENSE).

| Component | Purpose | License |
| --- | --- | --- |
| pypdfium2 / PDFium | PDF rendering | Apache-2.0 / BSD-3-Clause |
| pdfplumber / pdfminer.six | PDF text layer | MIT |
| charset_normalizer / cryptography | pdfminer runtime dependencies | MIT / Apache-2.0 OR BSD-3-Clause |
| RapidOCR + PP-OCR models | local OCR | Apache-2.0 |
| ONNX Runtime | OCR inference | MIT |
| zxing-cpp | QR codes | Apache-2.0 |
| OpenCV / NumPy / Pillow | images | Apache-2.0 / BSD / HPND |
| xlwt / xlrd | `.xls` read/write | BSD-3-Clause |
| tkinterdnd2 | drag and drop | MIT |
| PyInstaller | packaging | GPL-2.0 with exception |

---

## Documentation

- [中文 README](README.zh-CN.md)
- [使用说明](docs/使用说明.md) (Chinese)
- [开发说明](docs/开发说明.md) (Chinese)
- [GitHub 上传教程](docs/GitHub上传教程.md) (Chinese, beginner-friendly)
- [更新记录](CHANGELOG.md)

---

## Contributing

Issues and PRs are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) first; remove real invoices and company data before committing.
