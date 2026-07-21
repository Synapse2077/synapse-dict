#!/usr/bin/env python3
"""
豆包翻译德语词典中文释义 + 补德语本质字段的缺口。
对象 = synapse-dict-de.sqlite 里 is_lemma=1 且 translation 为空的词。
变位/变格词不走这里（已由规则出 infl，IPA 由 lemma sounds 或豆包补）。

一种数据一个权威：
  · kaikki 抽到的 gender/genitive/plural/aux/三基本形式/ipa 是权威，豆包只填 kaikki 留空的缺口。
  · 中文释义、搭配、CEFR 难度、审计 flag = 豆包。

设计（承 fr/pt b_translate 的成熟架构，de 独立文件不 import）：
- 可中断续跑：按 chunk 落盘 b_out/，重跑跳过已完成 chunk。
- 对齐安全：index-key JSON（本地 rid↔dict.id），逐词校验 zh 长度=义项数，不符记 __misalign__。
- 只喂 词/词性/英文gloss（消歧用，不直译）；已有的 gender/aux 不喂（省 token）。

用法（在 de/ 目录）：
  python3 b_translate.py --mode online --words "Haus,gehen,ankommen,gut,Frau,schön"  # 小样验证
  python3 b_translate.py --limit 40     # 小样测试
  python3 b_translate.py                # 全量续跑，落 b_out/
  python3 b_translate.py --merge        # b_out/ 写回 sqlite（含本质字段仲裁）
  python3 b_translate.py --stats        # 进度
"""
import argparse
import asyncio
import json
import re
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "synapse-dict-de.sqlite"
OUT_FILE = HERE / "b_out.jsonl"   # 单文件续跑：每批一行 JSON，不再一 chunk 一文件
CONFLICT_FILE = HERE / "conflict_review.tsv"   # merge 时 kaikki↔豆包 冲突留痕，供人工复核
ENV_PATH = HERE.parent / ".env"
MODE = "batch"
CHUNK = 50
CONC = 50
TEMP = 0.3
MAX_RETRY = 2

SYS_PROMPT = """你是德语→简体中文的词典编纂专家。我给你一批德语词条，每条含词形、词性、若干英文义项。英文释义仅作消歧参考——不要直译英文，请用你自己的德语知识判断该义项真正含义，再给出地道简体中文。

规则：
1. 逐义项翻译，与输入 senses 一一对应：顺序一致、数量完全相等。绝不自行增删义项。
2. 以德语实际含义为准。英文释义可能有误或过窄。
3. zh 里只给中文释义本身，不加词性/性别/搭配标注（另有数据）。一个义项内多个近义中文用"，"分隔。
4. senses 为空的词，凭你的德语知识给最常用释义，并在该词 flag 写"无英文锚点"。
5. 若该词是**名词**，返回 "gender" 字段：m(阳，der)/f(阴，die)/n(中，das)/mf(阴阳共性)；并返回 "genitive" 属格单数形（Haus→Hauses、Student→Studenten）与 "plural" 复数形（Haus→Häuser、Kind→Kinder、Auto→Autos）。德语复数不可预测，务必给。
6. 若该词是**动词**，返回三基本形式：其一 "aux" 完成时助动词 haben 或 sein（位移/状态变化类 gehen/kommen/werden/sterben 等用 sein，其余多为 haben，没把握不给）；"praeteritum" 过去式第三人称单数（gehen→ging、machen→machte）；"partizip2" 过去分词（gehen→gegangen、machen→gemacht）。若为**可分动词**，返回 "separable":true 并在 "sep_prefix" 给可分前缀（ankommen→"an"、aufstehen→"auf"）。
7. 若该词是**形容词/副词**且有比较级，返回 "comparative" 比较级（schön→schöner、gut→besser）与 "superlative" 最高级（am schönsten、am besten）；不可比较（如 tot、rund）则不给。
8. 若该词是**动词/形容词/介词**且有固定支配(Rektion)，返回 "government" 字段：① 动词/形容词支配的格——helfen→"+Dat"、gedenken→"+Gen"、danken→"+Dat"；② 支配"介词+格"——warten→"auf +Akk"、denken→"an +Akk"、stolz→"auf +Akk"、bestehen→"aus +Dat"；③ 介词支配的格——mit→"+Dat"、für→"+Akk"、wegen→"+Gen"、双向 in/an/auf→"+Akk/Dat"。格缩写用 Akk/Dat/Gen。无固定支配或拿不准则省略。
9. 返回 "ipa" 字段：该词音位式国际音标，德语约定——长元音加 ː（gehen /ˈɡeːən/）、词首元音可带声门塞音 ʔ、小舌音 ʁ、ch 按前后作 ç/x、词尾清化（Tag /taːk/、Hund /hʊnt/），两侧加斜杠。无读音的省略 ipa。
10. 返回 "col" 字段：该词最常用搭配或固定短语 1-3 条，形如 "zu Hause 在家"（德语在前、中文在后，空格分隔）。只给搭配/短语，不要整句例句。无则 []。
11. 若你强烈认为缺了常见义项，在 flag 写"疑缺义:<简述>"，但不要为此往 zh 加义项（zh 数量必须严格等于 senses）。
12. 生僻/拿不准/可能歧义的词，flag 写简短原因；有把握则 flag=null。
13. 返回 "level" 字段：该词的 CEFR 难度等级，取值 A1/A2/B1/B2/C1/C2 之一（A1 最基础常用、C2 最生僻高阶）；按该德语词的实际使用频率与掌握难度判断，务必每词都给。
14. 严格输出 JSON，键与输入一致，格式 {"1":{"zh":[...],"gender":"n","genitive":"Hauses","plural":"Häuser","aux":"sein","praeteritum":"ging","partizip2":"gegangen","separable":true,"sep_prefix":"an","comparative":"...","superlative":"...","government":"+Dat","ipa":"/.../","col":["..."],"level":"B1","flag":null},...}（各本质字段无则省略，level 必给），不要多余文字。"""


