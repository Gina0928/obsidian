---
name: inventory-init-validate
description: |
  Validate warehouse inventory initialization data in MySQL and reconcile
  discrepancies. Trigger on: 库存初始化验证, 库存校验, 初始化核对, 库存初始化差异,
  数量对不上, 差异商品定位, 商品编码反查, 首次初始化, 增量初始化, 失败明细,
  初始化失败, 失败记录, 统计失败数量, DB库存统计, inventory init validation.
  Five workflows:
  - A 首次初始化验证: total qty & amount from stk_sku_lot + stk_lot_att (stk_doc_type=0).
  - B 增量初始化验证: net qty change from stk_trans_log_{wh_id} since a date.
  - C 首次初始化差异定位: compare stk_init_detail(stk_doc_type=0) vs 批次, 反查 md_sku.
  - D 增量初始化差异定位: compare stk_init_detail(stk_doc_type=1) vs stk_trans_log 出库.
  - E 失败明细检查: list stk_init_detail rows with status=91 (失败) and their 失败原因, tally total failed qty & amount. Run BEFORE C/D.
  Read-only SQL via the MySQL MCP connector (mcp__mysql_wms_prod__query /
  mcp__mysql_wms_test__query), with an automatic Python/pymysql fallback
  (scripts/db_connect.py) when the MCP is unreachable.
agent_created: true
---

# Inventory Init Validate（库存初始化验证）

Validate inventory initialization data in MySQL and locate reconciliation
differences. Four workflows, two pairs:

- **A / C** — first-time init (`stk_doc_type = 0`), compares against batch lots.
- **B / D** — incremental init, compares against the transaction log.

For table schemas, join keys, and extended gotchas, load
`references/db_schema.md`.

## Prerequisites

The primary path is the MySQL MCP connector (read-only). Two server keys are
configured: `mysql_wms_prod` and `mysql_wms_test`. Each exposes a `query` tool
whose exact name is `mcp__mysql_{server}__query`, i.e.:

- `mcp__mysql_wms_prod__query` (production)
- `mcp__mysql_wms_test__query` (test)

To run a query through the MCP:

1. Load the tool schema once with `ToolSearch`, passing
   `tool_names: ["mcp__mysql_wms_prod__query"]` (swap the server key as needed).
2. Call it via `DeferExecuteTool` with the SQL from the chosen workflow.

The chosen server must match the target environment and must agree with the
`--server` value used by the Python fallback below.

Optional sanity check before heavy queries: run `SELECT 1` (or
`SELECT COUNT(*) FROM stk_sku_lot WHERE wh_id = {wh_id}`) via the MCP tool to
confirm connectivity.

**If the MCP connector is unreachable (ETIMEDOUT / connection error), fall back
to a direct Python connection — see "MCP 连接失败回退（Fallback）" below.** Do
NOT keep retrying the MCP blindly; the MCP layer often runs in an isolated
environment that cannot reach the DB even when the agent's own sandbox can.

## MCP 连接失败回退（Fallback when MCP is down）

Use this whenever `mcp__mysql_{server}__query` fails to connect. The agent's
sandbox network frequently reaches the database directly even when the MCP
server process cannot (common with Aliyun RDS behind an IP whitelist, or an
untrusted MCP that never started). Navicat on the user's machine also reaches
it — so the end of the road is to ask the user to run the query in Navicat and
paste the result.

**Step F1 — Detect & diagnose**

If the MCP call returns `ETIMEDOUT` / `connect ... timeout` / `ECONNREFUSED`:
1. Read `~/.workbuddy/mcp.json` and find the target server under `mcpServers`
   (e.g. `mysql_wms_prod`). Note its `env.MYSQL_HOST` and `env.MYSQL_PORT`.
2. Probe TCP reachability from the sandbox (no driver needed):
   ```python
   import socket
   socket.create_connection((HOST, PORT), timeout=8)
   ```
3. If the probe **succeeds**, the DB is reachable → go to Step F2 (Python).
   If the probe **fails**, the sandbox cannot reach the DB either → go to
   Step F3 (ask the user / Navicat).

**Step F2 — Direct Python connection (preferred fallback)**

Use `scripts/db_connect.py`, which reads credentials from `~/.workbuddy/mcp.json`
and runs the SQL via `pymysql`. It auto-installs `pymysql` into the running
interpreter if missing, and hard-rejects any non-SELECT statement (read-only
guard). Run it with the **managed Python venv** (or any interpreter that has
`pymysql`):

