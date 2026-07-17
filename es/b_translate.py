#!/usr/bin/env python3
"""
B 组：豆包翻译西语词典中文释义。
对象 = synapse-dict-es.sqlite 里 is_lemma=1 且 translation 为空的词（约 10.5 万）。
变位词不走这里（已由规则出 infl）。

设计：
- 可中断可续跑：按 chunk 落盘到 b_out/，重跑自动跳过已完成的 chunk（Ctrl-C 随时停）。
- 对齐安全：index-key JSON（本地序号↔dict.id），逐词校验 zh 长度=义项数，不符的记 __misalign__ flag。
- 只喂 词/词性/英文gloss（仅消歧，不直译）；性别/地区/语域/数已在 meta，不喂豆包。
- 单趟 + 可疑 flag：豆包自评拿不准写 flag；空壳(无gloss)词豆包按规则会标"无英文锚点"。

用法（在 es/ 目录）：
  python3 b_translate.py --limit 80      # 先小样测试（前 80 词）
  python3 b_translate.py                 # 全量翻译（续跑），结果落 b_out/
  python3 b_translate.py --merge         # 把 b_out/ 写回 sqlite 的 translation / flag 列
  python3 b_translate.py --stats         # 看进度（已翻 / 待翻 / flag 数）

配置见下方 CONFIG（模型 online/batch、chunk 大小等）。切 batch：MODE="batch"。
"""
import argparse
import asyncio
import glob
import json
import re
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ============== CONFIG（可改）==============
DB_PATH = HERE / "synapse-dict-es.sqlite"
OUT_DIR = HERE / "b_out"
ENV_PATH = HERE.parent / ".env"
MODE = "batch"          # "batch"(ep-bi) 或 "online"(ep-m)。batch 高并发不慢
CHUNK = 50             # 每批词数（不设 max_tokens，用模型默认上限；超了自动拆半）
CONC = 50              # 并发批数（AsyncArk 异步，提速关键）
TEMP = 0.3
MAX_RETRY = 2          # 网络类错误重试次数（截断类不重试、直接拆）
# ==========================================

SYS_PROMPT = """你是西班牙语→简体中文的词典编纂专家。我会给你一批西语词条，每条含词形、词性、若干义项。英文释义仅作消歧参考——不要直译英文，请用你自己的西语知识判断该义项的真正含义，再给出地道简体中文。

规则：
1. 逐义项翻译，与输入 senses 一一对应：顺序一致、数量完全相等。绝不自行增删义项。
2. 以西语实际含义为准。英文释义可能有误或过窄，例：escalera 的 "straight" 实为扑克"顺子"，不是"直的"。
3. zh 里只给中文释义本身，不要加词性/性别/地区/语域等标注（这些我另有数据）。一个义项内多个近义中文用"，"分隔。
4. senses 为空的词（英文缺失），凭你的西语知识给最常用释义，并在该词 flag 写"无英文锚点"。
5. 若该词是名词，返回 "g" 字段给性别：m(阳)/f(阴)/mf(阴阳共性)；非名词或没把握则不给 g。
6. 返回 "ipa" 字段：该词的音位式国际音标，约定 c/z→θ、ll/y→ʝ、j及ge/gi→x、单r→ɾ/rr→r、主重音标 ˈ、两侧加斜杠，例 escalera→/eskaˈleɾa/、whisky→/ˈwiski/。缩写/词缀等无词读音的省略 ipa。
7. 返回 "col" 字段：该词最常用的搭配或固定短语 1-3 条，每条形如 "escalera mecánica 自动扶梯"（西语在前、中文在后，空格分隔）。只给搭配/短语，**不要**给整句例句。没有典型搭配则 col 为空数组 []。
8. 若你强烈认为该词缺了一个常见义项（我给的 senses 没覆盖到），在 flag 写"疑缺义:<简述>"；但**不要**为此往 zh 加义项，zh 数量必须严格等于 senses。
9. 生僻、拿不准、可能歧义的词，在该词 flag 写一句简短原因；有把握则 flag=null。
10. 严格输出 JSON，键与输入一致，格式 {"1":{"zh":[...],"g":"f","ipa":"/.../","col":["..."],"flag":null},...}（g/ipa/col 无则省略或空），不要多余文字。"""


def load_env():
    env = {}
    for ln in open(ENV_PATH):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.strip().split("=", 1)
            env[k] = v
    return env


def get_client_model():
    from volcenginesdkarkruntime import Ark
    env = load_env()
    client = Ark(api_key=env["ARK_API_KEY"])
    if MODE == "online":
        return client.chat.completions, env["DOUBAO_MODEL_ONLINE_LITE"]
    return client.batch_chat.completions, env["DOUBAO_MODEL_BATCH_LITE"]


