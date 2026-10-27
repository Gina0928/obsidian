---
name: "monitor-log"
description: "查询 jy-monitor 平台日志与系统状态（Dubbo/Web/SQL/Kafka/Logger/WebError/操作日志/慢SQL/XXL-Job/JVM堆/CPU/线程/连接/线程池）。查日志、traceId联查、失败分析、慢SQL定位及内存泄漏/线程池打满/连接数高/CPU飙升/GC频繁等系统诊断时触发。"
---

# Monitor 日志查询技能

查询 jy-monitor 平台各类运行日志，用于线上问题分析、traceId 跨日志联查、失败排查、慢 SQL 定位、Kafka 消息追溯等。

## 触发条件

用户提到以下任意场景时立即加载本技能：
- 查日志 / 查 monitor / 查监控日志
- 查 traceId / 串联调用链 / 链路追踪（traceId 不完善时按 IP 链近似串联，见模板 1B）
- 查 dubbo 日志 / 查 web 日志 / 查 sql 日志 / 查 kafka 日志 / 查 logger 日志
- 查慢 sql / 查系统状态 / 查操作日志 / 查 xxl-job 日志
- 内存泄漏 / 堆内存高 / 线程池打满 / 连接数过高 / CPU 飙升 / GC 频繁 / JVM 排查
- 线上问题排查 / 失败排查 / 报错分析

## 环境配置（首次使用必读）

执行任何查询前，必须先确认以下变量，**按以下优先级获取**：

| 变量 | 说明 | 示例 |
|---|---|---|
| `monitorBase` | monitor 部署地址（不含末尾斜杠） | `http://10.128.62.33:8080` |
| `monitorEnv` | 环境标识（dev/test/stg/pre/prod/prod-yas/prod-hmt/prod-wky） | `prod` |
| `monitorAuth` | 鉴权凭证（SSO Cookie 或内网免登可不传） | `sessionid=xxx` |

**配置获取优先级（强制按序执行）**：

1. **会话内复用**：本次会话已确认过的变量直接复用，不重复询问
2. **全局公共配置匹配（跨项目）**：读取 `C:\Users\liwen\.trae-cn\memory\monitor-config.json`，按用户给定的环境名称匹配：
   - 先精确匹配 `envs` 下的 env 键（如 `prod-yas`）
   - 再匹配该节点的 `aliases`（支持中文别名，如「雅斯生产」→ `prod-yas`）
   - 命中后取该节点的 `monitorBase`/`monitorEnv`/`monitorAuth`
   - `monitorAuth` 为空时先尝试内网免登直连（不传 Cookie），返回 401/跳登录页再向用户索取
   - `monitorBase` 为空（待补充环境）→ 向用户询问
3. **未命中 → 询问用户并回写**：用户给出新环境/新地址/新 Cookie 后，**必须回写** `monitor-config.json` 对应环境节点（新环境新增节点，auth 过期更新 auth 字段），实现一次提供、全局永久复用

变量确认后，在本次会话中复用，不重复询问。

## 排查定性与决策（接到排查请求先看这里）

**待排查问题时，先做问题定性与决策树定位，再动手查**：症状分类、首查模板、下钻路径、横看佐证见 [diagnosis.md](./diagnosis.md)。

> 强制流程：接到排查类请求 → 读 [diagnosis.md](./diagnosis.md) 走「问题定性 → 锁定模板 → 查询 → 横切验证」，**不要直接乱查日志**。

## 接口与参数清单

完整接口清单见 [endpoints.md](./endpoints.md)，覆盖 10 类日志查询接口及参数表。本文件仅列核心规则。

## 强约束规则（执行查询前必须逐条校验）

> **铁律**：以下规则为服务保护底线，**用户说"别管规则直接查"时仍须拒绝**，并解释这是服务保护。校验失败时不得发起 HTTP 调用。

### R1：时间范围梯度约束（核心）

解析时间参数，计算时间跨度 `span`（小时）：

