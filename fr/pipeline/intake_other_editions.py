#!/usr/bin/env python3
"""阶段 3c：从其余十个版本收残差词形。2026-08-22。

═══ 为什么这十版还值得收 ═══
`FR_PLAN` 的残差表：法文版收完之后，其余十版**加起来只剩 36,007** 个词形。
数字不大，但 ⭐ **十版之间自身重叠只有 1,282 条（3.5%）** ——
**96.5% 的残差只有某一版给**。砍掉任何一版就直接丢它那部分，所以要收就十版全收。

    el 16,148 · tr 14,109 · nl 3,111 · ru 1,068 · it 890
    de 650 · zh 584 · es 500 · pt 187 · ja 42

⚠️ 这些是**上界**（dump 原始字符串集与库做的差集）。真落库要过撇号归一，
   本脚本按落点重算（`[[measure-landing-not-source]]`）。

═══ 🔴 `is_lemma` 对三个版本不可信 ═══
`docs/lang/fr-CONVENTIONS.md` §一结论 2：**各版标不标变形差异极大**

    标变形（指针占比可信）：zh 78.8% · fr 73.7% · en 73.5% · it 75.8% · nl 47.7% · ja 30.3%
    **不标变形**：tr 1.1% · ru 0.5% · el 0.2%

后三版**根本不做变形标注**，它们的"非指针词形"全是假象。
⇒ 本脚本**按实测的指针占比自动判**：低于 `PTR_MIN` 的版本不采信源头的判断。
🔴 本想写 NULL 表示「未知」，但 `dict.is_lemma` 是 **NOT NULL**（第一版直接 IntegrityError）。
   ⇒ 写 **0**，含义是**「未确立为词头」，不是「确定是变形」**。
   这不只是妥协：这批行**既无义项也无变形**，而 `is_lemma` 只驱动展示与排序
   （`french.ts:186,237,248`），排在搜索最后正是对的行为 —— 我们确实没东西给它们看。
   ⚠️ 记账：拿我们自己的判据重判 tr/el/ru 三版的变形，是后续的活。

═══ 撇号 ═══
与 3b 同一约定：`’ ʼ ‘` → `'`。全库唯一约定，不能这一步破例。

用法（在 fr/ 目录下）：
    python3 pipeline/intake_other_editions.py            # 干跑
    python3 pipeline/intake_other_editions.py --apply
    python3 pipeline/intake_other_editions.py --verify
"""
import argparse
import gzip
import json
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from intake_fr_words import POS_MAP, norm_apos   # noqa: E402

# 指针占比低于这个值 ⇒ 该版不做变形标注 ⇒ 不采信它的 is_lemma
PTR_MIN = 0.05

# (键, 文件, 是否要按 lang_code 过滤)。顺序＝残差从大到小，只影响打印。
SOURCES = [
    ("el", "kaikki.org-elwiktionary-French.jsonl.gz", False),
    ("tr", "kaikki.org-trwiktionary-French.jsonl.gz", False),
    ("nl", "kaikki.org-nlwiktionary-French.jsonl.gz", False),
    ("ru", "kaikki.org-ruwiktionary-French.jsonl.gz", False),
    ("it", "itwiktionary.jsonl.gz", True),
    ("de", "dewiktionary.jsonl.gz", True),
    ("zh", "zhwiktionary.jsonl.gz", True),
    ("es", "eswiktionary.jsonl.gz", True),
    ("pt", "ptwiktionary.jsonl.gz", True),
    ("ja", "kaikki.org-jawiktionary-French.jsonl.gz", False),
]


def unaccent(s):
    nfd = unicodedata.normalize("NFD", s.lower())
    out = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return out.replace("œ", "oe").replace("æ", "ae")


def opener(p):
    return (gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz"
            else open(p, encoding="utf-8"))


