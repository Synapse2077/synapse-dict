#!/usr/bin/env python3
"""译文分歧检测：库里的豆包译文 × 中文版维基词典。**确定性比对，不调模型**。2026-08-01。

═══ 这一步在回答什么 ═══
不是"我们的译文对不对"，而是"**我们和一个独立人工源在哪些词上对不上**"。
分歧清单是地图，不是判决。纪律⑩：能确定性比对的别问模型；先拿真值，再拿真值给模型打分。

═══ 判据（故意定得宽，宁可漏报分歧也不误报）═══
分歧 = 双方的中文词条**一个 token 都搭不上**（含互为子串）。
之所以宽：中文版常常只给一个义项、或给得比我们粗（`coche`→"汽車"，我们给五个义项），
**覆盖面不同不是分歧**，只有"完全对不上"才值得看。

⚠️ 三个必须先处理的坑（实测，不处理会把一致误判成分歧）：
  ① **繁简混用** —— `coche`→"汽車"、`libro`→"書"，而我们写"汽车""书"。不转简全是假分歧。
  ② **词性前缀** —— `comer`→"vi. 吃饭"，前缀要剥掉。
  ③ **元描述义项** —— "XX的复数/阴性/过去分词"是变形指针，不是释义，比了就是噪声。

用法（在 es/ 目录）：
    python3 probes/zh_translation_divergence.py            # 全量统计 + 样本
    python3 probes/zh_translation_divergence.py --dump     # 落分歧清单
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import json
import random
import re
import sqlite3

import zhconv

import paths

ZH = paths.WORK / "zh_es.jsonl"
OUT = paths.WORK / "runs" / "zh_translation_divergence.jsonl"

# ① 词性前缀（中文版贡献者手写风格，剥掉）
POS_PREFIX = re.compile(r"^\s*(?:v[itr]?|n|adj|adv|prep|conj|pron|interj|num|art)\.\s*", re.I)
# ② 括号内的补充说明，比对时剥掉（保留在原文里供人看）
PARENS = re.compile(r"[（(][^）)]*[）)]")
# ③ 元描述义项：变形指针 / 元描述，不是释义
# ⚠️ 第一版漏了"過去時分詞"（只写了"過去分詞"）和"的屈折"，于是 encabezado、astilla
#    这类被当成分歧。**元描述不清干净，分歧率就是噪声率。**
META_GLOSS = re.compile(
    r"的(?:复数|複數|阴性|陰性|阳性|陽性|屈折|变位|變位|简称|簡稱|缩写|縮寫|"
    r"另一种拼写|另一種拼寫|昵称|暱稱|指小词|指小詞)"
    r"|(?:过去|過去|现在|現在)(?:时|時)?(?:分词|分詞)"
    r"|(?:命令式|虚拟式|虛擬式|直陈式|直陳式|副动词|副動詞|人称单数|人稱單數|人称复数|人稱複數)"
    r"|源自[^，,]{0,12}的(?:姓氏|名字|人名)|^\s*(?:男性|女性)?(?:姓氏|名字|人名)"
    r"|^\s*(?:同|参见|參見|见|見)\s*[A-Za-zÀ-ÿ]"
    # —— 第二轮补：这些让 1,449 条里 ~1/4 是假分歧 ——
    r"|(?:首字母)?(?:縮略詞|缩略词|縮寫詞|缩写词)|(?:截斷|截断)形式|之同(?:義|义)詞|之同义词"
    r"|(?:同義詞|同义词|變體|变体|替代(?:形式|拼寫|拼写)|另一種|另一种)"
    # 纯语法描述（"阳性单数定冠词"），不是释义
    r"|(?:定|不定)冠詞|(?:定|不定)冠词|(?:人稱|人称)代詞|代词$|前置詞|介詞")
SPLIT = re.compile(r"[、，,；;：:/|｜\s]+")
HAS_CJK = re.compile(r"[一-鿿]")
STOP_CHARS = set("的了地得着与和或及等一二三四五六七八九十个人物事者性化式型上下中前后内外大小多少不无非有")


def toks(text):
    """中文释义串 → 归一化 token 集合。

    ⚠️ 括号**不能直接删**：`fa` 的译文是"发（音阶第四音）"，删了只剩"发"，
       跟中文版的"音乐中的第四个唱名"就一个字都不共享 —— 假分歧。
       正确做法是**括号内外都收**：外层是主释义，内层是限定语，两边都可能承载信息。
    """
    t = zhconv.convert(text, "zh-cn")
    t = POS_PREFIX.sub("", t)
    t = PARENS.sub("，", t)          # 括号→分隔符，内容通过下一行单独收
    t += "，" + "，".join(PARENS.findall(zhconv.convert(text, "zh-cn"))).replace("（", "").replace("）", "").replace("(", "").replace(")", "")
    out = set()
    for p in SPLIT.split(t):
        p = p.strip().strip("。.!！?？\"'“”‘’…-—")
        if p and HAS_CJK.search(p):
            out.add(p)
    return out


def agrees(a, b):
    """L1：任一 token 相等或互为子串 → 搭得上。"""
    if a & b:
        return True
    return any(x in y or y in x for x in a for y in b)


def chars(tokset):
    """token 集 → 实词字符集（去掉"的了地"这类无区分力的字）。"""
    return {c for t in tokset for c in t} - STOP_CHARS


def shares_char(a, b):
    """L2：共享至少一个实词字符 → 近义，多半不是分歧。

    ⚠️ 这一层是必需的，不是放水。中文近义词大量共字而不共词：
        碎屑/碎片、愚人/愚蠢的人、扇子/手摇扇、从侧翼攻击/侧翼包抄
    L1 一律判成"分歧"，但它们说的是同一件事。**只有连一个实词字都不共享，
    才是真的两边在讲不同的东西** —— 那才值得人去看。
    """
    return bool(chars(a) & chars(b))


def load_zh():
    """→ {word: (token集, 原始义项列表)}；元描述义项已剔除。"""
    d = {}
    for ln in open(ZH, encoding="utf-8"):
        e = json.loads(ln)
        raw, tk = [], set()
        for s in e["senses"]:
            for g in s["g"]:
                if META_GLOSS.search(g):
                    continue
                raw.append(g)
                tk |= toks(g)
        if tk:
            prev = d.get(e["word"])
            if prev:                       # 同词多词性，合并
                tk |= prev[0]
                raw = prev[1] + raw
            d[e["word"]] = (tk, raw)
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    a = ap.parse_args()

    zh = load_zh()
    conn = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT word, pos, definition, translation, level FROM dict WHERE is_lemma=1"
    ).fetchall()
    conn.close()

    n_lemma = len(rows)
    hit = comparable = l1 = l2 = diff = 0
    empty_ours = 0
    recs = []
    for w, pos, dfn, tr, lv in rows:
        z = zh.get(w)
        if not z:
            continue
        hit += 1
        ours = toks(tr or "")
        if not ours:
            empty_ours += 1
            continue
        comparable += 1
        if agrees(ours, z[0]):
            l1 += 1
        elif shares_char(ours, z[0]):
            l2 += 1
        else:
            diff += 1
            recs.append({"word": w, "pos": pos, "level": lv,
                         "ours": tr, "zh": z[1],
                         "ours_tok": sorted(ours)[:12], "zh_tok": sorted(z[0])[:12],
                         "def": (dfn or "").split("\n")[0][:120]})

    print(f"■ 中文版西语词条（去元描述后有中文释义）  {len(zh):,}")
    print(f"■ 我们的 lemma                            {n_lemma:,}")
    print(f"■ 交集                                    {hit:,}  （占 lemma {hit*100/n_lemma:.1f}%）")
    print(f"    其中我们有译文（可比）                {comparable:,}")
    print(f"    我们没译文                            {empty_ours:,}")
    print()
    c = max(comparable, 1)
    print(f"    ✅ L1 词级搭得上（同词或互为子串）    {l1:,}  ({l1*100/c:.1f}%)")
    print(f"    ✅ L2 共享实词字（近义，如 碎屑/碎片） {l2:,}  ({l2*100/c:.1f}%)")
    print(f"    ⚠️ 连一个实词字都不共享 = **真分歧**   {diff:,}  ({diff*100/c:.1f}%)")

    if recs:
        by_lv = {}
        for r in recs:
            by_lv[r["level"] or "—"] = by_lv.get(r["level"] or "—", 0) + 1
        print(f"\n    分歧按 CEFR 分布：{dict(sorted(by_lv.items()))}")
        random.seed(7)
        print("\n" + "=" * 78 + "\n■ 分歧样本 15 条\n")
        for r in random.sample(recs, min(15, len(recs))):
            print(f"  {r['word']}  [{r['pos']}·{r['level']}]")
            print(f"     我们 : {(r['ours'] or '').replace(chr(10), ' / ')[:100]}")
            print(f"     中文版: {' / '.join(r['zh'])[:100]}")
            print(f"     英文义: {r['def']}")
            print()

    if a.dump:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"→ {OUT}  ({len(recs):,} 条)")


if __name__ == "__main__":
    main()
