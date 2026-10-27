#!/usr/bin/env python3
"""
Shared Excel I/O helpers for the excel-validate-stats skill.

All scripts in this skill import from here so that:
- Column detection (库存数量 / 进价 / 5-key dedup columns) is consistent
- Decimal-safe cell reading is centralized
- Git-Bash style paths (/d/foo.xlsx) are normalized to Windows absolute
  paths so the scripts work regardless of how the caller passes the path.

No Java / JAR dependency. Pure openpyxl + stdlib.
"""

import re
import sys
from decimal import Decimal
from pathlib import Path

try:
    import openpyxl
except ImportError:
    raise SystemExit("错误: 需要安装 openpyxl 库，请运行: pip install openpyxl")


# 与对比/去重逻辑一致的关键列（用于判定"重复行"与差异键）
DUP_KEY_COLUMNS = [
    "外部商品编码",
    "库位",
    "供应商编码",
    "仓库供应商编码",
    "生产日期",
]


def normalize_path(p) -> Path:
    """
    Accept any of:
      - Windows absolute  D:\\data\\x.xlsx
      - Forward-slash     D:/data/x.xlsx
      - Git-Bash style    /d/data/x.xlsx   ->  D:/data/x.xlsx
    Returns a resolved absolute Path.
    """
    s = str(p).strip()
    # Git-Bash style: leading /<drive-letter>/
    m = re.match(r"^/([a-zA-Z])/(.*)$", s)
    if m:
        s = f"{m.group(1).upper()}:/{m.group(2)}"
    return Path(s)


def clean_header(h) -> str:
    """Clean a header cell: strip, drop leading '*', take first line."""
    if h is None:
        return ""
    s = str(h).strip()
    if s.startswith("*"):
        s = s[1:].strip()
    return s.split("\n")[0].strip()


def find_column(headers_clean, targets, fallback_keywords=None):
    """
    Find a column index by exact name first, then by keyword substring.
    Returns 0-based index or None.
    """
    if fallback_keywords is None:
        fallback_keywords = []
    for t in targets:
        for i, h in enumerate(headers_clean):
            if h == t:
                return i
    for kw in fallback_keywords:
        for i, h in enumerate(headers_clean):
            if kw in h:
                return i
    return None


def detect_qty_price_cols(headers_clean):
    """Return (qty_col_index, price_col_index) using exact-then-keyword fallback."""
    qty = find_column(headers_clean, ["库存数量"], ["库存", "数量", "现存", "结存"])
    price = find_column(headers_clean, ["进价"], ["进价", "单价", "价格", "成本"])
    return qty, price


def detect_key_indices(headers_clean):
    """
    Indices of the 5 dedup/diff key columns present in this file.

    Uses exact match first, then a substring fallback so headers with extra
    descriptive text (e.g. "外部商品编码 1.支持外部商家的商品编码 ...") still
    resolve to the right column instead of silently degrading to whole-row keys.
    """
    found = []
    for col_name in DUP_KEY_COLUMNS:
        # exact match
        idx = next((i for i, h in enumerate(headers_clean) if h == col_name), None)
        if idx is None:
            # substring fallback (first header containing the key name)
            idx = next((i for i, h in enumerate(headers_clean) if col_name in h), None)
        if idx is not None:
            found.append(idx)
    return found


def get_cell_decimal(cell):
    """Return a cell's value as Decimal, or None if absent/non-numeric."""
    if cell is None or cell.value is None:
        return None
    v = cell.value
    try:
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return Decimal(str(v))
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            return Decimal(s)
        if isinstance(v, Decimal):
            return v
    except Exception:
        return None
    return None


def cell_key_value(cell):
    """Normalize a cell into a comparable string fragment for key building."""
    if cell is None or cell.value is None:
        return ""
    v = cell.value
    if isinstance(v, float):
        return str(Decimal(str(v)))
    return str(v).strip()


