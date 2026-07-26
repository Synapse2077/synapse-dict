#!/usr/bin/env python3
"""英语常用核心译文 LLM 增补(enrich 不重写,见对话 2026-07-26)。
ECDICT 译文准确但偏老偏简:常缺现代常用义、偶有错译、个别"既是变形又是独立词"的词只当变形丢了义。
本脚本对常用核心(有词频/星级/考纲信号)turbo batch 增补:保留正确义 + 补漏常用义 + 纠明显错 + 保持 ECDICT 风格;
已准确完整就原样返回。只在"新≠旧 + 非空含中文 + 未删义项"时写库,写 overrides,先备份。
用法(仓库根):
  python3 en/enrich_core.py --pilot 300     # 过采样已判 bad/warn,增补后 pro 复判,看 migration,不写库
  python3 en/enrich_core.py --run           # 全量核心
"""
import argparse, asyncio, json, re, shutil, sqlite3, random, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DB = str(HERE / "synapse-dict-en.sqlite")
ENV = ROOT / ".env"
CHUNK, CONC, TIMEOUT = 20, 100, 1800
CORE = "(collins>0 OR oxford>0 OR frq>0 OR bnc>0 OR (tag IS NOT NULL AND TRIM(tag)<>''))"
CJK = re.compile(r'[一-鿿]')

SYS = """你是英汉词典编辑,负责给一部基于 ECDICT 的英汉词典**增补提质**(不是推倒重写)。给你一批英语词条,每条含 word、pos(词性)、def(英文释义,可能空)、zh(现有中文译文,常带 n./vt./a. 词性前缀,可能多行)。
现有译文来自 ECDICT——准确但**偏老偏简**:常缺现代/常用义、偶有错译、个别把"既是变形又是独立词"的词只当变形处理丢了词义。请输出**改进后的中文译文**:
- **保留**现有译文里正确的义项,不要删;
- **补上**该词缺失的**常用/现代**义项(concussion 要有"脑震荡";complimentary 要有"免费赠送的");
- **纠正**明显错译(Baal 不是"太阳神"是"巴力神");
- 若该词**既是某词变形、又有独立词义**,务必给出**独立词义**(可保留"(X的过去式)"这类简短形态说明);
- **保持 ECDICT 风格**:词性前缀(n./v./a./ad./vt./vi.)、多义用换行或逗号分隔、**简洁**;不要加例句、不要堆砌生僻义、不要改成大段解释。
- **若现有译文已经准确且常用义完整,原样把 zh 返回、不改。**
返回 JSON {"1":{"zh":"改进后的完整中文译文"},...},键与输入一致,无多余文字。

示例(输入词/现有zh → 期望 zh):
concussion / "n. 剧烈摇动, 震荡" → "n. 脑震荡；剧烈摇动，震荡"
complimentary / "a. 问候的, 称赞的" → "a. 赞美的，恭维的；免费赠送的，免费的"
Peking / "peke的现在分词 n. 北京" → "n. 北京（旧译名）"
settle / "vt. 安置, 使定居, 解决 vi. 定居, 沉淀" → "vt. 安置, 使定居, 解决 vi. 定居, 沉淀"  ← 已完整,原样返回"""


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
            r = await comps.create(model=model, temperature=0.3, **kw,
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


def core_rows():
    c = sqlite3.connect(DB)
    rows = c.execute(f"SELECT id, word, pos, definition, translation FROM stardict WHERE {CORE} "
                     "AND COALESCE(TRIM(translation),'')<>''").fetchall()
    c.close()
    return rows


def enrich(rows, env, batch=True):
    from volcenginesdkarkruntime import AsyncArk

    async def go():
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=TIMEOUT)
        model = env["DOUBAO_SEED_2_1_TURBO_BATCH"] if batch else env["DOUBAO_SEED_2_1_PRO"]
        comps = cl.batch.chat.completions if batch else cl.chat.completions
        hedge = (env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions, 180) if batch else None
        batches, metas = [], []
        for j in range(0, len(rows), CHUNK):
            sub = rows[j:j + CHUNK]
            p = {str(k): {"word": r[1], "pos": r[2] or "", "def": (r[3] or "")[:120], "zh": r[4]}
                 for k, r in enumerate(sub, 1)}
            batches.append(p); metas.append(sub)
        res, tok = await run_batches(SYS, batches, model, comps, hedge)
        await cl.close(); return metas, res, tok

    return asyncio.run(go())


