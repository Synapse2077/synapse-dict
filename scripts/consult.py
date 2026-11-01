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
import contextlib
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

# 流式（B9②）：多久没收到一个字节算卡住／一次咨询总时长封顶
READ_IDLE = 300
TOTAL_CAP = 2400


def env():
    return dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines()
                if "=" in l and not l.startswith("#"))


class Broken(Exception):
    """流式请求半路断了 —— 带着**断在哪**：用时、离上一个字节多久、已收到的思考／正文字数、原始异常。

    🔴 B9②（2026-11-01）：原来是非流式，思考的整段时间里连接上**一个字节都没有**，
       ko 那轮豆包跑满 1200s 挂掉时只知道「超时」——分不出是「模型还在写」还是「连接早断了、空等 20 分钟」。
       流式之后两者看得见：`离上一个字节` 小 ⇒ 还在产出、是总时长不够；大 ⇒ 卡住了。
       已收到的正文不丢（`report` 落成 `.partial.md`）—— 那些 token 已经付过钱了。
    """
    def __init__(self, cause, elapsed, idle, reasoning, content, model):
        self.cause, self.elapsed, self.idle = cause, elapsed, idle
        self.reasoning, self.content, self.model = reasoning, content, model
        super().__init__("%s: %r｜用时 %.0fs｜离上一个字节 %.0fs｜已收思考 %d 字、正文 %d 字"
                         % (type(cause).__name__, cause, elapsed, idle, reasoning, len(content)))


async def ask_stream(cl, url, key, body, cap=None):
    """OpenAI 兼容接口的流式调用（deepseek 与方舟同一种 SSE）。→ (正文, usage, 实际模型)；半路断了 raise `Broken`。"""
    body = dict(body, stream=True, stream_options={"include_usage": True})
    cap = TOTAL_CAP if cap is None else cap
    t0 = last = time.time()
    content, reasoning, usage, model = [], 0, {}, "?"
    try:
        async with cl.stream("POST", url, headers={"Authorization": "Bearer " + key}, json=body) as r:
            if r.status_code != 200:
                raise RuntimeError("HTTP %s: %s" % (r.status_code, (await r.aread())[:200].decode("utf-8", "replace")))
            async for line in r.aiter_lines():
                last = time.time()
                # 总时长封顶放在**循环里**而不是外面套 `wait_for`：外面取消走的是 CancelledError，
                # 不经过下面的 `except`，断在哪就又丢了
                if last - t0 > cap:
                    raise TimeoutError("总时长超过 %ds 封顶" % cap)
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                d = json.loads(data)
                model = d.get("model") or model
                usage = d.get("usage") or usage
                for ch in d.get("choices") or []:
                    delta = ch.get("delta") or {}
                    reasoning += len(delta.get("reasoning_content") or "")
                    content.append(delta.get("content") or "")
    except Exception as ex:
        now = time.time()
        raise Broken(ex, now - t0, now - last, reasoning, "".join(content), model) from ex
    return "".join(content), usage, model


async def ask_deepseek(cl, e, text, think):
    body = {"model": "deepseek-v4-pro",
            "messages": [{"role": "system", "content": SYS},
                         {"role": "user", "content": text}],
            "temperature": 0,
            "thinking": {"type": "enabled" if think else "disabled"}}
    return await ask_stream(cl, "https://api.deepseek.com/chat/completions",
                            e["DEEPSEEK_API_KEY"].strip(), body)


def doubao_model(e, lite=False):
    """→ 豆包端点 id。抽成函数是为了 `--selftest` 能锁住「默认是 pro」（B8）。"""
    return e["DOUBAO_MODEL_ONLINE_LITE" if lite else "DOUBAO_SEED_2_1_PRO"].strip()


async def ask_doubao(cl, e, text, think, lite=False):
    # 🔴 2026-09-21 修：这里一直发的是 `DOUBAO_MODEL_ONLINE_LITE`，
    #    而用户 2026-08-01 定的规矩原文是「同时咨询豆包 **pro** 和 deepseek v4-pro」。
    #    ⇒ 脚本与规矩漂开了，而两边都没人报错：**咨询照常返回，只是档次不对**。
    #    咨询是「商量规则」，正是该用 pro 的那一类；lite 留成显式选项。
    model = doubao_model(e, lite)
    body = {"model": model,
            "messages": [{"role": "system", "content": SYS},
                         {"role": "user", "content": text}],
            "temperature": 0,
            "thinking": {"type": "enabled" if think else "disabled"}}
    return await ask_stream(cl, "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
                            e["ARK_API_KEY"].strip(), body)