```bash
# ensure the managed venv has pymysql (Windows path shown)
VENV="C:/Users/yuai/.workbuddy/binaries/python/envs/default"
[ -d "$VENV" ] || C:/Users/yuai/.workbuddy/binaries/python/versions/3.13.12/python.exe -m venv "$VENV"
"$VENV/Scripts/python.exe" -m pip install -q pymysql
```

Then run the exact same SQL from the chosen workflow, passing `--server`
(`mysql_wms_prod` default, or `mysql_wms_test`):

```bash
"$VENV/Scripts/python.exe" \
  C:/Users/yuai/.workbuddy/skills/inventory-init-validate/scripts/db_connect.py \
  --server mysql_wms_prod \
  --sql "SELECT ... <same SQL as the workflow> ..."
```

- Credentials (host/port/user/password/database) are read **only** from
  `mcp.json`; the password is never printed or placed on the command line.
- SQL may also come from `--file query.sql` or stdin.
- `--list-servers` prints the configured MySQL server keys from `mcp.json`
  (useful when unsure which `--server` to pass).
- The script enforces read-only execution: any statement containing
  INSERT/UPDATE/DELETE/DROP/etc. (or `SELECT INTO`) is rejected before running.
- The script prints columns then rows, pipe-delimited — feed its output straight
  into the workflow's "Present" step.

**Step F3 — Last resort (neither MCP nor sandbox can connect)**

If the TCP probe in F1 fails, the DB is not reachable from this environment at
all. Then:
1. Tell the user the MCP connector AND the sandbox both fail to reach the DB
   (likely a whitelist / VPN restriction on the DB host).
2. Ask the user to run the workflow's SQL in **Navicat** (which works from their
   machine) and paste the result, OR to add the sandbox egress IP to the DB
   whitelist, OR to ensure the MCP connector is trusted/enabled.
3. Take the pasted result and proceed with the workflow's "Present" step.

> Keep the MCP tool's name `mcp__mysql_{server}__query` in the workflows as the
> primary path; the fallback above is only reached on connection failure.

## Routing table

| 用户意图 | 工作流 | 关键表 | stk_doc_type |
|----------|--------|--------|--------------|
| 首次初始化总数 / 金额核对 | **A** | stk_sku_lot + stk_lot_att | 0 |
| 增量初始化净变化核对 | **B** | stk_trans_log_{wh_id} | (交易日志) |
| 首次初始化数量对不上 / 定位差异商品 | **C** | stk_init_detail vs 批次 | 0 |
| 增量初始化数量对不上 / 定位差异 | **D** | stk_init_detail vs stk_trans_log | 1 |
| 差异定位前先查失败明细 / 统计失败数量金额 | **E** | stk_init_detail (status=91) | 0 或 1 |

If the user does not supply a required parameter for the chosen workflow, collect
it before executing. Use `AskUserQuestion` to prompt for the missing value(s),
drawing on the parameter table of the chosen workflow (e.g. `wh_id`,
`init_header_id`, `create_date`). Do not guess warehouse or header ids — they
must come from the user or from a prior query result.

## Conventions（所有工作流通用）

- **`%X` 后缀固定：** `att.po_no LIKE '%X'`（A、C）与 `business_code LIKE '%X'`（B、D）后缀固定为 `%X`，不再是每次收集的参数。如需不同后缀，直接改 SQL 字面量。
- **表名模板：** B、D 使用按仓库分表的 `stk_trans_log_{wh_id}`，`{wh_id}` 同时作为表名与过滤条件。
- **金额符号：** 出库流水（doc_type=23, trans_type='OUT'）在库中已为负数，对账时直接相加（`init_qty + out_qty`）即为有符号净额。
- **NULL 处理：** 差异查询中批次/流水缺失时务必 `COALESCE(..., 0)`，且过滤条件用 `a != IFNULL(b, 0)`（C）或 `HAVING SUM(...) + COALESCE(...) != 0`（D），避免 `x != NULL` 恒为假而漏掉缺失行。
- **显式别名：** 差异 JOIN 两侧有同名列（qty/amount/sku_id），必须用显式别名，禁止 `SELECT *`，否则列被折叠、真实值被掩盖。
- **只读执行：** 优先用 `mcp__mysql_{server}__query`（prod / test）；若 MCP 不可达，改用 `scripts/db_connect.py` 直连（同样只读，且脚本强制拒绝写操作）。二者都不要用 MCP 的 `execute` 工具。
- **强制报告：** 每个工作流执行完毕后，必须按下面的「Result Report Specification」输出完整结果报告——不得用一句"数量是 X"草草带过。报告就是交付物。

