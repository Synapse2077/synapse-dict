#!/usr/bin/env python3
"""把一份材料**并行**问豆包 pro 与 deepseek-v4-pro，各自落盘。2026-08-13。

用户 2026-08-01 定的规矩：关键判断/重要规则不能独断，必要时同时问两家，
我有最终决断权。此前每次都是现写一段一次性代码，这里固化成工具。

═══ 用它的纪律（都是踩出来的，见 [[llm-as-evaluator-discipline]]）═══
· **能确定性回源比对的，根本别问模型** —— 只问规则判断，不问逐行事实
· **材料里必须带权威源的真值**（没给 kaikki 原值导致连续四族误报）
· **别把结论写进材料标题** —— 两家"收敛"的可能只是我的偏见
· 商量规则**开思考**（成批当判官才关）；两家意见不一致时回源核对，不取多数

用法：
    python3 scripts/consult.py data/work/it/probe/consult_20260813.md
    python3 scripts/consult.py <材料.md> --out data/work/it/probe --no-think
"""
import argparse
import asyncio
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SYS = ("你是资深词典工程师与语言学顾问。回答要具体、可执行、敢下结论；"
       "不要复述提问者给的数据，不要罗列泛泛的利弊。")


def env():
    return dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines()
                if "=" in l and not l.startswith("#"))


async def ask_deepseek(cl, e, text, think):
    body = {"model": "deepseek-v4-pro",
            "messages": [{"role": "system", "content": SYS},
                         {"role": "user", "content": text}],
            "temperature": 0, "stream": False,
            "thinking": {"type": "enabled" if think else "disabled"}}
    r = await cl.post("https://api.deepseek.com/chat/completions",
                      headers={"Authorization": "Bearer " + e["DEEPSEEK_API_KEY"].strip()},
                      json=body)
    if r.status_code != 200:
        raise RuntimeError("HTTP %s: %s" % (r.status_code, r.text[:200]))
    d = r.json()
    return d["choices"][0]["message"]["content"], d.get("usage") or {}


async def ask_doubao(cl, e, text, think):
    model = e["DOUBAO_MODEL_ONLINE_LITE"].strip()
    body = {"model": model,
            "messages": [{"role": "system", "content": SYS},
                         {"role": "user", "content": text}],
            "temperature": 0, "stream": False,
            "thinking": {"type": "enabled" if think else "disabled"}}
    r = await cl.post("https://ark.cn-beijing.volces.com/api/v3/chat/completions",
                      headers={"Authorization": "Bearer " + e["ARK_API_KEY"].strip()},
                      json=body)
    if r.status_code != 200:
        raise RuntimeError("HTTP %s: %s" % (r.status_code, r.text[:200]))
    d = r.json()
    return d["choices"][0]["message"]["content"], d.get("usage") or {}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("doc")
    ap.add_argument("--out")
    ap.add_argument("--no-think", action="store_true")
    a = ap.parse_args()

    import httpx
    doc = pathlib.Path(a.doc)
    text = doc.read_text(encoding="utf-8")
    out = pathlib.Path(a.out) if a.out else doc.parent
    e = env()
    think = not a.no_think

    async with httpx.AsyncClient(timeout=1200) as cl:
        t0 = time.time()
        res = await asyncio.gather(
            ask_deepseek(cl, e, text, think),
            ask_doubao(cl, e, text, think),
            return_exceptions=True)

    for name, r in zip(("v4pro", "doubao"), res):
        p = out / ("%s.%s.md" % (doc.stem, name))
        if isinstance(r, Exception):
            print("🔴 %s 失败：%s" % (name, r), file=sys.stderr)
            continue
        content, usage = r
        p.write_text(content, encoding="utf-8")
        print("✓ %-7s %6d 字 → %s   tokens=%s" % (
            name, len(content), p, json.dumps(usage, ensure_ascii=False)))
    print("用时 %.0fs" % (time.time() - t0))


if __name__ == "__main__":
    asyncio.run(main())
