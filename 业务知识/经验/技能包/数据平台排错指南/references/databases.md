# 数据库连接与 DMatrix 配置机制

> **分享版说明**：本文件里的 RDS 主机地址、库清单、默认只读账号是**组织级基础设施**（与具体人无关），可直接复用；若团队自有机房/账号，按实际情况替换。
> **推荐查库方式**：统一走 `db-cli` 的 `dbq` 命令（实例名见主 SKILL.md 的「三环境实例速查」）。下文「MCP 连接方式」仅作备选，若团队没配 MCP 可跳过。

## 业务系统 MySQL（默认只读账号 db_viewer）

### 连接器 1：生产只读订单库

- **库**：`jy_order`
- **地址**：`rm-bp1q1459x6djo5kf0xo.mysql.rds.aliyuncs.com`（阿里云 RDS）
- **账号**：`db_viewer`（只读）
- **核心表**：

| 表 | 说明 | 关键字段 |
|----|------|---------|
| `order_data` | 订单主表 | store_id, order_create_date, pay_time |
| `order_item` | 订单明细 | vender_code(联营商编码), data_type, operations_nature, sku_id |
| `order_item_money` | 订单金额 | **pay_price(实付金额=销售额最源头)**, order_item_id |
| `order_item_money_promt` | 促销金额 | 促销分摊 |
| `order_refund` | 退款主表 | 退款状态 |
| `order_refund_item` | 退款明细 | 退款数量/金额 |
| `order_delivery` | 配送信息 | |
| `order_pos` | POS 订单 | |
| `order_group` | 订单组 | |

### 连接器 2：生产只读数据mysql库

- **库**：`jy_data`
- **地址**：`rm-bp13t7e0z001e04i05o.mysql.rds.aliyuncs.com`（阿里云 RDS）
- **账号**：`db_viewer`（只读）
- **核心表**：

| 表 | 说明 | 关键字段 |
|----|------|---------|
| `dmtx_data_serv_intf` | DMatrix 接口配置 | data_intf_code(接口编码), off_data_serv_extra_ids(离线取数ID) |
| `dmtx_data_serv_extra_config` | **DMatrix SQL 配置（核心）** | data_serv_code(数据集标识), **data_serv_extra_logic_code(实际SQL)**, ds_key(数据源), ds_type(1=MySQL/2=ES/3=Presto) |
| `dmatrix_data_bus_mysql_table` | 表映射配置 | src_tb_name, conn_id, tb_name, select_clause |
| `dmatrix_data_bus_import_mysql_single` | 拉链导入配置 | tb_name, bdm_tb, select_clause, where_clause |
| `dmatrix_data_bus_mysql_conn` | 数据源连接配置 | IP, 端口, 数据库名, 连接密钥 |
| `app_cus_joint_sku_sale_d` | 联营SKU销售日表 | dt, joint_code, joint_name, shop_id, sale_amt, sale_num |

## 三环境 RDS 主机总览（雅斯 yas / 好码特 hmt / 万客缘 wky）

> 只读账号统一 **db_viewer**（密码随团队而异，向用户确认），端口 3306。
> 设计：**一个 RDS 主机地址 = 一组库**，默认挂一个代表库；同主机其他库用 `库名.表名` 跨库查。
> 若团队改用了 MCP 连接器，把下表「主机地址」对应到连接器名即可（连接器命名规则自行对齐）。

### 雅斯 yas

| 主机地址 | 该主机上的全部库 |
|---------|----------------|
| rm-bp1151j106lak7koawo | jy_proto, jy_msg, jy_fund, jy_workflow, spider_flow, baize, jy_smart_store, jy_sso, t-gateway, xxl_job, jy_monitor, jy_ziwei, max_fire, market-spark, jy_assets |
| rm-bp17e7m4dk00or24aqo | jy_dcs, jy_cloudt_platform, jy_feixian, scm_wms, t_quanyou2, jy_cloudt, scm_scs, scm_pms, feixian_pms, t_quanyou, scm_tms, b_print, scm_sys, feixian_wms, tyloo, jy_glp, jy_tms, fire_im |
| rn-bp1x29z3g5k6lh201-clusterk2-l8（集群内网地址，主备等价） | jy_wms |
| rm-bp1wi1gw0g061fv6q9o | jy_market |
| rm-bp1lev83y71k6z29yuo | jy_search, zq_product, ty_product |
| rm-bp17bn2gkbf41pe0zxo | jy_batchstk, jy_roc, t_payment, jy_catering, jy_pms, jy_vc, jy_salestk, userdb, jy_aps, jy_after_sale, billdb, managementdb, gatewaydb, yb_oms, jy_hp, workflowdb, voucherdb, yb_pmc, yb_merchant, maindatadb, monitor, contractdb, jy_b2b, jy_eyun_ass, jy_yunbao, jy_dmt, budgetdb, assetdb, tcc |
| rm-bp1fmnl3s8v38wii6po | jy_finance, jy_finance_backup |
| rm-bp1q1459x6djo5kf0xo | jy_order, jy_order_history, jy_shield |
| rm-bp13t7e0z001e04i05o | jy_data, jy_azkaban, jy_dolphinscheduler, jy_cboard, jy_canal_manager |
| rm-bp1287bztg177w73loo | jy_star, jy_recommend |

