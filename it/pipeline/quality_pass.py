#!/usr/bin/env python3
"""it 服务级质检 —— 全部走 2.1pro（量不大，不用 lite 路由）。

三个子命令：
  --fill-ipa    给 ipa 为空的 lemma（52 条）补维基式意语 IPA，直接写库。
  --qa N        随机抽 N 条已翻 lemma，让 2.1pro 逐义项核对中文译文对错，
                产 qa_report.tsv + 打印错误率（估"服务级达标没"）。不改库。
  --qa-apply    读 qa_report.tsv，把判错且给了修正的译文人工复核后可选应用（默认只列，不自动改）。

设计同 b_*.py：AsyncArk、index-key JSON、可续跑。QA 只读不写库。
用法（在 es/ 目录）：
  python3 quality_pass.py --fill-ipa
  python3 quality_pass.py --qa 500
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
import argparse
import asyncio
import json
import random
import re
import sqlite3
from collections import Counter
from pathlib import Path

import paths

HERE = Path(__file__).resolve().parent
DB_PATH = paths.DB
ENV_PATH = paths.ENV
QA_REPORT = paths.WORK / "qa_report.tsv"
CHUNK = 20
CONC = 20
TEMP = 0.1
MODE = "online"    # "online"(秒回,小活) 或 "batch"(便宜,高延迟,大活;靠高并发喂满批次窗口)

IPA_SYS = """你是意大利语语音专家。我给你一批词（可能含外来词、地名、缩写、古拼写等），逐个给维基词典式意大利语 IPA。
约定：主重音标 ˈ；区分开/闭元音 e/ɛ、o/ɔ；双辅音写双（gatto /ˈɡatto/）；c/ci→k/t͡ʃ、g/gi→ɡ/d͡ʒ、gl(i)→ʎ、gn→ɲ、sc(e/i)→ʃ、z→ts 或 dz、单 r→r；两侧加斜杠，例 /kaˈsetta/。
缩写、纯数字序号、无单词读音的 → 该项返回 null。
严格输出 JSON，键与输入序号一致：{"1":"/.../","2":null,...}，无多余文字。"""

QA_SYS = """你是资深意大利语→简体中文词典审校专家。我给你一批已翻词条，每条含：词形 w、词性 pos、英文 gloss（消歧参考，可能有误）、以及待审的中文译文数组 zh（每项对应一个义项）。
请**独立**用你的意语知识逐义项核对 zh 是否准确、地道、无错义/漏译/多译/词性错配。英文 gloss 只作参考，以意语实际含义为准。
对每个词返回：
  "v": "ok"（全部义项都合格）| "warn"（有不够精准/可优化但不算错）| "bad"（存在明确错译/错义）
  "fix": 仅当 v!="ok" 时给出你建议的整条修正中文数组（与原 zh 等长、逐项对应）；v="ok" 省略。
  "note": 一句话说明问题（v!="ok" 时给），否则省略。
