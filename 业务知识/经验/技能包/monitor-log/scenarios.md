# 场景化查询模板

针对高频排查场景的查询模板。每个模板包含：场景描述、校验要点、调用步骤、结果整理方式。

---

## 模板 1：调用链跨日志串联（traceId / 无 traceId）

### 场景

串联完整调用链：Web 入口 → Dubbo 调用 → SQL 执行 → Logger 日志 → 前端错误。

> **重要**：monitor 的 traceId 接入**尚不完善**，部分链路未打点或未串起来。**无 traceId 或 traceId 查不到时，必须走"近似串联"路径（见 1B），不能因缺 traceId 放弃排查。**

### 关联原理（理解基础）

每类日志都含公共字段 `createDate` / `providerApp` / `providerIp` / `logId` / `env`，是关联的根基：

- **IP 是跨日志天然主键**：同一 `providerIp` 在 web / sql / logger 里都存在，可把同一实例的日志拉齐
- **Dubbo 标出服务边界**：`consumerApp`/`consumerIp`（调用方）+ `providerApp`/`providerIp`（被调方），一条记录即一条 A→B 边
- **IP 链 ≈ 调用链**：A 的 `providerIp` 会作为下一条达 B 的调用边界；逐层用 `consumerIp/providerIp` 衔接即可还原调用拓扑
- **业务标识做弱关联**：`user` / `uri` / `topic+key` / `param` 用于区分同一 IP 下的并发请求
- traceId 缺失时误差无可避免，**必须收窄时间窗口（秒级对齐）+ 用业务标识**，并在结果标注置信度

---

### 1A. 有 traceId（精确串联）

#### 校验要点

- 时间范围：用 traceId 精确匹配，范围 ≤ 1h 即可（R1 通过）
- 如 traceId 某类查不到，降级到 1B 近似关联（traceId 不完善）

#### 调用步骤

并行发起 5 个查询（同一 traceId）：

```
GET /sysLog/dubboLog/list?traceId={traceId}&executeDate={date}&executeTimeRange={range}
GET /sysLog/webLog/list?traceId={traceId}&executeDate={date}&executeTimeRange={range}
GET /sysLog/webErrorLog/list?url={uri}&executeDate={date}&executeTimeRange={range}    # 仅当 web 入口报错时
GET /sysLog/sqlLog/list?providerApps={app}&executeDate={date}&executeTimeRange={range}  # 按 web/dubbo 命中的应用过滤
GET /sysLog/loggerLog/list?traceId={traceId}&executeDate={date}&executeTimeRange={range}
```

WebErrorLog 无 traceId 参数（见模板 1 原说明），需用 url 关联。

---

### 1B. 无 traceId（近似串联，兼容场景）

> 触发时机：用户没给 traceId、traceId 在所有日志都查不到、或检测到部分链路未打点。

#### 校验要点

- 必须给定：`executeDate` + `executeTimeRange`（**时间窗口越窄越准，优先秒级对齐**）
- `uri` 或 `user` 或 `topic+key` 等业务标识至少给一个（增强区分度）
- 时间跨度 > 1h 时按 R1 仍须指定应用，此处通常自然满足（排查会锁定入口应用）

#### 调用步骤：沿 IP 链逐层下钻

```
第 1 步：找入口（web_log）
GET /sysLog/webLog/list?uri={uri}&user={user}&executeDate&executeTimeRange
→ 取入口实例 providerIp 与 providerApp

第 2 步：该实例作为调用方，查它发起的 dubbo（服务边界 A→B）
GET /sysLog/dubboLog/list?consumerApp={web的providerApp}&executeDate&executeTimeRange
→ 得 providerApp/providerIp（被调方 B）

第 3 步：对每个被调的 providerIp，查其 logger（异常/堆栈）
GET /sysLog/loggerLog/list?providerApps={providerApp}&providerIp={ip}&executeDate&executeTimeRange

第 4 步：查其执行的 SQL（数据库调用）
GET /sysLog/sqlLog/list?providerApps={providerApp}&executeDate&executeTimeRange

第 5 步：若 B 又调 C（存在 dubbo providerIp 继续被 consumerIp 引用）
→ 用 B 的 providerIp 重复第 2 步，逐层下钻，直到无更多下游调用
```

#### 结果整理与置信度标注

1. 按 `createDate` 正序合并各层日志成时间线
2. **标注每条记录的关联置信度**：
   - 高：`providerIp + 业务标识（user/uri/key/param）` 同时命中
   - 中：仅 `${providerIp} + 时间窗口` 命中（同一 IP 有并发请求时可能混入）
   - 低：仅按应用 + 时间聚合（多实例易偏移，需谨慎）
