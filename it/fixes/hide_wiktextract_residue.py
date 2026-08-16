#!/usr/bin/env python3
"""把 wiktextract 残渣从**出版层**隐藏（证据层原样保留）。2026-08-13，阶段 1。

═══ 是什么 ═══
`in men che niente` 在库里有 3 条"义项"：

    1. in less than no time            顷刻之间，一转眼     ← 真义项
    2. See also: men                   （中文为空）        ← 残渣
    3. Synonyms: in men che non si dica（中文为空）        ← 残渣

后两条是 wiktextract 把维基页面的"参见/同义词"小节当成义项抓下来的，
kaikki 原文里它们确实在 `senses` 里 —— 所以**不能从证据层删**（那是源头事实），
但它们不该出现在用户看到的义项列表里。

⇒ 这正是两层义项（`sense_src` 证据 / `sense` 出版）存在的理由：
   `sense.hidden=1` 隐藏，`sense_src` 一个字节不动，随时可翻案。
   **不删行**，所以复刻闸①仍然逐条对得上（它比对的是全部 sense，不看 hidden）。

═══ 判据 ═══
`sense_gloss(lang='en')` 以 `See also:` / `Synonyms:` / `Antonyms:` 等小节标题开头。
全库实测只命中 **3 行**（都在 `in men che niente`）—— 不是一族，是个案。
⚠️ 判据只认**行首**的这些词，不做模糊匹配：`synonyms` 出现在释义正文里是正常的。

用法（在 it/ 目录下）：
    python3 fixes/hide_wiktextract_residue.py            # 只看命中，不写库
    python3 fixes/hide_wiktextract_residue.py --apply
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

HEADS = ("See also", "Synonyms", "Antonyms", "Coordinate terms", "Hypernyms",
         "Hyponyms", "Related terms", "Meronyms", "Holonyms", "Alternative forms",
         "Usage notes", "Derived terms")
PAT = re.compile(r"^(%s)\s*:" % "|".join(HEADS))


def find(con):
    hits = []
    for sid, word, text in con.execute(
            "SELECT s.id, d.word, g.text FROM sense s "
            "JOIN dict d ON d.id = s.word_id "
            "JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='en' "
            "WHERE s.hidden IS NULL OR s.hidden = 0"):
        if PAT.match(text):
            hits.append((sid, word, text))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    cols = {r[1] for r in con.execute("PRAGMA table_info(sense)")}
    if "hidden" not in cols and not a.apply:
        print("(sense.hidden 列还没建，--apply 时会建)")
        con.execute("ALTER TABLE sense ADD COLUMN hidden INTEGER") if False else None
    hits = find(con) if "hidden" in cols else [
        (sid, word, text) for sid, word, text in con.execute(
            "SELECT s.id, d.word, g.text FROM sense s JOIN dict d ON d.id=s.word_id "
            "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='en'") if PAT.match(text)]
    con.close()

    print("■ 命中 %d 条：" % len(hits))
    for sid, word, text in hits:
        print("   sense#%-8s %-22s %s" % (sid, word, text[:60]))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    if not hits:
        print("无可隐藏的行")
        return 0

    with dbtool.session("hide-residue", expect={}) as s:
        c = {r[1] for r in s.conn.execute("PRAGMA table_info(sense)")}
        if "hidden" not in c:
            # 出版层可编辑：hidden=1 表示不展示给用户；证据层 sense_src 不动
            s.execute("ALTER TABLE sense ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
        s.executemany("UPDATE sense SET hidden=1 WHERE id=?", [(h[0],) for h in hits])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n = con.execute("SELECT count(*) FROM sense WHERE hidden=1").fetchone()[0]
    ns = con.execute("SELECT count(*) FROM sense_src").fetchone()[0]
    print("\n■ 已隐藏 %d 条；sense_src 仍为 %s 条（证据层一个字节没动）" % (n, f"{ns:,}"))
    return 0 if n == len(hits) else 1


if __name__ == "__main__":
    sys.exit(main())
