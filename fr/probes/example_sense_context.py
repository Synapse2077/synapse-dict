#!/usr/bin/env python3
"""探针 — **例句翻译喂了义项上下文，到底能改多少？** 2026-08-27。

═══ 起因 ═══
`pipeline/translate_examples.py` 的 payload 是 `fields=("id", "fr")` ——
**只喂句子，不喂它挂在哪条义项下**。而 77.4% 的例句在翻译器写出来的 29 分钟前
就已经挂好 `sense_id` 了（`ingest_examples.py` 08-25 22:07 / 翻译器 22:36）。
两家外审在 `taper` / `librairie` / `piqué` 三个词上各自独立指出同一形状：

    taper「发臭，散恶臭」 下  `Ça tape ici !`        → 「这儿真热！」
    librairie「公共图书馆」下 `La librairie du roi.`  → 「国王的书店」
    piqué「精神失常的」  下  `Il est un peu piqué.` → 「它有点酸了」

═══ 为什么先探针不直接重跑 ═══
风险面 119,164 条（多义词 **且** 挂在 rank>1）≈ 41 元。
但 119,164 是「**可能**错」不是「错了」—— 法文版大量例句是雨果、福楼拜的长引文，
**句子本身就把义项限定死了**，模型没有上下文照样翻对。
先花 0.2 元把真实差异率量出来，再决定那 41 元该不该花。

═══ 🔴 三个臂，缺一不可 ═══
只跑「带上下文重翻 → 和库里比」会得出一个**没有意义的数**：
重跑本身就会让措辞变一变。必须有控制组把「抖动」减掉。

    A  rank>1  **带**义项上下文     ← 想量的东西
    B  rank>1  **不带**（与原跑批 payload 逐字一致）  ← 控制组：纯重跑的抖动
    C  rank=1  带义项上下文         ← 低风险面对照（模型默认就按最常见义翻）

    真实改善 ≈ diff(A) − diff(B)

⚠️ 「文本不同」≠「变好了」。B 会给出「不同但都对」的基线，而 A 里多出来的那部分
   **我还要自己逐条读**，判断是真改对了还是只是换了说法
   （`[[llm-as-evaluator-discipline]]`：标签收敛 ≠ 内容收敛）。

═══ 纪律 ═══
· 答案落**另一个文件**，不许混进正式那份（`[[model-answer-files-key-by-id]]`）。
· 关思考（`[[batch-never-enables-thinking]]`：翻译不是推导型任务）。
· 抽样只抽**在全库只挂了一条义项**的句子，比较口径才干净。
· 本脚本**一个字都不写库**。

用法（在 fr/ 目录下）：
    python3 -u probes/example_sense_context.py --n 300      # 三臂各 300
    python3 -u probes/example_sense_context.py --read 25    # 逐条读 A 的差异
"""
import argparse
import json
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import paths                                  # noqa: E402
from pipeline import slot_translate           # noqa: E402

f = lambda n: format(n, ",")
OUT = paths.WORK / "examples" / "probe_sense_ctx.jsonl"
slot_translate.CHUNK = 40
slot_translate.CONC = 32

# 🔴 与 `translate_examples.SYS` **逐字相同**，只加了 `s` 字段那一段和规则 8。
#    改动越小，A 与 B 的差异才越能归因到「上下文」而不是「我换了 prompt」。
SYS_CTX = """你在把法语例句翻译成中文，用于一部给中文读者的法语词典。

输入是 JSON 数组，每项有 `id`（标识号，**不是序号**，原样回传）、`fr`（法语句子），
以及 `s`（这条例句挂在哪个义项下：`w`=被举例的词，`zh`=该义项的中文释义，`d`=该义项的法语定义，可能没有）。

规则
1. **完整翻译整句**，不节译、不概括、不加注。
2. 这些句子多是 19–20 世纪文学作品的引文。**保持原文的语体** —— 书面语译成书面语，口语译成口语。
3. 人名、地名、作品名：有通用中文译名的用通用译名；**没有的就保留法语原文**，不要音译生造。
4. 专业术语按该领域的中文说法。
5. **习语、俗语、固定搭配按中文里对应的说法译，不要字面直译。** 例如 `passer cent sept ans sur qch` 是「没完没了地耗在某事上」，不是「耗一百零七年」。
6. 原文残缺、只有半句、或看不出意思，`zh` 给空字符串，不要猜。
7. **只输出译文本身。** 不要输出文献出处、不要加括号解释、不要写「这句话的意思是」这类话。
8. **`s` 是消歧用的：`w` 那个词在这句里就是 `s.zh` 说的那个意思，按它翻。**不要把 `s.zh` 抄进译文，也不要因为它去改写句子的其他部分。

输出 JSON 数组：[{"id": <标识号>, "zh": "<中文译文>"}]
只输出 JSON，不要解释。"""

# B 臂：与正式跑批**逐字一致**的 prompt（从那边 import，不重抄）
from pipeline.translate_examples import SYS as SYS_PLAIN   # noqa: E402


