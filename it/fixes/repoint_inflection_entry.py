#!/usr/bin/env python3
"""`inflection.entry_id` 定语义：**指向原形的那个词条**。2026-08-18（阶段 8）。

═══ 问题：同一列有两套语义，按来源分裂 ═══
阶段 7 的收尾扫描发现这列有两族，各自内部一致、没有第三种：

    en 版  509,651 条 → **变形形自己的** entry（kaikki-en 把 `form_of` 写在变形形的词条里）
    en 版  122,234 条 → 原形的 entry（变形形自己没词条时的回落）
    fr 版  602,336 条 → 原形的 entry（fr 版把变形表写在原形词条里）

也就是说这一列**记的是"这句 form_of 是在哪个词条里读到的"** —— 忠实于源头，
但对查询毫无用处：同一个问题在两个来源上要用两种写法问。

═══ 定成哪一个：原形的 entry ═══
两条理由，都不是偏好：
① **另一读法是可推的**：变形形自己的 entry 从 `word_id` 一查就有，存一列冗余数据；
   而"这个形属于原形的哪个词条"是**推不出来**的 —— `porto` 是 `portare`（动词）的
   变位形，不是 `porto`（名词，港口）的，这个信息只有源头知道。
② 展示层将来要用的正是它：给原形词条列出它的全部变形（变位表），
   以及给一个变形形指回**具体那个**原形词条。

⚠️ 现在展示层还不读这一列（阶段 8 的词条页走 `inflection.base` 字符串）。
   先把语义定死并补上断言，是因为**语义分裂的列会随数据长大越来越难改**
   —— 等展示层开始读它，两套语义就变成用户看到的缺陷了。

═══ 定不了的一律写 NULL，不猜 ═══
    461,432  原形只有一个 entry            → 直接定
     36,758  多个 entry，按 src_ref 的词性唯一命中 → 定
     11,460  🔴 原形有**同词性的多个词源**，源头没说是哪一个 → **NULL**
          1  原形一个 entry 都没有            → NULL

留 NULL 而不是"挑词源号最小的那个"：`blind-gloss-inference-ceiling` 的结论 ——
猜出来的值和查出来的值在库里长得一模一样，下游分不出来。

用法（在 it/ 目录下）：
    python3 fixes/repoint_inflection_entry.py            # 干跑
    python3 fixes/repoint_inflection_entry.py --apply
    python3 fixes/repoint_inflection_entry.py --verify
"""
import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

f = lambda n: format(n, ",")


def entries_by_word(con):
    out = defaultdict(list)
    for eid, wid, pos in con.execute("SELECT id, word_id, pos FROM entry"):
        out[wid].append((eid, pos))
    return out


def plan(con):
    """→ (要改成具体 entry 的 [(entry_id, id)], 要改成 NULL 的 [id], 统计)。"""
    ent = entries_by_word(con)
    fix, null = [], []
    c = defaultdict(int)
    for iid, wid, bid, ref, eid in con.execute(
            "SELECT id, word_id, base_id, src_ref, entry_id FROM inflection"):
        if bid is None:
            c["原形悬空（源头真缺词头）"] += 1
            if eid is not None:
                null.append(iid)
            continue
        es = ent.get(bid, [])
        if not es:
            c["🔴 原形一个 entry 都没有"] += 1
            if eid is not None:
                null.append(iid)
            continue
        if len(es) == 1:
            want = es[0][0]
            c["原形只有一个 entry"] += 1
        else:
            # src_ref = kk-xx:<词形>:<词性>:<词源号>… —— 取词性去命中原形的 entry
            parts = ref.split(":")
            pos = parts[2] if len(parts) > 2 else None
            m = [e for e in es if e[1] == pos]
            if len(m) == 1:
                want = m[0][0]
                c["多 entry，按词性唯一命中"] += 1
            else:
                c["🔴 同词性多词源，定不了 → NULL"] += 1
                if eid is not None:
                    null.append(iid)
                continue
        if eid != want:
            fix.append((want, iid))
        else:
            c["  └ 本来就对"] += 1
    return fix, null, c


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        # 🔴 语义断言：非空的 entry_id **必须**属于原形，一条例外都不许有
        ("🔴 entry_id 不属于原形的",
         q("SELECT count(*) FROM inflection i JOIN entry e ON e.id=i.entry_id "
           "WHERE e.word_id <> i.base_id"), 0),
        ("🔴 指向不存在的 entry",
         q("SELECT count(*) FROM inflection i WHERE i.entry_id IS NOT NULL "
           "AND NOT EXISTS(SELECT 1 FROM entry e WHERE e.id=i.entry_id)"), 0),
        # 反向：原形只有一个 entry 时，没有理由留空
        ("🔴 原形唯一 entry 却留了空",
         q("SELECT count(*) FROM inflection i WHERE i.entry_id IS NULL "
           "AND i.base_id IS NOT NULL "
           "AND (SELECT count(*) FROM entry e WHERE e.word_id=i.base_id)=1"), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-36s %s (期望 %s)" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    n_null = con.execute("SELECT count(*) FROM inflection WHERE entry_id IS NULL").fetchone()[0]
    print("   ·  entry_id 为空 %s 条（原形同词性多词源 / 原形悬空，**有意留空**）" % f(n_null))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    fix, null, c = plan(ro)
    ro.close()
    for k, v in sorted(c.items(), key=lambda kv: -kv[1]):
        print("   %-32s %10s" % (k, f(v)))
    print("\n■ 要重指 %s 条、要清空 %s 条" % (f(len(fix)), f(len(null))))
    if not a.apply or not (fix or null):
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("repoint-inflection-entry", expect={"__rows__": 0}) as s:
        s.executemany("UPDATE inflection SET entry_id=? WHERE id=?", fix)
        for i in range(0, len(null), 20000):
            s.execute("UPDATE inflection SET entry_id=NULL WHERE id IN (%s)"
                      % ",".join(str(x) for x in null[i:i + 20000]))
        s.written = len(fix) + len(null)
    print("\n■ 已重指 %s 条、清空 %s 条" % (f(len(fix)), f(len(null))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