def build_row_key(row, key_indices, cleaned_headers):
    """
    Build the dedup/diff key for a row.
    Uses the detected key columns when present; otherwise falls back to the
    full row (matching the stats engine's degradation behavior).
    """
    if key_indices:
        return tuple(
            cell_key_value(row[i]) if i < len(row) else "" for i in key_indices
        )
    return tuple(cell_key_value(c) for c in row)


def load_sheet(path, header_row=1):
    """
    Load an Excel file for row-level processing.

    Returns a tuple:
        (workbook, raw_headers, cleaned_headers, rows, qty_col,
         price_col, key_indices)
    where `rows` is a list of openpyxl cell-row tuples (min_row = header_row+1).
    """
    p = normalize_path(path)
    wb = openpyxl.load_workbook(p, data_only=True)
    ws = wb.active
    raw_headers = [c.value for c in ws[header_row]]
    cleaned_headers = [clean_header(h) for h in raw_headers]
    rows = list(ws.iter_rows(min_row=header_row + 1, values_only=False))
    qty_col, price_col = detect_qty_price_cols(cleaned_headers)
    key_indices = detect_key_indices(cleaned_headers)
    return wb, raw_headers, cleaned_headers, rows, qty_col, price_col, key_indices


def insert_suffix(filename: str, suffix: str) -> str:
    """Insert suffix before the last dot: '1518-I.xlsx' + '_差异' -> '1518-I_差异.xlsx'."""
    dot = filename.rfind(".")
    if dot > 0:
        return filename[:dot] + suffix + filename[dot:]
    return filename + suffix


# ---------------------------------------------------------------------------
# 红线原则：输入文件只读校验（GOLDEN RULE）
#
# 任何工作流都不得修改用户提供的输入 Excel。所有产物（_重复行合并.xlsx、
# _差异.xlsx、同名 .txt 存档）都是新建文件。为把"输入未被修改"变成每次
# 执行都可验证的事实，脚本在入口记录输入文件的指纹（大小 + 修改时间），
# 执行结束后复核并在 stdout 打印 "输入文件只读确认 ✓"。
# ---------------------------------------------------------------------------

def file_fingerprint(p) -> tuple:
    """Return (size, mtime_ns) of a file — used to prove inputs were never modified."""
    p = normalize_path(p)
    st = p.stat()
    return (st.st_size, st.st_mtime_ns)


def verify_inputs_untouched(snapshots, labels):
    """
    Re-check input file fingerprints and print one confirmation line per file.

    Args:
        snapshots: list of (path, (size, mtime_ns)) taken BEFORE processing.
        labels:    list of human-readable labels, same length as snapshots.

    Returns:
        True if every input is unchanged; False otherwise (caller must abort
        with a non-zero exit code — an input being modified is never acceptable).
    """
    ok = True
    for (p, before), label in zip(snapshots, labels):
        try:
            after = file_fingerprint(p)
        except OSError:
            ok = False
            print(f"!! 输入文件只读校验失败: 无法读取 {p}", file=sys.stderr)
            continue
        if after != before:
            ok = False
            print(f"!! 输入文件只读校验失败: {label} 已被修改: {p}", file=sys.stderr)
        else:
            print(f"  输入文件只读确认 ✓ {label}: {Path(p).name} (大小/修改时间未变)")
    if not ok:
        print("!! 校验失败: 检测到输入文件被意外修改，立即终止并检查原因！", file=sys.stderr)
    return ok


# ---------------------------------------------------------------------------
# 输出格式一致性：Python 兜底引擎生成的 xlsx 必须与"原文件"样式/格式一致
#
# 早期实现用 openpyxl.Workbook() 新建空白簿并只写值，导致：工作表名变成
# 默认的 "Sheet"、表头失去原文件的字体/字号/加粗/填充、日期列数字格式改变、
# 列宽等全部丢失，和 JAR 产物（JAR 直接在原文件结构上改写）明显不一致。
#
# 解决：以"源文件"为骨架 —— 加载源工作簿（data_only=False 以保留样式），
# 保留其表头行与所有工作表级样式（工作表名、列宽、冻结窗格、列数字格式等），
# 仅清空并重写为新的数据行，且每个输出单元格都从源文件首个数据行对应列
# 拷贝样式（字体/填充/边框/对齐/数字格式/保护）。这样既保证数值正确，又
# 让产物在视觉与格式上与原始文件完全一致。源文件只被读取，输出另存为新文件，
# 红线原则（输入只读）不受影响。
# ---------------------------------------------------------------------------

