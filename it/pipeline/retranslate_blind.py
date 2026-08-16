#!/usr/bin/env python3
"""盲重译：直接从**意大利语**产出中文，法语只当参考。2026-08-14，阶段 3c。

═══ 与 judge_via_fr.py 的区别，以及为什么两个都要 ═══
`judge_via_fr` 把**我们的中文也给了模型**看 —— 那会锚定它往 "ok" 上靠（anchoring）。
本脚本**不给它看我们的答案**，只给意语词形 + 法语参考，让它独立产出中文。

⇒ 于是有两个**互相独立**的中文：
     A = 库里的（意 → 法 → 中，二跳）
     B = 本脚本的（意 → 中，一跳，法语仅参考）
   两边一致 = 高置信；两边不一致 = 真正该人看的清单。
   这是把"模型的意语知识"当第二来源、又不被自己答案带偏的唯一办法。

⚠️ B **不是权威源**，是第二来源。这批 17,508 个词形英文版和意语版都没收，
   本来就没有权威源可查 —— 所以"两个独立来源相互印证"是这里能拿到的最强证据。

用法（在 it/ 目录下）：
    python3 pipeline/retranslate_blind.py --run
    python3 pipeline/retranslate_blind.py --compare     # 与库里的比，出分歧清单
    python3 pipeline/retranslate_blind.py --apply       # 按裁决规则落库
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

import dbtool   # noqa: E402
import paths    # noqa: E402
import ark_batch   # noqa: E402  可观测、可续传的跑批器（每批 flush 落盘）

OUT = paths.WORK / "via_fr_blind.jsonl"
KEY = paths.WORK / "via_fr_blind_key.json"
PER = 20
# 见 judge_via_fr.py 的同名注释：turbo-batch 排队太久，改 online
MODE = "online"
CONC = 24
SRC = "doubao-pro:from-it"

SYS = """你是意大利语—中文词典编纂员。每条给你：
`w` 意大利语词形、`fr` 它在**法语**维基词典里的释义（仅供参考）。

请给出 `w` 的**中文对应词式释义**。

🔴 以你对**意大利语**的了解为准。`fr` 只是参考 —— 法语编者有时会换成法语自己的谚语、
   有时丢掉语体色彩、有时比原词更窄或更宽。`fr` 与你了解的意语不一致时，**以意语为准**。

规则：
1. 输出对应词，不是长句翻译；多个用中文逗号分隔，最多 3 个
2. 句末不加任何标点
3. 不要出现"意为""指""该词"这类元话语，也不要写词性标签
4. 习语/谚语给**地道的中文对应说法**，没有对应就给意思
5. 带语体色彩的（粗俗、俚语、文语）要在中文里体现出来
6. 你确实不认识这个意语词、法语也帮不上时，`zh` 输出空字符串 ""，**不要猜**

输出**只有** JSON 对象，键与输入键逐一对应（"1" "2" "3" …），
值形如 {"zh":"中文"}。不要围栏、不要解释、不要改键名。"""

# 负控：给几个**不存在的假意语词**，模型如果照样编出中文，说明它在瞎猜
FAKE = ["zbrellonicare", "mortabbiglio", "franzuletta", "sgrimboccolo", "veltrasione"]


def load(con):
    return [dict(id=r[0], w=r[1], fr=r[2], zh=r[3]) for r in con.execute(
        "SELECT s.id, d.word, x.text, g.text FROM sense_gloss g "
        "JOIN sense s ON s.id = g.sense_id JOIN dict d ON d.id = s.word_id "
        "JOIN sense_src x ON x.sense_id = s.id AND x.src='fr-edition' "
        "WHERE g.lang='zh' AND g.src LIKE '%via-fr' AND COALESCE(s.pos,'') <> 'name' "
        "ORDER BY s.id")]


def main():
    ap = argparse.ArgumentParser()
    for f in ("run", "compare", "apply"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    items = load(con)

    if a.run:
        rnd = random.Random(31)
        fakes = {}
        batches, meta = [], []
        cur, curmeta = {}, []
        for it in items:
            k = str(len(cur) + 1)
            cur[k] = {"w": it["w"], "fr": it["fr"][:160]}
            curmeta.append((k, it["id"]))
            if len(cur) == PER - 1 and rnd.randrange(50) == 0:
                # 掺一个不存在的假意语词：模型若照样编，说明它在瞎猜
                fk = FAKE[len(fakes) % len(FAKE)]
                k2 = str(len(cur) + 1)
                cur[k2] = {"w": fk, "fr": "Définition manquante."}
                fid = -(len(fakes) + 1)
                curmeta.append((k2, fid))
                fakes[fid] = fk
            if len(cur) >= PER:
                batches.append(cur); meta.append(curmeta); cur, curmeta = {}, []
        if cur:
            batches.append(cur); meta.append(curmeta)
        KEY.write_text(json.dumps(fakes, ensure_ascii=False), encoding="utf-8")
        print("■ %s 批，假词负控 %s 个" % (f"{len(batches):,}", f"{len(fakes):,}"))
        asyncio.run(ark_batch.run(SYS, batches, meta, OUT, mode=MODE, conc=CONC))
        return 0

    if a.compare:
        fakes = {int(k): v for k, v in json.loads(KEY.read_text()).items()}
        got = {}
        for line in OUT.open(encoding="utf-8"):
            r = json.loads(line)
            got[r["id"]] = r["zh"]
        made_up = [i for i in fakes if got.get(i)]
        print("🔴 假词负控：%s 个不存在的意语词，模型照样给出中文的 %s 个"
              % (f"{len(fakes):,}", f"{len(made_up):,}"))
        if fakes:
            print("   瞎猜率 %.1f%%（高于 20%% 说明它在编，B 这一路不可信）"
                  % (100.0 * len(made_up) / len(fakes)))
            for i in made_up[:5]:
                print("     %-16s → %s" % (fakes[i], got[i]))
        by = {i["id"]: i for i in items}
        same = diff = empty = 0
        rows = []
        for sid, b in got.items():
            if sid < 0 or sid not in by:
                continue
            a_ = by[sid]["zh"]
            if not b:
                empty += 1
            elif set(b) & set(a_):
                same += 1
            else:
                diff += 1
                rows.append((by[sid]["w"], by[sid]["fr"], a_, b))
        n = same + diff + empty
        print("\n■ 两个独立来源比对（%s 条）" % f"{n:,}")
        print("   一致（有字面重叠）  %8s (%.1f%%)" % (f"{same:,}", 100.0 * same / max(n, 1)))
        print("   🔴 不一致          %8s (%.1f%%)  ← 该看的清单" % (f"{diff:,}", 100.0 * diff / max(n, 1)))
        print("   B 侧留空            %8s (%.1f%%)" % (f"{empty:,}", 100.0 * empty / max(n, 1)))
        p = paths.WORK / "via_fr_disagree.json"
        p.write_text(json.dumps([{"w": w, "fr": f, "A_库里": a2, "B_盲重译": b}
                                 for w, f, a2, b in rows], ensure_ascii=False, indent=1),
                     encoding="utf-8")
        print("\n   分歧清单 → %s" % p)
        for w, f, a2, b in rows[:12]:
            print("   %-20s fr=%-26s A=%-14s B=%s" % (w[:20], f[:26], a2[:14], b[:18]))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
