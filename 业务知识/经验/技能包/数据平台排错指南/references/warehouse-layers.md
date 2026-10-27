# 数仓分层详细说明与核心表血缘

## 分层架构

```
业务系统 MySQL
    │
    │ bdm_*_chain: 业务数据同步（SyncData.py 增量拉链）
    ▼
BDM 层 (199 个 chain Job)
    │
    │ fdm_*_chain: 基础明细层（数据清洗标准化）
    ▼
FDM 层 (199 个 chain Job)
    │
    ├──→ DIM 层 (21 个脚本: 维度表，每天 INSERT OVERWRITE 全量刷新)
    │
    │ fdm → gdm: 关联多表 + 业务逻辑加工
    ▼
GDM 层 (58 个脚本: 通用明细宽表)
    │
    │ gdm → app: 聚合汇总
    ▼
APP 层 (104 个脚本: 应用汇总指标)
    │
    │ hive2mysql: 同步到 MySQL
    ▼
MySQL ADS 层 (结果库)
    │
    │ jy-data-bus 配置 API
    ▼
前端展示
```

## 各层详细

### BDM 层（Business Data Model）

- **职责**：从业务系统 MySQL 同步原始数据到 Hive
- **命名规则**：`bdm_{源系统}_{表名}_chain`
- **同步方式**：增量拉链（通过 `update_date` 字段只同步变更数据，REPLACE INTO 实现 upsert）
- **分区**：`dp = 'ACTIVE'` 表示有效分区
- **示例**：
  - `bdm_jy_order_order_data_chain` — 订单主表
  - `bdm_jy_order_order_item_chain` — 订单明细
  - `bdm_jy_finance_stock_general_ledger_detail_chain` — 库存总账明细
  - `bdm_jy_sso_shop_chain` — 门店
  - `bdm_jy_wms_stk_lot_loc_chain` — 批次库位

### FDM 层（Foundation Data Model）

- **职责**：贴源层，保留原始结构，数据清洗
- **命名规则**：`fdm_{源系统}_{表名}_chain`
- **与 BDM 的关系**：BDM 和 FDM 基本一一对应，BDM 是临时表，FDM 是正式表
- **分区**：`dp = 'ACTIVE'`

### DIM 层（Dimension）

- **职责**：维度表，描述业务实体（谁/哪里/什么）
- **命名规则**：`dim_{实体名}`
- **刷新方式**：每天 `INSERT OVERWRITE` 全量重新生成
- **核心维度表**：

| 表 | 说明 | 来源 |
|----|------|------|
| `dim_store` | 门店维度 | `fdm_jy_sso_shop_chain`（过滤测试/中转/仓门店） |
| `dim_itm_store_sku` | 商品门店SKU维度 | 包含 store_dept_id, pruch_dept_id, operations_nature, categ_lvl1~4 |
| `dim_user` | 用户维度 | 包含 inviter_id, first_ord_id |
| `dim_categ` | 品类维度 | categ_lvl1~4 |
| `dim_scm_supplier` | 供应商维度 | |
| `dim_sku` | SKU 维度 | |
| `dim_org_pruch_dept` | 采购部门维度 | |
| `dim_cam_promotion` | 促销维度 | |
| `dim_cam_coupon` | 优惠券维度 | |

### GDM 层（General Data Model）

- **职责**：通用明细宽表，关联多张 FDM/DIM 表，实现核心业务逻辑
- **命名规则**：`gdm_{业务域}_{描述}`
- **刷新方式**：按日期分区 `INSERT OVERWRITE`，通过 `tmp_pay_ord_update_dt` 控制增量
- **核心宽表**：

| 表 | 说明 | 重要性 |
|----|------|--------|
| `gdm_ord_detl` | 订单明细宽表 | GDM 基础 |
| **`gdm_ord_pay_detl`** | **成交订单宽表** | **数仓最热的表，48 个下游脚本消费** |
| `gdm_ord_refnd_detl` | 退款明细 | |
| `gdm_ord_pay_detl_mer` | 商户支付明细 | 联营相关 |
| `gdm_idx_ord_dept_sale_d` | 部门销售日汇总 | 11 个下游消费 |
| `gdm_idx_ord_sku_sale_d` | SKU 销售日汇总 | |
| `gdm_idx_jtop_store_sku_d` | 联营商门店SKU日汇总 | 联营商业绩报表查的 Hive 表 |
| `gdm_store_sku_ops_nature_chain` | 门店SKU经营性质时间线 | operations_nature=2 为联营 |
| `gdm_sale_cost_sku_d` | 销售成本SKU | |
| `gdm_inv_sku_stock_da` | SKU库存日汇总 | |

**`gdm_ord_pay_detl` 成交口径**（非常重要）：
1. 按支付时间统计
2. 剔除当天支付当天取消的订单
3. 剔除当天支付当天完成退款的数据（部分退扣减/整单退剔除）
4. 剔除礼品卡订单（ord_type NOT IN (50, 51, 53)）