### 好码特 hmt

| 主机地址 | 该主机上的全部库 |
|---------|----------------|
| rm-uf6ygz9g8a2mc395e7o | jy_proto, jy_msg, jy_fund, jy_workflow, spider_flow, baize, jy_smart_store, jy_sso, t-gateway, xxl_job, jy_monitor, jy_ziwei, max_fire, market-spark, jy_assets, fire_im |
| rm-uf6016128061p72r69o | jy_dcs, jy_cloudt_platform, jy_feixian, scm_wms, t_quanyou2, jy_cloudt, scm_scs, scm_pms, feixian_pms, t_quanyou, scm_tms, b_print, scm_sys, feixian_wms, jy_wms, tyloo, jy_glp, jy_tms |
| rm-uf61e2fl73rbsw14duo | jy_market |
| rm-uf6muy3y684w0479qjo | jy_data, jy_azkaban, jy_dolphinscheduler, jy_cboard, jy_canal_manager |
| rm-uf6j5t5gcvfkq4703co | jy_batchstk, jy_roc, t_payment, jy_catering, jy_pms, jy_vc, jy_salestk, userdb, jy_aps, jy_after_sale, billdb, managementdb, gatewaydb, yb_oms, jy_hp, workflowdb, voucherdb, yb_pmc, yb_merchant, maindatadb, monitor, contractdb, jy_b2b, jy_eyun_ass, jy_yunbao, jy_dmt, budgetdb, assetdb, tcc |
| rm-uf6220d4knio7q1q7co | jy_finance, jy_finance_backup |
| rm-uf6kt936oqs61bt590o | jy_order, jy_order_history, jy_shield |
| rm-uf6cq2nkk9pdl16yhio | jy_star, jy_recommend |

### 万客缘 wky

| 主机地址 | 该主机上的全部库 |
|---------|----------------|
| rm-bp1s9b14s350i8qer6o | jy_proto, jy_msg, jy_fund, jy_workflow, spider_flow, baize, jy_smart_store, jy_sso, t-gateway, xxl_job, jy_monitor, jy_ziwei, max_fire, market-spark, jy_assets, fire_im |
| rm-bp1980qxn7b4kkeaslo | jy_dcs, jy_cloudt_platform, jy_feixian, scm_wms, t_quanyou2, jy_cloudt, scm_scs, scm_pms, feixian_pms, t_quanyou, scm_tms, b_print, scm_sys, feixian_wms, jy_wms, tyloo, jy_glp, jy_tms |
| rm-bp1g79f3c787j2n80zo | jy_market |
| rm-bp12n70q94053f7jzto | jy_search, zq_product, ty_product |
| rm-bp146349d69exj16xto | jy_batchstk, jy_roc, t_payment, jy_catering, jy_pms, jy_vc, jy_salestk, userdb, jy_aps, jy_after_sale, billdb, managementdb, gatewaydb, yb_oms, jy_hp, workflowdb, voucherdb, yb_pmc, yb_merchant, maindatadb, monitor, contractdb, jy_b2b, jy_eyun_ass, jy_yunbao, jy_dmt, budgetdb, assetdb, tcc |
| rm-bp1u078v2f8uapo8y7o | jy_finance, jy_finance_backup |
| rm-bp1s81h48m38tb455fo | jy_order, jy_order_history, jy_shield |
| rm-bp113l9wkuaiu310rco | jy_data, jy_azkaban, jy_dolphinscheduler, jy_cboard, jy_canal_manager |
| rm-bp1zm0l0jmh3m757n6o | jy_star, jy_recommend |

## 连接方式（db-cli 实操，推荐）

- 命令：`dbq <target> "<SQL>"`，target 写法见主 SKILL.md「数据库连接方式」。
- 同主机切换库：连接器默认库不是目标库时，SQL 里用 `库名.表名` 跨库查（账号有该库权限即可）。
- 连不上 → 加 IP 白名单（外网常被阿里云安全组挡），用团队内部的 `aliyun-tool`（jar 位于 `<代码仓库根目录>`）：

```bash
cd <代码仓库根目录>
java -jar -Dmerchant=yas aliyun-tool-1.0.0-SNAPSHOT.jar   # yas / hmt / wky 三环境分别跑
```

