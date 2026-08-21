#!/usr/bin/env python3
"""`dbtool.prune_backups` 的测试。2026-08-21 随 fr 阶段 -2 建（从 it 搬来）。

🔴 它是本仓库里**唯一一个会自动删数据的函数**，写错了没有第二次机会。
fr 开工即带保留策略（库现在才 96 MB，但 it 从 155 MB 做到了 1.14 GB）——
策略要在库还小的时候装上，等它长大再装就已经堆了几十 GB。

测试在临时目录里造假文件，把 `dbtool.paths.BACKUPS` 和 `dbtool.DB` 指过去 ——
**不碰真备份**。每个用例都断言「留了谁、删了谁」，不只断言数量。

用法（在 fr/ 目录下）：
    python3 tests/test_prune_backups.py
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402


def build(d, specs):
    """specs: [(tag, 日期, 时分秒, MB)]，可选第 5 项 `(mtime日期, mtime时分秒)`。

    🔴 2026-08-21：mtime **默认等于文件名时间，但第 5 项能把它故意造得不一样** ——
       现实中就是不一样的：`backup()` 走 `shutil.copy2`，把源库的 mtime 一起搬进 .bak，
       所以 .bak 的 mtime 是「库最后一次被写」而不是「备份什么时候打的」，实测最狠差 9 天。
       排序判据必须是**文件名里的时间戳**。
    """
    for spec in specs:
        tag, day, hms, mb = spec[:4]
        mday, mhms = spec[4] if len(spec) > 4 else (day, hms)
        p = d / ("synapse-dict-tst.pre-%s-%s-%s.bak" % (tag, day, hms))
        p.write_bytes(b"\0" * (mb * 1024 * 1024))
        t = time.mktime(time.strptime(mday + mhms, "%Y%m%d%H%M%S"))
        import os
        os.utime(p, (t, t))
    return d


def run(specs, max_backups=None, max_bytes=None):
    """→ (留下的 tag 集合, 留下的**文件数**)

    🔴 2026-08-21 加了文件数：tag 集合会把「同 tag 的多个文件」折成一个，
       断言不到「同天两个里程碑都留着」这种形状（新增用例正是这个形状）。
    """
    d = Path(tempfile.mkdtemp())
    build(d, specs)
    old = (dbtool.paths.BACKUPS, dbtool.DB, dbtool.MAX_BACKUPS, dbtool.MAX_BACKUP_BYTES)
    try:
        dbtool.paths.BACKUPS = d
        dbtool.DB = d / "synapse-dict-tst.sqlite"
        if max_backups is not None:
            dbtool.MAX_BACKUPS = max_backups
        if max_bytes is not None:
            dbtool.MAX_BACKUP_BYTES = max_bytes
        dbtool.prune_backups(verbose=False)
        files = list(d.glob("*.bak"))
        left = {p.name.split(".pre-")[1].rsplit("-", 2)[0] for p in files}
        return left, len(files)
    finally:
        (dbtool.paths.BACKUPS, dbtool.DB,
         dbtool.MAX_BACKUPS, dbtool.MAX_BACKUP_BYTES) = old
        shutil.rmtree(d)


CASES = [
    (
        "① 同 tag 同天只留最新",
        [("aa", "20260820", "100000", 1), ("aa", "20260820", "110000", 1),
         ("bb", "20260820", "120000", 1)],
        {}, {"aa", "bb"}, 2,   # 期望留的 tag / 期望剩的文件数
    ),
    (
        "① 同 tag **不同天**都留",
        [("aa", "20260819", "100000", 1), ("aa", "20260820", "100000", 1)],
        {}, {"aa"}, 2,
    ),
    (
        "② 条数上限",
        [("t%d" % i, "20260820", "1000%02d" % i, 1) for i in range(5)],
        {"max_backups": 3}, {"t2", "t3", "t4"}, 3,
    ),
    (
        "🔴 ③ 总量封顶：条数没超、字节超了也要删",
        [("t%d" % i, "20260820", "1000%02d" % i, 100) for i in range(6)],
        # ⚠️ 上限是**累加**：250 MB ÷ 100 MB = 2 个。我第一版期望写了 3 个（=300 MB），
        #    测试当场报红 —— 是我的算术错，不是代码错（A33 先查期望）。
        {"max_backups": 12, "max_bytes": 250 * 1024 ** 2}, {"t4", "t5"}, 2,
    ),
    (
        "🔴 ③ 至少留 1 个（单个文件就超上限时）",
        [("big", "20260820", "100000", 100)],
        {"max_bytes": 1}, {"big"}, 1,
    ),
    (
        "🔴 keep 豁免字节上限：条数没超时一个都删不掉",
        [("keep-v2", "20260810", "100000", 100), ("keep-v3", "20260811", "100000", 100),
         ("a", "20260820", "100001", 100), ("b", "20260820", "100002", 100),
         ("c", "20260820", "100003", 100)],
        {"max_backups": 12, "max_bytes": 150 * 1024 ** 2},
        # 同上：150 MB 只装得下 1 个 100 MB 的非豁免备份；两个 keep 不计入、照常留
        {"keep-v2", "keep-v3", "c"}, 3,
    ),
    (
        # 🔴 2026-08-21 新契约：keep 不再豁免规则②。
        #    改这条的理由＝当天清盘发现自动淘汰一个都没删，堆积的正是豁免名单本身
        #    （it 7 个备份里 5 个带 keep）。代价是普通备份能挤掉最老的里程碑，
        #    所以函数里对这条路径**必须打印警告**。
        "🔴 keep 计入条数上限：挤超了最老的 keep 会被淘汰",
        [("keep-v2", "20260810", "100000", 1), ("keep-v3", "20260811", "100000", 1),
         ("a", "20260820", "100001", 1), ("b", "20260820", "100002", 1)],
        {"max_backups": 3}, {"keep-v3", "a", "b"}, 3,
    ),
    (
        # keep 仍豁免规则①：同一天同一个 tag 的两个里程碑不当重复删
        #（真实例：8-13 那对相隔 75 秒的 `keep-v3-entry`，只差 13,165 字节但都留着）
        "🔴 keep 豁免规则①：同 tag 同天两个里程碑都留",
        [("keep-v3-entry", "20260813", "102957", 1),
         ("keep-v3-entry", "20260813", "103112", 1),
         ("aa", "20260820", "100000", 1), ("aa", "20260820", "110000", 1)],
        {}, {"keep-v3-entry", "aa"}, 3,
    ),
    (
        # 🔴 2026-08-21：排序按**文件名里的时间戳**，不按 mtime。
        #    这里把两个时钟造成**相反**：文件名越新的 mtime 越旧
        #    （真实形状＝`es.pre-keep-v3-entry-20260820-140712` 的 mtime 是 8-11、差 9 天，
        #      因为那个库 8-11 封版后就没再写过）。
        #    按 mtime 排会留下 t0、t1；按文件名排才是对的 t1、t2。
        "🔴 mtime 与文件名时间相反 → 按文件名排",
        [("t0", "20260820", "100000", 1, ("20260820", "180000")),
         ("t1", "20260820", "100001", 1, ("20260820", "140000")),
         ("t2", "20260820", "100002", 1, ("20260820", "100000"))],
        {"max_backups": 2}, {"t1", "t2"}, 2,
    ),
]


def main():
    bad = 0
    for name, specs, kw, want_tags, want_n in CASES:
        left, n = run(specs, **kw)
        # 🔴 want_n 是**留下的文件数**（不是 tag 数，也不是造了几个）。
        #    改成 `==` 之前是 `len(tag集合) <= want_n`，几乎恒真 —— 等于没检查。
        ok = left == want_tags and n == want_n
        bad += not ok
        print("   %s %-44s 留下 %d 个 %s" % ("✅" if ok else "🔴", name, n, sorted(left)))
        if not ok:
            print("        期望 %d 个 %s" % (want_n, sorted(want_tags)))
    print("\n   %s" % ("✅ 全部通过" if not bad else "🔴 %d 条不符" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
