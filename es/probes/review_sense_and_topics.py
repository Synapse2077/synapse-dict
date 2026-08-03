#!/usr/bin/env python3
"""双家评审：**义项补全规则** + **领域标注(topics)本体归一**。2026-08-02。

豆包 pro + DeepSeek v4-pro，并行、各自独立、都开思考。最终决断权在我。

═══ 为什么这两件够格问 ═══
纪律⑩：能确定性回源比对的**根本别问模型**。音标那条不问（有西语版当尺子，
实测修好 7,805/改坏 0）。这两件不一样 —— **没有任何权威源能裁决**：
  · 「英文版没收 gata 的『母猫』义，我们该不该从中文版补进来」不是事实题，是编纂方针题；
  · 「英文版层级本体 vs 语言版扁平本体，合并后保留哪一级」两边都自洽，无客观答案。
用户 2026-08-02 定的判据：**要不要问取决于我拿不拿得准，不取决于事情大不大。**

═══ 遵守判官纪律 ═══
⑦ 两家并行、都开思考（推导型任务）。
⑧ payload 里写明**本词典的约定 + 用户画像 + 权威源实际给了什么**（不给我的结论）。
⑨ 材料标题不写结论；样本混排，不按"我认为该补/不该补"分组。
⑩ 只问规则与本体，不问逐条事实。

用法（在 es/ 目录）：
    python3 probes/review_sense_and_topics.py --build   # 只看材料，不发
    python3 probes/review_sense_and_topics.py --run
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import asyncio
import collections
import gzip
import json
import random
import re
import sqlite3
import time

import httpx

import paths

OUT = paths.WORK / "runs" / "sense_topics_review.json"
DIV = paths.WORK / "runs" / "zh_translation_divergence.jsonl"

RULE_DOC = """【这部词典是什么】
· 西班牙语→中文，767,293 行（lemma 105,267 + 变形层 662,026），面向**中国的西语学习者**，
  产品形态是划词弹窗（选中单词，弹出释义+音标+语法信息）。
· 释义链路：**英文版维基词典**给出义项集合与英文 gloss → 大模型逐义项译成中文。
  中文译文 767,293 行全部出自这条链路，**从未被独立人工源核过**。
· 每个 lemma 有一个逐义项的 `meta` 数组，与释义行一一对齐，形如：
    [{"pos":"n","g":"m","reg":["Mexico","Spain"],"lex":["colloquial"]}, {...}]
  `reg`=地理使用区，`lex`=语域（colloquial/vulgar/archaic/…），`g`=性，`pos`=逐义项词性。
· 音标已完成：与西语版维基词典逐字一致率 95.6%，可回核率 59.5%。

【第一件：义项覆盖】
拿**中文版维基词典**（唯一独立的人工中文释义源）确定性比对了 26,194 个 lemma：
词级搭得上 75.7%、共享实词字 19.4%、连一个实词字都不共享 4.9%（1,275 条）。
逐条看那 1,275 条，发现问题**不在翻译质量**，而在**英文版给的义项集合本身**。
下面 A 组是真实样本（我们的译文 / 中文版的释义 / 英文版原始 gloss 一并给出）。

【第二件：领域标注 topics】
两个源都有 `senses[].topics`，但**本体不同**：
  · 英文版：层级式，一条词同时挂 `sciences / natural-sciences / physical-sciences / chemistry`
  · 语言版（西语版）：扁平具体，只给 `chemistry`
落到我们库里的词形：英文版 11,222、西语版 21,096、并集 29,038（占 lemma 27.6%）。
库里现在 topics 覆盖为 0，这一列还没建。B 组是真实样本。"""

SYS = """你是双语词典编纂与词汇语义学专家。下面给你一部西班牙语→中文学习词典的现状、
它的两个待定规则，以及真实数据样本。严格输出 JSON：

{
 "sense_completion": {
   "should_import": "always|conditional|never",
   "conditions": ["若 conditional，列出该补的判据"],
   "ordering": "补进来的义项应排在哪里，依据是什么",
   "provenance": "该不该给补进来的义项打来源标记，怎么打",
   "risks": ["这条规则最可能在哪里出错"],
   "per_sample": [{"word":"词","verdict":"import|skip|needs_check","why":"一句话"}]
 },
 "topics_ontology": {
   "merge": "两套本体怎么合并",
   "keep_level": "层级本体保留到哪一级，为什么",
   "max_labels": "一个义项最多展示几个领域标签",
   "conflict": "两源给不同领域时怎么办",
   "risks": ["最可能出错的地方"]
 },
 "rule_holes": [
   {"which":"sense_completion 或 topics_ontology","issue":"没考虑到的情况",
    "example":"真实西语词","severity":"high|medium|low"}
 ]
}