def copy_cell_style(src_cell, dst_cell):
    """Copy a cell's visual style onto another cell (deep-copied, no sharing)."""
    from copy import copy
    dst_cell.font = copy(src_cell.font)
    dst_cell.fill = copy(src_cell.fill)
    dst_cell.border = copy(src_cell.border)
    dst_cell.alignment = copy(src_cell.alignment)
    dst_cell.number_format = src_cell.number_format
    dst_cell.protection = copy(src_cell.protection)


def write_workbook_preserving_format(src_path, header_row_index,
                                     data_rows, out_path, sheet_title=None):
    """
    Build ``out_path`` from ``src_path``'s workbook, keeping every visual style
    of the original file and only replacing the data rows.

    What is preserved automatically:
      * Sheet name (e.g. ``Sheet1``) — no longer the openpyxl default ``Sheet``
      * Column widths and any column-level number formats
      * The header row (descriptive ``*外部商品编码\\n...`` text + its font /
        size / bold / fill / alignment)
      * Per-cell data styling, especially the date number format on date columns
      * Freeze panes and other worksheet-level attributes

    Args:
        src_path:         workbook to inherit formatting from (read-only; we save
                          to a *different* path, so the source is never modified).
        header_row_index: 1-based last header row; data starts at
                          ``header_row_index + 1``. For these inventory files it is 1.
        data_rows:        list of rows; each row is a list of cell values in the
                          same column order as the source. Rows longer than the
                          source column count are truncated, shorter ones padded
                          with ``None``.
        out_path:         destination path (must differ from ``src_path``).
        sheet_title:      optional sheet rename; usually omitted to keep the
                          original sheet name.

    Returns:
        The ``out_path`` (``Path``).
    """
    from copy import copy
    src = openpyxl.load_workbook(normalize_path(src_path), data_only=False)
    ws = src.active
    ncols = ws.max_column

    # Capture the style template from the first data row (or the header row if
    # the source has no data rows yet) BEFORE deleting anything.
    trow = header_row_index + 1
    templates = []
    for ci in range(1, ncols + 1):
        cell = ws.cell(trow, ci) if trow <= ws.max_row else ws.cell(header_row_index, ci)
        templates.append({
            "font": copy(cell.font),
            "fill": copy(cell.fill),
            "border": copy(cell.border),
            "alignment": copy(cell.alignment),
            "number_format": cell.number_format,
            "protection": copy(cell.protection),
        })

    # Remove existing data rows (keep the header row(s)).
    if ws.max_row > header_row_index:
        ws.delete_rows(header_row_index + 1, ws.max_row - header_row_index)

    # Write the new data rows, each cell inheriting the template style so that
    # number formats (e.g. date format) and styling stay consistent.
    r = header_row_index + 1
    for row_vals in data_rows:
        vals = list(row_vals)
        if len(vals) < ncols:
            vals = vals + [None] * (ncols - len(vals))
        elif len(vals) > ncols:
            vals = vals[:ncols]
        for ci in range(1, ncols + 1):
            cell = ws.cell(r, ci)
            cell.value = vals[ci - 1]
            t = templates[ci - 1]
            cell.font = t["font"]
            cell.fill = t["fill"]
            cell.border = t["border"]
            cell.alignment = t["alignment"]
            cell.number_format = t["number_format"]
            cell.protection = t["protection"]
        r += 1

    if sheet_title:
        ws.title = sheet_title
    src.save(normalize_path(out_path))
    return normalize_path(out_path)