3. 同一 IP 并发高时，优先用 `param`（含业务主键，如订单号）强区分"同一次操作"
4. 用 `elapsedTime` 校验：web 耗时 ≈ dubbo 耗时 + sql 耗时 + 业务耗时，异常偏离说明漏环节

输出示例（无 traceId）：

```
## 调用链时间线（无 traceId，近似串联，置信度：中-高）
关联依据：IP 链(10.0.0.1→10.0.0.3) + user=user001 + 订单号 param=ORDER_123

[10:00:01] [Web](高)    POST /api/order/create  user=user001  providerIp=10.0.0.1  耗时=1200ms
[10:00:01] [Dubbo](高)  OrderService.create  consumer=web-app@10.0.0.1 → provider=order-app@10.0.0.3  耗时=1180ms
[10:00:02] [SQL](中)    order-app@10.0.0.3  INSERT INTO t_order where order_no=ORDER_123  耗时=850ms
[10:00:02] [Logger](高) order-app@10.0.0.3  ERROR  OrderService.create  创建订单失败: 库存不足
[10:00:02] [Dubbo](高)  StockService.deduct  consumer=order-app@10.0.0.3 → provider=stock-app@10.0.0.5  exception=StockNotEnoughException

## 异常定位
根因：StockService.deduct 抛 StockNotEnoughException（库存不足）
位置：stock-app @ 10.0.0.5
链路：web-app(10.0.0.1) → order-app(10.0.0.3) → stock-app(10.0.0.5)
置信度说明：IP+user+订单号命中为高，SQL 仅按 IP+时间命中为中，建议复核
```

---

### PowerShell 示例

```powershell
$params = @{
    Uri     = "$monitorBase/sysLog/dubboLog/list?traceId=abc123&executeDate=2026-08-13&executeTimeRange=09:00:00%20-%2010:00:00&pageNumber=1&pageSize=50"
    Headers = @{ "Cookie" = $monitorAuth }
}
Invoke-RestMethod @params
```

---

## 模板 2：Dubbo 失败排查

### 场景

某应用 Dubbo 调用失败/超时，需定位失败调用。

### 校验要点

- 时间范围 > 1h：必须指定 `providerApps` 或 `consumerApp`（R1.T2）
- 时间范围 ≤ 1h：可仅按 `status=fail` 查询

### 调用步骤

```
GET /sysLog/dubboLog/list?providerApps={app}&executeDate={date}&executeTimeRange={range}&status=fail&sort=elapsedTime
```

### 结果整理

1. 按异常类型分组（`exception` 字段提取根异常类名）
2. 统计失败次数、平均耗时、Top 失败接口
3. 高亮超时调用（`timeout=true`）
4. 输出 Top5 失败接口表 + 异常堆栈

---

## 模板 3：慢 SQL 定位

### 场景

某应用慢查询多，需定位慢 SQL。

### 校验要点

- 时间范围 > 1h：必须指定 `providerApps`（R1.T2）
- `sort=elapsedTime` 按耗时倒序

### 调用步骤

```
GET /sysLog/sqlLog/list?providerApps={app}&executeDate={date}&executeTimeRange={range}&sort=elapsedTime
```

### 结果整理

1. 按 `elapsedTime` 倒序展示 Top10 慢 SQL
2. 提取 SQL 模板（去掉参数值）
3. 统计相同 SQL 模板出现次数
4. 建议执行计划分析：`GET /db/sqlAnalyze/query?sql={sql}`

### 进阶：DB 慢 SQL 库

如需查 RDS 层面慢 SQL：

```
GET /db/dbSlowSql/list?dbId={dbId}
```

---

## 模板 4：Kafka 消息追溯 + 补发

### 场景

某 Kafka 消息丢失或处理失败，需追溯并补发。

### 校验要点

- 时间范围 > 1h：必须指定 `topic`（参照 R1，Kafka 日志的"应用过滤"等价为 topic）
- 补发消息需 R4 二次确认

### 调用步骤

1. 追溯消息：

```
GET /sysLog/kafkaLog/list?topic={topic}&key={key}&executeDate={date}&executeTimeRange={range}
```

2. 如需补发，列出待补发 `logId`，向用户确认：

```
待补发消息：
- logId=xxx1  topic=order-create  key=ORDER_123  时间=10:00:01
- logId=xxx2  topic=order-create  key=ORDER_124  时间=10:00:05

是否执行补发？(yes/no)
```

