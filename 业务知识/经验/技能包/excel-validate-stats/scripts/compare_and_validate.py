#!/usr/bin/env python3
"""
Compare two Excel inventory files and cross-validate statistics.

Engine selection (Java-preferred, Python-fallback):
- If `demo-0.0.1-SNAPSHOT.jar` is found (auto-detected or via --jar), the
  original Spring Boot JAR `compare` mode generates <source>_差异.xlsx.
- Otherwise the pure-Python implementation below generates the diff Excel,
  replicating the JAR's compare semantics exactly:
    * same key present in BOTH files with the SAME 进价 -> one row whose
      库存数量 = compare_qty - source_qty (net increment; rows whose rounded
      increment is 0 are dropped, matching the JAR's "删除增量=0的行" rule).
    * same key present in BOTH with a DIFFERENT 进价 -> TWO rows: a
      "remove-source" row (库存数量 = -source_qty at the source 进价) and an
      "add-compare" row (库存数量 = +compare_qty at the compare 进价). This is
      how the JAR expresses a price change, and is why such keys appear as
      duplicate 5-key groups in the diff file.
  Amount per row = 库存数量 x 进价 (read back by the stats engine).

Either way the pipeline then:
3. Compute stats for source, compare, and the diff file (Decimal precision),
   saving a same-name .txt alongside each.
4. Cross-validate: delta_qty (source - compare) must equal -diff_qty.
5. Print a side-by-side summary report.

The cross-validation is engine-agnostic: it reads the generated diff Excel and
checks the quantity identity, so it works identically for Java- or Python-made
diff files.

Usage:
    python compare_and_validate.py <source.xlsx> <compare.xlsx> [--out-dir DIR] [--jar PATH] [--force-python]
"""

import argparse
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inv_io import (  # noqa: E402
    load_sheet,
    normalize_path,
    build_row_key,
    get_cell_decimal,
    insert_suffix,
    clean_header,
    file_fingerprint,
    verify_inputs_untouched,
    write_workbook_preserving_format,
)
from calculate_stats import analyze_inventory, build_report_text  # noqa: E402


def fmt_dec(d: Decimal) -> str:
    """Format a Decimal for display — no scientific notation, keep precision."""
    return format(d.normalize(), "f")


def dup_label(info) -> str:
    if info["dup_row_count"] == 0:
        return "无重复行"
    return f"重复 {info['dup_row_count']} 行 / {info['dup_group_count']} 组"


def compute_side(path):
    """Return (raw_headers, qty_col, price_col, key_indices, {key: (qty, price, rep_row)})."""
    p = normalize_path(path)
    if not p.exists():
        print(f"错误: 文件不存在: {p}", file=sys.stderr)
        sys.exit(1)
    if p.suffix.lower() not in (".xlsx", ".xlsm"):
        print(f"错误: 不支持的格式: {p.suffix}", file=sys.stderr)
        sys.exit(1)

    _, raw_headers, cleaned_headers, rows, qty_col, price_col, key_indices = load_sheet(p)
    side = {}
    for row in rows:
        if all(c.value is None or str(c.value).strip() == "" for c in row):
            continue
        key = build_row_key(row, key_indices, cleaned_headers)
        q = get_cell_decimal(row[qty_col]) if qty_col is not None and qty_col < len(row) else None
        price = get_cell_decimal(row[price_col]) if price_col is not None and price_col < len(row) else None
        if key not in side:
            side[key] = {"qty": Decimal("0"), "price": price, "rep": row}
        if q is not None:
            side[key]["qty"] += q
    return raw_headers, qty_col, price_col, key_indices, side


def _prices_differ(a: Decimal, b: Decimal) -> bool:
    """True when the two purchase prices should be treated as different.

    Mirrors the JAR's compare mode: prices are compared at 2-decimal (分/cent)
    precision, so a difference of 0.01 or less is treated as "same price" and
    collapses to one net row (库存数量 = compare_qty - source_qty). Only a
    price gap strictly greater than 0.01 forces the two-row "remove-source /
    add-compare" split. This is exactly why the JAR emits 250 duplicate 5-key
    groups on these files rather than the ~551 a naive 6-decimal comparison
    would produce.

    Both None is "equal" (no price change). A None vs a real value counts as
    different.
    """
    if a is None and b is None:
        return False
    if a is None or b is None:
        return True
    # JAR compares prices at cent granularity: a gap strictly greater than 0.01
    # (one cent) counts as a real price change and triggers the two-row split;
    # anything within 0.01 collapses to a single net row. Verified against the
    # JAR's own output on these files (|diff| > 0.01 -> 250 split groups,
    # |diff| <= 0.01 -> 301 one-row groups; a clean separation).
    return abs(a - b) > Decimal("0.01")


