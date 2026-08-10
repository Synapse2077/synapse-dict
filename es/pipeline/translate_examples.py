#!/usr/bin/env python3
"""翻译例句，落进 `example_gloss`。2026-08-07。

三处「目标语言出口」的最后一处（`sense_gloss` ✅ / `collocation_gloss` ✅ / 本文件）。
`example` 表 50,766 条西语原句，**中文一条都没有**。

═══ 喂什么给模型 ═══
· `s` 西语原句
· `w` 该例句所属的词
· `sense` **该例句挂在哪条义项下的中文标题** ⇒ 消歧的关键。
  `ojo` 的例句可能属于「眼睛」也可能属于「钥匙孔」，不给义项就只能靠模型猜。
  2026-08-07 已把 40,113 条（79.0%）确定性挂到义项上，正好喂进来。
· `kw` 关键词在句中的位置（`example.bold`），告诉模型这句在演示哪个词

🔴 **`ref`（出处）不喂也不译**：它是书目信息（`Anónimo. Libro de los fueros…`），
   翻译它既没用又费 token。

═══ 排除 477 条不是句子的 ═══
`example` 里混着数学式、URL、单个单词：

    ①太短 <12 字符          436   `Esto es.` / `Símbolo: ☿.`
    ②无空格（单词非句子）      17   `astigmatismo.` / `http://es.wiktionary.com/…`
    ③拉丁字母占比 <50%        24   `3 2+i\\.2-i 1`（矩阵）
    合计 477（0.94%）

⚠️ **不排除「短且无句末标点」那 1,935 条**：`El ojo del martillo`（锤眼）
   是名词短语例句，有用。第一版判据把它们也筛掉了，是过度收紧。

═══ 模型 ═══
默认 flash。**例句翻译与短标签生成是两类任务**：后者是「压缩成词典体例」的编纂判断，
flash 在那里输在中英混排与成语倒装；前者是整句翻译，是生成不是推导，
`flash` 已在西语义项上验过 13.9 万条。⇒ 但仍先同批对比再定（`--model both`）。

═══ 落点与幂等 ═══
`example_gloss(example_id, lang='zh', text, src='llm-<模型>')`，
**只填空不覆盖**（[[replay-scripts-undo-fixes]]）：已有 zh 的例句一律不碰。

用法（在仓库根）：
    python3 -m es.pipeline.translate_examples --sample 200 --model both --ask
    python3 -m es.pipeline.translate_examples --all --model flash --ask --apply
"""
import argparse
import asyncio
import collections
import json
import random
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

RAW = paths.WORK / "example_zh_llm.jsonl"
CHUNK = {"flash": 25, "v4pro": 30, "doubao": 30}
PAR = 12
LAT = re.compile(r"[a-záéíóúüñ]", re.I)

SYS = """你是西班牙语→简体中文的译者，正在给一部西汉词典翻译例句。

输入每条含：id / w 该例句演示的词 / sense 这条例句所属义项的中文释义 / s 西语原句

翻译规则：
 · **忠实、自然的现代汉语**。不是逐词直译，是这句话用中文会怎么说。
 · 🔴 **必须体现 `sense` 那个意思**。同一个词在不同义项下译法不同：
     w=ojo  sense=眼睛    「Dora tiene ojos azules.」→「多拉有一双蓝眼睛。」
     w=ojo  sense=钥匙孔  「Miró por el ojo de la cerradura.」→「他从锁眼往里看。」
   若原句与 sense 明显对不上，以**原句**为准照实翻，不要硬套。
 · 句末标点跟随原句：原句有句号就有句号，是名词短语（`El ojo del martillo`）就不加。
 · 原句里的人名、地名、书名照常音译或沿用通行译名，不要留西语原文。
 · 🔴 古西语和方言照常翻（例句里有 13 世纪法典原文），不要输出「无法翻译」之类的话。
 · 不加译注、不加括号解释、不要重复原句。

只输出 JSON：{"结果":[{"id":例句id,"zh":"…"},…]}，条数与输入完全相等。"""


def fetch(con, limit=None, sample=None, seed=11):
    rows = con.execute("""
        SELECT e.id, e.word, e.text, g.text AS sense
        FROM example e
        LEFT JOIN sense s ON s.id = e.sense_id
        LEFT JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='zh' AND g.seq=0
        WHERE NOT EXISTS (SELECT 1 FROM example_gloss x
                          WHERE x.example_id = e.id AND x.lang='zh')
        GROUP BY e.id
        ORDER BY e.id""").fetchall()
    out, skip = [], collections.Counter()
    for eid, w, txt, sense in rows:
        t = (txt or "").strip()
        if len(t) < 12:
            skip["①太短（<12 字符）"] += 1
            continue
        if not re.search(r"\s", t):
            skip["②无空格（单词非句子）"] += 1
            continue
        if len(LAT.findall(t)) / max(len(t), 1) < 0.5:
            skip["③拉丁字母占比 <50%（公式）"] += 1
            continue
        it = {"id": eid, "w": w, "s": t}
        if sense:
            it["sense"] = sense[:40]
        out.append(it)
    if sample:
        random.seed(seed)
        out = random.sample(out, min(sample, len(out)))
    return (out[:limit] if limit else out), skip


def chunks(items, n):
    return [items[i:i + n] for i in range(0, len(items), n)]