---

## Result Report Specification（结果报告规范）

**每个工作流执行完毕后必须输出完整结果报告。** 无例外，不得简化为
"数量是 X" 的一行回复——报告本身就是交付物。

### Mandatory structure（四段式，缺一不可）

#### Section 1 — 执行概览（Execution Overview）

| 项目 | 值 |
|------|-----|
| 工作流 | {A/B/C/D/E} — {中文名} |
| 仓库 ID (wh_id) | {value} |
| init_header_id | {value or N/A} |
| create_date | {value or N/A} |
| stk_doc_type | {0/1/N/A} |
| 数据源 | {mcp__mysql_wms_prod / db_connect.py / Navicat manual} |
| 执行时间 | {YYYY-MM-DD HH:MM:SS} |
| 执行状态 | ✅ 成功 / ⚠️ 部分成功 / ❌ 失败 |

仅保留与该工作流相关的行；不适用的参数标 N/A 或省略。

#### Section 2 — 确定性指标（Deterministic Metrics）

| 指标名 (key) | 值 (value) | 类型 (type) | 说明 (note) |
|--------------|-----------|-------------|-------------|
| {metric_key} | {concrete_value} | {int/decimal/string/datetime} | {brief note} |

**硬性要求：**
- **值 (value) 必须是具体标量**（int / decimal / string），不得为 "—" / "差不多" /
  "基本正常"。空结果时 count/sum 类指标填 `0`（SQL 已 COALESCE），其余填 `空结果`。
- **类型 (type)** 取值：`int`、`decimal`、`string`、`datetime`。
- 每个工作流下方列出了它的**必填指标**——不可省略；可额外添加但不可删减。
- 指标值直接来自查询输出或对返回行的确定性聚合（COUNT / SUM / MAX / MIN），
  不得估算或推断。

#### Section 3 — 明细数据（Detail Data）

- 产生行级数据的工作流（C / D / E1）直接渲染为 Markdown 表，列名按各工作流规定。
- 仅汇总的工作流（A / B / E2）写"本工作流为汇总查询，无明细行"。
- 明细超过 50 行时，按工作流默认排序取前 50 行，注明总行数及截断。

#### Section 4 — 结论与建议（Conclusion & Next Steps）

- 一句话结论（对账一致 / 发现 N 个差异 SKU / 失败 N 行）。
- 是否可进入下一步（如"E 未发现失败，可继续 C" / "E 发现 5 条失败，先处理后继续"）。
- 如有异常，给出建议动作。

### Deterministic metric definition

指标为**确定性**当且仅当：
1. 是单个标量值（非行集合）。
2. 直接从查询输出计算（SUM / COUNT / COALESCE / MAX），非推断或估算。
3. 相同查询重跑必得相同值。

"数据看起来正常" / "差异不大" / "基本对得上" 等定性描述**不是**确定性指标，
不得出现在 Section 2，可在 Section 4 作为结论补充但不能替代硬数字。

### Optional: render_report.py（确定性报告渲染）

`scripts/render_report.py` 可选用于自动计算指标并渲染报告。传入工作流 ID、
参数 JSON、查询结果 JSON，输出四段式 Markdown：

```bash
"$VENV/Scripts/python.exe" \
  C:/Users/yuai/.workbuddy/skills/inventory-init-validate/scripts/render_report.py \
  --workflow A \
  --params '{"wh_id": 1604}' \
  --source mcp__mysql_wms_prod \
  --result '[{"total_qty": 12345.678, "total_amount": 98765.43, "lot_rows": 4321, "distinct_sku_count": 1234}]'
```

模型也可自行计算指标并按上述格式手写报告——规范是权威，脚本只是辅助。

---

## Workflow A: First-Time Init Validation（首次初始化验证）

Use when the user asks for 首次初始化验证 or total qty/amount of a first-time
load.

**Parameters**

| Parameter | Description | Example |
|-----------|-------------|---------|
| `wh_id` | Warehouse ID | `1604` |

**Step A1 — Execute**

```sql
SELECT
    SUM(ss.qty) + SUM(ss.qty_hold)                       AS total_qty,
    SUM(ss.qty * att.in_price) + SUM(ss.qty_hold * att.in_price) AS total_amount,
    COUNT(*)                                              AS lot_rows,
    COUNT(DISTINCT ss.sku_id)                             AS distinct_sku_count
FROM stk_sku_lot ss
INNER JOIN stk_lot_att att
    ON ss.wh_id = att.wh_id
    AND ss.sku_id = att.sku_id
    AND ss.lot_id = att.id
WHERE ss.wh_id = {wh_id}
    AND att.po_no LIKE '%X'
    AND att.del_flag = 0
```

