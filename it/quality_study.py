#!/usr/bin/env python3
"""质量相关性研究（it）：豆包"存疑"是否预测错误？三组抽样对比（pro online 当裁判）。
  A 组 misalign（flag 含 __misalign__，结构错位）
  B 组 语义存疑（flag 非空且非 misalign）
  C 组 无 flag
每组量：① 译文错译率(bad/warn) ② 性别误标率(裁判独立判 g vs 库) ③ 结构错位率(确定性: zh义数≠gloss义数)

⚠️ it 特有：收尾已把 A/B 的 flag 全清、A/B 译文已修，故**不能从当前库取分组**（会是空 + 假象变好）。
改从 `b_out/chunk_*.json` 取**原始 flag + 原始译文**（收尾前状态），pos/gloss/gender 从库按 word join。
这才是 es 当年"修之前"的口径，忠实测 flag 的预测力。
用法：python3 quality_study.py [每组样本数(默认 A200 B200 C300)]
"""
import asyncio
import glob
import json
import random
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-it.sqlite"
BOUT = HERE / "b_out"
ENV = HERE.parent / ".env"
OUT = HERE / "quality_study.tsv"
CHUNK, CONC = 20, 20

SYS = """你是资深意大利语→简体中文词典审校专家。给你一批词条，每条含：词形 w、词性 pos、英文 gloss（消歧参考，可能有误）、中文译文数组 zh。
请**独立**用你的意语知识核对：
1. 逐义项判断 zh 是否准确地道无错义/漏译/多译，返回 "v": "ok"(全合格) | "warn"(不够精准可优化,非错) | "bad"(有明确错译)。v!="ok" 时 "fix" 给整条修正中文数组（与 zh 等长）。
2. 若该词是名词，返回 "g" = 你判断的正确语法性别 m/f/mf（独立判断，不受任何影响）；非名词或无法判断填 "na"。
3. "note": v!="ok" 时一句话说明。
严格输出 JSON，键与输入一致：{"1":{"v":"ok","g":"f"},"2":{"v":"bad","fix":["..."],"g":"na","note":"..."},...}，无多余文字。"""


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
        s = re.sub(r'}\s*\n\s*(")', r'},\n\1', s)
        s = re.sub(r'}\s+(")', r'}, \1', s)
        s = re.sub(r',\s*([}\]])', r'\1', s)
        return json.loads(s)


def load_bout():
    """word -> (orig_zh_str, orig_flag)。同词多次出现取首个（统计抽样足够）。"""
    m = {}
    for fn in glob.glob(str(BOUT / "chunk_*.json")):
        d = json.load(open(fn))
        for _, v in d.items():
            w = v.get("w")
            if not w or w in m:
                continue
            zh = v.get("zh")
            zh_str = "\n".join(str(x) for x in zh) if isinstance(zh, list) else (zh or "")
            m[w] = (zh_str, v.get("flag"))
    return m


def sample_groups(nA, nB, nC):
    bout = load_bout()
    c = sqlite3.connect(str(DB))
    dbmap = {}   # word -> (id, pos, definition, gender, level)，取首个 lemma 行
    for _id, w, pos, defn, g, lv in c.execute(
            "SELECT id, word, pos, definition, gender, level FROM dict WHERE is_lemma=1"):
        if w not in dbmap:
            dbmap[w] = (_id, pos, defn, g, lv)
    c.close()
    A, B, C = [], [], []
    for w, (zh, fl) in bout.items():
        if w not in dbmap or not zh.strip():
            continue
        _id, pos, defn, g, lv = dbmap[w]
        if not (defn and defn.strip()):
            continue
        rec = (_id, w, pos, defn, zh, g, lv, fl)   # 与 es 同形，zh 为原始译文
        if fl and "misalign" in str(fl):
            A.append(rec)
        elif fl:
            B.append(rec)
        else:
            C.append(rec)
    random.seed(42)
    return {"A_misalign": random.sample(A, min(nA, len(A))),
            "B_semflag": random.sample(B, min(nB, len(B))),
            "C_noflag":  random.sample(C, min(nC, len(C)))}


