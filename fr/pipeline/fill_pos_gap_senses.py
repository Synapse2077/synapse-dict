#!/usr/bin/env python3
"""补**词性缺口义项**：法文版有这个意思，而我们连这个词性都没有。2026-08-25。

═══ 这批是什么 ═══
裁决（`adjudicate_fr_defs.py`）按词性硬过滤时，有 **10,579 条**法语释义
连一条同词性的候选义项都找不到 —— 当时记账留了下来。逐条读过样本，
**它们不是裁决失败，是真的义项缺口**：

    mandrin   [adj] 我们只有「卡盘，心轴」  + Relatif à Mandres-la-Côte, commune de la Haute-Marne.
    civilisé  [n]   我们只有「文明的，开化的」+ Personne sociable, évoluée, policée.
    inférieur [n]   我们只有「较低的，劣等的」+ Celui qui est au-dessous d'un autre en rang…
    à pic     [n]   我们只有「恰逢其时／陡峭的」+ Endroit d'une montagne dont la pente est très escarpée.

形状很清楚：**法语系统性地把形容词名词化、把地名形容词化**，而我们只收了其中一半。
    n 5,360 · adj 3,287 · adv 777 · phr 320 · intj 275 · v 217 …
    7,636 个 (词形, 词性) 组 / 7,361 个词形；其中 **7,624 组在 `entry` 层已有行**（99.8%）

═══ 这一步只建结构，**一个中文都不生成** ═══
建出 `sense` + `sense_gloss(lang='fr')` 之后，**现成的整条流水线自动接手**：
    geo/name/demonym/misc/pointer 五个模板   取数条件就是「有法语、没中文」⇒ 免费吃掉一批
    gloss_translate.py                      剩下的才送模型
⇒ 不写第二份翻译代码（`[[refactor-mindset-code-quality]]`）。

⚠️ **这批义项是可见的**（`hidden=0`），用户查 `senior` 会多出一条形容词义项 ——
   与裁决那批（只给已有义项配一行法语原文）不同，**它改变用户看到的内容**。
   用户 2026-08-25 明确说「直接做吧」。

═══ rank ═══
`sense` 有 `UNIQUE(word_id, rank)`。新义项一律**接在该词现有 rank 之后**，
不动已有展示顺序 —— 这批多是次要词义，排后面也对。

═══ 可逆 ═══
`[[prefer-reversible-designs]]`：三处写入都由 `src='fr-edition:gap'` 这一个标记串起来，
`--undo` 一条命令原样撤回，**不动任何已有行**。

用法（在 fr/ 目录下）：
    python3 -u pipeline/fill_pos_gap_senses.py            # 干跑
    python3 -u pipeline/fill_pos_gap_senses.py --sample 20
    python3 -u pipeline/fill_pos_gap_senses.py --apply
    python3 -u pipeline/fill_pos_gap_senses.py --verify
    python3 -u pipeline/fill_pos_gap_senses.py --undo
    # 之后照常跑模板 + 翻译，它们会自动认领这批
"""
import argparse
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbtool                                  # noqa: E402
import paths                                   # noqa: E402
from pipeline import adjudicate_fr_defs as A   # noqa: E402
from pipeline import gloss_clean               # noqa: E402

SRC = "fr-edition:gap"


