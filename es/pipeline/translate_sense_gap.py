#!/usr/bin/env python3
"""给补收回来的义项（`sense_add`）补中文。2026-08-10。

`ingest_sense_gap.py` 收了 1,963 条 dump 里有、库里没落地的义项，`zh` 全空。
本脚本填它，分工与 `sense_es` 那轮一致：收录归收录，翻译归翻译。

═══ 模板在模型前面（铁律「能确定性做的别问模型」）═══
这批里有一族是纯指针套话，句式固定，模板输出比模型稳，也不花钱：

    Grafía alternativa de UNESCO.   → UNESCO 的另一种写法
    Variante de armario ('mueble'). → armario 的变体
    Diminutivo de valle.            → valle 的指小形式
    Apellido.                       → 姓氏
    Forma femenina de -ato.         → -ato 的阴性形式

模板取自 `fixes/fix_altof_lemma.py`（英文侧）与本文件的西语侧对照表，**不另造一套措辞**。

═══ 🔴 送模型的那批，payload 必须带三样 ═══
① **该词已有的义项**。补收的义项是要**并进现有词条**的，模型不知道旁边有什么，
   就会把 `qué onda` 的 `what's up?, what's wrong?` 翻成又一条「你好吗」，
   和已有的「你好吗」并排显示两遍。⇒ 一并要它判 `dup`：与已有哪条重复（下标），
   不重复给 null。**翻译与判重一次调用产出**，多吐一个字段零成本（同 2026-08-06 的
   `en_i` 对齐：46 tokens/词 + 50/义项）。
② **上位义 `parent`**。`teléfono` 的「mobile phone」在 kaikki 里挂在
   「telephone (a telecommunication device…)」之下，单看 `mobile phone` 会翻成
   孤零零的「手机」，看不出它是电话的一个子义。
③ **词性**。`A` 的 `bishop` 是国际象棋记谱里的「象」（alfil），不是主教。

⚠️ 还要明说：`(Neophron percnopterus)` 这类学名、`:*` 残渣已清、句末标点不要带进中文
   —— 这四个 payload 坑在 `sense_es` 那轮踩过一遍。

═══ 模型 ═══
默认 flash（整句翻译是生成不是推导，已在 13.9 万条西语义项上验过）。
但这批**生僻词占比高**（636 个专名 + 41 个缩写 + 155 个小众词），
而豆包在生僻词释义上明显更强（机械式敷衍 3% vs 19%）⇒ `--model both` 先同批对比。
关思考（成批当判官/翻译默认关，见项目纪律）。

═══ 落点与幂等 ═══
写 `sense_add.zh` / `zh_src`，**只填空不覆盖**（[[replay-scripts-undo-fixes]]）。
🔴 **`dup` 存的是「已有那条义项的中文原文」，不是下标、也不是 `sense.id`。**
模型回的是 `exist` 列表的下标，本脚本落库前就把它解成文本存进 `sense_add.dup_zh`。
理由：出版层是 DROP 重建的，`sense.id` 每次都变；而下标是「按行号对齐」那个
已经咬过三次的契约的又一个变体。按原文精确匹配才是重建稳定的，
与 `sense_relation` 的挂载方式一致（那里 97.5% 命中）。
⚠️ 第一版把下标直接当 `sense.id` 用，结果是 **C① 静默变成 0 条**（不报错、不抛异常，
   只是一条都没并），而且小下标万一撞上同词的 sense id 就是真·错配。

用法（在仓库根）：
    python3 -m es.pipeline.translate_sense_gap --sample 120 --model both --ask
    python3 -m es.pipeline.translate_sense_gap --all --model flash --ask --apply
"""
import argparse
import asyncio
import collections
import json
import os
import random
import re
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))

import dbtool   # noqa: E402
import paths    # noqa: E402

PAR = 8
CHUNK = {"flash": 20, "v4pro": 30, "doubao": 20}

