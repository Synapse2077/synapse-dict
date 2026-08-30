#!/usr/bin/env python3
"""阶段 5b — 收语义关系（同义/反义/上下位…）→ `sense_relation`。2026-08-30。

═══ 收哪些、不收哪些（判据同 it/fr，不重新设计）═══
✅ **语义关系**：synonyms / antonyms / hypernyms / hyponyms / coordinate_terms /
   meronyms / holonyms —— 划词弹窗里「近义词：…」直接有用。
❌ **`derived` / `related` / `proverbs`**：构词族与联想词，**不是语义关系**。
   pt 实测这两族合计 59,324 条（derived 35,138 / related 44,119 里去重前），
   收进来才发现没人用是白做。**记账，不收。**

═══ 挂到哪一层：**各版的关系长在不同层上**（2026-08-30 实测，`probes/relations.py`）═══

    版本   条目      语义关系·词条级   语义关系·义项级
    pt   399,087       51,594            0        ← 全在词条级
    en   434,036        3,838       66,427        ← 主要在义项级
    fr   304,628       15,123            0
    zh   124,246        5,282            0

🔴 **不要看见某个词只有一条义项就"顺手"挂上去** —— 那是猜。源头没说，就不说。
   挂不上的照收、`sense_id` 留 NULL：挂在词上仍然有用（弹窗要的是「这个词」的近义词）。

═══ 义项坐标：**反解库里现成的 `src_ref`，不重放 `occ`** ═══
`sense_src.src_ref` 是 `kk-en:<word>:<pos_raw>:<etym>:<occ>#<义项下标>`。
重放 `occ` 需要复现**阶段 1 当时的词表**（那时 dict 只有 411,802 行，现在 769,011）——
词表变了 `occ` 就整体错位。⇒ 改成从库里反解出 `(词, 词性, 词源号, 下标)` 索引：

    解析失败 0 ／ 键 111,020 ／ **唯一命中 110,082** ／ 多义键 938（0.8%，留 NULL）

⚠️ 多义键 = 同一个 `(词,词性,词源号,下标)` 对应多条 JSON entry（wiktextract 把一个
   维基章节切开了）。**分不清就不挂**，不猜。

═══ 三道闸 ═══
① 不变量：`word_id` 都在 dict／`sense_id` 非空时都在 sense／`kind` 在白名单内／
   `target` 非空／不动阶段 2a 写的 `alt_of` 行。
② 账：义项级挂载率必须与探针实测对得上（拼错坐标会掉到个位数）。
③ 抽样反验：随机打 25 条给人眼核 —— 「A 是 B 的近义词」对不对，闸证明不了。

用法（在 pt/ 目录下）：
    python3 -u pipeline/ingest_relations.py            # 干跑（含闸预演）
    python3 -u pipeline/ingest_relations.py --apply
    python3 -u pipeline/ingest_relations.py --verify
"""
import argparse
import gzip
import json
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from intake_edition_words import EDITIONS, norm_apos   # noqa: E402

# 复数字段名 → 存进 `kind` 的单数名
SEM = {"synonyms": "synonym", "antonyms": "antonym", "hypernyms": "hypernym",
       "hyponyms": "hyponym", "coordinate_terms": "coordinate", "meronyms": "meronym",
       "holonyms": "holonym"}
SKIP = ("derived", "related", "proverbs")
f = lambda n: format(n, ",")


def sense_index(con):
    """→ {(词, 词性, 词源号, 义项下标): sense_id}，**只收唯一命中的**。"""
    idx = defaultdict(list)
    for sid, ref in con.execute(
            "SELECT sense_id, src_ref FROM sense_src WHERE src='en-edition'"):
        if sid is None or "#" not in ref:
            continue
        left, i = ref.rsplit("#", 1)
        try:
            w, pos, etym, _occ = left[len("kk-en:"):].rsplit(":", 3)
        except ValueError:
            continue
        idx[(w, pos, etym, int(i))].append(sid)
    return {k: v[0] for k, v in idx.items() if len(v) == 1}


def targets_of(v):
    """源头的关系项可能是 {'word': …} 也可能是裸串。→ [(词, tags)]"""
    out = []
    for x in v or []:
        if isinstance(x, dict):
            t = (x.get("word") or "").strip()
            tags = x.get("tags") or []
        else:
            t = str(x).strip()
            tags = []
        if t:
            out.append((t, tags))
    return out