跑起来会列出该环境所有 RDS 实例序号+地址，按序号给要连的实例授权白名单。授权后仍连不上：查账号只读/库名拼写。

## 连接方式（MCP 连接器，备选）

> 仅当团队已配置 MCP 连接器时使用。工具名 = `mcp__<连接器名>__<方法>`，方法：`execute_query` / `list_tables` / `describe_table`。同主机切换库用 `库名.表名` 跨库查；长期用则改连接器配置并重载。

## Hive 数仓连接

> ⚠️ **从本机直连数仓，用公网地址**（权威见主 SKILL.md「Hive 数仓（Presto 查询引擎）」一节）：
> 雅斯 `jdbc:hive2://114.55.7.61:10000`、万客缘 `jdbc:hive2://121.40.245.183:10000`（均免密 user=root, auth=NONE）。
> 用 db-cli 的 `yas-hive`/`wky-hive`（pyhive 直连）或 `yas-presto`/`wky-presto` 即可；**下方 `10.128.x.x` / `10.20.1.15` 是集群内网地址，仅 Azkaban / 数仓执行节点可达，从本机连会被安全组挡——勿再用它们做本机直连。**

### 直连配置（jy-data-bus application-test.properties，集群内网拓扑参考）

```properties
# Hive（ZooKeeper 服务发现）
dynamic.datasource.hive-data-warehouse.url=jdbc:hive2://10.128.62.92:2181,10.128.62.91:2181,10.128.62.90:2181/;serviceDiscoveryMode=zooKeeper;zooKeeperNamespace=hiveserver2

# Presto（查询引擎）
dynamic.datasource.presto-data-warehouse.url=jdbc:presto://10.128.62.91:7520/hive
dynamic.datasource.presto-data-warehouse.username=root
```

### Hive 执行节点（Azkaban）

- **JDBC URL**：`jdbc:hive2://10.20.1.15:10000`（Azkaban 执行节点上的 beeline）
- **用户名**：`root`
- **执行引擎**：TEZ（主）/ MR / Spark

### Azkaban 调度

- **地址**：`http://10.128.62.91:9081`
- **项目名**：`yas_test`（测试环境）

## DBX（数据库管理平台）

业务数据库连接信息不存储在代码仓库中，通过 **DBX 服务** 集中管理：

```properties
dbx.address=10.128.62.36
dynamic.datasource.jy-data-slave.token=38779f8407a74dcb967ce99ee2fd5b0c
dynamic.datasource.jy-data-master.token=38779f8407a74dcb967ce99ee2fd5b0c
```

**加载流程**：
1. 配置文件只写 `token`
2. `DynamicDataSourceRegister.java` 启动时解析 token
3. 通过 DBX 服务获取真实 IP/端口/用户名/密码
4. 创建 `DbxDruidDataSource` 或 `DbxHikariDataSource`

## DMatrix 数据查询链路（完整）

```
前端请求
    ↓
jy-datareport Controller (JtopDetlController / SkuDtlRptController / ...)
    ↓
BaseDlController.queryData()
    ↓
DmatrixQueryService.queryData()  ← 解析 @DmatrixClassMeta 注解
    ↓
JyDmatrixUnifiedDataServiceCaller.call()  ← Dubbo RPC
    ↓
jy-data-bus (DMatrix 服务端)
    ↓
DataServiceIntfCoreServiceImpl.coreHandle()
    ├── 根据 dataIntfCode 查 dmtx_data_serv_intf 获取接口配置
    └── 创建 OfflineDataQueryThread
        ├── 查 dmtx_data_serv_extra_config 获取 SQL (data_serv_extra_logic_code)
        ├── 解析 SQL 模板（SqlXmlReader，支持 <if>/<forEach> 等标签）
        └── ISensitiveSqlExecService.execute(dsType, dsKey, sql)  ← 执行查询
            ├── ds_type=1 → MySQL
            ├── ds_type=2 → Elasticsearch
            └── ds_type=3 → PrestoSQL (Hive 数仓)
```

## 关键查询 SQL（排查时直接用）

### 查某接口的实际 SQL

```sql
-- 1. 查接口配置
SELECT data_intf_code, data_intf_name, off_data_serv_extra_ids
FROM dmtx_data_serv_intf
WHERE data_intf_code = 't1_dl_jtop_detl';

-- 2. 查实际 SQL
SELECT data_serv_code, data_serv_extra_logic_code, ds_key, ds_type
FROM dmtx_data_serv_extra_config
WHERE data_serv_code IN ('t1_dl_jtop_list', 't1_dl_jtop_total');
```

### 查拉链同步配置

```sql
SELECT id, tb_name, conn_id, bdm_tb, select_clause, where_clause
FROM dmatrix_data_bus_import_mysql_single
WHERE tb_name LIKE '%joint%' OR bdm_tb LIKE '%joint%';
```
