from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

import cv2
import numpy as np
import pypdfium2 as pdfium
import zxingcpp
from PIL import Image, ImageOps

_PDFPLUMBER_ERROR = ""
try:
    import pdfplumber
except Exception as _pdfplumber_exc:  # pragma: no cover - 文字层为可选增强
    pdfplumber = None
    _PDFPLUMBER_ERROR = str(_pdfplumber_exc)

from rapidocr_onnxruntime import RapidOCR

Image.MAX_IMAGE_PIXELS = None

APP_NAME = "Invoice2RKD"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
PDF_EXTS = {".pdf"}

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

USER_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME
USER_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR = USER_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
PREVIEW_DIR = CACHE_DIR / "previews"
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)


def _read_json_file(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


BUNDLED_COMPANY = _read_json_file(DATA_DIR / "company.json")
COMPANY_PROFILE = re.sub(r"[^0-9A-Za-z_-]+", "_", str(BUNDLED_COMPANY.get("profile") or "")).strip("_")
COMPANY_FILE = USER_DIR / (f"company_{COMPANY_PROFILE}.json" if COMPANY_PROFILE else "company.json")
COMPANY = dict(BUNDLED_COMPANY)
COMPANY.update(_read_json_file(COMPANY_FILE))
BUYER_NAME = str(COMPANY.get("buyer") or "购买方公司名称")


def get_company() -> dict:
    return dict(COMPANY)


def save_company(title: str, buyer: str):
    """保存到用户目录，不修改安装包里的 data/company.json。"""
    global COMPANY, BUYER_NAME
    data = {
        "title": (title or "").strip() or "入库单",
        "buyer": (buyer or "").strip(),
    }
    if COMPANY_PROFILE:
        data["profile"] = COMPANY_PROFILE
    save_json(COMPANY_FILE, data)
    COMPANY = dict(COMPANY)
    COMPANY.update(data)
    BUYER_NAME = data["buyer"] or "购买方公司名称"


def company_needs_setup() -> bool:
    buyer = str(COMPANY.get("buyer") or "").strip()
    return not buyer or buyer == "购买方公司名称"

VALID_UNITS = set(
    "吨 公斤 千克 克 kg 件 个 套 根 项 米 m m² 平方米 支 把 付 张 卷 台 天 工 次 块 片 盒 包 桶 升 组 批 车 本 份 只 双 对 条 圈 袋 瓶 罐 捆 盘 箱 令 立方米 台班 人天".split()
)

UNIT_COMPLETE = {
    "不锈钢90°弯": "不锈钢90°弯头",
    "硬质合金钢板": "硬质合金钢板钻",
}


def load_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


class Catalog:
    def __init__(self, rows: Iterable[dict]):
        self.rows = list(rows)
        self._build()

    def _build(self):
        self.by_seller_name_spec = defaultdict(Counter)
        self.by_seller_name = defaultdict(Counter)
        self.by_name_spec = defaultdict(Counter)
        self.by_name = defaultdict(Counter)
        self.specs_by_seller_name = defaultdict(Counter)
        self.names = set()
        self.sellers = set()
        for r in self.rows:
            seller = str(r.get("seller", "")).strip()
            name = str(r.get("name", "")).strip()
            spec = str(r.get("spec", "")).strip()
            unit = str(r.get("unit", "")).strip()
            if not name:
                continue
            self.names.add(name)
            if seller:
                self.sellers.add(seller)
            if unit:
                self.by_seller_name_spec[(seller, name, spec)][unit] += 1
                self.by_seller_name[(seller, name)][unit] += 1
                self.by_name_spec[(name, spec)][unit] += 1
                self.by_name[name][unit] += 1
            if spec:
                self.specs_by_seller_name[(seller, name)][spec] += 1

    def add_rows(self, rows: Iterable[dict]):
        self.rows.extend(rows)
        self._build()

    def unit_for(self, seller: str, name: str, spec: str, fallback: str = "") -> str:
        for key in (
            (seller, name, spec),
            (seller, name),
            (name, spec),
            (name,),
        ):
            counter = None
            if len(key) == 3:
                counter = self.by_seller_name_spec.get(key)
            elif len(key) == 2:
                counter = self.by_seller_name.get(key) or self.by_name_spec.get(key)
            else:
                counter = self.by_name.get(key)
            if counter:
                unit = counter.most_common(1)[0][0]
                if unit:
                    return unit
        return fallback

    def spec_for(self, seller: str, name: str, spec: str) -> str:
        if not name:
            return spec
        candidates = self.specs_by_seller_name.get((seller, name))
        if not candidates:
            candidates = self.specs_by_seller_name.get(("", name))
        if not candidates:
            candidates = Counter()
            for (s, n), c in self.specs_by_seller_name.items():
                if n == name:
                    candidates.update(c)
        if not candidates:
            return spec
        if not spec:
            return candidates.most_common(1)[0][0]
        normalized = _normalize_spec_compare(spec)
        matches = [
            s
            for s in candidates
            if _normalize_spec_compare(s) == normalized
            or _normalize_spec_compare(s).startswith(normalized)
        ]
        if matches:
            return Counter(matches).most_common(1)[0][0]
        return spec

    def complete_name(self, name: str) -> str:
        if not name:
            return name
        if name in UNIT_COMPLETE:
            return UNIT_COMPLETE[name]
        best = None
        for cand in self.names:
            if not cand:
                continue
            if cand.startswith(name) or name.startswith(cand):
                if abs(len(cand) - len(name)) > 2:
                    continue
                r = _ratio(name, cand)
                if r >= 0.8 and (best is None or r > best[0]):
                    best = (r, cand)
        return best[1] if best else name


def _ratio(a: str, b: str) -> float:
    import difflib

    return difflib.SequenceMatcher(None, a, b).ratio()


def _normalize_spec_compare(s: str) -> str:
    s = re.sub(r"\s+", "", s or "")
    s = s.replace("(", "（").replace(")", "）")
    s = s.replace(",", "，").replace("。", ".")
    return s


class ResourceStore:
    def __init__(self):
        self.bundled_catalog = Catalog(load_json(DATA_DIR / "catalog.json", []))
        self.user_catalog_path = USER_DIR / "catalog_user.json"
        self.user_rows = load_json(self.user_catalog_path, [])
        self.catalog = Catalog(self.bundled_catalog.rows + self.user_rows)
        self.completions = dict(UNIT_COMPLETE)
        self.completions.update(load_json(DATA_DIR / "completions.json", {}))
        self.completions.update(load_json(USER_DIR / "completions.json", {}))
        self.alias_overrides = load_json(USER_DIR / "aliases.json", {})

    def reload(self):
        self.__init__()

    def add_user_rows(self, rows: list[dict]):
        if not rows:
            return
        seen = {
            (
                str(r.get("seller", "")),
                str(r.get("name", "")),
                str(r.get("spec", "")),
                str(r.get("unit", "")),
            )
            for r in self.user_rows
        }
        added = []
        for r in rows:
            key = (
                str(r.get("seller", "")),
                str(r.get("name", "")),
                str(r.get("spec", "")),
                str(r.get("unit", "")),
            )
            if key not in seen:
                seen.add(key)
                added.append(r)
        if added:
            self.user_rows.extend(added)
            save_json(self.user_catalog_path, self.user_rows)
            self.catalog = Catalog(self.bundled_catalog.rows + self.user_rows)

    def save_alias(self, seller: str, alias: str):
        self.alias_overrides[seller] = alias
        save_json(USER_DIR / "aliases.json", self.alias_overrides)


RESOURCES = ResourceStore()
_OCR_ENGINE: Optional[RapidOCR] = None


def get_ocr() -> RapidOCR:
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def collect_input_files(paths: Iterable[str], recursive: bool = False) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            it = p.rglob("*") if recursive else p.glob("*")
            for f in it:
                if f.is_file() and f.suffix.lower() in (IMAGE_EXTS | PDF_EXTS):
                    files.append(f)
        elif p.is_file():
            if p.suffix.lower() in (IMAGE_EXTS | PDF_EXTS):
                files.append(p)
    unique = []
    seen = set()
    for f in sorted(files, key=lambda x: natural_key(str(x))):
        key = str(f.resolve()).lower()
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def image_to_bgr(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
    return img


def load_image(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        pil = Image.open(path)
        pil = ImageOps.exif_transpose(pil).convert("RGB")
        img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    else:
        img = image_to_bgr(img)
    return img


def render_pdf_page(doc: pdfium.PdfDocument, page_index: int, dpi: int) -> np.ndarray:
    page = doc[page_index]
    bitmap = None
    try:
        bitmap = page.render(scale=dpi / 72.0)
        pil = bitmap.to_pil()
        return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    finally:
        try:
            if bitmap is not None:
                bitmap.close()
        except Exception:
            pass
        try:
            page.close()
        except Exception:
            pass


def rotate_image(img: np.ndarray, rotation: int) -> np.ndarray:
    rot = (rotation // 90) % 4
    if rot == 0:
        return img
    return np.rot90(img, rot).copy()


def boxes_from_result(result) -> list[dict]:
    boxes = []
    for box, text, score in result or []:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x0, x1 = float(min(xs)), float(max(xs))
        y0, y1 = float(min(ys)), float(max(ys))
        boxes.append(
            {
                "x0": x0,
                "x1": x1,
                "y0": y0,
                "y1": y1,
                "cx": (x0 + x1) / 2,
                "cy": (y0 + y1) / 2,
                "w": x1 - x0,
                "h": y1 - y0,
                "t": text,
                "s": float(score),
            }
        )
    return boxes


def ocr_image(img: np.ndarray) -> list[dict]:
    result, _ = get_ocr()(img)
    return boxes_from_result(result)


def norm_text(t: str) -> str:
    return re.sub(r"\s+", "", t or "")


def find_title_box(boxes: list[dict]) -> Optional[dict]:
    candidates = []
    for b in boxes:
        t = norm_text(b["t"])
        if "电子发票" in t or ("增值税" in t and "发票" in t):
            if b["w"] > b["h"] * 1.5:
                candidates.append(b)
    if not candidates:
        for seg in _line_segments(boxes, gap_threshold=600.0):
            text = norm_text("".join(b["t"] for b in seg))
            if len(text) > 40:
                continue
            has_title = (
                "电子发票" in text
                or ("电子发" in text and "发票" in text)
                or ("增值税" in text and "发票" in text)
            )
            if has_title:
                x0 = min(b["x0"] for b in seg)
                x1 = max(b["x1"] for b in seg)
                y0 = min(b["y0"] for b in seg)
                y1 = max(b["y1"] for b in seg)
                w, h = x1 - x0, y1 - y0
                if w > h * 1.5:
                    candidates.append(
                        {
                            "x0": x0,
                            "x1": x1,
                            "y0": y0,
                            "y1": y1,
                            "cx": (x0 + x1) / 2,
                            "cy": (y0 + y1) / 2,
                            "w": w,
                            "h": h,
                            "t": text,
                            "s": max(b["s"] for b in seg),
                        }
                    )
    return max(candidates, key=lambda b: b["s"] * b["w"]) if candidates else None


def find_footer_box(boxes: list[dict]) -> Optional[dict]:
    candidates = [b for b in boxes if "开票人" in norm_text(b["t"])]
    return max(candidates, key=lambda b: b["s"]) if candidates else None


def detect_orientation(preview: np.ndarray, progress: Optional[Callable] = None) -> int:
    h, w = preview.shape[:2]
    candidates = []
    for rot in (0, 90):
        im = rotate_image(preview, rot)
        hh, ww = im.shape[:2]
        boxes = ocr_image(im)
        title = find_title_box(boxes)
        footer = find_footer_box(boxes)
        text = " ".join(b["t"] for b in boxes)
        kwargs = 0
        for kw in ("发票", "名称", "金额", "税额", "价税合计", "购买方", "销售方", "项目名称", "开票日期", "发票号码"):
            kwargs += text.count(kw)
        mean_conf = sum(b["s"] for b in boxes) / max(1, len(boxes))
        score = kwargs * 2.0 + len(boxes) * 0.05 + mean_conf
        flip = 0
        if title:
            score += 100
            if title["cy"] < hh * 0.45:
                score += 50
            elif title["cy"] > hh * 0.55:
                score += 15
                flip = 1
            if footer:
                if title["cy"] < hh * 0.45 and footer["cy"] > hh * 0.55:
                    score += 50
                elif title["cy"] > hh * 0.55 and footer["cy"] < hh * 0.45:
                    score += 30
                    flip = 1
        candidates.append((score, rot, flip))
    _, rot, flip = max(candidates, key=lambda x: x[0])
    return (rot + (180 if flip else 0)) % 360


def decode_qr(img: np.ndarray) -> list[str]:
    found = []
    for rot in range(4):
        im = img if rot == 0 else np.rot90(img, rot).copy()
        try:
            for code in zxingcpp.read_barcodes(im):
                if code.text and code.text not in found:
                    found.append(code.text)
        except Exception:
            pass
    return found


def parse_qr_payload(payload: str) -> dict:
    info = {}
    if not payload:
        return info
    parts = payload.split(",")
    if len(parts) >= 6:
        number = parts[3].strip()
        amount = parts[4].strip()
        date = parts[5].strip()
        if number:
            info["number"] = number
        if re.fullmatch(r"\d+(?:\.\d+)?", amount):
            try:
                info["total"] = float(amount)
            except ValueError:
                pass
        if re.fullmatch(r"\d{8}", date):
            info["date"] = f"{date[:4]}.{date[4:6]}.{date[6:]}"
    return info


def ocr_invoice_number(boxes: list[dict]) -> str:
    for b in boxes:
        m = re.search(r"发票号码[:：]?\s*(\d{8,24})", norm_text(b["t"]))
        if m:
            return m.group(1)
    for b in boxes:
        m = re.search(r"\d{20}", norm_text(b["t"]))
        if m:
            return m.group(0)
    return ""


def ocr_invoice_date(boxes: list[dict]) -> str:
    for b in boxes:
        t = norm_text(b["t"])
        m = re.search(r"开票日期[:：]?\s*(\d{4})[年./-](\d{1,2})[月./-](\d{1,2})", t)
        if not m:
            m = re.search(r"(\d{4})[年./-](\d{1,2})[月./-](\d{1,2})", t)
        if m:
            return f"{int(m.group(1)):04d}.{int(m.group(2)):02d}.{int(m.group(3)):02d}"
    return ""


def ocr_total(boxes: list[dict]) -> Optional[float]:
    for b in boxes:
        t = norm_text(b["t"])
        if "小写" in t or "价税合计" in t:
            nums = re.findall(r"\d+(?:\.\d+)?", t.replace(",", ""))
            if nums:
                try:
                    return float(nums[-1])
                except ValueError:
                    pass
    for b in boxes:
        t = norm_text(b["t"])
        if ("¥" in t or "￥" in t) and re.search(r"\d+\.\d{2}", t):
            try:
                return float(re.findall(r"\d+(?:\.\d+)?", t.replace(",", ""))[-1])
            except ValueError:
                pass
    return None


def _box_lines(boxes: list[dict]) -> list[list[dict]]:
    """把 box 按 y 聚类成视觉行；同一行的左右字段稍后再按间距切段。"""
    ordered = sorted(boxes, key=lambda b: (b["cy"], b["x0"]))
    lines: list[dict] = []
    for b in ordered:
        placed = False
        for line in reversed(lines[-10:]):
            overlap = min(line["y1"], b["y1"]) - max(line["y0"], b["y0"])
            min_h = min(line["height"], max(b["h"], 1.0))
            max_h = max(line["height"], max(b["h"], 1.0))
            if max_h > max(24.0, 2.5 * min_h):
                continue
            same_cy = abs(line["cy"] - b["cy"]) <= max(3.0, 0.35 * min_h)
            if overlap > 0.35 * max(min_h, 1.0) or same_cy:
                line["boxes"].append(b)
                line["y0"] = min(line["y0"], b["y0"])
                line["y1"] = max(line["y1"], b["y1"])
                line["cy"] = (line["y0"] + line["y1"]) / 2
                line["height"] = line["y1"] - line["y0"]
                placed = True
                break
        if not placed:
            lines.append({"boxes": [b], "y0": b["y0"], "y1": b["y1"], "cy": b["cy"], "height": b["h"]})
    return [line["boxes"] for line in lines]


def _line_segments(boxes: list[dict], gap_threshold: float = 30.0) -> list[list[dict]]:
    segments: list[list[dict]] = []
    for line in _box_lines(boxes):
        line = sorted(line, key=lambda b: b["x0"])
        current = [line[0]]
        for b in line[1:]:
            gap = b["x0"] - current[-1]["x1"]
            if gap > gap_threshold:
                segments.append(current)
                current = [b]
            else:
                current.append(b)
        segments.append(current)
    return segments


def _clean_name_value(value: str) -> str:
    value = re.sub(r"\s+", "", value or "")
    value = re.split(r"统一社会信用代码|纳税人识别号", value)[0]
    value = re.sub(r"^(名称|名\s*称)\s*[:：]?", "", value)
    value = value.strip(" :：,，;；")
    return value


def _seller_candidates(boxes: list[dict]) -> list[tuple[str, float]]:
    candidates: list[tuple[str, float]] = []
    for seg in _line_segments(boxes):
        text = "".join(b["t"] for b in seg)
        m = re.search(r"名\s*称\s*[:：]?\s*(.+)", text)
        if not m:
            continue
        value = _clean_name_value(m.group(1))
        if not value:
            continue
        candidates.append((value, seg[0]["x0"]))
    return candidates


def _is_personal(value: str) -> bool:
    return value.strip(" :：") in ("个人", "自然人", "个人姓名")


def _is_buyer(value: str) -> bool:
    value = re.sub(r"\s+", "", value or "")
    if not value:
        return False
    buyer = re.sub(r"\s+", "", BUYER_NAME or "")
    if buyer and (value == buyer or value in buyer or buyer in value):
        return True
    buyer_core = re.sub(r"(有限公司|有限责任公司|股份有限公司|个体工商户)$", "", buyer)
    return bool(buyer_core and buyer_core in value)


def seller_from_boxes(boxes: list[dict], width: Optional[float] = None) -> str:
    """取销售方全称。新版电子发票固定为左侧购买方、右侧销售方。

    购买方可能是“个人”（没有税号）；任何情况下都不能把“个人”或购买方公司当成卖方。
    """
    candidates = _seller_candidates(boxes)
    if not candidates:
        return ""
    xs = [b["cx"] for b in boxes]
    mid = float(width) / 2 if width else ((min(xs) + max(xs)) / 2 if xs else 0.0)

    def valid(value: str) -> bool:
        return bool(value) and not _is_personal(value) and not _is_buyer(value)

    right = [(v, x) for v, x in candidates if x >= mid - 8]
    left = [(v, x) for v, x in candidates if x < mid - 8]
    pool = [p for p in right if valid(p[0])]
    if not pool:
        pool = [p for p in left if valid(p[0])]
    if not pool:
        return ""
    preferred = [p for p in pool if re.search(r"(公司|商行|商店|门市|经营部|中心|工厂|厂|店|社|部|院|校)$", p[0])]
    seller = max(preferred or pool, key=len)[0]
    known = RESOURCES.catalog.sellers
    if seller in known:
        return seller
    best = None
    for cand in known:
        r = _ratio(seller, cand)
        if r >= 0.88 and (best is None or r > best[0]):
            best = (r, cand)
    return best[1] if best else seller


def invoice_total_from_boxes(boxes: list[dict]) -> Optional[float]:
    """从“价税合计（小写）”行取价税合计，避免把中间金额当合计。"""
    small_labels = [b for b in boxes if "小写" in norm_text(b["t"])]
    for label in small_labels:
        same_line = [
            b
            for b in boxes
            if abs(b["cy"] - label["cy"]) <= max(12, label["h"] * 0.8)
            and b["x0"] >= label["x1"] - 12
            and re.search(r"\d+\.\d{2}", b["t"])
        ]
        if same_line:
            value = parse_num(max(same_line, key=lambda b: b["x0"])["t"])
            if value is not None:
                return value
    for b in boxes:
        if "价税合计" in norm_text(b["t"]):
            same_line = [
                t
                for t in boxes
                if abs(t["cy"] - b["cy"]) <= max(18, b["h"])
                and re.search(r"[¥￥]", t["t"])
                and re.search(r"\d+\.\d{2}", t["t"])
            ]
            if same_line:
                value = parse_num(max(same_line, key=lambda b: b["x1"])["t"])
                if value is not None:
                    return value
    return ocr_total(boxes)


def amount_to_text(amount: float) -> str:
    if abs(amount - round(amount)) < 0.005:
        return str(int(round(amount)))
    return f"{amount:.2f}"


def strip_company_suffix(name: str) -> str:
    name = (name or "").strip()
    for suffix in (
        "股份有限公司",
        "有限责任公司",
        "有限公司",
        "（个体工商户）",
        "(个体工商户)",
        "（个人独资）",
        "(个人独资)",
        "个体工商户",
        "个人独资",
    ):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
            break
    return name


def alias_for(seller: str) -> str:
    override = RESOURCES.alias_overrides.get(seller)
    if override:
        return override
    return strip_company_suffix(seller)


def safe_sheet_name(base: str, used: set[str], date_suffix: str = "") -> str:
    bad = set(':\\/?*[]')
    base = "".join(ch for ch in base if ch not in bad).strip() or "Sheet"
    if len(base) > 31:
        base = base[:31]
    candidate = base
    if candidate in used and date_suffix:
        suffix = "-" + date_suffix
        candidate = base[: 31 - len(suffix)] + suffix
    n = 2
    while candidate in used:
        suffix = f"-{n}"
        candidate = base[: 31 - len(suffix)] + suffix
        n += 1
    used.add(candidate)
    return candidate


def clean_num(s: str) -> str:
    s = re.sub(r"(?<=\d)\.\s+(?=\d+\.\d+)", " ", s or "")
    s = s.replace(" ", "").replace(",", "")
    s = s.replace("￥", "").replace("¥", "").replace("Y", "").replace("O", "0").replace("o", "0")
    s = s.replace("·", ".").replace("。", ".")
    return s


def parse_num(s: str) -> Optional[float]:
    s = clean_num(s)
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def nums_in(s: str) -> list[float]:
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", clean_num(s))]


def find_header(boxes: list[dict], needle: str, rate: bool = False) -> Optional[dict]:
    candidates = []
    for b in boxes:
        t = norm_text(b["t"])
        if (("税率" in t) if rate else (needle in t)):
            candidates.append(b)
    return max(candidates, key=lambda b: (b["s"], -b["y0"])) if candidates else None


def _synth_header(cx: float, cy: float) -> dict:
    return {"x0": cx - 50, "x1": cx + 50, "y0": cy - 15, "y1": cy + 15, "cx": cx, "cy": cy, "w": 100, "h": 30, "t": "", "s": 1.0}


def _numeric_clusters(boxes: list[dict], header_bottom: float, table_y: float) -> list[float]:
    values = []
    for b in boxes:
        if b["cy"] <= header_bottom + 5 or b["cy"] >= table_y:
            continue
        t = b["t"].strip()
        if len(t) > 24 or not re.search(r"\d", t):
            continue
        if "：" in t or ":" in t:
            continue
        values.append(b["cx"])
    if not values:
        return []
    values.sort()
    clusters = [[values[0]]]
    for x in values[1:]:
        if x - clusters[-1][-1] <= 90:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return [sum(c) / len(c) for c in clusters]


def _rightmost_numeric_cluster(boxes: list[dict], header_bottom: float) -> Optional[float]:
    candidates = []
    for b in boxes:
        if b["cy"] <= header_bottom + 5:
            continue
        t = b["t"].strip()
        if len(t) > 40 or not re.search(r"\d", t):
            continue
        if "：" in t or ":" in t:
            continue
        candidates.append(b["cx"])
    if not candidates:
        return None
    candidates.sort()
    clusters = [[candidates[0]]]
    for x in candidates[1:]:
        if x - clusters[-1][-1] <= 160:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return sum(clusters[-1]) / len(clusters[-1])


def get_headers(boxes: list[dict]) -> dict:
    keys = [
        ("name", "项目名称", False),
        ("spec", "规格型号", False),
        ("unit", "单位", False),
        ("qty", "数量", False),
        ("price", "单价", False),
        ("amount", "金额", False),
        ("rate", "税率", True),
        ("tax", "税额", False),
    ]
    found = {k: find_header(boxes, n, r) for k, n, r in keys}
    order = [k for k, _, _ in keys]
    present = [k for k in order if found.get(k)]
    if len(present) < 3:
        return found
    header_cy = sum(found[k]["cy"] for k in present) / len(present)
    header_bottom = max(found[k]["y1"] for k in present)
    table_y = min([b["y0"] for b in boxes if "价税合计" in norm_text(b["t"])], default=10**9)
    clusters = _numeric_clusters(boxes, header_bottom, table_y)
    used_clusters = set()
    if not found.get("tax") and clusters:
        anchor = found.get("rate") or found.get("amount")
        for cx in reversed(clusters):
            if cx in used_clusters:
                continue
            if anchor is not None and cx <= anchor["cx"] + 60:
                continue
            found["tax"] = _synth_header(cx, header_cy)
            used_clusters.add(cx)
            break
    if not found.get("rate") and clusters:
        left_anchor = found.get("amount") or found.get("price")
        right_anchor = found.get("tax")
        for cx in reversed(clusters):
            if cx in used_clusters:
                continue
            if left_anchor is not None and cx <= left_anchor["cx"] + 30:
                continue
            if right_anchor is not None and cx >= right_anchor["cx"] - 30:
                continue
            found["rate"] = _synth_header(cx, header_cy)
            used_clusters.add(cx)
            break
    if not found.get("amount") and clusters:
        left_anchor = found.get("price") or found.get("qty")
        right_anchor = found.get("rate") or found.get("tax")
        for cx in reversed(clusters):
            if cx in used_clusters:
                continue
            if left_anchor is not None and cx <= left_anchor["cx"] + 30:
                continue
            if right_anchor is not None and cx >= right_anchor["cx"] - 30:
                continue
            found["amount"] = _synth_header(cx, header_cy)
            used_clusters.add(cx)
            break
    if not found.get("qty") and found.get("price") and found.get("amount"):
        qcx = found["price"]["cx"] - (found["amount"]["cx"] - found["price"]["cx"])
        if qcx > 0:
            found["qty"] = _synth_header(qcx, header_cy)
    if not found.get("unit") and found.get("spec") and found.get("qty"):
        ucx = (found["spec"]["cx"] + found["qty"]["cx"]) / 2
        found["unit"] = _synth_header(ucx, header_cy)
    for idx, key in enumerate(order):
        if found.get(key):
            continue
        left = None
        right = None
        for j in range(idx - 1, -1, -1):
            if found.get(order[j]):
                left = order[j]
                break
        for j in range(idx + 1, len(order)):
            if found.get(order[j]):
                right = order[j]
                break
        cx = None
        if left and right:
            cx = (found[left]["cx"] + found[right]["cx"]) / 2
        elif left:
            prev = None
            li = order.index(left)
            for j in range(li - 1, -1, -1):
                if found.get(order[j]):
                    prev = order[j]
                    break
            if prev:
                cx = found[left]["cx"] + (found[left]["cx"] - found[prev]["cx"])
            else:
                cx = found[left]["cx"] + 200
        elif right:
            nxt = None
            ri = order.index(right)
            for j in range(ri + 1, len(order)):
                if found.get(order[j]):
                    nxt = order[j]
                    break
            if nxt:
                cx = found[right]["cx"] - (found[nxt]["cx"] - found[right]["cx"])
            else:
                cx = found[right]["cx"] - 200
        if cx is not None:
            found[key] = _synth_header(cx, header_cy)
    return found


def col_ranges(headers: dict) -> dict:
    keys = ["name", "spec", "unit", "qty", "price", "amount", "rate", "tax"]
    centers = [headers[k]["cx"] for k in keys]
    bounds = [(centers[i] + centers[i + 1]) / 2 for i in range(len(centers) - 1)]
    return {
        k: ((0 if i == 0 else bounds[i - 1]), (10**9 if i == len(keys) - 1 else bounds[i]))
        for i, k in enumerate(keys)
    }


def _round2(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    return round(float(v) + 1e-9, 2)


@dataclass
class LineItem:
    index: int
    name: str = ""
    spec: str = ""
    unit: str = ""
    qty: Optional[float] = None
    amount: Optional[float] = None
    tax: Optional[float] = None
    rate: Optional[float] = None
    unit_price: Optional[float] = None
    remark: str = ""

    @property
    def price(self) -> Optional[float]:
        if self.unit_price is not None:
            return self.unit_price
        if self.amount is None or not self.qty:
            return None
        return self.amount / self.qty

    @property
    def price_with_tax(self) -> Optional[float]:
        if self.amount is None or self.tax is None or not self.qty:
            return None
        return round((self.amount + self.tax) / self.qty, 6)

    @property
    def total(self) -> Optional[float]:
        if self.amount is None or self.tax is None:
            return None
        return round(self.amount + self.tax, 2)


@dataclass
class Invoice:
    source_file: str
    page: int
    image_path: str = ""
    rotation: int = 0
    engine: str = "ocr"
    seller: str = ""
    seller_alias: str = ""
    invoice_number: str = ""
    invoice_date: str = ""
    amount_total: Optional[float] = None
    tax_total: Optional[float] = None
    total: Optional[float] = None
    items: list[LineItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = "ok"
    sheet_name: str = ""
    arrival_date: str = ""
    stock_date: str = ""
    qr_payloads: list[str] = field(default_factory=list)

    def sum_amount(self) -> float:
        return round(sum((i.amount or 0) for i in self.items), 2)

    def sum_tax(self) -> float:
        return round(sum((i.tax or 0) for i in self.items), 2)

    def finalize_totals(self):
        if self.amount_total is None:
            self.amount_total = self.sum_amount()
        if self.tax_total is None:
            if self.total is not None:
                self.tax_total = round(self.total - (self.amount_total or 0), 2)
            else:
                self.tax_total = self.sum_tax()
        if self.total is None:
            self.total = round((self.amount_total or 0) + (self.tax_total or 0), 2)
        diff_a = round((self.amount_total or 0) - self.sum_amount(), 2)
        diff_t = round((self.tax_total or 0) - self.sum_tax(), 2)
        if self.items and (abs(diff_a) > 0.003 or abs(diff_t) > 0.003):
            if abs(diff_a) <= 0.05 and abs(diff_t) <= 0.05:
                last = self.items[-1]
                if last.amount is not None:
                    last.amount = round(last.amount + diff_a, 2)
                if last.tax is not None:
                    last.tax = round(last.tax + diff_t, 2)
            else:
                self.warnings.append(
                    f"明细合计({self.sum_amount():.2f}+{self.sum_tax():.2f})与发票合计不一致"
                )

    def validate(self) -> list[str]:
        warnings = list(self.warnings)
        if not self.seller:
            warnings.append("未识别到销售方名称")
        if not self.invoice_number:
            warnings.append("未识别到发票号码")
        if not self.invoice_date:
            warnings.append("未识别到开票日期")
        if not self.items:
            warnings.append("未识别到明细")
        if self.total is None:
            warnings.append("未识别到价税合计")
            return warnings
        if abs((self.amount_total or 0) + (self.tax_total or 0) - self.total) > 0.02:
            warnings.append("金额合计+税金合计不等于价税合计")
        if abs(self.sum_amount() - (self.amount_total or 0)) > 0.02:
            warnings.append("明细金额之和与金额合计不一致")
        if abs(self.sum_tax() - (self.tax_total or 0)) > 0.02:
            warnings.append("明细税额之和与税金合计不一致")
        for it in self.items:
            if not it.name:
                warnings.append(f"第{it.index}行缺少材料名称")
            if it.qty is None:
                warnings.append(f"第{it.index}行缺少数量")
            if it.amount is None:
                warnings.append(f"第{it.index}行缺少金额")
            if not it.unit:
                warnings.append(f"第{it.index}行缺少单位")
            if it.amount is not None and it.amount < 0:
                warnings.append(f"第{it.index}行为负数，请核对是否为优惠行")
            if it.amount is not None and it.tax is not None and it.rate:
                if abs(it.amount * it.rate - it.tax) > 0.03:
                    warnings.append(f"第{it.index}行金额×税率与税额不一致")
        return warnings


class ParseError(Exception):
    pass


def _same_item(a: LineItem, b: LineItem) -> bool:
    if a.name and b.name:
        na, nb = norm_text(a.name), norm_text(b.name)
        if na == nb:
            return True
        if _ratio(na, nb) >= 0.6 or na in nb or nb in na:
            return True
    if a.spec and b.spec:
        sa = _normalize_spec_compare(a.spec)
        sb = _normalize_spec_compare(b.spec)
        if sa == sb:
            return True
    return False


def merge_discount_lines(invoice: Invoice) -> Invoice:
    """把负数优惠行合并到前面的正数商品行，最终只保留净额明细。"""
    if not invoice.items:
        return invoice
    for item in invoice.items:
        if (item.unit_price or 0) < -0.005 and (item.amount or 0) >= 0:
            item.unit_price = round(item.amount / item.qty, 6) if item.qty else item.amount
    is_discount = lambda it: (it.amount or 0) < -0.005 or (it.tax or 0) < -0.005
    if not any(is_discount(it) for it in invoice.items):
        return invoice

    kept: list[LineItem] = []
    for item in invoice.items:
        if not is_discount(item):
            kept.append(item)
            continue
        target = None
        for prev in reversed(kept):
            if (prev.amount or 0) < 0:
                continue
            if _same_item(prev, item):
                target = prev
                break
        if target is None:
            for prev in reversed(kept):
                if (prev.amount or 0) >= 0:
                    target = prev
                    break
        if target is None:
            invoice.warnings.append(f"第{item.index}行是负数优惠，但前面没有可合并的商品行，已忽略")
            continue
        target.amount = round((target.amount or 0.0) + (item.amount or 0.0), 2)
        if item.tax is not None:
            target.tax = round((target.tax or 0.0) + item.tax, 2)
        if target.amount < -0.005:
            invoice.warnings.append(f"第{item.index}行优惠合并后金额仍为负数，已忽略该商品行")
            kept.remove(target)
            continue
        if target.qty:
            target.unit_price = round(target.amount / target.qty, 6)
        else:
            target.unit_price = target.amount
        invoice.warnings.append(f"第{item.index}行优惠已合并到第{target.index}行")

    for idx, item in enumerate(kept, 1):
        item.index = idx
    invoice.items = kept
    return invoice


def parse_invoice(
    boxes: list[dict],
    qr_payloads: list[str],
    width: int,
    height: int,
    text_layer: bool = False,
) -> Invoice:
    headers = get_headers(boxes)
    missing = [k for k in ("name", "spec", "unit", "qty", "price", "amount", "rate", "tax") if not headers.get(k)]
    if missing:
        raise ParseError("未识别到发票表格表头")
    ranges = col_ranges(headers)
    header_bottom = max(b["cy"] for b in headers.values()) + 2.0
    qr = parse_qr_payload(qr_payloads[0] if qr_payloads else "")
    total = qr.get("total")
    number = qr.get("number", "")
    date = qr.get("date", "")
    if not number:
        number = ocr_invoice_number(boxes)
    if not date:
        date = ocr_invoice_date(boxes)
    if total is None:
        total = invoice_total_from_boxes(boxes)

    price_total_ys = [b["y0"] for b in boxes if "价税合计" in norm_text(b["t"])]
    small_ys = [b["y0"] for b in boxes if "小写" in norm_text(b["t"])]
    bottoms = price_total_ys + small_ys
    table_bottom = (min(bottoms) if bottoms else height) - 5

    amount_boxes = [
        b
        for b in boxes
        if ranges["amount"][0] <= b["cx"] < ranges["amount"][1]
        and b["cy"] > header_bottom + 5
        and b["cy"] < table_bottom + 5
        and parse_num(b["t"]) is not None
    ]
    tax_boxes = [
        b
        for b in boxes
        if ranges["tax"][0] <= b["cx"] < ranges["tax"][1]
        and b["cy"] > header_bottom + 5
        and b["cy"] < table_bottom + 5
        and parse_num(b["t"]) is not None
    ]

    def has_item_label(cy):
        for b in boxes:
            if abs(b["cy"] - cy) > 40:
                continue
            if ranges["name"][0] <= b["cx"] < ranges["spec"][1] and b["t"].strip():
                return True
        return False

    totals_box = None
    tax_total = None
    currency_amounts = [b for b in amount_boxes if ("¥" in b["t"] or "￥" in b["t"])]

    def matching_tax(amount_box):
        value = parse_num(amount_box["t"])
        if value is None:
            return None, None
        near = [b for b in tax_boxes if abs(b["cy"] - amount_box["cy"]) <= 45]
        if total is not None:
            best = None
            for t in near:
                tv = parse_num(t["t"])
                if tv is None:
                    continue
                err = abs(value + tv - total)
                if best is None or err < best[0]:
                    best = (err, tv)
            if best and best[0] <= 0.03:
                return value, best[1]
            if abs(value - total) <= 0.02:
                return value, 0.0
            return None, None
        if near:
            return value, parse_num(max(near, key=lambda b: b["cy"])["t"])
        return value, None

    if total is not None:
        for b in sorted(currency_amounts, key=lambda x: -x["cy"]):
            value, matched_tax = matching_tax(b)
            if value is not None:
                totals_box, tax_total = b, matched_tax
                break

    currency_no_label = [b for b in currency_amounts if not has_item_label(b["cy"])]
    if totals_box is None and currency_no_label:
        totals_box = max(currency_no_label, key=lambda b: b["cy"])
    if totals_box is None:
        for b in sorted(amount_boxes, key=lambda b: -b["cy"]):
            if b["cy"] < table_bottom - 10 and not has_item_label(b["cy"]):
                totals_box = b
                break

    amount_total = None
    if totals_box is not None:
        amount_total = parse_num(totals_box["t"])
        totals_y = totals_box["cy"]
        expected_tax = None
        if total is not None and amount_total is not None:
            expected_tax = round(total - amount_total, 2)
        near_tax = [b for b in tax_boxes if abs(b["cy"] - totals_y) <= 45]
        if tax_total is None and near_tax:
            if expected_tax is not None:
                good = [
                    b
                    for b in near_tax
                    if parse_num(b["t"]) is not None
                    and abs((parse_num(b["t"]) or 0) - expected_tax) <= 0.03
                ]
                if good:
                    tax_total = parse_num(max(good, key=lambda b: b["cy"])["t"])
            if tax_total is None and expected_tax is None:
                tax_total = parse_num(max(near_tax, key=lambda b: b["cy"])["t"])
        if tax_total is None:
            tax_total = expected_tax
    else:
        totals_y = table_bottom

    item_bottom = min(totals_y, table_bottom) - 5
    anchors = []
    for b in amount_boxes:
        if totals_box is not None and b is totals_box:
            continue
        if b["cy"] >= item_bottom:
            continue
        if "¥" in b["t"] or "￥" in b["t"]:
            continue
        if totals_box is None and not has_item_label(b["cy"]):
            continue
        anchors.append((b["cy"], b, parse_num(b["t"])))
    anchors.sort()
    merged = []
    for ay, b, v in anchors:
        if merged and ay - merged[-1][0] < 12:
            if b["s"] > merged[-1][1]["s"]:
                merged[-1] = (ay, b, v)
        else:
            merged.append((ay, b, v))
    anchors = merged
    if not anchors:
        raise ParseError("未识别到发票明细行")

    centers = [a[0] for a in anchors]
    top = header_bottom + 3
    bands = []
    for i, cy in enumerate(centers):
        lo = top if i == 0 else (centers[i - 1] + cy) / 2
        hi = item_bottom if i == len(centers) - 1 else (cy + centers[i + 1]) / 2
        bands.append((lo, hi))

    def nearest_row(cy):
        return min(range(len(centers)), key=lambda i: abs(centers[i] - cy))

    def label_row(cy, h=0.0):
        """名称/规格会折行：归到“最后一个起始行不高于自己的明细行”，避免长名称串到下一行。"""
        tol = max(8.0, min(float(h or 0.0), 30.0) * 0.5)
        idx = 0
        for j, center in enumerate(centers):
            if center <= cy + tol:
                idx = j
            else:
                break
        return idx

    rows = [
        {"name": [], "spec": [], "unit": [], "qty": [], "price": [], "amount": [], "rate": [], "tax": []}
        for _ in anchors
    ]
    spec_left = None
    if headers.get("spec", {}).get("t"):
        spec_header = headers["spec"]
        margin = max(12.0, 0.18 * float(spec_header.get("w") or 100.0))
        spec_left = spec_header["x0"] - margin
    for b in boxes:
        if b["cy"] <= header_bottom + 3 or b["cy"] >= item_bottom + 2:
            continue
        col = None
        if text_layer and spec_left is not None and b["x0"] < spec_left:
            col = "name"
        else:
            for k, (lo, hi) in ranges.items():
                if lo <= b["cx"] < hi:
                    col = k
                    break
        if not col:
            continue
        if col in ("name", "spec"):
            idx = label_row(b["cy"], b["h"])
        else:
            idx = None
            for j, (lo, hi) in enumerate(bands):
                if lo <= b["cy"] < hi:
                    idx = j
                    break
            if idx is None:
                continue
        rows[idx][col].append(b)
    for row in rows:
        for k in row:
            row[k].sort(key=lambda b: (b["cy"], b["cx"]))

    seller = seller_from_boxes(boxes, width)
    invoice = Invoice(
        source_file="",
        page=0,
        seller=seller,
        invoice_number=number,
        invoice_date=date,
        amount_total=amount_total,
        tax_total=tax_total,
        total=total,
        qr_payloads=qr_payloads,
    )
    unit_ocr = [None] * len(rows)
    unit_boxes = []
    for row in rows:
        for b in row["unit"]:
            if not any(b is x for x in unit_boxes):
                unit_boxes.append(b)
    for b in unit_boxes:
        text = re.sub(r"\s+", "", b["t"])
        idxs = [i for i, cy in enumerate(centers) if b["y0"] - 8 <= cy <= b["y1"] + 8]
        if not idxs:
            idxs = [nearest_row(b["cy"])]
        if len(idxs) == 1:
            unit_ocr[idxs[0]] = text
        elif len(text) == len(idxs):
            for i, ch in zip(idxs, text):
                unit_ocr[i] = ch

    for i, row in enumerate(rows):
        amount = parse_num(anchors[i][1]["t"])
        rate = None
        for b in row["rate"]:
            m = re.search(r"(\d+(?:\.\d+)?)\s*%", b["t"])
            if m:
                rate = float(m.group(1)) / 100
                break
        tax = None
        for b in row["tax"]:
            v = parse_num(b["t"])
            if v is not None:
                tax = v
                break
        qty = None
        for b in row["qty"]:
            v = parse_num(b["t"])
            if v is not None:
                qty = v
                break
        price = None
        for b in row["price"]:
            ns = nums_in(b["t"])
            if ns:
                price = ns[-1]
                break
        if qty is None and amount is not None:
            best = None
            for b in row["qty"] + row["price"]:
                raw = re.sub(r"(?<=\d)[-—]\s*(?=\d)", ".", b["t"].strip())
                two = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*", raw)
                if two:
                    lv, rv = float(two.group(1)), float(two.group(2))
                    candidates = [(lv, rv)]
                    if abs(rv - round(rv)) < 1e-9:
                        rs = str(int(round(rv)))
                        for pos in range(1, len(rs)):
                            candidates.append((lv, float(rs[:pos] + "." + rs[pos:])))
                    for lv2, rv2 in candidates:
                        err = abs(lv2 * rv2 - amount)
                        if best is None or err < best[0]:
                            best = (err, lv2, rv2)
                else:
                    s = clean_num(raw)
                    for k in range(1, len(s)):
                        left, right = s[:k], s[k:]
                        if not re.fullmatch(r"\d+(?:\.\d+)?", left) or not re.fullmatch(r"\d+(?:\.\d+)?", right):
                            continue
                        lv, rv = float(left), float(right)
                        if lv <= 0 or rv <= 0:
                            continue
                        if len(right) == 1 and ("." in left or len(left) > 6):
                            continue
                        err = abs(lv * rv - amount)
                        if best is None or err < best[0]:
                            best = (err, lv, rv)
                    if best is None or best[0] > max(0.02, amount * 0.002):
                        for k in range(1, len(s)):
                            left = s[:k]
                            if not re.fullmatch(r"\d+(?:\.\d+)?", left):
                                continue
                            right = s[k:]
                            if not right.isdigit():
                                continue
                            lv = float(left)
                            for pos in range(1, len(right)):
                                rv = float(right[:pos] + "." + right[pos:])
                                err = abs(lv * rv - amount)
                                if best is None or err < best[0]:
                                    best = (err, lv, rv)
            if best and best[0] <= max(0.02, amount * 0.002):
                qty, price = best[1], best[2]
        if qty is None and price and amount is not None and price != 0:
            q = amount / price
            for nd in (0, 1, 2, 3):
                if abs(round(q, nd) - q) < 0.0005:
                    qty = round(q, nd)
                    break
        if price is None and qty and amount is not None and qty != 0:
            price = amount / qty
        if qty is None and price is None and amount is not None:
            qty = 1.0
            price = amount
        if tax is None and amount is not None and rate is not None:
            tax = _round2(amount * rate)
        if rate is None and amount and tax is not None:
            r0 = tax / amount
            for cand in (0.13, 0.09, 0.06, 0.05, 0.03, 0.01, 0.0):
                if abs(r0 - cand) < 0.01:
                    rate = cand
                    break

        name_parts = []
        spec_parts = []
        name_boxes = row["name"]
        for jb, b in enumerate(name_boxes):
            t = re.sub(r"\*[^*]*\*", "", b["t"])
            t = re.sub(r"^\s*\*+", "", t)
            t = re.sub(r"\s+", "", t)
            if not t:
                continue
            if jb == 0 and not row["spec"] and b["x1"] > ranges["spec"][0] + 5:
                m = re.search(r"([0-9A-Za-zφΦ][0-9A-Za-zφΦ.*×xX°/\-]*)$", t)
                if m and m.start() > 0:
                    spec_parts.insert(0, m.group(1))
                    t = t[: m.start()]
            name_parts.append(t)
        name = "".join(name_parts)
        while "*" in name:
            m = re.match(r"^[^*]*\*", name)
            if not m:
                break
            name = name[m.end() :]
        name = re.sub(r"\*[^*]*\*", "", name)
        name = re.sub(r"^\*+", "", name)
        if name and name[0] in "拿米中十木" and len(name) > 2:
            name = re.sub(r"^[拿米中十木]+(?=[\u4e00-\u9fff])", "", name)
        name = re.sub(r"(?<=\d)%(?=[\u4e00-\u9fff])", "°", name)

        for b in row["spec"]:
            spec_parts.append(b["t"])
        spec = re.sub(r"\s+", " ", " ".join(spec_parts)).strip()
        spec = spec.replace("中", "φ").replace("Φ", "φ").replace("$", "φ")
        spec = re.sub(r"φ\s+", "φ", spec)
        spec = re.sub(r"\s*\*\s*", "*", spec)
        spec = re.sub(r"(\d)\s*\.\s*(\d)", r"\1.\2", spec)

        if name in RESOURCES.completions:
            name = RESOURCES.completions[name]
        else:
            name = RESOURCES.catalog.complete_name(name)
        spec = RESOURCES.catalog.spec_for(seller, name, spec)
        if not spec:
            spec = RESOURCES.catalog.spec_for(seller, name, "")

        unit = unit_ocr[i] or ""
        inferred = infer_unit(seller, name, spec, unit)
        if unit not in VALID_UNITS:
            unit = inferred
        elif name in ("彩钢板", "彩钢板运费", "保温棉", "门折页", "门把手", "门插", "锁及其附件") or "运费" in name:
            unit = inferred
        elif any(k in name for k in ("螺丝", "螺栓", "螺钉", "垫片", "弹垫", "螺母", "销轴", "销子", "销钉", "垫圈")):
            combined = name + spec
            if re.search(r"[\[【(（]\s*\d+\s*(个|只|套|粒)", combined):
                unit = "份"
        if unit not in VALID_UNITS:
            unit = RESOURCES.catalog.unit_for(seller, name, spec, unit)
        item = LineItem(
            index=i + 1,
            name=name,
            spec=spec,
            unit=unit,
            qty=qty,
            amount=amount,
            tax=tax,
            rate=rate,
            unit_price=price,
        )
        invoice.items.append(item)

    rates = [it.rate for it in invoice.items if it.rate]
    if rates:
        dominant = Counter(rates).most_common(1)[0][0]
        for it in invoice.items:
            if it.rate is None and it.amount is not None:
                it.rate = dominant
            if it.tax is None and it.amount is not None and it.rate is not None:
                it.tax = _round2(it.amount * it.rate)
    merge_discount_lines(invoice)
    invoice.finalize_totals()
    return invoice


def infer_unit(seller: str, name: str, spec: str, ocr_unit: str = "") -> str:
    n = name or ""
    if re.search(r"[\[【(（]\s*\d+\s*(个|只|套|粒|件|包)", n + (spec or "")):
        return "份"
    if "运费" in n:
        return "项"
    if "人工费" in n:
        return "工"
    if "租车" in n:
        return "次"
    if "彩钢板" in n:
        return "m²"
    if "保温棉" in n:
        return "米"
    if n in ("门折页", "门把手"):
        return "付"
    if n == "门插":
        return "个"
    if n == "锁及其附件":
        return "把"
    if "监控设备" in n:
        return "套"
    if "无缝钢管" in n:
        return "吨"
    if "镀锌卷板" in n:
        return "吨"
    if n in ("铜板", "铜条"):
        return "kg"
    if "粉末涂料" in n or n == "涂料":
        return "公斤"
    if "气水分离器" in n:
        return "套"
    if "分气阀" in n:
        return "套"
    if "不锈钢酸洗管" in n:
        return "根"
    if "快接插头" in n:
        return "套"
    if "内丝" in n or "接头" in n or "弯头" in n or "阀门" in n:
        return "个"
    if "液体生胶带" in n or "生胶带卷" in n:
        return "个"
    if "防护罩" in n or "锁片" in n:
        return "件"
    if "钻头" in n or "钢板钻" in n:
        return "支"
    if "喷漆壶" in n:
        return "套"
    if "胶带" in n or "胶粘带" in n:
        return "卷"
    if "拉手" in n:
        return "个"
    if "脚轮" in n:
        return "个"
    if "密封" in n:
        return "个"
    if "断路" in n:
        return "个"
    if "喷漆" in n:
        return "瓶"
    if "三角带" in n:
        return "条"
    if "铰链" in n:
        return "个"
    if "抽纸" in n:
        return "件"
    if "扁凿" in n or "凿" in n:
        return "把"
    if "扁凿" in (spec or "") or "凿" in (spec or ""):
        return "把"
    if "锤" in n:
        return "把"
    if "搓纸轮" in n:
        return "个"
    if any(k in n for k in ("螺丝", "螺栓", "螺钉", "垫片", "弹垫", "螺母", "销轴", "销子", "销钉", "垫圈")):
        if re.search(r"[\[【(（]\s*\d+\s*(个|只|套|粒)", spec or ""):
            return "份"
        return "个"
    catalog_unit = RESOURCES.catalog.unit_for(seller, n, spec, "")
    if catalog_unit:
        return catalog_unit
    if ocr_unit in VALID_UNITS:
        return ocr_unit
    return ocr_unit or ""


def _cache_key(path: Path, page: int, rotation: int, dpi: int) -> str:
    try:
        st = path.stat()
        raw = f"pdfium|{path.resolve()}|{st.st_size}|{st.st_mtime_ns}|{page}|{rotation}|{dpi}"
    except Exception:
        raw = f"pdfium|{path}|{page}|{rotation}|{dpi}"
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()


def ocr_page_cached(path: Path, page: int, image: np.ndarray, rotation: int, dpi: int) -> list[dict]:
    key = _cache_key(path, page, rotation, dpi)
    cache_file = CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    boxes = ocr_image(image)
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(boxes, f, ensure_ascii=False)
    except Exception:
        pass
    return boxes


def preview_path_for(path: Path, page: int) -> Path:
    try:
        st = path.stat()
        raw = f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}|{page}"
    except Exception:
        raw = f"{path}|{page}"
    key = hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:16]
    return PREVIEW_DIR / f"{key}.png"


MODE_AUTO = "auto"
MODE_TEXT = "text"
MODE_OCR = "ocr"
VALID_MODES = (MODE_AUTO, MODE_TEXT, MODE_OCR)


def _clean_text_word(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text or ""))


def boxes_from_words(words: Iterable[dict]) -> list[dict]:
    """pdfplumber word -> 与 OCR 相同的 box 结构；顺便合并被拆开的单个汉字表头。"""
    items = []
    for w in words:
        text = _clean_text_word(w.get("text", ""))
        if not text:
            continue
        items.append(
            {
                "x0": float(w["x0"]),
                "x1": float(w["x1"]),
                "top": float(w["top"]),
                "bottom": float(w["bottom"]),
                "text": text,
                "single_cjk": len(text) == 1 and "\u4e00" <= text <= "\u9fff",
            }
        )
    items.sort(key=lambda w: (round(w["top"] / 3), w["x0"]))
    merged = []
    used = set()
    for i, w in enumerate(items):
        if i in used:
            continue
        cur = dict(w)
        if w["single_cjk"]:
            for j in range(i + 1, len(items)):
                if j in used:
                    continue
                v = items[j]
                if abs(v["top"] - cur["top"]) > 3:
                    if v["top"] - cur["top"] > 3:
                        break
                    continue
                gap = v["x0"] - cur["x1"]
                if gap > 12:
                    break
                if 0 <= gap <= 12 and v["single_cjk"]:
                    cur["text"] += v["text"]
                    cur["x1"] = v["x1"]
                    used.add(j)
        x0, x1 = cur["x0"], cur["x1"]
        y0, y1 = cur["top"], cur["bottom"]
        merged.append(
            {
                "x0": x0,
                "x1": x1,
                "y0": y0,
                "y1": y1,
                "cx": (x0 + x1) / 2,
                "cy": (y0 + y1) / 2,
                "w": x1 - x0,
                "h": y1 - y0,
                "t": cur["text"],
                "s": 1.0,
            }
        )
    return merged


def text_layer_sufficient(words: Iterable[dict]) -> bool:
    words = list(words)
    if len(words) < 15:
        return False
    text = "".join(_clean_text_word(w.get("text", "")) for w in words)
    has_number = bool(re.search(r"\d{20}", text)) or "发票号码" in text
    has_table = "项目名称" in text and ("金额" in text or "规格型号" in text)
    has_total = "价税合计" in text or "小写" in text
    return has_number and (has_table or has_total)


def decide_engine(mode: str, is_pdf: bool, words: Optional[Iterable[dict]]) -> str:
    """按页选择识别引擎：返回 text / ocr / none。"""
    mode = mode or MODE_AUTO
    if mode not in VALID_MODES:
        raise ValueError(f"未知识别模式: {mode}")
    if not is_pdf:
        return "none" if mode == MODE_TEXT else MODE_OCR
    sufficient = bool(words) and text_layer_sufficient(words)
    if mode == MODE_OCR:
        return MODE_OCR
    if mode == MODE_TEXT:
        return MODE_TEXT if sufficient else "none"
    return MODE_TEXT if sufficient else MODE_OCR


def parse_text_invoice(words: Iterable[dict], qr_payloads: list[str], width: int, height: int) -> Invoice:
    boxes = boxes_from_words(words)
    invoice = parse_invoice(boxes, qr_payloads, width, height, text_layer=True)
    invoice.engine = MODE_TEXT
    return invoice


def text_invoice_issues(invoice: Invoice) -> list[str]:
    issues = []
    if not invoice.invoice_number:
        issues.append("缺少发票号码")
    if invoice.total is None:
        issues.append("缺少价税合计")
    if not invoice.items:
        issues.append("缺少明细")
    if not invoice.seller or _is_personal(invoice.seller) or _is_buyer(invoice.seller):
        issues.append("销售方未识别")
    if invoice.items and abs(invoice.sum_amount() - (invoice.amount_total or 0)) > 0.06:
        issues.append("明细金额与合计不一致")
    if invoice.items and abs(invoice.sum_tax() - (invoice.tax_total or 0)) > 0.06:
        issues.append("明细税额与合计不一致")
    if any((it.amount or 0) < -0.005 for it in invoice.items):
        issues.append("明细仍有负数金额")
    return issues


def cross_validate_invoices(text_invoice: Invoice, ocr_invoice: Invoice) -> Invoice:
    """文字层优先精确字段；OCR 只补缺失，并记录冲突。"""
    primary = text_invoice
    used_ocr = False
    if not primary.seller or _is_personal(primary.seller) or _is_buyer(primary.seller):
        if ocr_invoice.seller and not _is_personal(ocr_invoice.seller) and not _is_buyer(ocr_invoice.seller):
            primary.seller = ocr_invoice.seller
            used_ocr = True
    elif ocr_invoice.seller and ocr_invoice.seller != primary.seller:
        primary.warnings.append(f"文字层销售方与OCR不一致：{primary.seller} / {ocr_invoice.seller}")
    for attr in ("invoice_number", "invoice_date"):
        if not getattr(primary, attr) and getattr(ocr_invoice, attr):
            setattr(primary, attr, getattr(ocr_invoice, attr))
            used_ocr = True
    if primary.total is None and ocr_invoice.total is not None:
        primary.total = ocr_invoice.total
        primary.amount_total = ocr_invoice.amount_total
        primary.tax_total = ocr_invoice.tax_total
        used_ocr = True
    if not primary.items and ocr_invoice.items:
        primary.items = ocr_invoice.items
        used_ocr = True
    primary.engine = "text+ocr" if used_ocr else MODE_TEXT
    return primary


@dataclass
class ProcessResult:
    invoices: list[Invoice] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)


class PageSkip(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _ocr_page_invoice(f: Path, page_idx: int, doc, dpi: int):
    try:
        full = render_pdf_page(doc, page_idx, dpi)
        preview = render_pdf_page(doc, page_idx, 150)
    except Exception as e:
        raise PageSkip(f"读取失败: {e}")
    rotation = detect_orientation(preview)
    oriented = rotate_image(full, rotation)
    preview_oriented = rotate_image(preview, rotation)
    try:
        boxes = ocr_page_cached(f, page_idx, oriented, rotation, dpi)
    except Exception as e:
        raise PageSkip(f"OCR失败: {e}")
    qr_payloads = decode_qr(oriented)
    qr_numbers = {parse_qr_payload(p).get("number") for p in qr_payloads}
    qr_numbers.discard(None)
    if len(qr_numbers) > 1:
        raise PageSkip("一页识别到多张发票，请拆分为单页后处理")
    title = find_title_box(boxes)
    if not qr_payloads and not title:
        raise PageSkip("不是发票页（可能是费用报销单）")
    try:
        invoice = parse_invoice(boxes, qr_payloads, oriented.shape[1], oriented.shape[0])
    except ParseError as e:
        qinfo = parse_qr_payload(qr_payloads[0] if qr_payloads else "")
        seller = seller_from_boxes(boxes, oriented.shape[1])
        raise PageSkip(
            f"已识别到发票 {qinfo.get('number', '')}（{seller or '未知销售方'}），但{str(e)}，请手动新增或校对"
        )
    except Exception as e:
        raise PageSkip(f"解析失败: {e}")
    invoice.engine = MODE_OCR
    return invoice, qr_payloads, rotation, preview_oriented


def _text_page_invoice(f: Path, page_idx: int, doc, words: list[dict], pdf_page):
    try:
        preview = render_pdf_page(doc, page_idx, 150)
    except Exception as e:
        raise PageSkip(f"读取失败: {e}")
    qr_payloads = decode_qr(preview)
    if not qr_payloads:
        try:
            hi = render_pdf_page(doc, page_idx, 250)
            qr_payloads = decode_qr(hi)
        except Exception:
            pass
    qr_numbers = {parse_qr_payload(p).get("number") for p in qr_payloads}
    qr_numbers.discard(None)
    if len(qr_numbers) > 1:
        raise PageSkip("一页识别到多张发票，请拆分为单页后处理")
    try:
        invoice = parse_text_invoice(
            words, qr_payloads, int(round(pdf_page.width)), int(round(pdf_page.height))
        )
    except Exception as e:
        raise PageSkip(f"文字层解析失败: {e}")
    return invoice, qr_payloads, preview


def process_inputs(
    paths: Iterable[str],
    recursive: bool = False,
    dpi: int = 300,
    progress: Optional[Callable[[str, int, int], None]] = None,
    stop_flag: Optional[Callable[[], bool]] = None,
    mode: str = MODE_AUTO,
) -> ProcessResult:
    mode = mode or MODE_AUTO
    if mode not in VALID_MODES:
        raise ValueError(f"未知识别模式: {mode}")
    files = collect_input_files(paths, recursive)
    result = ProcessResult()
    if not files:
        result.logs.append("没有找到 PDF 或图片文件")
        return result

    page_tasks = []
    opened_docs = []
    plumber_docs = {}
    for f in files:
        if f.suffix.lower() in PDF_EXTS:
            try:
                doc = pdfium.PdfDocument(str(f))
                opened_docs.append(doc)
                for idx in range(len(doc)):
                    page_tasks.append((f, idx, doc))
                if mode != MODE_OCR:
                    if pdfplumber is not None:
                        try:
                            plumber_docs[str(f)] = pdfplumber.open(str(f))
                        except Exception as e:
                            result.logs.append(f"{f.name}: 文字层不可用，将使用 OCR（{e}）")
                    else:
                        detail = f"（{_PDFPLUMBER_ERROR}）" if _PDFPLUMBER_ERROR else ""
                        result.logs.append(f"{f.name}: 未安装/无法加载 pdfplumber{detail}，文字层不可用，将使用 OCR")
            except Exception as e:
                result.logs.append(f"{f.name}: 无法打开 PDF ({e})")
        else:
            page_tasks.append((f, 0, None))
    total_pages = len(page_tasks)
    done = 0
    seen_numbers = set()
    seen_signatures = set()

    for f, page_idx, doc in page_tasks:
        if stop_flag and stop_flag():
            result.logs.append("已停止")
            break
        done += 1
        is_pdf = f.suffix.lower() in PDF_EXTS
        label = f"{f.name} 第{page_idx + 1}页" if is_pdf else f.name
        if progress:
            progress(f"正在识别 {label}", done - 1, total_pages)

        words: list[dict] = []
        pdf_page = None
        if is_pdf and str(f) in plumber_docs:
            try:
                pdf_page = plumber_docs[str(f)].pages[page_idx]
                if pdf_page.rotation % 360 in (90, 270):
                    result.logs.append(f"{label}: 文字层为旋转页，按扫描件走 OCR")
                else:
                    words = pdf_page.extract_words(use_text_flow=False, keep_blank_chars=False)
            except Exception as e:
                result.logs.append(f"{label}: 文字层读取失败，改用 OCR（{e}）")
                words = []

        engine = decide_engine(mode, is_pdf, words)
        if engine == "none":
            reason = "强制文字层模式：该页没有可用文字层（可能是扫描件/图片）"
            result.skipped.append({"file": str(f), "page": page_idx + 1, "reason": reason})
            continue

        invoice = None
        rotation = 0
        preview_oriented = None
        qr_payloads: list[str] = []
        text_invoice = None
        text_issues: list[str] = []

        if engine == MODE_TEXT:
            if pdf_page is None:
                result.skipped.append(
                    {"file": str(f), "page": page_idx + 1, "reason": "强制文字层模式：无法读取该页文字层"}
                )
                continue
            try:
                text_invoice, qr_payloads, preview_oriented = _text_page_invoice(
                    f, page_idx, doc, words, pdf_page
                )
            except PageSkip as e:
                text_issues = [e.reason]
            else:
                text_issues = text_invoice_issues(text_invoice)
                if text_issues:
                    result.logs.append(f"{label}: 文字层校验提示：{'；'.join(text_issues)}")
            if mode == MODE_TEXT:
                fatal = (
                    text_invoice is None
                    or not text_invoice.invoice_number
                    or not text_invoice.items
                    or text_invoice.total is None
                )
                if fatal:
                    reason = "强制文字层模式：" + ("；".join(text_issues) or "解析失败")
                    result.skipped.append({"file": str(f), "page": page_idx + 1, "reason": reason})
                    continue
                invoice = text_invoice
            elif text_invoice is not None and not text_issues:
                invoice = text_invoice
            else:
                try:
                    ocr_invoice, qr2, rotation, preview_oriented = _ocr_page_invoice(f, page_idx, doc, dpi)
                except PageSkip as e:
                    if text_invoice is not None:
                        invoice = text_invoice
                        invoice.warnings.append(f"文字层校验未通过且OCR回退失败：{e.reason}")
                    else:
                        result.skipped.append({"file": str(f), "page": page_idx + 1, "reason": e.reason})
                        continue
                except Exception as e:
                    if text_invoice is not None:
                        invoice = text_invoice
                        invoice.warnings.append(f"文字层校验未通过且OCR回退失败：{e}")
                    else:
                        result.skipped.append({"file": str(f), "page": page_idx + 1, "reason": f"OCR失败: {e}"})
                        continue
                else:
                    qr_payloads = qr2 or qr_payloads
                    if text_invoice is not None:
                        invoice = cross_validate_invoices(text_invoice, ocr_invoice)
                        invoice.warnings.append("文字层校验未通过，已OCR交叉校验：" + "；".join(text_issues))
                    else:
                        invoice = ocr_invoice
                    result.logs.append(f"{label}: 文字层未通过，已回退OCR（{'；'.join(text_issues)}）")
        else:
            if not is_pdf:
                try:
                    full = load_image(f)
                except Exception as e:
                    result.skipped.append({"file": str(f), "page": page_idx + 1, "reason": f"读取失败: {e}"})
                    continue
                preview = full
                h, w = full.shape[:2]
                scale = min(1.0, 1600 / max(h, w))
                if scale < 1.0:
                    preview = cv2.resize(full, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
                rotation = detect_orientation(preview)
                oriented = rotate_image(full, rotation)
                preview_oriented = rotate_image(preview, rotation)
                try:
                    boxes = ocr_page_cached(f, page_idx, oriented, rotation, dpi)
                except Exception as e:
                    result.skipped.append({"file": str(f), "page": page_idx + 1, "reason": f"OCR失败: {e}"})
                    continue
                qr_payloads = decode_qr(oriented)
                qr_numbers = {parse_qr_payload(p).get("number") for p in qr_payloads}
                qr_numbers.discard(None)
                if len(qr_numbers) > 1:
                    result.skipped.append(
                        {"file": str(f), "page": page_idx + 1, "reason": "一页识别到多张发票，请拆分为单页后处理"}
                    )
                    continue
                title = find_title_box(boxes)
                if not qr_payloads and not title:
                    result.skipped.append(
                        {"file": str(f), "page": page_idx + 1, "reason": "不是发票页（可能是费用报销单）"}
                    )
                    continue
                try:
                    invoice = parse_invoice(boxes, qr_payloads, oriented.shape[1], oriented.shape[0])
                except ParseError as e:
                    qinfo = parse_qr_payload(qr_payloads[0] if qr_payloads else "")
                    seller = seller_from_boxes(boxes, oriented.shape[1])
                    result.skipped.append(
                        {
                            "file": str(f),
                            "page": page_idx + 1,
                            "reason": f"已识别到发票 {qinfo.get('number', '')}（{seller or '未知销售方'}），但{str(e)}，请手动新增或校对",
                        }
                    )
                    continue
                invoice.engine = MODE_OCR
            else:
                try:
                    invoice, qr_payloads, rotation, preview_oriented = _ocr_page_invoice(f, page_idx, doc, dpi)
                except PageSkip as e:
                    result.skipped.append({"file": str(f), "page": page_idx + 1, "reason": e.reason})
                    continue
                except Exception as e:
                    result.skipped.append({"file": str(f), "page": page_idx + 1, "reason": f"OCR失败: {e}"})
                    continue

        invoice.source_file = str(f)
        invoice.page = page_idx + 1
        invoice.rotation = rotation
        invoice.seller_alias = alias_for(invoice.seller)
        if preview_oriented is None:
            try:
                preview_oriented = render_pdf_page(doc, page_idx, 150) if is_pdf else load_image(f)
            except Exception:
                preview_oriented = None
        pv = preview_path_for(f, page_idx)
        if preview_oriented is not None:
            try:
                cv2.imencode(".png", preview_oriented)[1].tofile(str(pv))
                invoice.image_path = str(pv)
            except Exception:
                pass
        signature = (invoice.seller, amount_to_text(invoice.total or 0), invoice.invoice_date)
        if invoice.invoice_number and invoice.invoice_number in seen_numbers:
            result.skipped.append(
                {"file": str(f), "page": page_idx + 1, "reason": f"重复发票 {invoice.invoice_number}"}
            )
            continue
        if not invoice.invoice_number and signature in seen_signatures:
            result.skipped.append({"file": str(f), "page": page_idx + 1, "reason": "疑似重复发票"})
            continue
        if invoice.invoice_number:
            seen_numbers.add(invoice.invoice_number)
        seen_signatures.add(signature)
        invoice.warnings = list(dict.fromkeys(invoice.warnings + invoice.validate()))
        invoice.status = "ok" if not invoice.warnings else "warning"
        result.invoices.append(invoice)
        result.logs.append(
            f"{label}: {invoice.seller or '未知销售方'} {invoice.invoice_number or ''} "
            f"{invoice.total or 0:.2f} 元, {len(invoice.items)} 项 [{invoice.engine}]"
        )
    for doc in opened_docs:
        try:
            doc.close()
        except Exception:
            pass
    for pdoc in plumber_docs.values():
        try:
            pdoc.close()
        except Exception:
            pass
    assign_sheet_names(result.invoices)
    if progress:
        progress("识别完成", total_pages, total_pages)
    return result


def assign_sheet_names(invoices: list[Invoice]):
    used = set()
    for inv in invoices:
        alias = inv.seller_alias or alias_for(inv.seller)
        inv.seller_alias = alias
        amount_text = amount_to_text(inv.total or 0)
        if len(alias) + len(amount_text) > 31:
            alias = alias[: max(0, 31 - len(amount_text))]
            inv.seller_alias = alias
        base = f"{alias}{amount_text}"
        date_suffix = ""
        if inv.invoice_date and len(inv.invoice_date) >= 10:
            date_suffix = inv.invoice_date[5:7] + inv.invoice_date[8:10]
        inv.sheet_name = safe_sheet_name(base, used, date_suffix)


def learn_from_folder(folder: str) -> tuple[int, int, list[str]]:
    import xlrd

    rows = []
    aliases = {}
    logs = []
    root = Path(folder)
    files = sorted(
        [p for p in root.rglob("*.xls") if p.is_file() and "入库单" in p.name],
        key=lambda p: natural_key(str(p)),
    )
    for p in files:
        try:
            book = xlrd.open_workbook(str(p), formatting_info=False)
        except Exception as e:
            logs.append(f"{p.name}: 打开失败 {e}")
            continue
        for sheet_name in book.sheet_names():
            try:
                sheet = book.sheet_by_name(sheet_name)
            except Exception:
                continue
            if sheet.nrows < 4 or sheet.ncols < 10:
                continue
            a2 = str(sheet.cell_value(1, 0)).strip()
            if not a2.startswith("收到"):
                continue
            seller = a2.split("：", 1)[-1].split(":", 1)[-1].strip()
            if not seller:
                continue
            m = re.match(r"^(.*?)(\d+(?:\.\d+)?)$", sheet_name.strip())
            if m and m.group(1).strip():
                aliases[seller] = m.group(1).strip()
            total_row = None
            for r in range(3, min(sheet.nrows, 80)):
                try:
                    if str(sheet.cell_value(r, 2)).strip() == "合计":
                        total_row = r
                        break
                except Exception:
                    pass
            if total_row is None:
                continue
            for r in range(3, total_row):
                try:
                    name = str(sheet.cell_value(r, 1)).strip()
                    spec = str(sheet.cell_value(r, 2)).strip()
                    unit = str(sheet.cell_value(r, 3)).strip()
                except Exception:
                    continue
                if name:
                    rows.append(
                        {
                            "source": str(p),
                            "sheet": sheet_name,
                            "seller": seller,
                            "name": name,
                            "spec": spec,
                            "unit": unit,
                        }
                    )
    RESOURCES.add_user_rows(rows)
    for seller, alias in aliases.items():
        if seller not in RESOURCES.alias_overrides:
            RESOURCES.alias_overrides[seller] = alias
    if aliases:
        save_json(USER_DIR / "aliases.json", RESOURCES.alias_overrides)
    return len(rows), len(aliases), logs