Replace `{wh_id}` with the collected value. The query now returns four metrics in
a single pass — `lot_rows` and `distinct_sku_count` are needed for the report's
deterministic-metrics section.

**Step A2 — Present**

Render the four-section report per Result Report Specification. Mandatory metrics:

| 指标名 (key) | 类型 | 说明 |
|--------------|------|------|
| total_qty | decimal | 库存总数量 (qty + qty_hold) |
| total_amount | decimal | 库存总金额 |
| lot_rows | int | 批次行数 (COUNT(*)) |
| distinct_sku_count | int | 涉及 SKU 数 |

Example:

#### 执行概览
| 项目 | 值 |
|------|-----|
| 工作流 | A — 首次初始化验证 |
| 仓库 ID | 1604 |
| 数据源 | mcp__mysql_wms_prod |
| 执行时间 | 2026-08-02 23:20:20 |
| 执行状态 | ✅ 成功 |

#### 确定性指标
| 指标名 | 值 | 类型 | 说明 |
|--------|-----|------|------|
| total_qty | 12345.678 | decimal | 库存总数量 |
| total_amount | 98765.4300 | decimal | 库存总金额 |
| lot_rows | 4321 | int | 批次行数 |
| distinct_sku_count | 1234 | int | 涉及 SKU 数 |

#### 明细数据
本工作流为汇总查询，无明细行。

#### 结论与建议
首次初始化库存共 12345.678 件 / 98765.43 元，覆盖 1234 个 SKU。可进入 Workflow C
做差异定位（如用户报告数量对不上）。

---

## Workflow B: Incremental Init Validation（增量初始化验证）

Use when the user asks for 增量初始化验证 or net qty change since a date.

**Parameters**

| Parameter | Description | Example |
|-----------|-------------|---------|
| `wh_id` | Warehouse ID (also the `stk_trans_log_{wh_id}` table suffix) | `1512` |
| `create_date` | Cutoff datetime for transaction filtering | `2026-07-07 09:42:26` |

**Step B1 — Execute**

```sql
SELECT
    COALESCE(SUM(CASE WHEN doc_type = 11 THEN qty ELSE 0 END), 0)
  + COALESCE(SUM(CASE WHEN doc_type = 23 AND trans_type = 'OUT' THEN qty ELSE 0 END), 0)
    AS net_qty,
    COALESCE(SUM(CASE WHEN doc_type = 11 THEN qty ELSE 0 END), 0)
    AS inbound_qty,
    COALESCE(SUM(CASE WHEN doc_type = 23 AND trans_type = 'OUT' THEN qty ELSE 0 END), 0)
    AS outbound_qty,
    COUNT(*)                       AS trans_rows,
    COUNT(DISTINCT sku_id)         AS distinct_sku_count
FROM stk_trans_log_{wh_id}
WHERE (doc_type = 11 OR (doc_type = 23 AND trans_type = 'OUT'))
    AND business_code LIKE '%X'
    AND create_date >= '{create_date}'
```

Replace `{wh_id}` and `{create_date}` with the collected values.

- `doc_type = 11`: inbound transactions (positive).
- `doc_type = 23` + `trans_type = 'OUT'`: outbound transactions (already negative in DB).
- `net_qty = inbound_qty + outbound_qty`（出库已为负，直接相加得有符号净额）。
- The single-pass conditional aggregation replaces the original CROSS JOIN of two
  single-row subqueries — one table scan instead of two, and no fragile
  join-on-no-condition that silently breaks when either side returns no rows.

**Step B2 — Present**

Render the four-section report per Result Report Specification. Mandatory metrics:

| 指标名 (key) | 类型 | 说明 |
|--------------|------|------|
| net_qty | decimal | 库存数量净额 (入库 + 出库，出库为负) |
| inbound_qty | decimal | 入库数量合计 (doc_type=11) |
| outbound_qty | decimal | 出库数量合计 (doc_type=23, 已为负) |
| trans_rows | int | 流水行数 |
| distinct_sku_count | int | 涉及 SKU 数 |

If the result is empty or all-zero (no matching rows), still render the report
with all metrics = 0 and state "未找到匹配流水" in 结论. Never omit the report.

