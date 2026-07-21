#!/usr/bin/env python3
"""
豆包翻译葡萄牙语词典中文释义 + 补葡语本质字段的缺口。
对象 = synapse-dict-pt.sqlite 里 is_lemma=1 且 translation 为空的词（约 7 万）。
变位词不走这里（已由规则出 infl；变位形音标葡语无法收割，多为空）。

一种数据一个权威：
  · kaikki 抽到的 gender/plural/feminine/双音(ipa_br/ipa_pt) 是权威，豆包只填缺口（merge 仲裁）。
  · 中文释义、搭配、CEFR 难度、审计 flag = 豆包。

葡语专属：豆包 IPA 兜底须**同时返回巴西(br)与葡萄牙(pt)两套音**；adj_pos(形容词位置变义)+
government(动词介词支配 regência) 由豆包填(kaikki 无此项、独源不冲突)；无 aux(葡语复合时态恒用 ter)。
双过去分词 pp/pp_short 由 build.py 从 kaikki 确定性抽，不走豆包。

设计（承 es/it/fr b_translate 成熟架构，pt 独立文件不 import）：
- 可中断续跑：按 chunk 落盘 b_out/，重跑跳过已完成 chunk。
- 对齐安全：index-key JSON，逐词校验 zh 长度=义项数，不符记 __misalign__。

用法（在 pt/ 目录）：
  python3 b_translate.py --limit 40     # 小样测试
  python3 b_translate.py                # 全量续跑
  python3 b_translate.py --merge        # 写回 sqlite（含本质字段仲裁）
  python3 b_translate.py --stats        # 进度
"""
import argparse
import asyncio
import json
import re
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "synapse-dict-pt.sqlite"
OUT_FILE = HERE / "b_out.jsonl"   # 单文件续跑：每批一行 JSON，不再一 chunk 一文件
CONFLICT_FILE = HERE / "conflict_review.tsv"   # merge 时 kaikki↔豆包 冲突留痕，供人工复核
ENV_PATH = HERE.parent / ".env"
MODE = "batch"
CHUNK = 50
CONC = 50
TEMP = 0.3
MAX_RETRY = 2

