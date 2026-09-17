#!/usr/bin/env python3
"""DeepSeek 的跑批器（ja 专用拷贝）。接口与 `it/pipeline/ds_batch` 完全一致。2026-09-15。

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
import datetime as _dt
import json
import re
import sys
from pathlib import Path


# 🔴 **不 import 任何别的语种的模块。**（铁律①：按语种解耦，宁可重复不要耦合）
# 2026-09-15 差点出事：`ja/pipeline/translate_defs.py` 为了用 `it/pipeline/ds_batch`，
# 把 `it/` 插到了 `sys.path` 最前面 —— 于是 `import paths` / `import dbtool` 拿到的是
# **意大利语那份**，脚本连上了 `synapse-dict-it.sqlite`。
# 这次只读没写（连接是 mode=ro），同一个形状发生在写库那一步就是往错的库里写。
# ⇒ 本文件是 `it/pipeline/ds_batch.py` 的拷贝，`load_env`/`loads_lenient` 一并带过来。

# 🔴 走 **ja 自己的** `paths.ENV`，不引别的语种（见文件头那个 near-miss）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import paths as _ja_paths            # noqa: E402
ENV_PATH = _ja_paths.ENV


def load_env():
    env = {}
    for ln in open(ENV_PATH):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.strip().split("=", 1)
            env[k] = v
    return env


def loads_lenient(s):
    """容错解析豆包坏 JSON。turbo 有时条目间换行不加逗号（报 Expecting ',' delimiter），
    或留尾逗号。先直解，失败则修复常见问题再解。"""
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        fixed = re.sub(r'}\s*\n\s*(")', r'},\n\1', s)   # 条目间缺逗号（换行分隔）
        fixed = re.sub(r'}\s+(")', r'}, \1', fixed)      # 条目间缺逗号（空格分隔）
        fixed = re.sub(r',\s*([}\]])', r'\1', fixed)     # 去尾逗号
        return json.loads(fixed)


# （`it/pipeline/quality_pass` 里另一套跑批器有意不带过来 —— 本文件只要 load_env/loads_lenient）


# ══════════════════════════════════════════════════════════════════
# 🔴🔴 **花钱之前必须让人看见现在是什么价。** 2026-09-16 装在这儿。
#
# 用户 2026-09-16：「我已经给你发过很多次了，我不知道你到底记在哪里了」。
# 查了一遍：**记了三次，都是对的**——
#     `es-dict-pipeline.md:208`   高峰(北京时间 9:00–12:00、14:00–18:00) 所有计费项 ×2
#     `de-dict-pipeline.md:30`    高峰＝工作日北京 09–12 与 14–18
#     `translation-model-has-no-prompt-channel.md:44`  高峰＝周一至周五 UTC 01–04 / 06–10
# 而我这一轮还是说错了两次（凭空说成「00:30–08:30」）。
#
# ⚠️ **问题不是没记，是记错了地方**：三份都躺在**语种账本**（es/de）里，
#    而铁律是「只动当前那门语言」⇒ 做 ja 时我根本不会去读那两个文件。
#    `de-dict-pipeline.md` 自己都写着「判据在 `slot_translate.is_peak()`，不在任何文档里」。
#    ⇒ 记第四份没有意义。**`[[lesson-must-become-mechanism]]`：让工具在该说的时候说出来。**
#
# ⚠️ 而 de 早就把机制建好了（`de/pipeline/slot_translate.announce_window()`），
#    **只是没传到 ja** —— `[[decision-not-propagated-across-editions]]` 的又一例。
#    装在 `ds_batch` 而不是某个脚本里：它是 ja **所有**付费调用的唯一出口。
CST = _dt.timezone(_dt.timedelta(hours=8))


def is_peak(now=None):
    """→ 现在是不是高峰（全价）。北京时间，**周末一律不是高峰**。

    高峰＝周一至周五 北京时间 9:00–12:00 与 14:00–18:00，其余为空闲时段。
    空闲时段价格 ＝ 高峰价的**一半**。
    """
    t = (now or _dt.datetime.now(CST)).astimezone(CST)
    if t.weekday() >= 5:
        return False
    m = t.hour * 60 + t.minute
    return 9 * 60 <= m < 12 * 60 or 14 * 60 <= m < 18 * 60


def announce_window():
    """跑批前无条件打出来。**不是可选项** —— 它存在的理由就是我记不住。"""
    t = _dt.datetime.now(CST)
    pk = is_peak(t)
    print("■ 北京时间 %s 星期%s ⇒ %s"
          % (t.strftime("%F %H:%M"), "一二三四五六日"[t.weekday()],
             "🔴 **高峰时段，全价**（空闲时段是它的一半）" if pk
             else "✅ **空闲时段，半价**（高峰＝工作日 9–12、14–18）"), flush=True)
    return pk


def _selftest():
    """⭐ 变异自检：窗口边界必须真的分得开。"""
    D = lambda s: _dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=CST)
    cases = [                       # 2026-09-16 是星期三，09-19 星期六
        ("2026-09-16 08:59", False), ("2026-09-16 09:00", True),
        ("2026-09-16 11:59", True),  ("2026-09-16 12:00", False),
        ("2026-09-16 13:59", False), ("2026-09-16 14:00", True),
        ("2026-09-16 17:59", True),  ("2026-09-16 18:00", False),
        ("2026-09-16 20:52", False), ("2026-09-16 02:00", False),
        ("2026-09-19 10:00", False), ("2026-09-20 15:00", False),  # 周末不是高峰
    ]
    ok = sum(is_peak(D(s)) == want for s, want in cases)
    for s, want in cases:
        got = is_peak(D(s))
        print("   %s %s → %s（期望 %s）" % ("✅" if got == want else "🔴", s,
                                          "高峰" if got else "空闲",
                                          "高峰" if want else "空闲"))
    print("\n   窗口自检 %d/%d" % (ok, len(cases)))
    return ok == len(cases)


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
        d = loads_lenient(s)
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
              every=10, on_row=None, thinking="disabled"):
    """thinking: "disabled"（默认，成批一律关）/ "enabled"。

    🔴 默认必须是关。`consult-two-models-on-rules` 定的：思考只留给商量规则，
       成批当判官/生成默认关；**能不能开由负控的数字决定，不由偏好决定**。
       参数化只是为了让"开 vs 关"能在同一批题目上被量出来（2026-08-17 补）。
    """
    import httpx
    announce_window()          # 🔴 无条件，花钱前必须看见价格档位
    env = load_env()
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
    print("■ 模型 %s  并发 %d  思考 %s" % (model, conc, thinking), flush=True)

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
                        "thinking": {"type": thinking},
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
                # 🔴 走到这儿有两种：抛异常（上面已计数）和 **`_parse` 返回 None**（没抛异常）。
                #    第二种原来一条都不计 ⇒ 22 批全没解析出来时报的是「完成 0 / 失败 0」，
                #    看上去像"什么都没发生"，实际是**协议对不上**（prompt 要数组、parser 要对象）。
                #    一个不报警的失败路径等于没有失败路径。
                async with lock:
                    if ctr["fail"] == 0 or ctr["done"] + ctr["fail"] < 3:
                        print("   ✗ 批 %d 解析不出来（prompt 与 parser 协议对不上？）" % i,
                              flush=True)
                    ctr["fail"] += 1
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


if __name__ == "__main__":
    import sys as _s
    _s.exit(0 if _selftest() else 1)