---

## Workflow C: First-Time Difference Investigation（差异定位与商品编码反查）

Use when Workflow A shows a **quantity/amount mismatch**, or the user asks to
查差异商品 / 数量对不上 / 定位哪个商品不一致. Finds which `sku_id` differs
between `stk_init_detail` (`stk_doc_type = 0`) and `stk_sku_lot`+`stk_lot_att`,
then resolves each differing sku to its product code via `md_sku`.

**Parameters**

| Parameter | Description | Example |
|-----------|-------------|---------|
| `init_header_id` | Init header id(s) from `stk_init_detail` | `508` |
| `wh_id` | Warehouse ID | `1102` |

**Step C0 — Failed-record pre-check（先查失败明细）**

Before locating differences, run **Workflow E** with `stk_doc_type = 0` and the
same `init_header_id`. If `failed_rows > 0`, present the failed detail and totals
first — failed rows (`status = 91`) never landed in the batch stock and would
otherwise appear as false "differences" in C1. Treat them as a separate operational
issue, not a genuine quantity mismatch.

**Step C1 — Find diverging SKUs**

```sql
SELECT
    a.sku_id              AS sku_id,
    a.qty                 AS init_qty,
    a.amount              AS init_amount,
    IFNULL(b.qty, 0)      AS lot_qty,
    IFNULL(b.amount, 0)   AS lot_amount,
    (IFNULL(b.qty, 0) - a.qty)       AS qty_diff,
    (IFNULL(b.amount, 0) - a.amount) AS amount_diff
FROM (
    SELECT abs(sum(qty)) AS qty, abs(sum(qty*in_price)) AS amount, sku_id
    FROM stk_init_detail
    WHERE init_header_id IN ({init_header_id})
      AND `status` = '20' AND del_flag = 0 AND stk_doc_type = 0
    GROUP BY sku_id
) a
LEFT JOIN (
    SELECT SUM(ss.qty) + SUM(ss.qty_hold) AS qty,
           SUM(ss.qty * att.in_price) + SUM(ss.qty_hold * att.in_price) AS amount,
           ss.sku_id
    FROM stk_sku_lot ss
    INNER JOIN stk_lot_att att
        ON ss.wh_id = att.wh_id AND ss.sku_id = att.sku_id AND ss.lot_id = att.id
    WHERE ss.wh_id = {wh_id}
      AND att.po_no LIKE '%X'
      AND att.del_flag = 0
    GROUP BY ss.sku_id
) b ON a.sku_id = b.sku_id
WHERE a.qty != IFNULL(b.qty, 0);
```

- `a` = 初始化明细聚合（按 sku_id 汇总 qty 与金额）；`b` = 实际批次聚合（qty + qty_hold 及对应金额）。
- `WHERE a.qty != IFNULL(b.qty, 0)` surfaces **both** cases: lot qty mismatched AND lot missing/zero (NULL → 0). The original `WHERE a.qty != b.qty` silently drops NULL-lot skus because `x != NULL` is never true.
- If the result is empty, the init data and batch data agree on quantity — no difference SKUs.

**Step C2 — Resolve product code (商品编码反查)**

For **each** `sku_id` returned in Step C1:

```sql
SELECT source_sku_id FROM md_sku WHERE id = {sku_id};
```

**Step C3 — Present**

Render the four-section report per Result Report Specification. Compute the
mandatory summary metrics **from the C1 result set** (deterministic aggregation
of returned rows):

| 指标名 (key) | 类型 | 计算方式 |
|--------------|------|----------|
| diff_sku_count | int | COUNT(*) of C1 rows |
| total_qty_diff | decimal | SUM(qty_diff) — 差异数量合计（正=批次多于初始化） |
| total_amount_diff | decimal | SUM(amount_diff) — 差异金额合计 |
| init_only_count | int | COUNT WHERE lot_qty = 0 — 仅初始化有、批次缺失的 SKU 数 |
| max_abs_qty_diff | decimal | MAX(ABS(qty_diff)) — 最大绝对差异数量 |
| failed_rows | int | from Workflow E（未跑 E 则填 0 并注明"E 未执行"） |

Detail table (Section 3):

| sku_id | 初始化数量 | 初始化金额 | 实际批次数量 | 实际批次金额 | 数量差异 | 金额差异 | 商品编码 (source_sku_id) |
|--------|-----------|-----------|-------------|-------------|---------|---------|--------------------------|
| {sku_id} | {init_qty} | {init_amount} | {lot_qty} | {lot_amount} | {qty_diff} | {amount_diff} | {source_sku_id} |

