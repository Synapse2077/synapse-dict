#!/usr/bin/env python3
"""全核心译文硬伤扫描(read-only,只产清单不写库)。见对话 2026-07-27。
在 acceptance 抽样(1500)之上,对全部常用核心做一遍 judge,产出"必须修"的硬伤清单。
判官口径按对话敲定**松绑**:学科标签/生僻旧义/缺词性前缀都不算 bad,只挑真错译/漏主要义/机翻残句/变形硬塞原形全义。
turbo batch 半价 + pro 超时兜底(同 enrich)。用法(仓库根):
  python3 en/sweep_core.py            # 全核心
  python3 en/sweep_core.py --limit 2000   # 先小跑测
"""
import argparse, asyncio, json, re, sqlite3, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DB = str(HERE / "synapse-dict-en.sqlite")
ENV = ROOT / ".env"
CHUNK, CONC = 20, 50   # ⚠️ CONC 曾用 100:大活儿(C6 4,854 批)一次性砸进 batch 队列会把它压堵,
                       #   前 100 个 worker 全部等满 hedge 后切 online pro(单价差一个量级),已止损重来。
                       #   降到 50;开大活儿前最好先探 20 批看队列通不通。
CORE = "(collins>0 OR oxford>0 OR frq>0 OR bnc>0 OR (tag IS NOT NULL AND TRIM(tag)<>''))"

# 松绑版判官:只挑硬伤,明确豁免标签/生僻义/格式
JUDGE_SYS = """你是英汉词典质检专家,负责从一部基于 ECDICT 的英汉词典里**挑出必须修的硬伤**。给你一批英语词条,每条含 word(英语词)、pos(词性,可能空)、def(英文释义,可能空)、zh(中文译文,可能带 n./vt. 等前缀或多行)。
凭你自身英语知识,判断 zh 对该英语词是否有**硬伤**。只把下列情况判 bad:
- **错译**:中文义与该词实际意思不符(taff 译成"肥胖的"、nervosa 译成"神经衰弱"、tonga 混入"雅司病");
- **漏掉最常用主要义**:只给了次要/生僻义,把最常用义漏了(checkmark 漏了"对勾");
- **机翻残句/垃圾**:中文读不通、是机翻残片或残缺(如"(时间)醒着换过的""[网络]游戏；一个游戏");
- **变形词严重跑偏**:一个变形词(现在分词/过去式/复数等)硬塞进原形的全部义项还混入(X)人名,严重偏离词条本身。

**以下一律不算问题,判 ok(务必从宽)**:
- 带学科标签 [医][机][计][化][法] 等——这是有用信息,**即使标签义与普通义重复也判 ok**,绝不因标签判 warn/bad;
- 保留了生僻义、古旧义、专业义,或义项列得较多——**只要没错就是 ok**,不因"义项多/有生僻义"判问题;
- 缺词性前缀、变形说明未加前缀、专名只给译名等**纯格式小瑕**——判 ok,不判 bad;
- 义项正确、只是文字略朴素——ok。

warn 只留给"义项对但明显漏了一个常用义/中文有小别扭"的中间地带,拿不准就判 ok。
目标是产出**干净的硬伤清单**,宁可放过也不要误伤正确词条。
严格输出 JSON {"1":{"v":"ok"},"2":{"v":"bad","note":"简短问题"},...},键与输入一致,无多余文字。"""


def load_env():
    e = {}
    for ln in open(ENV):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.strip().split("=", 1); e[k] = v
    return e


def loads_lenient(s):
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    out = {}
    for m in re.finditer(r'"(\d+)"\s*:\s*(?=\{)', s):
        key = m.group(1); i = m.end(); depth = 0
        for j in range(i, len(s)):
            if s[j] == '{':
                depth += 1
            elif s[j] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        out[key] = json.loads(s[i:j + 1])
                    except Exception:
                        pass
                    break
    if out:
        return out
    raise json.JSONDecodeError("lenient failed", s, 0)


