#!/usr/bin/env python3
"""读音↔词条 关联表：单个可空外键表达不了「一个读音属于哪几个词条」。2026-08-19。

═══ A81 记的缺口 ═══
`pesca` 的 /ˈpɛs.ka/ 在英文版里**同时挂在 `noun:1` 和 `adj:1` 下**。
`build_pronunciation_layer` 按 A57「唯一才写」的规矩把 `pronunciation.entry_id`
落成 NULL —— 区分力全丢。实测：同词形多读音的 8,375 个词里，归属**有区分力**的
2,129 个，单外键表达得了 1,515（71%），剩 **614** 只能留空。

⇒ 按 A20「多值落行」加关联表。**不重建 `pronunciation` 表** ——
  那张表上有 2026-08-19 五个修复脚本的成果（归一撇号重音符 7,094 行、
  删音节残渣 228 行、重新选主读音……），重建会把它们全冲掉。

═══ 做法：复用建表脚本自己的扫描函数，不另写一份解析 ═══
`build_pronunciation_layer.collect()` 已经把每个读音的 `ent`（一组 `(词性, 词源号)`）
算出来了 —— 建表时只是**用了 `len(ent)==1` 那一支**。这里把整组都落行。

行键用 `row_key(word_id, cmp_key(ipa), notation)`，与建表时**同一个函数** ——
`cmp_key` 会折掉各版排版习惯和撇号写法，所以那五个修复脚本改过的 `ipa` 仍然对得上。

═══ 闸 ═══
① 关联表里的每一行，`pronunciation_id` 和 `entry_id` 都必须存在，且**同一个词形**
② 凡是 `pronunciation.entry_id` 非空的行，关联表里必须**含有**那个 entry
   （新表不能与旧列打架）
③ 一个读音关联到的 entry 数 ≥ 1
④ 收回的区分力：`entry_id` 为空但关联表给出归属的读音行数 > 0（这是本步的产出）

用法（在 it/ 目录下）：
    python3 pipeline/build_pron_entry_link.py            # 干跑（要扫 761 MB，约几分钟）
    python3 pipeline/build_pron_entry_link.py --apply
    python3 pipeline/build_pron_entry_link.py --verify
    python3 pipeline/build_pron_entry_link.py --mutate
"""
import argparse
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool                        # noqa: E402
import paths                         # noqa: E402
from build_pronunciation_layer import collect, row_key, word_index   # noqa: E402
from ipa_variants import cmp_key     # noqa: E402

f = lambda n: format(n, ",")

DDL = """
CREATE TABLE IF NOT EXISTS pronunciation_entry (
  pronunciation_id INTEGER NOT NULL,
  entry_id         INTEGER NOT NULL,
  PRIMARY KEY (pronunciation_id, entry_id)
)
"""
IDX = "CREATE INDEX IF NOT EXISTS idx_pron_entry_pron ON pronunciation_entry(pronunciation_id)"


def entry_maps(con):
    """→ ({(src, 词形, 词性, 词源号): eid}, {(词形, 词性): {eid}})

    与 `build_pronunciation_layer.build()` 里那段**同样的解析**：词源号一律按字符串比
    （子条目改挂写出过 `1.2` 这类复合号，`int()` 会当场炸）。
    """
    ent_id, by_pos = {}, defaultdict(set)
    for eid, src, ref in con.execute("SELECT id, src, src_ref FROM entry"):
        try:
            body, pos, etym, _seq = ref.rsplit(":", 3)
        except ValueError:
            continue
        w = body.split(":", 1)[1]
        ent_id[(src, w, pos, etym)] = eid
        by_pos[(w, pos)].add(eid)
    return ent_id, by_pos


def plan(con, verbose=True):
    """→ (要插的 {(pron_id, entry_id)}, 统计)"""
    words, _moved = word_index(con)
    rows, _amap = collect(words, verbose=verbose)
    ent_id, by_pos = entry_maps(con)

    # 库里现有的读音行，按同一个行键索引
    db_rows = {}
    for pid, wid, ipa, notation, eid in con.execute(
            "SELECT id, word_id, ipa, notation, entry_id FROM pronunciation"):
        db_rows.setdefault(row_key(wid, ipa, notation), []).append((pid, eid))

    link, c = set(), Counter()

    # 🔴 先把旧列已有的归属整个搬进来，再加重算的 —— **并集，不是替换**。
    #    第一版只写重算结果，闸②报 3 行「旧列非空却没进关联表」：
    #    `tramonti` 的 `traˈmon.ti` 旧列挑了动词（第二人称单数）、重算挑了名词（复数）——
    #    **两个都对，那个词形的名词和动词读音本来就一样**。这正是关联表存在的理由：
    #    单外键逼着二选一，关联表不用选。
    #    （另两条 `bagordo` / `istigatore` 同一形状。）
    for pid, eid in con.execute(
            "SELECT id, entry_id FROM pronunciation WHERE entry_id IS NOT NULL"):
        link.add((pid, eid))
    c["从旧列搬进来的归属"] = len(link)

    for k, r in rows.items():
        hit = db_rows.get(k)
        if not hit:
            c["dump 里有、库里没有（五个修复脚本删过/改过）"] += 1
            continue
        eids = set()
        for pos, etym in r["ent"]:
            e = ent_id.get((r["ent_src"], r["word"], pos, str(etym)))
            if e is None:
                # 与建表时同一条退路：词源号跨版不可比，词性可比；
                # 该词形在这个词性下只有一个 entry 时才挂，多于一个就是编造。
                cands = by_pos.get((r["word"], pos)) or set()
                e = next(iter(cands)) if len(cands) == 1 else None
            if e is not None:
                eids.add(e)
        if not eids:
            c["归属对不上任何 entry"] += 1
            continue
        for pid, _old in hit:
            for e in eids:
                link.add((pid, e))
        c["✅ 落关联行"] += 1
        if len(eids) > 1:
            c["   其中多归属（旧列装不下的）"] += 1
    c["关联行数"] = len(link)
    return link, c


