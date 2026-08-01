#!/usr/bin/env python3
"""按桶抽样验收(read-only,不写库)。见对话 2026-07-27。

尾巴 387 万分九桶(见 buckets.py),各桶来源与病理不同,**必须分桶各测各的**,
不能拿一个总体数字代表全库。已知:B1 纯音译抽 1000 → bad 53.6%(过半是错的)。

⚠️ 服务面认知修正:早先以为"多词短语划不到、不用管"是**错的**。
   `packages/dict-core/src/index.ts:250` getEntry() 是 `WHERE word = ? COLLATE NOCASE`,
   拿划选原文精确匹配 → 划选 'clear title' / 'axial relief angle' 全部命中。
   **服务面是全部 387 万,短语同样要测质量。**

turbo batch 半价 + pro 超时兜底。
用法:
  python3 en/verify_bucket.py --bucket C6 --n 1000
  python3 en/verify_bucket.py --bucket B2 --n 1000
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
import argparse, asyncio, json, random, sqlite3
from collections import Counter
from pathlib import Path

import acceptance_en as A
import sweep_core as S
import buckets as B

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
CHUNK = 20

JUDGE_SYS = """你是英汉词典质检专家。给你一批英语词条,每条含 word(英语词或短语)、zh(中文译文)。
凭你自身英语知识,判断 zh 对该 word 是否**准确、可用**。只把下列情况判 bad:
- **错译**:中文与该词/短语实际意思不符;
- **张冠李戴**:译成了无关的人、物或概念;
- **无意义垃圾**:中文读不通、是机翻残片、乱码或明显残缺;
- **漏掉最主要义**:只给了次要/生僻义,把最常用义漏了。

**以下一律判 ok(务必从宽)**:
- 词条生僻、专业、古旧、方言 —— 只要译得对就是 ok;
- 是专业术语的直译(如"轴向后角""分光敏度测量")—— ok;
- 是人名/地名/学名的**合理音译或通行译名** —— ok;
- 带 [医][化][计][法] 学科标签、给了多个并列候选译名(用;分隔) —— ok;
- 缺词性前缀等格式小瑕 —— ok。

warn 只留给"意思大体对但明显不准确/有小错"的中间地带。拿不准就判 ok。
严格输出 JSON {"1":{"v":"ok"},"2":{"v":"bad","note":"简短问题"},...},键与输入一致,无多余文字。"""


def sample(bucket, n, seed):
    conn = sqlite3.connect(DB)
    pool = [(i, w, t) for i, w, t, b in B.load_tail(conn) if b == bucket]
    conn.close()
    random.seed(seed)
    return pool, random.sample(pool, min(n, len(pool)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", required=True, choices=list(B.LABELS))
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=20260727)
    a = ap.parse_args()

    pool, rows = sample(a.bucket, a.n, a.seed)
    print(f"[{a.bucket} {B.LABELS[a.bucket]}] 全桶 {len(pool)} 条,抽样 {len(rows)} 条", flush=True)

    env = A.load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
        model = env["DOUBAO_SEED_2_1_TURBO_BATCH"]
        # ⚠️ 阈值别用 180/300s:batch 队列一堵就**每批都切 online pro**,单价差一个数量级。
        #   而且这里还有第二重代价 —— **切过去的批次是 pro 判的,和 turbo 口径不同**,
        #   混在一个数字里就没法和历轮比(2026-07-30 实测豆包 pro 比 v4-pro 严 11pp,
        #   判官之间的系统性偏差远大于我们要测的变化量)。测量脚本尤其要让 hedge 尽量不触发。
        hedge = (env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions, 1200)
        batches, metas = [], []
        for j in range(0, len(rows), CHUNK):
            sub = rows[j:j + CHUNK]
            batches.append({str(k): {"word": r[1], "zh": r[2]} for k, r in enumerate(sub, 1)})
            metas.append(sub)
        res, tok = await S.run_batches(JUDGE_SYS, batches, model, cl.batch.chat.completions, hedge)
        await cl.close()
        return metas, res, tok

    metas, results, tok = asyncio.run(go())
    tally = Counter(); bad = []
    outp = HERE / f"runs/verify_bucket_{a.bucket}.jsonl"
    with open(outp, "w", encoding="utf-8") as f:
        for meta, res in zip(metas, results):
            res = res or {}
            for k, (rid, w, t) in enumerate(meta, 1):
                v = res.get(str(k))
                verdict = v.get("v") if isinstance(v, dict) else None
                if verdict not in ("ok", "warn", "bad"):
                    verdict = "novote"
                note = v.get("note", "") if isinstance(v, dict) else ""
                tally[verdict] += 1
                if verdict == "bad":
                    bad.append((w, t, note))
                f.write(json.dumps(dict(id=rid, w=w, zh=t, v=verdict, note=note),
                                   ensure_ascii=False) + "\n")

    tot = sum(tally.values()); scored = tot - tally["novote"]
    print(f"\n===== [{a.bucket}] {tot} 条(有效 {scored}) token {tok} =====")
    for lab in ("ok", "warn", "bad"):
        print(f"  {lab:5} {tally[lab]:>5} ({100*tally[lab]/max(scored,1):5.1f}%)")
    print(f"  novote {tally['novote']}")
    print(f"  可用率(ok+warn) {100*(tally['ok']+tally['warn'])/max(scored,1):.1f}%")
    print("\n  bad 样本:")
    for w, t, note in bad[:20]:
        print(f"    {w[:28]:30} {t.replace(chr(10),' / ')[:34]} || {note[:40]}")
    print(f"\n  明细 → {outp.name}")


if __name__ == "__main__":
    main()
