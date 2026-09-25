#!/usr/bin/env python3
"""阶段 6d 开跑前：把**不是例句的行**标出来。2026-09-24。

═══ 怎么发现的 ═══
1% 定价切片跑完，形状检查报「坏 11/334」。**逐条读**下去：
  · 「混进谚文」5 条**全是对的** —— `'마개'的词根是'막(다)'`：韩文是**被讨论的对象**，
    译掉就毁了句子。汉字词表（`白骨/백골、…`）同理。判据太宽。
  · 「只译了词头」6 条里 3 条是长度启发式的假阳性（`강렬한 빛. → 强烈的光。` 没毛病）
  · 🔴 **另外 3 条是真缺陷，而且不在译文里，在例句层本身。**

═══ 两类，各自的机制（回源逐条看的，不是猜的）═══
① **多词词条的成分拆解**（339 条）
   韩文版给谚语/惯用句词条，把**构成它的那些词**塞进了 `examples[]`：
       词条 `가난한 놈은 성도 없나`  examples: 가난하다 / 놈은 / 성도 / 없다
       词条 `구렁이 담 넘어가듯`    examples: <一条真例句> / 구렁이 / 담 / 넘어가다 / 듯
   那是**词条拆解，不是例句**。原样印在页面上，读者会看到
   「例句：없다」挂在一条谚语下面。
② **占位标签**（46 条）
   `예문`（＝"例句"）34 条、`음성 듣기`（＝"听语音"，是个 UI 按钮）9 条、
   `속담`（＝"谚语"）3 条 —— 源头这一格**本来就没有内容**，只有标签本身。
   ⚠️ 它们躲过了收割器的 `LABEL_KEEP` 剥离，因为**后面没有冒号**（`예문:` 才会被剥）。

═══ 判据怎么定的（两版，第二版才站得住）═══
第一版「词头有空格 且 正文无空格」命中 330。我拿**第二个独立信号**
（正文的词干出现在词头里）去验，只有 68.2% 吻合 ——
🔴 **但那 105 条"不一致"逐条读完，104 条仍然是成分拆解**：
   韩语用言词干会变形（`뛰는`→`뛰다`、`옴쳐야`→`옴치다`、`공든`→`공들다`），
   **是第二个信号坏，不是第一个信号错**。
   ⇒ `[[verify-before-claiming-confirmed]]`：两个信号不一致时，先问哪个信号更可信，
     别默认"不一致＝有假阳性"。
反方向也查了：漏掉 4 条**带空格的成分**（`삼 년`、`방귀 뀌다`、`식후 구경`）。
⇒ 第二版按含义写：**多词词条 ＋ 没有句末标点 ＋ ≤2 个词 ＋ ≤10 字**。
   命中 339，比第一版 **+9 −0**（多的 9 条全打出来读过：`먹다 보다`、`배, 산`、`들(1, 2)`）。
⭐ **反方向验过**：多词词头下**没被判为成分**的 293 条抽 18 条读，**全是真句子**
   （`무릎을 치다 → 희소식을 들은 김 씨는 무릎을 탁 치고서 환호했다.`）。零误伤。

═══ 🔴 为什么加 `hidden_why` 而不是直接标 `hidden=1` ═══
`hidden` 这一列**已经背了两种意思**：多行挤成一格的 blob 117 条、
K11 的构词公式 290 条。再塞第四种，展示层与验收就分不开"为什么不显示"。
⇒ 加一列 `hidden_why`，并**回填已有的 407 条**（判据：多行 ⇒ `crammed`，
  单行含 `→` ⇒ `构词公式`，实测 290/290 含 `→`、117 条多行里只有 1 条含）。
  `[[ipa-provenance-columns]]`：**来源/原因会变的字段才加列**。

═══ ⚠️ 不删，只标 ═══
成分拆解**是有信息的**（谚语 ↔ 它的构成词，那是关系层的料），
占位标签则是源头的空格子。两类都留在库里 —— 用户 2026-09-24 定过调
「我倾向保留数据，用不用另一回事」。⇒ 落账 **K15**：成分拆解可以进关系层。

跑（在仓库根）：
    python3 -u ko/pipeline/fix_nonexample_rows.py
    python3 -u ko/pipeline/fix_nonexample_rows.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import re
import sqlite3

import dbtool
import paths

f = lambda n: format(n, ",")

# 句末标点 —— 有它就是句子。**这是含义判据**：例句是句子，成分是词。
END = re.compile(r"[.!?。！？…]\s*$")
# 源头那一格只有标签、没有内容的几种写法。**穷举，不用前缀匹配** ——
# 前缀匹配会把 `예문: 나는 간다` 这种真例句一起圈进来（那种收割器已经剥过了）。
PLACEHOLDER = {"예문", "음성 듣기", "속담"}


def is_breakdown(word, text):
    """这条"例句"是不是**多词词条的成分拆解**。

    🔴 判据按含义写：
      · `' ' in word`      —— 单词词条没有"成分"可拆，谈不上拆解
      · 没有句末标点        —— 例句是句子，句子有句末标点；成分是词，没有
      · ≤2 个词 且 ≤10 字   —— 成分是一个词典词（`다 시키다` 这种带助词的占两个位）
    ⚠️ **不用"正文里有没有空格"**：那是形式代理，会漏掉 `삼 년`/`방귀 뀌다` 这 4 条。
    """
    if " " not in word:
        return False
    if END.search(text):
        return False
    return len(text.split()) <= 2 and len(text) <= 10


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--show", type=int, default=12)
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute(
        "SELECT id, word, text, hidden FROM example").fetchall()
    # 已经 hidden 的两类，回填原因
    back_crammed = [r[0] for r in rows if r[3] and "\n" in r[2]]
    back_formula = [r[0] for r in rows if r[3] and "\n" not in r[2]]
    # 本步新标的两类（只看还没 hidden 的）
    brk = [r for r in rows if not r[3] and is_breakdown(r[1], r[2])]
    plc = [r for r in rows if not r[3] and r[2].strip() in PLACEHOLDER]
    # 🔴 两类可能重叠（`속담` 在多词词条下）⇒ 按 id 去重，占位标签优先记原因
    plcids = {r[0] for r in plc}
    brk = [r for r in brk if r[0] not in plcids]

    print("■ 例句 %s 条（其中已 hidden %s）"
          % (f(len(rows)), f(sum(1 for r in rows if r[3]))))
    print("   回填原因：crammed（多行 blob） %s ／ 构词公式（K11） %s"
          % (f(len(back_crammed)), f(len(back_formula))))
    print("   🔴 本步新标：成分拆解 %s ／ 占位标签 %s"
          % (f(len(brk)), f(len(plc))))
    print("\n■ 成分拆解抽样")
    for r in brk[:a.show]:
        print("   词头 %-26s → %s" % (r[1][:26], r[2][:32]))
    print("■ 占位标签抽样")
    for r in plc[:6]:
        print("   词头 %-26s → %r" % (r[1][:26], r[2]))

    left = sum(1 for r in rows
               if not r[3] and r[0] not in plcids
               and not is_breakdown(r[1], r[2]))
    print("\n■ 本步之后**要翻译的例句**：%s 条（原来 %s，省下 %s）"
          % (f(left), f(sum(1 for r in rows if not r[3])),
             f(len(brk) + len(plc))))
    con.close()
    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return

    with dbtool.session(
            "ko-mark-nonexample-rows",
            expect={"example.hidden_why": len(back_crammed) + len(back_formula)
                                          + len(brk) + len(plc),
                    "example.hidden": len(brk) + len(plc)},
            invalidates=[
                "阶段 6d 待译例句数变了（本步标掉的不译）",
                "例句中文覆盖率的分母（`coverage.py` 与账的闸都按 hidden=0 算）",
                "外锚闸 `verify_layers_vs_dump.py`：它按 (word,text) 比，hidden 不参与 ⇒ 不受影响",
            ]) as s:
        s.execute("ALTER TABLE example ADD COLUMN hidden_why TEXT")
        s.executemany("UPDATE example SET hidden_why='crammed' WHERE id=?",
                      [(i,) for i in back_crammed])
        s.executemany("UPDATE example SET hidden_why='构词公式' WHERE id=?",
                      [(i,) for i in back_formula])
        s.executemany(
            "UPDATE example SET hidden=1, hidden_why='词条成分拆解' WHERE id=?",
            [(r[0],) for r in brk])
        s.executemany(
            "UPDATE example SET hidden=1, hidden_why='占位标签' WHERE id=?",
            [(r[0],) for r in plc])

    print("\n═══ 写后回核（从库里重算，不用上面任何一个 len）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        # 🔴 期望值**独立声明**：hidden 的每一行都得说得出原因
        ("hidden 的行全都有原因",
         q("SELECT COUNT(*) FROM example WHERE hidden=1 AND hidden_why IS NULL"), 0),
        ("没 hidden 的行没有原因",
         q("SELECT COUNT(*) FROM example WHERE COALESCE(hidden,0)=0 "
           "AND hidden_why IS NOT NULL"), 0),
        ("hidden 总数", q("SELECT COUNT(*) FROM example WHERE hidden=1"),
         sum(1 for r in rows if r[3]) + len(brk) + len(plc)),
        # 🔴 反向闸：**不该动的一条都没动** —— 多词词头下的真句子还在
        ("多词词头下的真例句一条没少",
         q("SELECT COUNT(*) FROM example WHERE COALESCE(hidden,0)=0 "
           "AND word LIKE '% %'"),
         sum(1 for r in rows if not r[3] and " " in r[1]
             and not is_breakdown(r[1], r[2]) and r[0] not in plcids)),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-30s %9s（期望 %s）" % ("✅" if good else "🔴", name,
                                             f(got), f(want)))
    print("\n■ 按原因分布")
    for r in con.execute("SELECT hidden_why, COUNT(*) FROM example "
                         "WHERE hidden=1 GROUP BY 1 ORDER BY 2 DESC"):
        print("   %-16s %6s" % (r[0], f(r[1])))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
