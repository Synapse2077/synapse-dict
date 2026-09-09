#!/usr/bin/env python3
"""flash 译文的**绝对**质量 —— 拿 ECDICT 人工中文当外锚，零 API。2026-09-07。

用户 2026-09-07：「flash 的质量还是得到了你的认可对吧」。
🔴 到此刻为止我说的全是**相对**的（比 mini 好、比不带锚好）。
绝对错误率 en 一次没量过 —— it 那门量出 1.2%（`[[it-translation-quality-measured]]`），
en 还没有对应的数。**"比另一个差的好"不等于"够好"。**

═══ 判据：不能用「与人工中文重合」═══
那正是今天刚栽的那条（`[[proxy-metric-gets-optimized]]` 2026-09-07 段）：
锚就在 payload 里，重合率是模型能直接优化的代理。
而且**无重合根本不等于错** —— ECDICT 是词条级的，我们的义项是义项级的，
词条级中文覆盖不到第 7 义是正常的，不是缺陷。

⇒ **按「锚该不该覆盖这条」分层**，再看无重合：
    rank=1 且人工中文只有一个词性  → 锚**本来就该**覆盖它，无重合 = 高度可疑
    rank>1 或人工中文多词性        → 锚覆盖不到是正常的，无重合无信息
只有第一格值得人读。这是把「可疑面」从 619 收窄到可以**全部读完**的量级
（`[[verification-gates-not-sampling]]`：可疑的那一格要 100% 读，不抽样）。

⚠️ 只读盘上已有的切片结果，不发请求。
    cd en && python3 probes/flash_absolute.py
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import json
import re
import sqlite3

import paths

OUT = paths.WORK / "slice"
HAN = re.compile(r"[㐀-䶿一-鿿]")
POS = re.compile(r"\b(n|v|vt|vi|a|adj|ad|adv|prep|conj|pron|int|num|art|aux)\.\s")


def frags(ref):
    s = re.sub(r"^[a-z]{1,5}\.\s*|\s*/\s*[a-z]{1,5}\.\s*", " ", ref or "")
    s = re.sub(r"\[[^\]]{1,6}\]", " ", s)
    return {x.strip() for x in re.split(r"[；;，,、/\s]+", s)
            if len(x.strip()) >= 2 and HAN.search(x)}


def main():
    B = {json.loads(l)["id"]: json.loads(l).get("zh", "")
         for l in (OUT / "slice_anchor.jsonl").open(encoding="utf-8")}
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ids = sorted(B)
    rows = []
    for k in range(0, len(ids), 900):
        ck = ids[k:k + 900]
        qs = ",".join("?" * len(ck))
        for sid, wid, w, pos, rk, en, frq, tag, ref in con.execute(
                "SELECT s.id, s.word_id, d.word, s.pos, s.rank, g.text, d.freq_rank, "
                "       d.exam_tag, lg.text "
                "FROM sense s JOIN dict d ON d.id=s.word_id "
                "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='en' "
                "LEFT JOIN legacy_gloss lg ON lg.word_id=s.word_id "
                "WHERE s.id IN (%s)" % qs, ck):
            if not (frq or tag) or not ref:
                continue
            rows.append(dict(id=sid, wid=wid, word=w, pos=pos or "", rank=rk,
                             en=en, ref=ref.replace("\n", " / "), zh=B.get(sid, "")))
    ns = {}
    wids = sorted({r["wid"] for r in rows})
    for k in range(0, len(wids), 900):
        ck = wids[k:k + 900]
        qs = ",".join("?" * len(ck))
        for wid, n in con.execute(
                "SELECT word_id, COUNT(*) FROM sense WHERE word_id IN (%s) GROUP BY word_id" % qs,
                ck):
            ns[wid] = n
    con.close()

    for r in rows:
        r["n"] = ns.get(r["wid"], 1)
        # 🔴 判据与 `model_bakeoff.py` 必须**逐字一致** —— 同一个"重合"我这一轮写过两份：
        #    那边子串包含、这边分词精确相等，`Saturnalia` 的
        #    `农神节（古罗马…）` 含 `农神节` 却被判成无重合（`[[refactor-mindset-code-quality]]`）。
        #    统一取**子串包含**（宽的那个）：宽会少报可疑，窄会假报可疑，
        #    而这一格是要人**逐条读完**的，假报比少报贵。
        r["ov"] = any(x in r["zh"] for x in frags(r["ref"]))
        r["single"] = len(set(POS.findall(r["ref"]))) <= 1 and "/" not in r["ref"]

    n = len(rows)
    print("═══ 核心层负控 %s 条（每条都有 ECDICT 人工中文，bad≈0.02%%）═══\n" % format(n, ","))
    print("   %-34s %6s %8s %10s" % ("格", "条数", "无重合", "占该格"))
    grid = {}
    for r in rows:
        key = ("锚该覆盖（首义·人工单词性）" if r["rank"] == 1 and r["single"]
               else "锚不必覆盖（非首义 或 人工多词性）")
        g = grid.setdefault(key, [0, 0])
        g[0] += 1
        g[1] += not r["ov"]
    for k in ("锚该覆盖（首义·人工单词性）", "锚不必覆盖（非首义 或 人工多词性）"):
        if k in grid:
            a, b = grid[k]
            print("   %-34s %6s %8s %9.1f%%" % (k, format(a, ","), format(b, ","), 100 * b / a))

    susp = [r for r in rows if r["rank"] == 1 and r["single"] and not r["ov"]]
    print("\n═══ 🔴 可疑面：%s 条（锚该覆盖却没重合）—— **全部列出，不抽样** ═══" % format(len(susp), ","))
    print("   逐条问：**flash 那句中文，说的是不是这条英文释义的意思？**")
    print("   是 → 只是换了说法（人工中文也可能反而不准）；不是 → 真错。\n")
    for r in sorted(susp, key=lambda x: x["word"]):
        print("   ── %s (%s) 第 %d/%d 义" % (r["word"], r["pos"], r["rank"], r["n"]))
        print("      en   : %s" % r["en"][:92])
        print("      flash: %s" % r["zh"][:62])
        print("      人工 : %s" % r["ref"][:78])
    return 0


if __name__ == "__main__":
    _sys.exit(main())
