#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dbq —— 统一数据库只读查询入口

一次调用起一个进程，查完即退，常驻进程 0 个。
护栏在代码里：非 SELECT 一律拒绝，退出码 2。生产库写操作走正式变更流程，
不是这个脚本能碰的。

用法
  dbq <target> <sql>                 查询
  dbq <target> @file.sql             从文件读 SQL
  dbq --list [env]                   列出连接（不含密码）
  dbq --ping <target>                探活
  dbq --find <关键词>                按库名/主机/备注反查该连哪个

target 三种写法
  环境/库      yas/jy_order
  库名         jy_order       命中多个环境时列出候选，绝不猜
  实例名       yas-order

常用参数
  --limit N        返回行数上限，默认 200，硬上限 5000
  --format table|tsv|json   默认 table
  --timeout N      查询超时秒数，默认 120
  --no-limit-check 关闭自动追加 LIMIT（仅限 SQL 自带 LIMIT 或聚合查询）
  --explain        只做 EXPLAIN，不执行

引擎
  mysql   pymysql 直连
  presto  REST（requests）
  es      REST，target 写 yas-es/<index>，SQL 位置传 JSON DSL 或 @file.json
  hive    自动转发到 hive39 venv（Python 3.9 + PyHive）
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from decimal import Decimal
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(os.path.dirname(HERE), "config", "connections.yaml")
HIVE_EXEC = os.path.join(HERE, "hive_exec.py")
# hive39 venv 解释器：Windows 是 Scripts/python.exe，mac/Linux 是 bin/python
if os.name == "nt":
    HIVE39_PY = os.path.join(os.path.expanduser("~"),
                             ".workbuddy", "binaries", "python", "envs",
                             "hive39", "Scripts", "python.exe")
else:
    HIVE39_PY = os.path.join(os.path.expanduser("~"),
                             ".workbuddy", "binaries", "python", "envs",
                             "hive39", "bin", "python")

EXIT_OK, EXIT_ERR, EXIT_GUARD = 0, 1, 2

# 首关键字白名单
ALLOW_FIRST = {"SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "WITH"}
# 语句里出现这些词一律拒绝，防止注释绕过、UNION 夹带、CTE 里藏写操作
BLOCK_WORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|REPLACE|"
    r"RENAME|CALL|KILL|OPTIMIZE|REPAIR|ANALYZE|LOCK\s+TABLES|LOAD\s+DATA|"
    r"INTO\s+OUTFILE|INTO\s+DUMPFILE|INSERT\s+OVERWRITE|SET\s+GLOBAL|"
    r"CREATE\s+TEMPORARY)\b",
    re.I,
)
ES_READ_PATHS = re.compile(r"^(_search|_count|_msearch|_mget|_cat|_mapping|_settings|_alias|_sql/?translate)$")


def die(msg, code=EXIT_ERR):
    print(msg, file=sys.stderr)
    sys.exit(code)


def proxies_for(host):
    """内网地址绕过环境 HTTP 代理，公网地址照常走代理。

    本机常设 HTTP_PROXY=127.0.0.1:5xxxx（WorkBuddy 自带代理），
    10.x / 192.168.x 这类内网库被它一转必然超时。
    """
    try:
        import ipaddress
        if ipaddress.ip_address(host).is_private:
            return {"http": None, "https": None}
    except ValueError:
        pass  # 域名，交给环境默认
    return None


def load_config():
    try:
        import yaml
    except ImportError:
        die("缺少 PyYAML。装一次即可：\n"
            "  %s -m pip install pyyaml" % sys.executable)
    if not os.path.exists(CONFIG):
        die("找不到注册表：%s" % CONFIG)
    return yaml.safe_load(open(CONFIG, encoding="utf-8"))


def all_instances(cfg):
    return cfg.get("instances", {})


