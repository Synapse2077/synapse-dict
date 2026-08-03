#!/usr/bin/env python3
"""义项缺口逐条裁决：核心层 154 条（A1/A2/B1）。豆包 pro + v4-pro 并行。2026-08-02。

═══ 这里模型的角色是**工具**不是真值 ═══
"这个中文释义是不是我们完全没覆盖的独立义项"是语义题，确定性做不了，只能问模型。
但纪律仍然生效：
  · 两家**独立**跑，**一致率当质量信号** —— 上一轮逐样本一致率只有 72%，
    若这次也低，说明这类判断本身不可靠，该停手而不是硬做；
  · payload 带**权威源真值**（英文版的完整 gloss 列表），否则模型不知道我们"已经有什么"，
    会把我们已覆盖的义项误报成缺口（纪律⑧，这个坑踩过四次）；
  · 判完的结果**先不落库**，抽样回核之后再说。

═══ 判据（双家评审后我定的，写死在 prompt 里）═══
补 = 现有义项**完全未覆盖该独立所指**；
不补 = 近义改述 / 同一义项的场景细化 / 元描述与语法说明 / 词源百科 /
       极狭窄方言古语 / 只存在于固定搭配中的义。

用法（在 es/ 目录）：
    python3 probes/adjudicate_sense_gaps.py --build
    python3 probes/adjudicate_sense_gaps.py --run
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import asyncio
import collections
import json
import re
import sqlite3
import time

import httpx

import paths

SRC = paths.WORK / "runs" / "zh_translation_divergence.jsonl"
OUT = paths.WORK / "runs" / "sense_gap_verdicts.json"
CHUNK = 40

SYS = """你在为一部**西班牙语→中文**学习词典做义项缺口裁决。用户是中国的西语学习者，
产品是划词弹窗。词典的义项集合来自**英文版维基词典**并逐条译成中文；
现在拿**中文版维基词典**（独立人工源）比对，找出可能漏掉的义项。

对每个词，我给你：
  ours_zh  —— 我们现有的中文释义（逐义项）
  ours_en  —— 这些义项对应的英文版原始 gloss（**权威源真值，判断"我们已经有什么"以此为准**）
  zh_wiki  —— 中文版维基给出的释义

对 zh_wiki 里的**每一条**判断它是不是我们完全没有的独立义项。

判「补」的条件（必须同时满足）：
  · 它表达的是一个**独立所指**，ours_zh/ours_en 里没有任何一条覆盖它；
  · 它是该词在通用语料里的常用义或核心义。

判「不补」的情形：
  · 与现有义项**所指相同**，只是译法、语体、表述角度不同（近义改述）；
  · 同一义项的场景细化、举例；
  · 元描述与语法说明（"XX的过去分词""XX的短尾形式""源自德语的姓氏"）；
  · 词源、百科属性说明；
  · 极狭窄的方言/古语/小众专科义；
  · 只存在于固定搭配中、单词独立使用时没有的义。