def python_diff(source_path: Path, compare_path: Path, out_dir: Path) -> Path:
    """Pure-Python diff generation, mirroring the JAR's compare semantics.

    Returns the diff Excel path. Per the JAR:
      * key in both files with the SAME 进价 -> one net row
        (库存数量 = compare_qty - source_qty), dropping rows whose rounded
        increment is 0 ("删除增量=0的行").
      * key in both with a DIFFERENT 进价 -> two rows: a "remove-source" row
        (库存数量 = -source_qty at the source 进价) and an "add-compare" row
        (库存数量 = +compare_qty at the compare 进价). Rows whose rounded
        quantity is 0 are dropped, so a price change on a single-side key still
        collapses to one row.
    """
    s_raw, s_qty, s_price, s_keys, s_side = compute_side(source_path)
    c_raw, c_qty, c_price, c_keys, c_side = compute_side(compare_path)

    if not s_keys or not c_keys:
        print("警告: 未检测到完整的对比关键列，将退化为整行匹配，差异结果可能不完整。")

    union_keys = set(s_side.keys()) | set(c_side.keys())

    # Optional 金额 column to keep the diff file human-readable.
    s_clean = [clean_header(h) for h in s_raw]
    amount_col = None
    for cand in ("金额", "金额总数量", "金额数量"):
        if cand in s_clean:
            amount_col = s_clean.index(cand)
            break

    diff_rows = []
    for key in union_keys:
        s_entry = s_side.get(key)
        c_entry = c_side.get(key)
        sq = s_entry["qty"] if s_entry else Decimal("0")
        cq = c_entry["qty"] if c_entry else Decimal("0")
        s_price_d = s_entry["price"] if s_entry else None
        c_price_d = c_entry["price"] if c_entry else None

        if not _prices_differ(s_price_d, c_price_d):
            # --- same price: one net row (JAR "删除增量=0的行") ---
            inc = (cq - sq).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
            if inc == Decimal("0"):
                continue
            rep_entry = s_entry or c_entry
            rep_row = rep_entry["rep"]
            price = rep_entry["price"]
            new_row = [c.value for c in rep_row]
            if s_qty is not None and s_qty < len(new_row):
                new_row[s_qty] = float(inc)
            if amount_col is not None and price is not None and amount_col < len(new_row):
                new_row[amount_col] = float(inc * price)
            diff_rows.append(new_row)
        else:
            # --- different price: two rows (remove source, add compare) ---
            if s_entry is not None:
                q1 = (-sq).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
                if q1 != Decimal("0"):
                    rep_row = s_entry["rep"]
                    price = s_entry["price"]
                    new_row = [c.value for c in rep_row]
                    if s_qty is not None and s_qty < len(new_row):
                        new_row[s_qty] = float(q1)
                    if amount_col is not None and price is not None and amount_col < len(new_row):
                        new_row[amount_col] = float(q1 * price)
                    diff_rows.append(new_row)
            if c_entry is not None:
                q2 = cq.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
                if q2 != Decimal("0"):
                    rep_row = c_entry["rep"]
                    price = c_entry["price"]
                    new_row = [c.value for c in rep_row]
                    if s_qty is not None and s_qty < len(new_row):
                        new_row[s_qty] = float(q2)
                    if amount_col is not None and price is not None and amount_col < len(new_row):
                        new_row[amount_col] = float(q2 * price)
                    diff_rows.append(new_row)

    diff_filename = insert_suffix(source_path.name, "_差异")
    diff_path = out_dir / diff_filename
    # Preserve the source file's styling: write the diff rows into a copy of the
    # source workbook (keeps sheet name "Sheet1", header style, column widths,
    # and the date number format), instead of a blank openpyxl workbook.
    write_workbook_preserving_format(
        source_path, header_row_index=1, data_rows=diff_rows, out_path=diff_path
    )
    return diff_path


