#!/usr/bin/env python3
"""阶段 6e 开跑**之前**修例句层的四类缺陷。vi，2026-10-03。

═══ 为什么这个脚本必须在花钱之前跑 ═══
6e 要买的就是「把 `example.text` 译成中文」。所以开跑前必须先问一句：
**`text` 里装的真是越南语例句吗？**

🔴🔴 **这是「花钱之前先逮到本层的缺陷」第二次兑现。** 第一次是 ko：1% 定价切片
   逮到 K15 —— 385 条谚语的「成分拆解」被当例句收了。那一次是切片逮到的；
   这一次**连切片都还没跑** —— 判据先量了一遍 `text` 自己。
   ⇒ ⭐ **要花钱加工某一列之前，先把那一列本身量一遍。**

═══ 四类 + 一类免费白捡 ═══
    ① 近义词/交叉引用元数据       53 条   隐藏 `metadata-not-example`
    ② 整条只有出处，正文缺失       24 条   隐藏 `citation-only`
    ③ 外语原文，源头没给越南语     111 条   隐藏 `source-has-no-vietnamese`
    ④ 出处串进 text 首行          202 条   首行搬进 `ref`（**仍可出版**）
    ⑤ 内嵌英译行          280 条 / 359 行   搬进 `example_gloss(en)`（**白捡**）

🔴 **判据一个都不在本文件里**，全部 import 自 `pipeline/stage6_sources.py` ——
   ko 建外锚闸时的那一跤：闸自己重写了一遍收割器的判据，于是同时更宽又更窄
   （`[[criteria-narrower-than-you-think]]`）。本文件只负责**搬**，不负责**判**。

═══ 🔴 ③ 不是「我们漏抽」，是源头缺 ═══
回 dump 逐条核过：kaikki 的 `text` 装着外语原文，`english` 装着英译，
而 `ref` 承诺的越南语译本**在 dump 里根本不存在**。
`tử ngữ` 的 `bold_text_offsets [[75, 88]]` 指向英文里的 "A dead language" ——
词头的引证是靠英文成立的。⇒ `[[dont-say-source-lerack-what-we-skipped]]`：
隐藏它、写明原因，**证据层一行不动**；哪天源头补了越南语正文就能放回来。

═══ ⑤ 为什么是「搬」不是「删」 ═══
281 条里 **262 条库里没有英译** ⇒ 剥掉就丢了英译。
⭐ 同一个形状在 ko 那门是「中文译文用全角空格挤在 text 同一格」，
  当时的动作也是搬不是删。⚠️ 但**判据不能复用**：韩语靠字形切得开，
  英语和越南语共用拉丁字母 —— 见 `split_inline_english` 的文档。

═══ 📋 有意不处理的一族（欠账 W16）═══
「越南语 + ` : ` + 法语释义」挤一格 **31 条**（`Nắng to : il fait grand soleil.`）。
它需要一个**政策决定**：法语尾巴丢掉还是留在证据层？三语方针说页面上不该有法语，
但那不是本轮用户批准的范围（批准的是「越南语正文缺失」那批）。
⇒ `is_not_vietnamese` 里的 `_mixed_vi_head` **显式放过它**，并记 W16。

用法：
    python3 -u vi/fixes/fix_example_defects.py            # 只报，不写
    python3 -u vi/fixes/fix_example_defects.py --apply    # 走写库闸门
"""
import argparse
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import dbtool                                             # noqa: E402
import paths                                              # noqa: E402
import stage6_sources as S6                               # noqa: E402

F = lambda n: format(n, ",")                              # noqa: E731


def plan(con):
    """→ (hide, ref_move, en_move)。**只读**，判据全部来自 S6。

    hide     [(example_id, hidden_why)]
    ref_move [(example_id, 出处, 新正文)]
    en_move  [(example_id, 新正文, [英译行…], 已有 en 译文的 rowid 或 None)]

    🔴🔴 **`tail_id` 不是「这条已经有英译了所以内嵌那行多余」。** 第一版我就是这么
       写的，而逐条比对 18 条**没有一条相同** —— 它们是同一段英译的**不同行**：
           id=17  内嵌 `The little guerrilla damsel holds her rifle high.`
                  库里 `The tall American dude totters, his head hanging low.`
       回 dump 核出来的是**源头的错位**：
           text    : 出处 ⏎ 越南语1 ⏎ 越南语2 ⏎ 英译1
           english : 英译2        ← 英译的**最后一行**单独进了字段，前面留在 text 里
       拼回去验得上：`Everyone has just one homeland,` ＋ `like their one and only
       mother.` 正好对 `Quê hương mỗi người chỉ một, / Như là chỉ một mẹ thôi.`
       ⇒ 动作是**把内嵌那几行接在已有 gloss 前面**，不是丢掉。
       按第一版会删掉 18 行真英译 —— `[[criterion-true-half-vouches-for-false-half]]`：
       「已有 en 译文」这半句是真的，于是给「所以内嵌那行是重复」那半句背了书，
       而后半句**一次都没验**。⇒ ⭐ 判「重复」必须真的比一次内容。
    """
    syl = S6.vi_syllables(con)
    tail = {}        # example_id → (gloss rowid, 已存的英译尾巴)
    for gid, eid, txt in con.execute(
            "SELECT id, example_id, text FROM example_gloss WHERE lang='en'"):
        tail.setdefault(eid, (gid, txt))
    hide, ref_move, en_move = [], [], []
    for eid, word, text, ref in con.execute(
            """SELECT e.id, d.word, e.text, e.ref FROM example e
               JOIN dict d ON d.id = e.word_id WHERE e.hidden = 0"""):
        why = S6.example_hidden_why(text, word, (), syl)
        if why:
            hide.append((eid, why))
            continue
        cite, body = S6.split_citation_prefix(text, syl)
        if cite:
            # 🔴 实测 202/202 条的 `ref` 都是空的。**但不许假设** ——
            #    `ref` 非空就跳过并大声报出来，覆盖一条正当出处比留着串位更坏。
            if (ref or "").strip():
                print("  ⚠️ id=%d 的 ref 非空，跳过搬运：%r" % (eid, ref[:60]))
                continue
            ref_move.append((eid, cite, body))
        else:
            body = text
        new_body, en = S6.split_inline_english(body)
        if en:
            en_move.append((eid, new_body, en, tail.get(eid)))
    return hide, ref_move, en_move


