#!/usr/bin/env python3
"""意语版把**搭配**写成了子义项：搬进 `collocation` 表，不留在义项层。2026-08-15。

═══ 用户从界面上看出来的 ═══
`tempo` 新增的义项里混着这两条：

    反应时间（从刺激到反应的时间间隔）   it: tempo di reazione: lasso temporale che…
    时间感知（主观的时间体验）           it: percezione del tempo: parziale o…

冒号前是 `tempo di reazione` / `percezione del tempo` —— 那是**另一个词项**，
不是 `tempo` 的义项。意大利语维基的编者把搭配写成了子义项，我照单全收了。

═══ 判据：冒号前是不是一个"比词头更长的词项" ═══
全库 89,531 条意语定义里，冒号结构 1,108 条，其中冒号前含词头且多于一词的 543 条。
再按「去掉词头后剩什么」分三形态，只有后两种是伪义项：

    A 词头 + 逗号同位语  166  `giallo ocra, colore RAL – codice RAL: RAL 1024`
                              → 词头本身就是 `giallo ocra`，释义是色号 ⇒ **合法，保留**
    B 词头 + 介词短语     77  `tempo di reazione` / `libretto di circolazione`  ⇒ 伪义项
    C 词头 + 其它实词    300  `vedova bianca` / `specchietto virtuale`          ⇒ 伪义项

⚠️ 判据只做到这三分，不再细化（`PITFALLS` A4：改判据三轮就停手）。
   A 类里若混着伪义项，按上界记账，不追。

═══ 为什么搬而不是删 ═══
它们**不是垃圾，是归错了地方**。`collocation` 表里本来就住着 `aquila reale`（金雕）
这类东西，23,197 条。搬过去等于把内容留住、把位置放对。
`aim-for-perfect-not-cheap`：别用"藏起来"代替把事情做对。

═══ 可逆 ═══
· 义项行不删，置 `hidden=1`
· 意语证据行 `sense_id` 退回 NULL（可重新裁决）
· 新增 `collocation` + `collocation_gloss` 行，`src` 记明来路

用法（在 it/ 目录下）：
    python3 fixes/move_pseudo_senses_to_colloc.py
    python3 fixes/move_pseudo_senses_to_colloc.py --apply
    python3 fixes/move_pseudo_senses_to_colloc.py --verify
"""
import argparse
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from strip_it_placeholder import clean   # noqa: E402

SRC_TAG = "it-edition:pseudo-sense"
COLON = re.compile(r"^\s*([^:：]{2,60})\s*[:：]\s*(.+)$", re.S)
PREP = re.compile(r"^(di|del|dello|della|dei|degli|delle|d’|d'|da|dal|a|al|in|nel|"
                  r"per|con|su|sul|tra|fra)\b", re.I)


def shape(word, head):
    """→ 'A' 同位语（保留） / 'B' 介词短语 / 'C' 其它实词 / None（不是这一族）"""
    if re.fullmatch(re.escape(word), head, re.I):
        return None
    if not re.search(r"\b%s\b" % re.escape(word), head, re.I):
        return None
    if len(head.split()) <= 1:
        return None
    tail = re.sub(r"\b%s\b" % re.escape(word), "", head, flags=re.I).strip()
    if tail.startswith(","):
        return "A"
    if not tail:
        return None
    return "B" if PREP.match(tail) else "C"


def plan(con):
    """→ ([(sense_id, word_id, word, phrase, zh)], 统计)"""
    zh = {sid: t for sid, t in con.execute(
        "SELECT sense_id, text FROM sense_gloss WHERE lang='zh' AND seq=0")}
    rows, stat = [], Counter()
    for wid, w, sid, t in con.execute(
            "SELECT d.id, d.word, g.sense_id, g.text FROM sense_gloss g "
            "JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id "
            "WHERE g.lang='it' AND g.kind='definition' AND COALESCE(s.hidden,0)=0"):
        m = COLON.match(clean(t))
        if not m:
            continue
        head = m.group(1).strip()
        k = shape(w, head)
        if k is None:
            continue
        if k == "A":
            stat["A 词头+逗号同位语（合法，保留）"] += 1
            continue
        stat["🔴 %s 搬进 collocation" % k] += 1
        rows.append((sid, wid, w, head, zh.get(sid) or ""))
    return rows, stat


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    left, _ = plan(con)
    checks = [
        ("🔴 义项层不再有搭配伪义项", len(left), 0),
        ("🔴 搬过去的搭配都带中文",
         q("SELECT count(*) FROM collocation k WHERE k.id IN "
           "(SELECT collocation_id FROM collocation_gloss WHERE src=?) "
           "AND NOT EXISTS(SELECT 1 FROM collocation_gloss g WHERE g.collocation_id=k.id "
           "AND g.lang='zh')", SRC_TAG), 0),
        ("🔴 被搬走的义项已隐藏、且其意语证据退回未裁决",
         q("SELECT count(*) FROM sense_src x JOIN sense s ON s.id=x.sense_id "
           "WHERE x.src='it-edition' AND s.hidden=1"), 0),
        ("🔴 已裁决的证据仍都有出版释义（没留孤儿）",
         q("SELECT count(*) FROM sense_src x WHERE x.src='it-edition' "
           "AND x.sense_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM sense_gloss g "
           "WHERE g.sense_id=x.sense_id AND g.lang='it' AND g.kind='definition')"), 0),
        ("搭配表的 rank 在每个词内不重复",
         q("SELECT count(*) FROM (SELECT word_id, rank FROM collocation "
           "GROUP BY 1,2 HAVING count(*)>1)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %s (期望 %s)" % ("✅" if good else "🔴", name,
                                           f"{got:,}", f"{want:,}"))
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
        print("   %-40s %6s" % (k, f"{v:,}"))
    print("\n■ 将搬走 %s 条" % f"{len(rows):,}")
    for _sid, _wid, w, ph, z in rows[:8]:
        print("   %-16s 搭配「%s」  中文「%s」" % (w[:16], ph[:34], z[:20]))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    mx = dict(ro.execute("SELECT word_id, max(rank) FROM collocation GROUP BY word_id"))
    ro.close()
    k_rows, g_rows, hide, unadj = [], [], [], []
    kid = None
    for sid, wid, _w, phrase, z in rows:
        mx[wid] = mx.get(wid, 0) + 1
        k_rows.append((wid, phrase, mx[wid]))
        hide.append((sid,))
        unadj.append((sid,))
    with dbtool.session("move-pseudo-senses",
                        expect={"#collocation": len(k_rows),
                                "#collocation_gloss": sum(1 for r in rows if r[4])}) as s:
        for (wid, phrase, rank), (sid, _wid, _w, _ph, z) in zip(k_rows, rows):
            cur = s.execute("INSERT INTO collocation (word_id,text,rank) VALUES (?,?,?)",
                            (wid, phrase, rank))
            kid = cur.lastrowid
            if z:
                s.execute("INSERT INTO collocation_gloss (collocation_id,lang,text,src) "
                          "VALUES (?,'zh',?,?)", (kid, z, SRC_TAG))
        s.executemany("UPDATE sense SET hidden=1 WHERE id=?", hide)
        s.executemany("UPDATE sense_src SET sense_id=NULL WHERE sense_id=? "
                      "AND src='it-edition'", unadj)
    print("\n■ 已搬走 %s 条" % f"{len(rows):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
