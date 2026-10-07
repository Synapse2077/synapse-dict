#!/usr/bin/env python3
"""阶段 -1 探测②：**重音住在哪**，以及 ru 版那 428 万条关系是什么。2026-10-07。只读可重跑。

═══ 🔴🔴🔴 为什么有这个脚本：`RU_PLAN` 的一个前提量反了 ═══
计划表 §0.2③ 预期「ru 版给词头标重音位置（`ко́шка`）」，于是 `norm_ru` 要去 U+0301。
`probe_sources.py` 实测**词头带重音符的比例是 0.00%**（七源最高 4 个条目）：

    en 1 ／ ru 0 ／ zh-s 3 ／ zh-t 0 ／ fr 4 ／ vi 0 ／ pl 0

⇒ 去重音符这件事**对词头是空操作**。而重音对俄语是**辨义的**
  （`замо́к` 锁 ／ `за́мок` 城堡）且屈折时会移动，学习者词典不标重音是重大缺陷。
  ⇒ 所以真问题不是「要不要去」，是「**重音在哪**」。
  §5 的 hyphenations 样例当场给了线索（`эбонитовый → э·бо/ни́/то/вый`）——
  本脚本把它量准，并顺带扫 `forms` / `sounds` 两个候选位置。

⚠️ `[[measure-landing-not-source]]` 的变体：这次是**前提量反了**，而不是落点量错了。
   前提错了而结论（「`norm_ru` 要去 U+0301」）仍然对 —— 但**理由不一样了**，
   于是「什么会推翻它」也不一样。如实改。

═══ 🔴 第二件：ru 版 `related` 428 万条，是 `BACKLOG` B17 的形状 ═══
B17：vi 的 naive 判据宽 11 倍，差的全是 `paronym + related`，而 paronym 是**语音**关系。
ru 版 `w:related` **4,284,809** 条（489,522 个条目，人均 8.8 条）——
俄语维基词典的「родственные слова」是**整个构词词族**（словообразовательное гнездо），
那是个合法的大段落，但**它不是「相关词」**。量清楚它的形状再决定进不进关系层。

用法：
    python3 ru/probes/probe_stress.py [--limit N] [--archive]
"""
import argparse
import collections
import gzip
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402

STRESS = "́"

SRC = [
    ("en", paths.KK),
    ("ru", paths.EDITION),
    ("zh-s", paths.ZH_SIMP),
    ("zh-t", paths.ZH_TRAD),
    ("fr", paths.FR_EDITION),
    ("vi", paths.VI_EDITION),
    ("pl", paths.PL_EDITION),
]


def rd(p, limit=None):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                return
            yield json.loads(line)


