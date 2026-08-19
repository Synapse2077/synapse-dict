#!/usr/bin/env python3
"""阶段 5 第一步：三版 dump 里有多少例句、能不能挂到义项上。不写库，只出数。2026-08-18。

═══ 要回答的四个问题 ═══
① 三版各有多少条例句？（按**条**数，不按词形 —— es 的 `derived` 就是漏了这层）
② 每条例句能不能挂到我们库里的**那一条义项**上？
   判据：`sense_src.src_ref` 是 `kk-en:<词>:<词性>:<词源号>:<seq>#<义项序>.<释义序>`，
   例句在 dump 里就长在 `senses[i].examples[]` 上 ⇒ 用 `#<i>.` 前缀去找，确定性对上。
③ 例句自带的译文是什么语言？（en 版给英文、fr 版给法文、it 版通常没有）
   A3 的三语原则管的是**释义**；例句译文同理只留中英意，法语版的法文译文不收。
④ 有多少是「用法说明/引文出处」而不是例句（`type`/`ref` 字段）—— 这些要分开。

用法（在 it/ 目录下）：
    python3 probes/example_census.py
"""
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import paths                                   # noqa: E402
from ipa_variants import SRC_PREFIX, iter_source   # noqa: E402

SOURCES = [("en-edition", paths.KK, None), ("it-edition", paths.EDITION, "it"),
           ("fr-edition", paths.KK_FR, None)]
f = lambda n: format(n, ",")


def main():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    # 义项坐标 → sense_id。
    # 🔴 **不要自己拼 src_ref 字符串去查** —— 三版的格式不一样：
    #      en   kk-en:<词>:<词性>:<词源号>:<seq>#<义项序>.<释义序>
    #      it/fr kk-it:<词>:<词性>#<义项序>.<释义序>        ← 没有词源号与 seq
    #    第一版我按 en 的格式拼给三版都用，it/fr 两版 **28,771 条例句全部"挂不上"**，
    #    而真实原因只是我的键长得不一样。⇒ 改成**解析库里的 ref**，键统一成
    #    (版本, 词形, 词性, 词源号, 义项序)。
    by_ref = {}
    for src0, ref, sid in con.execute(
            "SELECT src, src_ref, sense_id FROM sense_src WHERE sense_id IS NOT NULL"):
        if "#" not in ref:
            continue
        head, tail = ref.split("#", 1)
        i = int(tail.split(".")[0]) if tail.split(".")[0].isdigit() else None
        parts = head.split(":")
        if i is None or len(parts) < 3:
            continue
        if len(parts) >= 5 and parts[-1].isdigit() and parts[-2].isdigit():
            word, pos, etym = ":".join(parts[1:-3]), parts[-3], int(parts[-2])
        else:
            word, pos, etym = ":".join(parts[1:-1]), parts[-1], 0
        by_ref.setdefault((src0, word, pos, etym, i), sid)
    words = {w for (w,) in con.execute("SELECT word FROM dict")}
    con.close()
    print("■ 已裁决的义项坐标 %s 个" % f(len(by_ref)))

    for src, path, lc in SOURCES:
        c = Counter()
        langs = Counter()
        samples = []
        for w, d in iter_source(path, src, lc):
            in_dict = w in words
            pos = d.get("pos") or "?"
            etym = d.get("etymology_number") or 0
            for i, s in enumerate(d.get("senses") or []):
                exs = s.get("examples") or []
                if not exs:
                    continue
                sid = by_ref.get((src, w, pos, etym, i))
                for e in exs:
                    c["例句行"] += 1
                    if not in_dict:
                        c["词形不在库里"] += 1
                        continue
                    c["挂得上义项" if sid else "挂不上义项（该义项未裁决/未收）"] += 1
                    if e.get("text"):
                        c["有原文"] += 1
                    for k in ("english", "translation", "roman", "ref", "type", "note"):
                        if e.get(k):
                            c["字段·" + k] += 1
                    if e.get("type"):
                        langs[e["type"]] += 1
                    if len(samples) < 4 and sid and e.get("text"):
                        samples.append((w, e))
        print("\n■ %s" % src)
        for k, v in c.most_common():
            print("     %-30s %s" % (k, f(v)))
        if langs:
            print("     type 取值：%s" % dict(langs.most_common(6)))
        for w, e in samples:
            print("     %-14s %s" % (w[:14], json.dumps(e, ensure_ascii=False)[:150]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
