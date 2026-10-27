---
name: db-cli
description: 统一数据库只读查询入口，替代几十个常驻 MCP 连接器。查业务库/数仓/ES 数据、验证 SQL、核对报表、追数据来源时用。覆盖雅斯/万客缘/好码特/测试四环境 36 个实例，支持 MySQL、Hive、Presto、ES 四引擎，强制只读护栏。关键词：查库、连数据库、跑 SQL、数仓查询、jy_order、jy_data、jy_batchstk、jy_wms、Hive、Presto、ES、库名反查、连哪个库、核对数据。
agent_created: true
---

# db-cli 统一数据库查询

一个脚本 + 一份连接注册表，替代原来散在各 AI 工具里的几十个常驻 MCP 连接器。
**调用时才起进程，查完即退，常驻进程 0 个。**

**这是 WorkBuddy 里唯一的数据库查询入口。** 原 `db-resolver`（库名反查）、`hive-direct-connect`（Hive 直连）、`presto-direct-query`（Presto 直连）三个旧 skill 已合并进本 skill，不要再单独加载它们。

## 怎么用

```bash
~/.workbuddy/skills/db-cli/scripts/dbq <target> "<SQL>"
```

Windows（Git Bash）下直接可用；嫌长就在 `~/.bashrc` 加 `alias dbq=~/.workbuddy/skills/db-cli/scripts/dbq`。
PowerShell 想用则在 `$PROFILE` 加 `function dbq { & "$env:USERPROFILE\.workbuddy\skills\db-cli\scripts\dbq" @args }`。
之后直接 `dbq yas/jy_order "SELECT 1"`。

### target 三种写法

| 写法 | 例 | 适用 |
|---|---|---|
| 环境/库 | `yas/jy_order` | 推荐，最明确 |
| 库名 | `jy_order` | 只在单环境存在时可用，否则列候选 |
| 实例名 | `yas-order` | 库名重名或要点名某台机时 |

环境代号：`yas` 雅斯 / `wky` 万客缘 / `hmt` 好码特 / `test` 测试。

### 其他命令

```bash
dbq --list              # 列出全部 35 个实例（不显示密码）
dbq --list yas          # 只看某个环境
dbq --find azkaban      # 按库名/主机/备注反查该连哪个
dbq --ping yas/jy_order # 探活，拿不准网络先跑这个
```

### 常用参数

- `--limit N` 返回行数，默认 200，硬上限 5000
- `--format table|tsv|json` 默认 table。要塞进后续处理用 tsv 或 json，token 更省
- `--timeout N` 默认 120 秒
- `--no-limit-check` SQL 自带 LIMIT 或跑聚合时加，免得被追加
- `--explain` 只 EXPLAIN 不执行
- SQL 以 `@` 开头则从文件读：`dbq yas/jy_order @/c/Users/yuai/AppData/Local/Temp/q.sql`（Git Bash 下 Windows 路径写成 `/c/...` 或 `C:/...` 均可）

## 只读护栏（硬约束，不是建议）

脚本解析 SQL 首关键字，只允许 `SELECT / SHOW / DESC / EXPLAIN / WITH`。
以下情况**直接退出码 2，数据库连碰都不会碰**：

- 首关键字不在白名单（DELETE / UPDATE / INSERT / DROP…）
- 语句里出现被禁关键字（含注释里藏的、多语句分号后面夹带的、`INTO OUTFILE`、`INSERT OVERWRITE`）
- 一次传多条语句

护栏在代码里，不在提示词里。CodeBuddy、Trae 调同一个脚本受同一道约束。
**生产库写操作走 DBA 正式变更流程，这个脚本不提供通路。**

## 四引擎差异

| 引擎 | 实例 | 注意 |
|---|---|---|
| MySQL | 28 个 | pymysql 直连，最快，0.2s 级 |
| Presto | `yas-presto` | REST，外网可达，0.7s 级。查数仓优先用它 |
| Hive | `yas-hive` `wky-hive` | 自动转发到 hive39 venv（Python 3.9），4s 起跳 |
| ES | `yas-es` `wky-es` | 内网 10.x，**本机不可达**，需公司网络 |

