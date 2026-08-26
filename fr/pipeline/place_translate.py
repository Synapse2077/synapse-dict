#!/usr/bin/env python3
"""法国市镇名 → 中文音译。翻一次，全库复用。2026-08-24。

居民/关系族 99,049 条里，市镇名是唯一要翻的槽位（省名地名族那轮已经翻过，直接复用）。

    Habitant de Saint-Cloud, commune française située dans le département des Hauts-de-Seine.
        → 法国上塞纳省**圣克卢**市镇的居民

🔴 我一度提议**不翻**、直接保留法语原名，理由写了三条。用户驳回：
   「不要为了省 token 而省，该花花，目的都是质量为本」。
   复盘：三条理由里只有「这个决定可逆」站得住。
   「保留原名对查词的人更有用」**是我编的** —— 这是给中文用户的词典，
   条目里夹着 `Saint-Cloud` 就是半成品。
   我真正的理由是「25,682 个音译我核不完」，那是**我的验收能力问题，
   不是质量判断**，而我把它包装成了产品决策。
   ⇒ 记住这个形状：**当我给一个决定列了三条理由，先挑出哪条是真的。**

═══ 质量怎么保 ═══
① **每个名字只翻一次**（按原串存）⇒ 同一个市镇在全库永远同一个中文，
   模型跑三次给三个音译的问题从根上没有
② **模型留空 ⇒ 渲染时退回法语原名**，不猜、也不留白
③ ctx 带上省名，让模型知道是法国哪个地区的地名；prompt 明确禁止把 ctx 写进答案
   （`[[context-you-give-leaks-into-output]]`：意语那轮 1,583 条音译漏进了母地名）
④ 关思考、批 160 —— `[[batch-never-enables-thinking]]`

用法（在 fr/ 目录下）：
    python3 pipeline/place_translate.py --slice 60   # 小样，我逐条读
    python3 pipeline/place_translate.py              # 全量续跑
    python3 pipeline/place_translate.py --stats
"""
import argparse
import io
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths                                              # noqa: E402
from pipeline import slot_translate                       # noqa: E402
from pipeline.demonym_render import (COUNTRY_ZH, P_CTY, P_DEP,        # noqa: E402
                                     P_DEP2, dep_lookup, dep_zh, place_ok)

OUT = paths.WORK / "geo" / "place_zh.jsonl"

SYS = """你在给一部**法汉词典**做**法国市镇名**的中文译名。输入是 JSON 数组，每项给：
  `fr`   —— 市镇名（法语）
  `ctx`  —— 它所在的省或国家，**只用来帮你判断地区读音习惯**
           （比利时/瑞士的地名也在这批里，读音习惯与法国本土可能不同）

规则：
1. 输出该市镇名的**中文音译本身**，不要「市镇」「法国」「省」这类词，不要解释。
   `Saint-Cloud` → `圣克卢`。`Bannes` → `巴讷`。
2. 🔴 **有约定俗成译名的用约定译名**，不要另起炉灶：
   `Versailles`→`凡尔赛`、`Marseille`→`马赛`、`Lyon`→`里昂`、`Bordeaux`→`波尔多`、
   `Reims`→`兰斯`、`Cannes`→`戛纳`、`Nice`→`尼斯`。
3. 没有约定译名的（绝大多数小市镇），按**法语读音**音译，用《世界地名翻译大辞典》
   的常规用字。注意法语词尾辅音多不发音（`Paris`→`巴黎` 不是「巴黎斯」）。
4. 复合名保留连字符：`Saint-Cloud-en-Dunois` → `圣克卢-昂-迪努瓦`。
   `Saint-`→`圣`，`Sainte-`→`圣`，`-sur-`→`-叙尔-`（除非有约定译法如「河畔」）。
5. 🔴 `ctx` 只是判断依据，**一个字都不许写进答案**。答案里不许出现省名、
   「市镇」「法国」「位于」这类词。
6. 🔴 拿不准就输出空字符串 ""，**不要猜**。留空的会退回显示法语原名，不会出错。

输出**只有** JSON 数组，每项 {"fr": 原样回传, "zh": "音译"}，
不要围栏、不要解释。**每一条输入都要有对应输出，一条都不能少。**"""


def collect():
    """→ [{fr, kind, n, ctx}]，按出现次数降序。只收**真会被渲染用到**的那些。"""
    dz = dep_zh()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n, ctx = Counter(), {}
    # 🔴 也要看**本模板已经写过中文**的那些行 —— 否则修了抽取规则之后，
    #    新冒出来的市镇名永远进不了翻译队列（它们所在的行已经有中文了）。
    for (raw,) in con.execute("""
            SELECT g.text FROM sense s
            JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='fr'
            LEFT JOIN sense_gloss z ON z.sense_id = s.id AND z.lang='zh'
            WHERE z.sense_id IS NULL OR z.src='template:demonym'"""):
        t = " ".join(raw.split())
        if not t.startswith(("Habitant", "Relatif", "Relative")):
            continue
        m = P_DEP.match(t) or P_DEP2.match(t)
        if m:
            place, where = m.group(2).strip(), m.group(3).strip()
            if not place_ok(place) or not dep_lookup(dz, where):
                continue                  # 渲染时也会放弃，不必翻
        else:
            # 🔴 `Habitant de Willemeau **en Belgique**.` 这一族走 `P_CTY`，
            #    而这里原来**只收 P_DEP** ⇒ 2,889 条渲染出来是「比利时 Willemeau 的」，
            #    法语原名直接摆在中文释义里。外国地名也要音译。
            m = P_CTY.match(t)
            if not m:
                continue
            place, where = m.group(2).strip(), m.group(3).strip()
            if not place_ok(place) or not COUNTRY_ZH.get(where):
                continue
        n[place] += 1
        ctx.setdefault(place, where)
    return [{"fr": p, "kind": "P", "n": c, "ctx": ctx[p]} for p, c in n.most_common()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=int, default=0)
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()

    items = collect()
    if a.stats:
        got = slot_translate.done_keys(OUT)
        blank = [k for k, v in got.items() if not v["zh"]]
        print("■ 市镇名 %s 个；已翻 %s；模型留空 %s（渲染时退回法语原名）"
              % (format(len(items), ","), format(len(got), ","), format(len(blank), ",")))
        return 0

    todo = items[:a.slice] if a.slice else items
    slot_translate.translate(todo, SYS, OUT)

    got = slot_translate.done_keys(OUT)
    show = todo[:60]
    print("\n%-32s %-16s %s" % ("法语市镇名", "中文音译", "所在省"))
    print("-" * 76)
    for i in show:
        o = got.get(i["fr"])
        print("%-32s %-16s %s" % (i["fr"][:32], (o["zh"] if o else "—")[:16], i["ctx"][:24]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
