#!/usr/bin/env python3
"""就「CEFR level 字段该怎么办」并行请教豆包 pro 与 deepseek v4-pro。2026-08-07。

═══ 为什么这一条该问模型 ═══
项目铁律：**能确定性回源比对的根本别问模型**。`level` 恰恰是**没有源可回**的字段 ——
它不是从 dump 抽出来的，是 2026-07 那轮 `b_enrich.py` 让豆包凭一句
「按该西语词实际频率与掌握难度判断」现编的，10.5 万条，无锚点、无复核。

所以问的不是「casa 是不是 A1」（那种逐行事实不该问模型），而是三个规则的洞：
  · 按**词**标 CEFR 在词典学上成不成立
  · 有没有**可得**的外部尺子（我手上只有 wiktionary/kaikki dump，没有教材词表）
  · 这个字段挂词还是挂义项、覆盖不到的部分怎么办

⚠️ 用户 2026-08-07：商量规则可以开思考。
⭐ 材料纪律：不把我的结论写进标题（2026-07-31 踩过），数据给原样不给概括。

用法：
    python3 -m es.probes.consult_cefr_level          # 只打印材料，不发请求
    python3 -m es.probes.consult_cefr_level --ask
"""
import argparse
import asyncio
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import paths    # noqa: E402

OUT = paths.WORK / "consult_cefr_level.json"

SYS = """你是双语词典（西班牙语→中文）与西语教学的资深顾问。下面是一个真实词典项目的
现场数据和一个字段设计问题。请直接给结论和理由，不要客套，不确定的地方要明说不确定。"""

BACKGROUND = """【项目背景】
产品是**划词弹窗词典**：用户在网页上选中一个西语词，弹出释义。字段要轻快够用。
库里 113 万行，其中判定为词元（lemma）的 16.6 万行，其余是变形词形。

有一个 `level` 字段，取值 A1/A2/B1/B2/C1/C2，**只给 lemma 填**，已填 10.5 万条。
展示层把它渲染成词条标题旁边的一个彩色徽章。

【这个字段是怎么来的】
2026 年 7 月，把 10.5 万个 lemma 分批发给大模型，系统提示词里关于该字段只有一句：

    "level：CEFR 难度 A1/A2/B1/B2/C1/C2 之一（A1 最基础、C2 最高阶），
     按该西语词实际频率与掌握难度判断。**ask 含 level 时必给**。"

没有给模型任何词表、频次或语料证据；没有做过复核；也没有负控。
（另：我们后来实测过同一批数据同一模型 temperature=0 重跑结果不完全一致。）
"""


def facts(con) -> str:
    L = ["【现场实测数据（本次现查，非记忆）】", "", "分布："]
    for lv, n in con.execute(
            "SELECT level, COUNT(*) FROM dict WHERE level IS NOT NULL "
            "GROUP BY 1 ORDER BY 1"):
        L.append(f"    {lv}   {n:>7,}")
    nul = con.execute("SELECT COUNT(*) FROM dict WHERE level IS NULL").fetchone()[0]
    L.append(f"    NULL {nul:>7,}   （全部是非 lemma 的变形词形）")
    L.append("")

    L.append("抽查一批常用词，模型给的等级看起来是合理的：")
    row = []
    for w in ("casa", "agua", "hola", "comer", "gato", "libro", "ciudad",
              "siempre", "ayer", "ventana", "zapato", "cuchara", "nube",
              "banco", "tiempo"):
        r = con.execute("SELECT level FROM dict WHERE word=? AND is_lemma=1 LIMIT 1",
                        (w,)).fetchone()
        row.append(f"{w}={r[0] if r else '—'}")
    L.append("    " + "  ".join(row))
    L.append("")

    L.append("但 A1+A2+B1 这 16,236 条里，混进了这些（数量为实测）：")
    cats = {
        "词缀": r"word LIKE '-%' OR word LIKE '%-'",
        "纯符号/数字": r"word NOT GLOB '*[a-zA-ZáéíóúüñÁÉÍÓÚÜÑ]*'",
        "带点的缩写": r"word LIKE '%.%'",
        "首字母大写": r"word GLOB '[A-ZÁÉÍÓÚÑ]*'",
        "多词条目": r"word LIKE '% %'",
    }
    for name, cond in cats.items():
        n, ex = con.execute(
            f"SELECT COUNT(*), GROUP_CONCAT(word, ' / ') FROM "
            f"(SELECT word FROM dict WHERE level IN ('A1','A2','B1') AND ({cond}) "
            f"ORDER BY random() LIMIT 8)").fetchone()
        tot = con.execute(
            f"SELECT COUNT(*) FROM dict WHERE level IN ('A1','A2','B1') AND ({cond})"
        ).fetchone()[0]
        L.append(f"    {name:<12}{tot:>6}   例：{ex}")
    L.append("")
    L.append("这个字段目前有三处用途：")
    L.append("    ① 词条标题旁的彩色徽章（唯一的用户可见用途）")
    L.append("    ② 挑哪些词去合成 TTS 发音（选了 A1/A2/B1 那 1.6 万）")
    L.append("    ③ 内部脚本筛「核心层」做定向修补")
    L.append("")
    L.append("我们手上现成的数据只有：英文/西语/中文等各语言版 Wiktionary 的")
    L.append("wiktextract dump（kaikki），以及一份英汉词库 stardict.csv。")
    L.append("**没有**任何西语频次语料、教材词表、学习者语料。")
    return "\n".join(L)


