# 源码取证：默认走 git-cli 拉取到固定工作空间

排查需要看代码实现时，统一用 git-cli 技能把代码**只读**拉取到固定取证工作空间，
**不再以本地开发工作区（`D:\cl-wms`）的代码作为取证来源**——本地工作区的分支、
改动与版本和线上部署的可能不一致，拿它硬套生产行为是最容易出错的路径。

## 1. 固定取证工作空间

| 项 | 值 |
|---|---|
| 根目录 | `D:\workbuddy_file\git-repos\` |
| 目录规则 | `<仓库>-<品牌\|分支>`，如 `cl-wms-yas`、`scm-scs-yas` |
| 副本数量 | 同一「仓库 + 分支」只保留一份，重复执行自动 `pull --ff-only` 更新 |
| 隔离要求 | 不与开发工作区 `D:\cl-wms` 混用；不在 `D:\cl-wms` 里 pull / checkout / 改远程地址 |

仓库清单（scm-scs / scm-wms / jy-bltoise / cl-wms / qiulong / jy-dcs）以 git-cli 技能为唯一真源。

## 2. 拉取前先问两件事（不猜）

1. **拉哪个仓库**：用户已明确指定仓库（如「看 scm-wms 的处理逻辑」）直接执行；
   只给了现象没点名仓库时，先按第 5 节的链路判断涉及哪些仓库，列出后与用户确认。
2. **拉哪个分支**：品牌分支有三个候选——雅斯 `yas-master` / 好码特 `hmt-master` /
   万客缘 `wky-master`。用户没说哪个品牌、或可能要看开发分支 / 发版分支时，
   **必须先向用户确认**；映射表外的分支先 `git ls-remote --heads <url>` 列出远端
   分支让用户选，禁止猜分支（myt11 站点尤其）。

> 仓库 + 分支在同一次回复里一并问清，不要拆成多轮。同时向用户索取 git 密码
> （账号 `yu.ai`），密码不落盘，只在命令行里用一次。

## 3. 只读拉取（统一走 git-cli 技能的脚本）

1. 仓库与分支按第 2 节确认；不确定分支先 `git ls-remote --heads <url>`。
2. **向用户索取 git 密码**（账号 `yu.ai`）——密码不落盘，只在命令行里用一次。
3. 执行（脚本位于 git-cli 技能内，两个排查技能共用，改一处两处受益）：

```bash
PY="C:/Users/yuai/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
S="C:/Users/yuai/.workbuddy/skills/git-cli/scripts/pull_source.py"

$PY "$S" --list                                            # 仓库清单 + 品牌分支映射
$PY "$S" --repo scm-scs --brand yas --password <密码>       # 首次 clone
$PY "$S" --repo scm-scs --brand yas --password <密码>       # 已存在则自动 pull 更新
$PY "$S" --repo cl-wms  --brand hmt --password <密码>       # 看其它品牌分支
$PY "$S" --repo cl-wms  --branch <具体分支名> --password <密码>   # 开发/发版分支，分支名由用户确认
$PY "$S" --repo cl-wms  --brand yas --password <密码> --full   # 全量 clone（翻历史提交，先问用户）
$PY "$S" --repo cl-wms  --brand yas --password <密码> --dry-run # 只打印命令，密码自动打码
```

4. 脚本输出 `READY: <路径>`（默认 `D:\workbuddy_file\git-repos\<仓库>[-<品牌>]`），
   在该路径下只读检索（Grep / Glob / Read）。同一「仓库 + 分支」只保留一份，
   重复执行即更新。

手工拼命令时的三条硬规则：**必须 https**（http 被 301 且丢认证头 → 401）、
**clone 后把 origin 改回无凭据地址**、**`remote set-url --push origin DISABLED`**。
脚本已内置这三点。

## 4. 版本核对（判断「副本是不是环境在跑的代码」）

```bash
git -C <取证副本路径> log -1 --format="%H %ad %an %s" --date=iso
```

把副本的 commit 时间与 message，同时间区间内的日志、发版记录对照：

- **生产侧**：生产现象与副本代码对不上时，先怀疑「线上部署版本 ≠ 所拉分支」，
  回到第 2 节换分支重拉，再下结论；禁止用任何本地代码硬套生产行为。
- **测试侧**：测试环境常部署开发分支。复现不成功时先确认「测试环境跑的是哪个
  版本」，再判断是「问题不存在」还是「版本不对导致复现无意义」，不要直接下
  "未复现"结论。

## 5. 跨仓库链路分析

典型链路：scm-scs（单据来源）→ MQ → cl-wms（库存 / 单据）→ jy-dcs。
排查「上游数据与本系统对不上」时，把两端代码都拉下来对照字段与消息体；
证据必须落到具体 `类#方法` 与关键行，不能只描述现象。

## 6. 红线

- 只做 clone / pull / fetch / log / show / diff / grep；**禁止 push、commit、任何远程写操作**。
- 不在拉取的副本里改代码当「修复」——副本只是取证快照，修复方案以建议形式输出。
- 密码不写入任何文件、不写进日志与反馈池（`--topic` 里也不许出现）。
- 副本统一放 `D:\workbuddy_file\git-repos\`，不混进 `D:\cl-wms`。
