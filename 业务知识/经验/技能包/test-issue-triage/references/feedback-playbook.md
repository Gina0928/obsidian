# 反馈驱动自我改进手册

本技能不是静态文档：每次排查结束后把踩到的坑写进反馈池，达到阈值再合并进技能本体，
让下一次执行少走一遍弯路。**改技能是滞后动作，不是即时动作** —— 单次偶发事件不许改技能。

---

## 一、回路总览

```
捕获（任务中/任务末）  →  沉淀（写入共享池，同类自动命中+1）
        ↓                              ↓
   回验（改完自测）    ←  合并（达阈值后改 SKILL.md / references / scripts）
```

- 共享池：`C:\Users\yuai\.workbuddy\skills\.wms-triage-feedback\pool.jsonl`
- CLI：`scripts/feedback.py`（两技能各存一份，内容一致，改一处同步另一处）
- Python：`C:/Users/yuai/.workbuddy/binaries/python/envs/default/Scripts/python.exe`

---

## 二、什么时候必须记一条（捕获触发器）

**用户显式纠正**（`--source user`，直接判为 NOW）：

- 用户说"这个上次说过 / 记住 / 以后别这样 / 不是这样查的"
- 用户修正了口径、门店、时间区间、字段含义
- 用户指出结论错了（尤其是把测试结论当生产结论、或外推了性能结论）

**任务后自动复盘**（`--source auto`，靠命中次数累积）：

| 现象 | 建议 kind |
|---|---|
| SQL 报错：表不存在 / 字段不存在 / 分表不存在 | `correction` 或 `env` |
| `D:\cl-wms\docs` 里文档路径失效、内容为空、status=已废弃但索引仍指向它 | `env` |
| MCP 连不上，兜底到 db-cli 才查到 | `env` |
| 某个字段含义每次都要重新 `information_schema` 确认 | `gap` |
| 同一段查询片段第 3 次手写 | `efficiency` |
| 某个高频场景没有现成入口表清单 | `gap` |
| 差点写生产库 / 差点无门店就查 / 差点把测试结论外推 | `redline` |
| 环境连接映射、分表规则、文档索引发生变化 | `env` |
| 走了 3 步以上弯路才找到正确入口 | `efficiency` |

判断标准只有一句：**下次遇到同类任务，这条信息能不能让我少做一步？** 能就记，不能就别记。

---

## 三、字段填写标准

`--topic` 是同类去重的唯一依据，**必须写稳、写通用，不带具体单据号/门店号/日期**：

| 好 | 坏 |
|---|---|
| `stk_trans_log 分表不存在时的处理` | `1607 的分表查不到` |
| `md_warehouse 门店名解析多命中时的处理` | `沙市七中查出来两条` |
| `MCP 连接不可用时的 db-cli 兜底命令` | `今天 mysql_wms_yas_prod 连不上` |

其余字段：

- `--detail` 具体现象，一句话说清。
- `--evidence` 证据：报错原文 / SQL / 文档文件名。没有证据的条目合并前要补证。
- `--fix` 建议怎么改（写清"加在哪一段"）。
- `--target` 建议落点，见下方决策树。
- `--skill` `prod` / `test` / `both`。**两个技能都适用的填 `both`**，合并时两侧都要改。

---

## 四、合并落点决策树

```
影响「什么时候触发这个技能」        → frontmatter description
影响「每次都要遵守的动作/顺序/红线」 → SKILL.md 正文（前提是总长度 < 5k words）
事实性清单（表、字段、连接、片段）  → references/environment.md
文档索引与读取路由                  → references/docs-index.md
某类问题的完整排查定式              → 新建 references/<topic>.md，或抽成独立技能
重复手写的确定性操作                → scripts/（拼 URL、算分表名、生成报表）
一次性数据 / 临时偏好               → 不收，直接 reject
```

**两条容易踩的坑：**

1. **SKILL.md 正文超过 5k 词（中文约 8000 字）就必须下沉**，不要再往上堆。
   自查方式：`wc -m SKILL.md`。SKILL.md 只在技能触发时加载一次，references 才是按需加载。
   当前两技能 SKILL.md 均已在 8000～10000 字符区间，**新增内容默认放 `references/`**。
