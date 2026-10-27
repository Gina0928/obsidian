#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hive 执行器 —— 只在 hive39 venv（Python 3.9 + PyHive + thrift-sasl）下运行。

不由人直接调用；dbquery.py 遇到 engine=hive 时 subprocess 转发到这里。
stdin 收 JSON，stdout 吐 JSON。之所以拆开：PyHive 在 Python 3.13 装不上
thrift-sasl，只有 3.9 那个 venv 具备 Hive 连接能力。
"""

import json
import sys
import time


def fail(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception as e:
        fail("stdin 不是合法 JSON：%s" % e)

    host = payload["host"]
    port = int(payload.get("port", 10000))
    user = payload.get("user") or "root"
    db = payload.get("db") or "app"
    sql = payload["sql"]
    limit = int(payload.get("limit", 200))

    try:
        from pyhive import hive
    except ImportError:
        fail("hive39 venv 缺少 PyHive。装一次即可：\n"
             "  %s -m pip install pyhive thrift thrift-sasl" % sys.executable)

    t0 = time.time()
    try:
        conn = hive.Connection(host=host, port=port, username=user, database=db)
    except Exception as e:
        fail("Hive 连接失败 %s@%s:%s/%s：%s" % (user, host, port, db, e))

    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchmany(limit + 1)
        cols = []
        for d in (cur.description or []):
            name = d[0]
            # HiveServer2 返回的列名常带 table. 前缀，剥掉更好读
            cols.append(name.split(".")[-1] if "." in name else name)
    except Exception as e:
        fail("Hive 执行失败：%s" % e)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    truncated = len(rows) > limit
    rows = rows[:limit]

    def enc(v):
        if v is None:
            return None
        if isinstance(v, (str, int, float, bool)):
            return v
        if isinstance(v, (bytes, bytearray)):
            return v.decode("utf-8", "replace")
        return str(v)

    out = {
        "columns": cols,
        "rows": [[enc(v) for v in r] for r in rows],
        "total": len(rows),
        "truncated": truncated,
        "elapsed": round(time.time() - t0, 3),
    }
    json.dump(out, sys.stdout, ensure_ascii=False, default=str)


if __name__ == "__main__":
    main()
