# Bug 报告模板与知识库沉淀规范

供 bug-investigator skill 的 Phase 7/8 使用：报告模板、md 文件沉淀规范、知识图谱实体/关系设计、企业微信微盘沉淀规范、沉淀执行流程。

## 一、Bug 报告模板

```markdown
# {问题标题：一句话概括问题本质}

## 一、基本信息

| 项 | 内容 |
|---|---|
| 问题标识 | {Jira单号/来源，无则写"口头反馈"} |
| 问题类型 | 功能异常 / 性能问题 / 稳定性偶现（三选一） |
| 环境 | {env，如 prod / test} |
| 发生时间 | {yyyy-MM-dd HH:mm} |
| 排查日期 | {yyyy-MM-dd} |
| 影响范围 | {影响用户量/业务面，未知写"待评估"} |

## 二、现象与影响

{业务现象、用户表现、报错信息原文（脱敏）、影响面}

## 三、排查过程（证据时间线）

| # | 时间 | 来源 | 证据内容 | 结论指向 |
|---|---|---|---|---|
| E1 | 10:15:23 | monitor-web | POST /api/xxx 返回500，耗时1200ms | 指向 H1 |
| E2 | 10:15:24 | DB查询 | t_order 单据状态=已取消但库存未恢复 | 指向 H1 |
| E3 | - | 代码位置 XxxService.java:120 | 事务边界未覆盖库存回滚 | 证实 H1 |

> 来源取值：monitor-dubbo / monitor-web / monitor-weberror / monitor-sql / monitor-slowsql / monitor-logger / monitor-kafka / monitor-sysstatus / monitor-operlog / monitor-xxljob / DB查询 / 代码位置 / 用户提供

## 四、假设验证记录

| 假设 | 验证手段 | 结论 |
|---|---|---|
| H1 {描述} | {工具调用摘要} | 成立（证据 E2、E3） |
| H2 {描述} | {工具调用摘要} | 不成立（被 E1 否定） |

## 五、根因分析

- **根因**：{结论 + 证据链推导：E2 + E3 → 根因}；未收敛时写"未定论"，并列出存活假设与下一步取证建议
- **置信度**：高 / 中 / 低（未定论时填"低"）
- 【需要开发代码确认】项（如有）：
- 历史相似案例（如有）：{BUG-xxx，见 Phase 1 检索}

## 六、修复方案

- **改动点**：{文件/方法 + 变更说明；根因未定论时本节写"待根因确认后补充"}
- **方案说明**：{为什么这样改}
- **潜在风险**：{改动可能引入的风险}
- **影响范围**：{受影响的业务/接口/表}

## 七、验证与回归要点

- **自测要点**：{修复后如何验证}
- **回归范围**：{需要回归的关联功能}

## 八、最终确认结论（用户确认后回填，生成报告时标注"待确认"）

| 项 | 内容 |
|---|---|
| 最终根因 | {用户确认的根因：注明"候选 H{n} 确认"或"用户补充：{用户原文}"} |
| 最终处理方案 | {用户确认的方案：注明"采用建议方案"或"用户补充：{用户原文，如实际修复过程、数据修复结果}"} |
| 确认方式 | 对话确认 |
| 确认日期 | {yyyy-MM-dd} |

> 补充说明：{用户额外补充的遗留风险、后续跟进事项等；无则删除本行}

## 九、检索关键词

`{关键词1}` `{关键词2}` `{关键词3}` ...（接口名/表名/异常类名/业务术语，供未来相似问题检索）
```

## 二、md 文件沉淀规范

- **路径**：`{工程根目录}/docs/bug-reports/BUG-{yyyyMMdd}-{简述}.md`，默认当前工作区；出问题的工程非当前工作区时（如在 A 工程排查 B 工程的 bug），先向用户确认报告归属工程再写入
  - 简述：中文短语，≤20 字，体现问题本质（如 `BUG-20260820-订单取消库存未回滚.md`）
  - 目录不存在时先创建 `docs/bug-reports/`
- **编码**：UTF-8（无 BOM）
- **内容**：完整报告（上述模板）原文写入，不额外追加元信息（元信息由知识图谱承载）

## 三、知识图谱沉淀规范

### 实体设计

| 实体名 | entityType | 说明 |
|---|---|---|
| `BUG-{yyyyMMdd}-{简述}` | BugReport | 一次排查的完整案例，与 md 文件同名 |
| `{应用名}` | Service | 涉及服务（已存在则复用，不存在时创建） |
| `{表名}` | Table | 涉及数据表（已存在则复用，不存在时创建） |

### BugReport 实体 observations 字段（按序）

1. `现象摘要：{一句话}`
2. `问题类型：{功能异常/性能/稳定性}`
3. `环境：{env}`
4. `所属工程：{工程名，与 md 报告归属工程一致}`
5. `根因：{一句话；未定论时写"未定论：{存活假设摘要}"}`
6. `修复方案：{一句话；未定论时写"待定"}`
7. `最终确认：{最终根因一句话 | 最终处理方案一句话（以用户确认为准，用户补充时保留原话要点）}`
8. `检索关键词：{空格分隔的关键词}`
9. `报告文件：{工程名}/docs/bug-reports/BUG-xxx.md`
10. `排查日期：{yyyy-MM-dd}`

### 关系设计（active voice）

| from | relationType | to | 条件 |
|---|---|---|---|
| BugReport 实体 | involves_service | Service 实体 | 排查中确认的涉及服务 |
| BugReport 实体 | involves_table | Table 实体 | 排查中确认的涉及表 |
| BugReport 实体 | similar_to | 历史 BugReport 实体 | Phase 1 检索命中时 |

