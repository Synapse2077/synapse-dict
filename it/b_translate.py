#!/usr/bin/env python3
"""
豆包翻译意大利语词典中文释义 + 补意语本质字段的缺口。
对象 = synapse-dict-it.sqlite 里 is_lemma=1 且 translation 为空的词（约 15 万）。
变位词不走这里（已由规则出 infl + G2P 出 IPA）。

一种数据一个权威：
  · kaikki 抽到的 aux/gender/plural/ipa 是权威，豆包只填 kaikki 留空的缺口（merge 仲裁）。
  · 中文释义、搭配、审计 flag = 豆包。

设计（承 es b_translate 的成熟架构）：
- 可中断续跑：按 chunk 落盘 b_out/，重跑跳过已完成 chunk。
- 对齐安全：index-key JSON（本地 rid↔dict.id），逐词校验 zh 长度=义项数，不符记 __misalign__。
- 只喂 词/词性/英文gloss（消歧用，不直译）；已有的 aux/gender 不喂（省 token）。

用法（在 it/ 目录）：
  python3 b_translate.py --limit 40     # 小样测试
  python3 b_translate.py                # 全量续跑，落 b_out/
  python3 b_translate.py --merge        # b_out/ 写回 sqlite（含本质字段仲裁）
  python3 b_translate.py --stats        # 进度
"""
import argparse
import asyncio
import glob
import json
import re
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "synapse-dict-it.sqlite"
OUT_DIR = HERE / "b_out"
ENV_PATH = HERE.parent / ".env"
MODE = "batch"          # batch(ep-bi 便宜) / online(ep-m 快，测试)
CHUNK = 50
CONC = 50
TEMP = 0.3
MAX_RETRY = 2

SYS_PROMPT = """你是意大利语→简体中文的词典编纂专家。我给你一批意语词条，每条含词形、词性、若干英文义项。英文释义仅作消歧参考——不要直译英文，请用你自己的意大利语知识判断该义项真正含义，再给出地道简体中文。

规则：
1. 逐义项翻译，与输入 senses 一一对应：顺序一致、数量完全相等。绝不自行增删义项。
2. 以意语实际含义为准。英文释义可能有误或过窄。
3. zh 里只给中文释义本身，不加词性/性别/搭配标注（另有数据）。一个义项内多个近义中文用"，"分隔。
4. senses 为空的词，凭你的意语知识给最常用释义，并在该词 flag 写"无英文锚点"。
5. 若该词是**动词**，返回 "aux" 字段给复合时态助动词：avere / essere / both（既可 avere 又可 essere）；没把握则不给。
6. 若该词是**名词**，返回 "gender" 字段：m(阳)/f(阴)/mf(阴阳共性)；并在复数不规则时返回 "plural" 字段给复数形（如 uovo→uova、braccio→braccia）；规则复数或没把握则不给 plural。
7. 返回 "ipa" 字段：该词音位式国际音标，意语约定——双写辅音长化(gatto /ˈɡat.to/)、开/闭元音区分 ɛ/e 与 ɔ/o、ci/gi 软化为 t͡ʃ/d͡ʒ、gl→ʎ、gn→ɲ、sc(e/i)→ʃ、主重音标 ˈ、音节点 . 分隔、两侧加斜杠。缩写/无读音的省略 ipa。
8. 返回 "col" 字段：该词最常用搭配或固定短语 1-3 条，形如 "vino rosso 红葡萄酒"（意语在前、中文在后，空格分隔）。只给搭配/短语，不要整句例句。无则 []。
9. 若你强烈认为缺了常见义项，在 flag 写"疑缺义:<简述>"，但不要为此往 zh 加义项（zh 数量必须严格等于 senses）。
10. 生僻/拿不准/可能歧义的词，flag 写简短原因；有把握则 flag=null。
11. 返回 "level" 字段：该词的 CEFR 难度等级，取值 A1/A2/B1/B2/C1/C2 之一（A1 最基础常用、C2 最生僻高阶）；按该意语词的实际使用频率与掌握难度判断，务必每词都给。
12. 严格输出 JSON，键与输入一致，格式 {"1":{"zh":[...],"aux":"avere","gender":"f","plural":"...","ipa":"/.../","col":["..."],"level":"B1","flag":null},...}（aux/gender/plural/ipa/col 无则省略，level 必给），不要多余文字。"""


def load_env():
    env = {}
    for ln in open(ENV_PATH):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.strip().split("=", 1)
            env[k] = v
    return env


def pending(conn, limit=None, words=None):
    if words:  # 定向翻译指定词（UI 展示 / 豆包抽样质检用），忽略 is_lemma 限制
        ph = ",".join("?" * len(words))
        return conn.execute(
            f"SELECT id, word, pos, definition FROM dict "
            f"WHERE word IN ({ph}) COLLATE NOCASE AND is_lemma=1 ORDER BY id",
            words,
        ).fetchall()
    q = ("SELECT id, word, pos, definition FROM dict "
         "WHERE is_lemma=1 AND translation IS NULL ORDER BY id")
    if limit:
        q += f" LIMIT {int(limit)}"
    return conn.execute(q).fetchall()


