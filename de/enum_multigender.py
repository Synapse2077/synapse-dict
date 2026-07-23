"""只读枚举：kaikki 里所有跨词条多性别名词，看规模 + 每性别 kaikki 的属格/复数写全没写。

零风险第一步（不改库、不重建），供决策 noun_variants 是否动手 / 怎么存。
用法：python3 enum_multigender.py
"""

import json
import re
from collections import defaultdict

import build  # 复用 extract_noun / JSONL_PATH / DE_ALPHA 等

# 每词：gender -> 该性别下观察到的 (genitive, plural) 集合
# 用 list 保留出现，稍后判断是否每性别 gen/pl 不同
word_gender_forms = defaultdict(lambda: defaultdict(set))
# 记录含多性别合并单条（"m/n" 同一 etym）的词，属格/复数无法归到单一性别，单列
combined_gender_words = set()

with open(build.JSONL_PATH, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("lang_code") != "de":
            continue
        if e.get("pos") not in ("noun", "name"):
            continue
        word = (e.get("word") or "").strip()
        if not word:
            continue
        g, gen, pl = build.extract_noun(e, word, e.get("senses", []))
        if not g:
            continue
        genders = g.split("/")
        if len(genders) > 1:
            combined_gender_words.add(word)
        for gg in genders:
            word_gender_forms[word][gg].add((gen, pl))

# 多性别词 = 跨词条出现 >1 个不同性别
multi = {w: gf for w, gf in word_gender_forms.items() if len(gf) > 1}

# 真·多范式 = 属格或复数随性别而不同
def gender_paradigm_differs(gf):
    gens = {gg: {x[0] for x in forms if x[0]} for gg, forms in gf.items()}
    pls = {gg: {x[1] for x in forms if x[1]} for gg, forms in gf.items()}
    # 收集每性别的属格/复数代表值
    gen_by_g = {gg: sorted(v) for gg, v in gens.items() if v}
    pl_by_g = {gg: sorted(v) for gg, v in pls.items() if v}
    # 若至少两性别都各有属格且不同 → 属格随性别变；复数同理
    gen_vals = [tuple(v) for v in gen_by_g.values()]
    pl_vals = [tuple(v) for v in pl_by_g.values()]
    gen_differs = len(gen_by_g) >= 2 and len(set(gen_vals)) > 1
    pl_differs = len(pl_by_g) >= 2 and len(set(pl_vals)) > 1
    return gen_differs or pl_differs

true_paradigm = {w: gf for w, gf in multi.items() if gender_paradigm_differs(gf)}

# kaikki 属格/复数覆盖统计（多性别词里，每 (词,性别) 是否有 gen/pl）
n_pairs = 0
n_pairs_gen = 0
n_pairs_pl = 0
for w, gf in multi.items():
    for gg, forms in gf.items():
        n_pairs += 1
        if any(x[0] for x in forms):
            n_pairs_gen += 1
        if any(x[1] for x in forms):
            n_pairs_pl += 1

print("=" * 60)
print(f"跨词条多性别名词（>1 性别）：{len(multi)} 词")
print(f"  其中真·多范式（属格/复数随性别变）：{len(true_paradigm)} 词")
print(f"  其中含单条合并多性别（'m/n' 同 etym）：{len(combined_gender_words & set(multi))} 词")
print(f"(词,性别) 对：{n_pairs} 个 | kaikki 有属格 {n_pairs_gen} | 有复数 {n_pairs_pl}")
print("=" * 60)


def show(w):
    gf = word_gender_forms.get(w)
    if not gf:
        print(f"  {w}: (kaikki 无多性别 noun 记录)")
        return
    parts = []
    for gg in ("m", "f", "n"):
        if gg in gf:
            forms = sorted(gf[gg], key=lambda x: (x[0] or "", x[1] or ""))
            desc = "; ".join(f"gen={x[0] or '-'},pl={x[1] or '-'}" for x in forms)
            parts.append(f"{gg}[{desc}]")
    print(f"  {w}: {' | '.join(parts)}")


print("\n定向核对（memory 点名）：")
for w in ("Band", "See", "Steuer"):
    show(w)

print("\n真·多范式随机样本（20）：")
import random
random.seed(42)
sample = random.sample(sorted(true_paradigm), min(20, len(true_paradigm)))
for w in sorted(sample):
    show(w)
