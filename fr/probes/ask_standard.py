#!/usr/bin/env python3
"""问模型：你知道 GB/T 17693.2 吗？说明了之后你的答案会变吗？2026-08-24。

═══ 为什么问这个 ═══
我给市镇名翻译写的 prompt 里只说了「用《世界地名翻译大辞典》的常规用字」，
**没点名国家标准**。用户提出：模型可能本来就知道这个标准。

`[[prompt-beats-model-choice]]`：**选模型/造工具之前先问「这个差距是不是提示能补的」**。
我两次差点因为「模型能力不行」去买贵的，两次都是我自己的问题。
这次更甚 —— 我已经动手造译写器了，却没先问过模型。

═══ 三问 ═══
A. 直接问它知不知道该标准、能不能复述规则（**这是咨询，一问一答，开思考没关系**）
B. 拿我译写器与模型分歧最大的那批，**明确要求按标准**重译，看答案变不变
C. 同一批，让它**逐条说明依据哪条规则**，我核它是不是真在用规则而不是编

跑：python3 -u probes/ask_standard.py > log 2>&1 &
"""
import asyncio
import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths                              # noqa: E402
from pipeline import slot_translate       # noqa: E402

DIFF = paths.WORK / "geo" / "translit_diff.jsonl"

Q_KNOW = """请直接回答，不要客套：
1. 你知道中国国家标准 GB/T 17693.2-1999《外语地名汉字译写导则·法语》吗？
2. 如果知道，请复述它的**核心机制**（表怎么组织、词尾 -e 怎么处理、
   哪些词尾有固定译法、ville 怎么译、鼻化元音什么时候失效）。
3. 它与《世界地名译名词典》的关系是什么？哪个优先？
4. 你在做法语地名音译时，实际上是按这个标准推的，还是按记忆里见过的译名？
   **请诚实回答**，这决定了我要不要在提示里显式要求你套表。"""

SYS_STD = """你在给一部法汉词典做**法国市镇名**的中文译名。
🔴 **严格按中国国家标准 GB/T 17693.2-1999《外语地名汉字译写导则·法语》译写**：
· 按该标准的辅音×元音音节表逐音节取字
· 固定词尾按标准规定：-be布 -pe普 -de德 -te特 -ge日 -gue格 -que克 -ce斯 -ve沃
  -fe夫 -ze兹 -se斯 -che什 -je日 -me姆 -ne讷 -gne涅 -le勒 -re尔 -ille耶
· ville 译「维尔」，其派生形式同（Conteville→孔特维尔）
· 词尾哑辅音不译；h 不发音
· 鼻化元音组合后接元音字母、或 -m 后接 m / -n 后接 n 时，鼻化失效
· 避免望文生义：词首「东南西」用「栋楠锡」，词尾「海」用「亥」
⚠️ 但若该地名已被《世界地名译名词典》或新华社历史资料库收录（如 Paris→巴黎、
   Marseille→马赛、Lyon→里昂），**沿用约定译名，不套表**。

输入 JSON 数组，每项有 `fr`。输出**只有** JSON 数组，每项
{"fr": 原样, "zh": "译名", "why": "依据哪条（约定译名/音节表/固定词尾/…），不超过12字"}
不要围栏、不要解释。"""


async def ask(cl, key, sys_p, user, think):
    body = {"model": slot_translate.MODEL, "temperature": 0, "stream": False,
            "messages": ([{"role": "system", "content": sys_p}] if sys_p else []) +
                        [{"role": "user", "content": user}]}
    if not think:
        body["thinking"] = {"type": "disabled"}
        body["reasoning_effort"] = "none"
    r = await cl.post(slot_translate.URL, headers={"Authorization": "Bearer " + key},
                      json=body, timeout=600)
    if r.status_code != 200:
        return None, 0
    d = r.json()
    return d["choices"][0]["message"]["content"], (d.get("usage") or {}).get("total_tokens", 0)


async def main():
    import httpx
    key = slot_translate.env()["DEEPSEEK_API_KEY"].strip()
    diffs = [json.loads(l) for l in io.open(DIFF, encoding="utf-8")][:40]

    async with httpx.AsyncClient() as cl:
        # A. 咨询：一问一答，token 可忽略 ⇒ **这里开思考是允许的**
        txt, tok = await ask(cl, key, None, Q_KNOW, think=True)
        print("═══ A. 它知道这个标准吗（token %s）═══\n%s\n" % (format(tok, ","), txt))

        # B. 明确要求套表后重译（关思考，与正式跑批同条件）
        items = [{"fr": d["fr"]} for d in diffs]
        txt2, tok2 = await ask(cl, key, SYS_STD,
                               json.dumps(items, ensure_ascii=False), think=False)
        print("═══ B. 明确要求按标准后（token %s）═══" % format(tok2, ","))
        try:
            got = {o["fr"]: o for o in json.loads(
                re.sub(r"^```(?:json)?|```$", "", txt2.strip(), flags=re.M).strip())}
        except Exception as e:
            print("解析失败：%s\n%s" % (e, txt2[:400]))
            return
        print("%-26s %-13s %-13s %-13s %s" % ("法语", "原译(无标准)", "我的译写器", "点名标准后", "依据"))
        print("-" * 96)
        chg = agree_std = agree_old = 0
        for d in diffs:
            o = got.get(d["fr"])
            new = (o or {}).get("zh", "—")
            why = (o or {}).get("why", "")
            if new != d["model"]:
                chg += 1
            if new == d["std"]:
                agree_std += 1
            if new == d["model"]:
                agree_old += 1
            print("%-26s %-13s %-13s %-13s %s"
                  % (d["fr"][:26], d["model"][:13], d["std"][:13], new[:13], why[:16]))
        n = len(diffs)
        print("\n点名标准后改了 %d/%d；与我的译写器一致 %d；与原译一致 %d"
              % (chg, n, agree_std, agree_old))


if __name__ == "__main__":
    asyncio.run(main())
