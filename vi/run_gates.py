#!/usr/bin/env python3
"""跑欠着的闸（vi）—— **每道跑绿才划掉自己那一笔**。2026-09-28。

机制来自 ko 的 K31。关键在最后一步：**划账的动作只由「闸真的退出码 0」触发，
不由人声称**。`[[lesson-must-become-mechanism]]`：
「存在／有入口／覆盖这门语言／**真被跑**」是四道独立关卡，这个文件守第二关和第四关。

用法：
    python3 vi/run_gates.py            # 只跑欠着的
    python3 vi/run_gates.py --all      # 全跑一遍（换机器、或想确认现状时）
    python3 vi/run_gates.py --list     # 只看名单和欠账，不跑
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gates                                              # noqa: E402


def main():
    argv = sys.argv[1:]
    bad = gates.self_check()
    print("■ 闸名单自检：%d 道闸" % len(gates.GATES))
    for b in bad:
        print("   🔴 " + b)
    print("   %s" % ("✅ 通过" if not bad else "🔴 %d 个问题" % len(bad)))

    if "--list" in argv:
        for g in gates.GATES:
            dep = "（无数据依赖）" if g["deps"] is None else "、".join(sorted(g["deps"]))
            print("\n── %s\n   $ %s\n   依赖：%s" % (g["name"], g["cmd"], dep))
        gates.announce()
        raise SystemExit(1 if bad else 0)

    pending = gates.load()
    todo = [g["name"] for g in gates.GATES] if "--all" in argv else sorted(pending)
    if not todo:
        print("\n■ 没有欠跑的闸 ✓（想全跑一遍用 --all）")
        raise SystemExit(1 if bad else 0)

    print("\n■ 要跑 %d 道：%s" % (len(todo), "、".join(todo)))
    fail = [n for n in todo if not gates.run(n)]
    print("\n═══ 小结 ═══")
    print("   跑了 %d 道，红 %d 道" % (len(todo), len(fail)))
    for n in fail:
        print("   🔴 %s" % n)
    # 🔴 跑红的闸已经由 `gates.run()` 记回欠账 —— **红着而没人记得它红**
    #    正是这套机制要治的病。
    left = gates.announce()
    if not left:
        print("   ✅ 欠账已清空")
    raise SystemExit(1 if (fail or bad) else 0)


if __name__ == "__main__":
    main()
