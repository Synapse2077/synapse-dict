#!/usr/bin/env python3
"""**槽值翻译的共用件（de）**：一批德语串 → 中文，可续跑、逐条核对、按键落盘。

2026-09-03 从 `pt/pipeline/slot_translate.py` 移植（那份又源自 fr 2026-08-23）。
**逐语种各存一份是有意的**（`[[multilang-decoupling-essence]]`：按语种解耦、互不引用），
不是复制粘贴的懒惰 —— 跨语种共享会让某一门的判据改动静默波及另外五门。
⚠️ 与之相对，**同一门语言内部不许有第二份**：每一族只自己写 prompt 和取数，
   分批／并发／续跑／缺条重排队／落盘一律走这里
   （`[[refactor-mindset-code-quality]]`：同一文件两张西语地区表那次）。

═══ 这里保证的四件事 ═══
① **逐条核对**：请求里每个键都必须在应答里出现 —— flash 会**静默丢批里的一部分**
   （it 阶段 5 实测日志失败 0、实际 2,069 条从没被答过）。缺的自动重排队。
② **重排队会收敛**：对半切 + 封顶次数 + 到顶大声放弃，不静默丢也不无限重试
   （`[[retry-must-converge-or-drop-loud]]`）。
③ **答案按键存，不按下标** —— `[[model-answer-files-key-by-id]]`：
   按「第几条」存的答案，重跑时会把中文贴到别的条目上。
   ⚠️ 释义族的键必须是 `sense.id`（数据库主键），不是德语原串：
     同一句德语原文在库里出现多次（专名族尤甚，`deutschsprachiger Nachname`
     一句就挂着 1,534 个不同的姓），按原串存会把它们强行合并成一条。
④ **`think=False` 是硬默认**（`[[batch-never-enables-thinking]]`）：翻译不是推导型任务，
   实测开思考 141.4 vs 关 58.2 token/条。要开必须显式传，且只该在小样咨询里传。
"""
import asyncio
# ⚠️ 本文件是 `de/pipeline/slot_translate.py` 的**拷贝**（2026-09-07 复制到 en/）——
#    铁律①按语种解耦、互不引用；宁可重复不要耦合。
#    de 版里那些"德语原文/法语定义"的举例保持原样不改：它们是**判据的来历**，
#    改成英语会把当初为什么这么定的证据抹掉。en 只改默认字段名。
import datetime as _dt
import json
import re
from pathlib import Path

MODEL = "deepseek-v4-flash"
URL = "https://api.deepseek.com/chat/completions"
# 实测（关思考，真数据）：批 80/160/320 每条 58.2 / 56.8 / 61.3 token，**缺条全 0**。
# 成本按**请求数**走不按条数走 ⇒ 批越大越省；上限受「flash 会静默丢批里一部分」约束
# （it 阶段 5 实测丢 2,069 条），所以取 160 而不是 320，且逐条核对照留。
CHUNK = 160
CONC = 8
# 重试封顶。每次对半切，5 次能把 160 条切到 5 条 —— 收敛而不是原地打转。
RETRY = 5

ROOT = Path(__file__).resolve().parent.parent.parent


# ══════════════════════════════════════════════ 计费时段（北京时间）
# 🔴🔴 **这条规则我判错过几次，所以它不能只写在文档里。**
#    用户 2026-08-30：「我看你高峰低谷都没搞清楚，都这么几次了，
#    deepseek 是中国企业，你得按照北京时间」。
#
#    错法有三步，每一步都可以避免：
#      ① 用 **UTC** 推一家中国公司的时段 —— 换算对了也多一次出错机会
#      ② 结论建在**仓库里一行旧笔记**上，没回源
#      ③ 被质疑后用「以你的账单为准」把判断推回给用户
#
#    ⇒ `[[lesson-must-become-mechanism]]`：学到教训的交付物是**一道会自己响的闸**，
#      不是一条记忆。判据是「我完全忘了这件事，还会不会被提醒」。
#
#    官方规则（北京时间 UTC+8）：
#        高峰  周一至周五 09:00–12:00、14:00–18:00
#        空闲  其余全部时间（**含整个周末**）—— 价格减半
CST = _dt.timezone(_dt.timedelta(hours=8))


def is_peak(now=None):
    """→ 现在是不是高峰（全价）。北京时间，周末一律不是。"""
    t = (now or _dt.datetime.now(CST)).astimezone(CST)
    if t.weekday() >= 5:
        return False
    m = t.hour * 60 + t.minute
    return 9 * 60 <= m < 12 * 60 or 14 * 60 <= m < 18 * 60


