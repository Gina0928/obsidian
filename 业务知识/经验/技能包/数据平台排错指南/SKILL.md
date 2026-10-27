---
name: 数据平台排错指南
description: 数据平台排错指南（分享版）。当需要了解数据平台有哪些项目/数据库、追报表数据来源、排查数据问题、理解数仓分层、或需要"大局观+条线路径"来定位数据相关问题时使用。关键词：数据平台、数仓、报表、数据来源、业务表、Hive、DMatrix、jy-datareport、jy-data-bus、jy-warehouse-offline、联营商、销售额、数据排查。
agent_created: true
---

# 数据平台排错指南

> **分享版说明**：原作者在本地把绝对路径、个人目录、db-cli 安装位置全部抽成了下方「本地配置」。
> 安装到新机器后，**首次使用前请先按「本地配置」一节向用户确认那几个路径/账号**，再执行查库或读本地文档的动作。
> 本文所有 `<占位符>` 都对应那一节，确认后用真实值替换即可。

## 本地配置（首次使用请向用户确认）

本技能依赖以下"随机器/团队而变"的配置。不要硬编码猜测——拿到后可在会话内记忆，或写入本技能目录下的 `config.md` 方便复用。

| 配置项 | 占位符 | 怎么问用户 |
|--------|--------|-----------|
| 数据平台文档根目录 | `<数据平台文档根目录>` | "你们的数据平台知识库/排查记录/项目文档根目录在哪？"（原作者示例：`.../s11backend/数据后端项目/数据平台/`） |
| 前端仓库根目录 | `<前端仓库根目录>` | "各前端仓库（`*-front`）的平级父目录在哪？" |
| 代码仓库根目录 | `<代码仓库根目录>` | "后端/数仓代码与内部工具（如 aliyun-tool 加白名单 jar）放在哪个本地根目录？" |
| 后端/数仓代码根目录 | `<后端代码根目录>` | 通常 = `<代码仓库根目录>/s11backend/数据后端项目/`，确认后所有 `jy-warehouse-*`、`jy-datareport` 等仓库名即其下的子目录名 |
| 数据库查询方式 | — | 默认推荐 `db-cli`（见下）；若团队用 MCP 连接器，问清连接器命名规则再对应 |
| 只读账号/密码 | — | 若团队只读账号与「数据库连接」节不同，向用户询问（本文默认 `db_viewer`，密码随团队而异） |

### 数据库查询入口（db-cli，推荐）

统一走 `db-cli` 技能提供的 `dbq` 命令（安装 db-cli 后可用，建议先 `alias dbq="<db-cli 安装路径>/scripts/dbq"`）。
若用户**未安装 db-cli**：直接询问"你们平时怎么连这些库？"（MCP 连接器名 / 直连 pymysql 脚本 / 其他），按用户实际方式替换下方所有 `dbq ...` 示例。

> 本文所有 `dbq ...` 示例即"数据库查询命令"的占位，换成用户实际可用的查询方式即可。

## 目的

提供数据平台的"大局观 + 条线路径"，让 AI 或新人进来就知道：有哪些项目、有哪些数据库、数据怎么流转、遇到问题从哪条线进。

## 铁律（踩过的坑）

