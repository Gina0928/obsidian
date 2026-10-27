# 各项目详细说明

## 数据流转关系

```
业务系统数据库 (MySQL)
    │
    ▼
jy-warehouse-sync (数据同步: MySQL → Hive BDM/FDM)
    │
    ├─────────────────────────────┐
    ▼                             ▼
jy-warehouse-offline          jy-warehouse-flink-new
(离线批处理: FDM→DIM→GDM→APP)  (实时: Kafka→Flink→ES/MySQL)
    │                             │
    ▼                             │
jy-warehouse-baize-datapulse      │
(Hive APP → MySQL ADS 推送)       │
    │                             │
    ▼                             ▼
MySQL 结果库 (ADS 层)
    │
    ├──────────┬──────────────────┐
    ▼          ▼                  ▼
jy-data-bus  jy-data-tek     jy-datareport
(DMatrix     (分析BFF,        (报表服务,
 数据总线)    RPC转发)         50+接口)
    │          │                  │
    ▼          ▼                  ▼
管理后台前端   数据分析门户
(pages-admin)  (tek-pages)

jy-star-map (标签平台) ← Kafka → 用户行为数据 → Presto ETL → MySQL
```

## 1. jy-warehouse-offline（离线数仓）

- **定位**：离线数仓核心，195+ Python 脚本 + 778 个 Azkaban Job
- **技术栈**：Python + Hive SQL + Azkaban 调度
- **核心目录**：
  - `az_job/scripts/` — 195 个 Python 脚本（按 dim_/fdm_/gdm_/app_ 前缀分层）
  - `az_job/*.job` — 778 个 Azkaban 调度任务
  - `BigTools/` — 公共工具库（HiveTask.py、MysqlOperator.py、Calendar.py 等）
- **执行引擎**：TEZ / MR / Spark（TEZ 为主）
- **Hive 连接**：`jdbc:hive2://10.128.62.91:10000`（生产）/ `10.20.1.15:10000`（Azkaban 执行节点）
- **Azkaban**：`http://10.128.62.91:9081`
- **业务域**：订单销售(60脚本) > 用户行为 > 库存 > 商品分析 > 营销活动 > 供应商结算 > 仓配 > 流量 > 社群团购 > 礼品卡 > 财务

## 2. jy-warehouse-sync（数据同步）

- **定位**：MySQL ↔ Hive 数据搬运 + 实时看板脚本
- **技术栈**：Python + Hive JDBC + MySQL
- **核心目录**：
  - `scripts/workspace/` — 72 个同步脚本（实时看板 + 维度同步 + GDM 层）
  - `scripts/view/` — 9 个 SQL 视图定义（仓配实时看板）
  - `scripts/workspace-baize/` — 10 个货架数据分析脚本
  - `tools/SyncData.py` — 数据同步核心工具类（增量同步、批量提交、REPLACE 机制）
- **调度**：crontab（每 2 分钟 ~ 每日凌晨）
- **服务器**：s11-sync-0001，路径 `/usr/local/kettle/data-integration/workspace`

## 3. jy-warehouse-flink-new（Flink 实时计算）

- **定位**：实时数据流处理
- **技术栈**：Flink 1.12.7 + Hive 3.1.1 + Kafka + Elasticsearch
- **核心作业**：
  - `OrdSbjJob` — 订单主题（Kafka canal-json → 聚合 → ES/MySQL）
  - `OrdSkuJob` — 订单 SKU
  - `ShopHotValJob` — 门店热销值
  - `SpotSkuJob` — 现货 SKU 分析
  - `StoreSkuJob` — 门店 SKU 维表同步
  - `DMatrixSlowInterfaceMonitorJob` — DMatrix 慢接口监控
- **Flink SQL 配置**：`jy-warehouse-flink-job/src/main/resources/flink-sql/`（XML 格式）

## 4. jy-warehouse-baize-datapulse（数据脉冲）

