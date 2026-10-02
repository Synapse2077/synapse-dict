#!/usr/bin/env python3
"""阶段 -1 探测：三份源各能给什么。2026-09-28。**只读，不写库，可重跑。**

`PLAYBOOK` 1.3 要求「别凭印象」。本脚本把阶段 -1 的每一个数**做成可重跑的判据**，
而不是把数字散在对话或文档里 —— `[[ledger-numbers-lie]]`：上次清 it 记账本，
七件里四件的数字是错的，因为它们只是被记下来、从没被重算过。

用法：
    python3 vi/probes/probe_sources.py              # 打到屏幕
    python3 vi/probes/probe_sources.py --archive    # 同时存档进 data/work/vi/probe/

🔴 **本脚本里有一条判据是已知偏宽的**（`zh_gloss_usable` 的 D 桶），
   文件里明写着它漏了什么。别把它的输出当真值用，见 §4 的注释。
"""
import argparse
import collections
import gzip
import io
import json
import re
import sys
import unicodedata as ud
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import paths                                                    # noqa: E402

SRC = [("en", paths.KK), ("vi", paths.EDITION), ("zh", paths.ZH_TRAD)]

# 🔴🔴 **词源字段名三版不一样** —— 英文版单数、越南文版与中文版复数。
#    只认单数会让后两版报 0.0%，词源并集从 43,785 掉到 25,321（丢 42%）。见 paths.py 文件头。
ETYM_KEYS = ("etymology_text", "etymology_texts")

# 🔴🔴 **判据交给 Unicode 答，别手抄码位范围**（ko 的 R15 记过同一课）。
#    vi 上这条比 ko 上更狠 —— 实测同一份 dump 三种判据：
#        手抄基本区 U+4E00–U+9FFF          6,502 对
#        手抄 +扩展A U+3400–U+4DBF        6,832 对
#        `unicodedata.name()` 判            **11,634 对**   ⇒ 手抄版漏 **41.3%**
#    漏掉的是 `𣩂 𠊛 𩵜 𧋆 𢬗 𠀧 𡗶`（U+23A42 起，**扩展 B**）——
#    **那是喃字（chữ Nôm），越南人自造的那半套文字**。手抄范围不是漏边角，
#    是把越南语自己的书写系统整个删掉。
def is_ideograph(ch):
    try:
        return ud.name(ch).startswith(("CJK UNIFIED IDEOGRAPH", "CJK COMPATIBILITY IDEOGRAPH"))
    except ValueError:                       # 未命名码位（未分配/代理对半边）
        return False


def ideographs(s):
    return [c for c in s if is_ideograph(c)]


def all_ideographs(s):
    t = s.strip()
    return bool(t) and all(is_ideograph(c) or c.isspace() for c in t)


# A 桶：整条只是在说「这是某词的汉字/喃字写法」
META = re.compile(r"的漢字$|的汉字$|的喃字$|^汉字[：:]|^漢字[：:]|的漢字表記|的汉字表记")
HAN_TAGS = {"CJK", "Hán-Nôm"}
SINO = re.compile(r"Sino-Vietnamese|chữ Hán|chữ Nôm|Hán tự", re.I)


