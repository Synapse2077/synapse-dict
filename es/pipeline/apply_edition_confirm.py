#!/usr/bin/env python3
"""用西语版给库内音标**背书**（不改音标值）。2026-08-01。

═══ 这个脚本不做什么 ═══
🔴 **不替换任何一个音标值。** 原计划是"西语版有 37.7 万条人工音标 → 覆盖我们的 G2P 值"，
   前提是"真人写的能纠机器算的"。实测把这个前提推翻了：
   把记法差（14 种严式记号 / 二合元音 w·j↔u·i / ASCII g→ɡ）对齐之后，
   **465,806 个落点里 445,423 行本来就一致（95.6%）** —— 没什么可替换的。
   而剩下 4.4% 里两边**互有对错**（版对：kanji ˈkanxi→ˈkaɲʝi；我们对：FBI ˈfbi、mm ˈm、
   Guernsey 吞了 n），无脑覆盖是**净亏**。
   → 收益不在纠错，在**背书**：我们最大的一层无背书数据（G2P）被独立人工源逐字确认。

═══ 为什么是新列而不是把 src 写成 `rule+es-edition` ═══
「这个值从哪来」和「谁独立确认过它」是**两件正交的事**，拼进一个字符串会得到
组合爆炸的取值表，且以后再来第三个源就没法表达。所以：
    phonetic_src      值的来源            rule / kaikki-en / unknown
    phonetic_confirm  被谁独立确认过      es-edition / es-edition-notation / NULL
两列都在，才能回答"可回核率"这个质量指标。

confirm 的两档（弱的那档单独记，别混进强的）：
    es-edition            逐字相同
    es-edition-notation   仅记法差（二合元音 / 重音符），音位内容相同

用法（在 es/ 目录）：
    python3 pipeline/apply_edition_confirm.py            # 试算
    python3 pipeline/apply_edition_confirm.py --apply
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import html
import json
import re
import sqlite3
import unicodedata as U

import dbtool
import ipa_norm as N
import paths

HARVEST = paths.WORK / "es_edition_harvest.jsonl"

# 西语版音标里出现的**全部** 14 种组合记号（来自全量字符普查，不是一个个撞出来的）。
# 逐个撞的后果：我先只删了 ̪ ̃ ̞ 三种，残差里全是 n̟(U+031F)、θ̬(U+032C)，还以为是真差异。
NARROW = {chr(c) for c in (0x032A, 0x0303, 0x031E, 0x0361, 0x031F, 0x032C, 0x031D,
                           0x0301, 0x0327, 0x0302, 0x0308, 0x030A, 0x0306, 0x0326)}
VOWELS = "aeiou"

# 方言变体选择：**按源头自己的标签选，不从音标串猜**。
# 🔴 标签在 `raw_tags` 不在 `tags` —— 只读 tags 时 122 万个变体全显示"无 tag"，
#    我差点靠"串里有没有 θ/ʃ/ʎ"来猜方言。实测标签分布：
#    no seseante 87,398 / seseante 86,795 / sheísta 21,264 / yeísta 15,215 …
WANT = {"no seseante", "yeísta"}          # 区分 θ/s；yeísmo（今日绝大多数地区）
AVOID = {"seseante", "sheísta", "zheísta", "no yeísta"}


def canon_edition(s):
    """西语版严式值 → 本词典约定的裸音位串。"""
    s = html.unescape(s.replace("&#124;", "|")).replace("­", "")
    d = "".join(c for c in U.normalize("NFD", s) if c not in NARROW)
    return U.normalize("NFC", d).replace("g", "ɡ").strip()


def glide_fold(s):
    """二合元音记法折叠：版写 aw/ej，我们写 au/ei。可互相复原 → 属记法差。"""
    s = re.sub(r"(?<=[" + VOWELS + r"])w", "u", s)
    s = re.sub(r"(?<=[" + VOWELS + r"])j", "i", s)
    s = re.sub(r"w(?=[" + VOWELS + r"])", "u", s)
    s = re.sub(r"j(?=[" + VOWELS + r"])", "i", s)
    return s


def stress_fold(s):
    return s.replace("ˈ", "").replace("ˌ", "")


def pick(variants):
    """按标签打分选一条。无标签的（单变体词）自然胜出。"""
    if not variants:
        return None
    def score(v):
        t = set(v[1])
        return len(t & WANT) * 2 - len(t & AVOID) * 2 + (1 if not t else 0)
    return max(variants, key=score)[0]


def load_edition():
    d = {}
    for ln in open(HARVEST, encoding="utf-8"):
        r = json.loads(ln)
        if r["var"]:
            d[r["word"]] = [(v, tuple(t)) for v, t in r["var"]]
    return d


def build_plan():
    ed = load_edition()
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = conn.execute(
        "SELECT id, word, phonetic, phonetic_src FROM dict "
        "WHERE TRIM(COALESCE(phonetic,''))<>''").fetchall()
    conn.close()

    plan, stat, samples = [], collections.Counter(), []
    for rid, w, ph, src in rows:
        v = ed.get(w)
        if not v:
            continue
        new = canon_edition(N.normalize(w, canon_edition(pick(v))))
        src = src or "NULL"
        if new == ph:
            tag = "es-edition"
        elif glide_fold(new) == glide_fold(ph) or stress_fold(new) == stress_fold(ph):
            tag = "es-edition-notation"
        else:
            stat[("D 真·音段不同（不背书）", src)] += 1
            continue
        stat[(tag, src)] += 1
        plan.append((tag, rid))
        if len(samples) < 400:
            samples.append((w, ph, new, tag))
    return plan, stat, samples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    plan, stat, samples = build_plan()
    srcs = ["rule", "kaikki-en", "unknown", "NULL"]
    keys = ["es-edition", "es-edition-notation", "D 真·音段不同（不背书）"]
    print("■ 试算（分母＝库内有音标的行）")
    print("%-26s" % "" + "".join("%12s" % s for s in srcs) + "%12s" % "合计")
    for k in keys:
        print("  %-24s" % k + "".join("%12s" % format(stat[(k, s)], ",") for s in srcs)
              + "%12s" % format(sum(stat[(k, s)] for s in srcs), ","))
    print("\n■ 将写入 phonetic_confirm 的行数：{:,}".format(len(plan)))

    dbtool.sample_check([(w, p, n, t) for w, p, n, t in samples], n=12,
                        cols=("词", "库内值(不动)", "西语版归一后", "背书档"))

    if not a.apply:
        print("\n(试算完毕。加 --apply 落库)")
        return

    conn = sqlite3.connect(paths.DB)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(dict)")}
    if "phonetic_confirm" not in cols:
        conn.execute("ALTER TABLE dict ADD COLUMN phonetic_confirm TEXT")
        conn.commit()
        print("■ 已加列 phonetic_confirm")
    cur = conn.execute(
        "SELECT COUNT(*) FROM dict WHERE phonetic_confirm IS NOT NULL").fetchone()[0]
    conn.close()

    # **本脚本必须可重跑**：音标值一旦被别的修复改动（如 fix_x_gs.py 改了 1.5 万行），
    # 背书结论就过期了。所以先全表清空再重写，期望变化＝新旧非空计数之差。
    # 其余列（含 phonetic 本身）必须零变化 —— 这正是本脚本要证明的事：**没碰音标值**。
    keep = set(rid for _, rid in plan)
    with dbtool.session("edition-confirm",
                        expect={"phonetic_confirm": len(plan) - cur}) as s:
        s.execute("UPDATE dict SET phonetic_confirm=NULL")
        s.executemany("UPDATE dict SET phonetic_confirm=? WHERE id=?", plan)
        assert len(keep) == len(plan)


if __name__ == "__main__":
    main()