async def call_deepseek(cl, key, chunk, model):
    r = await cl.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": "Bearer " + key},
        json={"model": model,
              "messages": [{"role": "system", "content": SYS},
                           {"role": "user", "content": json.dumps(chunk, ensure_ascii=False)}],
              "temperature": 0, "response_format": {"type": "json_object"},
              "thinking": {"type": "disabled"}, "stream": False})
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
    d = json.loads(r.text)
    return d["choices"][0]["message"]["content"], (d.get("usage") or {})


async def run(items, which, env):
    import httpx
    ck = chunks(items, CHUNK.get(which, 30))
    out, usage = {}, collections.Counter()
    t0 = time.time()
    cl = httpx.AsyncClient(timeout=900)
    key = env["DEEPSEEK_API_KEY"].strip()
    mdl = "deepseek-v4-flash" if which == "flash" else "deepseek-v4-pro"
    sem = asyncio.Semaphore(PAR)
    done = [0]

    async def go(c):
        async with sem:
            try:
                txt, u = await call_deepseek(cl, key, c, mdl)
            except Exception as ex:
                print(f"\n  🔴 块失败：{ex}")
                return
            for k, v in (u or {}).items():
                if isinstance(v, int):
                    usage[k] += v
            try:
                d = json.loads(txt)
            except json.JSONDecodeError:
                print("\n  🔴 JSON 解析失败")
                return
            # 容错取 key：模型不保证用我们指定的 `结果`（v4-pro 常写 `result`）
            res = next((v for v in d.values() if isinstance(v, list)), [])
            if len(res) != len(c):
                print(f"\n  🔴 条数不符 {len(res)} vs {len(c)}")
                return
            want = {x["id"] for x in c}
            for r in res:                        # 按 id 对，不按位置
                if r.get("id") in want and (r.get("zh") or "").strip():
                    out[r["id"]] = r["zh"].strip()
            done[0] += len(c)
            print(f"\r  {which}: {len(out):,}/{len(items):,}  "
                  f"{usage.get('total_tokens', 0)/1e6:.2f}M tokens  "
                  f"{(time.time()-t0)/60:.1f} 分钟", end="", flush=True)

    await asyncio.gather(*(go(c) for c in ck))
    await cl.aclose()
    print(f"\n  {which} 完成：{len(out):,}/{len(items):,}，"
          f"{usage.get('total_tokens', 0):,} tokens，{time.time()-t0:.0f} 秒")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--model", default="flash", choices=["flash", "v4pro", "both"])
    ap.add_argument("--ask", action="store_true")
    ap.add_argument("--apply", action="store_true")
    # 🔴 一个坏条目会拖垮整块（25 条一块，1 条出问题 25 条全丢）。
    #    重跑三次后稳定卡在 125 条 ⇒ 把块调小，让失败**隔离**到单条。
    ap.add_argument("--chunk", type=int, help="覆盖每块条数；收尾时调到 1 隔离坏条目")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    items, skip = fetch(con, limit=args.limit, sample=args.sample)
    tot = con.execute("SELECT COUNT(*) FROM example").fetchone()[0]
    con.close()
    print(f"例句 {tot:,} 条")
    for k, v in skip.most_common():
        print(f"  排除 {k:<24}{v:>6,}")
    print(f"  待翻 {len(items):,}")
    with_sense = sum(1 for it in items if "sense" in it)
    print(f"    其中带义项标题（消歧）{with_sense:,}  {with_sense/max(len(items),1)*100:.1f}%")

    if not args.ask:
        for it in items[:4]:
            print(f"\n  [{it['id']}] {it['w']}  义项={it.get('sense','—')}")
            print(f"      {it['s'][:80]}")
        print("\n未加 --ask，不发请求。")
        return

    env = dict(l.split("=", 1) for l in paths.ENV.read_text().splitlines()
               if "=" in l and not l.startswith("#"))
    if args.chunk:
        for k in CHUNK:
            CHUNK[k] = args.chunk
    which = ["flash", "v4pro"] if args.model == "both" else [args.model]
    res = {w: asyncio.run(run(items, w, env)) for w in which}

    if len(which) > 1:
        print("\n" + "=" * 100)
        for it in items[:24]:
            print(f"\n  {it['w']} 〔{it.get('sense','—')}〕 {it['s'][:66]}")
            for w in which:
                print(f"      {w:<7}{res[w].get(it['id'], '—')[:60]}")

    RAW.parent.mkdir(parents=True, exist_ok=True)
    with RAW.open("a", encoding="utf-8") as f:
        for w in which:
            for eid, zh in res[w].items():
                f.write(json.dumps({"model": w, "id": eid, "zh": zh},
                                   ensure_ascii=False) + "\n")
    print(f"\n已追加 → {RAW}")

    if not args.apply:
        print("未加 --apply，不写库。")
        return
    if len(which) != 1:
        sys.exit("--apply 时只能指定一个模型")
    plan = [(eid, "zh", zh, f"llm-{which[0]}") for eid, zh in res[which[0]].items()]
    with dbtool.session("translate-examples", expect={}) as s:
        s.executemany(
            "INSERT OR IGNORE INTO example_gloss (example_id,lang,text,src) "
            "VALUES (?,?,?,?)", plan)
    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    n = con.execute("SELECT COUNT(*) FROM example_gloss WHERE lang='zh'").fetchone()[0]
    con.close()
    print(f"落库 {len(plan):,} 条；example_gloss 现有中文 {n:,}/{tot:,}")


if __name__ == "__main__":
    main()
