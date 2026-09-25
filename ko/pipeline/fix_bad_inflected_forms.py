#!/usr/bin/env python3
"""修 92 个**语法上不存在**的活用形。2026-09-24（阶段 8 后补）。

═══ 怎么发现的 ═══
建「从变形层反推不规则类」的判据时，拿它跟**后缀蕴含的类**交叉对了一遍：
    -짓다 结尾 ⇒ ㅅ불규칙（v4pro 说"无反例"，我用库里 403,687 行逐条验过）
    而 `짝짓다` / `한숨짓다` 两个词，形式反推出来是**규칙**
分歧就回源。源头（英文版）给这两个词生成的是**规则活用表**：

    库里有   짝짓어  짝짓으니  한숨짓어  한숨짓으니
    韩语里是  짝지어  짝지으니  한숨지어  한숨지으니

ㅅ불규칙的规则是「**元音开头的词尾前脱 ㅅ**」，辅音词尾前保留
（`짝짓고`/`짝짓는다` 是对的，不动）。⇒ 92 个词形错，92 个对。

🔴 **这批已经进了 `dict`** ⇒ 用户搜 `짝짓어` 搜得到，页面告诉他这是 `짝짓다` 的合法活用形。
   `[[dict-framework-doc]]`：**错比缺更伤权威**。

═══ 🔴 为什么外锚闸全绿而这批是错的 ═══
`verify_layers_vs_dump.py` 报变形层 403,687/403,687 双向恒等 —— **它是对的**：
这 92 条源头确实就这么写。恒等式问的是「我们收得对不对」，
**问不了「源头对不对」**。那道闸的文件头把这一条写在最前面，现在有了实例。
⇒ 逮到它的是**第三个独立信号**（后缀蕴含的类），不是闸。

═══ 改法：原地改 `dict.word`，不删不插 ═══
实测这 92 个词形身上**只挂着 `inflection` 行**（没有 entry/sense/读音/关系），
且修正后的 92 个词形**与库里已有词形零撞车**。
⇒ 最小改动是把 `dict.word` / `word_norm` 原地改对，`inflection.word_id` 一个字不动。
   删 + 插会换掉 `dict.id`，而 `id` 是别处引用的东西（`[[prefer-reversible-designs]]`）。

⚠️ 这是 `[[source-typo-fix-ours-not-quote]]` 的情形：**源头本身写错，改我们的出版文本**。
   `inflection` 是出版层。证据层（`sense_src`）这批词一个字没动，也不该动。

═══ 变换本身怎么验的 ═══
不是"我觉得对"，是**拿源头里写对了的那 5 个 `-짓다` 词当对照组**：
把 `결정짓다` 的 58 个正确形式反推成"如果源头写错会长什么样"，
再用本脚本的变换推回去 —— **58/58 还原**。

跑（在仓库根）：
    python3 -u ko/pipeline/fix_bad_inflected_forms.py
    python3 -u ko/pipeline/fix_bad_inflected_forms.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import sqlite3
import unicodedata

import dbtool
import paths

f = lambda n: format(n, ",")

# 🔴 名单写死，不用判据扫全库。理由：这是**两个词的源头错误**，不是一类现象；
#    写成判据会诱使我把它套到别的词上，而别的词没验过
#    （`[[criteria-narrower-than-you-think]]`：修判据三轮就停手，转"名单写死+逐条读"）。
#    交叉判据（后缀 vs 反推）全量跑过，**只报这 2 个，零假阳性** —— 名单就是全集。
LEMMAS = ["짝짓다", "한숨짓다"]
# ㅅ불규칙 脱落只发生在**元音开头的词尾**前。这三个是源头实际生成的词尾首字。
VOWEL_HEAD = ("어", "아", "으")


def drop_jong(ch):
    """把一个谚文音节的收音去掉：`짓` → `지`。"""
    n = ord(ch) - 0xAC00
    return chr(0xAC00 + (n // 588) * 588 + ((n % 588) // 28) * 28)


def fix_form(w, base):
    """`짝짓어` → `짝지어`。**只动词干最后一个音节的收音**，词尾一个字不碰。"""
    stem = base[:-1]
    assert w.startswith(stem), (w, base)
    return stem[:-1] + drop_jong(stem[-1]) + w[len(stem):]


def is_bad(w, base):
    stem = base[:-1]
    return any(w.startswith(stem + v) for v in VOWEL_HEAD)


def control(con):
    """对照组：源头**写对了**的 `-짓다` 词，反着验这条变换。

    🔴 `[[validate-criterion-where-source-is-right]]`：拿自己的规则去改源头的错之前，
       先在**源头没错的那批行**上验 —— 分歧只剩已知 bug 才算验过。
    """
    ok = bad = 0
    for lemma in ("결정짓다", "미소짓다", "특징짓다", "떼짓다", "여름짓다"):
        stem = lemma[:-1]
        good = stem[:-1] + drop_jong(stem[-1])          # 결정지
        for (w,) in con.execute(
                "SELECT DISTINCT d.word FROM inflection i JOIN dict d ON d.id=i.word_id "
                "WHERE i.base=?", (lemma,)):
            if not w.startswith(good) or w == lemma:
                continue
            spoiled = stem + w[len(good):]              # 假装源头写错
            (ok, bad) = (ok + 1, bad) if fix_form(spoiled, lemma) == w else (ok, bad + 1)
    return ok, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ok, bad = control(con)
    print("■ 对照组（源头写对了的 5 个 `-짓다` 词，反着验变换）：%d/%d" % (ok, ok + bad))
    if bad or ok < 50:
        raise SystemExit("🔴 变换在**源头没错的那批**上就对不上 —— 先别动数据")

    pairs, rows = [], 0
    for lemma in LEMMAS:
        for wid, w in con.execute(
                "SELECT DISTINCT d.id, d.word FROM inflection i JOIN dict d ON d.id=i.word_id "
                "WHERE i.base=?", (lemma,)):
            if not is_bad(w, lemma):
                continue
            pairs.append((wid, w, fix_form(w, lemma)))
    ids = {p[0] for p in pairs}
    rows = con.execute(
        "SELECT COUNT(*) FROM inflection WHERE word_id IN (%s)"
        % ",".join("?" * len(ids)), tuple(ids)).fetchone()[0]

    # 🔴 三条安全前提，**在写之前逐条验**，不是写完了再说
    other = con.execute(
        "SELECT (SELECT COUNT(*) FROM entry WHERE word_id IN (%(i)s))"
        " + (SELECT COUNT(*) FROM sense WHERE word_id IN (%(i)s))"
        " + (SELECT COUNT(*) FROM sense_src WHERE word_id IN (%(i)s))"
        " + (SELECT COUNT(*) FROM pronunciation WHERE word_id IN (%(i)s))"
        " + (SELECT COUNT(*) FROM sense_relation WHERE word_id IN (%(i)s))"
        % {"i": ",".join("?" * len(ids))}, tuple(ids) * 5).fetchone()[0]
    collide = [p for p in pairs
               if con.execute("SELECT 1 FROM dict WHERE word=?", (p[2],)).fetchone()]
    asbase = con.execute(
        "SELECT COUNT(*) FROM inflection WHERE base IN (%s)"
        % ",".join("?" * len(pairs)), tuple(p[1] for p in pairs)).fetchone()[0]
    # 🔴 写**之前**把基线取下来。回核里写 `q(x) == q(x)` 是一条永远通过的检查
    #    （我第一版就是这么写的）—— `[[expectation-must-be-declared]]`：
    #    期望值必须独立声明，不能从被检查的那个东西现场推。
    n_infl_before = con.execute("SELECT COUNT(*) FROM inflection").fetchone()[0]
    n_dict_before = con.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
    con.close()

    print("■ 要改的词形 %s 个／牵动 `inflection` 行 %s" % (f(len(pairs)), f(rows)))
    for wid, w, nw in pairs[:10]:
        print("   %-14s → %-14s" % (w, nw))
    print("\n■ 写之前的三条安全前提")
    for name, got in (("这些词形身上挂着别的层吗（要 0）", other),
                      ("修正后与已有词形撞车吗（要 0）", len(collide)),
                      ("它们被别人当 base 引用吗（要 0）", asbase)):
        print("   %s %-34s %s" % ("✅" if not got else "🔴", name, f(got)))
    if other or collide or asbase:
        raise SystemExit("🔴 前提不成立 —— 原地改名不安全，换方案")

    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return

    with dbtool.session(
            "ko-fix-bad-inflected-forms",
            # ⚠️ 原地改名：行数与列的非空数**一个都不变**，所以 expect 是空的。
            #    🔴 那就意味着写库闸门**对这次改动是瞎的** —— 它盯的是行数与列。
            #    ⇒ 真正守这次改动的是下面的写后回核＋新建的交叉闸，不是这道闸。
            #    把这句写在这儿，是为了不让"闸绿了"被当成"改对了"。
            expect={},
            invalidates=[
                "搜索层（阶段 9）：`search_prefix` 要在这批之后重建 —— 92 个词形的字符串变了",
                "外锚闸 `verify_layers_vs_dump.py` 的变形层那一支：**它会红**，"
                "因为库里不再与源头逐字相同 —— 这正是本次的目的，要在那道闸里把这 2 个词登记为已知偏离",
            ]) as s:
        s.executemany(
            "UPDATE dict SET word=?, word_norm=? WHERE id=?",
            [(nw, unicodedata.normalize("NFC", nw), wid) for wid, w, nw in pairs])

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x, *p: con.execute(x, p).fetchone()[0]
    names = ",".join("?" * len(pairs))
    checks = [
        ("坏词形已经不在 dict 里",
         q("SELECT COUNT(*) FROM dict WHERE word IN (%s)" % names,
           *[p[1] for p in pairs]), 0),
        ("正确词形都在 dict 里",
         q("SELECT COUNT(*) FROM dict WHERE word IN (%s)" % names,
           *[p[2] for p in pairs]), len(pairs)),
        # 🔴 反向闸：**不该动的一条都没动** —— 辅音词尾那批（짝짓고/짝짓는다）还在
        ("辅音词尾那批原样没动",
         q("SELECT COUNT(*) FROM dict WHERE word IN ('짝짓고','짝짓는다','한숨짓고','한숨짓는다')"), 4),
        ("inflection 行数没变", q("SELECT COUNT(*) FROM inflection"), n_infl_before),
        ("dict 行数没变（原地改名，不增不减）",
         q("SELECT COUNT(*) FROM dict"), n_dict_before),
        ("word_id 都还指得到",
         q("SELECT COUNT(*) FROM inflection i LEFT JOIN dict d ON d.id=i.word_id "
           "WHERE d.id IS NULL"), 0),
    ]
    okall = True
    for name, got, want in checks:
        good = got == want
        okall &= good
        print("   %s %-30s %8s（期望 %s）" % ("✅" if good else "🔴", name, f(got), f(want)))
    print("\n■ 改完的样子")
    for r in con.execute(
            "SELECT d.word, i.base, i.label_zh FROM inflection i JOIN dict d ON d.id=i.word_id "
            "WHERE i.base='짝짓다' ORDER BY d.word LIMIT 8"):
        print("   %-14s ← %s（%s）" % r)
    con.close()
    if not okall:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
