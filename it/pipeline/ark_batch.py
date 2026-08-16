#!/usr/bin/env python3
"""豆包 batch 的**可观测、可续传**跑批器。2026-08-14。

═══ 为什么要有这个文件 ═══
七月的 `quality_pass.run_batches` 把结果全攒在内存里、**跑完才一次性落盘**、没有续传。
后果：跑一小时期间进度完全不可见（`tail` 什么都看不到），中途崩一次前功尽弃。

我当天早些时候写 `translate_it_defs.run_batches` 时本来已经解决过这个问题
（每批 flush 落盘 + 断点续传 + 进度输出），但换成豆包 batch 通路时**又用回了旧写法**。
这个文件把那三件事固化下来，以后跑批一律走它。

    ① 每批跑完**立刻**写 JSONL 并 flush   → `wc -l` 随时能看到进度
    ② 启动时读已落盘的 id，**只跑没跑过的** → 中断可续、可分次跑
    ③ 进度 `flush=True`                    → 管道里也看得见

⚠️ 键必须是**每批本地 `1..N`**：豆包 turbo 会把全局键 `20_1` 重编号成 `1`
   （`quality_pass` 的原始注释记着这个坑）。
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import quality_pass as Q   # noqa: E402  复用它的 acall / model_comps / load_env


# ═══ 🔴 豆包已禁用（用户 2026-08-15：「豆包贵的离谱，不要用了」）═══
# 起因：我在 it 的 ④⑤ 上用豆包烧掉 509 万 tokens，其中 418 万因我 prompt 的缺陷作废，
# 直接导致用户账户欠费。本项目一律改用 DeepSeek（见 `ds_batch.py`）。
#
# 这里是**硬拦截**不是提醒：不带 allow_doubao=True 就直接抛错，一个请求都不发。
# 之所以做成拦截而不是"注意别用"——同一天我已经违反过自己写在 PLAYBOOK 里的
# 「别用 pro online 默认」，靠记性挡不住。
DOUBAO_DISABLED = True


class DoubaoDisabled(RuntimeError):
    pass


async def run(sys_prompt, batches, meta, out_path, mode="turbo-batch", conc=12,
              every=10, on_row=None, allow_doubao=False):
    """batches[i] = {"1": payload, …}；meta[i] = [(key, row_id), …]。

    每批完成即把 {"id": row_id, **值} 追加进 out_path 并 flush。
    已在 out_path 里出现过的 row_id 所属的批**整批跳过**（批内 id 是一起产出的）。
    """
    if DOUBAO_DISABLED and not allow_doubao:
        raise DoubaoDisabled(
            "🔴 豆包已在本项目禁用（2026-08-15，费用）。请用 pipeline/ds_batch.py。"
            "确需豆包时显式传 allow_doubao=True，并先跟用户确认花费。")
    from volcenginesdkarkruntime import AsyncArk
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done_ids = set()
    if out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            try:
                done_ids.add(json.loads(line)["id"])
            except Exception:
                pass
    todo = [i for i in range(len(batches))
            if not all(rid in done_ids for _, rid in meta[i])]
    print("■ 共 %s 批，已完成 %s 批，本轮跑 %s 批"
          % (f"{len(batches):,}", f"{len(batches) - len(todo):,}", f"{len(todo):,}"),
          flush=True)
    if not todo:
        return 0

    Q.MODE = mode
    env = Q.load_env()
    client = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
    model, comps = Q.model_comps(client)
    print("■ 模型 %s  模式 %s  并发 %d" % (model, mode, conc), flush=True)

    q = asyncio.Queue()
    for i in todo:
        q.put_nowait(i)
    fh = out_path.open("a", encoding="utf-8")
    lock = asyncio.Lock()
    ctr = {"done": 0, "tok": 0, "fail": 0}

    async def worker():
        while True:
            try:
                i = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                res, tok = await Q.acall(comps, model, sys_prompt, batches[i])
            except Exception as e:
                async with lock:
                    ctr["fail"] += 1
                    print("   ✗ 批 %d 失败 %s" % (i, str(e)[:80]), flush=True)
                q.task_done()
                continue
            async with lock:
                for k, rid in meta[i]:
                    v = (res or {}).get(k)
                    if isinstance(v, dict):
                        row = {"id": rid, **v}
                        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                        if on_row:
                            on_row(row)
                fh.flush()                      # 🔴 关键：每批落盘，进度随时可见
                ctr["done"] += 1
                ctr["tok"] += tok
                if ctr["done"] % every == 0 or ctr["done"] == len(todo):
                    print("   [%s/%s] token %s 失败 %d"
                          % (f"{ctr['done']:,}", f"{len(todo):,}",
                             f"{ctr['tok']:,}", ctr["fail"]), flush=True)
            q.task_done()

    await asyncio.gather(*[asyncio.create_task(worker())
                           for _ in range(min(conc, len(todo)))])
    await client.close()
    fh.close()
    print("■ 完成 %s 批 / 失败 %d 批 / token %s"
          % (f"{ctr['done']:,}", ctr["fail"], f"{ctr['tok']:,}"), flush=True)
    return ctr["tok"]