def resolve(cfg, target):
    """三级寻址：实例名 > 环境/库 > 库名。命中多个列候选。"""
    insts = all_instances(cfg)

    if target in insts:
        return insts[target], None

    if "/" in target:
        env, db = target.split("/", 1)
        hits = {k: v for k, v in insts.items()
                if v.get("env") == env and db in (v.get("databases") or [])}
        if not hits:
            # 环境对但库没登记：该环境 databases 为空的实例也允许，需显式写 库.表
            loose = {k: v for k, v in insts.items()
                     if v.get("env") == env and not (v.get("databases") or [])}
            if loose:
                return list(loose.values())[0], db
            die("环境 %s 下没有登记库 %s。用 dbq --list %s 看有哪些" % (env, db, env))
        if len(hits) > 1:
            die("环境 %s 下 %s 命中多个实例：%s\n请用实例名精确指定" % (env, db, ", ".join(hits)))
        inst = list(hits.values())[0]
        return inst, db

    hits = {k: v for k, v in insts.items() if target in (v.get("databases") or [])}
    if not hits:
        die("没有任何实例登记了库 %s。用 dbq --find %s 反查" % (target, target))
    if len(hits) > 1:
        envs = sorted(set(v["env"] for v in hits.values()))
        cand = ", ".join(sorted(hits))
        die("库 %s 在多个环境存在（%s），必须指定环境：\n  %s\n"
            "例：dbq %s/%s \"SELECT 1\"" % (target, "/".join(envs), cand, envs[0], target))
    return list(hits.values())[0], target


def strip_comments(sql):
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = re.sub(r"^\s*--.*$", " ", sql, flags=re.M)
    sql = re.sub(r"^\s*#.*$", " ", sql, flags=re.M)
    return sql.strip()


def guard_sql(sql, engine):
    """只读护栏。违规直接退出码 2，不给数据库任何执行机会。"""
    clean = strip_comments(sql)
    if not clean:
        die("SQL 为空", EXIT_GUARD)

    first = re.match(r"^(\w+)", clean)
    if not first:
        die("解析不出 SQL 首关键字：%r" % clean[:60], EXIT_GUARD)
    kw = first.group(1).upper()

    if kw not in ALLOW_FIRST:
        die("只读护栏拦截：首关键字 %s 不在允许列表 %s 内。\n"
            "生产库写操作请走 DBA 正式变更流程。" % (kw, "/".join(sorted(ALLOW_FIRST))), EXIT_GUARD)

    hit = BLOCK_WORDS.search(clean)
    if hit:
        die("只读护栏拦截：语句里出现被禁关键字 %r。\n"
            "生产库写操作请走 DBA 正式变更流程。" % hit.group(0), EXIT_GUARD)

    if re.search(r";\s*\S", clean.rstrip(";")):
        die("只读护栏拦截：检测到多语句（分号后还有内容），一次只跑一条。", EXIT_GUARD)


def ensure_limit(sql, limit):
    body = sql.strip().rstrip(";")
    if re.search(r"\bLIMIT\s+\d+", body, re.I):
        return body
    return "%s LIMIT %d" % (body, limit)


def norm(v, maxlen=60):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime) else v.strftime("%Y-%m-%d")
    if isinstance(v, timedelta):
        return str(v)
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8", "replace")[:maxlen]
        except Exception:
            return "<binary>"
    if isinstance(v, (dict, list)):
        s = json.dumps(v, ensure_ascii=False, default=str)
    else:
        s = str(v)
    s = s.replace("\n", "\\n").replace("\r", "").replace("\t", "\\t")
    return s if len(s) <= maxlen else s[: maxlen - 3] + "..."


def render(cols, rows, fmt, total=None, truncated=False):
    if fmt == "json":
        out = {"columns": cols, "rows": [[norm(r[i], 10 ** 6) for i in range(len(cols))] for r in rows]}
        if total is not None:
            out["total"] = total
        out["truncated"] = truncated
        return json.dumps(out, ensure_ascii=False, indent=1)

    if fmt == "tsv":
        lines = ["\t".join(cols)]
        lines += ["\t".join(norm(v, 10 ** 6) for v in r) for r in rows]
        return "\n".join(lines)

    if not cols:
        return "(无结果)"
    shown = [[norm(v) for v in r] for r in rows]
    widths = [max(len(cols[i]), *(len(r[i]) for r in shown)) if shown else len(cols[i])
              for i in range(len(cols))]
    widths = [min(w, 48) for w in widths]
    out = ["| " + " | ".join(cols[i].ljust(widths[i]) for i in range(len(cols))) + " |",
           "|" + "|".join("-" * (w + 2) for w in widths) + "|"]
    out += ["| " + " | ".join(r[i].ljust(widths[i]) for i in range(len(cols))) + " |" for r in shown]
    return "\n".join(out)


