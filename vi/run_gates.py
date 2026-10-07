#!/usr/bin/env python3
"""跑欠着的闸（vi）—— **每道跑绿才划掉自己那一笔**。2026-09-28。

机制来自 ko 的 K31。关键在最后一步：**划账的动作只由「闸真的退出码 0」触发，
不由人声称**。`[[lesson-must-become-mechanism]]`：
「存在／有入口／覆盖这门语言／**真被跑**」是四道独立关卡，这个文件守第二关和第四关。

═══ 🔴🔴 2026-10-06 加第五档：**变异**（W19 的结清交付物）═══
W19 账上剩下的那一句是「让『谁逼人跑变异』也成为机制」。
**变异验证是闸的闸** —— 普通档全绿只说明「检查还在」，不说明「检查逮得到东西」。
而 2026-10-05 我把 P12/P13 两条检查整段切掉，普通档报「✅ 全绿」，
**只有 `--mutate` 报了出来**，而它那时不在任何一条自动路上。

⚠️ 变异档**不能默认跑**：它动真库（注入→还原），代价和风险都比普通档大。
   ⇒ 单独一档，而「谁逼人跑」靠 `gates.mutation_debt()`：
     **闸的文件改过了就欠一次变异**（锚的是文件内容的 sha，不是时间）。
   默认跑法会把这笔欠账**印出来并计入退出码** —— 不印的话它又回到「写成文字」那一类。

用法：
    python3 vi/run_gates.py            # 只跑欠着的（并报变异欠账）
    python3 vi/run_gates.py --all      # 全跑一遍（换机器、或想确认现状时）
    python3 vi/run_gates.py --mutate   # 🔴 跑变异（动真库）：只跑欠着的那几道
    python3 vi/run_gates.py --mutate --all   # 跑所有有变异档的闸
    python3 vi/run_gates.py --list     # 只看名单和欠账，不跑
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gates                                              # noqa: E402


def _mutation_tier(argv):
    """🔴 变异档。→ 退出码。"""
    debt = dict(gates.mutation_debt())
    have = [g["name"] for g in gates.GATES if g.get("mutate")]
    todo = have if "--all" in argv else [n for n in have if n in debt]
    print("■ 变异档：%d 道闸有变异档，欠着 %d 道" % (len(have), len(debt)))
    for n, why in sorted(debt.items()):
        print("   · %-24s %s" % (n, why))
    # 🔴 没有变异档的那四道也印出来 —— **空名单不许静默**
    #   （`[[dont-recast-deliverables-as-junk]]`：空结果不是证据）。
    for g in gates.GATES:
        if not g.get("mutate"):
            print("   ⚠️ %-24s 无变异档：%s" % (g["name"], g.get("mutate_why", "")[:60]))
    if not todo:
        print("\n■ 没有欠着的变异 ✓（想全跑一遍用 `--mutate --all`）")
        return 0
    print("\n🔴 要跑 %d 道变异（**动真库**，每道自己注入后还原）：%s"
          % (len(todo), "、".join(todo)))
    fail = [n for n in todo if not gates.run_mutation(n)]
    print("\n═══ 变异小结 ═══")
    print("   跑了 %d 道，红 %d 道" % (len(todo), len(fail)))
    for n in fail:
        print("   🔴 %s" % n)
    left = gates.mutation_debt()
    if not left:
        print("   ✅ 变异欠账已清空")
    else:
        for n, why in left:
            print("   📋 还欠：%-24s %s" % (n, why))
    return 1 if (fail or left) else 0


def main():
    argv = sys.argv[1:]
    bad = gates.self_check()
    print("■ 闸名单自检：%d 道闸" % len(gates.GATES))
    for b in bad:
        print("   🔴 " + b)
    print("   %s" % ("✅ 通过" if not bad else "🔴 %d 个问题" % len(bad)))

    if "--mutate" in argv:
        raise SystemExit(_mutation_tier(argv) or (1 if bad else 0))

    if "--list" in argv:
        for g in gates.GATES:
            dep = "（无数据依赖）" if g["deps"] is None else "、".join(sorted(g["deps"]))
            mut = g.get("mutate") or "（无变异档）"
            print("\n── %s\n   $ %s\n   变异：%s\n   依赖：%s" % (g["name"], g["cmd"], mut, dep))
        gates.announce()
        _announce_mutations()
        raise SystemExit(1 if bad else 0)

    pending = gates.load()
    todo = [g["name"] for g in gates.GATES] if "--all" in argv else sorted(pending)
    if not todo:
        print("\n■ 没有欠跑的闸 ✓（想全跑一遍用 --all）")
        raise SystemExit(1 if (bad or _announce_mutations()) else 0)

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
    # 🔴🔴 变异欠账**也要印在这里**（W19）。只在 `--mutate` 那一档里印的话，
    #    不跑那一档的人永远看不见它 —— 而「看不见」就是 W19 那笔账本身的形状。
    mleft = _announce_mutations()
    raise SystemExit(1 if (fail or bad or mleft) else 0)


def _announce_mutations():
    """→ 欠着的变异道数（并打印）。"""
    debt = gates.mutation_debt()
    if not debt:
        print("   ✅ 变异欠账：0 道（每道有变异档的闸都在当前这版代码上跑绿过）")
        return 0
    print("\n🔴 **变异欠着 %d 道** —— 普通档全绿只说明「检查还在」，"
          "不说明「检查逮得到东西」：" % len(debt))
    for n, why in debt:
        print("   · %-24s %s" % (n, why))
    print("   ⇒ 一条命令：**python3 vi/run_gates.py --mutate**（动真库）")
    return len(debt)


if __name__ == "__main__":
    main()
