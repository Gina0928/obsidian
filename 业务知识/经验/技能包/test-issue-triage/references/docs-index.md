# D:\cl-wms\docs 文档索引（排查前必查）

排查前先按本索引定位并读取相关文档，**不要全量读取**（目录共 62 个 md，
其中单个文件最大 50KB+）。

## 使用方式

1. 读 `D:\cl-wms\docs\README.md` 了解目录约定（文档有 `status` 生命周期：
   `草案` / `已定稿` / `已废弃`，**已废弃的直接跳过**）。
2. 按下表按场景命中 → 只读命中的文件。
3. 文件名未命中时，用 Glob（`D:\cl-wms\docs\**\*.md`）按关键词搜文件名，
   仍无命中再说明「无相关文档」并继续排查，不要卡住。
4. 文档结论与数据库实测不一致时，**以数据库实测为准**，并把差异写出来。

## 慢 SQL / 接口超时 → `docs\优化\`

| 文档 | 针对对象 |
|---|---|
| `PosDoSync_listData慢SQL优化.md` | PosDo 同步列表查询 |
| `PosDoSync_retry性能优化.md` | PosDo 重试逻辑 |
| `PrintTaskDao.findPageTagCount慢SQL增量诊断.md` | 打印任务分页计数 |
| `RtvShipBizService.getJoinStkOptDTOS超时接口优化.md` | 退货出库关联库存 |
| `StkGalController.cancel接口超时诊断与优化方案_2026-08-07.md` | 损益单取消 |
| `StkMinusManager.findMinusBySkuPage慢SQL诊断与优化方案_2026-08-06.md` | 缺量分页 |
| `StkQueryController.findPageBySkuLot超时接口优化.md` | 库存批次分页（51KB，大文档） |
| `StkSkuLotDao.findPageList慢SQL终版诊断报告-已修复.md` | 批次分页（已修复，看结论即可） |
| `adjustPriceTagList超时接口优化交接文档.md` | 调价标签列表 |
| `findByTransDate超时接口优化.md` | 按业务日期查流水 |
| `findCountTransLogs慢SQL优化.md` | 流水计数 |
| `findListGroupBySku慢SQL优化.md` | 按商品分组列表 |
| `findSkuPairBySourceSkuIds慢SQL优化.md` | 商品配对查询 |
| `finishCount超时接口优化交接文档.md` | 盘点完成（33KB） |
| `generateReport盘点报告接口超时优化.md` | 盘点报告生成 |
| `listSkuPriceLoc慢SQL优化.md` | 商品价格库位列表 |
| `stkOrderPosDo超时接口优化交接文档.md` | 库存单据 PosDo（36KB） |

> 注意：`StkMinusManager.findMinusPage慢SQL诊断与优化方案_2026-08-05.md`
> 是**空文件（0 字节）**，读取会得到空内容，直接跳过改用 06 版。

## 功能修复 / 存量订正 → `docs\优化\`

| 文档 | 内容 |
|---|---|
| `分配规则并发新建重复修复_2026-09-03.md` | 分配规则并发重复 |
| `盘点损溢无可用批次库存跳过修复.md` | 盘点损溢跳过逻辑 |
| `调拨入库lotatt01真实供应商批次修复_存量订正与发布说明_2026-09-02.md` | 调拨入库批次订正 |
| `调拨出入库批次生产日期透传修复设计_2026-09-02.md` | 生产日期透传 |
| `调拨回加工厂收货价格回退设计_2026-09-03.md` | 回加工厂价格回退 |

## 表用途 / 归档设计 → `docs\需求与设计\`

| 文档 | 对应表 |
|---|---|
| `stk_trans_log用途与归档设计.md`（31KB） | stk_trans_log |
| `stk_trans_log_sku用途与归档设计.md` | stk_trans_log_sku |
| `stk_doc用途与归档设计.md`（27KB） | stk_doc |
| `stk_hold用途与归档设计.md` | stk_hold |
| `stk_minus_log用途与归档设计.md` | stk_minus_log |
| `stk_minus与stk_minus_log表用途与引用分析.md` | stk_minus / stk_minus_log |
| `负库存平负逻辑与链路归档_20261012.md` | **负库存平负链路（手动/自动/盘点）、四道校验关卡、联营判定口径** |
| `stk_lot_att批次表归档设计.md` | stk_lot_att |
| `stk_qty_snapshot用途与归档设计.md` | stk_qty_snapshot |
| `stk_cou_report_header用途与归档设计.md` | stk_cou_report_header |
| `pos_do用途与归档设计.md`（25KB） | pos_do |
| `async_msg_record用途与归档设计.md` | async_msg_record |
| `dataArchive配置review_2026-08-11.md` | 归档任务配置总览 |

## 分区 / DTS → `docs\需求与设计\`

- `库存六表wh_id分区_DTS执行方案_2026-08-27.md`
- `库存六表wh_id分区_DTS方案与pt-osc对比_2026-08-27.md`

## 业务流程

| 文档 | 场景 |
|---|---|
| `需求与设计\入库业务流程与数据表说明.md`（46KB） | 入库全链路 |
| `需求与设计\加工详细设计方案.md`（35KB） | 加工业务 |
| `需求与设计\asn\入库单接入逻辑说明文档.md` | ASN 入库单接入 |
| `需求与设计\asn\收货逻辑说明文档.md` | 收货 |
| `需求与设计\asn\PO明细取消接口设计.md` | PO 取消 |
| `需求与设计\STK_COU_IN_SIDE_FLAG枚举应用逻辑分析.md` | 内外仓标志枚举 |
| `需求与设计\StkLotAttExt批次扩展表初始化任务使用指南.md` | 批次扩展表初始化 |
| `接口文档\加工接口文档.md` | 加工接口 |

## 大表与架构

- `docs\大表优化诊断报告_2026-08-05.md`（25KB）— 大表诊断
- `docs\大表收敛方案_2026-08-05.md`（35KB）— 大表收敛
- `架构\项目异步处理机制手册.md` — 异步事件/事务回滚机制（排查异步问题时必读）

## 运维与初始化

- `部署运维\新增商户门店信息初始化指南.md` — 门店初始化（门店相关差异先看这个）
- `部署运维\30个SKU批次成本价修正方案.md` — 成本价修正
- `测试\损益单审批状态卡住排查交接文档.md` — 损益单审批卡住

## 项目规范

- `D:\cl-wms\RULES.md` — 开发规范（模块划分、命名、包结构）
- `D:\cl-wms\README.md` — 工程总览
- `D:\cl-wms\claude.md` — 项目自身对 AI 的约定
