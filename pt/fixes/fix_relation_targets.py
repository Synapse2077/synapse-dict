#!/usr/bin/env python3
"""渲染评审读出来的两族关系层残渣。2026-08-31。

═══ 怎么发现的 ═══
把 pt 的 38 个词（按形状取样）用 `render-dump` 导成用户真正看到的样子逐条读，
在 `pinta` 那一页上看见：

    近义 pénis (Portugal) / pênis 、falo 、… 、pistola 、piupiu 、pinta … 共 62
                                                                  ^^^^^ 自己

族A **关系指向自己**（669 条）：`pinta` 的近义词里有 `pinta`、`teu → teu`、`BOPE → BOPE`。
      零信息，而且**我 08-31 刚把 alt_of 接进渲染**，读者从此会在 `teu` 页上看见「异体 → teu」。
      按 kind：synonym 542 ／ alt_of 103 ／ coordinate 18 ／ antonym 6。
族B **源头把两种拼写塞在一格**（331 条）：`Amsterdã /Amesterdão`、`suflé /suflê`、
      `Grande Prémio /Grande Prêmio /Grand Prix`（巴葡/欧葡两套正字法）。
      后果有两层：这个串**在 dict 里永远查不到** ⇒ 渲染成不可点的死字；
      读者看到的是一个怪串而不是两个词。**拆开后 265/331 每一段都能对上 dict。**

═══ 判据 ═══
族A：`target` 与词头**精确相等**。
  🔴 **不许用归一比较** —— `Primavera → primavera` 是真信息（大小写异体），
     归一之后会被当成自指误杀（`[[criteria-from-meaning-not-form]]` 在葡语上的老账：
     变音符和大小写在这门语言里是区别性的）。
族B：`target` 含 `/`。按 `/` 切、去空白、丢空段；**每段单独存一条**，原串隐掉。
  ⚠️ 14 条切完仍对不上 dict（`mil quadrilhões//mil quatrilhões`），**照样切** ——
     切开之后至少是两个词形，比一个怪串强；对不上只是我们没收这个词。

⚠️ 两族都用 `hidden`，不删行（照 `example`/`sense` 的先例，一条 SQL 可全撤）。

用法（在 pt/ 目录下）：
    python3 fixes/fix_relation_targets.py
    python3 fixes/fix_relation_targets.py --apply
"""
import argparse
import collections
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

SRC = "split-target"

# ⭐ 负控：这些**不许**被判成自指。全部来自葡语里真实存在的大小写/变音符异体。
NEG_SELF = [("Primavera", "primavera"), ("primavera", "Primavera"),
            ("Óscar", "óscar"), ("pinta", "pinto")]


def is_self(word, target):
    """判据：**精确相等**才算自指。不归一。"""
    return word == target


def split_target(t):
    """`A /B /C` → [A, B, C]；不含斜杠返回 None。"""
    if "/" not in t:
        return None
    parts = [x.strip() for x in t.split("/") if x.strip()]
    return parts if len(parts) > 1 else None


def plan(con):
    selfs, splits = [], []
    for i, wid, sid, kind, target, src, w in con.execute(
            "SELECT r.id, r.word_id, r.sense_id, r.kind, r.target, r.src, d.word "
            "  FROM sense_relation r JOIN dict d ON d.id=r.word_id "
            " WHERE COALESCE(r.hidden,0)=0"):
        if is_self(w, target):
            selfs.append((i, w, kind, target))
        elif split_target(target):
            splits.append((i, wid, sid, kind, target, src, w))
    return selfs, splits


def main(a):
    print("■ 负控：%d 对真异体，必须一对都判不成自指" % len(NEG_SELF))
    bad = [p for p in NEG_SELF if is_self(*p)]
    for w, t in NEG_SELF:
        print("   %s %s → %s" % ("🔴 被误判" if is_self(w, t) else "✅", w, t))
    if bad:
        return 1
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = {w for (w,) in con.execute("SELECT DISTINCT word FROM dict")}
    selfs, splits = plan(con)
    f = lambda n: format(n, ",")
    print("\n■ 族A 关系指向自己：%s 条  %s"
          % (f(len(selfs)), dict(collections.Counter(x[2] for x in selfs).most_common())))
    for _i, w, k, t in selfs[:5]:
        print("   %-18s %-10s → %s" % (w[:18], k, t[:24]))
    print("\n■ 族B 一格塞多个拼写：%s 条" % f(len(splits)))
    ok = sum(1 for x in splits if all(p in words for p in split_target(x[4])))
    print("   拆开后每段都能对上 dict 的：%s" % f(ok))
    for _i, _wid, _sid, _k, t, _s, _w in splits[:5]:
        print("   %-38s → %s" % (t[:38], " ＋ ".join(split_target(t))))
    # 新行（去掉与已有行重复的，UNIQUE(word_id, sense_id, kind, target) 会拦）
    have = {(wid, sid, k, t) for wid, sid, k, t in con.execute(
        "SELECT word_id, sense_id, kind, target FROM sense_relation")}
    new, seen = [], set()
    for _i, wid, sid, kind, t, src, w in splits:
        for p in split_target(t):
            key = (wid, sid, kind, p)
            if p == w or key in have or key in seen:
                continue
            seen.add(key)
            new.append((wid, sid, kind, p, src, "%s:%d:%s" % (SRC, wid, p)))
    print("   拆出新关系行：%s（已存在或与词头相同的不重复插）" % f(len(new)))
    con.close()
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("fix-pt-relation-targets",
                        expect={"#sense_relation": len(new)}) as s:
        s.executemany("UPDATE sense_relation SET hidden=1 WHERE id=?",
                      [(i,) for i, *_ in selfs])
        s.executemany("UPDATE sense_relation SET hidden=1 WHERE id=?",
                      [(x[0],) for x in splits])
        s.executemany(
            "INSERT INTO sense_relation(word_id, sense_id, kind, target, src, src_ref, hidden) "
            "VALUES(?,?,?,?,?,?,0)", new)
    print("\n✓ 族A 隐 %s ／ 族B 隐 %s、拆出 %s"
          % (f(len(selfs)), f(len(splits)), f(len(new))))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    sys.exit(main(ap.parse_args()))
