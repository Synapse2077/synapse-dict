#!/usr/bin/env python3
"""外语版读音里的两类确定缺陷。2026-08-26。

起因：阶段 8 渲染出来看见 `eau` 的读音里有 `/oː/`（来自荷兰语版）——
那是**荷兰人念这个法语词的近似音**，不是法语读音。
回头量非 fr/en 版贡献的 8,530 行，按「像不像法语音标」分：

    ① 整条就是 `?`（占位符）                1,182   ← 本脚本删
    ② 含 `?`                                  2   ← 本脚本删
    ③ 用了错字符 `ǝ`(U+01DD) 而非 `ə`(U+0259)  91   ← 本脚本**改字符，不删**
    ④ 长音符 `ː`                            276   ← **不动**，见下
    ⑤ 词重音符 `ˈ` / `ˌ`                   1,276   ← **不动**，见下
    ⑥ 其余                                5,703   ← 不动

═══ 🔴 为什么只做 ①②③ ═══
④⑤ 看起来"不像法语"（标准法语无音长对立、无词重音），但：
    · **比利时法语确有音长**（`fête` /fɛːt/），魁北克法语也有
    · `ˈ` 可能是短语重音，不一定是错
拿"标准法语没有这个"当判据，就是**用形式代替含义** ——
2026-08-26 这一天我已经在这个形状上栽了六次（见 docs/FR_PLAN.md 阶段 8 第三节）。
⇒ 只做**无论哪种法语都不成立**的那两类：`?` 不是音标；`ǝ` 不是 IPA 字符。

═══ 🔴 `?` 为什么是删不是留 ═══
其中 50 行是该词形**唯一**的读音来源，删了那个词就没音标了。
仍然删 —— `docs/FRAMEWORK.md`：**错比缺更伤权威**。
用户看到 `/?/` 比看到没有音标更糟。

用法（在 fr/ 目录下）：
    python3 -u fixes/clean_foreign_pronunciations.py          # 只报数
    python3 -u fixes/clean_foreign_pronunciations.py --apply  # 落库
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import dbtool                                   # noqa: E402
import paths                                    # noqa: E402

f = lambda n: format(n, ",")
NATIVE = ("fr-edition", "en-edition", "legacy")
QMARK = re.compile(r"[?？]")
BAD_SCHWA = "ǝ"          # ǝ LATIN SMALL LETTER TURNED E —— 不是 IPA
GOOD_SCHWA = "ə"         # ə LATIN SMALL LETTER SCHWA


def plan(con):
    """→ (要删的 id, 要改字符的 [(新值, id)])"""
    drop, fix = [], []
    for pid, wid, ipa, src, prim in con.execute(
            "SELECT id, word_id, ipa, src, is_primary FROM pronunciation"):
        if src in NATIVE or not ipa:
            continue
        if QMARK.search(ipa):
            drop.append((pid, wid, ipa, src, prim))
        elif BAD_SCHWA in ipa:
            fix.append((ipa.replace(BAD_SCHWA, GOOD_SCHWA), pid, wid, ipa, src, prim))
    return drop, fix


def gates(con, drop, fix):
    ok = True

    def g(name, bad, n):
        nonlocal ok
        print("  %s %s：%s / %s" % ("✅" if not bad else "🔴", name, f(bad), f(n)))
        if bad:
            ok = False

    # ① 只删非 fr/en 版的
    g("① 只动非 fr/en/legacy 版",
      sum(1 for r in drop + [x[1:] for x in fix] if r[3] in NATIVE), len(drop) + len(fix))
    # ② 🔴 改字符只许改这一个码位，别的一个字都不许变。
    #    判据 = **等长，且只在旧串是 ǝ 的位置不同**。
    #    第一版写的是「两边各自抹掉 ǝ/ə 后相等」，在
    #    `sɔʁ.ti də sǝ.kuʁ`（同时含正确的 ə 和错的 ǝ）上报假红 ——
    #    它把本来就正确的那个 ə 也一起抹了，两侧自然不等长。
    def only_schwa(old, new):
        if len(old) != len(new):
            return False
        return all(a == b or (a == BAD_SCHWA and b == GOOD_SCHWA)
                   for a, b in zip(old, new))
    g("② 改字符只动了 ǝ→ə（等长且只在该位置不同）",
      sum(1 for new, _p, _w, old, _s, _pr in fix if not only_schwa(old, new)), len(fix))
    # ③ 改完不许再含错字符
    g("③ 改完不含 ǝ", sum(1 for x in fix if BAD_SCHWA in x[0]), len(fix))
    # ④ 改完不许与该词形已有的行撞 UNIQUE（归一必然产生重复，上次就栽这）
    have = {(w, i, n) for w, i, n in con.execute(
        "SELECT word_id, ipa, notation FROM pronunciation")}
    nota = {p: n for p, n in con.execute("SELECT id, notation FROM pronunciation")}
    clash = sum(1 for new, pid, wid, _o, _s, _pr in fix if (wid, new, nota[pid]) in have)
    print("  ℹ️ 改完会与已有行撞 UNIQUE 的：%s（这些改成删）" % f(clash))
    # ⑤ 删掉主读音的词形要重选
    lost = {r[1] for r in drop if r[4]} | {x[2] for x in fix if x[5]}
    print("  ℹ️ 涉及主读音的词形 %s ⇒ 落库后重选" % f(len(lost)))
    return ok, clash


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    drop, fix = plan(con)
    solo = 0
    nat = set()
    for w, in con.execute("SELECT DISTINCT word_id FROM pronunciation WHERE src IN %s" % str(NATIVE)):
        nat.add(w)
    solo = sum(1 for r in drop if r[1] not in nat)
    print("■ 删 %s 行（`?` 占位符）｜ 其中 %s 行是该词形唯一来源（仍删：错比缺更伤权威）"
          % (f(len(drop)), f(solo)))
    for _p, _w, ipa, src, prim in drop[:4]:
        print("     %-10s %-8r%s" % (src, ipa[:8], "  ★主" if prim else ""))
    print("■ 改 %s 行（ǝ → ə）" % f(len(fix)))
    for new, _p, _w, old, src, prim in fix[:4]:
        print("     %-10s %-18r → %r%s" % (src, old[:18], new[:18], "  ★主" if prim else ""))

    print("\n══ 闸 ══")
    ok, clash = gates(con, drop, fix)
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 闸未过，**不写库**")
        return 1

    # 🔴 改完会撞 UNIQUE 的直接删（那说明该词形已经有正确写法的同一个音）
    have = {(w, i, n) for w, i, n in con.execute(
        "SELECT word_id, ipa, notation FROM pronunciation")}
    nota = {p: n for p, n in con.execute("SELECT id, notation FROM pronunciation")}
    upd, extra_drop = [], []
    for new, pid, wid, _o, _s, _pr in fix:
        (extra_drop if (wid, new, nota[pid]) in have else upd).append((new, pid))
    dropped = [r[0] for r in drop] + [p for _n, p in extra_drop]
    lost = {r[1] for r in drop if r[4]} | {x[2] for x in fix if x[5]}
    with dbtool.session("keep-v3-foreign-pron", expect={"#pronunciation": -len(dropped)}) as s:
        s.executemany("DELETE FROM pronunciation WHERE id=?", [(i,) for i in dropped])
        s.executemany("UPDATE pronunciation SET ipa=? WHERE id=?", upd)
        for wid in lost:                       # 重选主读音，保住「一词一主」
            if s.execute("SELECT COUNT(*) FROM pronunciation WHERE word_id=? AND is_primary=1",
                         (wid,)).fetchone()[0]:
                continue
            row = s.execute("SELECT id FROM pronunciation WHERE word_id=? "
                            "ORDER BY (notation<>'phonemic'), id LIMIT 1", (wid,)).fetchone()
            if row:
                s.execute("UPDATE pronunciation SET is_primary=1 WHERE id=?", (row[0],))
    print("✓ 写入完成（删 %s、改 %s）" % (f(len(dropped)), f(len(upd))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
