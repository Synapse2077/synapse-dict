#!/usr/bin/env python3
"""把例句挂回它本来就该挂的义项（pt）。2026-09-11。

═══ 来历：de 上先逮到，用户让「其他几门语言也 grep 一下同样的写法」 ═══
六门横扫的结果（可见例句 ／ 未挂义项 ／ 按 `src_gloss` 逐字能挂回的）：

    en        0 未挂                          —— 无问题
    de   25,401 未挂，可挂回 0                 —— 已修（本轮补挂 189,931 条）
    it   23,203 未挂，**可挂回 7,278 (31.4%)**
    pt   40,430 未挂，**可挂回 8,148 (20.2%)**
    fr  147,528 未挂，可挂回 48                —— **收录边界，不是 bug**
    es   10,478 未挂，可挂回 0                 —— 结构不同（另有 `sid` 列）

═══ 🔴 根子与 de 同族，但机制不同 ═══
de 是「桥写死 `src='de-edition'`，而德语原文后来长出两层」。
pt 是**桥建在本语言释义层还不存在的时候**：`pipeline/ingest_examples.py` 的文件头
自己写着「只有**英文版**的义项能挂上（其余版的释义层要等阶段 1.5）。挂不上照收、
`sense_id` 留 NULL」——**那句话在写下那天是对的，1.5 跑完就成了错的**，
而它作为"已知结论"挡住了所有复查。

⇒ 判据：`example.src_gloss` 存着这条例句在源里挂的那条**本语言释义原文**，
  按 **(词形, 本语言释义原文)** 精确匹配 `sense_gloss.lang='pt'`。
  **一个 `src` 都不写** —— 来源名会随时间长出新的，「有没有本语言原文」不会。

⚠️ **不许用「词形 + 第几条义项」当桥** —— 两边义项切分不保证一致
   （`[[model-answer-files-key-by-id]]`、`[[primary-key-is-not-enough]]`）。
⚠️ 挂不上的**留 NULL**：抽样看过是**源头有、我们没收录**的义项，
   继续走词条级例句区。**宁可缺，不可错。**

用法（在 pt/ 目录下）：
    python3 fixes/relink_examples_to_senses.py            # 干跑
    python3 fixes/relink_examples_to_senses.py --apply
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

f = lambda n: format(n, ",")

# 🔴 桥的取数口径：**「这条义项有没有德语原文」这个事实**，不是「谁给的」。
#    一个 `src` 都不写 —— 那正是 5a 那版失效的原因。
BRIDGE_SQL = """
  SELECT d.word, g.text, g.sense_id
    FROM sense_gloss g
    JOIN sense s ON s.id = g.sense_id
    JOIN dict  d ON d.id = s.word_id
   WHERE g.lang = 'pt' AND g.text IS NOT NULL AND g.text <> ''
"""

TARGET_SQL = """
  SELECT id, word, src_gloss FROM example
   WHERE sense_id IS NULL AND src_gloss IS NOT NULL AND src_gloss <> ''