0. **项目分「雅斯」和「万客缘」两套分支代码 + 两套数据环境**：代表两个不同商家/客户的定制分支，代码有区别（项目基本相同、只是分支区别）。**不特意声明是哪一家时，默认就是雅斯。** 涉及万客缘会显式说明。数据也分环境——雅斯是「生产只读」那批库（`jy_order`/`jy_data`/`jy_batchstk`/`jy_finance` 等），万客缘是另一套业务库。⚠️ 切勿把雅斯误当万客缘。
1. **问"XX 查的哪个业务表"时，先翻 `<数据平台文档根目录>/` 目录的已有排查记录**，不要绕去数据库/代码现查。那里沉淀了大量业务表映射结论。
2. **"业务表" = 业务系统侧的 MySQL 源表**（如 `jy_order.*`、`jy_finance.*`），**≠ Hive 数仓层**（`gdm_*`/`fdm_*`/`dim_*`/`app_*` 等）。数仓表是加工后的，不是业务表。
3. **查数据库统一走 `db-cli` 脚本**（`dbq` 命令，由 db-cli 技能提供），这是推荐的数据库查询入口。MCP 连接器也可用，工具名规则见 `references/databases.md`。实例清单用 `dbq --list` 看，库→实例映射见下方「数据库连接方式（统一走 db-cli）」。四环境（雅斯/好码特/万客缘/测试）共 35 个实例，只读账号统一 `db_viewer`（密码见数据库连接节；测试环境账号可能不同，向用户确认）。
4. **DMatrix = jy-data-bus**，是数据服务总线，不是某个报表项目。报表项目（jy-datareport、jy-data-tek）通过 RPC 调用 DMatrix 获取数据。
5. **改 ETL SQL 必过 Hive 坑，改完先 `EXPLAIN` 预检再交重跑**：
   - ① `COUNT(*) AS cnt` 与 `ROW_NUMBER() OVER(ORDER BY cnt ...)` **不能写同一层 SELECT**——Hive 窗口 ORDER BY 只认 GROUP BY 输入列、不认聚合别名，报 `SemanticException: ... not in GROUP BY key 'cnt'`。必须分层：内层 GROUP BY 产出真列，外层再做窗口。
   - ② ETL 脚本里 SQL 的 `` \` ``（反斜杠+反引号）是给 **beeline 走 bash 的转义**（`HiveTask.__run_sql_in_hive` 用 `beeline -e` 执行），Hive 收到前 bash 已吃掉反斜杠。用 pyhive/JDBC 直连验证时必须先 `replace("\\`","`")` 还原，否则会误报 `ParseException character '\\' not supported here`。
   - ③ **`GROUP BY 1` 序数不可用**（本环境 Hive 版本）：`SELECT CASE ... END AS x, COUNT(*) ... GROUP BY 1` 报 `Expression not in GROUP BY key '...'`。CASE 桶要放在**子查询内算成真列**，外层 `GROUP BY 列名`。
   - ④ **FDM 拉链表列名先 DESCRIBE 再写 SQL**：如 `fdm_jy_wms_stk_lot_att_chain` 没有 `source_sku_id`（那是上游 WMS 批次表的列），列名是 `sku_id` 且存 **WMS 侧 ID**——业务商品 ID ≠ 拉链表 ID（如商品 990297 对应 sku_id=103701），按商品 ID 过滤会静默返回空结果而非报错。
   - 预检方法：桩掉 HiveTask 提取 f-string 真实 SQL（run_date 已代入）→ `EXPLAIN <sql>`（只编译不执行）→ 通过再交数仓值班重跑。

## 项目全景（10 个子项目）

| 项目 | 一句话定位 | 类型 |
|------|-----------|------|
| **jy-warehouse-offline** | 离线数仓核心，195+ Python 脚本 + 778 个 Azkaban Job，Hive SQL 加工 | Python/Hive |
| **jy-warehouse-sync** | 数据同步，MySQL → Hive 增量拉链同步 + 实时看板脚本 + crontab 调度 | Python |
| **jy-warehouse-flink-new** | Flink 实时计算，订单主题/门店热销/现货SKU等实时作业 | Java/Flink |
| **jy-warehouse-baize-datapulse** | 数据脉冲，Hive APP 层 → MySQL ADS 层推送（货架/门店维度指标） | Python |
| **jy-data-bus** | **DMatrix 数据总线**，数据源管理 + SQL 配置成 API（可视化编排） | Java/Spring |
| **jy-datareport** | **报表服务（jy-dl-web）**，50+ REST 接口覆盖销售/库存/供应商/仓配等 | Java/Spring |
| **jy-data-tek** | 数据分析 BFF，通过 DMatrix RPC 转发请求，本身不直接查库 | Java/Spring |
| **jy-star-map** | 星图标签平台，用户标签 ETL + 人群圈选 + 规则引擎转 Presto SQL | Java/Spring |
| **jy-data-tek-pages** | 数据分析前端（Vue 2.6），运营分析门户 | Vue |
| **jy-datareport-pages-admin** | 管理后台前端（Vue 2.5），BI 配置/指标/权限管理 | Vue |

> 详细项目文档见 `<数据平台文档根目录>/` 目录下 `项目文档/` 子目录各 `<项目名>.md` 文件，以及 `references/projects.md`。

## 数据库地图

### 业务系统 MySQL（统一走 db-cli）

| 实例 (db-cli) | 库 | 说明 | 关键表 |
|---------|-----|------|--------|
| `yas-order` | `jy_order` | 雅斯订单业务库 | `order_data`(订单主表), `order_item`(订单明细), `order_item_money`(支付金额, `pay_price`=实付), `order_refund`(退款) |
| `yas-data` | `jy_data` | 雅斯数据配置库 | `dmtx_data_serv_intf`(接口配置), `dmtx_data_serv_extra_config`(SQL配置, `data_serv_extra_logic_code`=实际SQL), `dmatrix_data_bus_mysql_table`(表映射), `dmatrix_data_bus_import_mysql_single`(拉链配置), `app_cus_joint_sku_sale_d`(联营SKU销售日表) |

> 业务库还有 `jy_finance`（成本/库存总账，`stock_general_ledger_detail`）等，统一走 db-cli 对应实例（`yas-finance` / `wky-finance` / `hmt-finance`）。

### Hive 数仓（Presto 查询引擎）

> 实测可用的是**公网地址**（本机 DBeaver 直连即用）；下表内网 `10.128.x.x` 已过时，勿再用。

| 连接方式 | 地址 | 认证 |
|---------|------|------|
| Hive 直连（雅斯） | `jdbc:hive2://114.55.7.61:10000` | 免密，用户 `root` |
| Hive 直连（万客缘） | `jdbc:hive2://121.40.245.183:10000` | 免密，用户 `root` |
| Presto（雅斯） | `jdbc:presto://114.55.7.61:8889/hive` | 免密，用户 `root` |
| Presto（万客缘） | `jdbc:presto://121.40.245.183:8889/hive` | 免密，用户 `root` |