### APP 层（Application）

- **职责**：面向业务场景的汇总指标，GROUP BY 后的聚合数据
- **命名规则**：`app_{业务域}_{描述}_{周期}`（_d=日/_w=周/_m=月/_h=小时）
- **核心 APP 表**：

| 表 | 说明 |
|----|------|
| `app_ord_store_sale_data_d` | 门店销售日汇总（GMV/订单数/同环比） |
| `app_sku_sales_rank` | SKU 销售排行 |
| `app_t11do_market_board_d/h/m/w` | 营销看板（日/时/月/周） |
| `app_tek_realtime_statis_h` | 实时统计小时表 |
| `app_ord_store_user_rettn_data_d/m/w` | 用户留存 |
| `app_cus_user_growth_d` | 用户增长 |
| `app_stk_sku_d` | SKU 库存日 |
| `app_inv_picker_detl_d` | 拣货明细 |
| `app_actvy_anlyz_tot` | 活动分析汇总 |

### ADS 层

- **职责**：MySQL 结果库，供前端毫秒级查询
- **同步方式**：
  - `hive2mysql_*` Job（141 个，离线同步脚本）
  - `jy-warehouse-baize-datapulse`（数据脉冲推送，`ON DUPLICATE KEY UPDATE` 幂等写入）

## 核心数据链路：门店销售

```
fdm.fdm_jy_order_order_data_chain (订单主表)
fdm.fdm_jy_finance_market_*_chain (营销分摊)
    │
    ▼
gdm_ord_detl (订单明细) ──▶ gdm_ord_pay_detl (成交订单宽表, 扣退款/取消/礼品卡)
gdm_ord_refnd_detl (退款明细)           ↑ 关联 dim_store / dim_itm_store_sku
    │                                   ↑ 分摊营销优惠
    ▼
gdm_idx_ord_dept_sale_d (部门销售日汇总)
    │
    ▼
app_ord_store_sale_data_d (门店销售日汇总, 含同环比 LAG 窗口函数)
    │
    ▼ hive2mysql
MySQL ads_app_ord_store_sale_data_d → DMatrix API → 前端
```

## 业务域与脚本数量

| 业务域 | 脚本数 | 核心脚本 |
|--------|--------|---------|
| 订单销售 | 60 | gdm_ord_pay_detl, gdm_idx_ord_dept_sale_d, app_ord_store_sale_data_d |
| 用户行为 | 30+ | gdm_cus_buy_statis, app_cus_user_growth_d, adm_cus_profile_pay_ord_cnt |
| 库存 | 20+ | gdm_inv_sku_stock_da, app_stk_sku_d, app_inv_picker_detl_d |
| 商品分析 | 15+ | app_sku_sales_rank, app_sku_sales_detl_d |
| 营销活动 | 15+ | app_actvy_anlyz_tot, app_cam_promt_discount_tot |
| 供应商 | 10+ | gdm_idx_suplr_store_sku_d, app_supplier_pruch_rcv_po_tot |
| 流量 | 10+ | gdm_trfc_log, gdm_trfc_statis |
| 仓配 | 10+ | app_scm_wms_out_do_sku_d |
| 社群团购 | 5+ | gdm_community_ord_pay_detl, app_community_order_detl |
| 礼品卡 | 5+ | app_gift_card_detl, app_gift_card_tot |

## 调度时序（典型）

```
凌晨 00:30  dim_store（维度表）
凌晨 01:00  gdm_ord_detl（订单明细）
凌晨 01:30  gdm_ord_pay_detl（成交订单宽表）
凌晨 02:00  gdm_idx_ord_dept_sale_d（部门销售汇总）
凌晨 02:30  app_ord_store_sale_data_d（门店销售汇总）
凌晨 03:00  hive2mysql / baize 脉冲（推送到 MySQL）
```

## 联营判定口径差异（注意！）

- **Jtop 脚本**（`gdm_idx_jtop_store_sku_d.py`）：用 `operations_nature=2` + `merchant_id`
- **saleAmt 追溯文档**：用 `data_type=1` + `vender_code`
- 两处口径略不同，核数对不上时先确认用的是哪支

## 核心字段血缘

### 销售额 (sale_amt)

```
业务库: jy_order.order_item_money.pay_price (实付金额)
    ↓ 同步
FDM: fdm_jy_order_order_item_money_chain.pay_price
    ↓ GDM 加工
GDM: gdm_ord_pay_detl.pay_amt / actl_sale_amt (扣退款后)
    ↓ APP 汇总
APP: app_ord_store_sale_data_d.sale_amt / gmv
    ↓ 推送
ADS: ads_app_ord_store_sale_data_d.sale_amt
```

### 联营商编码

```
业务库: jy_order.order_item.vender_code
    ↓
GDM: gdm_ord_pay_detl.vender_code / gdm_idx_jtop_store_sku_d.jtop_code
    ↓
报表: JtopDetlController → t1_dl_jtop_detl → jtop_code
```