要点：
- 判断请针对**中国的西语学习者 + 划词弹窗**这个具体场景，不要给通用词典学建议。
- `per_sample` 必须覆盖 A 组每一条。
- rule_holes 要给真实西语词作反例；举不出词就别写这条。
- 不要评论"要不要做例句""要不要加音频"这些不在问题里的产品选择。
- 我手上有权威源真值但没有全部给你，你的判断回头会拿它打分 —— 请只说你有把握的。"""


def build_sense_samples(k=18):
    recs = [json.loads(l) for l in open(DIV, encoding="utf-8")]
    random.seed(11)
    # 混排：核心词与长尾各取，不按"我认为该补/不该补"分组（纪律⑨）
    core = [r for r in recs if r["level"] in ("A1", "A2", "B1")]
    tail = [r for r in recs if r["level"] in ("B2", "C1", "C2")]
    pick = random.sample(core, min(k // 2, len(core))) + \
           random.sample(tail, min(k - k // 2, len(tail)))
    random.shuffle(pick)
    return [{"词": r["word"], "CEFR": r["level"], "词性": r["pos"],
             "我们的中文释义": (r["ours"] or "").split("\n"),
             "中文版维基的释义": r["zh"],
             "英文版维基的第一条 gloss": r["def"]} for r in pick]


def build_topic_samples(k=12):
    """同一个词在两个源里的 topics 对照 —— 现取现算，不留中间态。"""
    en = collections.defaultdict(set)
    for ln in open(paths.KK, encoding="utf-8"):
        e = json.loads(ln)
        for s in e.get("senses") or []:
            if s.get("topics"):
                en[e["word"]] |= set(s["topics"])
    es = collections.defaultdict(set)
    for ln in gzip.open(paths.EDITION, "rt", encoding="utf-8", errors="replace"):
        e = json.loads(ln)
        if e.get("lang_code") != "es":
            continue
        for s in e.get("senses") or []:
            if s.get("topics"):
                es[e["word"]] |= set(s["topics"])
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    lem = {w for (w,) in conn.execute("SELECT word FROM dict WHERE is_lemma=1")}
    conn.close()
    both = [w for w in (en.keys() & es.keys() & lem)]
    random.seed(11)
    out = []
    for w in random.sample(both, min(k, len(both))):
        out.append({"词": w, "英文版 topics": sorted(en[w]), "西语版 topics": sorted(es[w])})
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
        f = re.sub(r"}\s*\n\s*(\")", r"},\n\1", s)
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
            raise RuntimeError("HTTP %s: %s" % (r.status_code, r.text[:300]))
        d = json.loads(r.text.lstrip())
        return d["choices"][0]["message"]["content"], d.get("usage") or {}


async def ask_doubao(env, payload):
    from volcenginesdkarkruntime import AsyncArk
    cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
    r = await cl.chat.completions.create(
        model=env["DOUBAO_SEED_2_1_PRO"], temperature=0,
        thinking={"type": "enabled"},
        messages=[{"role": "system", "content": SYS},
                  {"role": "user", "content": payload}])
    return r.choices[0].message.content, {"prompt_tokens": r.usage.prompt_tokens,
                                          "completion_tokens": r.usage.completion_tokens}


def show(name, raw):
    try:
        d = loads_lenient(raw)
    except Exception as e:
        print("🔴 %s 解析失败：%s\n%s" % (name, e, raw[:400]))
        return
    print("\n" + "=" * 76 + "\n■ " + name)
    sc = d.get("sense_completion") or {}
    print("  ▸ 义项补全：**%s**" % sc.get("should_import", "?"))
    for c in (sc.get("conditions") or [])[:6]:
        print("      · " + str(c)[:110])
    print("    排序   : " + str(sc.get("ordering", ""))[:150])
    print("    来源标记: " + str(sc.get("provenance", ""))[:150])
    ps = sc.get("per_sample") or []
    vc = collections.Counter(x.get("verdict") for x in ps)
    print("    逐样本裁决: %s" % dict(vc))
    to = d.get("topics_ontology") or {}
    print("  ▸ topics 本体：保留到 **%s**，最多 %s 个标签" % (
        to.get("keep_level", "?"), to.get("max_labels", "?")))
    print("    合并   : " + str(to.get("merge", ""))[:150])
    print("    冲突   : " + str(to.get("conflict", ""))[:150])
    holes = d.get("rule_holes") or []
    print("  ▸ 规则漏洞 %d 条" % len(holes))
    for h in holes[:6]:
        print("      [%s|%s] %s ← 例 %s" % (h.get("severity", "?"), h.get("which", "?"),
                                            str(h.get("issue", ""))[:70], h.get("example")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()

    A = build_sense_samples()
    B = build_topic_samples()
    payload = (RULE_DOC
               + "\n\n【A 组：义项覆盖样本】\n" + json.dumps(A, ensure_ascii=False, indent=1)
               + "\n\n【B 组：topics 本体样本】\n" + json.dumps(B, ensure_ascii=False, indent=1))
    if not a.run:
        print(payload)
        print("\n… A 组 %d 条 / B 组 %d 条，payload 约 %s 字符" % (len(A), len(B), format(len(payload), ",")))
        return

    env = load_env()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    async def go():
        # gather 必须在 async 上下文里调，否则 "a coroutine was expected, got _GatheringFuture"
        return await asyncio.gather(
            ask_v4pro(env["DEEPSEEK_API_KEY"], payload), ask_doubao(env, payload),
            return_exceptions=True)

    v4, dou = asyncio.run(go())
    print("两家并行跑完 %.0fs" % (time.time() - t0))
    rec = {"A": A, "B": B, "ts": time.strftime("%Y-%m-%d %H:%M")}
    for name, r in (("v4pro", v4), ("doubao", dou)):
        if isinstance(r, Exception):
            print("🔴 %s 失败：%s" % (name, r))
            continue
        txt, u = r
        rec[name] = {"raw": txt, "usage": u}
        print("■ %s 用量 %s" % (name, u))
        show(name, txt)
    OUT.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n→ %s" % OUT)


if __name__ == "__main__":
    main()