3. 用户确认后：

```
POST /sysLog/kafkaLog/reSendMq?logIds=xxx1,xxx2
```

### 结果整理

补发后返回：`补发完成，成功:N 条，失败:M 条`

---

## 模板 5：前端错误排查

### 场景

前端页面报错，需定位是哪个接口、哪个用户、什么错误。

### 校验要点

- 时间范围 > 1h：必须指定 `providerApps`（systemCode，R1.T2）
- `providerApps` 在 webErrorLog 中对应 systemCode

### 调用步骤

```
GET /sysLog/webErrorLog/list?providerApps={systemCode}&executeDate={date}&executeTimeRange={range}&user={userPin}
```

### 结果整理

1. 按 `url` 分组统计错误次数
2. 提取 `exception` 字段根因
3. 关联 `reqPageUrl`（出错页面）和 `reqPageImg`（截图）
4. 输出：错误 URL → 错误次数 → 根因 → 受影响用户

---

## 模板 6：系统状态诊断（JVM / CPU / 连接池 / 线程池）

### 场景

应用 OOM、堆内存高、CPU 飙升、线程池打满、连接池耗尽、GC 频繁等系统级问题排查。

### 校验要点

- `providerApp` 与 `providerIp` **至少传一个**（接口要求二选一）
- 时间格式用 `executeDateStart`/`executeDateEnd`（**分钟级** `yyyy-MM-dd HH:mm`，区别于其他接口的日级）
- **不受 R1 单日限制**（接口支持跨日），但跨度 > 7 天时建议提示用户缩小范围

### 调用步骤

#### 第 1 步：定位容器（可选）

先按应用查存活/停用容器，确定要排查的具体 IP：

```
GET /sysLog/sysStatus/pods?appName={app}&executeDateStart={t1}&executeDateEnd={t2}
```

返回 `alive`（当前生效）与 `stopped`（最近停用）两个列表。

#### 第 2 步：查系统状态

按 IP 或应用查询：

```
# 按具体 IP（推荐，精确到实例）
GET /sysLog/sysStatus/list?providerIp={ip}&executeDateStart={yyyy-MM-dd HH:mm}&executeDateEnd={yyyy-MM-dd HH:mm}

# 或按应用（返回该应用所有实例）
GET /sysLog/sysStatus/list?providerApp={app}&executeDateStart={yyyy-MM-dd HH:mm}&executeDateEnd={yyyy-MM-dd HH:mm}
```

#### 第 3 步：导出 Excel（可选）

导出仅支持按 providerIp：

```
GET /sysLog/sysStatus/exportExcel?providerIp={ip}&executeDateStart={t1}&executeDateEnd={t2}
```

> **导出列说明**：Excel 仅含 `时间/服务器/Heap/Eden/Survivor/OldGen/Druid/Dubbo`，**不含 cpuUsage/memUsage/threadCount**。CPU、线程、内存使用率请通过 `list` 接口返回值查看。

### 指标 → 问题映射（诊断关键）

按以下规则分析返回结果中的指标趋势：

| 症状 | 判断依据 | 可能结论 |
|---|---|---|
| 内存泄漏 | `oldGenUsed`/`oldGenStr` 持续上涨且未下降、堆用比接近 90% | 老年代对象无法回收，疑似泄漏 |
| GC 压力大 | `oldGen` 接近 `oldGenMax`、Heap 频繁打满 | 频繁 Full GC，需 dump 堆分析 |
| 线程池打满 | `dubboUsed`/`dubboMax` ≥80% 或达上限 + `threadCount` 高 | Dubbo 线程池耗尽，可能下游慢/阻塞 |
| 连接池耗尽 | `druidActiveCount`/`druidMaxCount` ≥90% | 数据库连接被占满，可能慢 SQL/连接未释放 |
| CPU 瓶颈 | `cpuUsage` 趋近 100% 持续 | CPU 密集型或死循环，结合 Logger 定位 |
| 内存使用率高 | `memUsage` 接近 100%（指宿主机内存） | 宿主机内存告急，可能 OOM Kill |

> 内置告警阈值参考（采集端）：JVM 堆 ≥90%、Dubbo 线程池 ≥60%、Druid 连接池 ≥90%。

### 结果整理

1. 提取 `heapStr`、`oldGenStr` 趋势（Old Gen 持续上涨 → 内存泄漏）
2. 提取 `cpuUsage` 曲线（趋近 100% → CPU 瓶颈）
3. 提取 `dubboStr` 线程池使用率（≥80% → 线程池打满）
4. 提取 `druidStr` 连接池使用率（≥90% → 连接池耗尽）
5. 输出趋势表格 + 异常点标注 + 结合 Logger 日志定位根因

