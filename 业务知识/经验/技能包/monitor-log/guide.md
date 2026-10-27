# Monitor-Log Skill 使用指南

本指南介绍 monitor-log skill 的触发方式、首次配置、具体使用场景与技巧。适用于开发人员在 Trae IDE 中快速查询 monitor 平台日志、排查线上问题。

---

## 一、触发方式

本 skill 已注册到当前 workspace（`.trae/skills/monitor-log/`），**无需手动调用**，在 Trae 对话框中提到日志查询相关关键词即可自动加载。

### 自动触发关键词

| 关键词类型 | 示例 |
|---|---|
| 通用 | 查日志、查 monitor、查监控日志 |
| 链路 | 查 traceId、串联调用链、链路追踪 |
| 具体类型 | 查 dubbo 日志、查 web 日志、查 sql 日志、查 kafka 日志、查 logger 日志 |
| 场景 | 查慢 sql、查系统状态、查操作日志、查 xxl-job 日志 |
| 排查 | 线上问题排查、失败排查、报错分析 |

### 首次使用配置

配置获取按优先级执行（详见 SKILL.md「环境配置」）：

1. 会话内已确认 → 直接复用
2. **全局公共配置匹配**：读取 `C:\Users\liwen\.trae-cn\memory\monitor-config.json`，按用户给定的环境名称匹配 env 键或 aliases（支持中文别名，如「雅斯生产」→ prod-yas）；auth 为空先免登直连
3. 未命中 → 询问用户，并**回写**该 json 文件，实现一次提供、跨项目永久复用

| 变量 | 说明 | 示例 |
|---|---|---|
| `monitorBase` | monitor 部署地址（不含末尾斜杠） | `http://10.128.62.33:8080` |
| `monitorEnv` | 环境标识 | `prod` / `dev` / `test` 等 |
| `monitorAuth` | 鉴权凭证（SSO Cookie，内网免登可省略） | `sessionid=xxx` |

---

## 二、具体场景示例

### 场景 1：调用链串联（有 / 无 traceId）

**对话框输入**：

> 用户 user001 在 2026-08-13 10:00-10:30 下单报"库存不足"，帮忙串一下这次调用的完整链路

**AI 处理流程**：

1. 加载 monitor-log skill
2. 校验：时间跨度 30min ≤ 1h，R1 通过；携带 user 与 uri 业务标识
3. **traceId 缺失/不完善** → 走模板 1B 近似关联：
   - 先从 web_log 查 `user=user001 + uri` 找入口实例 IP
   - 再按该 IP 作为 consumerIp 查它发起的 dubbo，逐层下钻到各 provider
   - 对每个 provider 查 logger（异常）与 sql
4. 沿 IP 链还原拓扑，按时间正序合并，标注关联置信度
5. 收敛根因

**AI 输出示例**：

```
## 调用链时间线（无 traceId，近似串联，置信度：中-高）
关联依据：IP 链(web@10.0.0.1 → order@10.0.0.3 → stock@10.0.0.5) + user=user001 + order_no=ORDER_123

[10:15:23] [Web](高)   POST /api/order/create  user=user001  providerIp=10.0.0.1  耗时=1200ms
[10:15:23] [Dubbo](高) OrderService.create  web→order@10.0.0.3, param.order_no=ORDER_123  耗时=1180ms
[10:15:24] [SQL](中)   order@10.0.0.3  SELECT * FROM t_order WHERE order_no=ORDER_123  耗时=80ms
[10:15:24] [Logger](高) order@10.0.0.3  库存不足: ORDER_123  (StockNotEnoughException)
[10:15:24] [Dubbo](高) StockService.deduct  order@10.0.0.3→stock@10.0.0.5  exception=StockNotEnoughException

## 异常定位
- 根因：StockNotEnoughException（库存不足）
- 链路：web(10.0.0.1) → order(10.0.0.3) → stock(10.0.0.5)
- 置信度说明：IP+user+订单号命中为高，SQL 仅按 IP+时间命中为中，建议复核

## 提示
如用户在别处拿到 traceId，我可切换到精确串联复核；或在 traceId 完善后回查。
```

---

### 场景 2：时间范围超 1h 被拦截 → 引导补全参数

**对话框输入**：

> 查 2026-08-13 09:00-15:00 的 dubbo 失败日志

**AI 处理流程**：

