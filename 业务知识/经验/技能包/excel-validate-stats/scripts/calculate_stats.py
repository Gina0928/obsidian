#!/usr/bin/env python3
"""
Calculate precise inventory totals from an Excel file (库存文件统计).

Enhanced capabilities:
- Excel 总行数 (含表头) 与 数据行数 (参与统计行数) 分别报告
- 重复行检测：基于关键列组合 (外部商品编码/库位/供应商编码/仓库供应商编码/生产日期)，
  找不到关键列时退化为整行值组合判断
- 库存总数量 / 金额总数量 使用 Decimal 无损精度计算
- 输出结构化报告 (stdout) 并自动保存同名 .txt 存档；支持 --json 输出便于表格化展示

Usage:
    python calculate_stats.py <excel_file_path> [--json]
"""

import json
import sys
from decimal import Decimal
from pathlib import Path

try:
    import openpyxl
except ImportError:
    print("错误: 需要安装 openpyxl 库，请运行: pip install openpyxl")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inv_io import file_fingerprint, verify_inputs_untouched  # noqa: E402


# 关键列（用于判定"重复行"），与 diff/dedup 逻辑保持一致
DUP_KEY_COLUMNS = [
    "外部商品编码",
    "库位",
    "供应商编码",
    "仓库供应商编码",
    "生产日期",
]


def _clean_header(h):
    """Clean a header cell: strip whitespace, remove '*', take first line."""
    if h is None:
        return ""
    s = str(h).strip()
    if s.startswith("*"):
        s = s[1:].strip()
    s = s.split("\n")[0].strip()
    return s


def find_column_index(headers, targets, fallback_keywords=None):
    """
    Find a column index by exact name first, then by keyword matching.

    Args:
        headers: List of header cell values (strings).
        targets: List of exact header names to try (in order).
        fallback_keywords: List of substrings to search for if exact match fails.

    Returns:
        Column index (0-based) if found, None otherwise.
    """
    if fallback_keywords is None:
        fallback_keywords = []

    cleaned = [_clean_header(h) for h in headers]

    # 1. Exact match
    for target in targets:
        for i, h in enumerate(cleaned):
            if h == target:
                return i

    # 2. Fallback keyword match
    for keyword in fallback_keywords:
        for i, h in enumerate(cleaned):
            if keyword in h:
                return i

    return None


def detect_key_indices(headers_clean):
    """Indices of the 5 dedup/diff key columns present in this file (exact, then substring)."""
    found = []
    for col_name in DUP_KEY_COLUMNS:
        idx = next((i for i, h in enumerate(headers_clean) if h == col_name), None)
        if idx is None:
            idx = next((i for i, h in enumerate(headers_clean) if col_name in h), None)
        if idx is not None:
            found.append(idx)
    return found


def get_cell_decimal(row, col_idx):
    """
    Get a cell value as Decimal, handling numeric, string, and None types.

    Returns:
        Decimal value, or None if the cell cannot be converted.
    """
    if col_idx is None or row is None:
        return None

    cell = row[col_idx] if col_idx < len(row) else None
    if cell is None or cell.value is None:
        return None

    val = cell.value
    try:
        if isinstance(val, (int, float)):
            # Convert via string to avoid float precision issues
            return Decimal(str(val))
        if isinstance(val, str):
            stripped = val.strip()
            if not stripped:
                return None
            return Decimal(stripped)
        if isinstance(val, Decimal):
            return val
    except Exception:
        return None

    return None


def _cell_key_value(cell):
    """Normalize a cell value into a hashable, comparable key fragment."""
    if cell is None or cell.value is None:
        return ""
    v = cell.value
    if isinstance(v, float):
        # Normalize float to avoid 1.0 vs 1.00000001 mismatches
        return str(Decimal(str(v)))
    return str(v).strip()


