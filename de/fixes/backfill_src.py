#!/usr/bin/env python3
"""收尾单 C1：回填 `ipa_src` / `gender_src` 两个来源列。de，2026-09-05。

═══ C1 是什么 ═══
`ipa_src` / `translation_src` / `gender_src` 三列**建了从没回填**，
于是 `ipa` 110,124 行、`translation` 349,775 行、`gender` 100,879 行
**一条都说不出自己是哪来的**（`[[ipa-provenance-columns]]`）。

═══ 三列的处境**不一样**，量过才知道 ═══
    gender_src   `entry.gender` 对得上 **100,120 / 100,879 = 99.2%**（全部 `en-edition`）
                 ⇒ 确定性回填；剩 758 是 C7 那批豆包补的 ⇒ 写 `unknown`
    ipa_src      `pronunciation` 里同词同串对得上只有 **43,016 / 110,124 = 39.1%**
                 ⇒ 对得上的取那一行的 `src`，其余写 `unknown`
    translation_src  **按构造就填不了**：`dict.translation` 是「一个词的所有义项中文
                 用 \\n 拼成的一个串」（33.3% 是多行），一个串没有单一来源。
                 v3 里它已经拆成 `sense_gloss(zh)`，那里**每条各有自己的 `src`**
                 （`model:def` 124,687／`unknown` 116,707／`zh-edition` 10,122／
                 `template:alt_of` 8,869）。⇒ **这一列不回填**，它属于 pre-v3 的世界。

═══ 🔴🔴 回填 `ipa_src` 的路上撞见一个大得多的问题（见 C41）═══
`dict.ipa` 与 `pronunciation` **不是归一差异，是两代数据**：
    Arabisch     dict.ipa `ˈaʁaːbɪʃ`      pronunciation `aˈʁaːbɪʃ`    （重音位置）
    extra        dict.ipa `ˈɛks.tʁa`      pronunciation `ˈɛkstʁa`     （音节点）
    Brotback…    dict.ipa `ˈbʀoːt…`       pronunciation `ˈbʁoːt…`     （ʀ vs ʁ）
拿两边都有的 **71,764 对**当真值集跑归一（接受规则同 C22：一条已一致的都不许打坏），
收下四条映射（去音节点／`ʀ→ʁ`／`aʊ→aʊ̯`／`ɔʏ→ɔɪ̯`）之后一致率
**59.24% → 60.83% 就到头了** ⇒ 余下 39% 是**实质分歧**，而样本一面倒地说
`pronunciation`（阶段 4 从源头收、带 provenance）是对的、`dict.ipa`（七月遗留）是错的。

⇒ **`dict.ipa` 是遗留列**。本脚本给它回填来源只是让它**自己说清楚自己是什么**，
  不是让它复活。**不把它搬进 `pronunciation`** —— 那等于盲搬约 1.5 万条可疑值
  （`FRAMEWORK §一`：错比缺更伤权威）。

用法：
    python3 fixes/backfill_src.py            # 试算
    python3 fixes/backfill_src.py --write
"""
import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths                                                    # noqa: E402

f = lambda n: format(n, ",")
UNKNOWN = "unknown"          # `[[ipa-provenance-columns]]`：证明不了就写 unknown


def plan(con):
    """→ (ipa 行, gender 行)，各是 [(id, src)]。**判据只许这一份**。"""
    ipa = con.execute(
        "SELECT d.id, COALESCE((SELECT p.src FROM pronunciation p "
        "                        WHERE p.word_id=d.id AND p.ipa=d.ipa "
        "                        ORDER BY p.is_primary DESC, p.id LIMIT 1), ?) "
        "  FROM dict d WHERE COALESCE(d.ipa,'')<>'' "
        "   AND COALESCE(d.ipa_src,'')=''", (UNKNOWN,)).fetchall()
    gen = con.execute(
        "SELECT d.id, COALESCE((SELECT e.src FROM entry e "
        "                        WHERE e.word_id=d.id AND e.gender=d.gender LIMIT 1), ?) "
        "  FROM dict d WHERE COALESCE(d.gender,'')<>'' "
        "   AND COALESCE(d.gender_src,'')=''", (UNKNOWN,)).fetchall()
    return ipa, gen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ipa, gen = plan(con)
    for name, rows in (("ipa_src", ipa), ("gender_src", gen)):
        c = Counter(s for _, s in rows)
        print("■ %s：%s 行" % (name, f(len(rows))))
        for k, v in c.most_common():
            print("   %-24s %10s  %5.1f%%" % (k, f(v), 100.0 * v / max(len(rows), 1)))
    con.close()

    if not a.write:
        print("\n(未加 --write，未写库)")
        return 0

    import dbtool
    with dbtool.session("keep-v3-c1-backfill-src",
                        expect={"ipa_src": len(ipa), "gender_src": len(gen)}) as s:
        s.executemany("UPDATE dict SET ipa_src=? WHERE id=?", [(v, i) for i, v in ipa])
        s.executemany("UPDATE dict SET gender_src=? WHERE id=?", [(v, i) for i, v in gen])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    print("\n═══ 闸 ═══")
    checks = [
        ("🔴 有 ipa 却说不出来源（连 unknown 都没写）",
         q("SELECT COUNT(*) FROM dict WHERE COALESCE(ipa,'')<>'' AND COALESCE(ipa_src,'')=''"), 0),
        ("🔴 有 gender 却说不出来源",
         q("SELECT COUNT(*) FROM dict WHERE COALESCE(gender,'')<>'' AND COALESCE(gender_src,'')=''"), 0),
        ("🔴 没有值却写了来源（ipa）",
         q("SELECT COUNT(*) FROM dict WHERE COALESCE(ipa,'')='' AND COALESCE(ipa_src,'')<>''"), 0),
        ("🔴 没有值却写了来源（gender）",
         q("SELECT COUNT(*) FROM dict WHERE COALESCE(gender,'')='' AND COALESCE(gender_src,'')<>''"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-42s %10s  期望 %s" % ("✓" if good else "🔴", name, f(got), f(want)))
    con.close()
    print("\n%s" % ("✓ 闸全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
