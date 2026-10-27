#!/usr/bin/env python3
"""判定本周是否结束，供「周报生成器」技能作为生成闸门使用。

无第三方依赖，仅标准库。
用法:
    python check_week.py
    python check_week.py --now 2026-08-31T07:00:00

输出 JSON:
    week_start / week_end  报告目标周的周一/周日 (YYYY-MM-DD)
    cutoff                 生成闸门时间 = 目标周周日 22:00
    now                    当前时刻
    is_complete            True 可生成正式报告；False 仅出草稿
    days_remaining         距目标周周日还有几天（含当天为 0）
    note                   口语化提示
"""
import sys
import json
import datetime


def main():
    now = datetime.datetime.now()
    args = sys.argv[1:]
    if "--now" in args:
        i = args.index("--now")
        now = datetime.datetime.fromisoformat(args[i + 1])

    dow = now.weekday()  # 周一=0 .. 周日=6
    # 当前周（含今天）的周日
    current_week_end = now.date() + datetime.timedelta(days=(6 - dow))
    current_week_start = current_week_end - datetime.timedelta(days=6)

    if dow == 0:
        # 周一：报告"刚结束的上周"
        week_end = current_week_end - datetime.timedelta(days=7)
        week_start = week_end - datetime.timedelta(days=6)
        is_complete = True
        note = "本周一，生成本周结束的那一周（上周）正式周报"
        days_remaining = 0
    elif now >= datetime.datetime.combine(current_week_end, datetime.time(22, 0)):
        # 周日 22:00 之后：当前周已结束
        week_end = current_week_end
        week_start = current_week_start
        is_complete = True
        note = "本周已结束，可生成正式周报"
        days_remaining = 0
    else:
        # 周二~周日 22:00 前：当前周进行中 → 草稿
        week_end = current_week_end
        week_start = current_week_start
        is_complete = False
        days_remaining = (current_week_end - now.date()).days
        note = "本周还有 {} 天结束，先出【周中草稿】".format(days_remaining)

    cutoff = datetime.datetime.combine(week_end, datetime.time(22, 0))
    out = {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "cutoff": cutoff.isoformat(),
        "now": now.isoformat(timespec="seconds"),
        "is_complete": bool(is_complete),
        "days_remaining": int(days_remaining),
        "note": note,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
