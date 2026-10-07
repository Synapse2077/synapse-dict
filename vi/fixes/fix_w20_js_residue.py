#!/usr/bin/env python3
"""W20 结清：fr 版漏进例句正文的 **JavaScript 实参列表残渣**。2026-10-06。

═══ 这笔账为什么到今天才动 ═══
2026-10-03 阶段 6e 跑批时逮到它（模型拿到这两条没东西可译、原样返回，
被「译文里没有一个汉字」那条异常检查捞出来），当时**只落了账没有做任何事** ——
理由写的是「另一笔」。而 2026-10-06 重量这笔账时才看见：

    这 2 条 `hidden = 0`，**现在就在页面上**。
        `phá hoại` 的例句：`','vietphap','on')"morale`
        `nhũng`    的例句：`','vietphap','on')"tracassiers`

⇒ `[[gate-registers-status-quo-as-spec]]`：给这笔账「配一道闸锁住 3 条」
  等于把一个读者看得见的缺陷登记成规格。**它该被清掉，不是被锁住。**

═══ 判据之家在 `stage6_sources.example_hidden_why()`，**不在本文件里** ═══
🔴🔴 **第一版我把判据只写进了本脚本（直接 UPDATE 两行），外锚闸当场判红：
   「2 条键对上了而内容不一样」—— 而它是对的。**
   `collect()` 产不出 `hidden_why='js-markup-residue'` ⇒ 库不再是收割器的产物，
   而 `build_example_layer.py --sync`／`--rebuild` 会把这两行冲回出版层。
⭐ 这一跤项目里刚记过（阶段 6e 那轮）：**判据搬进收割器，不是搬进闸** ——
  搬进闸则 `--rebuild` 会把脏数据写回而闸照样绿。这次是搬进 `fixes/` 脚本，**同一个洞**。
⇒ `is_js_residue()` 住在 §⑤g，`example_hidden_why()` 第一条就调它；
  本脚本只剩一件事：**把判据已经改过的结论落到现有这份库上**（不重建 7.8 万行）。
  回归闸 **P33** 和例句层闸 **X13** 查的都是同一个函数的产物。

═══ 为什么只有 2 条，而账上写的是 3 条 ═══
账上的第三条是 `'tỉnh, province`（`id=73731`）。它**不是这一族**：
行首那个落单的单引号是同一个 JS 调用被截断留下的，但**整条是可读的**
（`tỉnh` ＋ 它的法语释义 `province`）—— 那是 **W16** 那一族
（fr 版把自己的释义语言挤进 examples），只是分隔符是逗号不是 ` : `。
同一个形状还有 3 条（`'huyện, division du phủ…` ／ `'chuồng ngựa` ／
`'âm hưởng' phòng hòa nhạc`）。

🔴 **把它们一起判成「不是例句」会删掉可读的内容**，而那比留着一个多余的引号更坏：
`[[source-typo-fix-ours-not-quote]]` —— 一条被截断的引文看起来是完整的。
⇒ 它们另记一笔（W20 的行里写明），本脚本一条都不碰。

用法：
    python3 vi/fixes/fix_w20_js_residue.py            # 只看
    python3 vi/fixes/fix_w20_js_residue.py --apply    # 写库
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "vi"))
sys.path.insert(0, str(ROOT / "vi" / "pipeline"))
import dbtool                                           # noqa: E402
import paths                                            # noqa: E402
import stage6_sources as S6                             # noqa: E402


def collect(con):
    """→ [(id, word, text)]；判据 `import` 自 §⑤g，本文件不重写。"""
    return [(i, w, t) for i, w, t in con.execute(
        "SELECT e.id, d.word, e.text FROM example e JOIN dict d ON d.id = e.word_id "
        " WHERE e.hidden = 0 ORDER BY e.id") if S6.is_js_residue(t)]


def report(con, rows):
    print("■ W20：可出版例句里整条只是 JS 标记残渣的 %d 条" % len(rows))
    for i, w, t in rows:
        print("   id=%-6d %-12s %r" % (i, w, t))
    # ⚠️ **邻居也要印出来**，否则「只有 2 条」这个结论没人能复核
    #    （`[[residual-bucket-is-not-evidence]]`：别拿自己制造的残差当证据）。
    nb = [(i, w, t) for i, w, t in con.execute(
        "SELECT e.id, d.word, e.text FROM example e JOIN dict d ON d.id = e.word_id "
        " WHERE e.hidden = 0 AND e.src = 'fr-edition' AND e.text LIKE '''%' ORDER BY e.id")
        if not S6.is_js_residue(t)]
    print("\n   ── 同一个 JS 调用截断留下的**可读**那几条（有意一条都不碰）：%d 条" % len(nb))
    for i, w, t in nb:
        print("      id=%-6d %-12s %r" % (i, w, t))
    # 🔴 读者口径：这两条挂着译文吗（挂着的话隐藏它们会让付费数据变成孤儿）
    orph = con.execute(
        "SELECT COUNT(*) FROM example_gloss WHERE example_id IN (%s)"
        % ",".join(str(i) for i, _w, _t in rows)).fetchone()[0] if rows else 0
    print("\n   ── 它们身上挂着的译文：%d 条（>0 就要先想清楚付费数据的去处）" % orph)
    return orph


def apply_(con, rows):
    with dbtool.session(
        "vi-w20-js-residue",
        expect={
            "example.hidden_why": len(rows),   # NULL → 'js-markup-residue'
            # `hidden` 本来就是 0（非空）⇒ 非空计数不变，不写进 expect
            "__rows__": 0,                     # 🔴 一行都不许增减（可逆）
        },
        invalidates=[],                        # 不插新词形，覆盖率分母不动
    ) as cur:
        for i, _w, _t in rows:
            cur.execute("UPDATE example SET hidden = 1, hidden_why = ? WHERE id = ?",
                        (S6.HIDDEN_JS_RESIDUE, i))


def main():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = collect(con)
    orph = report(con, rows)
    con.close()
    if "--apply" not in sys.argv:
        print("\n   （只看。要写库加 --apply）")
        return
    assert orph == 0, "有译文挂在这两条上 —— 先决定付费数据的去处，别顺手隐藏"
    apply_(sqlite3.connect(paths.DB), rows)


if __name__ == "__main__":
    main()