## 四、沉淀执行流程

1. Phase 6 结束后，按模板生成报告（「最终确认结论」章节填候选根因/建议方案 + 标注"待确认"）并展示给用户
2. 用 AskUserQuestion 确认最终根因与处理方案：给出候选选项，用户可选择候选，也可自由填写补充——实际根因不在候选中、实际处理与建议方案不同（如"数据已修，无需改代码"）时，以用户填写为准
3. 用户确认 → 回填「最终确认结论」章节，更新 md 为终稿 → 依次执行三写沉淀：
   - Write 写入 md 终稿文件
   - search_nodes 查重：确认 BugReport 实体名及涉及的 Service/Table 实体名是否已存在
   - create_entities 仅创建不存在的实体（BugReport + 缺失的 Service/Table，observations 含"最终确认"字段）；已存在的 Service/Table 不重复创建，仅用于建关系
   - 若同名 BugReport 已存在（重复沉淀）：不新建，改用 add_observations 追加"{yyyy-MM-dd} 更新：{变更摘要}"并提示用户
   - create_relations 建立关联
   - wecom-cli 上传 md 终稿到企业微信微盘目标目录（见「五、企业微信微盘沉淀规范」）
4. 输出沉淀结果：md 文件绝对路径 + 图谱实体名列表 + 微盘文件路径
5. 用户要求修正 → 修改报告（md 已写入则同步更新；微盘已上传则重新上传新文件并提示用户清理旧版——微盘不支持覆盖上传）；图谱实体已创建则用 update_entities / add_observations 修正。若修正导致简述变化：md 文件同步重命名（删旧写新）；图谱实体名无法直接改名，删除旧实体（delete_entities）后以新名重建并重建关系
6. 用户明确表示不沉淀 → 仅保留对话中的报告，不落盘

## 五、企业微信微盘沉淀规范

### 目标目录

默认上传路径：`系统资料 / 8质量管理 / Bug知识库`（团队约定）；用户可指定其他微盘目录，以用户指定为准。

### 前置检查（首次上传前执行）

```powershell
# CLI 版本（要求 >= 1.1.0）
& "$env:APPDATA\npm\wecom-cli.cmd" --version
# 未安装时执行：npm install -g @wecom/cli --prefix "$env:APPDATA\npm"
# 授权状态（输出 authorized 才可用）
& "$env:APPDATA\npm\wecom-cli.cmd" auth show --status
# 未授权时执行 & "$env:APPDATA\npm\wecom-cli.cmd" auth init，由用户扫码完成授权
```

### 上传流程

```powershell
$wecom = "$env:APPDATA\npm\wecom-cli.cmd"

# 1. 逐级定位目标文件夹 ID（示例：系统资料 > 8质量管理 > Bug知识库）
& $wecom disk files search --json '{\"keywords\": [\"系统资料\"], \"search_type\": \"space\", \"limit\": 20}'
& $wecom disk files search --json '{\"keywords\": [\"8质量管理\"], \"search_type\": \"folder\", \"space_keywords\": [\"系统资料\"], \"limit\": 20}'
& $wecom disk files search --json '{\"keywords\": [\"Bug知识库\"], \"search_type\": \"folder\", \"space_keywords\": [\"系统资料\"], \"limit\": 20}'

# 2. 上传 md 终稿（folder_id 取上一步 Bug知识库 的 id；file_path 为本地 md 绝对路径）
& $wecom disk files upload --json '{\"folder_id\": \"{folder_id}\", \"file_path\": \"{md绝对路径}\"}'

# 3. 验证（返回的 path 应为 系统资料/8质量管理/Bug知识库/{文件名}）
& $wecom disk files search --json '{\"keywords\": [\"{文件名关键词}\"], \"search_type\": \"file\", \"space_keywords\": [\"系统资料\"], \"limit\": 10}'
```

### 注意事项

- **PowerShell JSON 转义**：`--json` 参数在 PowerShell 5.1 中必须用 `'{\"k\": \"v\"}'` 转义形式传值，路径中的反斜杠无需再转义
- **errcode 850002（机器人无微盘权限）**：CLI 返回的 `help_message` 中含授权链接，将链接原样转交用户，在其企业微信中完成机器人「微盘」权限授权后重试
- **上传返回 `path: "无权限查看文件所在路径"` 不代表失败**：机器人身份写入的文件路径查询受限属正常现象，以上传流程第 3 步 search 验证结果为准
- **目标文件夹不存在**：用 `& $wecom disk folders create --json '{\"folder_id\": \"{父目录ID}\", \"folder_name\": \"{新文件夹名}\"}'` 创建后重试
- **微盘不支持覆盖上传**：报告修正后重传会生成新文件，需提示用户手动清理旧版
- **仅上传终稿**：上传时机必须在用户确认最终根因与处理方案之后，禁止将"待确认"草稿上传到团队知识库

## 六、降级策略

- 无 Knowledge Graph Memory MCP：只执行 md 文件写入 + 微盘上传，并在报告末尾提示"图谱索引未写入（当前环境无知识图谱工具）"
- wecom-cli 不可用（未安装且用户不同意安装 / 未授权 / 机器人无微盘权限且用户未完成授权）：跳过微盘上传，仅 md + 图谱双写，提示用户可手动上传报告到 `系统资料/8质量管理/Bug知识库`
- 当前工作区不可写（只读挂载等）：md 写入失败时，将报告全文输出到对话中，提示用户手动保存
