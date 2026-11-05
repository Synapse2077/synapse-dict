#!/usr/bin/env python3
"""K14＋K29：关系边的身份 —— 谁写的（`writer`）、源头第几个（`src_ref` 唯一）。ko，2026-11-03。

═══ 缺陷 ═══
K14 `sense_relation.src` 存的是「哪一版 dump」，而往这张表写行的脚本有 **8 个**（账上写的是 2 个），
    填同一批版名 ⇒ 「例句标签那一支收了多少条边」只能靠 `src_ref` 的形状去猜。
K29 `src_ref` 不唯一：一个指针义项对多个目标时几条边共用 `…#ptr:0`（9 组），
    K33 那一支一行「例句」拆出的几条边共用 `ko-example:<id>#k33`（250 组）⇒ 追不回是源头第几个。

═══ 做法 ═══
① 加列 `writer`，按下面的判据回填既有行（**一次性**：此后每个写入方在 INSERT 里自己写，见 `relation_writers`）。
② 多目标指针：组内按 id 序（＝插入序＝源头序），第 1 条不动、第 k 条（k≥1）末尾加 `:k` —— 与改过的生成器同形。
   K33：一律改成 `#k33:<序号>`（与 K11/K15 的 `#k11:0` 同形）。

═══ 回填判据：形状 ＋ id 段 —— 两个写入方形状一样时要两个信号 ═══
`topup_relations_new_words` 用的就是 `build_relation_layer.scan()`，**形状一模一样**，只能靠 id 段分：
id 序显示建库那一支止于 576,804，之后依次是 fix_meta_gloss／harvest／topup（638,474–642,310）／其余四支。
⇒ 第二个信号：topup 那段的边**落在「当时的新词」上**（`topup_relations_new_words.NEW_WORDS_SQL`）。
   实测 3,529 行里 3,505 行是；其余 24 行的词形后来收了日文版释义（有了 `ja-edition` 证据层），
   所以今天不再满足「没有证据层」—— 这一类本脚本逐条断言，**多一条说不清的就停机**。
③ 写完拿建库抽取器重扫源头，断言补了序号的指针边的 `src_ref` 与它现在的产出逐条一致。

跑（在仓库根）：
    python3 -u ko/fixes/fix_k14_k29_relation_identity.py            # 干跑
    python3 -u ko/fixes/fix_k14_k29_relation_identity.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import argparse
import collections
import sqlite3

import dbtool
import paths
import relation_writers as RW
from topup_relations_new_words import NEW_WORDS_SQL

f = lambda n: format(n, ",")

BUILD_LAST = 576804                 # 建库那一支的最后一行
TOPUP = (638474, 642310)            # 补新词那一支的 id 段


def classify(con):
    """→ {id: writer}；判据见文件头。说不清的行抛错。"""
    out = {}
    for i, ref in con.execute("SELECT id, src_ref FROM sense_relation"):
        if ref.endswith("#k33") or "#k33:" in ref:
            w = "reclass_nonexamples"
        elif "#k11:" in ref:
            w = "intake_word_formation"
        elif "#k15:" in ref:
            w = "intake_idiom_components"
        elif "#alt_hanja:" in ref:
            w = "backfill_alt_hanja"
        elif "#hanja:" in ref:
            w = "fix_meta_gloss"
        elif ":rel:" in ref and "#" not in ref:
            w = "harvest_relations_from_examples"
        elif TOPUP[0] <= i <= TOPUP[1]:
            w = "topup_relations_new_words"
        elif i <= BUILD_LAST:
            w = "build_relation_layer"
        else:
            raise SystemExit("🔴 id=%d `%s` 认不出写入方" % (i, ref))
        out[i] = w
    return out


def check_signals(con, wr):
    """第二个信号：各写入方的 id 段互不交叉；topup 那段的边落在「当时的新词」上。→ 说不清的行数"""
    span = collections.defaultdict(list)
    for i, w in wr.items():
        span[w].append(i)
    bad = 0
    for w, ids in span.items():
        print("   %-34s %9s 行  id %s–%s" % (w, f(len(ids)), f(min(ids)), f(max(ids))))
    order = sorted(span, key=lambda w: min(span[w]))
    for a, b in zip(order, order[1:]):
        if max(span[a]) > min(span[b]):
            print("   🔴 %s 与 %s 的 id 段交叉" % (a, b))
            bad += 1
    new = {r[0] for r in con.execute(NEW_WORDS_SQL)}
    ja = {r[0] for r in con.execute("SELECT DISTINCT word_id FROM sense_src WHERE src='ja-edition'")}
    off = [(i, wid) for i, wid in con.execute(
        "SELECT id, word_id FROM sense_relation WHERE id BETWEEN ? AND ?", TOPUP) if wid not in new]
    late = [x for x in off if x[1] in ja]
    print("   topup 段：%s 行，落在当时新词以外的 %s 行，其中后来收了日文版释义的 %s 行"
          % (f(len(span["topup_relations_new_words"])), f(len(off)), f(len(late))))
    return bad + len(off) - len(late)


def renumber(con):
    """→ [(新 src_ref, id)]：多目标指针第 k 条加 `:k`；K33 一律 `#k33:<序号>`。"""
    groups = collections.defaultdict(list)
    for i, ref in con.execute("SELECT id, src_ref FROM sense_relation ORDER BY id"):
        groups[ref].append(i)
    out = []
    for ref, ids in groups.items():
        if ref.endswith("#k33"):
            out += [("%s:%d" % (ref, k), i) for k, i in enumerate(ids)]
        elif len(ids) > 1 and "#ptr:" in ref:
            out += [("%s:%d" % (ref, k), i) for k, i in enumerate(ids) if k]
    return out


def verify_against_extractor(con, ids):
    """补了序号的指针边，拿建库抽取器重扫源头比 `src_ref` —— 序号是不是「源头第几个」。→ 对不上的行数"""
    from build_relation_layer import scan
    indict = {r[1]: r[0] for r in con.execute("SELECT id, word FROM dict")}
    inentry = {r[1]: r[0] for r in con.execute("SELECT id, src_ref FROM entry")}
    sense_of = {(w, e, r - 1): s for w, e, r, s in con.execute(
        "SELECT word_id, entry_id, rank, id FROM sense")}
    rows, _stat = scan(indict, inentry, sense_of)
    want = {(r[0], r[2], r[3]): r[6] for r in rows}
    bad = 0
    q = "SELECT word_id, kind, target, src_ref FROM sense_relation WHERE id IN (%s)" % ",".join("?" * len(ids))
    for wid, kind, tgt, ref in con.execute(q, ids):
        got = want.get((wid, kind, tgt))
        ok = got == ref
        bad += not ok
        print("      %s %-44s 抽取器给 %s" % ("✓" if ok else "🔴", ref, got))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    has_col = "writer" in {c[1] for c in con.execute("PRAGMA table_info(sense_relation)")}
    total = con.execute("SELECT COUNT(*) FROM sense_relation").fetchone()[0]
    wr = classify(con)
    assert set(wr.values()) <= set(RW.WRITERS), set(wr.values()) - set(RW.WRITERS)
    print("■ 写入方回填（%s 行）" % f(total))
    unexplained = check_signals(con, wr)
    ren = renumber(con)
    ptr = [i for r, i in ren if "#ptr:" in r]
    print("■ src_ref 补序号：%s 行（K33 %s／多目标指针 %s）"
          % (f(len(ren)), f(len(ren) - len(ptr)), f(len(ptr))))
    con.close()
    if unexplained:
        raise SystemExit("🔴 %d 行的写入方第二个信号对不上，逐条看过再写" % unexplained)
    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return

    with dbtool.session("ko-k14-k29-relation-identity",
                        expect={"sense_relation.writer": total, "__rows__": 0},
                        invalidates=[]) as s:
        if not has_col:
            s.execute("ALTER TABLE sense_relation ADD COLUMN writer TEXT")
        s.executemany("UPDATE sense_relation SET writer=? WHERE id=?",
                      [(w, i) for i, w in wr.items()])
        s.executemany("UPDATE sense_relation SET src_ref=? WHERE id=?", ren)

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("行数没变", q("SELECT COUNT(*) FROM sense_relation"), total),
        ("writer 为空", q("SELECT COUNT(*) FROM sense_relation WHERE writer IS NULL"), 0),
        ("writer 不在登记表", q("SELECT COUNT(*) FROM sense_relation WHERE writer NOT IN (%s)"
                              % ",".join("'%s'" % w for w in RW.WRITERS)), 0),
        ("src_ref 重复的组", q("SELECT COUNT(*) FROM (SELECT 1 FROM sense_relation"
                             " GROUP BY src_ref HAVING COUNT(*)>1)"), 0),
        ("还是旧形状 `#k33` 结尾", q("SELECT COUNT(*) FROM sense_relation WHERE src_ref LIKE '%#k33'"), 0),
    ]
    red = 0
    for name, got, want in checks:
        red += got != want
        print("   %s %-24s %s（期望 %s）" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    print("■ 多目标指针的序号 vs 建库抽取器重扫源头（%d 行）" % len(ptr))
    red += verify_against_extractor(con, ptr)
    if red:
        raise SystemExit("🔴 回核红")


if __name__ == "__main__":
    main()
