#!/usr/bin/env python3
"""外审第二轮逮到的、能确定性全量核的两族。2026-08-30。

═══ 第二轮怎么跑的 ═══
用户问「pt 是不是也得到了两家的肯定」——**没有**。第一轮外审的 prompt 第一句就是
「找出其中错的地方」、末句是「没问题的不用列出来」，所以四份回来的全是**错误清单**，
**没有一句是"这部词典可以了"**。而且第一轮之后我又改了七族（50 万条音标移位、
22 万条时态标签、3,904 条词性…），送审的那份材料**已经不是现在这份**。
⇒ 拿**修完之后**的渲染成品重跑一轮，59 个词条（按七族分层取样 ＋ **混进第一轮我判"外审说错了"的 16 个词，不做标记**），
  prompt 与第一轮**逐字相同**（同一把尺子才能比），两版 × 两家。

⭐ **结果最重要的一条：这一轮四份报告没有一条指向我这次改的七族。**
   它们挑出的音标问题全在**辅音与词尾元音**（`casa /ˈkasɐ/` 该 `/ˈkazɐ/`、
   `livro /ˈlibɾu/` 该 `/ˈlivɾu/`），**没有一条是重音符位置** —— 而重音符正是我动了
   50 万行的地方。这是弱证据，但方向是对的。

═══ 族 L：例句的「中文」栏里一个汉字都没有 ═══
外审点了 `cavalo`「例句译文是英文不是中文」。全量扫得 88 条：

    model:example  65   跑批时模型直接回了英文（5d 的控制表量到过 0.05%，在阈值下没拦）
    zh-edition     23   源头把英文译文标成了中文

⇒ 删掉这些 gloss —— **它们不是中文**，留着就是在中文栏里印英文。
   ⚠️ 删的是译文行不是例句行，例句本身留着（下一轮补中文时会重新进池子）。

═══ 族 M：`Rio Grande do Norte` 的中文丢了「北」 ═══
外审四份里三份点了 `Carnaúba dos Dantas → 巴西里约格兰德州城市`。
`Rio Grande do Norte` = **北**里奥格兰德州，丢了「北」就与 `Rio Grande do Sul`
（南里奥格兰德州）混掉。全量扫（判据收窄成「释义在说**某州的市镇/城市**」，
不是"州名出现在文本里"——后者会误圈语域标注 `(Uso: informal; Rio Grande do Sul)`）：

    北里奥格兰德  69   ✅ 对
    里约格兰德     5   🔴 丢了「北」
    北大河         2   🟡 另一种译法，不算错但不一致

⇒ 5 条补「北」；2 条归一到多数写法。**只动这一个州** —— 其余州的译名不一致
  （`阿拉戈斯 43 / 阿拉戈阿斯 3`）是 C22 那族，成因不同（音译取舍），另议。

用法（在 pt/ 目录下）：
    python3 fixes/fix_review_round2.py
    python3 fixes/fix_review_round2.py --apply
"""
import argparse
import collections
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

HAN = dbtool.has_han
# 判据按含义：释义在说「某州的市镇/城市」⇒ 州名是**指称对象**，不是语域标注
STATE_REF = re.compile(
    r"(?:munic[íi]pio|cidade|vila|distrito)\s+brasileir[oa]?\s+d[eo]\s+estado\s+d[eo]\s+(.+?)\s*$",
    re.I)
WRONG_RGN = re.compile(r"(?<!北)里(?:约|奥)格兰德")   # 「里约格兰德」前面没有「北」
ALT_RGN = "北大河"
GOOD_RGN = "北里奥格兰德"


def plan(con):
    # 族L
    l = [(eid, lang, z) for eid, lang, z in con.execute(
        "SELECT g.example_id, g.lang, g.text FROM example_gloss g "
        "  JOIN example e ON e.id=g.example_id "
        " WHERE g.lang='zh' AND COALESCE(e.hidden,0)=0") if not HAN(z)]
    # 族M
    m = []
    for sid, pt, zh in con.execute(
            "SELECT s.id, ss.text, g.text FROM sense s "
            "  JOIN sense_src ss ON ss.sense_id=s.id AND ss.lang='pt' "
            "  JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' "
            " WHERE COALESCE(s.hidden,0)=0"):
        mm = STATE_REF.search(pt.strip())
        if not mm or mm.group(1).strip() != "Rio Grande do Norte":
            continue
        if GOOD_RGN in zh:
            continue
        if ALT_RGN in zh:
            m.append((sid, zh, zh.replace(ALT_RGN, GOOD_RGN), "统一写法"))
        elif WRONG_RGN.search(zh):
            m.append((sid, zh, WRONG_RGN.sub(GOOD_RGN, zh), "补上「北」"))
    return l, m


def main(a):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    l, m = plan(con)
    f = lambda n: format(n, ",")
    print("■ 族L 例句「中文」栏无汉字（删该译文行）：%s" % f(len(l)))
    srcs = collections.Counter(
        r[0] for r in con.execute(
            "SELECT src FROM example_gloss WHERE lang='zh' AND example_id IN (%s)"
            % ",".join("?" * len(l)), [x[0] for x in l])) if l else {}
    print("   按来源：%s" % dict(srcs))
    for eid, _lg, z in l[:4]:
        w = con.execute("SELECT word FROM example WHERE id=?", (eid,)).fetchone()[0]
        print("     %-16s %s" % (w[:16], z[:56]))
    print("\n■ 族M `Rio Grande do Norte` 中文：%s 条要改" % f(len(m)))
    for _sid, old, new, why in m:
        print("     [%s] %s → %s" % (why, old[:34], new[:34]))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("fix-pt-review-r2", expect={"#example_gloss": -len(l)}) as s:
        s.executemany("DELETE FROM example_gloss WHERE example_id=? AND lang=?",
                      [(e, lg) for e, lg, _z in l])
        s.executemany("UPDATE sense_gloss SET text=? WHERE sense_id=? AND lang='zh'",
                      [(new, sid) for sid, _o, new, _w in m])
    print("\n✓ 族L 删 %s ／ 族M 改 %s" % (f(len(l)), f(len(m))))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    sys.exit(main(ap.parse_args()))
