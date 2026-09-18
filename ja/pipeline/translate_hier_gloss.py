#!/usr/bin/env python3
"""把「多层 gloss」修复暴露出来的具体释义与伞形译成中文。2026-09-17。

═══ 为什么不复用 `translate_defs.py` ═══
它的池子判据是「**还没有中文**的义项」，而这一轮要翻的 1,746 条**已经有中文了**
—— 那些中文翻的是伞形（`ある` 的 7 条全是「有」）。直接跑 `translate_defs`
一条都取不到，还会静静地报「池子 0 条」。
⇒ 池子由 `fixes/fix_hierarchical_gloss.py --pool` 导出，本脚本只负责送批。

═══ 🔴 payload 带 `umbrella`，而且明说不许翻它 ═══
`the left side of the stage in the Edo-style` 单看不知道在讲什么，
加上伞形 `in kabuki:` 才译得对。但**给模型的参考会直接漏进输出**
（`[[context-you-give-leaks-into-output]]`）—— 规则 2 专门堵它，
控制组 E7「译文长度异常」和逐条读一起兜。

⚠️ 伞形自己也要一条中文（页面上当小标题），它们在池子里 `key` 以 `u` 开头、
   没有 `word`/`umbrella` 字段 ⇒ 同一份 SYS 两种输入，规则 8 说明怎么处理。

跑（在仓库根）：
    python3 -u ja/pipeline/translate_hier_gloss.py --slice 5    # 5% 切片
    python3 -u ja/pipeline/translate_hier_gloss.py --read       # 逐条读
    python3 -u ja/pipeline/translate_hier_gloss.py              # 全量
"""
import sys as _sys
import pathlib as _pl
# 🔴 只把 `ja/` 放进 sys.path（铁律①）。理由见 `translate_defs.py` 文件头。
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import asyncio
import collections
import json

import paths                                            # noqa: E402
import ctrl                                             # noqa: E402
from pipeline.ds_batch import run as ds_run             # noqa: E402

f = lambda n: format(n, ",")
POOL = paths.WORK / "hier_gloss_pool.jsonl"
OUT = paths.WORK / "hier_gloss_zh.jsonl"
CHUNK = 60

SYS = """你在把日语词典的释义翻译成中文，用于一部给中文读者的日语词典。

输入是 JSON 数组，每项有：
  `key`       标识号，**不是序号**，原样回传
  `word`      被解释的日语词（伞形条目这一项是空字符串）
  `kana`      该词条的假名读音（同形异读时用它区分），可能没有
  `pos`       词性（n 名词／v 动词／adj 形容词／name 专名／kanji 汉字…）
  `umbrella`  这条义项所属的**上位标题**，可能没有。**只作理解参考，绝不翻译它、不要把它抄进译文**
  `en`        要翻译的英文释义 —— **只翻这一条**

规则
1. 输出**中文释义**，不是逐字翻译。能用一个常用汉语词对应就给那个词，
   不能对应就给一句简短的解释。
2. 🔴 **`umbrella` 的内容不许出现在译文里。** 它是上一级标题，页面上会单独印一次；
   抄进来就会变成「歌舞伎中：歌舞伎中的舞台左侧」这种重复。
   译文只说 `en` 那一条**自己**新增的信息。
3. 🔴 **不许出现任何假名**（ひらがな・カタカナ）。出现假名说明没翻完。
4. 🔴 **不要把词头 `word` 抄回来当释义**。原文只是重复 `word` 时，`zh` 给空字符串。
5. 🔴 **不要输出元描述**。「…的连用形」「…的异体字」说的是语法关系不是词义，
   `zh` 给空字符串。
6. 🔴 **词性要对上 `pos`**：`v` 给动词说法（「吃」不是「食物」），`n` 给名词说法。
7. 专名（`pos=name`）：有通用中文译名的用通用译名；没有的**保留原文汉字**，不要音译生造。
8. `word` 是空字符串的那些是**伞形标题本身**（`in kabuki:` / `a placename, especially:`）：
   照样译成中文，**去掉结尾的冒号**，译成一个能当小标题的短语（「歌舞伎中」「地名，尤指」）。
9. 学名、化学式、度量单位原样保留。
10. **不加句末标点**，不写「指」「表示」这类引导语。
11. 原文残缺或看不出意思，`zh` 给空字符串，不要猜。

输出 JSON **对象**，键是 `key`（字符串），值是 `{"zh": "<中文释义>"}`：
{"s141837": {"zh": "舞台左侧（江户流）"}, "u3": {"zh": "歌舞伎中"}}
每个输入 key 都要有一个键，一个都不能少。只输出 JSON，不要解释。"""


