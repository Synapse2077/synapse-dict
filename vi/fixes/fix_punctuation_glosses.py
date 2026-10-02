#!/usr/bin/env python3
"""**把「不载任何信息」的释义从出版层拿下来**。2026-10-02。

本脚本治两类，它们是同一件事的两种写法（所以**不拆成两个脚本** —— 同一个机制拆两份必漂）：

    ① 整串是标点          141 条   `.`                      ← 跑 5b **之前**抽样看见的
    ② 源头的词典标记缩写     45 条   `Trgt.` `Ph.` `L.` `X.`  ← 跑 5b **之后**控制组报出来的

②这一类是 5b 的形状检查「译文里没有一个汉字」带出来的：模型把 `Trgt.` 原样回显，
**那是对的 —— 没东西可译**。但它们本来就不该在出版层。
⭐ 这正是 ko 记的那条「1% 定价切片的真正价值是逮出本层自己的缺陷」—— 只是在 vi 上
   1% 切片里这一类只有 0.5 行，是**全量跑完的控制组**才报出来的。

═══ 它是怎么被逮到的 ═══
准备跑 5b（把缺中文的义项译成中文）时抽样看待译的释义，看见
`tè → . (Thấp, lùn) quá mức…` 和一堆整串就是 `.` 的 ——
回去量：**出版层有 141 条释义整串是标点**（全是 vi 版的 `.`）。

🔴 义项层闸 **E4 查的是 `TRIM(text)=''`**，而 `.` 不是空串 ⇒ 它穿过去了。
🔴🔴 更该记的是：**同一种源头残渣在三个层上各出现过一次**，而我只在本层处理了本层的：

    例句层（阶段 6a）  vi 版 `translation` 里 **214 条**整串是 `.`  ⇒ 当时只在例句侧判掉
    词源层（阶段 7a）  en 版 **122 段**整串是 `.`                 ⇒ 当时只在词源侧判掉
    义项层（阶段 5a）  **141 条**                                 ⇒ **一直没人判，就是这一笔**

三次都是「在本层把它挡掉」而**没把判据收进 `criteria.py`** ⇒ 下一层照样中。
⇒ 判据现在住在 `criteria.gloss_has_content()`，义项层闸加 **E12** 盯着出版层。

═══ ⚠️ 判据收窄得很紧：只判「有没有字母/数字/表意文字」，**不判长短** ═══
我第一版想按「短于 2 字符」清，**那会删掉 503 条正确释义** —— 实测短释义全是真的：

    năm → 五        bo → 硼        văn → 搓        （zh 一个汉字，494 条）
    bần đạo → I     mỗ → I         w → w          （en 一个字母，9 条）

`[[criteria-narrower-than-you-think]]`：**先读样本再定判据**。计数会骗人，样本不会。

═══ ⭐ 第二次收窄：我第一遍扫的时候手抄的字符类是 `\u4e00-\u9fff`（只有通用区）═══
那一版报 151 条，比最终判据多 10 条。那 10 条是**化学元素的汉字名，住在 CJK 扩展平面**：

    rơzơfođi → 𬬻 (U+2CB3B)   seaborgi → 𬭳   bohri → 𨨏   meitneri → 䥑   flerovi → 𫓧

**全是正确释义。** ⇒ 这正是 ko 记下的那条教训逐字重演：
「我手写字符类差点删掉 5 条正确释义（化学元素汉字名在 CJK 扩展平面）
⇒ **判据交给 Unicode 答，别手抄范围**」。同一个坑、同一类内容、换了一门语言。
⇒ `criteria.gloss_has_content()` 的字符类含扩展平面，这 10 条一条都不动。

═══ 做法：隐藏义项，**不删释义** ═══
这 151 条义项每条**只有**这一条垃圾释义（量过），所以隐藏义项不丢别的内容。
释义行留在 `sense_gloss` 里（证据不编辑，与 E7 同一个精神），只是 `sense.hidden=1`。
⚠️ 3 条例句挂在这些义项上 —— 它们不受影响（`example.sense_id` 仍然有效），
   但读者口径的释义覆盖率会**掉一点点**，那是诚实的。

用法：
    python3 vi/fixes/fix_punctuation_glosses.py [--apply]
"""
import argparse
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import dbtool                                                     # noqa: E402
import paths                                                      # noqa: E402
from criteria import gloss_has_content, is_vi_markup_gloss         # noqa: E402

F = lambda n: format(n, ",")                                      # noqa: E731
HIDDEN_WHY = "gloss-is-punctuation-only"
HIDDEN_WHY_MARKUP = "gloss-is-source-markup"