# ---------------- 引擎实现 ----------------

def run_mysql(inst, sql, db, timeout, limit, auto_limit):
    try:
        import pymysql
    except ImportError:
        die("缺少 pymysql。装一次即可：\n"
            "  %s -m pip install pymysql" % sys.executable)

    dbs = inst.get("databases") or []
    use_db = db or (dbs[0] if dbs else None)
    if not use_db:
        die("该实例未登记任何库，请用 库名.表名 写全限定名，或指定 db")

    if auto_limit:
        sql = ensure_limit(sql, limit)

    t0 = time.time()
    try:
        conn = pymysql.connect(
            host=inst["host"], port=int(inst.get("port", 3306)),
            user=inst.get("user"), password=inst.get("password") or "",
            database=use_db, charset="utf8mb4",
            connect_timeout=int(inst.get("connect_timeout", 8)),
            read_timeout=timeout,
        )
    except Exception as e:
        die("连接失败 %s@%s/%s：%s" % (inst.get("user"), inst["host"], use_db, e))

    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            cols = [d[0] for d in (cur.description or [])]
            total = len(rows)
            return cols, rows[:limit], total, total > limit, time.time() - t0
    finally:
        conn.close()


def run_presto(inst, sql, db, timeout, limit, auto_limit):
    import requests

    dbs = inst.get("databases") or []
    schema = db or (dbs[0] if dbs else "app")
    if auto_limit:
        sql = ensure_limit(sql, limit)

    base = "http://%s:%s" % (inst["host"], inst.get("port", 8889))
    headers = {
        "X-Presto-User": inst.get("user") or "root",
        "X-Presto-Catalog": inst.get("catalog") or "hive",
        "X-Presto-Schema": schema,
    }
    px = proxies_for(inst["host"])
    t0 = time.time()
    try:
        r = requests.post(base + "/v1/statement", data=sql.encode("utf-8"),
                          headers=headers, timeout=timeout, proxies=px)
    except Exception as e:
        die("Presto 请求失败：%s" % e)
    if r.status_code != 200:
        die("Presto 返回 %s：%s" % (r.status_code, r.text[:400]))

    cols, rows = [], []
    data = r.json()
    deadline = time.time() + timeout
    while True:
        err = data.get("error")
        if err:
            die("Presto 报错 %s：%s" % (err.get("errorName"), err.get("message", "")[:400]), EXIT_ERR)
        if data.get("columns") and not cols:
            cols = [c["name"] for c in data["columns"]]
        for chunk in data.get("data") or []:
            rows.append(chunk)
        nxt = data.get("nextUri")
        if not nxt:
            break
        if time.time() > deadline:
            die("Presto 查询超时（%ss）" % timeout)
        time.sleep(0.15)
        data = requests.get(nxt, headers=headers, timeout=timeout, proxies=px).json()

    total = len(rows)
    return cols, rows[:limit], total, total > limit, time.time() - t0


