#!/usr/bin/env python3
"""姓氏/名字族的**语言/国别形容词**翻一次，全库复用。2026-08-23。

`pipeline/name_patterns.py` 把 26,067 条姓氏/名字释义拆成「中文句式 + 槽位」。
性别是闭集（由 `GENDER_ZH` 解决），**唯一要翻的是 `L` 槽** —— 226 个形容词。

    Nom de famille français.        模式 → "{}姓氏"   槽值 L="français"
                                    本步 → français = 法国   ⇒ "法国姓氏"

**226 个形容词 → 24,951 条中文，110 倍压缩。**（地名族那轮是 30 倍）

🔴 阴阳性两种拼法都会出现（`anglais` / `anglaise`、`néerlandais` / `néerlandaise`），
   两者中文相同 —— 不去重，**各翻各的**，省得我再写一套词形还原判据出新错。

批调用逻辑在 `pipeline/slot_translate.py`（与地名族共用，三道防护见那里）。

用法（在 fr/ 目录下）：
    python3 pipeline/name_translate_slots.py --slice 40
    python3 pipeline/name_translate_slots.py
"""
import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths                                        # noqa: E402
from pipeline import slot_translate                 # noqa: E402
from pipeline.name_patterns import match, FAM       # noqa: E402

OUT = paths.WORK / "geo" / "name_slot_zh.jsonl"

SYS = """你在给一部**法汉词典**处理姓名条目。输入是一批**法语的语言/国别形容词**，
它们出现在「Nom de famille {fr}.」（{fr}姓氏）或「Prénom masculin {fr}.」（{fr}男子名）
这样的句子里。每项给：
  `fr`   —— 形容词本身
  `ctx`  —— 它真实出现过的一条法语原句

规则：
1. 输出**能直接放在「姓氏」「男子名」「女子名」前面做定语的中文**，不要「的」、不要解释。
   `français` → `法国`，于是渲染成「法国姓氏」。
   `arabe` → `阿拉伯`。`japonais` → `日本`。`breton` → `布列塔尼`。
2. 🔴 **阴性形与阳性形给同一个中文**：`anglais` 和 `anglaise` 都是 `英国`；
   `néerlandais` 和 `néerlandaise` 都是 `荷兰`。
3. 指**语言**而非国家的，用语言名：`anglophone` → `英语`、`francophone` → `法语`、
   `hispanophone` → `西班牙语`。
4. 指**地区/民族**的用该地区或民族名：`occitan` → `奥克`、`flamand` → `弗拉芒`、
   `mohawk` → `莫霍克`、`wallon` → `瓦隆`、`corse` → `科西嘉`。
5. 输出**只有那个定语**，不许出现「姓氏」「名字」「人」「的」「语言」这类词。
6. 🔴 拿不准就输出空字符串 ""，**不要猜**。宁可缺不可错。

输入是 JSON 数组。输出**只有** JSON 数组，每项 {"fr": 原样回传, "zh": "中文定语"}，
不要围栏、不要解释。**每一条输入都要有对应输出，一条都不能少。**"""


def collect():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = [" ".join(t.split()) for (t,) in con.execute("""
        SELECT g.text FROM sense s
        JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='fr'
        LEFT JOIN sense_gloss z ON z.sense_id = s.id AND z.lang='zh'
        WHERE z.sense_id IS NULL""")]
    n, ctx = Counter(), {}
    for t in rows:
        if not FAM.match(t):
            continue
        m = match(t)
        if not m:
            continue
        for kind, val in m[1]:
            if kind != "L":                 # 性别是闭集，不送模型
                continue
            v = val.strip()
            n[v] += 1
            if v not in ctx or len(t) < len(ctx[v]):
                ctx[v] = t
    return [{"fr": v, "kind": "L", "n": c, "ctx": ctx[v]} for v, c in n.most_common()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=int, default=0)
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()

    items = collect()
    if a.stats:
        got = slot_translate.done_keys(OUT)
        blank = [k for k, v in got.items() if not v["zh"]]
        print("■ L 槽 %d 个；已翻 %d；模型主动留空 %d"
              % (len(items), len(got), len(blank)))
        return 0

    slot_translate.translate(items[:a.slice] if a.slice else items, SYS, OUT)

    got = slot_translate.done_keys(OUT)
    show = items[:a.slice] if a.slice else items[:40]
    print("\n%-22s %-10s %s" % ("法语形容词", "中文", "代表原句"))
    print("-" * 92)
    for i in show:
        o = got.get(i["fr"])
        print("%-22s %-10s %s" % (i["fr"][:22], (o["zh"] if o else "—")[:10], i["ctx"][:52]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
