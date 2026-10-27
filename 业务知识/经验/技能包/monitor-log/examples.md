# 真实查询示例

完整的 PowerShell 调用示例与返回结构。所有示例假定已配置 `$monitorBase`、`$monitorAuth`、`$monitorEnv` 变量。

## 变量初始化（会话首次）

```powershell
# 用户首次使用时，AI 询问后填入以下变量
$monitorBase = "http://10.128.62.33:8080"   # monitor 部署地址
$monitorAuth = "sessionid=xxx"                # SSO Cookie
$monitorEnv  = "prod"                         # 环境

# 通用请求头
$headers = @{ "Cookie" = $monitorAuth }
```

---

## 示例 1：Dubbo 日志查询（≤ 1h，仅 traceId）

### 用户输入

> 查 traceId=abc123 的 dubbo 调用，时间 2026-08-13 10:00-10:30

### 校验

```
校验结果：通过
- 时间跨度：0.5h ≤ 1h，无需应用过滤（R1 通过）
- traceId 精确匹配，无 like 关键字（R3 跳过）
- pageSize 默认 50（R2 通过）
```

### 调用

```powershell
$uri = "$monitorBase/sysLog/dubboLog/list?traceId=abc123&executeDate=2026-08-13&executeTimeRange=10:00:00%20-%2010:30:00&pageNumber=1&pageSize=50"
$result = Invoke-RestMethod -Uri $uri -Headers $headers -TimeoutSec 30
$result | ConvertTo-Json -Depth 10
```

### 返回结构

```json
{
  "rows": [
    {
      "logId": "a1b2c3d4e5f6",
      "consumerApp": "web-portal",
      "providerApp": "order-service",
      "consumerIp": "10.0.0.1",
      "providerIp": "10.0.0.2",
      "interfaceMethod": "com.jy.order.api.OrderService.createOrder",
      "param": "{\"orderId\":\"ORD123\",\"amount\":99.00}",
      "returnValue": "{\"code\":200}",
      "exception": null,
      "elapsedTime": 156,
      "timeout": false,
      "providerThreadPool": "12/200",
      "traceId": "abc123",
      "createDate": "2026-08-13 10:15:23",
      "env": "prod"
    }
  ],
  "total": 1
}
```

### AI 输出

```
## Dubbo 调用查询结果（traceId: abc123）

| 时间 | 接口方法 | 消费者→提供者 | 耗时 | 状态 |
|---|---|---|---|---|
| 10:15:23 | OrderService.createOrder | web-portal → order-service | 156ms | 成功 |

参数: {"orderId":"ORD123","amount":99.00}
返回: {"code":200}
```

---

## 示例 2：Dubbo 日志查询（> 1h，拒绝 → 引导补充应用）

### 用户输入

> 查 2026-08-13 09:00-15:00 的 dubbo 失败日志

### 校验

```
校验结果：拒绝(T2)
- 时间跨度：6h > 1h，必须指定 providerApps 或 consumerApp
- 当前未指定应用过滤
```

### AI 输出

```
时间范围 6.0h 超过 1 小时，为避免查询过载，必须指定 providerApps 或 consumerApp。

请问要查哪个应用？如不确定，可告诉我应用名，我帮你校验是否存在。
```

### 用户补充

> 查 order-service 的

### 二次校验

```
校验结果：通过
- 时间跨度：6h > 1h，已指定 providerApps=order-service（R1.T2 通过）
- status=fail 精确匹配（R3 跳过）
```

### 调用

```powershell
$uri = "$monitorBase/sysLog/dubboLog/list?providerApps=order-service&executeDate=2026-08-13&executeTimeRange=09:00:00%20-%2015:00:00&status=fail&sort=elapsedTime&pageNumber=1&pageSize=50"
$result = Invoke-RestMethod -Uri $uri -Headers $headers -TimeoutSec 30
```

---

## 示例 3：traceId 跨日志联查

### 用户输入

> 帮我查 traceId=abc123 的完整链路，时间 2026-08-13 10:00-11:00

### 校验

```
校验结果：通过
- 时间跨度：1h ≤ 1h，无需应用过滤
- 5 个查询并行发起
```

### 调用（PS 5.1 兼容顺序执行）

> 注意：PowerShell 5.1 不支持 `ForEach-Object -Parallel`（该特性为 PS 7+ 专有）。以下用顺序执行保证 PS 5.1 兼容；如需并行可用 `Start-Job`，但顺序执行已足够（5 个查询总耗时约 2-5 秒）。

