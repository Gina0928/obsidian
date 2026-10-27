---
name: query-slow-sql
description: Query slow SQL logs from MySQL database by time range and export the RAW records to an Excel (.xlsx) file inside the user-specified workspace. Use when the user asks to check slow queries, slow SQL logs, MySQL performance issues, or analyze database query performance. If the user does not specify a time range, defaults to today; if the user does not specify a database, list the available databases and let the user pick one.
---

# Query Slow SQL

Query the `slow_sql_log` table in MySQL and export the raw slow SQL records for a specified time range and database as an Excel (.xlsx) file inside the user-specified workspace.

## Mandatory Parameters

Before executing the query, you MUST extract the following parameters from the user's request:

1. **workspace** — **MANDATORY. 强制必填，用户必须明确指定。** The workspace (absolute path to the project source code), e.g., `D:\projects\jy-backend`. The Excel file is exported to this directory. **If the user did NOT specify a workspace, you MUST ask the user to provide it — do NOT use the WorkBuddy default workspace, do NOT guess, do NOT substitute your own session/current working directory.** Do NOT proceed until the user explicitly states the workspace path.
2. **start-time** — OPTIONAL. The start of the time range in `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS` format (e.g., `2026-07-27` or `2026-07-27 08:00:00`). **If the user did NOT specify a time, default to today `YYYY-MM-DD 00:00:00`** (today = the current date).
3. **end-time** — OPTIONAL. The end of the time range in `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS` format (e.g., `2026-07-27` or `2026-07-27 18:00:00`). **If the user did NOT specify a time, default to today `YYYY-MM-DD 23:59:59`**.
4. **database** — the target database name (e.g., `mydb`). **If the user did NOT specify a database**, do NOT guess it and do NOT fail. Instead:

   a. Run the script in list mode: `python "scripts\query_slow_sql.py" --list-databases`
   b. The script executes `SELECT DISTINCT db_name FROM slow_sql_log` and prints the available database list.
   c. Present the full list to the user and ask the user to pick one of the databases.
   d. Only after the user selects a database, run the main query with the chosen database name.

If workspace is missing, **ask the user for it** with a clear message in Chinese and wait for their reply — do NOT fall back to the WorkBuddy default workspace:

> 请指定工作空间（导出慢SQL的目录，即项目源码绝对路径），例如：查询今天的慢SQL，工作空间 D:\projects\jy-backend。

Do NOT proceed to query until the user explicitly provides the workspace. Time defaults to today; database is resolved via the list if not specified.

## Execution

### Step 0 — Resolve the workspace (always required)

**workspace is mandatory and must come from the user.** If the user did not specify a workspace in their request, ask them explicitly:

> 请指定工作空间（导出慢SQL的目录），例如：D:\projects\jy-backend。

Never use the WorkBuddy default workspace, the current session directory, or any guessed path. Wait for the user's explicit answer before continuing.

### Step 1 — Resolve the database (only if the user did not specify one)

If the user's request does not contain a database name, run:

```bash
python "scripts\query_slow_sql.py" --list-databases
```

This executes `SELECT DISTINCT db_name FROM slow_sql_log ORDER BY db_name` and prints the list of databases, e.g.:

```
slow_sql_log 表中的数据库列表：
1. jy_monitor
2. jy_workflow
3. baize
```

Show the full list to the user and ask them to choose one. Do NOT pick one yourself.

### Step 2 — Run the query with the chosen database

Run the query script with the extracted parameters:

```bash
python "scripts\query_slow_sql.py" --start-time "<YYYY-MM-DD [HH:MM:SS]>" --end-time "<YYYY-MM-DD [HH:MM:SS]>" --database "<database_name>" --workspace "<workspace_path>"
```

If the user did NOT specify a time range, `--start-time` and `--end-time` may be omitted — the script defaults to today (`YYYY-MM-DD 00:00:00` to `YYYY-MM-DD 23:59:59`), e.g.:

```bash
python "scripts\query_slow_sql.py" --database "<database_name>" --workspace "<workspace_path>"
```

