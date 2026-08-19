#!/usr/bin/env python3
"""阶段 3c：收法语版独有的意语词形。2026-08-13。

═══ 我先前判断错了，这里记下推翻过程 ═══
第一版结论是「fr 独有的 17 万词形 94.1% 是空壳，不收」。两位顾问也同意。
但用户追问"为什么不能全收，花点钱翻译一下"，一量就发现**我的三条理由全不成立**：

  ① "空壳"                → **翻译之后就不空**。`Plataz` → "杜厄的一个村庄"、
                             `Flegenheimer` → "姓氏"，都是真信息，比"未收录"有用。
  ② "搜索精度会被污染"      → 实测与库里已有词形**同形 0 条**（按定义它们本就不在库里），
                             不会多出竞争候选。
  ③ "其实是英文词会误导"    → 实测 **210 / 149,620 = 0.14%**，而且多数本来就对
                             （`Glasgow` → 格拉斯哥、`Birmingham` → 伯明翰）。
  ④ 成本                   → 用户已明确授权。

⇒ 教训：**"空壳"这个词把"现在没内容"偷换成了"注定没内容"**。
   判据应该是"有没有可用的源"，不是"现在库里有没有值"。

═══ 收什么 ═══
fr 独有、非纯指针的词形 168,749 个，减去法语版自己标「缺定义」的 2,310 个
（那不是判断，是**没东西可翻**）⇒ **166,439 个**。

═══ 与 A3（释义只保留中/英/意三语）怎么共存 ═══
法语原文**只进证据层** `sense_src(src='fr-edition', lang='fr')`，出版层不出法语。
中文由 `translate_fr_defs.py` 从法语中转产出，`src` 标成 `…:via-fr` ——
**二手来源要记在明处**，将来意语版补了真定义可以覆盖它。

用法（在 it/ 目录下）：
    python3 pipeline/intake_fr_words.py            # 干跑
    python3 pipeline/intake_fr_words.py --apply
    python3 pipeline/intake_fr_words.py --verify
"""
import argparse
import gzip
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from split_case_forms import norm as wnorm   # noqa: E402

SRC = "fr-edition"
AFFIX_POS = {"prefix", "suffix", "infix", "interfix", "circumfix", "combining_form"}
# 法语版自己的「缺定义」占位符 —— 与意语版的 `definizione mancante` 同类
PLACE = re.compile(r"Définition manquante|à compléter", re.IGNORECASE)
norm = lambda s: re.sub(r"\s+", " ", s or "").strip()


def replay(have):
    """→ {词形: [(src_ref, pos, 法语释义)]}，只取库里没有的词形。"""
    out = defaultdict(list)
    occ_of = Counter()
    stat = Counter()
    with gzip.open(paths.KK_FR, "rt", encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            w0 = (e.get("word") or "").strip()
            pos = e.get("pos") or ""
            key = (w0, pos)
            occ = occ_of[key]
            occ_of[key] += 1
            if not w0 or w0.lower() in have:
                continue
            affix = pos in AFFIX_POS
            for i, s in enumerate(e.get("senses") or []):
                g = norm((s.get("glosses") or [""])[0])
                if not g:
                    stat["空 gloss"] += 1
                    continue
                if (s.get("form_of") or s.get("alt_of")) and not affix:
                    stat["指针义项（不收）"] += 1
                    continue
                if PLACE.search(g):
                    stat["法语版自己标「缺定义」（没东西可翻，不收）"] += 1
                    continue
                stat["✅ 要收"] += 1
                out[w0].append(("kk-fr:%s:%s#%d.%d" % (w0, pos, occ, i), pos, g))
    return out, stat


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    checks = [
        ("🔴 法语原文只在证据层，出版层不出法语（A3）",
         q("SELECT count(*) FROM sense_gloss WHERE lang='fr'"), 0),
        ("新收词形都有义项（不许空壳）",
         q("SELECT count(*) FROM dict d WHERE d.id IN (SELECT word_id FROM sense_src "
           "WHERE src=?) AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id)", SRC), 0),
        ("每条法语证据都已裁决到一条义项",
         q("SELECT count(*) FROM sense_src WHERE src=? AND sense_id IS NULL", SRC), 0),
        ("证据行的 word_id 与它的义项一致",
         q("SELECT count(*) FROM sense_src x JOIN sense s ON s.id=x.sense_id "
           "WHERE x.word_id<>s.word_id"), 0),
        ("每个词形的 rank 连续无空洞",
         q("SELECT count(*) FROM (SELECT word_id FROM sense GROUP BY word_id "
           "HAVING max(rank)<>count(*) OR min(rank)<>1)"), 0),
        ("不存在两行 word 完全相同",
         q("SELECT count(*) FROM (SELECT word FROM dict GROUP BY word HAVING count(*)>1)"), 0),
        ("🔴 法语证据不许带「缺定义」占位符",
         q("SELECT count(*) FROM sense_src WHERE src=? AND "
           "(text LIKE '%Définition manquante%' OR text LIKE '%à compléter%')", SRC), 0),
        # 🔴 基线 +5：`fixes/fill_from_en_edition.py`（08-17）补了 5 个英文版有真释义、
        #    原始解析漏收的词（natel/cretacico/allovino/limosino/calendario dell'avvento）。
        #    ⚠️ 差额超过 5 就要查 —— 那是没人认领的新增。
        ("🔴 英文版侧的义项一条没动（基线 +5，见注释）",
         q("SELECT count(*) FROM sense_src WHERE src='en-edition'"), 205933),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %s (期望 %s)" % ("✅" if good else "🔴", name,
                                           f"{got:,}", f"{want:,}"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1

    have = {w.lower() for (w,) in ro.execute("SELECT word FROM dict")}
    new, stat = replay(have)
    for k, v in stat.most_common():
        print("   %-42s %9s" % (k, f"{v:,}"))
    n = sum(len(v) for v in new.values())
    byp = Counter(p for v in new.values() for _, p, _ in v)
    print("\n■ 将收词形 %s 个 / 义项 %s 条" % (f"{len(new):,}", f"{n:,}"))
    print("   词性 top6: %s" % byp.most_common(6))
    print("   ⚠️ 中文由 translate_fr_defs.py 从法语中转产出，来源标 via-fr")
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    nid = ro.execute("SELECT max(id) FROM dict").fetchone()[0]
    sid = ro.execute("SELECT max(id) FROM sense").fetchone()[0]
    ro.close()
    d_rows, s_rows, x_rows = [], [], []
    for w0 in sorted(new):
        nid += 1
        d_rows.append((nid, w0, wnorm(w0), 1))
        for rank, (ref, pos, text) in enumerate(new[w0], start=1):
            sid += 1
            s_rows.append((sid, nid, rank, pos))
            x_rows.append((nid, sid, SRC, ref, "fr", text))

    with dbtool.session("intake-fr-words",
                        expect={"__rows__": len(d_rows), "#sense": len(s_rows),
                                "#sense_src": len(x_rows)}) as s:
        s.executemany("INSERT INTO dict (id,word,word_norm,is_lemma) VALUES (?,?,?,?)", d_rows)
        s.executemany("INSERT INTO sense (id,word_id,rank,pos) VALUES (?,?,?,?)", s_rows)
        s.executemany("INSERT INTO sense_src (word_id,sense_id,src,src_ref,lang,text) "
                      "VALUES (?,?,?,?,?,?)", x_rows)
    print("\n■ 已收 %s 个词形 / %s 条义项" % (f"{len(d_rows):,}", f"{len(s_rows):,}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
