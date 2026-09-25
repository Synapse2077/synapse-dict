#!/usr/bin/env python3
"""删掉**内容为空的维基标记**冒充的释义（`[[]]`）。ko，2026-09-25。

═══ 怎么发现的 ═══
收完日文版释义、译完落库之后，顺手查「译文里带句末句号的有多少」，
样本里赫然三行：

    [[]]。
    [[]]。
    [[]]。

日文版的源头 gloss 就是 `[[]]。` —— **一个空的维基内链**。
模型照规矩原样保留（prompt 第 6 条「吃不准的直译，不要编造」），
于是页面上会印出 `[[]]` 当释义。**比没有释义更糟。**

⭐ 又一次是**把落点打出来读**才看见的：
   跑批 927/927、失败 0、定题 3/3、逐 id 点名一条不差 —— 所有过程指标都完美，
   而其中 18 条的**内容**是空的。`[[fr-dict-pipeline]]`：**闸问「有没有」，判官问「对不对」。**

═══ 判据（按含义写）═══
    **一条释义里若没有任何「能读的字」（汉字 / 谚文 / 假名 / 拉丁字母 / 数字），
      它就不是释义。**
不写成「等于 `[[]]`」—— 那是形式代理，源头下次写成 `[[ ]]` 或 `（）` 就漏过去了
（`[[criteria-from-meaning-not-form]]`）。

实测：ja 那批 **18 行**，en/ko 那批 **2 行**，ko 版源头自带的 `?` / `.` **3 行**，共 **23 行**。

🔴🔴 **判据第一版又写宽了，差点删掉 5 条正确的释义。**
我手写了字符类 `[0-9A-Za-z぀-ヿ㐀-䶿一-鿿가-힯ᄀ-ᇿ]`，它**漏掉 CJK 扩展平面** ——
`두브늄`(dubnium)→`𨧀`、`시보르귬`(seaborgium)→`𨭎`、`러더포듐`→`𬬻`…
化学元素的汉字名**一个字就是完整释义**，而它们全在 U+28000/U+2B000 区。
⇒ 判据交给 Unicode 自己答（类别 `L*`/`N*`），**别手抄字符范围**。

═══ 删完把义项还原成空壳 ═══
这些义项是 `harvest_ja_glosses` 为了放译文而**取消 hidden 或新建**的。
释义没了，它就该退回 K10 里那 20 万条空壳的状态 —— 否则页面上会多出
一条**什么都没有的义项**，而那正是 K10 当初要治的东西。
⚠️ **证据层一个字不动**：源头确实写了 `[[]]`，那是事实
（`[[source-typo-fix-ours-not-quote]]`：改我们的出版文本，引文与证据层不动）。

跑（在仓库根）：
    python3 -u ko/pipeline/fix_empty_markup_gloss.py
    python3 -u ko/pipeline/fix_empty_markup_gloss.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import sqlite3
import unicodedata

import dbtool
import paths

f = lambda n: format(n, ",")

# 「能读的字」＝ Unicode 类别是**字母或数字**的字符。
# 🔴🔴 **第一版我手写了一个字符类**：`[0-9A-Za-z぀-ヿ㐀-䶿一-鿿가-힯ᄀ-ᇿ]`
#    —— 它漏掉了 **CJK 扩展平面**，当场要把 5 条**正确的释义**删掉：
#        두브늄(dubnium) → 𨧀      시보르귬(seaborgium) → 𨭎
#        러더포듐(rutherfordium) → 𬬻   더브늄 → 𬭊   시보귬 → 𬭛
#    那是化学元素的汉字名（U+28000/U+2B000 区），**一个字就是完整的释义**。
#    ⇒ 判据交给 Unicode 自己答（`L*` 字母 / `N*` 数字），别手抄字符范围。
#    `[[criteria-from-meaning-not-form]]`：手抄的范围表永远缺一块。
def is_empty(text):
    return not any(unicodedata.category(c)[0] in ("L", "N") for c in (text or ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = [r for r in con.execute(
        "SELECT g.rowid, g.sense_id, g.lang, g.text, g.src, d.word"
        " FROM sense_gloss g JOIN sense s ON s.id = g.sense_id"
        " JOIN dict d ON d.id = s.word_id") if is_empty(r[3])]
    print("■ 出版层里「没有任何能读的字」的释义 %s 行" % f(len(rows)))
    bysrc = {}
    for r in rows:
        bysrc[r[4]] = bysrc.get(r[4], 0) + 1
    for k, v in sorted(bysrc.items()):
        print("   %-40s %s" % (k, f(v)))
    print("\n■ 样本")
    for r in rows[:8]:
        print("   %-8s lang=%-3s text=%r" % (r[5], r[2], r[3]))

    # 删完哪些义项会**一条释义都不剩** ⇒ 退回空壳
    ids = {r[1] for r in rows}
    left = {r[0] for r in con.execute(
        "SELECT sense_id FROM sense_gloss WHERE sense_id IN (%s)"
        % ",".join(str(i) for i in ids)) } if ids else set()
    # 上面那条会把自己也算进去，改成排除要删的 rowid
    dead = set()
    if ids:
        keep = {r[0] for r in con.execute(
            "SELECT sense_id FROM sense_gloss WHERE sense_id IN (%s)"
            " AND rowid NOT IN (%s)"
            % (",".join(str(i) for i in ids),
               ",".join(str(r[0]) for r in rows)))}
        dead = ids - keep
    n_hidden_before = con.execute(
        "SELECT COUNT(*) FROM sense WHERE hidden=1").fetchone()[0]
    n_gloss_before = con.execute("SELECT COUNT(*) FROM sense_gloss").fetchone()[0]
    # 🔴 证据层那条回核的期望值**写前抓基线**，不要手写一个数。
    #    第一版我按屏幕上看到的 18 写死，而真值是 22（`sense_gloss` 里 18 条、
    #    `sense_src` 里还有 4 条从没被译过）—— 回核当场报红，而**数据是对的、期望是错的**。
    #    `[[expectation-must-be-declared]]`：期望要独立声明，但"独立"不等于"凭印象写"。
    n_src_markup = con.execute(
        "SELECT COUNT(*) FROM sense_src WHERE text LIKE '%[[]]%'").fetchone()[0]
    already_hidden = con.execute(
        "SELECT COUNT(*) FROM sense WHERE hidden=1 AND id IN (%s)"
        % ",".join(str(i) for i in dead)).fetchone()[0] if dead else 0
    print("\n■ 删完一条释义都不剩的义项 %s 条 ⇒ 退回空壳（hidden=1）" % f(len(dead)))
    print("   其中本来就是 hidden 的 %s" % f(already_hidden))
    con.close()

    if not rows:
        print("\n■ 没有要改的")
        return
    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return

    with dbtool.session(
            "ko-drop-empty-markup-gloss",
            expect={"#sense_gloss": -len(rows)},
            invalidates=[]) as s:
        s.executemany("DELETE FROM sense_gloss WHERE rowid=?",
                      [(r[0],) for r in rows])
        if dead:
            s.executemany("UPDATE sense SET hidden=1 WHERE id=?",
                          [(i,) for i in sorted(dead)])

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    still = sum(1 for r in con.execute("SELECT text FROM sense_gloss")
                if is_empty(r[0]))
    checks = [
        ("库里还有没有内容的释义", still, 0),
        ("sense_gloss 行数", q("SELECT COUNT(*) FROM sense_gloss"),
         n_gloss_before - len(rows)),
        ("空壳义项多了", q("SELECT COUNT(*) FROM sense WHERE hidden=1") - n_hidden_before,
         len(dead) - already_hidden),
        # 🔴 证据层一个字没动（源头确实写了 `[[]]`，那是事实）
        ("证据层里 `[[]]` 一条没动",
         q("SELECT COUNT(*) FROM sense_src WHERE text LIKE '%[[]]%'"), n_src_markup),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-30s %8s（期望 %s）" % ("✅" if good else "🔴", name, f(got), f(want)))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