---

## 模板 7：操作日志聚合统计

### 场景

分析用户功能使用情况、功能 PV/UV、Top 功能。

### 校验要点

- 用 `beginCreateDate`/`endCreateDate`，格式 `yyyy-MM-dd HH:mm:ss`
- 跨度 > 24h 时按 R1.T1 拒绝（操作日志也受时间约束）

### 调用步骤

按需选择接口：

```
# 用户功能使用列表
GET /sysLog/operlog/findUserOperlogs?groupId={gid}&beginCreateDate={t1}&endCreateDate={t2}&user={u}

# 功能 PV/UV Top
GET /sysLog/operlog/findFunctionOperlogs?groupId={gid}&beginCreateDate={t1}&endCreateDate={t2}&sort=desc

# Top30 功能统计
GET /sysLog/operlog/findOperlogStat?groupId={gid}&beginCreateDate={t1}&endCreateDate={t2}
```

### 结果整理

1. 按 PV 倒序排列
2. 计算 UV/PV 比（功能粘性）
3. 标注 Top3 高频功能 + Top3 低频功能

---

## 模板 8：XXL-Job 调度日志

### 场景

XXL-Job 定时任务执行异常，需查看任务日志详情。

### 校验要点

- 三个参数 `logId`、`serverIp`、`time` 均为必填
- `time` 格式含 `T` 分隔符（ISO 8601 部分）

### 调用步骤

```
GET /job/log/index?logId={logId}&serverIp={ip}&time=2026-08-13T10:00:00
```

### 结果整理

返回 HTML 日志内容，直接展示任务执行日志原文。

---

## 模板 9：异步导出/大批量任务堆内存急性打满（OOM 排查）

> 沉淀自 2026-09-03 zq-pmc-web 生产事故：任务中心「店仓商品导出」一次性全量加载（pageSize=999999，主查询返回 999999 行撞上限截断、实际 ≥100 万，笛卡尔 enrichment 223 万行），单个 pod 老年代 550→2560MB 钉死，22 分钟 84 次 CMF + 69 次 Full GC，服务不可用。

### 场景特征（满足即入本模板）

- 堆内存**急性打满**：分钟级老年代从正常水位骤升至 max，而非数天缓慢上涨（区别于泄漏）
- **单个 pod 独自打满**，同应用其他 pod 仅轻微联动（溢出流量）
- GC 日志：Full GC 回收量 ≈ 0（对象被活线程引用，非泄漏）+ concurrent mode failure 连发
- 触发点在任务中心/异步导出（如「上传下载任务中心」截图）或 XXL-Job，**异步执行体不出现在同步请求耗时里**

### 排查套路（四步）

#### 第 1 步：sysStatus 锁定元凶 pod

多 pod 逐个拉堆趋势，找「老年代骤升且钉死」的那个，其余 pod 作对照组：

```
GET /sysLog/sysStatus/list?providerIp={ip}&executeDateStart={t1}&executeDateEnd={t2}
```

判断要点：
- 元凶 pod：oldGen 正常水位 → 分钟内打满 max 并持续钉死
- 对照 pod：oldGen 轻微上涨后回落（溢出流量），或完全平稳
- 伴生指标佐证：`dubboStr` 打满、`threadCount` 上涨（长 STW 导致请求堆积）

#### 第 2 步：webLog 找异步任务提交记录（不是执行记录）

异步导出的提交请求耗时只有几 ms，**别用 elapsedTime 找**。用 requestBody 搜 serviceBean/功能名：

```
GET /sysLog/webLog/list?providerApps={app}&user={user}&executeDate={date}&executeTimeRange={提交前后1分钟}&pageSize=20
# 或全日搜：requestBody={serviceBean名}，如 requestBody=mtStoreSkuInfoExportManager
```

从 `requestBody` 拿到**导出筛选条件**——重点看筛选条件是否接近全空（storeIdList=null、状态/类目全空 = 全量导出）。

#### 第 3 步：sqlLog 量化真实数据量（本模板核心）

```
GET /sysLog/sqlLog/list?providerApps={app}&executeDate={date}&executeTimeRange={窗口}&pageSize=100
```

