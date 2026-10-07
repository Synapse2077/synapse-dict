#!/usr/bin/env python3
"""阶段 -1 探测：七份源各能给什么。2026-10-07。**只读，不写库，可重跑。**

`PLAYBOOK` 1.3 要求「别凭印象」。本脚本把阶段 -1 的每一个数**做成可重跑的判据**，
而不是把数字散在对话或文档里 —— `[[ledger-numbers-lie]]`：上次清 it 记账本，
七件里四件的数字是错的，因为它们只是被记下来、从没被重算过。

用法：
    python3 ru/probes/probe_sources.py              # 打到屏幕
    python3 ru/probes/probe_sources.py --archive    # 同时存档进 data/work/ru/probe/
    python3 ru/probes/probe_sources.py --limit 20000  # 每份只读前 N 行（改判据时先这样跑）

═══ 🔴 本脚本刻意**先量形状、再写判据** ═══
§9（中文释义可用率）只**抽样打印**，不给结论。
理由：ko 的 K24 是「白送中文释义 206,091 条」里 **97.2% 是元描述**，
而我量它时**第一版判据又太宽**（自写「不全是汉字就算真释义」，报 173,887 而真值 6）。
⇒ 判据要先看见数据长什么样再写，写完放进 `ru/pipeline/criteria.py`（唯一的家），
  本脚本 import 它、不重写。现在那个文件还不存在，所以 §9 只打样本。

═══ 🔴🔴 顶层字段名**全部打出来**（§2）═══
ko 的 **K36**：「只有英文版有词源」是**从错的字段名上读到的一个 0**（单数 vs 复数），
漏 48.5%，阶段 7 的 ✅ 被撤回。vi 同一个坑第二次。
⇒ 规矩：**写「某版没有 X」之前，先把该版的顶层字段名全打出来看一眼。**
  本脚本 §1 无条件打印每份源的全部顶层字段及出现率，不挑。
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
from pipeline import criteria                                   # noqa: E402

SRC = [
    ("en", paths.KK),
    ("ru", paths.EDITION),
    ("zh-s", paths.ZH_SIMP),
    ("zh-t", paths.ZH_TRAD),
    ("fr", paths.FR_EDITION),
    ("vi", paths.VI_EDITION),
    ("pl", paths.PL_EDITION),
]

# 🔴🔴 词源字段名**两版不一样**：英文版单数、其余各版复数。见 `paths.py` 文件头。
ETYM_KEYS = ("etymology_text", "etymology_texts")

STRESS = "́"        # COMBINING ACUTE ACCENT —— 重读符
BREVE = "̆"         # COMBINING BREVE       —— й 分解后的那一半
DIAERESIS = "̈"     # COMBINING DIAERESIS   —— ё 分解后的那一半


def rd(p, limit=None):
    op = gzip.open if str(p).endswith(".gz") else open
    with op(p, "rt", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                return
            yield json.loads(line)


def pct(a, b):
    return "%6.2f%%" % (100.0 * a / b) if b else "     —"


def head(t):
    print("\n" + "═" * 78)
    print("§ " + t)
    print("═" * 78)


# ══════════════════════════════════════════════════════════════════════════
def scan(limit=None):
    """一遍扫完，所有统计共用这一次 I/O。→ {src: acc}"""
    out = {}
    for name, p in SRC:
        a = {
            "lines": 0, "senses": 0, "glosses": 0,
            "words": set(), "keys": collections.Counter(),
            "sense_keys": collections.Counter(),
            "pos": collections.Counter(),
            # 词源
            "etym_sing": 0, "etym_plur": 0, "etym_tmpl": 0, "etym_links": 0,
            # ё / й / 重音符
            "w_yo": 0, "w_stress": 0, "w_breve_decomp": 0, "w_diaer_decomp": 0,
            "g_yo": 0, "g_len": 0,
            "nfc_mismatch": 0,
            # 音标
            "ipa_n": 0, "ipa_delim": collections.Counter(), "ipa_sample": [],
            # forms / 屈折
            "forms_rows": 0, "forms_tags": collections.Counter(),
            "has_forms": 0, "form_of": 0, "has_hyph": 0, "hyph_sample": [],
            # 例句 / 关系 / 录音
            "ex": 0, "ex_tr": 0, "audio": 0,
            "rel": collections.Counter(),
            # 抽样
            "gloss_sample": [],
        }
        for e in rd(p, limit):
            a["lines"] += 1
            w = e.get("word") or ""
            a["words"].add(w)
            for k in e:
                a["keys"][k] += 1
            a["pos"][e.get("pos") or "—"] += 1

            if e.get("etymology_text"):
                a["etym_sing"] += 1
            if e.get("etymology_texts"):
                a["etym_plur"] += 1
            if e.get("etymology_templates"):
                a["etym_tmpl"] += 1
            if e.get("etymology_links"):
                a["etym_links"] += 1

            # ── 词头的字符学 ──
            if "ё" in w or "Ё" in w:
                a["w_yo"] += 1
            if STRESS in w:
                a["w_stress"] += 1
            # 🔴 **分解态检查**：源头如果给的是 `и`+U+0306 而不是 `й`，
            #    那么「不做 NFD」的归一会把同一个词分成两个键。必须量，不能假设源头是 NFC。
            if BREVE in w:
                a["w_breve_decomp"] += 1
            if DIAERESIS in w:
                a["w_diaer_decomp"] += 1
            if ud.normalize("NFC", w) != w:
                a["nfc_mismatch"] += 1

            # ── 音标：ru 版用方括号，别门用斜杠（§0.2④）──
            for s in e.get("sounds") or []:
                ip = s.get("ipa")
                if ip:
                    a["ipa_n"] += 1
                    # 🔴 判据 **import 不重写**（`criteria.py` 文件头 ⚠️②）。
                    #    本脚本第一版在这里手写了「只认 `[` 和 `/`，其余算裸」，
                    #    于是法语版的 19,818 行反斜杠被塞进了「裸」这个残差桶。
                    a["ipa_delim"][criteria.ipa_delimiter(ip)] += 1
                    if len(a["ipa_sample"]) < 6:
                        a["ipa_sample"].append("%s %s" % (w, ip))
                if s.get("audio") or s.get("ogg_url") or s.get("mp3_url"):
                    a["audio"] += 1

            # ── forms：屈折层的规模与形状 ──
            fs = e.get("forms") or []
            if fs:
                a["has_forms"] += 1
            for f in fs:
                a["forms_rows"] += 1
                for t in f.get("tags") or ["（无 tag）"]:
                    a["forms_tags"][t] += 1

            # 指针：这个词形是不是某个词元的屈折形
            if e.get("form_of") or any(
                    s.get("form_of") for s in e.get("senses") or []):
                a["form_of"] += 1
            if e.get("hyphenations"):
                a["has_hyph"] += 1
                if len(a["hyph_sample"]) < 5:
                    a["hyph_sample"].append("%s %s" % (w, e["hyphenations"]))

            # ── 关系：**词级与义项级两处都要取**（es 只取词级漏 20,193 条）──
            for k in ("synonyms", "antonyms", "derived", "related", "hypernyms",
                      "hyponyms", "holonyms", "meronyms", "proverbs", "descendants"):
                if e.get(k):
                    a["rel"]["w:" + k] += len(e[k])

            for s in e.get("senses") or []:
                a["senses"] += 1
                for k in s:
                    a["sense_keys"][k] += 1
                for g in s.get("glosses") or []:
                    a["glosses"] += 1
                    a["g_len"] += len(g)
                    if "ё" in g or "Ё" in g:
                        a["g_yo"] += 1
                    if len(a["gloss_sample"]) < 400:
                        a["gloss_sample"].append((w, e.get("pos"), g))
                for ex in s.get("examples") or []:
                    a["ex"] += 1
                    if ex.get("english") or ex.get("translation"):
                        a["ex_tr"] += 1
                for k in ("synonyms", "antonyms", "derived", "related",
                          "hypernyms", "hyponyms", "holonyms", "meronyms"):
                    if s.get(k):
                        a["rel"]["s:" + k] += len(s[k])
        out[name] = a
        print("  · %-5s %-52s %9s 行" % (name, p.name, "{:,}".format(a["lines"])),
              file=sys.stderr)
    return out


# ══════════════════════════════════════════════════════════════════════════
def s1_shape(acc):
    head("1 七源形状（行 / 词形 / 义项 / 释义）")
    print("  %-6s%12s%12s%12s%12s%10s" % ("源", "行数", "唯一词形", "义项", "释义", "释义均长"))
    print("  " + "-" * 68)
    for name, _ in SRC:
        a = acc[name]
        print("  %-6s%12s%12s%12s%12s%10.0f" % (
            name, "{:,}".format(a["lines"]), "{:,}".format(len(a["words"])),
            "{:,}".format(a["senses"]), "{:,}".format(a["glosses"]),
            a["g_len"] / max(a["glosses"], 1)))
    allw = set()
    for name, _ in SRC:
        allw |= acc[name]["words"]
    print("\n  七源词形并集：{:,}".format(len(allw)))
    for name, _ in SRC:
        a = acc[name]["words"]
        only = a - set().union(*[acc[n]["words"] for n, _ in SRC if n != name])
        print("     %-6s %9s 个   其中**只有它有**的 %9s （%s）"
              % (name, "{:,}".format(len(a)), "{:,}".format(len(only)),
                 pct(len(only), len(a))))
    print("\n  🔴 「义项多」不等于「该当主源」——**源分工要按每一层分别量**"
          "（ko 那次整个判反了）。")


def s2_fields(acc):
    head("2 顶层字段**全打出来**（K36：别从错的字段名上读一个 0）")
    for name, _ in SRC:
        a = acc[name]
        n = a["lines"]
        print("\n  ── %s（%s 行）" % (name, "{:,}".format(n)))
        for k, c in a["keys"].most_common():
            print("     %-24s %9s  %s" % (k, "{:,}".format(c), pct(c, n)))
    head("2b 词源字段：单数 / 复数 / 模板")
    print("  %-6s%14s%14s%16s%14s" % ("源", "_text(单)", "_texts(复)", "_templates", "_links"))
    print("  " + "-" * 66)
    for name, _ in SRC:
        a = acc[name]
        n = max(a["lines"], 1)
        print("  %-6s%8s %s%8s %s%10s %s%8s %s" % (
            name,
            "{:,}".format(a["etym_sing"]), pct(a["etym_sing"], n),
            "{:,}".format(a["etym_plur"]), pct(a["etym_plur"], n),
            "{:,}".format(a["etym_tmpl"]), pct(a["etym_tmpl"], n),
            "{:,}".format(a["etym_links"]), pct(a["etym_links"], n)))
    print("\n  🔴 `RU_PLAN` §0.2① 要复核的就是这张表：ru 版若 `_text` 为 0 而 `_texts` 非 0，")
    print("     则「只认单数」会把 ru 版整版判成「没有词源」。")
    print("  🔴 §0.2② 要复核的是 `_templates` 那一列：vi 靠它推 `etym_type`。")
    print("     它若只在 en 版非零 ⇒ **`etym_type` 只能指望 en 版**，别假设能照搬 vi。")


def s3_cyrillic(acc):
    head("3 🔴🔴🔴 ё / й / 重音符 —— 归一判据的实测依据")
    print("  %-6s%14s%14s%16s%16s%14s" % (
        "源", "词头含ё", "词头带重音符", "词头非NFC", "词头含U+0306", "释义含ё"))
    print("  " + "-" * 74)
    for name, _ in SRC:
        a = acc[name]
        n = max(a["lines"], 1)
        g = max(a["glosses"], 1)
        print("  %-6s%7s %s%7s %s%9s %s%9s %s%7s %s" % (
            name,
            "{:,}".format(a["w_yo"]), pct(a["w_yo"], n),
            "{:,}".format(a["w_stress"]), pct(a["w_stress"], n),
            "{:,}".format(a["nfc_mismatch"]), pct(a["nfc_mismatch"], n),
            "{:,}".format(a["w_breve_decomp"]), pct(a["w_breve_decomp"], n),
            "{:,}".format(a["g_yo"]), pct(a["g_yo"], g)))
    print("\n  ⇒ **词头带重音符**那一列决定 `norm_ru` 要不要去 U+0301：非零就必须去，")
    print("    否则 `ко́шка` 和 `кошка` 是两个不同的键 ⇒ 同一个词裂成两页。")
    print("  ⇒ **词头非 NFC / 含 U+0306** 那两列是**反向检查**：源头若给分解态，")
    print("    「不做 NFD」的归一会把 `й` 和 `и`+̆ 分成两个键。两列都应当是 0；")
    print("    不为 0 则 `norm_ru` 必须补一步 **NFC 合成**（注意：NFC 不是 NFD，它不毁 ё）。")


def s4_ipa(acc):
    head("4 音标的定界符（§0.2④：ru 版用方括号，别门剥的是斜杠）")
    print("  %-6s%12s%34s" % ("源", "带 ipa 的 sound", "定界符分布"))
    print("  " + "-" * 62)
    for name, _ in SRC:
        a = acc[name]
        print("  %-6s%12s   %s" % (
            name, "{:,}".format(a["ipa_n"]),
            "  ".join("%s %s" % (k, "{:,}".format(v))
                      for k, v in a["ipa_delim"].most_common())))
    for name, _ in SRC:
        if acc[name]["ipa_sample"]:
            print("\n  ── %s 样例" % name)
            for s in acc[name]["ipa_sample"]:
                print("     " + s)


def s5_forms(acc):
    head("5 `forms` 的 tag 分布 —— **屈折层的规模，§0.4 第一个待拍板决定的分母**")
    for name, _ in SRC:
        a = acc[name]
        if not a["forms_rows"]:
            print("\n  ── %-5s forms 为空" % name)
            continue
        print("\n  ── %-5s  %s 行 forms，分布在 %s 个条目上（%s）"
              % (name, "{:,}".format(a["forms_rows"]),
                 "{:,}".format(a["has_forms"]), pct(a["has_forms"], a["lines"])))
        for t, c in a["forms_tags"].most_common(24):
            print("     %-26s %10s" % (t, "{:,}".format(c)))
        if len(a["forms_tags"]) > 24:
            print("     …… 另有 %d 种 tag" % (len(a["forms_tags"]) - 24))
    print("\n  🔴 vi 那门在这里逮到「`forms` 里一条屈折都没有」（装的全是汉字表记/异体/量词），")
    print("    于是变形层**有意为空**。俄语预期正相反 —— 但**预期不是实测**，看上面的 tag。")
    print("  🔴 `form_of` 指针（下表）才是「这个词形是谁的屈折形」，与 `forms` 是**反向的两条路**")
    print("    （`PLAYBOOK` 四：pt 补链补了四步，每一步都是发现上一步的判据够不着）。")
    print("\n  %-6s%16s%16s%16s" % ("源", "有 form_of 指针", "有 hyphenations", "带录音的 sound"))
    print("  " + "-" * 56)
    for name, _ in SRC:
        a = acc[name]
        n = max(a["lines"], 1)
        print("  %-6s%9s %s%9s %s%9s %s" % (
            name,
            "{:,}".format(a["form_of"]), pct(a["form_of"], n),
            "{:,}".format(a["has_hyph"]), pct(a["has_hyph"], n),
            "{:,}".format(a["audio"]), pct(a["audio"], n)))
    for name, _ in SRC:
        if acc[name]["hyph_sample"]:
            print("\n  ── %s 的 hyphenations 样例（别门都没有这个字段，值不值钱看这里）" % name)
            for s in acc[name]["hyph_sample"]:
                print("     " + s)


def s6_pos(acc):
    head("6 词性分布（`pos='unknown'` 的那一批是「扁平译词表」的信号）")
    for name, _ in SRC:
        a = acc[name]
        top = a["pos"].most_common(10)
        print("\n  ── %-5s %d 种 pos" % (name, len(a["pos"])))
        for k, c in top:
            print("     %-18s %10s  %s" % (k, "{:,}".format(c), pct(c, a["lines"])))


def s7_layers(acc):
    head("7 例句 / 关系 的存量（**词级与义项级分开算** —— es 只取词级漏 20,193 条）")
    print("  %-6s%14s%16s%16s" % ("源", "例句", "例句带译文", "关系条数合计"))
    print("  " + "-" * 56)
    for name, _ in SRC:
        a = acc[name]
        rel = sum(a["rel"].values())
        print("  %-6s%14s%10s %s%16s" % (
            name, "{:,}".format(a["ex"]),
            "{:,}".format(a["ex_tr"]), pct(a["ex_tr"], max(a["ex"], 1)),
            "{:,}".format(rel)))
    for name, _ in SRC:
        a = acc[name]
        if not a["rel"]:
            continue
        print("\n  ── %s 的关系分布（`w:` 词级 ／ `s:` 义项级）" % name)
        for k, c in a["rel"].most_common(14):
            print("     %-20s %10s" % (k, "{:,}".format(c)))


def s8_zh_samples(acc, n=40):
    head("8 中文释义**只抽样、不下结论**（ko 的 K24：97.2% 是元描述）")
    print("  🔴 判据要先看见数据再写，写完放进 `ru/pipeline/criteria.py`（唯一的家），")
    print("     本脚本 import 它、不重写。现在只打样本给人读。")
    print("  ⚠️ ko 那次我自写判据报 173,887 条「真释义」而真值是 6。")
    import random
    for name in ("zh-s", "zh-t"):
        a = acc.get(name)
        if not a or not a["gloss_sample"]:
            continue
        print("\n  ── %s（抽 %d 条）" % (name, n))
        for w, pos, g in random.sample(a["gloss_sample"], min(n, len(a["gloss_sample"]))):
            print("     %-22s %-10s %s" % (w[:20], (pos or "—")[:9], g[:60]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="每份只读前 N 行（调判据时用）")
    a = ap.parse_args()

    print("■ 扫描中（七份源，各一遍）……", file=sys.stderr)
    acc = scan(a.limit or None)

    buf = io.StringIO()
    with redirect_stdout(buf):
        print("■ 俄语阶段 -1 源头探测  2026-10-07"
              + ("（--limit %d，**不是全量**）" % a.limit if a.limit else "（全量）"))
        s1_shape(acc)
        s2_fields(acc)
        s3_cyrillic(acc)
        s4_ipa(acc)
        s5_forms(acc)
        s6_pos(acc)
        s7_layers(acc)
        s8_zh_samples(acc)
    txt = buf.getvalue()
    print(txt)
    if a.archive:
        paths.PROBE.mkdir(parents=True, exist_ok=True)
        out = paths.PROBE / ("probe_sources%s.txt" % ("-limit%d" % a.limit if a.limit else ""))
        out.write_text(txt, "utf-8")
        print("■ 已存档 → %s" % out, file=sys.stderr)


if __name__ == "__main__":
    main()
