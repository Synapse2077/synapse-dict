#!/usr/bin/env python3
"""阶段 5a —— 收割德语版例句 → `example`。2026-09-03。

═══ 挂回义项的桥：逐字节，不猜 ═══
例句在源里挂在 `senses[].examples` 下，而 1.5a 把**德语释义原文**存进了
`sense_src.text`（`src='de-edition'`）。⇒ 按 **(词形, 德语释义原文)** 精确匹配，
挂不上的 `sense_id` 留 NULL、`src_gloss` 原样存着，**不硬挂**。

🔴 **挂不上是正常的，不是缺陷**：库里 260,828 条义项里只有 135,179 条来自德语版
（其余 125,649 条是七月从英文版建的），德语版的例句本来就只挂得上自己那批。
⚠️ **不许用"词形+第几条义项"当桥** —— `[[model-answer-files-key-by-id]]`：
   两边的义项切分不保证一致，按下标挂会把例句贴到别的义项上。

═══ 判据：哪些例句不收 ═══
① **空句 / 只有标点**。
② **句子里根本没有这个词** —— 源头 `bold_text_offsets` 缺失且词形不出现在句中，
   说明这条例句挂错了词。判据用**含义**（词出没出现），不用长度这类形状代理。
③ ⚠️ **不按长度筛。** `[[criteria-from-meaning-not-form]]`：我在 fr 上写过
   「不是长句翻译」这种代理判据，坏了 1,528 条。长短由展示层决定，不在收割时砍。

═══ 本步不翻译 ═══
翻译是 5b，**单独跑、排空闲时段**。先收干净再决定买多少
（`[[prove-free-path-before-quoting]]`）。

用法（在 de/ 目录下）：
    python3 -u pipeline/harvest_examples.py           # 干跑
    python3 -u pipeline/harvest_examples.py --apply
"""
import argparse
import gzip
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbtool                                    # noqa: E402
import paths                                     # noqa: E402
from intake_edition_words import EDITIONS         # noqa: E402

f = lambda n: format(n, ",")
SRC = "de-edition"


def opener(p):
    p = Path(p)
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def harvest(words, bridge):
    """→ (rows, stat)。bridge = {(词形, 德语释义原文): sense_id}"""
    path, _ = EDITIONS["de"]
    rows, stat, seen = [], Counter(), set()
    with opener(path) as fh:
        for line in fh:
            if '"examples"' not in line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("lang_code") != "de":
                continue
            w = e.get("word") or ""
            if w not in words:
                stat["词形不在库里"] += 1
                continue
            for s in e.get("senses") or []:
                gl = ((s.get("glosses") or [""])[0] or "").strip()
                sid = bridge.get((w, gl))
                for x in s.get("examples") or []:
                    t = (x.get("text") or "").strip()
                    stat["源头例句"] += 1
                    if not t or not any(c.isalpha() for c in t):
                        stat["🔴 丢：空句或只有标点"] += 1
                        continue
                    off = x.get("bold_text_offsets") or []
                    if not off and w.lower() not in t.lower():
                        stat["🔴 丢：句子里没有这个词（挂错了词）"] += 1
                        continue
                    k = (w, t)
                    if k in seen:
                        stat["重复（同词同句）"] += 1
                        continue
                    seen.add(k)
                    rows.append((w, sid, t,
                                 json.dumps(off) if off else None,
                                 (x.get("ref") or "").strip() or None,
                                 gl or None,
                                 (x.get("translation") or "").strip() or None,
                                 "de" if x.get("translation") else None,
                                 0, SRC))
                    stat["收下"] += 1
                    if sid:
                        stat["  其中挂上了义项"] += 1
    return rows, stat


def gate2(con, expect):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("example 行数 == 期望", q("SELECT count(*) FROM example"), expect["rows"]),
        ("🔴 sense_id 指向不存在的义项",
         q("SELECT count(*) FROM example e LEFT JOIN sense s ON s.id=e.sense_id "
           "WHERE e.sense_id IS NOT NULL AND s.id IS NULL"), 0),
        ("🔴 词形不在 dict",
         q("SELECT count(*) FROM example e LEFT JOIN dict d ON d.word=e.word "
           "WHERE d.id IS NULL"), 0),
        ("🔴 空句", q("SELECT count(*) FROM example WHERE TRIM(text)=''"), 0),
        ("🔴 挂上的义项不属于这个词",
         q("SELECT count(*) FROM example e JOIN sense s ON s.id=e.sense_id "
           "JOIN dict d ON d.id=s.word_id WHERE d.word<>e.word"), 0),
        ("src 不是 de-edition", q("SELECT count(*) FROM example WHERE src<>'de-edition'"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-44s %10s  期望 %s" % ("✓" if good else "🔴", name, f(got), f(want)))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = {w for (w,) in con.execute("SELECT word FROM dict")}
    bridge = {}
    for w, txt, sid in con.execute(
            "SELECT d.word, x.text, x.sense_id FROM sense_src x "
            "JOIN dict d ON d.id=x.word_id WHERE x.src='de-edition' AND x.text IS NOT NULL"):
        bridge.setdefault((w, (txt or "").strip()), sid)
    print("■ 库内词形 %s ／ 挂桥可用的德语义项 %s" % (f(len(words)), f(len(bridge))))

    print("\n■ 扫德语版…")
    rows, stat = harvest(words, bridge)
    for k, v in stat.most_common():
        print("   %-34s %s" % (k, f(v)))

    n_sense = sum(1 for r in rows if r[1])
    n_ref = sum(1 for r in rows if r[4])
    L = sorted(len(r[2]) for r in rows)
    print("\n■ 收下 %s 条 ／ 挂上义项 %s（%.1f%%）／ 带文献出处 %s（%.1f%%）"
          % (f(len(rows)), f(n_sense), 100.0 * n_sense / max(len(rows), 1),
             f(n_ref), 100.0 * n_ref / max(len(rows), 1)))
    if L:
        print("   句长分位  中位 %d ／ 75%% %d ／ 90%% %d ／ 最长 %d 字符"
              % (L[len(L)//2], L[len(L)*3//4], L[len(L)*9//10], L[-1]))
        print("   总字符 %s  ⇒ 5b 全量翻译粗估 %s token（按 fr 实测 62.7 token/条）"
              % (f(sum(L)), f(int(len(rows) * 62.7))))
    print("   覆盖词形 %s" % f(len({r[0] for r in rows})))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    print("\n■ 将写入 example %s 行" % f(len(rows)))
    with dbtool.session("keep-v3-5a-examples", expect={"#example": len(rows)}) as s:
        s.executemany(
            "INSERT OR IGNORE INTO example "
            "(word,sense_id,text,bold,ref,src_gloss,src_translation,src_lang,hidden,src) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n = con.execute("SELECT count(*) FROM example").fetchone()[0]
    ok = gate2(con, {"rows": n})
    print("\n%s" % ("✓ 闸②全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
