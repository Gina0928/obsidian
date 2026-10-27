# 日志查询与交叉分析（monitor 日志导出 + WMS 场景路由）

> 本文档用于**测试环境（jy_wms 测试库，mysql_wms_test）**复现/验证时的日志查询。
> **测试环境日志只反映测试行为，结论不得外推生产。**
>
> 本文件是 test-issue-triage 的日志子模块，定位为 **monitor-log 技能的 WMS 场景化轻量版**：
> 覆盖「日志与数据库交叉印证 + 按症状路由到正确的日志类型 + 发起查询前的约束校验」。
> **超出本文件覆盖的复杂场景（Kafka 消息追溯、前端报错、操作日志聚合、写操作补发等），
> 直接加载 monitor-log 技能**取其完整模板与接口清单，不要重复造轮子。

## 一、先定性，再查（问题定性决策树）

> 铁律：接到日志查询请求，**先对症状定性、锁定首查通道，再动手拉日志**。不要一上来就只拉 loggerLog。

| 用户描述的症状 | 首查日志类型 | 关键过滤字段 | 补充佐证（横看） |
|---|---|---|---|
| 提供 traceId / 一次请求异常 | loggerLog + webLog + dubboLog（按 traceId 串联） | `traceId` | `elapsedTime` 校验耗时构成 |
| 接口报错 / 超时 / 依赖失败 | dubboLog（`status=fail/timeout`）+ loggerLog | `status` + `elapsedTime` | loggerLog 找异常抛出处 |
| 页面卡顿 / 接口慢 / 操作响应慢 | sqlLog（慢 SQL）+ sysStatus（资源） | `queryTime` Top | 系统状态看并发资源 |
| 定时任务没跑 / 跑失败（XXL-Job） | xxlJobLog | `logId` / 执行状态 | 调度器配置 |
| 系统级 OOM / 线程池打满 / 连接池耗尽 | sysStatus | `oldGenUsed` / `dubboUsed` / `druidActiveCount` | loggerLog 的 GC/堆转储记录 |
| 具体某条 SQL 慢（生产慢 SQL 库） | dbSlowSql | `dbId` | 执行计划 / 索引 |
| 缺货 / 分配异常 / 单据状态异常（WMS 业务） | loggerLog 按单据号·商品编码 + 数据库 | `message`（单据号/商品编码） | 回 `doc_alc_header` / `stk_trans_log_{wh_id}` 取明细 |

> 判断优先级（沿用 monitor-log）：① 有 traceId 永远先走精确串联，最快收敛；② **先排资源瓶颈再查代码**（线程池/连接池满常是报错根因）；③ 慢 ≠ 代码问题，慢 SQL 优先于业务代码；④ 单实例 vs 全量：仅某 pod 异常优先看该 IP 趋势，不要急着改代码。
> **测试特例**：测试库零数量行占比高、数据量小，sysStatus/慢 SQL 结论**不可外推生产**，须标注「生产需复核」。

## 二、约束校验（发起任何查询前必过）

> 仿 monitor-log 的 R1–R5 强约束。校验失败**不发起 HTTP 调用**，只输出拒绝话术。

| 编号 | 约束 | 规则（WMS 适配） |
|---|---|---|
| V1 | 时间区间梯度 | 仅支持**单日**（`executeDate`）。跨度 > 24h → 拒绝并要求按单日拆分；1h < 跨度 ≤ 24h 必须指定 `providerApps`/`providerIp` 等应用过滤；≤ 1h 可不指定 |
| V2 | 关键字最小长度 | `message`/`param`/`requestBody` 等模糊匹配值长度 < 3 → 拒绝（话术：`关键字 '{kw}' 长度不足 3 字符，会匹配过多记录，请补充更具体的关键字`） |
| V3 | 结果上限提示 | 结果集达上限时追加提示「建议缩小时间范围或增加过滤条件」 |
| V4 | 只读 | 仅 GET / 导出；`reSendMq` 等写操作必须二次确认（复杂写场景交 monitor-log） |