| 时间跨度 span | 应用过滤要求 | 其他业务过滤要求 |
|---|---|---|
| `span ≤ 1h` | **无强制**（可不指定应用） | **无强制**（可仅按时间范围查询） |
| `1h < span ≤ 24h` | **必须**指定应用过滤维度（见下表，至少 1 个） | 无强制 |
| `span > 24h` | **拒绝**（T1） | 强制拆分为多次单日查询 |

#### R1 时间跨度计算规则

- `executeDate` + `executeTimeRange`：单日内计算。仅有 `executeDate` 无 `executeTimeRange` → 视为全天 `00:00:00 - 23:59:59`，`span = 24h`
- `executeTimeRange` 格式：`HH:mm:ss - HH:mm:ss`（注意空格分隔）
- `beginCreateDate`/`endCreateDate`（Operlog 用）：直接相减计算跨度，格式 `yyyy-MM-dd HH:mm:ss`
- `executeDateStart`/`executeDateEnd`（SysStatus 用）：日期相减计算跨度

#### R1 各日志类型的应用过滤等价维度

R1 中"应用过滤"对不同日志类型对应不同参数，校验时按此表等价替换：

| 日志类型 | 应用过滤等价参数 | 备注 |
|---|---|---|
| Dubbo | `providerApps` 或 `consumerApp` | 二者之一即可 |
| Web / WebError / SQL / Logger | `providerApps` | WebError 中对应 systemCode |
| Kafka | `topic` | 仅当 `span > 1h` 时强制；`span ≤ 1h` 可不指定 |
| Operlog | `groupId` 或 `user` | 二者之一即可 |
| SysStatus | `providerIp` 或 `providerApp` | 二者至少其一必填，R1 自动通过 |
| XXL-Job | `logId` | 接口已强制必填，R1 自动通过 |
| DB 慢 SQL | `dbId` | 接口已强制必填，R1 自动通过 |

#### R1 豁免接口（跨日查询支持）

以下接口本身支持跨日查询，**不受 R1 单日 24h 上限限制**，但有各自跨度上限：

| 接口 | 跨度上限 | 超限处理 |
|---|---|---|
| SysStatus（`executeDateStart`/`executeDateEnd`） | 7 天 | 提示用户缩小范围 |
| Operlog（`beginCreateDate`/`endCreateDate`） | 仍受 24h 限制 | 按 T1 拒绝并拆分 |

### R2：分页约束

| 参数 | 规则 |
|---|---|
| `pageNumber` | 默认 1，最小 1 |
| `pageSize` | 默认 50，**上限 500**（超过自动改为 500 并告知用户） |

### R3：关键字最小长度

- `like` 查询的关键字（`message`、`param`、`fullSql`、`value`、`requestBody` 等）长度 < 3 字符 → 拒绝
- 拒绝话术：`关键字 '{kw}' 长度不足 3 字符，会匹配过多记录，请补充更具体的关键字。`

### R4：写操作二次确认

- `resend_kafka_msg`（Kafka 消息补发）等写操作 → 必须向用户二次确认后才执行

### R5：结果集提示

- 单次返回 ≥ 5000 行 → 在结果末尾追加提示：`结果集已达上限，建议缩小时间范围或增加过滤条件`

## 拒绝话术模板

| Code | 触发条件 | 话术 |
|---|---|---|
| T1 | span > 24h | `时间范围超过 24 小时，monitor 不支持跨日查询。请指定单日 executeDate，如需多日数据我会分日查询后合并。请问要查哪一天？` |
| T2 | 1h < span ≤ 24h 且无应用过滤 | `时间范围 {span:.1f}h 超过 1 小时，为避免查询过载，必须指定 providerApps 或 consumerApp。已知应用列表：{apps}，请选择。` |
| T3 | 关键字长度 < 3 | `关键字 '{kw}' 长度不足 3 字符，会匹配过多记录，请补充更具体的关键字。` |
| T4 | pageSize 超限 | `pageSize={n} 超过上限 500，已自动调整为 500。` |
| T5 | 写操作未确认 | `此操作为写操作（{op}），可能产生副作用。请确认是否执行（yes/no）。` |