def announce_window():
    """跑批前打出来。**花钱之前必须让人看见现在是什么价。**"""
    t = _dt.datetime.now(CST)
    pk = is_peak(t)
    print("■ 北京时间 %s 星期%s ⇒ %s"
          % (t.strftime("%F %H:%M"), "一二三四五六日"[t.weekday()],
             "🔴 **高峰时段，全价**（空闲时段是它的一半）" if pk else "✅ 空闲时段，半价"))
    return pk


def env():
    return dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines()
                if "=" in l and not l.startswith("#"))


def done_keys(out_path, land="id"):
    """→ {落盘键: 记录}。坏行（末行截断等）跳过。

    `land` = 落盘按哪个字段存，见 `translate()` 里那一大段。默认 `de`。
    """
    p = Path(out_path)
    if not p.exists():
        return {}
    got = {}
    for ln in p.open(encoding="utf-8"):
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if land in o:
            got[o[land]] = o
    return got


def _loads(txt):
    """带容错的 JSON 解析。

    🔴 全量那轮 1,643 批里 **66 批因为一个坏逗号整批丢掉**（约 8,000 条），
       而丢批走的是 `except` 分支 —— **不重排队、静默跳过**。
       `model_bakeoff.parse` 里本来就写过一份容错解析器，
       这个共用件却没用上（`[[refactor-mindset-code-quality]]` 的同一个形状：
       同一段逻辑写了两份，只有一份是好的）。
    ⚠️ 兜底是**逐条抠**：整体解析不了时，退到按 `{...}` 单元提取，
       坏的那一条丢掉、好的全留下 —— 一颗老鼠屎不该毁掉一整批。
    """
    for fix in (lambda x: x,
                lambda x: re.sub(r"}\s*\n\s*(\{)", r"},\n\1", x),   # 条目间缺逗号
                lambda x: re.sub(r",\s*([}\]])", r"\1", x),         # 尾逗号
                lambda x: x[:x.rfind("}") + 1] + "]"):              # 被截断
        try:
            v = json.loads(fix(txt))
            if isinstance(v, list):
                return v
        except Exception:
            continue
    out = []
    for m in re.finditer(r"\{[^{}]*\}", txt):
        try:
            out.append(json.loads(m.group(0)))
        except Exception:
            pass
    return out


async def _ask(cl, key, sys_prompt, items, fields, think=False, key_field="de",
               answer_field="zh", echo_field=None):
    # 🔴🔴 **跑批一律关思考**。用户 2026-08-15 定的规矩（豆包那次）：
    #    开思考只用于**咨询**（一问一答，token 可忽略），**跑批不许开**。
    #    2026-08-23 我违反了：地名族 2.4M + 姓名族 15.4 万 token 全是开着思考跑的，
    #    我从头到尾没检查过这个开关 —— 用户当天账单 11 块里有这一份。
    #    实测同一批 80 条真数据：**开 141.4 token/条 vs 关 58.2**。
    #    ⇒ 做成**硬默认**，不靠我记得。要开必须显式传 think=True，且只该在小样咨询里传。
    body = {"model": MODEL, "temperature": 0, "stream": False,
            "messages": [{"role": "system", "content": sys_prompt},
                         {"role": "user", "content": json.dumps(
                             # 字段**缺就不发** —— 可选字段（如 `hint`）只挂在命中的那些条上，
                             # 没命中的不该占 token，也不该因为缺键就崩。
                             [{k: i[k] for k in fields if k in i} for i in items],
                             ensure_ascii=False)}]}
    if not think:
        body["thinking"] = {"type": "disabled"}
        body["reasoning_effort"] = "none"
    r = await cl.post(URL, headers={"Authorization": "Bearer " + key}, json=body, timeout=300)
    if r.status_code != 200:
        raise RuntimeError("HTTP %s: %s" % (r.status_code, r.text[:200]))
    d = r.json()
    txt = d["choices"][0]["message"]["content"].strip()
    txt = re.sub(r"^```(?:json)?|```$", "", txt, flags=re.M).strip()
    out, echo = {}, {}
    for o in _loads(txt):
        if isinstance(o, dict) and key_field in o:
            # 🔴🔴 `echo_field`：让模型把**原文的一小段**抄回来，落盘时一并存。
            #    用途是核对「id 与内容有没有配错行」—— 2026-09-09 en 例句层实测
            #    有 134 片整批错开一位，而 `key_field` 是对的、所有计数闸全绿。
            #    **主键保证认领得上，不保证配对是对的。**
            if echo_field and echo_field in o:
                echo[str(o[key_field])] = o[echo_field]
            # `answer_field` 默认 `zh`（翻译族，值是字符串）。
            # 裁决族的答案是**一张挂载表**（list），所以这里**原样存**，不转 str ——
            # 转 str 会把 `[{...}]` 变成一段没法再解析的文本。
            v = o.get(answer_field)
            out[str(o[key_field])] = "" if v is None else (
                v if not isinstance(v, (str, int, float)) else str(v))
    u = d.get("usage") or {}
    # 🔴 入/出必须**分开记**：DeepSeek flash 入 $0.44/M、出 $1.32/M，差 3 倍。
    #    只记 total 就报不出价 —— 只能给一个 3 倍宽的区间。
    return out, echo, (u.get("total_tokens", 0),
                       u.get("prompt_tokens", 0), u.get("completion_tokens", 0))


