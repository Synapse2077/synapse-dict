#!/usr/bin/env python3
"""把义项搬回它自己那个拼写的行 —— 大小写折叠残留。2026-08-20。

═══ 缺陷（用户看得见）═══
建库时 `build.py:227` 的 `key = word.lower()` 把 `Gracias` 和 `gracias` 折成一行，
于是日常词的页面上混进了专名义项：

    搜 gracias（谢谢，zipf 5.86） → 页面上有「格拉西亚斯（洪都拉斯城镇）」
    搜 libre（自由的）            → 「革新自由主义」（洪都拉斯政党 LIBRE）
    搜 podemos（我们能）          → 「我们能党（西班牙左翼政党）」
    搜 mujeres（女人们）          → 「穆赫雷斯（姓氏）」
    搜 nuevo（新的）              → 「努埃沃」（地名）

另一个方向也有（84 条）：`Chad`（乍得）页面上混进了 `chad`（打孔屑）的义项。
以及 19 个词形上出现**近乎重复**的义项（`y` 的字母释义收了大小写两份）。

═══ 为什么现在才能确定性地修 ═══
`split_case_homographs.py`（2026-08-07）修过同族的 9,122 条，但当时
**英文版源头不分大小写**（`concepción` 一个词条里同时装着「受孕」和「女性名」），
6,083 条只能送模型判。

本批不一样：dump 里**确实有独立的大写词条**，`entry.spelling` 把原拼写记了下来
（2026-08-20 建 entry 层的副产品）。判据因此是确定性的一句话：

    **义项应该待在 `word` 等于 `entry.spelling` 的那一行。**

═══ 顺带修一个我自己当天写出来的 bug ═══
`build_entry_layer.build_rows` 第一版把精确表和小写回退表写成了同一张：

    word_id.setdefault(w, i); word_id.setdefault(w.lower(), i)

`Ángel` 的 id 比 `ángel` 小 ⇒ 扫到它时 `word_id['ángel']` 就被大写行占了。
结果 **17 个 entry 的 word_id 指错行**（22 条义项）——「天使」的释义挂到了
人名 `Ángel` 的词条上。源头已在 `build_entry_layer.py` 修好，这里修已落库的那 17 行。
⇒ 934 条里 **22 条是我的 bug、912 条是历史遗留**，两者判据相同、一起修。

═══ 可逆 ═══
改的只有 `sense.word_id` 和 `entry.word_id` 两个整数字段。
`sense_src` / `sense_gloss` / `example` / `sense_relation` 全部通过 `sense_id` 挂靠，
不受影响。判错了改回来即可。**`dict` 一列不动。**

═══ 闸 ═══
① 搬完之后 `sense.word_id == entry.word_id == (word=spelling 的那一行)`，残留只剩
   「spelling 在库里根本没有」的那些（`OCA` / `ANDA` / `UNA` 这类全大写缩写，
   义项现在待在 title-case 行上，是合理落点）
② 义项总数不变、每条义项仍恰好一条 sense_src（搬的是归属不是内容）
③ 反向：被搬走的义项不许在原来那一行的页面上再出现
④ 变异验证

用法（在 es/ 目录下）：
    python3 fixes/fix_case_fold_residue.py            # 试算
    python3 fixes/fix_case_fold_residue.py --apply
    python3 fixes/fix_case_fold_residue.py --mutate
"""
import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402


def load_authority(con):
    """→ (exact: word→id, owner: sense_id→裁决词形)。plan 与 gate **共用这一份**。"""
    exact = {}
    for i, w in con.execute("SELECT id, word FROM dict"):
        exact.setdefault(w, i)
    owner = {}
    for ref, w in con.execute("SELECT src_ref, word FROM sense_owner"):
        for (sid,) in con.execute("SELECT sense_id FROM sense_src WHERE src_ref=?", (ref,)):
            owner[sid] = w
    return exact, owner


def target_of(sid, spell, entry_wid, exact, owner):
    """这条义项应该待在哪一行。→ (word_id 或 None, 原因)

    🔴 判据的优先级就是权威的优先级：
       ① `sense_owner` —— 2026-08-07 人工/模型裁决过的，**它说了算**
       ② `entry.spelling` —— dump 记的原拼写，裁决没覆盖到的才用它
    plan 和 gate 都调这一个函数。判据与实现共用一份代码（A93）。
    """
    ow = owner.get(sid)
    if ow is not None:
        t = exact.get(ow)
        return (t, "裁决") if t is not None else (None, "裁决指向的词形库里没有")
    t = exact.get(spell)
    return (t, "spelling") if t is not None else (None, "spelling 库里没有独立行")


