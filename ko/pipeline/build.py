#!/usr/bin/env python3
"""阶段 1（上半）：建 `dict` 骨架 —— 从**英文版**切片。2026-09-20。
（下半是 `build_entry_layer.py` 建 `entry` 层；表结构已由阶段 0 的 `build_v3_schema.py` 建好）

═══ 🔴 为什么骨架是英文版（这一条是量出来的，不是惯性）═══
韩语上「英文版是骨架」比前七门**更成立**，因为 ja 上唯一让它失效的那条在 ko 上不成立：

    只有英文版有的      词源 38,796 条（另外四份源**全是 0**）
                        活用 359,583 个变形词形（韩文版只有 30,982）—— ja 是反的（英文版只给 7.0%）
                        pos 齐全（韩文版 14% unknown、中文版 **99.5%** unknown）

⚠️ **「最大」和「该当骨架」是两回事**：中文版简体片有 195,332 个词头（英文版的 3.4 倍），
   但实测 41 个韩语最基础的词（하다/있다/사람/때/좋다 这种）它**只覆盖 17 个（41%）**，
   而英/韩两版各是 41/41。它是一张**长尾偏重**的词表 ⇒ 当不了身份的锚。
   它的价值（15.7 万个别处没有的词 + 中文释义）走阶段 4 收词。

═══ 判据：什么进 `dict` ═══
🔴 **不要照抄 ja 的 `NOT_A_WORD = {soft-redirect, romanization}`** ——
   实测 ko 的 pos 值域 26 种里**根本没有 `soft-redirect`**（ja 有 44,899 条），
   `romanization` 只有 **8 条**（ja 有 32,062 条）。照抄等于写了一条几乎不做事的规则，
   而真正该拦的东西（下面那 6,089 个）一条都拦不住。

    ① 剔 `pos=romanization`        8 个词形（`pail` / `daun` / `paseo`）——
                                    罗马字拼写的韩语词，收进来词典里会冒出拉丁串词头
    ② 剔词形是空白的                实测 0 条。**判据保留**：一行空白比少收一个字更伤，
                                    而且它会让后续任何「词形非空」的不变量失效
    ③ 🔴 **整个词形一条 gloss 都没有的 6,089 个，本步不收**
                                    全是汉字（`説` `僕` `底` `層` `亠` `編`…），
                                    97.8%（5,955 个）带 `forms`（汉字↔谚文对应）但没有义项。
                                    现在收进来 = 6,089 个「搜得到、点进去没有释义」的页面
                                    —— pt 正是这么栽的（355,605 个词形＝46.2% 空白页）。
                                    ⇒ 它们连同 hanja↔hangeul 指向一起进**阶段 2**。
                                    ⚠️ 明说是**我们这一步不收**，不是源头没有
                                    （`[[dont-say-source-lacks-what-we-skipped]]`）。

⭐ **两把独立的尺子在这里收敛**（`[[reversal-needs-new-measurement]]` 的正面用法）：
   跨版交集脚本算出「英文版有释义的词形 51,163」，
   本脚本用完全不同的路径算 `57,252 - 6,089 = 51,163` —— 一条不差。

═══ `word_norm`：**NFC，不是 NFKC** —— 与 ja 相反，而且是量出来的 ═══
ja 用 `NFKC + 片假名→平假名`，接受了 576 组碰撞（"那几类折叠对检索是对的"）。
韩语实测：

    NFC    **0 组碰撞**
    NFKC   1 组碰撞：`㉾`（带圈谚文符号）被折成 `우`（真词）—— 那是**错的折叠**
    含半角谚文的词头  **0 个** ⇒ NFKC 在 ko 上唯一的收益是零

⇒ NFKC 在韩语上**零收益、有害**。用 NFC。
🔴 但 `word_norm` 这一列仍然必要，而且**检索侧必须归一**：
   源头 100% 已是 NFC，可 macOS/iOS 的输入法与剪贴板会产出 **NFD** 谚文
   （`가` 拆成 ᄀ+ᅡ），长得一模一样、字节不同、`=` 匹配不上。
   **「源头干净」和「不需要归一」是两件事。**
⚠️ SQLite 的 `COLLATE NOCASE` / `lower()` 只折 ASCII，对谚文完全无效
   ⇒ 归一必须在 Python 侧做，**不建 NOCASE 索引**（那会是个假索引）。

跑（在仓库根）：
    python3 -u ko/pipeline/build.py            # 干跑，只报数
    python3 -u ko/pipeline/build.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import json
import sqlite3
import unicodedata

# 🔴 判据**只写一份**，住在 `criteria.py` —— 建外锚闸时发现它在三个文件里
#    各有一份（当时三份一样，但三份一定会漂，而闸正要靠它）。
#    `[[refactor-mindset-code-quality]]`／外锚闸必须 import 收词器用的那一份。
from criteria import (NOT_A_WORD, norm_ko, is_pointer_sense)  # noqa: F401

import dbtool
import paths

# 🔴 判据是**源头自己给的 pos**，不是形式代理（`[[criteria-from-meaning-not-form]]`）。
#    ko 实测只有这一种要剔，而 ja 那份有两种 —— 照抄会写出一条几乎不做事的规则。





def scan():
    """扫英文版切片 → 每个词形一条记录。返回 (rows, stat, deferred)。"""
    words = {}                       # word → {pos:Counter, lemma:bool, gloss:bool}
    stat = collections.Counter()
    for line in open(paths.KK, encoding="utf-8"):
        o = json.loads(line)
        stat["原始行"] += 1
        pos = o.get("pos")
        if pos in NOT_A_WORD:
            stat["剔除·%s" % pos] += 1
            continue
        w = o.get("word")
        if not w:
            stat["无词头"] += 1
            continue
        if not w.strip():
            stat["剔除·词形是空白（源头有，我们不收）"] += 1
            continue
        stat["真词条目"] += 1
        e = words.setdefault(w, {"pos": collections.Counter(),
                                 "lemma": False, "gloss": False})
        e["pos"][pos] += 1
        for se in (o.get("senses") or []):
            if not (se.get("glosses") or []):
                continue
            e["gloss"] = True
            # 词元判据：**这个词形有没有至少一条不是指针的义项**。
            # 🔴 不用「词性是不是 X」这种形式代理 —— 指针与否是源头逐义项说清楚的。
            if not is_pointer_sense(se):
                e["lemma"] = True
    rows, deferred = [], []
    for w, e in words.items():
        # 聚合词性：多词条时按出现量排、`/` 连接（逐义项词性在 sense.pos）
        pos = "/".join(p for p, _ in e["pos"].most_common() if p)
        if not e["gloss"]:
            # 🔴 一条 gloss 都没有 ⇒ 本步不收，留给阶段 2（连同 hanja↔hangeul 指向）
            deferred.append((w, pos))
            continue
        rows.append((w, norm_ko(w), pos or None, 1 if e["lemma"] else 0))
    rows.sort(key=lambda r: r[0])
    deferred.sort()
    stat["扫到的词形"] = len(words)
    stat["本步收"] = len(rows)
    stat["推迟到阶段 2（无 gloss）"] = len(deferred)
    stat["词元"] = sum(r[3] for r in rows)
    return rows, stat, deferred


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    rows, stat, deferred = scan()
    print("■ 扫 %s" % paths.KK.name)
    for k in ("原始行", "剔除·romanization", "剔除·词形是空白（源头有，我们不收）",
              "无词头", "真词条目", "扫到的词形", "本步收",
              "推迟到阶段 2（无 gloss）", "词元"):
        if stat[k]:
            print("   %-30s %9s" % (k, format(stat[k], ",")))
    print("   %-30s %9s" % ("非词元（只有指针义项）",
                            format(stat["本步收"] - stat["词元"], ",")))

    # 推迟那批要能**说得出它们是什么**，否则「推迟」就变成了「丢掉」
    dp = collections.Counter(p for _, p in deferred)
    print("\n■ 推迟到阶段 2 的 %s 个词形，按词性：" % format(len(deferred), ","))
    for p, c in dp.most_common(6):
        print("   %-16s %7s   样本 %s" % (p, format(c, ","),
              [w for w, q in deferred if q == p][:5]))

    # 🔴 **抽样必须给全量**，不能先切一段再抽。第一版写的是 `rows[:4000:311]`，
    #    而 `rows` 按字典序排、Unicode 里汉字（U+4E00+）全排在谚文（U+AC00+）前面
    #    ⇒ 抽出来 10 条有 9 条是纯汉字词，**一条谚文词都没有**，
    #    看着像"这门语言主要是汉字词"。`sample_check` 自己会随机抽。
    dbtool.sample_check([(w, n, p, l) for w, n, p, l in rows],
                        12, ("词形", "归一", "词性", "词元"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    # 🔴 显式传 `invalidates=[]`：tag 以 `build` 开头本来就豁免收词闸，但**豁免不等于
    #    不用回答**。这一步是本语种第一次插行，确实一层都不受影响（此刻没有别的层），
    #    把这句话**写下来**比靠前缀绕过去好（`[[record-the-negative-decision]]`）。
    with dbtool.session("build-ko-skeleton",
                        expect={"__rows__": len(rows), "pos": len(rows)},
                        invalidates=[]) as s:
        s.executemany(
            "INSERT INTO dict (word, word_norm, is_lemma, pos) VALUES (?,?,?,?)",
            [(w, n, l, p) for w, n, p, l in rows])

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("dict 行数", q("SELECT COUNT(*) FROM dict"), len(rows)),
        ("word 唯一", q("SELECT COUNT(*) FROM (SELECT word FROM dict GROUP BY word "
                        "HAVING COUNT(*)>1)"), 0),
        ("word_norm 空", q("SELECT COUNT(*) FROM dict WHERE word_norm=''"), 0),
        ("词元数", q("SELECT COUNT(*) FROM dict WHERE is_lemma=1"), stat["词元"]),
        # 🔴 归一列自证：源头 100% 是 NFC ⇒ word_norm 必须逐行等于 word。
        #    这一条不是废话 —— 它锁住「哪天有人把 norm_ko 改成 NFKC」这件事，
        #    而 NFKC 在韩语上会把 `㉾` 折成真词 `우`（实测唯一的碰撞）。
        ("word_norm == word", q("SELECT COUNT(*) FROM dict WHERE word_norm<>word"), 0),
        ("pos 非空", q("SELECT COUNT(*) FROM dict WHERE pos IS NULL OR pos=''"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-18s %10s（期望 %s）" % ("✅" if good else "🔴", name,
                                              format(got, ","), format(want, ",")))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
