#!/usr/bin/env python3
"""es 的关系/搭配残渣：切碎的度量衡说明 + 重复搭配。2026-08-21。

═══ 怎么来的 ═══
it 那轮点测评审（2026-08-21）逮到四个**可用确定性判据查**的形状，拿同一批判据来量 es：

    形状              it        es
    括号残渣         808       **11**
    搭配重复         326       **7**
    音标位垃圾         4         0
    变形提示重复    2,428         0

es 干净得多（打磨了一个月），但这 18 条是实打实的，判据现成 ⇒ 顺手清掉。
🔴 判据 **import it 的那一份**（`it/fixes/fix_unclosed_paren.classify`），不另写 ——
   同一个缺陷在两个语种上用两套判据，迟早对不上。

═══ 这 18 条 ═══
A. 括号残渣 11 条
   · `barril` 10 条：源头是度量衡换算表 `cuarto (1008 barriles)`，按逗号切分时
     切成了 `cuarto (1` + `1008 barriles)` 两条 coordinate。两半都不是词。
   · `sálamo` 1 条：`madroño[w:Nicoya|Nicoya]], Guanacaste), …` —— wiki 标记残渣。
B. 搭配重复 6 组 7 行（`en el aire` 出现 3 次）

═══ 为什么是藏不是删 ═══
与 it 同一条理由：删行不可逆，且收录脚本重放时 `INSERT OR IGNORE` 会把删掉的行
原样填回来。`sense_relation` / `collocation` 各加 `hidden` 列。
🔴 **加列必须同步改读取路径**（`spanish.ts` 的 relationQuery / collocationQuery）——
   it 那轮就是只加列没改读取路径，`--verify` 还报了绿（它查的是 `WHERE hidden=0`，
   那只是**假设**展示层会过滤），渲染出来才看见残渣还在。

用法（在 es/ 目录下）：
    python3 fixes/hide_relation_colloc_residue.py            # 干跑
    python3 fixes/hide_relation_colloc_residue.py --apply
    python3 fixes/hide_relation_colloc_residue.py --verify
"""
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "it" / "fixes"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from fix_unclosed_paren import classify   # noqa: E402

f = lambda n: format(n, ",")


def scan(con):
    """→ (关系残渣 [(id, word, kind, target)], 搭配重复 [(id, word, text)])"""
    rel = [(rid, w, k, t) for rid, w, k, t in con.execute(
        "SELECT r.id, d.word, r.kind, r.target FROM sense_relation r "
        "JOIN dict d ON d.id=r.word_id") if classify(t)]
    # 搭配去重：同 word_id+text 只留 rank 最小（＝ id 最小）的那条
    col = []
    for wid, text in con.execute(
            "SELECT word_id, text FROM collocation GROUP BY word_id, text HAVING COUNT(*)>1"):
        rows = con.execute("SELECT c.id, d.word, c.text FROM collocation c JOIN dict d ON d.id=c.word_id "
                           "WHERE c.word_id=? AND c.text=? ORDER BY c.rank, c.id",
                           (wid, text)).fetchall()
        col.extend(rows[1:])              # 留第一条，其余藏掉
    return rel, col


def gate(con):
    ok = True
    for t, col in (("sense_relation", "target"), ("collocation", "text")):
        cols = {r[1] for r in con.execute("PRAGMA table_info(%s)" % t)}
        if "hidden" not in cols:
            print("🔴 %s 还没有 hidden 列" % t)
            ok = False
    if not ok:
        return False
    n1 = sum(1 for (t,) in con.execute(
        "SELECT target FROM sense_relation WHERE COALESCE(hidden,0)=0") if classify(t))
    n2 = con.execute("""SELECT COALESCE(SUM(k-1),0) FROM (
        SELECT COUNT(*) k FROM collocation WHERE COALESCE(hidden,0)=0
         GROUP BY word_id, text HAVING k>1)""").fetchone()[0]
    print("■ 读取路径上的括号残渣：%s 条" % f(n1))
    print("■ 读取路径上的重复搭配：%s 行" % f(n2))
    return n1 == 0 and n2 == 0


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        ok = gate(ro)
        ro.close()
        return 0 if ok else 1
    rel, col = scan(ro)
    ro.close()
    print("■ 关系残渣 %s 条 / 重复搭配 %s 行" % (f(len(rel)), f(len(col))))
    for rid, w, k, t in rel:
        print("     藏  %-14s %-11s %r" % (w[:14], k, t))
    for cid, w, t in col:
        print("     藏  %-14s 搭配   %r" % (w[:14], t))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("hide-relation-colloc-residue", expect={"__rows__": 0}) as s:
        for t in ("sense_relation", "collocation"):
            cols = {r[1] for r in s.execute("PRAGMA table_info(%s)" % t)}
            if "hidden" not in cols:
                s.execute("ALTER TABLE %s ADD COLUMN hidden INTEGER DEFAULT 0" % t)
        if rel:
            s.execute("UPDATE sense_relation SET hidden=1 WHERE id IN (%s)"
                      % ",".join(str(r[0]) for r in rel))
        if col:
            s.execute("UPDATE collocation SET hidden=1 WHERE id IN (%s)"
                      % ",".join(str(r[0]) for r in col))
        s.written = len(rel) + len(col)
    print("\n■ 已藏关系 %s 条、搭配 %s 行" % (f(len(rel)), f(len(col))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
