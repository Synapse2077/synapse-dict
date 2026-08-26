#!/usr/bin/env python3
"""**例句翻译**：豆包翻译模型 vs DeepSeek flash。2026-08-25，用户提议。

═══ 为什么要重新评估（上一轮我否掉过它）═══
`[[translation-model-has-no-prompt-channel]]` 那一轮评的是**释义翻译**，结论「不换」。
但用户 2026-08-25 指出：**例句这一族的任务性质变了 —— 它就是翻译。**
逐条对照上次否掉它的理由：

    上次的问题                        对例句还成立吗
    `Qui…` 族被译成问句 25 抽 12       ❌ 那是「释义要写成形容词短语」的要求，例句本来就该忠实翻译
    指针族它在翻译那个指针              ❌ 例句里没有指针
    从不留空、一律硬编                 ⚠️ 部分成立，但例句里该留空的只有 0.25%
    **没有任何提示通道**               ✅ 仍然成立

⇒ 传不进去的规则里，**两条会真咬人**：
   ③「人名地名没有通用译名就保留原文」—— 传不进去，可能被音译生造
   ⑤「习语不要字面直译」—— flash 加了这条规则才修好 `passer cent sept ans`（≠「一百零七年」）

═══ ⭐ 这一轮有上一轮没有的东西：免费真值 ═══
英文版给了 13,181 条例句的**英文译文**，已在 `example_gloss(lang='en')`。
⇒ 同一句法语，三栏并排：**源头英文 / flash 中文 / 豆包中文**，我逐条读。
   `[[llm-as-evaluator-discipline]]` ⑩：能回源比对就别问模型 —— 这里由我读，不找第三个模型投票。

═══ 价格（官网人民币直标，2026-08-25）═══
                       输入(未命中)   输出
    DeepSeek flash 空闲   1.5 元/M   4.5 元/M
    豆包翻译模型          1.2 元/M   3.6 元/M     ⇒ 便宜 20%，全量约省 38 元

跑：python3 -u probes/example_model_bakeoff.py --n 40      （在 fr/ 目录下）
"""
import argparse
import asyncio
import json
import random
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import paths                                     # noqa: E402
from pipeline import slot_translate              # noqa: E402
from pipeline import translate_examples as T     # noqa: E402

ARK = "https://ark.cn-beijing.volces.com/api/v3/responses"
EP_KEY = "DOUBAO_SEED_TRANSLATION"
# 🔴 实测（上一轮）：60 行起 HTTP 500。取 40。
ARK_LINES = 12   # 🔴 40 行长句 → HTTP 400；例句比槽值长，只能更小
P_DOUBAO_IN, P_DOUBAO_OUT = 1.2, 3.6      # 元/M
P_DS_IN, P_DS_OUT = 1.5, 4.5              # 元/M，空闲时段


def pairs_with_en(con, n, seed=13):
    """→ [(fr, en)]，取有英文译文的例句 —— 那是这一族唯一的免费真值。"""
    rows = list(con.execute(
        "SELECT e.text, g.text FROM example e "
        "JOIN example_gloss g ON g.example_id=e.id AND g.lang='en' "
        "WHERE length(e.text) BETWEEN 30 AND 300"))
    random.Random(seed).shuffle(rows)
    return rows[:n]


async def ds_call(cl, key, items):
    """DeepSeek flash：**完整 prompt**（七条规则），一次请求整批，关思考。"""
    body = {"model": "deepseek-v4-flash", "temperature": 0, "stream": False,
            "thinking": {"type": "disabled"}, "reasoning_effort": "none",
            "messages": [{"role": "system", "content": T.SYS},
                         {"role": "user", "content": json.dumps(items, ensure_ascii=False)}]}
    t0 = time.time()
    r = await cl.post("https://api.deepseek.com/chat/completions",
                      headers={"Authorization": "Bearer " + key}, json=body, timeout=600)
    dt = time.time() - t0
    if r.status_code != 200:
        return {}, {}, dt, "HTTP %s %s" % (r.status_code, r.text[:160])
    d = r.json()
    txt = re.sub(r"^```(?:json)?|```$", "",
                 d["choices"][0]["message"]["content"].strip(), flags=re.M).strip()
    try:
        got = {str(o["id"]): o.get("zh", "") for o in json.loads(txt)}
    except Exception as ex:
        return {}, d.get("usage") or {}, dt, "解析失败 %s" % ex
    return got, d.get("usage") or {}, dt, None


