#!/usr/bin/env python3
"""老词典层被数字实体的分号拆成两半的义项 —— 并回一条。en，2026-11-02（EN_PLAN §16.7②）。

═══ 缺陷 ═══
ECDICT 原文 `[地名] "飞&#xe193;川" ( 日 )`（`legacy_gloss`，`Hida-gawa`／`Hida-sanmyaku`）。
`build_legacy_sense.split_top` 按 `;` 切，实体自带的分号把它切成两条义项：
    rank 0  `"飞&#xe193`      ← 页面上是半截乱码
    rank 1  `川" ( 日 )`
根因在生成器（已改：`decode_num_entities` 先解码再切）。这个脚本把**已落库**的两行改成
生成器现在会产出的样子 —— 修生成侧不修已落库的行，修复就停在一半（`[[it-backlog-cleared]]`）。

═══ 怎么改 ═══
· 证据层 `sense_src`：前半那行的 `text` ＝ 生成器重算出来的整条（实体解码后的原文，私用区字照存，不替换）；
  后半那行连同它的义项删掉。
· 出版层 `sense_gloss`：同一条，再过 `fix_ecdict_garbled.MAP`（私用区 U+E193 → 驒）。
· 只认「生成器重算结果与库里现状对得上」的词：现状必须**恰好**是旧切法的两条、后半那条义项上除了
  `sense_src`/`sense_gloss` 什么都没挂 —— 任何一条不成立就停，不猜。

跑（在仓库根）：
    python3 -u en/fixes/fix_entity_split.py            # 干跑
    python3 -u en/fixes/fix_entity_split.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import sqlite3

import dbtool
import paths
import build_legacy_sense as B
from fix_ecdict_garbled import MAP

# 挂在义项上的表：后半那条义项上只许有这两张表的行
ALLOWED_ON_TAIL = {"sense_src", "sense_gloss"}


def plan(con):
    """→ [(word, keep_sid, drop_sid, 证据层新文本, 出版层新文本)]"""
    fk = [t for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
          if "sense_id" in [r[1] for r in con.execute("PRAGMA table_info(%s)" % t)]]
    out = []
    for wid, word, text in con.execute(
            "SELECT d.id, d.word, l.text FROM legacy_gloss l JOIN dict d ON d.id=l.word_id "
            "WHERE instr(l.text, '&#') > 0"):
        new = [g for _p, _m, g in B.parse(text)[0]]
        old = [g for _p, _m, g in B.parse(text.replace("&#", "\0"))[0]]   # 不解码时的切法
        old = [g.replace("\0", "&#") for g in old]
        have = [(sid, t) for sid, t in con.execute(
            "SELECT s.id, ss.text FROM sense s JOIN sense_src ss ON ss.sense_id=s.id "
            "WHERE s.word_id=? AND ss.src='ecdict' ORDER BY s.rank, s.id", (wid,))]
        if [t for _s, t in have] != old or len(old) != len(new) + 1 or len(new) != 1:
            raise SystemExit("🔴 %s：库里现状 %r 与旧切法 %r／新切法 %r 对不上 —— 不猜，停"
                             % (word, [t for _s, t in have], old, new))
        keep, drop = have[0][0], have[1][0]
        extra = {t for t in fk if t not in ALLOWED_ON_TAIL
                 and con.execute("SELECT 1 FROM %s WHERE sense_id=?" % t, (drop,)).fetchone()}
        if extra:
            raise SystemExit("🔴 %s：后半那条义项 %d 上还挂着 %s —— 不能直接删" % (word, drop, sorted(extra)))
        out.append((word, keep, drop, new[0], "".join(MAP.get(c, c) for c in new[0])))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    todo = plan(con)
    con.close()
    for word, keep, drop, src, pub in todo:
        print("   %-16s 留 %d ／ 删 %d\n      证据层 %r\n      出版层 %r" % (word, keep, drop, src, pub))
    print("■ 要并 %d 个词（各删 1 条义项）" % len(todo))
    if not a.apply or not todo:
        return
    n = len(todo)
    # 删行 ⇒ 这三张表每一列的非空计数都跟着变：表的行数写精确值，列逐个声明（None＝允许变、不校验数值）
    exp = {"#sense": -n, "#sense_src": -n, "#sense_gloss": -n}
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    for tb in ("sense", "sense_src", "sense_gloss"):
        for (col,) in con.execute("SELECT name FROM pragma_table_info(?)", (tb,)):
            exp["%s.%s" % (tb, col)] = None
    con.close()
    # 小改动模式：只动 6 行，写前把前像存进撤销文件，不复制整个 en 库
    with dbtool.session("en-fix-entity-split", expect=exp, small=20) as s:
        for _w, keep, drop, src, pub in todo:
            s.execute("UPDATE sense_src SET text=? WHERE sense_id=? AND src='ecdict'", (src, keep))
            s.execute("UPDATE sense_gloss SET text=? WHERE sense_id=? AND lang='zh' AND src='ecdict'", (pub, keep))
            s.execute("DELETE FROM sense_gloss WHERE sense_id=?", (drop,))
            s.execute("DELETE FROM sense_src WHERE sense_id=?", (drop,))
            s.execute("DELETE FROM sense WHERE id=?", (drop,))
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = con.execute("SELECT COUNT(*) FROM sense_src WHERE instr(text, '&#') > 0").fetchone()[0]
    print("■ 写后回核：证据层仍带数字实体 %d 行（期望 0）" % left)
    if left:
        raise SystemExit("🔴 回核红")


if __name__ == "__main__":
    main()