async def _run(todo, key, sys_prompt, out_path, fields, keep, key_field="de",
               answer_field="zh", think=False, echo_field=None):
    import httpx
    chunks = [todo[i:i + CHUNK] for i in range(0, len(todo), CHUNK)]
    q = asyncio.Queue()
    for c in chunks:
        q.put_nowait((c, 0))                                          # (这批, 已试次数)
    stat = {"done": 0, "tok": 0, "miss": 0, "gave_up": 0}
    lock = asyncio.Lock()
    fout = Path(out_path).open("a", encoding="utf-8")

    def requeue(items, att, why):
        """🔴 2026-08-26 修：原来两条路径都是错的 ——
        ① 异常路径 `task_done(); continue` **静默丢批**（例句族 66 批 503 = 2,640 条就这么没的）；
        ② 缺答路径把 `miss` **原样**塞回队列，模型答不出这批就**永远答不出** ⇒ 无限重试
           （例句族最后 42 条空转到 [105/66]，token 一直烧，答案文件一行不动）。
        ⇒ 现在：**重试必须收敛** —— 每次对半切（批小了模型才可能答得出），
          且封顶 `RETRY` 次，到顶就认输并**打出来**，不再假装还在进行。"""
        if att >= RETRY:
            stat["gave_up"] += len(items)
            print("  ✗ 放弃 %d 条（试了 %d 次·%s）：%s"
                  % (len(items), att, why, str(items[0].get(key_field))[:40]))
            return
        if len(items) > 1:
            h = len(items) // 2
            q.put_nowait((items[:h], att + 1))
            q.put_nowait((items[h:], att + 1))
        else:
            q.put_nowait((items, att + 1))

    async with httpx.AsyncClient() as cl:
        async def worker():
            while True:
                try:
                    ch, att = q.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    got, echo, tok3 = await _ask(
                        cl, key, sys_prompt, ch, fields, key_field=key_field,
                        answer_field=answer_field, think=think,
                        echo_field=echo_field)
                except Exception as e:
                    requeue(ch, att, str(e)[:60])                      # ← 不再静默丢
                    q.task_done()
                    continue
                miss = [i for i in ch if str(i[key_field]) not in got]   # ① 逐条核对
                if miss:
                    stat["miss"] += len(miss)
                    requeue(miss, att, "模型没答这几条")
                async with lock:
                    for i in ch:
                        if str(i[key_field]) in got:                  # ② 按原串存
                            rec = {k: i[k] for k in keep}
                            rec[answer_field] = got[str(i[key_field])]
                            if echo_field and str(i[key_field]) in echo:
                                rec[echo_field] = echo[str(i[key_field])]
                            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fout.flush()
                stat["done"] += 1
                tok, pin, pout = tok3
                stat["tok"] += tok
                stat["tok_in"] = stat.get("tok_in", 0) + pin
                stat["tok_out"] = stat.get("tok_out", 0) + pout
                if stat["done"] % 5 == 0:
                    print("  [%d/%d] token %s  待补 %d  放弃 %d"
                          % (stat["done"], len(chunks), format(stat["tok"], ","),
                             stat["miss"], stat["gave_up"]))
                q.task_done()

        await asyncio.gather(*[asyncio.create_task(worker())
                               for _ in range(min(CONC, len(chunks)))])
    fout.close()
    return stat


