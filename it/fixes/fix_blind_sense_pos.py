#!/usr/bin/env python3
"""盲推那批义项的 `sense.pos` 上留着第一轮的默认值 `v`。2026-08-19。

═══ 用户看得到 ═══
    Meleagridi   （火鸡科，一个分类学名）  显示成「动词」   ← 错
    a pancia in su（仰面朝天，副词短语）    显示成「动词」   ← 错
    DPCM         （部长会议主席令，缩写）   显示成「动词」   ← 错

═══ 根因：修在了 prompt 那一侧，没回头修已写进库的行 ═══
`prompt-self-harm-two-patterns` 记的第一条自伤就是 `fill_blind_gloss.scan()` 里的
`pos or "v"` —— 把 `dict.pos` 为空的分类学名/缩写/词缀都告知模型"这是动词"。
2026-08-17 把它改成了 `pos or "unknown"`，**但那是入参那一侧**；
写库那一行是 `epos = pos if pos != "unknown" else None`，
所以**第一轮已经落进 `sense.pos` 的 `v` 一个都没被改回来**。

证据：现行代码写不出「`dict.pos` 为空而 `sense.pos='v'`」这个组合，库里却有 **461 条**。

⇒ 这是「修复消失的第二种机制」的近亲：换了写入路径、旧行留在原地，
  查新写的行永远绿，而用户看到的是第一轮那批。

═══ 判据（不猜，全部来自 `sense_src.src_ref` 里的 kaikki 原值）═══
候选 = `sense.pos='v'` **且** `dict.pos` 不是 `v` **且** 这条义项是盲推来的。共 466 条。

    ① 该词形的证据词性映射后**只有一个**展示短码，且不是 v  → 改成它        （390）
    ② 映射后多于一个短码，但 `dict.pos` 非空且在其中          → 用 `dict.pos`  （  9）
    ③ 映射后多于一个短码，`dict.pos` 也帮不上                → 清空为 NULL   （  5）
    ④ 证据里**有**动词（`accappare` 确实是动词）             → 不动          （ 62）

🔴 ③ 宁可留空也不留一个证明是错的值 —— 「错比缺更伤权威」。
🔴 ④ 是这道判据的负控：它证明判据不是"把 v 一律清掉"。

⚠️ `sense.pos` 是**展示层短码**（`POS_MAP` 的值），不是 kaikki 原值 ——
   跟 `entry.pos` 的约定正好相反，别写反（`normalize_sense_pos` 的闸盯着这一条）。

用法（在 it/ 目录下）：
    python3 fixes/fix_blind_sense_pos.py            # 干跑
    python3 fixes/fix_blind_sense_pos.py --apply
    python3 fixes/fix_blind_sense_pos.py --verify
    python3 fixes/fix_blind_sense_pos.py --mutate
"""
import argparse
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool              # noqa: E402
import paths               # noqa: E402
from build import POS_MAP  # noqa: E402

f = lambda n: format(n, ",")

# `kk-<版>:<词形>:<词性>` + 可选的 `:词源:序号` + 可选的 `#位置`
# 与 `extend_entry_layer.REF` 同一个约定 —— 那边是唯一实现，这里只取词性。
REF = re.compile(r"^kk-[a-z]+:.*:(?P<pos>[a-z_]+)(?::\d+:\d+)?(?:#.*)?$")

BLIND = "%blind%"


def evidence_pos(con):
    """→ {word_id: {kaikki 词性}}，来自该词形**所有**证据行（含 sense_id 为空的词级行）。

    🔴 必须收词级行：盲推义项自己没有证据行，能证明它词性的只有同词形上
       那条 `definizione mancante` 占位符留下的 `kk-it:X:verb#0.0`。
    """
    ev = defaultdict(set)
    for wid, ref in con.execute(
            "SELECT word_id, src_ref FROM sense_src WHERE src_ref IS NOT NULL"):
        m = REF.match(ref or "")
        if m:
            ev[wid].add(m.group("pos"))
    return ev


def scan(con):
    """→ ([(sense_id, 词形, 新 pos, 理由)], {族: 计数})。新 pos 为 None 表示清空。"""
    ev = evidence_pos(con)
    todo, fam = [], Counter()
    for sid, wid, w, dpos in con.execute("""
            SELECT s.id, s.word_id, d.word, d.pos
            FROM sense s JOIN dict d ON d.id = s.word_id
            WHERE s.pos = 'v' AND COALESCE(s.hidden, 0) = 0
              AND (d.pos IS NULL OR d.pos <> 'v')
              AND EXISTS(SELECT 1 FROM sense_gloss g
                         WHERE g.sense_id = s.id AND g.src LIKE ?)
            ORDER BY s.id""", (BLIND,)):
        codes = {POS_MAP.get(p) for p in ev.get(wid, ())} - {None}
        if not codes:
            fam["⑤ 无可用证据，证不了错，不动"] += 1
        elif "v" in codes:
            fam["④ 证据里有动词，不动"] += 1
        elif len(codes) == 1:
            new = codes.pop()
            fam["① 证据唯一 → %s" % new] += 1
            todo.append((sid, w, new, "证据唯一"))
        elif dpos in codes:
            fam["② 多词性，用 dict.pos"] += 1
            todo.append((sid, w, dpos, "多词性，dict.pos 在其中"))
        else:
            fam["③ 多词性且 dict.pos 帮不上 → 清空"] += 1
            todo.append((sid, w, None, "证不出唯一词性，宁可留空"))
    return todo, fam


