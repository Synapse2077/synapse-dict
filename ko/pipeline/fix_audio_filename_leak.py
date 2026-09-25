#!/usr/bin/env python3
"""**音频文件名漏进了内容列**（罗马字 ＋ 读音）。ko，2026-09-25（阶段 9）。

═══ 怎么发现的 ═══
给欢迎页挑推荐词，把十六个常用词的字段打出来看，一眼撞见：

    하다      义项38  中文:做；泛指几乎任何动作…  罗马字:**Ko-hada.oga**
    공부하다   义项 1  中文:学习                罗马字:gongbuhada

`Ko-hada.oga` 是**维基共享资源上那条录音的文件名**。韩语最常用的动词，
页面上会把它的罗马字印成一个文件名。

⭐ **又一次是渲染逮到的，闸一条都没响**（`[[it-display-layer-stage8]]`）：
   四套罗马字齐全、非空、全是 ASCII、和词形一一对应 ——
   所有**形式**判据都满足，只有**内容**是错的。

═══ 源头就是这么写的（不是我们抽错了）═══
`kaikki.org-kowiktionary-Korean.jsonl` 里 `하다` 的 sounds：

    {"tags": ["revised", "romanization"],                 "roman": "Ko-hada.oga"}
    {"tags": ["revised", "romanization", "transliteration"], "roman": "Kohada.oga"}
    {"tags": ["McCune-Reischauer"],                       "roman": "Kohada.oga"}
    {"tags": ["Yale", "romanization"],                    "roman": "Kohata.oga"}

全库扫过：**16 条 sounds / 1 个词**，只有 `하다` 这一页这样。
⇒ `[[source-typo-fix-ours-not-quote]]`：**改我们的出版字段**，收割器加一道判据。

═══ 正确值怎么定的（**不是凭我知道**）═══
🔴 `[[verify-before-claiming-confirmed]]`：用**库内独立信号**定 ——
库里所有以 `하다` 结尾、罗马字非空的词（**8,567 个**，不含 `하다` 本身），
看它们罗马字的末四位：

    rr        hada 8,565 ／ kada 2
    translit  hada 8,566
    mr        hada 8,561
    yale      hata 8,567   ← 四套全部一致，且样本量三个数量级

⇒ `하다` ＝ rr `hada` ／ translit `hada` ／ mr `hada` ／ yale `hata`。

═══ 判据（写成「是什么」，不是「像什么」）═══
    罗马字**不可能以音频扩展名结尾**。
🔴 一开始我写的是 `GLOB '*.[a-z][a-z][a-z]'`（「带文件扩展名」）——
   它在 `roman_yale` 上命中 **5,487** 条，而那些全是对的：
   **Yale 用 `.` 做音节分隔**（`한국어` → `hānkwuk.e`）。
   `[[criteria-narrower-than-you-think]]` 的又一次：判据比它要描述的东西宽。
   同理「大写开头」也不行 —— 41 条里 40 条是**专名**（`Jungguk`/`Busan`），RR 本来就大写。

═══ 🔴🔴 第一版**只修了罗马字那四列，而同一个源头缺陷还落在读音层** ═══
修完罗马字、回归闸加了 R13、全绿 —— 然后把 `하다` 的页面**渲染出来读**，
读音那一行印着：

    Ko[ha̠da̠].oga    Ko하다.oga

`pronunciation.ipa` 与 `hangeul_phonetic` 里躺着同一个文件名。
R13 当时报绿，因为**它只查 `entry.roman_*` 四列** —— 判据的范围跟着
"我修的是哪几列"走，而不是跟着"这个缺陷可能落在哪儿"走。
`[[decision-not-propagated-across-editions]]`：一处做对了、别处照旧错着，
而每处自己的闸全绿。⇒ 判据改成**扫全库所有文本列**（`audio` 表除外 ——
那里放文件名是对的）。实测全库只剩这 2 行，都是 `하다`。

⚠️ 读音那一行 R10「读音裸存，不许有定界符」也没逮到它：
   R10 查的是 `ipa LIKE '[%'`（以定界符**开头**），而这一行是 `Ko[…].oga`。

跑（在仓库根）：
    python3 -u ko/pipeline/fix_audio_filename_leak.py
    python3 -u ko/pipeline/fix_audio_filename_leak.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import re
import sqlite3

import dbtool
import paths

f = lambda n: format(n, ",")

COLS = ("roman_rr", "roman_rr_translit", "roman_mr", "roman_yale")
# 🔴 判据只认**音频扩展名**，不认「有个点」也不认「大写开头」（见文件头）
AUDIO_EXT = re.compile(r"\.(oga|ogg|mp3|wav|flac|m4a|opus)$", re.I)
# 🔴🔴 **SQL 侧只做粗筛，判据在 Python 里。** 第一版把正则手工翻译成了
#    GLOB 字符类 `*.[oOmMwWfF][gGpPaAlL][aAgG3vVcC]` —— 它比正则**宽得多**，
#    当场把 `창가림막` 的 `cʰaŋ.ga.rim.mag` 判成音频文件名（`.mag` 逐位命中
#    m∈[oOmMwWfF]、a∈[gGpPaAlL]、g∈[aAgG3vVcC]），而那是一条**正确的、
#    按音节分隔的 IPA**。差一点就删掉一条真数据。
#    ⇒ 凡是"把判据翻译成另一种语法"的地方，翻译出来的那一版必须**更宽而不是更窄**，
#      并且**由原判据做最终裁决**。`[[criteria-narrower-than-you-think]]`。
SQL_LOOSE = " OR ".join("%s GLOB '*.*'" % c for c in COLS)

# 由库内 8,567 个 `*하다` 参照词定出来的（文件头）
FIX = {"하다": ("hada", "hada", "hada", "hata")}


def is_audio(v):
    return bool(v) and bool(AUDIO_EXT.search(v))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute(
        "SELECT e.id, d.word, %s FROM entry e JOIN dict d ON d.id = e.word_id "
        "WHERE %s" % (", ".join("e." + c for c in COLS), SQL_LOOSE)).fetchall()
    hit = [r for r in rows if any(is_audio(v) for v in r[2:])]

    print("■ 罗马字里是音频文件名的 entry 行 %s（涉及 %s 个词形）"
          % (f(len(hit)), f(len({r[1] for r in hit}))))
    for r in hit:
        print("   %-8s %s" % (r[1], list(r[2:])))

    # 🔴 判据的两条**反向**验证：确认它没把对的东西也算进来
    n_dot = con.execute(
        "SELECT COUNT(*) FROM entry WHERE roman_yale GLOB '*.*'").fetchone()[0]
    n_cap = con.execute(
        "SELECT COUNT(*) FROM entry WHERE roman_rr GLOB '[A-Z]*'").fetchone()[0]
    print("\n■ 判据收窄的证据（这两批**不是**缺陷，不许被顺手带走）")
    print("   roman_yale 含 `.` 的 %s 条 —— Yale 的**音节分隔符**（`hānkwuk.e`）" % f(n_dot))
    print("   roman_rr 大写开头的 %s 条 —— **专名**，RR 本来就大写（`Jungguk`）" % f(n_cap))

    # ── 第二处：读音层 ──
    # 🔴 这一行**整条删掉**，不是改值：`ipa` 与 `hangeul_phonetic` 双双是文件名，
    #    我没有正确值可填（罗马字那边有 8,567 个 `*하다` 参照词，这边没有对应物）。
    #    删掉之后 `하다` 仍有那条跨三版背书的 `ha̠da̠`（narrow）。
    #    `[[dont-gate-facts-on-my-uncertainty]]` 的正面用法：编不出来就别编。
    pron = [r for r in con.execute(
        "SELECT p.id, d.word, p.ipa, p.hangeul_phonetic, p.src FROM pronunciation p"
        " JOIN dict d ON d.id = p.word_id"
        " WHERE p.ipa GLOB '*.*' OR p.hangeul_phonetic GLOB '*.*'")
        if is_audio(r[2]) or is_audio(r[3])]
    print("\n■ 读音层里是音频文件名的行 %s" % f(len(pron)))
    orphan = []
    for pid, w, _ipa, _hp, _src in pron:
        left = con.execute(
            "SELECT COUNT(*) FROM pronunciation p JOIN dict d ON d.id=p.word_id"
            " WHERE d.word=? AND p.id<>?", (w, pid)).fetchone()[0]
        print("   %-8s %-18s %-14s 删掉后这个词还剩 %d 条读音" % (w, _ipa, _hp, left))
        if not left:
            orphan.append(w)
    if orphan:
        raise SystemExit("🔴 删了之后这些词就没有读音了：%s" % orphan)

    unknown = sorted({r[1] for r in hit} - set(FIX))
    if unknown:
        print("\n🔴 这些词没有查过的正确值，先别写：%s" % unknown)
        raise SystemExit("🔴 FIX 表里缺词 —— 正确值要用库内参照词定，不许凭印象填")
    con.close()

    if not a.apply:
        print("\n将写入：")
        for w, v in FIX.items():
            print("   %-8s rr=%s translit=%s mr=%s yale=%s" % ((w,) + v))
        print("\n（干跑。确认后 --apply）")
        return

    if not hit and not pron:
        print("\n■ 没有要改的（已经修过了）")
        return
    upd = [(FIX[r[1]] + (r[0],)) for r in hit]
    with dbtool.session(
            "ko-fix-audio-filename-leak",
            expect={"#pronunciation": -len(pron)},  # 罗马字是原地改值，非空计数不变
            invalidates=[]) as s:
        if upd:
            s.executemany(
                "UPDATE entry SET roman_rr=?, roman_rr_translit=?, roman_mr=?, "
                "roman_yale=? WHERE id=?", upd)
        s.executemany("DELETE FROM pronunciation WHERE id=?",
                      [(r[0],) for r in pron])

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        # 🔴 回核也**用原判据**（Python 正则），不用 SQL 近似
        ("库里不再有音频文件名当罗马字",
         sum(1 for r in con.execute(
             "SELECT %s FROM entry WHERE %s" % (", ".join(COLS), SQL_LOOSE))
             if any(is_audio(v) for v in r)), 0),
        ("`하다` 的 RR",
         q("SELECT COUNT(*) FROM entry e JOIN dict d ON d.id=e.word_id"
           " WHERE d.word='하다' AND e.roman_rr='hada'"), 1),
        # 🔴 全库扫一遍，不只扫我改过的那几列（这正是第一版漏掉读音层的原因）
        ("读音层里还有文件名的",
         sum(1 for r in con.execute(
             "SELECT ipa, hangeul_phonetic FROM pronunciation"
             " WHERE ipa GLOB '*.*' OR hangeul_phonetic GLOB '*.*'")
             if is_audio(r[0]) or is_audio(r[1])), 0),
        ("`하다` 还有几条读音",
         q("SELECT COUNT(*) FROM pronunciation p JOIN dict d ON d.id=p.word_id"
           " WHERE d.word='하다'"), 1),
        # 🔴 反向：那两批**对的**东西一条都没动
        ("roman_yale 含 `.` 的（Yale 音节点，应不变）",
         q("SELECT COUNT(*) FROM entry WHERE roman_yale GLOB '*.*'"), n_dot - len(hit)),
        ("roman_rr 大写开头的（专名，应不受影响）",
         q("SELECT COUNT(*) FROM entry WHERE roman_rr GLOB '[A-Z]*'"), n_cap - len(hit)),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-38s %7s（期望 %s）"
              % ("✅" if good else "🔴", name, f(got), f(want)))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
