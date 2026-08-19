#!/usr/bin/env python3
"""意语版给同一条义项写了第二条定义：记在 seq=1，不新建义项。2026-08-16。

═══ 这批是谁 ═══
`finish_it_defs --apply` 里有一行长期是 2,796：

    🔴 目标义项已有意语定义（留证据层）   2,796

模型认定这条意语释义讲的就是我们某条义项的意思，但那条义项**已经接过**
另一条意语定义了（`UNIQUE(sense_id,lang,kind,seq)`，seq=0 只能有一条）。
于是它们每轮都被挂 → 被挡 → 退回证据层，**永远排不空**，而且每轮都要再花一次钱送模型。

═══ 为什么不新建义项 ═══
试过。把「哪些义项已占用」告诉模型、逼它填 0，新建从 327 涨到 2,363 条 ——
我读了过完三道去重闸后存活的 20 条，**只有 3–4 条是真新意思**：

    prolusione  新「课程的开场讲座（大学课程开讲就职讲座）」← 括号里就是已有那条
    lanificio   新「羊毛加工厂」            已有「毛纺厂／羊毛厂」
    nascondersi 新「藏身于隐蔽处」           已有「躲藏／隐藏自己」

按这个比例上架，八成会让用户在同一个词下看到同一个意思列两遍 ——
就是 es 上 `Cefalópodos` 那个缺陷。⇒ **不新建。**

═══ 做法：记在 seq=1 ═══
`packages/dict-core/src/italian.ts` 取意语原文时写死了 `seq = 0`，
所以 seq≥1 **不进页面**。这一步只做三件事：
    · `sense_gloss` 写一行 (sense_id, 'it', 'definition', seq=N, 原文)
    · `sense_src.sense_id` 指过去 —— 池子真正排空
    · 页面一个字不变

得到的是「意语版认为这条义项还有另一种说法」的记账。它同时是一份线索：
一条义项挂了 2+ 条意语定义 ⇒ 我们那条可能是个**粗口袋**，将来做义项细分时从这里入手。

🔴 判断来源是 `it_finish.round1.jsonl` —— 那一轮模型**可以自由挂**（还没被告知
   哪些已占用），挂的结果就是我们要的「这条意语释义属于哪条义项」。
   答案按 `sense_src.id` 存（见 `model-answer-files-key-by-id`），可安全重放。

用法（在 it/ 目录下）：
    python3 fixes/attach_second_it_def.py
    python3 fixes/attach_second_it_def.py --apply
    python3 fixes/attach_second_it_def.py --verify
    python3 fixes/attach_second_it_def.py --mutate
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbtool      # noqa: E402
import paths       # noqa: E402
import finish_it_defs as F   # noqa: E402
from promote_it_gloss import SRC   # noqa: E402
from strip_it_placeholder import clean   # noqa: E402

ANS = paths.WORK / "it_finish.round1.jsonl"


def plan(con):
    """→ [(sense_id, xid, 原文, 该 sense 的下一个空 seq)]

    🔴 这里**不用** `align_it_multi.resolve()`：它已经改成「指向已占用的义项就拒绝」，
       而本步要的正是那些被拒绝的。同一条"一条义项最多接一条 seq=0"的约束
       在下面用 `taken` 独立执行，不靠答案自律。
    """
    units, _ = F.load(con)
    if not ANS.exists():
        return [], Counter({"🔴 答案文件不存在（先跑 finish_it_defs --run）": 1})
    ans = {}
    for line in ANS.open():
        d = json.loads(line)
        ans[d["id"]] = {e["n"]: e for e in (d.get("r") or [])
                        if isinstance(e, dict) and isinstance(e.get("n"), int)}

    seq_max = defaultdict(lambda: -1)
    for sid, sq in con.execute(
            "SELECT sense_id, max(seq) FROM sense_gloss "
            "WHERE lang='it' AND kind='definition' GROUP BY sense_id"):
        seq_max[sid] = sq
    rows, st, used = [], Counter(), set()
    for (wid, pos), u in units.items():
        a = ans.get("%d|%s" % (wid, pos))
        if not a:
            st["这一轮没有答案（新出现的证据）"] += len(u["its"])
            continue
        for xid, text in u["its"]:
            e = a.get(xid)
            if e is None:
                st["答案里没有这条"] += 1
                continue
            i = e.get("i")
            if not (isinstance(i, int) and 1 <= i <= len(u["ours"])):
                st["模型判 0（不属于任何已有义项）—— 不归本步管"] += 1
                continue
            sid = u["ours"][i - 1][0]
            if seq_max[sid] < 0:
                st["🔴 目标义项还没有 seq=0 意语定义（该走 finish_it_defs）"] += 1
                continue
            if (sid, clean(text)) in used or con.execute(
                    "SELECT 1 FROM sense_gloss WHERE sense_id=? AND lang='it' "
                    "AND kind='definition' AND text=?", (sid, clean(text))).fetchone():
                st["原文与该义项已有的逐字相同，跳过"] += 1
                continue
            seq_max[sid] += 1
            used.add((sid, clean(text)))
            rows.append((sid, xid, clean(text), seq_max[sid]))
            st["✅ 记到 seq≥1"] += 1
    return rows, st


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    checks = [
        ("🔴 一条 sense 仍然只有一条 seq=0 意语定义",
         q("SELECT count(*) FROM (SELECT sense_id FROM sense_gloss WHERE lang='it' "
           "AND kind='definition' AND seq=0 GROUP BY 1 HAVING count(*)>1)"), 0),
        # ⚠️ 第一版写成 JOIN 后逐行比，报了 3,672 条假红 —— 一条 sense 现在挂着
        #    多条证据，JOIN 出的是**笛卡尔积**，本来就对不上。判据应是
        #    「该义项的证据里**存在**一条能逐字节对上这条 gloss」。
        ("🔴 每条 seq≥1 的意语定义都能在该义项的证据里找到出处",
         len([1 for sid, t in con.execute(
             "SELECT sense_id, text FROM sense_gloss "
             "WHERE lang='it' AND kind='definition' AND seq>0")
             if not any(t in (e, clean(e)) for (e,) in con.execute(
                 "SELECT text FROM sense_src WHERE sense_id=? AND src=?", (sid, SRC)))]), 0),
        ("🔴 seq≥1 不许与同一义项的 seq=0 逐字相同",
         q("SELECT count(*) FROM sense_gloss a JOIN sense_gloss b "
           "ON b.sense_id=a.sense_id AND b.lang='it' AND b.kind='definition' AND b.seq=0 "
           "WHERE a.lang='it' AND a.kind='definition' AND a.seq>0 AND a.text=b.text"), 0),
        ("🔴 seq 在每条 sense 内连续无空洞",
         sum(1 for sid, n, mx in con.execute(
             "SELECT sense_id, count(*), max(seq) FROM sense_gloss "
             "WHERE lang='it' AND kind='definition' GROUP BY sense_id") if n != mx + 1), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-46s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    print("   · 页面只读 seq=0，本步不改变任何用户可见内容")
    return ok


def mutate():
    """闸必须能逮住：seq=0 出现两条 / seq 有空洞 / seq≥1 与证据对不上。"""
    import os
    import shutil
    tmp = Path(os.environ.get("CLAUDE_JOB_DIR", "/tmp")) / "tmp" / "attach_mut.sqlite"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    sid = ro.execute("SELECT sense_id FROM sense_gloss WHERE lang='it' AND kind='definition' "
                     "AND seq>0 LIMIT 1").fetchone()
    ro.close()
    if not sid:
        print("\n（库里还没有 seq≥1 的行，先 --apply 再验）")
        return False
    sid = sid[0]
    # ⚠️「同一义项两条 seq=0」这个变异做不出来 —— `UNIQUE(sense_id,lang,kind,seq)`
    #    直接把它挡在写入层。⇒ 那条闸是**表结构已经保证的**，留着当双保险，
    #    但真正需要变异验证的是下面三条 schema 拦不住的。
    cases = [
        ("删掉 seq=0，让 seq 从 1 起（空洞）",
         "DELETE FROM sense_gloss WHERE sense_id=%d AND lang='it' "
         "AND kind='definition' AND seq=0" % sid),
        ("篡改 seq≥1 的原文（与证据对不上）",
         "UPDATE sense_gloss SET text='XXX 篡改 XXX' WHERE sense_id=%d AND lang='it' "
         "AND kind='definition' AND seq=1" % sid),
        ("把 seq 捅出一个空洞",
         "UPDATE sense_gloss SET seq=7 WHERE sense_id=%d AND lang='it' "
         "AND kind='definition' AND seq=1" % sid),
        ("删掉证据行，让 seq≥1 找不到出处",
         "DELETE FROM sense_src WHERE sense_id=%d AND src='it-edition'" % sid),
    ]
    print("\n═══ 变异验证 ═══")
    ok = True
    for name, sql in cases:
        shutil.copy(paths.DB, tmp)
        c = sqlite3.connect(tmp)
        c.execute(sql)
        c.commit()
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = gate(c)
        c.close()
        red = not res
        ok &= red
        print("   %s %-34s %s" % ("✅" if red else "🔴", name,
                                  "闸红了（对）" if red else "闸没红 —— 这条闸是假的"))
    tmp.exists() and tmp.unlink()
    print("\n   变异验证 %s" % ("通过" if ok else "🔴 有闸是假的"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("apply", "verify", "mutate"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    if a.mutate:
        return 0 if mutate() else 1
    rows, st = plan(ro)
    for k, v in st.most_common():
        print("   %-46s %7s" % (k, f"{v:,}"))
    print("\n■ 将把 %s 条意语原文记到 seq≥1（页面不变）" % f"{len(rows):,}")
    for sid, _x, t, sq in rows[:8]:
        w = ro.execute("SELECT d.word FROM sense s JOIN dict d ON d.id=s.word_id "
                       "WHERE s.id=?", (sid,)).fetchone()
        s0 = ro.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang='it' "
                        "AND kind='definition' AND seq=0", (sid,)).fetchone()
        print("   %-16s #%-8s seq=%d" % ((w and w[0] or "?")[:16], sid, sq))
        print("        seq0  %s" % (s0 and s0[0] or "")[:66])
        print("        新增  %s" % t[:66])
    ro.close()
    if not a.apply or not rows:
        print("\n(未加 --apply，不写库)" if not a.apply else "")
        return 0
    with dbtool.session("attach-second-it-def",
                        expect={"#sense_gloss": len(rows), "#sense": 0}) as s:
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?,'it','definition',?,?,?)",
                      [(sid, sq, t, SRC) for sid, _x, t, sq in rows])
        s.executemany("UPDATE sense_src SET sense_id=? WHERE id=?",
                      [(sid, xid) for sid, xid, _t, _sq in rows])
    print("\n■ 已记入 %s 条" % f"{len(rows):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
