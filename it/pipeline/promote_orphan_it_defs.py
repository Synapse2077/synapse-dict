#!/usr/bin/env python3
"""阶段 3b 补：把「库里有词形、但一条义项都没有」的意语释义提升到出版层。2026-08-13。

═══ 这批是谁 ═══
`intake_it_words.py` 的闸逮到 **3,978 个词形 / 5,161 条意语释义**：词形在 `dict` 里，
但英文版把它们判成了**纯变形**（界面上一条释义都没有），而意语版给了它们**真定义**：

    ricordarsi   tenere a mente qualcuno        ← 自反式动词，es 的 `levantarse` 同族
    affumicato   insaporito con affumicatura…   ← 过去分词作形容词，意语词典的正经词条
    toscana      regione dell'Italia centrale…  ← 地区名
    anellini     tipo di pasta, piccoli anelli… ← 一种意面

这是 `SCHEMA` §9.1「被误判成变形层」的第三个来源（前两个：阶段 2a 的 `alt_of`、
阶段 3b 的收词），而**意语版就是判定它们是真词条的外部证据**。

═══ 安全性 ═══
这些词形当前 `sense` 为 0 ⇒ **没有可错配的对象**，与收词那批同理，风险为零。
⚠️ 但要过 `PTR` 正则：意语版给变形形的"释义"往往还是指针文本
（`create` → "seconda persona plurale dell'indicativo presente di creare"），那些不提升。

用法（在 it/ 目录下）：
    python3 pipeline/promote_orphan_it_defs.py            # 干跑
    python3 pipeline/promote_orphan_it_defs.py --apply
    python3 pipeline/promote_orphan_it_defs.py --verify
"""
import argparse
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from promote_it_gloss import PTR, SRC   # noqa: E402  同一把尺，不另写正则
from strip_it_placeholder import not_a_definition   # noqa: E402  占位符/纯域标签都不是释义


def plan(con):
    rows = defaultdict(list)
    stat = Counter()
    for xid, wid, text, ref in con.execute(
            "SELECT x.id, x.word_id, x.text, x.src_ref FROM sense_src x "
            "WHERE x.src=? AND x.sense_id IS NULL AND NOT EXISTS("
            "SELECT 1 FROM sense s WHERE s.word_id=x.word_id)", (SRC,)):
        if PTR.match(text):
            stat["意语版给的也是指针文本（不提升）"] += 1
            continue
        if not_a_definition(text):
            stat["占位符 definizione mancante（不提升）"] += 1
            continue
        stat["✅ 可提升"] += 1
        rows[wid].append((xid, text, ref))
    return rows, stat


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    checks = [
        # 🔴 判据必须与写入端**共用同一个函数**。第一版在 SQL 里用 NOT LIKE 前缀表
        #    近似复写了 `PTR` 正则，两把尺差出 33 条 —— 闸报的是我的近似，不是数据。
        ("🔴 提升后不存在「有非指针意语释义、却一条义项都没有」的词形",
         sum(1 for (t,) in con.execute(
             "SELECT x.text FROM sense_src x WHERE x.src=? AND x.sense_id IS NULL "
             "AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=x.word_id)", (SRC,))
             if not (PTR.match(t) or not_a_definition(t))), 0),
        ("出版层意语释义 == 已裁决的意语证据",
         q("SELECT count(*) FROM sense_gloss WHERE lang='it' AND kind='definition'")
         - q("SELECT count(*) FROM sense_src WHERE src=? AND sense_id IS NOT NULL", SRC), 0),
        ("每个词形的 rank 连续无空洞",
         q("SELECT count(*) FROM (SELECT word_id FROM sense GROUP BY word_id "
           "HAVING max(rank)<>count(*) OR min(rank)<>1)"), 0),
        ("证据行的 word_id 与它的义项一致",
         q("SELECT count(*) FROM sense_src x JOIN sense s ON s.id=x.sense_id "
           "WHERE x.word_id<>s.word_id"), 0),
        # 🔴 原来写死 205928 —— 违反自己定的 A28（闸里不许写死行数）。换成结构性口径：
        #    本脚本只碰 it-edition 的证据行，所以英文版证据必须**全部仍处于已裁决状态**。
        ("🔴 英文版侧的证据一条都没被退回未裁决",
         q("SELECT count(*) FROM sense_src WHERE src='en-edition' AND sense_id IS NULL"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-50s %s (期望 %s)" % ("✅" if good else "🔴", name,
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
        print("   %-38s %8s" % (k, f"{v:,}"))
    n = sum(len(v) for v in rows.values())
    print("\n■ 将提升 %s 个词形 / %s 条意语释义" % (f"{len(rows):,}", f"{n:,}"))
    if not a.apply:
        print("(未加 --apply，不写库)")
        return 0

    sid = ro.execute("SELECT max(id) FROM sense").fetchone()[0]
    ro.close()
    s_rows, g_rows, link = [], [], []
    for wid in sorted(rows):
        for rank, (xid, text, _ref) in enumerate(rows[wid], start=1):
            sid += 1
            s_rows.append((sid, wid, rank))
            g_rows.append((sid, "it", "definition", 0, text, SRC))
            link.append((sid, xid))

    with dbtool.session("promote-orphan-it",
                        expect={"#sense": len(s_rows), "#sense_gloss": len(g_rows)}) as s:
        s.executemany("INSERT INTO sense (id,word_id,rank) VALUES (?,?,?)", s_rows)
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?,?,?,?,?,?)", g_rows)
        s.executemany("UPDATE sense_src SET sense_id=? WHERE id=?", link)
    print("\n■ 已提升 %s 条" % f"{len(s_rows):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
