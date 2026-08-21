#!/usr/bin/env python3
"""把一份材料**并行**问豆包 pro 与 deepseek-v4-pro，各自落盘。2026-08-13。

用户 2026-08-01 定的规矩：关键判断/重要规则不能独断，必要时同时问两家，
我有最终决断权。此前每次都是现写一段一次性代码，这里固化成工具。

═══ 用它的纪律（都是踩出来的，见 [[llm-as-evaluator-discipline]]）═══
· **能确定性回源比对的，根本别问模型** —— 只问规则判断，不问逐行事实
· **材料里必须带权威源的真值**（没给 kaikki 原值导致连续四族误报）
· **别把结论写进材料标题** —— 两家"收敛"的可能只是我的偏见
· 商量规则**开思考**（成批当判官才关）；两家意见不一致时回源核对，不取多数

═══ 豆包在本项目的边界（用户 2026-08-19 定）═══
🔴 **咨询可以用豆包，跑批不行。** 2026-08-15 那次禁用（「贵的离谱」+ 跑到账户欠费）
   针对的是**批量**通路：`it/pipeline/ark_batch.py` 里 `DOUBAO_DISABLED=True` 硬拦截，
   不显式传 `allow_doubao=True` 一个请求都发不出去 —— 那条拦截**继续有效**。
   本脚本是另一回事：一份材料问一次，token 量可忽略，用户明确说「作为咨询师完全没问题」。

⚠️ 所以这里唯一要防的是**把跑批伪装成咨询** —— 拿它循环喂几千条就等于绕过了那道闸。
   下面的体积闸就是干这个的：材料超过 `MAX_KB` 必须显式加 `--big` 并说明理由。

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

# 一次咨询该有的体积上限。**这不是性能考虑，是通路考虑** —— 见文件头「豆包的边界」：
# 咨询与跑批的区别就在于量，量一大它就不再是咨询了。
MAX_KB = 64


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
    ap.add_argument("--only", choices=("v4pro", "doubao"), default="",
                    help="只问一家（默认两家并行）")
    ap.add_argument("--big", action="store_true",
                    help="材料超过 %d KB 时必须显式加上，见文件头「豆包的边界」" % MAX_KB)
    a = ap.parse_args()

    import httpx
    doc = pathlib.Path(a.doc)
    text = doc.read_text(encoding="utf-8")
    # 🔴 体积闸：拦的是「把跑批伪装成咨询」，不是拦大文件本身。
    kb = len(text.encode("utf-8")) / 1024
    if kb > MAX_KB and not a.big:
        sys.exit("🔴 材料 %.0f KB，超过咨询的量级（%d KB）。\n"
                 "   一次咨询 = 一个判断题；成千上万条要判就是跑批，跑批走 "
                 "it/pipeline/ds_batch.py，别从这里绕。\n"
                 "   确实是一份长材料就加 --big。" % (kb, MAX_KB))
    out = pathlib.Path(a.out) if a.out else doc.parent
    e = env()
    think = not a.no_think

    async with httpx.AsyncClient(timeout=1200) as cl:
        t0 = time.time()
        # ⚠️ 协程要**按需创建**：先建两个再丢掉一个，会留下 "never awaited" 警告，
        #    而那条警告长得跟"请求失败了"很像。
        makers = {"v4pro": lambda: ask_deepseek(cl, e, text, think),
                  "doubao": lambda: ask_doubao(cl, e, text, think)}
        names = [a.only] if a.only else list(makers)
        res = await asyncio.gather(*(makers[n]() for n in names),
                                   return_exceptions=True)

    for name, r in zip(names, res):
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
