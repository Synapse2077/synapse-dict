#!/usr/bin/env python3
"""B10：音标里的 X-SAMPA／乱码删掉，HTML 实体还原。it，2026-10-28。

═══ 来由 ═══
`docs/BACKLOG.md` **B10**：X-SAMPA（用 ASCII 表 IPA：`4`＝ɾ、`R`＝强 r、`_h`＝送气）混在维基各版的
`sounds.ipa` 里，fr（150 条）、ko（98 条）修过，另六门没查。2026-10-28 六门一起量：en／ja 0 条。

═══ 判据（两步，顺序不能反）═══
① **HTML 实体还原**：`&#124;` 是竖线 `|` 被转义后的残渣，而 `|` 是**合法 IPA**（短语内的小停顿，
   `ˈnãw | o.bɾiˈga.du`）。这一类是**修**不是删 —— 先还原，再走②，否则会被②当成乱码删掉。
② `BAD`：ASCII 大写字母、数字、反引号、反斜杠、下划线 —— IPA 里**一个都不会合法出现**
   （IPA 的小型大写是单独的码位：ʀ ɪ ʏ ʁ ɢ ʟ ɴ ʙ ʜ）。ko 的数字类 ∪ fr 的大写类。
   逮到的形状：X-SAMPA（`a"tSEtiko`、`IntEn"tsioːn`）／葡语版的音位记号 `R`（强 r，各地读 ʁ/h/x/r，
   **不是 IPA 字符**）／fr 版把上标变体标记拍平成的 `i_s.paɾ`、`ˈpɛ.ni_iʃ`／散文（`Dicionário Fonétic`）／
   粘上的编号 `7ˈpevera`／专名首字母大写 `Peˈru`。
   ⚠️ 必须用 Python 正则或 `GLOB`，不能 `LIKE`：`LIKE '%_%'` 的 `_` 是通配符（ko 第一版命中整库）。

═══ 删掉之后没有读音的词（照删，并逐个列出）═══
B10 的步骤②要求「删前先验删掉不会让词失去读音」。验出来**会有**，而它们剩下的那条读音本身就不是 IPA。
**印一个错的音标比不印更伤权威**（`docs/FRAMEWORK.md`）⇒ 照删，名单写进 `data/work/it/b10_ipa_orphans.txt`，
回头有正确来源（别的版／G2P）时按名单补。
录音表的 `audio.ipa` 只是录音的标注 ⇒ 录音保留，把那一格置空。

═══ it 与另三门不同：**藏不删** ═══
it 的读音表有 `hidden` 列，它自己的 `hide_junk_pronunciation.py`（08-21）对垃圾读音一律藏（可逆）。
🔴 2026-10-28 我第一版照另三门删了 28 行，回归闸 D8 当场红（6 个词的默认读音被删、没人接班）——
   ⇒ 用写前备份还原（之后无其他写入，行数正好差 28），改成**藏**，并按 it 自己的档位
   `hide_junk_pronunciation.REPICK_ORDER`（import，不另抄）在**还可见的**读音里重选默认读音。

跑（在仓库根）：
    python3 -u it/fixes/fix_ipa_xsampa.py            # 干跑
    python3 -u it/fixes/fix_ipa_xsampa.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import html
import re
import sqlite3

import dbtool
import paths
from fixes.hide_junk_pronunciation import REPICK_ORDER

f = lambda n: format(n, ",")
BAD = re.compile(r"[A-Z0-9`\\_]")
ENTITY = re.compile(r"&(#\d+|#x[0-9a-fA-F]+|[a-z]+);")


def plan(con):
    has = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    pron = con.execute("SELECT id, word_id, ipa, src FROM pronunciation "
                       "WHERE ipa IS NOT NULL AND COALESCE(hidden,0)=0").fetchall()
    unesc, dele = [], []
    for pid, wid, ipa, src in pron:
        fixed = html.unescape(ipa) if ENTITY.search(ipa) else ipa
        if fixed != ipa:
            unesc.append((pid, ipa, fixed))
        if BAD.search(fixed):
            dele.append((pid, wid, fixed, src))
    good = collections.Counter(wid for pid, wid, ipa, src in pron
                               if not BAD.search(html.unescape(ipa) if ENTITY.search(ipa) else ipa))
    orphans = sorted({wid for _p, wid, _i, _s in dele if not good[wid]})
    aud_unesc, aud_null = [], []
    if "audio" in has and "ipa" in {r[1] for r in con.execute("PRAGMA table_info(audio)")}:
        for aid, ipa in con.execute("SELECT rowid, ipa FROM audio WHERE ipa IS NOT NULL AND ipa<>''"):
            fixed = html.unescape(ipa) if ENTITY.search(ipa) else ipa
            if BAD.search(fixed):
                aud_null.append((aid, ipa))
            elif fixed != ipa:
                aud_unesc.append((aid, ipa, fixed))
    dep = "pronunciation_entry" in has
    return unesc, dele, orphans, aud_unesc, aud_null, dep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    unesc, dele, orphans, aud_unesc, aud_null, dep = plan(con)
    words = dict(con.execute("SELECT id, word FROM dict"))
    con.close()
    print("■ B10 音标清理（it）")
    print("   ① 读音行 HTML 实体还原        %6s" % f(len(unesc)))
    for pid, o, n in unesc[:5]:
        print("        %s  →  %s" % (o[:50], n[:50]))
    print("   ② 读音行藏起（不是 IPA）       %6s   按来源 %s"
          % (f(len(dele)), dict(collections.Counter(d[3] for d in dele))))
    for pid, wid, ipa, src in dele[:12]:
        print("        %-18s %-28s %s" % (words.get(wid, wid)[:18], ipa[:28], src))
    print("      删完没有读音的词            %6s" % f(len(orphans)))
    print("   ③ 录音的 ipa 实体还原         %6s ／ 不是 IPA 置空 %s" % (f(len(aud_unesc)), f(len(aud_null))))
    for aid, o in aud_null[:5]:
        print("        置空  %s" % o[:50])
    out = paths.WORK / "b10_ipa_orphans.txt" if hasattr(paths, "WORK") else None
    if not a.apply:
        print("\n（干跑。加 --apply 才写库）")
        return
    if orphans and out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join("%s\t%s\n" % (words.get(w, w), "｜".join(i for _p, ww, i, _s in dele if ww == w))
                               for w in orphans), encoding="utf-8")
        print("■ 删完没有读音的 %s 个词 → %s" % (f(len(orphans)), out))
    hide_ids = [d[0] for d in dele]
    with dbtool.session("b10-ipa-xsampa", expect={"#pronunciation": 0}) as s:
        for pid, _o, n in unesc:
            s.execute("UPDATE pronunciation SET ipa=? WHERE id=?", (n, pid))
        lost = {r[0] for r in s.execute(
            "SELECT DISTINCT word_id FROM pronunciation WHERE is_primary=1 AND id IN (%s)"
            % ",".join(map(str, hide_ids)))} if hide_ids else set()
        if hide_ids:
            s.execute("UPDATE pronunciation SET hidden=1, is_primary=0 WHERE id IN (%s)"
                      % ",".join(map(str, hide_ids)))
        repicked = 0
        for wid in lost:
            nid = s.execute("SELECT id FROM pronunciation WHERE word_id=? AND COALESCE(hidden,0)=0 "
                            "ORDER BY " + REPICK_ORDER + " LIMIT 1", (wid,)).fetchone()
            if nid:
                s.execute("UPDATE pronunciation SET is_primary=1 WHERE id=?", (nid[0],))
                repicked += 1
        print("■ 藏 %s 行；默认读音被藏的词 %s 个，重选了 %s 个（其余没有可见读音了）"
              % (f(len(hide_ids)), f(len(lost)), f(repicked)))
        for aid, _o, n in aud_unesc:
            s.execute("UPDATE audio SET ipa=? WHERE rowid=?", (n, aid))
        for aid, _o in aud_null:
            s.execute("UPDATE audio SET ipa=NULL WHERE rowid=?", (aid,))
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = plan(con)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [("读音行仍不是 IPA", len(left[1]), 0), ("读音行仍带 HTML 实体", len(left[0]), 0),
              ("录音 ipa 仍待处理", len(left[3]) + len(left[4]), 0)]
    checks.append(("有可见读音却没有唯一默认读音的词", q(
        "SELECT COUNT(*) FROM (SELECT word_id, SUM(is_primary) n FROM pronunciation "
        "WHERE COALESCE(hidden,0)=0 GROUP BY word_id HAVING n<>1)"), 0))
    red = 0
    print("\n■ 写后回核（从库里重算）")
    for name, got, want in checks:
        red += got != want
        print("   %s %-26s %6s  期望 %s" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    con.close()
    if red:
        raise SystemExit("🔴 回核 %d 条红" % red)


if __name__ == "__main__":
    main()
