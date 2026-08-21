#!/usr/bin/env python3
"""复数列的外锚审计：`dict.plural` 逐条回英文版 dump 核对。2026-08-19（阶段 8 记账项）。

═══ 为什么要这道审计 ═══
阶段 8 查 `braccio` 的双复数时撞见 `paro → 复数 line` —— **页面上就那么写着**。
顺着查下去，根因不是数据脏，是 `build.py` 的 `PLURAL_ARG_RE` **不认识 `<…>` 里的逗号**：

    paro   args: "para<g:f><l:archaic,&,rare><ref:… Treccani on line, Istituto …<<name:trec>>>"
           按逗号裸切 → 'l:archaic' '&' 'line' 'name:trec>>>'
                                     ↑ 文献标题「Vocabolario Treccani on line, Istituto…」里的一个词
           而**真复数 para 被整条丢掉**

一个缺陷同时造成两种后果：**编造出不存在的复数** + **丢掉真复数**。
⇒ 判据只能是回源：拿修正后的解析器重跑一遍 dump，与库里的值逐条比。

═══ 三类输出 ═══
    一致        库里的值确实是源头给的复数形之一
    🔴 编造     库里的值**不在**源头的任何复数形里（`paro → line`）
    ⚠️ 只存了一个  源头给了 ≥2 个复数形，而 `dict.plural` 是单列（`braccio` 的 braccia/bracci）

用法（在 it/ 目录下）：
    python3 probes/plural_audit.py             # 出数
    python3 probes/plural_audit.py --list      # 逐条列出可疑的
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import paths                       # noqa: E402
from build import _valid_plural    # noqa: E402

f = lambda n: format(n, ",")


def parse_plural_arg(spec):
    """it-noun 的第 2+ 个位置参数 → [(复数形, 性别 or None)]。**判据是深度不是逗号。**

    🔴 `<…>` 修饰块里可以有逗号，而且能嵌套（`<ref:… on line, Istituto …<<name:trec>>>`）。
       按逗号裸切会 ① 把文献标题里的词当成复数形 ② 把真复数整条丢掉。
    🔴 深度 0 的 `|` 之后是**别的具名参数**（`|dim=mangiarino,mangiaretto` 是指小词），
       不截断的话 `mangiare` 会把 `mangiaretto` 当成复数。
    """
    cut, depth = [], 0
    for ch in spec:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        if ch == "|" and depth == 0:
            break
        cut.append(ch)
    spec = "".join(cut)

    segs, depth, seg = [], 0, []
    for ch in spec:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            segs.append("".join(seg))
            seg = []
        else:
            seg.append(ch)
    segs.append("".join(seg))

    out = []
    for s in segs:
        s = s.strip()
        if not s:
            continue
        head = s.split("<", 1)[0].strip()          # 修饰块之前的那截才是词形
        if not head or head in ("#", "~", "-", "!", "+", "s") or "=" in head:
            continue
        m = re.search(r"<g:([mf]+)>", s)
        out.append((head, m.group(1) if m else None))
    return out


def plurals_of(e):
    """一条 dump JSON → {(复数形, 性别 or None)}。head_template 与 forms 两处都收。"""
    out = []
    for h in e.get("head_templates") or []:
        if h.get("name") != "it-noun":
            continue
        args = h.get("args") or {}
        for k in sorted((k for k in args if k.isdigit() and int(k) >= 2), key=int):
            for form, g in parse_plural_arg(str(args[k]).strip()):
                if _valid_plural(form):
                    out.append((form, g))
    for fm in e.get("forms") or []:
        tags = fm.get("tags") or []
        if "plural" in tags and "singular" not in tags:
            form = (fm.get("form") or "").strip()
            if _valid_plural(form):
                g = "f" if "feminine" in tags else ("m" if "masculine" in tags else None)
                out.append((form, g))
    seen, uniq = set(), []
    for x in out:
        if x[0] not in seen:
            seen.add(x[0])
            uniq.append(x)
    return uniq


def source_map():
    """扫英文版 dump → {词形: [(复数形, 性别)]}（只看名词条目）。"""
    src = {}
    with open(str(paths.KK), encoding="utf-8") as fh:
        for line in fh:
            if '"pos": "noun"' not in line and '"pos":"noun"' not in line:
                continue
            e = json.loads(line)
            if e.get("pos") != "noun":
                continue
            pl = plurals_of(e)
            if pl:
                src.setdefault(e["word"], []).extend(
                    x for x in pl if x[0] not in {y[0] for y in src.get(e["word"], [])})
    return src


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    print("■ 扫英文版 dump 重建复数真值…", flush=True)
    src = source_map()
    print("   源头给了复数的名词词形 %s 个" % f(len(src)))

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute("SELECT word, plural, plural_gender FROM dict "
                       "WHERE plural IS NOT NULL AND plural<>''").fetchall()
    c = Counter()
    made_up, multi = [], []
    for w, pl, pg in rows:
        forms = src.get(w)
        if not forms:
            c["源头没有这个名词/没给复数（多半来自 it 版或七月流水线）"] += 1
            continue
        names = {x[0] for x in forms}
        if pl in names:
            c["一致"] += 1
        else:
            c["🔴 库里的复数不在源头任何复数形里"] += 1
            made_up.append((w, pl, sorted(names)))
        if len(names) > 1:
            c["⚠️ 源头给了 ≥2 个复数形（单列只存得下一个）"] += 1
            multi.append((w, pl, pg, forms))

    print("\n■ 库里有复数的行 %s" % f(len(rows)))
    for k, v in c.most_common():
        print("   %-46s %s" % (k, f(v)))

    print("\n■ 编造的复数（前 20）")
    for w, pl, names in made_up[:20]:
        print("   %-20s 库=%-14s 源头=%s" % (w[:20], pl[:14], "/".join(names[:3])))
    if a.list and len(made_up) > 20:
        for w, pl, names in made_up[20:]:
            print("   %-20s 库=%-14s 源头=%s" % (w[:20], pl[:14], "/".join(names[:3])))

    print("\n■ 双复数（前 20）")
    for w, pl, pg, forms in multi[:20]:
        print("   %-16s 库=%-10s(%s)  源头=%s"
              % (w[:16], pl[:10], pg or "-", ", ".join("%s(%s)" % (x, g or "-") for x, g in forms)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
