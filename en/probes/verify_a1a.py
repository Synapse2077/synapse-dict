#!/usr/bin/env python3
"""A1a 回填结果抽样验证(read-only,pro online)。见对话 2026-07-27。

fix_a1a.py 把 15,675 条"纯元描述空壳"回填成「元描述 + base 词义」。
确定性核验已过(变动集==留痕集/只增不改/空壳清零/无[网络]/核心零波及),
但**确定性只能证明"改动如我所愿",证不了"词义对不对"** → 这一步交 pro 判内容。

判据:回填后的整条中文,对该英语词条是否准确可用。
  ok   = 词义对、变形关系也对(cofferdams=cofferdam的复数,义"围堰" → ok)
  warn = 义对但元描述标错(covaries 实为第三人称单数,却写"复数")或略生硬
  bad  = 真错:base 认错、词义与该词无关、回填内容自相矛盾

用法: python3 en/verify_a1a.py --n 300
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
import argparse, asyncio, json, random
from collections import Counter
from pathlib import Path

import acceptance_en as A  # 复用 load_env/run_batches

import paths

HERE = Path(__file__).resolve().parent
LOG = paths.WORK / "ledgers/a1a_fill.tsv"
CHUNK = 20

JUDGE_SYS = """你是英汉词典质检专家。给你一批英语词条,每条含 word(英语词)、zh(该词条的中文译文)。
这些 word 多是**变形词**(复数/分词/第三人称单数等),译文格式为「X的复数」等元描述 + 换行 + 原形 X 的词义。
凭你自身英语知识,判断**这条中文对该英语词是否准确、可用**:
- ok   = 词义正确,且元描述里的原形和变形关系也正确;
- warn = 词义正确但元描述的变形类型标错(如实为第三人称单数却写"复数"),或表述略生硬;
- bad  = 真错:原形认错、给出的词义与该词无关、内容自相矛盾或是无意义垃圾。
注意:词条生僻、或译文带 [医][化] 等学科标签、<德> 等语源标记,都**不算问题**。
每条返回 {"v":"ok|warn|bad","note":"简短问题(warn/bad时)"}。
严格输出 JSON {"1":{"v":"ok"},"2":{"v":"bad","note":"..."},...},键与输入一致,无多余文字。"""


REV = paths.WORK / "ledgers/a1a_reverted.tsv"
PREV = paths.WORK / "runs/verify_a1a.jsonl"


def load_rows(kept_only, fresh):
    """kept_only: 只取六道闸留存的; fresh: 排除上一轮已判过的词(六道闸是拿那批设计的,同批评估会高估)。"""
    rev = set()
    if kept_only and REV.exists():
        for i, ln in enumerate(open(REV, encoding="utf-8")):
            if i:
                rev.add(int(ln.split("\t")[0]))
    judged = set()
    if fresh and PREV.exists():
        for ln in open(PREV, encoding="utf-8"):
            judged.add(json.loads(ln)["w"])
    rows = []
    for i, ln in enumerate(open(LOG, encoding="utf-8")):
        if not i:
            continue
        p = ln.rstrip("\n").split("\t")
        if len(p) < 5 or int(p[0]) in rev or p[1] in judged:
            continue
        rows.append((p[1], p[4].replace("\\n", "\n")))  # word, after
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--kept-only", action="store_true", help="只验六道闸留存的 10,674 条")
    ap.add_argument("--fresh", action="store_true", help="排除上一轮已判过的词,取独立新样本")
    ap.add_argument("--seed", type=int, default=20260727)
    ap.add_argument("--out", default="runs/verify_a1a.jsonl")
    a = ap.parse_args()
    n = a.n

    allrows = load_rows(a.kept_only, a.fresh)
    random.seed(a.seed)
    rows = random.sample(allrows, min(n, len(allrows)))
    print(f"候选池 {len(allrows)} 条(kept_only={a.kept_only} fresh={a.fresh}),抽样 {len(rows)} 条交 pro")

    env = A.load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=A.TIMEOUT)
        batches, metas = [], []
        for j in range(0, len(rows), CHUNK):
            sub = rows[j:j + CHUNK]
            batches.append({str(k): {"word": r[0], "zh": r[1]} for k, r in enumerate(sub, 1)})
            metas.append(sub)
        res, tok = await A.run_batches(JUDGE_SYS, batches, env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions)
        await cl.close()
        return metas, res, tok

    metas, results, tok = asyncio.run(go())
    tally = Counter(); flagged = []
    outp = HERE / a.out
    with open(outp, "w", encoding="utf-8") as f:
        for meta, res in zip(metas, results):
            res = res or {}
            for k, (w, zh) in enumerate(meta, 1):
                v = res.get(str(k))
                verdict = v.get("v") if isinstance(v, dict) else None
                if verdict not in ("ok", "warn", "bad"):
                    verdict = "novote"
                note = v.get("note", "") if isinstance(v, dict) else ""
                tally[verdict] += 1
                if verdict in ("warn", "bad"):
                    flagged.append((verdict, w, zh, note))
                f.write(json.dumps(dict(w=w, zh=zh, v=verdict, note=note), ensure_ascii=False) + "\n")

    tot = sum(tally.values()); scored = tot - tally["novote"]
    print(f"\n===== A1a 抽样 {tot} 条(有效 {scored}) token {tok} =====")
    for lab in ("ok", "warn", "bad"):
        print(f"  {lab:5} {tally[lab]:>4} ({100*tally[lab]/max(scored,1):5.1f}%)")
    print(f"  novote {tally['novote']}")
    print("\n  非 ok 明细:")
    for v, w, zh, note in flagged[:40]:
        print(f"    [{v}] {w}: {zh.replace(chr(10),' ⏎ ')[:52]} || {note[:44]}")
    print(f"\n  明细 → {outp.name}")


if __name__ == "__main__":
    main()
