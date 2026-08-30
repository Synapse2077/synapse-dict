#!/usr/bin/env python3
"""阶段 1.5 收尾：把**变位指针**从出版层隐掉（它们归变形层）。2026-08-30。

═══ 怎么发现的 ═══
1.5b 翻译落库后**回归闸 A2 报红**：4,634 条出版义项没有中文。
逐条读完不是翻译漏了，是 **1.5a 收进来的一批"释义"根本不是释义** ——
葡语版把大量指针写成**散文**，而我 1.5a 只过滤了结构化的 `form_of`/`alt_of`：

    rosasse    → "terceira pessoa do singular do pretérito do subjuntivo do verbo rosar"
    poetizemos → "primeira pessoa do plural do imperativo afirmativo do verbo poetizar"

═══ 🔴 判据被反向查打回过一次 ═══
第一版判据是「指针句式」，一把抓了 `o mesmo que` / `sigla de` 这些。
**反向查（判据命中但模型给了中文的）立刻打回：1,338 条会被误伤**——

    ALALC       "sigla de Aliança Latino-Americana de Livre Comércio" → 拉丁美洲自由贸易协会
    Antárctica  "o mesmo que Antártida"                              → 南极洲

查 `Antárctica` 的读者要的是「南极洲」，不是空行。
⇒ **「指针句式」不等于「该隐藏」**，分界在**指向什么**：

    变位指针     指向某动词的某个语法形式   → 归变形层，隐掉      误伤面 **6**
    交叉引用     指向另一个**实词**         → 该补中文，不是隐掉  误伤面 **1,379**

本脚本**只处理变位指针那一族**。交叉引用那族进收尾单（它们能从库里
免费取到被引词的中文，是补不是删）。

⚠️ 那 6 条"有中文的变位指针"本身就是错的（`regravar` → 「我将重新录制」——
   把变位指针当句子翻了），一并隐掉。

用法（在 pt/ 目录下）：
    python3 fixes/hide_conjugation_pointers.py
    python3 fixes/hide_conjugation_pointers.py --apply
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

# 判据只在这一处。**按含义**：这句话描述的是「某动词的某个语法形式」。
CONJ = re.compile(
    r"^\s*((primeira|segunda|terceira)\s+(e\s+\w+\s+)?pessoas?\b"
    r"|infinitivo pessoal|particípio|gerúndio|plural pessoa)", re.I)


def plan(con):
    return [(sid, w, t, zh) for sid, w, t, zh in con.execute(
        "SELECT s.id, d.word, g.text,"
        "       (SELECT z.text FROM sense_gloss z WHERE z.sense_id=s.id AND z.lang='zh')"
        "  FROM sense s JOIN dict d ON d.id=s.word_id"
        "  JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='pt'"
        " WHERE COALESCE(s.hidden,0)=0") if CONJ.match(t)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    todo = plan(con)
    con.close()
    withzh = [r for r in todo if r[3]]
    print("■ 变位指针（要隐掉）：%s 条" % format(len(todo), ","))
    print("   其中模型给了中文的 %d 条 —— **那些中文本身是错的**，一并隐掉：" % len(withzh))
    for _s, w, t, zh in withzh[:8]:
        print("      %-16s %-44s → %s" % (w[:16], t[:44], zh[:24]))
    print("\n── 抽样 8 条 ──")
    for _s, w, t, _z in todo[:8]:
        print("   %-20s %s" % (w[:20], t[:66]))
    if not todo or not a.apply:
        print("\n(未加 --apply，不写库)" if todo else "\n✓ 没有要改的")
        return 0
    with dbtool.session("fix-pt-hide-conj-pointers", expect={}) as s:
        s.executemany("UPDATE sense SET hidden=1 WHERE id=?", [(r[0],) for r in todo])
    print("\n✓ 已隐掉 %s 条（**数据没删**，`hidden=1`，随时可revert）" % format(len(todo), ","))
    return 0


if __name__ == "__main__":
    sys.exit(main())