def pool(slice_pct=None):
    if not POOL.exists():
        _sys.exit("🔴 没有 %s —— 先跑 "
                  "`python3 -u ja/fixes/fix_hierarchical_gloss.py --pool`" % POOL)
    out = []
    for i, line in enumerate(open(POOL, encoding="utf-8")):
        o = json.loads(line)
        # 🔴 切片判据确定性可复现（按行号取模），不用随机 —— 随机没法「再跑一次对比」。
        if slice_pct and i % 100 >= slice_pct:
            continue
        out.append(o)
    return out


def read_back():
    """逐条读已跑的结果 ＋ 控制组统计。"""
    if not OUT.exists():
        _sys.exit("🔴 还没有结果")
    src = {o["key"]: o for o in map(json.loads, open(POOL, encoding="utf-8"))}
    st = collections.Counter()
    leak = []
    for line in open(OUT, encoding="utf-8"):
        o = json.loads(line)
        # ⚠️ `ds_batch` 落盘用的字段名是 `id`（meta 的第一元素），不是我们池子里的 `key`。
        k = o.get("id")
        zh = (o.get("zh") or "").strip()
        p = src.get(k) or {}
        # ⚠️ 参数顺序是 `check(zh, src_text, word, pos)` —— 我第一版按 (word, en, zh)
        #    传，三个都是字符串，**不会报错也不会报红**，只会把判据喂给错的位置。
        #    返回的是 [(代号, 说明), …] 不是 [代号]。
        codes = ctrl.check(zh, p.get("en", ""), p.get("word", ""),
                           p.get("pos")) if zh else [("E0", "留空")]
        st["/".join(c for c, _ in codes) if codes else "干净"] += 1
        # 🔴 本轮特有的一条：伞形漏进译文。控制组管不到它（它不是形式特征，
        #    是"这段文字本来该在别处"），只能在这里单独量。
        u = (p.get("umbrella") or "").strip()
        if u and zh and len(u) > 6 and u.rstrip(":").lower()[:12] in zh.lower():
            leak.append((k, u, zh))
    tot = sum(st.values())
    print("■ 共 %s 条" % f(tot))
    for k, v in st.most_common(12):
        print("   %-28s %6s  %5.2f%%" % (k, f(v), v * 100 / max(tot, 1)))
    print("\n■ 伞形漏进译文（规则 2）：%s 条" % f(len(leak)))
    for k, u, zh in leak[:8]:
        print("   %s  伞形=%r → 译文=%r" % (k, u[:34], zh[:34]))
    print("\n■ 随机 12 条：")
    import random
    random.seed(7)
    rows = [json.loads(l) for l in open(OUT, encoding="utf-8")]
    for o in random.sample(rows, min(12, len(rows))):
        p = src.get(o.get("id")) or {}
        print("   %-8s %-6s %r" % (o.get("id"), p.get("word", ""), (p.get("en") or "")[:46]))
        print("            伞形=%r" % (p.get("umbrella") or "")[:40])
        print("            译文=%r" % (o.get("zh") or ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=int)
    ap.add_argument("--read", action="store_true")
    ap.add_argument("--mode", default="flash")
    a = ap.parse_args()
    if a.read:
        return read_back()
    p = pool(a.slice)
    batches, meta = [], []
    for i in range(0, len(p), CHUNK):
        batches.append(p[i:i + CHUNK])
        meta.append([(x["key"], x["key"]) for x in p[i:i + CHUNK]])
    print("■ 池子 %s 条 / %s 批（CHUNK=%d）" % (f(len(p)), f(len(batches)), CHUNK))
    est = sum(len(json.dumps(b, ensure_ascii=False)) for b in batches) / 2.5
    print("■ 粗估入 token ≈ %s" % f(int(est)))
    tok = asyncio.run(ds_run(SYS, batches, meta, OUT, mode=a.mode, conc=10,
                             every=5, thinking="disabled"))
    print("■ 实跑 token %s" % f(tok))


if __name__ == "__main__":
    main()