1. 校验：时间跨度 6h > 1h，R1 要求必须指定应用过滤
2. 当前未指定 providerApps/consumerApp → 拒绝(T2)
3. 不发起查询，输出引导话术

**AI 输出**：

```
校验结果：拒绝(T2)
时间范围 6.0h 超过 1 小时，为避免查询过载，必须指定 providerApps 或 consumerApp。
请问要查哪个应用？如不确定，可告诉我应用名，我帮你校验是否存在。
```

**用户补充**：

> 查 order-service 的

**AI 二次处理**：

```
校验结果：通过（已指定 providerApps=order-service）
执行查询：GET /sysLog/dubboLog/list?providerApps=order-service&status=fail&sort=elapsedTime...
```

---

### 场景 3：慢 SQL 定位

**对话框输入**：

> 查 order-service 2026-08-13 全天的慢 SQL，按耗时排序

**AI 处理流程**：

1. 校验：时间跨度 24h（全天），已指定 providerApps=order-service，R1 通过
2. 查询 sql_log，sort=elapsedTime 倒序
3. 整理 Top10 慢 SQL 表格

**AI 输出**：

```
## order-service 慢 SQL Top10（2026-08-13 全天）

| 排名 | 耗时 | SQL 摘要 | 数据库 |
|---|---|---|---|
| 1 | 2350ms | SELECT * FROM t_order WHERE user_id = ? AND status = ? | order_db |
| 2 | 1850ms | UPDATE t_stock SET qty = qty - ? WHERE sku = ? | stock_db |

## 建议
1. SQL #1 缺少 (user_id, status) 复合索引，建议添加
2. 执行计划分析：GET /db/sqlAnalyze/query?sql=...
```

---

### 场景 4：Kafka 消息丢失补发（写操作需确认）

**对话框输入**：

> 帮我补发 topic=order-create, key=ORDER_123 的消息，时间 2026-08-13 10:00-10:30

**AI 处理流程**：

1. 校验：时间 0.5h ≤ 1h，已指定 topic，R1 通过
2. 先查询 kafka_log 追溯消息
3. 列出待补发 logId，请求二次确认（R4）
4. 用户确认后执行 reSendMq

**AI 输出（追溯后请求确认）**：

```
校验结果：需确认(T5)
待补发消息：
- logId=a1b2c3  topic=order-create  key=ORDER_123  时间=10:15:23
- logId=d4e5f6  topic=order-create  key=ORDER_123  时间=10:18:45

此操作为写操作（reSendMq），可能产生副作用（重复消费）。是否执行补发？(yes/no)
```

**用户确认**：

> yes

**AI 执行**：`POST /sysLog/kafkaLog/reSendMq?logIds=a1b2c3,d4e5f6` → 返回补发结果。

---

### 场景 5：前端错误排查

**对话框输入**：

> 查 H5 商城首页报错，时间 2026-08-13 14:00-14:30，用户 user001

**AI 处理流程**：

1. 校验：时间 0.5h ≤ 1h，R1 通过（无需应用过滤）
2. 查询 web_error_log，user=user001
3. 按 url 分组统计，提取 exception 根因

**AI 输出**：

```
## 前端错误排查（user001 @ 2026-08-13 14:00-14:30）

| 错误 URL | 次数 | 根因 | 出错页面 |
|---|---|---|---|
| /api/cart/list | 3 | TypeError: Cannot read property 'price' of undefined | /mall/cart |
| /api/order/preview | 1 | 500 Internal Server Error | /mall/checkout |

## 建议
1. /api/cart/list 返回结构变更，前端取值 price 处需加空值判断
2. /api/order/preview 后端 500，建议查后端 logger 日志定位
```

---

### 场景 6：系统状态诊断（内存泄漏）

**对话框输入**：

> 查 order-service 应用 2026-08-13 10:00-12:00 的堆内存和 CPU，看看是不是内存泄漏

**AI 处理流程**：

1. 校验：providerApp=order-service（二选一满足），时间分钟级 `2026-08-13 10:00` ~ `12:00`，SysStatus 豁免 R1 单日限制，跨度 < 7 天通过
2. 先调 `/sysLog/sysStatus/pods?appName=order-service` 定位容器 IP
3. 逐个 IP 查 sys_status_monitor_log，提取 heapStr / oldGenStr / cpuUsage 趋势
4. 结合指标→问题映射判断（Old Gen 持续上涨 → 内存泄漏）

