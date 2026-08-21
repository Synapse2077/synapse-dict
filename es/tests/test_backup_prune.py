#!/usr/bin/env python3
"""`dbtool.prune_backups` 的行为测试。2026-08-11。

═══ 为什么这个函数值得单独一份测试 ═══
它是**本仓库里唯一一处会自动删数据的代码**。写错了没有第二次机会 ——
备份删了就是删了，而它恰恰是"别的东西删错时的救命稻草"。

背景：`dbtool` 每次写库前全量复制（es 库 697 MB），十天攒了 118 个备份、**56 GB**，
其中大量是同一天同一个 tag 隔一两分钟的重复（8-07 光 `translate-examples` 就 7 个）。
2026-08-11 人工清掉 120 个、释放 50.9 GB，并加了这条保留策略防止复发
（台账：`data/work/_shared/backup_prune_20260811.json`）。

═══ 十二条必须成立的行为 ═══
① 同 tag 同天多个 → 只留最新一个
② 同 tag **不同天** → 都留（别把里程碑当重复删了）
③ 备份总数上限 `MAX_BACKUPS`
④ tag 里带 `keep` 的不被「最旧」淘汰（总数没超上限时）
④b 🔴 但 keep **计入条数上限**（2026-08-21 改）：塞满了会被挤掉
④c keep 仍豁免规则① —— 同 tag 同天的两个里程碑都留
⑤ 🔴 **不认识的文件名一个都不许动** —— 别的语种的备份、手工放进去的文件

⑥ 🔴 **总量封顶**（2026-08-20 加）：条数没超、字节超了也要删
⑦ 🔴 **至少留 1 个** —— 单个文件就超上限时也不能删光
⑧ `keep` 不计入字节上限
⑨⑩ 🔴 排序判据是**文件名里的时间戳**，不是 mtime（copy2 把源库 mtime 搬进了 .bak）

⚠️ ⑤ 是这几条里最重要的。前四条错了是"少留了几个备份"，
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


def trial(label, build, want, measure, unit, cap=None, size=1024, maxn=None):
    """cap: 临时把 `MAX_BACKUP_BYTES` 调小 —— 规则③要造出「字节超了」的场面，
    而真上限是 3 GB，总不能在测试里写 3 GB 文件。size: 每个假备份多大。
    maxn: 临时把 `MAX_BACKUPS` 调小，用来造规则②的场面。

    ⚠️ `mk(name, age)` 里的 age 只设 **mtime**；2026-08-21 起排序判据是
    **文件名里的时间戳**，两者可以（也应该）对不上 —— 现实中它们就是对不上的。"""
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        # 🔴 两个都要改：paths 是模块级引用，dbtool 里另有一份绑定
        paths.BACKUPS = d
        dbtool.paths.BACKUPS = d
        old_cap, old_n = dbtool.MAX_BACKUP_BYTES, dbtool.MAX_BACKUPS
        if cap is not None:
            dbtool.MAX_BACKUP_BYTES = cap
        if maxn is not None:
            dbtool.MAX_BACKUPS = maxn
        stem = dbtool.DB.stem

        def mk(name, age):
            (d / name).write_bytes(b"x" * size)
            os.utime(d / name, (time.time() - age, time.time() - age))

        build(stem, mk)
        n0 = len(list(d.glob("*.bak")))
        dbtool.prune_backups(verbose=False)
        left = sorted(p.name for p in d.glob("*.bak"))
        got = measure(left)
        ok = got == want
        dbtool.MAX_BACKUP_BYTES, dbtool.MAX_BACKUPS = old_cap, old_n
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

    # ④ keep 豁免必须压过「最旧」这个条件（总数没超上限时）
    ok &= trial(
        "keep 里程碑做成最旧 + 塞 5 个新的 → 仍在",
        lambda stem, mk: ([mk("%s.pre-keep-v2-schema-20260807-105628.bak" % stem, 999999),
                           mk("%s.pre-keep-ipanorm-20260801-160542.bak" % stem, 999999)]
                          + [mk("%s.pre-t%02d-20260810-1200%02d.bak" % (stem, i, i), i)
                             for i in range(5)]),
        2, lambda L: sum("keep" in n for n in L), "keep 剩余")

    # ④b 🔴 2026-08-21 新契约：keep **不再豁免规则②**。
    #     以前这里断言的是「塞 30 个新的、keep 仍在 2 个」。改掉它的理由 ——
    #     当天清盘发现自动淘汰一个都没删，而 backups 已 9.8 GB：
    #     es 9 个备份里 6 个带 keep 全豁免，剩 3 个非豁免的字节数又刚好没到上限，
    #     ⇒ **堆积的不是普通备份，是豁免名单本身**，里程碑只增不减。
    #     ⚠️ 代价就在这条用例里：普通备份能挤掉最老的里程碑。
    #        所以函数在这条路径上必须打印 `⚠️ 淘汰里程碑`，不许静默删。
    ok &= trial(
        "keep 做成最旧 + 塞 30 个新的 → 被条数上限挤掉",
        lambda stem, mk: ([mk("%s.pre-keep-v2-schema-20260807-105628.bak" % stem, 999999),
                           mk("%s.pre-keep-ipanorm-20260801-160542.bak" % stem, 999999)]
                          + [mk("%s.pre-t%02d-20260810-1200%02d.bak" % (stem, i, i), i)
                             for i in range(30)]),
        0, lambda L: sum("keep" in n for n in L), "keep 剩余")

    # ④c keep 仍豁免规则① —— 同一天同一个 tag 的两个里程碑不当重复删。
    #    真实例：it 8-13 那对相隔 75 秒的 `keep-v3-entry`，只差 13,165 字节，都留着。
    ok &= trial(
        "同 tag 同天两个 keep → 都留（豁免规则①）",
        lambda stem, mk: [mk("%s.pre-keep-v3-entry-20260813-102957.bak" % stem, 3),
                          mk("%s.pre-keep-v3-entry-20260813-103112.bak" % stem, 2),
                          mk("%s.pre-x-20260813-120000.bak" % stem, 1)],
        2, lambda L: sum("keep" in n for n in L), "keep 剩余")

    # ⑤ 🔴 最重要的一条
    ok &= trial(
        "外来文件名（别的语种 / 手工文件）→ 一个不动",
        lambda stem, mk: [mk("synapse-dict-it.pre-debare-20260727-1421.bak", 5),
                          mk("我手工存的.bak", 5),
                          mk("%s.pre-x-20260810-120000.bak" % stem, 1)],
        3, len, "剩余数")

    # ⑥ 🔴 规则③（2026-08-20 加）：条数没超、**字节超了**也要删。
    #    上限是**累加**的：500 KB ÷ 200 KB = 2 个。
    #    这条规则存在的理由：一轮收尾跑十几个不同 tag 的脚本，规则①②一个都拦不住，
    #    而库涨到 1 GB/次时 `MAX_BACKUPS=12` 就等于 12 GB。es 当天实测正是这个形状。
    ok &= trial(
        "条数没超但字节超了 → 按总量淘汰",
        lambda stem, mk: [mk("%s.pre-t%d-20260810-1200%02d.bak" % (stem, i, i), 6 - i)
                          for i in range(6)],
        2, len, "剩余数", cap=500 * 1024, size=200 * 1024)

    # ⑦ 🔴 至少留 1 个 —— 单个文件就超上限时也不能删光。
    #    真出事时手里得有一个能回滚的点；这条错了等于「磁盘满时把救命稻草也烧了」。
    ok &= trial(
        "单个文件就超上限 → 仍留 1 个",
        lambda stem, mk: [mk("%s.pre-big-20260810-120000.bak" % stem, 1)],
        1, len, "剩余数", cap=1, size=200 * 1024)

    # ⑧ keep 不计入字节上限（与 ④ 的条数豁免是两回事）
    ok &= trial(
        "keep 不计入字节上限 → 两个 keep 全留",
        lambda stem, mk: ([mk("%s.pre-keep-a-20260801-120000.bak" % stem, 999999),
                           mk("%s.pre-keep-b-20260802-120000.bak" % stem, 999998)]
                          + [mk("%s.pre-t%d-20260810-1200%02d.bak" % (stem, i, i), 5 - i)
                             for i in range(5)]),
        2, lambda L: sum("keep" in n for n in L), "keep 剩余",
        cap=300 * 1024, size=200 * 1024)

    # ⑨ 🔴 2026-08-21：排序判据是**文件名里的时间戳**，不是 mtime。
    #    `backup()` 走 `shutil.copy2`，把**源库的 mtime 一起搬进 .bak** ⇒
    #    .bak 的 mtime 是「这个库最后一次被写」，不是「备份什么时候打的」。
    #    实测最狠 `es.pre-keep-v3-entry-20260820-140712` 的 mtime 是 8-11、**差 9 天**
    #    （es 封版后库没再动过）。用错时钟会把刚打的里程碑排成最老的先删。
    #    这两条用例把两个时钟**故意造成相反**：文件名越新的、mtime 越旧。
    ok &= trial(
        "规则②：mtime 与文件名时间相反 → 按文件名排",
        lambda stem, mk: [mk("%s.pre-t%d-20260810-12000%d.bak" % (stem, i, i), i * 10000)
                          for i in range(3)],
        1, lambda L: int([n.rsplit("-", 1)[-1] for n in L] == ["120001.bak", "120002.bak"]),
        "留下的正是文件名最新的两个", maxn=2)

    ok &= trial(
        "规则①：同 tag 同天留「文件名最新」而非 mtime 最新",
        lambda stem, mk: [mk("%s.pre-dup-20260810-120000.bak" % stem, 0),        # mtime 最新
                          mk("%s.pre-dup-20260810-120500.bak" % stem, 99999)],   # 文件名最新
        1, lambda L: int([n.rsplit("-", 1)[-1] for n in L] == ["120500.bak"]),
        "留下的是 120500")

    print("\n" + ("✅ 十二项行为全部正确" if ok else "🔴 有项目不符，别用这个函数"))
    return 0 if ok else 1


if __name__ == "__main__":
    _sys.exit(main())