def pct(a, b):
    return "%6.2f%%" % (100.0 * a / b) if b else "     —"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--archive", action="store_true")
    a = ap.parse_args()
    limit = a.limit or None

    acc = {}
    for name, p in SRC:
        d = {
            "lines": 0,
            # ── 重音的四个候选位置 ──
            "w_stress": 0,                 # 词头
            "hyph": 0, "hyph_stress": 0,   # hyphenations.parts
            "forms": 0, "forms_stress": 0, # forms[].form
            "canon": 0, "canon_stress": 0, # forms[tags 含 canonical] —— 「规范写法」
            "ipa_mark": 0, "ipa_n": 0,     # IPA 里的 ˈ（它标的是重音，但那是音标不是拼写）
            # ── 关系的形状 ──
            "rel_items": collections.Counter(),
            "rel_shape": collections.Counter(),
            "rel_keys": collections.Counter(),
            "rel_sample": [],
            # ── IPA 定界符：**判据加上反斜杠**，见下面注释 ──
            "delim": collections.Counter(),
            "delim_other": [],
        }
        for e in rd(p, limit):
            d["lines"] += 1
            w = e.get("word") or ""
            if STRESS in w:
                d["w_stress"] += 1
            for h in e.get("hyphenations") or []:
                d["hyph"] += 1
                if STRESS in "".join(h.get("parts") or []):
                    d["hyph_stress"] += 1
            for f in e.get("forms") or []:
                fm = f.get("form") or ""
                d["forms"] += 1
                if STRESS in fm:
                    d["forms_stress"] += 1
                if "canonical" in (f.get("tags") or []):
                    d["canon"] += 1
                    if STRESS in fm:
                        d["canon_stress"] += 1
            for s in e.get("sounds") or []:
                ip = s.get("ipa")
                if not ip:
                    continue
                d["ipa_n"] += 1
                if "ˈ" in ip:
                    d["ipa_mark"] += 1
                # 🔴🔴 **`probe_sources.py` 第一版的判据漏了反斜杠**：
                #    法语版写 `\vɐ.ˈda\`，而第一版只认 `[` 和 `/`，其余一律归「裸」
                #    ⇒ **19,826 行被塞进了「裸」这个残差桶**
                #    （`[[residual-bucket-is-not-evidence]]`：「其他」桶是残差不是度量，
                #      消去器少一条它就虚胖）。
                # 🔴 补齐之后判据**搬进了 `criteria.py`，这里 import 不重写** ——
                #    本脚本和 `probe_sources.py` 一度各写一份，那正是要禁的形状。
                k = criteria.ipa_delimiter(ip)
                d["delim"][k] += 1
                if k in ("裸", "其他") and len(d["delim_other"]) < 5:
                    d["delim_other"].append(ip[:40])
            for k in ("related", "synonyms", "antonyms", "derived", "hypernyms",
                      "hyponyms", "holonyms", "meronyms", "proverbs", "descendants",
                      "coordinate_terms"):
                v = e.get(k)
                if not v:
                    continue
                d["rel_items"][k] += len(v)
                for it in v:
                    d["rel_shape"][k + ":" + type(it).__name__] += 1
                    if isinstance(it, dict):
                        for kk in it:
                            d["rel_keys"][k + "." + kk] += 1
                if k == "related" and len(d["rel_sample"]) < 6:
                    d["rel_sample"].append((w, len(v), v[:3]))
        acc[name] = d
        print("  · %-5s %9s 行" % (name, "{:,}".format(d["lines"])), file=sys.stderr)

    buf = io.StringIO()
    with redirect_stdout(buf):
        print("■ 俄语阶段 -1 探测②：重音住在哪 / 关系的形状  2026-10-07"
              + ("（--limit %d）" % a.limit if a.limit else "（全量）"))

        print("\n" + "═" * 78)
        print("§ A 🔴🔴🔴 重音住在哪 —— 四个候选位置逐个量")
        print("═" * 78)
        print("  %-6s%14s%22s%20s%18s" % (
            "源", "词头带重音", "hyphenations 带重音", "forms 带重音", "canonical 带重音"))
        print("  " + "-" * 76)
        for name, _ in SRC:
            d = acc[name]
            print("  %-6s%7s %s%12s %s%10s %s%9s %s" % (
                name,
                "{:,}".format(d["w_stress"]), pct(d["w_stress"], max(d["lines"], 1)),
                "{:,}".format(d["hyph_stress"]), pct(d["hyph_stress"], max(d["hyph"], 1)),
                "{:,}".format(d["forms_stress"]), pct(d["forms_stress"], max(d["forms"], 1)),
                "{:,}".format(d["canon_stress"]), pct(d["canon_stress"], max(d["canon"], 1))))
        print("\n  ⚠️ 分母各不相同：词头按**条目数**，后三列按**那个字段自己的行数**。")
        print("     （`[[measure-landing-not-source]]`：同一件事量出三个数，多半是量了三件事。）")
        print("\n  %-6s%16s%22s" % ("源", "带 ipa 的 sound", "IPA 里有 ˈ 的"))
        print("  " + "-" * 46)
        for name, _ in SRC:
            d = acc[name]
            print("  %-6s%16s%14s %s" % (
                name, "{:,}".format(d["ipa_n"]),
                "{:,}".format(d["ipa_mark"]), pct(d["ipa_mark"], max(d["ipa_n"], 1))))
        print("\n  🔴 **IPA 里的 ˈ 不能代替拼写上的重音符**：读者要的是 `замо́к` 这种**正字**")
        print("     标记（词典惯例），而 `[zɐˈmok]` 是音标。两者都要，但不能互相顶替。")

        print("\n" + "═" * 78)
        print("§ B IPA 定界符 —— **判据补上反斜杠之后**（第一版把 `\\…\\` 归进了「裸」）")
        print("═" * 78)
        for name, _ in SRC:
            d = acc[name]
            print("  %-6s%s" % (name, "  ".join(
                "%s %s" % (k, "{:,}".format(v)) for k, v in d["delim"].most_common())))
            if d["delim_other"]:
                print("         「裸」桶里的样子：%s" % " ｜ ".join(d["delim_other"]))
        print("\n  ⇒ 入库前要剥的定界符是**一个集合**，不是一个字符。")
        print("    `[[ipa-bare-storage-convention]]`：六语种统一裸存，展示层加 `/.../`。")

        print("\n" + "═" * 78)
        print("§ C 关系的形状 —— ru 版 `related` 428 万条是什么（`BACKLOG` B17）")
        print("═" * 78)
        for name, _ in SRC:
            d = acc[name]
            if not d["rel_items"]:
                continue
            print("\n  ── %s" % name)
            for k, c in d["rel_items"].most_common(12):
                shapes = {s.split(":")[1]: v for s, v in d["rel_shape"].items()
                          if s.startswith(k + ":")}
                print("     %-18s %10s   元素类型 %s" % (
                    k, "{:,}".format(c),
                    "、".join("%s×%s" % (t, "{:,}".format(v)) for t, v in shapes.items())))
            if d["rel_keys"]:
                print("     字段名（dict 元素里出现过的键）：")
                for k, c in d["rel_keys"].most_common(12):
                    print("        %-28s %10s" % (k, "{:,}".format(c)))
        print("\n  ── ru 版 `related` 样例（词 / 条数 / 前三条）")
        for w, n, v in acc["ru"]["rel_sample"]:
            print("     %-18s %5d 条   %s" % (w[:16], n, str(v)[:90]))
        print("\n  🔴 428 万 ÷ 48.9 万条目 ＝ 人均 8.8 条。俄语版的「родственные слова」")
        print("    （构词词族／словообразовательное гнездо）是一个合法的大段落，")
        print("    **但它不是「相关词」** —— 进关系层之前必须定它映射到哪个 kind，")
        print("    或者单独成层。`BACKLOG` B17 警告过的就是这个形状（vi 宽 11 倍）。")
    txt = buf.getvalue()
    print(txt)
    if a.archive:
        paths.PROBE.mkdir(parents=True, exist_ok=True)
        out = paths.PROBE / "probe_stress.txt"
        out.write_text(txt, "utf-8")
        print("■ 已存档 → %s" % out, file=sys.stderr)


if __name__ == "__main__":
    main()
