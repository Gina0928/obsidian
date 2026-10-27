---
name: git-cli
description: 记录内网 GitLab（git.selline.cn / git.myt11.com）的远程代码仓库，通过 git 以只读方式浅克隆指定品牌分支的最新代码，用于分析问题时查看远程源码。支持按品牌分支拉取：雅斯 yas-master、好码特 hmt-master、万客缘 wky-master。当分析问题需要查看远程代码、拉取最新代码、读源码时使用。触发词：看代码、读代码、拉代码、远程代码、git 只读、clone 代码、查源码、拉分支。
agent_created: true
---

# Git Cli

## 概述

本技能用于分析问题时，通过内网 GitLab 以**只读**方式拉取远程代码到本地查看。核心约束：**仅限读，禁止推送/修改远程仓库**。

## GitLab 连接信息

| 项 | 值 |
|----|----|
| GitLab 地址 | https://git.selline.cn/ （主）<br>https://git.myt11.com/ （奇龙 / DCS） |
| 账号 | yu.ai |
| 密码 | **不落盘**——每次拉取前向用户询问 |

> 两个站点使用同一账号 `yu.ai`。若某站点认证失败，先确认该站点是否存在独立账号，再向用户索取。

## 仓库清单

| 仓库名 | 远程地址 | 站点 |
|--------|----------|------|
| scm-scs | https://git.selline.cn/scm/scm-scs.git | selline |
| scm-wms | https://git.selline.cn/scm/scm-wms.git | selline |
| jy-bltoise | https://git.selline.cn/group-jy-pms/jy-bltoise.git | selline |
| cl-wms | https://git.selline.cn/cl-wms/cl-wms.git | selline |
| qiulong | https://git.myt11.com/qiulong/qiulong.git | myt11 |
| jy-dcs | https://git.myt11.com/cl-wms/jy-dcs.git | myt11 |

> 用户登记时给的是 `http://` 地址，按「使用约定 1」一律改写为 `https://` 使用。

## 品牌分支映射

| 品牌 | 分支 |
|------|------|
| 雅斯 | yas-master |
| 好码特 | hmt-master |
| 万客缘 | wky-master |

## 只读拉取流程

本地统一存放于 `D:\workbuddy_file\git-repos\<仓库>-<品牌>`（Windows）。同一「仓库 + 品牌」组合只 clone 一次，后续 pull 更新。

### 1. 首次浅克隆（指定品牌分支）

```bash
# 模板：密码不落盘，执行时向用户索取后临时拼入 https://yu.ai:<密码>@<host>/...
git clone --depth 1 --branch <品牌分支> https://yu.ai@<git.selline.cn|git.myt11.com>/<路径>.git D:/workbuddy_file/git-repos/<仓库>-<品牌>
```

示例（拉雅斯分支的 scm-wms）：

```bash
git clone --depth 1 --branch yas-master https://yu.ai@git.selline.cn/scm/scm-wms.git D:/workbuddy_file/git-repos/scm-wms-yas
```

示例（拉 myt11 的 jy-dcs）：

```bash
git clone --depth 1 --branch yas-master https://yu.ai@git.myt11.com/cl-wms/jy-dcs.git D:/workbuddy_file/git-repos/jy-dcs-yas
```

### 2. 更新到最新

```bash
git -C D:/workbuddy_file/git-repos/scm-wms-yas pull --depth 1
```

### 3. 只读护栏（每个仓库一次性执行）

clone 完成后立即禁用推送地址，从机制上杜绝误 push：

```bash
git -C D:/workbuddy_file/git-repos/scm-wms-yas remote set-url --push origin DISABLED
```

## 快捷脚本（推荐：`scripts/pull_source.py`）

手工拼 clone 命令容易踩坑（http 301 丢认证、分支猜错、凭据留在 `.git/config`），
统一用脚本，它一次做完「https 改写 + 浅克隆 + 去凭据 + 禁推送」：