**AI 输出**：

```
## 系统状态趋势（order-service @ 2026-08-13 10:00-12:00）

容器实例：10.0.0.1(alive)、10.0.0.2(alive)

| 时间 | Heap | Old Gen | CPU | 线程数 | Dubbo 线程 | Druid 连接 |
|---|---|---|---|---|---|---|
| 10:00 | 1.2G/4G | 600M | 15% | 120 | 20/200 | 15/50 |
| 10:20 | 1.8G/4G | 1.1G | 22% | 135 | 25/200 | 18/50 |
| 10:40 | 2.5G/4G | 1.9G ⚠️ | 30% | 150 | 30/200 | 22/50 |
| 11:00 | 3.2G/4G | 2.6G 🔴 | 38% | 165 | 35/200 | 28/50 |
| 11:20 | 3.8G/4G | 3.1G 🔴 | 45% | 180 | 40/200 | 33/50 |

## 异常定位
- Old Gen 从 600M 持续涨到 3.1G，堆用比达 95%（90% 为堆告警线）→ 强烈疑似内存泄漏
- CPU 同步抬升，可能是 Full GC 频繁导致
- 建议：dump 堆分析泄漏对象，查 Logger 日志确认 GC/报错
- 如需 Excel 详细数据，回复"导出 Excel"
```

---

### 场景 7：pageSize 超限自动调整

**对话框输入**：

> 查 dubbo 日志，pageSize=1000，应用 order-service，时间 2026-08-13 10:00-10:30

**AI 处理流程**：

1. 校验：时间 0.5h ≤ 1h，已指定应用，R1 通过
2. pageSize=1000 超过上限 500 → 自动调整为 500（T4）
3. 执行查询

**AI 输出**：

```
校验结果：调整(T4)
pageSize=1000 超过上限 500，已自动调整为 500。
如需更多数据，请翻页查询（pageNumber=2,3,...）。

执行查询中...
```

---

## 三、使用技巧

### 1. 信息越完整，结果越精准

| 必备信息 | 说明 |
|---|---|
| 时间范围 | 精确到小时，避免查全表 |
| 应用名 | 时间 >1h 时强制要求 |
| traceId | 能提高链路精度，尽量提供；缺失时走 IP 链近似串联（模板1B） |
| 业务关键字 | 用户、URI、接口方法等过滤维度 |

### 2. 善用追问

如果第一次查询结果不理想，可以追问：

> 上面这个 traceId 的 logger 日志里有没有 ERROR 级别的？

AI 会基于上下文继续查询，无需重复提供 traceId 和时间。

### 3. 跨场景组合

> 先查 order-service 今天的 dubbo 失败日志，找出超时的 traceId，再串联这些 traceId 的完整链路

AI 会分步执行：先查 dubbo_log(status=fail) → 提取 traceId 列表 → 逐个联查。

### 4. 触发约束时的配合

当 AI 拒绝查询（T1/T2/T3），按提示补充信息即可，不要尝试"绕过规则"——这是服务保护底线，绕不过去。

---

## 四、不可用的场景

| 场景 | 原因 | 替代方案 |
|---|---|---|
| 查应用列表 | monitor 无独立 HTTP 接口 | 从 monitor 前端页面获取应用名 |
| 跨天查询 dubbo/web 日志 | R1 限制单日 | 分日查询后 AI 合并 |
| 不带任何过滤的全文搜索 | R1/R3 拒绝 | 必须指定时间 + 应用或 traceId |
| 修改 monitor 配置 | skill 仅支持查询 + Kafka 补发 | 登录 monitor 后台操作 |

---

## 五、相关文档

| 文档 | 用途 |
|---|---|
| [SKILL.md](./SKILL.md) | skill 主入口：触发条件、强约束规则（R1-R5）、执行流程 |
| [endpoints.md](./endpoints.md) | 10 类日志查询接口完整规范（URL、参数、返回字段） |
| [scenarios.md](./scenarios.md) | 8 个场景化查询模板（含校验要点与结果整理规范） |
| [examples.md](./examples.md) | 8 个真实 PowerShell 调用示例 + 错误处理 + URL 编码要点 |
| [guide.md](./guide.md) | 本文档：使用指南与具体场景演示 |
