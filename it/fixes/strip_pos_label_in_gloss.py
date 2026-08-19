#!/usr/bin/env python3
"""释义正文里带着词性标签：`种族灭绝的（形容词）`。2026-08-16。

═══ 是什么 ═══
翻译 prompt 有一条明令「不要出现词性标签」，但仍漏了一批：

    genocida     [adj]  种族灭绝的（形容词）
    CC           [abbr] 民法典（缩写）
    cheniano     [n]    肯尼亚人（名词）

用户在页面上本来就看得到词性（分组标题「形容词」「缩写」），正文里再写一遍
纯属噪声，还挤占了本该放**区分信息**的括号。

═══ 判据：位置 + 与本义项词性相同 ═══
🔴 括号里的词类名不一定是标签，也可能是**这条释义适用于什么**：

    coniugare    [v]    给（动词）变位          ← 「动词」是宾语，合法
    coniugato    [adj]  （动词）变位的          ← 限定语，且词类≠本义项词性
    intransitivo [adj]  (动词)不及物的          ← 同上

⇒ 两个条件同时成立才算泄漏：
   ① 括号里的词类**等于本义项自己的词性**（`genocida` 是 adj，写「（形容词）」）
   ② 位置在**串尾** —— 合法的限定语都在前面或中间，标签才挂在末尾

实测 80 条命中条件①，剥掉 74 条。剩 6 条我逐条读过、留着：
   · `coniugare/coniugarsi/coniugandosi` 的「（动词）」是宾语/限定语，不动
   · `bronzo`×2、`mulino`「（动词）我磨碎…」是**另一族缺陷**
     （变形描述被当成了义项，且没说是哪个词的变形），本步不碰，记在这里
   · 头部确是标签的两条（`ei`「（冠词）i 的变体」、`minchia`「（感叹词）妈的，见鬼」）
     逐条读过后写进 `HEAD_OK` 放行 —— 头部不做通用规则，因为那里多是合法限定语

用法（在 it/ 目录下）：
    python3 fixes/strip_pos_label_in_gloss.py
    python3 fixes/strip_pos_label_in_gloss.py --apply
    python3 fixes/strip_pos_label_in_gloss.py --verify
    python3 fixes/strip_pos_label_in_gloss.py --mutate
"""
import argparse
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402

TAG = "+fix:pos-label"

# 中文词类名 → 展示层短码（`packages/dict-labels` 的 POS_LABELS 的反向）
LAB = {"名词": "n", "动词": "v", "形容词": "adj", "副词": "adv", "介词": "prep",
       "连词": "conj", "代词": "pron", "感叹词": "intj", "数词": "num",
       "冠词": "art", "短语": "phr", "缩写": "abbr"}
TAIL = re.compile(r"\s*[（(](%s)[）)]\s*$" % "|".join(LAB))
# 头部的标签：只放行逐条读过的，不做通用规则（头部多是合法限定语）
HEAD_OK = {"（冠词）i 的变体", "（感叹词）妈的，见鬼"}
HEAD = re.compile(r"^\s*[（(](%s)[）)]\s*" % "|".join(LAB))


def strip_label(text, pos):
    """→ 剥掉词性标签后的文本；None 表示不该剥。"""
    m = TAIL.search(text or "")
    if m and LAB[m.group(1)] == pos:
        out = TAIL.sub("", text).strip()
        return out or None
    if (text or "").strip() in HEAD_OK:
        m = HEAD.match(text)
        if m and LAB[m.group(1)] == pos:
            return HEAD.sub("", text).strip() or None
    return None


def plan(con):
    rows, st = [], Counter()
    for w, sid, t, pos in con.execute(
            "SELECT d.word, s.id, g.text, COALESCE(s.pos, e.pos) FROM sense_gloss g "
            "JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id "
            "LEFT JOIN entry e ON e.id=s.entry_id "
            "WHERE g.lang='zh' AND g.seq=0 AND COALESCE(s.hidden,0)=0"):
        new = strip_label(t, pos)
        if new and new != t:
            rows.append((sid, w, t, new))
            st["✅ 剥掉尾部词性标签"] += 1
    return rows, st


