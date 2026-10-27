#!/usr/bin/env python3
"""Fallback DB connector for inventory-init-validate.

Use this when the MySQL MCP connector (mcp__mysql__query) is unavailable
(typically ETIMEDOUT from WorkBuddy's MCP layer while the agent's own sandbox
network can still reach the database directly). It reads the connection
credentials from ~/.workbuddy/mcp.json (the MCP server env block) and runs a
read-only SQL query via pymysql.

Why this works: the MCP server process may run in an isolated/cloud environment
that cannot reach the DB (e.g. an Aliyun RDS behind an IP whitelist), whereas
the agent's own sandbox often shares the user's network egress and CAN reach it.
Navicat on the user's machine also reaches it — so when even this script fails,
ask the user to run the query in Navicat and paste the result.

Usage:
  # inline SQL
  db_connect.py --server mysql_wms_prod --sql "SELECT 1"
  # SQL from a file
  db_connect.py --server mysql_wms_test --file query.sql
  # SQL from stdin
  echo "SELECT 1" | db_connect.py --server mysql_wms_prod

Run with the managed Python venv that has pymysql installed, e.g.:
  <managed-venv>/Scripts/python.exe db_connect.py --server mysql_wms_prod --sql "..."

Safety:
  - Credentials are read ONLY from mcp.json; the password is never printed.
  - Connect uses connect_timeout=15 / read_timeout=60.
  - A read-only guard rejects any statement containing write keywords
    (INSERT/UPDATE/DELETE/DROP/...) or `SELECT INTO` before connecting.
  - `--list-servers` prints the configured MySQL server keys without connecting.
"""
import argparse
import json
import os
import re
import subprocess
import sys


WRITE_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
    "RENAME", "GRANT", "REVOKE", "REPLACE", "LOAD", "MERGE", "CALL",
    "LOCK", "UNLOCK", "SET", "USE", "INTO",
)
ALLOWED_PREFIX = ("SELECT", "WITH", "SHOW", "EXPLAIN", "DESCRIBE", "DESC")


def assert_readonly(sql):
    """Reject any statement that is not a pure read.

    Returns an error string when the SQL is unsafe, or None when it is safe to
    run. Splits on ';' and checks each non-empty statement: it must start with a
    read-only verb and must not contain any write keyword (INSERT/UPDATE/... or
    SELECT INTO).
    """
    for raw in sql.split(";"):
        s = raw.strip()
        if not s:
            continue
        # strip line and block comments crudely
        s = re.sub(r"--[^\n]*", " ", s)
        s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
        s = s.strip()
        if not s:
            continue
        first = s.split(None, 1)[0].upper()
        if first not in ALLOWED_PREFIX:
            return f"statement starts with '{first}', not a read-only verb"
        up = s.upper()
        for kw in WRITE_KEYWORDS:
            if re.search(r"\b" + kw + r"\b", up):
                return f"write keyword '{kw}' detected in statement"
    return None


def ensure_pymysql():
    try:
        import pymysql  # noqa: F401
    except ImportError:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "pymysql"],
            check=True,
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--server",
        default="mysql_wms_prod",
        help="Key under mcpServers in ~/.workbuddy/mcp.json "
             "(e.g. mysql_wms_prod, mysql_wms_test)",
    )
    ap.add_argument("--sql")
    ap.add_argument("--file", help="Read SQL from this file instead of --sql")
    ap.add_argument(
        "--mcp-json",
        default=os.path.expanduser("~/.workbuddy/mcp.json"),
    )
    ap.add_argument(
        "--list-servers",
        action="store_true",
        help="List MySQL server keys configured in mcp.json and exit",
    )
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    if args.list_servers:
        try:
            with open(args.mcp_json, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            print(f"ERROR reading {args.mcp_json}: {e}", file=sys.stderr)
            sys.exit(3)
        keys = [k for k in cfg.get("mcpServers", {}) if "mysql" in k.lower()]
        if keys:
            print("Available MySQL server keys in mcp.json:")
            for k in sorted(keys):
                print(f"  - {k}")
        else:
            print("No MySQL server keys found under mcpServers.")
        sys.exit(0)

    sql = args.sql
    if not sql and args.file:
        with open(args.file, encoding="utf-8") as f:
            sql = f.read()
    if not sql:
        sql = sys.stdin.read()
    sql = sql.strip()
    if not sql:
        print("ERROR: no SQL provided (use --sql, --file, or stdin)", file=sys.stderr)
        sys.exit(2)

    guard_err = assert_readonly(sql)
    if guard_err:
        print(f"ERROR: read-only guard blocked query: {guard_err}", file=sys.stderr)
        sys.exit(9)

    try:
        with open(args.mcp_json, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"ERROR reading {args.mcp_json}: {e}", file=sys.stderr)
        sys.exit(3)

    srv = cfg.get("mcpServers", {}).get(args.server)
    if not srv:
        print(
            f"ERROR: server '{args.server}' not found under mcpServers in "
            f"{args.mcp_json}",
            file=sys.stderr,
        )
        sys.exit(3)

    env = srv.get("env", {})
    host = env.get("MYSQL_HOST")
    port = int(env.get("MYSQL_PORT", 3306))
    user = env.get("MYSQL_USER")
    pw = env.get("MYSQL_PASSWORD")
    db = env.get("MYSQL_DATABASE", "")
    if not host or not user or pw is None:
        print(
            f"ERROR: incomplete connection env for '{args.server}' "
            f"(need MYSQL_HOST/USER/PASSWORD)",
            file=sys.stderr,
        )
        sys.exit(3)

    ensure_pymysql()
    import pymysql

    try:
        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=pw,
            database=db or None,
            connect_timeout=15,
            read_timeout=args.timeout,
            charset="utf8mb4",
        )
    except Exception as e:
        print(f"CONNECT_FAIL {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(4)

    try:
        cur = conn.cursor()
        cur.execute(sql)
        if cur.description:
            cols = [d[0] for d in cur.description]
            print(" | ".join(str(c) for c in cols))
            for r in cur.fetchall():
                print(" | ".join("" if v is None else str(v) for v in r))
        else:
            print(f"OK rows={cur.rowcount}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
