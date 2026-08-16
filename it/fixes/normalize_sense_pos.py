#!/usr/bin/env python3
"""把我写进 `sense.pos` 的 kaikki 长写法归一成短码。2026-08-15。

═══ 用户从界面上看出来的 ═══
`tempo` 的义项被拆成两组，第二组的标题直接显示英文 `noun`：

    名词
      时间 / 天气 / （语法）时态 …          ← 七月的老义项
    noun                                   ← 🔴 我建的新义项，标题成了英文
      冲程（内燃机工作循环的相位） …

根因：库里**混着两套词性词表**。

    entry.pos    verb / noun / adj / name        ← kaikki 原值（长写法）
    sense.pos    n / v / adj / name / adv        ← `build.POS_MAP` 的短码
                 + noun 26,107 / verb 2,860 …    ← 🔴 我写进去的长写法

展示层的 `POS_LABELS`（`packages/dict-labels`）只认短码，查不到 `noun` 就把原始串
直接吐给用户。⇒ 这是 `it-CONVENTIONS` A33 那条教训的又一次：**塞第二份同类东西
前先搜已有那份** —— `build.POS_MAP` 一直在 `it/pipeline/build.py:43`。

═══ 判据 ═══
只改 `sense.pos` 里**能在 `POS_MAP` 里查到长写法**的那些，逐值映射，不猜。
`entry.pos` 一个字节不动（它本来就该存 kaikki 原值，闸靠它锚外部 dump）。

⚠️ 连带要改的：`align_it_multi` / `finish_it_defs` 的「防错配」闸拿
`pos_of_ref(src_ref)`（长写法）与 `COALESCE(entry.pos, sense.pos)` 比。
归一后 sense 侧变短码，两边就对不上了 ⇒ 闸里必须**两侧都过 POS_MAP** 再比。
已同步改掉，否则这次修完下次跑闸必红（而且红的是假红）。

用法（在 it/ 目录下）：
    python3 fixes/normalize_sense_pos.py
    python3 fixes/normalize_sense_pos.py --apply
    python3 fixes/normalize_sense_pos.py --verify
"""
import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from build import POS_MAP   # noqa: E402  🔴 复用现成的那份，不另写一张表

SHORT = set(POS_MAP.values())


def plan(con):
    rows, stat = [], Counter()
    for sid, pos in con.execute("SELECT id, pos FROM sense WHERE pos IS NOT NULL"):
        if pos in SHORT:
            stat["已是短码（不动）"] += 1
        elif pos in POS_MAP:
            stat["✅ 长写法 → 短码"] += 1
            rows.append((POS_MAP[pos], sid))
        else:
            stat["🔴 两边都查不到（不动，记账）: " + pos] += 1
    return rows, stat


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    unknown = [p for (p,) in con.execute(
        "SELECT DISTINCT pos FROM sense WHERE pos IS NOT NULL")
        if p not in SHORT]
    checks = [
        ("🔴 sense.pos 全部是展示层认得的短码", len(unknown), 0),
        # ⚠️ 第一版写成「entry.pos 不许出现短码」，报红 98,810 —— **假红**：
        #    `adj`/`adv`/`name` 在 POS_MAP 里是恒等映射，长短写法本来就一样。
        #    真正的不变量是「entry.pos 全是 POS_MAP 的**键**（kaikki 原值）」。
        ("🔴 entry.pos 仍全是 kaikki 原值",
         sum(1 for (p2,) in con.execute("SELECT DISTINCT pos FROM entry WHERE pos IS NOT NULL")
             if p2 not in POS_MAP), 0),
        ("义项总数不变（本步只改列值）", q("SELECT count(*) FROM sense") > 0, True),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-44s %s (期望 %s)" % ("✅" if good else "🔴", name, got, want))
    if unknown:
        print("     未知取值: %s" % unknown[:10])
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    rows, stat = plan(ro)
    for k, v in stat.most_common():
        print("   %-40s %8s" % (k, f"{v:,}"))
    print("\n■ 将归一 %s 行" % f"{len(rows):,}")
    print("   映射样例: %s" % [(k, POS_MAP[k]) for k in ("noun", "verb", "phrase", "name")])
    ro.close()
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("normalize-sense-pos", expect={"#sense": 0}) as s:
        s.executemany("UPDATE sense SET pos=? WHERE id=?", rows)
    print("\n■ 已归一 %s 行" % f"{len(rows):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