def run_pipeline(source_path, compare_path, out_dir, jar=None, force_python=False) -> int:
    source_path = normalize_path(source_path)
    compare_path = normalize_path(compare_path)
    out_dir = normalize_path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if source_path.name == compare_path.name:
        print(f"错误: 两个输入文件不能同名: {source_path.name}", file=sys.stderr)
        return 1

    # 红线原则: 对比/比对场景下, 文件A 与 文件B 都必须是只读的。
    # 记录两个输入文件的指纹(大小+修改时间), 全部流程结束后必须均未变。
    input_snapshots = [
        (source_path, file_fingerprint(source_path)),
        (compare_path, file_fingerprint(compare_path)),
    ]
    input_labels = ["文件A(源文件)", "文件B(对比文件)"]

    # ---- Engine selection: Java preferred, Python fallback ----------------
    from java_bridge import find_jar, java_compare
    engine = None
    diff_path = None
    if not force_python:
        jar_path = find_jar(jar, near_source=source_path)
        if jar_path:
            try:
                diff_path = java_compare(jar_path, source_path, compare_path, out_dir)
                engine = "java"
            except Exception as exc:
                if jar:  # explicit --jar: fail loud
                    print(f"Java compare 失败: {exc}", file=sys.stderr)
                    return 1
                print(f"警告: Java 执行失败，回退到 Python: {exc}", file=sys.stderr)
    if diff_path is None:
        diff_path = python_diff(source_path, compare_path, out_dir)
        engine = "python"

    print(f"差异文件已生成: {diff_path}  [引擎: {engine}]")

    # ---- Stats for all three (Decimal) ------------------------------------
    print("\n正在分析统计数据...")
    stats = {}
    for label, fpath in [("source", source_path), ("compare", compare_path), ("diff", diff_path)]:
        try:
            info = analyze_inventory(fpath)
            stats[label] = info
            print(f"  OK {info['file_name']}: 数量={fmt_dec(info['total_quantity'])}, "
                  f"金额={fmt_dec(info['total_amount'])}, {dup_label(info)}")
            txt_path = Path(fpath).with_suffix(".txt")
            txt_path.write_text(build_report_text(info), encoding="utf-8")
        except Exception as exc:
            print(f"  FAIL {Path(fpath).name}: 统计失败 - {exc}", file=sys.stderr)
            return 4

    src, cmp, diff = stats["source"], stats["compare"], stats["diff"]
    delta_qty = src["total_quantity"] - cmp["total_quantity"]
    delta_amt = src["total_amount"] - cmp["total_amount"]

    # Quantity cross-validation: diff stores increment (compare - source),
    # so diff_qty == -(source - compare) == -delta_qty  ->  delta + diff == 0.
    qty_match = (delta_qty + diff["total_quantity"] == Decimal("0"))

    def check_mark(matched: bool) -> str:
        return "OK 匹配" if matched else "FAIL 不匹配"

    print()
    print("=" * 62)
    print("库存对比与交叉验证报告")
    print("=" * 62)
    print(f"差异生成引擎: {engine}")
    print()
    print(f"文件A (源文件): {source_path.name}")
    print(f"  Excel 总行数:  {src['excel_total_rows']}  (含表头)")
    print(f"  数据行数:      {src['data_row_count']}")
    print(f"  重复行:        {dup_label(src)}")
    print(f"  库存总数量:    {fmt_dec(src['total_quantity'])}")
    print(f"  金额总数量:    {fmt_dec(src['total_amount'])}")
    print()
    print(f"文件B (对比文件): {compare_path.name}")
    print(f"  Excel 总行数:  {cmp['excel_total_rows']}  (含表头)")
    print(f"  数据行数:      {cmp['data_row_count']}")
    print(f"  重复行:        {dup_label(cmp)}")
    print(f"  库存总数量:    {fmt_dec(cmp['total_quantity'])}")
    print(f"  金额总数量:    {fmt_dec(cmp['total_amount'])}")
    print()
    print("-" * 62)
    print("差额计算 (A - B):")
    print(f"  库存数量差:  {fmt_dec(delta_qty)}")
    print(f"  金额数量差:  {fmt_dec(delta_amt)}")
    print()
    print(f"差异文件 ({diff['file_name']}) 统计:")
    print(f"  Excel 总行数:  {diff['excel_total_rows']}  (含表头)")
    print(f"  数据行数:      {diff['data_row_count']}")
    print(f"  重复行:        {dup_label(diff)}")
    print(f"  库存总数量:    {fmt_dec(diff['total_quantity'])}")
    print(f"  金额总数量:    {fmt_dec(diff['total_amount'])}")
    print()
    print("-" * 62)
    print("交叉验证:")
    print(f"  库存数量差额:  {fmt_dec(delta_qty)}  (A - B)")
    print(f"  差异文件数量:  {fmt_dec(diff['total_quantity'])}  (增量方向: B - A)")
    print(f"  数量验证:      {check_mark(qty_match)}  (delta == -diff)")
    print()
    print(f"  金额差额:      {fmt_dec(delta_amt)}  (A - B, 简单相减)")
    print(f"  差异文件金额:  {fmt_dec(diff['total_amount'])}  (逐行: 增量 x 进价)")
    print(f"  注: 金额二者计算方式不同, 仅做参考对比")
    print("-" * 62)
    print("输入文件只读校验:")
    if not verify_inputs_untouched(input_snapshots, input_labels):
        print("=" * 62)
        return 3
    print("=" * 62)

    if not qty_match:
        print()
        print("WARNING: 库存数量交叉验证未通过!")
        discrepancy = delta_qty + diff["total_quantity"]
        print(f"  delta + diff = {fmt_dec(discrepancy)} (期望 0)")
        return 2

    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="对比两个 Excel 库存文件并交叉验证（Java 优先，Python 兜底）")
    ap.add_argument("source", help="源文件路径 (绝对路径)")
    ap.add_argument("compare", help="对比文件路径 (绝对路径)")
    ap.add_argument("--out-dir", default=None,
                    help="差异文件输出目录（默认：源文件所在目录）")
    ap.add_argument("--jar", default=None, help="显式指定 demo JAR 路径（强制走 Java）")
    ap.add_argument("--force-python", action="store_true",
                    help="即使找到 JAR 也强制使用 Python 实现")
    args = ap.parse_args()

    source_path = normalize_path(args.source)
    compare_path = normalize_path(args.compare)
    out_dir = normalize_path(args.out_dir) if args.out_dir else source_path.parent

    sys.exit(run_pipeline(source_path, compare_path, out_dir,
                          jar=args.jar, force_python=args.force_python))


if __name__ == "__main__":
    main()
