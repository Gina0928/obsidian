#!/usr/bin/env python3
"""构造 WMS 监控日志导出 URL（测试/生产），内置约束校验，可选下载。

用法:
  python build_log_url.py --env prod --date 2026-09-07 \
      --time-range "14:43:54 - 23:59:59" \
      --message 1788767039401 1788767039306 [--fetch out.csv]

校验（仿 monitor-log R1/V1、R3/V2）:
  - executeTimeRange 跨度过长（>24h 或 起始晚于结束）-> 拒绝，提示按单日拆分
  - message 任一条件长度 < 3 -> 拒绝（关键字过短会匹配过多）
  - 通过才打印 URL，并打印一行 `校验结果：通过`

说明:
  - executeTimeRange 中的 ':' 编码为 %3A，空格编码为 +，'-' 保持。
  - message 多条件用字面 '+' 直连，不做二次编码（避免破坏分隔符语义）。
  - --base 可覆盖基础地址，便于对齐 monitor-log 的 monitorBase 配置。
"""
import argparse
import urllib.request
import sys

BASE = {
    "test": "https://monitor-test.selline.cn/sysLog/loggerLog/export",
    "prod": "https://monitor-yas.myt11.com/sysLog/loggerLog/export",
}


def _parse_hms(s):
    h, m, sec = s.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + int(sec)


def validate(time_range, messages):
    """返回 (ok, reason)。"""
    # V1: 单日内时间区间，跨度 <= 24h，且 起始 <= 结束
    try:
        start_s, end_s = [t.strip() for t in time_range.split("-")]
        s_sec = _parse_hms(start_s)
        e_sec = _parse_hms(end_s)
    except Exception:
        return False, "时间区间格式应为 HH:MM:SS - HH:MM:SS"
    if e_sec < s_sec:
        return False, "时间区间起始晚于结束，请检查"
    span_h = (e_sec - s_sec) / 3600.0
    if span_h > 24:
        return False, f"时间跨度 {span_h:.1f}h 超过 24 小时，monitor 仅支持单日，请按单日拆分"
    # V2: message 各条件长度 >= 3
    for m in messages:
        if len(m) < 3:
            return False, f"关键字 '{m}' 长度不足 3 字符，会匹配过多记录，请补充更具体的关键字"
    return True, ""


def build(env, date, time_range, messages,
          provider_apps="yas-gateway-invoker",
          level="", class_name="", trace_id="", base=None):
    base_url = base or BASE[env]
    tr = time_range.replace(":", "%3A").replace(" ", "+")
    message = "+".join(messages) if messages else ""
    params = [
        ("providerApps", provider_apps),
        ("executeDate", date),
        ("executeTimeRange", tr),
        ("level", level),
        ("className", class_name),
        ("traceId", trace_id),
        ("message", message),
    ]
    query = "&".join(f"{k}={v}" for k, v in params)
    return f"{base_url}?{query}"


def main():
    p = argparse.ArgumentParser(description="Build WMS log export URL (with guardrails)")
    p.add_argument("--env", required=True, choices=["test", "prod"])
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--time-range", required=True, help='HH:MM:SS - HH:MM:SS')
    p.add_argument("--message", nargs="+", default=[],
                   help="one or more message filters, joined by +")
    p.add_argument("--provider-apps", default="yas-gateway-invoker")
    p.add_argument("--level", default="")
    p.add_argument("--class-name", default="")
    p.add_argument("--trace-id", default="")
    p.add_argument("--base", default=None,
                   help="override base URL (align with monitor-log monitorBase)")
    p.add_argument("--fetch", metavar="OUTFILE",
                   help="best-effort download export to OUTFILE")
    args = p.parse_args()

    ok, reason = validate(args.time_range, args.message)
    if not ok:
        print(f"校验结果：拒绝 — {reason}")
        sys.exit(1)
    print("校验结果：通过")

    url = build(args.env, args.date, args.time_range, args.message,
                args.provider_apps, args.level, args.class_name, args.trace_id,
                args.base)
    print(url)

    if args.fetch:
        try:
            urllib.request.urlretrieve(url, args.fetch)
            print(f"downloaded -> {args.fetch}")
        except Exception as e:  # noqa: BLE001
            print(f"FETCH_FAILED: {e}", file=sys.stderr)
            sys.exit(2)


if __name__ == "__main__":
    main()
