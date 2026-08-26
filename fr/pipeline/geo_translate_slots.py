#!/usr/bin/env python3
"""把地名模板的**槽值**翻成中文（只翻一次，全库复用）。2026-08-22。

═══ 这一步在做什么 ═══
`pipeline/geo_patterns.py` 那 30 条手写模式把 84,632 条地名释义拆成
「中文句式 + 槽位」。句式的中文我手写了；**槽值的中文靠这一步**。

    Commune française, située dans le département de la Somme.
        模式 → "法国{}省市镇"   槽值 R="Somme"
        本步 → Somme = 索姆       ⇒ "法国索姆省市镇"

**2,278 个槽值 → 77,959 条中文，34 倍压缩。**

═══ 为什么门槛取 n≥2 ═══
    ≥1  4,550 个槽值 → 80,224 条（94.8%）
    ≥2  2,278 个槽值 → 77,959 条（92.1%）   ← 取这个
    ≥3  1,571 个槽值 → 76,555 条（90.5%）
从 ≥2 放宽到 ≥1 要多翻 2,272 个只多渲染 2,265 条 —— **1:1，压缩比塌了**，
而多出来那批正是正则吞了从句的脏值（`Saône-et-Loire, créée en tant que commune
nouvelle le 1ᵉʳ janvier 2017 par regroupement…`，全是 n=1）。
⇒ 门槛不是拍的，是**压缩比崩掉的那个点**。

═══ 🔴 必须带代表性原句 ═══
法国的省名有 `Somme`（索姆）、`Aisne`（埃纳）、`Nord`（诺尔）、`Manche`（芒什）——
**单独送过去会被翻成「总和」「北方」「海峡」**。所以每个槽值都附一条它真实出现过的
法语原句。`[[context-you-give-leaks-into-output]]` 的另一面：上下文会漏进输出，
所以 prompt 里明确写「原句只用来判断这是什么地方，**不要把原句的内容写进答案**」。

═══ 三道防护（承 `[[control-must-cover-every-output-field]]` 的教训）═══
① **逐条核对**：请求里每个 `fr` 都必须在应答里出现 —— flash 会**静默丢批里的一部分**
   （it 阶段 5 实测日志失败 0、实际 2,069 条从没被答过）。缺的自动重排队。
② **答案按法语原串存**，不按下标 —— `[[model-answer-files-key-by-id]]`。
③ **先跑 `--slice`，我逐条读了再跑全量**。

用法（在 fr/ 目录下）：
    python3 pipeline/geo_translate_slots.py --slice 60    # 小样，落盘并打印供人读
    python3 pipeline/geo_translate_slots.py               # 全量续跑
    python3 pipeline/geo_translate_slots.py --stats
"""
import argparse
import asyncio
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths                                     # noqa: E402
from pipeline.geo_patterns import match, dirty   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
WORK = paths.WORK / "geo"
OUT = WORK / "slot_zh.jsonl"

MIN_N = 2           # 槽值出现次数门槛，见 docstring
CHUNK = 40
CONC = 8
MODEL = "deepseek-v4-flash"
URL = "https://api.deepseek.com/chat/completions"

FAM = re.compile(r"^(Commune|Ville|Village|Municipalité|Hameau|Localité|Bourg|Quartier)\b", re.I)

SYS = """你在给一部**法汉词典**做地名译名。输入是一批**从法语维基词典的地名释义里抽出来的
地名成分**（法语），每项给：
  `fr`   —— 地名成分本身（省/州/大区/市镇/村的名字）
  `ctx`  —— 它真实出现过的一条法语原句，**只用来让你判断这是哪个国家的什么级别的地方**

规则：
1. 输出**该地名的中文译名本身**，不要任何解释、不要国名前缀、不要行政区通名。
   `Somme`（原句是法国某省）→ `索姆`，**不是**「索姆省」也不是「法国索姆省」。
   `Bavière` → `巴伐利亚`。`Castille-et-León` → `卡斯蒂利亚-莱昂`。
2. 🔴 **有约定俗成的中文译名就用约定译名**，不要自己另音译。
   `Bavière`=巴伐利亚（不是「巴维埃」）、`Gênes`=热那亚、`Majorque`=马略卡、
   `Cologne`=科隆、`Munich`=慕尼黑、`Aix-la-Chapelle`=亚琛、`Anvers`=安特卫普。
   ⚠️ 法语对外国地名有自己的叫法，**中文要照该地本国的通行译名**，不要照法语拼读。
3. 没有约定译名的（多数小市镇/村），按**该地所在国语言**的读音音译，用《世界地名翻译
   大辞典》的常规用字。法国地名照法语读音，德国地名照德语读音，西班牙地名照西班牙语读音。
4. 🔴 `ctx` 只是判断依据，**不要把 ctx 里的任何内容写进答案**。答案里不许出现
   「市镇」「省」「州」「位于」「法国」这类词。
5. 复合地名保留连字符：`Rhénanie-Palatinat` → `莱茵兰-普法尔茨`。
6. 🔴 拿不准就输出空字符串 ""，**不要猜**。宁可缺不可错。

输入是 JSON 数组。输出**只有** JSON 数组，每项 {"fr": 原样回传, "zh": "译名"}，
不要围栏、不要解释。**每一条输入都要有对应输出，一条都不能少。**"""


def env():
    return dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines()
                if "=" in l and not l.startswith("#"))


