#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""周报重复描述行检测 / 自动清理，供「周报生成器」技能在落盘前作为硬闸门使用。

无第三方依赖，仅标准库，Python 3.8+。

用法:
    python dedupe_report.py <report.md>              # 仅检查，输出人读报告
    python dedupe_report.py <report.md> --fix        # 自动清理高置信重复后写回（原文件备份为 .bak）
    python dedupe_report.py <report.md> --json       # 机器可读输出
    python dedupe_report.py <report.md> --fix --json # 组合使用

退出码:
    0 = 未发现任何重复问题（干净，可落盘）
    1 = 发现问题：check 模式表示存在待人工处理项；fix 模式表示文件已被修改，需重跑确认

检测的四类重复:
    L1 字面重复行       规范化后完全相同的行                            → fix 模式自动保留首条、删除后续
    L2 跨条目近似重复    全文任意两条内容行 bigram 相似度 >= 0.70         → 需人工合并
    L3 bullet 复述标题   bullet 与其所属 ✅/🔄 标题行的综合相似度过高     → 高置信(>=0.55) 自动删；疑似(>=0.30) 提示
    L4 亮点/计划照抄正文  亮点/下周计划 行与正文条目相似度 >= 0.50         → 需人工改写为价值提炼 / 下一步动作

综合相似度 sim = 0.5 * jaccard + 0.3 * echo + 0.2 * coverage
    jaccard  : 两行 bigram 集合的交并比
    echo     : 标题 bigram 被 bullet 覆盖的比例（标题被复述了多少）
    coverage : bullet 的字集落在标题字集里的比例（bullet 有多少字是照搬标题）
