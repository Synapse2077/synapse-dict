#!/usr/bin/env python3
"""补词性缺口那批里，**中文与已有义项完全相同**的重复义项。2026-08-25。

═══ 判据只有一条，而且是按含义的 ═══
`pipeline/fill_pos_gap_senses.py` 新建了 10,478 条义项。其中一小撮和该词
**已有的某条义项中文一模一样** —— 用户点开会看到两条相同的释义。

    stipulaire   「托叶的」   ← Qui a rapport aux stipules…
    nonante-sept 「九十七」   ← 97.
    réutilisable 「可重复使用的」← Que l’on peut utiliser de nouveau.

🔴 **判据不是"词性是不是一类"。** 我先按词性分类去圈，三族全是混的：
    phr ← prov  224 条：有真重复（`pas de nouvelles` 两边都是「没有消息就是好消息」），
                       也有**真的第二种解读**（`qui vole un œuf` 的「偷窃无论轻重都应受罚」）
    adj ← num   235 条：有重复（`sept` 两边都是「七」），
                       也有**序数**（`quatre-vingt-dix` 的 adj 是「第九十」，不是「九十」）
    n   ← num   394 条：多数是真的（「以70结尾的年份」「编号为16的事物」）
⇒ 按词性砍会连真内容一起砍掉。**唯一可确定性判定的是「中文一样」** —— 166 条，1.6%。

═══ 不是简单隐掉：先把法语原文挪走 ═══
这批新义项**带着法语原文**（那是它唯一的新增价值）。直接隐 = 连原文一起丢。
⇒ 先把它的法语挪到老义项上（老义项没有这句时），再隐掉新义项。

═══ 可逆 ═══
`hidden` 置回 0、删掉挪过去的 `src='fr-edition:gap-moved'` 行即可。

用法（在 fr/ 目录下）：
    python3 -u fixes/dedup_gap_senses.py            # 干跑
    python3 -u fixes/dedup_gap_senses.py --apply
    python3 -u fixes/dedup_gap_senses.py --undo
"""
import argparse
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

GAP = "fr-edition:gap"
MOVED = "fr-edition:gap-moved"


def key(s):
    """比中文用的尺子：只留汉字与字母数字（标点/空格不参与）。"""
    return re.sub(r"[^一-鿿 A-Za-z0-9]", "", s or "").replace(" ", "")


def plan(con):
    new = {i for (i,) in con.execute(
        "SELECT sense_id FROM sense_gloss WHERE src=?", (GAP,))}
    zh = defaultdict(list)
    for wid, sid, t in con.execute(
            "SELECT s.word_id, s.id, g.text FROM sense s "
            "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' WHERE s.hidden=0"):
        zh[wid].append((sid, t))
    fr = dict(con.execute(
        "SELECT sense_id, text FROM sense_gloss WHERE lang='fr' AND src=?", (GAP,)))
    have_fr = set(con.execute(
        "SELECT sense_id, text FROM sense_gloss WHERE lang='fr'"))
    seq0 = defaultdict(int)
    for sid, in con.execute(
            "SELECT sense_id FROM sense_gloss WHERE lang='fr' AND kind='definition'"):
        seq0[sid] += 1

    out = []
    for wid, lst in zh.items():
        seen = {}
        for sid, t in sorted(lst):          # 小 id 在前 ⇒ 老的先占位
            k = key(t)
            if not k:
                continue
            if k in seen and sid in new:
                keep = seen[k]
                txt = fr.get(sid)
                move = txt if txt and (keep, txt) not in have_fr else None
                out.append((sid, keep, txt, move))
            else:
                seen.setdefault(k, sid)
    return out, seq0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)

    if a.undo:
        ids = [i for (i,) in con.execute(
            "SELECT sense_id FROM sense_gloss WHERE src=?", (MOVED,))]
        n = con.execute("SELECT count(*) FROM sense_gloss WHERE src=?",
                        (MOVED,)).fetchone()[0]
        hid = con.execute("SELECT count(*) FROM sense s JOIN sense_gloss g "
                          "ON g.sense_id=s.id AND g.src=? WHERE s.hidden=1",
                          (GAP,)).fetchone()[0]
        print("■ 撤回：挪过去的法语 %s 行、隐掉的义项 %s 条" % (n, hid))
        with dbtool.session("keep-v3-gapdedup-undo", expect={"#sense_gloss": -n}) as s:
            s.execute("DELETE FROM sense_gloss WHERE src=?", (MOVED,))
            s.execute("UPDATE sense SET hidden=0 WHERE id IN "
                      "(SELECT sense_id FROM sense_gloss WHERE src=?)", (GAP,))
        print("✓ 已撤回（%d 条老义项的挪入行已删）" % len(ids))
        return 0

    rows, seq0 = plan(con)
    n_move = sum(1 for *_x, m in rows if m)
    print("■ 中文与已有义项完全相同的新义项：%s 条" % format(len(rows), ","))
    print("   其中法语原文可以挪到老义项上的：%s 条（其余老义项已有同句）"
          % format(n_move, ","))
    words = dict(con.execute("SELECT id, word FROM dict"))
    wof = dict(con.execute("SELECT id, word_id FROM sense"))
    print("\n── 样本 8 条 ──")
    for sid, keep, txt, move in rows[:8]:
        print("   %-24s 隐 #%d → 并入 #%d ｜ 法语%s"
              % (words[wof[sid]][:24], sid, keep, "挪走" if move else "（老义项已有）"))

    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0

    ins = []
    for sid, keep, txt, move in rows:
        if move:
            ins.append((keep, seq0[keep], move))
            seq0[keep] += 1
    ids = [r[0] for r in rows]
    q = ",".join("?" * len(ids))
    with dbtool.session("keep-v3-gapdedup", expect={"#sense_gloss": len(ins)}) as s:
        s.executemany("INSERT OR IGNORE INTO sense_gloss "
                      "(sense_id,lang,kind,seq,text,src) VALUES (?,'fr','definition',?,?,?)",
                      [(k, q_, t, MOVED) for k, q_, t in ins])
        s.execute("UPDATE sense SET hidden=1 WHERE id IN (%s)" % q, ids)
    print("\n✓ 挪走法语 %s 行；隐掉重复义项 %s 条（撤回：--undo）"
          % (format(len(ins), ","), format(len(ids), ",")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
