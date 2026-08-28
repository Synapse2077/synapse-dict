#!/usr/bin/env python3
"""探针 — **无差别重跑，到底是改好了还是改坏了？** 2026-08-27。

═══ 为什么必须量这个 ═══
到这一步为止我知道的是：
  · 带义项上下文重翻，对**已知错案** 6/6 修对 ⇒ 机制有效
  · 风险面 400 条抽样，判官报 7.5%，我逐条读完真错约 1.3% ⇒ 约 1,500 条
  · 重跑会让 **85%** 的译文文本发生变化（纯抖动基线）

**缺的是最后一个数**：那 85% 被改动的译文，改完之后是**更对**还是**更错**？
不量这个就选"不重跑"，那是拿成本当理由；不量这个就选"重跑"，
那是拿 85% 的好译文赌 1.3% 的坏译文。

═══ 做法 ═══
同一批 300 条（`example_sense_context.py` 的 A 臂），用**同一个判官**
（`judge_example_sense.py` 的 SYS，正控 40/40、负控 5/6 已验过）判两次：

    judge(库里现有译文)      → 坏率 X
    judge(带上下文重翻的译文)  → 坏率 Y

    Y 明显 < X  ⇒ 无差别重跑确实提升质量，那 41 元该花
    Y ≈ X      ⇒ 重跑只是换说法，白花钱且白冒险
    Y > X      ⇒ **重跑是净损害**，必须只改判官圈中的

⚠️ 判官只看「`w` 有没有取对义项」，看不见「别处译得好不好」。
   所以 Y≈X 时**不能**推出"重跑无害"—— 重跑对判官看不见的部分做了什么，
   仍然是未知的风险。这个不对称本身就是"只改被圈中的"的理由。

用法（在 fr/ 目录下）：
    python3 -u probes/rerun_helps_or_hurts.py
"""
import importlib.util
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import paths                                  # noqa: E402
from pipeline import slot_translate           # noqa: E402

f = lambda n: format(n, ",")


def load(name):
    spec = importlib.util.spec_from_file_location(name, str(HERE / (name + ".py")))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    ctx = load("example_sense_context")
    jud = load("judge_example_sense")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    arms = ctx.sample(con, 300)
    newA = slot_translate.done_keys(ctx.OUT.with_suffix(".A.jsonl"))
    newB = slot_translate.done_keys(ctx.OUT.with_suffix(".B.jsonl"))
    if not newA:
        print("🔴 先跑 probes/example_sense_context.py --n 300")
        return 1

    q = con.execute
    base, cand, plain = [], [], []
    for it in arms["A"]:
        s = q("""SELECT (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='zh'
                          ORDER BY seq LIMIT 1)
                 FROM example e JOIN sense s ON s.id=e.sense_id WHERE e.id=?""",
              (int(it["id"]),)).fetchone()
        if not s or not s[0]:
            continue
        ra, rb = newA.get(it["fr"]), newB.get(it["fr"])
        if not ra or not rb:
            continue
        common = {"fr": it["fr"], "w": it["_word"], "sense": s[0]}
        base.append(dict(common, id="O" + it["id"], zh=it["_old"]))
        cand.append(dict(common, id="N" + it["id"], zh=ra.get("zh", "")))
        plain.append(dict(common, id="P" + it["id"], zh=rb.get("zh", "")))

    res = {}
    for tag, items in (("旧·库里现有", base), ("新·带上下文重翻", cand),
                       ("新·不带上下文重翻", plain)):
        out = paths.WORK / "examples" / ("rerun_%s.jsonl" % tag[:1])
        slot_translate.translate(items, jud.SYS, out,
                                 fields=("id", "fr", "w", "sense", "zh"),
                                 keep=("fr",), key_field="id", answer_field="v")
        got = slot_translate.done_keys(out)
        c = Counter()
        for it in items:
            r = got.get(it["fr"])
            v = str((r or {}).get("v", "")).strip().lower()
            c[v if v in ("ok", "bad") else "未答"] += 1
        res[tag] = c

    print("\n══ 同一批 %s 条、同一个判官，三种译文各判一次 ══" % f(len(base)))
    for tag, c in res.items():
        n = c["ok"] + c["bad"]
        print("   %-20s bad %-4s / %-4s = **%.2f%%**"
              % (tag, f(c["bad"]), f(n), 100.0 * c["bad"] / max(n, 1)))
    bo = res["旧·库里现有"]["bad"]
    bn = res["新·带上下文重翻"]["bad"]
    print("\n   带上下文重跑：坏的从 %d 条变成 %d 条  ⇒  **净 %+d**" % (bo, bn, bn - bo))
    print("   ⚠️ 判官只看义项取没取对，看不见别处的译文质量 ——")
    print("      所以「净持平」**不等于**「重跑无害」，只等于「重跑没在这一维上赚到」。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