def find(con):
    """→ [(sense_id, lang, text, hidden_why)]，两类合一个入口。"""
    out = []
    for sid, lang, t in con.execute(
            "SELECT g.sense_id, g.lang, g.text FROM sense s "
            "JOIN sense_gloss g ON g.sense_id=s.id WHERE s.hidden=0"):
        if not gloss_has_content(t):
            out.append((sid, lang, t, HIDDEN_WHY))
        elif lang == "vi" and is_vi_markup_gloss(t):
            out.append((sid, lang, t, HIDDEN_WHY_MARKUP))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    bad = find(con)
    if not bad:
        print("■ 出版层没有「整串是标点」的释义 ✓")
        con.close()
        return
    sids = sorted({s for s, _l, _t, _y in bad})
    why_of = {s: y for s, _l, _t, y in bad}
    q = ",".join(str(s) for s in sids)
    print("■ 出版层「不载信息」的释义 **%s 条**，落在 **%s 条义项**上"
          % (F(len(bad)), F(len(sids))))
    import collections
    print("   按语言：%s" % dict(collections.Counter(l for _s, l, _t, _y in bad)))
    print("   按原因：%s" % dict(collections.Counter(y for _s, _l, _t, y in bad)))
    n_all = con.execute("SELECT COUNT(*) FROM sense_gloss WHERE sense_id IN (%s)"
                        % q).fetchone()[0]
    print("   这些义项一共 %s 条释义 ⇒ %s"
          % (F(n_all), "每条只有这一条垃圾释义，隐藏不丢别的内容 ✓" if n_all == len(bad)
             else "🔴 有义项还带着好释义，**不能整条隐藏** —— 停下来重想"))
    if n_all != len(bad):
        raise SystemExit(1)
    ex = con.execute("SELECT COUNT(*) FROM example WHERE sense_id IN (%s)" % q).fetchone()[0]
    rel = con.execute("SELECT COUNT(*) FROM sense_relation WHERE sense_id IN (%s)"
                      % q).fetchone()[0]
    cov_before = con.execute(
        "SELECT COUNT(DISTINCT s.word_id) FROM sense s JOIN sense_gloss g "
        "ON g.sense_id=s.id WHERE s.hidden=0").fetchone()[0]
    tot = con.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
    only = con.execute(
        "SELECT COUNT(*) FROM (SELECT s.word_id FROM sense s WHERE s.hidden=0 "
        "GROUP BY s.word_id HAVING SUM(CASE WHEN s.id IN (%s) THEN 0 ELSE 1 END)=0)"
        % q).fetchone()[0]
    print("   挂在它们上的例句 %s ／ 关系 %s（不受影响）" % (F(ex), F(rel)))
    print("   ⚠️ 隐藏后**彻底没有可出版释义**的词形会多 %s 个 "
          "⇒ 读者口径释义覆盖 %.2f%% → %.2f%%（诚实地掉一点）"
          % (F(only), 100.0 * cov_before / tot, 100.0 * (cov_before - only) / tot))
    for s, lang, t, _y in bad[:10]:
        w = con.execute("SELECT d.word FROM sense s JOIN dict d ON d.id=s.word_id "
                        "WHERE s.id=?", (s,)).fetchone()[0]
        print("      %-18s %-3s %r" % (w, lang, t[:30]))
    con.close()

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    with dbtool.session(
            "fix-vi-punctuation-glosses",
            expect={"__rows__": 0},
            invalidates=["义项层的出版行少了 %s 条 ⇒ 读者口径释义覆盖率变了，"
                         "义项层闸要重跑；下游按「缺中文」挑行的 5b 也要重新取数"
                         % F(len(sids))]) as s:
        s.executemany("UPDATE sense SET hidden=1, hidden_why=? WHERE id=?",
                      [(why_of[i], i) for i in sids])

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = find(con)
    checks = [
        ("🔴 出版层还剩几条纯标点释义", len(left), 0),
        # 🔴 **期望值要对准「这一轮」，不是「累计」。** 第一版查的是
        #    `hidden_why IN (两类)` 的总行数，而本脚本是**两次分别跑**的
        #    （①141 条在跑 5b 之前、②45 条在跑 5b 之后）⇒ 第二次跑时查到 186、
        #    期望 45，报了一个**假红**（数据是对的，是检查写错了）。
        #    `[[expectation-must-be-declared]]`：期望值要独立声明且对准同一个口径。
        ("被隐藏的义项数（**本轮**的那些）",
         con.execute("SELECT COUNT(*) FROM sense WHERE hidden=1 AND id IN (%s)"
                     % q).fetchone()[0], len(sids)),
        # 🔴 证据不编辑：释义行必须还在
        ("🔴 那些释义行还在 sense_gloss 里（证据不编辑）",
         con.execute("SELECT COUNT(*) FROM sense_gloss WHERE sense_id IN (%s)"
                     % q).fetchone()[0], len(bad)),
        ("每条 sense 仍然至少有一条 gloss（E2 不许被破）",
         con.execute("SELECT COUNT(*) FROM sense s LEFT JOIN sense_gloss g "
                     "ON g.sense_id=s.id WHERE g.id IS NULL").fetchone()[0], 0),
    ]
    for name, got, want in checks:
        print("   %s %-44s %s（期望 %s）"
              % ("✅" if got == want else "🔴", name, F(got), F(want)))
    con.close()
    if any(g != w for _n, g, w in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
