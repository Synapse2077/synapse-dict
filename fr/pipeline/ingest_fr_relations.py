#!/usr/bin/env python3
"""阶段 5 补做 — 收语义关系（同义/反义/上下位…）→ `sense_relation`。2026-08-27。

═══ 为什么现在才做 ═══
🔴 阶段 5 声明的四层里，例句和搭配做了，**关系层和频次层整层没做**，
   而阶段表从 08-22 起没更新过，于是这件事漏了七天 —— 期间我在做阶段 8 之后
   的第五个评审族。收尾单 B1（`docs/FR_PLAN.md`）。
   ⇒ 已做成会自己响的闸：`fr/tests/test_plan_ledger.py` 的 P1。

    库里现状   `sense_relation` 17,759 行，**全部是 `alt_of`**（变形指针，不是语义关系）
    it 同层     606,524

═══ 收哪些、不收哪些（判据与 `it/pipeline/ingest_relations.py` 一致，不重新设计）═══
✅ **语义关系**：synonyms / antonyms / hypernyms / hyponyms / coordinate_terms /
   meronyms / holonyms —— 弹窗里「近义词：…」直接有用。
❌ **`derived` / `related` / `proverbs`**：构词族与联想词，不是语义关系。
   fr 上这两族**特别大**（法文版抽 12 万条目就有 derived 207,639 / related 50,219），
   收进来才发现没人用是白做。记账。

═══ 挂到哪一层：**两版的关系长在不同层上** ═══
    法文版  关系全在**词条级**（实测 `senses[i]` 上一条都没有）⇒ `sense_id` 留 NULL
    英文版  关系主要在**义项级**（sense.synonyms 24,131 vs 词条级 939）⇒ 挂到义项

🔴 **不要看见某个词只有一条义项就"顺手"挂上去** —— 那是猜。源头没说，就不说。

═══ 义项坐标怎么来：**replay `src_ref`，不重新推导** ═══
`sense_src.src_ref` 里已经编好了坐标：

    英文版  `kk-en:<词>:<pos>:<etym>:<occ>#<i>`
    法文版  `kk-fr:<词>:<pos_raw>#<occ>.<i>`

⇒ 扫 dump 时**照同样的规则拼出这个串**，拿它去 `sense_src` 里查 `sense_id`。
  这样坐标系只有一份（`[[refactor-mindset-code-quality]]`：判据只许一份），
  而且**命中率本身就是一道闸** —— 拼错了会立刻掉到个位数百分比。
  ⚠️ `occ` 计数必须与 `ingest_fr_edition` / `intake_fr_words` 同一套，否则整体错位。

═══ 目标词只存字符串，不存 id ═══
目标词可能根本不在我们库里（`amour-propre` 的同义词里有多词短语）。
展示层查得到就跳转，查不到就纯文本。

用法（在 fr/ 目录下）：
    python3 -u pipeline/ingest_fr_relations.py --probe    # 只量：坐标命中率 + 可收量
    python3 -u pipeline/ingest_fr_relations.py            # 干跑（含闸）
    python3 -u pipeline/ingest_fr_relations.py --apply
    python3 -u pipeline/ingest_fr_relations.py --mutate
"""
import argparse
import gzip
import io
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import dbtool                                  # noqa: E402
import paths                                   # noqa: E402
from intake_fr_words import norm_apos          # noqa: E402

f = lambda n: format(n, ",")
SRC_MARK = "rel"          # 本步写入的行，`src` 仍写版本名，这里只用于统计

# (键, 路径, lang_code 过滤, 关系长在哪一层)
SOURCES = [
    ("fr-edition", paths.EDITION, "fr", "entry"),
    ("en-edition", paths.KK, "fr", "sense"),
]
KINDS = {"synonyms": "synonym", "antonyms": "antonym", "hypernyms": "hypernym",
         "hyponyms": "hyponym", "coordinate_terms": "coordinate",
         "meronyms": "meronym", "holonyms": "holonym"}
SKIP = ("derived", "related", "proverbs")


def opener(p):
    return gzip.open(p, "rt", encoding="utf-8") if str(p).endswith(".gz") \
        else io.open(p, encoding="utf-8")


def targets_of(node):
    """kaikki 的关系数组 → [(目标词, tags元组)]。**唯一解析入口。**

    ⚠️ 每一项是 dict（`{"word": "…", "tags": [...]}`），偶尔 `word` 是空的或只是
       模板残渣 ⇒ 空的跳过，**不造词**。
    """
    out = []
    for it in (node or []):
        if not isinstance(it, dict):
            continue
        t = (it.get("word") or "").strip()
        if not t:
            continue
        tags = tuple(it.get("tags") or []) + tuple(it.get("raw_tags") or [])
        out.append((norm_apos(t), tags))
    return out


