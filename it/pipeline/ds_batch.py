#!/usr/bin/env python3
"""DeepSeek 的跑批器，接口与 `ark_batch.run` **完全一致**。2026-08-15。

═══ 为什么要同接口 ═══
要横评豆包 pro / 豆包 turbo / DeepSeek flash 哪个够用，就必须让三家做**同一道题**：
同一个 SYS、同一个 payload 形状、同一套控制组题目。

`translate_it_defs` 里那条 DeepSeek 通路用的是「JSON 数组进、数组出、靠 `id` 对齐」，
而 `ark_batch` 用的是「对象进、对象出、靠批内键对齐」。直接拿两边比，
**比的是我的两套提示，不是两家模型** —— `prompt-beats-model-choice` 那条教训
（我两次差点因"模型能力"买贵的，两次都是我自己的问题）。

⇒ 本文件让 DeepSeek 也走对象协议，三家唯一的差别就只剩模型本身。

保留 `ark_batch` 的三件事：每批 flush 落盘、按已落盘 id 续传、进度 `flush=True`。
"""
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import quality_pass as Q   # noqa: E402  只借它的 load_env / loads_lenient

MODELS = {
    "flash": "deepseek-v4-flash",
    "pro": "deepseek-v4-pro",
}
URL = "https://api.deepseek.com/chat/completions"


def _balance(t):
    """按括号栈**纠正/补齐闭合符**，一个内容字符都不改。

    🔴 实测坏样：`{"1": {"r": [{…}, {"n": 13, "i": 5}}}` ——
       数组该用 `]` 收尾，模型写成了 `}`。答案本身是完整的（13 条意语释义
       对应 13 个答案），坏的只是收尾符号的**类型**。
       `quality_pass.loads_lenient` 只补逗号，不看括号；我第一版只会在末尾追加，
       对"类型写错"同样无效 —— 必须按栈把闭合符改对。

    ⚠️ 只动 `]` `}` 两种字符，且**扫描时忽略字符串内部**；
       修完必须能解析成功才采用（见 `_try`），解析不了就整条丢弃，绝不猜内容。
    """
    out, stack, in_str, esc = [], [], False, False
    for ch in t:
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
        elif ch in "[{":
            stack.append(ch)
            out.append(ch)
        elif ch in "]}":
            if not stack:
                continue                       # 多余的闭合符，丢掉
            want = "]" if stack[-1] == "[" else "}"
            out.append(want)                   # 🔴 按栈写正确的那个，而不是模型给的
            stack.pop()
        else:
            out.append(ch)
    if in_str:
        return None
    out += ["]" if c == "[" else "}" for c in reversed(stack)]
    return "".join(out)


def _try(s):
    """⚠️ `quality_pass.loads_lenient` 解析失败时**抛异常**、不是返回 None。"""
    if not s:
        return None
    try:
        d = Q.loads_lenient(s)
    except Exception:
        return None
    return d if isinstance(d, dict) else None


def _parse(text):
    """对象协议：取最外层 {...} 解析。与 `quality_pass.acall` 同口径。"""
    t = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
    i = t.find("{")
    if i < 0:
        return None
    j = t.rfind("}")
    if j > i:
        d = _try(t[i:j + 1])
        if d is not None:
            return d
    return _try(_balance(t[i:]))   # 右括号缺失：按栈补齐后重试


async def run(sys_prompt, batches, meta, out_path, mode="flash", conc=12,
              every=10, on_row=None):
    import httpx
    env = Q.load_env()
    model = MODELS.get(mode, mode)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            try:
                done.add(json.loads(line)["id"])
            except Exception:
                pass
    todo = [i for i in range(len(batches))
            if not all(rid in done for _, rid in meta[i])]
    print("■ 共 %s 批，已完成 %s 批，本轮跑 %s 批"
          % (f"{len(batches):,}", f"{len(batches) - len(todo):,}", f"{len(todo):,}"),
          flush=True)
    if not todo:
        return 0
    print("■ 模型 %s  并发 %d" % (model, conc), flush=True)

    q = asyncio.Queue()
    for i in todo:
        q.put_nowait(i)
    fh = out_path.open("a", encoding="utf-8")
    lock = asyncio.Lock()
    ctr = {"done": 0, "tok": 0, "fail": 0}
    hdr = {"Authorization": "Bearer " + env["DEEPSEEK_API_KEY"].strip()}

    async def worker(cl):
        while True:
            try:
                i = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            res, tok = None, 0
            for attempt in range(3):
                try:
                    r = await cl.post(URL, headers=hdr, timeout=300, json={
                        "model": model, "temperature": 0, "stream": False,
                        "thinking": {"type": "disabled"},
                        "messages": [{"role": "system", "content": sys_prompt},
                                     {"role": "user", "content": "输入：\n" + json.dumps(
                                         batches[i], ensure_ascii=False)}]})
                    if r.status_code != 200:
                        raise RuntimeError("HTTP %s %s" % (r.status_code, r.text[:120]))
                    d = r.json()
                    res = _parse(d["choices"][0]["message"]["content"])
                    u = d.get("usage") or {}
                    tok = u.get("total_tokens", 0)
                    if res is not None:
                        break
                except Exception as e:
                    if attempt == 2:
                        async with lock:
                            ctr["fail"] += 1
                            print("   ✗ 批 %d 失败 %s" % (i, str(e)[:80]), flush=True)
                        res = None
                    else:
                        await asyncio.sleep(1 + attempt)
            if res is None:
                q.task_done()
                continue
            async with lock:
                for k, rid in meta[i]:
                    v = res.get(k)
                    if isinstance(v, dict):
                        row = {"id": rid, **v}
                        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                        if on_row:
                            on_row(row)
                fh.flush()
                ctr["done"] += 1
                ctr["tok"] += tok
                if ctr["done"] % every == 0 or ctr["done"] == len(todo):
                    print("   [%s/%s] token %s 失败 %d"
                          % (f"{ctr['done']:,}", f"{len(todo):,}",
                             f"{ctr['tok']:,}", ctr["fail"]), flush=True)
            q.task_done()

    async with httpx.AsyncClient() as cl:
        await asyncio.gather(*[asyncio.create_task(worker(cl))
                               for _ in range(min(conc, len(todo)))])
    fh.close()
    print("■ 完成 %s 批 / 失败 %d 批 / token %s"
          % (f"{ctr['done']:,}", ctr["fail"], f"{ctr['tok']:,}"), flush=True)
    return ctr["tok"]
