#!/usr/bin/env python3
"""阶段 7 —— 词源层。**只有英文版有**，38,796 条。零模型调用。2026-09-24。

═══ 家底（全量实测，不是估计）═══
    英文版切片   63,765 个条目 ── **38,796 条有 `etymology_text`（60.8%）**
    韩文版 / 中文简 / 中文繁 / 日文版   **全是 0 条** —— 不是少，是没有
⇒ 这一层只有一个源，没有跨版背书可做。

═══ 🔴 B4 那座桥：ko 从第一天就走**宽桥**，所以它在 ko 上不会发生 ═══
`docs/BACKLOG.md` **B4**：共享脚本 `scripts/ingest_etymology.py` 的 `db_keys()`
只认「**有已出版义项**」的词条，四门各漏一批（ja +1,177 ／ it +4,449 ／ fr +919）。
`KO_PLAN` §零早就判过「**会咬**」。实测确认它会咬多少：

    带词源的 entry                    38,796
      ├ 词形有出版义项                 36,829
      └ 🔴 **词形一条 `sense` 都没有**   1,967 (5.1%)   ← 窄桥会漏掉的正是这批

那 1,967 条正是 **K4**（15,871 个只有指针义项的汉字词形）里的一部分 ——
`犬` 这类条目在出版层是空的，但它**有词条、有词源正文**。
⇒ 本脚本的桥是 **`FROM entry`**，不是 `FROM sense JOIN entry`。
   理由不是"宽一点保险"，而是**这一层本来就是词条的属性，不是义项的属性**
   （`[[criteria-from-meaning-not-form]]`：判据按含义写）。

⭐ 实测这座桥**零损失**：38,796 条全部认得到 entry，`src_ref` 一条都没对不上。

═══ 🔴 `entry_id` 直接存，不让展示层重建键 ═══
ja 在这儿栽过：服务层只取**裸词源号**去查，而库里那一列写的是 `en-edition`
⇒ **40,270 行一条到不了页面**，而入库闸、写后回核、`tsc` 全绿
（`ko/pipeline/build_v3_schema.py` 的 `etymology` DDL 注释记着这一条）。
ko 的表**有 `entry_id` 外键**，所以展示层 `JOIN` 就行，**不需要拼键**——
拼键那一步不存在，它就不可能拼错。
`edition` / `etym_no` 仍然照实存，供按版筛选用。

═══ 🔴 正文一个字节不改 ═══
`etymology.text` 存**源头原文**（含 `Etymology tree` 这类结构化片段）。
清洗/拆解属于展示层的事，在这一层做就再也回不去了
（`[[source-typo-fix-ours-not-quote]]`：引文与证据层一个字不动）。

跑（在仓库根）：
    python3 -u ko/pipeline/build_etymology.py
    python3 -u ko/pipeline/build_etymology.py --apply
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

f = lambda n: format(n, ",")
BATCH = 20000
EDITION = "en-edition"          # 与 `entry.src` 一致；展示层按它筛版
SRC = paths.KK.name


def harvest(con):
    """→ (rows, stat)。rows = (word_id, entry_id, edition, etym_no, text, src, src_ref)"""
    eref = {r[1]: (r[0], r[2], r[3]) for r in con.execute(
        "SELECT id, src_ref, word_id, etym_no FROM entry")}
    rows, stat, miss = [], collections.Counter(), []
    seen = collections.Counter()
    for line in open(paths.KK, encoding="utf-8"):
        try:
            o = json.loads(line)
        except Exception:
            stat["🔴 这一行不是 JSON"] += 1
            continue
        praw = o.get("pos")
        w = (o.get("word") or "").strip()
        if praw == "romanization" or not w:
            continue
        en_ = o.get("etymology_number")
        etym = str(en_) if en_ is not None else "0"
        k = (w, praw, etym)
        seq = seen[k]
        seen[k] += 1
        text = (o.get("etymology_text") or "").strip()
        if not text:
            stat["条目·没有词源正文"] += 1
            continue
        stat["条目·有词源正文"] += 1
        ref = "kk-ko:%s:%s:%s:%d" % (w, praw, etym, seq)
        hit = eref.get(ref)
        if hit is None:
            stat["🔴 entry 认不到（src_ref 对不上）"] += 1
            if len(miss) < 6:
                miss.append((w, ref))
            continue
        eid, wid, e_no = hit
        # 🔴 号的两个来源必须一致：dump 的 `etymology_number` 与库里的 `entry.etym_no`
        #    本来就是同一个东西（建 entry 层时从同一处取的）。**不一致就是有一边坏了**，
        #    宁可当场停也不许静默挑一个（`[[expectation-must-be-declared]]`）。
        if e_no != etym:
            stat["🔴 词源号与 entry 不一致"] += 1
            if len(miss) < 6:
                miss.append((w, "dump=%s / entry=%s" % (etym, e_no)))
            continue
        rows.append((wid, eid, EDITION, etym, text, SRC, ref))
        stat["✅ 收"] += 1
    return rows, stat, miss


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    before = con.execute("SELECT COUNT(*) FROM etymology").fetchone()[0]
    if before:
        raise SystemExit("🔴 `etymology` 已有 %s 行 —— 本脚本只负责首次建层，"
                         "重跑要先想清楚怎么处置已有的行" % f(before))
    rows, stat, miss = harvest(con)
    print("■ 词源层（源：%s）" % SRC)
    for k, v in sorted(stat.items()):
        print("   %-36s %8s" % (k, f(v)))
    for w, why in miss:
        print("      %-16s %s" % (w, why))
    print("   %-36s %8s" % ("── 要写的", f(len(rows))))

    # ── 🔴 宽桥买到了什么：逐条量，不凭"宽一点保险" ──
    pub = {r[0] for r in con.execute(
        "SELECT DISTINCT word_id FROM sense WHERE COALESCE(hidden,0)=0")}
    anys = {r[0] for r in con.execute("SELECT DISTINCT word_id FROM sense")}
    g = collections.Counter()
    for wid, *_ in rows:
        g["词形有出版义项" if wid in pub
          else ("词形只有 hidden 义项" if wid in anys
                else "🔴 词形一条 sense 都没有（窄桥会漏掉）")] += 1
    print("\n■ B4 那座桥在 ko 上会漏多少（实测）")
    for k, v in g.most_common():
        print("   %-36s %8s (%4.1f%%)" % (k, f(v), 100.0 * v / max(len(rows), 1)))
    print("   ⇒ 本脚本走 `FROM entry` 的**宽桥** ⇒ 这 %s 条不会丢"
          % f(g["🔴 词形一条 sense 都没有（窄桥会漏掉）"]))

    nword = len({r[0] for r in rows})
    lemma = con.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1").fetchone()[0]
    print("\n■ 落点：%s 条词源落在 %s 个词形上（词元 %s ⇒ %.2f%%）"
          % (f(len(rows)), f(nword), f(lemma), 100.0 * nword / lemma))
    print("   ⚠️ 这个数低是因为分母里有中文版收来的 19.5 万个词 —— "
          "它们在英文版里根本不存在，**不是我们漏抽**"
          "（`[[dont-say-source-lacks-what-we-skipped]]`：源头没写 ≠ 我们没抽）")
    en_words = con.execute(
        "SELECT COUNT(DISTINCT d.id) FROM dict d JOIN entry e ON e.word_id=d.id "
        "WHERE e.src='en-edition'").fetchone()[0]
    print("   ⇒ 只看**英文版收来的** %s 个词形：覆盖 %.2f%%"
          % (f(en_words), 100.0 * nword / max(en_words, 1)))
    con.close()

    if not a.apply:
        print("\n（这是 dry 跑。加 --apply 才写库）")
        return

    with dbtool.session(
            "ko-build-etymology",
            expect={"#etymology": len(rows)},
            invalidates=[
                "🔴 空白页判据（`ko/pipeline/coverage.py`）**还没算进词源层** —— "
                "文件头写着「那一层建完要再加一条」。加了之后空白页基线会降，"
                "**那不是修好了，是口径变了**，改 R1 基线时必须写明",
                "🔴 展示层（阶段 9）：词源用 `etymology.entry_id` **JOIN**，"
                "不要拿 `edition`＋`etym_no` 拼键 —— ja 正是在拼键那一步把 40,270 行"
                "全挡在页面外，而三层闸全绿",
                "阶段 8 的闸：要有一条锁住「词源层走的是宽桥」——"
                "即『有词源正文而没有 sense 的词条，词源仍然在库里』",
            ]) as s:
        for i in range(0, len(rows), BATCH):
            s.executemany(
                "INSERT INTO etymology (word_id, entry_id, edition, etym_no, text,"
                " src, src_ref) VALUES (?,?,?,?,?,?,?)", rows[i:i + BATCH])

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    print("\n■ 写后回核（从库里重算）")
    red = 0
    checks = [
        ("etymology 行数", q("SELECT COUNT(*) FROM etymology"), len(rows)),
        ("🔴 entry_id 认不到 entry 的行",
         q("SELECT COUNT(*) FROM etymology t WHERE NOT EXISTS"
           "(SELECT 1 FROM entry e WHERE e.id=t.entry_id)"), 0),
        ("🔴 word_id 认不到 dict 的行",
         q("SELECT COUNT(*) FROM etymology t WHERE NOT EXISTS"
           "(SELECT 1 FROM dict d WHERE d.id=t.word_id)"), 0),
        ("🔴 正文是空的行", q("SELECT COUNT(*) FROM etymology WHERE TRIM(text)=''"), 0),
        ("🔴 `edition` 与 `entry.src` 对不上的行",
         q("SELECT COUNT(*) FROM etymology t JOIN entry e ON e.id=t.entry_id "
           "WHERE t.edition <> e.src"), 0),
        ("🔴 `etym_no` 与 `entry.etym_no` 对不上的行",
         q("SELECT COUNT(*) FROM etymology t JOIN entry e ON e.id=t.entry_id "
           "WHERE t.etym_no <> e.etym_no"), 0),
        ("⭐ 宽桥保住的：没有 sense 却有词源的行",
         q("SELECT COUNT(*) FROM etymology t WHERE NOT EXISTS"
           "(SELECT 1 FROM sense s WHERE s.word_id=t.word_id)"),
         g["🔴 词形一条 sense 都没有（窄桥会漏掉）"]),
    ]
    for name, got, want in checks:
        mark = "✅" if got == want else "🔴"
        red += got != want
        print("   %s %-38s %9s  期望 %9s" % (mark, name, f(got), f(want)))
    print("\n■ 抽样（人眼看）")
    for w, no, t in con.execute(
            "SELECT d.word, t.etym_no, t.text FROM etymology t "
            "JOIN dict d ON d.id=t.word_id ORDER BY RANDOM() LIMIT 6"):
        print("   %-12s #%s  %s" % (w, no, t.replace("\n", " ⏎ ")[:86]))
    con.close()
    if red:
        raise SystemExit("🔴 回核 %d 条红" % red)


if __name__ == "__main__":
    main()
