import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from invoice2rkd.core import (  # noqa: E402
    Invoice,
    LineItem,
    amount_to_text,
    assign_sheet_names,
    decide_engine,
    merge_discount_lines,
    safe_sheet_name,
    seller_from_boxes,
    strip_company_suffix,
    text_layer_sufficient,
)
from invoice2rkd.excel_writer import verify_workbook, write_workbook  # noqa: E402


def main():
    assert amount_to_text(8130.0) == "8130"
    assert amount_to_text(8999.1) == "8999.10"
    assert strip_company_suffix("示例供应商有限公司") == "示例供应商"
    assert strip_company_suffix("示例商行（个体工商户）") == "示例商行"

    used = set()
    assert safe_sheet_name("测试供应商1130", used, "1101") == "测试供应商1130"
    assert safe_sheet_name("测试供应商1130", used, "1101") == "测试供应商1130-1101"

    invoice = Invoice(
        source_file="",
        page=1,
        seller="示例供应商有限公司",
        invoice_number="EXAMPLE001",
        invoice_date="2026.11.01",
        amount_total=1500.0,
        tax_total=195.0,
        total=1695.0,
        items=[
            LineItem(
                index=1,
                name="示例材料A",
                spec="M10*20",
                unit="个",
                qty=100,
                amount=1000.0,
                tax=130.0,
                rate=0.13,
                unit_price=10.0,
            ),
            LineItem(
                index=2,
                name="示例材料B",
                spec="20*30",
                unit="件",
                qty=5,
                amount=500.0,
                tax=65.0,
                rate=0.13,
                unit_price=100.0,
            ),
        ],
        arrival_date="2026.11.01",
        stock_date="2026.11.01",
    )
    assign_sheet_names([invoice])
    assert invoice.sheet_name == "示例供应商1695"

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "test.xls")
        write_workbook([invoice], out, backup=False)
        issues = verify_workbook(out, [invoice])
        assert issues == [], issues

        import xlrd

        book = xlrd.open_workbook(out)
        sheet = book.sheet_by_index(0)
        total_row = None
        for r in range(3, min(sheet.nrows, 60)):
            if str(sheet.cell_value(r, 2)).strip() == "合计":
                total_row = r
                break
        assert total_row is not None
        assert abs(float(sheet.cell_value(total_row, 7)) - 1500.0) < 0.001
        assert abs(float(sheet.cell_value(total_row, 8)) - 195.0) < 0.001
        assert abs(float(sheet.cell_value(total_row, 9)) - 1695.0) < 0.001

    test_discount_merge()
    test_seller_selection()
    test_mode_selection()
    test_i18n()
    print("OK: basic tests passed")


def _box(text, x0, x1, y0, y1):
    return {
        "x0": x0,
        "x1": x1,
        "y0": y0,
        "y1": y1,
        "cx": (x0 + x1) / 2,
        "cy": (y0 + y1) / 2,
        "w": x1 - x0,
        "h": y1 - y0,
        "t": text,
        "s": 1.0,
    }


