#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
WMS 排查技能 —— 反馈池 CLI（纯标准库，无第三方依赖）

生产 / 测试两个排查技能共用同一个反馈池，经验互推。
本文件在两个技能中各存一份，内容完全一致，改一处要同步另一处。

共享池目录: C:\\Users\\yuai\\.workbuddy\\skills\\.wms-triage-feedback\\
  pool.jsonl   每行一条 JSON，含 open / merged / rejected 全量（审计留痕）

用法:
  python feedback.py add      --skill prod|test|both --kind <类型> --topic "<标题>" \
                              [--detail "<发生了什么>"] [--fix "<建议怎么改>"] \
                              [--target "<落点文件>"] [--evidence "<证据>"] [--source user|auto]
  python feedback.py review   [--all] [--skill prod|test|both] [--kind <类型>] [--json]
  python feedback.py hit      <ID> [--evidence "<这次的证据>"]
  python feedback.py resolve  <ID> --to <落点文件> [--note "<备注>"]
  python feedback.py reject   <ID> --reason "<为什么不采纳>"
  python feedback.py stats

kind 取值:
  correction 纠错  —— 技能里写错了 / 已过期（表名、字段名、连接名、阈值、文档路径）
  gap        补齐  —— 缺了某个高频知识点或步骤，导致每次都要重新摸索
  efficiency 效率  —— 走了弯路、重复劳动，可固化为脚本或查询片段
  redline    红线  —— 差点违反或已违反硬约束（写生产库、无门店查生产、性能结论外推）
  env        环境  —— 环境 / MCP 连接 / 文档索引 / 分表规则发生变化

合并就绪判定（review 里的 READY 列）:
  NOW    红线类 / 用户显式纠正 / 命中 >= 2 次      -> 应立即合并进技能
  REVIEW 命中 1 次且已沉淀 >= 14 天                 -> 复核一次，判断是偶发还是规律
  WAIT   其余                                       -> 继续观察，不要改技能
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

POOL_DIR = os.environ.get(
    "WMS_FEEDBACK_POOL",
    r"C:\Users\yuai\.workbuddy\skills\.wms-triage-feedback",
)
POOL_FILE = os.path.join(POOL_DIR, "pool.jsonl")

