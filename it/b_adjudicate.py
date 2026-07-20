#!/usr/bin/env python3
"""意语冲突裁决器 —— 对 conflict_review.tsv 里 gender/aux/plural 三类冲突，让豆包 online
「盲投」：只给词形+词义消歧，**不给 kaikki/上次豆包 的候选值**，让它独立单字段判断，避免复读原判。
再与 kaikki、上次豆包 三方比对：
  · 盲投 == kaikki          → keep_kaikki（当年全译时手滑，kaikki 本就对，保留不动）
  · 盲投 == 上次豆包(≠kaikki) → override_doubao（两个独立豆包信号 vs kaikki → kaikki 疑错，待覆盖）
  · 三方各不同               → three_way（真疑难，留人眼）
IPA 冲突不投（kaikki/豆包 两套转写约定，处处不同非错误）。零翻译重跑、不动中文。

用法（在 it/ 目录）：
  python3 b_adjudicate.py --limit 40   # 小样先验盲投质量
  python3 b_adjudicate.py              # 全量盲投 → adjudicate_out.jsonl（续跑安全）
  python3 b_adjudicate.py --decide     # 读盲投结果，三方比对 → decisions.tsv
"""
import argparse
import asyncio
import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "synapse-dict-it.sqlite"
CONFLICT_FILE = HERE / "conflict_review.tsv"
OUT_FILE = HERE / "adjudicate_out.jsonl"       # 每批一行 {field:{rid:vote}}，续跑
DECISIONS = HERE / "decisions.tsv"
ENV_PATH = HERE.parent / ".env"
FIELDS = ("gender", "aux", "plural")           # 只裁离散词法字段；ipa 不投
CHUNK = 50
CONC = 40
TEMP = 0.1

SYS = {
    "gender": """你是意大利语词典专家。我给你一批意语名词（含中文词义消歧）。判断每个词的语法性别，只回：
m（阳性 il/lo）、f（阴性 la）、mf（共性，同形兼阳阴，如职业名词 il/la presidente、il/la cantante）。
按你的意大利语知识独立判断，严格输出 JSON {"1":"m","2":"f",...}，键与输入一致，无多余文字。""",
    "aux": """你是意大利语词典专家。我给你一批意语动词（含中文词义消歧）。判断每个动词在复合时态
（passato prossimo）中用哪个助动词，只回：avere、essere、both（两可，如 correre/vivere）。
不及物的位置移动/状态变化类多用 essere，及物多用 avere。严格输出 JSON {"1":"avere",...}，无多余文字。""",
    "plural": """你是意大利语词典专家。我给你一批意语名词的单数形（含中文词义消歧）。给出其标准复数词形。
外来词/辅音结尾/重音结尾等不变词，复数回原词本身。只回复数词形本身。严格输出 JSON {"1":"复数形",...}，无多余文字。""",
}


def load_env():
    env = {}
    for ln in open(ENV_PATH):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.strip().split("=", 1)
            env[k] = v
    return env


def read_conflicts():
    """读 tsv，返回 {field: [(word, kaikki, doubao_orig), ...]}（去重同 word）。"""
    out = {f: [] for f in FIELDS}
    seen = {f: set() for f in FIELDS}
    if not CONFLICT_FILE.exists():
        raise SystemExit(f"缺 {CONFLICT_FILE.name}，先跑 b_translate.py --merge")
    for i, ln in enumerate(open(CONFLICT_FILE, encoding="utf-8")):
        if i == 0:
            continue
        p = ln.rstrip("\n").split("\t")
        if len(p) < 4:
            continue
        w, f, kv, dv = p
        if f in out and w not in seen[f]:
            seen[f].add(w)
            out[f].append((w, kv, dv))
    return out


def gloss_map(words):
    conn = sqlite3.connect(str(DB_PATH))
    m = {}
    for i in range(0, len(words), 400):
        batch = words[i:i + 400]
        ph = ",".join("?" * len(batch))
        for w, d in conn.execute(
                f"SELECT word, definition FROM dict WHERE word IN ({ph}) "
                f"COLLATE NOCASE AND is_lemma=1", batch).fetchall():
            if w not in m:
                m[w] = (d or "").split("\n")[0][:40]
    conn.close()
    return m


async def acall(comps, model, field, items):
    """items: [(idx, word, gloss)]；返回 {idx: vote}。"""
    payload = {str(i): {"w": w, "zh": g} for i, w, g in items}
    r = await comps.create(
        model=model, temperature=TEMP,
        messages=[{"role": "system", "content": SYS[field]},
                  {"role": "user", "content": "输入：\n" + json.dumps(payload, ensure_ascii=False)}])
    out = r.choices[0].message.content.strip()
    out = out[out.find("{"):out.rfind("}") + 1]
    res = json.loads(out)
    tok = getattr(getattr(r, "usage", None), "total_tokens", 0)
    return {field: {k: str(v).strip() for k, v in res.items()}}, tok, [i for i, _, _ in items]