def report(names, res, out, doc, t0, err=sys.stderr):
    """落盘 ＋ 打结果。→ 退出码：0 都回来了／2 两家只回来一家／1 全挂。

    🔴 B9（2026-10-27）：原来挂了一家照样退 0、只在 stderr 打一行 ⇒ 调用方默认拿到的是双份。
       而「两家独立一致」是这仓库反复引用的信号 —— **挂掉一家时必须显式降级**，不能当成「一家说了算」。
    """
    ok = 0
    for name, r in zip(names, res):
        p = out / ("%s.%s.md" % (doc.stem, name))
        if isinstance(r, Exception):
            # 🔴 2026-09-24：原来写的是 `%s % r`，而**超时类异常的 `str()` 是空串** ——
            #    ko 那轮豆包跑满 1200s 挂掉，打出来就是「🔴 doubao 失败：」后面什么都没有，
            #    我拿不到任何可诊断的东西，连"是超时还是 4xx"都分不出。
            #    ⇒ 打**类型名 ＋ repr**，空 `str()` 的异常也说得出自己是谁。
            #    ⚠️ 同一形状：`[[residual-bucket-is-not-evidence]]` 的反面 ——
            #      **"什么都没打印"被我读成了"没什么可说的"**，而它其实是信息丢了。
            if isinstance(r, Broken):
                print("🔴 %s 失败：%s" % (name, r), file=err)
                if r.content:
                    pp = out / ("%s.%s.partial.md" % (doc.stem, name))
                    pp.write_text("<!-- model: %s ｜ 🔴 未完成：%s -->\n%s" % (r.model, r, r.content),
                                  encoding="utf-8")
                    print("   已收到的正文落盘 → %s（不完整，不能当答案引用）" % pp, file=err)
            else:
                print("🔴 %s 失败：%s: %r（用时 %.0fs）"
                      % (name, type(r).__name__, r, time.time() - t0), file=err)
            continue
        content, usage, model = r
        # 答案文件第一行写明**实际是谁答的**（接口回报的 model），B8 那种档次漂移日后查得到
        p.write_text("<!-- model: %s -->\n%s" % (model, content), encoding="utf-8")
        ok += 1
        print("✓ %-7s %6d 字 → %s   model=%s tokens=%s" % (
            name, len(content), p, model, json.dumps(usage, ensure_ascii=False)))
    print("用时 %.0fs" % (time.time() - t0))
    if ok == len(names):
        return 0
    if ok == 0:
        print("🔴🔴 一家都没回来", file=err)
        return 1
    print("🔴🔴 **本轮不构成两家交叉验证**：只回来 %d/%d 家 —— 别把它当成「两家一致」引用"
          % (ok, len(names)), file=err)
    return 2


def selftest():
    """离线自检，一个请求都不发。锁住 B8（默认 pro）与 B9（失败分支说得出自己是谁／挂一家要降级）。"""
    import io, tempfile
    bad = []
    e = {"DOUBAO_SEED_2_1_PRO": "ep-pro ", "DOUBAO_MODEL_ONLINE_LITE": "ep-lite"}
    if doubao_model(e) != "ep-pro":
        bad.append("B8 默认豆包端点不是 pro：%r" % doubao_model(e))
    if doubao_model(e, lite=True) != "ep-lite":
        bad.append("B8 --lite 没走 lite")
    _td = tempfile.TemporaryDirectory()          # 2026-10-31：用完即删（原来每跑一次留一个目录）
    out = pathlib.Path(_td.name)
    doc = out / "q.md"
    for res, want_code, must in [
        ([("答", {}, "m1"), TimeoutError()], 2, ["TimeoutError", "不构成两家交叉验证"]),
        ([TimeoutError(), RuntimeError("HTTP 500")], 1, ["一家都没回来"]),
        ([("答", {}, "m1"), ("答", {}, "m2")], 0, []),
    ]:
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()):
            code = report(["v4pro", "doubao"], res, out, doc, time.time(), err=err)
        if code != want_code:
            bad.append("B9 退出码 %d ≠ %d（%s）" % (code, want_code, res))
        for m in must:
            if m not in err.getvalue():
                bad.append("B9 stderr 里没有「%s」：%r" % (m, err.getvalue()))
    if not (out / "q.v4pro.md").read_text(encoding="utf-8").startswith("<!-- model: m1 -->"):
        bad.append("B8 答案文件第一行没写实际模型")
    bad += asyncio.run(_stream_selftest(out, doc))
    for b in bad:
        print("🔴 " + b)
    print("✅ consult.py 自检通过（B8 端点／B9 失败降级／B9② 流式四种结局）" if not bad else "🔴 %d 项失败" % len(bad))
    return 1 if bad else 0




