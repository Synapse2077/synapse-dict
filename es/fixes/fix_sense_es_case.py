#!/usr/bin/env python3
"""补收因大小写匹配失败而漏掉的西语版义项。2026-08-06。

═══ 这是 `ingest_es_senses.py`（2026-08-05）的一个 bug ═══
那个脚本用 `word` **精确匹配** dump 与库内 lemma：

    both = [w for w in cache if w in lemmas]

而西语版 dump 保留了正字法大小写（`Japón`、`Chile`、`María`），我们的库把专名
压成了小写（`japón`、`chile`、`maría`）——于是这些词头一条义项都没收进来。
实测漏了 **3,039 条**：

    797 个 lemma 一条都没收                       987 条
    1,663 个已收的词，dump 另有大小写写法带额外义项  2,052 条

═══ 🔴 合并是被迫的，所以必须留下拆回去的凭据 ═══
dump 里 1,716 组词头 casefold 后同名，其中**有些是真不同的词**：

    virgo（处女／处女膜）  ←→  Virgo（处女座）
    be（字母 B）          ←→  Be（铍的元素符号）
    mayo（五月）          ←→  Mayo（专名）

我们的库是「一个词形一行、大小写压平」——这本身是个已知缺陷（全库 1,899 个小写专名
与普通名词挤在一行，2026-08-06 查出，尚未修）。在那个缺陷修好之前，义项**只能**挂到
唯一那一行上。

⇒ 新增 `src_word` 列，记 dump 的**原始拼写**。将来拆分专名时，
  `where src_word='Virgo'` 就能把该走 Virgo 的义项整批摘出来，不用重扫 dump。
  不记这一列，今天的合并就是不可逆的信息损失。

排序：**本词形的义项在前，其他拼写的接在后面**，这样已落库的 idx 不变、新的往后追加，
不会重排已有数据（`UNIQUE(word, idx)` 也就不会撞）。

用法：
    python3 -m es.fixes.fix_sense_es_case            # 只报告
    python3 -m es.fixes.fix_sense_es_case --apply
"""
import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

CACHE = paths.WORK / "edition_senses_es.jsonl"


def load_cache() -> dict:
    out = {}
    with CACHE.open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            out[d["word"]] = d["senses"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    cache = load_cache()
    by_ci = collections.defaultdict(list)
    for w in cache:
        by_ci[w.casefold()].append(w)

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    lemmas = {w: i for w, i in con.execute(
        "SELECT word, id FROM dict WHERE is_lemma=1")}
    # 🔴 别用 defaultdict：循环里读 have[w] 会把键创建出来，
    #    之后 `w not in have` 恒为假，统计会骗人（2026-08-06 踩过）。
    have: dict = {}
    for w, i, g in con.execute("SELECT word, idx, gloss FROM sense_es"):
        have.setdefault(w, {})[i] = g
    con.close()

    rows, stat = [], collections.Counter()
    touched_words = set()
    for w, did in lemmas.items():
        spells = by_ci.get(w.casefold())
        if not spells:
            continue
        existing = have.get(w, {})
        # 本词形优先，其余按字母序 —— 保证已落库的 idx 不被重排
        order = ([w] if w in cache else []) + sorted(x for x in spells if x != w)
        idx = 0
        added = 0
        for sp in order:
            for s in cache[sp]:
                if idx not in existing:                # 这个位置还没有 → 要补
                    rows.append((w, did, idx, s["g"], s.get("pos"), s.get("pt"),
                                 json.dumps(s.get("tags") or [], ensure_ascii=False),
                                 json.dumps(s.get("raw") or [], ensure_ascii=False),
                                 None, None, "es-edition", sp))
                    added += 1
                idx += 1
        if added:
            touched_words.add(w)
            stat["新增义项"] += added
            stat["整词全新" if not existing else "已有词追加"] += 1

    print(f"待补 {stat['新增义项']:,} 条义项，涉及 {len(touched_words):,} 个词")
    print(f"  其中整词全新 {stat['整词全新']:,}，已有词追加 {stat['已有词追加']:,}")
    print("\n■ 抽样（词 / dump 原拼写 / 义项）：")
    for r in rows[:12]:
        print(f"    {r[0]:<16} ← {r[11]:<16} {r[3][:56]}")

    if not args.apply:
        print("\n未加 --apply，不写库。")
        return

    with dbtool.session("fix-sense-es-case", expect={}) as s:
        # 先加列并把已有行回填成自身拼写（它们都来自精确匹配）
        s.execute("ALTER TABLE sense_es ADD COLUMN src_word TEXT")
        s.execute("UPDATE sense_es SET src_word = word WHERE src_word IS NULL")
        s.executemany(
            "INSERT INTO sense_es"
            "(word,dict_id,idx,gloss,pos,pos_title,tags,raw_tags,zh,zh_src,src,src_word)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    n = con.execute("SELECT COUNT(*) FROM sense_es").fetchone()[0]
    nw = con.execute("SELECT COUNT(DISTINCT word) FROM sense_es").fetchone()[0]
    dup = con.execute("SELECT COUNT(*) FROM (SELECT word,idx FROM sense_es "
                      "GROUP BY 1,2 HAVING COUNT(*)>1)").fetchone()[0]
    nosrc = con.execute("SELECT COUNT(*) FROM sense_es WHERE src_word IS NULL").fetchone()[0]
    diff = con.execute("SELECT COUNT(*) FROM sense_es WHERE src_word <> word").fetchone()[0]
    con.close()
    print(f"\n落库后 sense_es {n:,} 行 / {nw:,} 词")
    print(f"  (word,idx) 重复 {dup}   src_word 为空 {nosrc}   src_word≠word（合并进来的）{diff:,}")
    assert dup == 0 and nosrc == 0


if __name__ == "__main__":
    main()