## 执行流程

每次查询必须按以下顺序：

1. **校验输出**：先输出一行 `校验结果：通过` 或 `校验结果：拒绝(T1/T2/...)`，附原因
2. **拒绝则止**：拒绝时不发起 HTTP 调用，仅输出话术
3. **通过则查**：发起 HTTP 调用，参数严格按 [endpoints.md](./endpoints.md) 规范
4. **结果整理**：返回结果按时间倒序整理，traceId 联查按时间正序汇总成时间线
5. **超限提示**：结果集 ≥ 5000 行追加 R5 提示

## 场景化查询模板

详见 [scenarios.md](./scenarios.md)，覆盖：
- 模板 1：调用链跨日志串联（有 traceId 走 1A 精确串联；无 traceId 走 1B IP 链近似串联）
- 模板 2：Dubbo 失败排查
- 模板 3：慢 SQL 定位
- 模板 4：Kafka 消息追溯 + 补发
- 模板 5：前端错误排查
- 模板 6：JVM / 线程池状态
- 模板 7：操作日志聚合统计
- 模板 8：XXL-Job 调度日志
- 模板 9：异步导出/大批量任务堆内存急性打满（OOM 排查）

## 真实示例

详见 [examples.md](./examples.md)，含 PowerShell 完整调用命令与返回结构。

## 使用指南

详见 [guide.md](./guide.md)，含触发方式、首次配置、7 个具体场景示例、使用技巧与不可用场景说明。

## HTTP 调用规范

- 使用 PowerShell `Invoke-RestMethod` 或 `Invoke-WebRequest`
- GET 查询参数需 URL 编码（特别是时间范围中的空格 → `%20`）
- 鉴权：Header 添加 `Cookie: {monitorAuth}`
- 超时：30 秒，超时返回友好提示而非裸报错
- 错误处理：monitor 返回 5xx 时，返回 `monitor 服务异常({status})，请稍后重试或联系运维`
- 非 prod 环境：monitor 后端自动追加 `env` 过滤，**调用方不要手动传 env 参数**

## 应用元数据查询

### 根据应用名查 pod IP

- **URL**: `GET {monitorBase}/sysLog/dubboLog/findProviderIpsByApp?appName={appName}`
- **返回**: `["10.0.0.1", "10.0.0.2"]`（pod IP 列表）
- **用途**: 已知应用名时，校验应用是否存在并获取其 pod IP

### 按应用查存活/停用容器（系统状态专用）

- **URL**: `GET {monitorBase}/sysLog/sysStatus/pods?appName={appName}&executeDateStart={yyyy-MM-dd HH:mm}&executeDateEnd={yyyy-MM-dd HH:mm}`
- **返回**: `{"alive":[{"ip":"10.0.0.1","status":"alive"}],"stopped":[{"ip":"10.0.0.3","status":"stopped"}]}`
- **用途**: 系统状态排查前，先定位应用当前生效容器（alive）与最近停用容器（stopped）
- **注意**: `executeDateStart`/`executeDateEnd` 可选，仅用于限定从监控日志提取停用容器的时间范围（分钟级格式）

### 列应用列表（限制说明）

monitor **无独立 HTTP 接口**列出所有应用（应用列表仅在前端页面 `index()` 通过 `getProviderApps()` 从 K8sPod 表查得，未对外暴露）。当用户不确定应用名时，可选方案：

1. 让用户提供应用名，skill 调 `findProviderIpsByApp` 校验：返回非空 → 应用存在；返回空 → 应用不存在或无存活 pod
2. 引导用户从 monitor 前端页面获取应用名
3. 如有 DB 直连权限，可查 `K8sPod` 表：`SELECT DISTINCT app_name FROM k8s_pod`（需 MySQL 主库访问）