def analyze_inventory(file_path, header_row=1):
    """
    Full inventory analysis of one Excel file.

    Returns a dict with:
        file_name, excel_total_rows (含表头), data_row_count (参与统计行数),
        qty_col_name, price_col_name,
        total_quantity, total_amount (Decimal),
        dup_row_count (重复出现的行总数), dup_group_count (重复键组数),
        dup_examples (最多3组重复键示例),
        dup_columns_used (判定重复所用的列), missing_price_rows,
        no_qty_rows (无库存数量的行数), txt_path
    """
    wb = openpyxl.load_workbook(file_path, data_only=True)
    ws = wb.active

    # 表头
    headers = [cell.value for cell in ws[header_row]]
    if not headers or all(h is None or str(h).strip() == "" for h in headers):
        wb.close()
        raise ValueError(f"Excel 文件第{header_row}行缺少表头行")

    # 数量列 / 价格列
    qty_col = find_column_index(
        headers, targets=["库存数量"], fallback_keywords=["库存", "数量", "现存", "结存"]
    )
    if qty_col is None:
        wb.close()
        raise ValueError(f"无法找到库存数量列，表头列名: {[_clean_header(h) for h in headers if h]}")

    price_col = find_column_index(
        headers, targets=["进价"], fallback_keywords=["进价", "单价", "价格", "成本"]
    )

    qty_name = _clean_header(headers[qty_col]) if qty_col is not None else ""
    price_name = _clean_header(headers[price_col]) if price_col is not None else ""

    # 判定重复行的关键列（与 diff/dedup 一致）
    cleaned_headers = [_clean_header(h) for h in headers]
    dup_cols = detect_key_indices(cleaned_headers)

    excel_total_rows = ws.max_row  # 含表头
    total_quantity = Decimal("0")
    total_amount = Decimal("0")
    data_row_count = 0
    no_qty_rows = 0
    missing_price_rows = 0

    seen = {}          # key -> count
    dup_rows = 0       # 出现 >= 2 次的行总数
    dup_groups = 0     # 重复键组数
    dup_examples = []  # 示例

    # 迭代数据行
    for row in ws.iter_rows(min_row=header_row + 1, values_only=False):
        # 整行为空 -> 跳过（不计入任何统计）
        if all(c.value is None or str(c.value).strip() == "" for c in row):
            continue

        qty = get_cell_decimal(row, qty_col)
        price = get_cell_decimal(row, price_col) if price_col is not None else None

        # 重复判定：优先关键列组合，否则整行
        if dup_cols:
            key = tuple(_cell_key_value(row[i]) if i < len(row) else "" for i in dup_cols)
            key_used = ",".join(cleaned_headers[i] for i in dup_cols)
        else:
            key = tuple(_cell_key_value(c) for c in row)
            key_used = "整行(无关键列)"

        cnt = seen.get(key, 0) + 1
        seen[key] = cnt
        if cnt == 2:
            dup_groups += 1
            if len(dup_examples) < 3:
                dup_examples.append(
                    {cleaned_headers[i]: _cell_key_value(row[i]) for i in dup_cols[:5]} if dup_cols else {"整行": str(key)[:80]}
                )
        if cnt >= 2:
            dup_rows += 1

        if qty is not None:
            total_quantity += qty
            data_row_count += 1
            if price is not None:
                total_amount += qty * price
            else:
                missing_price_rows += 1
        else:
            no_qty_rows += 1

    wb.close()

    result = {
        "file_name": Path(file_path).name,
        "excel_total_rows": excel_total_rows,
        "data_row_count": data_row_count,
        "qty_col_name": qty_name,
        "price_col_name": price_name,
        "total_quantity": total_quantity,
        "total_amount": total_amount,
        "dup_row_count": dup_rows,
        "dup_group_count": dup_groups,
        "dup_examples": dup_examples,
        "dup_columns_used": key_used,
        "no_qty_rows": no_qty_rows,
        "missing_price_rows": missing_price_rows,
        "has_price_col": price_col is not None,
    }
    return result


def calculate_totals(file_path, header_row=1):
    """
    Backward-compatible wrapper: returns
    (total_quantity, total_amount, data_row_count, qty_col_name, price_col_name).
    """
    info = analyze_inventory(file_path, header_row=header_row)
    return (
        info["total_quantity"],
        info["total_amount"],
        info["data_row_count"],
        info["qty_col_name"],
        info["price_col_name"],
    )


def build_report_text(info):
    """Build the human-readable report text (also saved as .txt)."""
    qty = info["total_quantity"]
    amt = info["total_amount"]
    dup_state = "✓ 无重复行" if info["dup_row_count"] == 0 else f"✗ 存在 {info['dup_row_count']} 行重复"
    lines = []
    lines.append("=" * 62)
    lines.append(f"库存文件统计报告")
    lines.append("=" * 62)
    lines.append(f"文件:           {info['file_name']}")
    lines.append(f"Excel 总行数:   {info['excel_total_rows']}  (含表头)")
    lines.append(f"数据行数:       {info['data_row_count']}  (参与统计)")
    lines.append(f"重复行判定:     {dup_state}")
    lines.append(f"  重复行数:     {info['dup_row_count']}")
    lines.append(f"  重复组数:     {info['dup_group_count']}")
    lines.append(f"  判定列:       {info['dup_columns_used']}")
    if info["dup_examples"]:
        lines.append(f"  重复示例:     {info['dup_examples']}")
    lines.append("-" * 62)
    lines.append(f"库存总数量 ({info['qty_col_name']}):")
    lines.append(f"  {format(qty.normalize(), 'f')}")
    lines.append(f"  原始精度: {qty}")
    if info["has_price_col"]:
        lines.append("-" * 62)
        lines.append(f"金额总数量 (库存数量 × {info['price_col_name']}):")
        lines.append(f"  {format(amt.normalize(), 'f')}")
        lines.append(f"  原始精度: {amt}")
    else:
        lines.append("-" * 62)
        lines.append(f"金额总数量: 无进价列，不适用")
    lines.append("=" * 62)
    return "\n".join(lines)


def _dec_default(o):
    """JSON serializer for Decimal."""
    if isinstance(o, Decimal):
        return str(o)
    raise TypeError


def main():
    if len(sys.argv) < 2:
        print("用法: python calculate_stats.py <excel_file_path> [--json]")
        print("示例: python calculate_stats.py 1512-I_重复行合并.xlsx")
        sys.exit(1)

    as_json = "--json" in sys.argv[1:]
    file_path = Path(sys.argv[1])
    if not file_path.exists():
        print(f"错误: 文件不存在: {file_path}")
        sys.exit(1)

    if not file_path.suffix.lower() in (".xlsx", ".xlsm"):
        print(f"错误: 不支持的文件格式: {file_path.suffix}，仅支持 .xlsx / .xlsm")
        sys.exit(1)

    # 红线原则: 输入文件只读, 记录指纹, 结束后复核
    input_fp = file_fingerprint(file_path)

    try:
        info = analyze_inventory(file_path)
    except Exception as e:
        print(f"计算失败: {e}")
        sys.exit(1)

    if as_json:
        print(json.dumps(info, ensure_ascii=False, indent=2, default=_dec_default))
    else:
        output = build_report_text(info)
        print(output)

        # Auto-save txt alongside the Excel file
        txt_path = file_path.with_suffix(".txt")
        txt_path.write_text(output, encoding="utf-8")
        print(f"\n结果已保存至: {txt_path}")

    if not verify_inputs_untouched([(file_path, input_fp)], ["输入文件"]):
        sys.exit(3)


if __name__ == "__main__":
    main()
