#!/usr/bin/env python3
"""阶段 3a-2：补回被「按折叠词形去重」吃掉的义项。2026-08-22。

═══ 缺陷 ═══
`build.py:483` 的去重是 `if g in rec["real_seen"]` —— 而 `rec` 是按 **`word.lower()`** 建的。
于是同一个折叠键下、**不同拼写**的两条义项，只要英文 gloss 文字相同，第二条就被丢掉：

    Andorran (n)  "Andorran"   ← 留下
    andorran (adj) "Andorran"  ← **丢掉**（文字一样）

在折叠状态下这看不出问题（反正显示在同一行）。但**阶段 3a 拆行之后就露馅了**：
实测 **56 个词形拆完一条义项都不剩**，全是族称/地名 ——
`islam`/`Islam`、`andorran`/`Andorran`、`gambien`/`Gambien`、`franco-ontarien`/`Franco-Ontarien`。
而法语的规矩恰恰是**小写作形容词（安道尔的）、大写作名词（安道尔人）**，它们是两个词。
⇒ 拆是对的，**去重的键错了**：应该按**拼写**去重，不是按折叠词形。

═══ 规模（实测，不是估的）═══
    按折叠词形去重（现状）      119,697 条
    按拼写去重（拆行后正确）    119,897 条
    ⇒ 补回 **200 条**

═══ 补回来的义项没有中文，本步**不猜** ═══
双胞胎那条有中文（`Andorran` → 安道尔人），但**不能复制过来** ——
`andorran` 是形容词，中文该是「安道尔的」。同一句英文 + 不同词性 ≠ 同一句中文。
⇒ 只落英文 gloss + `sense_src` 证据，中文留给阶段 1.5（200 条，已记账）。

用法（在 fr/ 目录下）：
    python3 fixes/recover_deduped_senses.py            # 干跑
    python3 fixes/recover_deduped_senses.py --apply
    python3 fixes/recover_deduped_senses.py --verify
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from build_entry_layer import AFFIX_POS, SRC, norm_gloss   # noqa: E402


def replay_two_keys(dump_path, folded):
    """同时按**折叠词形**和**拼写**两把尺子去重，把差集挑出来。

    → recovered[(word_src)] = [(gloss, key0, occ, idx, tags, raw, ordinal)]
      ordinal_of[src_ref] = 该义项在 dump 里的全局次序（用于给现有义项排 rank）
    """
    seen_fold, seen_spell = defaultdict(set), defaultdict(set)
    occ_of = Counter()
    recovered = defaultdict(list)
    ordinal_of = {}
    ordinal = 0
    stat = Counter()

    with open(dump_path, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("lang_code") != "fr":
                continue
            w0 = (e.get("word") or "").strip()
            if not w0 or w0.lower() not in folded:
                continue
            w = w0.lower()
            pos_raw = e.get("pos") or ""
            etym = str(e.get("etymology_number") or 0)
            key0 = (w0, pos_raw, etym)
            occ = occ_of[key0]
            occ_of[key0] += 1
            is_affix = pos_raw in AFFIX_POS
            for i, s in enumerate(e.get("senses") or []):
                if (s.get("form_of") or s.get("alt_of")) and not is_affix:
                    continue
                g = norm_gloss((s.get("glosses") or [""])[0])
                if not g:
                    continue
                ordinal += 1
                ref = "kk-en:%s:%s:%s:%d#%d" % (key0[0], key0[1], key0[2], occ, i)
                ordinal_of[ref] = ordinal
                dup_fold = g in seen_fold[w]
                dup_spell = g in seen_spell[w0]
                seen_fold[w].add(g)
                seen_spell[w0].add(g)
                if dup_spell:
                    stat["同一拼写内真重复（照旧丢弃）"] += 1
                    continue
                if dup_fold:
                    # 🔴 就是这一支：折叠尺子说重复、拼写尺子说不重复
                    stat["🔴 被折叠去重吃掉、该补回的"] += 1
                    recovered[w0].append(
                        (g, key0, occ, i, s.get("tags") or [],
                         s.get("raw_tags") or [], ordinal, ref))
                else:
                    stat["正常义项"] += 1
    return recovered, ordinal_of, stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return verify(con)

    ids = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    folded = {w.lower() for w in ids}
    print("■ 两把尺子同时跑…")
    recovered, ordinal_of, stat = replay_two_keys(paths.KK, folded)
    for k, v in sorted(stat.items()):
        print("   %-36s %10s" % (k, f"{v:,}"))
    n = sum(len(v) for v in recovered.values())
    print("   %-36s %10s（落在 %s 个拼写上）"
          % ("→ 要补回的义项", f"{n:,}", f"{len(recovered):,}"))

    miss = [w for w in recovered if w not in ids]
    print("   🔴 拼写在库里找不到 dict 行的：%d %s" % (len(miss), miss[:5]))

    print("\n── 样本 ──")
    for w in sorted(recovered)[:10]:
        cur = con.execute("SELECT count(*) FROM sense WHERE word_id=?",
                          (ids[w],)).fetchone()[0] if w in ids else -1
        print("   %-18r 现有义项 %d → 补 %d 条：%s"
              % (w, cur, len(recovered[w]), recovered[w][0][0][:44]))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    return apply_(con, ids, recovered, ordinal_of, n)


def apply_(con, ids, recovered, ordinal_of, n):
    eid = dict(con.execute("SELECT src_ref, id FROM entry"))
    # 现有义项的 dump 次序：靠它的 sense_src.src_ref 反查
    ord_of_sense = {}
    for sid, ref in con.execute(
            "SELECT sense_id, src_ref FROM sense_src "
            "WHERE src='en-edition' AND sense_id IS NOT NULL"):
        if ref in ordinal_of:
            ord_of_sense[sid] = ordinal_of[ref]

    nid = con.execute("SELECT max(id) FROM sense").fetchone()[0]
    new_sense, new_gloss, new_src, ranks = [], [], [], []
    st = Counter()

    for w, items in recovered.items():
        if w not in ids:
            st["🔴 跳过：拼写无 dict 行"] += len(items)
            continue
        wid = ids[w]
        cur = list(con.execute("SELECT id FROM sense WHERE word_id=?", (wid,)))
        seq = [(ord_of_sense.get(s[0], 10 ** 12 + s[0]), "old", s[0]) for s in cur]
        for (g, key0, occ, i, tags, raw, ordinal, ref) in items:
            nid += 1
            seq.append((ordinal, "new", nid))
            ent_ref = "kk-en:%s:%s:%s:0" % (key0[0], key0[1], key0[2])
            new_sense.append((nid, wid, 0, key0[1], eid.get(ent_ref)))
            new_gloss.append((nid, "en", "equivalent", 0, g, SRC))
            new_src.append((wid, nid, SRC, ref, "en", g,
                            json.dumps({"tags": tags, "raw_tags": raw}, ensure_ascii=False)))
            st["补回义项"] += 1
        seq.sort()
        for r, (_, _, sid) in enumerate(seq, 1):
            ranks.append((r, sid))

    # 词性用 entry 的映射值（与 2a 一致）
    from build_entry_layer import POS_MAP
    new_sense = [(i, w_, r_, POS_MAP.get(p_, p_), e_) for i, w_, r_, p_, e_ in new_sense]

    for k, v in sorted(st.items()):
        print("   %-32s %8s" % (k, f"{v:,}"))
    print("   %-32s %8s" % ("重排 rank", f"{len(ranks):,}"))
    con.close()

    with dbtool.session("keep-v3-dedup",
                        expect={"#sense": len(new_sense),
                                "#sense_gloss": len(new_gloss),
                                "#sense_src": len(new_src)}) as s:
        s.executemany("UPDATE sense SET rank=-rank WHERE id=?", [(x,) for _, x in ranks])
        s.executemany(
            "INSERT INTO sense (id,word_id,rank,pos,entry_id) VALUES (?,?,?,?,?)", new_sense)
        s.executemany(
            "INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) VALUES (?,?,?,?,?,?)",
            new_gloss)
        s.executemany(
            "INSERT INTO sense_src (word_id,sense_id,src,src_ref,lang,text,raw_tags) "
            "VALUES (?,?,?,?,?,?,?)", new_src)
        s.executemany("UPDATE sense SET rank=? WHERE id=?", ranks)

    return verify(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True))


def verify(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("🔴 既无义项也无变形的 dict 行（3a 拆出来的空行必须清零）",
         q("SELECT count(*) FROM dict d "
           "LEFT JOIN sense s ON s.word_id=d.id "
           "LEFT JOIN inflection i ON i.word_id=d.id "
           "WHERE s.id IS NULL AND i.id IS NULL"), 0),
        ("rank 不从 1 连续的词形",
         q("SELECT count(*) FROM (SELECT word_id FROM sense GROUP BY word_id "
           "HAVING max(rank)<>count(*) OR min(rank)<>1)"), 0),
        ("没有任何 gloss 的 sense",
         q("SELECT count(*) FROM sense s LEFT JOIN sense_gloss g ON g.sense_id=s.id "
           "WHERE g.sense_id IS NULL"), 0),
        ("孤儿 sense", q("SELECT count(*) FROM sense s LEFT JOIN dict d ON d.id=s.word_id "
                         "WHERE d.id IS NULL"), 0),
        ("挂到不存在 entry 上的 sense",
         q("SELECT count(*) FROM sense s LEFT JOIN entry e ON e.id=s.entry_id "
           "WHERE s.entry_id IS NOT NULL AND e.id IS NULL"), 0),
        ("sense_src.src_ref 重复", q("SELECT count(*) FROM (SELECT src_ref FROM sense_src "
                                     "GROUP BY src_ref HAVING count(*)>1)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-52s %8s  期望 %s" % ("✓" if good else "🔴", name, f"{got:,}", f"{want:,}"))
    print("\n%s" % ("✓ 闸全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
