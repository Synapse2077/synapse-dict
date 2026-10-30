#!/usr/bin/env python3
"""B10：音标里的 X-SAMPA／乱码删掉，HTML 实体还原。es，2026-10-28。

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
**印一个错的音标比不印更伤权威**（`docs/FRAMEWORK.md`）⇒ 照删，名单写进 `data/work/es/b10_ipa_orphans.txt`，
回头有正确来源（别的版／G2P）时按名单补。
录音表的 `audio.ipa` 只是录音的标注 ⇒ 录音保留，把那一格置空。

跑（在仓库根）：
    python3 -u es/fixes/fix_ipa_xsampa.py            # 干跑
    python3 -u es/fixes/fix_ipa_xsampa.py --apply
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

f = lambda n: format(n, ",")
BAD = re.compile(r"[A-Z0-9`\\_]")
ENTITY = re.compile(r"&(#\d+|#x[0-9a-fA-F]+|[a-z]+);")


def plan(con):
    has = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    pron = con.execute("SELECT id, word_id, ipa, src FROM pronunciation WHERE ipa IS NOT NULL").fetchall()
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
    # ④ 老扁平列 `dict.phonetic`：展示层仍在读（`spanish.ts` 词条行与变位指向的原形）。
    #    第一版漏了它，回归闸加断言时才量出 4 条（`PDF417 → ˈpdf417`、`COVID-19 → koˈbid ˈ19`，
    #    西语版给的）。源头原文在 `phonetic_raw` 里一字不动，只清出版列。
    dict_null = [(wid, ipa) for wid, ipa in con.execute(
        "SELECT id, phonetic FROM dict WHERE phonetic IS NOT NULL AND phonetic<>''")
        if BAD.search(html.unescape(ipa) if ENTITY.search(ipa) else ipa)]
    return unesc, dele, orphans, aud_unesc, aud_null, dep, dict_null


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    unesc, dele, orphans, aud_unesc, aud_null, dep, dict_null = plan(con)
    words = dict(con.execute("SELECT id, word FROM dict"))
    con.close()
    print("■ B10 音标清理（es）")
    print("   ① 读音行 HTML 实体还原        %6s" % f(len(unesc)))
    for pid, o, n in unesc[:5]:
        print("        %s  →  %s" % (o[:50], n[:50]))
    print("   ② 读音行删除（不是 IPA）       %6s   按来源 %s"
          % (f(len(dele)), dict(collections.Counter(d[3] for d in dele))))
    for pid, wid, ipa, src in dele[:12]:
        print("        %-18s %-28s %s" % (words.get(wid, wid)[:18], ipa[:28], src))
    print("      删完没有读音的词            %6s" % f(len(orphans)))
    print("   ③ 录音的 ipa 实体还原         %6s ／ 不是 IPA 置空 %s" % (f(len(aud_unesc)), f(len(aud_null))))
    for aid, o in aud_null[:5]:
        print("        置空  %s" % o[:50])
    print("   ④ dict.phonetic 不是 IPA 置空   %6s" % f(len(dict_null)))
    for wid, o in dict_null[:8]:
        print("        %-18s %s" % (words.get(wid, wid)[:18], o[:40]))
    out =paths.WORK / "b10_ipa_orphans.txt" if hasattr(paths, "WORK") else None
    if not a.apply:
        print("\n（干跑。加 --apply 才写库）")
        return
    if orphans and out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join("%s\t%s\n" % (words.get(w, w), "｜".join(i for _p, ww, i, _s in dele if ww == w))
                               for w in orphans), encoding="utf-8")
        print("■ 删完没有读音的 %s 个词 → %s" % (f(len(orphans)), out))
    exp = {"#pronunciation": -len(dele)}
    if dict_null:
        exp.update(phonetic=-len(dict_null), phonetic_src=None)
    with dbtool.session("b10-ipa-xsampa", expect=exp) as s:
        for pid, _o, n in unesc:
            s.execute("UPDATE pronunciation SET ipa=? WHERE id=?", (n, pid))
        for pid, *_ in dele:
            if dep:
                s.execute("DELETE FROM pronunciation_entry WHERE pronunciation_id=?", (pid,))
            s.execute("DELETE FROM pronunciation WHERE id=?", (pid,))
        for aid, _o, n in aud_unesc:
            s.execute("UPDATE audio SET ipa=? WHERE rowid=?", (n, aid))
        for aid, _o in aud_null:
            s.execute("UPDATE audio SET ipa=NULL WHERE rowid=?", (aid,))
        for wid, _o in dict_null:
            s.execute("UPDATE dict SET phonetic=NULL, phonetic_src=NULL WHERE id=?", (wid,))
    con =sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = plan(con)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [("读音行仍不是 IPA", len(left[1]), 0), ("读音行仍带 HTML 实体", len(left[0]), 0),
              ("录音 ipa 仍待处理", len(left[3]) + len(left[4]), 0),
              ("dict.phonetic 仍不是 IPA", len(left[6]), 0),
              ("phonetic 空而 phonetic_src 有值", q("SELECT COUNT(*) FROM dict WHERE phonetic IS NULL "
                                                  "AND phonetic_src IS NOT NULL"), 0)]
    if dep:
        checks.append(("悬空的 pronunciation_entry", q("SELECT COUNT(*) FROM pronunciation_entry pe "
                       "WHERE NOT EXISTS (SELECT 1 FROM pronunciation p WHERE p.id=pe.pronunciation_id)"), 0))
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
