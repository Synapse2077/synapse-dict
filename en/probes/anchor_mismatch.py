#!/usr/bin/env python3
"""1.5c 追问：**锚不吻合的时候，B 会不会被锚拖错**。2026-09-07。

`slice_review.py` 报了 230 条「疑似锚泄漏」，但那个判据只说得出
「B 用了锚的词而 A 没用」—— 锚本来就吻合时这**是对的**。
拿那 230 条的印象去决定全量带不带锚，等于拿嫌疑当证据。

═══ 真正的用例长什么样 ═══
锚是**词条级**的：`legacy_gloss` 一个 word_id 一行，而 `sense` 一个词有多条。
所以「锚不吻合」不是随机发生的，它有确定的产地：

    单义词        → 锚几乎必然吻合（`polysyndactyly` 只有一个意思）
    多义词的首义   → 锚大概率吻合（ECDICT 先写常见义）
    🔴 多义词的**非首义** → 锚是**别的义项的**中文，这才是会拖错的地方
       （`turtle` 第 4 义「印刷机弯板」配 ref「海龟」）

⇒ 本脚本按 (词的义项数 × 该义项的 rank) 分层，量各层的命中率，
   再**从最高风险层随机抽**给人眼裁决。不排序取头部
   （`[[criteria-narrower-than-you-think]]` 的反面：样本必须来自会出错的那一格）。

═══ 判据的边界（说清楚它判不了什么）═══
「B 命中 ref 片段」是**形式**判据，它只定位嫌疑区，不判对错。
对错这一格必须人看 —— 所以输出是**并排三栏**（英文释义 / A / B / ref），
让人一眼能答「B 说的是不是这条 en 释义的意思」。

⚠️ 只读，不写库。
    cd en && python3 probes/anchor_mismatch.py
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import json
import random
import re
import sqlite3

import paths

OUT = paths.WORK / "slice"
HAN = re.compile(r"[㐀-䶿一-鿿]")


def load(p):
    d = {}
    for ln in p.open(encoding="utf-8"):
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if "id" in o:
            d[o["id"]] = o
    return d


def frags(ref):
    if not ref:
        return set()
    s = re.sub(r"^[a-z]{1,5}\.\s*|\s*/\s*[a-z]{1,5}\.\s*", " ", ref)
    s = re.sub(r"\[[^\]]{1,6}\]", " ", s)            # [化] [地质] 这类学科标记不算内容片段
    return {x.strip() for x in re.split(r"[；;，,、/\s]+", s)
            if len(x.strip()) >= 2 and HAN.search(x)}


def bucket(n):
    return "1 义" if n == 1 else "2-3 义" if n <= 3 else "4-9 义" if n <= 9 else "10+ 义"


ORDER = ["1 义", "2-3 义", "4-9 义", "10+ 义"]


def main():
    A, B = load(OUT / "slice_noanchor.jsonl"), load(OUT / "slice_anchor.jsonl")
    both = [i for i in B if i in A]

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    meta = {}
    for chunk in (both[i:i + 900] for i in range(0, len(both), 900)):
        qs = ",".join("?" * len(chunk))
        for sid, wid, w, pos, rk, en, lg in con.execute(
                "SELECT s.id, s.word_id, d.word, s.pos, s.rank, g.text, lg.text "
                "FROM sense s JOIN dict d ON d.id=s.word_id "
                "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='en' "
                "LEFT JOIN legacy_gloss lg ON lg.word_id=s.word_id "
                "WHERE s.id IN (%s)" % qs, chunk):
            meta[sid] = dict(wid=wid, word=w, pos=pos, rank=rk, en=en, ref=lg)
    wids = sorted({m["wid"] for m in meta.values()})
    nsense = {}
    for chunk in (wids[i:i + 900] for i in range(0, len(wids), 900)):
        qs = ",".join("?" * len(chunk))
        for wid, n in con.execute(
                "SELECT word_id, COUNT(*) FROM sense WHERE word_id IN (%s) GROUP BY word_id" % qs,
                chunk):
            nsense[wid] = n

    # ── 分层统计
    grid, rows = {}, []
    for i in both:
        m = meta.get(i)
        if not m or not m["ref"]:
            continue
        f = frags(m["ref"])
        if not f:
            continue
        az, bz = (A[i].get("zh") or ""), (B[i].get("zh") or "")
        hb = sum(1 for x in f if x in bz)
        ha = sum(1 for x in f if x in az)
        n = nsense.get(m["wid"], 1)
        key = (bucket(n), "首义" if m["rank"] == 1 else "非首义")
        g = grid.setdefault(key, [0, 0, 0])
        g[0] += 1
        g[1] += bool(hb)
        g[2] += bool(hb and not ha)
        rows.append((i, key, hb, ha, n))

    print("═══ 锚命中率：按「词的义项数 × 该义项位次」分层 ═══")
    print("   命中 = B 的译文里出现了锚的中文片段。锚吻合时命中是**对的**，")
    print("   所以看的不是命中率高低，而是**非首义那一列有没有跟着高**：")
    print("   非首义的锚多半是别的义项的中文，那一格高才是被拖着抄。\n")
    print("   %-8s %-8s %7s %9s %11s" % ("义项数", "位次", "可比", "B 命中", "B 中 A 未中"))
    for b in ORDER:
        for r in ("首义", "非首义"):
            g = grid.get((b, r))
            if not g:
                continue
            print("   %-8s %-8s %7s %6s %4.0f%% %6s %4.0f%%"
                  % (b, r, format(g[0], ","), g[1], 100 * g[1] / g[0], g[2], 100 * g[2] / g[0]))

    # ── 最高风险层：多义词 + 非首义 + B 命中锚而 A 没命中
    risk = [i for i, key, hb, ha, n in rows
            if n >= 4 and meta[i]["rank"] > 1 and hb and not ha]
    print("\n═══ 🔴 最高风险层（4+ 义词的非首义，B 抄了锚而 A 没抄）%s 条 ═══" % format(len(risk), ","))
    print("   这一格就是「锚是别的义项的中文」的产地。逐条问一句：")
    print("   **B 那句中文，说的是不是上面那条英文释义的意思？**")
    print("   是 → 锚无害（甚至更准）；不是 → 锚把它拖到别的义项去了。\n")
    random.seed(11)
    for i in random.sample(risk, len(risk)):
        m = meta[i]
        print("   ── %s (%s) 第 %d/%d 义" % (m["word"], m["pos"], m["rank"], nsense[m["wid"]]))
        print("      en : %s" % m["en"][:88])
        print("      A  : %s" % (A[i].get("zh") or "")[:64])
        print("      B  : %s" % (B[i].get("zh") or "")[:64])
        print("      ref: %s" % (m["ref"] or "").replace("\n", " / ")[:78])

    # ── 全量口径：这一格在 890k 里占多大
    print("\n═══ 全量里这一格有多大 ═══")
    tot, anch, risk_pop = con.execute(
        "SELECT COUNT(*), "
        "       SUM(CASE WHEN lg.word_id IS NOT NULL THEN 1 ELSE 0 END), "
        "       SUM(CASE WHEN lg.word_id IS NOT NULL AND s.rank>1 THEN 1 ELSE 0 END) "
        "FROM sense s LEFT JOIN legacy_gloss lg ON lg.word_id=s.word_id").fetchone()
    print("   义项总数            %11s" % format(tot, ","))
    print("   有锚                %11s  %.1f%%" % (format(anch, ","), 100 * anch / tot))
    print("   有锚且非首义（风险） %11s  %.1f%%（占全体）" % (format(risk_pop, ","), 100 * risk_pop / tot))
    con.close()
    return 0


if __name__ == "__main__":
    _sys.exit(main())
