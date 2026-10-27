# 测试环境速查（jy_wms）

## 数据库连接映射

2026-09-04 实测核对：

| 工具 | 数据库 | 表数 | 门店分表数 | 状态 |
|---|---|---|---|---|
| `mcp__mysql_wms_test__query` | `jy_wms` | 492 | 110 | **测试环境（默认）** |
| `mcp__mysql_wms_testhw__query` | — | — | — | **已失效**，ECONNREFUSED，勿用 |
| `mcp__mysql_wms_yas_prod__query` | `jy_wms` | ~500 | 100+ | 生产主库，仅用于跨环境比对 |
| `mcp__mysql_wms_wky_prod__query` | `jy_wms` | 387 | 18 | 生产（wky），仅用于跨环境比对 |

测试库与生产库同名（都是 `jy_wms`），靠连接区分，输出结论时必须写明是哪一侧。

## 门店编码

与生产一致：门店编码 `warehouse_code` 即分表后缀 `wh_id`，与 `store_id` 同值，
主表 `md_warehouse`。

```sql
SELECT warehouse_code, warehouse_name, city
FROM md_warehouse
WHERE warehouse_name LIKE CONCAT('%', '<名称>', '%');
```

## 分表规则

库存流水按门店分表：`stk_trans_log_{wh_id}`，例如 `stk_trans_log_1607`。
测试环境约 110 个分表，但并非生产的所有门店都有对应分表，查前先确认存在。

## 核心表分组

与生产同构（同名同结构，数据量不同）：

**库存主表**
`stk_sku`、`stk_sku_loc`、`stk_sku_lot`、`stk_lot_loc`、`stk_lot_att`、
`stk_minus`、`stk_minus_log`、`stk_trans_log_{wh_id}`

**库存初始化**
`stk_init_header`、`stk_init_detail`、`stk_init_out_log`、`stk_init_compare`

## 主库存异步写入链路（StkHoldSyncJob）— 库存"不更新/查不到"的首选排查点

**机制**：`stk_lot_loc`、`stk_sku`、`stk_sku_loc`、`stk_sku_lot` 四张主库存表
只有一条异步写入路径 —— `StkHoldSyncJob`（manager 模块，5 个固定线程轮询）
把占用表 `stk_hold_sync` 的记录搬到主库存（`StkHoldSyncBizService.convert()`）。
而 `stk_lot_att`（批次）与 `stk_trans_log_{wh_id}`（流水）是业务链路**同步**写的。

> 因此：**「流水/批次在更新，但主库存不更新」≈ StkHoldSyncJob 积压或停摆**，
> 不要再只在库存表内部打转。

**吞吐口径**（用于判定"停"还是"慢"）：配置 `stk.sync.count=500`、
`stk.sync.second=2`、`POOL_SIZE=5` → 理论上限 1250 条/秒，保守 250 条/秒。
若实际产生速率仅个位数条/秒却持续积压，即可判定为消费者线程停止（不是慢）。

**四步判定 SQL**：

```sql
-- 1) 积压总量与起点
SELECT COUNT(*), COUNT(DISTINCT wh_id), MIN(create_date), MAX(create_date) FROM stk_hold_sync;

-- 2) 按门店定位停滞范围（正常门店只会有个位数实时记录）
SELECT wh_id, COUNT(*) cnt, MIN(create_date), MAX(create_date)
FROM stk_hold_sync GROUP BY wh_id ORDER BY cnt DESC;

-- 3) 判定"停/慢"：主库存最后更新时间 vs 流水/批次
SELECT wh_id, MAX(update_date) FROM stk_lot_loc WHERE wh_id IN (...) GROUP BY wh_id;
SELECT MAX(create_date) FROM stk_lot_att    WHERE wh_id = <wh_id>;
SELECT MAX(create_date) FROM stk_trans_log_<wh_id>;

-- 4) 看队头（Job 取数顺序 ORDER BY update_date ASC, id ASC）
SELECT id, wh_id, sku_id, lot_id, loc_id, qty, opt_type, doc_no, create_date, update_date, version
FROM stk_hold_sync WHERE wh_id=<门店> ORDER BY update_date ASC, id ASC LIMIT 5;
-- update_date = create_date 且 version=1 → 该条从未被成功处理，即毒丸候选
```

**已知代码缺陷**（解释为何会静默停摆 10+ 小时）：
1. 门店与 5 个线程**固定绑定**（`idsList` 顺序稳定 + `subJobs[i%5]`），一个线程卡死 = 该组门店永久停，重分配也落回同一线程；
2. 队头阻塞：取数按 `update_date asc, id asc`，任一条处理抛异常 → 事务回滚、记录不删 → 下轮重复取同一条；
3. 异常被吞：`catch (Throwable) { e.printStackTrace(); }`，无 ERROR 日志、无告警、无死信；
4. 无积压监控；5. 逐条单事务 + 逐条 save，无批量；
6. 开关 `STK_FIELD_CHG_RUN_JOB=1` 会先 `whIds.clear()` 再 return → 全停（排查时确认其当前值）。

**恢复**：解除卡点后重启 leader 节点应用复位线程，积压按 250~1250 条/秒自动消化。

**单据**
`doc_alc_header`／`doc_alc_detail`（调拨）、`doc_do_header`／`doc_do_detail`（出库）、
`asn_header`／`asn_detail`（收货）、`stk_cou_header`／`stk_cou_detail`（盘点）

**主数据**
`md_warehouse`、`md_sku`、`md_supplier`、`md_location`

完整清单参考 `prod-issue-triage/references/environment.md`（两侧结构一致）。

## 常用查询片段

确认分表存在：

```sql
SELECT table_name FROM information_schema.tables
WHERE table_schema = DATABASE() AND table_name = 'stk_trans_log_<wh_id>';
```

查看表结构（不凭记忆写 SQL）：

```sql
SELECT column_name, column_type, column_comment
FROM information_schema.columns
WHERE table_schema = DATABASE() AND table_name = '<表名>'
ORDER BY ordinal_position;
```

跨环境比对表结构差异：

```sql
SELECT column_name, column_type
FROM information_schema.columns
WHERE table_schema = DATABASE() AND table_name = '<表名>'
ORDER BY ordinal_position;
```

（分别在测试与生产两个连接各跑一次，再比对结果。）

查看某门店的数据规模，判断是否具备复现条件：

```sql
SELECT COUNT(*) AS rows_cnt,
       SUM(CASE WHEN qty = 0 THEN 1 ELSE 0 END) AS zero_qty_rows
FROM stk_lot_loc
WHERE wh_id = '<wh_id>';
```

## 注意事项

- **零数量行占比高**：测试环境大量 qty=0 的记录，会让执行计划与生产不同，
  排查性能问题时尤其注意。
- **性能结论不外推**：测试环境跑得快不代表生产没问题，性能类结论必须回生产
  用 `EXPLAIN` 复核。
- 数据量不足导致无法复现时，如实说明，不要编造结论。
- 默认只读；确需改数据时先取得用户明确同意。