> 数仓统一走 `db-cli` 的 `yas-hive` / `wky-hive`（自动转发到 hive venv），或 `yas-presto` / `wky-presto` 查数仓。例：`dbq yas-presto "SELECT count(*) FROM app.app_stk_sku_d WHERE dt='2026-08-25'"`。

### 数仓分层（自下而上）

```
业务库 MySQL → BDM(同步) → FDM(贴源) → DIM(维度) → GDM(宽表) → APP(汇总) → ADS(MySQL结果库) → 前端
```

| 层 | 前缀 | 职责 | 典型表 |
|----|------|------|--------|
| BDM | `bdm_` | 业务数据同步，原始 | `bdm_jy_order_order_data_chain` |
| FDM | `fdm_` | 贴源层，保留原始结构 | `fdm_jy_order_order_data_chain` |
| DIM | `dim_` | 维度表（门店/SKU/用户/品类/供应商） | `dim_store`, `dim_itm_store_sku`, `dim_user` |
| GDM | `gdm_` | 通用明细宽表，跨表关联 + 业务逻辑 | `gdm_ord_pay_detl`(成交订单宽表,最热的表), `gdm_ord_detl`(订单明细) |
| APP | `app_` | 应用汇总指标 | `app_ord_store_sale_data_d`(门店销售日汇总) |
| ADS | `ads_*` | MySQL 结果库，供前端查询 | 通过 hive2mysql 同步 + baize 脉冲推送 |

> 详细分层说明见 `references/warehouse-layers.md`，核心表血缘见 `<数据平台文档根目录>/项目文档/jy-warehouse-offline-脚本导航手册.md`。

## 数据库连接方式（统一走 db-cli）