KINDS = ["correction", "gap", "efficiency", "redline", "env"]
KIND_CN = {
    "correction": "纠错",
    "gap": "补齐",
    "efficiency": "效率",
    "redline": "红线",
    "env": "环境",
}
SKILLS = ["prod", "test", "both"]
READY_AGE_DAYS = 14
READY_HITS = 2

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load():
    if not os.path.exists(POOL_FILE):
        return []
    out = []
    with open(POOL_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def save(items):
    os.makedirs(POOL_DIR, exist_ok=True)
    with open(POOL_FILE, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")


def next_id(items):
    n = 0
    for it in items:
        raw = str(it.get("id", ""))
        if raw.startswith("F") and raw[1:].isdigit():
            n = max(n, int(raw[1:]))
    return "F%03d" % (n + 1)


def age_days(ts):
    try:
        return (datetime.now() - datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")).days
    except Exception:
        return 0


def readiness(e):
    if e.get("status") != "open":
        return "-"
    if e.get("kind") == "redline":
        return "NOW"
    if e.get("source") == "user":
        return "NOW"
    if int(e.get("hits", 1)) >= READY_HITS:
        return "NOW"
    if age_days(e.get("ts", "")) >= READY_AGE_DAYS:
        return "REVIEW"
    return "WAIT"


def norm(s):
    return "".join((s or "").split()).lower()


def cmd_add(args):
    if args.kind not in KINDS:
        sys.exit("kind 必须是: %s" % ", ".join(KINDS))
    if args.skill not in SKILLS:
        sys.exit("skill 必须是: %s" % ", ".join(SKILLS))

    items = load()
    key = (norm(args.topic), args.kind, args.skill)

    # 同类去重：已存在同 skill + 同 kind + 同 topic 的 open 条目 -> 命中 +1
    for it in items:
        if it.get("status") == "open" and \
           (norm(it.get("topic")), it.get("kind"), it.get("skill")) == key:
            it["hits"] = int(it.get("hits", 1)) + 1
            it["ts"] = now_str()
            if args.evidence:
                it["evidence"] = (it.get("evidence", "") + " | " + args.evidence).strip(" |")
            if args.fix and not it.get("fix"):
                it["fix"] = args.fix
            if args.target and not it.get("target"):
                it["target"] = args.target
            save(items)
            print("已存在同类条目 %s，命中次数 +1 -> %s（%s）"
                  % (it["id"], it["hits"], readiness(it)))
            return

    entry = {
        "id": next_id(items),
        "ts": now_str(),
        "skill": args.skill,
        "kind": args.kind,
        "source": args.source,
        "topic": args.topic,
        "detail": args.detail or "",
        "fix": args.fix or "",
        "target": args.target or "",
        "evidence": args.evidence or "",
        "hits": 1,
        "status": "open",
        "resolved_ts": None,
        "resolution": None,
    }
    items.append(entry)
    save(items)
    print("已记录 %s [%s/%s] %s  (READY=%s)"
          % (entry["id"], entry["skill"], KIND_CN[entry["kind"]], entry["topic"],
             readiness(entry)))


def cmd_review(args):
    items = load()
    if not args.all:
        items = [e for e in items if e.get("status") == "open"]
    if args.skill:
        items = [e for e in items if e.get("skill") in (args.skill, "both")]
    if args.kind:
        items = [e for e in items if e.get("kind") == args.kind]

    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return

    if not items:
        print("反馈池为空（无待办条目）。")
        return

    order = {"NOW": 0, "REVIEW": 1, "WAIT": 2, "-": 3}
    items.sort(key=lambda e: (order.get(readiness(e), 9), e.get("id", "")))

    print("反馈池: %s" % POOL_FILE)
    print("=" * 78)
    for e in items:
        print("[%s] READY=%-6s %s/%s  命中%s次  %s"
              % (e.get("id"), readiness(e),
                 e.get("skill"), KIND_CN.get(e.get("kind"), e.get("kind")),
                 e.get("hits", 1), e.get("ts")))
        print("  主题  : %s" % e.get("topic"))
        if e.get("detail"):
            print("  现象  : %s" % e.get("detail"))
        if e.get("evidence"):
            print("  证据  : %s" % e.get("evidence"))
        if e.get("fix"):
            print("  建议  : %s" % e.get("fix"))
        if e.get("target"):
            print("  落点  : %s" % e.get("target"))
        if e.get("source") == "user":
            print("  来源  : 用户显式纠正")
        if e.get("status") != "open":
            print("  状态  : %s @ %s  %s"
                  % (e.get("status"), e.get("resolved_ts"), e.get("resolution") or ""))
        print("-" * 78)

    now_n = len([e for e in items if readiness(e) == "NOW"])
    both_n = len([e for e in items if e.get("skill") == "both" and e.get("status") == "open"])
    print("合计 %s 条，其中 %s 条应立即合并(NOW)。" % (len(items), now_n))
    if both_n:
        print("注意: 有 %s 条 skill=both，合并时须同步修改 prod-issue-triage 与 "
              "test-issue-triage 两个技能。" % both_n)


def find(items, eid):
    eid = eid.upper()
    for e in items:
        if str(e.get("id", "")).upper() == eid:
            return e
    return None


def cmd_hit(args):
    items = load()
    e = find(items, args.id)
    if not e:
        sys.exit("未找到条目 %s" % args.id)
    if e.get("status") != "open":
        sys.exit("条目 %s 已关闭（%s），如需重新观察请新建一条。" % (e["id"], e["status"]))
    e["hits"] = int(e.get("hits", 1)) + 1
    e["ts"] = now_str()
    if args.evidence:
        e["evidence"] = (e.get("evidence", "") + " | " + args.evidence).strip(" |")
    save(items)
    print("已存在条目 %s 命中次数 +1 -> %s（%s）" % (e["id"], e["hits"], readiness(e)))


def cmd_resolve(args):
    items = load()
    e = find(items, args.id)
    if not e:
        sys.exit("未找到条目 %s" % args.id)
    e["status"] = "merged"
    e["resolved_ts"] = now_str()
    e["resolution"] = ("已合并 -> %s" % args.to) + (" | %s" % args.note if args.note else "")
    if args.to and not e.get("target"):
        e["target"] = args.to
    save(items)
    print("已标记 %s 为 merged -> %s" % (e["id"], args.to))
    if e.get("skill") == "both":
        print("该条 skill=both，请确认 prod-issue-triage 与 test-issue-triage 两侧都已改到。")


def cmd_reject(args):
    items = load()
    e = find(items, args.id)
    if not e:
        sys.exit("未找到条目 %s" % args.id)
    e["status"] = "rejected"
    e["resolved_ts"] = now_str()
    e["resolution"] = args.reason
    save(items)
    print("已标记 %s 为 rejected: %s" % (e["id"], args.reason))


def cmd_stats(args):
    items = load()
    if not items:
        print("反馈池为空。")
        return
    open_items = [e for e in items if e.get("status") == "open"]
    by_kind, by_skill, by_status = {}, {}, {}
    for e in items:
        by_kind[e.get("kind", "?")] = by_kind.get(e.get("kind", "?"), 0) + 1
        by_skill[e.get("skill", "?")] = by_skill.get(e.get("skill", "?"), 0) + 1
        by_status[e.get("status", "?")] = by_status.get(e.get("status", "?"), 0) + 1

    print("反馈池: %s" % POOL_FILE)
    print("总条目 %s | 待办 %s | 已合并 %s | 已拒绝 %s"
          % (len(items), len(open_items),
             by_status.get("merged", 0), by_status.get("rejected", 0)))
    print("按技能: " + ", ".join("%s=%s" % (k, v) for k, v in sorted(by_skill.items())))
    print("按类型: " + ", ".join(
        "%s(%s)=%s" % (k, KIND_CN.get(k, k), v) for k, v in sorted(by_kind.items())))
    now_n = [e for e in open_items if readiness(e) == "NOW"]
    if now_n:
        print("待合并(NOW): " + ", ".join(e["id"] for e in now_n))
    else:
        print("待合并(NOW): 无")


def main():
    p = argparse.ArgumentParser(
        description="WMS 排查技能反馈池 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    a = sub.add_parser("add", help="记录一条反馈（同类自动命中+1）")
    a.add_argument("--skill", required=True, choices=SKILLS)
    a.add_argument("--kind", required=True, choices=KINDS)
    a.add_argument("--topic", required=True, help="简短标题，同类去重的依据，要写稳")
    a.add_argument("--detail", default="", help="具体发生了什么")
    a.add_argument("--fix", default="", help="建议怎么改")
    a.add_argument("--target", default="", help="建议落点，如 SKILL.md / references/environment.md")
    a.add_argument("--evidence", default="", help="证据：报错、SQL、文档名")
    a.add_argument("--source", default="auto", choices=["user", "auto"],
                   help="user=用户显式纠正（立即就绪），auto=任务后自动复盘")
    a.set_defaults(func=cmd_add)

    r = sub.add_parser("review", help="列出待办条目")
    r.add_argument("--all", action="store_true", help="含已合并/已拒绝")
    r.add_argument("--skill", choices=SKILLS)
    r.add_argument("--kind", choices=KINDS)
    r.add_argument("--json", action="store_true", help="输出 JSON 供程序消费")
    r.set_defaults(func=cmd_review)

    h = sub.add_parser("hit", help="再次踩到同一个坑，命中次数 +1")
    h.add_argument("id")
    h.add_argument("--evidence", default="")
    h.set_defaults(func=cmd_hit)

    v = sub.add_parser("resolve", help="标记已合并进技能")
    v.add_argument("id")
    v.add_argument("--to", required=True, help="实际落点文件")
    v.add_argument("--note", default="")
    v.set_defaults(func=cmd_resolve)

    j = sub.add_parser("reject", help="标记不采纳")
    j.add_argument("id")
    j.add_argument("--reason", required=True)
    j.set_defaults(func=cmd_reject)

    s = sub.add_parser("stats", help="统计概览")
    s.set_defaults(func=cmd_stats)

    args = p.parse_args()
    if not getattr(args, "cmd", None):
        p.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