2. **新建的 references 文件必须在 SKILL.md 里有指向它的路径引用**，否则渐进式披露下它
   永远不会被读到，等于没写。合并后逐条确认这条链路存在。

---

## 五、合并阈值（`review` 输出的 READY 列）

| READY | 判定 | 动作 |
|---|---|---|
| `NOW` | 红线类 / 用户显式纠正 / 命中 ≥ 2 次 | 立即合并 |
| `REVIEW` | 命中 1 次且已沉淀 ≥ 14 天 | 复核一次，判断偶发还是规律，是规律就合并 |
| `WAIT` | 其余 | 继续观察，**不许改技能** |

用 `--source user` 记的用户纠正会直接跳到 NOW，因为用户已经做过判断。

---

## 六、合并操作规范

1. `python feedback.py review --skill prod`（或 `test`）扫出 NOW 条目。
2. 按决策树改对应文件。**改动要小**：一条反馈对应一到两处改动，不顺手重构整篇。
3. 若条目 `skill=both`，**两侧技能都要改**：
   - `C:\Users\yuai\.workbuddy\skills\prod-issue-triage\`
   - `C:\Users\yuai\.workbuddy\skills\test-issue-triage\`
4. 回验：
   - 改了 `description` → 用一句典型触发话术自测"这句话会不会命中技能"。
   - 改了 `references` → 确认 SKILL.md 里有指向它的引用路径。
   - 改了 `scripts` → 实跑一遍，确认退出码 0。
5. `python feedback.py resolve <ID> --to <实际落点文件>` 关闭条目。
6. 不采纳的走 `python feedback.py reject <ID> --reason "…"`，留痕，别直接删。

---

## 七、反模式（禁止）

- **把具体数据写进技能**：门店号、单据号、日期、某次的数量。要提炼成规则。
- **因单次偶发事件改技能**：环境抖一次就改连接映射，第二天就错了。
- **改红线来迁就一次方便**：只读、门店必填、先读文档再查库 —— 这三条任何反馈都不能推翻，
  遇到冲突说明是执行问题，不是规则问题。
- **把临时偏好当通用规则**："这次要 CSV" 是本次诉求，不是技能规则。
- **无证据合并**：`--evidence` 为空的条目，先补证再合并。
- **合并后不回验**：改完不看一眼 SKILL.md 是否还自洽，容易留下互相矛盾的条款。
- **只记录不清理**：NOW 条目长期不清零，反馈池就变成噪音源。

---

## 八、两技能互推

`prod-issue-triage` 与 `test-issue-triage` 共用同一个池子，所以：

- `review` 时**不按技能过滤地扫一遍** `both` 条目，避免生产学到的经验测试还在踩。
- 环境类（`env`）、文档索引类反馈绝大多数是 `both`。
- 只有真正确认与环境强相关的才标 `prod` 或 `test`（例如只对生产成立的门店分表规模结论）。

---

## 九、命令速查

```bash
PY="C:/Users/yuai/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
SK="C:/Users/yuai/.workbuddy/skills/prod-issue-triage/scripts/feedback.py"

# 记一条（用户纠正）
$PY $SK add --skill both --kind env --topic "MCP 连接不可用时的 db-cli 兜底命令" \
  --detail "启动阶段 MCP 显示 Still connecting，卡住等连接会浪费一轮" \
  --fix "SKILL.md Step 0 直接给出 dbquery.py 兜底命令" \
  --target "SKILL.md" --evidence "2026-09-10 连接超时" --source user

# 再次踩到同一个坑（topic 写一致即可自动命中，也可手动指定 ID）
$PY $SK hit F001 --evidence "2026-09-12 再次复现"

# 看待办 / 统计 / 关闭
$PY $SK review
$PY $SK review --all --skill both
$PY $SK stats
$PY $SK resolve F001 --to "SKILL.md"
$PY $SK reject F002 --reason "一次性环境抖动"
```

---

## 十、节拍建议

- **每次任务结束**：花 10 秒扫一遍"这次有没有踩坑"，有就 `add`，没有就不写（别凑数）。
- **NOW 条目**：出现即清，保持清零。
- **每月一次**：`stats` 回看，重点看 `rejected` 里有没有判错的。
