#!/usr/bin/env python3
"""
西语豆包「顺带富化」pass —— 西语翻译早已 100% 完成，本轮碰每个 lemma 时：
  · 必补 CEFR level（全 10.5 万 lemma）
  · 按需顺带补 kaikki 留空的缺口：transitivity(动词)/gender(名词)/ipa(缺音标者)
  只填空、不覆盖 kaikki（一种数据一个权威）；且**只对缺该字段的词请求**该字段，省 token。

第一档富化（用户 2026-07-19 选定）：只补 CEFR + 及物性/性别/IPA，可靠且几乎免费。
搭配/例句/feminine 不在本轮（前者另开、后者豆包易幻觉）。

架构承 de/fr b_translate（chunk 落盘续跑、index-key 对齐、对半重试、merge 仲裁）。
IPA 存半岛音（含 θ）；拉美 seseo 音由 spanish.ts 的 seseoLatam() 显示层派生，不入库。

用法（在 es/ 目录）：
  python3 b_enrich.py --mode online --limit 40   # 小样验证（先跑这个）
  python3 b_enrich.py                            # 全量续跑，落 b_enrich_out/
  python3 b_enrich.py --merge                    # 写回 level + 缺口 gender/trans/ipa
  python3 b_enrich.py --stats
"""
import argparse
import asyncio
import json
import re
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "synapse-dict-es.sqlite"
OUT_FILE = HERE / "b_enrich_out.jsonl"   # 单文件续跑：每批一行 JSON，不再一 chunk 一文件
ENV_PATH = HERE.parent / ".env"
MODE = "batch"
CHUNK = 60
CONC = 50
TEMP = 0.2
MAX_RETRY = 2

SYS_PROMPT = """你是西班牙语教学与词典编纂专家。我给你一批西语词条，每条含词形、词性、中文释义（消歧用）和一个 ask 列表（指明本词需要你返回哪些字段）。只返回 ask 里列出的字段，不在 ask 里的一律不要返回。

字段规则：
- level：CEFR 难度 A1/A2/B1/B2/C1/C2 之一（A1 最基础、C2 最高阶），按该西语词实际频率与掌握难度判断。**ask 含 level 时必给**。
- trans：动词的及物性，t(及物)/i(不及物)/ti(兼)。有把握才给，没把握省略。
- gender：名词的语法性别，m(el)/f(la)/mf(共性)。有把握才给，没把握省略。
- ipa：该词**半岛标准音**（distinción，字母 c(e/i)、z 读 θ；音位式，两侧加斜杠），如 gracias→/ˈɡɾaθjas/、casa→/ˈkasa/、cielo→/ˈθjelo/。有把握才给。

严格输出 JSON，键与输入一致：{"1":{"level":"A2","trans":"t"},"2":{"level":"B1","gender":"m"},...}，只含 ask 要求且你有把握的字段，无多余文字。"""


def load_env():
    env = {}
    for ln in open(ENV_PATH):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.strip().split("=", 1)
            env[k] = v
    return env


def needs(pos, gender, transitivity, phonetic):
    """按缺口决定本词要向豆包请求哪些字段（level 恒有）。"""
    ask = ["level"]
    posset = set(pos.split("/")) if pos else set()
    if "v" in posset and not transitivity:
        ask.append("trans")
    if ({"n", "name"} & posset) and not gender:
        ask.append("gender")
    if not phonetic:
        ask.append("ipa")
    return ask


def pending(conn, limit=None):
    q = ("SELECT id, word, pos, translation, gender, transitivity, phonetic "
         "FROM dict WHERE is_lemma=1 AND level IS NULL ORDER BY id")
    if limit:
        q += f" LIMIT {int(limit)}"
    return conn.execute(q).fetchall()