def report(con, hide, ref_move, en_move):
    from collections import Counter
    print("═══ ① ② ③ 隐藏 %s 条 ═══" % F(len(hide)))
    for why, n in Counter(w for _, w in hide).most_common():
        print("   %-28s %5d" % (why, n))
    print("\n═══ ④ 出处搬进 ref：%s 条 ═══" % F(len(ref_move)))
    for eid, cite, body in ref_move[:3]:
        print("   id=%-6d ref ← %r" % (eid, cite[:76]))
        print("            正文 = %r" % body.split("\n")[0][:76])
    print("\n═══ ⑤ 内嵌英译搬进 example_gloss：%s 条例句 / %s 行 ═══"
          % (F(len(en_move)), F(sum(len(e) for _, _, e, _ in en_move))))
    tails = [(eid, en, t) for eid, _b, en, t in en_move if t]
    print("   新建 gloss（库里原本没有英译，白捡）        %d 条" % (len(en_move) - len(tails)))
    print("   **接在已有英译前面**（源头把末行单独放了）  %d 条" % len(tails))
    for eid, body, en, t in en_move[:2]:
        print("   id=%-6d en ← %r" % (eid, en[0][:72]))
    for eid, en, (gid, txt) in tails[:2]:
        print("   id=%-6d en ← %r  ⊕  %r" % (eid, en[0][:46], txt[:40]))
    # 🔴 **读者口径**（`[[correct-steps-can-compose-a-hole]]`）：
    #    修完之后页面上还剩多少条带非越南语行 —— 这一条查的是展示层会 SELECT 的那一列。
    ids = {e for e, _ in hide}
    print("\n   修完后 `text` 里仍带非越南语行的可出版例句：%d 条（应为 0）"
          % sum(1 for eid, body, en, t in en_move
                if eid not in ids and S6.split_inline_english(body)[1]))


def apply_(con, hide, ref_move, en_move):
    """写库。**先取齐 undo 需要的一切** —— `[[fix-regression-and-gate]]` 那一跤：
    回归闸的变异 undo 用子查询去读已删除的行，真丢了一行释义。
    这里不删任何行，只 UPDATE ＋ INSERT，所以 dbtool 的备份即是 undo。
    """
    gloss_new = [(eid, "\n".join(en)) for eid, _b, en, t in en_move if not t]
    with dbtool.session(
        "fix-example-defects-6e",
        expect={
            # ① ② ③：hidden 0→1 并写 hidden_why
            "example.hidden_why": len(hide),
            # ④：ref 从空变非空
            "example.ref": len(ref_move),
            # ④⑤ 都改 text，但 text 本来就非空 ⇒ 非空计数不变（闸门数的是非空）
            # ⑤：新增 example_gloss 行（接在已有英译前面的那 18 条是 UPDATE，不新增行）
            "#example_gloss": len(gloss_new),
            "__rows__": 0,          # 🔴 example 表一行都不许增减
        },
        invalidates=[],   # 🔴 显式声明：不插新词形，覆盖率的分母不动
    ) as cur:
        for eid, why in hide:
            cur.execute("UPDATE example SET hidden=1, hidden_why=? WHERE id=?", (why, eid))
        for eid, cite, body in ref_move:
            new_body = S6.split_inline_english(body)[0]
            cur.execute("UPDATE example SET ref=?, text=? WHERE id=?", (cite, new_body, eid))
        moved_ref = {e for e, _, _ in ref_move}
        for eid, body, en, t in en_move:
            if eid not in moved_ref:
                cur.execute("UPDATE example SET text=? WHERE id=?", (body, eid))
            if t:
                # 🔴 源头把英译的**末行**单独放进 `english`，前面几行留在 `text`
                #    ⇒ 内嵌的接在**前面**。顺序不是随便定的，是 dump 的结构决定的。
                gid, txt = t
                cur.execute("UPDATE example_gloss SET text=? WHERE id=?",
                            ("\n".join(en) + "\n" + txt, gid))
            else:
                cur.execute(
                    "INSERT INTO example_gloss(example_id, lang, text, src) VALUES(?,?,?,?)",
                    (eid, "en", "\n".join(en), "en-edition"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    hide, ref_move, en_move = plan(con)
    report(con, hide, ref_move, en_move)
    con.close()
    if not a.apply:
        print("\n（只报不写。加 --apply 走写库闸门。）")
        return
    con = sqlite3.connect(paths.DB)
    apply_(con, hide, ref_move, en_move)


if __name__ == "__main__":
    main()