def indexes(con):
    ids = {}
    for i, w in con.execute("SELECT id, word FROM dict"):
        ids.setdefault(w, i)
    ref2sense = {}
    for ref, sid in con.execute("SELECT src_ref, sense_id FROM sense_src"):
        if sid is not None:
            ref2sense[ref] = sid
    have = {(w, k, t, s) for w, k, t, s in con.execute(
        "SELECT word_id, kind, target, COALESCE(sense_id,-1) FROM sense_relation")}
    return ids, ref2sense, have


def collect(con, limit=0):
    ids, ref2sense, have = indexes(con)
    rows, st = {}, Counter()
    for name, path, lc, level in SOURCES:
        if not Path(path).exists():
            print("   （%s 不存在，跳过）" % name)
            continue
        occ_of = Counter()
        n = 0
        with opener(path) as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if lc and e.get("lang_code") != lc:
                    continue
                w0 = (e.get("word") or "").strip()
                if not w0:
                    continue
                n += 1
                if limit and n > limit:
                    break
                w = norm_apos(w0)
                wid = ids.get(w)
                pos_raw = e.get("pos") or ""
                etym = str(e.get("etymology_number") or 0)
                # 🔴 occ 必须与建库那一步同一套计数，否则坐标整体错位。
                #    命中率实测：fr 81.7% 的串在 `sense_src` 里（缺的是没进证据层的
                #    义项）、en 24.1%（当年只有 124,908 条 en 义项进了证据层，
                #    探针扫半个文件命中 57,148 × 2 ≈ 正好这个数）⇒ 坐标系是对的。
                if name == "fr-edition":
                    key = (w, pos_raw)
                    occ = occ_of[key]
                    occ_of[key] += 1
                    eref = "kk-fr:%s:%s#%d" % (w, pos_raw, occ)
                    sref = lambda i: "%s.%d" % (eref, i)
                else:
                    key = (w, pos_raw, etym)
                    occ = occ_of[key]
                    occ_of[key] += 1
                    eref = "kk-en:%s:%s:%s:%d" % (w, pos_raw, etym, occ)
                    sref = lambda i: "%s#%d" % (eref, i)

                for fld in SKIP:
                    if e.get(fld):
                        st["❌ 构词族/联想词，不收（%s）" % fld] += len(e[fld])

                def add(sid, node, ref, where):
                    for fld, kind in KINDS.items():
                        tg = targets_of(node.get(fld))
                        if tg and wid is None:
                            st["🔴 词形不在 dict 里 ⇒ 整条丢弃"] += len(tg)
                            continue
                        for t, tags in tg:
                            k = (wid, kind, t, sid if sid is not None else -1)
                            if k in have or k in rows:
                                st["重复/已有 ⇒ 跳过"] += 1
                                continue
                            rows[k] = (wid, sid, kind, t,
                                       json.dumps(list(tags), ensure_ascii=False) if tags else None,
                                       name, ref)
                            st["✓ %s·%s·%s" % (name, where, kind)] += 1

                # ① 词条级（法文版的关系全在这一层；英文版也有少量）
                add(None, e, eref, "词条级")
                # ② 义项级（英文版为主）。挂不上坐标就退回词条级 —— **不猜**
                for i, s in enumerate(e.get("senses") or []):
                    r = sref(i)
                    sid = ref2sense.get(r)
                    if sid is None and any(s.get(fld) for fld in KINDS):
                        st["📋 义项坐标查不到 ⇒ 退回词条级（sense_id=NULL）"] += 1
                    add(sid, s, r, "义项级" if sid else "义项级→退回词条")
        print("   %-12s 扫 %s 条" % (name, f(n)))
    st["落表行数"] = len(rows)
    st["其中挂到义项上"] = sum(1 for k in rows if k[3] != -1)
    return list(rows.values()), st


