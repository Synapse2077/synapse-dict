#!/usr/bin/env python3
"""族G：变位行内容重复（读者眼里的同一行躺两遍）。2026-08-30。

═══ 它是被族E 的修复"照"出来的，不是新造出来的 ═══
族E 把时态标签改对之后，回归闸 B6 立刻红了 105,554。
先问「数据错了还是断言过期」——**数据错了，而且一直错着**：

    ver → vi   [陈述式简单过去时第一人称单数]   ×2   en-edition + pt-edition-forms

两个版本本来就都收了这个形式；改标签之前 pt 版那行写的是「陈述式第一人称单数」
（`past` 不在 TENSE 里、时态被丢掉），字符串不同 ⇒ 闸看不见、读者却看得见两行相似的。
**改对标签把它们变成了字面相同，重复才浮出来。**

⚠️ 这就是「闸绿不等于没问题」的一个干净例子：闸比的是字符串，读者比的是意思。

═══ 顺带：B6 的判据比它要描述的问题窄 ═══
B6 第二段写的是
    COUNT(DISTINCT src LIKE '%-edition-forms') > 1     ← 只算**跨来源**的重复
而 `en-edition + en-edition` 自己撞的 1,322 组（`o→os [阳性复数]`、`dado→dada [阴性单数]`）
它从建成那天起就看不见。判据该问的是「读者会不会看到同一行两遍」，
和这行是哪个版本写的无关（`[[criteria-narrower-than-you-think]]` 第 N 次）。
⇒ 本步同时把 B6 收窄成按含义的版本。

═══ 保留哪一行 ═══
🔴 **不能随便留第一条** —— 那是族A 合并录音时踩过的坑（只留第一条就把地区扔了）。
   同组各行的 `tags` / `desc_en` 不一样：英文版带 `desc_en`（"first-person singular
   preterite indicative of ver"），各语言版的 `-edition-forms` 行 `desc_en` 是空的。
   ⇒ 优先留**有 desc_en** 的那行；都有或都没有则留 id 最小的（进库最早）。

用法（在 pt/ 目录下）：
    python3 fixes/fix_inflection_dedup.py
    python3 fixes/fix_inflection_dedup.py --apply
"""
import argparse
import collections
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402


def plan(con):
    groups = collections.defaultdict(list)
    for iid, wid, base, lab, desc in con.execute(
            "SELECT id, word_id, base, label_zh, desc_en FROM inflection"):
        groups[(wid, base, lab)].append((iid, desc))
    drop, kept_lost_desc = [], 0
    for _k, rows in groups.items():
        if len(rows) == 1:
            continue
        rows.sort(key=lambda r: (r[1] is None or r[1] == "", r[0]))   # 有 desc_en 的排前面
        keep = rows[0]
        drop.extend(i for i, _d in rows[1:])
        if (keep[1] is None or keep[1] == "") and any(d for _i, d in rows[1:]):
            kept_lost_desc += 1
    return drop, len(groups), kept_lost_desc


def main(a):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    before = con.execute("SELECT COUNT(*) FROM inflection").fetchone()[0]
    drop, ngroups, lost = plan(con)
    f = lambda n: format(n, ",")
    dup_groups = con.execute(
        "SELECT COUNT(*) FROM (SELECT word_id,base,label_zh FROM inflection "
        "GROUP BY 1,2,3 HAVING COUNT(*)>1)").fetchone()[0]
    print("■ inflection 现有 %s 行 / %s 个 (词形,原形,标签) 组" % (f(before), f(ngroups)))
    print("■ 重复组 %s，要删 %s 行" % (f(dup_groups), f(len(drop))))
    # 负控：留下的那行绝不该比被删的行信息少
    print("■ 负控 —— 留下的行丢了 desc_en 而被删的行有：%d（必须是 0）" % lost)
    if lost:
        return 1
    for w, b, l, n, s in con.execute(
            "SELECT d.word,i.base,i.label_zh,COUNT(*),GROUP_CONCAT(i.src) FROM inflection i "
            "JOIN dict d ON d.id=i.word_id GROUP BY i.word_id,i.base,i.label_zh "
            "HAVING COUNT(*)>1 LIMIT 5"):
        print("     %-14s → %-16s [%s] ×%d  %s" % (b[:14], w[:16], l, n, s))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("fix-pt-inflection-dedup", expect={"#inflection": -len(drop)}) as s:
        s.executemany("DELETE FROM inflection WHERE id=?", [(i,) for i in drop])
    left = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True).execute(
        "SELECT COUNT(*) FROM (SELECT word_id,base,label_zh FROM inflection "
        "GROUP BY 1,2,3 HAVING COUNT(*)>1)").fetchone()[0]
    print("\n✓ 删 %s 行；剩余重复组 %d（必须是 0）" % (f(len(drop)), left))
    return 1 if left else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    sys.exit(main(ap.parse_args()))
