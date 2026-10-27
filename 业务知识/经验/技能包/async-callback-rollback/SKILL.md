---
name: async-callback-rollback
agent_created: true
model: Hy4 preview
description: |
  排查「业务状态应该变更但没变 / 变了又被打回」的问题——典型根因是异步消息消费链路中
  本地状态更新与外部系统回写在同一个事务里，外部调用抛异常导致整体回滚。
  触发词：状态没变、状态没更新、状态回滚、状态回退、状态打回、单据状态不对、
  异步回写、回写失败、callback、updateSrcAsn、要货单状态、一PO多DO、
  Kafka 消费失败、消息没消费、async_msg_record、消息处理失败、事务回滚。
  支撑能力：DB 状态三件套判读、异步消息表消费结果判读（version/del_flag 组合含义）、
  monitor 异常堆栈定位到行号、@Transactional 边界审计、补偿 job 是否运行的确认。
  硬约束：先定性（没执行 / 写了回滚 / 被覆盖）再动手，禁止一上来就改代码；
  结论必须带可复核的证据（DB 行值 + 日志时间点 + 源码行号），并标注环境与数据口径；
  性能类或环境类结论不得直接外推到生产，须标注「生产需复核」。
---

# 异步回写失败导致业务状态回滚 —— 排查定式

## 适用场景

单据/记录的状态「按业务逻辑应该已经变更，实际却停留在旧状态」时优先用本技能。
在 cl-wms 里最常见的形态是：ASN（入库单/要货单/物流单）在收货、关单后状态未推进。

## 第一步：先定性，不要一上来就读代码

状态没变只有三种可能，定性错了后面全白做：

| 类型 | 特征 | 判别方法 |
|---|---|---|
| **A. 没执行到**（条件不满足 / 未触发） | 无任何写入痕迹，更新时间未变 | 查日志：状态更新方法的入口日志是否存在 |
| **B. 写了但回滚**（外部调用异常） | 更新时间未变或回到旧值，但**存在异常堆栈**；异步消息表显示未消费 | 查异常堆栈 + 异步消息表 + `@Transactional` 边界 |
| **C. 写了又被覆盖** | 更新时间在预期之后又被改回，能找到后续写操作 | 按 `update_date` 排序找最后一次写入方 |

**判据（B 型的铁证组合）**：
1. 异步消息表该单据记录 `version` 未递增 / `del_flag = 0`（未消费成功）；
2. 日志中存在该单据的异常堆栈，且堆栈里同时出现「状态更新方法」和「外部调用方法」；
3. 源码中这两者在同一个 `@Transactional` 内，且外部调用**没有 try/catch**。

三条同时满足即可定性为 B，不用再怀疑业务匹配逻辑。

## 第二步：DB 取「状态三件套」

按主表 → 明细 → 写入痕迹的顺序取，一次取全，避免反复查。

```sql
-- 1) 主表：当前状态 / 数量 / 时间（先看 asn_status、received_qty、update_date）
SELECT id, asn_no, asn_type, asn_sub_type, asn_status,
       expt_qty, received_qty, po_no, asn_ref_no1, wh_id,
       create_date, update_date, del_flag
FROM asn_header WHERE id IN (<主表id>) OR asn_no IN ('<单号>');

-- 2) 明细：确认行级状态是否与头一致（头未动但明细动了一半 = 强回滚信号）
SELECT id, asn_header_id, line_status, sku_id, expt_qty, received_qty,
       po_no, do_no, org_do_item_id, create_date, update_date
FROM asn_detail WHERE asn_header_id IN (<主表id>) ORDER BY asn_header_id, id;

-- 3) 异步消息表：判断消息是否被消费成功
SELECT id, msg_type, business_id, business_no, version, del_flag,
       create_date, update_date
FROM async_msg_record
WHERE business_no IN ('<单号>') OR business_id IN (<主表id>);

-- 4) 同类单据横向对比（最能说明"是个例还是通病"）
SELECT s.id, s.asn_no, s.asn_status, s.received_qty, s.po_no,
       p.id AS po_id, p.asn_no AS po_asn, p.asn_status AS po_status,
       p.received_qty AS po_recv, p.expt_qty AS po_expt
FROM asn_header s
JOIN asn_header p ON p.asn_ref_no1 = s.po_no
     AND p.asn_type = 1 AND p.asn_sub_type = 103
     AND p.wh_id = s.wh_id AND p.del_flag = 0
WHERE s.asn_type = 5 AND s.del_flag = 0 AND s.create_date >= '<近几天>'
ORDER BY s.id DESC LIMIT 40;
```

