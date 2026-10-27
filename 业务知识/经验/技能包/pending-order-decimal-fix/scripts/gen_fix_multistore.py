#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
挂单计件小数修复 —— 多门店批量 UPDATE 生成器（带整除闸门，复用 gen_fix_sql.is_divisible）

读取：
  --coeff  coeff.csv       列: wh,source_sku_id,coeff
  --pos    pos_rows.json   列: id,wh_id,source_sku_id,qty
  --asn    asn_rows.json   列: id,wh_id,sku_id,expt_qty   (sku_id 为 md_sku.id)
  --map    md_sku.id -> source_sku_id 的反查映射（硬编码自本次 md_sku 查询）

输出：
  --out  SQL 文件（默认 fix_all.sql），含幂等保护条件的 UPDATE + 整除核对结论 + 覆盖率。
  --manifest CSV 明细（同目录，便于复核）。

安全闸门（沿用 gen_fix_sql）：
  1. 已整数行（FLOOR(qty)==qty）：跳过，绝不除系数（避免 1.000 -> 0.909）。
  2. 不能整除行（qty 非系数整数倍）：进人工复核，不进 UPDATE。
  3. 缺系数行：进人工复核。
仅「小数 且 能被系数整除」的行生成 UPDATE；本脚本绝不执行 DML。
"""
import argparse
import csv
import json
import os
import sys
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 34

# md_sku.id -> source_sku_id（自各批次生产库 md_sku 查询累计；新增商品请在此补映射）
SKU2SRC = {
    "55628": "671447", "64313": "427185", "64758": "670923", "66514": "462595",
    "66718": "492918", "68245": "808426", "71145": "846307", "71268": "609704", "72024": "808423",
    "73200": "52316", "76761": "314492", "84196": "759798", "90278": "837884", "95307": "485119", "95350": "822932",
    "95671": "808424", "101024": "822931", "106189": "435995", "106622": "715365", "106679": "727207",
    "106669": "691870", "106681": "516589", "106697": "727205", "106699": "855753", "120568": "867324",
    "136812": "868400", "137796": "739078",
    "105782": "404897", "106628": "736103", "106674": "855752", "106729": "736104",
    "90256": "808995", "159507": "889054", "66867": "846895", "106724": "727195",
    "93282": "855737",
    "91754": "262073", "106235": "436005",
    "112558": "821649", "112565": "821644", "112588": "821687",
    "82541": "516591", "106248": "561519", "112570": "821654", "112581": "821668",
    "112563": "821674", "112577": "821682", "112600": "821671", "112603": "821686",
    "112607": "821645",
    "106277": "561520",
    "99266": "730671",
    "88393": "402611",
    "112620": "821683", "112628": "821652", "112649": "821650", "112650": "821651",
    "112674": "821648",     "122759": "869677", "168284": "892716", "168286": "892711", "168797": "892715",
    "95852": "732724",
    "112562": "821678",
}

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_fix_sql as g  # 复用 is_divisible / TOL


def load_coeff(path):
    coeff = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            wh = str(row["wh"]).strip()
            src = str(row["source_sku_id"]).strip()
            coeff[f"{wh}:{src}"] = Decimal(str(row["coeff"]).strip())
    return coeff


def gate_pos(row, coeff):
    rid = row["id"]
    wh = str(row["wh_id"])
    src = str(row["source_sku_id"]).strip()
    key = f"{wh}:{src}"
    qty = Decimal(str(row["qty"]))
    coef = coeff.get(key)
    if coef is None:
        return ("dirty", rid, key, qty, None, "缺系数(未提供该门店+商品系数)")
    if qty == qty.to_integral_value(rounding=ROUND_HALF_UP):
        return ("skip", rid, key, qty, coef, "qty 已为整数，跳过以免破坏数据")
    if g.is_divisible(qty, coef):
        new = (qty / coef).to_integral_value(rounding=ROUND_HALF_UP)
        return ("clean", rid, key, qty, coef, new)
    return ("dirty", rid, key, qty, coef, f"qty 不能被系数 {coef} 整除")


def gate_asn(row, coeff):
    rid = row["id"]
    wh = str(row["wh_id"])
    sku = str(row["sku_id"]).strip()
    src = SKU2SRC.get(sku)
    key = f"{wh}:{src}" if src else f"{wh}:?"
    qty = Decimal(str(row["expt_qty"]))
    coef = coeff.get(key)
    if src is None:
        return ("dirty", rid, key, qty, None, f"sku_id={sku} 未命中 md_sku 映射")
    if coef is None:
        return ("dirty", rid, key, qty, None, "缺系数(未提供该门店+商品系数)")
    if qty == qty.to_integral_value(rounding=ROUND_HALF_UP):
        return ("skip", rid, key, qty, coef, "expt_qty 已为整数，跳过以免破坏数据")
    if g.is_divisible(qty, coef):
        new = (qty / coef).to_integral_value(rounding=ROUND_HALF_UP)
        return ("clean", rid, key, qty, coef, new)
    return ("dirty", rid, key, qty, coef, f"expt_qty 不能被系数 {coef} 整除")


def emit_section(lines, title, rows, table, col, clean, skipped, dirty, combos_with_rows, combos_all):
    lines.append("")
    lines.append(f"-- ========== {title} ({table}) ==========")
    lines.append(f"-- 通过(生成UPDATE): {len(clean)} 行 | 跳过(已整数): {len(skipped)} 行 | 人工复核: {len(dirty)} 行")
    lines.append("")
    lines.append(f"-- 诊断查询（只读，复核现状；覆盖本批全部 {len(combos_all)} 个门店+商品组合）:")
    if table == "pos_do_detail":
        lines.append("select id, wh_id, source_sku_id, qty, do_h_id, del_flag")
        lines.append("from pos_do_detail")
        lines.append("where (wh_id, source_sku_id) in (")
        pairs = ", ".join(f"({wh},{sk})" for (wh, sk) in sorted(combos_all))
        lines.append("  " + pairs)
        lines.append(") and qty != FLOOR(qty) and del_flag = 0;")
    else:
        lines.append("select id, wh_id, sku_id, expt_qty, asn_header_id, line_status, del_flag")
        lines.append("from asn_detail")
        lines.append("where (wh_id, sku_id) in (")
        # 反查 sku_id
        src2sku = {v: k for k, v in SKU2SRC.items()}
        pairs = ", ".join(f"({wh},{src2sku[sk]})" for (wh, sk) in sorted(combos_all) if sk in src2sku)
        lines.append("  " + pairs)
        lines.append(") and expt_qty != FLOOR(expt_qty) and del_flag = 0;")
    lines.append("")
    lines.append("-- ---------- 生成的 UPDATE（带保护条件，幂等；仅整除通过的行） ----------")
    if clean:
        by_store = {}
        for r in clean:
            by_store.setdefault(r[1].split(":")[0], []).append(r)
        for store in sorted(by_store):
            lines.append(f"-- ---- 门店 wh_id = {store} ----")
            for rid, key, qty, coef, new in by_store[store]:
                lines.append(f"-- id={rid} {key}  {qty} / {coef} = {new}")
                lines.append(
                    f"update {table} t set t.{col} = t.{col} / {coef}, t.update_date = NOW() "
                    f"where t.id = {rid} and t.{col} != FLOOR(t.{col}) and t.del_flag = 0;"
                )
    else:
        lines.append("-- （无符合闸门条件的行，UPDATE 集为空）")
    lines.append("")
    lines.append("-- ---------- 人工复核清单（不进 UPDATE） ----------")
    if skipped:
        lines.append("-- [已整数-跳过] 当前值已是整数，直接除系数会破坏数据：")
        for rid, key, qty, coef, note in skipped:
            lines.append(f"--   id={rid} {key} qty={qty} -> {note}")
    if dirty:
        lines.append("-- [不能整除/缺系数] 需人工确认系数或数据：")
        for rid, key, qty, coef, note in dirty:
            lines.append(f"--   id={rid} {key} qty={qty} coef={coef} -> {note}")
    if not skipped and not dirty:
        lines.append("-- （无）")


def main():
    ap = argparse.ArgumentParser(description="多门店挂单计件小数修复 UPDATE 生成器")
    ap.add_argument("--coeff", required=True, help="coeff.csv (wh,source_sku_id,coeff)")
    ap.add_argument("--pos", default="", help="pos_rows.json")
    ap.add_argument("--asn", default="", help="asn_rows.json")
    ap.add_argument("--out", default="fix_all.sql", help="输出 SQL 文件")
    args = ap.parse_args()

    coeff = load_coeff(args.coeff)
    combos_all = set()
    for k in coeff:
        wh, src = k.split(":", 1)
        combos_all.add((wh, src))

    pos_clean, pos_skip, pos_dirty = [], [], []
    asn_clean, asn_skip, asn_dirty = [], [], []
    pos_combos = set()       # 仅 clean（生成 UPDATE）
    asn_combos = set()
    pos_all_combos = set()   # clean+skip+dirty（有小数行的全部组合，用于覆盖率）
    asn_all_combos = set()

    def _combo(key):
        wh, src = key.split(":", 1)
        return (wh, src)

    if args.pos:
        with open(args.pos, encoding="utf-8") as f:
            for row in json.load(f):
                st, rid, key, qty, coef, extra = gate_pos(row, coeff)
                pos_all_combos.add(_combo(key))
                if st == "clean":
                    pos_clean.append((rid, key, qty, coef, extra))
                    pos_combos.add(_combo(key))
                elif st == "skip":
                    pos_skip.append((rid, key, qty, coef, extra))
                else:
                    pos_dirty.append((rid, key, qty, coef, extra))
    if args.asn:
        with open(args.asn, encoding="utf-8") as f:
            for row in json.load(f):
                st, rid, key, qty, coef, extra = gate_asn(row, coeff)
                asn_all_combos.add(_combo(key))
                if st == "clean":
                    asn_clean.append((rid, key, qty, coef, extra))
                    asn_combos.add(_combo(key))
                elif st == "skip":
                    asn_skip.append((rid, key, qty, coef, extra))
                else:
                    asn_dirty.append((rid, key, qty, coef, extra))

    lines = []
    lines.append("-- ============================================================")
    lines.append("-- 挂单计件小数修复脚本 (auto-generated by pending-order-decimal-fix / gen_fix_multistore)")
    lines.append(f"-- 门店+商品组合数: {len(combos_all)}")
    lines.append(f"-- pos_do_detail: 通过={len(pos_clean)} 跳过={len(pos_skip)} 复核={len(pos_dirty)}")
    lines.append(f"-- asn_detail   : 通过={len(asn_clean)} 跳过={len(asn_skip)} 复核={len(asn_dirty)}")
    lines.append("-- 安全闸门: 仅「小数 且 能被系数整除」的行生成 UPDATE；")
    lines.append("--          已整数行 / 不能整除行 / 缺系数行 一律不进 UPDATE。")
    lines.append("-- 生产库执行前请人工复核；本脚本不自动执行任何 DML。")
    lines.append("-- ============================================================")

    emit_section(lines, "PART 1 挂单小数 pos_do_detail", pos_clean, "pos_do_detail", "qty",
                 pos_clean, pos_skip, pos_dirty, pos_combos, combos_all)
    emit_section(lines, "PART 2 收货异常小数 asn_detail", asn_clean, "asn_detail", "expt_qty",
                 asn_clean, asn_skip, asn_dirty, asn_combos, combos_all)

    # 覆盖率：本批组合中，哪些没有小数行（无需处理）
    lines.append("")
    lines.append("-- ========== 覆盖率说明 ==========")
    lines.append(f"-- pos_do_detail 有小数行的组合: {len(pos_all_combos)} / {len(combos_all)}")
    lines.append(f"-- asn_detail   有小数行的组合: {len(asn_all_combos)} / {len(combos_all)}")
    lines.append(f"-- 其中 pos 已生成 UPDATE 的组合: {len(pos_combos)} | 进人工复核(不能整除/已整数)的组合: {len(pos_all_combos - pos_combos)}")
    lines.append(f"-- 其中 asn 已生成 UPDATE 的组合: {len(asn_combos)} | 进人工复核(不能整除/已整数)的组合: {len(asn_all_combos - asn_combos)}")
    pos_zero = sorted(combos_all - pos_all_combos)
    asn_zero = sorted(combos_all - asn_all_combos)
    lines.append(f"-- 无 pos 小数行（确实无需处理）: {len(pos_zero)} 组合")
    lines.append("--   " + (", ".join(f"{wh}/{sk}" for wh, sk in pos_zero) or "（无）"))
    lines.append(f"-- 无 asn 小数行（确实无需处理）: {len(asn_zero)} 组合")
    lines.append("--   " + (", ".join(f"{wh}/{sk}" for wh, sk in asn_zero) or "（无）"))
    lines.append("")

    sql = "\n".join(lines)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(sql)

    # manifest
    man = os.path.splitext(args.out)[0] + ".manifest.csv"
    with open(man, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["table", "id", "wh", "key", "qty", "coeff", "status", "new_qty_or_note"])
        for rid, key, qty, coef, extra in pos_clean:
            w.writerow(["pos_do_detail", rid, key.split(":")[0], key, qty, coef, "clean", extra])
        for rid, key, qty, coef, extra in pos_skip:
            w.writerow(["pos_do_detail", rid, key.split(":")[0], key, qty, coef, "skip", extra])
        for rid, key, qty, coef, extra in pos_dirty:
            w.writerow(["pos_do_detail", rid, key.split(":")[0], key, qty, coef, "dirty", extra])
        for rid, key, qty, coef, extra in asn_clean:
            w.writerow(["asn_detail", rid, key.split(":")[0], key, qty, coef, "clean", extra])
        for rid, key, qty, coef, extra in asn_skip:
            w.writerow(["asn_detail", rid, key.split(":")[0], key, qty, coef, "skip", extra])
        for rid, key, qty, coef, extra in asn_dirty:
            w.writerow(["asn_detail", rid, key.split(":")[0], key, qty, coef, "dirty", extra])

    print(f"[OK] {args.out}  pos(clean={len(pos_clean)} skip={len(pos_skip)} dirty={len(pos_dirty)}) "
          f"asn(clean={len(asn_clean)} skip={len(asn_skip)} dirty={len(asn_dirty)})", file=sys.stderr)
    print(f"[OK] manifest -> {man}", file=sys.stderr)


if __name__ == "__main__":
    main()