- **定位**：Hive APP 层 → MySQL ADS 层推送
- **技术栈**：Python + MySQL
- **核心功能**：门店维度指标加工（idx_d）、货架维度索引（shelf_idx_d）、品类 SKU 维度
- **工具库**：`tools-baize/`（MysqlTask.py、Calendar.py、SendMail.py）

## 5. jy-data-bus（DMatrix 数据总线）

- **定位**：数据服务总线，通过可视化配置将 SQL 封装成 API
- **部署名**：`jy-dmatrix-web`，访问路径 `/dmatrix`
- **技术栈**：Spring Boot + MyBatis + Dubbo + Elasticsearch
- **模块**：api（网关）/ client（SDK）/ ext（扩展）/ service（核心）
- **核心机制**：
  - 数据源管理（多数据源注册，DBX Token 方式获取连接）
  - 数据服务接口配置（`dmtx_data_serv_intf` 表存接口配置）
  - SQL 配置（`dmtx_data_serv_extra_config` 表存实际 SQL，`data_serv_extra_logic_code` 字段）
  - 通过 Dubbo RPC 对外提供 `JyDmatrixUnifiedDataService`
- **ds_type 枚举**：1=MySQL, 2=ES, 3=PrestoSQL

## 6. jy-datareport（报表服务）

- **定位**：报表服务（jy-dl-web），50+ REST 接口
- **技术栈**：Spring Boot 2.1.2 + MyBatis + Presto + Hive JDBC + Redis + Kafka + Dubbo
- **模块**：common / framework(动态数据源+SQL XML引擎) / domain(DTO/VO) / dao / service / permission / jy-dl-web(Web层) / code-gen
- **核心机制**：
  - `@DmatrixClassMeta(dataIntfCode="t1_dl_xxx")` 注解标记 VO，`DmatrixQueryService` 自动解析并 RPC 调用 DMatrix
  - `RequestAdvice` 自动注入权限参数（`__shopIds__`、`__purchDeptIds__`）
  - `BaseDlController` 提供 queryData/queryDataList/export 通用方法
- **业务域**：实时看板 / 商品分析(19控制器) / 供应商分析(8控制器) / 财务 / 配送 / 仓配 / 库存 / 供应链 / 运营

## 7. jy-data-tek（数据分析 BFF）

- **定位**：BFF 层，通过 DMatrix RPC 转发请求，本身不直接查库
- **技术栈**：Spring Boot + Dubbo（消费者）+ ShardingSphere + Nacos
- **核心业务**：用户分析、T+ 分析、视图服务（总览看板/热力图/客诉/促销/实时指标）
- **调用方式**：`JyDmatrixUnifiedDataServiceCaller.call("接口编码", parameters)`

## 8. jy-star-map（星图标签平台）

- **定位**：用户标签与行为分析，规则引擎转 Presto SQL 执行 ETL
- **技术栈**：Spring Boot + MyBatis + Presto + Kafka + Quartz + QLExpress + Groovy
- **核心功能**：标签管理（定义/版本/分层/目录树）、行为分析、人群圈选、标签 ETL（Kafka 驱动 + Quartz 调度）

## 前端项目

- **jy-data-tek-pages**：Vue 2.6 + Element UI，运营分析门户（dashboard/operationAnalysis/tplus）
- **jy-datareport-pages-admin**：Vue 2.5 + Webpack 3，管理后台（biconfig/indicator/source/role/user）

## 技术栈汇总

| 类别 | 技术 |
|------|------|
| 后端 | Spring Boot 2.x, JDK 1.8, Maven |
| ORM | MyBatis |
| 数据库 | MySQL 8.x |
| 缓存 | Redis (Redisson) |
| 消息队列 | Kafka |
| 大数据 | Flink 1.12, Hive 3.1 |
| 搜索 | Elasticsearch |
| 调度 | Azkaban (离线), crontab (同步), Quartz (标签) |
| 脚本 | Python 2/3 |
| 前端 | Vue 2.x + Element UI |
| 私服 | Nexus (maven.myt11.com) |