### `async_msg_record` 消费结果判读（关键）

| version | del_flag | 含义 |
|---|---|---|
| 1 | 0 | **未消费 / 消费失败**，是排查重点 |
| ≥2 | 1 | 消费成功（version 递增后逻辑删除） |

同批其它单据都是 `version≥2 / del_flag=1`，只有目标单是 `1/0` → 几乎可以锁定是消费环节抛异常。

## 第三步：日志找异常堆栈

monitor **只索引 WARN/ERROR**（INFO 级日志查不到，别浪费时间）。
cl-wms 在测试环境的真实应用名（生产对应去掉 `-pre` 或按 monitor-log 技能查）：

| 应用名 | 职责 |
|---|---|
| `cl-wms-adapter-api-pre` | **Kafka 消费端**，异步消息处理失败堆栈在这里 |
| `cl-wms-job-pre` | XXL-Job 定时任务（含 `asyncMsgHandlerJob` 补偿） |
| `cl-wms-web-pre` | Web 接口层 |

```bash
# 按单号找（只出 ERROR/WARN）
curl -s -m 90 -G "https://monitor-test.selline.cn/sysLog/loggerLog/list" \
  --data-urlencode "providerApps=cl-wms-adapter-api-pre" \
  --data-urlencode "executeDate=2026-09-10" \
  --data-urlencode "executeTimeRange=14:20:00 - 14:30:00" \
  --data-urlencode "message=<单号或关键字如 消息处理失败>" \
  --data-urlencode "page=1" --data-urlencode "limit=50" -o out.json
```

解析要点：返回的 `message` 带 HTML，需 `re.sub(r'<[^>]+>','')` + `html.unescape()` 后读全文。
**看堆栈最后几行**：`业务方法(文件:行号)` 的调用链直接给出事务内哪一步炸的。

## 第四步：回读源码，审计事务边界

拿到堆栈里的行号后，读该方法，**自上而下检查**：

1. 方法上是否有 `@Transactional`（或类上、或 AOP 切面）；
2. 方法内依次做了哪些写操作（本地 DB 更新）；
3. 方法内是否有 **dubbo / HTTP / MQ 等外部调用**；
4. 外部调用**是否被 try/catch 包住**；异常是吞掉还是继续冒泡；
5. 触发条件：外部调用是在什么状态下才触发（决定了「为什么这类场景才暴露」）。

定式结论模板：

```
<状态更新方法>(X.java:102)  // 本地写：已正确算出并把状态改为 Y
  ↓ 同一事务
<外部回写方法>(X.java:104)  // dubbo → <外部系统>/<接口>
  ↓ RpcException: No provider available（无 try/catch）
整个事务 ROLLBACK → 状态被打回原值
```

## 第五步：确认补偿链路是否可用

