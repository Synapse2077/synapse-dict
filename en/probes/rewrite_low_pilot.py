#!/usr/bin/env python3
"""qual=low(40.6 万)的核对式纠错 —— pilot。见对话 2026-07-30。

⭐ 为什么**不先标记**:low 实测 bad 28.4%,基准率一高,标记阶段就不划算了 ——
   它的价值来自"跳过大量正确条目省重译费",而当 28% 是坏的,省下的钱
   抵不过标记器丢掉约 30% 召回的损失。实测算账(v4-pro 单价):
     先标记再修  65 元 / 修到 ~80,700 条 = 0.00081 元/条
     直接核对    88 元 / 覆盖 ~115,300 条 = 0.00076 元/条  ← 更便宜且多抓 43%
   反过来 fair(bad 9.4%)算下来标记划算。**交叉点约在 bad 率 15–20%。**

🔴 本轮最大风险:low 里 **98.1% 无 kaikki 锚**(B1 22.2 万是 [网络] 众包音译,
   词本身 Wiktionary 都没收)。让模型给这些词"纠错"= 让它凭空造词义。
   fix_a1_shells_turbo 记过这个坑:ammianuss / chamaea fasciatas 被编出了像样的释义,
   "在给不该存在的词条编造合法性"。
   → 选 v4-pro 正是因为它最保守(判官岗位实测 100% 精确率 / 22% 召回,且不编造),
     并且 prompt 里把 skip 写成第一优先。**skip 率过低要当成危险信号,不是效率低。**

read-only,不写库。用法:
  python3 en/rewrite_low_pilot.py                    # 默认 500 条 pilot
  python3 en/rewrite_low_pilot.py --n 200 --bucket B1
  python3 en/rewrite_low_pilot.py --n 20000 --conc 32   # 规模化试跑,量真实话费
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
import argparse, asyncio, json, random, sqlite3, time
from collections import Counter
from pathlib import Path

import acceptance_en as A
import buckets as B
from judge_sample import ARK_MODELS, ark_call, ds_call

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
CHUNK = 10          # 输出比判官重(要写译文),批小一点降低单批失败代价
GLOSS = ["anchors/b1_kaikki_gloss.json", "anchors/b2_kaikki_gloss.json",
         "anchors/c3_kaikki_gloss.json", "anchors/residue_kaikki_gloss.json"]

SYS = """你是英汉词典编纂专家。给你一批英语词条,每条含:
  word  英语词条
  zh    词典现有中文译文 —— 来自网络众包,**质量很差**(实测约 28% 是错的)
  en    (有则给)该词在 Wiktionary 的英文释义,**可信**,有则以它为准

对每条给出三种处置之一:
  keep  现有 zh 准确可用           → {"a":"keep"}
  fix   现有 zh 错,而你**确知**该词正确含义 → {"a":"fix","zh":"正确译文"}
  skip  你**不确知**该词含义        → {"a":"skip"}

🔴 **最重要的一条,优先于其他所有要求**:
   这批词里有相当比例是原词典机械造出来的、拼错的、或根本不存在的词形。
   **你不认识就必须 skip,绝对不许猜。**
   给一个不存在的词编出像样的释义,比留着原来的错译**更有害** ——
   它会让错误显得可信,而且没人能发现。
   宁可 skip 一百条,也不要编造一条。judge 会专门检查这一点。

fix 时的写法要求:
  - 给该词**本身**的实际词义,不要写"X 的变形"这类形态说明;
  - 词性用 n./adj./v./adv. 等;可带 [医][化][计][法][生][地] 学科标签;
  - **不要写 [网络] 这个标记**;
  - 人名/地名要补上它是谁/在哪;学名要给中文名;
  - 简短即可,词典条目不需要解释句。

