#!/usr/bin/env python3
"""5e 切片的质量复核。2026-09-08。零 API，只读盘上答案。

═══ 四件，前两件机械可判、后两件必须人读 ═══
① **交付完整性**：空输出／无汉字／抄回原文／答案 id 不在池子里
② **出处漏进译文**：规则 5 写了「文献出处不出现在译文里」——
   🔴 规则写了不等于守住（今天已验证两次）。判据：译文里出现了 `ref` 里的年份/作者。
③ **义项对不对**：fr 最大的一族（风险面 22.1 万、重跑 41 元）。
   🔴 **机械判不了**，只能并排打出来人读。挑**多义词的非首义**——
   那是最容易取错义项的一格（同 1.5c 的分层思路）。
④ **古英语那批**：源头给了现代英语转写，看模型是不是真按 `m` 理解了原句。

⚠️ 机械命中一律只当**嫌疑**，不当判决 —— 今天三次栽在拿形式代理当判据。

    cd en && python3 -u probes/review_examples.py
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import json
import random
import re
import sqlite3

import paths
import translate_examples as te   # 🔴 判据只许有一份，探针 import 管道那一份

ANS = paths.WORK / "examples" / "slice.jsonl"
HAN = re.compile(r"[㐀-䶿一-鿿]")
YEAR = re.compile(r"(1[5-9]\d\d|20[0-2]\d)")


def main():
    ans = {}
    for ln in ANS.open(encoding="utf-8"):
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if "id" in o:
            ans[int(o["id"])] = (o.get("zh") or "").strip()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = con.execute
    meta = {}
    ids = sorted(ans)
    for k in range(0, len(ids), 900):
        ck = ids[k:k + 900]
        qs = ",".join("?" * len(ck))
        for eid, w, txt, ref, sid, tr in q(
                "SELECT id, word, text, ref, sense_id, src_translation FROM example "
                "WHERE id IN (%s)" % qs, ck):
            # 🔴 `m` 必须过管道那一份判据 —— 探针直接读 `src_translation` 时，
            #    ④ 打出来的是**原始字段**（里面混着书名 `Phantom`/`The Great Bible`），
            #    看上去像"模型收到了污染的上下文"，其实管道已经把它们挡掉了。
            #    闸与它守的那段逻辑用两个判据 ＝ 噪声源（[[fix-regression-and-gate]] 第三种机制）。
            meta[eid] = dict(w=w, en=txt, ref=ref, sid=sid,
                             m=(tr if te.is_rendering(txt, tr) else None), raw_m=tr)
    sids = [m["sid"] for m in meta.values() if m["sid"]]
    gl, rank, nsense = {}, {}, {}
    for k in range(0, len(sids), 900):
        ck = sids[k:k + 900]
        qs = ",".join("?" * len(ck))
        for sid, r, wid, g in q("SELECT s.id, s.rank, s.word_id, g.text FROM sense s "
                                "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='en' "
                                "WHERE s.id IN (%s)" % qs, ck):
            gl[sid] = g
            rank[sid] = r
            nsense[sid] = wid
    cnt = {}
    for wid in set(nsense.values()):
        cnt[wid] = q("SELECT COUNT(*) FROM sense WHERE word_id=?", (wid,)).fetchone()[0]

    n = len(ans)
    empty = [i for i, z in ans.items() if not z]
    nohan = [i for i, z in ans.items() if z and not HAN.search(z)]
    copy = [i for i, z in ans.items() if z and i in meta and z == meta[i]["en"].strip()]
    print("═══ ① 交付完整性（%s 条）═══" % format(n, ","))
    for name, bad in (("空输出（规则 7）", empty), ("译文无汉字", nohan), ("抄回英文原文", copy)):
        print("   %-22s %6s  %.3f%%" % (name, format(len(bad), ","), 100 * len(bad) / n))

    # ② 出处漏进译文
    susp = []
    for i, z in ans.items():
        m = meta.get(i)
        if not m or not m.get("ref") or not z:
            continue
        ys = set(YEAR.findall(m["ref"])) - set(YEAR.findall(m["en"]))
        if ys and any(y in z for y in ys):
            susp.append(i)
    print("\n═══ ② 出处漏进译文（规则 5）═══")
    print("   带 ref 的译文里出现了**只在出处里有**的年份：%s 条 %.3f%%"
          % (format(len(susp), ","), 100 * len(susp) / n))
    for i in susp[:5]:
        print("      ref: %s" % (meta[i]["ref"] or "")[:70])
        print("      zh : %s" % ans[i][:70])

    # ③ 义项对不对 —— 挑多义词非首义，人读
    hard = [i for i in ans if ans[i] and meta.get(i, {}).get("sid")
            and rank.get(meta[i]["sid"], 1) > 1
            and cnt.get(nsense.get(meta[i]["sid"]), 0) >= 6]
    print("\n═══ ③ 义项对不对（fr 最大的一族）—— **人读，机械判不了** ═══")
    print("   多义词(6+义)的非首义例句 %s 条，随机 12 条：" % format(len(hard), ","))
    random.seed(11)
    for i in random.sample(hard, min(12, len(hard))):
        m = meta[i]
        print("   ── %s 第%d/%d义  义项: %s"
              % (m["w"], rank[m["sid"]], cnt[nsense[m["sid"]]], (gl.get(m["sid"]) or "")[:56]))
        print("      例: %s" % m["en"][:90])
        print("      译: %s" % ans[i][:78])

    # ④ 古英语
    old = [i for i in ans if ans[i] and meta.get(i, {}).get("m")]
    print("\n═══ ④ 带现代英语转写的（古英语/方言）%s 条 ═══" % format(len(old), ","))
    for i in old[:5]:
        m = meta[i]
        print("   古: %s" % m["en"][:82])
        print("   今: %s" % (m["m"] or "")[:82])
        print("   译: %s" % ans[i][:70])
    con.close()
    return 0


if __name__ == "__main__":
    _sys.exit(main())