**连通方式：`db-cli` 脚本**（不是 MCP、不是常驻连接）。所有连接信息写在 db-cli 技能目录下的 `config/connections.yaml`（权限 600，唯一真源）。用法与实例清单见 **db-cli 技能的 `SKILL.md`**。MCP 连接器也可用，但 db-cli 是推荐且统一的通道。

### target 写法与挑法

`dbq <target> "<SQL>"`，target 三选一：

- `环境/库`：`yas/jy_order`（推荐，最明确）
- `库名`：`jy_order`（只在单环境存在时可用，否则列候选）
- `实例名`：`yas-order`（库名重名或要点名某台机时）

环境代号：`yas` 雅斯 / `wky` 万客缘 / `hmt` 好码特 / `test` 测试。库名重名必须带环境前缀（雅斯 ≠ 万客缘 ≠ 好码特）。

### 三环境实例速查（挑库口诀）

| 要查的库 | 雅斯实例 | 好码特实例 | 万客缘实例 |
|---------|-----------|-------------|-------------|
| jy_order / 历史 / shield | `yas-order` | `hmt-order` | `wky-order` |
| jy_data / azkaban / canal | `yas-data` | `hmt-star`（官方 mysql-data） | `wky-data` |
| jy_batchstk / jy_pms / jy_roc / t_payment 等大组 | `yas-batchstk` | `hmt-batchstk` | `wky-batchstk` |
| jy_finance / backup | `yas-finance` | `hmt-finance` | `wky-finance` |
| 系统库：baize / jy_msg / jy_sso / jy_monitor / jy_ems（无 jy_proto/jy_fund） | `yas-proto` | `hmt-proto` | `wky-proto`（三台均为官方 mysql-system 实例） |
| jy_dcs / jy_glp / jy_tms / 飞象系 | `yas-dcs` | `hmt-dcs` | `wky-dcs` |
| jy_wms | `yas-wms` | `hmt-dcs`（同实例） | `wky-dcs`（同实例） |
| scm_wms / scm_scs / scm_tms | `yas-scm-new` | `hmt-dcs`（同实例） | `wky-dcs`（同实例） |
| jy_market | `yas-market` | `hmt-market` | `wky-market` |
| jy_search / zq_product / ty_product | `yas-search` | `hmt-data`（官方 mysql-product） | `wky-search` |
| jy_star / jy_star_data / jy_recommend | `yas-star` | `hmt-order`（jy_recommend 在此） | `wky-star`（仅 jy_recommend） |
| 数仓 Hive（gdm/fdm/app/dim） | `yas-hive` / `wky-hive` | — | — |
| 数仓 Presto（查数仓优先） | `yas-presto` | — | — |
| ES 实时索引 | `yas-es` / `wky-es` | — | — |

> 不确定库归哪个实例：`dbq --find <库名>` 反查。某实例默认库不是目标库时，SQL 里用 `库名.表名` 跨库查（账号有该库权限即可）。完整实例用 `dbq --list` 看。

### 连不上的标准动作：加 IP 白名单

外网连 RDS 常被阿里云安全组挡。用团队内部的 `aliyun-tool` jar 给本机出口 IP 授权：

```bash
cd <代码仓库根目录>
java -jar -Dmerchant=yas aliyun-tool-1.0.0-SNAPSHOT.jar   # yas / hmt / wky 三环境分别跑
```

- 跑起来会列出该环境所有 RDS 实例的序号+地址；按序号给要连的实例授权白名单。
- 三个环境都连不上就分别跑 `yas` / `hmt` / `wky` 三次。
- 授权后仍连不上：检查账号只读、库名拼写；**直接走 db-cli（`dbq`）即可，无需重启任何东西**。
- ⚠️ 若团队没有 `aliyun-tool`，向用户询问"加白名单/授权出口 IP 用什么方式"。

### 直接连接就是 db-cli 本身（无需另外直连）

db-cli 脚本**本身就是**直连通道——它调用托管 venv 里共享的 `pymysql` / `pyhive` / `requests` 直连数据库，不经过任何 MCP、不常驻进程、查完即退。所以不存在"MCP 没注入就查不了"的情况：只要 `dbq` 脚本在，就能查。

