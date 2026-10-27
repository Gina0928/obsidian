# DB Schema Reference — inventory-init-validate

Detailed table schemas, join relationships, and extended gotchas for the
`inventory-init-validate` skill. The SKILL.md workflows assume familiarity with
these structures; load this file when you need to debug a query, extend a
workflow, or understand a column's meaning.

## Tables & key columns

### `stk_sku_lot` (批次库存)
| Column | Type | Notes |
|--------|------|-------|
| `wh_id` | int | Warehouse id |
| `sku_id` | int | Product sku id (joins `md_sku.id`) |
| `lot_id` | int | Lot id — joins `stk_lot_att.id` |
| `qty` | decimal | On-hand quantity |
| `qty_hold` | decimal | Held / reserved quantity |

### `stk_lot_att` (批次属性)
| Column | Type | Notes |
|--------|------|-------|
| `wh_id` | int | Warehouse id |
| `sku_id` | int | Product sku id |
| `id` | int | Lot id — joins `stk_sku_lot.lot_id` |
| `po_no` | varchar | PO number; filtered with `LIKE '%X'` |
| `in_price` | decimal | Unit inbound cost |
| `del_flag` | tinyint | `0` = active; always filter `= 0` |

### `stk_init_detail` (初始化明细)
| Column | Type | Notes |
|--------|------|-------|
| `init_header_id` | bigint | Init batch header id |
| `sku_id` | bigint | Product sku id (used in Workflow C) |
| `source_sku_id` | varchar(15) | Product code — joins `md_sku.source_sku_id` |
| `sku_name` | varchar(50) | Product name (shown in failure detail, Workflow E) |
| `loc_code` | varchar(30) | Location / bin code |
| `qty` | decimal(12,3) | Init quantity (signed in Workflow D, `abs()` in C) |
| `in_price` | decimal(18,6) | Unit inbound cost |
| `status` | tinyint | Processing stage: `0` 待处理, `1`/`10` 处理中, `11` 生成PO单, `12` 生成入库单, `20` 已完成, `90` 已取消, `91` **失败 (failed, carries error_msg — authoritative failed marker, Workflow E)**. **`20` = confirmed** (Workflow C filter). |
| `error_flag` | tinyint | **`1` 出现在失败行（辅助信号），`NULL`/0 = 未标记.** 失败以 `status = 91` 为准；`error_flag` 仅为次要信号（即使 `status = 20` 也可能为 `1`，不算失败）。 |
| `error_msg` | varchar(255) | Failure reason, populated when `error_flag = 1`. |
| `del_flag` | tinyint | `0` = active |
| `stk_doc_type` | tinyint | `0` = 采购 (first-time), `1` = 退供 (incremental) |
| `wh_id` | bigint | Warehouse / store id |

> **No `amount` column.** Line amount must be computed as `qty * in_price`.
> Workflow C's `amount` is derived the same way; never `SELECT amount` from this table.

### `stk_trans_log_{wh_id}` (出入库流水 — per-warehouse table)
| Column | Type | Notes |
|--------|------|-------|
| `sku_id` | int | Product sku id — joins `md_sku.id` |
| `doc_type` | int | `11` = inbound, `23` = outbound |
| `trans_type` | varchar | `'OUT'` for outbound |
| `business_code` | varchar | Filtered with `LIKE '%X'` |
| `qty` | decimal | **Already signed** — outbound is negative in DB |
| `create_date` | datetime | Transaction time; used as cutoff filter |

> The `{wh_id}` suffix in the table name is a physical shard per warehouse.
> `wh_id` is therefore both the table selector and an implicit filter.

### `md_sku` (商品主数据)
| Column | Type | Notes |
|--------|------|-------|
| `id` | int | Primary sku id |
| `source_sku_id` | varchar | Product code — **expected unique** |

## Join map

```
stk_sku_lot.ss
   ├─ INNER JOIN stk_lot_att.att
   │     ON ss.wh_id = att.wh_id
   │    AND ss.sku_id = att.sku_id
   │    AND ss.lot_id = att.id
   └─ (Workflow C) aggregated by ss.sku_id

stk_init_detail d
   ├─ (Workflow C) GROUP BY sku_id, compares against批次 by sku_id
   └─ (Workflow D) INNER JOIN md_sku s
         ON d.source_sku_id = s.source_sku_id   →  s.id
         LEFT JOIN stk_trans_log_{wh_id} l_sum
            ON s.id = l_sum.sku_id
```

## doc_type / trans_type semantics

| doc_type | trans_type | Meaning | Sign in DB |
|----------|-----------|---------|-------------|
| 11 | — | Inbound (入库) | positive |
| 23 | `'OUT'` | Outbound (出库) | **negative** |
| 23 | other | Non-outbound movements | varies |

Reconciliation rule: `init_qty + out_qty` where `out_qty` is already negative
yields the **signed net discrepancy**. `0` = perfectly reconciled.

## Index recommendations

- `stk_trans_log_{wh_id}`: composite index
  `(doc_type, trans_type, create_date, business_code, sku_id)` for large tables.
- `business_code LIKE '%X'` and `po_no LIKE '%X'` use a **leading-wildcard**
  pattern, which cannot use a plain index on that column. If the exact prefix is
  known, prefer `=` or a non-leading-wildcard value.

## Extended gotchas

- **`md_sku.source_sku_id` uniqueness:** Workflow D's `INNER JOIN md_sku s
  ON d.source_sku_id = s.source_sku_id` silently drops any init row whose
  `source_sku_id` is absent in `md_sku` — a missing mapping would be mistaken
  for "no diff". If missing mappings are possible, switch to
  `LEFT JOIN md_sku s` and use `COALESCE(s.id, -1)` as the `l_sum` join key.
- **First-time vs incremental are different scripts:** Workflow C compares
  `stk_init_detail` (`stk_doc_type = 0`) against `stk_sku_lot`+`stk_lot_att`;
  Workflow D compares `stk_init_detail` (`stk_doc_type = 1`) against
  `stk_trans_log_{wh_id}`. The tables, joins, and `stk_doc_type` value all
  differ — do not mix them up.
- **NULL handling in difference queries:** a missing batch/flow row must be
  `COALESCE(..., 0)`-ed, and the mismatch filter must be
  `a != IFNULL(b, 0)` (Workflow C) or `HAVING SUM(...) + COALESCE(...) != 0`
  (Workflow D). Using `x != NULL` is never true and silently hides missing-row
  differences.
- **No `SELECT *` in difference JOINs:** both sides expose identically-named
  columns (`qty`/`amount`/`sku_id`); `SELECT *` collapses them and hides the
  real `b`-side values. Always select with explicit aliases.
- **Failed records vs reconciliation differences:** `stk_init_detail.status = 91`
  marks rows that failed to initialize (reason in `error_msg`; `error_flag = 1` is a
  secondary signal only). These rows often surface as false "differences" in Workflow
  C/D because their `qty` may not have landed in the batch / transaction log. Always
  run **Workflow E (failed-check) before C/D** and report/tally failed rows separately.
  Do NOT filter C/D on `error_flag` alone to "fix" the diff — failed rows are a real
  operational issue, not a reconciliation match.
