#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
query_test_data.py — kanma-review 测试数据查询脚本

为「事实驱动铁律 · 第三步 提供数据获取途径」提供可运行的真实数据查询工具，
用于把 A 类表（被查询/校验、需要真实数据的表）的真实行取出来，作为测试用例入参。

设计约束（与技能安全底线 HR-07 一致）：
  - 仅执行只读查询（SELECT / SHOW / information_schema），绝不执行任何写操作（INSERT/UPDATE/DELETE/DDL）。
  - 仅允许连接隔离测试库（localtest / localtesthw）；命中疑似生产库时直接拦截退出，除非显式置
    KANMA_ALLOW_PROD=1（不推荐）。
  - 连接信息来自命令行参数、连接配置文件（--config）、或环境变量（KANMA_DB_HOST/PORT/USER/PASS/NAME），三者优先级 命令行 > 配置文件 > 环境变量；不硬编码任何凭据。
  - 因沙箱默认禁直连 TCP，运行本脚本须带 Bash 工具的 dangerouslyDisableSandbox: true。

依赖：优先使用 pymysql；若未安装则自动回退到系统 mysql CLI（需 mysql 客户端在 PATH）。
输出：JSON（ensure_ascii=False），便于 agent 直接解析后填入测试参数。
"""
import argparse
import json
import os
import sys
import subprocess

# 疑似生产库的弱特征（仅作提示，非穷举）；命中即拦截，除非 KANMA_ALLOW_PROD=1
PROD_HINTS = ("prod", "production", ".g7", "hbyasi.com", "online", "正式")


def die(msg):
    sys.stderr.write("[query_test_data] " + msg + "\n")
    sys.exit(1)


# --------------------------------------------------------------------------- #
# 连接参数
# --------------------------------------------------------------------------- #
def resolve_conn(args):
    # 优先级：命令行 > 配置文件（--config）> 环境变量
    cfg = {}
    if getattr(args, "config", None):
        try:
            with open(args.config, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            die("读取连接配置文件 %s 失败: %s" % (args.config, e))
    host = args.host or cfg.get("host") or os.environ.get("KANMA_DB_HOST")
    port = args.port or cfg.get("port") or int(os.environ.get("KANMA_DB_PORT", "3306"))
    user = args.user or cfg.get("user") or os.environ.get("KANMA_DB_USER")
    password = args.password or cfg.get("password") or os.environ.get("KANMA_DB_PASS")
    database = args.database or cfg.get("database") or os.environ.get("KANMA_DB_NAME")
    if not (host and user and database):
        die("缺少连接参数：请通过 --host/--user/--database 提供，或设置环境变量 "
            "KANMA_DB_HOST / KANMA_DB_USER / KANMA_DB_NAME（密码 KANMA_DB_PASS，端口 KANMA_DB_PORT）。")
    # 生产库弱拦截
    low = (host + " " + database).lower()
    if any(h in low for h in PROD_HINTS) and not os.environ.get("KANMA_ALLOW_PROD"):
        die("安全拦截：检测到疑似生产库 (%s / %s)。本脚本仅允许隔离测试库(localtest/localtesthw)。"
            "如确属误判，置 KANMA_ALLOW_PROD=1 后重试。" % (host, database))
    return host, port, user, password, database


# --------------------------------------------------------------------------- #
# 执行 SELECT：优先 pymysql，回退 mysql CLI
# --------------------------------------------------------------------------- #
def _run_pymysql(sql, conn):
    import pymysql
    c = pymysql.connect(host=conn[0], port=conn[1], user=conn[2], password=conn[3],
                        database=conn[4], charset="utf8mb4", connect_timeout=10,
                        cursorclass=pymysql.cursors.DictCursor)
    try:
        with c.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()
    finally:
        c.close()


def _run_cli(sql, conn):
    host, port, user, password, database = conn
    cmd = ["mysql", "-h" + host, "-P" + str(port), "-u" + user, "-D" + database,
           "--default-character-set=utf8mb4", "--json", "-e", sql]
    env = dict(os.environ)
    if password:
        env["MYSQL_PWD"] = password
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        die("mysql CLI 执行失败: " + (r.stderr.strip() or r.stdout.strip()))
    out = r.stdout.strip()
    if not out:
        return []
    data = json.loads(out)
    # mysql --json 可能返回 {"records":[...]} 或直接是列表
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "records" in data:
        return data["records"]
    return []


def run_select(sql, conn):
    try:
        return _run_pymysql(sql, conn)
    except ImportError:
        return _run_cli(sql, conn)


def dump(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


# --------------------------------------------------------------------------- #
# 子命令
# --------------------------------------------------------------------------- #
def cmd_schema(args, conn):
    table = args.table
    ddl = run_select("SHOW CREATE TABLE `%s`" % table, conn)
    cols = run_select(
        "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY, "
        "COLUMN_DEFAULT, EXTRA FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = '%s' AND TABLE_NAME = '%s' ORDER BY ORDINAL_POSITION"
        % (conn[4], table), conn)
    cons = run_select(
        "SELECT CONSTRAINT_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME "
        "FROM information_schema.KEY_COLUMN_USAGE "
        "WHERE TABLE_SCHEMA = '%s' AND TABLE_NAME = '%s' "
        "AND REFERENCED_TABLE_NAME IS NOT NULL" % (conn[4], table), conn)
    dump({
        "table": table,
        "ddl": (ddl[0].get("Create Table") if ddl else None),
        "columns": cols,
        "foreign_keys": cons,
    })


def cmd_fetch(args, conn):
    table = args.table
    fields = args.fields or "*"
    where = (" WHERE " + args.where) if args.where else ""
    limit = args.limit
    sql = "SELECT %s FROM `%s`%s LIMIT %d" % (fields, table, where, limit)
    rows = run_select(sql, conn)
    dump({"sql": sql, "row_count": len(rows), "rows": rows})


def cmd_branches(args, conn):
    """对 A 类表取 正常 / 边界 / 异常 三类真实数据，直接服务于测试用例分支覆盖。"""
    table, pk = args.table, args.pk
    n = args.limit
    normal = run_select("SELECT * FROM `%s` WHERE `%s` IS NOT NULL LIMIT %d" % (table, pk, n), conn)
    # 边界：取数值列的 最小/最大 各一行（未指定 --num-col 则跳过并提示）
    if args.num_col:
        boundary_min = run_select("SELECT * FROM `%s` ORDER BY `%s` ASC LIMIT 1" % (table, args.num_col), conn)
        boundary_max = run_select("SELECT * FROM `%s` ORDER BY `%s` DESC LIMIT 1" % (table, args.num_col), conn)
    else:
        boundary_min = boundary_max = "（未指定 --num-col，跳过边界值查询；请补充数值列名以取最小/最大边界行）"
    # 异常：取一个必然不存在的主键值（MAX+1）跑一次，确认用于 NOT FOUND 分支
    mx = run_select("SELECT MAX(`%s`) AS m FROM `%s`" % (pk, table), conn)
    maxv = mx[0].get("m") if mx else None
    nonexist = (maxv if isinstance(maxv, int) else 0) + 1
    exc = run_select("SELECT * FROM `%s` WHERE `%s` = %s" % (table, pk, nonexist), conn)
    dump({
        "table": table,
        "pk": pk,
        "normal_existing_rows": normal,
        "boundary_min_row": boundary_min,
        "boundary_max_row": boundary_max,
        "exception_nonexistent_pk_value": nonexist,
        "exception_query_result": exc,
        "note": "normal_existing_rows 用于正常用例入参；boundary_* 用于边界值用例；"
                "exception_query_result 为空即证明该 pk 不存在，可作为异常/查不到分支的入参。",
    })


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(
        description="kanma-review 测试数据查询脚本（仅只读；仅隔离测试库；支持 pymysql 或 mysql CLI）")
    p.add_argument("--host", help="数据库地址（或环境变量 KANMA_DB_HOST）")
    p.add_argument("--port", type=int, help="端口（默认 3306 / KANMA_DB_PORT）")
    p.add_argument("--user", help="用户名（或环境变量 KANMA_DB_USER）")
    p.add_argument("--password", help="密码（或环境变量 KANMA_DB_PASS）")
    p.add_argument("--database", "-d", help="库名（或环境变量 KANMA_DB_NAME）")
    p.add_argument("--config", help="连接配置文件路径（JSON：{host,port,user,password,database}），优先级高于环境变量、低于命令行参数")

    sub = p.add_subparsers(dest="cmd", required=True)

    s_schema = sub.add_parser("schema", help="输出表结构（DDL + 列 + 外键），用于确认约束/枚举/默认值")
    s_schema.add_argument("table", help="表名")

    s_fetch = sub.add_parser("fetch", help="取真实数据行（正常用例入参来源）")
    s_fetch.add_argument("table", help="表名")
    s_fetch.add_argument("--fields", help="字段列表，逗号分隔（默认 *，仅取方法实际用到的字段+主键）")
    s_fetch.add_argument("--where", help="WHERE 条件（不含 WHERE 关键字）")
    s_fetch.add_argument("--limit", type=int, default=10, help="返回行数上限（默认 10）")

    s_branch = sub.add_parser("branches", help="取 正常/边界/异常 三类数据，服务用例分支覆盖")
    s_branch.add_argument("table", help="A 类表名")
    s_branch.add_argument("pk", help="主键列名（用于正常存在性校验与异常 NOT FOUND）")
    s_branch.add_argument("--num-col", help="数值列名，用于取最小/最大边界行")
    s_branch.add_argument("--limit", type=int, default=5, help="正常行取样数量（默认 5）")

    args = p.parse_args()
    conn = resolve_conn(args)

    if args.cmd == "schema":
        cmd_schema(args, conn)
    elif args.cmd == "fetch":
        cmd_fetch(args, conn)
    elif args.cmd == "branches":
        cmd_branches(args, conn)


if __name__ == "__main__":
    main()