QUESTIONS = """【问题一】按「词」标一个 CEFR 等级，在词典学上站得住吗？
我的疑虑是：CEFR 官方定义的是**学习者能力**等级，不是词汇属性；
欧洲各语言的官方词表（西语这边是塞万提斯学院的 Plan Curricular）只覆盖到 B2，
而且是按**义项/交际功能**列的，不是按词形。
如果你认为按词标不成立，请说清楚：那这个字段应该删掉、还是换成别的东西？

【问题二】如果保留，外部尺子有哪些是**真能拿到**的？
请按「可得性」排序给出具体来源（名称 + 大致规模 + 授权情况 + 拿到之后怎么用），
并对每一个说明它的陷阱。特别请你评估这几条我想到的路子：
  a. 塞万提斯学院 Plan Curricular 的词汇清单（A1–B2）
  b. 影视字幕频次表（OpenSubtitles 系，如 hermitdave/FrequencyWords 的 es_50k）
  c. SUBTLEX-ESP / CREA / EsPal 这类心理语言学或官方语料频次
  d. Python 的 wordfreq 包（内置多语频次，含西语）
  e. 从我们自己已有的 Wiktionary dump 里推（比如按各语言版收录该词的版本数）
如果这些都不理想，请直说，并给你认为最务实的做法。

【问题三】外部尺子通常只覆盖几千到几万个高频词，而我们有 16.6 万个 lemma。
覆盖不到的那 10 万多怎么办？外推？留空？还是这本身说明字段设计有问题？

【问题四】这个字段该挂在词上还是挂在义项上？
真实例子：`banco` 在我们库里有 7 条出版义项，包括「长凳」「银行」「鱼群」
「（地质）沙洲、暗礁」「数据库/血库等的『库』」。
作为一个词它是 A2，但「沙洲」这条显然不是 A2 学习者的内容。

【问题五】如果只能保留一个「难度/常用度」字段，你会选 CEFR 等级还是原始频次分位
（比如「前 1000 词 / 前 5000 词 / 前 2 万词 / 更罕见」）？对**划词弹窗**这个产品形态
而言，哪个对用户更有价值？为什么？

请对每一问给出：结论 → 理由 → 你认为我最可能判断错的地方。
最后请单独说一句：如果这件事你也没有把握，明确说出来，不要编。
"""


async def ask_doubao(prompt, env):
    from volcenginesdkarkruntime import AsyncArk
    cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
    try:
        r = await cl.chat.completions.create(
            model=env["DOUBAO_SEED_2_1_PRO"],
            messages=[{"role": "system", "content": SYS},
                      {"role": "user", "content": prompt}],
            temperature=0.3,
            thinking={"type": "enabled"},      # 商量规则，开思考
        )
        return r.choices[0].message.content, dict(r.usage or {})
    finally:
        await cl.close()


async def ask_v4pro(prompt, env):
    import httpx
    async with httpx.AsyncClient(timeout=1800) as cl:
        r = await cl.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": "Bearer " + env["DEEPSEEK_API_KEY"].strip()},
            json={"model": "deepseek-reasoner",
                  "messages": [{"role": "system", "content": SYS},
                               {"role": "user", "content": prompt}],
                  "stream": False})
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        d = json.loads(r.text)
        return d["choices"][0]["message"]["content"], (d.get("usage") or {})


async def main_async(prompt, env):
    """🔴 **并行**问两家（用户 2026-08-01 定），互不影响、互不看对方答案。"""
    return await asyncio.gather(ask_doubao(prompt, env), ask_v4pro(prompt, env),
                                return_exceptions=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ask", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    prompt = "\n".join([BACKGROUND, facts(con), QUESTIONS])
    con.close()

    print(prompt)
    if not args.ask:
        print("\n" + "=" * 70)
        print("未加 --ask，不发请求。")
        return

    env = dict(l.split("=", 1) for l in paths.ENV.read_text().splitlines()
               if "=" in l and not l.startswith("#"))
    res = asyncio.run(main_async(prompt, env))
    out = {"prompt": prompt}
    for name, r in zip(("doubao-pro", "v4-pro"), res):
        if isinstance(r, Exception):
            print(f"\n🔴 {name} 失败：{r}")
            out[name] = {"error": str(r)}
            continue
        text, usage = r
        # ⚠️ 豆包 SDK 的 usage 里嵌着 PromptTokensDetails 这类对象，直接 json.dumps 会崩。
        #    问答已经拿到了却存不下盘，等于白问一次 —— 一律转字符串。
        out[name] = {"text": text, "usage": {k: str(v) for k, v in usage.items()}}
        print("\n" + "=" * 70)
        print(f"【{name}】tokens={usage}")
        print("=" * 70)
        print(text)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已存 → {OUT}")


if __name__ == "__main__":
    main()