```powershell
$traceId = "abc123"
$date = "2026-08-13"
$range = "10:00:00%20-%2011:00:00"

# 顺序发起 3 个查询（traceId 精确匹配）
$results = @{}
$results.Dubbo  = Invoke-RestMethod -Uri "$monitorBase/sysLog/dubboLog/list?traceId=$traceId&executeDate=$date&executeTimeRange=$range" -Headers $headers -TimeoutSec 30
$results.Web    = Invoke-RestMethod -Uri "$monitorBase/sysLog/webLog/list?traceId=$traceId&executeDate=$date&executeTimeRange=$range" -Headers $headers -TimeoutSec 30
$results.Logger = Invoke-RestMethod -Uri "$monitorBase/sysLog/loggerLog/list?traceId=$traceId&executeDate=$date&executeTimeRange=$range" -Headers $headers -TimeoutSec 30

# sqlLog 和 webErrorLog 需先从 web/dubbo 结果提取应用名/uri，再二次查询
# WebErrorLog 无 traceId 参数，需用 url={uri} 关联（见 scenarios.md 模板1）
# 此处省略二次查询逻辑
```

### AI 输出（时间线整理）

```
## 调用链时间线（traceId: abc123）

[10:15:23] [Web]    POST /api/order/create  user=user001  耗时=1200ms
[10:15:23] [Dubbo]  OrderService.createOrder  web-portal → order-service  耗时=1180ms
[10:15:24] [SQL]    INSERT INTO t_order ...  耗时=850ms  database=order_db
[10:15:24] [Logger] order-service  ERROR  OrderService.createOrder  创建订单失败: 库存不足
[10:15:24] [Dubbo]  StockService.deduct  order-service → stock-service  exception=StockNotEnoughException  耗时=5ms

## 异常定位
- 根因：StockNotEnoughException（库存不足）
- 位置：stock-service @ 10.0.0.5
- 影响：订单创建失败，用户 user001 受影响
- 链路：web-portal → order-service → stock-service（库存校验失败）
```

---

## 示例 4：慢 SQL 定位（按耗时排序）

### 用户输入

> 查 order-service 2026-08-13 全天的慢 SQL，按耗时排序

### 校验

```
校验结果：通过
- 时间跨度：全天 24h > 1h，已指定 providerApps=order-service（R1.T2 通过）
- sort=elapsedTime
```

### 调用

```powershell
$uri = "$monitorBase/sysLog/sqlLog/list?providerApps=order-service&executeDate=2026-08-13&sort=elapsedTime&pageNumber=1&pageSize=50"
$result = Invoke-RestMethod -Uri $uri -Headers $headers -TimeoutSec 30
```

### AI 输出（Top10 慢 SQL 表格）

```
## order-service 慢 SQL Top10（2026-08-13 全天）

| 排名 | 耗时 | SQL 摘要 | 数据库 |
|---|---|---|---|
| 1 | 2350ms | SELECT * FROM t_order WHERE user_id = ? AND status = ? | order_db |
| 2 | 1850ms | UPDATE t_stock SET qty = qty - ? WHERE sku = ? | stock_db |
| ... | | | |

## 建议
1. SQL #1 缺少 (user_id, status) 复合索引，建议添加
2. SQL #2 行锁竞争，建议改为乐观锁
3. 执行计划分析：GET /db/sqlAnalyze/query?sql=...
```

---

## 示例 5：Kafka 消息补发（写操作，需确认）

### 用户输入

> 帮我补发 topic=order-create, key=ORDER_123 的消息，时间 2026-08-13 10:00-10:30

### 步骤 1：追溯消息

```
校验结果：通过
- 时间跨度：0.5h ≤ 1h，已指定 topic（Kafka 日志的应用过滤等价物）
```

```powershell
$uri = "$monitorBase/sysLog/kafkaLog/list?topic=order-create&key=ORDER_123&executeDate=2026-08-13&executeTimeRange=10:00:00%20-%2010:30:00"
$result = Invoke-RestMethod -Uri $uri -Headers $headers -TimeoutSec 30
```

### 步骤 2：列出待补发消息，请求确认

```
校验结果：需确认(T5)
待补发消息：
- logId=a1b2c3  topic=order-create  key=ORDER_123  时间=10:15:23  value={"orderId":"ORD123"}
- logId=d4e5f6  topic=order-create  key=ORDER_123  时间=10:18:45  value={"orderId":"ORD124"}

此操作为写操作（reSendMq），可能产生副作用（重复消费）。是否执行补发？(yes/no)
```

### 步骤 3：用户确认后执行

```powershell
# 用户回复 yes 后执行
$logIds = "a1b2c3,d4e5f6"
$uri = "$monitorBase/sysLog/kafkaLog/reSendMq?logIds=$logIds"
$result = Invoke-RestMethod -Uri $uri -Method POST -Headers $headers -TimeoutSec 30
# 返回：补发完成，成功:2 条，失败:0 条
```

---

## 示例 6：系统状态查询 + Excel 导出

### 用户输入

> 查 order-service 应用 2026-08-13 10:00 到 11:00 的堆内存和 CPU 状态