def collect():
    """→ [{fr, kind, n, ctx}]，按出现次数降序。ctx 取**最短**的那条原句（噪声最少）。"""
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = [" ".join(t.split()) for (t,) in con.execute("""
        SELECT g.text FROM sense s
        JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='fr'
        LEFT JOIN sense_gloss z ON z.sense_id = s.id AND z.lang='zh'
        WHERE z.sense_id IS NULL""")]
    n = Counter()
    ctx = {}
    for t in rows:
        if not FAM.match(t):
            continue
        r = match(t)
        if not r:
            continue
        for kind, val in r[1]:
            if kind == "TYPE":          # 通名是闭集，由 TYPE_ZH 解决，不送模型
                continue
            v = val.strip()
            if dirty(v):                # 吞了从句的槽值：**根本不送翻译**，见 geo_patterns.dirty
                continue
            n[(kind, v)] += 1
            if v not in ctx or len(t) < len(ctx[v]):
                ctx[v] = t
    return [{"fr": v, "kind": k, "n": c, "ctx": ctx[v]}
            for (k, v), c in n.most_common() if c >= MIN_N]


def done_keys():
    if not OUT.exists():
        return {}
    got = {}
    for ln in OUT.open(encoding="utf-8"):
        try:
            o = json.loads(ln)
        except Exception:
            continue                    # 末行截断等坏行跳过
        got[o["fr"]] = o
    return got


async def ask(cl, key, items):
    body = {"model": MODEL, "temperature": 0, "stream": False,
            "messages": [{"role": "system", "content": SYS},
                         {"role": "user", "content": json.dumps(
                             [{"fr": i["fr"], "ctx": i["ctx"]} for i in items],
                             ensure_ascii=False)}]}
    r = await cl.post(URL, headers={"Authorization": "Bearer " + key},
                      json=body, timeout=300)
    if r.status_code != 200:
        raise RuntimeError("HTTP %s: %s" % (r.status_code, r.text[:200]))
    d = r.json()
    txt = d["choices"][0]["message"]["content"].strip()
    txt = re.sub(r"^```(?:json)?|```$", "", txt, flags=re.M).strip()
    out = {}
    for o in json.loads(txt):
        if isinstance(o, dict) and "fr" in o:
            out[str(o["fr"])] = str(o.get("zh") or "")
    return out, (d.get("usage") or {}).get("total_tokens", 0)


async def run(todo, key):
    import httpx
    chunks = [todo[i:i + CHUNK] for i in range(0, len(todo), CHUNK)]
    q = asyncio.Queue()
    for c in chunks:
        q.put_nowait(c)
    stat = {"done": 0, "tok": 0, "miss": 0}
    lock = asyncio.Lock()
    fout = OUT.open("a", encoding="utf-8")

    async with httpx.AsyncClient() as cl:
        async def worker():
            while True:
                try:
                    ch = q.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    got, tok = await ask(cl, key, ch)
                except Exception as e:
                    print("  ✗ 批失败（%d 条）：%s" % (len(ch), str(e)[:120]))
                    q.task_done()
                    continue
                # 🔴 ① 逐条核对：flash 会静默丢批里的一部分
                miss = [i for i in ch if i["fr"] not in got]
                if miss:
                    stat["miss"] += len(miss)
                    if len(ch) > 1:
                        q.put_nowait(miss)          # 重排队，不静默丢
                async with lock:
                    for i in ch:
                        if i["fr"] in got:
                            fout.write(json.dumps(
                                {"fr": i["fr"], "kind": i["kind"], "n": i["n"],
                                 "zh": got[i["fr"]]}, ensure_ascii=False) + "\n")
                    fout.flush()
                stat["done"] += 1
                stat["tok"] += tok
                if stat["done"] % 5 == 0:
                    print("  [%d/%d] token %s  待补 %d"
                          % (stat["done"], len(chunks), f"{stat['tok']:,}", stat["miss"]))
                q.task_done()

        await asyncio.gather(*[asyncio.create_task(worker())
                               for _ in range(min(CONC, len(chunks)))])
    fout.close()
    return stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=int, default=0, help="只跑前 N 个（按出现次数降序）并打印")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()

    WORK.mkdir(parents=True, exist_ok=True)
    all_slots = collect()
    got = done_keys()
    print("■ 槽值（n≥%d）%s 个；已翻 %s；待翻 %s"
          % (MIN_N, f"{len(all_slots):,}", f"{len(got):,}",
             f"{len([s for s in all_slots if s['fr'] not in got]):,}"))
    if a.stats:
        blank = [k for k, v in got.items() if not v["zh"]]
        print("   其中模型主动留空 %s 个（这些退回模型走整句翻译）" % f"{len(blank):,}")
        return 0

    todo = [s for s in all_slots if s["fr"] not in got]
    if a.slice:
        todo = todo[:a.slice]
    if not todo:
        print("✓ 无待翻")
        return 0

    key = env()["DEEPSEEK_API_KEY"].strip()
    stat = asyncio.run(run(todo, key))
    print("\n✓ 完成 %d 批 / token %s / 曾缺 %d 条（已重排队）"
          % (stat["done"], f"{stat['tok']:,}", stat["miss"]))

    if a.slice:
        got = done_keys()
        print("\n%-34s %-14s %s" % ("法语槽值", "中文", "代表原句"))
        print("-" * 110)
        for s in todo:
            o = got.get(s["fr"])
            print("%-34s %-14s %s"
                  % (s["fr"][:34], (o["zh"] if o else "—")[:14], s["ctx"][:56]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