IPA_PROMPT = """你是西班牙语语音专家。我给你一批词（可能含外来词、地名、缩写、古拼写 ç 等），逐个给音位式 IPA。
约定：c/z/ç→θ、ll/y→ʝ、j 及 ge/gi→x、单 r→ɾ/rr→r、主重音标 ˈ、两侧加斜杠，例 /eskaˈleɾa/。
缩写、纯数字序号（1º/DVDs/OMG 等）、无单词读音的 → 该项返回 null。
严格输出 JSON，键与输入序号一致：{"1":"/.../","2":null,...}，无多余文字。"""


def ipatodo():
    """给 b_ipa_todo.txt 里规则搞不定的词（外文字符/古拼写）做 ipa-only 豆包补。"""
    todo = HERE / "b_ipa_todo.txt"
    words = [w.strip() for w in todo.read_text(encoding="utf-8").splitlines() if w.strip()]
    print(f"ipa-todo {len(words)} 词，MODE={MODE}")
    endpoint, model = get_client_model()
    conn = sqlite3.connect(str(DB_PATH))
    filled = 0
    for ci in range(0, len(words), CHUNK):
        chunk = words[ci:ci + CHUNK]
        payload = {str(j + 1): w for j, w in enumerate(chunk)}
        usr = "词表：\n" + json.dumps(payload, ensure_ascii=False)
        try:
            r = endpoint.create(model=model, temperature=0, messages=[
                {"role": "system", "content": IPA_PROMPT}, {"role": "user", "content": usr}])
            out = re.sub(r"^```(json)?|```$", "", r.choices[0].message.content.strip(), flags=re.M).strip()
            res = json.loads(out)
        except Exception as e:
            print(f"  chunk {ci} 失败: {e}"); continue
        for j, w in enumerate(chunk, 1):
            ipa = res.get(str(j))
            if isinstance(ipa, str) and ipa.startswith("/"):
                conn.execute("UPDATE dict SET phonetic=? WHERE word=? AND phonetic IS NULL", (ipa, w))
                filled += 1
        conn.commit()
        print(f"  [{ci//CHUNK+1}] 已补 {filled}")
    conn.close()
    print(f"完成，补 IPA {filled} / {len(words)}（其余为缩写/数字，豆包正确留空）")


def pending(conn, limit=None):
    q = ("SELECT id, word, pos, definition FROM dict "
         "WHERE is_lemma=1 AND translation IS NULL ORDER BY id")
    if limit:
        q += f" LIMIT {int(limit)}"
    return conn.execute(q).fetchall()


async def acall(comps, model, subrows):
    """subrows→(res{str(rid):{...}}, tok)。JSON 键用 rid。抛异常=失败。异步。"""
    payload = {str(rid): {"w": w, "pos": pos, "senses": d.split("\n") if d else []}
               for rid, w, pos, d in subrows}
    usr = "输入：\n" + json.dumps(payload, ensure_ascii=False)
    r = await comps.create(
        model=model, temperature=TEMP,          # 不设 max_tokens，用模型默认上限
        messages=[{"role": "system", "content": SYS_PROMPT},
                  {"role": "user", "content": usr}])
    out = r.choices[0].message.content.strip()
    out = re.sub(r"^```(json)?|```$", "", out, flags=re.M).strip()
    res = json.loads(out)
    tok = getattr(getattr(r, "usage", None), "total_tokens", 0)
    return res, tok


async def aresolve(comps, model, subrows):
    """重试；持久失败(截断)则对半拆递归，坏词不连累整批。返回 (res, tok)。"""
    last = None
    for attempt in range(MAX_RETRY + 1):
        try:
            return await acall(comps, model, subrows)
        except json.JSONDecodeError as e:
            last = e
            break                                 # 截断/坏JSON：重试也会坏，直接去拆
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
        o = res.get(str(rid), {})
        zh = o.get("zh", []) if isinstance(o, dict) else []
        g = o.get("g") if isinstance(o, dict) else None
        ipa = o.get("ipa") if isinstance(o, dict) else None
        col = o.get("col") if isinstance(o, dict) else None
        flag = o.get("flag") if isinstance(o, dict) else "__no_output__"
        if senses and len(zh) != len(senses):
            flag = (flag + " | " if flag else "") + f"__misalign__ {len(zh)}≠{len(senses)}"
        out[str(rid)] = {"w": w, "zh": zh, "g": g, "ipa": ipa, "col": col, "flag": flag}
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
    """已落盘（任一 chunk 文件里出现过）的 rid 集合——词级续跑，改 CHUNK 也不会重译。"""
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
    rows = [r for r in rows if r[0] not in done]      # 词级续跑
    chunks = [rows[i:i + CHUNK] for i in range(0, len(rows), CHUNK)]
    print(f"待翻 {len(rows)} 词（已完成 {len(done)}）/ {len(chunks)} 批 MODE={MODE} CHUNK={CHUNK}")
    if not chunks:
        print("全部已完成，直接 --merge")
        return
    tok = asyncio.run(arun(chunks))
    print(f"完成本轮。累计 token {tok}。下一步：python3 b_translate.py --merge")