Section 4 结论 must state: total differing SKU count, whether to investigate
root cause per SKU (largest |qty_diff| first), and whether failed rows from E
explain any of the differences.

---

## Workflow D: Incremental Init Difference（增量初始化差异定位）

Use when the user reports an **incremental** init mismatch (增量初始化差异 /
增量初始化数量对不上), or asks to compare `stk_init_detail` (`stk_doc_type = 1`)
against the outbound transaction log. **Different script from Workflow C** — it
compares init detail against `stk_trans_log_{wh_id}`, not `stk_sku_lot`.

**Parameters**

| Parameter | Description | Example |
|-----------|-------------|---------|
| `init_header_id` | Incremental init header id from `stk_init_detail` | `473` |
| `wh_id` | Warehouse ID (also the `stk_trans_log_{wh_id}` table suffix) | `1512` |
| `create_date` | Cutoff datetime for transaction filtering | `2026-07-07 09:42:26` |

> `business_code` suffix (`%X`) and `stk_doc_type` (`1`) are fixed in the SQL per
> the通用 Conventions above — do not collect them as parameters. Change the SQL
> literal directly if a different suffix is ever needed.

**Step D0 — Failed-record pre-check（先查失败明细）**

Before locating differences, run **Workflow E** with `stk_doc_type = 1` and the
same `init_header_id`. If `failed_rows > 0`, present the failed detail and totals
first. Then, when reading D1's result, cross-reference each differing sku against
E1's failed list: any row present in **both** is a failed init record, not a genuine
reconciliation difference — flag it as such so it isn't double-counted as a mismatch.

**Step D1 — Find diverging SKUs**

```sql
SELECT
    s.id                                           AS sku_id,
    d.source_sku_id                                AS source_sku_id,
    d.init_qty                                     AS init_qty,
    COALESCE(l.out_qty, 0)                         AS out_qty,
    d.init_qty + COALESCE(l.out_qty, 0)            AS recon_diff,
    ABS(d.init_qty) - ABS(COALESCE(l.out_qty, 0))  AS abs_diff
FROM (
    SELECT source_sku_id, SUM(qty) AS init_qty
    FROM stk_init_detail
    WHERE init_header_id = {init_header_id}
      AND stk_doc_type = 1
      AND del_flag = 0
    GROUP BY source_sku_id
) d
LEFT JOIN md_sku s
    ON d.source_sku_id = s.source_sku_id
LEFT JOIN (
    SELECT sku_id, SUM(qty) AS out_qty
    FROM stk_trans_log_{wh_id}
    WHERE doc_type = 23
      AND business_code LIKE '%X'
      AND trans_type = 'OUT'
      AND create_date >= '{create_date}'
    GROUP BY sku_id
) l
    ON COALESCE(s.id, -1) = l.sku_id
HAVING recon_diff != 0
ORDER BY ABS(recon_diff) DESC;
```

- `init_qty` = 初始化明细数量（init detail，先按 `source_sku_id` 在子查询里聚合成 **1 行/SKU**，避免与出库侧连接时产生 fan-out 放大）。
- `out_qty` = 出库流水数量（`doc_type = 23` + `trans_type = 'OUT'`，**库中已为负**），同样先在子查询里按 `sku_id` 聚合成 1 行/SKU。无匹配出库行时 `COALESCE(..., 0)` 返回 `0`，因此仅初始化侧有数据的 SKU 也会被列出。
- `recon_diff` = `init_qty + out_qty` = 有符号净额差异。`0` 表示初始化数量与出库量完全对冲；任何非零值都是真实差异。用**有符号**求和（而非 `ABS(a) != ABS(b)`）更稳健——它还能捕捉两侧量值相同但符号相反的情况。
- `abs_diff` = `|init_qty| − |out_qty|`，保留用于与原量值差报告的展示一致。
- `HAVING recon_diff != 0` 直接对 SELECT 别名过滤。**⚠️ 旧版 bug 警告**：旧写法 `HAVING SUM(d.qty) + COALESCE(SUM(l_sum.b), 0) != 0` 在内层 `l_sum.b` 已被聚合的前提下，又在外层 `GROUP BY` 中对它再次 `SUM`，会把出库量按 init 行数放大 N 倍，导致**已对账（recon_diff=0）的 SKU 被误报为差异（假阳性）**。必须用本版的预聚合 + 1:1 关联 + `HAVING recon_diff != 0`。
- `s.id`（sku_id）与 `d.source_sku_id`（商品编码）直接返回，无需额外 `md_sku` 反查（不同于 Workflow C）。
- **Unmapped SKU 处理**：默认用 `LEFT JOIN md_sku s` 并在与出库子查询关联时用 `COALESCE(s.id, -1) = l.sku_id`，这样 `source_sku_id` 在 `md_sku` 中缺失的初始化行也不会被静默丢弃，而是作为差异正常浮现。