# ═══ 西语侧指针套话 → 中文模板（英文侧的在 fix_altof_lemma.PREFIX_ZH）═══
ES_TMPL = [
    (re.compile(r"^Grafía\s+alternativa\s+de\s+(.+?)\.?$", re.I), "{} 的另一种写法"),
    (re.compile(r"^Grafía\s+obsoleta\s+de\s+(.+?)\.?$", re.I), "{} 的已废拼写"),
    (re.compile(r"^Variante\s+(?:obsoleta\s+)?de\s+(.+?)\.?$", re.I), "{} 的变体"),
    (re.compile(r"^Diminutivo\s+de\s+(.+?)\.?$", re.I), "{} 的指小形式"),
    (re.compile(r"^Aumentativo\s+de\s+(.+?)\.?$", re.I), "{} 的指大形式"),
    (re.compile(r"^Superlativo\s+de\s+(.+?)\.?$", re.I), "{} 的最高级"),
    (re.compile(r"^Forma\s+femenina\s+de\s+(.+?)\.?$", re.I), "{} 的阴性形式"),
    (re.compile(r"^Forma\s+masculina\s+de\s+(.+?)\.?$", re.I), "{} 的阳性形式"),
    (re.compile(r"^Apócope\s+de\s+(.+?)\.?$", re.I), "{} 的截短形式"),
    (re.compile(r"^Acortamiento\s+de\s+(.+?)\.?$", re.I), "{} 的截短形式"),
    (re.compile(r"^Apellido\.?$", re.I), "姓氏"),
    (re.compile(r"^Nombre\s+de\s+pila\s+de\s+varón\.?$", re.I), "男性名"),
    (re.compile(r"^Nombre\s+de\s+pila\s+de\s+mujer\.?$", re.I), "女性名"),
]
# 括号补充说明（`cuzco (perro)`）保留在中文里会更准，但模板只取到括号前，
# 与 fix_altof_lemma 的取舍一致：模板保正文，补充说明由原文列承担。
PAREN_TAIL = re.compile(r"\s*\([^)]*\)\s*$")


def tmpl_zh(gloss: str):
    """→ (中文, 模板名)；套不上返回 ('','')。"""
    g = gloss.strip()
    for rx, out in ES_TMPL:
        m = rx.match(g)
        if m:
            if "{}" not in out:
                return out, rx.pattern[:28]
            base = PAREN_TAIL.sub("", m.group(1)).strip()
            return out.format(base), rx.pattern[:28]
    return "", ""


SYS = """你是西班牙语→中文词典的编纂者。输入是一个 JSON 数组，每个元素是一条**待补收**的义项。

字段：
  id     条目号，原样回传
  w      词形
  lang   这条原文的语言：en=英文版维基的对应词，es=西语版维基的单语定义
  g      原文
  pos    词性
  parent 上位义原文（可能没有）。有它说明 g 是它的一个**子义**，中文要体现从属关系
  exist  该词**已有**的义项中文列表（可能为空）。你要判断 g 是不是其中某一条的重复

对每条输出：
  id
  zh    中文释义。词典体例：名词给对应词或短定义，动词给动词短语；不要整句翻译腔；
        **不要句末标点**；不要把 (Neophron percnopterus) 这类拉丁学名写进中文，
        但可以译出它指的是什么动植物；不要把 pos/地区标签写进释义
  dup   若 g 与 exist 里第 i 条（从 0 数）表达的是**同一个义项**，填 i；否则填 null。
        只在意思真的重合时才填；子义比上位义更具体、地区用法不同，都**不算**重复

只输出 JSON：{"结果": [{"id":…, "zh":"…", "dup":null}, …]}，条数与输入一致。"""


