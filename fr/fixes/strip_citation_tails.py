#!/usr/bin/env python3
"""剥掉法语释义尾巴上的**引文署名**，并把受影响的中文撤下来重翻。2026-08-25。

    Nom, en Égypte, d’un poids de 45 kg. — (Journal des Débats, 30 septembre 1876)
        → Nom, en Égypte, d’un poids de 45 kg.

═══ 为什么要修 ═══
wiktextract 把**例句连同署名**混进了 `senses[].glosses`。全库 217 条。
量落点（不量源头）：**中文里跟着漏进去 12 条**，而且漏的是最坏的一种 ——
**整句例句被当成释义翻了**：

    Elle était généreuse par braverie… — (George Sand, François le Champi, 1848)
      → 「她因炫耀而慷慨，喜欢被人感谢。——（乔治·桑，《弗朗索瓦·勒尚皮》，1848年）」

这不是释义，是一句小说原文。摆在词条页上比留空更伤。

═══ 判据 ═══
剥 `— (…)` 到行尾。**一个例外**：`— (Note d’usage : …)` 是真内容（用法说明），
全库 1 条，不剥。⚠️ 破折号是 em dash `—`，不是连字符；法语引文署名的固定写法。

剥完仍有内容 216 条（剥完为空 0 条）。其中 53 条的正文本身就偏例句
（`Les marins disent plus ordinairement jouail. Le jas d’une ancre est…`），
但**不能按"像不像例句"删** —— 逐条读下来它们多数仍给出了词义（那条的中文是「锚杆」，对的）。
⇒ 只做确定性的事：剥署名、重翻，**不替模型判断哪句是释义**。

═══ 为什么把中文撤下来而不是原地改 ═══
那 12 条的中文是**从带署名的原文翻出来的**，改不动源就等于留着错译。
撤下来之后它们自动回到 `gloss_translate.py` 的待翻池（判据是"有没有中文"），
用现成流水线重翻，不另造一套。可逆：备份在，中文本身也可再生。

用法（在 fr/ 目录下）：
    python3 fixes/strip_citation_tails.py           # 干跑
    python3 fixes/strip_citation_tails.py --apply
    python3 pipeline/gloss_translate.py             # 重翻这批
    python3 pipeline/gloss_translate.py --apply
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

# em dash + 空格 + 左括号 …… 到行尾
CIT = re.compile(r"\s*—\s*\(.*$", re.S)
# 唯一的例外：用法说明，是真内容
KEEP = re.compile(r"—\s*\(\s*Note", re.I)


def plan(con):
    out = []
    for sid, lang, kind, seq, t in con.execute(
            "SELECT sense_id, lang, kind, seq, text FROM sense_gloss WHERE lang='fr'"):
        if not CIT.search(t) or KEEP.search(t):
            continue
        new = " ".join(CIT.sub("", t).split()).rstrip(" ,;:")
        if new and new != " ".join(t.split()):
            out.append((sid, lang, kind, seq, t, new))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = plan(con)
    ids = [r[0] for r in rows]
    q = ",".join("?" * len(ids))
    nzh = con.execute("SELECT count(*) FROM sense_gloss WHERE lang='zh' AND sense_id IN (%s)"
                      % q, ids).fetchone()[0] if ids else 0
    print("■ 要剥引文署名 %s 条；其中已有中文、要撤下来重翻的 %s 条"
          % (format(len(rows), ","), format(nzh, ",")))

    # 不变量：只许删掉「— (…) 到行尾」这一段，**正文一个字母都不许动**
    word = lambda x: re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ]", "", x)          # noqa: E731
    bad = [(t, n) for *_x, t, n in rows if not word(t).startswith(word(n))]
    left = [n for *_x, n in rows if CIT.search(n)]
    note = con.execute("SELECT count(*) FROM sense_gloss WHERE lang='fr' "
                       "AND text LIKE '%— (Note%'").fetchone()[0]
    print("\n── 不变量 ──")
    print("   ① 正文被改动（新值不是原值的前缀）：%d" % len(bad))
    print("   ② 剥完仍有引文署名：%d" % len(left))
    print("   ③ `— (Note …)` 用法说明保留：%d 条（应保持不变）" % note)
    if bad or left:
        for t, n in bad[:3]:
            print("      %r\n      → %r" % (t[:90], n[:90]))
        print("\n🔴 不变量红了，**不写**")
        return 1

    print("\n── 样本 8 条 ──")
    for *_x, t, n in rows[:8]:
        print("   %-96s\n   → %s" % (" ".join(t.split())[:96], n[:96]))

    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0

    bak = paths.WORK / "fr_citation_tails_before.jsonl"
    bak.parent.mkdir(parents=True, exist_ok=True)
    old_zh = {r[0]: r[1] for r in con.execute(
        "SELECT sense_id, text FROM sense_gloss WHERE lang='zh' AND sense_id IN (%s)" % q, ids)}
    bak.write_text("\n".join(
        json.dumps({"sense_id": s, "lang": l, "kind": k, "seq": qq,
                    "before_fr": t, "before_zh": old_zh.get(s)}, ensure_ascii=False)
        for s, l, k, qq, t, _n in rows), encoding="utf-8")
    print("\n■ 改前原文（含被撤下的中文）已留痕 → %s" % bak)

    with dbtool.session("keep-v3-citation", expect={"#sense_gloss": -nzh}) as s:
        s.executemany(
            "UPDATE sense_gloss SET text=? WHERE sense_id=? AND lang=? AND kind=? AND seq=?",
            [(n, sid, l, k, qq) for sid, l, k, qq, _t, n in rows])
        s.execute("DELETE FROM sense_gloss WHERE lang='zh' AND sense_id IN (%s)" % q, ids)
    print("✓ 剥了 %s 条法语释义；撤下 %s 条中文（下一步跑 gloss_translate.py 重翻）"
          % (format(len(rows), ","), format(nzh, ",")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
