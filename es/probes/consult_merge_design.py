#!/usr/bin/env python3
"""就「义项归并的层级设计」并行请教豆包 pro 与 deepseek v4-pro。2026-08-07。

═══ 为什么问模型（以及为什么这次该问）═══
项目铁律：**能确定性回源比对的根本别问模型**。所以本脚本**不问** `en_i` 判据那类
事实问题（`mona` 已给出铁证：`en_i` 是义项行号不是英文释义序号，回源即可判定）。

问的是**规则的洞**——词典学取舍，没有权威源可查，我自己拿不准：
20.7% 的对齐是「1 条英文义项 ↔ N 条西语义项」。把它们做成父子义项之后，
`ojo` 会出现「**1. 眼睛 → d) 与眼睑开口相似的平面几何形**」。这成立吗？

⚠️ 用户 2026-08-07：商量规则**可以开思考**（成批当判官才默认关思考）。

⭐ 材料准备的两条纪律（都是踩过的坑）：
  · **别把结论写进材料标题**——2026-07-31 我把「疑似过度」写进评审材料，
    两家收敛的是我的偏见，回源核对后推翻了其中最大两条
  · 给足权威源原文（西语定义 + 英文 gloss 全列），别只给我的概括

用法：
    python3 -m es.probes.consult_merge_design            # 只打印材料，不发请求
    python3 -m es.probes.consult_merge_design --ask
"""
import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import paths    # noqa: E402

OUT = paths.WORK / "consult_merge_design.json"

SYS = """你是双语词典（西班牙语→中文）的资深编纂顾问。下面是一个正在做的词典项目的
真实数据与一个结构设计问题。请给出你的专业判断，不要客套，直接说结论和理由。"""

BACKGROUND = """【背景】
我们有同一个西语词的**两套义项**：
  A. 英文维基词典给的：**对应词**式（ojo → eye / keyhole / caution），平均 23 字符
  B. 西语维基词典给的：**单语定义**式（ojo → "Órgano sensible a la luz que permite
     la visión…"），平均 64 字符，切分细得多

已用大模型做过 A↔B 的义项对齐，产出「这条西语义项对应英文第几条」。结果分三种：
  · 1 条西语义项认领 1 条英文义项      49,088 组（79.3%）
  · N 条西语义项认领同一条英文义项     12,822 组（20.7%）
  · 无人认领                          英文侧 15,063 条、西语侧 92,901 条

现在要把两套合成**一套出版义项**（用户在划词弹窗里读到的 1. 2. 3.）。
产品形态是划词弹窗：选中一个西语词，弹出释义，要求准确、可快速扫读。
"""

QUESTIONS = """【问题一】N 条西语义项认领同一条英文义项时，做成父子义项对吗？
拟议做法：英文那条作**父**（提供对应词），N 条西语作**子**（提供定义）。
请特别评估下面这个真实例子里，第 ④ 条做成 "眼睛" 的子义项是否成立；
如果不成立，你认为正确的处理是什么（独立成条？归入别的父？还是别的做法）。

【问题二】父义项只有对应词没有定义、子义项只有定义没有对应词。
展示时若空间只够显示一层，应该显示哪一层？为什么？

【问题三】1:1 合并的那 79.3%，一条义项会同时有两份中文：
从英文对应词翻来的「眼睛」和从西语定义翻来的「对光敏感、使生物具有视觉的器官」。
应该怎么呈现？（都显示？只显示一个？如果只显示一个，选哪个？）

请针对每一问给出：结论 → 理由 → 你认为我方案里最可能出错的地方。
"""


def build_case(con) -> str:
    """取 ojo 的完整真实数据当案例。**给全，不给我的概括。**"""
    de = con.execute("SELECT definition FROM dict WHERE word='ojo'").fetchone()[0]
    en = [x for x in de.split("\n")]
    rows = con.execute(
        "SELECT idx, en_i, gloss, zh FROM sense_es WHERE word='ojo' ORDER BY idx").fetchall()
    L = ["【真实案例：西语词 ojo】", "", "英文版义项（按行号）："]
    for i, g in enumerate(en):
        L.append(f"  en[{i}] = {g}")
    L.append("")
    L.append("西语版义项（含对齐结果与中文译文）：")
    for idx, eni, g, zh in rows:
        tag = f"→ en[{eni}]" if eni is not None else "→ 英文版没有"
        L.append(f"  es#{idx:<2} {tag:<16} {g}")
        L.append(f"       中文：{zh}")
    L.append("")
    L.append("按拟议做法，ojo 会呈现成：")
    L.append("  1. 眼睛                                    ← 来自 en[0]")
    L.append("     a) 对光敏感、使生物具有视觉的器官          ← es#0")
    L.append("     b) （引申）任何功能与视觉器官类似的装置     ← es#1")
    L.append("     c) 眼球外部可见的部分，尤指虹膜            ← es#2")
    L.append("     d) 任何与眼睑开口可见的眼部相似的平面几何形  ← es#3")
    L.append("  2. 钥匙孔 / 锁芯中插入钥匙的孔洞")
    L.append("  3. 【转喻】小心，提防")
    L.append("  4~22. （西语版独有的 18 条，英文版没有）")
    return "\n".join(L)


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
    res = await asyncio.gather(ask_doubao(prompt, env), ask_v4pro(prompt, env),
                               return_exceptions=True)
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ask", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    prompt = "\n".join([BACKGROUND, build_case(con), QUESTIONS])
    con.close()

    print(prompt)
    if not args.ask:
        print("\n" + "=" * 70)
        print("未加 --ask，不发请求。")
        return

    env = dict(l.split("=", 1) for l in paths.ENV.read_text().splitlines()
               if "=" in l and not l.startswith("#"))
    res = asyncio.run(main_async(prompt, env))
    out = {}
    for name, r in zip(("doubao-pro", "v4-pro"), res):
        if isinstance(r, Exception):
            print(f"\n🔴 {name} 失败：{r}")
            out[name] = {"error": str(r)}
            continue
        text, usage = r
        out[name] = {"text": text, "usage": usage}
        print("\n" + "=" * 70)
        print(f"【{name}】tokens={usage}")
        print("=" * 70)
        print(text)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已存 → {OUT}")


if __name__ == "__main__":
    main()
