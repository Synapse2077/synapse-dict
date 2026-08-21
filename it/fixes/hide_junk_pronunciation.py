#!/usr/bin/env python3
"""音标层的两族确定垃圾：占位星号 / 只剩标记符号 / fr 版切出来的词尾残片。2026-08-21。

═══ 怎么发现的 ═══
点测评审时 v4-pro 指出 `nacque` 的 `/ˈnakːe/` 错（意语 `qu` 必读 /kw/）。回源确认那行
`src=fr-edition`，而 en 版给的是 `ˈnak.kwe` —— A54 早就定了 **fr 版在音段分歧上无覆盖权**。
顺着查同族时，撞见了更明显的一批：**`*` 当音标，而且是主音标**。

═══ 判据修了三轮，前两轮都太宽（都停手了，残差当上界记账）═══
  ① 「词形含 qu 而音标无 kw」→ 116 条。**太宽**：`bouquet`/`moquette`/`boutique`
     是法语借词（qu 本就读 /k/）、`quinoa`/`quechua` 是西语借词、`ziqqurat` 的 q
     根本不在 qu 组合里。
  ② 「音标裸串长度不到词形一半」→ 167 条。**太宽**：`Doubs`→`ˈdu`、`Hérault`→`eˈro`
     是外国地名的真读音，法语正字法本就不是音素对应。
  ③ 「裸串是同词另一条读音的前缀/后缀」→ 173 条。**还是太宽**：`B` 的 `b`（辅音）
     与 `ˈbi`（字母名）**两个都对**，`K` 的 `k` 与 `ˈkap.pa` 同理，单字母/缩写上全废。
⇒ 按 `measure-landing-not-source` 的规矩「修判据三轮就停手，残差当上界报」：
   **173 条只作为上界记账**，本脚本只动**逐条读过、名单写死**的 8 条。

═══ 这 8 条 ═══
A. 占位符/空音标（4 条，**其中 3 条是主音标**，用户直接看到 `/*/`）
B. fr 版把音标切剩词尾（4 条，全是次读音，但页面会并排显示成"另一读音"）

🔴 `Vantaa` 藏掉后**一条读音都不剩** —— 这是有意的：显示 `/ː/` 比不显示更伤。
   （`blind-gloss-inference-ceiling` 的同一条原则：不填，留诚实空白。）
🔴 `nostalgicamente` / `parodo` 的主音标被藏 ⇒ **必须重选 primary**，
   否则整个词变成"有读音但没有默认读音"，展示层拿不到东西。

用法（在 it/ 目录下）：
    python3 fixes/hide_junk_pronunciation.py            # 干跑
    python3 fixes/hide_junk_pronunciation.py --apply
    python3 fixes/hide_junk_pronunciation.py --verify
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

f = lambda n: format(n, ",")

# 🔴 判据要**反着定义**：列出「不是音段的记号」，去掉它们还剩东西就是音标。
#    第一版列的是「音段字符白名单」`[a-zɡʃʒʎɲʧʤθðŋœøɛɔyæɐʁʀβɣχ]` —— **漏了一堆真音段**，
#    于是把 `r`→`ɾ`（齿龈闪音）、`ah`→`ʔ`（喉塞音）、`-ə`→`ə`、`-ɜ`→`ɜ` 全判成了垃圾，
#    17 条里有 9 条是误伤。IPA 的字符集没有边界，白名单永远列不全；
#    而「标记符号」是**有限且封闭**的。
#    ⚠️ 这是同一天第四次「判据比它要描述的东西更宽」，四次全是数据打回来的，
#       没有一次是读代码看出来的。
MARKS = set("\u02c8\u02cc.\u02d0\u02b2\u203f|*-\u2013\u2014 \t\u035c\u0361\u02de\u0329\u0330")


def is_junk_ipa(ipa):
    """`*` / `\u02d0` / 空串这类**根本不是音标**的值。"""
    return not any(ch not in MARKS for ch in (ipa or ""))


# ── B 族：fr 版把音标切剩词尾。**逐条读过**后按 id 写死 ────────────────────
#    判据是 A54（fr 版在音段分歧上无覆盖权）+ 同词 en 版给了完整且含 kw 的音标。
FR_TAIL = {
    153040: ("acquietano", "ˈa.no",   "akˈkwjɛ.ta.no"),
    153042: ("acquietino", "ˈi.no",   "akˈkwjɛ.ti.no"),
    137764: ("nacque",     "ˈnak.ke", "ˈnak.kwe"),
    137765: ("nacqui",     "ˈnak.ki", "ˈnak.kwi"),
}


def scan(con):
    """→ (要藏的 [(id, word, ipa, is_primary, 理由)], 要重选 primary 的 [(word_id, 新 id)])"""
    hide = []
    for pid, w, ipa, prim in con.execute(
            "SELECT p.id, d.word, p.ipa, p.is_primary FROM pronunciation p "
            "JOIN dict d ON d.id=p.word_id"):
        if is_junk_ipa(ipa):
            hide.append((pid, w, ipa, prim, "不是音标"))
    for pid, (w, bad, good) in FR_TAIL.items():
        row = con.execute("SELECT p.id, d.word, p.ipa, p.is_primary FROM pronunciation p "
                          "JOIN dict d ON d.id=p.word_id WHERE p.id=?", (pid,)).fetchone()
        if not row or row[2] != bad:
            raise SystemExit("🔴 名单对不上：id=%s 期望 %r，实际 %r" % (pid, bad, row and row[2]))
        hide.append((row[0], row[1], row[2], row[3], "fr 版切剩词尾（en 版给的是 %s）" % good))

    # 主音标被藏的词，要在**剩下的可见读音**里重选一条
    hidden_ids = {h[0] for h in hide}
    repick = []
    for pid, w, prim in [(h[0], h[1], h[3]) for h in hide if h[3] == 1]:
        wid = con.execute("SELECT word_id FROM pronunciation WHERE id=?", (pid,)).fetchone()[0]
        # 与 A54 的档位一致：en > it > rule:accent > fr > rule:plain
        cand = con.execute(
            """SELECT id, src FROM pronunciation WHERE word_id=? AND id NOT IN (%s)
               ORDER BY CASE src WHEN 'en-edition' THEN 0 WHEN 'it-edition' THEN 1
                                 WHEN 'rule:accent' THEN 2 WHEN 'fr-edition' THEN 3
                                 ELSE 4 END, id LIMIT 1"""
            % ",".join(str(i) for i in hidden_ids), (wid,)).fetchone()
        repick.append((w, wid, cand[0] if cand else None, cand[1] if cand else None))
    return hide, repick


def gate(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(pronunciation)")}
    if "hidden" not in cols:
        print("🔴 pronunciation 还没有 hidden 列")
        return False
    left = sum(1 for (t,) in con.execute(
        "SELECT ipa FROM pronunciation WHERE COALESCE(hidden,0)=0") if is_junk_ipa(t))
    # 每个还有可见读音的词，必须**恰好有一条** is_primary
    bad = con.execute("""
        SELECT COUNT(*) FROM (
          SELECT word_id, SUM(CASE WHEN is_primary=1 THEN 1 ELSE 0 END) k
            FROM pronunciation WHERE COALESCE(hidden,0)=0 GROUP BY word_id HAVING k<>1)
        """).fetchone()[0]
    print("■ 读取路径上仍不是音标的值：%s 条" % f(left))
    print("■ 有可见读音却没有（或有多条）默认读音的词形：%s 个" % f(bad))
    return left == 0 and bad == 0


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        ok = gate(ro)
        ro.close()
        return 0 if ok else 1
    hide, repick = scan(ro)
    ro.close()
    print("■ 要藏的读音行：%s 条" % f(len(hide)))
    for pid, w, ipa, prim, why in hide:
        print("     藏  %-18s %-14r primary=%s  %s" % (w[:18], ipa, prim, why))
    print("■ 主音标被藏、需重选默认读音的词：%s 个" % f(len(repick)))
    for w, wid, nid, src in repick:
        print("     %-18s → %s" % (w[:18], ("id=%s src=%s" % (nid, src)) if nid
                                   else "🔴 无可用读音，该词将没有音标（有意：显示垃圾更伤）"))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("hide-junk-pronunciation", expect={"__rows__": 0}) as s:
        cols = {r[1] for r in s.execute("PRAGMA table_info(pronunciation)")}
        if "hidden" not in cols:
            s.execute("ALTER TABLE pronunciation ADD COLUMN hidden INTEGER DEFAULT 0")
        s.execute("UPDATE pronunciation SET hidden=1, is_primary=0 WHERE id IN (%s)"
                  % ",".join(str(h[0]) for h in hide))
        for w, wid, nid, _src in repick:
            if nid:
                s.execute("UPDATE pronunciation SET is_primary=1 WHERE id=?", (nid,))
        s.written = len(hide) + sum(1 for r in repick if r[2])
    print("\n■ 已藏 %s 条、重选默认读音 %s 个"
          % (f(len(hide)), f(sum(1 for r in repick if r[2]))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