async def acall(comps, model, payload):
    for att in range(3):
        try:
            r = await comps.create(model=model, temperature=0.1, reasoning_effort="minimal",
                messages=[{"role": "system", "content": SYS},
                          {"role": "user", "content": "输入：\n" + json.dumps(payload, ensure_ascii=False)}])
            out = r.choices[0].message.content.strip()
            out = re.sub(r"^```(json)?|```$", "", out, flags=re.M).strip()
            out = out[out.find("{"):out.rfind("}") + 1]
            return loads_lenient(out), getattr(getattr(r, "usage", None), "total_tokens", 0)
        except Exception:
            if att == 2:
                raise
            await asyncio.sleep(1)


async def run(rows):
    from volcenginesdkarkruntime import AsyncArk
    env = load_env()
    client = AsyncArk(api_key=env["ARK_API_KEY"], timeout=600)
    model = env["DOUBAO_SEED_2_1_PRO"]
    batches, metas = [], []
    for j in range(0, len(rows), CHUNK):
        sub = rows[j:j + CHUNK]
        p = {}
        for k, r in enumerate(sub, 1):
            _, w, pos, en, zh, g, lv, fl = r
            p[str(k)] = {"w": w, "pos": pos or "", "gloss": (en or "").split("\n"),
                         "zh": (zh or "").split("\n")}
        batches.append(p); metas.append(sub)
    results = [{} for _ in batches]
    q = asyncio.Queue()
    for i, b in enumerate(batches):
        q.put_nowait((i, b))
    tok = [0]
    async def worker():
        while True:
            try:
                i, p = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                res, t = await acall(client.chat.completions, model, p)
                results[i] = res; tok[0] += t
            except Exception as e:
                print(f"  ✗ {e}")
            q.task_done()
    await asyncio.gather(*[asyncio.create_task(worker()) for _ in range(min(CONC, len(batches)))])
    await client.close()
    out = []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, r in enumerate(meta, 1):
            out.append((r, res.get(str(k), {})))
    print(f"  token {tok[0]}")
    return out


def analyze(name, judged):
    tv = Counter(); g_mismatch = 0; g_checked = 0; struct = 0; n = len(judged)
    rows = []
    for r, v in judged:
        _id, w, pos, en, zh, g_db, lv, fl = r
        verdict = v.get("v", "novote") if isinstance(v, dict) else "novote"
        tv[verdict] += 1
        if en and zh and len(zh.split("\n")) != len(en.split("\n")):
            struct += 1
        gj = v.get("g") if isinstance(v, dict) else None
        if gj in ("m", "f", "mf") and g_db in ("m", "f", "mf"):
            g_checked += 1
            if gj != g_db:
                g_mismatch += 1
        rows.append((name, w, lv or "", verdict, g_db or "", gj or "",
                     "struct" if (en and zh and len(zh.split("\n")) != len(en.split("\n"))) else ""))
    bad = tv.get("bad", 0); warn = tv.get("warn", 0); ok = tv.get("ok", 0)
    print(f"\n【{name}】样本 {n}")
    print(f"  译文: ok {100*ok/max(n,1):.1f}% | warn {100*warn/max(n,1):.1f}% | bad(明确错译) {100*bad/max(n,1):.1f}%  (novote {tv.get('novote',0)})")
    print(f"  性别误标: {g_mismatch}/{g_checked} = {100*g_mismatch/max(g_checked,1):.1f}%")
    print(f"  结构错位(确定性): {struct}/{n} = {100*struct/max(n,1):.1f}%")
    return rows, (n, bad, warn, g_mismatch, g_checked, struct)


def main():
    args = [int(a) for a in sys.argv[1:] if a.isdigit()]
    nA, nB, nC = (args + [200, 200, 300])[:3]
    groups = sample_groups(nA, nB, nC)
    all_rows = []
    print("=" * 55)
    for name, rows in groups.items():
        print(f"\n>>> 跑 {name} ({len(rows)} 词) ...")
        judged = asyncio.run(run(rows))
        r, _ = analyze(name, judged)
        all_rows += r
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("group\tword\tlevel\tverdict\tgender_db\tgender_judge\tstruct\n")
        for row in all_rows:
            f.write("\t".join(map(str, row)) + "\n")
    print(f"\n明细 → {OUT.name}")


if __name__ == "__main__":
    main()
