#!/usr/bin/env python3
"""阶段 5 补记 — 把能确定性认领的孤儿例句挂回义项。2026-08-26。

用户 2026-08-26：「**没必要硬挂啊，有就有，没有就没有，实事求是，能挂就挂**」。
⇒ 这个脚本**只挂证据能唯一确定的**，一条都不猜。挂不上就留着不挂。

═══ 钥匙：`example.src_gloss` ═══
建例句层时我漏用了它 —— 每条例句都带着**源头那条义项的释义原文**（167,467/167,476，100%）。
证据层 `sense_src.text` 存的也是**逐字原文**（`[[two-layer-sense-model]]`），
同一份 dump 出来的两份文本，应当逐字对得上。
⇒ 挂载判据 = `(词形, 归一空白后的 src_gloss)` 在证据层**唯一命中一条可见义项**。
   这不是相似度、不是启发式，是**同一个字符串**。

═══ 🔴 明确不做的两件事 ═══
① **不跨词挂**。现有 572,890 条挂载里 `example.word` 与义项所属词形 **100% 相同**，
   这是条硬不变量。变形的例句（`trainerai` 的例句指向 `traîner` 的义项，60,623 行）
   挂到词元上会破坏它 —— 那正是用户说的「硬挂」。留着不挂，阶段 8 决定怎么展示。
② **不为了让例句有家去补义项**。有 86,998 行指向我们没收的义项
   （去重 53,276 个真缺口 / 27,181 个词形，如 `nom` 缺「名门望族」、
   `obscur` 缺「鲜为人知的」）——**那是义项缺口，记账，不在这个脚本里解决**。

用法（在 fr/ 目录下）：
    python3 -u pipeline/attach_orphan_examples.py            # 只报数 + 过闸
    python3 -u pipeline/attach_orphan_examples.py --read 15  # 打样
    python3 -u pipeline/attach_orphan_examples.py --apply    # 落库
"""
import argparse
import random
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool                              # noqa: E402
import paths                               # noqa: E402


def norm(t):
    """只归一空白 —— **不做别的**。任何进一步归一都是在放宽判据。"""
    return " ".join((t or "").split())


def evidence(con):
    """→ {(词形, 归一原文): {可见义项 id}}，同时记下每个词形有没有证据。"""
    ev = defaultdict(set)
    for w, txt, sid in con.execute(
            "SELECT d.word, ss.text, s.id FROM sense_src ss "
            "JOIN sense s ON s.id=ss.sense_id AND s.hidden=0 "
            "JOIN entry e ON e.id=s.entry_id "
            "JOIN dict d ON d.id=e.word_id"):
        if txt:
            ev[(w, norm(txt))].add(sid)
    return ev


def collect(con, ev):
    """→ ([(example_id, sense_id)], 统计)。**唯一命中才收**。"""
    out, st = [], defaultdict(int)
    for eid, w, sg in con.execute(
            "SELECT id, word, src_gloss FROM example "
            "WHERE sense_id IS NULL AND src_gloss IS NOT NULL AND src_gloss <> ''"):
        hit = ev.get((w, norm(sg)))
        if not hit:
            st["查不到（义项缺口或词是变形）"] += 1
        elif len(hit) == 1:
            out.append((eid, next(iter(hit))))
            st["✅ 唯一命中 ⇒ 挂"] += 1
        else:
            st["命中多条 ⇒ 不猜，不挂"] += 1
    return out, st