"""
import sys
import json
import shutil
import argparse
import datetime
import re

# ---------- 阈值（集中配置，便于按实际语料微调） ----------
TH_L2_SIMILAR = 0.70     # 跨条目近似重复
TH_L3_AUTOFIX = 0.55     # bullet 复述标题 —— 高置信，自动删除
TH_L3_SUSPECT = 0.30     # bullet 复述标题 —— 疑似，仅提示
TH_L4_COPY = 0.50        # 亮点/计划 照抄正文条目
MIN_LEN = 6              # 短于此长度的行不参与检测（避免误伤短句）

# ---------- 文本规范化 ----------
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u2B00-\u2BFF\u2705\u274C\u2757]"
)
DATE_RE = re.compile(r"[（(]\s*\d{1,2}\s*-\s*\d{1,2}\s*(?:~|～)\s*\d{1,2}\s*-\s*\d{1,2}\s*[)）]")
DATE1_RE = re.compile(r"[（(]\s*\d{1,2}\s*-\s*\d{1,2}\s*[)）]")
MD_RE = re.compile(r"[*`>#\-]+")
PUNCT_RE = re.compile(r"[\s，。、；：！？,.;:!?\"'·|/\\\[\]{}（）()~～\-—_=+%]")
# 常见无信息量的填充词，参与比较前剔除，避免拉高相似度
FILLER = ["已上线", "已完成", "进行中", "已处理", "已解决", "已闭环", "已修复",
          "持续", "继续", "进一步", "相关", "本次", "本周", "目前", "当前", "进行"]


def strip_noise(s):
    """去掉 emoji / 日期标注 / Markdown 符号 / 标点空白。"""
    s = EMOJI_RE.sub("", s)
    s = DATE_RE.sub("", s)
    s = DATE1_RE.sub("", s)
    s = MD_RE.sub("", s)
    s = PUNCT_RE.sub("", s)
    return s.strip()


def normalize(s):
    """用于字面比较的规范化：去噪 + 去填充词。"""
    s = strip_noise(s)
    for w in FILLER:
        s = s.replace(w, "")
    return s


def bigrams(s):
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def jaccard(a, b):
    A, B = bigrams(a), bigrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def echo_ratio(title, bullet):
    """标题的 bigram 有多少被 bullet 复述。"""
    A = bigrams(title)
    if not A:
        return 0.0
    return len(A & bigrams(bullet)) / len(A)


def coverage(bullet, title):
    """bullet 的字有多少是照搬标题里的字。"""
    sb, st = set(bullet), set(title)
    if not sb:
        return 0.0
    return len(sb & st) / len(sb)


def sim(a, b):
    """a=标题, b=bullet 的综合相似度。"""
    return 0.5 * jaccard(a, b) + 0.3 * echo_ratio(a, b) + 0.2 * coverage(b, a)


# ---------- 增量信息豁免 ----------
# bullet 只要命中下列任一项，即视为"带来了标题没有的信息"，不算复述，不标记。
INC_CONCLUSION = re.compile(r"(结论为|结论是|根因为?|定位为|定位是|原因是|原因为|归因于?|排查为|排查发现|确认为)")
INC_DAY = re.compile(r"^\d{1,2}-\d{1,2}\s*[：:]")          # 08-19：xxx 分天细节
INC_RISK = re.compile(r"(风险|阻塞|瓶颈|隐患|不可用|超时)")   # 价值/影响描述
INC_NUM = re.compile(r"\d+(?:\.\d+)?\s*(?:个|张|条|次|天|周|小时|分钟|秒|%|％|倍|万|亿|行|家|门店|表|接口|版|次)")

# 下一步动作词：命中即说明这行在写"下周要做什么"，不是照抄本周条目
NEXT_ACTION_RE = re.compile(
    r"(收尾|收口|继续|跟进|推进|上线|发布|落地|验证|回归|观察|跟踪|稳定性|复盘"
    r"|评估|确认|优化|完善|补充|灰度|试运行|联调|压测)")


def has_increment(title_raw, bullet_raw):
    """判断 bullet 是否提供了标题之外的增量信息。"""
    tb = strip_noise(title_raw)
    bb = strip_noise(bullet_raw)
    if INC_CONCLUSION.search(bullet_raw):
        return True
    if INC_DAY.match(bullet_raw.strip()):
        return True
    if INC_RISK.search(bullet_raw):
        return True
    for m in INC_NUM.finditer(bullet_raw):
        token = strip_noise(m.group(0))
        if token and token not in tb:
            return True
    # bullet 明显比标题长很多（承载了展开细节）
    if len(bb) >= 2.0 * max(len(tb), 1):
        return True
    return False


# ---------- 结构解析 ----------
SECTION_RE = re.compile(r"^#{2,3}\s*(?:[一二三四五六七八九十]+、)?\s*(.+)")
BULLET_RE = re.compile(r"^\s*[-*]\s+(.+)")
NUM_RE = re.compile(r"^\s*\d+[.、]\s*(.+)")
ITEM_RE = re.compile(r"^\s*([\u2705\U0001F504\U0001F31F\u26A0]|[✅🔄🌟⚠️])\s*(.+)")
SECTION_NAMES = {
    "summary": ["本周工作总结", "工作总结", "本周工作"],
    "highlight": ["本周亮点", "亮点"],
    "issue": ["遇到的问题", "问题"],
    "plan": ["下周计划", "计划"],
}


def which_section(heading_text):
    for key, names in SECTION_NAMES.items():
        for n in names:
            if n in heading_text:
                return key
    return "other"


def parse(md_text):
    """解析为行列表，每项: {no, raw, norm, kind, section, title_norm}

    kind: heading / item / bullet / plain
    """
    lines = md_text.splitlines()

    # 剥离 YAML frontmatter
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break

    out = []
    section = "other"
    cur_item = None
    cur_item_raw = ""
    cur_status = ""
    for idx in range(start, len(lines)):
        raw = lines[idx]
        norm = normalize(raw)
        stripped = raw.strip()

        mh = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if mh:
            level = len(mh.group(1))
            # 只有二级标题（## 本周工作总结 / ## 本周亮点 …）切换大节；
            # 三级标题（### 一、xxx）只是小节，不改变所属大节，否则会误判为 other
            if level <= 2:
                section = which_section(mh.group(2))
            cur_item = None
            cur_item_raw = ""
            out.append({"no": idx + 1, "raw": raw, "norm": norm, "kind": "heading",
                        "section": section, "title_norm": "", "title_raw": ""})
            continue

        if not stripped:
            out.append({"no": idx + 1, "raw": raw, "norm": "", "kind": "blank",
                        "section": section, "title_norm": "", "title_raw": ""})
            continue

        mi = ITEM_RE.match(stripped)
        mb = BULLET_RE.match(stripped)
        mn = NUM_RE.match(stripped)

        if mi and (section == "summary"):
            sym = mi.group(1)
            status = "wip" if sym in ("🔄", "\U0001F504") else "done"
            cur_item = norm
            cur_item_raw = raw
            cur_status = status
            out.append({"no": idx + 1, "raw": raw, "norm": norm, "kind": "item",
                        "section": section, "title_norm": "", "title_raw": "",
                        "status": status})
        elif mb:
            out.append({"no": idx + 1, "raw": raw, "norm": norm, "kind": "bullet",
                        "section": section, "title_norm": cur_item or "",
                        "title_raw": cur_item_raw, "status": cur_status})
        elif section in ("highlight", "plan", "issue") and (mi or mn or (not stripped.startswith("-"))):
            out.append({"no": idx + 1, "raw": raw, "norm": norm, "kind": "plain",
                        "section": section, "title_norm": "", "title_raw": "",
                        "status": ""})
        else:
            out.append({"no": idx + 1, "raw": raw, "norm": norm, "kind": "plain",
                        "section": section, "title_norm": "", "title_raw": "",
                        "status": ""})
    return out, start


# ---------- 检测 ----------
def detect(entries):
    issues = []       # 需人工处理
    autofix = []      # 可自动删除的行号

    content = [e for e in entries if e["kind"] in ("item", "bullet", "plain") and len(e["norm"]) >= MIN_LEN]

    # L1 字面完全重复
    seen = {}
    for e in content:
        key = e["norm"]
        if key in seen:
            issues.append({
                "level": "L1", "kind": "字面重复行",
                "line": e["no"], "dup_of": seen[key],
                "text": e["raw"].strip(),
                "action": "删除第 {} 行（与第 {} 行完全相同）".format(e["no"], seen[key]),
                "autofix": True,
            })
            autofix.append(e["no"])
        else:
            seen[key] = e["no"]

    autofix_set = set(autofix)

    # L2 跨条目近似重复（同一 section 内的 item 之间、以及 item 与 item）
    items = [e for e in content if e["kind"] == "item"]
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            s = jaccard(a["norm"], b["norm"])
            if s >= TH_L2_SIMILAR:
                issues.append({
                    "level": "L2", "kind": "跨条目近似重复",
                    "line": b["no"], "dup_of": a["no"],
                    "text": b["raw"].strip(),
                    "similar_to": a["raw"].strip(),
                    "score": round(s, 3),
                    "action": "合并第 {} 行与第 {} 行为一条，日期标区间".format(b["no"], a["no"]),
                    "autofix": False,
                })

    # L3 bullet 复述所属标题
    for e in content:
        if e["kind"] != "bullet" or not e["title_norm"]:
            continue
        s = sim(e["title_norm"], e["norm"])
        if s >= TH_L3_AUTOFIX and not has_increment(e["title_raw"], e["raw"]):
            issues.append({
                "level": "L3", "kind": "bullet 复述标题（高置信）",
                "line": e["no"], "dup_of": None,
                "text": e["raw"].strip(),
                "title": e["title_norm"],
                "score": round(s, 3),
                "action": "删除第 {} 行：标题已完整表达，bullet 无增量信息".format(e["no"]),
                "autofix": True,
            })
            autofix.append(e["no"])
            autofix_set.add(e["no"])
        elif s >= TH_L3_SUSPECT and not has_increment(e["title_raw"], e["raw"]):
            issues.append({
                "level": "L3", "kind": "bullet 疑似复述标题",
                "line": e["no"], "dup_of": None,
                "text": e["raw"].strip(),
                "title": e["title_norm"],
                "score": round(s, 3),
                "action": "人工判断第 {} 行：若无增量细节（量化数据/结论/根因/分天/风险）则删除整行".format(e["no"]),
                "autofix": False,
            })

    # L4 亮点 / 计划 照抄正文条目
    # 豁免：下周计划延续「进行中(🔄)」且写明下一步动作的，是正常承接，不算重复；
    #       只有照抄「已完成(✅)」条目、或计划行没有任何下一步动作词时才判定为重复。
    body_items = [e for e in content if e["section"] == "summary"]
    for e in content:
        if e["section"] not in ("highlight", "plan"):
            continue
        best, best_s = None, 0.0
        for b in body_items:
            s = jaccard(b["norm"], e["norm"])
            if s > best_s:
                best, best_s = b, s
        if best is None or best_s < TH_L4_COPY:
            continue
        if e["section"] == "plan" and (
            best.get("status") == "wip" or NEXT_ACTION_RE.search(e["raw"])
        ):
            continue
        issues.append({
            "level": "L4", "kind": "{}照抄正文条目".format(
                "亮点" if e["section"] == "highlight" else "下周计划"),
            "line": e["no"], "dup_of": best["no"],
            "text": e["raw"].strip(),
            "similar_to": best["raw"].strip(),
            "score": round(best_s, 3),
            "action": "改写第 {} 行：亮点写价值与影响，计划写下一步动作，均不得照抄正文".format(e["no"]),
            "autofix": False,
        })

    return issues, sorted(set(autofix))


def apply_fix(md_text, drop_lines):
    lines = md_text.splitlines(keepends=True)
    drop = set(drop_lines)
    kept = [l for i, l in enumerate(lines, start=1) if i not in drop]
    return "".join(kept)


def human_report(path, issues, fixed_lines, changed):
    w = sys.stdout.write
    w("=" * 70 + "\n")
    w("周报重复描述行检测：{}\n".format(path))
    w("=" * 70 + "\n")

    if not issues:
        w("\n✅ 未发现重复描述行，可以落盘。\n")
        return

    by_level = {}
    for it in issues:
        by_level.setdefault(it["level"], []).append(it)

    level_name = {
        "L1": "L1 字面重复行",
        "L2": "L2 跨条目近似重复（需合并）",
        "L3": "L3 bullet 复述标题",
        "L4": "L4 亮点/计划照抄正文",
    }
    for lv in ("L1", "L2", "L3", "L4"):
        if lv not in by_level:
            continue
        w("\n【{}】{} 处\n".format(level_name[lv], len(by_level[lv])))
        w("-" * 70 + "\n")
        for it in by_level[lv]:
            w("  第 {} 行  {}\n".format(it["line"], it["text"]))
            if it.get("similar_to"):
                w("           相似于 第{}行: {}\n".format(it["dup_of"], it["similar_to"]))
            if it.get("score") is not None:
                w("           相似度 {}\n".format(it["score"]))
            w("           → {}\n".format(it["action"]))
            w("\n")

    auto = [i for i in issues if i["autofix"]]
    manual = [i for i in issues if not i["autofix"]]
    w("-" * 70 + "\n")
    w("汇总：共 {} 处 —— 可自动清理 {} 处，需人工处理 {} 处\n".format(
        len(issues), len(auto), len(manual)))
    if changed:
        w("已自动清理 {} 行（原文件备份为 {}.bak），请重跑本脚本确认。\n".format(
            len(fixed_lines), path))
    elif manual:
        w("⚠️ 存在需人工处理的重复项，请按上方 action 修改后重跑，直到输出「未发现重复描述行」。\n")
    w("")


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("report", help="周报 .md 文件路径")
    ap.add_argument("--fix", action="store_true", help="自动清理高置信重复项并写回")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    path = args.report
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        sys.stderr.write("读取失败: {}\n".format(e))
        sys.exit(2)

    entries, _ = parse(text)
    issues, autofix = detect(entries)

    changed = False
    if args.fix and autofix:
        shutil.copyfile(path, path + ".bak")
        new_text = apply_fix(text, autofix)
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        changed = True

    if args.json:
        print(json.dumps({
            "file": path,
            "checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "total": len(issues),
            "auto_fixed": len(autofix) if changed else 0,
            "needs_manual": len([i for i in issues if not i["autofix"]]),
            "changed": changed,
            "issues": issues,
        }, ensure_ascii=False, indent=2))
    else:
        human_report(path, issues, autofix, changed)

    sys.exit(1 if (issues or changed) else 0)


if __name__ == "__main__":
    main()