The script will:
- Validate that the required parameters are provided (time defaults to today if omitted; workspace must be explicitly provided by the user)
- Connect to the MySQL database at `rm-bp1151j106lak7koawo.mysql.rds.aliyuncs.com:3306`
- Query `slow_sql_log` filtered by time range (`execution_start_time >= start_time AND execution_start_time <= end_time`) and database, ordered by `query_time` descending
- Export ALL raw fields of every record to an Excel file `<workspace>/slow_sql_<start>_to_<end>_<database>.xlsx`

## Output

- The script exports the raw records to an Excel (.xlsx) file inside the workspace directory.
- Only raw data is exported — NO aggregation, statistics, summary rows, or summary sheets are added.
- The sheet `慢SQL原始数据` contains one column per table field (id, db_instance_id, db_name, sql_text, sql_hash, query_time, execution_start_time, host_address, parse_row_counts, lock_time, return_row_counts, live_uuid, ...) and one row per record.
- Present the generated Excel file path to the user and open the file for them.

## Examples

**示例1：按天查询**

User: 查询 2026-07-27 数据库 production_db 的慢SQL，工作空间 D:\projects\jy-backend

Agent:
1. Extract workspace=`D:\projects\jy-backend`, start_time=`2026-07-27 00:00:00`, end_time=`2026-07-27 23:59:59`, database=`production_db`
2. Run: `python scripts/query_slow_sql.py --start-time "2026-07-27 00:00:00" --end-time "2026-07-27 23:59:59" --database "production_db" --workspace "D:\projects\jy-backend"`
3. Present the generated Excel file to the user

**示例2：按小时查询**

User: 查询 2026-07-27 上午 8 点到 12 点数据库 mydb 的慢SQL，工作空间 D:\projects\jy-backend

Agent:
1. Extract workspace=`D:\projects\jy-backend`, start_time=`2026-07-27 08:00:00`, end_time=`2026-07-27 12:00:00`, database=`mydb`
2. Run: `python scripts/query_slow_sql.py --start-time "2026-07-27 08:00:00" --end-time "2026-07-27 12:00:00" --database "mydb" --workspace "D:\projects\jy-backend"`
3. Present the generated Excel file to the user

**示例3：用户未指定数据库**

User: 查询 2026-07-27 全天的慢SQL，工作空间 D:\projects\jy-backend

Agent:
1. Extract workspace=`D:\projects\jy-backend`, start_time=`2026-07-27 00:00:00`, end_time=`2026-07-27 23:59:59`, database=未指定
2. Run: `python scripts/query_slow_sql.py --list-databases` → 脚本执行 `SELECT DISTINCT db_name FROM slow_sql_log` 并打印数据库列表
3. 将数据库列表完整展示给用户，请用户选择一个数据库
4. 用户选择 `production_db` 后，Run: `python scripts/query_slow_sql.py --start-time "2026-07-27 00:00:00" --end-time "2026-07-27 23:59:59" --database "production_db" --workspace "D:\projects\jy-backend"`
5. Present the generated Excel file to the user

**示例4：用户未指定时间（默认今天）**

User: 查看今天的慢SQL，工作空间 D:\projects\jy-backend，数据库 production_db

Agent:
1. Extract workspace=`D:\projects\jy-backend`, database=`production_db`, start_time/end_time=未指定 → 默认今天：`2026-08-02 00:00:00` ~ `2026-08-02 23:59:59`（today 按当前日期计算）
2. Run: `python scripts/query_slow_sql.py --database "production_db" --workspace "D:\projects\jy-backend"`（省略 --start-time / --end-time，脚本自动用今天全天）
3. Present the generated Excel file to the user

**示例5：用户未指定工作空间（强制询问，禁止用默认工作空间）**

User: 查看今天的慢SQL，数据库 production_db

Agent:
1. Extract database=`production_db`, start_time/end_time=未指定（默认今天），workspace=**未指定**
2. **禁止**使用 WorkBuddy 默认工作空间或当前会话目录。向用户询问：`请指定工作空间（导出慢SQL的目录），例如：D:\projects\jy-backend。`
3. 用户回复 `D:\projects\jy-backend` 后，Run: `python scripts/query_slow_sql.py --database "production_db" --workspace "D:\projects\jy-backend"`
4. Present the generated Excel file to the user