严格输出 JSON，不要任何解释文字：
{"verdicts":[
  {"word":"词","import":["确实该补的中文释义原文", ...],
   "skip_reason":"若 import 为空，一句话说明为什么全都不补",
   "confidence":"high|medium|low"}
]}
`import` 里放**中文版原文**（可去掉 "m."/"f."/"vi." 这类词性前缀），没有该补的就给空数组。
宁可漏补也不要滥补 —— 错的义项比缺的义项更伤词典。"""


def build():
    recs = [json.loads(l) for l in open(SRC, encoding="utf-8")]
    core = [r for r in recs if r["level"] in ("A1", "A2", "B1")]
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    en = dict(conn.execute(
        "SELECT word, definition FROM dict WHERE is_lemma=1 "
        "AND TRIM(COALESCE(definition,''))<>''"))
    conn.close()
    out = []
    for r in core:
        out.append({
            "word": r["word"], "CEFR": r["level"], "pos": r["pos"],
            "ours_zh": (r["ours"] or "").split("\n"),
            "ours_en": (en.get(r["word"]) or "").split("\n"),
            "zh_wiki": r["zh"],
        })
    return out


def load_env():
    env = {}
    for ln in open(paths.ENV, encoding="utf-8"):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.strip().split("=", 1)
            env[k] = v
    return env


def loads_lenient(s):
    s = re.sub(r"^```(json)?|```$", "", s.strip(), flags=re.M).strip()
    if "{" in s:
        s = s[s.find("{"):s.rfind("}") + 1]
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        f = re.sub(r"}\s*\n\s*(\{)", r"},\n\1", s)
        return json.loads(re.sub(r",\s*([}\]])", r"\1", f))


async def ask_v4pro(key, payload):
    async with httpx.AsyncClient(timeout=1800) as cl:
        r = await cl.post("https://api.deepseek.com/chat/completions",
                          headers={"Authorization": "Bearer " + key},
                          json={"model": "deepseek-v4-pro",
                                "messages": [{"role": "system", "content": SYS},
                                             {"role": "user", "content": payload}],
                                "temperature": 0,
                                "response_format": {"type": "json_object"},
                                "thinking": {"type": "enabled"}, "stream": False})
        if r.status_code != 200:
            raise RuntimeError("HTTP %s: %s" % (r.status_code, r.text[:200]))
        d = json.loads(r.text.lstrip())
        return d["choices"][0]["message"]["content"]


async def ask_doubao(env, payload):
    from volcenginesdkarkruntime import AsyncArk
    cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
    r = await cl.chat.completions.create(
        model=env["DOUBAO_SEED_2_1_PRO"], temperature=0,
        thinking={"type": "enabled"},
        messages=[{"role": "system", "content": SYS},
                  {"role": "user", "content": payload}])
    return r.choices[0].message.content


def collect(raws):
    """多块结果合并 → {word: (import列表, confidence)}"""
    out = {}
    for raw in raws:
        if isinstance(raw, Exception) or not raw:
            continue
        try:
            d = loads_lenient(raw)
        except Exception:
            continue
        for v in d.get("verdicts") or []:
            if v.get("word"):
                out[v["word"]] = (v.get("import") or [], v.get("confidence", "?"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()

    items = build()
    chunks = [items[i:i + CHUNK] for i in range(0, len(items), CHUNK)]
    print("■ 核心层 %d 条（%s），切成 %d 块" % (
        len(items),
        dict(collections.Counter(x["CEFR"] for x in items)), len(chunks)))
    if not a.run:
        print(json.dumps(items[:3], ensure_ascii=False, indent=1))
        return

    env = load_env()
    t0 = time.time()

    async def go():
        tasks = []
        for c in chunks:
            p = json.dumps(c, ensure_ascii=False, indent=1)
            tasks.append(ask_v4pro(env["DEEPSEEK_API_KEY"], p))
            tasks.append(ask_doubao(env, p))
        return await asyncio.gather(*tasks, return_exceptions=True)

    res = asyncio.run(go())
    print("■ %d 个请求并行跑完 %.0fs" % (len(res), time.time() - t0))
    v4 = collect(res[0::2])
    dou = collect(res[1::2])
    for name, d in (("v4pro", v4), ("doubao", dou)):
        n_imp = sum(1 for k in d if d[k][0])
        print("  %-8s 收到 %d 词，判需补 %d" % (name, len(d), n_imp))

    agree = both_imp = only_v4 = only_dou = neither = 0
    rows = []
    for it in items:
        w = it["word"]
        a1 = bool(v4.get(w, ([], ""))[0])
        a2 = bool(dou.get(w, ([], ""))[0])
        if a1 == a2:
            agree += 1
        if a1 and a2:
            both_imp += 1
            rows.append((it, v4[w][0], dou[w][0]))
        elif a1:
            only_v4 += 1
        elif a2:
            only_dou += 1
        else:
            neither += 1
    n = len(items)
    print("\n■ 两家一致率 %d/%d = %.0f%%" % (agree, n, agree * 100 / n))
    print("    都判需补   %d" % both_imp)
    print("    只有 v4pro %d | 只有豆包 %d | 都判不补 %d" % (only_v4, only_dou, neither))

    print("\n■ 两家都判需补的（这是最可信的一档）")
    for it, i1, i2 in rows[:30]:
        print("   %-14s [%s]" % (it["word"], it["CEFR"]))
        print("      我们  : %s" % " / ".join(it["ours_zh"])[:70])
        print("      v4pro : %s" % i1)
        print("      豆包  : %s" % i2)

    OUT.write_text(json.dumps(
        {"items": items, "v4pro": v4, "doubao": dou,
         "ts": time.strftime("%Y-%m-%d %H:%M")}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print("\n→ %s" % OUT)


if __name__ == "__main__":
    main()
