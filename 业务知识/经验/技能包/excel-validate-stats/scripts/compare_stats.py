#!/usr/bin/env python3
"""
Compare two Excel inventory files — stats only, no Java dependency.

Reads two Excel files, computes 库存总数量 / 金额总数量 (Decimal), plus
Excel 总行数 / 数据行数 / 重复行信息 for each, saves a same-name .txt file
alongside each Excel, and prints a side-by-side summary report with deltas.

Usage:
    python compare_stats.py <source.xlsx> <compare.xlsx>
"""

import sys
from decimal import Decimal
from pathlib import Path

# Pull in calculate_stats from the same scripts/ directory
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from calculate_stats import analyze_inventory, build_report_text  # noqa: E402
from inv_io import file_fingerprint, verify_inputs_untouched  # noqa: E402


def fmt_dec(d: Decimal) -> str:
    """Format a Decimal for display — no scientific notation, keep precision."""
    return format(d.normalize(), 'f')


def dup_label(info) -> str:
    """Short duplicate-status label for a file."""
    if info["dup_row_count"] == 0:
        return "无重复行"
    return f"重复 {info['dup_row_count']} 行 / {info['dup_group_count']} 组"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(source_path: Path, compare_path: Path) -> int:
    """
    Compute stats for two Excel files, save TXT files, and print a
    side-by-side comparison report.

    Returns 0 on success, non-zero on failure.
    """

    # ---- 0. Resolve to absolute paths ----------------------------------------
    source_path = source_path.resolve()
    compare_path = compare_path.resolve()

    # 红线原则: 对比场景下两个输入文件都只读; 记录指纹, 结束前复核
    input_snapshots = [
        (source_path, file_fingerprint(source_path)),
        (compare_path, file_fingerprint(compare_path)),
    ]
    input_labels = ["文件A(源文件)", "文件B(对比文件)"]

    # ---- 1. Validate inputs --------------------------------------------------
    if not source_path.exists():
        print(f"错误: 源文件不存在: {source_path}", file=sys.stderr)
        return 1
    if not source_path.suffix.lower() in (".xlsx", ".xlsm"):
        print(f"错误: 不支持的源文件格式: {source_path.suffix}", file=sys.stderr)
        return 1
    if not compare_path.exists():
        print(f"错误: 对比文件不存在: {compare_path}", file=sys.stderr)
        return 1
    if not compare_path.suffix.lower() in (".xlsx", ".xlsm"):
        print(f"错误: 不支持的对比文件格式: {compare_path.suffix}", file=sys.stderr)
        return 1

    # ---- 2. Analyze both files -----------------------------------------------
    print("正在分析统计数据...\n")

    try:
        src = analyze_inventory(source_path)
        print(f"  ✓ {src['file_name']}: 数量={fmt_dec(src['total_quantity'])}, 金额={fmt_dec(src['total_amount'])}, {dup_label(src)}")
    except Exception as exc:
        print(f"  ✗ {source_path.name}: 统计失败 - {exc}", file=sys.stderr)
        return 2

    try:
        cmp = analyze_inventory(compare_path)
        print(f"  ✓ {cmp['file_name']}: 数量={fmt_dec(cmp['total_quantity'])}, 金额={fmt_dec(cmp['total_amount'])}, {dup_label(cmp)}")
    except Exception as exc:
        print(f"  ✗ {compare_path.name}: 统计失败 - {exc}", file=sys.stderr)
        return 2

    # ---- 3. Save same-name TXT files alongside each Excel --------------------
    src_txt = source_path.with_suffix(".txt")
    src_txt.write_text(build_report_text(src), encoding="utf-8")
    print(f"  📄 {src_txt.name}")

    cmp_txt = compare_path.with_suffix(".txt")
    cmp_txt.write_text(build_report_text(cmp), encoding="utf-8")
    print(f"  📄 {cmp_txt.name}")

    # ---- 4. Compute deltas ---------------------------------------------------
    delta_qty = src["total_quantity"] - cmp["total_quantity"]
    delta_amt = src["total_amount"] - cmp["total_amount"]

    # ---- 5. Print side-by-side summary report --------------------------------
    print()
    print("=" * 62)
    print("库存对比报告")
    print("=" * 62)
    print()
    print(f"文件A: {src['file_name']}")
    print(f"  完整路径:      {source_path}")
    print(f"  Excel 总行数:  {src['excel_total_rows']}  (含表头)")
    print(f"  数据行数:      {src['data_row_count']}")
    print(f"  重复行:        {dup_label(src)}")
    print(f"  库存总数量:    {fmt_dec(src['total_quantity'])}")
    print(f"  金额总数量:    {fmt_dec(src['total_amount'])}")
    print()
    print(f"文件B: {cmp['file_name']}")
    print(f"  完整路径:      {compare_path}")
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
    print("-" * 62)
    print("输入文件只读校验:")
    if not verify_inputs_untouched(input_snapshots, input_labels):
        print("=" * 62)
        return 3
    print("=" * 62)

    return 0


def main() -> None:
    if len(sys.argv) < 3:
        print("用法: python compare_stats.py <源文件.xlsx> <对比文件.xlsx>")
        print("示例: python compare_stats.py D:/data/1518-I.xlsx D:/data/1518-II.xlsx")
        print()
        print("两个文件均需使用绝对路径。")
        print("脚本会为每个 Excel 生成同名的 .txt 统计文件，")
        print("并打印并排对比报告（含差额计算）。")
        sys.exit(1)

    source_path = Path(sys.argv[1])
    compare_path = Path(sys.argv[2])

    exit_code = run(source_path, compare_path)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