def plan(con):
    """→ [(word_id, pos, [(src_id, 洗过的法语), …]), …]，以及统计。"""
    st = Counter()
    decided = A.load_decided()
    pub = set(con.execute(
        "SELECT s.word_id, g.text FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
        "WHERE g.lang='fr'"))
    sen = defaultdict(list)
    for wid, sid, rank, pos in con.execute(
            "SELECT word_id, id, rank, pos FROM sense WHERE hidden=0 ORDER BY rank"):
        sen[wid].append((sid, rank, pos or ""))

    grp = defaultdict(list)
    w_of = dict(con.execute("SELECT id, word FROM dict"))   # clean 的词条头判据要词形
    for sid, wid, t, ref in con.execute(
            "SELECT id, word_id, text, src_ref FROM sense_src WHERE src='fr-edition'"):
        c = gloss_clean.clean(t, w_of.get(wid))
        if not c:
            continue
        if (wid, c) in pub:
            st["已出版"] += 1
            continue
        if sid in decided:
            st["裁决问过（模型判定不挂）"] += 1
            continue
        p = A.pos_key(A.ref_pos(ref))
        cands = [x for x in sen.get(wid, []) if A.pos_key(x[2]) == p]
        if cands and len(cands) <= A.S_CAP:
            st["🔴 还有没裁决的（应先跑 adjudicate）"] += 1
            continue
        if len(cands) > A.S_CAP:
            st["📋 候选超过 %d，本步也不建（避免给超多义词再加行）" % A.S_CAP] += 1
            continue
        grp[(wid, p)].append((sid, c))

    out = []
    for (wid, p), lst in grp.items():
        # 组内按洗过的文本去重 —— 同一个意思不建两条义项
        seen, keep = set(), []
        for sid, c in lst:
            k = " ".join(c.split()).lower()
            if k in seen:
                st["组内重复的法语释义（不重复建行）"] += 1
                continue
            seen.add(k)
            keep.append((sid, c))
        st["要建的新义项"] += len(keep)
        out.append((wid, p, keep))
    st["涉及 (词形,词性) 组"] = len(out)
    return out, st


def build_rows(con, groups):
    """→ (新义项要插的行, 证据归属, 每组的起始 rank)。"""
    maxrank = dict(con.execute("SELECT word_id, max(rank) FROM sense GROUP BY word_id"))
    ent = {}
    for eid, wid, pos in con.execute("SELECT id, word_id, pos FROM entry ORDER BY id"):
        ent.setdefault((wid, pos), eid)
    rows = []
    for wid, p, lst in groups:
        r = maxrank.get(wid, 0)
        for sid, txt in lst:
            r += 1
            rows.append({"word_id": wid, "rank": r, "pos": p,
                         "entry_id": ent.get((wid, p)), "src_id": sid, "fr": txt})
        maxrank[wid] = r
    return rows


def apply_rows(con, rows):
    n_ent = sum(1 for r in rows if r["entry_id"])
    print("\n■ 落库：新义项 %s 行（其中 %s 行能挂上 entry）"
          % (format(len(rows), ","), format(n_ent, ",")))
    with dbtool.session("keep-v3-posgap",
                        expect={"#sense": len(rows), "#sense_gloss": len(rows)}) as s:
        for r in rows:
            cur = s.execute(
                "INSERT INTO sense (word_id, rank, pos, entry_id, hidden) "
                "VALUES (?,?,?,?,0)", (r["word_id"], r["rank"], r["pos"], r["entry_id"]))
            sid = cur.lastrowid
            s.execute("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?,'fr','definition',0,?,?)", (sid, r["fr"], SRC))
            s.execute("UPDATE sense_src SET sense_id=? WHERE id=? AND sense_id IS NULL",
                      (sid, r["src_id"]))
    print("✓ 写入完成（撤回：--undo）")
    return 0


