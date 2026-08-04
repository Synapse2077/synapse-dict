#!/usr/bin/env python3
"""西语版新收词译文验收：抽样 → 豆包 pro + v4-pro 并行判 → 我复核。2026-08-03。

═══ 判官纪律（[[llm-as-evaluator-discipline]]，这里逐条落实）═══
⑥ **谁写的不能由谁判**：译文是 flash 写的，判官用豆包 pro 与 v4-pro，两家独立。
⑦ **用前必跑负控**：样本里混入 `NEG` 条 —— 把 A 的译文安到 B 头上。
   判官若逮不住这些，它就量不了 bad 率，这一轮的数字全部作废，别拿去汇报。
   同时混入 `POS` 条已落库的模板译文（`Apellido`→姓氏），判官若把它们判 bad，
   说明判官偏严，读数要往下调。
⑧ **payload 必带权威源真值**：西语版原文一并给（这里它就是真值），
   否则判官只能靠中文自洽性猜，历史上连续四族误报都是这么来的。
② **跨判官的数字不能相减**，两家分开报。
   一致率本身是质量信号：低一致率＝这类判断不可靠，该停手而不是硬做。
判官开思考（推导型任务）。

用法（在 es/ 目录）：
    python3 probes/review_intake_translation.py --build      # 只看抽样，不调模型
    python3 probes/review_intake_translation.py --run
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import asyncio
import collections
import json
import random
import re
import sqlite3
import time

import httpx

import paths

OUT = paths.WORK / "runs" / "intake_translation_review.json"
N = 300          # 真样本
NEG = 24         # 负控：译文张冠李戴
POS = 16         # 正控：已落库的模板译文（确定性、必对）
CHUNK = 34
SEED = 20260803_2

SYS = """你在验收一部**西班牙语→中文**词典的机器译文。用户是中国的西语学习者，
产品是划词弹窗：选中一个西语词 → 弹出中文释义。

对每个词我给你：
  w    西语词
  pos  词性
  es   西语版维基词典的原文释义（这是真值，判断以它为准）。
       ⚠️ 若这一栏写的是「词根 …」「De … con el pronombre …」或「源头无任何释义」，
       说明**源头根本没写释义**，那栏只是词源/构词线索，**不是真值**。
       这种情况请你**凭自己的西班牙语知识**判断中文对不对；
       你自己也不确定这个词是什么意思时，判 ok（别拿"我不认识"当 bad）。
  zh   我们的中文译文（与 es 逐条一一对应）

逐条判断中文译文是不是**忠实且可用**的词典释义。

判 bad 的情形：
  · 意思错了、指错了对象、方向反了（及物/自动、施事/受事弄反）；
  · 漏掉了原文的核心限定，导致义项范围明显偏移；
  · 中文不成词典释义（句子化、解释性废话、把原文照抄回来、空洞如"某种东西"）；
  · 与 es 条目数不符、顺序错位。
判 ok 的情形（**别拿这些扣分**）：
  · 措辞与你的首选不同但所指相同；
  · 详略取舍不同（词典释义本来就要压缩）；
  · 学名、地名、专有名词按惯例保留原文；
  · 元描述（"某词的变体/缩写"）照实翻译。

严格输出 JSON，不要解释文字：
{"v":[{"w":"词","bad":[0-based 出问题的义项下标, ...],
       "why":"若 bad 非空，一句话说明错在哪（不超过 30 字）"}]}
