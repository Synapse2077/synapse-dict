#!/usr/bin/env python3
"""R19：把不是俄语的词头从骨架层移出。ru，2026-11-02。

═══ 缺陷 ═══
zh 繁版俄语区里有一条 `且聽下回分解`（汉语章回小说的结束语），落成了 `dict` 词头，
挂着 1 个 entry、2 条义项（中文版原文释义）、1 段词源。全库词头一个西里尔/拉丁/希腊字母都没有的只有它一个
（判据 `criteria.headword_script_ok`；`Роᛋᛋия` 那种混着如尼字母的俄语拼写不在此列）。
生成侧已改（`entry_accept` ②b，ru-crit-20），本脚本移出**已落库**的那一条及挂着的行。

═══ 怎么删 ═══
挂着的行逐表**先量再删**，每张表的删除行数在 `expect` 里写死；量出来与写死的不一致就停。
全是源头数据（`zh-edition-trad`），没有付费译文。源头原文仍在 dump 里，删的是我们的骨架层，不是证据。

跑（在仓库根）：
    python3 -u ru/fixes/fix_r19_non_russian_head.py            # 干跑
    python3 -u ru/fixes/fix_r19_non_russian_head.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import argparse
import sqlite3

import dbtool
import paths
import criteria as C


def plan(con):
    """→ [(表, 列, [id…])]，按删除顺序（先子后父）。"""
    wids = [i for i, w in con.execute("SELECT id, word FROM dict") if not C.headword_script_ok(w)]
    if not wids:
        return [], []
    q = lambda sql, ids: [r[0] for r in con.execute(sql % ",".join(map(str, ids)))] if ids else []
    sids = q("SELECT id FROM sense WHERE word_id IN (%s)", wids)
    eids = q("SELECT id FROM entry WHERE word_id IN (%s)", wids)
    steps = [("sense_tag", "sense_id", sids), ("sense_gloss", "sense_id", sids),
             ("sense_src", "word_id", wids), ("sense", "word_id", wids),
             ("etymology", "word_id", wids), ("entry", "word_id", wids), ("dict", "id", wids)]
    # 🔴 还有没列进上面的表挂着它 ⇒ 停（删了父行留下孤儿比不删更坏）
    listed = {t for t, _c, _ in steps}    # 表在清单里 ⇒ 按清单那一列删的就是这个词的全部行
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        cols = [r[1] for r in con.execute("PRAGMA table_info(%s)" % t)]
        for col, ids in (("word_id", wids), ("entry_id", eids), ("sense_id", sids)):
            if col in cols and t not in listed and ids and con.execute(
                    "SELECT 1 FROM %s WHERE %s IN (%s) LIMIT 1" % (t, col, ",".join(map(str, ids)))).fetchone():
                raise SystemExit("🔴 %s.%s 还挂着要删的行 —— 本脚本没覆盖，停" % (t, col))
    return [w for (w,) in con.execute("SELECT word FROM dict WHERE id IN (%s)" % ",".join(map(str, wids)))], steps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words, steps = plan(con)
    counts = {t: con.execute("SELECT COUNT(*) FROM %s WHERE %s IN (%s)" % (t, c, ",".join(map(str, ids)))).fetchone()[0]
              if ids else 0 for t, c, ids in steps}
    cols = {t: [r[1] for r in con.execute("PRAGMA table_info(%s)" % t)] for t, _c, _i in steps}
    con.close()
    print("■ 不是俄语的词头：%s" % words)
    for t, n in counts.items():
        print("   删 %-12s %d 行" % (t, n))
    if not a.apply or not words:
        return
    exp = {"#%s" % t: -n for t, n in counts.items() if t != "dict"}
    exp["__rows__"] = -counts["dict"]
    for t, cs in cols.items():          # 删行 ⇒ 这些表每列的非空计数都会变：声明允许变，表行数写死
        for col in cs:
            # ⚠️ `dict` 的列在 dbtool 的不变量里是**裸列名**（`word_norm`），别的表带表名前缀
            exp[col if t == "dict" else "%s.%s" % (t, col)] = None
    with dbtool.session("ru-fix-r19-non-russian-head", expect=exp, invalidates=[],
                        small=sum(counts.values()) + 5) as s:
        for t, c, ids in steps:
            if ids:
                s.execute("DELETE FROM %s WHERE %s IN (%s)" % (t, c, ",".join(map(str, ids))))
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = sum(1 for (w,) in con.execute("SELECT word FROM dict") if not C.headword_script_ok(w))
    print("■ 写后回核：不是俄语的词头 %d 个（期望 0）" % left)
    if left:
        raise SystemExit("🔴 回核红")


if __name__ == "__main__":
    main()
