#!/usr/bin/env python3
"""清掉出版层的两小族残渣。2026-08-14，阶段 1.5 补跑之后。

═══ 族一：带占位符的意语定义（5 条，我自己灌回去的）═══
`promote_it_gloss` 重跑时只滤了 `PURE`（整条都是占位符），漏掉**夹在句中**的：

    toccato    (di frutto) definizione mancante; se vuoi, aggiungila tu
    zazzeruto  o definizione mancante; se vuoi, aggiungila tu

清洗后只剩 `(di frutto)`「（指水果）」这种域标签 —— 源头明说"定义缺失"，
剩的那点不是定义。⇒ 判据收紧成 `bears_placeholder()`（带占位符就整条不提升），
本脚本把已经灌进去的 5 条退回证据层。

═══ 族二：可见却一条释义都没有的义项（2 条，老账）═══
    ens’    fr-edition 证据 = "Ious maly."                       ← 源头乱码
    squat   fr-edition 证据 = "Exemple d’utilisation manquant."  ← 法语版自己的占位符

法语版也有它自己的"缺失"模板，收词时没认出来。这两条中文根本没生成出来，
界面上就是个空壳。⇒ 藏掉（`hidden=1`），证据层原样保留。

⚠️ 记账：法语版占位符模板还没有系统性判据（这里只逮到 2 条实例）。
   `docs/lang/it-CONVENTIONS.md` backlog 记一条，等 ③/④ 那轮统一处理。

═══ 可逆 ═══
只删出版层 `sense_gloss` 行、退回 `sense_id`、置 `hidden`。证据层一个字节不动。

用法（在 it/ 目录下）：
    python3 fixes/purge_placeholder_residue.py
    python3 fixes/purge_placeholder_residue.py --apply
    python3 fixes/purge_placeholder_residue.py --verify
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
from strip_it_placeholder import (bears_placeholder, not_a_definition,   # noqa: E402
                                  only_label)   # 判据只有一个家，见那边的说明


def plan(con):
    """→ (要退回的意语定义 [(sense_id, word, text)], 要藏的空义项 [(sense_id, word)])"""
    bad = [(sid, w, t) for sid, w, t in con.execute(
        "SELECT g.sense_id, d.word, g.text FROM sense_gloss g "
        "JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id "
        "WHERE g.lang='it' AND g.kind='definition'")
        if not_a_definition(t)]
    # 「删掉族一之后还剩几条释义」—— 在 Python 里数，别在 SQL 里拼 IN 列表
    drop = {sid for sid, _, _ in bad}
    left = Counter()
    for sid, lang, kind in con.execute("SELECT sense_id, lang, kind FROM sense_gloss"):
        if sid in drop and lang == "it" and kind == "definition":
            continue
        left[sid] += 1
    empty = [(sid, w) for sid, w in con.execute(
        "SELECT s.id, d.word FROM sense s JOIN dict d ON d.id=s.word_id "
        "WHERE COALESCE(s.hidden,0)=0") if left[sid] == 0]
    return bad, empty


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    bad, empty = plan(con)
    checks = [
        ("🔴 出版层不再有带占位符的意语定义", len(bad), 0),
        ("🔴 不存在「可见却一条释义都没有」的义项", len(empty), 0),
        ("🔴 已裁决的证据都必须有对应的出版释义（退回要撤裁决）",
         q("SELECT count(*) FROM sense_src x WHERE x.src='it-edition' "
           "AND x.sense_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM sense_gloss g "
           "WHERE g.sense_id=x.sense_id AND g.lang='it' AND g.kind='definition')"), 0),
        # ⚠️ 第一版这里断言「带占位符的证据一条都没被裁决」，报红 17 条 —— **断言写过头了**，
        #    不是数据错：`strip` 的既定策略就是证据层保留占位符原文、出版侧剪干净，
        #    出版侧实测 0 条带占位符。判据应该盯**出版侧**，证据层不归这条管。
        ("🔴 出版层不存在「去掉括号就什么都不剩」的意语定义",
         sum(1 for (t,) in con.execute(
             "SELECT text FROM sense_gloss WHERE lang='it' AND kind='definition'")
             if only_label(t)), 0),
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

    bad, empty = plan(ro)
    print("■ 族一+三 占位符 / 纯域标签的意语定义 %d 条（退回证据层）" % len(bad))
    for sid, w, t in bad:
        print("   %-20s %s" % (w, t[:58]))
    print("\n■ 族二 可见却无释义的义项 %d 条（藏掉）" % len(empty))
    for sid, w in empty:
        print("   sense#%-8d %s" % (sid, w))
    ro.close()
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    if not bad and not empty:
        return 0

    with dbtool.session("purge-placeholder-residue",
                        expect={"#sense_gloss": -len(bad)}) as s:
        s.executemany("DELETE FROM sense_gloss WHERE sense_id=? AND lang='it' "
                      "AND kind='definition'", [(sid,) for sid, _, _ in bad])
        s.executemany("UPDATE sense_src SET sense_id=NULL WHERE sense_id=? "
                      "AND src='it-edition'", [(sid,) for sid, _, _ in bad])
        s.executemany("UPDATE sense SET hidden=1 WHERE id=?", [(sid,) for sid, _ in empty])
    print("\n■ 已退回 %d 条、藏掉 %d 条" % (len(bad), len(empty)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
