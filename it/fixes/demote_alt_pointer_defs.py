#!/usr/bin/env python3
"""把「本身就是指针」的意语定义从出版层退回证据层。2026-08-14，阶段 1.5 补。

═══ 怎么冒出来的 ═══
`promote_it_gloss` 重跑（阶段 2a/3 之后 1:1 人群变了）提升了 1,846 条，其中一部分
落在了 `alt_of` 关系义项上，闸② 报红 703 条。逐条读下来，703 是**两种东西**：

    laudare    it=variante antica di lodare      ← 指针，与中文「lodare 的异体形式」重复
    anitra     it=uccello degli Anseriformi      ← 🔴 真定义！意语版把它当正经词条写
    granturco  it=pianta erbacea annuale…        ← 🔴 真定义（玉米）
    acquasanta it=acqua benedetta con…           ← 🔴 真定义（圣水）

⇒ 闸② 那条断言「意语定义不许挂在 alt 义项上」**口径太粗**：它假设落在 alt 义项上的
   一定是噪声，而实际上意语版给了我们英文版没有的真定义 —— 那正是收意语版的目的。

═══ 判据：不再往 PTR 正则里堆词 ═══
`PTR` 已经改到第二版，`PITFALLS` A4 说改判据三轮就停手。而且 `variante` 开头**不等于**
指针 ——「variante del gioco del calcio praticata su spiaggia」（沙滩足球）是真定义。

这里有个**确定性判据**，不用猜：指针文本末尾 `di X` 里的 X，应该正好等于我们
`sense_relation.alt_of.target` 里已经记下的目标词。查表比对：

    laudare  it 末尾 = "lodare"   target = "lodare"   ⇒ 指针，退回
    anitra   it 末尾 = "anseriformi" target = "anatra" ⇒ 真定义，留下

实测 372 指针 / 331 真定义。
⚠️ 残差按上界报，不再改判据：
   · `conscienza` it="conscienza f; termine arcaico per coscienza" —— 是指针但不含 " di "，
     判成了真定义（同时带 wiktextract 残渣 `conscienza f`）
   · `monitorizzare` it="variante di monitorare, in origine più comune ma ormai…" ——
     目标词后面还有用法说明，判成真定义。这条我认为**判对了**，那句说明有价值。

═══ 可逆 ═══
只删出版层的 `sense_gloss` 行、把证据行的 `sense_id` 退回 NULL。
证据层文字一个字节不动，随时可以重提升。

用法（在 it/ 目录下）：
    python3 fixes/demote_alt_pointer_defs.py
    python3 fixes/demote_alt_pointer_defs.py --apply
    python3 fixes/demote_alt_pointer_defs.py --verify
"""
import argparse
import sqlite3
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from promote_it_gloss import SRC   # noqa: E402


def norm(x):
    """去重音、小写、剥两端标点。只用于**比对**，不写回库。"""
    return "".join(ch for ch in unicodedata.normalize("NFD", x.lower())
                   if unicodedata.category(ch) != "Mn").strip(" .,;:")


def is_pointer(text, target):
    """意语文字是不是「指向 target 的指针」—— 确定性判据，见文件头。"""
    n = norm(text)
    tail = n.rsplit(" di ", 1)[-1] if " di " in n else n
    return tail == norm(target)


def plan(con):
    """→ [(sense_id, word, text, target)]，全是判定为指针的。"""
    out = []
    for sid, w, text, target in con.execute(
            "SELECT g.sense_id, d.word, g.text, r.target FROM sense_gloss g "
            "JOIN sense_relation r ON r.sense_id=g.sense_id AND r.kind='alt_of' "
            "JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id "
            "WHERE g.lang='it' AND g.kind='definition'"):
        if is_pointer(text, target):
            out.append((sid, w, text, target))
    return out


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    left = plan(con)
    checks = [
        ("🔴 出版层不再有「指向自己 alt 目标」的意语定义", len(left), 0),
        # 退回的证据必须真的退回，不能只删出版行留着已裁决的孤儿
        ("🔴 已裁决的证据都必须有对应的出版释义",
         q("SELECT count(*) FROM sense_src x WHERE x.src=? AND x.sense_id IS NOT NULL "
           "AND NOT EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=x.sense_id "
           "AND g.lang='it' AND g.kind='definition')", SRC), 0),
        ("被裁决的证据行数 == 出版层意语释义数",
         q("SELECT count(*) FROM sense_src WHERE src=? AND sense_id IS NOT NULL", SRC)
         - q("SELECT count(*) FROM sense_gloss WHERE lang='it' AND kind='definition'"), 0),
        # 🔴 真定义那批必须**还在**。退错了这里会掉下去 —— 这条防的是"一刀切全删"。
        ("🔴 alt 义项上的真定义仍保留（不是一刀切）",
         q("SELECT count(*) FROM sense_gloss g JOIN sense_relation r "
           "ON r.sense_id=g.sense_id AND r.kind='alt_of' "
           "WHERE g.lang='it' AND g.kind='definition'") > 0, True),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-48s %s (期望 %s)" % ("✅" if good else "🔴", name, got, want))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1

    rows = plan(ro)
    tot = ro.execute("SELECT count(*) FROM sense_gloss g JOIN sense_relation r "
                     "ON r.sense_id=g.sense_id AND r.kind='alt_of' "
                     "WHERE g.lang='it' AND g.kind='definition'").fetchone()[0]
    print("■ alt 义项上共有意语定义 %s 条" % f"{tot:,}")
    print("   判为指针，退回证据层  %s" % f"{len(rows):,}")
    print("   判为真定义，保留      %s" % f"{tot - len(rows):,}")
    print("\n■ 退回样例：")
    for sid, w, t, tg in rows[:6]:
        print("   %-16s target=%-14s it=%s" % (w, tg, t[:48]))
    print("\n■ 保留样例（意语版给的真定义，英文版没有）：")
    demoted = {sid for sid, *_ in rows}
    shown = 0
    for sid, w, t in ro.execute(
            "SELECT g.sense_id, d.word, g.text FROM sense_gloss g JOIN sense_relation r "
            "ON r.sense_id=g.sense_id AND r.kind='alt_of' JOIN sense s ON s.id=g.sense_id "
            "JOIN dict d ON d.id=s.word_id WHERE g.lang='it' AND g.kind='definition'"):
        if sid in demoted or shown >= 6:
            continue
        print("   %-16s it=%s" % (w, t[:60]))
        shown += 1
    ro.close()
    if not a.apply:
        print("(未加 --apply，不写库)")
        return 0

    ids = [(sid,) for sid, *_ in rows]
    with dbtool.session("demote-alt-pointer", expect={"#sense_gloss": -len(ids)}) as s:
        s.executemany("DELETE FROM sense_gloss WHERE sense_id=? AND lang='it' "
                      "AND kind='definition'", ids)
        s.executemany("UPDATE sense_src SET sense_id=NULL WHERE sense_id=? AND src='%s'"
                      % SRC, ids)
    print("\n■ 已退回 %s 条" % f"{len(ids):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
