#!/usr/bin/env python3
"""**槽值翻译的共用件**：一批法语短串 → 中文，可续跑、逐条核对、按原串存。2026-08-23。

═══ 为什么抽出来 ═══
`geo_translate_slots.py` 写完之后，姓氏/名字族要用**同一套**批调用逻辑
（分批 / 并发 / 续跑 / 缺条重排队 / 按原串落盘）。
🔴 复制一份 = `[[refactor-mindset-code-quality]]` 那次批评的形状
（同一个文件里两张西语地区表，译文没分叉纯属运气）。
⇒ 调用逻辑放这里，**每一族只自己写 prompt 和取数**。

═══ 这里保证的三件事 ═══
① **逐条核对**：请求里每个 `fr` 都必须在应答里出现 —— flash 会**静默丢批里的一部分**
   （it 阶段 5 实测日志失败 0、实际 2,069 条从没被答过）。缺的自动重排队。
② **答案按法语原串存**，不按下标 —— `[[model-answer-files-key-by-id]]`：
   按「第几条」存的答案，重跑时会把中文贴到别的条目上。
③ **可续跑**：已在落盘文件里的原串不再请求。
"""
import asyncio
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


def env():
    return dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines()
                if "=" in l and not l.startswith("#"))


def done_keys(out_path, land="fr"):
    """→ {落盘键: 记录}。坏行（末行截断等）跳过。

    `land` = 落盘按哪个字段存，见 `translate()` 里那一大段。默认 `fr`。
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


async def _ask(cl, key, sys_prompt, items, fields, think=False, key_field="fr",
               answer_field="zh"):
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
    out = {}
    for o in _loads(txt):
        if isinstance(o, dict) and key_field in o:
            # `answer_field` 默认 `zh`（翻译族，值是字符串）。
            # 裁决族的答案是**一张挂载表**（list），所以这里**原样存**，不转 str ——
            # 转 str 会把 `[{...}]` 变成一段没法再解析的文本。
            v = o.get(answer_field)
            out[str(o[key_field])] = "" if v is None else (
                v if not isinstance(v, (str, int, float)) else str(v))
    return out, (d.get("usage") or {}).get("total_tokens", 0)


async def _run(todo, key, sys_prompt, out_path, fields, keep, key_field="fr",
               answer_field="zh"):
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
                    got, tok = await _ask(cl, key, sys_prompt, ch, fields,
                                          key_field=key_field,
                                          answer_field=answer_field)
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
                            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fout.flush()
                stat["done"] += 1
                stat["tok"] += tok
                if stat["done"] % 5 == 0:
                    print("  [%d/%d] token %s  待补 %d  放弃 %d"
                          % (stat["done"], len(chunks), format(stat["tok"], ","),
                             stat["miss"], stat["gave_up"]))
                q.task_done()

        await asyncio.gather(*[asyncio.create_task(worker())
                               for _ in range(min(CONC, len(chunks)))])
    fout.close()
    return stat


def translate(items, sys_prompt, out_path, fields=("fr", "ctx"), keep=("fr", "kind", "n"),
              key_field="fr", answer_field="zh", land="fr"):
    """items = [{fr, …}]。只请求尚未落盘的。→ stat dict。

    `fields` = 发给模型的字段；`keep` = 落盘时保留的字段（答案字段自动加）。

    `key_field` = **应答按哪个字段认领**。默认 `fr`（短槽值，原串就是天然主键）。
    整句释义要用 `id` —— 法语原文太长，让模型原样回传一整句既费 token 又容易被它
    "顺手改一个字"导致认领不上。

    `land` = **落盘按哪个字段存**，默认 `fr`（`keep` 里必须有它）。
    默认这条是**翻译族的不变量**：同一句法语在全库永远只有一个中文，所以按原串
    落盘既能续跑又能天然去重。

    🔴 **判断族不能用这条不变量。** 判官的产物取决于 `(法语, 中文)` 这一**对**，
       而同一句法语配不同中文是存在的 —— 族 E 探针实测：98,305 条义项里有
       6,352 条的法语定义与别的义项**逐字相同但中文不同**（6.5%）。按 `fr` 落盘
       会让其中一条静默领走另一条的判断结果，而**产物正是一个比率**，
       这种污染不会报错、只会把数悄悄改掉。⇒ 那种任务传 `land="id"`。
       （`[[model-answer-files-key-by-id]]`：编号一律用数据库主键。）

    `answer_field` = 答案挂在应答对象的哪个键上。默认 `zh`（翻译族）。
    **裁决族传 `m`** —— 那一族的产物不是中文，是一张「哪条法语原文挂到哪条义项」的表；
    这个参数就是为了让裁决复用整套批调用/续跑/逐条核对，而不是再抄一份
    （`[[refactor-mindset-code-quality]]`）。
    """
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    got = done_keys(out_path, land)
    todo = [i for i in items if i[land] not in got]
    print("■ 槽值 %s 个；已翻 %s；待翻 %s"
          % (format(len(items), ","), format(len(got), ","), format(len(todo), ",")))
    if land not in keep:
        raise ValueError("keep 里必须有落盘键 %r" % land)
    if land != "fr":
        n = len({i[land] for i in items})
        if n != len(items):
            raise ValueError("落盘键 %r 在这批里不唯一（%d 个值 / %d 条）"
                             % (land, n, len(items)))
    if not todo:
        return {"done": 0, "tok": 0, "miss": 0}
    stat = asyncio.run(_run(todo, env()["DEEPSEEK_API_KEY"].strip(),
                            sys_prompt, out_path, list(fields), list(keep),
                            key_field=key_field, answer_field=answer_field))
    print("✓ 完成 %d 批 / token %s / 曾缺 %d 条（已重排队）"
          % (stat["done"], format(stat["tok"], ","), stat["miss"]))
    return stat
