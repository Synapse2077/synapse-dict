#!/usr/bin/env python3
"""en 音标归一规则的**双家评审** —— 豆包 pro + DeepSeek v4-pro，并行、各自独立。2026-08-01。

用户要求：关键判断与重要规则的编写不能独断，必要时同时咨询两家，最终决断权在我。

═══ 🔴 为什么这次比 es 那次更需要 ═══
es 的 coda 规则落库前有**西语版可回核**，拿到了硬验收（46.7 万双源词，修好 5,647、改坏 0）。
**en 没有第二权威源**（维基体系只能补 0.8%）。落库前我手上的 17 个测试 + 7/7 变异，
**全是在验「代码是否实现了我定的规则」，没有一样在验「我定的规则对不对」**。
→ 所以两家的意见这次只能作参考，**拿不到 es 那种精确率打分**。别把它们的结论当真值。

═══ 遵守判官纪律（llm-as-evaluator-discipline）═══
⑦ 两家都**开思考**（推导型任务）；两家**并行**发。
⑧ 把本词典的约定与**用户画像**（中国的英语学习者）明确写进 prompt。
⑨ 材料标题不写结论；三类样本（改了的 / 故意不改的 / 越界标记的）混排。
⑩ 只问「规则有没有洞」「该跟哪个约定」，不问逐条事实。

用法（在 en/ 目录）：
  python3 probes/review_ipa_norm.py --build
  python3 probes/review_ipa_norm.py --run
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import asyncio
import json
import random
import re
import sqlite3
import time

import httpx

import paths
import ipa_norm as N

OUT = paths.WORK / "runs" / "en_ipa_norm_review.json"

RULE_DOC = """【本词典的英语音标现状与约定】
· 目标用户：**中国的英语学习者**，产品形态是划词弹窗（选中单词，弹出释义+音标）。
· 音标分两列：`phonetic_uk`（英式，111,076 行）与 `phonetic_us`（美式，110,089 行），
  数据来自英文维基词典。存裸串，展示层再加斜杠。
· 另有一列 ECDICT 遗留音标（370,203 行，90 年代教材记法，已判定无参考价值，保留不用）。
· **本词典没有第二个权威源可以回核英语音标**。

【正在评审的归一规则】
判据：**归一之后，源头原本的陈述还能不能从新值复原？**能→归一；不能→一个字节都不动，
呈现方式交展示层。据此分两类：

A. 归一（认为可复原、无损）
   1) 删音节点 `.`                   uk 19,932 行 / us 21,542 行
   2) 删连结弧 `͡`（d͡ʒ→dʒ）          5,979 / 6,479
   3) 删非成音节符 `̯`（eɪ̯→eɪ）       710 / 649
   4) 删送气符 `ʰ`（kʰæti→kæti）        53 / 95
   5) 删跨词连接符 `‿`                 133 / 135
   6) 暗 l `ɫ` → `l`                   213 / 122
   7) ASCII `g` → IPA `ɡ`(U+0261)        3 / 3
   8) **`r` → `ɹ`**                 11,500 / 20,886

B. 不动（认为是真信息，压平即替源头下断言）
   1) 可选音段 `(…)`：`əˈbæn.d(ə)n.m(ə)nt`、`ˈfɑː.ðə(ɹ)`、`əˈbeɪ.ən(t)s`   9,377 / 2,900
   2) 成音节辅音 `̩`：`əˈbleɪ.ʃn̩`、`ˈeɪ.bl̩`                              1,362 / 1,351
   3) 闪音 `ɾ`：`ˈbʌɾɚ`(butter) / `ˈlæɾɚ`(ladder)                            35 / 176
   4) 喉塞 `ʔ`                                                              50 / 66

C. 只标记不修改：不属于英语音位清单的字符（uk 315 / us 350 行），
   多为 `əɖvɵˈkeʈ`(advocate)、`ˈɑːχ.mɛd` 这类。"""

SYS = """你是英语语音学与词典编纂专家。下面给你一部面向中国英语学习者的词典正在使用的
音标归一规则，以及它在真实数据上的一批输出。严格输出 JSON：

{
 "r_vs_turned_r": {
   "recommend": "r" 或 "ɹ",
   "why": "理由，两三句",
   "confidence": "high|medium|low"
 },
 "rule_holes": [
   {"issue":"规则的什么情况没考虑到","example_words":["真实英语单词1","单词2"],
    "why":"为什么会出错","severity":"high|medium|low"}
 ],
 "misclassified": [
   {"item":"规则里的哪一条（如 A6 或 B2）","should_be":"A(归一) 或 B(不动)","why":"理由"}
 ],
 "wrong_outputs": [ {"i":样本序号,"should_be":"你认为正确的值","why":"理由"} ]
}

要点：
- `r_vs_turned_r` 是本次最大的一块（3.2 万行）。请特别考虑：维基词典用 ɹ，
  而剑桥/牛津学习词典与中国英语教材普遍用 r。你的建议针对**中国学习者**这个用户群。
