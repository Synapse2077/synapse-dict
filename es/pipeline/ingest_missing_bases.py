#!/usr/bin/env python3
"""补 8,077 个缺失的词头 —— 变形形在库里、原形查不到的那批。2026-08-20。

═══ 缺陷 ═══
    搜 zancajoso   → **查不到**（下拉只给 zancajosos）
    搜 zancajosa   → 有，写着「zancajoso 的 阴性」
    搜 acoparse    → 下拉**全空**

用户最可能查的正是**词典形**（`zancajoso`），而库里只有它的变形形。
8,077 个词头，10,867 条变形指着它们。

═══ 为什么以前发现不了 ═══
`dict.infl` 是文本列，「zancajoso 的 阴性」只是一个字符串，
**「这个原形在不在词典里」根本不是一个能查的问题**。
2026-08-20 建 `inflection` 表、有了 `base_id` 之后，这 10,867 行同时回答了「不在」。

═══ 源头确实没有这些词头（已回源确认，不是我们漏收）═══
`sublimatorio` 为例：西语版 dump 里有 `sublimatorios` / `sublimatoria` / `sublimatorias`
三个**变形页**（机器人批量生成的），词头页自己不存在。英文版整份 dump 里 0 命中。
8,264 个逐个查过两版 dump，**一个都没有**。

═══ 补什么、不补什么 ═══
补：词形、去重音形、词性、规则音标。**不补释义。**
🔴 释义不补是量出来的结论，不是偷懒：这批全是生僻/古旧单词，
   而模型盲推这一族的错误率实测卡在 **24–25%**（见 [[blind-gloss-inference-ceiling]]，
   开思考也只到 16% 且贵 13 倍）。**宁可留诚实空白，不要 1/4 是错的。**

⚠️ 代价要说清楚：这会**第一次**打破「169,762 个词头每一个都有中文」这个
   当前 100% 成立的性质。补完是 8,077 个无释义词头（占 lemma 的 4.5%）。
   换来的是这 8,077 个词从「搜不到」变成「搜得到、知道词性、知道怎么读、
   知道它有哪些变形形」。

词性怎么来：从**变形形自己的 `dict.pos` 反推**，确定性，不猜。
   8,047 个词性唯一；30 个多词性按库里既有约定拼成 `n/adj` 这种串。
音标怎么来：`b_ipa.word_to_ipa`（规则 G2P），`phonetic_src='rule'` ——
   与库里已有的 599,644 条同一个来源，不是新造一套。

═══ 闸 ═══
① 增量精确：新增行数 == 待补词头数；每一行都能被至少一条 inflection 指到
② 悬空清零：`inflection.base_id IS NULL AND hidden=0 AND base<>''` 必须降到 0
③ 不误伤：新增行的 `word` 不许与任何已有 `word` 精确相同（已验 0 冲突）
④ 变异验证

用法（在 es/ 目录下）：
    python3 pipeline/ingest_missing_bases.py            # 试算
    python3 pipeline/ingest_missing_bases.py --apply
    python3 pipeline/ingest_missing_bases.py --mutate
"""
import argparse
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import dbtool   # noqa: E402
import paths    # noqa: E402
from b_ipa import word_to_ipa      # noqa: E402
from build import unaccent         # noqa: E402  判据 import 被复刻的那份（A93）


# `build.py:277` 已裁决为**非标准词**的原形，不给它们建词头。
# 🔴 差点漏掉：`merer` 有 14 条变形指着它，判据「原形不在库里」照样命中 ——
#    但 build.py 当年是**有意**不收它的（`JUNK_BASES`），只是那套过滤
#    只作用于 `exchange`、没作用于 `infl`，所以指针一直留在文本列里没人看见。
#    ⇒ 「原形缺失」和「原形被裁决过不该有」是两回事，判据必须能分开它们。
JUNK_BASES = {"merer", "ethnographique"}

