#!/usr/bin/env python3
"""
西语 CEFR 难度专补（豆包）——西语翻译早已 100% 完成，本脚本只补 level 一列，最省钱。
对象 = synapse-dict-es.sqlite 里 is_lemma=1 且 level 为空的词。

只喂 词 + 已有中文释义（消歧），让豆包判 A1-C2；不重翻、不动其它字段。
承 de/fr b_translate 的成熟架构（chunk 落盘续跑、index-key 对齐、对半重试）。

用法（在 es/ 目录）：
  python3 b_cefr.py --mode online --limit 40   # 小样验证
  python3 b_cefr.py                            # 全量续跑，落 b_cefr_out/
  python3 b_cefr.py --merge                    # 写回 level
  python3 b_cefr.py --stats
"""
import argparse
import asyncio
import glob
import json
import re
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "synapse-dict-es.sqlite"
OUT_DIR = HERE / "b_cefr_out"
ENV_PATH = HERE.parent / ".env"
MODE = "batch"
CHUNK = 80
CONC = 50
TEMP = 0.2
MAX_RETRY = 2

SYS_PROMPT = """你是西班牙语教学与 CEFR 分级专家。我给你一批西语词条，每条含词形与中文释义（仅供消歧）。请为每个词判定它的 CEFR 难度等级。

规则：
1. 每个词返回 level，取值 A1/A2/B1/B2/C1/C2 之一（A1 最基础常用、C2 最生僻高阶），按该西语词的实际使用频率与掌握难度判断，务必每词都给。
2. 只判等级，不要翻译、不要解释。
3. 严格输出 JSON，键与输入一致：{"1":{"level":"A1"},"2":{"level":"B2"},...}，无多余文字。"""


def load_env():
    env = {}
    for ln in open(ENV_PATH):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.strip().split("=", 1)
            env[k] = v
    return env


def pending(conn, limit=None):
    q = ("SELECT id, word, translation FROM dict "
         "WHERE is_lemma=1 AND level IS NULL ORDER BY id")
    if limit:
        q += f" LIMIT {int(limit)}"
    return conn.execute(q).fetchall()


async def acall(comps, model, subrows):
    payload = {str(rid): {"w": w, "zh": (t or "").replace("\n", "；")[:60]}
               for rid, w, t in subrows}
    usr = "输入：\n" + json.dumps(payload, ensure_ascii=False)
    r = await comps.create(
        model=model, temperature=TEMP,
        messages=[{"role": "system", "content": SYS_PROMPT},
                  {"role": "user", "content": usr}])
    out = r.choices[0].message.content.strip()
    out = re.sub(r"^```(json)?|```$", "", out, flags=re.M).strip()
    res = json.loads(out)
    tok = getattr(getattr(r, "usage", None), "total_tokens", 0)
    return res, tok


async def aresolve(comps, model, subrows):
    last = None
    for attempt in range(MAX_RETRY + 1):
        try:
            return await acall(comps, model, subrows)
        except json.JSONDecodeError as e:
            last = e
            break
        except Exception as e:
            last = e
            await asyncio.sleep(1.5 * (attempt + 1))
    if len(subrows) > 1:
        mid = len(subrows) // 2
        r1, t1 = await aresolve(comps, model, subrows[:mid])
        r2, t2 = await aresolve(comps, model, subrows[mid:])
        r1.update(r2)
        return r1, t1 + t2
    print(f"  ✗ 单词失败 rid={subrows[0][0]} {subrows[0][1]}: {last}")
    return {}, 0


def assemble_out(chunk, res):
    out = {}
    for rid, w, t in chunk:
        o = res.get(str(rid), {}) if isinstance(res, dict) else {}
        o = o if isinstance(o, dict) else {}
        lvl = o.get("level")
        lvl = lvl.strip().upper() if isinstance(lvl, str) else None
        if lvl not in ("A1", "A2", "B1", "B2", "C1", "C2"):
            lvl = None
        out[str(rid)] = {"w": w, "level": lvl}
    return out


async def arun(todo):
    from volcenginesdkarkruntime import AsyncArk
    env = load_env()
    client = AsyncArk(api_key=env["ARK_API_KEY"], timeout=600)
    if MODE == "online":
        model, comps = env["DOUBAO_MODEL_ONLINE_LITE"], client.chat.completions
    else:
        model, comps = env["DOUBAO_MODEL_BATCH_LITE"], client.batch.chat.completions
    print(f"模型 {model}  并发 {CONC}")
    q = asyncio.Queue()
    for c in todo:
        q.put_nowait(c)
    counters = {"done": 0, "tok": 0}

    async def worker():
        while True:
            try:
                chunk = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            res, tok = await aresolve(comps, model, chunk)
            out = assemble_out(chunk, res)
            fp = OUT_DIR / f"chunk_{chunk[0][0]:07d}.json"
            json.dump(out, open(fp, "w"), ensure_ascii=False, indent=1)
            counters["done"] += 1
            counters["tok"] += tok
            if counters["done"] % 10 == 0 or counters["done"] == len(todo):
                print(f"  [{counters['done']}/{len(todo)}] 累计 token {counters['tok']}")
            q.task_done()

    await asyncio.gather(*[asyncio.create_task(worker())
                           for _ in range(min(CONC, len(todo)))])
    await client.close()
    return counters["tok"]


def done_rids():
    s = set()
    for fp in glob.glob(str(OUT_DIR / "chunk_*.json")):
        try:
            s.update(int(k) for k in json.load(open(fp)))
        except Exception:
            pass
    return s


def translate(limit=None):
    OUT_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    rows = pending(conn, limit)
    conn.close()
    done = done_rids()
    rows = [r for r in rows if r[0] not in done]
    chunks = [rows[i:i + CHUNK] for i in range(0, len(rows), CHUNK)]
    print(f"待判 {len(rows)} 词（已完成 {len(done)}）/ {len(chunks)} 批 MODE={MODE} CHUNK={CHUNK}")
    if not chunks:
        print("全部已完成，直接 --merge")
        return
    tok = asyncio.run(arun(chunks))
    print(f"完成本轮。累计 token {tok}。下一步：python3 b_cefr.py --merge")


def merge():
    conn = sqlite3.connect(str(DB_PATH))
    n = 0
    for fp in sorted(glob.glob(str(OUT_DIR / "chunk_*.json"))):
        for rid, o in json.load(open(fp)).items():
            lvl = o.get("level")
            if lvl in ("A1", "A2", "B1", "B2", "C1", "C2"):
                conn.execute("UPDATE dict SET level=? WHERE id=?", (lvl, int(rid)))
                n += 1
    conn.commit()
    conn.close()
    print(f"写回 CEFR {n} 词")


def stats():
    conn = sqlite3.connect(str(DB_PATH))
    lemma = conn.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1").fetchone()[0]
    done = conn.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1 AND level IS NOT NULL").fetchone()[0]
    conn.close()
    outn = len(glob.glob(str(OUT_DIR / "chunk_*.json")))
    print(f"lemma {lemma} | 已判 CEFR {done} | 待判 {lemma-done} | 已落盘 chunk {outn}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--mode", choices=["online", "batch"], default=None)
    ap.add_argument("--chunk", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=None)
    args = ap.parse_args()
    if args.mode:
        MODE = args.mode
    if args.chunk:
        CHUNK = args.chunk
    if args.concurrency:
        CONC = args.concurrency
    if args.merge:
        merge()
    elif args.stats:
        stats()
    else:
        translate(args.limit)
