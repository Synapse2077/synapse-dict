#!/usr/bin/env python3
"""阶段 1（下半）：建 `entry` 层 —— 词条 = (词形, 词性, 词源号, seq)。2026-09-20。

`entry` 是夹在 `dict`（词形/搜索单位）与 `sense`（义项）之间的**源头自己的单位**。
韩语的一等字段住在这儿，理由见 `ko/pipeline/build_v3_schema.py` 文件头。

═══ 🔴🔴 最重要的一条：**不合并重复键，全部用 seq 分开** ═══
ja 的做法是：`(词形,词性,词源号)` 重复时，**若音标与词源文本相同就合并成一个 entry**
（把 wiktextract 的切分还原成维基的一个章节，ja 实测 1,813 组里 1,811 组可合并）。

**这条判据搬到 ko 上会失效，而且是最难发现的那种失效 —— 它在空值上恒真。**

    ko 的重复键 178 组
      ├ 「音标相同」 173 组
      │    ├ 🔴 其实是**两边都没有音标**  127 组（73%）  ← 判据比的是两个空集
      │    └ 真的有音标且相同              46 组
      └ 音标不同（无论如何要分开）           5 组

韩语的 `character` 条目大量没有音标（10,280 条里 6,114 条连 gloss 都没有），
于是「音标相同」这个判据在它们身上**恒为真**。而回源看样本，它们根本不是切分伪影：

    厂 [0] foot of a mountain / hill / cave …   ← 读「한」
      [1] factory, plant / shed / stable …      ← 读「창」
    丰 [0] pretty, lovely                        㓞 [0] to chop finely
      [1] appearance, demeanor                     [1] alternative form of 契

**同一个汉字的不同韩语汉字音 + 各自一组义项** —— 合并就是把两个词条揉成一个。
⇒ ko 一律 `seq` 分开。理由不只是保守：**分开可逆、合并不可逆**
  （`[[prefer-reversible-designs]]`）。真有切分伪影，将来拿更好的判据再合并得了；
  合并错了就再也分不开。

⚠️ 这一条是 `[[criteria-narrower-than-you-think]]` 的镜像形态：
   判据本身没写错，**它作用的数据变了**（ja 的条目大多有音标，ko 的大多没有）。
   ⇒ **换语种时，照搬的不只是判据，还有判据默认成立的那个前提。**

═══ `hanja`：单值列取第一个，其余进关系层 ═══
实测 18,553 个条目带 `hanja` form，其中一条记录内只有 1 个的占 99.4%（18,453），
2–3 个的 100 条全是**异体字或数字写法**（奇跡/奇蹟/奇迹、10月/十月）。
⇒ 本步取第一个写进 `entry.hanja`，其余**记账**留给关系层 `kind='alt_hanja'`。
🔴 落账而不是丢掉：本脚本会把它们写进 `data/work/ko/entry_multi_hanja.tsv`。

═══ 罗马字：本步**一列都不填** ═══
英文版的 `romanization` form 实测与韩文版的 RR 一致 92.4%，本来可以填。
**有意不填** —— 四套罗马字阶段 3 从韩文版一次填全。
先填一套再被覆盖 ＝ 同一个字段两个写入方，ja 的 `inflection` 正是这么栽的
（最后不得不建 OWNERS 登记 + 对不上账就停机的闸）。**一个字段一个写入方。**

跑（在仓库根）：
    python3 -u ko/pipeline/build_entry_layer.py
    python3 -u ko/pipeline/build_entry_layer.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import json
import sqlite3

import dbtool
import paths

# 🔴 **这张表只许有一份。** ja 上同一个 POS_MAP 写了两份（`build_entry_layer` 一份、
#    `intake_edition_words` 一份更短的），结果同一个概念在库里有两个码
#    （`prov` 218 / `proverb` 99、`kana` 789 / `syllable` 4），展示层分成两组、
#    其中一组印英文（`[[refactor-mindset-code-quality]]`）。
#    ⇒ 后续脚本一律 `from build_entry_layer import POS_MAP`，不许再抄一份。
#
# ⚠️ **不是照抄 ja 的**：`character` 在韩语里是 **hanja** 不是 kanji，
#    `syllable` 是**谚文音节**不是假名。照抄会把日语的概念印到韩语页面上。
POS_MAP = {
    "noun": "n", "verb": "v", "adj": "adj", "adv": "adv", "name": "name",
    "pron": "pron", "det": "det", "num": "num", "counter": "counter",
    "prefix": "pref", "suffix": "suf", "affix": "affix", "interfix": "infix",
    "particle": "part", "postp": "postp", "conj": "conj", "intj": "intj",
    "phrase": "phr", "proverb": "prov", "contraction": "contr",
    "root": "root", "symbol": "sym", "punct": "punct",
    # 韩语特有的两个 —— 别用日语的码
    "character": "hanja",      # 汉字条目（`犬` → "hanja form of 견"）
    "syllable": "syl",         # 谚文音节条目（`낭` `갹` `규`）
}

# 阶段 1 的骨架源是英文版。`dict` 里没有的词形（阶段 1 推迟的 6,089 个无 gloss 汉字）
# 不建 entry —— 它们连同 hanja↔hangeul 指向一起进阶段 2。
SRC = "en-edition"


def hanja_of(o):
    """→ (主汉字表记, 其余异体列表)。判据是源头给的 `tags` 含 `hanja`，不是字形。"""
    hs = []
    for f in (o.get("forms") or []):
        if "hanja" in (f.get("tags") or []) and f.get("form"):
            if f["form"] not in hs:
                hs.append(f["form"])
    return (hs[0] if hs else None), hs[1:]


def scan(indict):
    """扫英文版 → entry 行。`indict`: word → dict.id。"""
    seen = collections.Counter()          # (word,pos_raw,etym) → 已出现几条 ⇒ seq
    rows, multi_hanja = [], []
    stat = collections.Counter()
    for line in open(paths.KK, encoding="utf-8"):
        o = json.loads(line)
        praw = o.get("pos")
        if praw == "romanization":        # 与 build.py 同一条判据（源头给的 pos）
            stat["剔除·romanization"] += 1
            continue
        w = o.get("word")
        if not w or not w.strip():
            continue
        wid = indict.get(w)
        if wid is None:
            stat["词形不在 dict 里（阶段 1 推迟的无 gloss 词）"] += 1
            continue
        en_ = o.get("etymology_number")
        etym = str(en_) if en_ is not None else "0"
        k = (w, praw, etym)
        seq = seen[k]
        seen[k] += 1
        if seq:
            stat["🔴 同键重复 ⇒ seq 分开"] += 1
        hanja, rest = hanja_of(o)
        if rest:
            multi_hanja.append((w, praw, etym, seq, hanja, "|".join(rest)))
            stat["一条记录多个 hanja（其余落账给关系层）"] += 1
        if hanja:
            stat["有 hanja"] += 1
        rows.append((wid, w, POS_MAP.get(praw, praw), praw, etym, seq,
                     hanja, SRC if hanja else None,
                     SRC, "kk-ko:%s:%s:%s:%d" % (w, praw, etym, seq)))
        stat["entry"] += 1
    return rows, stat, multi_hanja


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    indict = {r[1]: r[0] for r in con.execute("SELECT id, word FROM dict")}
    have = con.execute("SELECT COUNT(*) FROM entry").fetchone()[0]
    con.close()
    print("■ dict 里 %s 个词形；entry 现有 %s 行" % (format(len(indict), ","), format(have, ",")))
    if have:
        raise SystemExit("🔴 entry 非空 —— 本步是首建，不是增量。先确认是不是重复跑了。")

    rows, stat, multi = scan(indict)
    print("■ 扫 %s" % paths.KK.name)
    for k, v in stat.most_common():
        print("   %-40s %9s" % (k, format(v, ",")))

    # `src_ref` 必须唯一 —— 它是 entry 的身份，UNIQUE 约束会拦，但**先自己查一遍**，
    # 让错误停在写库之前（写库前发现 = 改代码；写库后发现 = 回滚 + 改代码）
    refs = collections.Counter(r[-1] for r in rows)
    dupref = {k: c for k, c in refs.items() if c > 1}
    print("   %-40s %9s" % ("src_ref 唯一性", "✅ 全唯一" if not dupref else "🔴 %d 个重复" % len(dupref)))
    if dupref:
        raise SystemExit("🔴 src_ref 重复：%s" % list(dupref.items())[:5])

    pos_dist = collections.Counter(r[2] for r in rows)
    print("   词性分布（映射后）: %s" % pos_dist.most_common(8))
    unmapped = {r[3] for r in rows if r[3] not in POS_MAP}
    print("   %-40s %s" % ("POS_MAP 没覆盖到的 pos_raw",
                           "✅ 无" if not unmapped else "🔴 %s" % unmapped))

    dbtool.sample_check([(r[1], r[2], r[4], r[5], r[6] or "—") for r in rows],
                        12, ("词形", "词性", "词源号", "seq", "汉字表记"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    paths.WORK.mkdir(parents=True, exist_ok=True)
    mp = paths.WORK / "entry_multi_hanja.tsv"
    with open(mp, "w", encoding="utf-8") as f:
        f.write("word\tpos_raw\tetym_no\tseq\tkept_hanja\tdeferred_alt_hanja\n")
        for r in multi:
            f.write("\t".join(str(x) for x in r) + "\n")
    print("■ 多汉字表记的 %d 条已落账 → %s（阶段 2 进关系层 alt_hanja）"
          % (len(multi), mp))

    with dbtool.session("build-ko-entry",
                        expect={"#entry": len(rows),
                                "entry.hanja": sum(1 for r in rows if r[6]),
                                "entry.hanja_src": sum(1 for r in rows if r[7])},
                        invalidates=[]) as s:
        s.executemany(
            "INSERT INTO entry (word_id, word_src, pos, pos_raw, etym_no, seq, "
            "hanja, hanja_src, src, src_ref) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("entry 行数", q("SELECT COUNT(*) FROM entry"), len(rows)),
        ("src_ref 唯一", q("SELECT COUNT(*) FROM (SELECT src_ref FROM entry "
                           "GROUP BY src_ref HAVING COUNT(*)>1)"), 0),
        ("word_id 都指得到 dict",
         q("SELECT COUNT(*) FROM entry e LEFT JOIN dict d ON d.id=e.word_id "
           "WHERE d.id IS NULL"), 0),
        # 🔴 每个 dict 词形至少有一个 entry —— 少了就是**有词形没词条**，
        #    那正是「搜得到、点进去空白页」的前身
        ("dict 词形都有 entry",
         q("SELECT COUNT(*) FROM dict d LEFT JOIN entry e ON e.word_id=d.id "
           "WHERE e.id IS NULL"), 0),
        ("hanja 非空数", q("SELECT COUNT(*) FROM entry WHERE hanja IS NOT NULL"),
         sum(1 for r in rows if r[6])),
        # 罗马字本步一列都不填（阶段 3 才填）—— 锁住它，防止将来有人顺手在这儿填一套
        ("罗马字四列全空",
         q("SELECT COUNT(*) FROM entry WHERE roman_rr IS NOT NULL OR "
           "roman_rr_translit IS NOT NULL OR roman_mr IS NOT NULL OR "
           "roman_yale IS NOT NULL"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-24s %10s（期望 %s）" % ("✅" if good else "🔴", name,
                                              format(got, ","), format(want, ",")))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
