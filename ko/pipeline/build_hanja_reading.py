#!/usr/bin/env python3
"""阶段 1（第四步）：建 `hanja_reading` —— 谚文音节 → 一组汉字（한자음）。2026-09-20。

═══ 这一步为什么存在 ═══
`KO_PLAN` §4.3 原本判断"不需要汉字音层"，判据是「`한자` 切片只能净增 619 个字头」。
那句话是真的，**但它回答的不是这个问题**
（`[[criterion-true-half-vouches-for-false-half]]`）：
韩语汉字音的数据根本不在 `한자` 切片里，在**英文版的 `pos=syllable` 条目**里 ——
8,639 条义项，100% 是单音节谚文，集中在 343 个音节（`사` 171 条／`정` 154／`주` 131）。
建义项层时抽样反验看见 `주` 有 53 条"义项"、内容只是一个汉字，才发现。

它们已被 `build_sense_layer.py` 挡在出版层之外（否则 `사` 的页面会有 171 条
只有一个汉字、没有释义的"义项"），证据层照收。本步把它们**变成结构化数据**。

═══ 🔴 只抽能确定性拿到的两列，`eumhun` / `mc` 留空并记账 ═══
源头的 `glosses` 是这样的（`일` 为例，层级 gloss 占 62%）：

    glosses[0] = "More information(eumhun reading: 하나 일 …)(MC reading: 一 …)
                  (eumhun reading: 날 일 …)(MC reading: 日 …)(MC reading: 逸 …)…"
                 ← **整个音节共享的信息框**，每条义项都重复带着它
    glosses[-1] = "一: one"    ← 这一条自己的内容

⇒ `hanja` 和 `gloss_en` 从 `glosses[-1]` 解析，**确定性、逐条自证**。

🔴 **`eumhun` 和 `mc` 本步留 NULL，不从信息框里解析。**
   量的是什么：信息框里确实带着 712 条 eumhun、1,810 条 MC reading。
   为什么不抽：信息框里 eumhun 与汉字的对应关系**只能靠位置推断**
   （一个 `eumhun reading` 后面跟着一串 `MC reading`，直到下一个 eumhun）——
   而位置推断正是**最容易错配**的做法。`eumhun` 错配到别的汉字上是**错**，
   留空只是**缺**，而错比缺更伤权威（`[[dict-framework-doc]]`）。
   什么会推翻它：①找到逐字结构化的 eumhun 源（韩文版 / `한자` 切片 / 国立国语院）；
   或 ②能写出一条**两个独立信号一致**的判据（如"位置推断的结果与某个外部字表一致"），
   像 pt 的 2d/2e 那样（结构化字段 ＝ 散文结尾，99.2% 一致才收）。

═══ 判据 ═══
    glosses[-1] 形如  `汉字` / `汉字: 英文释义` / `* 汉字`（带星号前缀）
                  或  `坑, 更, 硜, 粳, 羹, 賡, 鏗`（逗号分隔的纯汉字列表）
    `汉字` 部分**逐字**用 `dbtool.has_han_char` 验（**全区间，含扩展 G/H/I**）——
    🔴 不用 `[一-鿿]` 这种基本区正则：韩语汉字音里大量是扩展区字
       （`䘌` `䭿` `㼁` `㦤`），而 `𰜩` 更是在**扩展 G**（U+30729）——
       拷过来的 `_HAN_RANGES` 停在 U+2FA1F，当场把它判成"不是汉字"。
       那份区间表已在 `ko/dbtool.py` 补齐，变异 M5c/M5d 锁住上界。

═══ 🔴 解析不出的 113 条：**说得清是什么，才敢留在桶里** ═══
（`[[residual-bucket-is-not-evidence]]`：残差是残差，不是度量）

    分布在 12 个音节，其中 **只有 4 个音节会因此完全没有汉字音数据**，
    而那 4 个里 **3 个本来就不是汉字音列表**：
        갸  "Archaic pronunciation of 架; the modern Korean equivalent is 가"  说明文本
        디  "See the relevant section at the entry for 지 (ji)."              交叉引用
        튽  "alternative form of 장 (jang, …)"                               指针
        갱  "坑, 更, 硜, 粳, 羹, 賡, 鏗"    ← **唯一真的丢了数据** ⇒ 为它加了逗号列表规则

    其余 9 个音节（차 33 条／유 34／돌 25／혼 13…）解析不出的是**整块信息框**
    （`More information\n* 且:\n(MC reading: …)`）。
    ⭐ **那是已抽数据的汇总，不是补充**：`차` 正常抽到 32 条、块内正好 32 个 `* 汉字:`，
      `혼` 抽到 6 条、块内 6 个 —— **逐一对上，零增量**。所以不解析块不丢东西。
    🔴 判据按「**哪个音节会变成空的**」问，不按「还剩多少条没解析」问。

跑（在仓库根）：
    python3 -u ko/pipeline/build_hanja_reading.py
    python3 -u ko/pipeline/build_hanja_reading.py --apply
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

SRC = "en-edition"
SYLLABLE_POS = "syllable"


def parse_gloss(t):
    """`glosses[-1]` → [(汉字, 英文释义 or None), ...]。解析不出返回 []。

    🔴 汉字判据用 `dbtool.has_han_char`（全区间，含扩展 G/H/I），不是基本区正则。
       韩语汉字音里真实出现 `𰜩`（U+30729，扩展 G）—— 拷过来的区间表停在 U+2FA1F。

    两种形态：
      ① `汉字` / `汉字: 英文` / `* 汉字`     —— 8,524 条，主力
      ② `坑, 更, 硜, 粳, 羹, 賡, 鏗`          —— 逗号分隔的汉字列表
         ⚠️ 这一条是为**丢了数据的那个音节**加的，不是为了多几行：
            13 个有解析不出条目的音节里，**只有 `갱` 一个完全没抽到东西**，
            而它的内容正是这种逗号列表。判据按「哪个音节会变成空的」问，
            不按「还剩多少条没解析」问（`[[residual-bucket-is-not-evidence]]`：
            残差是残差，不是度量）。
    """
    t = (t or "").strip()
    if t.startswith("*"):                      # 带星号前缀（`* 且`）
        t = t[1:].strip()
    head, _, rest = t.partition(":")
    head = head.strip()
    if not head or "\n" in head:
        return []
    if all(dbtool.has_han_char(c) for c in head):
        return [(head, rest.strip().split("\n")[0].strip() or None)]
    # ② 逗号分隔的纯汉字列表。整串必须**只由汉字、逗号、空格**组成才收 ——
    #    判据宽一格就会把 `点/奌: alternative form of 點` 这类混进来。
    if not rest and "," in head:
        parts = [p.strip() for p in head.split(",")]
        if len(parts) > 1 and all(p and all(dbtool.has_han_char(c) for c in p)
                                  for p in parts):
            return [(p, None) for p in parts]
    return []


def scan(indict, inentry):
    seen_entry = collections.Counter()
    rows, unparsed = [], []
    stat = collections.Counter()
    # 🔴 **同一个 (音节, 汉字) 只留一行。** 第一版只保证了 `src_ref` 唯一，
    #    而 src_ref 认的是"来源位置"不是"事实" ⇒ 同一个字在同一个音节下的
    #    多条义项各存一行，`섭` 的 `聶` 存了 6 遍、`폭` 的 `暴` 6 遍，
    #    实测冗余 **3,114 行**。
    #    ⚠️ 这与变形层那 31,896 行冗余是**同一个病**（wiktextract 把同一块
    #       内容解析多遍），而我当时只在变形层修了 —— **同一条判据要在所有层上一致**，
    #       否则就是"修了一个、另一个静静留着"（`[[decision-not-propagated-across-editions]]`
    #       的层内版本）。
    seen_pair = set()
    for line in open(paths.KK, encoding="utf-8"):
        o = json.loads(line)
        praw = o.get("pos")
        if praw != SYLLABLE_POS:
            continue
        w = o.get("word")
        if not w or not w.strip():
            continue
        wid = indict.get(w)
        if wid is None:
            stat["词形不在 dict 里"] += 1
            continue
        en_ = o.get("etymology_number")
        etym = str(en_) if en_ is not None else "0"
        k = (w, praw, etym)
        seq = seen_entry[k]
        seen_entry[k] += 1
        eref = "kk-ko:%s:%s:%s:%d" % (w, praw, etym, seq)
        eid = inentry.get(eref)
        for i, se in enumerate(o.get("senses") or []):
            g = se.get("glosses") or []
            if not g:
                continue
            stat["syllable 义项"] += 1
            got = parse_gloss(g[-1])
            if not got:
                unparsed.append((w, g[-1][:70]))
                stat["解析不出汉字（见下）"] += 1
                continue
            # 一条义项可能产出多行（逗号列表）⇒ src_ref 带上**这条里的第几个**，
            # 否则 `갱` 的 7 个汉字会撞同一个 src_ref
            for j, (hanja, gloss) in enumerate(got):
                if (wid, hanja) in seen_pair:
                    stat["跳过·同 (音节,汉字) 重复"] += 1
                    continue
                seen_pair.add((wid, hanja))
                rows.append((wid, eid, hanja, gloss, None, None, SRC,
                             "%s#%d.%d" % (eref, i, j)))
                stat["→ hanja_reading"] += 1
                if gloss:
                    stat["带英文释义"] += 1
            if len(got) > 1:
                stat["逗号列表（一条义项多个汉字）"] += 1
    return rows, stat, unparsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    indict = {r[1]: r[0] for r in con.execute("SELECT id, word FROM dict")}
    inentry = {r[1]: r[0] for r in con.execute("SELECT id, src_ref FROM entry")}
    have = con.execute("SELECT COUNT(*) FROM hanja_reading").fetchone()[0]
    con.close()
    if have:
        raise SystemExit("🔴 hanja_reading 非空（%d 行）—— 本步是首建。" % have)

    rows, stat, unparsed = scan(indict, inentry)
    for k, v in stat.most_common():
        print("   %-24s %9s" % (k, format(v, ",")))

    syls = len({r[0] for r in rows})
    chars = len({r[2] for r in rows})
    print("   %-24s %9s" % ("涉及谚文音节", format(syls, ",")))
    print("   %-24s %9s" % ("不同汉字", format(chars, ",")))

    # 🔴 解析不出的必须能**说得出是什么**，否则"解析不出"就成了一个藏东西的桶
    #    （`[[residual-bucket-is-not-evidence]]`：残差不是度量）
    if unparsed:
        print("\n🔴 解析不出汉字的 %d 条，样本：" % len(unparsed))
        for w, t in unparsed[:8]:
            print("     %s  %r" % (w, t))

    refs = collections.Counter(r[7] for r in rows)
    dup = {k: c for k, c in refs.items() if c > 1}
    print("   %-24s %s" % ("src_ref 唯一", "✅" if not dup else "🔴 %d 重复" % len(dup)))
    if dup:
        raise SystemExit("🔴 src_ref 重复")

    # 🔴 与证据层对账：本表每一行都该能在 `sense_src` 里找到同一个 src_ref。
    #    两条路径独立生成，对得上才说明判据一致（`[[correct-steps-can-compose-a-hole]]`）。
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    srcrefs = {r[0] for r in con.execute("SELECT src_ref FROM sense_src")}
    con.close()
    orphan = [r for r in rows if r[7].rsplit(".", 1)[0] not in srcrefs]
    print("   %-24s %s" % ("每行都对得上 sense_src",
                           "✅" if not orphan else "🔴 %d 行对不上 %s"
                           % (len(orphan), [o[7] for o in orphan[:3]])))
    if orphan:
        raise SystemExit("🔴 与证据层对不上账")

    # 🔴 **抽样给全量、不切片；反向映射先建好、不在循环里 O(n) 查。**
    #    这两个毛病我今天各犯了三次（`build.py` / `build_sense_layer.py` / 这里），
    #    症状是抽出来的 12 条全是生僻汉字 —— 因为列表按字典序排，
    #    Unicode 里汉字（U+4E00+）全在谚文（U+AC00+）前面。
    word_of = {i: w for w, i in indict.items()}
    dbtool.sample_check([(r[2], r[3] or "—", word_of[r[0]]) for r in rows],
                        12, ("汉字", "英文释义", "谚文音"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    with dbtool.session("build-ko-hanja-reading",
                        expect={"#hanja_reading": len(rows)},
                        invalidates=[]) as s:
        s.executemany(
            "INSERT INTO hanja_reading (word_id, entry_id, hanja, gloss_en, "
            "eumhun, mc, src, src_ref) VALUES (?,?,?,?,?,?,?,?)", rows)

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("hanja_reading 行数", q("SELECT COUNT(*) FROM hanja_reading"), len(rows)),
        ("word_id 都指得到 dict",
         q("SELECT COUNT(*) FROM hanja_reading h LEFT JOIN dict d ON d.id=h.word_id "
           "WHERE d.id IS NULL"), 0),
        ("hanja 非空", q("SELECT COUNT(*) FROM hanja_reading WHERE hanja=''"), 0),
        ("没有 (音节,汉字) 重复",
         q("SELECT COUNT(*) FROM (SELECT 1 FROM hanja_reading "
           "GROUP BY word_id, hanja HAVING COUNT(*)>1)"), 0),
        # eumhun/mc 本步有意留空 —— 锁住它，将来谁填了这两列必须是**有判据地**填
        ("eumhun/mc 本步全空",
         q("SELECT COUNT(*) FROM hanja_reading WHERE eumhun IS NOT NULL "
           "OR mc IS NOT NULL"), 0),
        # 那 42 个「只有汉字音义项」的词形，现在有内容了吗
        ("零出版义项的词形都有汉字音",
         q("SELECT COUNT(*) FROM dict d "
           "WHERE NOT EXISTS (SELECT 1 FROM sense s WHERE s.word_id=d.id) "
           "  AND NOT EXISTS (SELECT 1 FROM hanja_reading h WHERE h.word_id=d.id) "
           "  AND NOT EXISTS (SELECT 1 FROM sense_src ss WHERE ss.word_id=d.id "
           "                    AND ss.sense_id IS NULL)"), 0),
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