严格输出 JSON，键与输入一致：{"1":{"v":"ok"},"2":{"v":"bad","fix":["..."],"note":"..."},...}，无多余文字。"""


def load_env():
    env = {}
    for ln in open(ENV_PATH):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.strip().split("=", 1)
            env[k] = v
    return env


def is_batch():
    return MODE.endswith("batch")


def model_comps(client):
    env = load_env()
    if MODE == "turbo-batch":   # turbo 半价、batch 隔夜（大批量）；走 client.batch.*
        return env["DOUBAO_SEED_2_1_TURBO_BATCH"], client.batch.chat.completions
    if MODE == "batch":         # pro batch（512次503、基本没用，留着对照）
        return env["DOUBAO_SEED_2_1_PRO_BATCH"], client.batch.chat.completions
    return env["DOUBAO_SEED_2_1_PRO"], client.chat.completions   # online pro（快、小批量）


def loads_lenient(s):
    """容错解析豆包坏 JSON。turbo 有时条目间换行不加逗号（报 Expecting ',' delimiter），
    或留尾逗号。先直解，失败则修复常见问题再解。"""
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        fixed = re.sub(r'}\s*\n\s*(")', r'},\n\1', s)   # 条目间缺逗号（换行分隔）
        fixed = re.sub(r'}\s+(")', r'}, \1', fixed)      # 条目间缺逗号（空格分隔）
        fixed = re.sub(r',\s*([}\]])', r'\1', fixed)     # 去尾逗号
        return json.loads(fixed)


async def acall(comps, model, sys, payload):
    # 关思考：online 用 reasoning_effort（batch 路径不认、会 TypeError）；batch 用 thinking
    kw = {"thinking": {"type": "disabled"}} if is_batch() else {"reasoning_effort": "minimal"}
    max_try = 5 if is_batch() else 3   # batch 延迟波动、online 偶发坏JSON，都重试（重发常自愈）
    delay = 3
    for attempt in range(max_try):
        try:
            r = await comps.create(
                model=model, temperature=TEMP, **kw,
                messages=[{"role": "system", "content": sys},
                          {"role": "user", "content": "输入：\n" + json.dumps(payload, ensure_ascii=False)}])
            out = r.choices[0].message.content.strip()
            out = re.sub(r"^```(json)?|```$", "", out, flags=re.M).strip()
            out = out[out.find("{"):out.rfind("}") + 1]
            tok = getattr(getattr(r, "usage", None), "total_tokens", 0)
            return loads_lenient(out), tok
        except Exception:
            if attempt == max_try - 1:
                raise
            await asyncio.sleep(delay if is_batch() else 1)
            delay = min(delay * 2, 30)


async def run_batches(sys, batches):
    """batches: list of payload dict（每批用本地键 '1'..'N'）。
    返回 (results, tok)：results 与 batches 等长，每项是该批解析出的 dict（失败为 {}）。
    ⚠️ 不能用全局唯一键 + merged——豆包(尤其turbo)会把 '20_1' 重编号成 '1'，全局键必错配。
    改为每批本地 '1'..'N'、按批回收，模型天然返回 1..N 稳定匹配。"""
    from volcenginesdkarkruntime import AsyncArk
    env = load_env()
    # batch 单请求延迟 2s~5min 大波动，timeout 给足别误杀；online 端点秒回，600s 够
    client = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800 if is_batch() else 600)
    model, comps = model_comps(client)
    print(f"裁判 {model}  模式 {MODE}  并发 {CONC}  批 {len(batches)}")
    results = [{} for _ in batches]
    q = asyncio.Queue()
    for idx, b in enumerate(batches):
        q.put_nowait((idx, b))
    ctr = {"done": 0, "tok": 0}
    lock = asyncio.Lock()

    async def worker():
        while True:
            try:
                idx, payload = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                res, tok = await acall(comps, model, sys, payload)
            except Exception as e:
                print(f"  ✗ 批失败 {e}")
                q.task_done(); continue
            async with lock:
                results[idx] = res
                ctr["done"] += 1; ctr["tok"] += tok
                if ctr["done"] % 5 == 0 or ctr["done"] == len(batches):
                    print(f"  [{ctr['done']}/{len(batches)}] token {ctr['tok']}")
            q.task_done()

    await asyncio.gather(*[asyncio.create_task(worker()) for _ in range(min(CONC, len(batches)))])
    await client.close()
    return results, ctr["tok"]


# ---------------- IPA 补空 ----------------
def fill_ipa():
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT id, word FROM dict WHERE is_lemma=1 AND (ipa IS NULL OR TRIM(ipa)='')"
    ).fetchall()
    print(f"待补 IPA: {len(rows)} 条")
    if not rows:
        conn.close(); return
    batches, metas = [], []
    for j in range(0, len(rows), CHUNK):
        sub = rows[j:j + CHUNK]
        payload, m = {}, []
        for k, (rid, w) in enumerate(sub, 1):
            payload[str(k)] = w
            m.append(rid)
        batches.append(payload); metas.append(m)
    results, tok = asyncio.run(run_batches(IPA_SYS, batches))
    n = 0
    for m, res in zip(metas, results):
        res = res or {}
        for k, rid in enumerate(m, 1):
            ipa = res.get(str(k))
            if isinstance(ipa, str) and ipa.startswith("/"):
                conn.execute("UPDATE dict SET ipa=? WHERE id=?", (ipa, rid))
                n += 1
    conn.commit(); conn.close()
    print(f"写库 {n} 条 IPA。token {tok}")


# ---------------- 译文抽检 ----------------
def sample_rows(n, seed=42):
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT id, word, pos, definition, translation, level FROM dict "
        "WHERE is_lemma=1 AND translation IS NOT NULL AND TRIM(translation)<>''"
    ).fetchall()
    conn.close()
    random.seed(seed)
    return random.sample(rows, min(n, len(rows)))


def qa(n):
    rows = sample_rows(n)
    print(f"抽样 {len(rows)} 条")
    batches, metas = [], []
    for j in range(0, len(rows), CHUNK):
        sub = rows[j:j + CHUNK]
        payload, m = {}, []
        for k, (rid, w, pos, en, zh, lvl) in enumerate(sub, 1):
            payload[str(k)] = {"w": w, "pos": pos or "",
                               "gloss": (en or "").split("\n"),
                               "zh": (zh or "").split("\n")}
            m.append((rid, w, pos, en, zh, lvl))
        batches.append(payload); metas.append(m)
    results, tok = asyncio.run(run_batches(QA_SYS, batches))
    tally = Counter()
    by_level = Counter()
    lines = []
    for m, res in zip(metas, results):
        res = res or {}
        for k, (rid, w, pos, en, zh, lvl) in enumerate(m, 1):
            v = res.get(str(k), {})
            verdict = v.get("v", "novote") if isinstance(v, dict) else "novote"
            tally[verdict] += 1
            if verdict in ("bad", "warn"):
                by_level[lvl or "?"] += 1
            fix = v.get("fix") if isinstance(v, dict) else None
            note = v.get("note", "") if isinstance(v, dict) else ""
            lines.append((w, pos or "", lvl or "", verdict,
                          (zh or "").replace("\n", " / "),
                          " / ".join(fix) if isinstance(fix, list) else "",
                          note))
    with open(QA_REPORT, "w", encoding="utf-8") as f:
        f.write("word\tpos\tlevel\tverdict\tzh_orig\tzh_fix\tnote\n")
        for r in sorted(lines, key=lambda x: {"bad": 0, "warn": 1, "ok": 2, "novote": 3}.get(x[3], 9)):
            f.write("\t".join(r) + "\n")
    total = sum(tally.values())
    ok = tally.get("ok", 0)
    bad = tally.get("bad", 0)
    warn = tally.get("warn", 0)
    print(f"\n=== 抽检结果（{total} 条）→ {QA_REPORT.name} ===")
    print(f"  ok   {ok:4d}  ({100*ok/max(total,1):.1f}%)")
    print(f"  warn {warn:4d}  ({100*warn/max(total,1):.1f}%)  不够精准/可优化")
    print(f"  bad  {bad:4d}  ({100*bad/max(total,1):.1f}%)  明确错译 ← 服务级关键指标")
    print(f"  novote {tally.get('novote',0)}")
    print(f"  按 CEFR 分布(warn+bad): {dict(by_level.most_common())}")
    print(f"  token {tok}")
    print(f"\n错译率 {100*bad/max(total,1):.2f}% —— <1% 可判服务级达标；偏高则按上表 CEFR 高错区定向重译。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fill-ipa", action="store_true")
    ap.add_argument("--qa", type=int, metavar="N")
    ap.add_argument("--chunk", type=int)
    ap.add_argument("--conc", type=int)
    ap.add_argument("--mode", choices=["online", "turbo-batch", "batch"],
                    help="online=pro秒回(小活); turbo-batch=turbo半价隔夜(大活); batch=pro批(废)")
    args = ap.parse_args()
    if args.chunk:
        CHUNK = args.chunk
    if args.conc:
        CONC = args.conc
    if args.mode:
        MODE = args.mode
    if args.fill_ipa:
        fill_ipa()
    elif args.qa:
        qa(args.qa)
    else:
        ap.print_help()