# 补完之后仍会剩下的悬空条数。**实测值**：`merer` 14 + `ethnographique` 1 = 15。
# 🔴 我第一版**猜**了 16（以为 ethnographique 有 2 条），结果变异①「少补一个词头」
#    该红没红 —— 少补造成的 16 恰好等于我猜的基线，被当成正常吞掉了。
#    A94 说的就是这个：**基线必须在动作之后量，不能在动作之前猜**。
#    猜高一条的代价不是「宽松一点」，是让整整一类回归对这道闸隐形。
BASE_DANGLING = 15


def norm_pos(raw):
    """变形形的 pos 串（可能是 'n,adj' 或 'n/v'）→ 库里的既有约定 'adj/n'。"""
    parts = set()
    for chunk in (raw or "").split(","):
        for p in chunk.split("/"):
            p = p.strip()
            if p:
                parts.add(p)
    return "/".join(sorted(parts)) or None


def plan(con, verbose=True):
    have = {w for (w,) in con.execute("SELECT word FROM dict")}
    rows = con.execute("""
        SELECT i.base, GROUP_CONCAT(DISTINCT d.pos), COUNT(*)
        FROM inflection i JOIN dict d ON d.id = i.word_id
        WHERE i.base_id IS NULL AND i.base <> '' AND COALESCE(i.hidden, 0) = 0
        GROUP BY i.base""").fetchall()
    out, c = [], Counter()
    for base, poss, n in rows:
        if base in have:
            c["🔴 已在库里，跳过"] += 1
            continue
        if base.lower() in JUNK_BASES:
            c["build.py 已裁决为非标准词，不补"] += 1
            continue
        pos = norm_pos(poss)
        ipa = None
        if " " not in base:
            try:
                ipa = (word_to_ipa(base) or "").strip("/") or None
            except Exception:
                ipa = None
        c["✅ 待补" if ipa else "✅ 待补（G2P 算不出音标）"] += 1
        out.append((base, unaccent(base), ipa, "rule" if ipa else None, pos))
    if verbose:
        print("■ 试算")
        for k, v in sorted(c.items()):
            print("     %-30s %s" % (k, format(v, ",")))
        print("     指着它们的变形行 %s 条" % format(sum(r[2] for r in rows), ","))
    return out, c


def apply(con, rows):
    con.executemany(
        "INSERT INTO dict (word, word_norm, phonetic, phonetic_src, pos, is_lemma)"
        " VALUES (?,?,?,?,?,1)", rows)
    # 把新词头接回变形层 —— 这才是「解决悬空」，插了行不接等于没做。
    #
    # ⚠️ **不要写成相关子查询** `WHERE d.word = inflection.base`：
    #    `idx_word` 建的是 `word COLLATE NOCASE`，而这里要的是**精确**匹配（二进制），
    #    索引用不上 ⇒ 109 万行每行一次全表扫，实测跑十分钟没跑完。
    #    [[query-perf-collation-traps]] 那条这次栽在反方向：不是漏写 NOCASE，
    #    是索引带了 NOCASE 而查询要精确。⇒ 映射在 Python 里建，executemany 写回。
    id_of = {}
    for i, w in con.execute("SELECT id, word FROM dict"):
        id_of.setdefault(w, i)
    upd = [(id_of[b], iid) for iid, b in con.execute(
        "SELECT id, base FROM inflection WHERE base_id IS NULL AND base<>''")
        if b in id_of]
    con.executemany("UPDATE inflection SET base_id=? WHERE id=?", upd)
    return len(rows)


