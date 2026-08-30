#!/usr/bin/env python3
"""`dbtool.prune_backups` 的测试。2026-08-29 随 pt 阶段 -2 建（拷自 fr，本体语种无关）。

🔴 **为什么每个语种都要有自己的一份**：这个函数会自动删数据，而它按 `DB.stem` 分语种
   glob 自己的备份 —— 换句话说每门语言各跑各的淘汰。没有本语种的行为测试，
   就等于「fr 的测试绿着，pt 的删除逻辑没人验过」。

🔴 它是本仓库里**唯一一个会自动删数据的函数**，写错了没有第二次机会。

测试在临时目录里造假文件，把 `dbtool.paths.BACKUPS` 和 `dbtool.DB` 指过去 ——
**不碰真备份**。每个用例都断言「留了谁、删了谁」，不只断言数量。

═══ 当前契约（2026-08-25）═══
① 同 (tag, 日期) 只留一个：普通留**最新**，keep 留**最早**（真正的 pre-state）
② 普通备份只留最近 `KEEP_PLAIN` 个
③ 总字节封顶 `MAX_BACKUP_BYTES`（**keep 也计入**）：先砍普通的，
   还超就按**稀疏度**抽稀（`_thin`）—— 密集簇的中间点先走，**首尾永不删**

🔴 ③ 的稀疏度淘汰换掉了原来的「条数上限」。旧规则只会按时间从老到新砍，
   而该砍的恰恰是同一天连打的那几个近乎重复的快照 —— 它砍在了最不该砍的地方
   （实测挤掉 `keep-v3-infl@20260822` 这个不可再生的迁移锚点）。
   **下面「稀疏老锚点存活、密集簇被抽稀」那条用例就是为了钉死这个行为。**

用法（在 pt/ 目录下）：
    python3 tests/test_prune_backups.py
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402

MB = 1024 ** 2


def build(d, specs):
    """specs: [(tag, 日期, 时分秒, MB)]，可选第 5 项 `(mtime日期, mtime时分秒)`。

    🔴 mtime **默认等于文件名时间，但第 5 项能把它故意造得不一样** ——
       现实中就是不一样的：`backup()` 走 `shutil.copy2`，把源库的 mtime 一起搬进 .bak，
       所以 .bak 的 mtime 是「库最后一次被写」而不是「备份什么时候打的」，实测最狠差 9 天。
       排序判据必须是**文件名里的时间戳**。
    """
    for spec in specs:
        tag, day, hms, mb = spec[:4]
        mday, mhms = spec[4] if len(spec) > 4 else (day, hms)
        p = d / ("synapse-dict-tst.pre-%s-%s-%s.bak" % (tag, day, hms))
        p.write_bytes(b"\0" * (mb * MB))
        t = time.mktime(time.strptime(mday + mhms, "%Y%m%d%H%M%S"))
        os.utime(p, (t, t))
    return d


def run(specs, keep_plain=None, max_bytes=None):
    """→ (留下的 tag 集合, 留下的**文件数**)

    🔴 文件数不能省：tag 集合会把「同 tag 的多个文件」折成一个，
       断言不到「同天两个快照留了几个」这种形状。
    """
    d = Path(tempfile.mkdtemp())
    build(d, specs)
    old = (dbtool.paths.BACKUPS, dbtool.DB, dbtool.KEEP_PLAIN, dbtool.MAX_BACKUP_BYTES)
    try:
        dbtool.paths.BACKUPS = d
        dbtool.DB = d / "synapse-dict-tst.sqlite"
        if keep_plain is not None:
            dbtool.KEEP_PLAIN = keep_plain
        if max_bytes is not None:
            dbtool.MAX_BACKUP_BYTES = max_bytes
        dbtool.prune_backups(verbose=False)
        files = list(d.glob("*.bak"))
        left = {p.name.split(".pre-")[1].rsplit("-", 2)[0] for p in files}
        return left, len(files)
    finally:
        (dbtool.paths.BACKUPS, dbtool.DB,
         dbtool.KEEP_PLAIN, dbtool.MAX_BACKUP_BYTES) = old
        shutil.rmtree(d)


BIG = 999 * 1024 ** 3      # 字节上限设成"够大"，用来单独测 ①②

CASES = [
    (
        "① 普通：同 tag 同天只留**最新**",
        [("aa", "20260820", "100000", 1), ("aa", "20260820", "110000", 1),
         ("bb", "20260820", "120000", 1)],
        {"max_bytes": BIG}, {"aa", "bb"}, 2,
    ),
    (
        "① 普通：同 tag **不同天**都留",
        [("aa", "20260819", "100000", 1), ("aa", "20260820", "100000", 1)],
        {"max_bytes": BIG}, {"aa"}, 2,
    ),
    (
        # 🔴 2026-08-23 契约：keep 也进规则①，但方向**相反 —— 留最早的**。
        #    里程碑的意义是「操作 X **之前**的状态」；同一天同 tag 跑了三次，
        #    第一个才是真 pre-state，后两个是改到一半的中间态，作为回滚锚点严格更差。
        "① keep：同 tag 同天留**最早**",
        [("keep-x", "20260813", "102957", 1),
         ("keep-x", "20260813", "103112", 1),
         ("keep-x", "20260813", "104500", 1)],
        {"max_bytes": BIG}, {"keep-x"}, 1,
    ),
    (
        "② 普通备份只留最近 KEEP_PLAIN 个",
        [("t%d" % i, "20260820", "1000%02d" % i, 1) for i in range(5)],
        {"keep_plain": 2, "max_bytes": BIG}, {"t3", "t4"}, 2,
    ),
    (
        "② keep 不受 KEEP_PLAIN 约束",
        [("keep-%d" % i, "2026081%d" % i, "100000", 1) for i in range(5)],
        {"keep_plain": 2, "max_bytes": BIG}, {"keep-%d" % i for i in range(5)}, 5,
    ),
    (
        # 🔴 这条是新契约的核心。旧的条数上限会从**最老的**开始砍，正好砍掉稀疏锚点；
        #    稀疏度淘汰砍的是**密集簇的中间点**，老锚点因为没有近邻而存活。
        "🔴 ③ 稀疏度：老锚点存活，当天的密集簇被抽稀",
        [("keep-old", "20260801", "100000", 100)] +
        [("keep-d%d" % i, "20260825", "1000%02d" % i, 100) for i in range(5)],
        {"max_bytes": 350 * MB}, {"keep-old", "keep-d0", "keep-d4"}, 3,
    ),
    (
        "🔴 ③ 首尾永不删（预算小到只够一个也留两个）",
        [("keep-a", "20260801", "100000", 100),
         ("keep-b", "20260810", "100000", 100),
         ("keep-c", "20260820", "100000", 100)],
        {"max_bytes": 1}, {"keep-a", "keep-c"}, 2,
    ),
    (
        "③ keep 计入字节：普通的先被砍光",
        [("keep-a", "20260801", "100000", 100),
         ("keep-b", "20260820", "100000", 100),
         ("p1", "20260825", "100001", 100), ("p2", "20260825", "100002", 100)],
        {"keep_plain": 2, "max_bytes": 200 * MB}, {"keep-a", "keep-b"}, 2,
    ),
    (
        # 🔴 排序按**文件名里的时间戳**，不按 mtime。这里把两个时钟造成**相反**：
        #    文件名越新的 mtime 越旧（真实形状＝某个库封版后 9 天才打的备份）。
        #    按 mtime 排会留下 t0、t1；按文件名排才是对的 t1、t2。
        "🔴 mtime 与文件名时间相反 → 按文件名排",
        [("t0", "20260820", "100000", 1, ("20260820", "180000")),
         ("t1", "20260820", "100001", 1, ("20260820", "140000")),
         ("t2", "20260820", "100002", 1, ("20260820", "100000"))],
        {"keep_plain": 2, "max_bytes": BIG}, {"t1", "t2"}, 2,
    ),
]


def main():
    bad = 0
    for name, specs, kw, want_tags, want_n in CASES:
        left, n = run(specs, **kw)
        ok = left == want_tags and n == want_n
        bad += not ok
        print("   %s %-46s 留下 %d 个 %s" % ("✅" if ok else "🔴", name, n, sorted(left)))
        if not ok:
            print("        期望 %d 个 %s" % (want_n, sorted(want_tags)))
    print("\n   %s" % ("✅ 全部通过" if not bad else "🔴 %d 条不符" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
