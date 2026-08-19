#!/usr/bin/env python3
"""有意语原文却没中文的义项，从意语原文补中文。2026-08-17。

═══ 这是一个判据漏了一族的残留 ═══
`fixes/fill_empty_zh.py`（早先）把「有可见义项却没中文」从 489 降到 59，
剩下 59 条我判成「**源头本身是空的**」记了账。今天回查，**判错了**：

    Zhiuk         it: Un cognome                        （一个姓氏）
    fustato       it: attributo araldico che si applica a…（纹章学属性）
    in fascia     it: termine araldico che si riferisce…  （纹章学术语）
    centesi-      it: prima parte di lemmi formati…       （构词成分）

**59 条全部有意语原文**，只是当时的判据只看了英文 gloss（`en`），没看 `it`。
⇒ 「源头是空的」这个结论是我按自己的取数口径下的，不是数据的事实。
  （`measure-landing-not-source` 的又一次：先假设我的度量错了。）

═══ 怎么补 ═══
从**意语原文**译中文，走本项目验证过的翻译通路（`flash-translation-validated`，
实测 bad 1–3%），与凭构词猜释义（25% 错）完全不是一回事。
`src` 记 `deepseek-v4-flash:from-it`，与库里已有 22,455 条同一来源，口径一致。

⚠️ 输入**不按字数截断**（A45：`azzurro` 曾被切在 `rep|ubblicani` 中间）。
⚠️ 纹章学/构词成分这类术语占多数，prompt 要说明「保留学科语境，不要改写成日常说法」。

用法（在 it/ 目录下）：
    python3 fixes/fill_zh_from_it.py            # 干跑
    python3 fixes/fill_zh_from_it.py --apply
    python3 fixes/fill_zh_from_it.py --verify
"""
import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool     # noqa: E402
import ds_batch   # noqa: E402
import paths      # noqa: E402

WORK = paths.DATA / "work" / "it"
OUT = WORK / "zh_from_it_residual.jsonl"
SRC = "deepseek-v4-flash:from-it"

SYS = """你是意大利语词典编纂助手。给你一批义项的**意大利语原文定义**，请译成简明中文释义。

规则：
1. 只翻译给出的意语原文，不要自己补充别的意思，不要改写成日常说法。
2. 里面有不少**纹章学**（araldico）、**构词成分**（prima parte di lemmi…）、
   **姓名/姓氏**（Un nome / Un cognome）这类条目，保留学科语境：
   纹章学术语就写纹章学的说法；构词成分写「（构词成分）…」；姓氏写「（姓氏）」。
3. 中文写释义本身，不写词性说明、不写"意为"。
4. 原文若本身没有可译的内容（只是重复词形、或是残缺片段），把 zh 留空。
5. 严格只返回 JSON 对象：{"标识号": {"zh": "..."}, ...}，标识号是每行的 n，原样回传。"""


def scan(con):
    """→ [(sense_id, 词形, 意语原文)]，有可见义项、有意语原文、没中文的。"""
    return con.execute("""
        SELECT s.id, d.word,
               (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='it' LIMIT 1) AS it
        FROM sense s JOIN dict d ON d.id = s.word_id
        WHERE COALESCE(s.hidden,0)=0
          AND NOT EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id
                         AND g.lang='zh' AND trim(COALESCE(g.text,'')) <> '')
          AND EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id
                     AND g.lang='it' AND trim(COALESCE(g.text,'')) <> '')
    """).fetchall()


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    left = scan(con)
    checks = [
        ("🔴 没有「有意语原文却没中文」的义项了", len(left), 0),
        ("🔴 本步中文不许为空",
         q("SELECT count(*) FROM sense_gloss WHERE src='%s' "
           "AND trim(COALESCE(text,''))=''" % SRC), 0),
        # 🔴 本步只补空，不许覆盖别的来源写的中文
        ("🔴 每条本步中文所在的义项只有这一条中文",
         q("""SELECT count(*) FROM sense_gloss g WHERE g.src='%s' AND EXISTS(
                SELECT 1 FROM sense_gloss h WHERE h.sense_id=g.sense_id
                AND h.lang='zh' AND h.src <> '%s')""" % (SRC, SRC)), 0),
        ("（记账）没有意语原文、也没中文的义项", q("""
            SELECT count(*) FROM sense s WHERE COALESCE(s.hidden,0)=0
              AND NOT EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id
                             AND g.lang='zh' AND trim(COALESCE(g.text,''))<>'')"""), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-46s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("apply", "verify"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    rows = scan(ro)
    print("■ 有意语原文却没中文的义项 %d 条" % len(rows))
    for sid, w, it in rows[:8]:
        print("   %-20s %s" % (w[:20], it[:60]))
    if not a.apply or not rows:
        ro.close()
        if not a.apply:
            print("\n(未加 --apply，不写库)")
        return 0
    ro.close()
    payload = [{"n": sid, "w": w, "it": it} for sid, w, it in rows]
    B = 30
    batches, meta = [], []
    for i in range(0, len(payload), B):
        batches.append(payload[i:i + B])
        meta.append([(str(x["n"]), x["n"]) for x in payload[i:i + B]])
    tok = asyncio.run(ds_batch.run(SYS, batches, meta, OUT, mode="flash", conc=4,
                                   every=1, thinking="disabled"))
    print("■ token %s" % format(tok, ","))
    zh = {}
    for line in OUT.open(encoding="utf-8"):
        r = json.loads(line)
        if (r.get("zh") or "").strip():
            zh[r["id"]] = r["zh"].strip()
    print("■ 译回 %d / %d 条" % (len(zh), len(rows)))
    todo = [(sid, zh[sid]) for sid, w, it in rows if sid in zh]
    with dbtool.session("fill-zh-from-it",
                        expect={"__rows__": 0, "#sense_gloss": len(todo)}) as s:
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?,'zh','equivalent',0,?,?)",
                      [(sid, t, SRC) for sid, t in todo])
    print("■ 已补 %d 条" % len(todo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