```bash
PY="C:/Users/yuai/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
S="C:/Users/yuai/.workbuddy/skills/git-cli/scripts/pull_source.py"

$PY "$S" --list                                   # 看仓库清单与品牌分支映射
$PY "$S" --repo scm-wms --brand yas --password <密码>          # 首次克隆
$PY "$S" --repo scm-wms --brand yas --password <密码>          # 已存在则自动 pull 更新
$PY "$S" --repo jy-dcs  --branch yas-master --password <密码>  # 不按品牌、直接指定分支
$PY "$S" --url https://git.myt11.com/cl-wms/jy-dcs.git --branch yas-master --password <密码>
$PY "$S" --repo cl-wms --brand yas --password <密码> --full    # 全量 clone（翻历史提交用，先问用户）
$PY "$S" --repo cl-wms --brand yas --password <密码> --dry-run # 只打印将要执行的命令（密码打码）
```

要点：

- 密码用 `--password` 或环境变量 `GIT_HTTP_PASSWORD` 传入，**不落盘**；脚本回显会把密码打码。
- 目标目录默认 `D:\workbuddy_file\git-repos\<仓库>[-<品牌>]`，可用 `--dest` / `--root` 覆盖。
- clone 成功后脚本自动把 `origin` 改回无凭据地址并 `set-url --push origin DISABLED`，
  避免明文密码留在 `.git/config`。手工 clone 时也必须自己补这两步。
- 已存在的副本默认 `pull --ff-only` 更新；浅克隆历史不连续导致失败时，删目录重新 clone 即可。
- 分支不确定时先 `git ls-remote --heads <url>` 再看，不要猜（myt11 站点尤其）。
- 该脚本被 `prod-issue-triage` / `test-issue-triage` 共用，改动后两个排查技能同步受益。

## 编译拉取的代码（按品牌选 settings）

需要本地编译 / 打包拉取下来的品牌分支代码时，Maven 用 `D:\tools\apache-maven-3.8.1\conf\`
下按品牌区分的 settings，**不要用全局默认 settings**（品牌依赖走各自的 snapshot 仓库）：

| 品牌 | settings | 说明 |
|------|----------|------|
| 雅斯（yas） | `settings-ys.xml` | localRepository `D:/maven_sys/yas`，snapshot `yas-snapshot` |
| 好码特 / 万客缘（hmt / wky） | `settings-testhw.xml` | localRepository `D:/maven-testhw`，snapshot `testhw-snapshot` |

```bash
mvn -s D:/tools/apache-maven-3.8.1/conf/settings-ys.xml clean package
```

要点：Nexus 为内网 `http://maven.selline.cn`，两份 settings 均已用 mirror 放行 http
（Maven 3.8.1 默认禁 http）；品牌映射与上表「品牌分支映射」一一对应，拉哪个品牌分支
就配哪份 settings。

## 使用约定（必读）

1. **必须用 https 直连**：两个站点的仓库地址一律用 `https://git.selline.cn/...` 或 `https://git.myt11.com/...`。用 `http://` 会被 301 重定向到 https，且重定向过程中认证头丢失，导致 `HTTP Basic: Access denied`（401）认证失败。这是踩过的坑，务必 https（用户登记地址时给 http 也照改写）。
2. **密码不落盘**：本技能与工作日志均不记录密码。每次拉取代码前，必须先向用户索取 git 密码，临时拼入 `https://yu.ai:<密码>@<host>/...` 执行，用完即弃，不写入任何文件。
3. **仅限读**：只执行 clone / pull / fetch / log / show / diff / grep 等读操作，禁止 push、禁止 commit 后推送、禁止 force push、禁止对远程做任何写操作。
4. **分支优先**：默认拉取品牌分支（yas-master / hmt-master / wky-master），不拉 master/main。拉取前先确认目标品牌。myt11 上的 qiulong / jy-dcs 若无品牌分支，先 `git ls-remote --heads` 列出远端分支再确认，不要猜。
5. **浅克隆**：默认 `--depth 1` 只看最新代码；如分析历史 bug 需翻旧提交，改为全量 clone 并先与用户确认。
6. **目录约定**：本地路径 `<工作区>/<仓库>-<品牌>`，与真实开发工作区（`D:\cl-wms` 等）隔离。
7. **变更维护**：新增仓库时，在「仓库清单」追加一行并标注所属站点即可。
