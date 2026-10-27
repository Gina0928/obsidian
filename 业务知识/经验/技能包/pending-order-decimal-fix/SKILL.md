---
name: pending-order-decimal-fix
description: 修复 WMS「挂单计件小数」脏数据。当 pos_do_detail 因商品计件系数（如 1.1/0.5/1.5）导致 qty 出现非整数，或 asn_detail 因挂单产生收货异常小数时，按门店+商品系数把 qty/expt_qty 还原为真实计件数。连接 yas 生产库（mysql_wms_yas_prod/jy_wms），只读诊断 + 带整除闸门生成 UPDATE 脚本，绝不擅自执行 DML；每批处理完后自动收敛产物，只保留并交付当前批次（删除历史批次）。触发词：挂单小数、计件小数、pos_do_detail qty 非整数、挂单导致收货异常、商品系数还原、pending order decimal。
agent_created: true
---

# 挂单计件小数修复

## 适用场景

WMS 挂单（pos_do_detail）与收货（asn_detail）中，因商品「计件单位系数」被错误地写进数量列，导致 `qty` / `expt_qty` 出现非整数小数。修复逻辑是用数量除以该商品系数，还原成真实计件数。

典型触发：
- 用户报「挂单数量有小数」「计件小数」「pos_do_detail qty 非整数」。
- 排查「挂单导致收货异常」「asn_detail 预期数量带小数」。
- 需要按商品系数（如 670923→1.1、822931→0.5、808424→1.5）批量还原数量。

## 核心安全闸门（必读，违反即破坏数据）

1. **生产库只读。** 诊断用 `SELECT`；`UPDATE/DELETE` 只作为脚本文本输出，由用户复核后自行执行。绝不调用 execute 工具改生产库。
2. **整除核对（本技能灵魂）。** 仅当 `qty` 是系数的整数倍（`qty = 系数 × 整数`，残差 ≤ 1e-4）时才生成 UPDATE。不能整除的行列入人工复核，不进 UPDATE。
3. **已整数行绝不除系数。** 若当前 `qty` 已是整数（`FLOOR(qty)==qty`），说明已修复或示例过时，再除系数会把 `1.000` 变成 `0.909`，直接破坏数据 → 跳过。
4. **示例 id 不可直接套用。** 必须以当次查询返回的真实行为准；用户给的示例 id/系数只作格式参考。
5. **id 空间陷阱。** `pos_do_detail` 用 `source_sku_id`；`asn_detail.sku_id` 存的是 `md_sku.id`（组内主键），不是 source_sku_id。查 asn 前必须先做 source_sku_id → md_sku.id 映射（见 references/schema-and-coeff.md）。

## 工作流

### Step 1　连接与只读护栏
连接 `mysql_wms_yas_prod`（jy_wms）。全程 `SELECT`，不执行 DML。所有查询带 `wh_id` 与 `del_flag = 0`。

### Step 2　集团商品映射
```sql
select id, source_sku_id, sku_name, full_name
from md_sku
where source_sku_id in (808423, 671447, 808424, 715365, 516589, 822931, 670923);
```
取 `source_sku_id ↔ md_sku.id` 映射，供 asn_detail 侧使用。

### Step 3　查挂单小数
```sql
select id, wh_id, source_sku_id, qty, do_h_id, del_flag
from pos_do_detail
where wh_id = :wh and source_sku_id in (:coeff_keys)
  and qty != FLOOR(qty) and del_flag = 0;
```
把结果（id / source_sku_id / qty）交给生成器。

### Step 4　查收货异常小数（注意 id 空间）
先按 Step 2 映射，再用 `md_sku.id` 查：
```sql
select id, wh_id, sku_id, expt_qty, asn_header_id, line_status, del_flag
from asn_detail
where wh_id = :wh and sku_id in (:md_sku_ids)   -- 如 671447→55628, 808423→72024
  and expt_qty != FLOOR(expt_qty) and del_flag = 0;
```
未提供系数的 asn 商品只做定位 + 人工复核，不自动生成 UPDATE。

### Step 5　整除核对（闸门）
对 Step 3/4 的每一行：
- `qty` 已为整数 → 跳过（防破坏）。
- `qty / 系数` 为整数（残差 ≤ 1e-4）→ 通过，进入 UPDATE。
- 否则 / 缺系数 → 人工复核清单。

用 `scripts/gen_fix_sql.py` 自动完成核对与脚本生成（见下）。

### Step 6　生成 UPDATE 脚本（单门店）
```bash
python scripts/gen_fix_sql.py \
  --rows rows.json \
  --coeff 670923:1.1,822931:0.5,808424:1.5 \
  --wh 1520 --table pos_do_detail --out fix_1520.sql
```
脚本输出：诊断查询 + 带保护条件的 UPDATE（`where id = ? and qty != FLOOR(qty) and del_flag = 0`，幂等）+ 人工复核清单。把 `fix_1520.sql` 交付用户复核后执行，**本技能不自动执行**。