def test_discount_merge():
    inv = Invoice(
        source_file="",
        page=1,
        seller="测试供应商有限公司",
        invoice_number="X1",
        invoice_date="2026.09.01",
        amount_total=255.22,
        tax_total=33.18,
        total=288.40,
        items=[
            LineItem(index=1, name="角磨机", spec="9810MA", unit="台", qty=2, amount=285.31, tax=37.09, rate=0.13, unit_price=142.655),
            LineItem(index=2, name="角磨机", spec="9810MA", unit="台", qty=1, amount=-30.09, tax=-3.91, rate=0.13, unit_price=-30.09),
        ],
    )
    merge_discount_lines(inv)
    assert len(inv.items) == 1
    item = inv.items[0]
    assert abs(item.amount - 255.22) < 0.001
    assert abs(item.tax - 33.18) < 0.001
    assert abs(item.unit_price - 127.61) < 0.001
    assert item.qty == 2
    assert item.amount >= 0 and item.unit_price >= 0
    assert any("优惠" in w for w in inv.warnings)

    inv2 = Invoice(
        source_file="",
        page=1,
        items=[
            LineItem(index=1, name="A", qty=1, amount=100, tax=13, rate=0.13),
            LineItem(index=2, name="B", qty=1, amount=50, tax=6.5, rate=0.13),
            LineItem(index=3, name="B", qty=1, amount=-10, tax=-1.3, rate=0.13),
        ],
    )
    merge_discount_lines(inv2)
    assert len(inv2.items) == 2
    assert abs(inv2.items[1].amount - 40) < 0.001

    inv3 = Invoice(
        source_file="",
        page=1,
        items=[
            LineItem(index=1, name="C", qty=1, amount=10, tax=1.3, rate=0.13),
            LineItem(index=2, name="C", qty=1, amount=-10, tax=-1.3, rate=0.13),
        ],
    )
    merge_discount_lines(inv3)
    assert len(inv3.items) == 1 and inv3.items[0].amount == 0

    inv4 = Invoice(
        source_file="",
        page=1,
        items=[LineItem(index=1, name="D", qty=2, amount=10, tax=1.3, rate=0.13, unit_price=-5)],
    )
    merge_discount_lines(inv4)
    assert inv4.items[0].unit_price == 5


def test_seller_selection():
    width = 609
    merged = [
        _box("名称：个人", 26, 85, 97, 106),
        _box("名称：北京京东工业品贸易有限公司", 325, 460, 97, 106),
        _box("名称：个人", 26, 85, 120, 129),
    ]
    assert seller_from_boxes(merged, width) == "北京京东工业品贸易有限公司"

    split = [
        _box("购", 26, 35, 87, 96),
        _box("名", 41, 50, 97, 106),
        _box("称", 55, 64, 97, 106),
        _box(":", 64, 69, 101, 110),
        _box("个人", 71, 84, 97, 105),
        _box("销", 312, 321, 87, 96),
        _box("名", 325, 334, 97, 106),
        _box("称", 339, 348, 97, 106),
        _box(":", 348, 354, 101, 110),
        _box("北京京东工业品贸易有限公司", 356, 460, 97, 105),
        _box("下载次数：1", 587, 596, 90, 141),
    ]
    assert seller_from_boxes(split, width) == "北京京东工业品贸易有限公司"

    buyer_only = [
        _box("名称：个人", 26, 85, 97, 106),
        _box("名称：个人", 325, 460, 97, 106),
    ]
    assert seller_from_boxes(buyer_only, width) == ""


def test_mode_selection():
    words = [
        {"text": "电子发票"},
        {"text": "发票号码：26342000002848663861"},
        {"text": "项目名称"},
        {"text": "金额"},
        {"text": "价税合计"},
    ] + [{"text": "x"} for _ in range(12)]
    assert text_layer_sufficient(words)
    assert decide_engine("auto", True, words) == "text"
    assert decide_engine("text", True, words) == "text"
    assert decide_engine("ocr", True, words) == "ocr"
    assert decide_engine("auto", True, []) == "ocr"
    assert decide_engine("text", True, []) == "none"
    assert decide_engine("auto", False, []) == "ocr"
    assert decide_engine("text", False, []) == "none"


def test_i18n():
    from invoice2rkd import i18n

    orig = i18n.SETTINGS_FILE
    try:
        with tempfile.TemporaryDirectory() as tmp:
            i18n.SETTINGS_FILE = Path(tmp) / "settings.json"
            i18n.set_language("en")
            assert i18n.get_language() == "en"
            assert i18n.tr("添加 PDF/图片") == "Add PDF/Images"
            assert i18n.tr_runtime("第1行缺少单位") == "Line 1: missing unit"
            assert i18n.tr_runtime("识别完成: 140 张发票，跳过 0 页") == "Done: 140 invoice(s), 0 page(s) skipped"
            i18n.set_language("zh")
            assert i18n.get_language() == "zh"
            assert i18n.tr("添加 PDF/图片") == "添加 PDF/图片"
    finally:
        i18n.SETTINGS_FILE = orig


if __name__ == "__main__":
    main()
