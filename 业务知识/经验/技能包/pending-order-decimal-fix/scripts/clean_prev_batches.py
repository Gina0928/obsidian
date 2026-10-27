#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
挂单计件小数修复 —— 产物收敛脚本

规则（来自 SKILL.md Step 7）：每批处理完后，只保留当前批次产物，删除之前的产物。

用法:
  python scripts/clean_prev_batches.py --keep <当前批次目录> [--root <工作根目录>] [--apply]

默认 dry-run：只打印将要删除的内容，不真正删除。加 --apply 才真正删除。

删除范围（精确 allowlist，绝不碰 .workbuddy 与其他无关目录/文件）：
  - 目录名匹配 fix_batch* 或 fix_current，且不是 --keep 本身
  - 工作根目录下独立文件匹配: fix_*.sql / fix_*.manifest.csv / 挂单计件小数修复*.sql

安全边界：
  - 绝不删除 .workbuddy 目录（记忆/配置）。
  - 绝不删除 --keep 指定的当前批次目录及其内容。
  - 不递归删除其它无关目录；仅按上述名单精确处理。
"""
import argparse
import os
import shutil
import sys

PRODUCT_DIR_PREFIXES = ("fix_batch", "fix_current")
PRODUCT_FILE_PATTERNS = (".sql", ".manifest.csv")
PRODUCT_FILE_PREFIXES = ("fix_", "挂单计件小数修复")


def is_product_dir(name):
    return any(name.startswith(p) for p in PRODUCT_DIR_PREFIXES)


def is_product_file(name):
    for pre in PRODUCT_FILE_PREFIXES:
        if name.startswith(pre):
            return name.endswith(PRODUCT_FILE_PATTERNS)
    return False


def main():
    ap = argparse.ArgumentParser(description="挂单计件小数修复 —— 产物收敛（只留当前批次）")
    ap.add_argument("--keep", required=True, help="当前批次目录绝对路径（唯一保留）")
    ap.add_argument("--root", default=None, help="工作根目录（默认取 --keep 的父目录）")
    ap.add_argument("--apply", action="store_true", help="真正删除；默认 dry-run")
    args = ap.parse_args()

    keep = os.path.abspath(args.keep)
    root = os.path.abspath(args.root) if args.root else os.path.dirname(keep)
    if not os.path.isdir(root):
        print(f"[ERR] root 不存在: {root}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isdir(keep):
        print(f"[ERR] keep 不存在: {keep}", file=sys.stderr)
        sys.exit(1)

    targets = []
    for name in sorted(os.listdir(root)):
        full = os.path.abspath(os.path.join(root, name))
        if full == keep:
            continue
        if name == ".workbuddy":
            continue
        if os.path.isdir(full) and is_product_dir(name):
            targets.append(("dir", full))
        elif os.path.isfile(full) and is_product_file(name):
            targets.append(("file", full))

    if not targets:
        print(f"[OK] 无旧产物需清理（仅保留 {keep}）。", file=sys.stderr)
        return

    deleted = 0
    for kind, full in targets:
        if args.apply:
            if kind == "dir":
                shutil.rmtree(full)
            else:
                os.remove(full)
            deleted += 1
            print(f"[DEL] {kind} {full}")
        else:
            print(f"[DRY] would delete {kind} {full}")
    if not args.apply:
        print("\n[Dry-run] 以上为将要删除的内容。加 --apply 真实删除。", file=sys.stderr)
    else:
        print(f"\n[OK] 已删除 {deleted} 项，仅保留 {keep}。", file=sys.stderr)


if __name__ == "__main__":
    main()
