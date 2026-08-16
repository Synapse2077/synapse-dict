#!/usr/bin/env python3
"""意语版拿 `phrase` 当筐：用英文版当外部锚，改成功能词性。2026-08-16。

═══ 用户从界面上看出来的 ═══
`Dodoma`（坦桑尼亚首都）显示成【短语】。查下来是意大利语维基把 `phrase`
用成了多词表达的**统一筐**，而英文版给的是**功能词性**：

    rispetto a      我们 phr  英文版 prep   ← 它是介词
    in fretta       我们 phr  英文版 adv    ← 它是副词
    diritti umani   我们 phr  英文版 n      ← 人权，名词
    fare carriera   我们 phr  英文版 v      ← 发展事业，动词

归在「短语」下等于把这条信息丢了。

═══ 三条判据，都不问模型 ═══
① **外部锚**：该词形在英文版里有且只有一个非 phr 词性 ⇒ 用它。实测 1,563 条。
   英文版没收的（3,735）与英文版也说是短语的（62）一律不动。
② **自相矛盾**：词形是**单个词**却标成 phr —— 短语至少两个词。
   首字母大写的 7 条逐条判（`Dodoma`→专名、`SIMD`→缩写…），写死在下面的表里，
   因为它们各不相同、又少到值得逐条看。
③ 单个词 + 小写的 67 条：`eccomelo`（ecco+me+lo 合体）、`vattelappesca`（俚语）——
   改成什么不确定，**留原样记账**，不猜。

⚠️ 只改 `sense.pos`，`entry.pos` 与证据层一个字节不动 —— 那两处锚着外部 dump。

用法（在 it/ 目录下）：
    python3 fixes/fix_phrase_pos.py
    python3 fixes/fix_phrase_pos.py --apply
    python3 fixes/fix_phrase_pos.py --verify
"""
import argparse
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from build import POS_MAP   # noqa: E402

# 判据②：单个词却标成 phr 的 7 条，逐条判。写在明处，不藏在正则里。
BY_HAND = {
    "Dodoma": "name",       # 坦桑尼亚首都
    "Chabad": "name",       # 哈巴德（犹太教哈西德派）
    "Judaika": "name",      # 犹太文物
    "Russiagate": "name",   # 通俄门
    "SIMD": "abbr",         # 单指令多数据
    "DEF": "abbr",          # 意大利经济财政文件
    "E=mc²": "n",           # 质能方程，当名词条目
}


def en_pos(ref):
    """kk-en:<词形>:<词性>:<词源号>:<x>#<occ>.<idx>；词形可能含 ':'，从右边数。"""
    p = ref.rsplit("#", 1)[0].split(":")
    return p[-3] if len(p) >= 4 else None


def anchors(con):
    en = defaultdict(set)
    for wid, ref in con.execute("SELECT word_id, src_ref FROM sense_src WHERE src='en-edition'"):
        p = en_pos(ref)
        if p:
            en[wid].add(POS_MAP.get(p, p))
    return en


def plan(con):
    en = anchors(con)
    rows, stat = [], Counter()
    for sid, wid, w in con.execute(
            "SELECT s.id, s.word_id, d.word FROM sense s JOIN dict d ON d.id=s.word_id "
            "WHERE s.pos='phr' AND COALESCE(s.hidden,0)=0"):
        if w in BY_HAND:
            stat["② 单词却标 phr，逐条判"] += 1
            rows.append((BY_HAND[w], sid))
            continue
        e = en.get(wid)
        if not e:
            stat["英文版没收（无锚，留 phr）"] += 1
        elif "phr" in e:
            stat["英文版也说是短语（留）"] += 1
        elif len(e) == 1:
            stat["① 英文版给唯一功能词性 → 改"] += 1
            rows.append((next(iter(e)), sid))
        else:
            stat["英文版给多个词性（留）"] += 1
    return rows, stat


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    en = anchors(con)
    left = 0
    for wid, w, pos in con.execute(
            "SELECT s.word_id, d.word, s.pos FROM sense s JOIN dict d ON d.id=s.word_id "
            "WHERE s.pos='phr' AND COALESCE(s.hidden,0)=0"):
        e = en.get(wid)
        if e and "phr" not in e and len(e) == 1:
            left += 1
    # ⚠️ 第一版把「修之前」测到的 67 写死当基线，修完剩 29 就报红 —— **锚自己上一版**，
    #    今天第三次栽在这。改成结构性口径：剩下的单词 phr **必须都是没有外部锚的**，
    #    也就是"能修的都修了"，与具体剩几条无关。
    single_recoverable = 0
    for wid, w in con.execute(
            "SELECT DISTINCT s.word_id, d.word FROM sense s JOIN dict d ON d.id=s.word_id "
            "WHERE s.pos='phr' AND COALESCE(s.hidden,0)=0"):
        if any(ch in w for ch in " '’-"):
            continue
        e = en.get(wid)
        if e and "phr" not in e and len(e) == 1:
            single_recoverable += 1
    checks = [
        ("🔴 有外部锚的 phr 已全部改成功能词性", left, 0),
        ("🔴 剩下的单词 phr 都已无外部锚可用", single_recoverable, 0),
        ("🔴 sense.pos 全是展示层认得的短码",
         sum(1 for (p,) in con.execute("SELECT DISTINCT pos FROM sense WHERE pos IS NOT NULL")
             if p not in set(POS_MAP.values())), 0),
        ("🔴 entry.pos 未被本步触碰",
         sum(1 for (p,) in con.execute("SELECT DISTINCT pos FROM entry WHERE pos IS NOT NULL")
             if p not in POS_MAP), 0),
        # ⚠️ 第一版断言"这 7 个词的**所有**义项都等于指定值" —— 写过头了：
        #    `Chabad` 有两条义项（运动名 name / 派系成员 n），后者本来就不是 phr。
        #    真正的不变量是：这 7 个词**不再有 phr 义项**。
        # ⚠️ 第二版又写错：`sum(1 for … in con.execute("SELECT count(*) …"))` 数的是**行数**，
        #    而 count(*) 永远返回一行 ⇒ 结果恒为 1，闸永远红。要取的是那一行的**值**。
        ("逐条判的那 7 个词已无 phr 义项",
         q("SELECT count(*) FROM sense s JOIN dict d ON d.id=s.word_id "
           "WHERE s.pos='phr' AND COALESCE(s.hidden,0)=0 AND d.word IN (%s)"
           % ",".join("'%s'" % k.replace("'", "''") for k in BY_HAND)), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %s (期望 %s)" % ("✅" if good else "🔴", name,
                                           f"{got:,}", f"{want:,}"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    rows, stat = plan(ro)
    for k, v in stat.most_common():
        print("   %-34s %6s" % (k, f"{v:,}"))
    print("\n■ 将改 %s 条" % f"{len(rows):,}")
    print("   去向 %s" % Counter(p for p, _ in rows).most_common())
    ro.close()
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("fix-phrase-pos", expect={"#sense": 0}) as s:
        s.executemany("UPDATE sense SET pos=? WHERE id=?", rows)
    print("\n■ 已改 %s 条" % f"{len(rows):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
