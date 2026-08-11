#!/usr/bin/env python3
"""`dbtool.prune_backups` 的行为测试。2026-08-11。

═══ 为什么这个函数值得单独一份测试 ═══
它是**本仓库里唯一一处会自动删数据的代码**。写错了没有第二次机会 ——
备份删了就是删了，而它恰恰是"别的东西删错时的救命稻草"。

背景：`dbtool` 每次写库前全量复制（es 库 697 MB），十天攒了 118 个备份、**56 GB**，
其中大量是同一天同一个 tag 隔一两分钟的重复（8-07 光 `translate-examples` 就 7 个）。
2026-08-11 人工清掉 120 个、释放 50.9 GB，并加了这条保留策略防止复发
（台账：`data/work/_shared/backup_prune_20260811.json`）。

═══ 五条必须成立的行为 ═══
① 同 tag 同天多个 → 只留最新一个
② 同 tag **不同天** → 都留（别把里程碑当重复删了）
③ 非豁免备份总数上限 `MAX_BACKUPS`
④ tag 里带 `keep` 的**永不淘汰**，哪怕它是最旧的、哪怕总数远超上限
⑤ 🔴 **不认识的文件名一个都不许动** —— 别的语种的备份、手工放进去的文件

⚠️ ⑤ 是这五条里最重要的。前四条错了是"少留了几个备份"，
   ⑤ 错了是"把别人的东西删了"。

全部在临时目录里跑，把 `paths.BACKUPS` 指到沙箱，**绝不碰真备份**。

用法（在 es/ 目录）：
    python3 tests/test_backup_prune.py
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import os
import pathlib
import tempfile
import time

import dbtool
import paths


def trial(label, build, want, measure, unit):
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        # 🔴 两个都要改：paths 是模块级引用，dbtool 里另有一份绑定
        paths.BACKUPS = d
        dbtool.paths.BACKUPS = d
        stem = dbtool.DB.stem

        def mk(name, age):
            (d / name).write_bytes(b"x" * 1024)
            os.utime(d / name, (time.time() - age, time.time() - age))

        build(stem, mk)
        n0 = len(list(d.glob("*.bak")))
        dbtool.prune_backups(verbose=False)
        left = sorted(p.name for p in d.glob("*.bak"))
        got = measure(left)
        ok = got == want
        print("  %s %-48s 造 %2d → 剩 %2d   %s=%d（期望 %d）"
              % ("✅" if ok else "🔴", label, n0, len(left), unit, got, want))
        return ok


def main():
    print("■ `dbtool.prune_backups` 行为测试（沙箱，不碰真备份）\n")
    ok = True

    # ① 同 tag 同天只留最新。做成**最新的一批**，否则会被规则③顺带淘汰，
    #    测出来的就不是规则①了（第一版就栽在这儿，报了个假红）。
    ok &= trial(
        "同 tag 同天 5 个 → 只留最新 1 个",
        lambda stem, mk: [mk("%s.pre-translate-examples-20260807-14%s.bak" % (stem, t), i)
                          for i, t in enumerate(("2513", "2624", "2736", "2827", "2851"))],
        1, lambda L: sum("translate-examples" in n for n in L), "剩余数")

    # ② 跨天不许合并 —— 同一个 build 脚本在不同日期的备份是不同的时间点
    ok &= trial(
        "同 tag 但不同天 3 个 → 都留",
        lambda stem, mk: [mk("%s.pre-build-sense-layer-2026080%d-120000.bak" % (stem, day), i)
                          for i, day in enumerate((5, 6, 7))],
        3, len, "剩余数")

    # ③ 上限
    ok &= trial(
        "20 个不同 tag → 只留最近 %d 个" % dbtool.MAX_BACKUPS,
        lambda stem, mk: [mk("%s.pre-tag%02d-20260810-1200%02d.bak" % (stem, i, i), i)
                          for i in range(20)],
        dbtool.MAX_BACKUPS, len, "剩余数")

    # ④ keep 豁免必须压过「最旧」和「超上限」两个条件
    ok &= trial(
        "keep 里程碑做成最旧 + 塞 30 个新的 → 仍在",
        lambda stem, mk: ([mk("%s.pre-keep-v2-schema-20260807-105628.bak" % stem, 999999),
                           mk("%s.pre-keep-ipanorm-20260801-160542.bak" % stem, 999999)]
                          + [mk("%s.pre-t%02d-20260810-1200%02d.bak" % (stem, i, i), i)
                             for i in range(30)]),
        2, lambda L: sum("keep" in n for n in L), "keep 剩余")

    # ⑤ 🔴 最重要的一条
    ok &= trial(
        "外来文件名（别的语种 / 手工文件）→ 一个不动",
        lambda stem, mk: [mk("synapse-dict-it.pre-debare-20260727-1421.bak", 5),
                          mk("我手工存的.bak", 5),
                          mk("%s.pre-x-20260810-120000.bak" % stem, 1)],
        3, len, "剩余数")

    print("\n" + ("✅ 五项行为全部正确" if ok else "🔴 有项目不符，别用这个函数"))
    return 0 if ok else 1


if __name__ == "__main__":
    _sys.exit(main())