async def _stream_selftest(out, doc):
    """B9②：流式三种结局，用假的传输层，一个请求都不发。"""
    import io
    import httpx
    bad = []

    def sse(*objs):
        return [("data: " + json.dumps(o, ensure_ascii=False) + "\n\n").encode() for o in objs]

    ok_chunks = sse({"model": "m-x", "choices": [{"delta": {"reasoning_content": "想想"}}]},
                    {"model": "m-x", "choices": [{"delta": {"content": "答"}}]},
                    {"model": "m-x", "choices": [{"delta": {"content": "案"}}]},
                    {"model": "m-x", "choices": [], "usage": {"total_tokens": 7}}) + [b"data: [DONE]\n\n"]

    async def gen(chunks, then=None, delay=0.0):
        for c in chunks:
            if delay:
                await asyncio.sleep(delay)
            yield c
        if then:
            raise then

    def client(handler):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    # ① 正常：正文拼对、usage／实际模型取到
    async with client(lambda req: httpx.Response(200, content=gen(ok_chunks))) as cl:
        got = await ask_stream(cl, "https://x/", "k", {})
    if got != ("答案", {"total_tokens": 7}, "m-x"):
        bad.append("B9② 流式正常结局拼错：%r" % (got,))
    # ② 半路断（读超时）：说得出断在哪、已收的正文落成 .partial.md、退出码 2
    async with client(lambda req: httpx.Response(200, content=gen(
            ok_chunks[:2], then=httpx.ReadTimeout("")))) as cl:
        try:
            await ask_stream(cl, "https://x/", "k", {})
            r2 = None
        except Broken as ex:
            r2 = ex
    if r2 is None or r2.content != "答" or r2.reasoning != 2:
        bad.append("B9② 半路断没带进度：%r" % (r2,))
    else:
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()):
            code = report(["v4pro", "doubao"], [("答", {}, "m1"), r2], out, doc, time.time(), err=err)
        for m in ("ReadTimeout", "离上一个字节", "已收思考 2 字", ".partial.md"):
            if m not in err.getvalue():
                bad.append("B9② stderr 里没有「%s」：%r" % (m, err.getvalue()))
        pp = out / ("%s.doubao.partial.md" % doc.stem)
        if code != 2 or not pp.exists() or "未完成" not in pp.read_text(encoding="utf-8"):
            bad.append("B9② 半路断：退出码 %d／partial 文件 %s" % (code, pp.exists()))
    # ③ 总时长封顶：在循环里触发，同样带进度
    async with client(lambda req: httpx.Response(200, content=gen(ok_chunks, delay=0.02))) as cl:
        try:
            await ask_stream(cl, "https://x/", "k", {}, cap=0.03)
            bad.append("B9② 总时长封顶没触发")
        except Broken as ex:
            if not isinstance(ex.cause, TimeoutError) or "封顶" not in str(ex):
                bad.append("B9② 封顶触发了但没说清：%r" % ex)
    # ④ HTTP 错误：状态码与响应体前 200 字进消息
    async with client(lambda req: httpx.Response(429, content=b"rate limited")) as cl:
        try:
            await ask_stream(cl, "https://x/", "k", {})
            bad.append("B9② HTTP 429 没报错")
        except Broken as ex:
            if "429" not in str(ex) or "rate limited" not in str(ex):
                bad.append("B9② HTTP 错误没带状态码／响应体：%s" % ex)
    return bad


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("doc", nargs="?")
    ap.add_argument("--selftest", action="store_true", help="离线自检，不发请求")
    ap.add_argument("--out")
    ap.add_argument("--no-think", action="store_true")
    ap.add_argument("--only", choices=("v4pro", "doubao"), default="",
                    help="只问一家（默认两家并行）")
    ap.add_argument("--lite", action="store_true",
                    help="豆包走 lite 端点（默认 pro —— 商量规则用 pro 是用户定的）")
    ap.add_argument("--big", action="store_true",
                    help="材料超过 %d KB 时必须显式加上，见文件头「豆包的边界」" % MAX_KB)
    a = ap.parse_args()
    if not a.doc:
        ap.error("要给材料文件")

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
    # B8：发出去之前把**实际端点**说出来 —— 档次漂移不报错，只能靠看得见
    print("■ v4pro → deepseek-v4-pro ／ doubao → %s%s" % (
        doubao_model(e, a.lite), "（--lite）" if a.lite else "（pro）"))

    # 流式之后 read 超时量的是「多久没收到一个字节」（卡住），不再是总时长；总时长另封顶。
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=READ_IDLE)) as cl:
        t0 = time.time()
        # ⚠️ 协程要**按需创建**：先建两个再丢掉一个，会留下 "never awaited" 警告，
        #    而那条警告长得跟"请求失败了"很像。
        makers = {"v4pro": lambda: ask_deepseek(cl, e, text, think),
                  "doubao": lambda: ask_doubao(cl, e, text, think, a.lite)}
        names = [a.only] if a.only else list(makers)
        res = await asyncio.gather(*(makers[n]() for n in names),
                                   return_exceptions=True)

    # 🔴 建目录要在**写之前**：2026-09-24 两家都答完了、写盘时 `FileNotFoundError`，
    #    一次咨询的钱白花。失败点在最后一步，而最后一步之前的东西都已经付过钱了。
    out.mkdir(parents=True, exist_ok=True)
    sys.exit(report(names, res, out, doc, t0))


if __name__ == "__main__":
    # 自检要自己开事件循环（流式那几项是协程），不能套在 main() 的循环里
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    asyncio.run(main())