def plan(con, verbose=True):
    """→ (搬义项 [(新word_id, sense_id)], 修entry [(新word_id, entry_id)], 计数)"""
    exact, owner = load_authority(con)
    move_sense, fix_entry, c = [], [], Counter()

    # ① entry.word_id 指错行（我的 bug）
    for eid, wid, spell in con.execute("SELECT id, word_id, spelling FROM entry"):
        right = exact.get(spell)
        if right is not None and right != wid:
            fix_entry.append((right, eid))
            c["entry.word_id 指错行 → 改指 spelling 那一行"] += 1

    right_of_entry = {eid: w for w, eid in fix_entry}

    # ② 义项待在别的拼写的行上
    for sid, swid, eid, ewid, spell in con.execute(
            "SELECT s.id, s.word_id, e.id, e.word_id, e.spelling "
            "FROM sense s JOIN entry e ON e.id = s.entry_id"):
        # entry.word_id 的修正先并进来，再交给共用的 target_of 裁决
        if eid in right_of_entry:
            ewid = right_of_entry[eid]
        target, why = target_of(sid, spell, ewid, exact, owner)
        if target is None:
            c["不动：" + why] += 1
            continue
        if why == "spelling" and target != ewid:
            target = ewid                      # spelling 与 entry 行一致时以 entry 行为准
        if target == swid:
            continue
        move_sense.append((target, sid))
        c["义项搬到「%s」说的那一行" % why] += 1

    # 🔴 `sense` 有 `UNIQUE(word_id, rank)` —— 搬过去会与目标行已有的 rank 撞。
    #    ⇒ 排到目标行现有义项的**后面**。这批是被误并进来的专名/异形，
    #    放在原生义项之后是对的顺序（`Gracias` 城镇排在 `Gracias` 已有义项之后）。
    nxt = {}
    for wid, mx in con.execute("SELECT word_id, MAX(rank) FROM sense GROUP BY word_id"):
        nxt[wid] = (mx or 0) + 1
    ranked = []
    for target, sid in move_sense:
        r = nxt.get(target, 1)
        nxt[target] = r + 1
        ranked.append((target, r, sid))

    if verbose:
        print("■ 试算")
        for k, v in sorted(c.items()):
            print("     %-44s %s" % (k, format(v, ",")))
    return ranked, fix_entry, c


def apply(con, move_sense, fix_entry):
    con.executemany("UPDATE entry SET word_id=? WHERE id=?", fix_entry)
    con.executemany("UPDATE sense SET word_id=?, rank=? WHERE id=?", move_sense)
    return len(move_sense) + len(fix_entry)


def gate(con, verbose=True):
    """🔴 判据与 `plan` **共用 `target_of`**，不另写一套。

    第一版 gate 只认 `entry.spelling`，而 plan 改成听 `sense_owner` 之后，
    两者会互相报红 —— 「判据与被验的实现共用一份代码」这条在这里是硬要求。
    """
    bad = []
    exact, owner = load_authority(con)

    # ① 残留只剩「裁决/拼写都指不到库里的行」的
    resid = other = 0
    for sid, swid, ewid, spell in con.execute(
            "SELECT s.id, s.word_id, e.word_id, e.spelling FROM sense s "
            "JOIN entry e ON e.id = s.entry_id"):
        t, why = target_of(sid, spell, ewid, exact, owner)
        if t is None:
            if swid != ewid:
                resid += 1
            continue
        if why == "spelling" and t != ewid:
            t = ewid
        if t != swid:
            other += 1
    if other:
        bad.append("🔴 仍有 %s 条义项不在权威（裁决 > spelling）说的那一行"
                   % format(other, ","))
    if resid > BASE_NO_ROW:
        bad.append("🔴 「权威指不到库里的行」从基线 %s 涨到 %s"
                   % (BASE_NO_ROW, format(resid, ",")))

    # ② entry.word_id 与 spelling 自洽
    n = sum(1 for wid, sp in con.execute("SELECT word_id, spelling FROM entry")
            if sp in exact and exact[sp] != wid)
    if n:
        bad.append("🔴 entry.word_id 与 spelling 对不上 %s 行" % format(n, ","))

    # ③ 搬的是归属不是内容
    q = lambda s: con.execute(s).fetchone()[0]
    if q("SELECT COUNT(*) FROM sense") != BASE_SENSES:
        bad.append("🔴 义项总数变了（应为 %s，现在 %s）"
                   % (BASE_SENSES, q("SELECT COUNT(*) FROM sense")))
    n = q("SELECT COUNT(*) FROM sense s WHERE NOT EXISTS("
          "SELECT 1 FROM sense_src ss WHERE ss.sense_id=s.id)")
    if n:
        bad.append("🔴 有 %s 条义项没有证据行了" % format(n, ","))
    # ④ 义项所在行必须存在
    n = q("SELECT COUNT(*) FROM sense s LEFT JOIN dict d ON d.id=s.word_id WHERE d.id IS NULL")
    if n:
        bad.append("🔴 有 %s 条义项挂到了不存在的 dict 行" % format(n, ","))
    if verbose:
        print("■ 闸：不在权威说的行上 %s（应 0）；权威指不到库里的行 %s（基线 %s）" % (
            other, resid, BASE_NO_ROW))
        for b in bad:
            print("     " + b)
        if not bad:
            print("     ✅ 全部通过")
    return bad