async def acall(comps, model, subrows):
    payload = {}
    for rid, w, pos, tr, g, trans, ph in subrows:
        payload[str(rid)] = {"w": w, "pos": pos or "",
                             "zh": (tr or "").replace("\n", "；")[:50],
                             "ask": needs(pos, g, trans, ph)}
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
    for rid, w, pos, tr, g, trans, ph in chunk:
        o = res.get(str(rid), {}) if isinstance(res, dict) else {}
        o = o if isinstance(o, dict) else {}
        lvl = o.get("level")
        lvl = lvl.strip().upper() if isinstance(lvl, str) else None
        if lvl not in ("A1", "A2", "B1", "B2", "C1", "C2"):
            lvl = None
        out[str(rid)] = {"w": w, "level": lvl, "trans": o.get("trans"),
                         "gender": o.get("gender"), "ipa": o.get("ipa")}
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
    lock = asyncio.Lock()
    fout = open(OUT_FILE, "a", encoding="utf-8")   # 追加写单文件

    async def worker():
        while True:
            try:
                chunk = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            res, tok = await aresolve(comps, model, chunk)
            out = assemble_out(chunk, res)
            async with lock:                        # 串行化追加，一批一行，并发安全
                fout.write(json.dumps(out, ensure_ascii=False) + "\n")
                fout.flush()
            counters["done"] += 1
            counters["tok"] += tok
            if counters["done"] % 10 == 0 or counters["done"] == len(todo):
                print(f"  [{counters['done']}/{len(todo)}] 累计 token {counters['tok']}")
            q.task_done()

    await asyncio.gather(*[asyncio.create_task(worker())
                           for _ in range(min(CONC, len(todo)))])
    fout.close()
    await client.close()
    return counters["tok"]


def done_rids():
    s = set()
    if OUT_FILE.exists():
        for ln in open(OUT_FILE, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            try:                                    # 崩溃截断的末行会解析失败，跳过即可
                s.update(int(k) for k in json.loads(ln))
            except Exception:
                pass
    return s


def translate(limit=None):
    conn = sqlite3.connect(str(DB_PATH))
    rows = pending(conn, limit)
    conn.close()
    done = done_rids()
    rows = [r for r in rows if r[0] not in done]
    chunks = [rows[i:i + CHUNK] for i in range(0, len(rows), CHUNK)]
    print(f"待处理 {len(rows)} 词（已完成 {len(done)}）/ {len(chunks)} 批 MODE={MODE} CHUNK={CHUNK}")
    if not chunks:
        print("全部已完成，直接 --merge")
        return
    tok = asyncio.run(arun(chunks))
    print(f"完成本轮。累计 token {tok}。下一步：python3 b_enrich.py --merge")


VALIDIPA = re.compile(r"^/[^/]+/$")


def _iter_out():
    """逐行读单文件 JSONL，产出 (rid, o)；同一 rid 多次出现时后写覆盖前写。"""
    if not OUT_FILE.exists():
        return
    for ln in open(OUT_FILE, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            data = json.loads(ln)
        except Exception:
            continue
        for rid, o in data.items():
            yield rid, o


def merge():
    conn = sqlite3.connect(str(DB_PATH))
    n_lvl = n_tr = n_g = n_ipa = 0
    seen = {}
    for rid, o in _iter_out():
        seen[rid] = o                       # 去重：同 rid 取最后一次
    for rid, o in seen.items():
        rid = int(rid)
        row = conn.execute(
            "SELECT pos, gender, transitivity, phonetic, level "
            "FROM dict WHERE id=?", (rid,)).fetchone()
        if not row:
            continue
        pos, c_g, c_tr, c_ph, c_lvl = row
        posset = set(pos.split("/")) if pos else set()
        sets, vals = [], []
        lvl = o.get("level")
        if isinstance(lvl, str) and lvl.strip().upper() in ("A1", "A2", "B1", "B2", "C1", "C2"):
            if c_lvl is None:
                sets.append("level=?"); vals.append(lvl.strip().upper()); n_lvl += 1
        # 仲裁：只填 kaikki 留空的缺口
        tr = o.get("trans")
        if not c_tr and tr in ("t", "i", "ti") and "v" in posset:
            sets.append("transitivity=?"); vals.append(tr); n_tr += 1
        g = o.get("gender")
        if not c_g and isinstance(g, str) and g.strip() in ("m", "f", "mf") and ({"n", "name"} & posset):
            sets.append("gender=?"); vals.append(g.strip()); n_g += 1
        ipa = o.get("ipa")
        if not c_ph and isinstance(ipa, str) and VALIDIPA.match(ipa.strip()):
            sets.append("phonetic=?"); vals.append(ipa.strip()); n_ipa += 1
        if sets:
            vals.append(rid)
            conn.execute(f"UPDATE dict SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    conn.close()
    print(f"写回：CEFR {n_lvl} | 及物性 {n_tr} | 性别 {n_g} | IPA {n_ipa}")


def stats():
    conn = sqlite3.connect(str(DB_PATH))
    lemma = conn.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1").fetchone()[0]
    done = conn.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1 AND level IS NOT NULL").fetchone()[0]
    conn.close()
    logged = len(done_rids())
    print(f"lemma {lemma} | 已判 CEFR {done} | 待处理 {lemma-done} | 已落盘(单文件) {logged} 词")


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