def merge():
    conn = sqlite3.connect(str(DB_PATH))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(dict)")]
    if "flag" not in cols:
        conn.execute("ALTER TABLE dict ADD COLUMN flag TEXT")
    if "collocation" not in cols:
        conn.execute("ALTER TABLE dict ADD COLUMN collocation TEXT")
    n = nf = ng_fill = ng_conf = nc = nip = 0
    for fp in sorted(glob.glob(str(OUT_DIR / "chunk_*.json"))):
        data = json.load(open(fp))
        for rid, o in data.items():
            rid = int(rid)
            # —— 消毒：豆包偶尔把 zh/col/ipa 返回成 list 或非串 ——
            zh = o.get("zh") or []
            if not isinstance(zh, list):
                zh = [zh]
            zh = [str(x).strip() for x in zh if x not in (None, "")]
            tr = "\n".join(zh) if zh else None
            flag = o.get("flag")
            if flag is not None and not isinstance(flag, str):
                flag = str(flag)
            g = o.get("g")
            col = o.get("col") or []
            if not isinstance(col, list):
                col = [col]
            col = [str(x).strip() for x in col if isinstance(x, str) and x.strip()]
            collocation = "\n".join(col) if col else None
            ipa = o.get("ipa")
            if not (isinstance(ipa, str) and ipa.startswith("/")):
                ipa = None
            pos, meta_json, cur_ph = conn.execute(
                "SELECT pos, meta, phonetic FROM dict WHERE id=?", (rid,)).fetchone()
            # 音标只在库里没有时才用豆包的（kaikki/规则 优先）
            new_ph = cur_ph
            if not cur_ph and ipa:
                new_ph = ipa
                nip += 1
            new_meta = meta_json
            # 性别裁决（仅纯名词，避免给混合pos的动词义项误加性别）：
            #   kaikki 无 → 用豆包(补缺)；kaikki 均一 → 规则合并（任一方 mf 取 mf，
            #   两单性冲突取豆包）；kaikki 混合(逐义项不同性别，如 orden) → 保留不动。
            is_pure_noun = pos in ("n", "name", "n/name", "name/n")
            if g in ("m", "f", "mf") and is_pure_noun:
                meta = json.loads(meta_json) if meta_json else []
                kaikki_gs = {s.get("g") for s in meta if s.get("g")}
                resolved = None
                if not kaikki_gs:
                    resolved = g
                    ng_fill += 1
                elif len(kaikki_gs) == 1:
                    k = next(iter(kaikki_gs))
                    if k == g:
                        resolved = k
                    elif "mf" in (k, g):
                        resolved = "mf"        # 谁说 mf 取 mf
                    else:
                        resolved = g           # m↔f 完全冲突 → 豆包
                        ng_conf += 1
                # kaikki_gs 多值(混合)→ resolved None，保留 kaikki 逐义项
                if resolved:
                    if meta:
                        for s in meta:
                            s["g"] = resolved
                    else:
                        meta = [{"g": resolved} for _ in zh] if zh else [{"g": resolved}]
                    new_meta = json.dumps(meta, ensure_ascii=False)
            conn.execute("UPDATE dict SET translation=?, flag=?, meta=?, collocation=?, phonetic=? WHERE id=?",
                         (tr, flag, new_meta, collocation, new_ph, rid))
            n += 1
            if flag:
                nf += 1
            if collocation:
                nc += 1
    conn.commit()
    conn.close()
    print(f"写回 {n} 词，带 flag {nf}（待复核）；性别补缺 {ng_fill}，"
          f"m↔f冲突取豆包 {ng_conf}；有搭配 {nc}；补音标 {nip}")


def stats():
    conn = sqlite3.connect(str(DB_PATH))
    lemma = conn.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1").fetchone()[0]
    done = conn.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1 AND translation IS NOT NULL").fetchone()[0]
    cols = [r[1] for r in conn.execute("PRAGMA table_info(dict)")]
    flagged = (conn.execute("SELECT COUNT(*) FROM dict WHERE flag IS NOT NULL").fetchone()[0]
               if "flag" in cols else 0)
    conn.close()
    outn = len(glob.glob(str(OUT_DIR / "chunk_*.json")))
    print(f"lemma {lemma} | 已翻(库) {done} | 待翻 {lemma-done} | flag {flagged} | 已落盘chunk {outn}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--ipatodo", action="store_true", help="给 b_ipa_todo.txt 做 ipa-only 豆包补")
    ap.add_argument("--mode", choices=["online", "batch"], default=None,
                    help="覆盖 CONFIG 的 MODE：online(ep-m,快,测试) / batch(ep-bi,便宜,跑量)")
    ap.add_argument("--chunk", type=int, default=None, help="覆盖每批词数")
    ap.add_argument("--concurrency", type=int, default=None, help="并发批数(提速)")
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
    elif args.ipatodo:
        ipatodo()
    else:
        translate(args.limit)