没有问题的词，`bad` 给空数组。宁可放过也不要滥判 —— 我要的是 bad 率，不是挑刺。"""


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
        return json.loads(re.sub(r",\s*([}\]])", r"\1", s))


def build(src="llm-flash"):
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if src == "llm-derived":
        # 🔴 这批**没有西语原文**（源头就是 no-gloss）。判官手里没有真值，
        #    只能当第二意见，不能当尺子 —— 真尺子是那个盲测（见 fill_nogloss.py）。
        #    给判官的 es 一栏放证据（词源/词根），并在 prompt 里说明它不是释义。
        import json as _j
        ev = {x["w"]: x for x in _j.loads(
            (paths.WORK / "nogloss_evidence.json").read_text(encoding="utf-8"))}
        rows = [(w, p, "｜".join(
            ([e0.get("ety", "")] if ev.get(w, {}).get("ety") else []) +
            ["词根 %s=%s" % (r["w"], r["zh"]) for r in (ev.get(w, {}).get("root") or [])]
        ) or "（源头无任何释义，仅凭词形与西语知识推断）", t)
            for w, p, t in conn.execute(
                "SELECT word, pos, translation FROM dict WHERE translation_src=?",
                (src,))
            for e0 in [ev.get(w, {})]]
        tmpl = conn.execute(
            "SELECT word, pos, definition_es, translation FROM dict "
            "WHERE translation_src='template-es-edition'").fetchall()
        conn.close()
        return _mix(rows, tmpl)
    rows = conn.execute(
        "SELECT word, pos, definition_es, translation FROM dict "
        "WHERE translation_src='llm-flash' "
        "AND TRIM(COALESCE(definition_es,''))<>''").fetchall()
    tmpl = conn.execute(
        "SELECT word, pos, definition_es, translation FROM dict "
        "WHERE translation_src='template-es-edition'").fetchall()
    conn.close()
    return _mix(rows, tmpl)


def _mix(rows, tmpl):
    rnd = random.Random(SEED)
    pick = rnd.sample(rows, min(N + NEG, len(rows)))
    real, negsrc = pick[:N], pick[N:]

    items, truth = [], {}
    for w, pos, d, t in real:
        items.append({"w": w, "pos": pos, "es": d.split("\n"), "zh": t.split("\n")})
        truth[w] = "real"
    # 负控：把译文换成**另一条同样长度**的译文 —— 长度一致才逼判官看内容而不是数条数
    bylen = collections.defaultdict(list)
    for w, pos, d, t in rows:
        bylen[len(t.split("\n"))].append(t)
    for w, pos, d, t in negsrc:
        n = len(d.split("\n"))
        cand = [x for x in bylen.get(n, []) if x != t]
        if not cand:
            continue
        items.append({"w": w, "pos": pos, "es": d.split("\n"),
                      "zh": rnd.choice(cand).split("\n")})
        truth[w] = "neg"
    for w, pos, d, t in rnd.sample(tmpl, min(POS, len(tmpl))):
        if w in truth:
            continue
        items.append({"w": w, "pos": pos, "es": d.split("\n"), "zh": t.split("\n")})
        truth[w] = "pos"
    rnd.shuffle(items)
    return items, truth


async def ask_v4pro(key, p):
    async with httpx.AsyncClient(timeout=1800) as cl:
        r = await cl.post("https://api.deepseek.com/chat/completions",
                          headers={"Authorization": "Bearer " + key},
                          json={"model": "deepseek-v4-pro",
                                "messages": [{"role": "system", "content": SYS},
                                             {"role": "user", "content": p}],
                                "temperature": 0,
                                "response_format": {"type": "json_object"},
                                "thinking": {"type": "enabled"}, "stream": False})
        if r.status_code != 200:
            raise RuntimeError("HTTP %s: %s" % (r.status_code, r.text[:200]))
        return json.loads(r.text.lstrip())["choices"][0]["message"]["content"]


async def ask_doubao(env, p):
    from volcenginesdkarkruntime import AsyncArk
    cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
    r = await cl.chat.completions.create(
        model=env["DOUBAO_SEED_2_1_PRO"], temperature=0,
        thinking={"type": "enabled"},
        messages=[{"role": "system", "content": SYS}, {"role": "user", "content": p}])
    return r.choices[0].message.content


def collect(raws):
    out = {}
    for raw in raws:
        if isinstance(raw, Exception) or not raw:
            continue
        try:
            d = loads_lenient(raw)
        except Exception:
            continue
        for v in d.get("v") or []:
            if v.get("w"):
                out[v["w"]] = (v.get("bad") or [], v.get("why", ""))
    return out


def score(name, verd, items, truth):
    st = collections.Counter()
    bad_items = []
    for it in items:
        w = it["w"]
        kind = truth[w]
        b = verd.get(w)
        if b is None:
            st[kind + ":无判"] += 1
            continue
        isbad = bool(b[0])
        st[kind + (":bad" if isbad else ":ok")] += 1
        if isbad and kind == "real":
            bad_items.append((w, it["es"], it["zh"], b[0], b[1]))
    nr = st["real:bad"] + st["real:ok"]
    ng = st["neg:bad"] + st["neg:ok"]
    npz = st["pos:bad"] + st["pos:ok"]
    print("\n" + "=" * 74)
    print("■ %s" % name)
    print("   负控（张冠李戴，应判 bad）逮住 {}/{} = {:.0f}%   ← 低于 80% 这一轮读数作废".format(
        st["neg:bad"], ng, st["neg:bad"] * 100 / max(ng, 1)))
    print("   正控（模板译文，应判 ok）误判 {}/{} = {:.0f}%   ← 越高说明判官越严".format(
        st["pos:bad"], npz, st["pos:bad"] * 100 / max(npz, 1)))
    print("   ▸ 真样本 bad 率 {}/{} = {:.1f}%".format(
        st["real:bad"], nr, st["real:bad"] * 100 / max(nr, 1)))
    if st["real:无判"] or st["neg:无判"]:
        print("   （无判 real {} / neg {}）".format(st["real:无判"], st["neg:无判"]))
    return st, bad_items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--nogloss", action="store_true",
                    help="验收 llm-derived 那批（源头无释义、模型凭西语知识推的）")
    a = ap.parse_args()

    items, truth = build("llm-derived" if a.nogloss else "llm-flash")
    print("■ 抽样 {:,} 条：真样本 {} / 负控 {} / 正控 {}".format(
        len(items), sum(1 for v in truth.values() if v == "real"),
        sum(1 for v in truth.values() if v == "neg"),
        sum(1 for v in truth.values() if v == "pos")))
    if not a.run:
        for it in items[:6]:
            print("   %-16s %s\n        → %s" % (
                it["w"], " | ".join(it["es"])[:70], " | ".join(it["zh"])[:52]))
        return

    payload = [{k: v for k, v in it.items()} for it in items]
    chunks = [payload[i:i + CHUNK] for i in range(0, len(payload), CHUNK)]
    env = load_env()
    t0 = time.time()

    async def go():
        tasks = []
        for c in chunks:
            p = json.dumps(c, ensure_ascii=False)
            tasks.append(ask_v4pro(env["DEEPSEEK_API_KEY"], p))
            tasks.append(ask_doubao(env, p))
        return await asyncio.gather(*tasks, return_exceptions=True)

    res = asyncio.run(go())
    print("■ {} 个请求并行跑完 {:.0f}s".format(len(res), time.time() - t0))
    for r in res:
        if isinstance(r, Exception):
            print("   🔴 一块失败：%s" % r)
    v4 = collect(res[0::2])
    dou = collect(res[1::2])
    s1, bad1 = score("v4-pro", v4, items, truth)
    s2, bad2 = score("豆包 pro", dou, items, truth)

    real = [it["w"] for it in items if truth[it["w"]] == "real"]
    agree = sum(1 for w in real
                if bool(v4.get(w, ([], ""))[0]) == bool(dou.get(w, ([], ""))[0]))
    both = [w for w in real
            if v4.get(w, ([], ""))[0] and dou.get(w, ([], ""))[0]]
    print("\n■ 两家在真样本上一致 {}/{} = {:.0f}%；**都判 bad** {} 条 = {:.1f}%".format(
        agree, len(real), agree * 100 / max(len(real), 1),
        len(both), len(both) * 100 / max(len(real), 1)))
    print("   （两家都判 bad 是最可信的一档，我按这一档逐条复核）")

    byw = {it["w"]: it for it in items}
    print("\n■ 两家都判 bad 的，逐条列出供人眼复核")
    for w in both[:40]:
        it = byw[w]
        print("   %-18s %s" % (w, " | ".join(it["es"])[:66]))
        print("        我们: %s" % " | ".join(it["zh"])[:60])
        print("        v4  : %s" % v4[w][1][:50])
        print("        豆包: %s" % dou[w][1][:50])

    OUT.write_text(json.dumps(
        {"items": items, "truth": truth, "v4pro": v4, "doubao": dou,
         "ts": time.strftime("%Y-%m-%d %H:%M")}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print("\n→ %s" % OUT)


if __name__ == "__main__":
    main()
