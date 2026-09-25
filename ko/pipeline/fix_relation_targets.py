#!/usr/bin/env python3
"""修 `sense_relation.target` 里**塞了句子而不是词**的行。ko，2026-09-25（阶段 9）。

═══ 怎么发现的 ═══
阶段 9 写 `dict-labels/src/ko.ts` 时，我给 `dialectal` 写了「方言」这个标签，
随手看了眼样本：

    쉬리 → `of 쉬다`        tags=["future","poetic"]     ← 这不是方言关系
    페루 공화국 → `gonghwaguk`                            ← 目标是罗马字

顺着查下去，发现 `target` 这一列里混着**整段释义**：

    proverb  속담: 가늘게 먹고 가는 똥 싸라 : 지나치게 욕심을 부리지 말라는 뜻.
    related  길거리에 임시로 물건을 벌여 놓고 파는 곳.\\n:* 그 거리에는 노상 가게가…
    derived  恩惠 : grace

⭐ **逮到它的不是闸，是写展示层标签表时看了一眼数据。**
   `[[it-display-layer-stage8]]`：接上展示层是独立一道闸。
   我差一点就给这些行印上「方言」「谚语」的标签，让一段释义冒充一个可点的词。

═══ 三类，判据与处置各不相同 ═══
    A 可修   `恩惠 : grace` / `-부터: from`   ⇒ **取冒号左边**   1,574 条
    B 不可修 整段释义（含例句、换行）塞进 target ⇒ 删            442 条
    C 纯标签 target 就是 `속담`/`관용구`/`참고` 这几个词 ⇒ 删       76 条

🔴 **「取左边」是我的判断，不能自说自话 —— 验过才用**：
   切出来的左半边 **94.6%（1,574/1,663）是库里真实存在的词头**。
   剩下 89 个不在库里，但**仍是合法词形**（`나모 닷`、`鍼灸`、`낯이 간지럽다`）——
   关系指向未收录词在本库是正常的（服务层用 `ok` 标记它点不动）。
   ⚠️ 例外：维基**命名空间前缀**（`부록:…`＝附录、`위키낱말사전:…`）切完剩下的是
     命名空间名不是词 ⇒ **归 B 删掉**，不归 A。

═══ ⚠️ 为什么不顺手把 `dialectal` 那 75 条也处理了 ═══
它们**目标字段没坏**，坏的是 kind 判得对不对（`쉬리 → of 쉬다` 标成 dialectal）。
那是另一件事、另一条判据，**这一步不碰** —— 落账 **K19**。
`[[one-problem-at-a-time]]`：一个一个问题来。

跑（在仓库根）：
    python3 -u ko/pipeline/fix_relation_targets.py
    python3 -u ko/pipeline/fix_relation_targets.py --apply
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
from build_inflection_layer import is_korean_form

f = lambda n: format(n, ",")

SPLIT = re.compile(r"\s*[:：]\s*")
# 维基命名空间前缀：切完剩下的是命名空间名，不是词
NAMESPACE = {"부록", "위키낱말사전", "분류", "틀", "도움말", "Appendix", "Wiktionary",
             "Category", "Template"}
# 目标就是这几个**标签词本身**，源头那一格没有内容（与 K15 的 `예문` 同形）
LABEL_ONLY = {"속담", "관용구", "참고", "예문", "유의어", "반의어", "파생어",
              "관련어", "동의어", "비슷한말"}


# 句末标点 —— 有它就是句子，不是词
SENT = re.compile(r"[.。!！?？]\s*$")


def is_wordish(t):
    """这串**能不能当一个关系目标**（一个词，不是一句话）。

    🔴 判据按含义写，不用 `is_korean_form`：那条是给**变形词形**用的，
       它不认括号 —— 而 ko 的词头**惯例上就带汉字括注**（`아(A)`、`거간(居間)군`、
       `번(番)째`）。拿它来判关系目标，会把合法词头判成"整段释义"。
       ⚠️ 同一条判据用错地方 —— `[[criteria-narrower-than-you-think]]` 里
         「import 对了不等于用对了」的同一个形状。
    ⇒ 三条：有谚文或汉字 · 没有句末标点 · 不太长。
    """
    if not t or len(t) > 24:
        return False
    if SENT.search(t):
        return False
    return any("가" <= ch <= "힣" or dbtool.has_han_char(ch) for ch in t)


# 🔴 汉字那一族的目标**天然就是一个谚文词**，哪怕那个词恰好也被源头当标签用。
#    `俗談 --hangeul--> 속담` 是对的：俗談 就是 속담 的汉字表记。
#    第一版没分 kind，把这 20 条一起删了 ⇒ **回归闸当场报出 6 个新空白页**
#    （`俗談`/`參考`/`慣用句`/`類義語`… 失去唯一的链）。已回滚。
#    ⚠️ `속담` 既是源头用的标签，**也是一个真词** —— 判据必须把这两件事分开。
HANJA_KINDS = {"hangeul", "hanja_form_of", "hanja_spelling", "alt_hanja"}


def classify(target, kind=None):
    """→ ('keep', None) / ('fix', 新目标) / ('drop', 原因)

    🔴🔴 **两种形状，取的段不一样 —— 我把它们混成一条判据，当场改坏了 1,231 行。**

        恩惠 : grace                          目标 : 释义      ⇒ 取**第一段**
        속담: 가늘게 먹고 가는 똥 싸라 : …뜻.    标签 : 目标 : 释义 ⇒ 取**第二段**

    第一版无脑取第一段，于是把 `속담`（"谚语"这个标签词）当成了关系目标，
    把真正的谚语扔了。写后回核报「1,231 条目标是纯标签词」逮到，**已回滚重来**。
    ⚠️ 教训不是"多写一个分支"，是：**看见分隔符先问它分开的是什么**，
      别默认"左边是主体"。`[[criteria-narrower-than-you-think]]`。
    """
    t = (target or "").strip()
    if not t:
        return "drop", "目标是空的"
    if t in LABEL_ONLY and kind not in HANJA_KINDS:
        return "drop", "目标是纯标签词，源头那一格没有内容"
    # 带换行 ⇒ 整段正文塞进来了，**与有没有冒号无关**
    if "\n" in t:
        return "drop", "整段释义/例句塞进了 target"
    if ":" not in t and "：" not in t:
        return "keep", None

    segs = [x.strip() for x in SPLIT.split(t) if x.strip()]
    if not segs:
        return "drop", "切开之后什么都不剩"
    if segs[0] in NAMESPACE:
        return "drop", "维基命名空间前缀，不是词"
    # 🔴 第一段是标签词 ⇒ 真正的目标在第二段
    pick = segs[1] if (segs[0] in LABEL_ONLY and len(segs) > 1) else segs[0]
    if (pick in LABEL_ONLY and kind not in HANJA_KINDS) or pick in NAMESPACE:
        return "drop", "切完仍然只是个标签词"
    if not is_wordish(pick):
        return "drop", "整段释义/例句塞进了 target"
    return ("keep", None) if pick == t else ("fix", pick)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute("SELECT id, kind, target FROM sense_relation").fetchall()
    indict = {r[0] for r in con.execute("SELECT word_norm FROM dict")}
    n_before = len(rows)
    # 🔴 写**之前**取基线。下面那条反向闸原来写的是 `q(...) > 0` —— 恒真，
    #    一条永远通过的检查等于没检查（`[[expectation-must-be-declared]]`）。
    resolvable_before = con.execute(
        "SELECT COUNT(*) FROM sense_relation r WHERE EXISTS("
        "SELECT 1 FROM dict d WHERE d.word_norm = r.target)").fetchone()[0]

    # 🔴 切完之后可能**与已有的正确关系重了** —— `恩惠 : grace` → `恩惠`，
    #    而 `恩惠` 这条边本来就在。第一版直接 UPDATE，写库闸门当场 rollback
    #    （UNIQUE(word_id, sense_id, kind, target)）。
    #    ⇒ 重了就**删**不是改：信息已经在库里，留着是重复不是修复。
    #    ⚠️ 不用 `UPDATE OR IGNORE` —— 那会把坏行**静默留下**，
    #      而闸报的行数还对得上（`[[fix-regression-and-gate]]` 的假绿形状）。
    have = {(r[0], r[1], r[2], r[3]) for r in con.execute(
        "SELECT word_id, COALESCE(sense_id,-1), kind, target FROM sense_relation")}
    keyof = {r[0]: (r[1], r[2] if r[2] is not None else -1, r[3]) for r in con.execute(
        "SELECT id, word_id, sense_id, kind FROM sense_relation")}

    fixes, drops = [], []
    for rid, kind, target in rows:
        act, val = classify(target, kind)
        if act == "fix":
            wid, sid, k = keyof[rid]
            if (wid, sid, k, val) in have:
                drops.append((rid, kind, target, "切完与已有的正确关系重复"))
            else:
                have.add((wid, sid, k, val))
                fixes.append((rid, kind, target, val))
        elif act == "drop":
            drops.append((rid, kind, target, val))

    hit = sum(1 for _r, _k, _t, v in fixes if v in indict)
    print("■ 关系边 %s" % f(n_before))
    print("   改目标 %s 条（切冒号左边）" % f(len(fixes)))
    print("     其中左半边**是库里真实词头**的 %s = %.1f%%  ← 这是切法站得住的凭据"
          % (f(hit), 100.0 * hit / max(len(fixes), 1)))
    print("   删 %s 条" % f(len(drops)))
    import collections
    for why, n in collections.Counter(v for *_x, v in drops).most_common():
        print("     %-32s %s" % (why, f(n)))

    print("\n■ 改的样本")
    for _r, k, t, v in fixes[:8]:
        print("   %-14s %-44s → %s" % (k, t[:44].replace("\n", "⏎"), v))
    print("■ 删的样本")
    for _r, k, t, v in drops[:6]:
        print("   %-14s %-44s   （%s）" % (k, t[:44].replace("\n", "⏎"), v))

    # 🔴 反向：**没被碰的那批**必须仍然干净 —— 抽查它们不含冒号
    untouched = n_before - len(fixes) - len(drops)
    still = con.execute(
        "SELECT COUNT(*) FROM sense_relation WHERE target LIKE '%:%' OR target LIKE '%：%'"
    ).fetchone()[0]
    print("\n   没碰的 %s 条；库里现有带冒号的 %s（应当全部落在改/删两堆里：%s）"
          % (f(untouched), f(still), f(len(fixes) + len([d for d in drops if ":" in d[2] or "：" in d[2]]))))
    con.close()

    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return

    with dbtool.session(
            "ko-fix-relation-targets",
            expect={"#sense_relation": -len(drops),
                    "sense_relation.target": -len(drops)},
            invalidates=[
                "关系层行数变了：`test_plan_ledger` 阶段 2/6 的交付物计数",
                "外锚闸不受影响（关系层不在那三层里），但**阶段 6b 的边数会变**",
            ]) as s:
        s.executemany("UPDATE sense_relation SET target=? WHERE id=?",
                      [(v, rid) for rid, _k, _t, v in fixes])
        s.executemany("DELETE FROM sense_relation WHERE id=?",
                      [(rid,) for rid, *_x in drops])

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("关系边总数", q("SELECT COUNT(*) FROM sense_relation"), n_before - len(drops)),
        # 🔴 改完之后**不许再有带冒号的目标** —— 这是本步的定义
        ("目标里不再有冒号",
         q("SELECT COUNT(*) FROM sense_relation WHERE target LIKE '%:%' "
           "OR target LIKE '%：%'"), 0),
        ("目标里不再有换行",
         q("SELECT COUNT(*) FROM sense_relation WHERE target LIKE '%' || char(10) || '%'"), 0),
        # 🔴 期望不是 0：汉字族那 20 条**有意保留**（`俗談 --hangeul--> 속담` 是对的）。
        #    判据要把 kind 写进来，否则这条回核就是在否定上面刚做对的决定。
        ("目标是纯标签词的（汉字族之外，应为 0）",
         q("SELECT COUNT(*) FROM sense_relation WHERE TRIM(target) IN (%s)"
           " AND kind NOT IN (%s)"
           % (",".join("'%s'" % x for x in LABEL_ONLY),
              ",".join("'%s'" % x for x in HANJA_KINDS))), 0),
        # 🔴 反向闸：改完之后**指得到库里词头的边应该变多** ——
        #    删掉 660 条坏行会让这个数降，而修好 1,531 条会让它升，
        #    净效果必须是升（94.3% 的左半边是真词头）。这是"修对了"的正面证据，
        #    不是"没报错"。
        ("指得到库里词头的边（写前 %s）" % f(resolvable_before),
         q("SELECT COUNT(*) FROM sense_relation r WHERE EXISTS("
           "SELECT 1 FROM dict d WHERE d.word_norm = r.target)")
         > resolvable_before, True),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-34s %10s（期望 %s）" % ("✅" if good else "🔴", name,
                                              f(got) if isinstance(got, int) else got,
                                              f(want) if isinstance(want, int) else want))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