def scan(ids, sidx, editions):
    rows, stat, seen = [], Counter(), set()
    for ed in editions:
        path, filt = EDITIONS[ed]
        if not path.exists():
            stat["🔴 dump 不存在：" + ed] += 1
            continue
        occ_of = Counter()
        op = gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" \
            else open(path, encoding="utf-8")
        with op as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if filt and e.get("lang_code") != "pt":
                    continue
                w0 = (e.get("word") or "").strip()
                if not w0:
                    continue
                wid = ids.get(norm_apos(w0))
                if wid is None:
                    stat["词不在库里（跳过）"] += 1
                    continue
                pos_raw = e.get("pos") or ""
                etym = str(e.get("etymology_number") or 0)
                occ = occ_of[(w0, pos_raw, etym)]
                occ_of[(w0, pos_raw, etym)] += 1

                def add(kind, tgt, tags, sid, ref):
                    k = (wid, sid, kind, tgt)
                    if k in seen:
                        stat["重复（不重收）"] += 1
                        return
                    seen.add(k)
                    rows.append((wid, sid, kind, tgt,
                                 json.dumps(tags, ensure_ascii=False) if tags else None,
                                 "%s-edition" % ed, ref))

                base = "kk-%s:%s:%s:%s:%d" % (ed, w0, pos_raw, etym, occ)
                for fld, kind in SEM.items():                    # 词条级
                    for t, tags in targets_of(e.get(fld)):
                        stat["词条级·" + kind] += 1
                        add(kind, t, tags, None, base)
                for fld in SKIP:
                    stat["✗ 不收·" + fld] += len(e.get(fld) or [])
                for i, sn in enumerate(e.get("senses") or []):   # 义项级
                    sid = sidx.get((w0, pos_raw, etym, i)) if ed == "en" else None
                    for fld, kind in SEM.items():
                        tg = targets_of(sn.get(fld))
                        if tg:
                            stat["义项级·挂上了" if sid else "义项级·挂不上（sense_id=NULL）"] += len(tg)
                        for t, tags in tg:
                            add(kind, t, tags, sid, "%s#%d" % (base, i))
                    for fld in SKIP:
                        stat["✗ 不收·" + fld] += len(sn.get(fld) or [])
        stat["扫完 " + ed] += 1
    return rows, stat


def verify(con, before_alt=None):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    kinds = "','".join(SEM.values())
    checks = [
        ("word_id 不在 dict",
         q("SELECT COUNT(*) FROM sense_relation r WHERE NOT EXISTS"
           "(SELECT 1 FROM dict d WHERE d.id=r.word_id)"), 0),
        ("sense_id 非空但不在 sense",
         q("SELECT COUNT(*) FROM sense_relation r WHERE r.sense_id IS NOT NULL"
           " AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.id=r.sense_id)"), 0),
        ("target 为空",
         q("SELECT COUNT(*) FROM sense_relation WHERE TRIM(COALESCE(target,''))=''"), 0),
        ("kind 不在白名单（alt_of 是阶段 2a 的，合法）",
         q("SELECT COUNT(*) FROM sense_relation WHERE kind NOT IN ('%s','alt_of')" % kinds), 0),
        # 🔴 期望值**从写库前取**。写死行数的断言必然过期
        #    —— 字面量闸今天第二次逮到我犯同一条（第一次在 `link_table_forms.verify`）。
        ("🔴 阶段 2a 的 alt_of 行被动过",
         q("SELECT COUNT(*) FROM sense_relation WHERE kind='alt_of'"), before_alt),
        ("🔴 收了不该收的族（derived/related/proverbs）",
         q("SELECT COUNT(*) FROM sense_relation WHERE kind IN "
           "('derived','related','proverb')"), 0),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-46s %10s  (期望 %s)" % ("✅" if ok else "🔴", name, f(got), f(want)))
    print("\n   语义关系行数 %s（其中挂到义项的 %s）"
          % (f(q("SELECT COUNT(*) FROM sense_relation WHERE kind<>'alt_of'")),
             f(q("SELECT COUNT(*) FROM sense_relation WHERE kind<>'alt_of' "
                 "AND sense_id IS NOT NULL"))))
    print("\n%s" % ("✅ 全部通过" if not bad else "🔴 %d 条红" % bad))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    # 🔴 **源清单只许一份** —— 从 `EDITIONS` 派生，不手抄。
    #    2026-08-30 实测：补下八个切片后只改了 `EDITIONS`，而这四个文件
    #    （relations/audio/examples/link_table_forms）各自手抄了一份默认值 ⇒
    #    **新源一个都没被扫**，`audio` 跑完行数一条没涨。
    #    `[[refactor-mindset-code-quality]]`：同一张表在两处各存一份，
    #    没分叉纯属运气。
    ap.add_argument("--editions", default=",".join(EDITIONS))
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n_alt = ro.execute(
        "SELECT COUNT(*) FROM sense_relation WHERE kind='alt_of'").fetchone()[0]
    if a.verify:
        return verify(ro, n_alt)

    ids = {}
    for i, w in ro.execute("SELECT id, word FROM dict"):
        ids.setdefault(w, i)
    sidx = sense_index(ro)
    print("■ 义项坐标索引：唯一命中 %s 个键" % f(len(sidx)))

    rows, stat = scan(ids, sidx, [x for x in a.editions.split(",") if x])
    for k, v in sorted(stat.items()):
        print("   %-38s %10s" % (k, f(v)))
    print("   %-38s %10s" % ("→ 去重后要写入", f(len(rows))))

    w_of = {i: w for i, w in ro.execute("SELECT id, word FROM dict")}
    ro.close()
    print("\n── 抽样反验 25 条（「A 是 B 的近义词」对不对，只有人眼看得出来）──")
    random.seed(0)
    for r in random.sample(rows, min(25, len(rows))):
        print("   %-24s %-10s → %-26s %s%s"
              % (w_of.get(r[0], "?")[:24], r[2], r[3][:26], r[5],
                 "" if r[1] is None else "  [义项级]"))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    with dbtool.session("keep-v3-5b-relations",
                        expect={"#sense_relation": len(rows)}) as s:
        s.executemany(
            "INSERT OR IGNORE INTO sense_relation "
            "(word_id,sense_id,kind,target,tags,src,src_ref) VALUES (?,?,?,?,?,?,?)", rows)
    return verify(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True), n_alt)


if __name__ == "__main__":
    sys.exit(main())
