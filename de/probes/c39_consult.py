#!/usr/bin/env python3
"""收尾单 C39 —— 生成**盲测 A/B 咨询材料**：这些德语音标，哪一边是对的。2026-09-05。

═══ 为什么要问 ═══
C39 的残差已经从 36,090 压到 1,374，而我逐族看下来的判断是
「**几乎全是法语版自己的转写缺陷，不是我们的错**」。
那个判断决定了 C39 做不做，所以**不能由我一个人拍板**
（`[[consult-two-models-on-rules]]`：关键判断同时问两家，我有最终决断权）。

═══ 🔴 盲测：材料里不许出现「哪边是我们的」═══
甲/乙 两侧**按词随机对调**（固定种子，可复现）。理由不是形式主义：
`[[context-you-give-leaks-into-output]]` —— 给模型的「仅供参考」上下文会直接漏进输出；
只要写了「乙是我们的库」，模型多半会顺着我想听的答。
⚠️ 也**不写我的结论**（`scripts/consult.py` 头部那条：别把结论写进材料标题，
   两家「收敛」的可能只是我的偏见）。

═══ 抽样口径 ═══
**按族分层抽**，不是随机抽 —— 随机抽 32 条会全落在最大的那两族上，
剩下的族一条都问不到（同契约闸「按形状取样」那条理由）。

用法（在 de/ 目录下）：
    python3 probes/c39_consult.py > ../data/work/de/probe/consult_c39_20260905.md
    python3 ../scripts/consult.py ../data/work/de/probe/consult_c39_20260905.md
"""
import difflib
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE))

from c39_fr_audit import CONTESTED, SEP_PREFIX, _marks, load        # noqa: E402
from ipa_conventions import BUCKETS, bucket, full_key, refine, variants  # noqa: E402

SEED = 20260905
PER_FAMILY = 2
REAL = ("⑨", "③b", "④b")


def classify(rows):
    """→ {族名: [(词形, 我们的, 法语版的)]}，只收「待看清单」那几桶。"""
    rank = {nn: j for j, (nn, _) in enumerate(BUCKETS)}
    fam = defaultdict(list)
    for w, P, A, B in rows:
        if {v for p in P for v in variants(p)} & {v for b in B for v in variants(b)}:
            continue
        if {v for x in A for v in variants(x)} & {v for b in B for v in variants(b)}:
            continue
        x, y, nm, best = sorted(P)[0], sorted(B)[0], None, 99
        for p in sorted(P):
            for b in sorted(B):
                raw = bucket(p, b)
                i = rank.get(raw, 98)
                if i < best:
                    best, nm, x, y = i, refine(raw, p, b), p, b
        if nm and nm.startswith("⑨"):
            nx, ny = _marks(x), _marks(y)
            if any(fn(nx, ny) for _c, fn in CONTESTED):
                continue
        elif nm and nm.startswith("③b") and w.lower().startswith(SEP_PREFIX):
            continue
        if not nm or not nm.startswith(REAL):
            continue
        if nm.startswith("③b"):
            key = "主重音落在不同音节"
        elif nm.startswith("④b"):
            key = "元音长短不同"
        else:
            a2, b2 = full_key(x), full_key(y)
            op = [(a2[i1:i2], b2[j1:j2]) for t, i1, i2, j1, j2 in
                  difflib.SequenceMatcher(None, a2, b2, autojunk=False).get_opcodes()
                  if t != "equal"]
            key = ("%s / %s" % (op[0][0] or "∅", op[0][1] or "∅")
                   if len(op) == 1 else "多处不同")
        fam[key].append((w, x, y))
    return fam


def main():
    rnd = random.Random(SEED)
    fam = classify(load())
    big = [k for k, v in sorted(fam.items(), key=lambda kv: -len(kv[1])) if len(v) >= 8][:14]

    print("# 德语音标：两个来源不一致，请判断哪一边正确\n")
    print("下面每一条是**同一个德语词形**在两份词典数据里的音标，两边不一致。")
    print("请对每一条给出：**甲对 / 乙对 / 两个都对（都是可接受的变体或方言）/ 两个都不对**，")
    print("并用一句话说明理由（涉及哪条德语音系规则）。\n")
    print("判断标准是**标准德语（Standardlautung, Duden/DAWB 口径）**。")
    print("如果一条属于「两种读法都载入词典」的情况（地域变体、可分/不可分动词等），"
          "请明确选「两个都对」——不要在两个正确答案之间硬选一个。\n")
    print("⚠️ 甲/乙 的先后顺序是**逐条随机**的，两边没有固定的来源。\n")

    n = 0
    for k in big:
        items = fam[k][:]
        rnd.shuffle(items)
        print("\n## 差异类型：%s（这一类共 %d 条，抽 %d 条）\n"
              % (k, len(fam[k]), min(PER_FAMILY, len(items))))
        for w, ours, fr in items[:PER_FAMILY]:
            n += 1
            ours_is_first = rnd.random() < 0.5
            a, b = (ours, fr) if ours_is_first else (fr, ours)
            print("%d. **%s**   甲 `%s`   乙 `%s`" % (n, w, a, b))
            # 🔴 **答案钥匙走 stderr**，与材料同一遍随机、同一个种子 ——
            #    分两次跑「材料」和「钥匙」总有一天会错位
            #    （`[[model-answer-files-key-by-id]]` 的同一个形状：按顺序对齐会贴错）。
            print("KEY\t%d\t%s\t%s\t%s" % (n, w, "甲" if ours_is_first else "乙", k),
                  file=sys.stderr)

    print("\n---\n")
    print("最后请回答一个总体问题：**这两份数据里，有没有哪一份在系统性地犯某一类错误？**")
    print("如果有，请指出是哪一类错误、以及你据以判断的条目编号。")
    print("\n（共 %d 条）" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