**执行顺序**：
1. 输出一行 `校验结果：通过` 或 `校验结果：拒绝(Vx)`，附原因。
2. 拒绝则止，不发起调用。
3. 通过则构造 URL 并拉取。

## 三、多日志类型路由（接口要点，完整规范见 monitor-log）

以下为本技能最常用、且与 WMS 排查强相关的接口（monitor 平台均为 HTTP GET，返回 JSON
形如 `{rows:[...], total:N}`）。每个接口需带 `executeDate`；鉴权 `Cookie: {monitorAuth}`，
内网免登可省略；非 prod 环境后端自动追加 env 过滤，调用方**不要手动传 env**。

| 日志类型 | 接口路径 | WMS 排查要点 / 关键返回字段 |
|---|---|---|
| Logger 应用日志 | `/sysLog/loggerLog/list` | 按 `traceId`/`level`/`className`/`message` 过滤；本技能的**默认关键字/堆栈通道** |
| Web 请求日志 | `/sysLog/webLog/list` | 按 `uri`/`user`/`traceId`/`elapsedTime` 查请求链路与耗时 |
| Dubbo 调用日志 | `/sysLog/dubboLog/list` | `status=fail/timeout` + `elapsedTime` 定位失败/超时；`providerThreadPool` 看线程池 |
| SQL 执行日志 | `/sysLog/sqlLog/list` | 关键字段 `sqlText`/`queryTime`/`parseRowCounts`(扫描行数)/`returnRowCounts`(返回行数)/`dbName`；`returnRowCounts` 等于 pageSize 上限=查询被截断；排序建议客户端按 `queryTime`，勿传 `sort=elapsedTime`（实测 500） |
| 系统状态 | `/sysLog/sysStatus/list` | JVM 堆/Eden/OldGen、CPU、线程数、`druidActiveCount`/`druidMaxCount`(连接池)、`dubboUsed`/`dubboMax`(线程池)；阈值参考 堆≥90%/Dubbo≥60%/Druid≥90%；时间格式**分钟级** `yyyy-MM-dd HH:mm`，无分页，无 env 过滤 |
| XXL-Job 调度 | `/job/log/index` | 参数 `logId`+`serverIp`+`time`(含 `T`)；返回 HTML 日志 |
| DB 慢 SQL | `/db/dbSlowSql/list` | 参数 `dbId`（必填）；查生产慢 SQL 配置库 |

> `/list` 类接口用 `curl` 拉取 JSON（示例见 monitor-log `examples.md`）；其余接口（Kafka、
> WebError、操作日志聚合、应用元数据）详见 monitor-log `endpoints.md`，本技能不重复列。

### 3.1 cl-wms 在 monitor 测试环境的已确认应用名（实测 2026-09-10）

`build_log_url.py` 默认填的 `yas-gateway-invoker` 只是网关，**看不到业务异常**。查 cl-wms 用下面这些：

| providerApps | 角色 | 典型日志 |
|---|---|---|
| `cl-wms-web-pre` | Web 服务 | `MessageSendService` 的 `mq send, topic:wms_data_sync_topic` |
| `cl-wms-adapter-api-pre` | **Kafka 消费端**（异步消息真正执行处） | `DataSyncBizService` 的 `消息处理失败：` + 完整堆栈 |
| `cl-wms-job-pre` | XXL-Job | `XxlJobAspect` 任务启停、`ExpAsnAdapter`（批次下传） |
| `salestock-rpc-test` / `jy-roc-web-yas` | 库存/ROC 侧 | 库存变动、交易参数 |

两个实测坑：

1. **loggerLog 只索引 WARN/ERROR**，`log.info` 打不出来。所以「某 handler 没打日志」≠「没执行」，
   要回到数据库看落库结果（如 `async_msg_record` 是否已被逻辑删除）再下结论。
2. `loggerLog/export` 返回的其实是 **xlsx（zip）**，不是 CSV。用 `zipfile` 读
   `xl/sharedStrings.xml` + `xl/worksheets/sheet1.xml` 解析；`iconv` 无效。
   想省事直接用 `loggerLog/list` 拿 JSON（`list` 字段），`message` 里带 `<span style=...>` 高亮标签，需剥离。