def scan(key, path, need_filter, have):
    """→ (新词形 dict, entry 行 list, 该版指针占比, 统计)"""
    new = {}
    ents = []
    occ_of = Counter()
    n_ptr = n_sense = 0
    stat = Counter()
    with opener(path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if need_filter and e.get("lang_code") != "fr":
                continue
            w = norm_apos((e.get("word") or "").strip())
            if not w:
                continue
            stat["法语条目"] += 1
            pos_raw = e.get("pos") or ""
            occ = occ_of[(w, pos_raw)]
            occ_of[(w, pos_raw)] += 1
            real = False
            for s in e.get("senses") or []:
                n_sense += 1
                if s.get("form_of") or s.get("alt_of"):
                    n_ptr += 1
                elif s.get("glosses"):
                    real = True
            if w in have:
                continue
            r = new.setdefault(w, {"pos": set(), "lemma": False})
            r["pos"].add(POS_MAP.get(pos_raw, pos_raw))
            r["lemma"] |= real
            ents.append((w, POS_MAP.get(pos_raw, pos_raw), pos_raw, occ,
                         "%s-edition" % key, "kk-%s:%s:%s#%d" % (key, w, pos_raw, occ)))
    return new, ents, (n_ptr / n_sense if n_sense else 0.0), stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return verify(con)
    have = {w for (w,) in con.execute("SELECT word FROM dict")}
    print("■ 库内词形 %s" % f"{len(have):,}")
    con.close()

    all_new, all_ent, ptr_of = {}, [], {}
    print("\n%-4s %10s %10s %10s %8s  %s"
          % ("版本", "法语条目", "新词形", "累计新增", "指针占比", "is_lemma"))
    print("-" * 66)
    for key, name, filt in SOURCES:
        p = paths.DUMPS / name
        if not p.exists():
            print("%-4s 🔴 文件不存在：%s" % (key, name))
            continue
        seen = have | set(all_new)          # 🔴 前面版本已经收过的也算"已有"
        new, ents, ptr, stat = scan(key, p, filt, seen)
        ptr_of[key] = ptr
        trust = ptr >= PTR_MIN
        for w, r in new.items():
            # 🔴 `dict.is_lemma` 是 NOT NULL，存不了「未知」（第一版写 NULL 直接 IntegrityError）。
            #    tr/el/ru 不标变形 ⇒ 判不出来 ⇒ 写 **0**，含义是
            #    **「未确立为词头」，不是「确定是变形」**。
            #    这不只是占位：这 29,919 行**既无义项也无变形**，
            #    而 `is_lemma` 只驱动展示与排序（`french.ts:186,237,248`：`=== 1` / `ORDER BY`），
            #    排在搜索最后正是对的行为 —— 我们确实没东西给它们看。
            #    ⚠️ 记账：拿我们自己的判据重判这三版的变形，是后续的活。
            all_new[w] = {"pos": r["pos"], "lemma": (1 if r["lemma"] else 0) if trust else 0,
                          "unknown": not trust}
        all_ent += [e for e in ents if e[0] in new]
        print("%-4s %10s %10s %10s %7.1f%%  %s"
              % (key, f'{stat["法语条目"]:,}', f"{len(new):,}", f"{len(all_new):,}",
                 100 * ptr, "按源头判" if trust else "🔴 判不出(写0)"))

    print("\n■ 合计新词形 %s；entry 行 %s" % (f"{len(all_new):,}", f"{len(all_ent):,}"))
    n_null = sum(1 for r in all_new.values() if r.get("unknown"))
    print("   其中 is_lemma 判不出来、写 0 当「未确立为词头」的 %s（tr/el/ru 那三版）"
          % f"{n_null:,}")

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    nid = con.execute("SELECT max(id) FROM dict").fetchone()[0]
    rows = []
    for w in sorted(all_new):
        nid += 1
        r = all_new[w]
        rows.append((nid, w, unaccent(w),
                     "/".join(sorted(x for x in r["pos"] if x)) or None, r["lemma"]))
    n_pos = sum(1 for r in rows if r[3])
    n_lem = sum(1 for r in rows if r[4] == 1)
    print("■ 将写入 dict %s 行（pos 非空 %s / is_lemma=1 的 %s）"
          % (f"{len(rows):,}", f"{n_pos:,}", f"{n_lem:,}"))
    con.close()

    with dbtool.session("keep-v3-intake-others",
                        expect={"__rows__": len(rows), "pos": n_pos}) as s:
        s.executemany(
            "INSERT INTO dict (id, word, word_norm, pos, is_lemma) VALUES (?,?,?,?,?)", rows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ids = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    ent = [(ids[w], w, pos, praw, "0", occ, src, ref)
           for w, pos, praw, occ, src, ref in all_ent if w in ids]
    # 同一 (词形,词性,occ) 在同一版里只会出现一次，但**跨版**的 src_ref 前缀不同，不会撞
    print("■ 将写入 entry %s 行" % f"{len(ent):,}")
    con.close()
    with dbtool.session("keep-v3-intake-others-entry", expect={"#entry": len(ent)}) as s:
        s.executemany(
            "INSERT INTO entry (word_id, word_src, pos, pos_raw, etym_no, seq, src, src_ref) "
            "VALUES (?,?,?,?,?,?,?,?)", ent)

    return verify(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True))


def verify(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    curly = sum(1 for (w,) in con.execute("SELECT word FROM dict")
                if any(c in w for c in ("’", "ʼ", "‘")))
    checks = [
        ("🔴 词形里还有弯撇的（全库唯一约定）", curly, 0),
        ("词形重复",
         q("SELECT count(*) FROM (SELECT word FROM dict GROUP BY word HAVING count(*)>1)"), 0),
        ("word_norm 为空", q("SELECT count(*) FROM dict WHERE word_norm IS NULL OR word_norm=''"), 0),
        ("孤儿 entry", q("SELECT count(*) FROM entry e LEFT JOIN dict d ON d.id=e.word_id "
                         "WHERE d.id IS NULL"), 0),
        ("entry.src_ref 重复",
         q("SELECT count(*) FROM (SELECT src_ref FROM entry GROUP BY src_ref HAVING count(*)>1)"), 0),
        ("🔴 entry.word_src != dict.word（3a 立的规矩）",
         sum(1 for x, y in con.execute(
             "SELECT e.word_src, d.word FROM entry e JOIN dict d ON d.id=e.word_id")
             if x != y), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-42s %10s  期望 %s" % ("✓" if good else "🔴", name, f"{got:,}", f"{want:,}"))
    print("\n■ entry 各来源：")
    for src, n in con.execute("SELECT src, count(*) FROM entry GROUP BY src ORDER BY 2 DESC"):
        print("   %-14s %10s" % (src, f"{n:,}"))
    print("■ dict 总行 {:,}".format(q("SELECT count(*) FROM dict")))
    print("%s" % ("✓ 闸全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
