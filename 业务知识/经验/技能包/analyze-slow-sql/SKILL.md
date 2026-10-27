---
name: analyze-slow-sql
description: Perform root cause analysis on a specific slow SQL record and generate optimization recommendations. Supports locating the record either by slow_sql_log primary key ID or by live_uuid (when the user passes a UUID, the record is queried by slow_sql_log.live_uuid). Queries slow_sql_log (all columns), slow_sql_live_log (execution plan + call chain), slow_db_monitor_log (performance baseline of the 10 minutes before the slow SQL), extracts all table names from the slow SQL, and fetches each table's DDL structure from db_table. Combines table structure, database diagnostics with workspace source code review. Use when the user asks to analyze a slow SQL, diagnose slow query causes, or generate SQL optimization plans.
---

# Analyze Slow SQL

Perform deep root cause analysis on a specific slow SQL record and output a structured optimization report.

## Mandatory Parameters

Extract parameters from the user's request:

1. **workspace** — absolute path to the project source code (e.g., `D:\projects\jy-backend`). **REQUIRED — 必须由用户明确指定。**
2. **id 或 uuid（二选一，必填其一）** — 慢SQL记录的定位方式：
   - **id**：`slow_sql_log` 表的主键 ID；
   - **uuid**：慢SQL记录的 `live_uuid`。当用户传入 UUID 时，必须按 `slow_sql_log.live_uuid` 字段查询对应记录，不得要求用户改传 ID。

判断规则：
- 若用户给的是一个标准 UUID 格式（如 `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` 或形似的唯一标识字符串），按 **uuid** 处理；
- 若用户给的是纯数字，按 **id** 处理；
- 若用户明确说明"用 UUID / live_uuid 查"，则一律按 **uuid** 处理，无论格式如何。

### workspace 强制指定规则（禁止使用默认工作空间）

- `workspace` 是**强制必填**参数。**严禁**在用户未指定时回退使用 WorkBuddy 默认工作空间（如 `C:\Users\admin\WorkBuddy\...`）作为源码目录或输出目录。
- 如果用户的请求中**没有**提供工作空间路径，必须**立即追问并要求用户指定**，不得自行猜测、不得沿用默认路径、不得开始分析。
- 追问时使用中文，明确要求给出绝对路径，例如：

> 请指定工作空间路径（项目源码所在目录的绝对路径），例如：D:\projects\jy-backend。在您提供工作空间之前，我无法开始分析。

- 只有同时具备用户指定的 `workspace`和 `id`/`uuid`（其一）后，才允许开始执行分析流程。
- 若用户既未提供 workspace，也未提供 id 或 uuid，则停止执行并等待用户输入。

## Workflow

### Step 1: Collect Diagnosis Data

**依赖前置（首次运行必读）**：采集脚本依赖 `pymysql`。首次运行前先检查隔离 venv 是否已安装，缺失则安装（不要污染全局环境）：

```bash
# 检查：若 venv 不存在则先用受管 Python 创建（路径按当前用户 HOME 展开，勿写死用户名）
"$HOME/.workbuddy/binaries/python/envs/default/Scripts/python.exe" -m pip install pymysql --quiet
# Windows Git Bash 下 HOME=/c/Users/<用户名>；也可直接用绝对路径，例如
#   C:/Users/<用户名>/.workbuddy/binaries/python/envs/default/Scripts/python.exe
# 之后统一用该 venv 的 python 运行采集脚本
```

Run the data collection script to gather all relevant information from the monitoring database. The output JSON file **must** be written inside the user-specified `workspace` directory (e.g. `<workspace>\diagnosis\<slow_sql_id>.json`), never into the WorkBuddy default workspace.

**当用户传入 uuid 时，使用 `--uuid` 参数按 `slow_sql_log.live_uuid` 查询：**

```bash
python "scripts\collect_diagnosis_data.py" --uuid <LIVE_UUID> --output "<workspace>\diagnosis\<LIVE_UUID>.json"
```

**当用户传入 id 时，使用 `--id` 参数按主键查询：**

```bash
python "scripts\collect_diagnosis_data.py" --id <SLOW_SQL_ID> --output "<workspace>\diagnosis\<SLOW_SQL_ID>.json"
```

`--id` 与 `--uuid` 互斥，二选一传入。脚本会先用 id 或 uuid 定位 `slow_sql_log` 记录，再从该记录中取出 `live_uuid`、`db_instance_id`、`execution_start_time` 等字段完成后续查询。若按 uuid 未找到记录，需将脚本输出的错误信息如实告知用户（该 UUID 在 `slow_sql_log` 中不存在），不得自行猜测或改用其他表的数据。

This script queries four data sources and outputs a JSON file:
- `slow_sql_log` — the slow SQL record details (**ALL columns**)
- `slow_sql_live_log` — EXPLAIN plan (JSON) and code call chain (JSON stack trace)
- `slow_db_monitor_log` — performance metrics for the **10-minute window** before the slow SQL occurred
- `db_table` — DDL structure of every table referenced in the slow SQL:
  1. The script extracts **all table names** from `sql_text` (handles `FROM`/`JOIN`/`INTO`/`UPDATE`/`TABLE` keywords, backtick-quoted names `` `table` ``, `db.table` prefixes, and drops aliases)
  2. For each table it runs `SELECT table_ddl FROM db_table WHERE db_name = ? AND table_name = ?` and collects the DDL (CREATE TABLE statement)
  3. Results are stored under `table_analysis.table_ddls`; tables without a DDL record go to `table_analysis.missing_tables`, and query failures (e.g. missing SELECT privilege) go to `table_analysis.query_errors` — collection never aborts on missing table structures