def load_env():
    env = {}
    for ln in open(ENV_PATH):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.strip().split("=", 1)
            env[k] = v
    return env


def pending(conn, limit=None, words=None):
    if words:
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
        out[str(rid)] = {
            "w": w, "zh": zh,
            "gender": o.get("gender"), "genitive": o.get("genitive"),
            "plural": o.get("plural"), "aux": o.get("aux"),
            "praeteritum": o.get("praeteritum"), "partizip2": o.get("partizip2"),
            "separable": o.get("separable"), "sep_prefix": o.get("sep_prefix"),
            "comparative": o.get("comparative"), "superlative": o.get("superlative"),
            "government": o.get("government"),
            "ipa": o.get("ipa"), "col": o.get("col"),
            "level": o.get("level"), "flag": flag}
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


def _iter_batches():
    """逐行读单文件 JSONL，产出每批的 dict（末行截断等坏行跳过）。"""
    if not OUT_FILE.exists():
        return
    for ln in open(OUT_FILE, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            yield json.loads(ln)
        except Exception:
            pass


def done_rids():
    s = set()
    for data in _iter_batches():
        s.update(int(k) for k in data)
    return s


def translate(limit=None, words=None):
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


# 德语正字法字符类（含变音/eszett/大写），复数/属格/派生形消毒用
_DE_FORM = re.compile(r"[A-Za-zÄÖÜäöüßÁÀÂÉÈÊËÍÌÎÓÒÔÚÙÛÑÇáàâéèêëíìîóòôúùûñç'’ .\-]{1,40}$")


def _clean_form(v):
    if isinstance(v, str) and v.strip() and _DE_FORM.fullmatch(v.strip()):
        return v.strip()
    return None


def merge():
    conn = sqlite3.connect(str(DB_PATH))
    n = nf = nc = n_lvl = 0
    n_g = n_gen = n_pl = n_aux = n_pt = n_pp = n_sep = n_cmp = n_sup = n_ipa = 0
    n_gov = 0
    conflicts = []   # (word, field, kaikki值, 豆包值)：两边都有值且不一致，留痕不覆盖
    for data in _iter_batches():
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
            lvl = o.get("level")
            lvl = lvl.strip().upper() if isinstance(lvl, str) else None
            if lvl not in ("A1", "A2", "B1", "B2", "C1", "C2"):
                lvl = None

            row = conn.execute(
                "SELECT word, pos, gender, genitive, plural, aux, praeteritum, partizip2, "
                "separable, sep_prefix, comparative, superlative, government, ipa "
                "FROM dict WHERE id=?", (rid,)
            ).fetchone()
            if not row:
                continue
            (word, pos, c_g, c_gen, c_pl, c_aux, c_pt, c_pp,
             c_sep, c_spx, c_cmp, c_sup, c_gov, c_ipa) = row
            posset = set(pos.split("/")) if pos else set()
            sets = ["translation=?", "flag=?", "collocation=?", "level=?"]
            vals = [tr, flag, collocation, lvl]

            # 本质字段仲裁：kaikki 优先——空则填豆包，已有值而豆包不同则记冲突（不覆盖，供复核）
            d_g = o.get("gender")
            if isinstance(d_g, str) and d_g.strip() in ("m", "f", "n", "mf") and ({"n", "name"} & posset):
                d_g = d_g.strip()
                if not c_g:
                    sets.append("gender=?"); vals.append(d_g); n_g += 1
                elif c_g.strip() != d_g:
                    conflicts.append((word, "gender", c_g, d_g))
            if {"n", "name"} & posset:
                v = _clean_form(o.get("genitive"))
                if v:
                    if not c_gen:
                        sets.append("genitive=?"); vals.append(v); n_gen += 1
                    elif c_gen.strip() != v:
                        conflicts.append((word, "genitive", c_gen, v))
                v = _clean_form(o.get("plural"))
                if v:
                    if not c_pl:
                        sets.append("plural=?"); vals.append(v); n_pl += 1
                    elif c_pl.strip() != v:
                        conflicts.append((word, "plural", c_pl, v))
            d_aux = o.get("aux")
            if d_aux in ("haben", "sein", "both") and "v" in posset:
                if not c_aux:
                    sets.append("aux=?"); vals.append(d_aux); n_aux += 1
                elif c_aux.strip() != d_aux:
                    conflicts.append((word, "aux", c_aux, d_aux))
            if "v" in posset:
                v = _clean_form(o.get("praeteritum"))
                if v:
                    if not c_pt:
                        sets.append("praeteritum=?"); vals.append(v); n_pt += 1
                    elif c_pt.strip() != v:
                        conflicts.append((word, "praeteritum", c_pt, v))
                v = _clean_form(o.get("partizip2"))
                if v:
                    if not c_pp:
                        sets.append("partizip2=?"); vals.append(v); n_pp += 1
                    elif c_pp.strip() != v:
                        conflicts.append((word, "partizip2", c_pp, v))
            if not c_sep and o.get("separable") is True and "v" in posset:
                spx = _clean_form(o.get("sep_prefix"))
                sets.append("separable=?"); vals.append(1); n_sep += 1
                if spx and not c_spx:
                    sets.append("sep_prefix=?"); vals.append(spx)
            if posset & {"adj", "adv"}:
                v = _clean_form(o.get("comparative"))
                if v:
                    if not c_cmp:
                        sets.append("comparative=?"); vals.append(v); n_cmp += 1
                    elif c_cmp.strip() != v:
                        conflicts.append((word, "comparative", c_cmp, v))
                v = _clean_form(o.get("superlative"))
                if v:
                    if not c_sup:
                        sets.append("superlative=?"); vals.append(v); n_sup += 1
                    elif c_sup.strip() != v:
                        conflicts.append((word, "superlative", c_sup, v))
            # government（Rektion）：kaikki 无此项，豆包独源，只填不冲突
            d_gov = o.get("government")
            if (isinstance(d_gov, str) and d_gov.strip()
                    and (posset & {"v", "adj", "adv", "prep"}) and not c_gov):
                sets.append("government=?"); vals.append(d_gov.strip()); n_gov += 1
            if ipa:
                if not c_ipa:
                    sets.append("ipa=?"); vals.append(ipa); n_ipa += 1
                elif c_ipa.strip() != ipa.strip():
                    conflicts.append((word, "ipa", c_ipa, ipa.strip()))

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
    if conflicts:
        with open(CONFLICT_FILE, "w", encoding="utf-8") as cf:
            cf.write("word\tfield\tkaikki\tdoubao\n")
            for w_, f_, kv, dv in conflicts:
                cf.write(f"{w_}\t{f_}\t{kv}\t{dv}\n")
    print(f"写回 {n} 词，flag {nf}；补缺 gender {n_g}/属格 {n_gen}/复数 {n_pl}/aux {n_aux}/"
          f"过去式 {n_pt}/过去分词 {n_pp}/可分 {n_sep}/比较级 {n_cmp}/最高级 {n_sup}/支配 {n_gov}/ipa {n_ipa}；"
          f"搭配 {nc}；CEFR {n_lvl}")
    print(f"kaikki↔豆包 冲突 {len(conflicts)} 处"
          + (f" → {CONFLICT_FILE.name}（已按 kaikki 保留，可人工复核）" if conflicts else ""))


def stats():
    conn = sqlite3.connect(str(DB_PATH))
    lemma = conn.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1").fetchone()[0]
    done = conn.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1 AND translation IS NOT NULL").fetchone()[0]
    conn.close()
    outn = len(done_rids())
    print(f"lemma {lemma} | 已翻(库) {done} | 待翻 {lemma-done} | 已落盘(单文件) {outn} 词")


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