- 驱动是共享的，装一次反复用（MySQL 走默认托管 venv，Hive 走专用 hive venv），不要每次 pip install。
- 连不上的根因只有两类：①网络被阿里云安全组挡（走上方 aliyun-tool 加白名单）；②本机在跳板代理后（脚本已按地址分流：内网绕代理、公网走代理）。
- 只读护栏在代码层：非 SELECT/SHOW/DESC/EXPLAIN/WITH 一律退出码 2，绝不写库。生产写操作走 DBA 正式变更流程。
- 排查结论照常沉淀到 `<数据平台文档根目录>/`。

## 导航条线（遇到问题从这里进）

### 条线 0："从浏览器地址反查到后端接口"（拿到一个页面 URL，先定位它调哪个接口）

给一个浏览器地址（如 `https://dili.hbyasi.com/#/stockAnalyse/saleStock`），要定位它某个 tab 调用的后端接口。三条路径，按可用性选，人工不熟悉时就是这样一步步查、查完必须记文档：

★ **前端仓库位置（务必先去这里找，别再说"前端不在工作区"）**：所有前端仓库都在**平级目录 `<前端仓库根目录>/`**（一整排 `*-front`）。雅斯地利前端 = **`<前端仓库根目录>/jy-dili-front`**（对应 dili.hbyasi.com），其余如 jy-data-tek-pages、jy-datareport-pages-admin 等也在此。后端/数仓在 `<后端代码根目录>/`。两个目录，查前端去 `<前端仓库根目录>`、查后端/数仓去 `<后端代码根目录>`。

```
路径A｜前端源码静态反查（首选，路由映射铁证；前端就在 <前端仓库根目录>，直接可用）
  hash 路由 #/stockAnalyse/saleStock
  → grep 'saleStock' <前端仓库根目录>/jy-dili-front/src/router/*.js 找路由 → component 指向的 .vue
  → 打开该组件(常是多 tab 容器 index.vue) → 按 tab label 定位目标子组件(如 detail.vue)
  → 子组件 import 的 api 方法(如 ivtDtlQueryPage) → 到 src/api/*.js 查该方法的真实 url(/dl/product/ivt/dtl/queryPage)
  → 拿 url 到后端 jy-dl-web grep @RequestMapping 定位 Controller → VO 上 @DmatrixClassMeta 取数key

路径B｜浏览器运行时抓包（最快，无需源码，需登录态）
  用浏览器打开页面并登录 → F12 Network → 点该 tab → 看 XHR 请求的 url + payload
  ⚠️ 前提：网络可达该站点 + 有效登录账号(cookie/密码)。可用 agent-browser skill 自动化。

路径C｜后端反查（前端拿不到时的兜底，易追错，慎用）
  用页面语义/字段名(如"进货数量/退供金额") → 在 jy-datareport 的 controller/VO 里 grep 字段或接口关键词
  → 找到 @DmatrixClassMeta(dataIntfCode="t1_dl_xxx") → 多字段联合唯一匹配确定接口 → 再走条线1追表
  ⚠️ 局限：靠字段唯一性"推断"，非铁证。教训：saleStock 明细tab 曾用路径C 误判为 t1_dl_ivt_classify_detl_list，
     实际前端铁证是 t1_dl_ivt_dtl_rpt(/dl/product/ivt/dtl)。字段名撞车时路径C 会追错接口，能用路径A 就别用C。
```

★ **有前端就先走路径A（铁证），别用路径C 推断**：路径C 只在前端确实拿不到时兜底，且必须多字段联合、结果要回头用 SQL 印证。

### 条线 1："某报表查的哪个表"