严格输出 JSON,键与输入一致:{"1":{"a":"keep"},"2":{"a":"fix","zh":"…"},"3":{"a":"skip"}}
不要任何解释文字。"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--bucket", choices=["B1", "B2", "C3"])
    ap.add_argument("--seed", type=int, default=20260730)
    ap.add_argument("--model", default="deepseek-v4-pro")
    ap.add_argument("--provider", choices=["deepseek", "ark"], default="deepseek",
                    help="ark 时 --model 用 mini/lite/pro/turbo")
    ap.add_argument("--skip-from", help="不抽库,改从上一轮 jsonl 里取 a==skip 的条目当池。"
                                        "用于**换个模型二次核对** v4-pro 不认识的那半边")
    ap.add_argument("--exclude-from", action="append", default=[],
                    help="排除这些 jsonl 里已处置过的 id(可多次),别花钱重跑")
    ap.add_argument("--conc", type=int, default=20)
    ap.add_argument("--mix", choices=["real", "even"], default="real",
                    help="real=按 low 池真实桶占比(B1 55%%/B2 38%%/C3 7%%)抽,默认;"
                         "even=40/40/20,只为复现 2026-07-30 首轮 pilot")
    a = ap.parse_args()

    gl = {}
    for f in GLOSS:
        p = HERE / f
        if p.exists():
            for k, v in json.load(open(p, encoding="utf-8")).items():
                if k not in gl:
                    s = v if isinstance(v, str) else (
                        next((str(x) for x in v if str(x).strip()), "") if isinstance(v, list) else "")
                    if s.strip():
                        gl[k] = s.strip()
    print(f"锚库合并后 {len(gl):,} 词形", flush=True)

    pool = {"B1": [], "B2": [], "C3": []}
    if a.skip_from:
        for ln in open(HERE / a.skip_from, encoding="utf-8"):
            r = json.loads(ln)
            if not r.get("_meta") and r.get("a") == "skip" and r["bucket"] in pool:
                pool[r["bucket"]].append((r["id"], r["w"], r["before"]))
        print(f"[skip 池] 取自 {a.skip_from}:{sum(len(v) for v in pool.values()):,} 条", flush=True)
    else:
        conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        q = dict(conn.execute("SELECT id, COALESCE(qual,'') FROM stardict"))
        for rid, w, t, bk in B.load_tail(conn):
            if q.get(rid) == "low" and bk in pool:
                pool[bk].append((rid, (w or "").strip(), (t or "").strip()))
        conn.close()

    if a.exclude_from:
        seen = set()
        for f in a.exclude_from:
            for ln in open(HERE / f, encoding="utf-8"):
                r = json.loads(ln)
                if not r.get("_meta"):
                    seen.add(r["id"])
        before = sum(len(v) for v in pool.values())
        for bk in pool:
            pool[bk] = [r for r in pool[bk] if r[0] not in seen]
        print(f"[排除] 已处置 {len(seen):,} 条 → 池 {before:,} 减到 "
              f"{sum(len(v) for v in pool.values()):,}", flush=True)
    random.seed(a.seed)
    # ⚠️ 桶配比会**改变最终结果**,不只是改变成本:实测 fix 率 B2 52.5% vs B1 31.5%、
    #   skip 率 B1 65%,而 bad 几乎全堆在 skip 里。40/40/20 抽出来的 bad 降幅不能外推全量。
    #   (成本倒是不敏感,两种配比每条输出只差 1%。)
    if a.bucket:
        quota = {a.bucket: a.n}
    elif a.mix == "even":
        quota = {"B1": int(a.n * .4), "B2": int(a.n * .4), "C3": a.n - 2 * int(a.n * .4)}
    else:
        tot = sum(len(v) for v in pool.values())
        quota = {b: round(a.n * len(pool[b]) / tot) for b in pool}
    rows = []
    for bk, k in quota.items():
        take = random.sample(pool[bk], min(k, len(pool[bk])))
        rows += [(r[0], r[1], r[2], bk) for r in take]
        print(f"  {bk} 全池 {len(pool[bk]):,} → 抽 {len(take)}", flush=True)
    random.shuffle(rows)

    nen = sum(1 for r in rows if gl.get(r[1].lower()))
    print(f"共 {len(rows)} 条,其中有 kaikki 锚 {nen} ({100*nen/max(len(rows),1):.1f}%)", flush=True)

    env = A.load_env()

    async def go():
        if a.provider == "ark":
            from volcenginesdkarkruntime import AsyncArk
            cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
            mdl = env[ARK_MODELS[a.model]]
            call = lambda p: ark_call(cl, mdl, SYS, p)
        else:
            import httpx
            cl = httpx.AsyncClient(timeout=httpx.Timeout(900.0))
            call = lambda p: ds_call(cl, env["DEEPSEEK_API_KEY"], a.model, SYS, p)
        metas = [rows[j:j + CHUNK] for j in range(0, len(rows), CHUNK)]
        batches = []
        for m in metas:
            b = {}
            for k, r in enumerate(m, 1):
                d = {"word": r[1], "zh": r[2][:150]}
                g = gl.get(r[1].lower())
                if g:
                    d["en"] = g[:180]
                b[str(k)] = d
            batches.append(b)
        sem = asyncio.Semaphore(a.conc)
        out = [None] * len(batches); pt = [0]; ct = [0]; hit = [0]; done = [0]
        try:
            await call(batches[0])
            print("  [预热] 缓存已建立", flush=True)
        except Exception as e:
            print(f"  [预热] {type(e).__name__}", flush=True)

        async def one(i, p):
            async with sem:
                d = 3
                for att in range(4):
                    try:
                        txt, (pi, co, hi) = await call(p)
                        pt[0] += pi; ct[0] += co; hit[0] += hi
                        out[i] = A.loads_lenient(txt.strip())
                        break
                    except Exception as e:
                        if att == 3:
                            print(f"  ✗ 批{i} {type(e).__name__}: {str(e)[:90]}", flush=True)
                        else:
                            await asyncio.sleep(d); d = min(d * 2, 30)
                done[0] += 1
                if done[0] % 10 == 0 or done[0] == len(batches):
                    print(f"  [{done[0]}/{len(batches)}] 输入 {pt[0]:,}(命中 {hit[0]:,}) "
                          f"输出 {ct[0]:,}", flush=True)

        t0 = time.time()
        await asyncio.gather(*[one(i, p) for i, p in enumerate(batches)])
        await (cl.close() if a.provider == "ark" else cl.aclose())
        return metas, out, pt[0], ct[0], hit[0], time.time() - t0

    metas, res, pin, cout, chit, dt = asyncio.run(go())

    tal = Counter(); bybk = Counter(); recs = []
    for meta, r in zip(metas, res):
        r = r or {}
        for k, (rid, w, t, bk) in enumerate(meta, 1):
            v = r.get(str(k))
            act = (v.get("a") if isinstance(v, dict) else None) or "novote"
            if act not in ("keep", "fix", "skip"):
                act = "novote"
            new = (v.get("zh") or "").strip() if isinstance(v, dict) else ""
            tal[act] += 1; bybk[(bk, act)] += 1
            recs.append(dict(id=rid, w=w, bucket=bk, before=t, a=act, after=new,
                             anchored=bool(gl.get(w.lower()))))

    tag = time.strftime("%Y%m%d-%H%M")
    name = a.model if a.provider == "deepseek" else f"ark-{a.model}"
    outp = HERE / f"runs/low_{'skip2' if a.skip_from else 'pilot'}_{name}_{len(recs)}_{tag}.jsonl"
    with open(outp, "w", encoding="utf-8") as f:
        f.write(json.dumps(dict(_meta=True, model=a.model, n=len(recs), seed=a.seed,
                                prompt_tokens=pin, completion_tokens=cout, cache_hit=chit,
                                seconds=round(dt, 1)), ensure_ascii=False) + "\n")
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n = len(recs)
    print(f"\n===== {a.model}  {n} 条  {dt:.0f}s =====")
    for k in ("keep", "fix", "skip", "novote"):
        print(f"  {k:7} {tal[k]:>4} ({100*tal[k]/max(n,1):5.1f}%)")
    print(f"\n  —— 按桶 ——")
    print(f"    {'':4}{'keep':>7}{'fix':>7}{'skip':>7}")
    for bk in ("B1", "B2", "C3"):
        if sum(bybk[(bk, x)] for x in ("keep", "fix", "skip", "novote")):
            print(f"    {bk:4}" + "".join(f"{bybk[(bk,x)]:>7}" for x in ("keep", "fix", "skip")))
    print(f"\n  token 输入 {pin:,}(命中 {chit:,}) 输出 {cout:,}")
    if a.provider == "deepseek":     # v4-pro:命中 0.025 未命中 3 输出 6 元/M
        yuan = (chit * 0.025 + (pin - chit) * 3.0 + cout * 6.0) / 1e6
        print(f"  实付 ≈ {yuan:.4f} 元  → 折算 low 全量 406,104 条 ≈ {yuan/max(n,1)*406104:.0f} 元")
    else:                            # ⚠️ 豆包单价没在项目里记过,不瞎折算,只给 token
        print(f"  每条 输入 {pin/max(n,1):.1f} 输出 {cout/max(n,1):.1f} tok(豆包单价未记录,自行折算)")
    print(f"\n  ⚠️ skip 率是**安全指标**:过低说明它在编造。")
    print(f"  → {outp.name}")


if __name__ == "__main__":
    main()
