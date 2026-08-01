#!/usr/bin/env python3
"""拿**真实音标 + 当前展示层输出**送两家模型审。见对话 2026-07-30。

为什么不能只做抽象评审(上一轮 review_ipa_rules.py):模型只看代码不看数据时会**凭想象举例**
—— v4-pro 拿德语借词 Kuchen 论证 kç 规则,而库里根本没有这种词。
→ 喂真实样本,让它判"用户实际看到的这一条对不对",凭据才落地。

⭐ 分层抽样:不能纯随机。问题符号(ɾ/ʔ/ɐ)全库才几十上百条,纯随机 2000 条一条都抽不到,
   而它们恰恰是已知缺陷所在。分层保证每个可疑族都有足够样本量能算出比例。

⚠️ 两家独立判,不给对方答案。上一轮的教训:**标签收敛 ≠ 内容收敛**
   (两家都答"分英美处理",但英式做法一个是删、一个是留,完全相反)。

read-only。用法:
  python3 en/audit_ipa_sample.py --n 2000
  python3 en/audit_ipa_sample.py --n 200 --only ds    # 只跑一家,调 prompt 时用
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
import argparse, asyncio, json, random, sqlite3, time
from collections import Counter
from pathlib import Path

import acceptance_en as A
from ipa_normalize import normalize
from judge_sample import ds_call, ark_call

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
CHUNK = 25

SYS = """你是英语语音学 + 词典编纂双背景的专家。审核一个**中文用户划词弹窗**里实际显示的音标。

每条给你:
  w       单词
  uk/us   **用户当前看到的音标**(已经过展示层规则处理)
  uk0/us0 (若与处理后不同才给)处理前的 Wiktionary 严式原文

展示层规则的意图是「严式 → 教学式」:去变音符、连弧塞擦音归并、ɹ→r、ɾ→r、ɚ→ər、ɝ→ɜːr、
ʔ 删除、ɐ→ə、ɨ→ɪ、ɛ→e、ɫ→l、去音节点、**括号原样保留**。英式美式**共用同一套规则**。

只挑**有问题的**条目列出,每条给一个字母码 + 建议的正确形式:
  A 规则把对的改错了(音位级错误,如闪音/喉塞/元音音质被改坏)
  B 括号碍读(严式可选音括号透到了用户眼前)
  C 英美混淆(美式列里是英式音标,或英式里出现了不该有的 r)
  D 严式残留(去掉标记后反而读不出来,或残留怪符号)
  E 其他

⚠️ 以下**不要列出**:
- 音标正确、只是词生僻/专业;
- 风格差异(如美式用 ɛ 还是 e)本身不算错,除非它导致读错;
- 缺音标(空字符串)不归你判。