def gate(con):
    """闸：本步的判据在**修完之后**必须查不出任何候选（自洽），
    且 ④ 那 62 条必须还在（判据不是"把 v 一律清掉"）。"""
    todo, fam = scan(con)
    keep = fam["④ 证据里有动词，不动"]
    ok = True
    for name, got, want in (("残余候选", len(todo), 0),
                            ("④ 保留的真动词", keep, 62)):
        good = got == want
        ok &= good
        print("   %s %-18s %s（应 %s）" % ("✅" if good else "🔴", name, f(got), f(want)))
    # 反错配：改过的行，其新 pos 必须仍在该词形的证据里推得出来
    ev = evidence_pos(con)
    bad = 0
    for sid, wid, spos in con.execute(
            "SELECT s.id, s.word_id, s.pos FROM sense s WHERE s.pos IS NOT NULL "
            "AND EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.src LIKE ?)",
            (BLIND,)):
        codes = {POS_MAP.get(p) for p in ev.get(wid, ())} - {None}
        if codes and spos not in codes:
            bad += 1
    good = bad == 0
    ok &= good
    print("   %s %-18s %s（应 0）" % ("✅" if good else "🔴", "词性与证据冲突", f(bad)))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify", "mutate"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    if a.mutate:
        return mutate(ro)
    todo, fam = scan(ro)
    print("■ 候选 %s 条，其中要改 %s 条" % (f(sum(fam.values())), f(len(todo))))
    for k, v in sorted(fam.items()):
        print("   %-28s %s" % (k, f(v)))
    print("\n■ 样本")
    for sid, w, new, why in todo[:10]:
        print("   %-24s v → %-6s %s" % (w[:24], new or "(空)", why))
    if not a.apply:
        ro.close()
        print("\n(未加 --apply，不写库)")
        return 0
    ro.close()
    # `pos` 从 'v' 改成别的短码：非空计数只在清空的那几条上减少。
    cleared = sum(1 for _s, _w, new, _r in todo if new is None)
    with dbtool.session("fix-blind-sense-pos",
                        expect={"__rows__": 0, "sense.pos": -cleared}) as s:
        for sid, _w, new, _r in todo:
            s.execute("UPDATE sense SET pos=? WHERE id=?", (new, sid))
    print("■ 已改 %s 条（其中清空 %s）" % (f(len(todo)), f(cleared)))
    return 0


def mutate(ro):
    """变异验证：故意打坏，闸必须红。

    🔴 变异要打在**闸真正在问的东西**上（`it-display-layer-stage8` 的教训：
       契约闸那一版变异全是"改数据"，而检查问的是"组件有没有渲染"，构造上不可能红）。
       这道闸问的是「`sense.pos` 与证据是否自洽」⇒ 变异就该改 `sense.pos`。
    """
    ev = evidence_pos(ro)
    cases = []

    # 🔴 变异必须挑**闸判断得了**的行。第一版挑的 `apicultura` 一条证据行都没有
    #    （盲推那批里有一族是"连占位符都没有"的词），`codes` 为空 ⇒ 落进第 ⑤ 族
    #    「证不了错，不动」，冲突检查也 `if codes` 短路跳过。于是怎么改都不红 ——
    #    **是变异挑错了行，不是闸假**（`it-display-layer-stage8`：变异没触发先查变异）。
    def pick(pos):
        for sid, w, wid in ro.execute("""SELECT s.id, d.word, s.word_id
                FROM sense s JOIN dict d ON d.id=s.word_id
                WHERE s.pos=? AND (d.pos IS NULL OR d.pos<>'v')
                  AND EXISTS(SELECT 1 FROM sense_gloss g
                             WHERE g.sense_id=s.id AND g.src LIKE ?)""", (pos, BLIND)):
            codes = {POS_MAP.get(p) for p in ev.get(wid, ())} - {None}
            if codes and "v" not in codes:
                return sid, w
        return None

    # ① 把一条已修好的名词改回 v ⇒ 残余候选应变 1
    row = pick("n")
    if row:
        cases.append(("把 %s 的词性改回 v" % row[1], "UPDATE sense SET pos='v' WHERE id=%d" % row[0]))
    # ② 把 ④ 那族里的一条真动词清空 ⇒ 「④ 保留的真动词」应少 1
    row = ro.execute("""SELECT s.id, d.word FROM sense s JOIN dict d ON d.id=s.word_id
        WHERE s.pos='v' AND d.pos IS NULL
          AND EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.src LIKE ?)
        LIMIT 1""", (BLIND,)).fetchone()
    if row:
        cases.append(("把真动词 %s 的词性清空" % row[1], "UPDATE sense SET pos=NULL WHERE id=%d" % row[0]))
    # ③ 给一条盲推义项写一个证据里根本没有的词性 ⇒ 「词性与证据冲突」应变 1
    row = pick("n")
    if row:
        cases.append(("给 %s 写一个证据里没有的词性 conj" % row[1],
                      "UPDATE sense SET pos='conj' WHERE id=%d" % row[0]))
    ro.close()
    import shutil
    import tempfile
    passed = 0
    for name, sql in cases:
        tmp = Path(tempfile.mkdtemp()) / "m.sqlite"
        shutil.copy(paths.DB, tmp)
        con = sqlite3.connect(tmp)
        con.execute(sql)
        con.commit()
        print("\n── 变异：%s" % name)
        red = not gate(con)
        con.close()
        shutil.rmtree(tmp.parent)
        print("   %s" % ("✅ 闸报红" if red else "🔴 闸没报 —— 这道检查是假的"))
        passed += red
    print("\n■ 变异 %s/%s" % (passed, len(cases)))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
