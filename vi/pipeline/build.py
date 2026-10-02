#!/usr/bin/env python3
"""阶段 1（上半）：建 `dict` 骨架 —— 从**英文版**切片。2026-09-28。
（下半是 `build_entry_layer.py` 建 `entry` 层；表结构已由阶段 0 建好）

═══ 为什么骨架是英文版 —— 这条是**量出来的**，而且与八门都不同 ═══
`VI_PLAN` §4.1 的判据是「量各版在同一个词上给的字段谁更全」，不许按总量拍。量的结果：

    en 45,281 词形 ／ vi 41,507 ／ **交集只有 19,681** —— 两边各自独有两万多
    ⇒ 前七门「英文版主源 + 本语言版补」、ko「整个反过来」，**两种都不适用**

定下来的是**第三种**分工：

    两版都有的词 ⇒ **en 定 `entry` 切分与 `pos`**，vi/zh 内容挂上去
    只有一版有的词 ⇒ 那一版自建 entry（vi 独有那 21,826 个走**阶段 4 收词**，不在本步）

骨架归 en 的三条理由，全是量出来的：
  ① vi 版 `pos` 有洞：**4,652 条 `unknown`**（源页面没写词性），
     而且 vi 版**根本没有 `classifier` 这个词性** —— 量词层正是 vi 的特色层
  ② en 切得更细且方向一致：2,382 : 796 ≈ 3:1。
     **细骨架挂粗内容只需要挂，粗骨架挂细内容需要拆** —— 只有前者有确定解
  ③ 录音与结构化表记是 en 独占（1,743:10、5,948:36），它们天然锚在 en 的 entry 上
⚠️ **骨架归 en ≠ 内容归 en**：vi 版独占例句（33,858 : 11,569，2.9 倍）。

═══ 判据：什么进 `dict` ═══
**判据全部 import 自 `criteria.py`，本文件一条都不重写**（ko 建外锚闸时发现
同一判据散在三个文件里，而闸正要靠它）。两条与 ko 相反的，理由写在 `criteria.py` 文件头：

    ① `NOT_A_WORD` 是**空集** —— ko 剔 `pos=romanization`，而 vi 的这个 pos 装的是
       **汉越音**（`y → Sino-Vietnamese reading of 衣`），照搬会丢掉 145 个真实音节
    ② 剔汉字词头的判据是**字形**不是 pos —— `pos=character` 两个方向都切错：
       漏掉 6,619 条（pos 是 noun/verb 的表意词头）、误伤 325 条（越南语字母 A y X CH）

    剔 · 全表意文字词头        14,523 个词形   用户 2026-09-28 定：只喂汉字层
    剔 · 词形是空白            实测 0 条。**判据保留** —— 一行空白比少收一个字更伤，
                               而且它会让后续任何「词形非空」的不变量失效
    推迟 · 一条 gloss 都没有    见跑出来的数。**明说是我们这一步不收，不是源头没有**
                               （`[[dont-say-source-lacks-what-we-skipped]]`）

跑（在仓库根）：
    python3 -u vi/pipeline/build.py            # 干跑，只报数
    python3 -u vi/pipeline/build.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import gzip
import json
import sqlite3

from criteria import (NOT_A_WORD, norm_vi, is_han_headword, is_pointer_sense,
                      syllables, entry_type_of)

import dbtool
import paths


def scan():
    """扫英文版切片 → 每个词形一条记录。返回 (rows, stat, deferred, han)。"""
    words = {}
    stat = collections.Counter()
    han = collections.Counter()          # 剔掉的表意词头，按 pos 记账
    with gzip.open(paths.KK, "rt", encoding="utf-8") as f:
        for line in f:
            o = json.loads(line)
            stat["原始行"] += 1
            pos = o.get("pos")
            if pos in NOT_A_WORD:        # 空集 —— 这一行此刻不做事，但它是显式声明
                stat["剔除·pos 黑名单"] += 1
                continue
            w = o.get("word")
            if not w:
                stat["无词头"] += 1
                continue
            if not w.strip():
                stat["剔除·词形是空白（源头有，我们不收）"] += 1
                continue
            if is_han_headword(w):
                stat["剔除·全表意词头（→ 阶段 2 汉字层）"] += 1
                han[pos] += 1
                continue
            stat["真词条目"] += 1
            e = words.setdefault(w, {"pos": collections.Counter(),
                                     "lemma": False, "gloss": False})
            e["pos"][pos] += 1
            for se in (o.get("senses") or []):
                if not (se.get("glosses") or []):
                    continue
                e["gloss"] = True
                # 词元判据：这个词形有没有**至少一条不是指针**的义项。
                # 🔴 三路判据取并（结构字段／en 正文写法／vi 正文写法）—— 见 W5。
                if not is_pointer_sense(se):
                    e["lemma"] = True

    rows, deferred = [], []
    for w, e in words.items():
        poss = [p for p, _ in e["pos"].most_common() if p]
        pos = "/".join(poss)
        if not e["gloss"]:
            deferred.append((w, pos))
            continue
        rows.append((w, norm_vi(w), pos or None, 1 if e["lemma"] else 0,
                     entry_type_of(w, poss), syllables(w)))
    rows.sort(key=lambda r: r[0])
    deferred.sort()
    stat["扫到的词形"] = len(words)
    stat["本步收"] = len(rows)
    stat["推迟（一条 gloss 都没有）"] = len(deferred)
    stat["词元"] = sum(r[3] for r in rows)
    return rows, stat, deferred, han


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    rows, stat, deferred, han = scan()
    print("■ 扫 %s" % paths.KK.name)
    for k in ("原始行", "剔除·pos 黑名单", "剔除·词形是空白（源头有，我们不收）",
              "剔除·全表意词头（→ 阶段 2 汉字层）", "无词头", "真词条目",
              "扫到的词形", "本步收", "推迟（一条 gloss 都没有）", "词元"):
        if stat[k]:
            print("   %-34s %9s" % (k, format(stat[k], ",")))
    print("   %-34s %9s" % ("非词元（只有指针义项）",
                            format(stat["本步收"] - stat["词元"], ",")))

    # 🔴 剔掉的那批要**说得出它们是什么**，否则「剔除」就变成了「丢掉」
    print("\n■ 剔掉的全表意词头 %s 条，按源头 pos：" % format(sum(han.values()), ","))
    print("   %s" % "、".join("%s %s" % (k, format(v, ",")) for k, v in han.most_common(8)))
    print("   ⚠️ 其中 %s 条的 pos 不是 `character` —— **只按 pos 剔会整批漏掉**"
          % format(sum(v for k, v in han.items() if k != "character"), ","))

    print("\n■ 推迟的 %s 个词形，按词性：" % format(len(deferred), ","))
    dp = collections.Counter(p for _, p in deferred)
    for p, c in dp.most_common(6):
        print("   %-16s %7s   样本 %s" % (p, format(c, ","),
              [w for w, q in deferred if q == p][:5]))

    print("\n■ `entry_type` 分布（判据只用源头 pos 直接映射，不猜）：")
    et = collections.Counter(r[4] for r in rows)
    for k, v in et.most_common():
        print("   %-16s %7s   样本 %s"
              % (k, format(v, ","), [r[0] for r in rows if r[4] == k][:5]))

    print("\n■ `syllables` 分布（空格与连字符都算分隔）：")
    sy = collections.Counter(r[5] for r in rows)
    print("   %s" % "、".join("%d 音节 %s" % (k, format(v, ",")) for k, v in sorted(sy.items())[:8]))

    # 🔴 抽样必须给全量，不能先切一段再抽（ko 那次按字典序切前 4000，
    #    结果 10 条有 9 条是纯汉字词，看着像「这门语言主要是汉字词」）
    dbtool.sample_check(rows, 12, ("词形", "归一", "词性", "词元", "类型", "音节"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    # 🔴 显式传 `invalidates=[]`：本语种第一次插行，此刻确实一层都不受影响。
    #    豁免不等于不用回答（`[[record-the-negative-decision]]`）。
    #
    # 🔴 **这道闸第一次跑就红了，而它是对的** —— 我只声明了 `__rows__`，
    #    `dict` 那 5 个 TRACK 列一个都没声明，闸逐列报「改到了不该改的地方」。
    #    插 30,738 行本来就会把这 5 列一起填上，所以要**把它们逐列写出来**，
    #    而不是把闸调松。⚠️ `freq_zipf` **有意不在这里**：阶段 1 不填频次，
    #    它要是也涨了，说明有人在这一步偷偷灌了别的东西。
    n = len(rows)
    with dbtool.session("build-vi-skeleton",
                        expect={"__rows__": n, "word_norm": n, "entry_type": n,
                                "is_lemma": n, "pos": n, "syllables": n},
                        invalidates=[]) as s:
        s.executemany(
            "INSERT INTO dict (word, word_norm, pos, is_lemma, entry_type, syllables) "
            "VALUES (?,?,?,?,?,?)",
            [(w, n, p, l, t, y) for w, n, p, l, t, y in rows])

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("dict 行数", q("SELECT COUNT(*) FROM dict"), len(rows)),
        ("word 唯一", q("SELECT COUNT(*) FROM (SELECT word FROM dict GROUP BY word "
                        "HAVING COUNT(*)>1)"), 0),
        ("word_norm 空", q("SELECT COUNT(*) FROM dict WHERE word_norm=''"), 0),
        ("pos 非空", q("SELECT COUNT(*) FROM dict WHERE pos IS NULL OR pos=''"), 0),
        ("词元数", q("SELECT COUNT(*) FROM dict WHERE is_lemma=1"), stat["词元"]),
        # 🔴 **反向断言**：表意词头一个都不许在库里。
        #    这一条锁的是用户 2026-09-28 那个决定 —— 下次重跑收词脚本它们不能悄悄回来
        #    （`[[decision-not-propagated-across-editions]]`）。
        ("表意词头 0 条", sum(1 for (w,) in con.execute("SELECT word FROM dict")
                              if is_han_headword(w)), 0),
        # 🔴 归一列自证：`word_norm` 必须逐行等于 `norm_vi(word)`。
        #    它锁住「哪天有人给 norm_vi 加了去声调」—— 那会把 má/mà/mả/mã/mạ 合成一个词。
        ("word_norm 与判据一致",
         sum(1 for w, n in con.execute("SELECT word, word_norm FROM dict") if norm_vi(w) != n), 0),
        ("syllables ≥1", q("SELECT COUNT(*) FROM dict WHERE syllables < 1"), 0),
        ("entry_type 值域",
         q("SELECT COUNT(*) FROM dict WHERE entry_type NOT IN "
           "('word','phrase','proverb','bound_morpheme','letter')"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-22s %10s（期望 %s）" % ("✅" if good else "🔴", name,
                                              format(got, ","), format(want, ",")))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