def run_es(inst, index, dsl, timeout, limit, auto_limit):
    import requests

    if not index:
        die("ES 的 target 要写成 实例名/<index>，例：yas-es/rlt_gdm_ord_sku")
    try:
        body = json.loads(dsl)
    except Exception as e:
        die("ES 查询体必须是 JSON：%s" % e)

    if auto_limit and "size" not in body and "aggs" not in body:
        body["size"] = min(limit, 200)

    base = "http://%s:%s" % (inst["host"], inst.get("port", 9200))
    url = "%s/%s/_search" % (base, index)
    t0 = time.time()
    try:
        r = requests.post(url, json=body, timeout=timeout, proxies=proxies_for(inst["host"]),
                          headers={"Content-Type": "application/json"})
    except Exception as e:
        die("ES 请求失败：%s\n内网 ES（10.x）本机不可达，需公司网络或 VPN。" % e)
    if r.status_code >= 400:
        die("ES 返回 %s：%s" % (r.status_code, r.text[:400]))
    data = r.json()

    hits = data.get("hits", {})
    srcs = [h.get("_source", {}) for h in (hits.get("hits") or [])]
    total = hits.get("total")
    if isinstance(total, dict):
        total = total.get("value")

    if data.get("aggregations"):
        cols, rows = ["aggregation", "value"], []
        for k, v in data["aggregations"].items():
            if "value" in v:
                rows.append([k, v["value"]])
            elif "buckets" in v:
                for b in v["buckets"][:limit]:
                    rows.append(["%s.%s" % (k, b.get("key")), b.get("doc_count")])
            else:
                rows.append([k, json.dumps(v, ensure_ascii=False)[:200]])
        return cols, rows, len(rows), False, time.time() - t0

    if not srcs:
        return [], [], 0, False, time.time() - t0
    cols = sorted({k for s in srcs for k in s})
    rows = [[s.get(c) for c in cols] for s in srcs]
    return cols, rows[:limit], total if total is not None else len(rows), \
        len(rows) > limit, time.time() - t0


def run_hive(inst, sql, db, timeout, limit, auto_limit):
    """转发到 hive39 venv：PyHive 在 Python 3.13 下不可用，只有 3.9 环境装了 thrift-sasl。"""
    if not os.path.exists(HIVE39_PY):
        die("找不到 hive39 解释器：%s" % HIVE39_PY)
    dbs = inst.get("databases") or []
    use_db = db or (dbs[0] if dbs else "app")

    payload = json.dumps({
        "host": inst["host"], "port": int(inst.get("port", 10000)),
        "user": inst.get("user") or "root", "db": use_db,
        "sql": ensure_limit(sql, limit) if auto_limit else sql,
        "timeout": timeout, "limit": limit,
    })
    try:
        p = subprocess.run([HIVE39_PY, HIVE_EXEC], input=payload,
                           capture_output=True, text=True, timeout=timeout + 60)
    except subprocess.TimeoutExpired:
        die("Hive 查询超时（%ss）" % timeout)

    if p.returncode != 0:
        die(p.stderr.strip() or "Hive 执行失败（退出码 %s）" % p.returncode)
    try:
        res = json.loads(p.stdout)
    except Exception:
        die("Hive 返回无法解析：%s" % p.stdout[:400])

    rows = [tuple(r) for r in res["rows"]]
    return res["columns"], rows, res["total"], res["truncated"], res.get("elapsed", 0)


ENGINES = {"mysql": run_mysql, "presto": run_presto, "es": run_es, "hive": run_hive}


# ---------------- 命令 ----------------

def cmd_list(cfg, env=None, verbose=False):
    insts = all_instances(cfg)
    by_env = {}
    for k, v in sorted(insts.items()):
        by_env.setdefault(v.get("env", "?"), []).append((k, v))
    for e in sorted(by_env):
        if env and e != env:
            continue
        print("\n[%s]" % e)
        for k, v in by_env[e]:
            dbs = ",".join(v.get("databases") or []) or "(不限)"
            print("  %-14s %-6s %-46s %s" % (k, v.get("engine"), dbs, v.get("note", "")))
    print("\n共 %d 个实例。用法：dbq <env>/<db> \"SQL\" 或 dbq --find <库名>" % len(insts))


def cmd_find(cfg, kw):
    insts = all_instances(cfg)
    kw = kw.lower()
    hits = []
    for k, v in sorted(insts.items()):
        blob = " ".join([k, v.get("env", ""), v.get("host", ""), v.get("note", ""),
                         " ".join(v.get("databases") or [])]).lower()
        if kw in blob:
            hits.append((k, v))
    if not hits:
        die("没找到包含 %r 的连接" % kw)
    for k, v in hits:
        dbs = ",".join(v.get("databases") or []) or "(不限)"
        print("%-14s %-6s %-8s %-46s %s" % (k, v.get("engine"), v.get("env"), dbs, v.get("note", "")))
    print("\n共 %d 个匹配" % len(hits))