def gate(con):
    ok = True

    def chk(name, got, want, cmp="=="):
        nonlocal ok
        good = (got == want) if cmp == "==" else (got > want)
        ok &= good
        print("   %s %-46s %s（应 %s %s）"
              % ("✅" if good else "🔴", name, f(got), cmp, f(want)))

    q = lambda s: con.execute(s).fetchone()[0]
    if not con.execute("SELECT name FROM sqlite_master WHERE name='pronunciation_entry'").fetchone():
        print("   🔴 关联表还没建（先 --apply）")
        return False
    chk("🔴 ① 指向不存在的读音行", q(
        "SELECT count(*) FROM pronunciation_entry l WHERE NOT EXISTS"
        "(SELECT 1 FROM pronunciation p WHERE p.id=l.pronunciation_id)"), 0)
    chk("🔴 ① 指向不存在的词条", q(
        "SELECT count(*) FROM pronunciation_entry l WHERE NOT EXISTS"
        "(SELECT 1 FROM entry e WHERE e.id=l.entry_id)"), 0)
    chk("🔴 ① 读音与词条不是同一个词形（反错配）", q(
        "SELECT count(*) FROM pronunciation_entry l JOIN pronunciation p ON p.id=l.pronunciation_id "
        "JOIN entry e ON e.id=l.entry_id WHERE e.word_id <> p.word_id"), 0)
    chk("🔴 ② 旧列非空却没进关联表", q(
        "SELECT count(*) FROM pronunciation p WHERE p.entry_id IS NOT NULL AND NOT EXISTS"
        "(SELECT 1 FROM pronunciation_entry l WHERE l.pronunciation_id=p.id "
        "AND l.entry_id=p.entry_id)"), 0)
    chk("④ 旧列为空、关联表给出归属的读音行", q(
        "SELECT count(DISTINCT l.pronunciation_id) FROM pronunciation_entry l "
        "JOIN pronunciation p ON p.id=l.pronunciation_id WHERE p.entry_id IS NULL"), 0, ">")
    n = q("SELECT count(DISTINCT p.word_id) FROM pronunciation_entry l "
          "JOIN pronunciation p ON p.id=l.pronunciation_id WHERE p.entry_id IS NULL")
    print("   ·  收回归属的词形 %s 个" % f(n))
    return ok


def mutate():
    cases = [
        ("把一条关联挂到别的词形的词条上",
         "UPDATE pronunciation_entry SET entry_id=(SELECT e.id FROM entry e "
         "JOIN pronunciation p ON p.id=pronunciation_entry.pronunciation_id "
         "WHERE e.word_id<>p.word_id LIMIT 1) "
         "WHERE rowid=(SELECT min(rowid) FROM pronunciation_entry)"),
        ("删掉一条与旧列一致的关联（新旧打架）",
         "DELETE FROM pronunciation_entry WHERE rowid=(SELECT min(l.rowid) "
         "FROM pronunciation_entry l JOIN pronunciation p ON p.id=l.pronunciation_id "
         "AND p.entry_id=l.entry_id)"),
        ("把关联指向一个不存在的词条",
         "UPDATE pronunciation_entry SET entry_id=99999999 "
         "WHERE rowid=(SELECT min(rowid) FROM pronunciation_entry)"),
        ("清空整张关联表（该报「没有收回任何归属」）", "DELETE FROM pronunciation_entry"),
    ]
    passed = 0
    for name, sql in cases:
        d = Path(tempfile.mkdtemp())
        shutil.copy(paths.DB, d / "m.sqlite")
        con = sqlite3.connect(d / "m.sqlite")
        con.execute(sql)
        con.commit()
        print("\n── 变异：%s" % name)
        red = not gate(con)
        con.close()
        shutil.rmtree(d)
        print("   %s" % ("✅ 闸报红" if red else "🔴 闸没报 —— 这道检查是假的"))
        passed += red
    print("\n■ 变异 %s/%s" % (passed, len(cases)))
    return 0 if passed == len(cases) else 1


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify", "mutate"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return mutate()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    link, c = plan(ro)
    ro2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n■ 计划")
    for k, v in c.most_common():
        print("   %-42s %s" % (k, f(v)))
    ro.close()
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    # 续跑安全：只插缺的。`replay-scripts-undo-fixes` —— `INSERT OR IGNORE` 保证不重复，
    # 但要让 expect 对得上，得先数清楚这一次到底会新增几行。
    have = set()
    if ro2.execute("SELECT name FROM sqlite_master WHERE name='pronunciation_entry'").fetchone():
        have = set(ro2.execute("SELECT pronunciation_id, entry_id FROM pronunciation_entry"))
    ro2.close()
    add = sorted(link - have)
    with dbtool.session("build-pron-entry-link",
                        expect={"__rows__": 0, "#pronunciation_entry": len(add)}) as s:
        s.execute(DDL)
        s.execute(IDX)
        s.executemany("INSERT OR IGNORE INTO pronunciation_entry VALUES (?,?)", add)
    print("■ 已落 %s 行关联（表内共 %s）" % (f(len(add)), f(len(link))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
