#!/usr/bin/env python3
"""阶段 5：收语义关系（同/反/上下位…）→ `sense_relation`。2026-08-18。

═══ 现状 ═══
`sense_relation` 表里只有 7,995 条 `alt_of`（阶段 2a 的异体指针），
**真正的语义关系一条都没收**，而三版 dump 里现成的有：

    it 版  词条级 同义 600,662 / 反义 200,702 / 上位 17,393 / 下位 9,785
    en 版  义项级 同义  39,127 / 反义   3,438 / 同级  1,253 / 上位 517
    fr 版  词条级 同义  11,151 / 反义   2,552

这正是 `SCHEMA` 里记的那句「源头现成，一条没用」。

═══ 收哪些、不收哪些 ═══
✅ **语义关系**：synonyms / antonyms / hypernyms / hyponyms / coordinate_terms /
   meronyms / holonyms —— 划词弹窗里「近义词：autonomo, franco, indipendente」直接有用。
❌ **`derived` / `related` / `proverbs`**：那是**构词族与联想词**，不是语义关系
   （`casa` 的 derived 里有 `casalingo`、`casata`…），量大（十万级）且弹窗用不上。
   记账，等展示层真需要「词族」时再收 —— 收进来才发现没人用，是白做（A31 的同一条道理）。

═══ 挂到哪一层 ═══
· en 版的关系长在 `senses[i]` 上 ⇒ 用与例句同一套坐标挂到**义项**上（确定性，不猜）
· it / fr 版的关系长在**词条级** ⇒ `sense_id` 留 NULL，只挂词形
  ⚠️ 不要看见 it 版某个词只有一条义项就"顺手"挂上去 —— 那是猜。源头没说，就不说。
· `raw_tags` 是意语版给的**语境限定**（`casa` 的同义词 `stabile` 带
  「casa in senso burocratico e legale」）⇒ 原样存进 `tags`，不翻译不丢弃。

═══ 目标词不入库 ═══
关系的 `target` 只存**词形字符串**，不存 id：目标词可能根本不在我们库里
（意语版的同义词里有 `amico dell’uomo` 这种多词短语）。展示层查得到就跳转，查不到就纯文本。
这与 A27（指针类词条读取时 join，不在库里复制）是同一个原则。

用法（在 it/ 目录下）：
    python3 pipeline/ingest_relations.py            # 干跑
    python3 pipeline/ingest_relations.py --apply
    python3 pipeline/ingest_relations.py --verify
    python3 pipeline/ingest_relations.py --mutate
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))

import dbtool                                       # noqa: E402
import paths                                        # noqa: E402
from build_pronunciation_layer import word_index    # noqa: E402
from ingest_examples import sense_index             # noqa: E402
from ipa_variants import SRC_PREFIX, iter_source    # noqa: E402

SOURCES = [("en-edition", paths.KK, None), ("it-edition", paths.EDITION, "it"),
           ("fr-edition", paths.KK_FR, None)]
# 收的关系类型 → 存进 `kind` 的值（单数，与已有的 `alt_of` 同风格）
KINDS = {"synonyms": "synonym", "antonyms": "antonym", "hypernyms": "hypernym",
         "hyponyms": "hyponym", "coordinate_terms": "coordinate",
         "meronyms": "meronym", "holonyms": "holonym"}
# 明确不收（构词族/联想词，不是语义关系）
SKIP = ("derived", "related", "proverbs")
f = lambda n: format(n, ",")


def targets_of(node):
    """kaikki 的关系数组 → [(目标词, tags元组)]。**唯一解析入口。**

    ⚠️ 每一项是 dict（`{"word": "autonomo", "raw_tags": [...]}`），偶尔 `word` 是空的
       或只是个模板残渣 ⇒ 空的跳过，不造词。
    """
    out = []
    for it in (node or []):
        if not isinstance(it, dict):
            continue
        t = (it.get("word") or "").strip()
        if not t:
            continue
        tags = tuple(it.get("tags") or []) + tuple(it.get("raw_tags") or [])
        out.append((t, tags))
    return out


def collect(con, verbose=True):
    smap = sense_index(con)
    ids, _ = word_index(con)
    id2word = {i: w for i, w in con.execute("SELECT id, word FROM dict")}
    seen = {(w, k, t) for w, k, t in con.execute(
        "SELECT word_id, kind, target FROM sense_relation")}      # 已有的 alt_of，不重复
    rows, c = {}, Counter()
    for src, path, lc in SOURCES:
        for w, d in iter_source(path, src, lc):
            wid = ids.get(w)
            if wid is None:
                c["词形不在库里"] += 1
                continue
            pos = d.get("pos") or "?"
            etym = d.get("etymology_number") or 0
            # ① 词条级
            for field, kind in KINDS.items():
                for t, tags in targets_of(d.get(field)):
                    key = (wid, kind, t, None)
                    if key[:3] in seen or key in rows:
                        c["重复/已有"] += 1
                        continue
                    rows[key] = (wid, None, kind, t, tags, src,
                                 "%s:%s:%s:%s" % (SRC_PREFIX[src], w, pos, etym))
                    c[src + "·词条级·" + kind] += 1
            # ② 义项级（en 版才有）
            for i, s in enumerate(d.get("senses") or []):
                sid = smap.get((src, w, pos, etym, i))
                for field, kind in KINDS.items():
                    for t, tags in targets_of(s.get(field)):
                        key = (wid, kind, t, sid)
                        if key[:3] in seen or key in rows:
                            c["重复/已有"] += 1
                            continue
                        rows[key] = (wid, sid, kind, t, tags, src,
                                     "%s:%s:%s:%s#%d" % (SRC_PREFIX[src], w, pos, etym, i))
                        c[src + "·义项级·" + kind + ("" if sid else "（义项没收到，挂词上）")] += 1
    c["落表行数"] = len(rows)
    c["挂到义项上的"] = sum(1 for k in rows if k[3] is not None)
    return list(rows.values()), c


def gate(con, anchor=None):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("🔴 ② 词形必须在 dict 里",
         q("SELECT count(*) FROM sense_relation r WHERE NOT EXISTS"
           "(SELECT 1 FROM dict d WHERE d.id=r.word_id)"), 0),
        ("🔴 ② 挂的义项必须属于同一个词形",
         q("SELECT count(*) FROM sense_relation r JOIN sense s ON s.id=r.sense_id "
           "WHERE s.word_id <> r.word_id"), 0),
        ("🔴 ② 目标词不许为空",
         q("SELECT count(*) FROM sense_relation WHERE trim(COALESCE(target,''))=''"), 0),
        ("🔴 ② (词形,类型,目标,义项) 不许重复",
         q("SELECT count(*) FROM (SELECT word_id,kind,target,COALESCE(sense_id,-1) k FROM "
           "sense_relation GROUP BY word_id,kind,target,k HAVING count(*)>1)"), 0),
        ("🔴 ② kind 只有约定的这几种",
         q("SELECT count(*) FROM sense_relation WHERE kind NOT IN ('alt_of',%s)"
           % ",".join("'%s'" % v for v in sorted(set(KINDS.values())))), 0),
        ("🔴 ③ 不许收构词族（derived/related/proverbs）",
         q("SELECT count(*) FROM sense_relation WHERE kind IN ('derived','related','proverb')"), 0),
        ("（记账）alt_of 一条没动（基线 7,995）",
         q("SELECT count(*) FROM sense_relation WHERE kind='alt_of'"), 7995),
    ]
    if anchor is not None:
        have = set()
        for wid, kind, t in con.execute(
                "SELECT word_id, kind, target FROM sense_relation WHERE kind<>'alt_of'"):
            have.add((wid, kind, t))
        checks.append(("🔴 ① 表里有、而三版 dump 里查不到的关系", len(have - anchor), 0))
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-46s %s (期望 %s)" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    return ok


def anchor_set(con):
    """外锚：三版 dump 里实际存在的 (word_id, kind, target)。"""
    ids, _ = word_index(con)
    out = set()
    for src, path, lc in SOURCES:
        for w, d in iter_source(path, src, lc):
            wid = ids.get(w)
            if wid is None:
                continue
            nodes = [d] + list(d.get("senses") or [])
            for node in nodes:
                for field, kind in KINDS.items():
                    for t, _tags in targets_of(node.get(field)):
                        out.add((wid, kind, t))
    return out


def mutate():
    print("═══ 变异验证 A：解析判据 ═══")
    cases = [
        ("正常项", targets_of([{"word": "autonomo"}]), [("autonomo", ())]),
        ("带 raw_tags 的语境限定要留住",
         targets_of([{"word": "stabile", "raw_tags": ["senso legale"]}]),
         [("stabile", ("senso legale",))]),
        ("🔴 空词形不许造词", targets_of([{"word": ""}, {"raw_tags": ["x"]}]), []),
        ("🔴 非 dict 项跳过", targets_of(["autonomo"]), []),
        ("多词短语照收", targets_of([{"word": "amico dell’uomo"}]), [("amico dell’uomo", ())]),
    ]
    ok = True
    for name, got, want in cases:
        good = got == want
        ok &= good
        print("   %s %-40s → %s" % ("✅" if good else "🔴", name, got))

    print("\n═══ 变异验证 B：闸能不能逮住数据被改坏（备份副本上）═══")
    import contextlib
    import io
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "m.sqlite"
    shutil.copy(paths.DB, tmp)
    muts = [
        ("把 1 条关系挂到别的词的义项上",
         "UPDATE sense_relation SET sense_id=(SELECT id FROM sense WHERE word_id<>"
         "sense_relation.word_id LIMIT 1) WHERE id=(SELECT min(id) FROM sense_relation)"),
        ("塞 1 条 derived 进来",
         "INSERT INTO sense_relation (word_id,kind,target,src,src_ref) VALUES "
         "((SELECT min(id) FROM dict),'derived','x','y','z')"),
        ("塞 1 条空目标",
         "INSERT INTO sense_relation (word_id,kind,target,src,src_ref) VALUES "
         "((SELECT min(id) FROM dict),'synonym','','y','z')"),
        ("删 3 条 alt_of（阶段 2a 的成果不许被覆盖）",
         "DELETE FROM sense_relation WHERE kind='alt_of' AND id IN "
         "(SELECT id FROM sense_relation WHERE kind='alt_of' LIMIT 3)"),
        ("造一条完全重复的关系",
         "INSERT INTO sense_relation (word_id,sense_id,kind,target,src,src_ref) "
         "SELECT word_id,sense_id,kind,target,src,src_ref FROM sense_relation "
         "WHERE kind<>'alt_of' LIMIT 1"),
    ]
    caught = 0
    for name, sql in muts:
        c2 = sqlite3.connect(tmp)
        try:
            c2.execute(sql)
            c2.commit()
        except sqlite3.IntegrityError:
            c2.close()
            shutil.copy(paths.DB, tmp)
            caught += 1
            print("   ✅ 逮住 %s（UNIQUE 直接拦下）" % name)
            continue
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            good = gate(c2)
        c2.close()
        shutil.copy(paths.DB, tmp)
        caught += (not good)
        print("   %s %s" % ("✅ 逮住" if not good else "🔴 没逮住", name))
    ok &= caught == len(muts)
    print("\n   变异验证 %s（%d/%d）" % ("通过" if ok else "🔴 有洞", caught, len(muts)))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify", "mutate"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.mutate:
        ro.close()
        return 0 if mutate() else 1
    if a.verify:
        print("■ 建外锚（重扫三版 dump）", flush=True)
        return 0 if gate(ro, anchor_set(ro)) else 1

    rows, c = collect(ro)
    ro.close()
    print("\n■ 语义关系 %s 条" % f(len(rows)))
    for k, v in c.most_common(18):
        print("     %-46s %s" % (k, f(v)))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("ingest-relations",
                        expect={"__rows__": 0, "#sense_relation": len(rows)}) as s:
        s.executemany(
            "INSERT INTO sense_relation (word_id,sense_id,kind,target,tags,src,src_ref) "
            "VALUES (?,?,?,?,?,?,?)",
            [(wid, sid, kind, t, json.dumps(list(tags), ensure_ascii=False) if tags else None,
              src, ref) for wid, sid, kind, t, tags, src, ref in rows])
    print("\n■ 已落表 %s 条" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
