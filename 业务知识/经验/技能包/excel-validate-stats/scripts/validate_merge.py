#!/usr/bin/env python3
"""
Validate / deduplicate a single inventory Excel file.

Engine selection (Java-preferred, Python-fallback):
- If `demo-0.0.1-SNAPSHOT.jar` is found (auto-detected or via --jar), the
  original Spring Boot JAR `validate` mode is used.
- Otherwise the pure-Python implementation below runs: it groups data rows by
  the 5-key combo (外部商品编码 / 库位 / 供应商编码 / 仓库供应商编码 / 生产日期);
  when any key column is missing it degrades to whole-row grouping (same as the
  stats engine). For each unique key it writes one row whose 库存数量 is the SUM
  of the group's quantities, preserving every other column from the first
  occurrence.

Output in both cases: <name>_重复行合并.xlsx written next to the source file.
The original file is never modified.

Usage:
    python validate_merge.py <source.xlsx> [--overwrite] [--jar PATH] [--force-python]
"""

import argparse
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inv_io import (  # noqa: E402
    load_sheet,
    normalize_path,
    build_row_key,
    get_cell_decimal,
    insert_suffix,
    file_fingerprint,
    verify_inputs_untouched,
    write_workbook_preserving_format,
)


def _fmt_float(d: Decimal):
    """Convert a Decimal to float for Excel storage (lossless for typical qty/amt)."""
    return float(d)


def validate_merge(source_path, overwrite=False):
    p = normalize_path(source_path)
    if not p.exists():
        print(f"错误: 文件不存在: {p}", file=sys.stderr)
        return 1
    if p.suffix.lower() not in (".xlsx", ".xlsm"):
        print(f"错误: 不支持的格式: {p.suffix}", file=sys.stderr)
        return 1

    out_path = p.parent / insert_suffix(p.name, "_重复行合并")
    if out_path.exists() and not overwrite:
        print(f"跳过: 已存在合并文件 {out_path.name}（使用 --overwrite 覆盖）")
        return 0

    src_fp = file_fingerprint(p)  # 红线原则: 输入文件只读, 结束后必须未变
    wb, raw_headers, cleaned_headers, rows, qty_col, price_col, key_indices = load_sheet(p)

    # Optional 金额 column to keep internally consistent after merging quantity.
    amount_col = None
    for cand in ("金额", "金额总数量", "金额数量"):
        if cand in cleaned_headers:
            amount_col = cleaned_headers.index(cand)
            break

    groups = {}  # key -> {"rep": row, "sum": Decimal}
    for row in rows:
        if all(c.value is None or str(c.value).strip() == "" for c in row):
            continue
        key = build_row_key(row, key_indices, cleaned_headers)
        q = get_cell_decimal(row[qty_col]) if qty_col is not None and qty_col < len(row) else None
        if key not in groups:
            groups[key] = {"rep": row, "sum": Decimal("0")}
        if q is not None:
            groups[key]["sum"] += q

    wb.close()

    # Build merged rows as plain value-lists, then write them back into a copy
    # of the source workbook so the output keeps the original file's styling
    # (sheet name, header style, column widths, date number formats, etc.).
    merged_rows = []
    for key, g in groups.items():
        new_row = [c.value for c in g["rep"]]
        if qty_col is not None and qty_col < len(new_row):
            new_row[qty_col] = _fmt_float(g["sum"])
        if amount_col is not None and amount_col < len(new_row):
            price = None
            if price_col is not None and price_col < len(new_row):
                try:
                    price = Decimal(str(new_row[price_col]))
                except Exception:
                    price = None
            if price is not None:
                new_row[amount_col] = _fmt_float(g["sum"] * price)
        merged_rows.append(new_row)

    write_workbook_preserving_format(
        p, header_row_index=1, data_rows=merged_rows, out_path=out_path
    )
    merged_count = len(merged_rows)
    print(f"已生成去重合并文件: {out_path}")
    print(f"  原始数据行: {len([r for r in rows if not all(c.value is None or str(c.value).strip()=='' for c in r)])}"
          f"  ->  合并后唯一键行: {merged_count}")
    if not verify_inputs_untouched([(p, src_fp)], ["输入文件"]):
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description="去重合并单个库存 Excel（Java 优先，Python 兜底）")
    ap.add_argument("source", help="源 Excel 文件路径")
    ap.add_argument("--overwrite", action="store_true", help="若合并文件已存在则覆盖")
    ap.add_argument("--jar", default=None, help="显式指定 demo JAR 路径（强制走 Java）")
    ap.add_argument("--force-python", action="store_true",
                    help="即使找到 JAR 也强制使用 Python 实现")
    args = ap.parse_args()

    from java_bridge import find_jar, java_validate, find_unmerged_duplicate_rows

    if not args.force_python:
        jar = find_jar(args.jar, near_source=args.source)
        if jar:
            try:
                out = java_validate(jar, args.source, overwrite=args.overwrite)
                # JAR validate marks strict duplicates instead of merging them;
                # detect that and fall back to the Python merge for a clean file.
                marked, markers = find_unmerged_duplicate_rows(out)
                if marked > 0:
                    print(f"[Java] 警告: JAR 检测到 {marked} 行严格重复且未执行合并"
                          f"（如: {markers[0] if markers else '重复行校验不通过'}），"
                          f"回退 Python 引擎完成合并兜底", file=sys.stderr)
                    rc = validate_merge(args.source, overwrite=True)
                    print(f"[Python兜底] 已将 JAR 标记的 {marked} 行严格重复合并，生成: {out}")
                    sys.exit(rc)
                print(f"[Java] 已生成去重合并文件: {out}")
                sys.exit(0)
            except Exception as exc:
                if args.jar:  # explicit --jar: fail loud, don't hide the error
                    print(f"Java validate 失败: {exc}", file=sys.stderr)
                    sys.exit(1)
                print(f"警告: Java 执行失败，回退到 Python: {exc}", file=sys.stderr)

    sys.exit(validate_merge(args.source, overwrite=args.overwrite))


if __name__ == "__main__":
    main()