**Step D2 — Present**

Render the four-section report per Result Report Specification. The D1 query
already returns the discrepancy (`recon_diff`, `abs_diff`) and is ordered
largest-first. Compute the mandatory summary metrics **from the D1 result set**:

| 指标名 (key) | 类型 | 计算方式 |
|--------------|------|----------|
| diff_sku_count | int | COUNT(*) of D1 rows |
| total_recon_diff | decimal | SUM(recon_diff) — 对账差异合计 |
| positive_diff_count | int | COUNT WHERE recon_diff > 0（初始化 > 出库） |
| negative_diff_count | int | COUNT WHERE recon_diff < 0（出库 > 初始化） |
| max_abs_recon_diff | decimal | MAX(ABS(recon_diff)) — 最大绝对对账差异 |
| failed_rows | int | from Workflow E（未跑 E 则填 0 并注明"E 未执行"） |

Detail table (Section 3), ordered by ABS(recon_diff) DESC:

| sku_id | 商品编码 (source_sku_id) | 初始化数量 init_qty | 出库数量 out_qty | 对账差异 recon_diff | |init|−|out| abs_diff |
|--------|--------------------------|---------------------|------------------|---------------------|----------------------|
| {sku_id} | {source_sku_id} | {init_qty} | {out_qty} | {recon_diff} | {abs_diff} |

Section 4 结论 must state: total differing SKU count, positive vs negative
split (init exceeds outbound vs outbound exceeds init), flag the top rows
(largest |recon_diff|) for 优先排查, and note whether failed rows from E
explain any differences. A positive `recon_diff` means init quantity exceeds
outbound; a negative one means outbound exceeds init.

---

## Workflow E: Failed Init Detail Check（失败明细检查）

Run this **before** Workflow C or D (and standalone whenever the user asks
查失败明细 / 初始化失败记录 / 统计失败数量). Many "differences" surfaced by C/D are
actually records that never finished initializing — they carry `status = 91`
and a `error_msg` reason. Checking first means failed rows are reported and tallied
separately from genuine reconciliation differences.

**Parameters**

| Parameter | Description | Example |
|-----------|-------------|---------|
| `init_header_id` | Init header id from `stk_init_detail` | `812` |
| `stk_doc_type` | `0` for first-time (pairs with C), `1` for incremental (pairs with D) | `1` |

> `status = 91` (NOT `error_flag`) is the authoritative "failed" marker — see
> `references/db_schema.md`. `error_flag` is only a secondary signal and may be `1`
> even when `status = 20` (not a failure); always key failure detection on
> `status = 91`. `del_flag = 0` filters out soft-deleted rows.

**Step E1 — List failed detail**

```sql
SELECT
    init_header_id,
    source_sku_id    AS 商品编码,
    sku_name         AS 商品名称,
    loc_code         AS 库位编码,
    qty              AS 库存数量,
    in_price         AS 进价,
    (qty * in_price) AS 金额,
    status,
    error_flag,
    error_msg        AS 失败原因
FROM stk_init_detail
WHERE init_header_id = {init_header_id}
  AND stk_doc_type = {stk_doc_type}
  AND status = 91
  AND del_flag = 0
ORDER BY source_sku_id;
```

- `status = 91` is the failed marker (authoritative). Do not filter on `error_flag`, which is only a secondary signal.
- `error_msg` is the human-readable failure reason (e.g. 商品编码不存在、库存不足、批次生成失败).
- `金额` is computed as `qty * in_price` — there is **no** `amount` column on
  `stk_init_detail`; never `SELECT amount` from this table.

**Step E2 — Totals**

```sql
SELECT
    COUNT(*)                          AS failed_rows,
    COALESCE(SUM(qty), 0)             AS total_failed_qty,
    COALESCE(SUM(qty * in_price), 0)  AS total_failed_amount
FROM stk_init_detail
WHERE init_header_id = {init_header_id}
  AND stk_doc_type = {stk_doc_type}
  AND status = 91
  AND del_flag = 0;
```

