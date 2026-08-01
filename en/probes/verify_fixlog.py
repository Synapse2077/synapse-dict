#!/usr/bin/env python3
"""对任意一份改写留痕 TSV 做改造后抽样验收(read-only)。见对话 2026-07-29。

为什么需要:2026-07-29 盘点发现 07-28 15:14 之后的 15 轮改造共 31.6 万条**零验收** ——
不是没做,是没有工具沉淀,每次都靠临时脚本。本脚本把"改完就验"固化下来。

判据逐字沿用 verify_bucket.py 的 JUDGE_SYS,数字才能和历轮/全库抽样直接比。
模型默认 **pro online**(判对错是知识题);hedge=None → run_batches 走 acall(batch=False)。

🔴 **谁写的就不能由谁判**:2026-07-30 用豆包 pro 改写 skip 集时发现,前面几轮验收的判官
   恰好也是豆包 pro —— 自己给自己打分,bad 率必然虚低。--judge ds-pro 走 DeepSeek v4-pro
   做交叉验证(它在判官岗位上实测 100% 精确率,且是这批任务里最保守的一个)。

用法:
  python3 en/verify_fixlog.py a1_turbo_fix.newshell.tsv --n 300
  python3 en/verify_fixlog.py b2_anchored_fix.tsv --n 500 --seed 42
  python3 en/verify_fixlog.py low_skip2_fix.tsv --n 266 --judge ds-pro   # 交叉验证
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
import argparse, asyncio, json, random, secrets
from collections import Counter
from pathlib import Path

import acceptance_en as A
import sweep_core as S
from verify_bucket import JUDGE_SYS

HERE = Path(__file__).resolve().parent
CHUNK = 20


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tsv", help="改写留痕 TSV(列:id word before after)")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--judge", choices=["ark-pro", "ds-pro"], default="ark-pro",
                    help="判官。改写方是豆包时**必须**换 ds-pro,否则是自己判自己")
    ap.add_argument("--conc", type=int, default=20)
    a = ap.parse_args()
    seed = a.seed if a.seed is not None else secrets.randbelow(2**31)

    src = HERE / a.tsv
    rows = []
    for i, ln in enumerate(open(src, encoding="utf-8")):
        if not i:
            continue
        c = ln.rstrip("\n").split("\t")
        if len(c) >= 4:
            un = lambda s: s.replace("\\t", "\t").replace("\\n", "\n")
            rows.append((int(c[0]), c[1], un(c[2]), un(c[3])))

    random.seed(seed)
    pick = random.sample(rows, min(a.n, len(rows)))
    print(f"[{a.tsv}] 全量 {len(rows):,} 条,随机抽 {len(pick)} 条  seed={seed}", flush=True)

    env = A.load_env()
    metas = [pick[j:j + CHUNK] for j in range(0, len(pick), CHUNK)]
    # 只喂 word + 改写后译文:判"这条现在对不对",不给 before 以免锚定判官
    batches = [{str(k): {"word": r[1], "zh": r[3]} for k, r in enumerate(m, 1)} for m in metas]

    async def go_ark():
        from volcenginesdkarkruntime import AsyncArk
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
        print(f"  → {len(batches)} 批,豆包 pro online", flush=True)
        res, tok = await S.run_batches(JUDGE_SYS, batches, env["DOUBAO_SEED_2_1_PRO"],
                                       cl.chat.completions, None)
        await cl.close()
        return res, tok

    async def go_ds():
        import httpx
        from judge_sample import ds_call
        cl = httpx.AsyncClient(timeout=httpx.Timeout(900.0))
        print(f"  → {len(batches)} 批,DeepSeek v4-pro(交叉验证)", flush=True)
        out = [None] * len(batches); tk = [0]; sem = asyncio.Semaphore(a.conc)

        async def one(i, p):
            async with sem:
                d = 3
                for att in range(4):
                    try:
                        txt, (pi, co, _) = await ds_call(cl, env["DEEPSEEK_API_KEY"],
                                                         "deepseek-v4-pro", JUDGE_SYS, p)
                        tk[0] += pi + co
                        out[i] = A.loads_lenient(txt.strip())
                        return
                    except Exception as e:
                        if att == 3:
                            print(f"  ✗ 批{i} {type(e).__name__}", flush=True)
                        else:
                            await asyncio.sleep(d); d = min(d * 2, 30)

        await asyncio.gather(*[one(i, p) for i, p in enumerate(batches)])
        await cl.aclose()
        return out, tk[0]

    results, tok = asyncio.run(go_ds() if a.judge == "ds-pro" else go_ark())

    tally = Counter(); bad = []
    out = HERE / f"runs/verify_{src.stem}.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps(dict(_meta=True, src=a.tsv, seed=seed, n=len(pick),
                                pool=len(rows), model=a.judge), ensure_ascii=False) + "\n")
        for meta, res in zip(metas, results):
            res = res or {}
            for k, (rid, w, before, after) in enumerate(meta, 1):
                v = res.get(str(k))
                verdict = v.get("v") if isinstance(v, dict) else None
                if verdict not in ("ok", "warn", "bad"):
                    verdict = "novote"
                note = v.get("note", "") if isinstance(v, dict) else ""
                tally[verdict] += 1
                if verdict == "bad":
                    bad.append((w, before, after, note))
                f.write(json.dumps(dict(id=rid, w=w, before=before, after=after,
                                        v=verdict, note=note), ensure_ascii=False) + "\n")

    tot = sum(tally.values()); scored = tot - tally["novote"]
    print(f"\n===== {a.tsv} {tot} 条(有效 {scored}) token {tok:,} =====")
    for lab in ("ok", "warn", "bad"):
        print(f"  {lab:5} {tally[lab]:>4} ({100*tally[lab]/max(scored,1):5.1f}%)")
    print(f"  novote {tally['novote']}")
    print(f"  可用率(ok+warn) {100*(tally['ok']+tally['warn'])/max(scored,1):.1f}%")
    p = tally["bad"] / max(scored, 1)
    se = (p * (1 - p) / max(scored, 1)) ** 0.5
    print(f"  bad 率 95% CI ≈ {100*max(0,p-1.96*se):.1f}% – {100*(p+1.96*se):.1f}%")
    print("\n  bad 样本(前 15):")
    for w, bf, af, note in bad[:15]:
        print(f"    {w[:22]:24} 前:{bf.replace(chr(10),' / ')[:24]:26} 后:{af.replace(chr(10),' / ')[:30]}")
        print(f"      └ {note[:70]}")
    print(f"\n  明细 → {out.name}")


if __name__ == "__main__":
    main()
