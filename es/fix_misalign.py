#!/usr/bin/env python3
"""修复结构错位（义项数不匹配）：zh 义项数 ≠ 英文 gloss 义项数的词，用 turbo batch 重译对齐。
只重译这类词（确定性筛出），要求新 zh 数组长度严格等于 gloss 数组，**只在对齐成功时才写库**。
对齐失败的留 flag，不覆盖旧值。翻译只走 turbo batch（便宜、量小～700词）。

用法（在 es/）：
  python3 fix_misalign.py --dry        # 只看有多少待修 + 样本，不调用
  python3 fix_misalign.py --run        # turbo batch 重译 → 写库（自动备份）
  python3 fix_misalign.py --check 60   # 重译后，pro 抽样验收 N 条对齐质量
"""
import argparse
import asyncio
import json
import random
import re
import sqlite3
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "synapse-dict-es.sqlite"
ENV = HERE.parent / ".env"
CHUNK, CONC = 15, 100      # batch 喜欢高并发；chunk 小些降截断风险
TIMEOUT = 1800

SYS = """你是西班牙语→简体中文词典翻译专家。给你一批西语词条，每条含词形 w、词性 pos、英文释义数组 gloss（每个元素是一个义项）。
逐义项翻译成地道简体中文，返回 "zh" 数组：
- **长度必须严格等于 gloss 数组长度，一一对应**，绝不合并、拆分、增删义项。
- 英文释义仅作参考，以西语实际含义为准（英文可能有误或过窄）。
- 一个义项内多个近义中文用"，"分隔；只给中文释义本身，不加词性/性别等标注。
严格输出 JSON，键与输入一致：{"1":{"zh":["义项1","义项2",...]},...}，无多余文字。"""

CHECK_SYS = """你是资深西班牙语→简体中文词典审校专家。给你一批词条，含词形 w、英文 gloss 数组、中文译文 zh 数组。
核对：① zh 与 gloss 是否义项数一致、逐项对应；② 译文是否准确。
返回每词 "v": "ok"(对齐且准确) | "warn"(小瑕疵) | "bad"(错译或错位)，v!=ok 时 "note" 简述。
严格输出 JSON {"1":{"v":"ok"},...}，无多余文字。"""


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
    # 修常见坏 JSON：条目/元素间缺逗号、尾逗号
    fixed = re.sub(r'}\s*\n\s*(")', r'},\n\1', s)
    fixed = re.sub(r'}\s+(")', r'}, \1', fixed)
    fixed = re.sub(r'\]\s*\n?\s*(")', r'],\1', fixed)
    fixed = re.sub(r'"\s*\n\s*(")', r'",\1', fixed)
    fixed = re.sub(r',\s*([}\]])', r'\1', fixed)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    # 终极兜底：按平衡括号逐条目提取 "N":{...}，容忍条目间任何脏东西
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


def find_misaligned():
    """返回 [(id, word, pos, gloss_list, old_zh_list), ...]：zh 义项数 ≠ gloss 义项数。"""
    c = sqlite3.connect(str(DB))
    out = []
    for _id, w, pos, en, zh in c.execute(
            "SELECT id, word, pos, definition, translation FROM dict "
            "WHERE is_lemma=1 AND translation IS NOT NULL AND TRIM(translation)<>'' "
            "AND definition IS NOT NULL AND TRIM(definition)<>''"):
        gl, zl = en.split("\n"), zh.split("\n")
        if len(gl) != len(zl):
            out.append((_id, w, pos, gl, zl))
    c.close()
    return out


async def acall(comps, model, sys, payload, batch=True):
    kw = {"thinking": {"type": "disabled"}} if batch else {"reasoning_effort": "minimal"}
    delay = 3
    for att in range(5 if batch else 3):
        try:
            r = await comps.create(model=model, temperature=0.2, **kw,
                messages=[{"role": "system", "content": sys},
                          {"role": "user", "content": "输入：\n" + json.dumps(payload, ensure_ascii=False)}])
            out = r.choices[0].message.content.strip()
            out = re.sub(r"^```(json)?|```$", "", out, flags=re.M).strip()
            out = out[out.find("{"):out.rfind("}") + 1]
            return loads_lenient(out), getattr(getattr(r, "usage", None), "total_tokens", 0)
        except Exception:
            if att == (4 if batch else 2):
                raise
            await asyncio.sleep(delay if batch else 1); delay = min(delay * 2, 30)


async def run_batches(sys, batches, model, comps, batch=True, hedge=None):
    """hedge=(online_model, online_comps, after_sec)：尾延迟对冲——batch 某批超过 after_sec
    还没回，就把这批切到 pro online 秒回兜底。主体享 batch 半价、长尾享 online 快。"""
    results = [{} for _ in batches]
    q = asyncio.Queue()
    for i, b in enumerate(batches):
        q.put_nowait((i, b))
    tok = [0]; done = [0]; hedged = [0]

    async def one(p):
        if batch and hedge:
            om, oc, after = hedge
            try:
                return await asyncio.wait_for(acall(comps, model, sys, p, True), after)
            except Exception:
                hedged[0] += 1                       # 慢批/失败 → 切 online 兜底
                return await acall(oc, om, sys, p, False)
        return await acall(comps, model, sys, p, batch)

    async def worker():
        while True:
            try:
                i, p = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                res, t = await one(p)
                results[i] = res; tok[0] += t
            except Exception as e:
                print(f"  ✗ {e}")
            done[0] += 1
            if done[0] % 10 == 0 or done[0] == len(batches):
                tail = f" (切online {hedged[0]})" if hedge else ""
                print(f"  [{done[0]}/{len(batches)}] token {tok[0]}{tail}", flush=True)
            q.task_done()

    await asyncio.gather(*[asyncio.create_task(worker()) for _ in range(min(CONC, len(batches)))])
    return results, tok[0]


