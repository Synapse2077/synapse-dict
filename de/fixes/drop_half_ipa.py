#!/usr/bin/env python3
"""收尾单 C42 —— 清掉「半截音标」：源头用连字符标接续的那些行。de，2026-09-05。

═══ 缺陷 ═══
英文版给 `Svalbard` 四条读音：

    ˈsvaːlˌbart    ˈsʋaːlˌbaʁt    -ˌbaɐ̯t    -ˌbaːt

后两条开头的 `-` 意思是「前半截同上、后半截读这样」。它不是一条能独立读的音标，
单独摆到页面上**读者得不到任何信息** —— 与 C40 那批 `Saison → …zoːn` 一模一样，
只是记号从省略号换成了连字符（`FRAMEWORK §一`：**半截是「错」不是「缺」**）。

🔴 **不是 C41 引进来的，是 C41 把它放大了 60 倍。** 阶段 4 的德语版层里本来就有 21 条，
   而 `truncated()` 那道过滤只认省略号 ⇒ 一直放行。C41 补进英文版音标后变成 1,309 条。
   ⇒ 根因修在生成侧：`truncated()` 第四版加上连字符（**判据只许那一份**，本脚本 import 它）。
   ⚠️ 判据必须**按位置**配、不能按包含配 —— `USB-Stick` 词形中间就有连字符，
     按包含判会把 `-ˌʃtɪk` 放行。词缀条目（`-algie` → `-alˈɡiː`）则照样合法。

═══ 为什么是删不是藏 ═══
`pronunciation` 没有 `hidden` 列，而这些行**没有任何下游用途**：它们不是某个词的
「另一读」，是同一读的后半截。留着只会在下次谁写「导出全部读音」时再冒出来。
⚠️ 删之前先证明**没有任何词形因此丢掉唯一的读音**（闸②第一条）—— 实测这 1,309 条
   `is_primary` 全是 0，但**「实测是 0」不能代替断言**（下次重跑排序可能变）。

用法（在 de/ 目录下）：
    python3 -u fixes/drop_half_ipa.py
    python3 -u fixes/drop_half_ipa.py --apply
"""
import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import paths                                            # noqa: E402
from harvest_pronunciation import truncated             # noqa: E402

f = lambda n: format(n, ",")


def bad_rows(con):
    """→ [(id, word, ipa, src)]。**判据只许这一份**，回归闸 D2 import `truncated`。"""
    return [r for r in con.execute(
        "SELECT p.id, d.word, p.ipa, p.src FROM pronunciation p JOIN dict d ON d.id=p.word_id")
        if truncated(r[2] or "", r[1])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n_before = con.execute("SELECT COUNT(*) FROM pronunciation").fetchone()[0]
    rows = bad_rows(con)
    print("■ 半截音标 %s 行" % f(len(rows)))
    for k, v in Counter(r[3] for r in rows).most_common():
        print("   %-14s %8s" % (k, f(v)))

    # 🔴 删之前先算清楚：有没有词形**只**有半截读音。有的话不能直接删。
    ids = {r[0] for r in rows}
    lonely = [w for (w, n, m) in con.execute(
        "SELECT d.word, COUNT(*), SUM(CASE WHEN p.id IN (%s) THEN 1 ELSE 0 END) "
        "  FROM pronunciation p JOIN dict d ON d.id=p.word_id "
        " WHERE p.word_id IN (SELECT word_id FROM pronunciation WHERE id IN (%s)) "
        " GROUP BY d.word" % (",".join("?" * len(ids)), ",".join("?" * len(ids))),
        list(ids) + list(ids)) if n == m]
    print("\n■ 删掉之后会**一条读音都不剩**的词形 %s%s"
          % (f(len(lonely)), ("  ← %s" % lonely[:8]) if lonely else "  ✓"))
    print("■ 其中 is_primary=1 的行 %s"
          % f(con.execute("SELECT COUNT(*) FROM pronunciation WHERE is_primary=1 AND id IN (%s)"
                          % ",".join("?" * len(ids)), list(ids)).fetchone()[0]))
    print("\n■ 样本")
    for _i, w, ipa, src in rows[:12]:
        print("   %-26s %-24s %s" % (w[:26], ipa[:24], src))
    # 受影响的词形，删完之后逐个回查「还有没有读音」——**非抽样**
    words_before = [w for (w,) in con.execute(
        "SELECT DISTINCT word_id FROM pronunciation WHERE id IN (%s)"
        % ",".join("?" * len(ids)), list(ids))]
    con.close()

    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if lonely:
        print("\n🔴 有词形会因此一条读音都不剩 —— **先弄清楚再动**")
        return 1

    import dbtool
    with dbtool.session("keep-v3-c42-half-ipa", expect={"#pronunciation": -len(rows)}) as s:
        s.execute("DELETE FROM pronunciation WHERE id IN (%s)" % ",".join("?" * len(ids)),
                  list(ids))

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = len(bad_rows(con))
    q = lambda x: con.execute(x).fetchone()[0]
    print("\n═══ 闸② ═══")
    checks = [
        ("🔴 还剩半截音标", left, 0),
        # 🔴 **反向闸**：只许删这些行，别的一行都不许动。
        #    ⚠️ 第一版我在这里写了个 `... AND 0` 的条件 —— 它**恒为 0、永远通过**，
        #      正是本仓库通篇在骂的假绿（`[[fix-regression-and-gate]]`）。
        ("🔴 删多了或删少了（应恰好 %s 行）" % f(n_before - len(rows)),
         q("SELECT COUNT(*) FROM pronunciation"), n_before - len(rows)),
        ("🔴 有词形本来有读音、现在一条都不剩",
         len([w for w in words_before
              if not q("SELECT COUNT(*) FROM pronunciation WHERE word_id=%d" % w)]), 0),
        ("🔴 一个 (词形,词性) 没有首选读音了",
         q("SELECT COUNT(*) FROM (SELECT word_id, COALESCE(pos,'') FROM pronunciation "
           "GROUP BY 1,2 HAVING SUM(is_primary)=0)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-40s %10s  期望 %s" % ("✓" if good else "🔴", name, f(got), f(want)))
    con.close()
    print("\n%s" % ("✓ 闸全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
