# 生产环境速查（jy_wms）

## 数据库连接映射

2026-09-04 实测核对，库名与规模如下：

| 工具 | 数据库 | 表数 | 门店分表数 | 归属 |
|---|---|---|---|---|
| `mcp__mysql_wms_yas_prod__query` | `jy_wms` | ~500 | 100+ | **生产主库（默认）** |
| `mcp__mysql_wms_wky_prod__query` | `jy_wms` | 387 | 18 | 生产（wky 那套） |
| `mcp__mysql_ty_yas_product_prod__query` | `ty_product` | 46 | 0 | 商品主数据（生产） |
| `mcp__mysql_zq_yas_product_prod__query` | `zq_product` | 146 | 0 | 商品主数据（生产） |
| `mcp__mysql_wms_test__query` | `jy_wms` | 492 | 110 | 测试环境（本技能不用） |
| `mcp__mysql_wms_testhw__query` | — | — | — | **已失效**，连接被拒（ECONNREFUSED），勿用 |

未指定时一律走生产主库 `mcp__mysql_wms_yas_prod__query`。

## 门店编码

门店编码 `warehouse_code` 即分表后缀 `wh_id`，与 `store_id` 取值一致。
主表 `md_warehouse`，常用列：`warehouse_code`（编码）、`warehouse_name`（名称）、
`warehouse_short_name`（简称）、`store_id`、`city`、`warehouse_type`（1=大卖场
2=标超 3=便利店）。

按名称反查编码：

```sql
SELECT warehouse_code, warehouse_name, city
FROM md_warehouse
WHERE warehouse_name LIKE CONCAT('%', '<名称>', '%');
```

按编码反查名称：

```sql
SELECT warehouse_code, warehouse_name, city
FROM md_warehouse
WHERE warehouse_code IN ('1607', '1285');
```

实测样例：1607=沙市七中，1285=熟食加工厂，1300=面包加工厂，1802=松雅湖店，1112=雅斯天紫荟。

## 分表规则

库存流水按门店分表：`stk_trans_log_{wh_id}`，例如 `stk_trans_log_1607`。
已确认存在的分表后缀包括 1102~1803 区间的大量门店，以及 2100、2300、3038、
3040、3041、8010~8070、9002、9100、9901 等。

查之前先确认分表存在，不存在则如实说明，不要退回主表 `stk_trans_log`。

## 核心表分组

**库存主表**
`stk_sku`、`stk_sku_loc`、`stk_sku_lot`、`stk_lot_loc`、`stk_lot_att`、
`stk_lot_att_ext`、`stk_minus`、`stk_minus_log`、`stk_trans_log_{wh_id}`、
`stk_allocated`、`stk_picked`、`stk_hold`、`stk_pending`、`stk_qty_snapshot`

**库存初始化**
`stk_init_header`、`stk_init_detail`、`stk_init_out_log`、`stk_init_compare`
（三者均有 `_his` 历史版本）

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
- 调拨：`doc_alc_header`、`doc_alc_detail`
- 出库：`doc_do_header`、`doc_do_detail`、`doc_do_lack_detail`、`doc_do_wave`
- 收货：`asn_header`、`asn_detail`、`asn_excp_header`、`asn_excp_detail`
- 拣货／波次：`task_pick`、`rul_wave_header`、`rul_wave_detail`
- 盘点：`stk_cou_header`、`stk_cou_detail`、`stk_cou_item`

**主数据**
`md_warehouse`（门店）、`md_sku`（商品）、`md_supplier`（供应商）、
`md_location`（库位）、`md_cargo_owner`（货主）、`md_merchant`

**报表／历史**
`rpt_doc_do_header`、`rpt_doc_do_detail`、`report_do_header`、`report_do_detail`、
`his_doc_do_header`、`his_doc_do_detail`

## 常用查询片段

确认某门店分表是否存在：

```sql
SELECT table_name FROM information_schema.tables
WHERE table_schema = DATABASE() AND table_name = 'stk_trans_log_1607';
```

查看表结构（不确定字段时先用这个，不要凭记忆写 SQL）：

```sql
SELECT column_name, column_type, column_comment
FROM information_schema.columns
WHERE table_schema = DATABASE() AND table_name = '<表名>'
ORDER BY ordinal_position;
```

查看某表在库中的所有索引（排查慢查询时用）：

```sql
SELECT index_name, GROUP_CONCAT(column_name ORDER BY seq_in_index) AS cols, non_unique
FROM information_schema.statistics
WHERE table_schema = DATABASE() AND table_name = '<表名>'
GROUP BY index_name, non_unique;
```

## 注意事项

- 生产库一律只读，`SELECT` 之外一律不执行。
- 涉及大表（如 `stk_lot_loc`、`stk_minus`，生产量级 700 万行以上）时，
  必须带门店／时间等过滤条件，或在查询前先 `EXPLAIN` 确认走索引，避免全表扫描。
- 金额字段为 Decimal，聚合时保持 Decimal 运算，转 float 会丢精度。
