#!/usr/bin/env python3
"""双家咨询：补入义项时，三列（definition/translation/meta）怎么写。2026-08-02。

═══ 我拿不准的到底是什么 ═══
库里三列**逐义项逐行对齐**：
    definition   英文 gloss，\\n 分行，来自英文版维基
    translation  中文，\\n 分行，与 definition 逐行对应
    meta         JSON 数组，与上面两列逐项对应
现在要从**中文版维基**补 9 个义项进来，而中文版**只有中文、没有英文 gloss**。
于是 `definition` 那一行只能：留空 / 放中文 / 放机器回译 / 放来源标记。
四种都会破坏「definition 这一列是英文」这个不变量的某个方面。

用户 2026-08-02 定的规矩：**拿不准就问两家，我裁决。**这件事我确实拿不准 —— 它不是
事实题（没有权威源能裁决），而且**一旦定下来 it/fr/de/pt 四门直接套**，改起来贵。

用法（在 es/ 目录）：python3 probes/review_sense_append_schema.py --run
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import asyncio
import json
import re
import time

import httpx

import paths

OUT = paths.WORK / "runs" / "sense_append_schema.json"

DOC = """【库的结构】
表 dict，一行一个词形，767,293 行。lemma 行的三列**逐义项逐行对齐**：

  definition   英文 gloss，\\n 分行。全部来自英文版维基词典。
  translation  中文，\\n 分行，与 definition **逐行一一对应**。
  meta         JSON 数组，与上面两列**逐项一一对应**，形如
               [{"pos":"n","g":"m","reg":["Mexico"],"lex":["colloquial"],"top":["boxing"]}, …]

真实例子（expreso）：
  definition   "espresso (strong type of coffee)"
  translation  "浓缩咖啡"
  meta         [{"pos":"n","g":"m"}]

另有来源列的既有约定：`phonetic_src`（值从哪来）、`phonetic_confirm`（谁独立确认过），
两者正交、不合并成一个字符串。

【要做的事】
拿中文版维基词典（独立人工源，**只有中文释义，没有英文 gloss**）比对后，确认
9 个义项是我们完全缺的，要补进去。例如 expreso 要补「明确的」和「快车」两个义项。
补入的义项一律**追加到末尾**（我们没有词频数据，无法按常用度排序）。

【拿不准的点】
补入的那一行，`definition` 列写什么？候选：
  A. 留空行（保住"definition 只放英文版原值"，但产生空洞，且 UI 可能显示空白）
  B. 放中文释义（与 translation 重复，且破坏"这一列是英文"）
  C. 放机器回译的英文（凭空造一个英文版从未说过的 gloss）
  D. 放固定标记文本，如 "[zh-wiktionary]"（不是 gloss，但占位明确）
  E. 其它你认为更好的做法

【产品约束】
划词弹窗：用户选中西语单词 → 弹出中文释义（主）、音标、语法信息。
**英文 gloss 目前不直接展示给用户**，它的作用是：① 溯源与审计 ② 未来做英西对照的基础
③ 我们自己做质检时的对照物。"""

SYS = """你是词典数据库结构设计与词典编纂专家。严格输出 JSON：

{
 "definition_column": {
   "choice": "A|B|C|D|E",
   "if_E": "若选 E，具体写什么",
   "why": "理由，三到五句，要针对这部词典的实际用途而不是通用最佳实践",
   "downside": "你这个选择的代价是什么"
 },
 "provenance": {
   "where": "补入义项的来源标记放哪里（哪一列、什么形状）",
   "value": "具体取值建议"
 },
 "alignment_risk": {
   "risk": "三列逐行对齐这个设计，在追加义项时最可能怎么坏掉",
   "guard": "应该加什么校验来防住它"
 },
 "reversibility": "这次追加如果以后要整体撤销，需要预先留下什么",
 "other_langs": "同样的规则要套到意/法/德/葡四门，有没有需要现在就考虑的差异"
}

要点：
- 不要建议改表结构（如"拆成 senses 子表"）—— 那是另一个量级的工程，现在不做。
- 不要建议引入新的外部数据源。
- `downside` 必须写，不许留空 —— 我要的是权衡不是推销。"""


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
        return json.loads(re.sub(r",\s*([}\]])", r"\1", s))


async def ask_v4pro(key, p):
    async with httpx.AsyncClient(timeout=1800) as cl:
        r = await cl.post("https://api.deepseek.com/chat/completions",
                          headers={"Authorization": "Bearer " + key},
                          json={"model": "deepseek-v4-pro",
                                "messages": [{"role": "system", "content": SYS},
                                             {"role": "user", "content": p}],
                                "temperature": 0,
                                "response_format": {"type": "json_object"},
                                "thinking": {"type": "enabled"}, "stream": False})
        if r.status_code != 200:
            raise RuntimeError("HTTP %s: %s" % (r.status_code, r.text[:200]))
        return json.loads(r.text.lstrip())["choices"][0]["message"]["content"]


async def ask_doubao(env, p):
    from volcenginesdkarkruntime import AsyncArk
    cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
    r = await cl.chat.completions.create(
        model=env["DOUBAO_SEED_2_1_PRO"], temperature=0,
        thinking={"type": "enabled"},
        messages=[{"role": "system", "content": SYS}, {"role": "user", "content": p}])
    return r.choices[0].message.content


def show(name, raw):
    try:
        d = loads_lenient(raw)
    except Exception as e:
        print("🔴 %s 解析失败：%s\n%s" % (name, e, raw[:300]))
        return
    dc = d.get("definition_column") or {}
    print("\n" + "=" * 74 + "\n■ " + name)
    print("  ▸ definition 列：**%s**  %s" % (dc.get("choice"), dc.get("if_E") or ""))
    print("     理由: %s" % str(dc.get("why", ""))[:260])
    print("     代价: %s" % str(dc.get("downside", ""))[:200])
    pv = d.get("provenance") or {}
    print("  ▸ 来源标记: %s → %s" % (pv.get("where"), pv.get("value")))
    ar = d.get("alignment_risk") or {}
    print("  ▸ 对齐风险: %s" % str(ar.get("risk", ""))[:180])
    print("     护栏    : %s" % str(ar.get("guard", ""))[:180])
    print("  ▸ 可撤销  : %s" % str(d.get("reversibility", ""))[:180])
    print("  ▸ 其它语种: %s" % str(d.get("other_langs", ""))[:180])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if not a.run:
        print(DOC)
        return
    env = load_env()
    t0 = time.time()

    async def go():
        return await asyncio.gather(ask_v4pro(env["DEEPSEEK_API_KEY"], DOC),
                                    ask_doubao(env, DOC), return_exceptions=True)

    v4, dou = asyncio.run(go())
    print("两家并行跑完 %.0fs" % (time.time() - t0))
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M")}
    for name, r in (("v4pro", v4), ("doubao", dou)):
        if isinstance(r, Exception):
            print("🔴 %s 失败：%s" % (name, r))
            continue
        rec[name] = r
        show(name, r)
    OUT.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n→ %s" % OUT)


if __name__ == "__main__":
    main()