def cmd_ping(cfg, target):
    inst, db = resolve(cfg, target)
    eng = inst.get("engine")
    t0 = time.time()
    try:
        if eng == "es":
            import requests
            r = requests.get("http://%s:%s" % (inst["host"], inst.get("port", 9200)),
                             timeout=8, proxies=proxies_for(inst["host"]))
            ok = r.status_code == 200
            msg = "HTTP %s" % r.status_code
        else:
            cols, rows, total, trunc, el = ENGINES[eng](inst, "SELECT 1", db, 15, 5, False)
            ok, msg = True, "SELECT 1 返回 %s 行" % total
    except SystemExit:
        raise
    except Exception as e:
        ok, msg = False, str(e)
    print("%-14s %-6s %-46s %s  (%.2fs)" %
          (target, eng, inst["host"], "OK  " + msg if ok else "FAIL " + msg, time.time() - t0))
    sys.exit(EXIT_OK if ok else EXIT_ERR)


def main():
    ap = argparse.ArgumentParser(
        prog="dbq", add_help=True,
        description="统一数据库只读查询入口（mysql/presto/es/hive）")
    ap.add_argument("target", nargs="?", help="yas/jy_order | jy_order | yas-order")
    ap.add_argument("sql", nargs="?", help="SQL；@file.sql 从文件读；ES 传 JSON DSL")
    ap.add_argument("--list", nargs="?", const="", metavar="ENV", help="列出连接")
    ap.add_argument("--find", metavar="KW", help="按库名/主机/备注反查")
    ap.add_argument("--ping", metavar="TARGET", help="探活")
    ap.add_argument("--limit", type=int, default=None, help="返回行数上限，默认 200")
    ap.add_argument("--format", default="table", choices=["table", "tsv", "json"])
    ap.add_argument("--timeout", type=int, default=None, help="查询超时秒数，默认 120")
    ap.add_argument("--no-limit-check", action="store_true", help="不自动追加 LIMIT")
    ap.add_argument("--explain", action="store_true", help="只 EXPLAIN 不执行")
    a = ap.parse_args()

    cfg = load_config()

    if a.list is not None:
        cmd_list(cfg, a.list or None)
        return
    if a.find:
        cmd_find(cfg, a.find)
        return
    if a.ping:
        cmd_ping(cfg, a.ping)
        return
    if not a.target or not a.sql:
        ap.print_help()
        sys.exit(EXIT_ERR)

    sql = a.sql
    if sql.startswith("@"):
        path = os.path.expanduser(sql[1:])
        if not os.path.exists(path):
            die("SQL 文件不存在：%s" % path)
        sql = open(path, encoding="utf-8").read()

    inst, db = resolve(cfg, a.target)
    eng = inst.get("engine")
    if eng not in ENGINES:
        die("未知引擎：%s" % eng)

    limit = a.limit or int(inst.get("max_rows", 200))
    limit = min(limit, 5000)
    timeout = a.timeout or int(inst.get("query_timeout", 120))

    index = None
    if eng == "es":
        # target 形如 yas-es/<index>
        if "/" in a.target:
            index = a.target.split("/", 1)[1]
        else:
            index = db
        db = None
    else:
        guard_sql(sql, eng)
        if a.explain:
            sql = "EXPLAIN " + sql

    runner = ENGINES[eng]
    if eng == "es":
        cols, rows, total, trunc, el = runner(inst, index, sql, timeout, limit, not a.no_limit_check)
    else:
        cols, rows, total, trunc, el = runner(inst, sql, db, timeout, limit,
                                              not a.no_limit_check and not a.explain)

    out = render(cols, rows, a.format, total=total, truncated=trunc)
    print(out)

    tail = []
    if eng != "es":
        tail.append("%s %s %s" % (inst.get("env"), inst.get("engine"), db or ""))
    tail.append("%.2fs" % el)
    if total is not None:
        tail.append("%s 行" % total)
    if trunc:
        tail.append("已截断到 %s 行" % limit)
    print("\n-- " + " | ".join(tail), file=sys.stderr)


if __name__ == "__main__":
    main()