def translate(items, sys_prompt, out_path, fields=("en", "word", "pos"),
              keep=("id", "word"), key_field="id", answer_field="zh",
              land="id", think=False, echo_field=None):
    """items = [{fr, …}]。只请求尚未落盘的。→ stat dict。

    `fields` = 发给模型的字段；`keep` = 落盘时保留的字段（答案字段自动加）。

    `key_field` = **应答按哪个字段认领**。默认 `de`（短槽值，原串就是天然主键）。
    整句释义要用 `id` —— 德语原文太长，让模型原样回传一整句既费 token 又容易被它
    "顺手改一个字"导致认领不上。

    `land` = **落盘按哪个字段存**，默认 `de`（`keep` 里必须有它）。
    默认这条是**翻译族的不变量**：同一句德语在全库永远只有一个中文，所以按原串
    落盘既能续跑又能天然去重。

    🔴 **判断族不能用这条不变量。** 判官的产物取决于 `(法语, 中文)` 这一**对**，
       而同一句德语配不同中文是存在的 —— 族 E 探针实测：98,305 条义项里有
       6,352 条的法语定义与别的义项**逐字相同但中文不同**（6.5%）。按 `fr` 落盘
       会让其中一条静默领走另一条的判断结果，而**产物正是一个比率**，
       这种污染不会报错、只会把数悄悄改掉。⇒ 那种任务传 `land="id"`。
       （`[[model-answer-files-key-by-id]]`：编号一律用数据库主键。）

    `answer_field` = 答案挂在应答对象的哪个键上。默认 `zh`（翻译族）。
    **裁决族传 `m`** —— 那一族的产物不是中文，是一张「哪条法语原文挂到哪条义项」的表；
    这个参数就是为了让裁决复用整套批调用/续跑/逐条核对，而不是再抄一份
    （`[[refactor-mindset-code-quality]]`）。
    """
    # 🔴🔴 **应答键必须也在发出去的字段里** —— 2026-09-07 en 1.5c 切片当场栽了：
    #    我把 `key_field` 改成 `id`（主键，照 `[[model-answer-files-key-by-id]]`），
    #    却没把 `id` 加进 `fields` ⇒ **模型从没收到过 id，只能瞎编**。
    #    后果不是"没结果"，是**最坏的那种**：编出来的数字碰巧撞上真主键就落盘，
    #    于是 `portmanteau` 形容词义项（"由两个词合成的"）被写成「小杯；小罐」——
    #    中文贴到了别的义项上。2,000 条只落 1 条，还是错的，烧掉 175 万 token。
    #    ⇒ 判据做成机制：**发不出去就不许当键**。
    if key_field not in fields:
        raise ValueError(
            "key_field=%r 不在 fields=%r 里 —— 模型收不到这个字段就没法原样回传，"
            "只会瞎编，编中了就是把答案贴到别的条目上。把它加进 fields。"
            % (key_field, tuple(fields)))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    got = done_keys(out_path, land)
    todo = [i for i in items if i[land] not in got]
    print("■ 槽值 %s 个；已翻 %s；待翻 %s"
          % (format(len(items), ","), format(len(got), ","), format(len(todo), ",")))
    if land not in keep:
        raise ValueError("keep 里必须有落盘键 %r" % land)
    if land != "__never__":
        n = len({i[land] for i in items})
        if n != len(items):
            raise ValueError("落盘键 %r 在这批里不唯一（%d 个值 / %d 条）"
                             % (land, n, len(items)))
    if not todo:
        return {"done": 0, "tok": 0, "miss": 0}
    announce_window()
    if think:
        # 🔴 开思考是**例外**，必须在日志里留痕 —— 用户 2026-08-15 定「跑批一律关」，
        #    我 8-23 违反过一次而且是用户看账单才发现的（`[[batch-never-enables-thinking]]`）。
        #    这里不拦（判据是「任务是不是推导型」，对齐裁决是），但**大声说出来**。
        print("⚠️ **本轮开了思考**（跑批默认关）。判据：这是推导型任务（对齐裁决），"
              "不是翻译。见 `[[llm-as-evaluator-discipline]]` ⑦。")
    stat = asyncio.run(_run(todo, env()["DEEPSEEK_API_KEY"].strip(),
                            sys_prompt, out_path, list(fields), list(keep),
                            key_field=key_field, answer_field=answer_field,
                            think=think, echo_field=echo_field))
    print("✓ 完成 %d 批 / token %s（入 %s ／ 出 %s）/ 曾缺 %d 条（已重排队）"
          % (stat["done"], format(stat["tok"], ","),
             format(stat.get("tok_in", 0), ","), format(stat.get("tok_out", 0), ","),
             stat["miss"]))
    return stat