def fetch(con, sample=None, limit=None, seed=7):
    """→ (待送模型的条目, 模板已解决的 {id: (zh, 模板名)}, 统计)"""
    rows = con.execute(
        "SELECT id, word, dict_id, lang, gloss, pos, meta FROM sense_add "
        "WHERE TRIM(COALESCE(zh,''))='' ORDER BY id").fetchall()
    exist = collections.defaultdict(list)
    for did, t in con.execute(
            "SELECT s.word_id, g.text FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
            "WHERE g.lang='zh' ORDER BY s.rank"):
        exist[did].append(t)

    items, done, stat = [], {}, collections.Counter()
    for sid, w, did, lang, g, pos, mj in rows:
        zh, name = tmpl_zh(g)
        if zh:
            done[sid] = (zh, name)
            stat["模板确定性生成"] += 1
            continue
        it = {"id": sid, "w": w, "lang": lang, "g": g}
        if pos:
            it["pos"] = pos
        try:
            m = json.loads(mj) if mj else {}
        except json.JSONDecodeError:
            m = {}
        if m.get("parent"):
            it["parent"] = m["parent"]
            stat["  其中带上位义"] += 1
        # 🔴 限定条数：`toque` 有 30 条已有义项，全喂进去 payload 会爆且没必要
        ex = exist.get(did) or []
        if ex:
            it["exist"] = ex[:12]
            stat["  其中带已有义项（要判重）"] += 1
        items.append(it)
        stat["送模型"] += 1
    if sample:
        random.seed(seed)
        items = random.sample(items, min(sample, len(items)))
    return (items[:limit] if limit else items), done, stat


def chunks(xs, n):
    return [xs[i:i + n] for i in range(0, len(xs), n)]


async def call(cl, which, chunk, env):
    if which == "doubao":
        url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
        key, mdl = env["ARK_API_KEY"].strip(), env["DOUBAO_SEED_2_1_PRO"].strip()
        body = {"model": mdl, "temperature": 0,
                "thinking": {"type": "disabled"},
                "response_format": {"type": "json_object"}}
    else:
        url = "https://api.deepseek.com/chat/completions"
        key = env["DEEPSEEK_API_KEY"].strip()
        mdl = "deepseek-v4-flash" if which == "flash" else "deepseek-v4-pro"
        body = {"model": mdl, "temperature": 0, "stream": False,
                "thinking": {"type": "disabled"},
                "response_format": {"type": "json_object"}}
    body["messages"] = [{"role": "system", "content": SYS},
                        {"role": "user", "content": json.dumps(chunk, ensure_ascii=False)}]
    r = await cl.post(url, headers={"Authorization": "Bearer " + key}, json=body)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
    d = json.loads(r.text)
    return d["choices"][0]["message"]["content"], (d.get("usage") or {})


async def run(items, which, env):
    import httpx
    ck = chunks(items, CHUNK.get(which, 20))
    out, usage, bad = {}, collections.Counter(), []
    t0 = time.time()
    cl = httpx.AsyncClient(timeout=900)
    sem = asyncio.Semaphore(PAR)

    async def go(c):
        async with sem:
            try:
                txt, u = await call(cl, which, c, env)
            except Exception as ex:
                bad.append(f"块失败：{ex}")
                return
            for k, v in (u or {}).items():
                if isinstance(v, int):
                    usage[k] += v
            try:
                d = json.loads(txt)
            except json.JSONDecodeError:
                bad.append("JSON 解析失败")
                return
            # 容错取 key：模型不保证用我们指定的 `结果`（v4-pro 常写 `result`）
            res = next((v for v in d.values() if isinstance(v, list)), [])
            want = {x["id"] for x in c}
            for r in res:                        # 按 id 对，不按位置
                if r.get("id") in want and (r.get("zh") or "").strip():
                    out[r["id"]] = (r["zh"].strip(),
                                    r.get("dup") if isinstance(r.get("dup"), int) else None)
            print(f"\r  {which}: {len(out):,}/{len(items):,}  "
                  f"{usage.get('total_tokens', 0)/1e6:.2f}M tokens  "
                  f"{(time.time()-t0)/60:.1f} 分钟", end="", flush=True)

    await asyncio.gather(*(go(c) for c in ck))
    await cl.aclose()
    print(f"\n  {which} 完成：{len(out):,}/{len(items):,}，"
          f"{usage.get('total_tokens', 0):,} tokens，{time.time()-t0:.0f} 秒")
    # 🔴 项目教训：失败那一栏必须看得见，不能只报个数
    for b in bad[:10]:
        print(f"     🔴 {b}")
    if len(bad) > 10:
        print(f"     …… 另有 {len(bad)-10} 个失败块")
    return out