- Signed sums: `qty` is normally positive for init rows. If a failed row ever holds
  a negative qty, the signed sum still reflects it correctly.
- `COALESCE(..., 0)` guards the empty-result case (no failed rows → `0`, not NULL).
- **实测观察：** `status = 91` 失败行可能带数量（如 `error_msg = '退供单创建失败：采购单门店与导入的门店不一致;'` 的某行 qty=113），也可能 qty=0（创建失败发生在分配数量之前）。全局共 1191 条失败、失败数量 116、金额 989.68。失败排查价值在于 `failed_rows` 计数、`error_msg` 原因归类与数量金额合计三者，**不要因单列 qty=0 而误判"无失败"**。

**Step E4 — Error distribution（失败原因分布）**

Run alongside E1/E2 to power the report's `top_error_msg` /
`distinct_error_count` metrics:

```sql
SELECT
    IFNULL(error_msg, '(空)') AS error_msg,
    COUNT(*)                  AS count
FROM stk_init_detail
WHERE init_header_id = {init_header_id}
  AND stk_doc_type = {stk_doc_type}
  AND status = 91
  AND del_flag = 0
GROUP BY IFNULL(error_msg, '(空)')
ORDER BY count DESC;
```

- `IFNULL(error_msg, '(空)')` ensures NULL reasons are grouped and counted
  rather than silently dropped.
- `distinct_error_count` = number of rows returned by E4.
- `top_error_msg` / `top_error_count` = first row of E4.

**Step E3 — Present**

Render the four-section report per Result Report Specification. Mandatory
metrics (from E2 + E4):

| 指标名 (key) | 类型 | 来源 |
|--------------|------|------|
| failed_rows | int | E2.failed_rows |
| total_failed_qty | decimal | E2.total_failed_qty |
| total_failed_amount | decimal | E2.total_failed_amount |
| distinct_error_count | int | E4 — 失败原因种类数 |
| top_error_msg | string | E4 — 出现次数最多的失败原因 |
| top_error_count | int | E4 — 该原因出现次数 |

Detail table (Section 3) — E1 rows:

| 商品编码 | 商品名称 | 库位编码 | 库存数量 | 进价 | 金额 | status | 失败原因 |
|----------|----------|----------|----------|------|------|--------|----------|
| {source_sku_id} | {sku_name} | {loc_code} | {qty} | {in_price} | {amount} | {status} | {error_msg} |

Followed by the error-distribution sub-table (E4 results), then Section 4
结论.

If `failed_rows = 0`, state that no failed init records exist for this header,
render the metrics table with all values = 0, and proceed to C/D. If
`failed_rows > 0`, render the full report above and **treat these rows as a
separate concern** from the C/D reconciliation differences — failed rows must
not be counted as genuine quantity mismatches against the batch / transaction
log.

---

## Cross-workflow reminders

- **每次执行必须输出完整报告：** 按 Result Report Specification 的四段式结构
  （执行概览 / 确定性指标 / 明细数据 / 结论与建议）输出。确定性指标必须为具体标量值，
  不得用定性描述替代。可用 `scripts/render_report.py` 辅助渲染，也可手写——规范是权威。
- A uses `stk_sku_lot` + `stk_lot_att`; B uses `stk_trans_log_{wh_id}`. They
  are different tables and may use different warehouses.
- A returns four metrics (total_qty, total_amount, lot_rows, distinct_sku_count);
  B returns five (net_qty, inbound_qty, outbound_qty, trans_rows, distinct_sku_count).
- **First-time vs incremental diff are different scripts:** C compares init
  detail (`stk_doc_type=0`) against `stk_sku_lot`+`stk_lot_att`; D compares
  init detail (`stk_doc_type=1`) against `stk_trans_log_{wh_id}`. Do NOT mix
  them up — the tables, joins, and `stk_doc_type` value differ.
- C/D 的确定性指标从各自查询返回的明细行聚合计算（COUNT / SUM / MAX），无需额外 SQL。
- E 现包含四个步骤：E1（失败明细）、E2（汇总）、E4（原因分布）、E3（报告渲染）。
  `top_error_msg` / `distinct_error_count` 来自 E4。
- All queries are read-only. Primary: `mcp__mysql_{server}__query`
  (`mcp__mysql_wms_prod__query` / `mcp__mysql_wms_test__query`). Fallback when
  the MCP is unreachable: `scripts/db_connect.py` (direct pymysql, reads creds
  from `~/.workbuddy/mcp.json`). Never use the MCP `execute` tool.