BASE_SENSES = 268937        # 搬运不改条数
# **实测 0**：加上 `sense_owner` 这条权威之后，`OCA`/`ANDA`/`UNA` 那批也各有归属，
# 没有剩余。（第一版只认 `entry.spelling` 时是 8，我还先后写过没实测的 30 和 8。）
# 🔴 基线一律实测 —— 同一天已经在 `ingest_missing_bases` 的 C7 上栽过一次：
#    猜宽一条不是「宽松」，是让一整类回归对这道闸隐形。
BASE_NO_ROW = 0


def mutate(move_sense, fix_entry):
    import shutil
    import tempfile
    MUT = [
        ("① 少搬一条义项", lambda m, f: (m[:-1], f), True),
        ("② 把一条义项搬到不存在的行",
         lambda m, f: (m + [(9 ** 9, 999, m[0][2])], f), True),
        # ⚠️ 原来写的是「不应用 fix_entry」，但那 17 个 entry 上一轮已经修好了、
        #    `fix_entry` 现在是空的 ⇒ 变异是空操作，**构造上不可能红**。
        #    改成直接把一个 entry 的 word_id 指歪 —— 打在闸真正检查的那个落点上。
        ("③ 把一个 entry 的 word_id 指歪", lambda m, f: (m, f), True),
        ("④ 顺手删一条义项（搬运不该改条数）",
         lambda m, f: (m, f), True),          # 删除在下面单独执行
        ("⑤【负控】原样应用", lambda m, f: (m, f), False),
    ]
    ok, cases = 0, []
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.sqlite"
        shutil.copy2(paths.DB, p)
        c = sqlite3.connect(p)
        for i, (name, mut, want_red) in enumerate(MUT):
            c.execute("SAVEPOINT m")
            try:
                m2, f2 = mut(list(move_sense), list(fix_entry))
                apply(c, m2, f2)
                if i == 2:
                    # ⚠️ 原来指向 `MIN(id) FROM dict`，而 entry#1 的 word_id 本来就是 1
                    #    ⇒ 变异是空操作、构造上不可能红（今天第三次栽在「变异自己坏了」）。
                    c.execute("UPDATE entry SET word_id=(SELECT MAX(id) FROM dict) "
                              "WHERE id=(SELECT MIN(e.id) FROM entry e JOIN dict d ON d.id=e.word_id"
                              "          WHERE d.word=e.spelling)")
                if i == 3:
                    c.execute("DELETE FROM sense WHERE id=(SELECT MIN(id) FROM sense)")
                bad = gate(c, verbose=False)
            finally:
                c.execute("ROLLBACK TO m")
                c.execute("RELEASE m")
            good = bool(bad) == want_red
            ok += good
            cases.append((name, ("✅ 报红" if bad else "✅ 照常绿") if good
                          else ("🔴 该红没红" if want_red else "🔴 不该红却红了")))
        c.close()
    print("\n■ 变异验证")
    for n, s in cases:
        print("     %-34s %s" % (n, s))
    print("     %d/%d" % (ok, len(cases)))
    return 0 if ok == len(cases) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    move_sense, fix_entry, _ = plan(con)
    con.close()
    print("■ 将搬 %s 条义项、修 %s 个 entry 的归属"
          % (format(len(move_sense), ","), format(len(fix_entry), ",")))
    if a.mutate:
        return mutate(move_sense, fix_entry)
    if not a.apply:
        print("\n(未加 --apply，没有写库)")
        return 0
    with dbtool.session("case-fold-residue", expect={}) as s:
        s.written = apply(s.conn, move_sense, fix_entry)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    bad = gate(con)
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