SYS_PROMPT = """你是葡萄牙语→简体中文的词典编纂专家。我给你一批葡语词条，每条含词形、词性、若干英文义项。英文释义仅作消歧参考——不要直译英文，请用你自己的葡语知识判断该义项真正含义，再给出地道简体中文。

规则：
1. 逐义项翻译，与输入 senses 一一对应：顺序一致、数量完全相等。绝不自行增删义项。
2. 以葡语实际含义为准。英文释义可能有误或过窄。
3. zh 里只给中文释义本身，不加词性/性别/搭配标注（另有数据）。一个义项内多个近义中文用"，"分隔。
4. senses 为空的词，凭你的葡语知识给最常用释义，并在该词 flag 写"无英文锚点"。
5. 若该词是**名词**，返回 "gender" 字段：m(阳)/f(阴)/mf(阴阳共性)；并在复数不规则时返回 "plural" 字段给复数形（如 pão→pães、animal→animais、ator→atores）；规则复数(+s)或没把握则不给 plural。
6. 若该词是**名词或形容词**且有阴性对应形，返回 "feminine" 字段：名词给阴性对应词（ator→atriz、cão→cadela、menino→menina），形容词给阴性形（bonito→bonita、bom→boa）；阴阳同形或无阴性形则不给。
7. 返回巴西与葡萄牙**两套音标**：字段 "ipa_br"(巴西 pt-BR) 与 "ipa_pt"(欧洲 pt-PT)，音位式、两侧加斜杠。葡语约定——鼻化元音 ɐ̃/õ/ɐ̃w̃、开闭元音、巴西非重读 e/o 常读 i/u 且词尾 -te/-de→t͡ʃ/d͡ʒ、葡萄牙非重读 a→ɐ 且 e 常弱化为 ɨ、音节点 . 分隔。如 livre → ipa_br "/ˈli.vɾi/"、ipa_pt "/ˈli.vɾɨ/"。缩写/无读音的省略。
8. 返回 "col" 字段：该词最常用搭配或固定短语 1-3 条，形如 "água potável 饮用水"（葡语在前、中文在后，空格分隔）。只给搭配/短语，不要整句例句。无则 []。
9. 若该词是**形容词**，返回 "adj_pos" 字段：pre(通常前置)/post(通常后置)/both(前后皆可且位置常改变词义，如 velho amigo 老友 vs amigo velho 年长的朋友；grande homem 伟人 vs homem grande 大个子)。多数描述性形容词后置；表主观/大小/次第的常前置；拿不准则省略。
10. 若该词是**动词或形容词**且强制搭配某介词(regência 支配)，返回 "government" 字段，形如 "gostar de"、"precisar de"、"assistir a"、"obedecer a"、"depender de"、"consistir em"。无固定支配或拿不准则省略。
11. 若你强烈认为缺了常见义项，在 flag 写"疑缺义:<简述>"，但不要为此往 zh 加义项（zh 数量必须严格等于 senses）。
12. 生僻/拿不准/可能歧义的词，flag 写简短原因；有把握则 flag=null。
13. 返回 "level" 字段：该词的 CEFR 难度等级，取值 A1/A2/B1/B2/C1/C2 之一（A1 最基础常用、C2 最生僻高阶）；按该葡语词的实际使用频率与掌握难度判断，务必每词都给。
14. 严格输出 JSON，键与输入一致，格式 {"1":{"zh":[...],"gender":"m","plural":"...","feminine":"...","adj_pos":"post","government":"gostar de","ipa_br":"/.../","ipa_pt":"/.../","col":["..."],"level":"B1","flag":null},...}（gender/plural/feminine/adj_pos/government/ipa_br/ipa_pt/col 无则省略，level 必给），不要多余文字。"""


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
        out[str(rid)] = {"w": w, "zh": zh, "gender": o.get("gender"),
                         "plural": o.get("plural"), "feminine": o.get("feminine"),
                         "adj_pos": o.get("adj_pos"), "government": o.get("government"),
                         "ipa_br": o.get("ipa_br"), "ipa_pt": o.get("ipa_pt"),
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


def _clean_ipa(v):
    return v if (isinstance(v, str) and v.startswith("/") and v.endswith("/")) else None


def merge():
    conn = sqlite3.connect(str(DB_PATH))
    n = nf = n_gender = n_plural = n_fem = n_br = n_pt = nc = n_lvl = 0
    n_adjpos = n_gov = 0
    _wordre = re.compile(r"[a-zàáâãçéêíóôõúA-Z'’ -]{2,}")
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
            br = _clean_ipa(o.get("ipa_br"))
            pt = _clean_ipa(o.get("ipa_pt"))

            lvl = o.get("level")
            lvl = lvl.strip().upper() if isinstance(lvl, str) else None
            if lvl not in ("A1", "A2", "B1", "B2", "C1", "C2"):
                lvl = None

            row = conn.execute(
                "SELECT word, pos, gender, plural, feminine, ipa_br, ipa_pt, adj_pos, government "
                "FROM dict WHERE id=?", (rid,)
            ).fetchone()
            if not row:
                continue
            (word, pos, cur_gender, cur_plural, cur_fem, cur_br, cur_pt,
             cur_adjpos, cur_gov) = row
            posset = set(pos.split("/")) if pos else set()
            sets = ["translation=?", "flag=?", "collocation=?", "level=?"]
            vals = [tr, flag, collocation, lvl]

            # kaikki 优先——空则填豆包，kaikki 已有值而豆包不同则记冲突（不覆盖，供人工复核）
            d_g = o.get("gender")
            if d_g in ("m", "f", "mf") and ({"n", "name"} & posset):
                if not cur_gender:
                    sets.append("gender=?"); vals.append(d_g); n_gender += 1
                elif cur_gender.strip() != d_g:
                    conflicts.append((word, "gender", cur_gender, d_g))
            d_pl = o.get("plural")
            if (isinstance(d_pl, str) and _wordre.fullmatch(d_pl.strip()) and "n" in posset):
                d_pl = d_pl.strip()
                if not cur_plural:
                    sets.append("plural=?"); vals.append(d_pl); n_plural += 1
                elif cur_plural.strip() != d_pl:
                    conflicts.append((word, "plural", cur_plural, d_pl))
            d_fem = o.get("feminine")
            if (isinstance(d_fem, str) and _wordre.fullmatch(d_fem.strip())
                    and (posset & {"adj", "n", "name"})):
                d_fem = d_fem.strip()
                if not cur_fem:
                    sets.append("feminine=?"); vals.append(d_fem); n_fem += 1
                elif cur_fem.strip() != d_fem:
                    conflicts.append((word, "feminine", cur_fem, d_fem))
            # adj_pos / government：kaikki 无此项，豆包独源，只填不冲突
            d_ap = o.get("adj_pos")
            if d_ap in ("pre", "post", "both") and "adj" in posset and not cur_adjpos:
                sets.append("adj_pos=?"); vals.append(d_ap); n_adjpos += 1
            d_gov = o.get("government")
            if (isinstance(d_gov, str) and d_gov.strip()
                    and (posset & {"v", "adj"}) and not cur_gov):
                sets.append("government=?"); vals.append(d_gov.strip()); n_gov += 1
            # 双读音：巴西 ipa_br / 葡萄牙 ipa_pt 各自仲裁
            if br:
                if not cur_br:
                    sets.append("ipa_br=?"); vals.append(br); n_br += 1
                elif cur_br.strip() != br.strip():
                    conflicts.append((word, "ipa_br", cur_br, br.strip()))
            if pt:
                if not cur_pt:
                    sets.append("ipa_pt=?"); vals.append(pt); n_pt += 1
                elif cur_pt.strip() != pt.strip():
                    conflicts.append((word, "ipa_pt", cur_pt, pt.strip()))

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
    print(f"写回 {n} 词，flag {nf}；补缺 gender {n_gender}/plural {n_plural}/feminine {n_fem}/"
          f"形容词位置 {n_adjpos}/介词支配 {n_gov}/巴西音 {n_br}/葡音 {n_pt}；搭配 {nc}；CEFR {n_lvl}")
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
    ap.add_argument("--words", type=str, default=None)
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
