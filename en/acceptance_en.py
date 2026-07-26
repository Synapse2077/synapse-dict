#!/usr/bin/env python3
"""英语词典验收抽样(read-only,不改库)。见对话 2026-07-26。
英语=ECDICT 基座、stardict 表、译文是中文(带 na./vt. 前缀),与五门(kaikki+豆包)结构不同,判法也不同:
  Part A 结构扫(常用核心,确定性免费):核心规模 / 缺音标 / [网络]垃圾 / 空译文。
  Part B 译文抽样(pro online):在**常用核心**(frq/bnc/collins/tag 任一)按均匀抽 N 条,pro 判
    "中文译文对该英语词是否准确/完整/自然"(pro 懂英语,拿自身知识核对,不依赖英文 gloss)。
只测常用核心——70万[网络]垃圾全在无词频信号的生僻尾巴、几乎不被划词命中,不是产品面向用户的质量。
用法(仓库根或 en/):
  python3 en/acceptance_en.py --struct
  python3 en/acceptance_en.py --run --n 1500
"""
import argparse, asyncio, json, re, sqlite3, random, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DB = str(HERE / "synapse-dict-en.sqlite")
ENV = ROOT / ".env"
CHUNK, CONC, TIMEOUT = 20, 80, 600

# 常用核心:有任一难度/词频信号(=真正会被查的词);排除纯生僻长尾
CORE = "(collins>0 OR oxford>0 OR frq>0 OR bnc>0 OR (tag IS NOT NULL AND TRIM(tag)<>''))"
NOPH = "(COALESCE(TRIM(phonetic),'')='' AND COALESCE(TRIM(phonetic_uk),'')='' AND COALESCE(TRIM(phonetic_us),'')='')"

JUDGE_SYS = """你是英汉词典质检专家。给你一批英语词条,每条含 word(英语词)、pos(词性,可能空)、def(英文释义,可能空)、zh(中文译文,可能带 na./n./vt. 等词性前缀)。
凭你自身的英语知识,判断**中文译文对该英语词的意思是否准确、完整、自然**:
- 是否**错译**(中文与该词实际意思不符);
- 是否**漏掉主要义项**(只给了次要/生僻义,漏了最常用义);
- 中文是否**通顺、像人话**(垃圾如"[网络] 游戏；一个游戏"、机翻腔算 bad);
- 词性前缀(n./vt.)与实际是否大体相符。
每条返回 {"v":"ok|warn|bad","note":"简短问题(warn/bad时)"}。
ok=准确且主要义完整、可直接上线;warn=可用但有小瑕疵(漏次要义/略生硬/多余术语标记);bad=真错(错译/漏主要义/译文是垃圾或残缺)。
严格输出 JSON {"1":{"v":"ok"},"2":{"v":"bad","note":"..."},...},键与输入一致,无多余文字。"""


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


def struct_audit():
    c = sqlite3.connect(DB)
    def q(s, p=()): return c.execute(s, p).fetchone()[0]
    W = "WHERE " + CORE
    total = q("SELECT COUNT(*) FROM stardict")
    core = q("SELECT COUNT(*) FROM stardict " + W)
    noph = q("SELECT COUNT(*) FROM stardict " + W + " AND " + NOPH)
    net = q("SELECT COUNT(*) FROM stardict " + W + " AND translation LIKE ?", ("%[网络]%",))
    empty = q("SELECT COUNT(*) FROM stardict " + W + " AND COALESCE(TRIM(translation),'')=''")
    c.close()
    print(f"全库 {total} | 常用核心(有词频/星级/考纲信号) {core}")
    print(f"  核心缺音标(三列全空): {noph} ({100*noph/core:.1f}%)")
    print(f"  核心含[网络]: {net} ({100*net/core:.2f}%)")
    print(f"  核心空译文: {empty}")


def sample_core(n, seed=20260726):
    c = sqlite3.connect(DB)
    rows = c.execute(f"SELECT id, word, pos, definition, translation FROM stardict WHERE {CORE} "
                     "AND COALESCE(TRIM(translation),'')<>''").fetchall()
    c.close()
    random.seed(seed)
    return random.sample(rows, min(n, len(rows)))


async def acall(comps, model, sysp, payload):
    delay = 1
    for att in range(3):
        try:
            r = await comps.create(model=model, temperature=0.2, reasoning_effort="minimal",
                messages=[{"role": "system", "content": sysp},
                          {"role": "user", "content": "输入:\n" + json.dumps(payload, ensure_ascii=False)}])
            out = r.choices[0].message.content.strip()
            out = re.sub(r"^```(json)?|```$", "", out, flags=re.M).strip()
            out = out[out.find("{"):out.rfind("}") + 1]
            return loads_lenient(out), getattr(getattr(r, "usage", None), "total_tokens", 0)
        except Exception:
            if att == 2:
                raise
            await asyncio.sleep(delay); delay *= 2


async def run_batches(sysp, batches, model, comps):
    results = [{} for _ in batches]
    q = asyncio.Queue()
    for i, b in enumerate(batches):
        q.put_nowait((i, b))
    tok = [0]; done = [0]

    async def worker():
        while True:
            try:
                i, p = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                res, t = await acall(comps, model, sysp, p); results[i] = res; tok[0] += t
            except Exception as e:
                print(f"  ✗ {e}")
            done[0] += 1
            if done[0] % 20 == 0 or done[0] == len(batches):
                print(f"  [{done[0]}/{len(batches)}] token {tok[0]}", flush=True)
            q.task_done()

    await asyncio.gather(*[asyncio.create_task(worker()) for _ in range(min(CONC, len(batches)))])
    return results, tok[0]


def do_run(n):
    rows = sample_core(n)
    print(f"[en] 常用核心抽样 {len(rows)} 条")
    env = load_env()
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=TIMEOUT)
        model = env["DOUBAO_SEED_2_1_PRO"]
        batches, metas = [], []
        for j in range(0, len(rows), CHUNK):
            sub = rows[j:j + CHUNK]
            p = {str(k): {"word": r[1], "pos": r[2] or "", "def": (r[3] or "")[:120], "zh": r[4]}
                 for k, r in enumerate(sub, 1)}
            batches.append(p); metas.append(sub)
        res, tok = await run_batches(JUDGE_SYS, batches, model, cl.chat.completions)
        await cl.close(); return metas, res, tok

    metas, results, tok = asyncio.run(go())
    from collections import Counter
    tally = Counter(); bad = []
    outp = HERE / "acceptance_en.jsonl"
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
                if verdict == "bad":
                    bad.append((w, (zh or "")[:40].replace("\n", " "), note))
                f.write(json.dumps(dict(w=w, v=verdict, note=note, zh=zh), ensure_ascii=False) + "\n")
    tot = sum(tally.values()); scored = tot - tally["novote"]
    print(f"\n===== [en] 常用核心译文验收 {tot} 条(有效 {scored}) token {tok} =====")
    for lab in ("ok", "warn", "bad"):
        print(f"  {lab}  {tally[lab]} ({100*tally[lab]/max(scored,1):.1f}%)")
    print(f"  novote {tally['novote']}")
    print(f"  可用率(ok+warn): {100*(tally['ok']+tally['warn'])/max(scored,1):.1f}%")
    print("  bad 样本:")
    for w, z, note in bad[:15]:
        print(f"    {w}: zh={z} || {note[:44]}")
    print(f"  明细 → {outp.name}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--struct", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--n", type=int, default=1500)
    a = ap.parse_args()
    if a.struct or not a.run:
        struct_audit()
        if not a.run:
            sys.exit()
    if a.run:
        do_run(a.n)
