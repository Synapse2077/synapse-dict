#!/usr/bin/env python3
"""盲测 A/B 逮到的 A5 回归 —— 我重写反而改坏的那两条。2026-08-28。

═══ 怎么发现的 ═══
A5 的第④道闸是「旧的判错、新的判对才替换」，但那两次判断**是同一个判官**下的
（`[[llm-as-evaluator-discipline]]` 第⑥条：谁写的不能由谁判）。
⇒ 抽 60 条旧新并排、**不说哪个是新的**（顺序按 `sense_id` 奇偶定），交两家盲判：

    v4-pro   新的胜 95%（57/60）  旧的胜 1  都不对 2
    豆包      新的胜 92%（55/60）  旧的胜 2  都不对 3

**两家都点名的回归只有一条，另一条一家点名。** 这两条都在「单词交叉引用臂」——
法语定义只有一个词，模型没有比上一轮更多的信息，只是**又猜了一次**。

    antidicot  FR `Antidicotylédone.`   旧 抗双子叶植物的   新 双子叶植物的  ← 丢了「抗」
    bomerie    FR `Bodinerie.`          旧 木器业          新 愚蠢行为      ← **两个都不对**

回源：`antidicotylédone` 在我们库里就是「抗双子叶植物的」；
`bodinerie` 在我们库里是「船舶抵押借款契约」（bottomry，海事借贷）——
`bomerie` 正是这个词的异体。⇒ 两条都能**确定性**给出正确值，不用再问模型。

═══ ⚪ 顺带否掉一个看起来很美的方案（`[[record-the-negative-decision]]`）═══
既然 97% 的单词交叉引用，其被引词就在我们库里且有中文，那**直接把被引词的中文抄过来**
不就全解决了？—— **不行，会改坏一大批。** 限定到「被引词只有一条可见义项」还剩 7,924 条，
其中 6,155 条与现值不同，打印出来一看：

    Week-end     现「周末」   ↔ 被引词「西姆卡汽车公司1955至1956年生产的敞篷车型」
    Treize       现「十三」   ↔ 被引词「姓氏」
    Petit        现「小的」   ↔ 被引词「佩蒂特（姓氏）」
    Mayonnaise   现「蛋黄酱」 ↔ 被引词「法国瓦尔省马永市镇的女居民」

法语定义句首**天然大写**，而大写词头在库里往往是**专名**（`[[case-folding-contaminates-columns]]`
那一族的反面）。现值全是对的，"解析"出来的全是错的。
⇒ **看着像确定性，其实是大小写陷阱。** 打印 12 条就看出来了，一行代码都没写。

用法（在 fr/ 目录下）：
    python3 -u fixes/fix_a5_ab_regressions.py            # 只报数
    python3 -u fixes/fix_a5_ab_regressions.py --apply
"""
import argparse
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import dbtool                                   # noqa: E402
import paths                                    # noqa: E402

# (词形, 法语定义, 现值, 应为, 依据)
FIX = [
    ("antidicot", "Antidicotylédone.", "双子叶植物的", "抗双子叶植物的",
     "库里 `antidicotylédone` 自己的中文就是「抗双子叶植物的」；两家盲测都点名"),
    ("bomerie", "Bodinerie.", "愚蠢行为", "船舶抵押借款契约",
     "库里 `bodinerie` 的中文是「船舶抵押借款契约」（bottomry 海事借贷）；旧值「木器业」同样不对"),
]


def plan(con):
    out = []
    for w, fr, now, want, why in FIX:
        for sid, cur in con.execute(
                "SELECT s.id, (SELECT text FROM sense_gloss WHERE sense_id=s.id "
                "  AND lang='zh' ORDER BY seq LIMIT 1) "
                "FROM sense s JOIN dict d ON d.id=s.word_id "
                "WHERE d.word=? AND s.hidden=0 AND EXISTS("
                "  SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='fr' "
                "    AND g.text=?)", (w, fr)):
            out.append((sid, w, cur, want, why, cur == now))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = plan(con)
    con.close()
    print("■ 待改 %d 条" % len(rows))
    for sid, w, cur, want, why, matched in rows:
        print("   %s #%-7s %-11s %s → %s\n        依据：%s"
              % ("✅" if matched else "⚠️ 现值与记录的不符，跳过", sid, w, cur, want, why))
    todo = [(want, sid) for sid, w, cur, want, why, matched in rows if matched]
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not todo:
        print("🔴 没有可改的（现值与记录的不符 ⇒ 已经被别的脚本动过，先回头查）")
        return 1
    with dbtool.session("keep-v3-a5-ab-regressions", expect={}) as s:
        s.executemany(
            "UPDATE sense_gloss SET text=?, src='manual:ab-fix' "
            "WHERE sense_id=? AND lang='zh' AND seq=("
            "  SELECT MIN(seq) FROM sense_gloss WHERE sense_id=? AND lang='zh')",
            [(t, i, i) for t, i in todo])
    print("✓ 改 %d 条" % len(todo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
