#!/usr/bin/env python3
"""补收 573 个被大小写去重吃掉的西语版词头。2026-08-06。

═══ 怎么漏的 ═══
`ingest_edition.py:277` 判「这个词我们已经有了」用的是**折叠大小写**的集合：

    have = {w.lower() for (w,) in conn.execute("SELECT word FROM dict")}
    if not w or w.lower() in have:      # 🔴 Cefalópodos.lower() == cefalópodos
        continue

于是凡是**小写形已在库**的大写词头，一个都没进来。而它们和小写形根本不是一个词：

    cefalópodo    Adjetivo / Sustantivo     属于头足纲的；头足类动物   ← 库里有
    cefalópodos   （上一条的阳性复数变形）                              ← 库里有
    Cefalópodos   Sustantivo propio         头足纲（Cephalopoda）这个分类单元 ← 缺

同族的还有 `Anfibios`(两栖纲) / `Aves`(鸟纲) / `Moluscos`(软体动物门) /
`Amazonia`(亚马逊流域) / `Dallas` / `COVID-19` / `CREA` / `COPE`。

⭐ 这是 `docs/SCHEMA.md` §9 缺陷② 的同一个根：**大小写承载词汇区别**
   （`virgo`/`Virgo`、`be`/`Be`、`chile`/`Chile`），折叠掉就丢词。
   区别在于②是「压成一行」，本脚本这批是「整个词头没进来」。

🔴 **绝不能把它们的义项挂到小写行上** —— 那正是缺陷②的做法，
   会让 `cefalópodos`（复数变形）平白多出一条「头足纲」的释义。必须建新行。

═══ 收什么（573 个词头 / 590 条义项）═══
    461  姓氏      释义就一个词 `Apellido.`
     70  地名/机构/普通名词   Amazonia / Dallas / CREA / COPE / COVID-19 / huique
     35  人名      `Nombre de pila de varón|mujer`
      7  生物分类单元 Cefalópodos / Anfibios / Aves / Moluscos / Acantopterigios …

按用户方针①「词汇尽量全，其他语言版本的词汇尽量收集」全收。
姓氏那 461 条的中文由 `translate_intake.py --tmpl` 确定性生成（上一轮 `Apellido.`
就占 41.1%，模板现成），不花钱。

═══ 列怎么写 ═══
完全沿用 `ingest_edition.py` 的约定，这批词和 2026-08-03 收的 369,001 行同构：
  · 西语 gloss 进 `definition_es`（`definition` 是「英文版原值」，这批词英文版没有）
  · `translation` 留空，交 `translate_intake.py`
  · `phonetic` 取西语版音标（有就有，没有不编）
  · `is_lemma=1`：这批全是词条不是变形（`pos_title` 不以 "Forma " 开头，缓存已过滤）

═══ ⚠️ 落库后必须改 `spanish.ts` 的 exactQuery ═══
`WHERE word = ? COLLATE NOCASE ORDER BY is_lemma DESC LIMIT 1` ——
新行 `is_lemma=1` 会**压过**已有的 `cefalópodos`(is_lemma=0)，
导致搜「cefalópodos」返回分类单元而不是复数形。必须把**精确大小写命中**
加成第一排序键。见本脚本末尾的提示。

用法（在仓库根）：
    python3 -m es.pipeline.ingest_missing_propers            # 扫描 + 计划，不写库
    python3 -m es.pipeline.ingest_missing_propers --apply
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sqlite3          # noqa: E402
import dbtool           # noqa: E402
import kaikki_util as K  # noqa: E402
import paths            # noqa: E402
from pipeline.build import POS_MAP, meta_of, unaccent  # noqa: E402
# 音标归一直接复用 ingest_edition 那一份 —— 它与 apply_edition_confirm 用同一套表达式，
# 在 46.6 万个落点上与库内值 95.6% 逐字一致。另写一份就会漂移。
from pipeline.ingest_edition import pick_ipa  # noqa: E402

CACHE = paths.WORK / "edition_senses_es.jsonl"
INSERT_COLS = ("word", "word_norm", "phonetic", "phonetic_raw", "phonetic_src",
               "pos", "is_lemma", "definition_es", "meta")


def missing_words() -> set:
    """缓存里有、`sense_es` 里没有的词头。

    比对要认 `src_word`：`fix_sense_es_case.py` 把 `Japón` 的义项挂到了库里的
    `japón` 行上，并把 dump 原拼写存进 `src_word`。不认它会把那 2,469 个词
    误判成「未收」。
    """
    cache = {}
    for line in CACHE.open(encoding="utf-8"):
        d = json.loads(line)
        cache[d["word"]] = d["senses"]
    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    covered = set()
    for w, sw in con.execute("SELECT word, src_word FROM sense_es"):
        covered.add(sw or w)
        covered.add(w)
    dbw = {w for (w,) in con.execute("SELECT word FROM dict")}
    con.close()
    miss = {w for w in cache if w not in covered}
    # 🔴 精确拼写去重（不折叠大小写）—— 折叠正是漏收的原因
    clash = {w for w in miss if w in dbw}
    assert not clash, f"这些词精确拼写已在 dict，不该重复插：{sorted(clash)[:5]}"
    return miss, cache


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    miss, cache = missing_words()
    print(f"待补词头 {len(miss):,}，义项 {sum(len(cache[w]) for w in miss):,} 条")

    # 回 dump 取完整条目（缓存只存了 gloss/pos/tags，没有音标）
    print(f"扫西语版整包取音标与词性：{paths.EDITION.name}")
    recs = {}
    for w, e in K.iter_edition():
        if e.get("lang_code") != "es" or w not in miss:
            continue
        r = recs.setdefault(w, {"pos": [], "ipa": None, "ipa_raw": None,
                                "gl": [], "meta": [], "seen": set()})
        pos = e.get("pos") or "unknown"
        p = POS_MAP.get(pos, pos)
        if p not in r["pos"]:
            r["pos"].append(p)
        if r["ipa"] is None:
            r["ipa"], r["ipa_raw"] = pick_ipa(e)
        for s in (e.get("senses") or []):
            g = re.sub(r"\s+", " ", (s.get("glosses") or [""])[0]).strip()
            if not g or g in r["seen"]:
                continue
            r["seen"].add(g)
            r["gl"].append(g)
            r["meta"].append(meta_of(s, pos))

    print(f"  dump 里取到 {len(recs):,} 个（缓存里有 {len(miss):,}）")
    lost = miss - set(recs)
    if lost:
        print(f"  🔴 dump 里没取到：{len(lost)}  {sorted(lost)[:8]}")

    rows, stat = [], collections.Counter()
    for w, r in sorted(recs.items()):
        if not r["gl"]:
            stat["无义项，不收"] += 1
            continue
        rows.append((w, unaccent(w), r["ipa"], r["ipa_raw"],
                     "es-edition" if r["ipa"] else None,
                     "/".join(r["pos"]) if r["pos"] else None, 1,
                     "\n".join(r["gl"]),
                     json.dumps(r["meta"], ensure_ascii=False) if r["meta"] else None))
        stat["收"] += 1
        stat["有音标" if r["ipa"] else "无音标"] += 1
    for k, v in stat.most_common():
        print(f"  {k:<12}{v:>6,}")

    # 行数必须与 meta 条数对齐（`novia` 那个坑）
    bad = [r[0] for r in rows
           if len(r[7].split("\n")) != len(json.loads(r[8] or "[]"))]
    print(f"断言 definition_es 行数 ≠ meta 条数的：{len(bad)}  {bad[:5]}")
    assert not bad

    dbtool.sample_check(
        [(r[0], r[5] or "-", (r[2] or "-")[:18], r[7].split("\n")[0][:38]) for r in rows[:12]],
        12, ("词", "词性", "音标", "西语版释义"))

    if not args.apply:
        print("\n未加 --apply，不写库。")
        return

    ph = ",".join("?" * len(INSERT_COLS))
    with dbtool.session("ingest-missing-propers", expect={
            "__rows__": +len(rows),
            "definition_es": +len(rows),
            "meta": +len(rows),
            "pos": +sum(1 for r in rows if r[5]),
            "phonetic": +sum(1 for r in rows if r[2]),
            "phonetic_raw": +sum(1 for r in rows if r[3]),
            "phonetic_src": +sum(1 for r in rows if r[4]),
    }) as s:
        s.executemany(
            f"INSERT INTO dict ({','.join(INSERT_COLS)}) VALUES ({ph})", rows)

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    n = con.execute("SELECT COUNT(*) FROM dict WHERE translation IS NULL").fetchone()[0]
    con.close()
    print(f"\ntranslation 为空的行：{n:,}（= 本批 {len(rows):,}，待 translate_intake 填）")
    print("\n下一步：")
    print("  ① python3 -m es.pipeline.translate_intake --tmpl --apply   # 姓氏/人名，免费")
    print("  ② python3 -m es.pipeline.translate_intake --llm            # 剩下的")
    print("  ③ python3 -m es.pipeline.ingest_es_senses                  # 进 sense_es")
    print("  ⚠️ 别忘了改 packages/dict-core/src/spanish.ts 的 exactQuery 排序，"
          "否则搜 cefalópodos 会返回分类单元")


if __name__ == "__main__":
    main()
