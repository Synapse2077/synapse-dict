#!/usr/bin/env python3
"""阶段 3b：填 `entry` 的四套罗马字。从**韩文版**一次填全。2026-09-21。

═══ 为什么阶段 1 有意留空、到这一步才填 ═══
英文版的 `romanization` form 实测与韩文版的 RR 一致 92.4%，阶段 1 本来可以顺手填。
**有意不填** —— 四套罗马字必须**一个写入方一次填全**。
先填一套再被这一步覆盖 ＝ 同一个字段两个写入方，ja 的 `inflection` 正是这么栽的
（`fixes/recover_pointer_senses.py` 与重建脚本各写各的，最后不得不建 OWNERS 登记
＋「对不上账就停机」的闸）。

═══ 四套是什么，为什么四套都存 ═══
    roman_rr           revised            韩国 2000 年起的**官方国标**（路牌/护照/教科书）
    roman_rr_translit  revised+translit   RR 的**转写**变体（逐字母，`한국어`→`hangug-eo`）
    roman_mr           McCune-Reischauer  英语学术文献与旧地名（`Pusan` 对 `Busan`）
    roman_yale         Yale               语言学界
用户 2026-09-20 定：**四套全存，页面只显示 RR**。
🔴 「只显示 RR」这个决定要靠**回归闸扫展示层源码**站岗（照搬 ja 给 `core_level` 的 X3），
   所以列名起成了能被源码扫描认出来的样子 —— 别改成 `roman1/2/3`。

═══ ⚠️ 一个要记下来的结构疑点 ═══
阶段 0 把罗马字放进 `entry`，判据是「**同一条 JSON 记录内** 99.92% 单值」。
但罗马字其实是**从谚文拼写机械转写**出来的 ⇒ 它大概率是**词形级**属性，
同一个词形的各个 entry 会填一模一样的值（冗余）。
本步实测这个数并报出来。⚠️ **不因此就改 schema** ——
现在改要动已落库的数据，而冗余的代价是几列重复、不是错误。
🔴 什么会让它值得改：若某个词形的不同 entry 真的出现**不同**的罗马字
（那说明它是 entry 级的、放对了），或冗余量大到影响库体积。

跑（在仓库根）：
    python3 -u ko/pipeline/fill_romanization.py
    python3 -u ko/pipeline/fill_romanization.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import json
import re
import sqlite3

import dbtool
import paths

SRC = "ko-edition"

# 🔴 源头把**录音文件名**喂进了罗马字模板：`하다` 的四套罗马字在 ko 版里是
#    `Ko-hada.oga` / `Kohada.oga` / `Kohata.oga`（16 条 sounds，全库只此一词）。
#    第一版原样收了，四套齐全、非空、全 ASCII —— **所有形式判据都满足**，
#    是阶段 9 把数据渲染出来才看见的（`ko/pipeline/fix_roman_audio_filename.py`）。
# ⚠️ 判据只认**音频扩展名**：写成「带文件扩展名」会误伤 32,324 条 `roman_yale`
#    （Yale 用 `.` 做音节分隔，`hānkwuk.e`），写成「大写开头」会误伤 40 条专名。
AUDIO_EXT = re.compile(r"\.(oga|ogg|mp3|wav|flac|m4a|opus)$", re.I)


def scheme_of(tags):
    """一组 sound tag → 哪一套罗马字。**判据用 tag 不用值的样子。**"""
    ts = set(tags or [])
    if "romanization" in ts and "revised" in ts:
        return "roman_rr_translit" if "transliteration" in ts else "roman_rr"
    if "revised" in ts:
        return "roman_rr_translit" if "transliteration" in ts else "roman_rr"
    if "McCune-Reischauer" in ts:
        return "roman_mr"
    if "Yale" in ts:
        return "roman_yale"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--topup", action="store_true",
                    help="只给 roman_rr 还是 NULL 的 entry 行补（补收词之后用）")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    # 词形 → 它的所有 entry_id
    byword = collections.defaultdict(list)
    for eid, w in con.execute(
            "SELECT e.id, d.word FROM entry e JOIN dict d ON d.id=e.word_id"):
        byword[w].append(eid)
    filled = con.execute(
        "SELECT COUNT(*) FROM entry WHERE roman_rr IS NOT NULL").fetchone()[0]
    before_src = con.execute(
        "SELECT COUNT(*) FROM entry WHERE roman_src IS NOT NULL").fetchone()[0]
    con.close()
    # 🔴 2026-09-24 加 `--topup`：**只填空、不覆盖**。
    #    起因：阶段 8 补收了韩文版 13,062 个无 gloss 词头（外锚闸逮到的，见 K13），
    #    它们 99.9% 带四套罗马字，而新建的 `entry` 行四列全空。
    #    ⚠️ 它**不是**第二个写入方：判据与取值仍然全部由本脚本算，
    #      只是把写入范围限制在「这一列还是 NULL 的行」——
    #      `[[enrich-not-rebuild]]`：给已含数据的库补字段，原地补列，别重建搬运。
    if filled and not a.topup:
        raise SystemExit("🔴 `roman_rr` 已有 %d 行非空 —— 本步是首填，"
                         "**一个字段一个写入方**。要给新收的词补空位请加 `--topup`。"
                         % filled)
    if a.topup:
        con2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        empty = {r[0] for r in con2.execute(
            "SELECT id FROM entry WHERE roman_rr IS NULL")}
        con2.close()
        print("■ `--topup`：`roman_rr` 还是空的 entry 行 %s 条（只写这些）"
              % format(len(empty), ","))
        byword = {w: [e for e in ids if e in empty]
                  for w, ids in byword.items()}
        byword = {w: ids for w, ids in byword.items() if ids}

    # word → {列: 值}
    out = {}
    stat = collections.Counter()
    conflict = []
    for line in open(paths.EDITION, encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        w = d.get("word")
        if not w or w not in byword:
            continue
        for s in (d.get("sounds") or []):
            r = (s.get("roman") or "").strip()
            if not r:
                continue
            if AUDIO_EXT.search(r):
                # 🔴 不静默跳过 —— 报出来（见上方 AUDIO_EXT 的由来）
                stat["🔴 跳过·罗马字位置上是音频文件名"] += 1
                continue
            col = scheme_of(s.get("tags"))
            if not col:
                stat["跳过·认不出是哪一套"] += 1
                continue
            cur = out.setdefault(w, {})
            if col in cur and cur[col] != r:
                # 同一个词形两个不同值 —— 多半是多词条各读各的音（`읽다` 那种）。
                # 🔴 **取第一个并报出来**，不静默覆盖
                conflict.append((w, col, cur[col], r))
                stat["🔴 同词形同套两个值（取第一个）"] += 1
                continue
            cur[col] = r
            stat[col] += 1

    rows = []
    for w, v in out.items():
        for eid in byword[w]:
            rows.append((v.get("roman_rr"), v.get("roman_rr_translit"),
                         v.get("roman_mr"), v.get("roman_yale"), SRC, eid))
    for k, v in stat.most_common():
        print("   %-34s %9s" % (k, format(v, ",")))
    print("   %-34s %9s" % ("覆盖词形", format(len(out), ",")))
    print("   %-34s %9s" % ("要写的 entry 行", format(len(rows), ",")))
    # ⚠️ 结构疑点的实测：一个词形平均摊到几个 entry（＝冗余倍数）
    print("   %-34s %9.2f" % ("每词形平均 entry 数（冗余倍数）",
                              len(rows) / max(len(out), 1)))
    four = sum(1 for v in out.values() if len(v) == 4)
    print("   %-34s %9s" % ("四套齐全的词形", format(four, ",")))
    if conflict:
        print("\n⚠️ 同词形同套出现两个不同值的 %d 条（取第一个），样本：" % len(conflict))
        for c in conflict[:5]:
            print("     %s" % (c,))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    with dbtool.session(
            "fill-ko-romanization",
            expect={"entry.roman_rr": sum(1 for r in rows if r[0]),
                    "entry.roman_rr_translit": sum(1 for r in rows if r[1]),
                    "entry.roman_mr": sum(1 for r in rows if r[2]),
                    "entry.roman_yale": sum(1 for r in rows if r[3]),
                    "entry.roman_src": len(rows)},
            invalidates=[]) as s:
        s.executemany(
            "UPDATE entry SET roman_rr=?, roman_rr_translit=?, roman_mr=?, "
            "roman_yale=?, roman_src=? WHERE id=?", rows)

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        # 🔴 `--topup` 下期望值要**加上本步之前已有的** —— 不然拿"本步写了多少"
        #    去比"库里总共有多少"，两个不同的量（`[[expectation-must-be-declared]]`）。
        ("roman_rr 非空", q("SELECT COUNT(*) FROM entry WHERE roman_rr IS NOT NULL"),
         filled + sum(1 for r in rows if r[0])),
        ("roman_src 非空", q("SELECT COUNT(*) FROM entry WHERE roman_src IS NOT NULL"),
         before_src + len(rows)),
        # 🔴 罗马字是**拉丁转写**：出现谚文就是填错了列
        ("罗马字列里没有谚文",
         q("SELECT COUNT(*) FROM entry WHERE roman_rr GLOB '*[가-힣]*' "
           "OR roman_mr GLOB '*[가-힣]*' OR roman_yale GLOB '*[가-힣]*'"), 0),
        # 🔴 四套是**成套**的：有 RR 就该有 MR/Yale（实测源头四套等量）
        ("有 RR 的也有 MR",
         q("SELECT COUNT(*) FROM entry WHERE roman_rr IS NOT NULL "
           "AND roman_mr IS NULL"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-24s %10s（期望 %s）" % ("✅" if good else "🔴", name,
                                              format(got, ","), format(want, ",")))
    print("\n■ 抽样：四套并排看差异")
    for r in con.execute(
            "SELECT d.word, e.roman_rr, e.roman_rr_translit, e.roman_mr, e.roman_yale "
            "FROM entry e JOIN dict d ON d.id=e.word_id "
            "WHERE d.word IN ('한국어','부산','읽다','개') AND e.roman_rr IS NOT NULL "
            "LIMIT 6"):
        print("     %-8s RR=%-12s translit=%-14s MR=%-12s Yale=%s" % r)
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