def verify():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ok = True

    def chk(name, got, want):
        nonlocal ok
        ok &= got == want
        print("   %s %-52s %10s  期望 %s"
              % ("✓" if got == want else "🔴", name, format(got, ","), format(want, ",")))

    ids = [i for (i,) in con.execute(
        "SELECT sense_id FROM sense_gloss WHERE src=?", (SRC,))]
    print("■ 本步新建义项 %s 条" % format(len(ids), ","))
    if not ids:
        return 0
    q = ",".join("?" * len(ids))
    chk("① 新义项里有 rank 与已有行冲突的",
        con.execute("SELECT count(*) FROM (SELECT word_id, rank FROM sense "
                    "GROUP BY word_id, rank HAVING count(*)>1)").fetchone()[0], 0)
    chk("② 新义项的 pos 为空",
        con.execute("SELECT count(*) FROM sense WHERE id IN (%s) "
                    "AND (pos IS NULL OR pos='')" % q, ids).fetchone()[0], 0)
    # ③ 词性必须与法文版证据一致（这一步的立身之本）
    bad = 0
    for ref, pos in con.execute(
            "SELECT x.src_ref, s.pos FROM sense_src x JOIN sense s ON s.id=x.sense_id "
            "JOIN sense_gloss g ON g.sense_id=s.id AND g.src=? ", (SRC,)):
        if A.pos_key(A.ref_pos(ref)) != A.pos_key(pos or ""):
            bad += 1
    chk("③ 新义项的词性与法文版证据不一致", bad, 0)
    # ④ 可逆性：每一行都能由「证据 + clean」重建
    bad = 0
    for txt, src_txt, w in con.execute(
            "SELECT g.text, x.text, d.word FROM sense_gloss g "
            "JOIN sense_src x ON x.sense_id=g.sense_id AND x.src='fr-edition' "
            "JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id "
            "WHERE g.src=?", (SRC,)):
        if gloss_clean.clean(src_txt, w) != txt:
            bad += 1
    chk("④ 新行无法由「证据 + clean」重建", bad, 0)
    chk("⑤ 新义项已经有中文了（本步不该生成中文）",
        con.execute("SELECT count(*) FROM sense_gloss WHERE lang='zh' AND sense_id IN (%s)"
                    % q, ids).fetchone()[0], 0)
    n = con.execute("SELECT count(*) FROM sense WHERE hidden=0").fetchone()[0]
    print("■ 可见义项 %s" % format(n, ","))
    print("%s" % ("✓ 闸全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


def undo():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ids = [i for (i,) in con.execute(
        "SELECT sense_id FROM sense_gloss WHERE src=?", (SRC,))]
    if not ids:
        print("■ 没有本步写入的行")
        return 0
    q = ",".join("?" * len(ids))
    nzh = con.execute("SELECT count(*) FROM sense_gloss WHERE sense_id IN (%s)" % q,
                      ids).fetchone()[0]
    print("■ 撤回：义项 %s 条、释义行 %s 条（含之后生成的中文）"
          % (format(len(ids), ","), format(nzh, ",")))
    with dbtool.session("keep-v3-posgap-undo",
                        expect={"#sense": -len(ids), "#sense_gloss": -nzh}) as s:
        s.execute("UPDATE sense_src SET sense_id=NULL WHERE sense_id IN (%s)" % q, ids)
        s.execute("DELETE FROM sense_gloss WHERE sense_id IN (%s)" % q, ids)
        s.execute("DELETE FROM sense WHERE id IN (%s)" % q, ids)
    print("✓ 已撤回")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--undo", action="store_true")
    a = ap.parse_args()
    if a.verify:
        return verify()
    if a.undo:
        return undo()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    groups, st = plan(con)
    for k, v in st.most_common():
        print("   %-48s %10s" % (k, format(v, ",")))
    rows = build_rows(con, groups)
    print("\n■ 按词性：%s" % Counter(r["pos"] for r in rows).most_common(10))

    if a.sample:
        words = dict(con.execute("SELECT id, word FROM dict"))
        zh = defaultdict(list)
        for wid, t in con.execute(
                "SELECT s.word_id, g.text FROM sense s "
                "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' WHERE s.hidden=0"):
            zh[wid].append(t)
        xs = random.Random(5).sample(rows, min(a.sample, len(rows)))
        print("\n══ 抽样 %d 条新义项 ══" % len(xs))
        for r in xs:
            print("   %-22s [%-4s rank%d] 现有中文 %s"
                  % (words[r["word_id"]][:22], r["pos"], r["rank"],
                     zh[r["word_id"]][:2]))
            print("        新增法语: %s" % r["fr"][:100])

    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    con.close()
    apply_rows(sqlite3.connect(paths.DB), rows)
    return verify()


if __name__ == "__main__":
    sys.exit(main())