> ### ⚠️ 先记住这条硬判据：async_msg_record **跨天必死**
> 补偿 Job `AsyncMsgHandlerJob` 捞待处理用的语句是（已核实源码）：
> ```java
> // cl-wms-service/src/main/java/com/jy/cl/wms/service/md/impl/AsyncMsgRecordService.java:31
> pp._where("del_flag = 0 and to_days(create_date) = to_days(now())");   // 只扫当天！
> ```
> **推论：任何当天没处理成功的异步消息，跨过 24:00 后再没有任何自动机制重试它。**
> 唯一救济是人工把 msg id 当参数传给 `asyncMsgHandlerJob`（`AsyncMsgHandlerJob.java:41-48` 支持单条重跑）。
>
> 所以排查「单据卡死」时不要只问"消息为什么失败"，还要问**"它是什么时候失败的"**：
> - `create_date < CURDATE() 且 del_flag=0` → **已是孤儿**，Job 救不了，只能人工喂 id 或手动重推；
> - `create_date >= CURDATE() 且 del_flag=0` → 还在窗口期内，Job 会持续重试，先看日志为什么一直失败。
>
> 直接证据 SQL：
> ```sql
> SELECT msg_type, COUNT(*) cnt, MIN(create_date) earliest, MAX(create_date) latest
> FROM async_msg_record WHERE del_flag = 0 AND create_date < CURDATE()
> GROUP BY msg_type ORDER BY cnt DESC;
> ```
>
> **生产实测基线（2026-09-11，yas/jy_wms）**：`msg_type=4`（入库单回写）孤儿 **20,862 条，最早 2025-10-17**；
> `msg_type=3`（负库存）76 条；当天窗口内仅 82 条 → **每天新增约 80 条失败，跨天转孤儿，已持续 11 个月**。
> 门店分布全局分散（1801/1502/1708/1702/9901…）= 系统性失败，不是个例。
> 拿到类似数字时**不要当成突发故障**，这是长期存量；要判断的是**当天新增量是否在恶化**。
>
> ⚠️ 定性别踩坑：这批孤儿单 `asn_status=20 收货完成` 是 **NORMAL 类型 ASN 的正常终态**
> （近 30 天 NORMAL 单分布：20 有 253,024 条、90 有 0 条）→ 本地看着正常，
> **损失在下游 PMS/SCM 收不到回写**。判断"是否真损失"不能只看本地单据状态。;
> ```

静默 `return` 也算卡点：很多 Handler 在「msgType 不匹配 / 单据为空 / 状态不满足」时直接 `return;`，
**既不处理也不删记录** → 消息永久滞留 + 推高表膨胀。已知位置：
`AsyncAsnCallBackHandler:57,60,72`、`AsyncStkMinusMsgHandler:29,32`、
`SyncWaveStatusAfterPickedHandler:64`、`SyncWaveStatusAfterConfluenceHandler:58`。
全局自查：
```bash
cd D:/cl-wms && for f in $(find . -path ./ys-maven -prune -o -name "*Handler.java" -print); do \
    awk -v F="$f" '/return;/{print F":"NR": "$0}' "$f"; done
```

- 查补偿 job 当天是否执行过：`asyncMsgHandlerJob`（XXL-Job，支持传 msg id 单条重跑）。
- 若 job 未运行或积压严重（可查 `async_msg_record WHERE del_flag=0` 的最早 `create_date`），
  则失败消息不会自动自愈，需要在外部系统恢复后手动重跑。
- **重跑前务必确认幂等性**：若状态更新是「当前值 + 本次量」的累加式，
  已成功提交后再重复触发会重复累加。

## 修复建议（按优先级，可直接复用）

1. **拆事务边界**：把 `callbackSCM` / `callbackPMS` 这类外部回写移出本地状态更新的事务。
   做法：catch 掉 `RpcException` 后记录日志 + 告警；或改成事务提交后（`afterCommit`）执行 + 独立重试。
   理由：外部系统抖动不应该回滚本地已经算对的业务状态——**这条在生产同样成立**。
2. **启用/完善补偿**：让 `asyncMsgHandlerJob` 定时扫描未消费消息并重试，避免依赖单次消费成功。
3. **加幂等校验**：外部回写与本地状态更新都要能容忍重复触发。
4. **区分环境问题**：`No provider available` 属环境依赖缺失（测试环境常见），
   不是业务代码逻辑错误；要单独向用户说明，避免被误判为 bug。

## 输出要求

- 结论先行，再给证据；证据用表格，包含「项 / 值 / 来源（哪张表或哪份日志）」。
- 必须给出**数据口径**：哪个环境、哪个库、时间范围。
- 涉及生产影响的判断，标注「生产需复核」并给出复核 SQL。
- 提供可复制的复核 SQL。

## 工具与兜底

- 查库优先 `mcp__mysql_wms_test__query`（测试）/ 生产对应 MCP。
  MCP 连不上时用 db-cli 兜底（**已验证可用**）：
  ```bash
  cd "C:\Users\yuai\.workbuddy\skills\db-cli\scripts"
  P=C:/Users/yuai/.workbuddy/binaries/python/envs/default/Scripts/python.exe
  $P dbquery.py test/jy_wms "<SQL>" --format tsv --no-limit-check
  ```
  注意：聚合查询/自带 LIMIT 要加 `--no-limit-check`；`DESC` 会被追加 LIMIT 报错，
  改用 `information_schema.columns` 查列名。
- 复杂日志场景（Kafka 积压、前端报错、操作日志聚合、写操作补发）转 `monitor-log` 技能。
- 本技能的完整实战案例见 `references/case-asn-2026-09-10.md`。
