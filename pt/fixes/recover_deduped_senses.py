#!/usr/bin/env python3
"""阶段 3a-2：补回被「按折叠词形去重」吃掉的义项。2026-08-29。

═══ 缺陷 ═══
`build.py:434` 的去重是 `if g in rec["real_seen"]` —— 而 `rec` 是按 **`word.lower()`** 建的。
于是同一个折叠键下、**不同拼写**的两条义项，只要英文 gloss 文字相同，第二条就被丢掉：

    B (字母)  "The second letter of the Portuguese alphabet"   ← 留下
    b (字母)  同一句                                            ← **丢掉**（文字一样）

在折叠状态下这看不出问题（反正显示在同一行）。但**阶段 3a 拆行之后就露馅了**。
⇒ 拆是对的，**去重的键错了**：应该按**拼写**去重，不是按折叠词形。

═══ 规模（pt 实测 2026-08-29，不是抄 fr 的）═══
    补回 **24 条**（fr 那轮 200 条），落在 24 个拼写上，
    绝大多数是**大写字母词条**（`B`/`D`/`F`/`G`/`H`/`I`/`K`/`L`…）——
    它们的 gloss「The Nth letter of the Portuguese alphabet」与小写行逐字相同。

⚠️ **pt 与 fr 在这里的形状不同，别照抄结论**：
   3a 拆行后"一条义项都不剩"的有 **444 行**，但其中只有 24 行是本缺陷的受害者。
   另外 420 行是**正当的**：小写是真变形（`abacaxis` = abacaxi 的复数、
   `acaba` = acabar 的变位），大写才是专名（`Abissínia` 阿比西尼亚）——
   拆完小写行留着变形、大写行拿走专名义，这正是拆分要达到的结果。
   fr 那轮 56 行**全部**是受害者，pt 只有 5%。

═══ 补回来的义项没有中文，本步**不猜** ═══
双胞胎那条有中文，但**不能复制过来** —— 同一句英文 + 不同词性 ≠ 同一句中文。
⇒ 只落英文 gloss + `sense_src` 证据，中文留给阶段 1.5（24 条，已记账）。

用法（在 pt/ 目录下）：
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
            if e.get("lang_code") != "pt":
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
        # 🔴 2026-08-29 改判据。fr 那条写的是「空行必须清零」，对 fr 成立、对 pt 不成立：
        #    pt 有 2 行既无义项也无变形，而它们是**源数据缺陷且 kaikki 自己标了**——
        #       rubina  tags=['feminine','no-gloss']
        #       Mito    tags=['Brazil','empty-gloss','error-lua-exec','no-gloss']
        #    英文版那两条的 glosses 本来就是 None（`Mito` 那条还是 Lua 模板执行错误），
        #    **没有东西可以捞回来**，删行又会丢掉 `rubina` 已有的音标。
        #
        #    ⇒ 判据换成一条**自足、且真能逮到 bug** 的：**空行必须源头就空。**
        #      `definition`/`translation` 是阶段 0 冻结的迁移锚点（只读、不再被写）。
        #      如果哪一步把义项搬丢了，那两列**仍然有值**而 sense 没了 ⇒ 当场红。
        #      源头就没释义的行，那两列本来也是空的 ⇒ 不报。
        #      这条不会过期：它问的是"有没有搬丢"，不是"有几行"。
        ("🔴 空行必须源头就空（有 definition/translation 却没 sense = 搬丢了）",
         q("SELECT count(*) FROM dict d "
           "WHERE NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id) "
           "  AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id) "
           "  AND (TRIM(COALESCE(d.definition,''))<>'' "
           "       OR TRIM(COALESCE(d.translation,''))<>'')"), 0),
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
