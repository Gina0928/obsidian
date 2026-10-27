#!/usr/bin/env python3
"""Collect diagnosis data for a specific slow SQL record.

The slow SQL record can be located either by primary key ID or by live_uuid.

Queries:
  1. slow_sql_log         — slow SQL record by ID or by live_uuid (ALL columns)
  2. slow_sql_live_log    — EXPLAIN plan + code call chain by UUID
  3. slow_db_monitor_log  — performance baseline (10 minutes before slow SQL)
  4. db_table             — table DDL structures for every table referenced in the slow SQL

Output: JSON file with all collected data.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta

import pymysql

from db_config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, CONNECT_TIMEOUT, READ_TIMEOUT


def parse_args():
    parser = argparse.ArgumentParser(description="Collect slow SQL diagnosis data")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--id", type=int, help="Primary key ID of the slow SQL record")
    group.add_argument(
        "--uuid",
        help="live_uuid of the slow SQL record (queried against slow_sql_log.live_uuid)",
    )
    parser.add_argument("--output", required=True, help="Output JSON file path")
    return parser.parse_args()


def get_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        connect_timeout=CONNECT_TIMEOUT,
        read_timeout=READ_TIMEOUT,
    )


def query_slow_sql(cursor, record_id=None, record_uuid=None):
    """Query slow_sql_log, returning ALL columns.

    Lookup priority: if record_uuid is provided, search by live_uuid;
    otherwise search by primary key ID.
    """
    if record_uuid:
        sql = """
            SELECT *
            FROM slow_sql_log
            WHERE live_uuid = %s
        """
        param = record_uuid
    else:
        sql = """
            SELECT *
            FROM slow_sql_log
            WHERE id = %s
        """
        param = record_id
    cursor.execute(sql, (param,))
    row = cursor.fetchone()
    if not row:
        if record_uuid:
            print(f"错误：未找到 live_uuid={record_uuid} 的慢SQL记录。", file=sys.stderr)
        else:
            print(f"错误：未找到 ID={record_id} 的慢SQL记录。", file=sys.stderr)
        sys.exit(1)
    result = {k: str(v) if isinstance(v, datetime) else v for k, v in row.items()}
    return result


def query_live_log(cursor, uuid_val):
    """Query slow_sql_live_log by UUID."""
    sql = """
        SELECT id, uuid, explain_plan, code_invoke, server_ip, create_date
        FROM slow_sql_live_log
        WHERE uuid = %s
    """
    cursor.execute(sql, (uuid_val,))
    row = cursor.fetchone()

    result = {}
    if row:
        result = {k: (str(v) if isinstance(v, datetime) else v) for k, v in row.items()}

        # Parse JSON fields
        for field in ("explain_plan", "code_invoke"):
            raw = result.get(field)
            if raw and isinstance(raw, str):
                try:
                    result[field] = json.loads(raw)
                except json.JSONDecodeError:
                    pass  # keep raw string

    return result


def query_monitor_log(cursor, db_instance_id, exec_start_time):
    """Query slow_db_monitor_log for the 10 minutes before the slow SQL execution time."""
    if isinstance(exec_start_time, str):
        exec_start_time = datetime.strptime(exec_start_time, "%Y-%m-%d %H:%M:%S")

    window_start = exec_start_time - timedelta(minutes=10)

    sql = """
        SELECT db_instance_id, performance_type, performance_key,
               performance_value, create_date
        FROM slow_db_monitor_log
        WHERE db_instance_id = %s
          AND create_date >= %s
          AND create_date <= %s
        ORDER BY performance_type, create_date
    """
    cursor.execute(sql, (db_instance_id, window_start, exec_start_time))
    rows = cursor.fetchall()

    # Group by performance_type
    grouped = {}
    for row in rows:
        ptype = row["performance_type"]
        if ptype not in grouped:
            grouped[ptype] = []
        grouped[ptype].append({
            "create_date": str(row["create_date"]) if isinstance(row["create_date"], datetime) else row["create_date"],
            "performance_key": row["performance_key"],
            "performance_value": row["performance_value"],
        })

    return {
        "window_start": str(window_start),
        "window_end": str(exec_start_time),
        "db_instance_id": db_instance_id,
        "total_records": sum(len(v) for v in grouped.values()),
        "metrics": grouped,
    }


def strip_sql_comments(sql_text):
    """Remove SQL comments (-- line comments, /* */ block comments, # line comments)."""
    if not sql_text:
        return ""
    # Block comments
    s = re.sub(r"/\*.*?\*/", " ", sql_text, flags=re.S)
    # Line comments
    s = re.sub(r"--[^\n]*", " ", s)
    s = re.sub(r"#[^\n]*", " ", s)
    return s


def extract_table_names(sql_text):
    """Extract all table names referenced by the slow SQL.

    Scans keywords FROM / JOIN / INTO / UPDATE / TABLE and collects the
    identifier that follows, handling:
      - backtick-quoted names: `user`
      - db-prefixed names:     dbname.user  -> user
      - aliases:               FROM user u   -> user (alias dropped)
    Returns a sorted, de-duplicated list of table names.
    """
    if not sql_text:
        return []

    cleaned = strip_sql_comments(sql_text)

    # Tokenize: find each keyword occurrence, take the next identifier
    # Identifiers may contain backticks or dots (db.table)
    table_names = set()
    # Matches a keyword (case-insensitive) followed by an identifier
    keyword_pat = re.compile(
        r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+"
        r"(`[^`]+`|\w+(?:\.`?[^`\s]+`?)?)",
        re.IGNORECASE,
    )

    for m in keyword_pat.finditer(cleaned):
        ident = m.group(1)
        # Unquote backticks
        if ident.startswith("`") and ident.endswith("`"):
            ident = ident[1:-1]
        # Drop database prefix if present (dbname.table / `dbname`.`table`)
        if "." in ident:
            ident = ident.split(".")[-1].strip("`")
        ident = ident.strip()
        if ident and ident.lower() not in ("select", "dual", "values"):
            table_names.add(ident)

    return sorted(table_names)


def query_table_ddls(cursor, db_name, table_names):
    """Query table DDL structures from the db_table table.

    For each table name, run:
        SELECT table_ddl FROM db_table WHERE db_name = %s AND table_name = %s
    Returns a dict {table_name: table_ddl, ...} for tables that were found,
    plus a list of tables with no matching DDL record (or query errors).
    Robust by design: a permission error or missing record for one table
    must NOT abort the whole diagnosis data collection.
    """
    ddls = {}
    missing = []
    errors = {}
    if not db_name or not table_names:
        return ddls, missing, errors

    sql = """
        SELECT table_ddl
        FROM db_table
        WHERE db_name = %s
          AND table_name = %s
        LIMIT 1
    """
    for table in table_names:
        try:
            cursor.execute(sql, (db_name, table))
            row = cursor.fetchone()
            if row and row.get("table_ddl"):
                ddls[table] = row["table_ddl"]
            else:
                missing.append(table)
        except pymysql.MySQLError as e:
            errors[table] = str(e)
            missing.append(table)

    return ddls, missing, errors


def main():
    args = parse_args()

    conn = None
    try:
        conn = get_connection()
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            # Step 1: Query slow SQL record (by uuid or id)
            if args.uuid:
                print(f"查询慢SQL记录 live_uuid={args.uuid} ...")
            else:
                print(f"查询慢SQL记录 ID={args.id} ...")
            slow_sql = query_slow_sql(cursor, record_id=args.id, record_uuid=args.uuid)
            print(f"  -> 找到记录 (id={slow_sql.get('id')}), db={slow_sql['db_name']}, uuid={slow_sql['live_uuid']}")

            # Step 2: Query live log (explain plan + code invoke)
            uuid_val = slow_sql.get("live_uuid")
            live_log = {}
            if uuid_val:
                print(f"查询调用链与执行计划 uuid={uuid_val} ...")
                live_log = query_live_log(cursor, uuid_val)
                print(f"  -> explain_plan={'有' if live_log.get('explain_plan') else '无'}, code_invoke={'有' if live_log.get('code_invoke') else '无'}")

            # Step 3: Query performance baseline
            db_instance_id = slow_sql.get("db_instance_id")
            exec_start_time = slow_sql.get("execution_start_time")
            monitor_log = {}
            if db_instance_id and exec_start_time:
                print(f"查询性能基线 db_instance={db_instance_id}, 时间窗口={exec_start_time}前10分钟 ...")
                monitor_log = query_monitor_log(cursor, db_instance_id, exec_start_time)
                print(f"  -> 共 {monitor_log['total_records']} 条性能记录，{len(monitor_log['metrics'])} 种指标类型")

            # Step 4: Extract table names from slow SQL and query table DDLs
            db_name = slow_sql.get("db_name")
            sql_text = slow_sql.get("sql_text")
            table_names = extract_table_names(sql_text)
            table_ddls, missing_tables, ddl_errors = {}, [], {}
            if db_name and table_names:
                print(f"提取慢SQL表名({len(table_names)}个): {', '.join(table_names)}")
                table_ddls, missing_tables, ddl_errors = query_table_ddls(cursor, db_name, table_names)
                print(f"  -> 获取到表结构 {len(table_ddls)} 个: {', '.join(table_ddls.keys()) or '无'}")
                if ddl_errors:
                    print(f"  -> 表结构查询出错 {len(ddl_errors)} 个: {', '.join(ddl_errors.keys())}（可能是权限不足）")
                if missing_tables:
                    print(f"  -> 未找到表结构记录: {', '.join(missing_tables)}")
            else:
                print("未提取到表名或缺少 db_name，跳过表结构查询。")

        # Assemble output
        output = {
            "slow_sql": slow_sql,
            "live_log": live_log,
            "monitor_log": monitor_log,
            "table_analysis": {
                "db_name": db_name,
                "tables": table_names,
                "table_ddls": table_ddls,
                "missing_tables": missing_tables,
                "query_errors": ddl_errors,
            },
        }

        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        print(f"\n诊断数据已保存至: {args.output}")

    except pymysql.MySQLError as e:
        print(f"数据库操作失败: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"执行失败: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()
