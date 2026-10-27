#!/usr/bin/env python3
"""Deterministic report renderer for inventory-init-validate.

Takes a workflow ID, parameters, and query result rows, then outputs a
four-section Markdown report per the skill's Result Report Specification:

  1. 执行概览 (Execution Overview)
  2. 确定性指标 (Deterministic Metrics)
  3. 明细数据 (Detail Data)
  4. 结论与建议 (Conclusion & Next Steps)

This script is OPTIONAL — the model can also compute metrics and hand-write the
report. The spec in SKILL.md is authoritative; this script is a convenience tool
that guarantees the deterministic-metrics section is computed from raw rows
rather than paraphrased.

Usage:
  # result as inline JSON
  render_report.py --workflow A \
    --params '{"wh_id": 1604}' \
    --source mcp__mysql_wms_prod \
    --result '[{"total_qty": 12345.678, "total_amount": 98765.43, "lot_rows": 4321, "distinct_sku_count": 1234}]'

  # result from a file
  render_report.py --workflow C \
    --params '{"wh_id": 1102, "init_header_id": 508}' \
    --source db_connect.py \
    --result-file result.json \
    --extra '{"failed_rows": 0}'

  # pipe-delimited result (from db_connect.py stdout) via stdin
  db_connect.py --server mysql_wms_prod --sql "..." | \
    render_report.py --workflow A --params '{"wh_id":1604}' --source db_connect.py --stdin-pipe

The --result JSON must be an array of row objects (column name -> value).
For summary workflows (A, B, E2) it is typically a single-row array.
For detail workflows (C, D, E1) it is the full result set; this script
computes the summary metrics from it.
"""
import argparse
import json
import sys
from datetime import datetime


def to_num(v):
    """Best-effort numeric coercion; returns None if not convertible.

    For floats, returns the float (does NOT truncate via int()). For integer
    strings, returns int. This preserves decimal precision for amounts/qty.
    """
    if v is None or v == "" or v == "None":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    # Try int first (only if no decimal point)
    if "." not in s and "e" not in s.lower():
        try:
            return int(s)
        except ValueError:
            pass
    try:
        return float(s)
    except ValueError:
        return None


def fmt_num(v):
    """Format a number: ints without trailing .0, floats keep their precision.

    For string inputs that are not numeric, return the string as-is.
    Trailing zeros from float repr are stripped (e.g. 98765.4300 -> 98765.43)
    but meaningful decimals are preserved (e.g. 12345.678 -> 12345.678).
    """
    if v is None:
        return ""
    if isinstance(v, str):
        n = to_num(v)
        if n is None:
            return v  # non-numeric string, return as-is (e.g. error_msg)
        v = n
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        # Strip trailing zeros from repr without losing precision
        s = repr(v)
        # Handle float repr like 98765.43
        return s
    if isinstance(v, int):
        return str(v)
    return str(v)


