#!/usr/bin/env python3
"""跑闸。默认只跑**欠着的那几道**；每道跑绿才划掉自己那一笔。K31，2026-09-26。

═══ 为什么划账的动作在这儿、而不在各道闸里 ═══
「绿」的唯一定义是**退出码 0**。如果让每道闸自己划账，就得往九个文件里各塞一行，
而其中三道是 tsx、一道是跨语种共用的（别的语言也在跑它）——
那三道不该知道 ko 的欠账文件存在。
⇒ 划账集中在这里：`gates.run()` 起子进程、看退出码、绿了才 `clear()`。
  **跑不绿的留着**，账的闸 P10 会一直红 —— 这正是 09-25 那两条缺的东西。

跑（在仓库根）：
    python3 -u ko/run_gates.py              # 只跑欠着的
    python3 -u ko/run_gates.py --all        # 全跑（收尾前、或想从零对齐时）
    python3 -u ko/run_gates.py --list       # 只看名单和当前欠账，不跑
    python3 -u ko/run_gates.py --only 外锚闸·义项
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse

import gates


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="全跑，不只跑欠着的")
    ap.add_argument("--list", action="store_true", help="只看，不跑")
    ap.add_argument("--only", action="append", default=[], help="只跑这几道（可重复）")
    a = ap.parse_args()

    # 🔴 **先跑名单自检**。名单本身坏了（闸文件被删、npm 入口不存在、
    #    某张表没人盯着），那么「跑完全绿」是没有意义的
    #    —— `[[expectation-must-be-declared]]`：闸自己的闸要在结论之前。
    bad = gates.self_check()
    if bad:
        print("🔴 闸名单自检未通过 —— **先修名单，再谈跑闸**：")
        for b in bad:
            print("   " + b)
        raise SystemExit(1)
    print("■ 闸名单自检通过 ✓（%d 道闸）" % len(gates.GATES))

    cur = gates.load()
    if a.only:
        todo = list(a.only)
        unknown = [n for n in todo if gates.by_name(n) is None]
        if unknown:
            raise SystemExit("🔴 没有这几道闸：%s\n   名单：%s"
                             % (unknown, [g["name"] for g in gates.GATES]))
    elif a.all:
        todo = [g["name"] for g in gates.GATES]
    else:
        todo = sorted(cur)

    if a.list or not todo:
        print("\n■ 名单（deps ＝ 动了这些表它就过期）")
        for g in gates.GATES:
            dep = "（有意无数据依赖）" if g["deps"] is None else " ".join(sorted(g["deps"]))
            print("   %s %-26s %s" % ("🔴欠" if g["name"] in cur else "  ", g["name"], dep))
        if not todo:
            print("\n■ 没有欠跑的闸 ✓" if not a.list else "")
        return

    print("\n■ 要跑 %d 道：%s" % (len(todo), "、".join(todo)))
    red = [n for n in todo if not gates.run(n)]

    print("\n═══ 结果 ═══")
    print("   跑了 %d 道，绿 %d，红 %d" % (len(todo), len(todo) - len(red), len(red)))
    left = gates.load()
    if red:
        for n in red:
            print("   🔴 %s —— 这一笔**留着**" % n)
    if left:
        gates.announce(left)
        raise SystemExit(1)
    print("   ✅ 欠账已清空")


if __name__ == "__main__":
    main()
