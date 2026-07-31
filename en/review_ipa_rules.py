#!/usr/bin/env python3
"""把展示层的音标映射规则交给两个模型独立评审。见对话 2026-07-30。

为什么要两家:2026-07-30 实测同一批数据不同模型口径能差一倍(bad 5.3% vs 10.8%),
**单一模型的意见不能当结论**。两家独立评、只采信收敛的部分,分歧处留给人判。
⚠️ 不给它们看对方的答案,也不透露我自己的倾向 —— 否则就是让它们附和。

read-only,只打印。用法:
  python3 en/review_ipa_rules.py
"""
import asyncio, json, re
from pathlib import Path

import acceptance_en as A
from judge_sample import ds_call

HERE = Path(__file__).resolve().parent
RULES = HERE.parent / "packages/dict-core/src/index.ts"

SYS = """你是英语语音学 + 词典编纂双背景的专家。请评审一段**展示层音标映射代码**。

背景:
- 产品是**中文用户的划词翻译弹窗**(不是语音学工具),用户扫一眼就要知道怎么念,读者是中国的英语学习者;
- 数据源是 Wiktionary 的**严式(narrow)IPA**,库里存裸音标,UI 显示时自己加 /.../;
- 这个函数的定位是「严式存储 → 教学式展示」的降噪层,**英式和美式共用同一个函数**;
- 库里 uk/us 两列分开存,分别过这个函数。

请回答四个问题,不要客套:
1. **有没有错的规则**?即会把正确音标改成错误音标的。逐条指出并说明为什么错。
2. **有没有该做没做的**?尤其:输入里有大量括号表示可选音,如 æbˈdʌktə(r)、ˈæb.s(ə)n̩s、
   æbˈd(j)uˌsɛnz、ɔ(ː)。当前代码**只清空括号和括号内空格,内容原样保留**,
   所以用户看到的是 /ˈæbs(ə)ns/。对这个产品定位,你认为该怎么处理?英式美式要不要区别对待?
3. **英美共用一个函数**是否可行?哪些规则其实必须分列?
4. 如果只能改三处,你改哪三处?按收益排序。

务实一点:指出的问题要能落到具体正则上。严格输出 JSON:
{"wrong":[{"rule":"规则编号或正则","why":"为什么错","example":"具体词例"}],
 "missing":[{"what":"该做什么","why":"","example":""}],
 "paren":{"verdict":"保留/去括号留内容/分英美处理/其他","uk":"英式怎么做","us":"美式怎么做","why":""},
 "split_uk_us":{"needed":true,"rules":["必须分列的规则"]},
 "top3":["按收益排序的三处改动"]}"""


def extract_rules():
    t = RULES.read_text(encoding="utf-8")
    i = t.index("function normalizePronunciation")
    j = t.index("\n}", i) + 2
    return t[t.rindex("/**", 0, i):j]


async def ark_review(env, code):
    from volcenginesdkarkruntime import AsyncArk
    cl = AsyncArk(api_key=env["ARK_API_KEY"], timeout=1800)
    r = await cl.chat.completions.create(
        model=env["DOUBAO_SEED_2_1_PRO"], temperature=0,
        messages=[{"role": "system", "content": SYS},
                  {"role": "user", "content": "待评审代码:\n```typescript\n" + code + "\n```"}])
    await cl.close()
    return r.choices[0].message.content


async def ds_review(env, code):
    import httpx
    cl = httpx.AsyncClient(timeout=httpx.Timeout(900.0))
    txt, _ = await ds_call(cl, env["DEEPSEEK_API_KEY"], "deepseek-v4-pro", SYS,
                           {"code": code})
    await cl.aclose()
    return txt


def show(tag, raw):
    print(f"\n{'='*66}\n  {tag}\n{'='*66}")
    try:
        d = A.loads_lenient(raw.strip().strip("`").replace("json\n", "", 1)
                            if raw.strip().startswith("`") else raw.strip())
    except Exception:
        print(raw[:3000]); return None
    for k, title in (("wrong", "🔴 判定为错的规则"), ("missing", "🟡 该做没做的")):
        print(f"\n{title}:")
        for it in d.get(k) or []:
            print(f"  • {it.get('rule') or it.get('what')}")
            print(f"      理由: {it.get('why','')}")
            if it.get("example"):
                print(f"      词例: {it['example']}")
        if not (d.get(k) or []):
            print("  (无)")
    p = d.get("paren") or {}
    print(f"\n🔵 括号处置: {p.get('verdict','')}")
    print(f"    英式: {p.get('uk','')}")
    print(f"    美式: {p.get('us','')}")
    print(f"    理由: {p.get('why','')}")
    s = d.get("split_uk_us") or {}
    print(f"\n🟣 英美必须分列? {s.get('needed')}   {'; '.join(s.get('rules') or [])}")
    print("\n⭐ 只改三处的话:")
    for i, x in enumerate(d.get("top3") or [], 1):
        print(f"  {i}. {x}")
    return d


def main():
    code = extract_rules()
    print(f"待评审:{len(code)} 字符,{code.count('.replace')} 条 replace 规则")
    env = A.load_env()
    ark, ds = asyncio.run(_both(env, code))
    out = HERE / "runs/ipa_rule_review.json"
    json.dump({"ark_pro": ark, "ds_v4_pro": ds}, open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"原始回复已存 → {out.name}")     # ⚠️ 别只 print:上一轮被 head 截断,重跑要再花钱
    a = show("豆包 seed-2.1 pro", ark)
    b = show("DeepSeek v4-pro", ds)
    if a and b:
        print(f"\n{'='*66}\n  收敛度\n{'='*66}")
        for k in ("wrong", "missing"):
            na, nb = len(a.get(k) or []), len(b.get(k) or [])
            print(f"  {k:8} 豆包 {na} 条 / v4-pro {nb} 条")
        print(f"  括号处置  豆包「{(a.get('paren') or {}).get('verdict','')}」"
              f" vs v4-pro「{(b.get('paren') or {}).get('verdict','')}」")


async def _both(env, code):
    return await asyncio.gather(ark_review(env, code), ds_review(env, code))


if __name__ == "__main__":
    main()
