# 数据平台排错指南（分享版）— 安装说明

这是「数据平台排错指南」技能的去本地化版本，原作者把本机相关的绝对路径、个人目录、db-cli 安装位置、内部 jar 路径全部抽成了占位符，方便分享给同团队其他人直接安装使用。

## 与原版的区别（已做去本地化）

| 原文（本机专属） | 现改为 |
|----------------|--------|
| `/Users/songbaiyan/Documents/IdeaProjects/s11backend/数据后端项目/数据平台/` | `<数据平台文档根目录>`（首次用问用户） |
| `/Users/songbaiyan/Documents/IdeaProjects/s11front/` | `<前端仓库根目录>` |
| `/Users/songbaiyan/Documents/IdeaProjects` | `<代码仓库根目录>` |
| `~/.workbuddy/skills/db-cli/scripts/dbq` 硬编码路径 | 统称 `dbq` 命令 + 安装 db-cli 提示 |
| 强制"MCP 全部禁用" | 改为"推荐 db-cli，MCP 也可用" |
| venv 绝对路径 | 由 db-cli 托管，无需关心路径 |

**保留未动（组织级基础设施，与具体人无关）**：四环境 RDS 主机地址、库清单、默认只读账号 `db_viewer`、数仓公网地址、项目全景、数仓分层、5 条排查条线等所有领域知识。

## 安装步骤

1. 把本目录（`数据平台排错指南-分享版/`）整体复制到目标机器的：
   `~/.workbuddy/skills/数据平台排错指南/`
   （目录名可保留或改回「数据平台排错指南」，若已存在同名技能则覆盖/改名二选一）
2. 若要用 `dbq` 查库，一并安装 `db-cli` 技能，并在其 `config/connections.yaml` 填入本团队的实例与只读账号。
3. **首次对话时**，按 SKILL.md 顶部「本地配置」一节，向用户确认以下信息并把真实值替换到正文 `<占位符>` 处（或写入本目录 `config.md` 让 AI 自动读取）：
   - 数据平台文档根目录
   - 前端仓库根目录
   - 代码仓库根目录
   - 后端/数仓代码根目录
   - 只读账号/密码（若与默认 `db_viewer` 不同）
   - 加白名单工具（aliyun-tool）是否可用

## 目录结构

```
数据平台排错指南-分享版/
├── SKILL.md                  # 主提示词（已去本地化，含本地配置节）
├── README-安装说明.md         # 本文件
└── references/
    ├── projects.md           # 各项目详细说明（无本地路径，原样保留）
    ├── databases.md          # 数据库连接/DMatrix 机制（jar 路径已占位）
    └── warehouse-layers.md   # 数仓分层/核心表血缘（无本地路径，原样保留）
```
