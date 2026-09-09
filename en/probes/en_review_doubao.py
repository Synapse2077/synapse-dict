#!/usr/bin/env python3
"""外审**第二家**：豆包 seed-2.1 pro（online 咨询）。2026-09-09。

═══ 为什么可以用豆包 ═══
用户 2026-09-09：「商量的事儿，豆包pro是可以用的，之前不都这样吗，咨询花钱可控」。
项目规矩是 **禁跑批、不禁咨询**（`[[consult-two-models-on-rules]]`）——
硬拦截 `ark_batch.DOUBAO_DISABLED` 守的是 `run()`（批量），
本脚本走 `quality_pass.acall`（online 一问一答），是它一直允许的那条路。
⚠️ 我上一轮说「没有第二家的通道」是**记错了**，通道一直在。

═══ 为什么必须有第二家 ═══
`[[render-review-with-models]]`：**把渲染成品发两家**。
一家的意见只是一家的意见 —— 两家**都说**的那条，才值得优先回源；
两家**分歧**的地方，往往是判据本身有歧义。
⚠️ 不许把一家的输出说成「外审共识」。

═══ 纪律（与 DeepSeek 那轮同一份 prompt）═══
用**完全相同**的材料和 prompt，否则两家的差异里混着我的变量。
配额、边界、`sure` 字段一字不改（见 `en_review.SYS`）。

    cd en && python3 -u probes/en_review_doubao.py --part 1     # 先实测单价
    cd en && python3 -u probes/en_review_doubao.py --all
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "probes"))
sys.path.insert(0, str(ROOT.parent / "it" / "pipeline"))

import quality_pass as Q                                  # noqa: E402
import en_review as R                                     # noqa: E402

OUT = Path("/Users/fangyi/.claude/jobs/c235368c/tmp")
SRC = R.SRC


def chunks():
    """与 DeepSeek 那轮**同一套切片**（同一个函数算出来的，不重抄）。"""
    CAP = 8000
    blocks, cur = [], []
    for ln in SRC.read_text(encoding="utf-8").splitlines(True):
        if ln.startswith("## ") and cur:
            blocks.append("".join(cur)); cur = []
        cur.append(ln)
    if cur:
        blocks.append("".join(cur))
    out = []
    for b in blocks:
        head = b.split("\n", 1)[0]
        if len(b) <= CAP:
            out.append(b); continue
        buf = []
        for ln in b.split("\n"):
            if sum(len(x) + 1 for x in buf) + len(ln) > CAP and buf:
                out.append(head + "（接上页）\n" + "\n".join(buf)); buf = []
            buf.append(ln)
        if buf:
            out.append(head + "（接上页）\n" + "\n".join(buf))
    return out


async def ask(one, idx):
    from volcenginesdkarkruntime import AsyncArk
    env = Q.load_env()
    cl = AsyncArk(api_key=env["ARK_API_KEY"])
    model, comps = Q.model_comps(cl)
    # 🔴 `acall` 的 payload 是 dict；这里按它的约定用本地键 "1"
    #    （`quality_pass` 的注释写着：**别用全局唯一键，豆包会重编号** ——
    #     那正是我今天在 DeepSeek 上撞到的「配错行」的同一个病，
    #     这个库早就记着了，见 `[[primary-key-is-not-enough]]`）
    res, tok = await Q.acall(comps, model, R.SYS, {"1": one})
    return res, tok, model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", type=int, default=0)
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    cs = chunks()
    todo = range(1, len(cs) + 1) if a.all else [a.part or 1]
    total = 0
    for i in todo:
        out = OUT / ("doubao_review%d.json" % i)
        if out.exists():
            continue
        res, tok, model = asyncio.run(ask(cs[i - 1], i))
        total += tok
        out.write_text(json.dumps(res, ensure_ascii=False), "utf-8")
        n = len(res.get("issues") or []) if isinstance(res, dict) else 0
        print("■ 第 %d/%d 片 ｜ 模型 %s ｜ token %s ｜ 报 %d 条"
              % (i, len(cs), model, format(tok, ","), n), flush=True)
    print("\n■ 本轮 token %s" % format(total, ","))
    return 0


if __name__ == "__main__":
    sys.exit(main())
