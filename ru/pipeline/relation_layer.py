#!/usr/bin/env python3
"""阶段 6b：**关系层** —— `sense_relation`。ru，2026-10-23。不花钱。

    python3 -u ru/pipeline/relation_layer.py --dry
    python3 -u ru/pipeline/relation_layer.py
    python3 -u ru/pipeline/relation_layer.py --rebuild

判据一条都不在本文件里写 —— `criteria` §⑫。依据见 RU_PLAN §十四。

═══ 三种来源、一张表 ═══
① 源头的关系字段（词级 ／ en 版的义项级）→ `REL_KINDS`，认不出的字段**抛错**不归 related；
   ru 版 `related` → `word_family`（构词词族，带 `rel_group`/`form_group`，R1/R10）。
② 体对 `aspect_pair`：en/zh 版动词 `forms[]` 里的体对伙伴（`criteria.aspect_partner`，按字段分支）。
③ 有意不收：anagrams/metagrams/translations（`REL_NOT_COLLECTED`，各带推翻条件）。

═══ 挂到哪一级 ═══
· en 版义项级字段 ⇒ 那条义项（可出版才挂，否则 NULL）
· ru 版词级字段带 `sense_index`（1 起数，实测 95,682/95,810 在范围内，`ё → йо/эй/привет` 落在「招呼语」义项）
  ⇒ 那条义项；越界的挂 entry
· 其余（fr/pl 的 `sense_index` 指向不出版的义项、zh/vi 没有）⇒ entry 级
🔴 `target_id`：先精确、再去重音精确；**不折大小写**（`Ящерица`/`ящерица` 不许互指 —— vi 的 `Trang`/`trang`）。
   解析不到留 NULL —— 那是一等信息（展示层据此不做成链接，ko「关系词 34.6% 点下去空白页」）。

═══ 藏不删 ═══
· 同一 entry、同一义项、同一 kind 下目标重复 ⇒ `REL_DUP`
· B17：同一词形下 `related` 的目标也出现在更具体的 kind 里 ⇒ `REL_REDUNDANT`
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
SKIP_FIELDS = frozenset({"forms", "senses", "examples", "sounds", "head_templates",
                         "inflection_templates", "categories", "etymology_templates",
                         "descendants_templates", "form_of", "alt_of", "info_templates",
                         "attestations", "links", "wikipedia", "hyphenations", "hyphenation"})


def _is_rel_list(v):
    return isinstance(v, list) and v and isinstance(v[0], dict) and "word" in v[0]


def norm_target(t):
    return criteria.strip_stress(t).lower().replace("ё", "е")


def collect(conn, limit=None, verbose=True):
    """→ (rows, stat)。row ＝
    (word_id, entry_id, sense_id, kind, subkind, rel_group, form_group, target, target_id, why, src, src_ref)"""
    wid = dict(conn.execute("SELECT word, id FROM dict"))
    tid = {}
    for w, i in conn.execute("SELECT word, id FROM dict ORDER BY id"):
        tid.setdefault(w, i)
    eid = dict(conn.execute("SELECT src_ref, id FROM entry"))
    s_ok = {i for (i,) in conn.execute("SELECT id FROM sense WHERE hidden=0")}
    ssrc = {r: s for r, s in conn.execute("SELECT src_ref, sense_id FROM sense_src") if s in s_ok}
    ref = criteria.SrcRef()
    rows, st = [], collections.Counter()
    junk_tags = collections.Counter()

    def resolve(t):
        i = tid.get(t)
        if i is None:
            i = tid.get(criteria.strip_stress(t))
        return i

    for src, p in SRC:
        t0 = time.time()
        for e in rd(p, limit):
            ok, _skip, pos = criteria.entry_accept(e)
            if not ok:
                continue
            w = e["word"]
            no, sub = criteria.etym_no_pair(e)
            sref, _seq = ref.take(src, w, pos, no, sub)
            entry_id = eid.get(sref)
            word_id = wid.get(w) or wid.get(criteria.strip_stress(w))
            if entry_id is None or word_id is None:
                st["🔴 挂不上 entry/dict"] += 1
                continue
            senses = e.get("senses") or []
            levels = [("w", None, e)] + [("s%d" % si, si, s) for si, s in enumerate(senses)]
            for lvl, si, obj in levels:
                for field, v in obj.items():
                    if field in SKIP_FIELDS or not _is_rel_list(v):
                        continue
                    try:
                        kind = criteria.relation_kind(src, field)
                    except KeyError:
                        raise SystemExit("🔴 认不出的关系字段 `%s`（%s）—— 先登记进 criteria.REL_KINDS "
                                         "或 REL_NOT_COLLECTED" % (field, src))
                    if kind is None:
                        st["有意不收：%s" % field] += len(v)
                        continue
                    for i, it in enumerate(v):
                        tgt, fixed, drop = criteria.relation_target(it, kind)
                        if drop:
                            st["丢：%s" % drop] += 1
                            continue
                        if fixed:
                            st["目标清洗：%s" % fixed] += 1
                        # 挂义项
                        sense_id = None
                        if si is not None:
                            sense_id = ssrc.get("%s#s%d" % (sref, si))
                        elif src == "ru-edition" and isinstance(it.get("sense_index"), int):
                            k = it["sense_index"] - 1
                            if 0 <= k < len(senses):
                                sense_id = ssrc.get("%s#s%d" % (sref, k))
                            else:
                                st["ru 版 sense_index 越界 ⇒ entry 级"] += 1
                        rg = fg = None
                        if kind == "word_family":
                            rg, fg, junk, extra = criteria.family_groups(it)
                            if junk:
                                st["词族：残渣标签（R10）⇒ 分组记空"] += 1
                                junk_tags.update(junk)
                            if extra:
                                st["词族：源头给了两个不同分组 ⇒ 取第一个"] += 1
                        rows.append([word_id, entry_id, sense_id, kind, None, rg, fg, tgt, resolve(tgt),
                                     None, src, "rel:%s:%s:%s:%d" % (sref, lvl, field, i)])
                        st["收：%s" % kind] += 1
            if pos == "verb":
                for fi, f in enumerate(e.get("forms") or []):
                    hit = criteria.aspect_partner(src, f)
                    if not hit:
                        continue
                    rows.append([word_id, entry_id, None, "aspect_pair", hit[1], None, None, hit[0],
                                 resolve(hit[0]), None, src, "rel:%s:forms:aspect:%d" % (sref, fi)])
                    st["收：aspect_pair"] += 1
        if verbose:
            print("   …%s 扫完（%.0fs）" % (src, time.time() - t0), flush=True)

    # ── 藏不删 ①：同一 entry、同一义项、同一 kind 下目标重复
    seen = set()
    for r in rows:
        k = (r[1], r[2], r[3], norm_target(r[7]))
        if k in seen:
            r[9] = criteria.REL_DUP
        else:
            seen.add(k)
    # ── 藏不删 ②：B17
    specific = set()
    for r in rows:
        if r[9] is None and r[3] in criteria.REL_SUBSUME:
            specific.add((r[0], norm_target(r[7])))
    for r in rows:
        if r[9] is None and r[3] == "related" and (r[0], norm_target(r[7])) in specific:
            r[9] = criteria.REL_REDUNDANT
    for r in rows:
        if r[9]:
            st["藏：%s" % r[9]] += 1
    st["__junk_tags__"] = junk_tags
    return rows, st


def report(rows, st):
    junk = st.pop("__junk_tags__", collections.Counter())
    print("\n■ 关系 %s 行（可出版 %s）" % (F(len(rows)), F(sum(1 for r in rows if r[9] is None))))
    for k, v in sorted(st.items()):
        print("   %-50s %11s" % (k, F(v)))
    by = collections.Counter((r[3], r[10]) for r in rows if r[9] is None)
    print("   ── 可出版 kind × 版：")
    for k, v in sorted(by.items()):
        print("      %-14s %-18s %10s" % (k[0], k[1], F(v)))
    pub = [r for r in rows if r[9] is None]
    print("   目标解析得到 dict：%.1f%%；挂到义项：%.1f%%" % (
        100.0 * sum(1 for r in pub if r[8]) / max(1, len(pub)),
        100.0 * sum(1 for r in pub if r[2]) / max(1, len(pub))))
    wf = [r for r in pub if r[3] == "word_family"]
    print("   词族：有词性分组 %.1f%%／有构词分组 %.1f%%" % (
        100.0 * sum(1 for r in wf if r[5]) / max(1, len(wf)), 100.0 * sum(1 for r in wf if r[6]) / max(1, len(wf))))
    print("   R10 残渣标签 %d 种，最多的 15 个：%s" % (len(junk), junk.most_common(15)))


def write(rows, conn, rebuild=False):
    have = conn.execute("SELECT COUNT(*) FROM sense_relation").fetchone()[0]
    if have and not rebuild:
        raise SystemExit("🔴 `sense_relation` 已有 %s 行 —— 要重算就加 `--rebuild`" % F(have))
    q = lambda s: conn.execute(s).fetchone()[0] if rebuild else 0      # noqa: E731
    nn = lambda i: sum(1 for r in rows if r[i] is not None)             # noqa: E731
    exp = {
        "#sense_relation": len(rows) - q("SELECT COUNT(*) FROM sense_relation"),
        "sense_relation.subkind": nn(4) - q("SELECT COUNT(*) FROM sense_relation WHERE subkind IS NOT NULL "
                                            "AND TRIM(subkind)<>''"),
        "sense_relation.rel_group": nn(5) - q("SELECT COUNT(*) FROM sense_relation WHERE rel_group IS NOT NULL "
                                              "AND TRIM(rel_group)<>''"),
        "sense_relation.form_group": nn(6) - q("SELECT COUNT(*) FROM sense_relation WHERE form_group IS NOT NULL "
                                               "AND TRIM(form_group)<>''"),
        "sense_relation.entry_id": nn(1) - q("SELECT COUNT(*) FROM sense_relation WHERE entry_id IS NOT NULL"),
        "sense_relation.target_id": nn(8) - q("SELECT COUNT(*) FROM sense_relation WHERE target_id IS NOT NULL"),
    }
    conn.close()
    with dbtool.session("relation-layer" + ("-rebuild" if rebuild else ""), expect=exp,
                        invalidates=["sense_relation"]) as s:
        if rebuild:
            s.execute("DELETE FROM sense_relation")
        s.executemany("INSERT INTO sense_relation(word_id,entry_id,sense_id,kind,subkind,rel_group,form_group,"
                      "target,target_id,hidden,hidden_why,src,src_ref) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      ((r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], 1 if r[9] else 0, r[9], r[10], r[11])
                       for r in rows))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("■ 阶段 6b 关系层  判据 %s" % criteria.RULE_VER, flush=True)
    rows, st = collect(conn, a.limit)
    if st.get("🔴 挂不上 entry/dict"):
        raise SystemExit("🔴 有条目挂不上 entry —— 重算 src_ref 的顺序与骨架层不一致？先查")
    report(rows, st)
    dbtool.sample_check([(r[3], r[7][:30], r[9] or "出版") for r in rows], 12, ("kind", "目标", "出版/藏"))
    if a.dry or a.limit:
        print("\n(干跑。)")
        return
    write(rows, conn, a.rebuild)
    print("\n■ 写库完成。")


if __name__ == "__main__":
    main()