### Step 2: Explore Source Code in Workspace

Using the `code_invoke` call chain from the diagnosis data, locate the relevant source files in the workspace. Focus on:

- The DAO/Repository method that issues the SQL
- The Service method that calls the DAO
- The Controller endpoint that triggers the request

Also read the mapper XML fragments the SQL is assembled from (`<sql id="...">` includes) — the recorded SQL is the expanded form, and the `<if>` branches reveal which parameters were actually passed. Then count **how many times the same statement id is invoked per request** (e.g. UI badge counts often re-run the identical count 2–3 times).

### Step 3: Verify with `EXPLAIN ANALYZE` on the live instance (MySQL 8.0.18+)

The recorded EXPLAIN gives estimates only. When the target database is reachable, run `EXPLAIN ANALYZE` to get per-node **actual rows and actual time**, then:

1. Locate which node actually burns the time (`actual rows` vs plan `rows`, and `loops=` on dependent subqueries).
2. Quantify condition selectivity with one aggregate query (e.g. `SUM(CASE WHEN … THEN 1 END)` per predicate) — plan `filtered` is a heuristic constant for un-indexed columns and is often off by 100x+.
3. Validate each proposed fix by measuring a variant (index hint / rewritten SQL) **before** recommending DDL, and report measured vs estimated separately.

Two cautions: (a) these statements execute, so prefer one partition / a narrow window and note the load in the report; (b) a "merge the duplicate EXISTS into the existing join" rewrite is **not** automatically faster — it moves the filter after the join, so the join then loops per candidate row instead of per result row. Measure it before recommending.

Use `Grep` and `Glob` to find the Java files referenced in the call chain. Read the relevant methods to understand the business logic.

### Step 4: Produce Structured Analysis Report

Combine all gathered data to produce a report covering two dimensions:

#### Database-Level Analysis

- **Table structure analysis**: Inspect each table's DDL from `table_analysis.table_ddls` — examine the full column list, data types, PRIMARY KEY, indexes (normal/unique/fulltext), and foreign keys. Verify whether the WHERE/JOIN/ORDER BY columns of the slow SQL are indexed; check for oversized rows (wide VARCHAR/TEXT/BLOB), missing indexes on join/condition columns, and redundancy between the EXPLAIN plan and the actual schema
- **Index analysis**: Based on EXPLAIN plan (`type`, `key`, `rows`, `Extra` fields) cross-referenced with the DDL indexes, identify missing indexes or index misuse
- **SQL rewrite**: Identify inefficient query patterns (large OFFSET, full table scan, large date range, SELECT * etc.) and suggest rewrites
- **Parameter tuning**: Based on performance metrics (buffer pool hit rate, connection count, IOPS, lock waits etc.), suggest MySQL parameter adjustments

#### Code-Level Analysis

- **Call chain tracing**: Map each stack frame to specific workspace files and line numbers
- **ORM/DAO refactoring**: Suggest changes to the query construction (use cursor-based pagination instead of OFFSET, add time range limits, split complex queries)
- **Caching strategy**: Evaluate if results can be cached (Redis, local cache) based on data volatility
- **Batch processing**: Evaluate if the query can be split into smaller batches

### Output Format

```markdown
## 慢SQL根因分析报告

### 基本信息
慢SQL基本信息取自 `slow_sql_log` 的**全部列**（id, db_instance_id, db_name, sql_text, sql_hash, query_time, execution_start_time, host_address, parse_row_counts, lock_time, return_row_counts, live_uuid, ...），报告至少展示以下关键项：
- 慢SQL ID: {id}
- 数据库实例: {db_instance_id}
- 执行时间: {execution_start_time}
- 执行耗时: {query_time}毫秒
- 数据库: {db_name}
- UUID: {live_uuid}

### SQL语句
{sql_text}

### 涉及表及表结构
| 表名 | 表结构(DDL) | 说明 |
|------|-------------|------|
| {table_name} | {table_ddl 摘要（关键字段/索引/主键）} | 是否命中索引、存在索引缺失等 |

- 涉及的表的 DDL 完整内容取自 `table_analysis.table_ddls`
- 若某表在 `db_table` 中无记录或查询失败（见 `missing_tables` / `query_errors`），需在报告中明确标注"表结构缺失，无法进行结构级分析"，但不得跳过该表的分析
- 结合表结构逐条核对慢SQL中出现的每个 WHERE / JOIN / ORDER BY 字段是否有对应索引

### 执行计划分析
- 访问类型(type): ...
- 使用索引(key): ...
- 扫描行数(rows): ...
- 额外信息(Extra): ...
- 问题诊断: ...

### 数据库性能基线（慢SQL发生前10分钟）
| 指标类型 | 关键数据 |
|----------|----------|
| ... | ... |

### 代码调用链
| 类名 | 文件 | 行号 | 方法 |
|------|------|------|------|
| ... | ... | ... | ... |

### 根因分析
1. **数据库层面**:（结合表结构与执行计划，指出索引缺失/字段类型问题/扫描行数过大等）
2. **代码层面**: ...

### 优化方案
#### 数据库优化
1. ...（涉及建索引时，给出基于 DDL 的具体索引建议，如 `ALTER TABLE xxx ADD INDEX idx_xxx (col1, col2)`）
2. ...

#### 代码优化
1. ...
2. ...
```

Do NOT skip any section. Every field must be populated from the collected data and code review.
