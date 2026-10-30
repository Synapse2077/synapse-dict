#!/usr/bin/env python3
"""B10：音标里的 X-SAMPA／乱码删掉，录音标注的双重定界符还原。fr，2026-10-29。

═══ 来由 ═══
`docs/BACKLOG.md` **B10**。fr 是第一个修 X-SAMPA 的（2026-08-25，150 条），但当时的判据（回归闸 A5
`_XSAMPA`）只查**大写**、只查**读音表** ⇒ 2026-10-29 用十门统一判据回扫，fr 还剩：
  读音表 5 行：`pain de poisson → pron2`（模板参数名）、`filles de pute → fij.d_m9_"ˈpyt_m`、
             `Loir-et-Cher → lwa.ʁ_̌e.ʃɛʁ`（上标变体被拍平成 `_`）、`absenter → s_ap.sɑ̃.te`（el 版）
  录音标注 59 格（`audio.ipa`，页面印成「对应读音 …」）——见下。

═══ 判据（顺序不能反）═══
① **HTML 实体还原**（`&#124;` → `|`，`|` 是合法 IPA）。
② **录音标注的双重定界符还原**：fr 版录音标注一律带方括号存（`[a.kœj]`，4.1 万格都这样），
   其中 37 格里面又套了一层 fr 版自己的音位定界符 `\…\`（`[\sɔ.mɛʁ\]`）—— **内容是对的**，
   去掉反斜杠就是 `[sɔ.mɛʁ]`。这一类是**修**不是删，必须先于③，否则会被③当乱码清掉。
③ `BAD`：ASCII 大写、数字、反引号、反斜杠、下划线 ∪ HTML 实体 —— 与 es/it/pt/de/ko/ru 同一份。
   录音标注里剩下的：占位符 `[IPA]`／`[API]`、录音地点 `[France (Paris)]`、别的词 `[Listãburg]`、
   拍平的 `[lwa.ʁ_̌e.ʃɛʁ]`、字母名 `[vi.ta.min‿A]` ⇒ **置空那一格，录音保留**。
   读音行 ⇒ 删（fr 读音表没有 hidden 列；5 行都不是主音标，删前验过每个词另有读音）。

跑（在仓库根）：
    python3 -u fr/fixes/fix_ipa_xsampa.py            # 干跑
    python3 -u fr/fixes/fix_ipa_xsampa.py --apply
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
DOUBLE_DELIM = re.compile(r"^\[\\(.*)\\\]$")


def is_bad(ipa):
    return bool(ipa) and bool(BAD.search(ipa) or ENTITY.search(ipa))


def repair_audio(ipa):
    """录音标注 → 修好的串（①②），不需要修就原样返回。"""
    fixed = html.unescape(ipa) if ENTITY.search(ipa) else ipa
    m = DOUBLE_DELIM.match(fixed)
    return "[%s]" % m.group(1) if m else fixed


def plan(con):
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
    aud_fix, aud_null = [], []
    for aid, ipa in con.execute("SELECT id, ipa FROM audio WHERE ipa IS NOT NULL AND ipa<>''"):
        fixed = repair_audio(ipa)
        if is_bad(fixed):
            aud_null.append((aid, ipa))
        elif fixed != ipa:
            aud_fix.append((aid, ipa, fixed))
    return unesc, dele, orphans, aud_fix, aud_null


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    unesc, dele, orphans, aud_fix, aud_null = plan(con)
    words = dict(con.execute("SELECT id, word FROM dict"))
    con.close()
    print("■ B10 音标清理（fr）")
    print("   ① 读音行 HTML 实体还原        %6s" % f(len(unesc)))
    print("   ③ 读音行删除（不是 IPA）       %6s   按来源 %s"
          % (f(len(dele)), dict(collections.Counter(d[3] for d in dele))))
    for pid, wid, ipa, src in dele:
        print("        %-18s %-28s %s" % (words.get(wid, wid)[:18], ipa[:28], src))
    print("      删完没有读音的词            %6s" % f(len(orphans)))
    print("   ② 录音标注还原（双重定界符/实体） %6s" % f(len(aud_fix)))
    for aid, o, n in aud_fix[:5]:
        print("        %s  →  %s" % (o[:40], n[:40]))
    print("   ③ 录音标注不是 IPA 置空         %6s   %s"
          % (f(len(aud_null)), dict(collections.Counter(o for _a, o in aud_null).most_common(8))))
    if not a.apply:
        print("\n（干跑。加 --apply 才写库）")
        return
    if orphans:
        out = paths.WORK / "b10_ipa_orphans.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join("%s\t%s\n" % (words.get(w, w), "｜".join(i for _p, ww, i, _s in dele if ww == w))
                               for w in orphans), encoding="utf-8")
        print("■ 删完没有读音的 %s 个词 → %s" % (f(len(orphans)), out))
    with dbtool.session("b10-ipa-xsampa", expect={"#pronunciation": -len(dele)}) as s:
        for pid, _o, n in unesc:
            s.execute("UPDATE pronunciation SET ipa=? WHERE id=?", (n, pid))
        for pid, *_ in dele:
            s.execute("DELETE FROM pronunciation WHERE id=?", (pid,))
        for aid, _o, n in aud_fix:
            s.execute("UPDATE audio SET ipa=? WHERE id=?", (n, aid))
        for aid, _o in aud_null:
            s.execute("UPDATE audio SET ipa=NULL WHERE id=?", (aid,))
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = plan(con)
    checks = [("读音行仍不是 IPA", len(left[1]), 0), ("读音行仍带 HTML 实体", len(left[0]), 0),
              ("录音标注仍待处理", len(left[3]) + len(left[4]), 0)]
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