### ES 用法特殊

ES 不接受 SQL，target 写 `实例名/<index>`，查询位置传 JSON DSL：

```bash
dbq yas-es/rlt_gdm_ord_sku '{"size":0,"aggs":{"by_shop":{"terms":{"field":"store_id"}}}}'
```

index 名查 `jy_data.dmtx_data_serv_extra_config WHERE ds_type=2` 的 `ds_key`。
聚合结果自动摊平成 `aggregation | value` 两列。

### 引擎语法坑（Presto）

- **中文列别名必须双引号**：`AS "期初数量"`，裸写报 `mismatched input`
- **日期函数**：`DATE_ADD('day', -1, d)` / `DATE_DIFF('day', d1, d2)`；Hive 是 `date_sub(d,1)` / `datediff(d1,d2)`
- **聚合查询**里裸的非分组表达式要包 `MAX(...)`，比 Hive 严格
- **`MAX_BY(col, sort_col)`** 取按某列排序的最后一条（等价 Hive `MAX(named_struct(...)).v`）
- **`GROUP BY 1` 不等于"按第 1 列分组"**：它按 SELECT 第 1 个表达式分组；若第 1 列本身是聚合（如 `MAX(x) AS 门店`）会报 `cannot contain aggregations`——单参数查询直接去掉 GROUP BY
- **SQL 文件分号截断**：脚本按第一个分号截断，尾部注释块放分号之后

### 引擎语法坑（Hive / 数仓）

- **分区表必须带 `dt` 范围**，否则全表扫描（`gdm_*`/`app_*` 按 `dt` 分区，`trs_dt` 是业务日期、`dt` 是分区键，裁剪靠 `dt`）
- **`MySQL` 镜像多是空表**：`jy_data.app_stk_sku_d` 等 `COUNT(*)=0`（历史遗留），数仓对账只能走 Hive/Presto
- **库存净变动 `trs_num` 已带符号**（入库 +/出库 −），是最简洁的单一净变动；各类型列（`pa_num`/`pos_num`/`out_num`/...）本身也是带符号净值，代数相加 == `trs_num`，两者等价
- **经营性质字段**：app 层用 `op_nature`，gdm 层用 `operations_nature`（两表列名不同，别混）；联营口径 `op_nature=2` / `operations_nature=2`
- **报表取数 SQL 在哪**：先查 `jy_data.dmtx_data_serv_extra_config`（`data_serv_extra_logic_code` 字段，按接口 key 找）；取出的是 MyBatis 模板（`<if>`/`<foreach>`/`#{x}`/`__shopIds__`），**不能直接跑**，要剥离分支、替换占位符、`__shopIds__` 之类的权限占位自己跑可去掉，再在 Presto 验证
- 数仓表和业务表口径不同（如毛利是否含返利），对账前先确认口径

## 网络

本机常设 `HTTP_PROXY=127.0.0.1:5xxxx`。脚本已按地址分流：
内网地址（10.x/192.168.x）绕过代理直连，公网地址照常走代理。
所以 Presto（公网）通、ES（内网）不通是**网络环境限制**，不是脚本问题。

## 铁律

- **只 SELECT**。生产库写操作一律走 DBA。
- **环境隔离**：雅斯 ≠ 万客缘 ≠ 好码特。库名重名时必须带环境前缀。
- **连不上的时候先 `--ping`**，别一上来就怀疑脚本。
- 连接信息唯一真源是 `config/connections.yaml`（权限 600）。
  改密码只改那一个文件，各 AI 工具的 mcp.json 不再承载数据库连接。

## 和别的 skill 怎么配合

- 追数据链路、查报表口径 → 「数据平台排错指南」（它已统一指向本 skill 查库）
- 本 skill 已合并原 `db-resolver`（库名反查）、`hive-direct-connect`（Hive 直连）、`presto-direct-query`（Presto 直连）的能力，无需再单独加载那三个 skill