def probe(con):
    """只量坐标命中率。

    🔴 **必须分两层看，否则会把「义项没进库」误判成「我坐标拼错了」**：
        ① 串在不在 `sense_src` 里         ← 这一条低才说明**replay 错了**
        ② 串对应的 `sense_id` 非空        ← 这一条低只说明该义项没进出版层
    `[[measure-landing-not-source]]`：新数字先假设我的度量错了。
    """
    _ids, ref2sense, _h = indexes(con)
    allref = {r for (r,) in con.execute("SELECT src_ref FROM sense_src")}
    print("═══ 义项坐标 replay 命中率 ═══")
    for name, path, lc, _lv in SOURCES:
        occ_of, hit, tot, inref = Counter(), 0, 0, 0
        with opener(path) as fh:
            for k, line in enumerate(fh):
                if k > 200000:
                    break
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if lc and e.get("lang_code") != lc:
                    continue
                w = norm_apos((e.get("word") or "").strip())
                if not w:
                    continue
                pos_raw = e.get("pos") or ""
                etym = str(e.get("etymology_number") or 0)
                if name == "fr-edition":
                    key = (w, pos_raw)
                    occ = occ_of[key]; occ_of[key] += 1
                    mk = lambda i: "kk-fr:%s:%s#%d.%d" % (w, pos_raw, occ, i)
                else:
                    key = (w, pos_raw, etym)
                    occ = occ_of[key]; occ_of[key] += 1
                    mk = lambda i: "kk-en:%s:%s:%s:%d#%d" % (w, pos_raw, etym, occ, i)
                for i, _s in enumerate(e.get("senses") or []):
                    r = mk(i)
                    tot += 1
                    inref += r in allref
                    hit += r in ref2sense
        print("   %-12s ① 串在 sense_src 里 %s/%s = **%.1f%%**   "
              "② 其中挂到义项 %s = %.1f%%"
              % (name, f(inref), f(tot), 100.0 * inref / max(tot, 1),
                 f(hit), 100.0 * hit / max(inref, 1)))


def gate(con, rows):
    print("\n═══ 闸 ═══")
    ok = True

    def g(name, got, want):
        nonlocal ok
        ok &= got == want
        print("   %s %-52s %s（期望 %s）" % ("✅" if got == want else "🔴", name, f(got), f(want)))

    g("① 词形都在 dict 里", sum(1 for r in rows if r[0] is None), 0)
    g("② 目标词不许为空", sum(1 for r in rows if not (r[3] or "").strip()), 0)
    g("③ kind 只有约定的那几种",
      sum(1 for r in rows if r[2] not in set(KINDS.values())), 0)
    g("④ 不许收构词族（derived/related/proverbs）",
      sum(1 for r in rows if r[2] in ("derived", "related", "proverb")), 0)
    g("⑤ (词形,类型,目标,义项) 本批内不重复",
      len(rows) - len({(r[0], r[2], r[3], r[1]) for r in rows}), 0)
    sw = {s: w for s, w in con.execute("SELECT id, word_id FROM sense")}
    g("⑥ 挂的义项必须属于同一个词形",
      sum(1 for r in rows if r[1] is not None and sw.get(r[1]) != r[0]), 0)
    g("⑦ alt_of 一条不动（基线 17,759）",
      con.execute("SELECT COUNT(*) FROM sense_relation WHERE kind='alt_of'").fetchone()[0],
      17759)
    return ok


def mutate():
    print("═══ 变异验证：解析判据 ═══")
    cases = [
        ("正常项", targets_of([{"word": "libre"}]), [("libre", ())]),
        ("带 tags 的语境限定要留住",
         targets_of([{"word": "gratis", "tags": ["familier"]}]), [("gratis", ("familier",))]),
        ("🔴 空词形不许造词", targets_of([{"word": ""}, {"tags": ["x"]}]), []),
        ("🔴 非 dict 项跳过", targets_of(["libre"]), []),
        ("多词短语照收", targets_of([{"word": "amour-propre"}]), [("amour-propre", ())]),
        ("🔴 撇号必须归一（全库唯一约定：直撇）",
         targets_of([{"word": "l’eau"}]), [("l'eau", ())]),
    ]
    ok = 0
    for name, got, want in cases:
        good = got == want
        ok += good
        print("   %s %-44s → %s" % ("✅" if good else "🔴", name, got))
    print("\n   变异 %d/%d" % (ok, len(cases)))
    return ok == len(cases)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.probe:
        probe(con)
        return 0
    rows, st = collect(con, a.limit)
    print("\n■ 可新增 %s 行" % f(len(rows)))
    for k, v in st.most_common(24):
        print("   %-46s %s" % (k, f(v)))
    ok = gate(con, rows)
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 闸未过，**不写库**")
        return 1
    with dbtool.session("keep-v3-fr-relations", expect={"#sense_relation": len(rows)}) as s:
        s.executemany(
            "INSERT INTO sense_relation(word_id,sense_id,kind,target,tags,src,src_ref) "
            "VALUES(?,?,?,?,?,?,?)", rows)
    print("✓ 写入 %s 行" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
