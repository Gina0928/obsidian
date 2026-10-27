#!/usr/bin/env python3
"""只读拉取内网 GitLab 代码到本地（供 cl-wms 系列排查时查看跨项目源码）。

设计要点：
- 只用 https（http 会被 301 且丢认证头 → 401）
- 默认 --depth 1 浅克隆；同一「仓库+分支」只 clone 一次，之后 pull 更新
- 密码只出现在命令行 URL 里，clone 完成后立刻把 origin 改回无凭据地址，
  并把 push 地址设为 DISABLED，从机制上杜绝误 push
- 不做任何 push / commit / 远程写操作
"""

import argparse
import os
import re
import subprocess
import sys

USER = "yu.ai"
DEFAULT_ROOT = "D:/workbuddy_file/git-repos"

REPOS = {
    "scm-scs": "https://git.selline.cn/scm/scm-scs.git",
    "scm-wms": "https://git.selline.cn/scm/scm-wms.git",
    "jy-bltoise": "https://git.selline.cn/group-jy-pms/jy-bltoise.git",
    "cl-wms": "https://git.selline.cn/cl-wms/cl-wms.git",
    "qiulong": "https://git.myt11.com/qiulong/qiulong.git",
    "jy-dcs": "https://git.myt11.com/cl-wms/jy-dcs.git",
}

BRANCHES = {
    "yas": "yas-master",
    "hmt": "hmt-master",
    "wky": "wky-master",
}


def mask(text):
    """把 URL 里的密码打码，避免出现在回显/日志里。"""
    return re.sub(r"(://[^:/@\s]+:)[^@/\s]*@", r"\1****@", text)


def run(cmd, cwd=None):
    print("+ " + mask(" ".join(cmd)))
    env = dict(os.environ)
    # 认证失败时不要让 git 弹交互式密码框卡住，直接失败（密码必须显式传入）
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = ""
    return subprocess.run(cmd, cwd=cwd, env=env)


def auth_url(url, password):
    if not password:
        return url
    return url.replace("https://", "https://%s:%s@" % (USER, password), 1)


def local_path(repo_key, brand, root):
    name = repo_key
    if brand:
        name += "-" + brand
    return os.path.join(root, name).replace("\\", "/")


def main():
    ap = argparse.ArgumentParser(description="只读拉取内网 GitLab 代码")
    ap.add_argument("--repo", help="仓库名（见 REPOS）或完整 URL")
    ap.add_argument("--url", help="完整仓库 URL（--repo 未在清单里时用）")
    ap.add_argument("--brand", default="", choices=["", "yas", "hmt", "wky"],
                    help="品牌：yas/hmt/wky，决定分支与目标目录后缀")
    ap.add_argument("--branch", help="显式指定分支，优先于 --brand")
    ap.add_argument("--password", help="git 密码（也可用环境变量 GIT_HTTP_PASSWORD）")
    ap.add_argument("--dest", help="目标目录，默认 <root>/<repo>-<brand>")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="本地存放根目录")
    ap.add_argument("--depth", type=int, default=1, help="浅克隆深度，默认 1")
    ap.add_argument("--full", action="store_true", help="全量 clone（需翻历史提交时用，先与用户确认）")
    ap.add_argument("--list", action="store_true", help="列出仓库清单与品牌分支映射后退出")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要执行的命令")
    args = ap.parse_args()

    if args.list:
        print("仓库清单：")
        for k, v in REPOS.items():
            print("  %-12s %s" % (k, v))
        print("品牌分支：")
        for k, v in BRANCHES.items():
            print("  %-4s %s" % (k, v))
        return 0

    if not args.repo and not args.url:
        print("需要 --repo <仓库名> 或 --url <完整地址>（--list 看清单）", file=sys.stderr)
        return 3

    raw = args.url or REPOS.get(args.repo)
    if not raw:
        print("未知仓库：%s（用 --list 看清单，或改用 --url 传完整地址）" % args.repo, file=sys.stderr)
        return 3

    url = raw.replace("http://", "https://") if raw.startswith("http://") else raw
    if not url.startswith("https://"):
        print("仓库地址必须是 https（http 会被 301 且丢认证头导致 401）：%s" % url, file=sys.stderr)
        return 3

    repo_key = args.repo or url.rstrip("/").split("/")[-1].replace(".git", "")
    branch = args.branch or BRANCHES.get(args.brand, "")
    dest = args.dest or local_path(repo_key, args.brand, args.root)

    password = args.password or os.environ.get("GIT_HTTP_PASSWORD", "")

    if os.path.isdir(os.path.join(dest, ".git")):
        if not branch:
            print("已存在副本，但无法判断分支（用 --branch 或 --brand 指定）", file=sys.stderr)
            return 3
        cmd = ["git", "-C", dest, "pull", "--ff-only", auth_url(url, password), branch]
        if not args.full:
            cmd.insert(4, "--depth")
            cmd.insert(5, str(args.depth))
        if args.dry_run:
            run(["echo"] + cmd)
            return 0
        r = run(cmd)
        if r.returncode != 0:
            print("更新失败（浅克隆历史不连续时常见）。删除 %s 后重新 clone 即可。" % dest, file=sys.stderr)
            return r.returncode
        print("READY: %s" % dest)
        return 0

    if not branch:
        print("未知分支：用 --brand yas|hmt|wky 或 --branch <分支名>；"
              "myt11 站点建议先 git ls-remote --heads <url> 确认分支，不要猜", file=sys.stderr)
        return 3

    cmd = ["git", "clone", "--branch", branch]
    if not args.full:
        cmd += ["--depth", str(args.depth)]
    cmd += [auth_url(url, password), dest]

    if not password:
        print("未提供 git 密码：用 --password <密码> 或设置环境变量 GIT_HTTP_PASSWORD。"
              "密码不落盘，用完即弃。", file=sys.stderr)

    if args.dry_run:
        print("DRY-RUN: " + mask(" ".join(cmd)))
        return 0

    r = run(cmd)
    if r.returncode != 0:
        return r.returncode

    # 护栏：去掉 URL 里的凭据 + 禁用推送
    run(["git", "-C", dest, "remote", "set-url", "origin", url])
    run(["git", "-C", dest, "remote", "set-url", "--push", "origin", "DISABLED"])
    print("READY: %s" % dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