> **sqlLog 字段坑（必读）**：实际返回字段为 `sqlText` / `queryTime` / `parseRowCounts`（扫描行数）/ `returnRowCounts`（返回行数）/ `executionStartTimeStr` / `dbName` / `sqlHash`；文档旧字段名 `fullSql`/`elapsedTime`/`createDate` 取出来是空。`sort` 仅支持 `createDate`/`elapsedTime`，传 `queryTime` 等 500 报错——**建议不加 sort，客户端按 queryTime 排序**。该接口对 providerApps 过滤可能不严格，用 SQL 注释中的 dao 类名（如 `com.jy.zq.pmc.dao.`）识别归属。

分析三条线索：
1. **主查询行数**：`returnRowCounts` 正好等于 pageSize 上限（如 999999）→ 查询被截断，数据不完整（即使没 OOM 导出的文件也是错的）
2. **enrichment 笛卡尔查询**：主查询之后按 `IN(skuIdList) × IN(storeIdList)` 类关联查询，**返回行数可能远超主查询**（实测 100 万主行 → 223 万关联行），别只看主查询
3. **时间线对齐**：`executionStartTimeStr + queryTime` 推算 SQL 起止，与 GC 晋升起点、首次 CMF 时刻对齐，锁定因果（实测：主查询结束时间 = 晋升开始时间，分秒吻合）

#### 第 4 步：三角对照验证（区分代码问题 vs 数据量问题）

1. **同功能其他用户/pod 对照**：同一导出功能在不同用户下行的数不同（导出范围随用户店铺权限变化），行数差几倍是常态——查同期其他提交的 `returnRowCounts`
2. **历史几天对照**：逐日搜同功能的提交记录（webLog `requestBody=serviceBean名`）+ sqlLog 关键字（`fullSql=dao方法名`），得出历史最大行数基线
3. **内存估算**：工作集 ≈ 总实体行数（主查询 + 笛卡尔关联）× 均摊 500B~1KB/实体。**该均摊已含实体 List / 关联 Map / VO / Excel 多形态的摊销，勿再乘副本系数（会重复计算）**。校准参照：本次 320 万实体 → 老年代增量 ≈ 2.0GB，均摊约 700B

### 结果整理输出结构

```
| 时间 | 事件 |（提交请求 → count SQL → 主查询 → enrichment → 晋升 → CMF → 伴生错误）

根因：<哪个功能/任务> + <数据量> + <内存模式缺陷>
对照：历史最大 N 行正常 / 本次 M 行崩溃 / 同期其他用户 K 行正常
数据完整性：returnRowCounts 是否撞 pageSize 上限
```

### 伴生症状清单（勿当独立问题排查）

长 STW 期间会出现一批"次生灾害"日志，属同一根因，不要逐个排查：
- `ClientAbortException: Broken pipe`（响应写回时客户端已超时断开）
- Redisson `Unable to send PING command`（GC 停顿导致心跳超时）
- Kafka `Offset commit failed`
- Dubbo 线程池打满、线程数上涨、`zq-pmc` 消费组重平衡

### 修复建议清单（输出时附带）

1. 改真分页流式导出（循环分页查询 + 每批 enrichment + SXSSFWorkbook/EasyExcel 分批写），删掉 `pageSize=999999` 类伪分页
2. 硬性导出上限校验（count 超阈值直接拒绝提示缩小范围），禁止静默截断
3. enrichment 关联查询按批切分，避免 IN×IN 笛卡尔一次性返回
4. 任务中心大导出全局并发限流（并发=1 或按内存水位排队）
5. JVM 加 `-XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=...` 兜底
6. 即时处置：重启元凶 pod 释放被钉死的导出线程（任务需重新发起）

---

## 通用结果整理规范

### 时间线展示

跨日志联查结果按时间正序展示，每行格式：

```
[HH:mm:ss] [日志类型]  关键字段=值  关键字段=值
```

### 异常定位

发现 `exception` 字段时：

1. 提取根异常类名（最后一个 `Caused by:`）
2. 关联上下游调用（同 traceId 的其他日志）
3. 输出：根因 → 位置 → 影响 → 建议

### 表格展示

单类日志查询结果用表格展示，列选择：

| 日志类型 | 推荐列 |
|---|---|
| Dubbo | 时间, 接口方法, 消费者→提供者, 耗时, 状态, traceId |
| Web | 时间, URI, 应用, 耗时, user, traceId |
| SQL | 时间, 应用, SQL摘要, 耗时, database |
| Kafka | 时间, topic, key, value摘要 |
| Logger | 时间, 应用, 级别, 类名, 消息摘要 |
| WebError | 时间, URL, 错误摘要, user, 页面URL |

SQL 摘要规则：截取前 100 字符，多空白压缩为单空格。
