#!/usr/bin/env python3
"""R16：变格／变位类层（`entry_class`）。ru，2026-11-11。**不花钱。**

en 版 `forms` 里 `tags: [class]` 的那些行（`velar-stem`／`accent-c`／`a*②`／`2a imperfective transitive`）
落成 `entry_class`，一值一行。判据全在 `criteria` ⑪c（`entry_class_rows`），本文件一条都不写。

    python3 -u ru/pipeline/class_layer.py            # 干跑：分布 ＋ 已知答案
    python3 -u ru/pipeline/class_layer.py --apply    # 整表重建（这张表上没有付费数据）

⚠️ 页面**暂不印**（扎利兹尼亚克码对中文读者没有解释就是天书）。推翻：展示层要在变格表表头印
「硬词干 · 重音型 c」时，接 `russian.ts` ＋ 中文名映射表 ＋ 契约闸。见 `RU_PLAN` R16。
外锚闸 `test_dump_anchor.py` 的 class 层 import 本文件的 `collect`，不许自己重写。
"""
import argparse
import collections
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import dbtool                                                   # noqa: E402
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402
from pipeline.build import SRC, rd                              # noqa: E402

F = lambda n: format(n, ",")                                    # noqa: E731


def collect(conn, limit=None, verbose=True):
    """→ (rows, stat)。row ＝ (entry_id, system, kind, code, raw, hidden, hidden_why, src)。**只读。**
    `entry.src_ref` 必须用 `criteria.SrcRef` 按源头顺序重放（每个被接受的 entry 都要 take 一次）。"""
    eid = dict(conn.execute("SELECT src_ref, id FROM entry"))
    ref = criteria.SrcRef()
    rows, st = [], collections.Counter()
    for src, p in SRC:
        t0 = time.time()
        for e in rd(p, limit):
            ok, _skip, pos = criteria.entry_accept(e)
            if not ok:
                continue
            no, sub = criteria.etym_no_pair(e)
            sref, _seq = ref.take(src, e["word"], pos, no, sub)
            forms = e.get("forms") or []
            vals, tt = [], None
            for f in forms:
                tags = f.get("tags") or []
                v = (f.get("form") or "").strip()
                if not v:
                    continue
                if "inflection-template" in tags:
                    tt = tt or v
                elif "class" in tags:
                    vals.append(v)
            if not vals:
                continue
            entry_id = eid.get(sref)
            if entry_id is None:
                st["🔴 挂不上 entry"] += 1
                continue
            for system, kind, code, raw, why in criteria.entry_class_rows(tt, vals):
                rows.append((entry_id, system, kind, code, raw, 1 if why else 0, why, src))
                st["%s·%s" % (system, kind) if not why else "藏：" + why] += 1
            st["entry（%s）" % src] += 1
        if verbose:
            print("   …%s 扫完（%.0fs）" % (src, time.time() - t0), flush=True)
    return rows, st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("■ R16 变格／变位类层  判据 %s" % criteria.RULE_VER, flush=True)
    rows, st = collect(conn)
    for k in sorted(st):
        print("   %-34s %8s" % (k, F(st[k])))
    print("   %-34s %8s" % ("合计行", F(len(rows))))
    if st.get("🔴 挂不上 entry"):
        raise SystemExit("🔴 有 class 挂不上 entry —— src_ref 重放顺序与骨架层不一致？先查")
    have = conn.execute("SELECT COUNT(*) FROM entry_class").fetchone()[0]
    conn.close()
    if not a.apply:
        print("\n(干跑。)")
        return
    with dbtool.session("class-layer", expect={"#entry_class": len(rows) - have}, invalidates=[]) as s:
        s.execute("DELETE FROM entry_class")
        s.executemany("INSERT INTO entry_class(entry_id, system, kind, code, raw, hidden, hidden_why, src) "
                      "VALUES (?,?,?,?,?,?,?,?)", rows)
    print("\n■ 写库完成。")


if __name__ == "__main__":
    main()
