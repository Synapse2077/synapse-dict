#!/usr/bin/env python3
"""阶段 2a：补收阶段 1 推迟的 6,089 个无 gloss 汉字词形（欠账 K1）。2026-09-21。

═══ 为什么它们当初被推迟，现在又要收 ═══
阶段 1 的判据是「整个词形一条 gloss 都没有 ⇒ 本步不收」，理由是
**现在收进来 = 6,089 个「搜得到、点进去没有释义」的页面**（pt 栽过的形状）。

现在可以收了，因为**这一步之后它们立刻有内容**：
    5,955 个带 `forms`，其中 `hangeul` tag 的 5,896 条就是它们的**谚文读法**
    （`犬` → `견`），阶段 2d 会把这层对应写进关系层。
⇒ **收词的前提不是"源头有"，是"收进来之后这个页面有东西看"。**

🔴 **同一条判据也挡住了 134 个**：它们 forms / sounds / etymology / 关系
   **四样全空**（全是生僻汉字 㒣 譗 㗲 㗶，kaikki 收了词头但一个字段都没抽到）。
   收 5,955、不收 134 —— 两个数字出自**同一条判据**，不是两套标准。
   不收的那批落账在 `data/work/ko/deferred_hanja_empty.txt`，写明什么会推翻。

🔴 顺序不能反（`PLAYBOOK` 四）：**先收词，再建变形层**。
   反过来就是 pt 的 355,605 个空白页 —— 变形层建在收词之前，
   新收的词形一条链都没有，而且**没有人会回头重跑**。

═══ 这一步会让什么过期 ═══
`dbtool.session` 的收词闸要求显式声明 `invalidates`。此刻库里只有义项层和汉字音层，
两者都**不按这批词计算**（它们无义项），但**分母会变**：
「有出版义项的词形占比」从 68.8%（35,201/51,155）掉到 61.6%（35,201/57,110）。
⚠️ 那不是缺陷，是分母变大 —— 但**必须当场说出来**，否则下次看见 61.5% 会当成回归
（ja 的读音覆盖 99.90%→39.8% 就是这么变成惊吓的）。

跑（在仓库根）：
    python3 -u ko/pipeline/intake_deferred_hanja.py
    python3 -u ko/pipeline/intake_deferred_hanja.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import json
import sqlite3
import unicodedata

import dbtool
import paths
from build_entry_layer import POS_MAP, hanja_of, SRC   # 🔴 映射表只许有一份


def norm_ko(s):
    """与 `build.py` **同一条归一**。⚠️ 不在这儿另写一份实现 ——
    两份归一迟早漂开，而症状是「同一个词两行、搜不到」。"""
    return unicodedata.normalize("NFC", s or "")


def scan(indict):
    """扫英文版 → 该补收的 (dict 行, entry 行)。判据与 `build.py` 逐字相同，
    只是**取反**：那边收"有 gloss 的"，这边收"一条 gloss 都没有的"。"""
    words = {}
    seen_entry = collections.Counter()
    entries = []
    stat = collections.Counter()
    for line in open(paths.KK, encoding="utf-8"):
        o = json.loads(line)
        praw = o.get("pos")
        if praw == "romanization":
            continue
        w = o.get("word")
        if not w or not w.strip():
            continue
        if w in indict:
            continue                                   # 阶段 1 已收
        e = words.setdefault(w, {"pos": collections.Counter(), "gloss": False,
                                 "forms": 0, "sounds": 0, "etym": False, "rel": 0})
        e["pos"][praw] += 1
        e["forms"] += len(o.get("forms") or [])
        e["sounds"] += len(o.get("sounds") or [])
        e["etym"] |= bool(o.get("etymology_text"))
        for key in ("synonyms", "antonyms", "derived", "related",
                    "hypernyms", "descendants"):
            e["rel"] += len(o.get(key) or [])
        for se in (o.get("senses") or []):
            if se.get("glosses"):
                e["gloss"] = True
        stat["条目"] += 1
    # 🔴 自证：这批**必须**全都没有 gloss。有 gloss 的说明阶段 1 漏收了，
    #    那是另一个问题，不能在这儿悄悄一起收掉。
    withg = [w for w, e in words.items() if e["gloss"]]
    stat["🔴 竟然有 gloss（阶段 1 该收而没收）"] = len(withg)

    rows, empty = [], []
    for w, e in sorted(words.items()):
        pos = "/".join(p for p, _ in e["pos"].most_common() if p)
        # 🔴🔴 **收词的判据是「收进来之后这个页面有东西看」，不是「源头有这个词头」。**
        #    实测 134 个词形（全是 `character`，全是生僻汉字 㒣 譗 㗲 㗶…）
        #    **forms / sounds / etymology / 关系 四样全空** —— kaikki 收了词头但
        #    一个字段都没抽到。收进来就是 134 个真正的空白页。
        #    ⚠️ 这不是"源头没有"，是"源头这一条什么都没有"，两件事都要说清
        #    （`[[dont-say-source-lacks-what-we-skipped]]`）。
        if not (e["forms"] or e["sounds"] or e["etym"] or e["rel"]):
            empty.append(w)
            stat["🔴 四样全空 ⇒ 不收（落账）"] += 1
            continue
        rows.append((w, norm_ko(w), 0, pos or None))   # is_lemma=0：无非指针义项
        stat["→ dict"] += 1
    return rows, empty, stat, withg


def scan_entries(indict2):
    """第二遍：为新收的词形建 entry。必须等 dict 插完拿到 id。"""
    seen = collections.Counter()
    rows = []
    stat = collections.Counter()
    for line in open(paths.KK, encoding="utf-8"):
        o = json.loads(line)
        praw = o.get("pos")
        if praw == "romanization":
            continue
        w = o.get("word")
        if not w or not w.strip():
            continue
        wid = indict2.get(w)
        if wid is None:
            continue
        en_ = o.get("etymology_number")
        etym = str(en_) if en_ is not None else "0"
        k = (w, praw, etym)
        seq = seen[k]
        seen[k] += 1
        hanja, rest = hanja_of(o)
        rows.append((wid, w, POS_MAP.get(praw, praw), praw, etym, seq,
                     hanja, SRC if hanja else None,
                     SRC, "kk-ko:%s:%s:%s:%d" % (w, praw, etym, seq)))
        stat["→ entry"] += 1
        if seq:
            stat["同键重复 ⇒ seq 分开"] += 1
    return rows, stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    indict = {r[0] for r in con.execute("SELECT word FROM dict")}
    before_dict = len(indict)
    max_id_before = con.execute("SELECT COALESCE(MAX(id),0) FROM dict").fetchone()[0]
    before_sense_cov = con.execute(
        "SELECT COUNT(DISTINCT word_id) FROM sense").fetchone()[0]
    con.close()

    rows, empty, stat, withg = scan(indict)
    for k, v in stat.most_common():
        print("   %-40s %9s" % (k, format(v, ",")))
    if withg:
        raise SystemExit("🔴 有 %d 个词形带 gloss 却不在 dict 里 —— 阶段 1 的判据出问题了，"
                         "先查那个，别在这儿顺手收掉：%s" % (len(withg), withg[:5]))

    pos_dist = collections.Counter(r[3] for r in rows)
    print("   按词性: %s" % pos_dist.most_common(6))
    print("\n■ 收词前后的**分母**（必须当场说清，否则下次看见会当成回归）：")
    after = before_dict + len(rows)
    print("   dict 词形        %s → %s" % (format(before_dict, ","), format(after, ",")))
    print("   有出版义项占比    %.1f%% → %.1f%%（分子不变 %s，**分母变大**）"
          % (100 * before_sense_cov / before_dict, 100 * before_sense_cov / after,
             format(before_sense_cov, ",")))

    if empty:
        paths.WORK.mkdir(parents=True, exist_ok=True)
        ep = paths.WORK / "deferred_hanja_empty.txt"
        ep.write_text("\n".join(empty) + "\n", encoding="utf-8")
        print("\n🔴 **不收**的 %d 个（四样全空）已落账 → %s" % (len(empty), ep))
        print("   什么会推翻：从韩文版/中文版/`한자` 切片拿到这些字的任一内容"
              "（读音/字义/汉字音）时，连同内容一起收")

    dbtool.sample_check([(r[0], r[3]) for r in rows], 10, ("词形", "词性"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    with dbtool.session(
            "intake-ko-deferred-hanja",
            expect={"__rows__": len(rows), "pos": len(rows)},
            invalidates=[
                "义项覆盖率（分子不变、**分母变大** 51,155 → 57,110）",
                "阶段 2c 变形层：这批的 forms 要一起进（本步之后立刻做）",
                "阶段 2d 关系层：这批的 hangeul 对应是它们**唯一的内容**",
                "阶段 3 读音层 / 阶段 7 词源层：覆盖率分母要按新的词形数算",
            ]) as s:
        s.executemany(
            "INSERT INTO dict (word, word_norm, is_lemma, pos) VALUES (?,?,?,?)", rows)

    # entry 要等 dict 有 id 之后再建 —— 单独一次会话。
    # 🔴 **按插入前的 MAX(id) 取新行，不用「最大的 N 个 id」**：后者假设
    #    「新插的正好是 id 最大的 N 个」，那在有过删除的库上会悄悄圈进旧行。
    #    这里的判据是**这一次写库的边界**，它不依赖任何关于 id 分布的假设。
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    newids = {r[1]: r[0] for r in con.execute(
        "SELECT id, word FROM dict WHERE id > ?", (max_id_before,))}
    con.close()
    if len(newids) != len(rows):
        raise SystemExit("🔴 新收的行数对不上：查到 %d，本该 %d" % (len(newids), len(rows)))
    erows, estat = scan_entries(newids)
    print("\n■ 为新词形建 entry：%s" % estat.most_common())

    with dbtool.session(
            "intake-ko-deferred-hanja-entry",
            expect={"#entry": len(erows),
                    "entry.hanja": sum(1 for r in erows if r[6]),
                    "entry.hanja_src": sum(1 for r in erows if r[7])},
            invalidates=[]) as s:
        s.executemany(
            "INSERT INTO entry (word_id, word_src, pos, pos_raw, etym_no, seq, "
            "hanja, hanja_src, src, src_ref) VALUES (?,?,?,?,?,?,?,?,?,?)", erows)

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("dict 行数", q("SELECT COUNT(*) FROM dict"), after),
        ("word 仍唯一", q("SELECT COUNT(*) FROM (SELECT word FROM dict GROUP BY word "
                          "HAVING COUNT(*)>1)"), 0),
        ("新收的都是 is_lemma=0",
         q("SELECT COUNT(*) FROM dict WHERE is_lemma=0"), 15871 + len(rows)),
        ("每个词形都有 entry",
         q("SELECT COUNT(*) FROM dict d LEFT JOIN entry e ON e.word_id=d.id "
           "WHERE e.id IS NULL"), 0),
        ("entry.src_ref 仍唯一",
         q("SELECT COUNT(*) FROM (SELECT src_ref FROM entry GROUP BY src_ref "
           "HAVING COUNT(*)>1)"), 0),
        # 🔴 新收的这批**一条出版义项都不该有**（它们本来就没 gloss）
        ("新收的没有出版义项",
         q("SELECT COUNT(*) FROM sense s JOIN dict d ON d.id=s.word_id "
           "WHERE d.is_lemma=0 AND NOT EXISTS (SELECT 1 FROM sense_src ss "
           "  WHERE ss.word_id=d.id AND ss.sense_id IS NOT NULL)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-26s %10s（期望 %s）" % ("✅" if good else "🔴", name,
                                              format(got, ","), format(want, ",")))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