def gate(con, new_words, verbose=True):
    """new_words: 本次新增的词形集合。

    ⚠️ 判据必须能认出「哪些行是这次加的」。第一版写的是
       「is_lemma=1 且 phonetic_src='rule' 且无释义无译文」—— 那会把**本来就存在**
       的旧行也算进来，负控当场报红（该绿的绿不了）。又一次尺子错，不是数据错。
    """
    q = lambda s: con.execute(s).fetchone()[0]
    bad = []
    n_dang = q("SELECT COUNT(*) FROM inflection WHERE base_id IS NULL "
               "AND base<>'' AND COALESCE(hidden,0)=0")
    if n_dang > BASE_DANGLING:
        bad.append("🔴 仍有 %s 条悬空（已接受基线 %s）"
                   % (format(n_dang, ","), BASE_DANGLING))
    pointed = {w for (w,) in con.execute(
        "SELECT DISTINCT d.word FROM dict d JOIN inflection i ON i.base_id = d.id")}
    orphan = [w for w in new_words if w not in pointed]
    if orphan:
        bad.append("🔴 有 %s 个新词头没有任何变形指着它 —— 凭空多出来的行，例：%s"
                   % (format(len(orphan), ","), orphan[:3]))
    dup = q("SELECT COUNT(*) FROM (SELECT word FROM dict GROUP BY word HAVING COUNT(*)>1)")
    if dup:
        bad.append("🔴 dict.word 出现 %s 组精确重复" % format(dup, ","))
    if verbose:
        print("■ 闸：悬空 %s（基线 %s）；孤立新行 %s；word 重复 %s"
              % (n_dang, BASE_DANGLING, len(orphan), dup))
        for b in bad:
            print("     " + b)
        if not bad:
            print("     ✅ 全部通过")
    return bad


def mutate(rows):
    """变异验证。闸盯「悬空清零 / 不凭空造行 / 不重复」，变异就打这三处。"""
    import shutil
    import tempfile
    MUT = [
        ("① 少补一个词头（应留下悬空）", lambda r: r[:-1], True),
        ("② 凭空多补一个没人指的词头",
         lambda r: r + [("__ghost__", "__ghost__", None, "rule", "n")], True),
        ("③ 补一个与已有词形重名的",
         lambda r: r + [("casa", "casa", None, "rule", "n")], True),
        ("④【负控】原样应用，不该红", lambda r: r, False),
    ]
    # ⚠️ 第一版每个用例都 `shutil.copy2` 一份 730 MB 的库 —— 四个用例跑了 10 分钟没跑完。
    #    复制一次 + savepoint 回滚就够了，闸读的是同一个连接里的状态。
    ok, cases = 0, []
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.sqlite"
        shutil.copy2(paths.DB, p)
        c = sqlite3.connect(p)
        for name, mut, want_red in MUT:
            c.execute("SAVEPOINT m")
            try:
                apply(c, mut(list(rows)))
                bad = gate(c, [r[0] for r in mut(list(rows))], verbose=False)
            finally:
                c.execute("ROLLBACK TO m")
                c.execute("RELEASE m")
            good = bool(bad) == want_red
            ok += good
            cases.append((name, ("✅ 报红" if bad else "✅ 照常绿") if good
                          else ("🔴 该红没红" if want_red else "🔴 不该红却红了")))
        c.close()
    print("\n■ 变异验证")
    for n, s in cases:
        print("     %-34s %s" % (n, s))
    print("     %d/%d" % (ok, len(cases)))
    return 0 if ok == len(cases) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows, c = plan(con)
    con.close()
    n_ipa = sum(1 for r in rows if r[2])
    n_pos = sum(1 for r in rows if r[4])
    print("■ 将新增 %s 个词头（音标 %s / 词性 %s）" % (
        format(len(rows), ","), format(n_ipa, ","), format(n_pos, ",")))
    if a.mutate:
        return mutate(rows)
    if not a.apply:
        print("\n(未加 --apply，没有写库)")
        return 0
    with dbtool.session("missing-bases", expect={
            "__rows__": len(rows), "phonetic": n_ipa, "phonetic_src": n_ipa,
            "pos": n_pos}) as s:
        s.written = apply(s.conn, rows)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    bad = gate(con, [r[0] for r in rows])
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
