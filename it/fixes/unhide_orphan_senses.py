#!/usr/bin/env python3
"""把「藏起来之后整个词就没内容了」的义项放回来。2026-08-17。

═══ 是什么 ═══
`sense.hidden=1` 有 2,310 条，绝大多数是对的（wiktextract 残渣、占位符、逐字重复的归并）。
但其中 **18 条**藏完之后，**它所在的词一条可见义项都不剩**：

    discapito     zh「损害，损失」   en detriment, damage    → 界面上整条空白
    congestione   zh「充血，拥堵」   en congestion
    essere al verde  zh「身无分文」
    oliva giallastro zh「橄榄黄（RAL 6014）」

中文都是好的。藏它们的判据（意语原文是 `a discapito: a danno…` 这种**子条目**释义）
在"该词还有别的义项"时成立，在"这是它唯一的义项"时就变成了**把整个词抹掉**。

═══ 判据 ═══
① `hidden=1`
② 该义项有非空中文
③ 该义项所在的词头**一条可见义项都没有**

    ⚠️ 三条缺一不可。只看 ①② 会命中 377 条 —— 那 359 条所在的词有别的义项在显示，
       藏起来是对的（多为 [[two-layer-sense-model]] 的「原文逐字相同」归并）。

用法（在 it/ 目录下）：
    python3 fixes/unhide_orphan_senses.py            # 干跑
    python3 fixes/unhide_orphan_senses.py --apply
    python3 fixes/unhide_orphan_senses.py --verify
    python3 fixes/unhide_orphan_senses.py --mutate
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

SQL = """
SELECT s.id, s.word_id, d.word,
       (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='zh' LIMIT 1)
FROM sense s JOIN dict d ON d.id = s.word_id
WHERE s.hidden = 1
  AND EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='zh'
             AND trim(COALESCE(g.text,'')) <> '')
  AND NOT EXISTS(SELECT 1 FROM sense x WHERE x.word_id=s.word_id
                 AND COALESCE(x.hidden,0)=0)
"""


def scan(con):
    return con.execute(SQL).fetchall()


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("🔴 没有「藏完就整词空白」的义项了", len(scan(con)), 0),
        # 🔴 本步只许放出符合三条件的，其余隐藏义项一条都不能动
        ("🔴 仍被隐藏的义项数（只减不增，基线 2,310−18）",
         q("SELECT count(*) FROM sense WHERE hidden=1"), 2292),
        # 🔴 反向：放出来的词现在必须真的有内容可显示
        ("🔴 放出来之后每个词都至少有一条带中文的可见义项",
         q("""SELECT count(*) FROM (SELECT DISTINCT s.word_id FROM sense s
              WHERE COALESCE(s.hidden,0)=0
                AND NOT EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id
                               AND g.lang='zh' AND trim(COALESCE(g.text,''))<>'')
                AND NOT EXISTS(SELECT 1 FROM sense x WHERE x.word_id=s.word_id
                               AND COALESCE(x.hidden,0)=0 AND EXISTS(
                                 SELECT 1 FROM sense_gloss g2 WHERE g2.sense_id=x.id
                                 AND g2.lang='zh' AND trim(COALESCE(g2.text,''))<>'')))
              WHERE word_id IN (SELECT word_id FROM sense WHERE hidden=1)"""), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-46s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    return ok


def mutate(con):
    """判据必须能识破：只看「有中文」会误伤 359 条正当归并。"""
    print("\n═══ 变异验证 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    loose = q("""SELECT count(*) FROM sense s WHERE s.hidden=1
                 AND EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id
                            AND g.lang='zh' AND trim(COALESCE(g.text,''))<>'')""")
    tight = len(scan(con))
    cases = [
        ("🔴 去掉「该词没有可见义项」这条 ⇒ 面从 18 涨到 377", loose > tight * 10, True),
        ("三条件收紧后的面", tight in (0, 18), True),
    ]
    ok = True
    for name, got, want in cases:
        ok &= got == want
        print("   %s %-46s %s（宽 %d / 紧 %d）"
              % ("✅" if got == want else "🔴", name, got, loose, tight))
    print("\n   变异验证 %s" % ("通过" if ok else "🔴 判据有问题"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("apply", "verify", "mutate"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.mutate:
        return 0 if mutate(ro) else 1
    if a.verify:
        return 0 if gate(ro) else 1
    rows = scan(ro)
    print("■ 要放出来的 %d 条" % len(rows))
    for sid, wid, w, zh in rows:
        print("   %-24s %s" % (w[:24], (zh or "")[:30]))
    if not a.apply or not rows:
        ro.close()
        if not a.apply:
            print("\n(未加 --apply，不写库)")
        return 0
    ro.close()
    with dbtool.session("unhide-orphan-senses", expect={"__rows__": 0}) as s:
        s.executemany("UPDATE sense SET hidden=0 WHERE id=?", [(r[0],) for r in rows])
    print("\n■ 已放出 %d 条" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
