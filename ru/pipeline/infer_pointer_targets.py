#!/usr/bin/env python3
"""词形页指针区的两列派生值（2026-11-02）—— `sense_src.inferred_target`（R22 反查目标）＋ `sense_src.ptr_tags`（R32 fr 说明解析出的标签）。

═══ 为什么 ═══
23 万个词形页点进去是空的：源头只在释义散文里写了原形（`страд. прич. прош. вр. от взбулгачить`、
`Accusatif masculin singulier de Янков.`），`pointer_target` 空 ⇒ 展示层的指针区不印。
判据与实测见 `criteria.py` ⑯：屈折层反查唯一 ＋ 散文点名一致才收。

═══ 范围 ═══
`sense_src` 里 `sense_id IS NULL`（证据层）、`pointer_target IS NULL`（源头没给目标）、
挂在 `is_lemma=0` 的词形上的行。**只写这一列**，证据层其余各列一个字不动。

跑（在仓库根）：
    python3 -u ru/pipeline/infer_pointer_targets.py            # 干跑
    python3 -u ru/pipeline/infer_pointer_targets.py --apply
"""
import argparse
import collections
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dbtool                                                     # noqa: E402
import paths                                                      # noqa: E402
from pipeline import criteria                                     # noqa: E402
from pipeline.build_v3_schema import ADD_COLUMNS                  # noqa: E402

COL = "inferred_target"
TAGS = "ptr_tags"      # R32：fr 版指针说明解析出的语法标签（`criteria.fr_pointer_tags`）


def collect_tags(con):
    """→ ({sense_src.id: 'a|b|c'}, 统计)。范围：页面上会印的 fr 指针（有源头目标或反查目标）。"""
    out, st = {}, collections.Counter()
    #   2026-11-05：范围 fr → fr/vi/pl，先查人工裁决表（`criteria.pointer_tags`）；vi/pl 只有裁决表里的才有标签
    for xid, lang, text in con.execute(
            "SELECT id, lang, text FROM sense_src WHERE sense_id IS NULL AND lang IN ('fr', 'vi', 'pl') "
            "AND (pointer_target IS NOT NULL OR inferred_target IS NOT NULL)"):
        tags = criteria.pointer_tags(lang, text)
        if tags:
            out[xid] = "|".join(tags)
            st["解析成标签"] += 1
        else:
            st["认不全，留原文（vi/pl 不在裁决表的都在这里）"] += 1
    return out, st


HID = "ptr_hidden_why"   # R32 结清：不印的指针（`criteria.pointer_hidden_why`，人工裁决）


def collect_hidden(con):
    """→ {sense_src.id: 理由}。范围：页面上会印的指针（有源头目标或反查目标）。"""
    return {xid: why for xid, lang, text in con.execute(
        "SELECT id, lang, text FROM sense_src WHERE sense_id IS NULL "
        "AND (pointer_target IS NOT NULL OR inferred_target IS NOT NULL)")
        for why in [criteria.pointer_hidden_why(lang, text)] if why}


