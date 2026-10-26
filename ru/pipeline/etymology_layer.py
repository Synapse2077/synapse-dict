#!/usr/bin/env python3
"""阶段 7：**词源层** —— `etymology`。ru，2026-10-24。不花钱（词源译中文若做，是另一次拍板）。

    python3 -u ru/pipeline/etymology_layer.py --dry
    python3 -u ru/pipeline/etymology_layer.py
    python3 -u ru/pipeline/etymology_layer.py --rebuild

判据一条都不在本文件里写 —— `criteria` §⑭。依据见 RU_PLAN §十七。

═══ 挂靠：直接到 entry（比 vi 准）═══
vi 按 (词形, 词源号) 挂，一段词源对多条 entry。ru 重放 `criteria.SrcRef` ⇒ **每段词源就挂在抄它的那条 entry 上**，
同一词形的同形异义词（`да` 语气词／连词各有各的来源）分得开。

═══ 🔴 同一段在同一词形的几个 entry 上各抄一遍：**各存一行，不藏** ═══
藏掉「重复」的那行 ⇒ 那条 entry 在逐 entry 展示时一个字词源都没有 —— **正是 vi 的 B18**（407 个词形词源印不出来）。
去重是展示层（阶段 9）按 (词形, 版, 出版正文) 做的事，数据层两种展示都要做得到。

═══ 两类「没有」在结构上分开 ═══
· 清洗后为空（`От ??` 占位、只有挂件）⇒ **不落库**，计「源头没给」；
· fr/vi/pl 的散文 ⇒ **落库但 hidden**（三语方针：进证据层不出版；将来译成中文时有原文可用）。
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
    """→ (rows, stat)。row ＝ (word_id, entry_id, etym_no, etym_sub, text, text_pub, src_field, etym_type,
    why, src, src_ref)。**只读。**"""
    wid = dict(conn.execute("SELECT word, id FROM dict"))
    eid = dict(conn.execute("SELECT src_ref, id FROM entry"))
    ref = criteria.SrcRef()
    rows, st = [], collections.Counter()
    for src, p in SRC:
        t0 = time.time()
        for e in rd(p, limit):
            ok, _skip, pos = criteria.entry_accept(e)
            if not ok:
                continue
            w = e["word"]
            no, sub = criteria.etym_no_pair(e)
            sref, _seq = ref.take(src, w, pos, no, sub)
            segs = criteria.etymology_segments(e)
            if not segs:
                continue
            entry_id = eid.get(sref)
            word_id = wid.get(w) or wid.get(criteria.strip_stress(w))
            if entry_id is None or word_id is None:
                st["🔴 挂不上 entry/dict"] += len(segs)
                continue
            et = criteria.etym_type_of(e.get("etymology_templates"))
            for k, t, field in segs:
                tp = criteria.etymology_text_pub(t, src)
                if not tp:
                    st["不落库：整段是占位/挂件（源头没给）·%s" % src] += 1
                    continue
                if tp != t.strip():
                    st["出版正文有清洗·%s" % src] += 1
                why = criteria.etymology_hidden_why(src, w, tp)
                rows.append((word_id, entry_id, no, sub, t, tp if tp != t else None, field, et, why, src,
                             "%s#etym%d" % (sref, k)))
                st[("藏：" + why) if why else "✅ 出版·%s" % src] += 1
        if verbose:
            print("   …%s 扫完（%.0fs）" % (src, time.time() - t0), flush=True)
    return rows, st


def report(rows, st, conn):
    print("\n■ 词源 %s 段（出版 %s）" % (F(len(rows)), F(sum(1 for r in rows if not r[8]))))
    for k, v in sorted(st.items()):
        print("   %-56s %10s" % (k, F(v)))
    et = collections.Counter(r[7] for r in rows if not r[8])
    print("   etym_type（出版段）：%s" % dict(et.most_common()))
    lem = {i for (i,) in conn.execute("SELECT id FROM dict WHERE is_lemma=1")}
    have = {r[0] for r in rows if not r[8] and r[0] in lem}
    zh = {r[0] for r in rows if not r[8] and r[0] in lem and criteria.ETYM_LANG[r[9]] == "zh"}
    print("   读者口径：词元有可出版词源 %s（%.2f%%）／其中有中文词源 %s（%.2f%%）" % (
        F(len(have)), 100.0 * len(have) / len(lem), F(len(zh)), 100.0 * len(zh) / len(lem)))


def write(rows, conn, rebuild=False):
    have = conn.execute("SELECT COUNT(*) FROM etymology").fetchone()[0]
    if have and not rebuild:
        raise SystemExit("🔴 `etymology` 已有 %s 行 —— 要重算就加 `--rebuild`" % F(have))
    paid = conn.execute("SELECT COUNT(*) FROM etymology_gloss").fetchone()[0]
    if paid and rebuild:
        raise SystemExit("🔴🔴 `etymology_gloss` 有 %s 行（可能是付费译文）—— 不许 --rebuild" % F(paid))
    q = lambda s: conn.execute(s).fetchone()[0] if rebuild else 0      # noqa: E731
    nn = lambda i: sum(1 for r in rows if r[i])                         # noqa: E731
    exp = {
        "#etymology": len(rows) - q("SELECT COUNT(*) FROM etymology"),
        "etymology.text": len(rows) - q("SELECT COUNT(*) FROM etymology WHERE text IS NOT NULL AND TRIM(text)<>''"),
        "etymology.src_field": len(rows) - q("SELECT COUNT(*) FROM etymology WHERE src_field IS NOT NULL "
                                             "AND TRIM(src_field)<>''"),
        "etymology.text_pub": nn(5) - q("SELECT COUNT(*) FROM etymology WHERE text_pub IS NOT NULL "
                                        "AND TRIM(text_pub)<>''"),
        "etymology.hidden_why": nn(8) - q("SELECT COUNT(*) FROM etymology WHERE hidden_why IS NOT NULL "
                                          "AND TRIM(hidden_why)<>''"),
        "etymology.etym_type": nn(7) - q("SELECT COUNT(*) FROM etymology WHERE etym_type IS NOT NULL "
                                         "AND TRIM(etym_type)<>''"),
        "etymology.entry_id": len(rows) - q("SELECT COUNT(*) FROM etymology WHERE entry_id IS NOT NULL"),
    }
    conn.close()
    with dbtool.session("etymology-layer" + ("-rebuild" if rebuild else ""), expect=exp,
                        invalidates=["etymology"]) as s:
        if rebuild:
            s.execute("DELETE FROM etymology")
        s.executemany("INSERT INTO etymology(word_id,entry_id,etym_no,etym_sub,text,text_pub,src_field,etym_type,"
                      "hidden,hidden_why,src,src_ref) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], 1 if r[8] else 0, r[8], r[9], r[10])
                       for r in rows])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("■ 阶段 7 词源层  判据 %s" % criteria.RULE_VER, flush=True)
    rows, st = collect(conn, a.limit)
    if st.get("🔴 挂不上 entry/dict"):
        raise SystemExit("🔴 有词源挂不上 entry —— 先查")
    report(rows, st, conn)
    dbtool.sample_check([(r[9][:5], (r[5] or r[4])[:60].replace("\n", "⏎"), r[8] or "出版") for r in rows], 12,
                        ("源", "出版正文", "出版/藏"))
    if a.dry or a.limit:
        print("\n(干跑。)")
        return
    write(rows, conn, a.rebuild)
    print("\n■ 写库完成。")


if __name__ == "__main__":
    main()