def do_pilot(n):
    # 过采样:优先取 acceptance 判过 bad/warn 的词,掺入 ok 的,看能否修好且不改坏
    verdict = {}
    jp = HERE / "acceptance_en.jsonl"
    if jp.exists():
        for l in open(jp):
            o = json.loads(l); verdict[o["w"].lower()] = o["v"]
    rows = core_rows()
    bw = [r for r in rows if verdict.get(r[1].lower()) in ("bad", "warn")]
    okk = [r for r in rows if verdict.get(r[1].lower()) == "ok"]
    random.seed(7)
    sample = random.sample(bw, min(int(n * 0.7), len(bw))) + random.sample(okk, min(int(n * 0.3), len(okk)))
    print(f"[en] pilot 增补 {len(sample)} 条(bad/warn {min(int(n*0.7),len(bw))} + ok {min(int(n*0.3),len(okk))}),不写库")
    env = load_env()
    metas, results, tok = enrich(sample, env, batch=True)
    # 收集 old/new 对,再用 acceptance 的 judge 复判 new
    pairs = []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, (rid, w, pos, dfn, old) in enumerate(meta, 1):
            v = res.get(str(k))
            new = v.get("zh") if isinstance(v, dict) else None
            pairs.append((w, pos, dfn, old, new, verdict.get(w.lower(), "?")))
    changed = [p for p in pairs if p[4] and p[4] != p[3]]
    print(f"增补 token {tok} | 有改动 {len(changed)}/{len(pairs)}")
    print("\n=== 抽看 old→new(前20改动) ===")
    for w, pos, dfn, old, new, ov in changed[:20]:
        print(f"  [{ov}] {w}:\n     旧 {old[:56].replace(chr(10),' / ')}\n     新 {new[:56].replace(chr(10),' / ')}")
    # 复判 new
    import importlib.util
    spec = importlib.util.spec_from_file_location("acc", HERE / "acceptance_en.py")
    acc = importlib.util.module_from_spec(spec); spec.loader.exec_module(acc)

    async def judge(items):
        from volcenginesdkarkruntime import AsyncArk
        cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=600)
        batches = []
        for j in range(0, len(items), 20):
            sub = items[j:j + 20]
            batches.append({str(k): {"word": w, "pos": pos, "def": (dfn or "")[:120], "zh": zh}
                            for k, (w, pos, dfn, zh) in enumerate(sub, 1)})
        res, _ = await run_batches(acc.JUDGE_SYS, batches, env["DOUBAO_SEED_2_1_PRO"], cl.chat.completions)
        await cl.close(); return res

    judge_items = [(w, pos, dfn, new) for w, pos, dfn, old, new, ov in changed if new]
    from collections import Counter
    jr = asyncio.run(judge(judge_items))
    newv = {}
    idx = 0
    for b in jr:
        b = b or {}
        for k in sorted(b, key=int):
            if idx < len(judge_items):
                newv[judge_items[idx][0]] = b[k].get("v") if isinstance(b[k], dict) else "novote"
                idx += 1
    mig = Counter()
    for w, pos, dfn, old, new, ov in changed:
        nv = newv.get(w, "novote")
        mig[f"{ov}→{nv}"] += 1
    print("\n=== migration(改动条目的 旧判→新判) ===")
    for k, v in sorted(mig.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    improved = sum(v for kk, v in mig.items() if kk.split("→")[0] in ("bad", "warn") and kk.split("→")[1] == "ok")
    degraded = sum(v for kk, v in mig.items() if kk.split("→")[0] == "ok" and kk.split("→")[1] in ("bad",))
    print(f"\n改好(bad/warn→ok): {improved} | 改坏(ok→bad): {degraded}")


def do_run():
    rows = core_rows()
    print(f"[en] 常用核心增补: {len(rows)} 条")
    bak = Path(DB).with_suffix(f".pre-enrich-{time.strftime('%Y%m%d-%H%M')}.bak")
    shutil.copy(DB, bak); print(f"已备份 {bak.name}")
    env = load_env()
    metas, results, tok = enrich(rows, env, batch=True)
    conn = sqlite3.connect(DB)
    ov = HERE / "overrides.tsv"
    fixed = same = skip = 0
    ov_lines = []
    for meta, res in zip(metas, results):
        res = res or {}
        for k, (rid, w, pos, dfn, old) in enumerate(meta, 1):
            v = res.get(str(k))
            new = v.get("zh") if isinstance(v, dict) else None
            if not new or not isinstance(new, str) or not CJK.search(new):
                skip += 1; continue
            if new.strip() == old.strip():
                same += 1; continue
            # 安全:新译不应比旧译短太多(防丢义项)
            if len(new) < len(old) * 0.6:
                skip += 1; continue
            conn.execute("UPDATE stardict SET translation=? WHERE id=?", (new, rid))
            ov_lines.append(f"{w}\ttranslation\t{old.replace(chr(10),' / ')}\t{new.replace(chr(10),' / ')}")
            fixed += 1
    conn.commit(); conn.close()
    if ov_lines:
        with open(ov, "a", encoding="utf-8") as f:
            f.write("\n".join(ov_lines) + "\n")
    print(f"\n✅ [en] 写库 {fixed} | 未变(原样) {same} | 跳过(空/短/无中文) {skip} | token {tok}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", type=int, metavar="N")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.pilot:
        do_pilot(a.pilot)
    elif a.run:
        do_run()
    else:
        ap.print_help()
