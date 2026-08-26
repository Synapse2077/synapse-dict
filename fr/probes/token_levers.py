#!/usr/bin/env python3
"""token 成本的**两个杠杆**：批大小 × 开不开思考。2026-08-23。

`probes/token_cost.py` 量出一件反直觉的事：
**出方向 token 几乎不随批里的条数变**（20 条 36k、40 条 41k、80 条 26k）
⇒ flash 在跑思考链，成本按**请求数**走，不按条数走。

那么真正要定的是两件事，而不是"每条多少钱"：
  ① 批多大 —— 越大越省，但 it 阶段 5 实测 flash 会**静默丢批里的一部分**（2,069 条）
  ② 思考开不开 —— `[[blind-gloss-inference-ceiling]]` 记过「开思考贵 13 倍」

🔴 关思考不是纯省钱：那条记忆同时记了**质量差**（盲测错误率 25% vs 16%）。
   所以本探针**同时**打印两边的产出，让我逐条比，不能只看 token。

跑：python3 -u probes/token_levers.py > log 2>&1 &
    （🔴 必须 `-u`：重定向到文件时 stdout 是块缓冲的，
      上一轮我以为脚本卡死，其实只是输出没刷出来。）
"""
import asyncio
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths                              # noqa: E402
from pipeline import slot_translate       # noqa: E402
from probes.token_cost import SYS_B, DEMO, SKIP   # noqa: E402


def plain(n):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    out = []
    for sid, w, raw in con.execute("""
            SELECT s.id, d.word, g.text FROM sense s
            JOIN dict d ON d.id = s.word_id
            JOIN sense_gloss g ON g.sense_id = s.id AND g.lang='fr'
            LEFT JOIN sense_gloss z ON z.sense_id = s.id AND z.lang='zh'
            WHERE z.sense_id IS NULL"""):
        t = " ".join(raw.split())
        if SKIP.match(t) or DEMO.match(t):
            continue
        out.append({"id": sid, "word": w, "fr": t})
        if len(out) >= n:
            return out
    return out


async def one(cl, key, items, think):
    body = {"model": slot_translate.MODEL, "temperature": 0, "stream": False,
            "messages": [{"role": "system", "content": SYS_B},
                         {"role": "user", "content": json.dumps(items, ensure_ascii=False)}]}
    if not think:
        # DeepSeek 的关思考开关。若该模型不认这个字段，用量不会掉 —— 那就说明关不掉。
        body["thinking"] = {"type": "disabled"}
        body["reasoning_effort"] = "none"
    try:
        r = await cl.post(slot_translate.URL, headers={"Authorization": "Bearer " + key},
                          json=body, timeout=900)
    except Exception as e:
        return {"err": str(e)[:80]}
    if r.status_code != 200:
        return {"err": "HTTP %s %s" % (r.status_code, r.text[:100])}
    d = r.json()
    u = d.get("usage") or {}
    txt = d["choices"][0]["message"]["content"]
    try:
        got = {str(o["id"]): o.get("zh", "")
               for o in json.loads(re.sub(r"^```(?:json)?|```$", "", txt.strip(),
                                          flags=re.M).strip())}
    except Exception:
        got = None
    return {"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0),
            "tot": u.get("total_tokens", 0), "n": len(items), "got": got}


async def main():
    import httpx
    key = slot_translate.env()["DEEPSEEK_API_KEY"].strip()
    pool = plain(320)
    print("■ 样本 %d 条（真·要送模型的那批）\n" % len(pool))
    print("思考  批大小   入token    出token    合计     每条    回条数  缺条")
    res = {}
    async with httpx.AsyncClient() as cl:
        # 🔴 2026-08-23 用户中断：**不再发开思考的请求**。
        #    开思考的基线已经量到（80 条 11,312 token / 每条 141.4），够用了。
        #    真正该比的不是开/关两边的中文，是**关思考的中文对不对**——
        #    我拿法语原文逐条核，不拿另一边的模型输出当真值。
        for think in (False,):
            for size in (80, 160, 320):
                r = await one(cl, key, pool[:size], think)
                if "err" in r:
                    print("%-4s %5d   🔴 %s" % ("开" if think else "关", size, r["err"]))
                    continue
                miss = size if r["got"] is None else sum(
                    1 for i in pool[:size] if str(i["id"]) not in r["got"])
                print("%-4s %5d %9s %10s %9s %8.1f %8s %5d%s"
                      % ("开" if think else "关", size, format(r["in"], ","),
                         format(r["out"], ","), format(r["tot"], ","), r["tot"] / size,
                         "解析失败" if r["got"] is None else len(r["got"]), miss,
                         "  🔴" if miss else ""))
                if size == 80:
                    res[think] = r["got"]

    # 🔴 质量必须并排看，不能只看 token
    b = res.get(False)
    if b:
        print("\n── 关思考的产出，对着法语原文看（前 30 条）──")
        print("%-18s %-56s %s" % ("词形", "法语释义", "关思考给的中文"))
        print("-" * 108)
        for i in pool[:30]:
            print("%-18s %-56s %s"
                  % (i["word"][:18], i["fr"][:56], (b.get(str(i["id"])) or "—")[:24]))
        blank = sum(1 for i in pool[:80] if not b.get(str(i["id"])))
        print("\n80 条里模型主动留空 %d 条" % blank)


if __name__ == "__main__":
    asyncio.run(main())