- rule_holes 必须给真实英语单词作反例；举不出词就别写这条。
- misclassified 用来指出「A 类里其实有该归 B 的」或反之。没有就给空数组。
- wrong_outputs 只标你确信写错的；没有就给空数组。别凑数。
- 不要评论"要不要加斜杠""要不要分英美两列"这些已定的产品选择。"""


def load_env():
    env = {}
    for ln in open(paths.ENV, encoding="utf-8"):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.strip().split("=", 1)
            env[k] = v
    return env


def loads_lenient(s):
    s = re.sub(r"^```(json)?|```$", "", s.strip(), flags=re.M).strip()
    if "{" in s:
        s = s[s.find("{"):s.rfind("}") + 1]
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        f = re.sub(r'}\s*\n\s*(")', r'},\n\1', s)
        return json.loads(re.sub(r',\s*([}\]])', r'\1', f))


def build(seed=7):
    random.seed(seed)
    conn = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT word, phonetic_uk, phonetic_us FROM stardict WHERE qual IN ('core','good') "
        "AND (TRIM(COALESCE(phonetic_uk,''))<>'' OR TRIM(COALESCE(phonetic_us,''))<>'')"
    ).fetchall()
    conn.close()
    changed, kept, flagged = [], [], []
    for w, uk, us in rows:
        for col, v in (("uk", uk), ("us", us)):
            if not (v or "").strip():
                continue
            n = N.normalize(v)
            if N.non_english(n):
                flagged.append((w, col, v, n))
            elif n != v:
                changed.append((w, col, v, n))
            elif any(ch in v for ch in "()̩ɾʔ"):
                kept.append((w, col, v, n))
    pick = (random.sample(changed, min(26, len(changed)))
            + random.sample(kept, min(14, len(kept)))
            + random.sample(flagged, min(6, len(flagged))))
    random.shuffle(pick)
    return [{"i": i, "词": w, "列": col, "原值": v, "本词典输出": n}
            for i, (w, col, v, n) in enumerate(pick, 1)]


async def ask_v4pro(key, payload):
    async with httpx.AsyncClient(timeout=900) as cl:
        r = await cl.post("https://api.deepseek.com/chat/completions",
                          headers={"Authorization": f"Bearer {key}"},
                          json={"model": "deepseek-v4-pro",
                                "messages": [{"role": "system", "content": SYS},
                                             {"role": "user", "content": payload}],
                                "temperature": 0,
                                "response_format": {"type": "json_object"},
                                "thinking": {"type": "enabled"},
                                "stream": False})
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        d = json.loads(r.text.lstrip())
        return d["choices"][0]["message"]["content"], d.get("usage") or {}


async def ask_doubao(env, payload):
    from volcenginesdkarkruntime import AsyncArk
    cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=900)
    r = await cl.chat.completions.create(
        model=env["DOUBAO_SEED_2_1_PRO"], temperature=0,
        thinking={"type": "enabled"},
        messages=[{"role": "system", "content": SYS},
                  {"role": "user", "content": payload}])
    return r.choices[0].message.content, {"prompt_tokens": r.usage.prompt_tokens,
                                          "completion_tokens": r.usage.completion_tokens}


def show(name, raw):
    try:
        d = loads_lenient(raw)
    except Exception as e:
        print(f"🔴 {name} 解析失败：{e}\n{raw[:400]}")
        return
    print(f"\n{'='*74}\n■ {name}")
    rv = d.get("r_vs_turned_r") or {}
    print(f"  ▸ r vs ɹ：**{rv.get('recommend','?')}**（{rv.get('confidence','?')}）")
    print(f"     {rv.get('why','')}")
    for key, lab in (("misclassified", "分类有误"), ("rule_holes", "规则漏洞"),
                     ("wrong_outputs", "输出有错")):
        arr = d.get(key) or []
        print(f"  ▸ {lab} {len(arr)} 条")
        for x in arr[:5]:
            if key == "misclassified":
                print(f"     [{x.get('item')}] 应归 {x.get('should_be')} —— {str(x.get('why',''))[:96]}")
            elif key == "rule_holes":
                print(f"     [{x.get('severity','?')}] {str(x.get('issue',''))[:70]}")
                print(f"        例 {x.get('example_words')} ← {str(x.get('why',''))[:80]}")
            else:
                print(f"     #{x.get('i')} 应为 {x.get('should_be')} ← {str(x.get('why',''))[:80]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    samples = build()
    payload = RULE_DOC + "\n\n【真实输出样本】\n" + json.dumps(samples, ensure_ascii=False, indent=1)
    if not a.run:
        print(payload[:2400])
        print(f"\n… 共 {len(samples)} 条样本，payload 约 {len(payload):,} 字符")
        return
    env = load_env()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    async def go():
        # 🔴 gather 必须在 async 上下文里调 —— 直接 asyncio.run(asyncio.gather(...))
        #    会报 "a coroutine was expected, got _GatheringFuture"。
        return await asyncio.gather(
            ask_v4pro(env["DEEPSEEK_API_KEY"], payload), ask_doubao(env, payload),
            return_exceptions=True)

    v4, dou = asyncio.run(go())
    print(f"两家并行跑完 {time.time()-t0:.0f}s")
    rec = {"samples": samples, "ts": time.strftime("%Y-%m-%d %H:%M")}
    for name, r in (("v4pro", v4), ("doubao", dou)):
        if isinstance(r, Exception):
            print(f"🔴 {name} 失败：{r}")
            continue
        txt, u = r
        rec[name] = {"raw": txt, "usage": u}
        print(f"■ {name} 用量 {u}")
        show(name, txt)
    OUT.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