async def acall(comps, model, subrows):
    payload = {str(rid): {"w": w, "pos": pos, "senses": d.split("\n") if d else []}
               for rid, w, pos, d in subrows}
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
    """重试；持久失败(截断)对半拆递归。返回 (res, tok)。"""
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
    for rid, w, pos, d in chunk:
        senses = d.split("\n") if d else []
        o = res.get(str(rid), {}) if isinstance(res, dict) else {}
        o = o if isinstance(o, dict) else {}
        zh = o.get("zh", [])
        flag = o.get("flag")
        if not res or str(rid) not in res:
            flag = "__no_output__"
        if senses and isinstance(zh, list) and len(zh) != len(senses):
            flag = (str(flag) + " | " if flag else "") + f"__misalign__ {len(zh)}≠{len(senses)}"
        out[str(rid)] = {"w": w, "zh": zh, "aux": o.get("aux"), "gender": o.get("gender"),
                         "plural": o.get("plural"), "ipa": o.get("ipa"),
                         "col": o.get("col"), "level": o.get("level"), "flag": flag}
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


def translate(limit=None, words=None):
    OUT_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    rows = pending(conn, limit, words)
    conn.close()
    done = done_rids()
    rows = [r for r in rows if r[0] not in done]
    chunks = [rows[i:i + CHUNK] for i in range(0, len(rows), CHUNK)]
    print(f"待翻 {len(rows)} 词（已完成 {len(done)}）/ {len(chunks)} 批 MODE={MODE} CHUNK={CHUNK}")
    if not chunks:
        print("全部已完成，直接 --merge")
        return
    tok = asyncio.run(arun(chunks))
    print(f"完成本轮。累计 token {tok}。下一步：python3 b_translate.py --merge")


def merge():
    conn = sqlite3.connect(str(DB_PATH))
    n = nf = n_aux = n_gender = n_plural = n_ipa = nc = n_lvl = 0
    for fp in sorted(glob.glob(str(OUT_DIR / "chunk_*.json"))):
        data = json.load(open(fp))
        for rid, o in data.items():
            rid = int(rid)
            zh = o.get("zh") or []
            if not isinstance(zh, list):
                zh = [zh]
            zh = [str(x).strip() for x in zh if x not in (None, "")]
            tr = "\n".join(zh) if zh else None
            flag = o.get("flag")
            if flag is not None and not isinstance(flag, str):
                flag = str(flag)
            col = o.get("col") or []
            if not isinstance(col, list):
                col = [col]
            col = [str(x).strip() for x in col if isinstance(x, str) and x.strip()]
            collocation = "\n".join(col) if col else None
            ipa = o.get("ipa")
            if not (isinstance(ipa, str) and ipa.startswith("/")):
                ipa = None

            # CEFR 等级：豆包独有权威（kaikki 无），总是写；只收合法值 A1-C2
            lvl = o.get("level")
            lvl = lvl.strip().upper() if isinstance(lvl, str) else None
            if lvl not in ("A1", "A2", "B1", "B2", "C1", "C2"):
                lvl = None

            row = conn.execute(
                "SELECT pos, aux, conj, gender, plural, ipa FROM dict WHERE id=?", (rid,)
            ).fetchone()
            if not row:
                continue
            pos, cur_aux, cur_conj, cur_gender, cur_plural, cur_ipa = row
            sets, vals = ["translation=?", "flag=?", "collocation=?", "level=?"], [tr, flag, collocation, lvl]

            # 本质字段仲裁：kaikki 优先，仅填 kaikki 留空的缺口
            d_aux = o.get("aux")
            if not cur_aux and d_aux in ("avere", "essere", "both") and pos and "v" in pos.split("/"):
                sets.append("aux=?"); vals.append(d_aux); n_aux += 1
            d_g = o.get("gender")
            if not cur_gender and d_g in ("m", "f", "mf") and pos and any(
                    p in ("n", "name") for p in pos.split("/")):
                sets.append("gender=?"); vals.append(d_g); n_gender += 1
            d_pl = o.get("plural")
            # 消毒：豆包偶尔返回词典惯例符号（~=不变/+=规则/#/-）当复数，非真实词形，拦掉。
            if (not cur_plural and isinstance(d_pl, str)
                    and re.fullmatch(r"[a-zàèéìíòóùA-Z]{2,}", d_pl.strip())
                    and pos and "n" in pos.split("/")):
                sets.append("plural=?"); vals.append(d_pl.strip()); n_plural += 1
            if not cur_ipa and ipa:
                sets.append("ipa=?"); vals.append(ipa); n_ipa += 1

            vals.append(rid)
            conn.execute(f"UPDATE dict SET {', '.join(sets)} WHERE id=?", vals)
            n += 1
            if flag:
                nf += 1
            if collocation:
                nc += 1
            if lvl:
                n_lvl += 1
    conn.commit()
    conn.close()
    print(f"写回 {n} 词，flag {nf}；补缺 aux {n_aux}/gender {n_gender}/plural {n_plural}/ipa {n_ipa}；"
          f"搭配 {nc}；CEFR {n_lvl}")


def stats():
    conn = sqlite3.connect(str(DB_PATH))
    lemma = conn.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1").fetchone()[0]
    done = conn.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1 AND translation IS NOT NULL").fetchone()[0]
    conn.close()
    outn = len(glob.glob(str(OUT_DIR / "chunk_*.json")))
    print(f"lemma {lemma} | 已翻(库) {done} | 待翻 {lemma-done} | 已落盘 chunk {outn}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--words", type=str, default=None,
                    help="逗号分隔的定向词表（UI 展示/豆包抽样质检），只翻这些词")
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
        wl = [w.strip() for w in args.words.split(",") if w.strip()] if args.words else None
        translate(args.limit, wl)
