#!/usr/bin/env python3
"""族K：同一段引文从两个版本各收了一遍。2026-08-30。

外审说 `godo` 的例句出现两次。族J 修完字段错位后，这条还在 —— 因为它**真的是两行**：

    pt-edition  …que não sei se pode ser aceita…
    fr-edition  …que nào sei se pode ser aceita…     ← 源头把 não 拼错了

`UNIQUE(word, text)` 挡不住：两个字符串确实不一样。

═══ 判据 ═══
按**含义**：读者眼里这是同一句话。⇒ 去掉变音符与全部非字母数字字符后相同即为同一句。
    「Eu tenho dez dedos nas mãos」 vs 「Eu tenho dez dedos nas mãos.」   句点
    「Se você não paga…」          vs 「se você não paga…」              首字母大小写
    「…não sei…」                  vs 「…nào sei…」                      源头拼写错

⚠️ 这条判据比 `UNIQUE(word,text)` **宽**，是有意的 —— 那个约束防的是"同一条进两遍"，
   这里防的是"同一句话的两个抄本"。两者不是一回事。

═══ 留哪一条 ═══
🔴 不留第一条（`[[it-backlog-cleared]]` 合并录音那次的教训）：
   有中文译文 → 有出处 → 文本更长（标点更完整） → id 最小。

用法（在 pt/ 目录下）：
    python3 fixes/fix_example_near_dup.py
    python3 fixes/fix_example_near_dup.py --apply
"""
import argparse
import collections
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402


def same_sentence(s):
    """→ 归一键：去变音符、去大小写、去一切非字母数字。判据只在这里。"""
    s = "".join(c for c in unicodedata.normalize("NFD", s.lower())
                if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", s)


def plan(con):
    zh = {r[0] for r in con.execute("SELECT example_id FROM example_gloss WHERE lang='zh'")}
    g = collections.defaultdict(list)
    for i, w, t, r in con.execute(
            "SELECT id, word, text, ref FROM example WHERE COALESCE(hidden,0)=0"):
        g[(w, same_sentence(t))].append((i, t, r))
    drop, lost = [], 0
    for _k, rows in g.items():
        if len(rows) == 1:
            continue
        rows.sort(key=lambda x: (x[0] not in zh, x[2] is None, -len(x[1]), x[0]))
        drop.extend(x[0] for x in rows[1:])
        if rows[0][0] not in zh and any(x[0] in zh for x in rows[1:]):
            lost += 1
    return drop, lost, len(g)


def main(a):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    drop, lost, ngroups = plan(con)
    f = lambda n: format(n, ",")
    print("■ 可见例句归成 %s 个「同一句话」组；重复多出 %s 行" % (f(ngroups), f(len(drop))))
    print("■ 负控 —— 留下的那条丢了中文而被删的有：%d（必须是 0）" % lost)
    if lost:
        return 1
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    orphan = [(r[0], r[1]) for r in con.execute(
        "SELECT example_id, lang FROM example_gloss WHERE example_id IN (%s)"
        % ",".join("?" * len(drop)), drop)] if drop else []
    with dbtool.session("fix-pt-example-near-dup",
                        expect={"#example": -len(drop),
                                "#example_gloss": -len(orphan)}) as s:
        s.executemany("DELETE FROM example_gloss WHERE example_id=? AND lang=?", orphan)
        s.executemany("DELETE FROM example WHERE id=?", [(i,) for i in drop])
    print("\n✓ 删 %s 行（连带译文 %s 行）" % (f(len(drop)), f(len(orphan))))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    sys.exit(main(ap.parse_args()))
