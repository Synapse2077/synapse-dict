#!/usr/bin/env python3
"""指针文案的「目标位」上混进了英文用法说明：在源头 `sense_relation` 修。2026-08-16。

═══ 怎么发现的 ═══
建译文质量尺子时，T 层（模板产出，14.7 万条）本该走确定性核验而不是抽样。
第一版核验**全绿**，我差点就收了 —— 但它核的是「模板套得对不对」，
而不是「套进去的东西对不对」。补一条「目标位必须是个词形」之后，逮到 88 条：

    Mi    → 「mi、sometimes used when referring to God or another important
             figure who is understood from context 的敬称大写变体」
    face  → 「fa、third-person singular present indicative of fare 的异体形式」
    sun   → 「su used before a vowel 的异体形式」

**用户在页面上看到的就是这一整串英文。**

═══ 根因 ═══
英文版的 gloss 形如 `alternative form of fa, third-person singular present
indicative of fare` —— 逗号后面那半是**对目标词 `fa` 的语法描述**，不是第二个目标。
抽取器把逗号切开、每段都当成一个 target 灌进了 `sense_relation`。
`su used before a vowel` 是另一种形状：说明**粘在同一个 target 串里**。

═══ 为什么改 `sense_relation` 而不是只改中文 ═══
中文是从关系表模板生成的。只改中文，下次任何重放都会把它长回来
（`replay-scripts-undo-fixes`：UNIQUE 保证不重复，不保证不倒退）。
⇒ 修源头，再从源头重新生成中文。

═══ 判据（按含义写，不按长短）═══
一个 target 应当是**一个意语词形或词组**（或缩写的展开式）。它不是 target，当它：
    ① 整串是对**别的词**的语法描述：`third-person singular present indicative of fare`
    ② 整串是用法说明：`used epenthetically after a consonant`
    ③ 说明粘在真 target 后面：`su used before a vowel` ⇒ 截到 `su`

⚠️ 判据吃不掉的两条逐条判、写在 `BY_HAND` 里（`fix_surgical_suffix` 同一套做法）。

用法（在 it/ 目录下）：
    python3 fixes/trim_pointer_notes.py            # 只看，逐条打印 前→后
    python3 fixes/trim_pointer_notes.py --apply
    python3 fixes/trim_pointer_notes.py --verify
    python3 fixes/trim_pointer_notes.py --mutate   # 变异验证：闸必须报红
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbtool          # noqa: E402
import paths           # noqa: E402
from recover_alt_of import zh_label   # noqa: E402

TAG = "+fix:ptr-note"

# ① 整串是语法描述
GRAM = re.compile(
    r"^(?:first|second|third)[-/ ].*\bof\b|"
    r"^(?:plural|singular|feminine|masculine|past|present|imperative)\b.*\bof\b|"
    r"^synonym of\b|^\w+ (?:participle|form) of\b|^apocopic form of\b", re.I)
# ② 整串是用法说明
NOTE_ONLY = re.compile(r"^(?:used|sometimes|often|usually|only when|as in|on car)\b", re.I)
# ③ 说明粘在真 target 后面 —— 从这里截断
NOTE = re.compile(r"\s+(?:used\b|sometimes\b|often\b|usually\b|only when\b|as in\b|"
                  r"for euphony\b|when it\b|on car\b)", re.I)

# 判据吃不掉的，逐条判。键是词形，值是**整条目标列表**的最终值。
BY_HAND = {
    # `i.e.` 是拉丁语 id est 的缩写；`isto es or Latin id est` 是散文，不是目标
    "i.e.": ["id est"],
    # `(imperative) confronta` 的词性标注不该留在目标位
    "cfr.": ["confronta"],
}


def trim(t):
    """→ 修好的目标；None 表示这一项整个不是目标，该删。"""
    if GRAM.search(t) or NOTE_ONLY.search(t):
        return None
    m = NOTE.search(t)
    return (t[:m.start()].strip() if m else t) or None


def is_note(t):
    """判据的另一面：这个 target 里还留着英文说明吗 —— 闸用这个。"""
    return bool(GRAM.search(t) or NOTE_ONLY.search(t) or NOTE.search(t))


def pointer_senses(con):
    """T 层里的指针文案那批（模板产出、非 via-fr）。"""
    return {sid: (w, zh) for sid, w, zh in con.execute(
        "SELECT g.sense_id, d.word, g.text FROM sense_gloss g "
        "JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id "
        "WHERE g.lang='zh' AND g.seq=0 AND COALESCE(s.hidden,0)=0 "
        "AND g.src LIKE 'template%' AND g.src NOT LIKE '%via-fr%'")}


def load_rel(con, sids):
    rel = {}
    for rid, sid, t in con.execute(
            "SELECT id, sense_id, target FROM sense_relation "
            "WHERE sense_id IS NOT NULL ORDER BY id"):
        if sid in sids:
            rel.setdefault(sid, []).append((rid, t))
    return rel


def plan(con):
    """→ [(word, sid, 旧中文, 新中文, [(rid,新target或None)])]"""
    sids = pointer_senses(con)
    rel = load_rel(con, sids)
    en = {sid: t for sid, t in con.execute(
        "SELECT sense_id, text FROM sense_gloss WHERE lang='en' AND seq=0")}
    out = []
    for sid, (w, zh) in sids.items():
        rows = rel.get(sid, [])
        if w in BY_HAND:
            want = BY_HAND[w]
            acts = [(rid, want[i] if i < len(want) else None)
                    for i, (rid, _t) in enumerate(rows)]
            new_t = want
        else:
            acts = [(rid, trim(t)) for rid, t in rows]
            new_t = [x for _r, x in acts if x]
        if [t for _r, t in rows] == new_t:
            continue
        if not new_t:            # 一个目标都不剩就别动，留着让闸继续报
            continue
        nz = zh_label(en.get(sid), new_t)[0]
        out.append((w, sid, zh, nz, acts))
    out.sort(key=lambda x: x[0].lower())
    return out


def residual(con):
    """闸的判据：指针文案的目标位上还有几条是英文说明。"""
    sids = pointer_senses(con)
    rel = load_rel(con, sids)
    return [(sids[sid][0], t) for sid, rows in rel.items()
            for _r, t in rows if is_note(t)]


def gate(con):
    print("\n═══ 闸 ═══")
    left = residual(con)
    rows = plan(con)
    checks = [
        ("🔴 指针目标位上不许再有英文说明", len(left), 0),
        ("🔴 已经没有可修的了（修完就该为 0）", len(rows), 0),
        ("改过的中文仍能从关系表逐字节重建",
         sum(1 for _w, _s, _o, n, _a in rows if not n), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-40s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    for w, t in left[:8]:
        print("     ⚠️ %-18s %s" % (w[:18], t[:60]))
    return ok


def mutate():
    """把干净的 target 人为弄脏，闸必须报红。一条永远通过的检查等于没检查。"""
    cases = [
        ("语法描述整串", "third-person singular present indicative of fare"),
        ("用法说明整串", "used epenthetically after a consonant"),
        ("说明粘在真词后", "su used before a vowel"),
        ("干净词形（不该报）", "fare"),
        ("干净词组（不该报）", "Organizzazione Mondiale del Commercio"),
    ]
    print("\n═══ 变异验证 ═══")
    ok = True
    for name, t in cases:
        want_red = "不该报" not in name
        red = is_note(t)
        good = red == want_red
        ok &= good
        print("   %s %-22s %-46s %s" % ("✅" if good else "🔴", name, t[:46],
                                        "报红" if red else "没报"))
    print("\n   变异验证 %s" % ("通过" if ok else "🔴 判据是假的"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    rows = plan(ro)
    print("■ 将修 %d 条指针文案（源头改 sense_relation，中文从源头重新生成）\n" % len(rows))
    for w, _sid, old, new, _acts in rows:
        print("%-16s %s\n%16s → %s" % (w[:16], old[:88], "", new[:88]))
    ro.close()
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    # UNIQUE(word_id, sense_id, kind, target)：截断后可能与同义项已有的行撞，撞了就删
    with dbtool.session("trim-pointer-notes", expect={"#sense_gloss": 0}) as s:
        seen = {}
        for _w, sid, _o, new, acts in rows:
            for rid, t in acts:
                if t is None or (sid, t) in seen:
                    s.execute("DELETE FROM sense_relation WHERE id=?", (rid,))
                else:
                    seen[(sid, t)] = rid
                    s.execute("UPDATE sense_relation SET target=? WHERE id=?", (t, rid))
        s.executemany(
            "UPDATE sense_gloss SET text=?, src=COALESCE(src,'unknown')||? "
            "WHERE sense_id=? AND lang='zh' AND seq=0",
            [(new, TAG, sid) for _w, sid, _o, new, _a in rows])
    print("\n■ 已修 %d 条" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