```
1. 先搜 `<数据平台文档根目录>/` 目录（grep 关键词），看有没有已沉淀的排查记录
2. 找报表入口 Controller（在 jy-datareport/jy-dl-web/src/.../controller/ 下，仓库位于 <后端代码根目录>/）
3. Controller 调 BaseDlController.queryData() → DmatrixQueryService → RPC 到 jy-data-bus
4. 在 Controller 对应的 IntfVO 类中找 @DmatrixClassMeta(dataIntfCode="t1_dl_xxx")
5. 用 db-cli 查（如 `dbq yas-data "SELECT ..."`）jy_data.dmtx_data_serv_extra_config:
   SELECT data_serv_code, data_serv_extra_logic_code, ds_key, ds_type
   FROM dmtx_data_serv_extra_config
   WHERE data_serv_code IN ('t1_dl_xxx_list', 't1_dl_xxx_total');
6. data_serv_extra_logic_code 字段就是实际 SQL，ds_key 标明查的哪个库
   ★ 快速定位：SQL 头部通常带注释 `@flow`(业务流程) 和 `@table`(主表)，直接读注释就知道查哪张表，不必通读整段 SQL
   ★ ds_key 判读：`presto-data-warehouse`(ds_type=3) → Presto 查 Hive 数仓；mysql 类 ds_key → 直查 MySQL 结果库
7. 如果是 Presto → 查的是 Hive 数仓表（gdm_*/app_*），不是业务表
8. 要追业务源表 → 读对应 ETL 脚本（jy-warehouse-offline/az_job/scripts/<表名>.py，位于 <后端代码根目录>/）
   顶部注释块的 `SRC_TABLE`(上游表) 和 `TGT_TABLE`(产出表) 直接列明血缘，顺 gdm_→fdm_→业务库 继续追
```

### 条线 2："数据对不上"

```
1. 查 dmtx_data_serv_extra_config 里的 SQL 配置（列表 SQL vs 汇总 SQL）
2. 重点看：GROUP BY 是否一致、过滤条件是否一致、退货扣减口径
3. 检查权限参数：__shopIds__、__purchDeptIds__（动态注入，可能过滤了数据）
4. 检查 groupType 参数：不同分组方式会导致不同结果
5. 对比业务系统原始数据（用 db-cli 查 jy_order 业务表，如 `dbq yas-order "..."`）
6. 注意口径差异：数仓层是加工后的（扣退款/剔取消/分摊营销），与原始订单不同
```

### 条线 3："数仓 ETL 链路追溯"

```
1. 找目标表对应的 ETL 脚本：jy-warehouse-offline/az_job/scripts/<表名>.py（位于 <后端代码根目录>/）
2. 读脚本第 1~20 行，找 SRC_TABLE / 源表定义
3. 顺着 SRC_TABLE 往上追：gdm → fdm → bdm → 业务库 MySQL
4. 查调度依赖：在 az_job/ 下 grep <表名>.job 找 dependencies
5. 核心枢纽表：gdm_ord_pay_detl（48 个下游脚本消费，是数仓最热的表）
```

### 条线 3b："追到业务库源头 + 直连验证"（数仓表 → 是从哪个业务库哪张表同步来的）

排查不能只停在数仓层（app_/gdm_/fdm_），要给出业务侧源头。方法：
```
1. FDM 贴源表命名即线索：fdm_<业务库>_<业务表>_chain。
   例 fdm_jy_batchstk_trs_data_chain → 业务库 jy_batchstk、业务表 trs_data。
   FDM 表 DDL(table-ddl/hive_ddl/fdm.sql) 通常带 source_db/source_table 字段，二次印证。
2. 找同步脚本确认 src_db/src_tb：grep 表名 jy-warehouse-sync/scripts/workspace/sync/（位于 <后端代码根目录>/）
   脚本里 src_db='jy_batchstk'、src_tb='trs_data'、tgt_db='jy_data'、pri_keys、inc_keys 一目了然。
   有 sync_(实时) 和 offline_sync_(离线) 两个版本。
3. 拿业务库物理连接：用 db-cli 查（如 `dbq yas-data`）jy_data.dmatrix_data_bus_mysql_conn，或搜 jy-warehouse-offline/bak/dmatrix.sql
   得到 host/port/db（例 jy_batchstk = 172.16.1.82:3306 从库 jy-batchstk-slave）。
4. ★ 直连验证：业务库同步到 jy_data 后通常有落地表 bdm_<库>_<表>(增量) / ods_<库>_<表>(全量)。
   业务库本身若配了 db-cli 实例(如 `yas-batchstk`) 可直查；内网从库连不通时，
   改查 jy_data 里的 bdm_/ods_ 落地表等价验证（用 `yas-data` 实例）。
   SHOW TABLES LIKE '%<业务表>%' 先探落地表名，再按数仓口径 GROUP BY 复算核对。
```

