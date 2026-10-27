# WMS 排查技能 —— 共享反馈池

`prod-issue-triage` 与 `test-issue-triage` 两个技能共用的反馈池。放在 `skills/` 根目录下、
以 `.` 开头且无 `SKILL.md`，因此不会被当作技能加载。

## 文件

| 文件 | 用途 |
|---|---|
| `pool.jsonl` | 每行一条 JSON，含 `open` / `merged` / `rejected` 全量，审计留痕，不删条目 |

## 操作入口

不要用编辑器手改 `pool.jsonl`，一律走 CLI（两技能各有一份，内容相同）：

```
C:\Users\yuai\.workbuddy\skills\prod-issue-triage\scripts\feedback.py
C:\Users\yuai\.workbuddy\skills\test-issue-triage\scripts\feedback.py
```

```bash
PY="C:/Users/yuai/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
SK="C:/Users/yuai/.workbuddy/skills/prod-issue-triage/scripts/feedback.py"

$PY $SK add --skill both --kind env --topic "<通用规则>" --detail "..." --evidence "..."
$PY $SK review            # 看 READY 列：NOW 合并 / REVIEW 复核 / WAIT 观察
$PY $SK hit F001          # 再次踩到同一个坑
$PY $SK resolve F001 --to "references/environment.md"
$PY $SK reject F002 --reason "..."
$PY $SK stats
```

## 条目字段

| 字段 | 说明 |
|---|---|
| `id` | `F001` 形式，自动生成 |
| `ts` | 首次记录 / 最近一次命中的时间 |
| `skill` | `prod` / `test` / `both`（`both` 合并时两侧技能都要改） |
| `kind` | `correction` 纠错 / `gap` 补齐 / `efficiency` 效率 / `redline` 红线 / `env` 环境 |
| `source` | `user` 用户显式纠正（直接判 NOW）/ `auto` 任务后自动复盘 |
| `topic` | 通用规则标题，**同类自动去重的依据**，不得带门店号/单据号/日期 |
| `detail` / `evidence` / `fix` / `target` | 现象 / 证据 / 建议改法 / 建议落点 |
| `hits` | 命中次数，≥2 即判 NOW |
| `status` | `open` / `merged` / `rejected` |

## 合并阈值

| READY | 判定 |
|---|---|
| `NOW` | 红线类，或用户显式纠正，或命中 ≥ 2 次 |
| `REVIEW` | 命中 1 次且沉淀 ≥ 14 天 |
| `WAIT` | 其余，继续观察，不许改技能 |

完整落地规范见任一技能下的 `references/feedback-playbook.md`。

## 换机器 / 换路径

改环境变量 `WMS_FEEDBACK_POOL` 指向新目录即可，CLI 会自动创建目录与文件。
