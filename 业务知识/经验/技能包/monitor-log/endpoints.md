# Monitor 日志查询接口清单

monitor 平台所有日志查询接口的完整规范。所有接口均为 HTTP GET，返回 JSON 格式 `{rows:[...], total:N}`（部分接口返回 `Grid` 对象 `{list:[...], total:N}`）。

## 通用规则

### 请求头
```
Cookie: {monitorAuth}    # 鉴权凭证，内网免登可省略
```

### 通用分页参数

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `pageNumber` | int | 1 | 页码，从 1 开始 |
| `pageSize` | int | 50 | 每页条数，上限 500 |

### 通用时间参数

| 参数 | 类型 | 必填 | 格式 | 说明 |
|---|---|---|---|---|
| `executeDate` | string | 是 | `yyyy-MM-dd` | 查询日期，仅支持单日 |
| `executeTimeRange` | string | 否 | `HH:mm:ss - HH:mm:ss` | 时间范围，不传则全天 |

时间范围约束见 [SKILL.md R1](./SKILL.md#r1时间范围梯度约束核心)。

### 环境过滤

- 非 prod 环境：monitor 后端自动追加 `env='当前环境'` 过滤，**调用方不要手动传 env**
- prod 环境：查全量数据，无 env 过滤

---

## 1. Dubbo 日志

查询 Dubbo 服务调用日志，包含接口方法、参数、返回值、异常、耗时、traceId。

- **URL**: `GET {monitorBase}/sysLog/dubboLog/list`
- **数据源**: Doris `sys_log.dubbo_log`
- **采集链路**: 业务应用 → Redis `global:dubbo_logs` → Doris Stream Load

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `consumerApp` | string | 否 | 消费者应用名（单选） |
| `providerApps` | string | 否 | 提供者应用名（多选，逗号分隔） |
| `providerIp` | string | 否 | 提供者 IP |
| `interfaceMethod` | string | 否 | 接口方法（like 模糊匹配） |
| `traceId` | string |否 | 追踪 ID（精确匹配） |
| `param` | string | 否 | 参数内容（like，最小 3 字符） |
| `elapsedTime` | string | 否 | 耗时大于（ms，正整数） |
| `providerThreadPool` | string | 否 | 线程池活跃数大于（正整数） |
| `status` | string | 否 | 执行状态：`ok`/`fail`/`timeout` |
| `sort` | string | 否 | 排序字段：`createDate`（默认）/`elapsedTime` |
| `executeDate` | string | 是 | 查询日期 |
| `executeTimeRange` | string | 否 | 时间范围 |

### 返回字段

```json
{
  "logId": "uuid",
  "consumerApp": "app-name",
  "providerApp": "app-name",
  "consumerIp": "10.0.0.1",
  "providerIp": "10.0.0.2",
  "interfaceMethod": "com.xxx.Service.method",
  "param": "{...}",
  "returnValue": "{...}",
  "exception": "stack trace",
  "elapsedTime": 123,
  "timeout": false,
  "providerThreadPool": "10/200",
  "traceId": "abc123",
  "createDate": "2026-08-13 10:00:00",
  "env": "prod"
}
```

---

## 2. Web 请求日志

查询 HTTP 请求日志，包含 URI、请求体、响应、header、traceId、user。

- **URL**: `GET {monitorBase}/sysLog/webLog/list`
- **数据源**: Doris `sys_log.web_log`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `providerApps` | string | 否 | 应用名（多选，逗号分隔） |
| `providerIp` | string | 否 | 应用 IP |
| `uri` | string | 否 | 请求 URI（精确匹配） |
| `requestBody` | string | 否 | 请求体（like，最小 3 字符） |
| `requestParam` | string | 否 | 请求参数（like，最小 3 字符） |
| `requestHeader` | string | 否 | 请求头（like，最小 3 字符） |
| `traceId` | string | 否 | 追踪 ID（精确匹配） |
| `user` | string | 否 | 用户标识 |
| `elapsedTime` | string | 否 | 耗时大于 N 毫秒（正整数，过滤慢请求） |
| `sort` | string | 否 | 排序字段，默认 `createDate` |
| `executeDate` | string | 是 | 查询日期 |
| `executeTimeRange` | string | 否 | 时间范围 |

---

## 3. Web 错误日志

查询前端 H5/小程序上报的错误日志（前端通过 `/collectErrorLog` 主动上报）。

- **URL**: `GET {monitorBase}/sysLog/webErrorLog/list`
- **数据源**: Doris `sys_log.web_error_log`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `providerApps` | string | 否 | 系统编码（多选，逗号分隔） |
| `providerIp` | string | 否 | 应用 IP |
| `url` | string | 否 | 请求 URL（匹配 `uri` 或 `reqPageUrl`） |
| `requestBody` | string | 否 | 请求体（like，最小 3 字符） |
| `responseBody` | string | 否 | 响应体（like，最小 3 字符） |
| `requestParam` | string | 否 | 请求参数（like，最小 3 字符） |
| `requestHeader` | string | 否 | 请求头（like，最小 3 字符） |
| `user` | string | 否 | 用户标识 |
| `sort` | string | 否 | 排序字段，默认 `createDate` |
| `executeDate` | string | 是 | 查询日期 |
| `executeTimeRange` | string | 否 | 时间范围 |

---

## 4. SQL 执行日志

查询业务应用执行的 SQL 日志，包含完整 SQL、执行耗时、应用、database。

- **URL**: `GET {monitorBase}/sysLog/sqlLog/list`
- **数据源**: Doris `sys_log.sql_log`

> **实际返回字段与调用坑（2026-09-03 实测）**：
> - 实际**返回字段**：`sqlText`（完整 SQL）、`queryTime`（耗时 ms）、`parseRowCounts`（扫描行数）、`returnRowCounts`（返回行数）、`executionStartTimeStr`（执行开始时间）、`dbName`、`dbInstanceId`、`hostAddress`、`sqlHash`、`lockTime`
> - 旧文档中 `fullSql`/`elapsedTime`/`createDate` 在**返回 JSON 里不存在**（取值为空），整理结果务必用上列字段；但 `fullSql` 作为**查询参数**仍有效（like 检索），两者不冲突
> - `sort` 传非文档值（如 `queryTime`）返回 500；`sort=elapsedTime` 实测也曾 500，稳定性存疑——**建议不加 sort，客户端按 `queryTime` 排序**
> - `providerApps` 过滤可能不严格（会混入其他应用 SQL），归属识别用 SQL 注释中的 dao 全类名（如 `/* com.jy.zq.pmc.dao.XxxDao.method */`）
> - 量化数据量时：`parseRowCounts`=扫描行数（看索引效率），`returnRowCounts`=返回行数（看业务数据量）；`returnRowCounts` 正好等于业务 pageSize 上限 → 查询被截断

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `providerApps` | string | 否 | 应用名（多选，逗号分隔） |
| `fullSql` | string | 否 | 完整 SQL（like，最小 3 字符） |
| `database` | string | 否 | 数据库名（精确匹配） |
| `sort` | string | 否 | 排序字段，默认 `createDate`，常用 `elapsedTime` |
| `executeDate` | string | 是 | 查询日期 |
| `executeTimeRange` | string | 否 | 时间范围 |

---

## 5. Kafka 消息日志

查询 Kafka 消息日志，支持消息补发。

- **URL**: `GET {monitorBase}/sysLog/kafkaLog/list`
- **数据源**: Doris `sys_log.kafka_log`

### 查询参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `topic` | string | 否 | Kafka topic（精确匹配） |
| `key` | string | 否 | 消息 key（精确匹配） |
| `value` | string | 否 | 消息内容（like，最小 3 字符） |
| `executeDate` | string | 是 | 查询日期 |
| `executeTimeRange` | string | 否 | 时间范围 |

### 消息补发（写操作，需 R4 二次确认）

- **URL**: `POST {monitorBase}/sysLog/kafkaLog/reSendMq`
- **参数**: `logIds=id1,id2,id3`
- **说明**: 根据 logIds 查询 kafka_log 表，重新发送 Kafka 消息

---

## 6. Logger 应用日志

查询应用 logback 输出的 logger 日志，支持日志级别、类名、traceId、内容过滤。

- **URL**: `GET {monitorBase}/sysLog/loggerLog/list`
- **数据源**: Doris `sys_log.logger_log`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `providerApps` | string | 否 | 应用名（多选，逗号分隔） |
| `providerIp` | string | 否 | 应用 IP |
| `level` | string | 否 | 日志级别：`ERROR`/`WARN`/`INFO` |
| `traceId` | string | 否 | 追踪 ID（精确匹配） |
| `className` | string | 否 | 全类名（like 模糊匹配） |
| `message` | string | 否 | 日志内容（like，最小 3 字符） |
| `message2` | string | 否 | 第二个日志内容关键字（与 message 为或关系） |
| `messageType` | string | 否 | 消息类型（预留参数，源码已声明但当前未实际处理） |
| `executeDate` | string | 是 | 查询日期 |
| `executeTimeRange` | string | 否 | 时间范围 |

### 特殊功能

- **修改日志级别**：`POST /dev/modifyLogLevel/execute?aliveServers=ALL&appName={app}&level={level}`
- **K8S 日志查看**：`{k8sNodeIp}/log/{appName}-deployment?namespace={namespace}`（浏览器打开）

---

## 7. 系统状态监控

查询应用在某时间的系统资源：JVM 堆内存（Heap/Eden/Survivor/OldGen）、CPU、内存、线程数、Druid 连接池、Dubbo 线程池。用于定位内存泄漏、线程池打满、连接池耗尽、CPU 飙升、GC 频繁等系统级问题。

### 7.1 查询列表

- **URL**: `GET {monitorBase}/sysLog/sysStatus/list`
- **数据源**: Doris `sys_log.sys_status_monitor_log`

#### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `providerApp` | string | **\*二选一** | 应用名（与 providerIp 至少其一） |
| `providerIp` | string | **\*二选一** | 服务器 IP（与 providerApp 至少其一） |
| `executeDateStart` | string | **是** | 起始时间 `yyyy-MM-dd HH:mm`（**分钟级**） |
| `executeDateEnd` | string | **是** | 结束时间 `yyyy-MM-dd HH:mm`（**分钟级**，接口按 +1 分钟处理） |

> 注意：
> - `providerApp` 与 `providerIp` 至少传一个；两者都空或时间缺失 → 返回空结果
> - **时间格式为分钟级** `yyyy-MM-dd HH:mm`（非日级），区别于其他日志接口
> - **无分页**，返回时间范围内全量记录
> - **无 env 过滤**（与 dubbo/web 等不同），需自行按环境区分
> - 采集频率：每 5 分钟一条；数据保留 5 天

### 7.2 按应用查存活/停用容器

- **URL**: `GET {monitorBase}/sysLog/sysStatus/pods`
- **参数**: `appName`（必填）、`executeDateStart`/`executeDateEnd`（可选，分钟级，用于限定停用容器提取时间范围）
- **返回**: `{"alive":[{"ip":"...","status":"alive"}],"stopped":[{"ip":"...","status":"stopped"}]}`
- **用途**: 排查前先定位应用当前生效容器与最近停用容器，再对具体 IP 逐个查系统状态

### 7.3 导出 Excel

- **URL**: `GET {monitorBase}/sysLog/sysStatus/exportExcel`
- **参数**: `providerIp`（必填）、`executeDateStart`/`executeDateEnd`（必填，分钟级）
- **返回**: 二进制 xlsx 文件（列：时间、服务器、Heap、Eden、Survivor、OldGen、Druid、Dubbo）

### 7.4 关键字段

| 字段 | 说明 | 单位/格式 |
|---|---|---|
| `heapUsed` / `heapMax` | JVM 堆已用/最大 | 字节 |
| `edenSpaceUsed` / `edenSpaceMax` | Eden 区已用/最大 | 字节 |
| `survivorSpaceUsed` / `survivorSpaceMax` | Survivor 区已用/最大 | 字节 |
| `oldGenUsed` / `oldGenMax` | 老年代已用/最大 | 字节 |
| `dubboUsed` / `dubboMax` | Dubbo 线程池已用/最大 | 线程数 |
| `druidActiveCount` / `druidMaxCount` | Druid 连接池活跃/最大 | 连接数 |
| `threadCount` | 应用线程总数 | 线程数 |
| `cpuUsage` | CPU 使用率 | 百分比（0-100） |
| `memUsage` | 内存使用率 | 百分比（0-100） |

### 7.5 展示格式化字段（list 返回）

```
createDateStr, providerIp, providerApp,
heapStr("used/max MB"), edenSpaceStr, survivorSpaceStr, oldGenStr,
druidStr("active/max"), dubboStr("used/max"), threadCount, cpuUsage, memUsage
```

### 7.6 内置告警阈值（采集端，可作诊断参考）

| 指标 | 默认阈值 | 说明 |
|---|---|---|
| JVM 堆内存 | 90%（`heap.percent.alarm`） | 堆已用/最大 ≥90% 触发严重告警 |
| Dubbo 线程池 | 60%（`dubbo.percent.alarm`） | 线程池已用/最大 ≥60% 触发 |
| Druid 连接池 | 90%（`druid.percent.alarm`） | 连接池活跃/最大 ≥90% 触发 |

> 告警注意：同一 IP 5 小时内最多告警一次（采集端去重），阈值仅供诊断参考，不代表已入库的告警全部触发。

---

## 8. 操作日志聚合统计

操作日志按 URI 维度聚合统计，支持用户功能使用分析。

- **URL**: 多个聚合接口
- **数据源**: Doris `sys_log.operlog_uri_stat`

### 8.1 用户操作日志列表

- **URL**: `GET {monitorBase}/sysLog/operlog/findUserOperlogs`
- **参数**: `groupId`, `beginCreateDate`, `endCreateDate`, `user`, `pageNumber`, `pageSize`

### 8.2 功能操作报表

- **URL**: `GET {monitorBase}/sysLog/operlog/findFunctionOperlogReport`
- **参数**: `groupId`, `beginCreateDate`, `endCreateDate`, `function`

### 8.3 功能操作列表

- **URL**: `GET {monitorBase}/sysLog/operlog/findFunctionOperlogs`
- **参数**: `groupId`, `beginCreateDate`, `endCreateDate`, `function`, `role`, `sort`, `use`, `uri`

### 8.4 操作统计 Top30

- **URL**: `GET {monitorBase}/sysLog/operlog/findOperlogStat`
- **参数**: `groupId`, `beginCreateDate`, `endCreateDate`, `device`

### 时间参数说明

操作日志用 `beginCreateDate`/`endCreateDate`（非 `executeDate`），格式 `yyyy-MM-dd HH:mm:ss`，**支持跨日**（但仍受 R1 约束）。

---

## 9. DB 慢 SQL

查询数据库慢 SQL 配置库（MySQL 主库，非 Doris）。

- **URL**: `GET {monitorBase}/db/dbSlowSql/list`
- **数据源**: MySQL `jy_monitor.db_slow_sql`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `dbId` | long | 是 | 数据库 ID |
| `pageNumber` | int | 否 | 默认 1 |
| `pageSize` | int | 否 | 默认 20 |

---

## 10. XXL-Job 调度日志

查询 XXL-Job 调度任务执行日志，数据源为 ES。

- **URL**: `GET {monitorBase}/job/log/index`
- **数据源**: ES 索引 `plume_log_run_yyyyMMdd`

### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `logId` | string | 是 | 任务日志 ID |
| `serverIp` | string | 是 | 日志服务地址 |
| `time` | string | 是 | 任务执行时间（含 `T` 分隔符，如 `2026-08-13T10:00:00`） |

### 返回

直接返回 HTML 日志内容（非 JSON）。

---

## 应用元数据接口

### 列应用 Pod IP

- **URL**: `GET {monitorBase}/sysLog/dubboLog/findProviderIpsByApp?appName={appName}`
- **返回**: `["10.0.0.1", "10.0.0.2"]`

### 应用列表来源

应用列表来自 `K8sPod` 表（MySQL 主库），monitor 启动时 `ServerHealthCheckController.registry()` 接收应用上报。用户提及应用名时，可调用此接口校验应用是否存在并获取 pod IP。