宁可漏报不要凑数。严格输出 JSON,只含有问题的条目,键与输入一致:
{"3":{"c":"A","uk":"建议的英式","us":"建议的美式","why":"12字以内"},"7":{"c":"B","us":"…","why":"…"}}
没问题的条目**不要出现在输出里**。全部没问题则输出 {}。"""

STRATA = [
    ("常用核心", "COALESCE(qual,'')='core'", 0.40),
    ("含括号", "(phonetic_uk LIKE '%(%' OR phonetic_us LIKE '%(%')", 0.20),
    ("含疑符ɾʔɐɨ", "(phonetic_uk GLOB '*[ɾʔɐɨ]*' OR phonetic_us GLOB '*[ɾʔɐɨ]*')", 0.15),
    ("英式带ɚɝ", "(phonetic_uk LIKE '%ɚ%' OR phonetic_uk LIKE '%ɝ%')", 0.10),
    ("其余随机", "1=1", 0.15),
]


def sample(n, seed):
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    base = "COALESCE(phonetic_uk,'')<>'' OR COALESCE(phonetic_us,'')<>''"
    picked, seen = [], set()
    for name, cond, frac in STRATA:
        rows = conn.execute(
            f"SELECT id,word,COALESCE(phonetic_uk,''),COALESCE(phonetic_us,''),COALESCE(qual,'') "
            f"FROM stardict WHERE ({base}) AND {cond}").fetchall()
        rows = [r for r in rows if r[0] not in seen]
        random.seed(seed + len(name))
        take = random.sample(rows, min(int(n * frac), len(rows)))
        for r in take:
            seen.add(r[0])
        picked += [(*r, name) for r in take]
        print(f"  {name:12} 池 {len(rows):>7,} → 抽 {len(take):>4}", flush=True)
    conn.close()
    random.shuffle(picked)
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20260730)
    ap.add_argument("--conc", type=int, default=24)
    ap.add_argument("--only", choices=["ds", "ark"])
    a = ap.parse_args()

    rows = sample(a.n, a.seed)
    print(f"共 {len(rows)} 条", flush=True)

    metas, batches = [], []
    for j in range(0, len(rows), CHUNK):
        sub = rows[j:j + CHUNK]
        b = {}
        for k, (rid, w, uk, us, q, strat) in enumerate(sub, 1):
            nuk, nus = normalize(uk), normalize(us)
            d = {"w": w}
            if nuk:
                d["uk"] = nuk
                if uk != nuk:
                    d["uk0"] = uk
            if nus:
                d["us"] = nus
                if us != nus:
                    d["us0"] = us
            b[str(k)] = d
        metas.append(sub); batches.append(b)
    print(f"  → {len(batches)} 批 × {CHUNK}", flush=True)

    env = A.load_env()

    async def run(tag):
        if tag == "ark":
            from volcenginesdkarkruntime import AsyncArk
            cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
            mdl = env["DOUBAO_SEED_2_1_PRO"]
            call = lambda p: ark_call(cl, mdl, SYS, p)
        else:
            import httpx
            cl = httpx.AsyncClient(timeout=httpx.Timeout(900.0))
            call = lambda p: ds_call(cl, env["DEEPSEEK_API_KEY"], "deepseek-v4-pro", SYS, p)
        sem = asyncio.Semaphore(a.conc)
        out = [None] * len(batches); done = [0]; tk = [0, 0]
        try:
            await call(batches[0])
        except Exception:
            pass

        async def one(i, p):
            async with sem:
                d = 3
                for att in range(4):
                    try:
                        txt, (pi, co, _) = await call(p)
                        tk[0] += pi; tk[1] += co
                        out[i] = A.loads_lenient(
                            txt.strip().strip("`").replace("json\n", "", 1)
                            if txt.strip().startswith("`") else txt.strip())
                        break
                    except Exception:
                        if att == 3:
                            print(f"    ✗ [{tag}] 批{i}", flush=True)
                        else:
                            await asyncio.sleep(d); d = min(d * 2, 30)
                done[0] += 1
                if done[0] % 20 == 0 or done[0] == len(batches):
                    print(f"    [{tag}] {done[0]}/{len(batches)}", flush=True)

        t0 = time.time()
        await asyncio.gather(*[one(i, p) for i, p in enumerate(batches)])
        await (cl.close() if tag == "ark" else cl.aclose())
        print(f"  [{tag}] 完成 {time.time()-t0:.0f}s  输入 {tk[0]:,} 输出 {tk[1]:,}", flush=True)
        return out

    tags = [a.only] if a.only else ["ds", "ark"]
    res = asyncio.run(_all(run, tags))

    recs = {}
    for tag, out in zip(tags, res):
        for meta, r in zip(metas, out or []):
            r = r or {}
            for k, (rid, w, uk, us, q, strat) in enumerate(meta, 1):
                v = r.get(str(k))
                if isinstance(v, dict):
                    code = str(v.get("c", "E"))[:1].upper()
                    recs.setdefault(rid, dict(w=w, uk=normalize(uk), us=normalize(us),
                                              uk0=uk, us0=us, qual=q, strat=strat, votes={}))
                    recs[rid]["votes"][tag] = dict(c=code, uk=v.get("uk", ""),
                                                   us=v.get("us", ""), why=v.get("why", ""))
    outp = HERE / f"runs/ipa_audit_{len(rows)}_{time.strftime('%Y%m%d-%H%M')}.jsonl"
    with open(outp, "w", encoding="utf-8") as f:
        f.write(json.dumps(dict(_meta=True, n=len(rows), seed=a.seed,
                                models=tags), ensure_ascii=False) + "\n")
        for rid, v in recs.items():
            f.write(json.dumps(dict(id=rid, **v), ensure_ascii=False) + "\n")

    LAB = {"A": "规则改错了", "B": "括号碍读", "C": "英美混淆", "D": "严式残留", "E": "其他"}
    print(f"\n===== {len(rows)} 条,被标出 {len(recs)} 条 =====")
    for tag in tags:
        c = Counter(v["votes"][tag]["c"] for v in recs.values() if tag in v["votes"])
        n = sum(c.values())
        print(f"\n  [{tag}] 标出 {n} 条 ({100*n/len(rows):.1f}%)")
        for code, cnt in c.most_common():
            print(f"      {code} {LAB.get(code,code):<8} {cnt:>4}")
    if len(tags) == 2:
        both = [v for v in recs.values() if len(v["votes"]) == 2]
        agree = [v for v in both if v["votes"]["ds"]["c"] == v["votes"]["ark"]["c"]]
        print(f"\n  两家都标出 {len(both)} 条,其中同码 {len(agree)} 条"
              f" (占并集 {100*len(both)/max(len(recs),1):.0f}%)")
    print(f"\n  → {outp.name}")


async def _all(run, tags):
    return await asyncio.gather(*[run(t) for t in tags])


if __name__ == "__main__":
    main()