### 条线 4："实时数据问题"

```
1. 实时数据链路：Kafka → Flink(jy-warehouse-flink-new) → ES/MySQL → 前端
2. 实时同步脚本在 jy-warehouse-sync/scripts/workspace/（crontab 调度，每 2~10 分钟，位于 <后端代码根目录>/）
3. Flink 作业配置：jy-warehouse-flink-new/jy-warehouse-flink-job/src/main/resources/flink-sql/
4. 查看 `<数据平台文档根目录>/问题排查/` 下的实时相关排查记录
```

### 条线 5："新表接入数仓"

```
参考 `<数据平台文档根目录>/项目文档/完整新表接入流程.md` 和 `<数据平台文档根目录>/Skills/数仓新表接入Workflow.md`
核心流程：业务库 → BDM(同步) → FDM(贴源) → [DIM(维度)] → [GDM(宽表)] → APP(汇总) → ADS(MySQL) → DMatrix(API) → 前端
```

## 关键文件索引

| 需要找 | 去哪里 |
|--------|--------|
| 已有排查记录 | `<数据平台文档根目录>/问题排查/` 目录（60+ 篇） |
| 业务表映射结论 | `<数据平台文档根目录>/跟踪表/跟踪数据来源表.md` |
| 分析点滴总结 | `<数据平台文档根目录>/问题排查/scratch/一步步分析总结的点滴.md` |
| 数仓分层详解 | `<数据平台文档根目录>/项目文档/理解DMatrix和数仓分层设计思路.md` |
| 数据链路详解 | `<数据平台文档根目录>/项目文档/数仓运行机制-门店销售数据链路.md` |
| 离线脚本导航 | `<数据平台文档根目录>/项目文档/jy-warehouse-offline-脚本导航手册.md` |
| 离线脚本清单 | `<数据平台文档根目录>/项目文档/jy-warehouse-offline-脚本清单.xlsx` |
| 项目总览 | `<数据平台文档根目录>/总览/项目总览.md` |
| DMatrix 机制 | `<数据平台文档根目录>/项目文档/jy-data-bus.md` |
| 报表服务详情 | `<数据平台文档根目录>/项目文档/jy-datareport.md` |
| 权限体系 | `<数据平台文档根目录>/权限体系/数据平台权限体系说明（含加权限案例）.md` |
| 字段血缘追溯 | `<数据平台文档根目录>/问题排查/Flink与实时稳定性/trade_date字段血缘追溯.md` |
| 销售额追溯 | `<数据平台文档根目录>/问题排查/报表字段与渠道溯源/供应商销售额字段saleAmt追溯.md` |

## 参考文件

- `references/projects.md` — 各项目详细说明（技术栈、模块结构、核心功能）
- `references/databases.md` — 数据库连接配置、DMatrix 表结构、DBX 机制
- `references/warehouse-layers.md` — 数仓分层详细说明、核心表血缘、调度依赖

## 安装给其他人的说明

1. 把本目录（`数据平台排错指南-分享版/`）整体复制到目标机器的 `~/.workbuddy/skills/` 下，目录名可保留或改为 `数据平台排错指南`。
2. 若目标机器也要用 `dbq` 查库，一并安装 `db-cli` 技能，并在其 `config/connections.yaml` 填入该团队的实例与只读账号。
3. 首次对话时，按本文件顶部「本地配置」一节，向用户确认那几个路径与账号，并把真实值替换到正文 `<占位符>` 处（或写入 `config.md` 让 AI 自己读）。