3. 响应里 `executeTime` 常为 `null`，要定位精确时间就二分收敛 `executeTimeRange`。

## 四、Logger 日志导出流程（保留可用路径，默认关键字/traceId 场景）

本流程用 `loggerLog/export` CSV 导出（与上方 `/list` JSON 同源，但导出为 CSV 便于本地
Read 分析）。接口地址：

| 环境 | 基础地址 |
|---|---|
| 测试 | `https://monitor-test.selline.cn/sysLog/loggerLog/export` |
| 生产 | `https://monitor-yas.myt11.com/sysLog/loggerLog/export` |

两者路径与参数完全一致，仅域名不同。

- **构造 URL**：运行 `scripts/build_log_url.py`（已内置 V1/V2 校验），避免手工拼接出错
  （尤其 `executeTimeRange` 的 `%3A` 与 `message` 的 `+` 分隔符）：

  ```bash
  python <skill_dir>/scripts/build_log_url.py \
    --env test --date 2026-09-07 --time-range "14:43:54 - 23:59:59" \
    --message 1788767039401 1788767039306
  ```

- **拉取日志**：优先 `curl` 下载到 `D:\cl-wms\logs\`（目录不存在先 `mkdir`）：

  ```bash
  curl -L -o "D:\cl-wms\logs\export-test-2026-09-07.csv" "<上一步生成的URL>"
  ```

  下载后用 Read 工具打开分析。

- **失败兜底**：该接口为内部监控平台，可能需要登录态（Cookie/Token）或处于内网。若
  `curl` 返回 401/403 或网络不可达：**不要反复重试**；直接把构造好的 URL 交给用户，请其在
  已登录的浏览器中打开下载；或让用户把导出的日志文件放到 `D:\cl-wms\logs\` 下，再由本技能读取分析。

## 五、与数据库交叉分析（核心）

日志与数据库是互补的两条证据链，复现/验证时合并呈现，不单看一侧。

- **日志 → 数据库**：用 `traceId`/异常堆栈/出现的单据号·商品编码，回测试库取数，确认数据侧是否也异常（例如日志报空指针，DB 里对应记录是否缺字段）。
- **数据库 → 日志**：测试库定位到异常单据/时间点后，用 `message`（单据号/商品编码/traceId）或时间区间去日志看完整调用链，确认现象发生的确切服务与报错，验证"复现成功"。
- **时间对齐**：日志时间=服务器时间，通常与 DB 一致；用时间区间把"DB 一条异常记录"和"日志一段调用"对齐。
- **横切验证矩阵**（下钻后反向佐证）：

  | 怀疑点 | 印证日志 | 印证指标 |
  |---|---|---|
  | 线程池打满 | sysStatus + dubboLog | `dubboUsed/dubboMax ≥80%` |
  | 连接池耗尽 | sysStatus + sqlLog | `druidActiveCount/druidMaxCount ≥90%` 且慢 SQL Top 高 |
  | SQL 未命中索引 | sqlLog | `parseRowCounts` 巨大（全表扫描） |
  | GC 停顿 / OOM | loggerLog + sysStatus | `cpuUsage` 突刺 + `oldGenUsed` 打满 |

- **输出合并证据**：同一份分析同时引用两侧，例如「DB 中单据 DBxxxx 缺货明细为空（SQL 见上）；
  traceId=yyy 日志在 14:43:55 显示 AaaService 提前 return，未生成缺货记录」。
  **测试环境日志只反映测试行为，结论不得外推到生产**；引用日志必标注环境与时间。

## 六、红线

- 日志接口仅用于读取 / 导出，不发起任何写操作；复杂写场景交 monitor-log 并二次确认。
- 跨环境标注：不要把测试环境日志当成生产日志，反之亦然；引用必标来源环境。
- 拉取的内部日志可能含敏感信息，导出文件只落在 `D:\cl-wms\logs\`，不私自外传。
- 未过 V1/V2 校验不发起调用；校验拒绝时如实告知用户并给出收敛建议。
- 测试环境的性能/资源类结论（慢 SQL、线程池、连接池）**一律标注「生产需复核」**，不得外推。