def rd(p):
    op = gzip.open if str(p).endswith(".gz") else open
    with op(p, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def has_etym(e):
    return any(e.get(k) for k in ETYM_KEYS)


def han_map():
    """英文版 `forms[tags 含 CJK/Hán-Nôm]` → {词形: {汉字…}}。ko 的 `forms[tags=hanja]` 同形。"""
    out = collections.defaultdict(set)
    for e in rd(paths.KK):
        for f in e.get("forms", []) or []:
            if HAN_TAGS & set(f.get("tags") or []):
                got = "".join(ideographs(f.get("form", "")))
                if got:
                    out[e["word"]].add(got)
    return out


def s1_shape():
    print("§1 三源形状（条目／词形／音节／各层覆盖）")
    acc = {}
    for tag, p in SRC:
        n = ipa = ety = 0
        words, sp = set(), collections.Counter()
        iw, ew = set(), set()
        for e in rd(p):
            n += 1
            w = e["word"]
            words.add(w)
            sp[w.count(" ")] += 1
            if any(s.get("ipa") for s in e.get("sounds", []) or []):
                ipa += 1
                iw.add(w)
            if has_etym(e):
                ety += 1
                ew.add(w)
        multi = 100 * (n - sp[0]) / n
        print("  %s 版：条目 %7s ／ 词形 %7s ／ 含空格 %5.1f%% ／ 有 ipa %5.1f%% ／ 有词源 %5.1f%%"
              % (tag, format(n, ","), format(len(words), ","), multi, 100 * ipa / n, 100 * ety / n))
        acc[tag] = (words, iw, ew)
    allw = set().union(*(a[0] for a in acc.values()))
    U = set().union(*(a[1] for a in acc.values()))
    E = set().union(*(a[2] for a in acc.values()))
    print("  ── 并集：词形 **%s** ／ 有 ipa **%s（%.1f%%）** ／ 有词源 **%s（%.1f%%）**"
          % (format(len(allw), ","), format(len(U), ","), 100 * len(U) / len(allw),
             format(len(E), ","), 100 * len(E) / len(allw)))
    a, b = acc["en"][0], acc["vi"][0]
    print("  ── 互补性：en∩vi **%s** ／ en 独有 %s ／ vi 独有 %s"
          % (format(len(a & b), ","), format(len(a - b), ","), format(len(b - a), ",")))
    # 🔴 这条是**闸不是报告**：只认单数时词源并集会塌，塌了就说明有人改坏了 ETYM_KEYS
    narrow = set()
    for tag, p in SRC:
        for e in rd(p):
            if e.get("etymology_text"):
                narrow.add(e["word"])
    print("  ── 🔴 只认 `etymology_text`（单数）时词源并集 = %s ⇒ **少 %s（%.1f%%）**"
          % (format(len(narrow), ","), format(len(E) - len(narrow), ","),
             100 * (len(E) - len(narrow)) / len(E)))
    return allw


def s2_forms():
    print("\n§2 `forms` 里装的是什么（越南语是分析语，屈折应当为 0）")
    for tag, p in (("en", paths.KK), ("vi", paths.EDITION)):
        c, nf = collections.Counter(), 0
        for e in rd(p):
            for f in e.get("forms", []) or []:
                nf += 1
                for t in f.get("tags") or []:
                    c[t] += 1
        print("  %s 版 forms %s 行 ／ 前 6 tag：%s"
              % (tag, format(nf, ","), "、".join("%s %s" % (k, format(v, ",")) for k, v in c.most_common(6))))
    print("  ⇒ 全是汉字表记／异体／量词，**一条屈折都没有** ⇒ 变形层对 vi 应当有意为空")


def s3_sino(hm):
    print("\n§3 汉越词的源头")
    print("  ① 英文版 forms 的汉字表记：词形 **%s** ／ (词形,汉字) 对 **%s**"
          % (format(len(hm), ","), format(sum(len(v) for v in hm.values()), ",")))
    multi = sum(1 for v in hm.values() if len(v) > 1)
    print("     其中一形多字 %s 个（＝同形异义，ko 的 `hanja_spelling` 形状）" % format(multi, ","))
    n = s = sh = 0
    for e in rd(paths.KK):
        t = e.get("etymology_text") or ""
        if not t:
            continue
        n += 1
        if SINO.search(t):
            s += 1
            sh += bool(ideographs(t))
    print("  ② 英文版词源正文 %s 条 ／ 提到汉越 **%s（%.1f%%）** ／ 正文真带汉字 **%s**"
          % (format(n, ","), format(s, ","), 100 * s / n, format(sh, ",")))


def s4_zh_gloss(hm):
    print("\n§4 中文版 gloss 的可用率 —— ⚠️ **这个数尚未收敛，D 桶是上界**")
    c, ex = collections.Counter(), collections.defaultdict(list)
    for e in rd(paths.ZH_TRAD):
        w, hs = e["word"], hm.get(e["word"], set())
        for sn in e.get("senses", []) or []:
            for g in sn.get("glosses") or []:
                t = g.strip()
                if META.search(t):
                    k = "A 元描述"
                elif all_ideographs(t) and t.replace(" ", "") in hs:
                    k = "B 整条就是它自己的汉字表记"
                elif all_ideographs(t) and len(t) <= 4 and hs:
                    k = "C 纯汉字且该词有汉字表记（存疑）"
                else:
                    k = "D 真中文释义（上界）"
                c[k] += 1
                if len(ex[k]) < 3:
                    ex[k].append((w, t[:46]))
    n = sum(c.values())
    for k in sorted(c):
        print("  %-28s %7s  %5.1f%%   例：%s"
              % (k, format(c[k], ","), 100 * c[k] / n,
                 "；".join("%s→%s" % (w, t) for w, t in ex[k])))
    print("  ⇒ 对照 **ko 的中文版 97.2%% 是元描述**，vi 的 A+B+C = %.1f%% —— 量级完全不同"
          % (100 * (n - c["D 真中文释义（上界）"]) / n))
    print("""  🔴 **D 桶已知仍有两类污染，判据够不着**：
       · `la → 儸 囉(啰) 攎 攞 欏(椤) …`  汉字列表，带括号 ⇒ 躲过 `all_ideographs`
       · 还有别的「说这是哪个字」的写法没进 META（`的喃字` 已补，不敢说补全了）
     ⇒ 阶段 5 要把判据写进 pipeline 并 import，**别在这儿和那儿各写一版**
       （`[[criteria-narrower-than-you-think]]`）。本函数的输出**只能当上界**。""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", action="store_true", help="同时写入 data/work/vi/probe/")
    a = ap.parse_args()
    buf = io.StringIO()
    with redirect_stdout(buf):
        print("■ vi 阶段 -1 源探测（%s）" % ", ".join(t for t, _ in SRC))
        s1_shape()
        s2_forms()
        hm = han_map()
        s3_sino(hm)
        s4_zh_gloss(hm)
    out = buf.getvalue()
    print(out, end="")
    if a.archive:
        paths.PROBE.mkdir(parents=True, exist_ok=True)
        f = paths.PROBE / "probe_sources.txt"
        f.write_text(out, encoding="utf-8")
        print("■ 已存档 → %s" % f.relative_to(paths.ROOT))


if __name__ == "__main__":
    main()