def load_env():
    env = {}
    if paths.ENV.exists():
        for ln in paths.ENV.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items()
                if k.endswith("_KEY") or k.startswith(("ARK_", "DOUBAO_"))})
    return env


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--model", default="flash", choices=["flash", "v4pro", "doubao", "both"])
    ap.add_argument("--ask", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--chunk", type=int, help="覆盖每块条数；收尾时调到 1 隔离坏条目")
    args = ap.parse_args()
    if args.chunk:
        for k in CHUNK:
            CHUNK[k] = args.chunk

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    items, done, stat = fetch(con, sample=args.sample, limit=args.limit)
    tot = con.execute("SELECT COUNT(*) FROM sense_add").fetchone()[0]
    con.close()
    print(f"`sense_add` 共 {tot:,} 条，待补中文 {tot - 0:,}")
    for k, v in stat.most_common():
        print(f"  {k:<24}{v:>7,}")
    if done:
        dbtool.sample_check([(n, z) for z, n in list(done.values())[:10]],
                            10, ("命中的模板", "生成的中文"))

    if not args.ask:
        print("\n未加 --ask，不发请求。")
        if items:
            print("  送模型的前 3 条 payload：")
            for it in items[:3]:
                print("   ", json.dumps(it, ensure_ascii=False)[:220])
        return

    env = load_env()
    which = ["flash", "doubao"] if args.model == "both" else [args.model]
    got = {}
    for w in which:
        got[w] = asyncio.run(run(items, w, env))

    if args.model == "both":
        a, b = got["flash"], got["doubao"]
        both = set(a) & set(b)
        print(f"\n两家都给出的 {len(both):,} 条，逐条对比抽 12：")
        by = {x["id"]: x for x in items}
        for sid in list(both)[:12]:
            print(f"  {by[sid]['w']:<16}{by[sid]['g'][:38]:<40}"
                  f"flash={a[sid][0][:14]:<16}豆包={b[sid][0][:14]}")
        print("\n⚠️ 两家不同不等于谁错。选哪家由你定，别拿一次抽样当规律。")
        return

    res = got[which[0]]
    src = f"llm-{which[0]}"
    # 🔴 下标 → 原文。`by[sid]["exist"]` 就是喂给模型的那份列表，逐位对上。
    #    越界（模型瞎填）一律当「不重复」，不猜。
    by = {x["id"]: x for x in items}
    rows, oob = [], 0
    for sid, (zh, dup) in res.items():
        ex = by.get(sid, {}).get("exist") or []
        dz = None
        if isinstance(dup, int):
            if 0 <= dup < len(ex):
                dz = ex[dup]
            else:
                oob += 1
        rows.append((zh, src, dz, sid))
    if oob:
        print(f"  ⚠️ dup 下标越界、按「不重复」处理：{oob}")
    rows += [(zh, f"tmpl:{name}", None, sid) for sid, (zh, name) in done.items()]
    print(f"\n可写 {len(rows):,} 条（模板 {len(done):,} + 模型 {len(res):,}）")
    if not args.apply:
        print("未加 --apply，不写库。")
        return

    with dbtool.session(f"translate-sense-gap-{which[0]}", expect={}) as s:
        cols = {r[1] for r in s.execute("PRAGMA table_info(sense_add)")}
        if "dup_zh" not in cols:
            s.execute("ALTER TABLE sense_add ADD COLUMN dup_zh TEXT")
        # 🔴 只填空不覆盖：`WHERE TRIM(COALESCE(zh,''))=''`
        s.executemany(
            "UPDATE sense_add SET zh=?, zh_src=?, dup_zh=? "
            "WHERE id=? AND TRIM(COALESCE(zh,''))=''", rows)

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    n, m = con.execute("SELECT COUNT(*), COUNT(NULLIF(TRIM(COALESCE(zh,'')),'')) "
                       "FROM sense_add").fetchone()
    con.close()
    print(f"\n`sense_add` {n:,} 条，有中文 {m:,}（{m/n*100:.1f}%）")
    print("下一步：python3 -m es.pipeline.build_sense_layer --apply   # 重建出版层")


if __name__ == "__main__":
    main()