def sample(con, n, seed=20260827):
    """→ {arm: [{id, fr, s, _zh_old, _word, _rank}]}

    只抽**在全库只挂了一条义项**的句子 —— 一句挂多条义项（给不同的词当例句）
    时"该喂哪条上下文"本身是个待定问题，混进来会把差异率搞浑。
    """
    nsense = dict(con.execute(
        "SELECT word_id, COUNT(*) FROM sense WHERE hidden=0 GROUP BY 1"))
    per_text = Counter(t for (t,) in con.execute(
        "SELECT text FROM example WHERE sense_id IS NOT NULL"))
    pools = defaultdict(list)
    for eid, text, sid, rank, wid, word, zh_old in con.execute("""
            SELECT e.id, e.text, s.id, s.rank, s.word_id, d.word,
                   (SELECT text FROM example_gloss WHERE example_id=e.id AND lang='zh')
            FROM example e JOIN sense s ON s.id=e.sense_id
            JOIN dict d ON d.id=s.word_id
            WHERE e.sense_id IS NOT NULL AND e.hidden=0"""):
        if not zh_old or per_text[text] != 1 or nsense.get(wid, 0) < 2:
            continue                       # 没中文 / 一句挂多义项 / 单义词，都不抽
        arm = "A" if rank > 1 else "C"     # 多义词：rank>1 是风险面，rank=1 是对照
        zh = con.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang='zh' "
                         "ORDER BY seq LIMIT 1", (sid,)).fetchone()
        d = con.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang='fr' "
                        "ORDER BY seq LIMIT 1", (sid,)).fetchone()
        ctx = {"w": word, "zh": zh[0] if zh else ""}
        if d:
            ctx["d"] = d[0]
        pools[arm].append({"id": str(eid), "fr": text, "s": ctx,
                           "_old": zh_old, "_word": word, "_rank": rank})
    R = random.Random(seed)
    out = {}
    out["A"] = R.sample(pools["A"], min(n, len(pools["A"])))
    out["C"] = R.sample(pools["C"], min(n, len(pools["C"])))
    # 🔴 B 臂必须与 A 臂**同一批句子**，否则减法没有意义。
    out["B"] = [dict(x, id="B" + x["id"]) for x in out["A"]]
    return out


def norm(s):
    return "".join((s or "").split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--read", type=int, default=0)
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    arms = sample(con, a.n)
    print("■ 抽样：A(rank>1 带上下文) %s ｜ B(同一批，不带) %s ｜ C(rank=1 带上下文) %s"
          % (f(len(arms["A"])), f(len(arms["B"])), f(len(arms["C"]))))

    for arm, sys_prompt, fields in (("A", SYS_CTX, ("id", "fr", "s")),
                                    ("B", SYS_PLAIN, ("id", "fr")),
                                    ("C", SYS_CTX, ("id", "fr", "s"))):
        items = arms[arm]
        # 落盘键是 `fr`，B 臂与 A 臂句子相同 ⇒ B 单独一个文件，否则互相认领
        out = OUT.with_suffix(".%s.jsonl" % arm)
        slot_translate.translate(items, sys_prompt, out,
                                 fields=fields, keep=("fr",),
                                 key_field="id", answer_field="zh")

    print("\n══ 结果 ══")
    got = {}
    for arm in "ABC":
        got[arm] = slot_translate.done_keys(OUT.with_suffix(".%s.jsonl" % arm))
    stat = {}
    for arm in "ABC":
        items, diff, blank = arms[arm], 0, 0
        n = 0
        for it in items:
            rec = got[arm].get(it["fr"])
            if not rec:
                continue
            n += 1
            new = rec.get("zh", "")
            if not new.strip():
                blank += 1
            if norm(new) != norm(it["_old"]):
                diff += 1
        stat[arm] = (n, diff, blank)
        print("   %s  已答 %-5s 与库里不同 %-5s (%.1f%%)  留空 %s"
              % (arm, f(n), f(diff), 100.0 * diff / max(n, 1), f(blank)))
    nA, dA, _ = stat["A"]
    nB, dB, _ = stat["B"]
    print("\n   A %.1f%%  −  B(纯重跑抖动) %.1f%%  =  **归因于义项上下文 %.1f 个百分点**"
          % (100.0 * dA / max(nA, 1), 100.0 * dB / max(nB, 1),
             100.0 * dA / max(nA, 1) - 100.0 * dB / max(nB, 1)))
    print("   ⚠️ 这只是「文本变了」。变好没变好要我自己读 —— `--read N`")

    if a.read:
        print("\n══ A 臂的差异（逐条读；B = 同一句不带上下文重跑）══")
        shown = 0
        for it in arms["A"]:
            ra, rb = got["A"].get(it["fr"]), got["B"].get(it["fr"])
            if not ra or norm(ra.get("zh", "")) == norm(it["_old"]):
                continue
            shown += 1
            print("\n[%s r%d] %s" % (it["_word"], it["_rank"], it["s"]["zh"]))
            print("   FR   %s" % it["fr"][:150])
            print("   库里 %s" % (it["_old"] or "")[:110])
            print("   带ctx %s" % ra.get("zh", "")[:110])
            if rb:
                print("   不带  %s" % rb.get("zh", "")[:110])
            if shown >= a.read:
                break
    return 0


if __name__ == "__main__":
    sys.exit(main())