def do_run():
    rows = find_misaligned()
    print(f"待修结构错位: {len(rows)} 条")
    if not rows:
        return
    bak = DB.with_suffix(f".pre-misalign-{time.strftime('%Y%m%d-%H%M')}.bak")
    import shutil; shutil.copy(DB, bak)
    print(f"已备份 {bak.name}")
    env = load_env()
    from volcenginesdkarkruntime import AsyncArk
    async def go():
        client = AsyncArk(api_key=env["ARK_API_KEY"], timeout=TIMEOUT)
        model = env["DOUBAO_SEED_2_1_TURBO_BATCH"]
        batches, metas = [], []
        for j in range(0, len(rows), CHUNK):
            sub = rows[j:j + CHUNK]
            p = {str(k): {"w": r[1], "pos": r[2] or "", "gloss": r[3]} for k, r in enumerate(sub, 1)}
            batches.append(p); metas.append(sub)
        print(f"turbo batch 重译：{len(rows)} 词 / {len(batches)} 批 / 并发 {CONC}（尾延迟对冲: 慢批切pro online）")
        hedge = (env["DOUBAO_SEED_2_1_PRO"], client.chat.completions, 180)
        results, tok = await run_batches(SYS, batches, model, client.batch.chat.completions, True, hedge)
        await client.close()
        return metas, results, tok
    metas, results, tok = asyncio.run(go())
    # 写库：只在新 zh 数 == gloss 数 时更新
    conn = sqlite3.connect(str(DB))
    fixed = still_bad = novote = 0
    for meta, res in zip(metas, results):
        res = res or {}
        for k, (rid, w, pos, gl, old) in enumerate(meta, 1):
            v = res.get(str(k))
            if not isinstance(v, dict) or "zh" not in v:
                novote += 1; continue
            zh = v["zh"] if isinstance(v["zh"], list) else [str(v["zh"])]
            if len(zh) == len(gl):
                conn.execute("UPDATE dict SET translation=?, flag=NULL WHERE id=?",
                             ("\n".join(str(x) for x in zh), rid))
                fixed += 1
            else:
                still_bad += 1
    conn.commit(); conn.close()
    print(f"\n✅ 对齐成功写库 {fixed} 条 | 仍不对齐(未写) {still_bad} | 无返回 {novote} | token {tok}")
    print("下一步验收：python3 fix_misalign.py --check 60")


def do_check(n):
    """pro 抽样验收：从刚修过(flag已清、原属misalign集)的词里抽 N 条核对对齐+准确。
    简化：抽当前 zh数==gloss数 但曾在待修集里的——直接抽随机已翻词核对(重点看对齐)。"""
    c = sqlite3.connect(str(DB))
    rows = c.execute(
        "SELECT id, word, definition, translation FROM dict "
        "WHERE is_lemma=1 AND translation IS NOT NULL AND flag IS NULL "
        "AND definition IS NOT NULL AND TRIM(definition)<>''").fetchall()
    c.close()
    random.seed(1); samp = random.sample(rows, min(n, len(rows)))
    env = load_env()
    from volcenginesdkarkruntime import AsyncArk
    async def go():
        client = AsyncArk(api_key=env["ARK_API_KEY"], timeout=600)
        model = env["DOUBAO_SEED_2_1_PRO"]
        batches = []
        for j in range(0, len(samp), 20):
            sub = samp[j:j + 20]
            p = {str(k): {"w": r[1], "gloss": r[2].split("\n"), "zh": r[3].split("\n")}
                 for k, r in enumerate(sub, 1)}
            batches.append(p)
        res, tok = await run_batches(CHECK_SYS, batches, model, client.chat.completions, False)
        await client.close()
        return res, tok
    results, tok = asyncio.run(go())
    from collections import Counter
    t = Counter()
    for j, res in enumerate(results):
        for k in range(1, 21):
            v = (res or {}).get(str(k))
            if v: t[v.get("v", "novote") if isinstance(v, dict) else "novote"] += 1
    tot = sum(t.values())
    print(f"\npro 验收 {tot} 条: ok {t['ok']}({100*t['ok']/max(tot,1):.0f}%) / warn {t['warn']} / bad {t['bad']}  token {tok}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--check", type=int, metavar="N")
    a = ap.parse_args()
    if a.dry:
        rows = find_misaligned()
        print(f"待修结构错位: {len(rows)} 条\n样本:")
        for r in rows[:8]:
            print(f"  {r[1]}: gloss{len(r[3])}义 vs zh{len(r[4])}义  gloss={r[3][:2]}")
    elif a.run:
        do_run()
    elif a.check:
        do_check(a.check)
    else:
        ap.print_help()