### 校验

```
校验结果：通过
- providerApp=order-service（providerApp 与 providerIp 二选一，已满足）
- 时间格式分钟级：executeDateStart=2026-08-13 10:00, executeDateEnd=2026-08-13 11:00
- 跨度 1h（sysStatus 支持跨日，不受 R1 单日限制）
```

### 调用

```powershell
# 列表查询（按应用）
$uri = "$monitorBase/sysLog/sysStatus/list?providerApp=order-service&executeDateStart=2026-08-13%2010:00&executeDateEnd=2026-08-13%2011:00"
$result = Invoke-RestMethod -Uri $uri -Headers $headers -TimeoutSec 30

# 先按应用定位容器，再按具体 IP 查（精确到实例）
$podsUri = "$monitorBase/sysLog/sysStatus/pods?appName=order-service&executeDateStart=2026-08-13%2010:00&executeDateEnd=2026-08-13%2011:00"
$pods = Invoke-RestMethod -Uri $podsUri -Headers $headers -TimeoutSec 30
# 从 $pods.alive 取 IP 逐个查询，例：ip = $pods.alive[0].ip

# 导出 Excel（仅支持按 providerIp）
$exportUri = "$monitorBase/sysLog/sysStatus/exportExcel?providerIp=10.0.0.2&executeDateStart=2026-08-13%2010:00&executeDateEnd=2026-08-13%2011:00"
$outputFile = "$env:TEMP\sysStatus_20260813_1000_1100.xlsx"
Invoke-WebRequest -Uri $exportUri -Headers $headers -OutFile $outputFile
Write-Host "Excel 已导出: $outputFile"
```

> 时间参数必须用分钟级 `yyyy-MM-dd HH:mm` 并编码空格为 `%20`（PS 5.1 兼容）。

---

## 示例 7：操作日志统计（Top30 功能）

### 用户输入

> 查 2026-08-13 当天功能使用 Top30

### 校验

```
校验结果：通过
- 时间跨度：1 天 = 24h（1h < span ≤ 24h），按 R1 需应用过滤
- 已指定 groupId=1（Operlog 应用过滤等价维度，R1 通过）
- beginCreateDate/endCreateDate 含空格，URL 中编码为 %20
```

### 调用

```powershell
# URL 中空格编码为 %20（PS 5.1 兼容）
$uri = "$monitorBase/sysLog/operlog/findOperlogStat?groupId=1&beginCreateDate=2026-08-13%2000:00:00&endCreateDate=2026-08-13%2023:59:59"
$result = Invoke-RestMethod -Uri $uri -Headers $headers -TimeoutSec 30
```

---

## 示例 8：pageSize 超限自动调整

### 用户输入

> 查 dubbo 日志，pageSize=1000

### 校验

```
校验结果：调整(T4)
- pageSize=1000 超过上限 500，已自动调整为 500
```

### AI 输出

```
pageSize=1000 超过上限 500，已自动调整为 500。如需更多数据，请翻页查询（pageNumber=2,3,...）。

执行查询：...
```

---

## 错误处理示例

### monitor 返回 5xx

```powershell
try {
    $result = Invoke-RestMethod -Uri $uri -Headers $headers -TimeoutSec 30
} catch [System.Net.WebException] {
    $status = $_.Exception.Response.StatusCode.value__
    if ($status -ge 500) {
        Write-Host "monitor 服务异常($status)，请稍后重试或联系运维"
    } elseif ($status -eq 401 -or $status -eq 403) {
        Write-Host "鉴权失败，请检查 monitorAuth Cookie 是否有效"
    }
}
```

### 查询超时

```powershell
try {
    $result = Invoke-RestMethod -Uri $uri -Headers $headers -TimeoutSec 30
} catch [System.Management.Automation.PipelineStoppedException] {
    Write-Host "查询超时（30s），请缩小时间范围或增加过滤条件后重试"
}
```

---

## URL 编码要点

PowerShell 中 URL 含空格需编码为 `%20`：

```powershell
# 错误：直接拼接含空格的 URL
$uri = "$monitorBase/sysLog/dubboLog/list?executeTimeRange=10:00:00 - 10:30:00"  # 可能解析失败

# 正确：空格编码为 %20
$uri = "$monitorBase/sysLog/dubboLog/list?executeTimeRange=10:00:00%20-%2010:30:00"

# 或使用 UriBuilder 自动编码
$builder = [System.UriBuilder]::new("$monitorBase/sysLog/dubboLog/list")
$builder.Query = "executeTimeRange=10:00:00 - 10:30:00"  # 自动编码
$uri = $builder.ToString()
```

多选应用名 `providerApps` 逗号分隔，无需编码：

```powershell
# 正确：逗号无需编码
$uri = "$monitorBase/sysLog/dubboLog/list?providerApps=app1,app2,app3"
```