async def acall(comps, model, sysp, payload, batch=True):
    kw = {"thinking": {"type": "disabled"}} if batch else {"reasoning_effort": "minimal"}
    delay = 3
    for att in range(5 if batch else 3):
        try:
            r = await comps.create(model=model, temperature=0.2, **kw,
                messages=[{"role": "system", "content": sysp},
                          {"role": "user", "content": "输入:\n" + json.dumps(payload, ensure_ascii=False)}])
            out = r.choices[0].message.content.strip()
            out = re.sub(r"^```(json)?|```$", "", out, flags=re.M).strip()
            out = out[out.find("{"):out.rfind("}") + 1]
            return loads_lenient(out), getattr(getattr(r, "usage", None), "total_tokens", 0)
        except Exception:
            if att == (4 if batch else 2):
                raise
            await asyncio.sleep(delay if batch else 1); delay = min(delay * 2, 30)


async def run_batches(sysp, batches, model, comps, hedge=None):
    results = [{} for _ in batches]
    q = asyncio.Queue()
    for i, b in enumerate(batches):
        q.put_nowait((i, b))
    tok = [0]; done = [0]; hedged = [0]

    async def one(p):
        if not hedge:
            return await acall(comps, model, sysp, p, False)
        om, oc, after = hedge
        try:
            return await asyncio.wait_for(acall(comps, model, sysp, p, True), after)
        except Exception:
            hedged[0] += 1
            return await acall(oc, om, sysp, p, False)

    async def worker():
        while True:
            try:
                i, p = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                res, t = await one(p); results[i] = res; tok[0] += t
            except Exception as e:
                print(f"  ✗ {e}")
            done[0] += 1
            if done[0] % 25 == 0 or done[0] == len(batches):
                print(f"  [{done[0]}/{len(batches)}] token {tok[0]} (切online {hedged[0]})", flush=True)
            q.task_done()

    await asyncio.gather(*[asyncio.create_task(worker()) for _ in range(min(CONC, len(batches)))])
    return results, tok[0]


def core_rows(limit=None):
    c = sqlite3.connect(DB)
    sql = (f"SELECT id, word, pos, definition, translation FROM stardict WHERE {CORE} "
           "AND COALESCE(TRIM(translation),'')<>''")
    if limit:
        sql += f" LIMIT {limit}"
    rows = c.execute(sql).fetchall()
    c.close()
    return rows


def main(limit):
    rows = core_rows(limit)
    print(f"[en] 全核心硬伤扫描: {len(rows)} 条", flush=True)
    env = load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
        model = env["DOUBAO_SEED_2_1_TURBO_BATCH"]
        hedge = (env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions, 180)
        batches, metas = [], []
        for j in range(0, len(rows), CHUNK):
            sub = rows[j:j + CHUNK]
            p = {str(k): {"word": r[1], "pos": r[2] or "", "def": (r[3] or "")[:120], "zh": r[4]}
                 for k, r in enumerate(sub, 1)}
            batches.append(p); metas.append(sub)
        res, tok = await run_batches(JUDGE_SYS, batches, model, cl.batch.chat.completions, hedge)
        await cl.close(); return metas, res, tok

    metas, results, tok = asyncio.run(go())
    from collections import Counter
    tally = Counter()
    outp = HERE / "runs/sweep_core.jsonl"
    with open(outp, "w", encoding="utf-8") as f:
        for meta, res in zip(metas, results):
            res = res or {}
            for k, (rid, w, pos, dfn, zh) in enumerate(meta, 1):
                v = res.get(str(k))
                verdict = v.get("v") if isinstance(v, dict) else None
                if verdict not in ("ok", "warn", "bad"):
                    verdict = "novote"
                tally[verdict] += 1
                note = v.get("note", "") if isinstance(v, dict) else ""
                f.write(json.dumps(dict(id=rid, w=w, v=verdict, note=note, zh=zh), ensure_ascii=False) + "\n")
    tot = sum(tally.values()); scored = tot - tally["novote"]
    print(f"\n===== [en] 全核心硬伤扫描 {tot} 条(有效 {scored}) token {tok} =====", flush=True)
    for lab in ("ok", "warn", "bad"):
        print(f"  {lab}  {tally[lab]} ({100*tally[lab]/max(scored,1):.2f}%)")
    print(f"  novote {tally['novote']}")
    print(f"  硬伤(bad)清单 → {outp.name}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    main(a.limit)
