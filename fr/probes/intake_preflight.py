#!/usr/bin/env python3
"""阶段 3b 收词前的**落点预检**。2026-08-22。

═══ 为什么必须先做这一步 ═══
`[[measure-landing-not-source]]` 是本项目最高频的自伤错误（两天犯十次）：
**量源头有多少，不量能落到库里多少行。**
残差表里那 1,667,018 是**dump 里的原始字符串集**与库做的差集 —— 那是**上界**。
真落库要过归一，其中一部分会塌回已有行。别的版本上实测有 13.3% 是这种"假新词"。

本脚本在写任何一行之前回答四个问题：
  ① 有多少"新词"其实只差**大小写 / 重音符 / 撇号**（归一后与已有行重合）
  ② 法文版的 `pos` 值域是什么（能不能套英文版的 POS_MAP）
  ③ 法文版有没有 `etymology_number`（it 那轮踩过：意语版没有，用 `etymology_texts` 复数
     ⇒ `kk-en:<w>:<pos>:<etym>:<seq>` 那套 src_ref 键**不能直接套**）
  ④ 新词里有多少是变形指针、多少像词头（决定 3b 要不要建 `inflection`）

⚠️ 撇号是法语的重灾区：`l'homme` 的撇号有直撇 `'`（U+0027）和弯撇 `’`（U+2019）两种写法，
   两版约定可能不同。不先量就插，会造出一整批看不见的重复词条。

跑：python3 probes/intake_preflight.py      （在 fr/ 目录下，约 10 分钟）
"""
import gzip
import json
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import paths   # noqa: E402
from build_entry_layer import POS_MAP   # noqa: E402

APOS = {"’": "'", "ʼ": "'", "‘": "'"}


def deapos(s):
    for a, b in APOS.items():
        s = s.replace(a, b)
    return s


def deacc(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if not unicodedata.combining(c))


def main():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {w for (w,) in con.execute("SELECT word FROM dict")}
    have_fold = {w.casefold() for w in have}
    have_apos = {deapos(w).casefold() for w in have}
    have_acc = {deacc(w.casefold()) for w in have}
    print("■ 库内词形 %s" % f"{len(have):,}")

    pos_c = Counter()
    etym_have = etym_none = 0
    new_exact = set()
    per_word_pointer = defaultdict(lambda: [0, 0])    # word → [指针义项, 真释义]
    n_entry = 0

    with gzip.open(paths.EDITION, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("lang_code") != "fr":
                continue
            w = (e.get("word") or "").strip()
            if not w:
                continue
            n_entry += 1
            pos_c[e.get("pos") or ""] += 1
            if e.get("etymology_number") is not None:
                etym_have += 1
            else:
                etym_none += 1
            if w not in have:
                new_exact.add(w)
            for s in e.get("senses") or []:
                if s.get("form_of") or s.get("alt_of"):
                    per_word_pointer[w][0] += 1
                elif s.get("glosses"):
                    per_word_pointer[w][1] += 1

    print("■ 法文版 fr 条目 %s / 不同词形 %s"
          % (f"{n_entry:,}", f"{len(per_word_pointer):,}"))
    print("■ **精确大小写**下库里没有的词形：%s" % f"{len(new_exact):,}")

    print("\n── ① 这些「新词」里有多少归一后会塌回已有行 ──")
    n_case = n_apos = n_acc = 0
    ex = {"case": [], "apos": [], "acc": []}
    for w in new_exact:
        if w.casefold() in have_fold:
            n_case += 1
            if len(ex["case"]) < 4:
                ex["case"].append(w)
        elif deapos(w).casefold() in have_apos:
            n_apos += 1
            if len(ex["apos"]) < 4:
                ex["apos"].append(w)
        elif deacc(w.casefold()) in have_acc:
            n_acc += 1
            if len(ex["acc"]) < 4:
                ex["acc"].append(w)
    net = len(new_exact) - n_case - n_apos - n_acc
    for k, v, e_ in (("只差大小写", n_case, ex["case"]), ("只差撇号", n_apos, ex["apos"]),
                     ("只差重音符", n_acc, ex["acc"])):
        print("   %-12s %9s  %5.2f%%   %s"
              % (k, f"{v:,}", 100.0 * v / max(len(new_exact), 1), e_))
    print("   %-12s %9s  ← 真正的新词" % ("净新词", f"{net:,}"))
    print("   🔴 **大小写这一族必须原样收**（3a 刚证明 `Écosse`/`écosse` 是两个词）；")
    print("      撇号/重音符那两族要逐条看是**异体**还是**同一个词的两种写法**。")

    print("\n── ② 法文版的 pos 值域（前 20）──")
    unknown = [p for p in pos_c if p not in POS_MAP]
    for p, v in pos_c.most_common(20):
        print("   %-16s %9s %s" % (p, f"{v:,}", "🔴 不在 POS_MAP 里" if p not in POS_MAP else ""))
    print("   🔴 POS_MAP 覆盖不到的 pos 共 %d 种，占 %s 条目"
          % (len(unknown), f"{sum(pos_c[p] for p in unknown):,}"))

    print("\n── ③ etymology_number ──")
    print("   有 %s / 无 %s" % (f"{etym_have:,}", f"{etym_none:,}"))
    if etym_have == 0:
        print("   🔴 法文版**没有** etymology_number ⇒ src_ref 键不能照抄英文版那套，")
        print("      得用 `kk-fr:<词形>:<词性>#<该键第几条JSON>` （it 那轮同样处理）")

    print("\n── ④ 新词的成分（决定 3b 要不要建 inflection）──")
    only_ptr = sum(1 for w in new_exact if per_word_pointer[w][1] == 0
                   and per_word_pointer[w][0] > 0)
    has_real = sum(1 for w in new_exact if per_word_pointer[w][1] > 0)
    neither = len(new_exact) - only_ptr - has_real
    for k, v in (("纯变形指针（像变位形）", only_ptr), ("有真释义（像词头）", has_real),
                 ("两者皆无", neither)):
        print("   %-22s %9s  %5.1f%%" % (k, f"{v:,}", 100.0 * v / max(len(new_exact), 1)))


if __name__ == "__main__":
    sys.exit(main())
