#!/usr/bin/env python3
"""阶段 1.5a — 收葡语原文释义 → `sense_src` / `sense` / `sense_gloss(lang='pt')`。2026-08-30。

⚠️ **本步不花一分钱。** 收原文释义、建出版层义项、把中文版白送的中文放进去，全是确定性的。
   翻译是 **1.5b**（`translate_defs.py`），单独报价、单独跑。
   两件事分开的理由同例句那轮：**捆在一起就没法先看"免费能拿到多少"再决定买多少。**

═══ 规模（实测 2026-08-30，`probes/stage15.py`，九版全量）═══

    零义项词头                48,810
      至少一版有真释义         48,192  (98.7%)
      🔴 中文版直接给中文       2,921   ← **免费**
      源头压根没释义             618   ← 花钱也买不到
      要送翻译                45,271   （67,582 条义项 / 290 万字符，均 43）

═══ 🔴 只收葡语版的定义，别的版另算 ═══
`[[gloss-three-languages]]`：**每个维基版只给"自己语言的词"写定义，对外语词只写翻译。**
探针样例逐条印证：

    pt 版  abacelar  → "ato de plantar bacelos de maneira a criar videiras novas"   ✅ 真定义
    fr 版  abdomen   → "Abdomen."                                                   ❌ 抄回原词
    fr 版  DDT       → "DDT (dichlorodiphényltrichloroéthane)."                     ❌ 同上
    ru 版  autogiro  → "автожир"                                                    ❌ 俄语翻译

⇒ 本步**只收 `pt` 版**（覆盖 46,751 / 48,192 = 97%）。其余 1,441 个词进收尾单，
  它们的"释义"是别的语言的对应词，性质不同，要另设判据 —— **不混进同一批**。

═══ 中文版的中文：**免费，先拿** ═══
zh 版给 2,921 个词的 2,956 条义项**全部带汉字**（实测 100%）。直接进 `sense_gloss(lang='zh')`。
⚠️ 但仍要建 `sense_src` 留底 —— 出版层的每个字都要答得出"哪来的"。

═══ 判据：什么算「真释义」═══
`senses[].glosses[0]` 非空，**且该义项没有 `form_of`/`alt_of`** ——
指针义项归变形层（阶段 2 定的规矩，这里不重开）。

用法（在 pt/ 目录下）：
    python3 -u pipeline/ingest_pt_senses.py            # 干跑
    python3 -u pipeline/ingest_pt_senses.py --apply
    python3 -u pipeline/ingest_pt_senses.py --verify
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
from build_entry_layer import POS_MAP   # noqa: E402
from intake_edition_words import EDITIONS, norm_apos   # noqa: E402

f = lambda n: format(n, ",")
# 「含中文吗」的判据在 `dbtool.has_han` 一份 —— 只查基本区会把化学元素字误判成非中文。
has_han = dbtool.has_han


def scan(need, editions=("pt", "zh")):
    """→ per_word[word] = [(ed, pos_raw, occ, i, gloss, tags)]，按 dump 顺序。"""
    per, stat = defaultdict(list), Counter()
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
                w = norm_apos((e.get("word") or "").strip())
                if w not in need:
                    continue
                pos_raw = e.get("pos") or ""
                occ = occ_of[(w, pos_raw)]
                occ_of[(w, pos_raw)] += 1
                for i, sn in enumerate(e.get("senses") or []):
                    if sn.get("form_of") or sn.get("alt_of"):
                        stat["指针义项（归变形层，不收）"] += 1
                        continue
                    g = (sn.get("glosses") or [""])[0].strip()
                    if not g:
                        continue
                    per[w].append((ed, pos_raw, occ, i, g,
                                   json.dumps({"tags": sn.get("tags") or [],
                                               "raw_tags": sn.get("raw_tags") or []},
                                              ensure_ascii=False)))
                    stat["%s·义项" % ed] += 1
        stat["扫完 " + ed] += 1
    return per, stat


def build(con, per):
    ids = {}
    for i, w in con.execute("SELECT id, word FROM dict"):
        ids.setdefault(w, i)
    ent = defaultdict(list)
    for eid, wid, pos in con.execute("SELECT id, word_id, pos FROM entry"):
        ent[wid].append((pos, eid))
    # 保险：rank 从该词已有的最大值往后排（判据修对之后应该都是 0，但不靠"应该"）
    maxrank = defaultdict(int)
    for wid_, r_ in con.execute("SELECT word_id, MAX(rank) FROM sense GROUP BY word_id"):
        maxrank[wid_] = r_
    src_rows, sense_rows, gloss_rows, stat = [], [], [], Counter()
    for w in sorted(per):
        wid = ids.get(w)
        if wid is None:
            stat["🔴 词不在库里"] += 1
            continue
        if maxrank[wid]:
            stat["🔴 这个词已经有义项了（判据该拦住的）"] += 1
        rank = maxrank[wid]
        for ed, pos_raw, occ, i, g, tags in per[w]:
            rank += 1
            pos = POS_MAP.get(pos_raw, pos_raw)
            eid = next((x for p, x in ent.get(wid, []) if p == pos), None)
            ref = "kk-%s:%s:%s:%d#%d" % (ed, w, pos_raw, occ, i)
            sense_rows.append((wid, rank, pos, eid))
            src_rows.append((wid, ed + "-edition", ref, "zh" if ed == "zh" else "pt",
                             g, tags))
            # 出版层：葡语原文进 lang='pt'；中文版的中文**直接进 lang='zh'**（免费）
            lang = "zh" if (ed == "zh" and has_han(g)) else "pt"
            gloss_rows.append((wid, rank, lang, "definition", 0, g,
                               "%s-edition" % ed))
            stat["出版义项·" + lang] += 1
    return src_rows, sense_rows, gloss_rows, stat


def verify(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("sense.word_id 不在 dict",
         q("SELECT COUNT(*) FROM sense s WHERE NOT EXISTS"
           "(SELECT 1 FROM dict d WHERE d.id=s.word_id)"), 0),
        ("sense_gloss 指向不存在的 sense",
         q("SELECT COUNT(*) FROM sense_gloss g WHERE NOT EXISTS"
           "(SELECT 1 FROM sense s WHERE s.id=g.sense_id)"), 0),
        ("sense_src 指向不存在的 sense",
         q("SELECT COUNT(*) FROM sense_src x WHERE x.sense_id IS NOT NULL AND NOT EXISTS"
           "(SELECT 1 FROM sense s WHERE s.id=x.sense_id)"), 0),
        ("(word_id, rank) 重复",
         q("SELECT COUNT(*) FROM (SELECT word_id,rank FROM sense GROUP BY 1,2 HAVING COUNT(*)>1)"), 0),
        ("🔴 出版层出现空释义",
         q("SELECT COUNT(*) FROM sense_gloss WHERE TRIM(text)=''"), 0),
        # ⚠️ 基线 3 条，**全是七月建库的老数据**（`src='unknown'`），不是本步带进来的：
        #      cookie → 'Cookie，HTTP Cookie'   para- → 'para-'   -opia → '-opia'
        #    已进收尾单 C16。本步自己写的行必须是 0 ⇒ 判据限定在本步的 src 上。
        ("🔴 lang='zh' 的释义里没有汉字（本步）",
         sum(1 for (t,) in con.execute(
             "SELECT text FROM sense_gloss WHERE lang='zh' AND src LIKE '%-edition'")
             if not has_han(t)), 0),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-46s %10s  (期望 %s)" % ("✅" if ok else "🔴", name, f(got), f(want)))
    print("\n   sense %s ／ sense_gloss pt %s ／ zh %s ／ 仍无中文的义项 %s"
          % (f(q("SELECT COUNT(*) FROM sense")),
             f(q("SELECT COUNT(*) FROM sense_gloss WHERE lang='pt'")),
             f(q("SELECT COUNT(*) FROM sense_gloss WHERE lang='zh'")),
             f(q("SELECT COUNT(*) FROM sense s WHERE NOT EXISTS"
                 "(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='zh')"))))
    print("\n%s" % ("✅ 全部通过" if not bad else "🔴 %d 条红" % bad))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return verify(ro)
    # 🔴 判据走 **`sense.word_id` 直连**，不走 `entry` 链。
    #    第一版写成 `NOT EXISTS(entry JOIN sense ON s.entry_id=e.id)` ——
    #    而 `sense.entry_id` 可空（实测 21 条为空）⇒ 那 20 个词有义项却不在查询路径上，
    #    被当成"零义项"，插 rank=1 时撞上已有行。
    #    **是 `UNIQUE(word_id, rank)` 拦住的** —— 这次闸救了我，数据没写进去。
    #    ⇒ 「这个词有没有出版义项」本来就该直接问 `sense`，而且它正好与那个 UNIQUE 同键。
    need = {w for (w,) in ro.execute(
        "SELECT d.word FROM dict d WHERE d.is_lemma=1 AND NOT EXISTS("
        "  SELECT 1 FROM sense s WHERE s.word_id=d.id)")}
    print("■ 零义项词头 %s" % f(len(need)))
    per, stat = scan(need)
    for k, v in sorted(stat.items()):
        print("   %-30s %10s" % (k, f(v)))
    src_rows, sense_rows, gloss_rows, bstat = build(ro, per)
    ro.close()
    for k, v in sorted(bstat.items()):
        print("   %-30s %10s" % (k, f(v)))
    print("   %-30s %10s" % ("→ sense 行", f(len(sense_rows))))
    print("   %-30s %10s" % ("→ 覆盖词头", f(len(per))))

    print("\n── 抽样反验 15 条 ──")
    random.seed(0)
    for w in random.sample(sorted(per), min(15, len(per))):
        ed, _p, _o, _i, g, _t = per[w][0]
        print("   [%s] %-22s %s" % (ed, w[:22], g[:78]))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    with dbtool.session("keep-v3-15a-pt-senses",
                        expect={"#sense": len(sense_rows),
                                "#sense_src": len(src_rows),
                                "#sense_gloss": len(gloss_rows)}) as s:
        s.executemany("INSERT INTO sense (word_id,rank,pos,entry_id) VALUES (?,?,?,?)",
                      sense_rows)
        sid = {(w, r): i for i, w, r in s.execute("SELECT id, word_id, rank FROM sense")}
        s.executemany(
            "INSERT OR IGNORE INTO sense_src "
            "(word_id,sense_id,src,src_ref,lang,text,raw_tags) VALUES (?,?,?,?,?,?,?)",
            [(w, sid[(w, r)], sr, rf, lg, tx, tg)
             for (w, sr, rf, lg, tx, tg), (_w, r, _p, _e) in zip(src_rows, sense_rows)])
        s.executemany(
            "INSERT OR IGNORE INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
            "VALUES (?,?,?,?,?,?)",
            [(sid[(w, r)], lg, k, q, tx, sc) for w, r, lg, k, q, tx, sc in gloss_rows])
    return verify(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True))


if __name__ == "__main__":
    sys.exit(main())