### Step 6b　多门店批量（推荐用于跨店系数表）
当一次性给出「门店 / 商品 / 系数」整表时，用 `scripts/gen_fix_multistore.py`：
```bash
python scripts/gen_fix_multistore.py \
  --coeff coeff.csv \          # 列: wh,source_sku_id,coeff（复合键，808426 按店区分）
  --pos  pos_rows.json \       # 列: id,wh_id,source_sku_id,qty
  --asn  asn_rows.json \       # 列: id,wh_id,sku_id,expt_qty（sku_id 为 md_sku.id）
  --out  fix_all.sql
```
- 系数按 `(wh_id, source_sku_id)` 复合键取值，**808426 在 1117 是 0.6、在 1102/1279 是 0.3**，必须区分，否则还原值错位。
- 复用 `gen_fix_sql.is_divisible` 做 Decimal 高精度整除闸门；输出 `fix_all.sql`（含诊断查询 + 幂等 UPDATE + 覆盖率说明）与 `fix_all.manifest.csv`（逐行 门店/商品/qty/系数/整除结果）。
- 仍只产出脚本、绝不执行 DML。

### Step 7　产物收敛（只留当前批次，必做）
每处理完一批（无论单门店或整表），**只保留当前批次产物，删除之前所有批次产物**，并只把当前批次交付给用户。这是本技能的硬性交付约定，避免多批次 SQL 混淆、误执行旧脚本。

1. **目录约定**：当前批次产物统一放入专属目录，推荐命名为 `fix_current/`（旧批次曾用 `fix_batchN/`，清理时一并移除）。目录内包含 `fix_all.sql`、`fix_all.manifest.csv` 与输入三件套（`coeff.csv`/`pos_rows.json`/`asn_rows.json`）。
2. **收敛清理**：生成当前批次后，运行收敛脚本，传入当前批次目录：
   ```bash
   python scripts/clean_prev_batches.py --keep <当前批次绝对路径> --apply
   ```
   - 该脚本**默认 dry-run**（只列待删项），必须显式加 `--apply` 才真正删除。
   - 精确 allowlist：仅删除工作根目录下 `fix_batch*` / `fix_current` 目录、以及根级 `fix_*.sql` / `fix_*.manifest.csv` / `挂单计件小数修复*.sql`；**绝不碰 `.workbuddy` 与无关文件**，绝不递归删除其它目录。
   - `--keep` 指定的当前批次目录及其内容始终保留。
3. **文档收敛**：把 `references/schema-and-coeff.md` 的 §5 实测快照收敛为「仅当前批次」——将最新一次快照重编号为 §5.1，删除更早的 §5.x，避免悬空引用已删目录。
4. **交付**：仅用 `present_files` 返回当前批次的 `fix_all.sql` 与 `fix_all.manifest.csv`，**不要**返回任何历史批次文件。

> 收敛脚本会在真正删除前打印待删清单；执行 `--apply` 后请核对输出，确认只删除了预期的历史产物。

## 资源

### scripts/gen_fix_sql.py
整除闸门脚本生成器（单门店）。读小数行 JSON + 系数表，输出 gated UPDATE。关键逻辑（Decimal 高精度）：
- 已整数行跳过；不能整除 / 缺系数行列入人工复核；仅通过行生成 UPDATE。
- 自带保护条件，即使误跑也不会把已整数行除坏。

### scripts/gen_fix_multistore.py
多门店批量生成器。读 `coeff.csv`（复合键）+ `pos_rows.json` + `asn_rows.json`，复用同一整除闸门，输出 `fix_all.sql` 与 `fix_all.manifest.csv`，并自动生成「无小数行组合」覆盖率清单。系数按 `(门店,商品)` 双列取，规避 808426 跨店系数不一致陷阱。

### scripts/clean_prev_batches.py
产物收敛脚本（Step 7 用）。精确 allowlist 删除工作根目录下的历史批次产物（`fix_batch*`/`fix_current` 目录与根级 `fix_*.sql`/`fix_*.manifest.csv`/`挂单计件小数修复*.sql`），保留 `--keep` 指定的当前批次与 `.workbuddy`。默认 dry-run，加 `--apply` 才真正删除。

### references/schema-and-coeff.md
表结构要点、source_sku_id ↔ md_sku.id 映射、多门店系数表（含 808426 例外）、门店约定、整除口径，以及最近一次实测快照（按产物收敛约定只保留当前批次，见 §5.1）。

## 反馈

若某门店/商品的系数与默认表不符，或发现新的 id 空间陷阱，记入 `~/.workbuddy/skills/.wms-triage-feedback/pool.jsonl`（单次偶发不改技能，命中够多再合并）。