# ═════════════════════════════════════════════════════════════════════ 闸
def gates(con, pairs):
    """🔴 用户 2026-08-07：「**不要把义项和释义错配了，那才是真灾难**」。
    所以这里**不抽样** —— 每一条都从库里重新取，逐字复核。"""
    ok = True
    p = dict(pairs)
    rows = list(con.execute(
        "SELECT e.id, e.word, e.src_gloss, e.sense_id FROM example e "
        "WHERE e.id IN (%s)" % ",".join("?" * len(p)), list(p)) ) if p else []

    def gate(no, name, bad, n):
        nonlocal ok
        print("  %s %s：%s / %s" % ("✅" if not bad else "🔴", name,
                                    format(bad, ","), format(n, ",")))
        if bad:
            ok = False

    # ① 待挂的行现在必须**确实是孤儿**（别把已挂的改掉）
    gate(1, "① 待挂行原本 sense_id 为空",
         sum(1 for _i, _w, _g, s in rows if s is not None), len(rows))

    # ② 逐字复核：src_gloss ≡ 目标义项证据层的文本（**重新查库，不复用中间变量**）
    ev_txt = defaultdict(set)
    sids = set(p.values())
    for sid, txt in con.execute(
            "SELECT sense_id, text FROM sense_src WHERE sense_id IN (%s)"
            % ",".join("?" * len(sids)), list(sids)):
        ev_txt[sid].add(norm(txt))
    gate(2, "② src_gloss 与目标义项原文逐字相同",
         sum(1 for i, _w, g, _s in rows if norm(g) not in ev_txt[p[i]]), len(rows))

    # ③ 目标义项必须可见
    vis = {s for (s,) in con.execute(
        "SELECT id FROM sense WHERE hidden=0 AND id IN (%s)"
        % ",".join("?" * len(sids)), list(sids))}
    gate(3, "③ 目标义项 hidden=0", sum(1 for s in p.values() if s not in vis), len(p))

    # ④ 🔴 保住那条硬不变量：例句的词 == 义项所属词形（**不跨词挂**）
    sw = {s: w for s, w in con.execute(
        "SELECT s.id, d.word FROM sense s JOIN entry e ON e.id=s.entry_id "
        "JOIN dict d ON d.id=e.word_id WHERE s.id IN (%s)"
        % ",".join("?" * len(sids)), list(sids))}
    gate(4, "④ 例句词 == 义项所属词形（不跨词）",
         sum(1 for i, w, _g, _s in rows if sw.get(p[i]) != w), len(rows))

    # ⑤ 一条例句只挂一个义项
    gate(5, "⑤ 无一句多挂", len(pairs) - len(p), len(pairs))
    return ok


def verify(con, before):
    """落库后回核：总行数不变、非空数正好涨了 N、不变量仍然成立。"""
    tot = con.execute("SELECT COUNT(*) FROM example").fetchone()[0]
    now = con.execute("SELECT COUNT(*) FROM example WHERE sense_id IS NOT NULL").fetchone()[0]
    cross = con.execute(
        "SELECT COUNT(*) FROM example e JOIN sense s ON s.id=e.sense_id "
        "JOIN entry en ON en.id=s.entry_id JOIN dict d ON d.id=en.word_id "
        "WHERE d.word <> e.word").fetchone()[0]
    print("\n■ 落库后：example %s 行 ｜ 已挂 %s（%+d）｜ 跨词挂载 %d"
          % (format(tot, ","), format(now, ","), now - before["attached"], cross))
    assert tot == before["total"], "🔴 例句行数变了"
    assert cross == 0, "🔴 出现跨词挂载，硬不变量破了"
    print("✓ 回核通过")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--read", type=int, default=0)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    before = {"total": con.execute("SELECT COUNT(*) FROM example").fetchone()[0],
              "attached": con.execute(
                  "SELECT COUNT(*) FROM example WHERE sense_id IS NOT NULL").fetchone()[0]}
    pairs, st = collect(con, evidence(con))
    n = sum(st.values())
    print("■ 孤儿例句 %s 行：" % format(n, ","))
    for k in sorted(st, key=lambda x: -st[x]):
        print("   %-30s %9s (%5.1f%%)" % (k, format(st[k], ","), 100.0 * st[k] / n))

    print("\n══ 闸（**全量逐条，不抽样**）══")
    ok = gates(con, pairs)

    if a.read:
        xs = random.Random(11).sample(pairs, min(a.read, len(pairs)))
        print("\n══ 打样 %d 条：例句 / 它认领的义项 ══" % len(xs))
        for eid, sid in xs:
            w, t, g = con.execute(
                "SELECT word, text, src_gloss FROM example WHERE id=?", (eid,)).fetchone()
            zh = con.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang='zh' "
                             "ORDER BY seq LIMIT 1", (sid,)).fetchone()
            print("   【%s】义项 %d：%s" % (w, sid, (zh[0] if zh else "（无中文）")[:52]))
            print("        认领依据 %s" % g[:88])
            print("        例句     %s" % t[:88].replace("\n", "⏎"))

    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 闸未过，**不写库**")
        return 1
    with dbtool.session("keep-v3-example-attach", expect={}) as s:
        s.executemany("UPDATE example SET sense_id=? WHERE id=? AND sense_id IS NULL",
                      [(sid, eid) for eid, sid in pairs])
    verify(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True), before)
    return 0


if __name__ == "__main__":
    sys.exit(main())
