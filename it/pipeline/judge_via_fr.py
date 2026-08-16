#!/usr/bin/env python3
"""全量筛查「二手·普通词」那 17,508 条中文。2026-08-14，阶段 3c。

═══ 这一轮判官能做什么、不能做什么 ═══
🔴 **拿「中文 vs 法语」判，逮不到那四种损耗** —— 损耗发生在法语那一步，法语本身
   就是错的/窄的（`chi va a Roma perde la poltrona` 的法语侧是**另一条法语谚语**）。
⇒ payload 必须**同时给意语词形**，让判官用自己的意语知识判。
   但这样判官就从"验证者"变成了"第二个来源"：按 `llm-as-evaluator-discipline`，
   它**只能定位、不能验收**（判官自噪实测 45%）。本脚本的产物是**可疑清单**，不是判决。

═══ 为什么用豆包 turbo batch ═══
· 中文是 deepseek 家（flash / v4-pro）写的 ⇒ **谁写的不能由谁判**，换豆包家
· 全量 1.7 万条，turbo batch 半价、隔夜延迟无所谓
· 关思考（这是校对不是推导）

═══ 两个必须的护栏 ═══
① **本地键 `1..N`**：豆包 turbo 会把全局键 `20_1` 重编号成 `1`（`quality_pass` 踩过）
② **负控**：混入人为弄坏的条目，判官逮不到就说明这轮结果不能用

用法（在 it/ 目录下）：
    python3 pipeline/judge_via_fr.py --plan
    python3 pipeline/judge_via_fr.py --run
    python3 pipeline/judge_via_fr.py --report
"""
import argparse
import asyncio
import json
import random
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import paths   # noqa: E402
import ark_batch   # noqa: E402  可观测、可续传的跑批器（每批 flush 落盘）

OUT = paths.WORK / "via_fr_judge.jsonl"
KEY = paths.WORK / "via_fr_judge_key.json"
PER = 20          # 每批条数
# 🔴 turbo-batch 实测单批要 24 分钟（在排队），全量要 29 小时 —— 半价不值这个等待。
#    改走 online pro：贵一些但可控。`ark_batch` 有续传，切模式不丢已跑的。
MODE = "online"
CONC = 24
POISON_RATE = 60  # 每 60 条掺 1 条负控

SYS = """你是意大利语—中文词典质检员。每条给你三样东西：
`w` 意大利语词形、`fr` 它在法语维基词典里的释义、`zh` 我们据此产出的中文释义。

判断 **`zh` 是否正确传达了 `w` 这个意大利语词的意思**。
⚠️ `fr` 只是参考：法语编者有时会换成法语自己的说法、或丢掉语体色彩。
   以你对**意大利语**的了解为准，`fr` 与意语不符时以意语为准。

每条给：
- `v`：`ok`（可用）/ `weak`（意思大致对但偏窄、偏宽、丢语体、不像词典说法）/ `bad`（意思错或没翻）
- `s`：仅当 `v` 不是 ok 时给出你建议的中文（对应词式，不超过 15 字，句末无标点）

输出**只有** JSON 对象，键与输入的键**逐一对应**（就是 "1" "2" "3" …），
值形如 {"v":"ok"} 或 {"v":"bad","s":"建议中文"}。不要围栏、不要解释、不要改键名。"""


def load(con):
    return [dict(id=r[0], w=r[1], fr=r[2], zh=r[3]) for r in con.execute(
        "SELECT s.id, d.word, x.text, g.text FROM sense_gloss g "
        "JOIN sense s ON s.id = g.sense_id JOIN dict d ON d.id = s.word_id "
        "JOIN sense_src x ON x.sense_id = s.id AND x.src='fr-edition' "
        "WHERE g.lang='zh' AND g.src LIKE '%via-fr' AND COALESCE(s.pos,'') <> 'name' "
        "ORDER BY s.id")]


POISON = ["张三", "电冰箱", "紫色", "钢琴", "跑步", "星期二"]


def main():
    ap = argparse.ArgumentParser()
    for f in ("plan", "run", "report"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    items = load(con)

    if a.plan:
        print("■ 待判 %s 条（二手·普通词）" % f"{len(items):,}")
        print("   分 %s 批 × %d 条；负控约 %s 条"
              % (f"{(len(items) + PER - 1) // PER:,}", PER, f"{len(items) // POISON_RATE:,}"))
        return 0

    if a.run:
        rnd = random.Random(29)
        poisoned = {}
        batches, meta = [], []
        cur, curmeta = {}, []
        for it in items:
            k = str(len(cur) + 1)
            zh = it["zh"]
            if rnd.randrange(POISON_RATE) == 0:
                zh = POISON[len(poisoned) % len(POISON)]
                poisoned[it["id"]] = zh
            cur[k] = {"w": it["w"], "fr": it["fr"][:160], "zh": zh}
            curmeta.append((k, it["id"]))
            if len(cur) == PER:
                batches.append(cur); meta.append(curmeta); cur, curmeta = {}, []
        if cur:
            batches.append(cur); meta.append(curmeta)
        KEY.write_text(json.dumps(poisoned, ensure_ascii=False), encoding="utf-8")
        print("■ %s 批，负控 %s 条" % (f"{len(batches):,}", f"{len(poisoned):,}"))
        asyncio.run(ark_batch.run(SYS, batches, meta, OUT, mode=MODE, conc=CONC))
        return 0

    if a.report:
        poisoned = {int(k): v for k, v in json.loads(KEY.read_text()).items()}
        got = {}
        for line in OUT.open(encoding="utf-8"):
            r = json.loads(line)
            got[r["id"]] = r
        c = Counter(v.get("v") for v in got.values())
        caught = sum(1 for i in poisoned if got.get(i, {}).get("v") == "bad")
        soft = sum(1 for i in poisoned if got.get(i, {}).get("v") in ("bad", "weak"))
        print("■ 判了 %s / %s 条" % (f"{len(got):,}", f"{len(items):,}"))
        print("   %s" % dict(c))
        print("\n🔴 负控：人为弄坏 %s 条，判 bad 的 %s、判 bad/weak 的 %s"
              % (f"{len(poisoned):,}", f"{caught:,}", f"{soft:,}"))
        if poisoned:
            print("   负控召回率 %.1f%%（低于 90%% 这轮结果不能用）"
                  % (100.0 * caught / len(poisoned)))
        real = {i: v for i, v in got.items() if i not in poisoned}
        cr = Counter(v.get("v") for v in real.values())
        n = sum(cr.values()) or 1
        print("\n■ 真实数据（%s 条）" % f"{n:,}")
        for k in ("ok", "weak", "bad"):
            print("   %-6s %8s (%.1f%%)" % (k, f"{cr[k]:,}", 100.0 * cr[k] / n))
        by = {i["id"]: i for i in items}
        print("\n■ 判 bad 的样例")
        shown = 0
        for i, v in real.items():
            if v.get("v") == "bad" and shown < 12 and i in by:
                x = by[i]
                print("   %-22s fr=%-30s 我们=%-14s 判官建议=%s"
                      % (x["w"][:22], x["fr"][:30], x["zh"][:14], (v.get("s") or "")[:16]))
                shown += 1
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