def parse_pipe_delim(text):
    """Parse pipe-delimited text (first line = headers) into list of dicts."""
    lines = [l.rstrip("\n\r") for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return []
    headers = [h.strip() for h in lines[0].split("|")]
    rows = []
    for line in lines[1:]:
        parts = [p.strip() for p in line.split("|")]
        row = {}
        for i, h in enumerate(headers):
            row[h] = parts[i] if i < len(parts) else ""
        rows.append(row)
    return rows


def metric_row(key, value, mtype, note):
    return f"| {key} | {fmt_num(value)} | {mtype} | {note} |"


def overview_rows(workflow, params, source, status="✅ 成功"):
    """Build the Section 1 table rows."""
    wf_names = {
        "A": "A — 首次初始化验证",
        "B": "B — 增量初始化验证",
        "C": "C — 首次初始化差异定位",
        "D": "D — 增量初始化差异定位",
        "E": "E — 失败明细检查",
    }
    rows = []
    rows.append(f"| 工作流 | {wf_names.get(workflow, workflow)} |")
    if "wh_id" in params:
        rows.append(f"| 仓库 ID (wh_id) | {params['wh_id']} |")
    if "init_header_id" in params:
        rows.append(f"| init_header_id | {params['init_header_id']} |")
    if "create_date" in params:
        rows.append(f"| create_date | {params['create_date']} |")
    if "stk_doc_type" in params:
        rows.append(f"| stk_doc_type | {params['stk_doc_type']} |")
    rows.append(f"| 数据源 | {source} |")
    rows.append(f"| 执行时间 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |")
    rows.append(f"| 执行状态 | {status} |")
    return rows


# ---- Per-workflow metric computation ----

def metrics_A(rows, extra):
    """Workflow A: single-row summary. Metrics come directly from the row."""
    r = rows[0] if rows else {}
    return [
        metric_row("total_qty", r.get("total_qty", 0), "decimal", "库存总数量 (qty + qty_hold)"),
        metric_row("total_amount", r.get("total_amount", 0), "decimal", "库存总金额"),
        metric_row("lot_rows", r.get("lot_rows", 0), "int", "批次行数"),
        metric_row("distinct_sku_count", r.get("distinct_sku_count", 0), "int", "涉及 SKU 数"),
    ]


def metrics_B(rows, extra):
    r = rows[0] if rows else {}
    return [
        metric_row("net_qty", r.get("net_qty", 0), "decimal", "库存数量净额 (入库 + 出库)"),
        metric_row("inbound_qty", r.get("inbound_qty", 0), "decimal", "入库数量合计 (doc_type=11)"),
        metric_row("outbound_qty", r.get("outbound_qty", 0), "decimal", "出库数量合计 (doc_type=23, 已为负)"),
        metric_row("trans_rows", r.get("trans_rows", 0), "int", "流水行数"),
        metric_row("distinct_sku_count", r.get("distinct_sku_count", 0), "int", "涉及 SKU 数"),
    ]


def metrics_C(rows, extra):
    """Workflow C: detail rows. Compute summary from the result set."""
    diff_count = len(rows)
    total_qty_diff = sum(to_num(r.get("qty_diff")) or 0 for r in rows)
    total_amt_diff = sum(to_num(r.get("amount_diff")) or 0 for r in rows)
    init_only = sum(1 for r in rows if to_num(r.get("lot_qty")) in (0, None))
    max_abs = max((abs(to_num(r.get("qty_diff")) or 0) for r in rows), default=0)
    failed = extra.get("failed_rows", "0 (E 未执行)") if extra else "0 (E 未执行)"
    return [
        metric_row("diff_sku_count", diff_count, "int", "差异 SKU 数"),
        metric_row("total_qty_diff", total_qty_diff, "decimal", "差异数量合计"),
        metric_row("total_amount_diff", total_amt_diff, "decimal", "差异金额合计"),
        metric_row("init_only_count", init_only, "int", "仅初始化有、批次缺失的 SKU 数"),
        metric_row("max_abs_qty_diff", max_abs, "decimal", "最大绝对差异数量"),
        metric_row("failed_rows", failed, "int", "失败行数 (from E)"),
    ]


def metrics_D(rows, extra):
    """Workflow D: detail rows. Compute summary from the result set."""
    diff_count = len(rows)
    total_recon = sum(to_num(r.get("recon_diff")) or 0 for r in rows)
    pos_count = sum(1 for r in rows if (to_num(r.get("recon_diff")) or 0) > 0)
    neg_count = sum(1 for r in rows if (to_num(r.get("recon_diff")) or 0) < 0)
    max_abs = max((abs(to_num(r.get("recon_diff")) or 0) for r in rows), default=0)
    failed = extra.get("failed_rows", "0 (E 未执行)") if extra else "0 (E 未执行)"
    return [
        metric_row("diff_sku_count", diff_count, "int", "差异 SKU 数"),
        metric_row("total_recon_diff", total_recon, "decimal", "对账差异合计"),
        metric_row("positive_diff_count", pos_count, "int", "正差异 SKU 数 (init > out)"),
        metric_row("negative_diff_count", neg_count, "int", "负差异 SKU 数 (out > init)"),
        metric_row("max_abs_recon_diff", max_abs, "decimal", "最大绝对对账差异"),
        metric_row("failed_rows", failed, "int", "失败行数 (from E)"),
    ]


def metrics_E(rows, extra):
    """Workflow E: rows = E1 detail, extra = E2+E4 summary."""
    e2 = (extra or {}).get("e2", {})
    e4 = (extra or {}).get("e4", [])
    failed_rows = e2.get("failed_rows", 0)
    total_qty = e2.get("total_failed_qty", 0)
    total_amt = e2.get("total_failed_amount", 0)
    distinct_err = len(e4)
    top_msg = e4[0]["error_msg"] if e4 else "(无)"
    top_cnt = e4[0]["count"] if e4 else 0
    return [
        metric_row("failed_rows", failed_rows, "int", "失败行数"),
        metric_row("total_failed_qty", total_qty, "decimal", "失败库存总数量"),
        metric_row("total_failed_amount", total_amt, "decimal", "失败金额"),
        metric_row("distinct_error_count", distinct_err, "int", "失败原因种类数"),
        metric_row("top_error_msg", top_msg, "string", "出现次数最多的失败原因"),
        metric_row("top_error_count", top_cnt, "int", "该原因出现次数"),
    ]


METRIC_FNS = {
    "A": metrics_A,
    "B": metrics_B,
    "C": metrics_C,
    "D": metrics_D,
    "E": metrics_E,
}


def detail_table(workflow, rows):
    """Build Section 3 detail table, or summary-only note."""
    summary_only = {"A", "B"}
    if workflow in summary_only:
        return "本工作流为汇总查询，无明细行。"

    if not rows:
        return "（查询返回 0 行）"

    # Column display maps per workflow
    col_maps = {
        "C": ["sku_id", "init_qty", "init_amount", "lot_qty", "lot_amount", "qty_diff", "amount_diff", "source_sku_id"],
        "D": ["sku_id", "source_sku_id", "init_qty", "out_qty", "recon_diff", "abs_diff"],
        "E": ["source_sku_id", "sku_name", "loc_code", "qty", "in_price", "amount", "status", "error_msg"],
    }
    cols = col_maps.get(workflow, list(rows[0].keys()))
    header_cn = {
        "C": "| sku_id | 初始化数量 | 初始化金额 | 实际批次数量 | 实际批次金额 | 数量差异 | 金额差异 | 商品编码 |",
        "D": "| sku_id | 商品编码 | 初始化数量 | 出库数量 | 对账差异 | |init|−|out| |",
        "E": "| 商品编码 | 商品名称 | 库位编码 | 库存数量 | 进价 | 金额 | status | 失败原因 |",
    }
    sep = "|" + "|".join(["--------"] * len(cols)) + "|"

    lines = [header_cn.get(workflow, "| " + " | ".join(cols) + " |"), sep]
    truncated = False
    total = len(rows)
    display_rows = rows[:50]
    if total > 50:
        truncated = True

    for r in display_rows:
        vals = [fmt_num(r.get(c, "")) for c in cols]
        lines.append("| " + " | ".join(vals) + " |")

    if truncated:
        lines.append(f"\n（共 {total} 行，仅显示前 50 行，已截断）")
    return "\n".join(lines)


def conclusion(workflow, rows, extra):
    """Build Section 4 conclusion text."""
    if workflow == "A":
        r = rows[0] if rows else {}
        return (
            f"首次初始化库存共 {fmt_num(r.get('total_qty', 0))} 件 / "
            f"{fmt_num(r.get('total_amount', 0))} 元，覆盖 "
            f"{fmt_num(r.get('distinct_sku_count', 0))} 个 SKU。"
            "可进入 Workflow C 做差异定位（如用户报告数量对不上）。"
        )
    if workflow == "B":
        r = rows[0] if rows else {}
        net = to_num(r.get("net_qty")) or 0
        if net == 0 and (to_num(r.get("trans_rows")) or 0) == 0:
            return "未找到匹配流水，所有指标为 0。请检查 create_date / business_code 过滤条件。"
        return (
            f"增量初始化净库存 {fmt_num(net)}（入库 {fmt_num(r.get('inbound_qty', 0))}，"
            f"出库 {fmt_num(r.get('outbound_qty', 0))}），"
            f"覆盖 {fmt_num(r.get('distinct_sku_count', 0))} 个 SKU / "
            f"{fmt_num(r.get('trans_rows', 0))} 条流水。"
            "可进入 Workflow D 做差异定位（如用户报告数量对不上）。"
        )
    if workflow == "C":
        n = len(rows)
        if n == 0:
            return "首次初始化与批次数据一致，无数值差异。"
        max_abs = max((abs(to_num(r.get("qty_diff")) or 0) for r in rows), default=0)
        failed = (extra or {}).get("failed_rows", 0)
        note = f"（其中 E 报告 {failed} 条失败行已单独列出）" if failed else ""
        return (
            f"发现 {n} 个 SKU 数量/金额不一致{note}，最大绝对差异数量 {fmt_num(max_abs)}。"
            "建议按 |qty_diff| 降序逐个排查根因（批次缺失 / qty=0 / 数据录入错误）。"
        )
    if workflow == "D":
        n = len(rows)
        if n == 0:
            return "增量初始化与出库流水完全对账一致，无差异。"
        pos = sum(1 for r in rows if (to_num(r.get("recon_diff")) or 0) > 0)
        neg = n - pos
        max_abs = max((abs(to_num(r.get("recon_diff")) or 0) for r in rows), default=0)
        failed = (extra or {}).get("failed_rows", 0)
        note = f"（其中 E 报告 {failed} 条失败行已单独列出，不计为对账差异）" if failed else ""
        return (
            f"发现 {n} 个 SKU 对账不一致（正差异 {pos} / 负差异 {neg}）{note}，"
            f"最大绝对对账差异 {fmt_num(max_abs)}。"
            "建议按 |recon_diff| 降序优先排查 Top 行。"
        )
    if workflow == "E":
        e2 = (extra or {}).get("e2", {})
        fr = e2.get("failed_rows", 0)
        if fr == 0:
            return "未发现失败明细（status=91），可继续 C/D 差异定位。"
        top = (extra or {}).get("e4", [{}])[0]
        return (
            f"共 {fr} 条失败行，失败数量 {fmt_num(e2.get('total_failed_qty', 0))} / "
            f"金额 {fmt_num(e2.get('total_failed_amount', 0))}。"
            f"首要原因：{top.get('error_msg', '(空)')}（{top.get('count', 0)} 次）。"
            "失败行需单独处理，不得计入 C/D 对账差异。"
        )
    return ""


def render(workflow, params, source, rows, extra, status="✅ 成功"):
    out = []
    out.append(f"### 执行报告 — Workflow {workflow}\n")
    # Section 1
    out.append("#### 执行概览\n")
    out.append("| 项目 | 值 |")
    out.append("|------|-----|")
    out.extend(overview_rows(workflow, params, source, status))
    out.append("")
    # Section 2
    out.append("#### 确定性指标\n")
    out.append("| 指标名 (key) | 值 (value) | 类型 (type) | 说明 (note) |")
    out.append("|--------------|-----------|-------------|-------------|")
    fn = METRIC_FNS.get(workflow)
    if fn:
        out.extend(fn(rows, extra))
    out.append("")
    # Section 3
    out.append("#### 明细数据\n")
    out.append(detail_table(workflow, rows))
    out.append("")
    # Section 4
    out.append("#### 结论与建议\n")
    out.append(conclusion(workflow, rows, extra))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Render inventory-init-validate report")
    ap.add_argument("--workflow", required=True, choices=["A", "B", "C", "D", "E"])
    ap.add_argument("--params", default="{}", help="JSON string of workflow parameters")
    ap.add_argument("--source", default="mcp__mysql_wms_prod", help="Data source label")
    ap.add_argument("--result", help="Query result as inline JSON array of row objects")
    ap.add_argument("--result-file", help="File containing result JSON")
    ap.add_argument("--extra", default="{}", help="JSON: extra data (e.g. failed_rows, e2, e4)")
    ap.add_argument("--stdin-pipe", action="store_true", help="Read pipe-delimited result from stdin")
    ap.add_argument("--status", default="✅ 成功")
    args = ap.parse_args()

    params = json.loads(args.params) if args.params else {}
    extra = json.loads(args.extra) if args.extra else {}

    if args.stdin_pipe:
        text = sys.stdin.read()
        rows = parse_pipe_delim(text)
    elif args.result_file:
        with open(args.result_file, encoding="utf-8") as f:
            rows = json.load(f)
    elif args.result:
        rows = json.loads(args.result)
    else:
        rows = []

    if not isinstance(rows, list):
        rows = [rows]

    print(render(args.workflow, params, args.source, rows, extra, args.status))


if __name__ == "__main__":
    main()