async def arun(tasks):
    """tasks: [(field, [(idx,word,gloss)...]), ...]"""
    from volcenginesdkarkruntime import AsyncArk
    env = load_env()
    client = AsyncArk(api_key=env["ARK_API_KEY"], timeout=600)
    model, comps = env["DOUBAO_MODEL_ONLINE_LITE"], client.chat.completions
    print(f"模型 {model}  并发 {CONC}  批 {len(tasks)}")
    q = asyncio.Queue()
    for t in tasks:
        q.put_nowait(t)
    counters = {"done": 0, "tok": 0}
    lock = asyncio.Lock()
    fout = open(OUT_FILE, "a", encoding="utf-8")

    async def worker():
        while True:
            try:
                field, items = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                res, tok, _ = await acall(comps, model, field, items)
            except Exception as e:
                print(f"  ✗ {field} 批失败: {e}")
                q.task_done(); continue
            async with lock:
                fout.write(json.dumps(res, ensure_ascii=False) + "\n"); fout.flush()
            counters["done"] += 1; counters["tok"] += tok
            if counters["done"] % 10 == 0 or counters["done"] == len(tasks):
                print(f"  [{counters['done']}/{len(tasks)}] 累计 token {counters['tok']}")
            q.task_done()

    await asyncio.gather(*[asyncio.create_task(worker()) for _ in range(min(CONC, len(tasks)))])
    fout.close()
    await client.close()
    return counters["tok"]


def done_keys():
    """已盲投过的 (field, idx)，续跑跳过。"""
    s = set()
    if OUT_FILE.exists():
        for ln in open(OUT_FILE, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                for field, votes in json.loads(ln).items():
                    for k in votes:
                        s.add((field, k))
            except Exception:
                pass
    return s


def run(limit=None):
    conf = read_conflicts()
    allwords = sorted({w for f in FIELDS for w, _, _ in conf[f]})
    gl = gloss_map(allwords)
    # 全局唯一 idx：field 内按序号，落盘键 = f"{field}:{i}"，续跑对齐
    done = done_keys()
    tasks = []
    for field in FIELDS:
        rows = conf[field]
        if limit:
            rows = rows[:limit]
        items = [(i, w, gl.get(w, "")) for i, (w, kv, dv) in enumerate(rows)
                 if (field, str(i)) not in done]
        for j in range(0, len(items), CHUNK):
            tasks.append((field, items[j:j + CHUNK]))
    total = sum(len(conf[f][:limit] if limit else conf[f]) for f in FIELDS)
    pending = sum(len(it) for _, it in tasks)
    print(f"冲突 {total}（gender {len(conf['gender'])}/aux {len(conf['aux'])}/plural {len(conf['plural'])}）"
          f"，待盲投 {pending} / {len(tasks)} 批")
    if not tasks:
        print("全部已盲投，下一步：--decide")
        return
    tok = asyncio.run(arun(tasks))
    print(f"完成。token {tok}。下一步：python3 b_adjudicate.py --decide")


def _norm(field, v):
    v = (v or "").strip()
    return v.casefold() if field == "plural" else v


def decide():
    conf = read_conflicts()
    votes = {f: {} for f in FIELDS}       # field -> {idx(str): vote}
    for ln in open(OUT_FILE, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            for field, vs in json.loads(ln).items():
                votes.setdefault(field, {}).update(vs)
        except Exception:
            pass
    tally = {"keep_kaikki": 0, "override_doubao": 0, "three_way": 0, "no_vote": 0}
    rows_out = []
    for field in FIELDS:
        for i, (w, kv, dv) in enumerate(conf[field]):
            fresh = votes.get(field, {}).get(str(i))
            if not fresh:
                verdict = "no_vote"
            elif _norm(field, fresh) == _norm(field, kv):
                verdict = "keep_kaikki"
            elif _norm(field, fresh) == _norm(field, dv):
                verdict = "override_doubao"
            else:
                verdict = "three_way"
            tally[verdict] += 1
            rows_out.append((w, field, kv, dv, fresh or "", verdict))
    with open(DECISIONS, "w", encoding="utf-8") as f:
        f.write("word\tfield\tkaikki\tdoubao_orig\tdoubao_fresh\tverdict\n")
        for r in rows_out:
            f.write("\t".join(r) + "\n")
    print(f"三方比对 {sum(tally.values())} 条 → {DECISIONS.name}")
    print(f"  keep_kaikki {tally['keep_kaikki']}（kaikki 对，保留）")
    print(f"  override_doubao {tally['override_doubao']}（kaikki 疑错，待覆盖，需人眼抽验）")
    print(f"  three_way {tally['three_way']}（三方不同，留人眼）")
    print(f"  no_vote {tally['no_vote']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--decide", action="store_true")
    ap.add_argument("--chunk", type=int, default=None)
    args = ap.parse_args()
    if args.chunk:
        CHUNK = args.chunk
    if args.decide:
        decide()
    else:
        run(args.limit)