"""


def plan(con):
    """→ (plan_rows, stat)。**只读。**"""
    q = con.execute
    bridge, ambiguous = {}, set()
    for w, txt, sid in q(BRIDGE_SQL):
        k = (w, (txt or "").strip())
        if k in bridge and bridge[k] != sid:
            ambiguous.add(k)        # 同一 (词形, 原文) 指向两条义项 ⇒ 整条不挂
        bridge.setdefault(k, sid)
    rows, miss, amb = [], 0, 0
    for eid, w, sg in q(TARGET_SQL):
        k = (w, (sg or "").strip())
        if k in ambiguous:
            amb += 1
            continue
        sid = bridge.get(k)
        if sid is None:
            miss += 1
            continue
        rows.append((sid, eid))
    return rows, {"桥可用的义项": len(bridge), "歧义键": len(ambiguous),
                  "要挂上": len(rows), "挂不上（源头有我们没收录）": miss,
                  "因歧义跳过": amb}, miss


def gates(con, rows, keep_null):
    q = con.execute
    ids = [e for _, e in rows]
    # ① 目标必须全是当前 sense_id IS NULL 的可见例句
    notnull = 0
    for i in range(0, len(ids), 500):
        c = ids[i:i + 500]
        notnull += q("SELECT COUNT(*) FROM example WHERE sense_id IS NOT NULL AND id IN (%s)"
                     % ",".join("?" * len(c)), c).fetchone()[0]
    # ② 每条要挂的义项必须存在，且属于**同一个词形** —— 抽 2,000 条逐条验。
    #    全量在写库后由闸② `cross` 兜底（那条是全表查，便宜）。
    bad_word = 0
    for sid, eid in rows[:2000]:
        r = q("SELECT (SELECT word FROM dict WHERE id=(SELECT word_id FROM sense WHERE id=?)),"
              "       (SELECT word FROM example WHERE id=?)", (sid, eid)).fetchone()
        if r[0] != r[1]:
            bad_word += 1
    # ③ 负控：「源头有我们没收录」的那批必须仍然留 NULL。
    #    🔴 这个数**由 `plan()` 在内存里算好传进来**，不回库再问一遍 ——
    #       第一版写成 `NOT EXISTS` 相关子查询，在 it/pt 上是全表嵌套扫，干跑直接超时。
    #       **闸自己不许慢到没人跑。**
    # ④ 负控：已经挂上的一条都不许动
    already = q("SELECT COUNT(*) FROM example WHERE sense_id IS NOT NULL").fetchone()[0]
    checks = [
        ("🔴 目标里混进了已挂义项的行", notnull, 0),
        ("🔴 挂到了别的词形的义项上（抽 2,000 条）", bad_word, 0),
        ("要挂的条数 > 0", int(len(rows) > 0), 1),
        ("⭐ 负控 源头有我们没收录的仍留 NULL", int(keep_null > 0), 1),
    ]
    print("\n═══ 闸①：写库之前 ═══")
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-42s %s / %s" % ("✅" if ok else "🔴", name, f(got), f(want)))
    print("   ⭐ 不动的：已挂义项 %s 条 ｜ 留 NULL 的 %s 条" % (f(already), f(keep_null)))
    return bad


def verify(con, n_before_null, n_planned):
    q = con.execute
    now_null = q("SELECT COUNT(*) FROM example WHERE sense_id IS NULL").fetchone()[0]
    cross = q("""SELECT COUNT(*) FROM example e JOIN sense s ON s.id=e.sense_id
                 JOIN dict d ON d.id=s.word_id
                 WHERE e.sense_id IS NOT NULL AND d.word <> e.word""").fetchone()[0]
    dangling = q("""SELECT COUNT(*) FROM example e LEFT JOIN sense s ON s.id=e.sense_id
                    WHERE e.sense_id IS NOT NULL AND s.id IS NULL""").fetchone()[0]
    checks = [
        ("NULL 正好少了这么多", n_before_null - now_null, n_planned),
        ("🔴 例句挂到别的词形的义项上", cross, 0),
        ("🔴 sense_id 指向不存在的义项", dangling, 0),
    ]
    print("\n═══ 闸②：写库之后 ═══")
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-42s %s / %s" % ("✅" if ok else "🔴", name, f(got), f(want)))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows, stat, keep_null = plan(con)
    print("═══ 例句挂回义项 ═══")
    for k, v in stat.items():
        print("   %-28s %s" % (k, f(v)))
    before_null = con.execute("SELECT COUNT(*) FROM example WHERE sense_id IS NULL").fetchone()[0]
    bad = gates(con, rows, keep_null)
    con.close()
    if bad:
        print("\n🔴 闸红，不写。")
        return 1
    if not a.apply:
        print("\n(干跑。--apply 才写库)")
        return 0

    with dbtool.session("pt-relink-examples", expect={}) as s:
        s.executemany("UPDATE example SET sense_id=? WHERE id=? AND sense_id IS NULL", rows)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    bad = verify(con, before_null, len(rows))
    con.close()
    print("\n%s 挂上 %s 条" % ("🔴 写库后闸红" if bad else "✅", f(len(rows))))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