def residual(con):
    """闸的判据：还有几条释义带着与本义项词性相同的标签（头/中/尾都算）。"""
    out = []
    any_lab = re.compile(r"[（(](%s)[）)]" % "|".join(LAB))
    for w, t, pos in con.execute(
            "SELECT d.word, g.text, COALESCE(s.pos, e.pos) FROM sense_gloss g "
            "JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id "
            "LEFT JOIN entry e ON e.id=s.entry_id "
            "WHERE g.lang='zh' AND g.seq=0 AND COALESCE(s.hidden,0)=0"):
        m = any_lab.search(t)
        if m and LAB[m.group(1)] == pos:
            out.append((w, t, "尾" if m.end() == len(t) else ("头" if m.start() == 0 else "中")))
    return out


def gate(con):
    print("\n═══ 闸 ═══")
    left = residual(con)
    tail = [x for x in left if x[2] == "尾"]
    rows, _ = plan(con)
    checks = [
        ("🔴 串尾不许再有与本义项词性相同的标签", len(tail), 0),
        ("🔴 没有还能剥却没剥的", len(rows), 0),
        # 🔴 已接受基线 6 + 理由（逐条读过）：`coniugare/coniugarsi/coniugandosi` 的
        #    「（动词）」是宾语/限定语；`bronzo`×2 和 `mulino` 是**另一族缺陷**
        #    ——变形描述被当成了义项，而且没说是哪个词的变形，本步不碰。
        #    **基线只减不增**，这里写 == 是为了涨了立刻红。
        ("头/中位置的（已读过：限定语或另案，基线 6）", len(left) - len(tail), 6),
        ("🔴 剥完不许留下空串或悬空标点",
         sum(1 for (t,) in con.execute(
             "SELECT text FROM sense_gloss WHERE src LIKE ?", ("%" + TAG,))
             if not t.strip() or t.strip()[-1] in "，,；;（("), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-44s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    for w, t, at in left[:10]:
        print("     · [%s] %-16s %s" % (at, w[:16], t[:46]))
    return ok


def mutate():
    print("\n═══ 变异验证 ═══")
    cases = [
        ("尾部标签、词性相同 ⇒ 剥", "种族灭绝的（形容词）", "adj", "种族灭绝的"),
        ("尾部标签、缩写 ⇒ 剥", "民法典（缩写）", "abbr", "民法典"),
        ("🔴 词性不同 ⇒ 不剥（是限定语）", "（动词）变位的", "adj", None),
        ("🔴 中间位置 ⇒ 不剥（是宾语）", "给（动词）变位，发生屈折变化", "v", None),
        ("🔴 头部未逐条读过 ⇒ 不剥", "（动词）第一人称单数现在时形式", "v", None),
        ("头部、逐条读过 ⇒ 剥", "（冠词）i 的变体", "art", "i 的变体"),
        ("🔴 括号里不是词类名 ⇒ 不剥", "半场（足球等比赛的）", "n", None),
        ("🔴 剥完会变空 ⇒ 不剥", "（名词）", "n", None),
    ]
    ok = True
    for name, t, pos, want in cases:
        got = strip_label(t, pos)
        good = got == want
        ok &= good
        print("   %s %-30s %-26s → %s" % ("✅" if good else "🔴", name, t[:26], got))
    print("\n   变异验证 %s" % ("通过" if ok else "🔴 判据有问题"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("apply", "verify", "mutate"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    rows, st = plan(ro)
    for k, v in st.most_common():
        print("   %-36s %7s" % (k, f"{v:,}"))
    print("\n■ 将剥 %s 条\n" % f"{len(rows):,}")
    for _sid, w, old, new in rows[:16]:
        print("   %-18s %-34s → %s" % (w[:18], old[:34], new[:34]))
    ro.close()
    if not a.apply or not rows:
        print("\n(未加 --apply，不写库)" if not a.apply else "")
        return 0
    with dbtool.session("strip-pos-label", expect={"#sense_gloss": 0}) as s:
        s.executemany(
            "UPDATE sense_gloss SET text=?, src=COALESCE(src,'unknown')||? "
            "WHERE sense_id=? AND lang='zh' AND seq=0",
            [(new, TAG, sid) for sid, _w, _o, new in rows])
    print("\n■ 已剥 %s 条" % f"{len(rows):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