async def ark_batch(cl, key, ep, items):
    """豆包翻译模型：**没有提示通道**，只能把多行塞进一条正文，靠行号对齐。"""
    got, usage = {}, {"input_tokens": 0, "output_tokens": 0}
    t0 = time.time()
    err = None
    lost = 0
    for k in range(0, len(items), ARK_LINES):
        ch = items[k:k + ARK_LINES]
        text = "\n".join("%d\t%s" % (i + 1, x["fr"]) for i, x in enumerate(ch))
        body = {"model": ep, "input": [{"role": "user", "content": [
            {"type": "input_text", "text": text,
             "translation_options": {"source_language": "fr", "target_language": "zh"}}]}]}
        r = await cl.post(ARK, headers={"Authorization": "Bearer " + key},
                          json=body, timeout=300)
        if r.status_code != 200:
            err = "HTTP %s %s" % (r.status_code, r.text[:160])
            continue
        d = r.json()
        out = d["output"][0]["content"][0]["text"]
        for f in usage:
            usage[f] += (d.get("usage") or {}).get(f, 0)
        seen = 0
        for ln in out.splitlines():
            m = re.match(r"\s*(\d+)\s*\t?\s*(.*)$", ln)
            if not m:
                continue
            i = int(m.group(1)) - 1
            if 0 <= i < len(ch):
                got[ch[i]["id"]] = m.group(2).strip()
                seen += 1
        lost += len(ch) - seen
    return got, usage, time.time() - t0, err, lost


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    a = ap.parse_args()
    env = slot_translate.env()
    ep = env.get(EP_KEY, "").strip()
    if not ep:
        print("🔴 .env 里没有 %s" % EP_KEY)
        return 1

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = pairs_with_en(con, a.n)
    items = [{"id": str(i), "fr": fr} for i, (fr, _en) in enumerate(rows)]
    print("■ 样本 %d 条（**都带英文译文**，可当真值对照）" % len(items))

    async def run():
        import httpx
        async with httpx.AsyncClient() as cl:
            ds = await ds_call(cl, env["DEEPSEEK_API_KEY"].strip(), items)
            db = await ark_batch(cl, env["ARK_API_KEY"].strip(), ep, items)
            return ds, db

    (ds_got, ds_u, ds_t, ds_e), (db_got, db_u, db_t, db_e, lost) = asyncio.run(run())
    if ds_e:
        print("🔴 flash: %s" % ds_e)
    if db_e:
        print("🔴 豆包: %s" % db_e)

    n = len(items)
    ds_in, ds_out = ds_u.get("prompt_tokens", 0), ds_u.get("completion_tokens", 0)
    db_in, db_out = db_u.get("input_tokens", 0), db_u.get("output_tokens", 0)
    print("\n══ 成本（元/百万：flash 1.5/4.5 ｜ 豆包 1.2/3.6）══")
    for tag, i_, o_, pi, po, dt, ls in (
            ("DeepSeek flash", ds_in, ds_out, P_DS_IN, P_DS_OUT, ds_t, 0),
            ("豆包翻译模型", db_in, db_out, P_DOUBAO_IN, P_DOUBAO_OUT, db_t, lost)):
        y = (i_ * pi + o_ * po) / 1e6
        print("   %-16s 入 %6s 出 %6s ｜ %.1f token/条 ｜ %.1fs ｜ 全量 615,214 句 ≈ **%.0f 元**%s"
              % (tag, format(i_, ","), format(o_, ","), (i_ + o_) / max(n, 1), dt,
                 y / max(n, 1) * 615214, "  🔴 丢 %d 行" % ls if ls else ""))

    print("\n══ 三栏并排：源头英文（真值）/ flash / 豆包 ══")
    for i, (fr, en) in enumerate(rows):
        k = str(i)
        print("\n[%d] FR    %s" % (i + 1, fr[:120]))
        print("    EN    %s" % en[:120])
        print("    flash %s" % (ds_got.get(k) or "（无）")[:120])
        print("    豆包  %s" % (db_got.get(k) or "（无）")[:120])
    return 0


if __name__ == "__main__":
    sys.exit(main())