def collect(con):
    """→ ({sense_src.id: 目标}, 统计)。纯函数，回归闸 import 它重算。"""
    rows = con.execute(
        "SELECT x.id, d.id, d.word, x.text FROM sense_src x JOIN dict d ON d.id = x.word_id "
        "WHERE x.sense_id IS NULL AND x.pointer_target IS NULL AND d.is_lemma = 0").fetchall()
    # 一条整批 SQL 反查全部原形（2026-11-02：原来逐个词形发 23 万次查询，36 秒 → 13 秒；结果逐行对过相同）。
    #   义项闸 E16 每次（含每条变异）都要重算它，所以省下的时间乘以变异条数。
    parents_of = collections.defaultdict(set)
    for wid, p in con.execute(
            "WITH w AS (SELECT DISTINCT d.id, d.word FROM sense_src x JOIN dict d ON d.id = x.word_id "
            "           WHERE x.sense_id IS NULL AND x.pointer_target IS NULL AND d.is_lemma = 0) "
            "SELECT DISTINCT w.id, d2.word FROM w JOIN inflection i ON i.form = w.word "
            "JOIN entry e ON e.id = i.entry_id JOIN dict d2 ON d2.id = e.word_id WHERE e.word_id <> w.id"):
        parents_of[wid].add(p)
    out, st = {}, collections.Counter()
    for xid, wid, word, text in rows:
        ps = parents_of.get(wid, set())
        t = criteria.inferred_target(ps, text)
        if t:
            out[xid] = t
            st["收：两个信号一致"] += 1
        elif not ps:
            st["留空：屈折层查不到"] += 1
        elif len(ps) > 1:
            st["留空：屈折层反查不唯一"] += 1
        elif not criteria.named_parents(text):
            st["留空：释义里没点名原形"] += 1
        else:
            st["留空：两个信号不一致"] += 1
    return out, st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    assert ("sense_src", COL, "TEXT") in ADD_COLUMNS, "先在 build_v3_schema.ADD_COLUMNS 登记这一列"
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have_col = COL in {r[1] for r in con.execute("PRAGMA table_info(sense_src)")}
    want, st = collect(con)
    have = dict(con.execute("SELECT id, %s FROM sense_src WHERE %s IS NOT NULL" % (COL, COL))) if have_col else {}
    con.close()
    print("■ 证据层指针行（源头没给目标、挂在词形页上）：%s" % format(sum(st.values()), ","))
    for k, v in st.most_common():
        print("   %-24s %9s" % (k, format(v, ",")))
    upd = [(t, i) for i, t in want.items() if have.get(i) != t]
    clr = [(i,) for i in have if i not in want]
    print("■ 反查目标：要写 %s 行／要清 %s 行" % (format(len(upd), ","), format(len(clr), ",")))
    # ── R32：fr 指针说明的标签（依赖上面的反查目标决定「会不会印」⇒ 按写完之后的口径算）
    assert ("sense_src", TAGS, "TEXT") in ADD_COLUMNS, "先在 build_v3_schema.ADD_COLUMNS 登记这一列"
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have_tcol = TAGS in {r[1] for r in con.execute("PRAGMA table_info(sense_src)")}
    want_t, st_t = collect_tags(con) if not (upd or clr) else ({}, collections.Counter())
    have_t = dict(con.execute("SELECT id, %s FROM sense_src WHERE %s IS NOT NULL" % (TAGS, TAGS))) if have_tcol else {}
    con.close()
    if upd or clr:
        print("   （反查目标还要变 ⇒ 标签等目标写完再跑一次本脚本）")
    for k, v in st_t.most_common():
        print("   fr 指针说明 %-14s %9s" % (k, format(v, ",")))
    upd_t = [(t, i) for i, t in want_t.items() if have_t.get(i) != t]
    clr_t = [(i,) for i in have_t if i not in want_t] if not (upd or clr) else []
    print("■ 指针标签：要写 %s 行／要清 %s 行" % (format(len(upd_t), ","), format(len(clr_t), ",")))
    # ── R32 结清：不印的指针（同样按写完反查目标之后的口径）
    assert ("sense_src", HID, "TEXT") in ADD_COLUMNS, "先在 build_v3_schema.ADD_COLUMNS 登记这一列"
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have_hcol = HID in {r[1] for r in con.execute("PRAGMA table_info(sense_src)")}
    want_h = collect_hidden(con) if not (upd or clr) else {}
    have_h = dict(con.execute("SELECT id, %s FROM sense_src WHERE %s IS NOT NULL" % (HID, HID))) if have_hcol else {}
    con.close()
    upd_h = [(t, i) for i, t in want_h.items() if have_h.get(i) != t]
    clr_h = [(i,) for i in have_h if i not in want_h] if not (upd or clr) else []
    print("■ 不印的指针：要写 %s 行／要清 %s 行（裁决表 %d 条）"
          % (format(len(upd_h), ","), format(len(clr_h), ","), len(criteria.POINTER_HIDDEN_ADJUDICATED)))
    if len(want_h) > len(criteria.POINTER_HIDDEN_ADJUDICATED):
        raise SystemExit("🔴 命中比裁决表多 —— 同一句说明在别的词形上也出现了，逐条看过再藏")
    if not a.apply or not (upd or clr or upd_t or clr_t or upd_h or clr_h
                           or not have_col or not have_tcol or not have_hcol):
        return
    exp = {"sense_src.%s" % COL: len(want) - len(have)}
    if not (upd or clr):
        exp["sense_src.%s" % TAGS] = len(want_t) - len(have_t)
        exp["sense_src.%s" % HID] = len(want_h) - len(have_h)
    with dbtool.session("ru-infer-pointer-targets", expect=exp, invalidates=[]) as s:
        if not have_col:
            s.execute("ALTER TABLE sense_src ADD COLUMN %s TEXT" % COL)
        if not have_tcol:
            s.execute("ALTER TABLE sense_src ADD COLUMN %s TEXT" % TAGS)
        if not have_hcol:
            s.execute("ALTER TABLE sense_src ADD COLUMN %s TEXT" % HID)
        s.executemany("UPDATE sense_src SET %s=? WHERE id=?" % COL, upd)
        s.executemany("UPDATE sense_src SET %s=NULL WHERE id=?" % COL, clr)
        s.executemany("UPDATE sense_src SET %s=? WHERE id=?" % TAGS, upd_t)
        s.executemany("UPDATE sense_src SET %s=NULL WHERE id=?" % TAGS, clr_t)
        s.executemany("UPDATE sense_src SET %s=? WHERE id=?" % HID, upd_h)
        s.executemany("UPDATE sense_src SET %s=NULL WHERE id=?" % HID, clr_h)


if __name__ == "__main__":
    main()
