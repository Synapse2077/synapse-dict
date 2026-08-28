#!/usr/bin/env python3
"""把出版层已有的法语定义重新过一遍清洗器。2026-08-27。

═══ 起因 ═══
阶段 8 收尾时跑最后 19 条裁决，16 条"挂上了"的全是**重复**：

    已有: } Variscite.
    新增:   Variscite.

`} ` 是 wikitext 模板残渣。裁决那一步靠「(词形, 洗过的文本) 在不在出版层」判重，
出版层这一侧带着残渣、证据层那一侧洗干净了 ⇒ **判重永远不命中** ⇒ 同一句法语被
当成"还没出版"再挂一遍。

🔴 根因是**提升先于清洗器**：`pipeline/promote_fr_defs.py`（8-22）把 523,723 条法语
定义搬进 `sense_gloss` 时，`pipeline/gloss_clean.py` 还不存在（8-25 才建）。
`[[replay-scripts-undo-fixes]]` 的第二种机制反过来演了一遍 ——
那次是"修复只做在一层、后一步从另一层重灌"，这次是"清洗器晚于搬运"。
⇒ 判据只许一份（`gloss_clean`），这个脚本只负责把出版层**追平**到那一份。

═══ 处理面（全库 648,506 条 lang='fr'）═══
    ① 洗完为空（`Définition manquante ou à compléter. (Ajouter)` / `…`）  882
       其中 882 条义项已经是 hidden=1，1 条可见（`se mêler` r3，gloss 是空串）
    ② 前缀残渣 `}` `{` `&` `*` `?`                                        48
    ③ 词条头泄漏 `\音标\性数词性`                                          43
       —— ③ 这一条判据是本次新加进 `gloss_clean` 的，见那边的 docstring。

⚠️ **可见的只有 64 条**（其余在 hidden=1 的义项上）。数字小，但 ③ 是**渲染出来
   就能看见**的那种错：`Samot` 的"法语定义"是 `\sa.mo\`。
   `docs/FRAMEWORK.md`：错比缺更伤权威。

═══ 可逆 ═══
落库前把每一条的原文写进 `data/work/fr/fr_reclean_before.jsonl`（含主键四元组），
`--undo` 原样写回。删掉的行同样从这份文件重建。

用法（在 fr/ 目录下）：
    python3 -u fixes/reclean_published_fr_defs.py            # 只报数 + 逐条打印
    python3 -u fixes/reclean_published_fr_defs.py --apply    # 落库
    python3 -u fixes/reclean_published_fr_defs.py --undo     # 撤回
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import dbtool                                    # noqa: E402
import paths                                     # noqa: E402
from pipeline import gloss_clean                 # noqa: E402

f = lambda n: format(n, ",")
BEFORE = paths.WORK / "fr_reclean_before.jsonl"


def plan(con):
    """→ (upd, drop)；每项 = (sense_id, kind, seq, word, 旧文本, 新文本)"""
    upd, drop = [], []
    for sid, kind, seq, txt, word in con.execute(
            "SELECT g.sense_id, g.kind, g.seq, g.text, d.word "
            "FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
            "JOIN dict d ON d.id=s.word_id WHERE g.lang='fr'"):
        new = gloss_clean.clean(txt, word)
        if new == " ".join((txt or "").split()):
            continue
        (upd if new else drop).append((sid, kind, seq, word, txt, new))
    return upd, drop


def gates(con, upd, drop):
    ok = True

    def g(name, bad, n):
        nonlocal ok
        print("  %s %s：%s / %s" % ("✅" if not bad else "🔴", name, f(bad), f(n)))
        if bad:
            ok = False

    # ① 新值必须**正是**清洗器算出来的那一个（不是我在这里另写的规则）
    g("① UPDATE 的新值 == clean(旧值, 词形) 且非空",
      sum(1 for s, k, q, w, o, n in upd if not n or n != gloss_clean.clean(o, w)),
      len(upd))
    # ② 删的那些必须洗完确实是空
    g("② DELETE 的 clean(旧值, 词形) == ''",
      sum(1 for s, k, q, w, o, n in drop if gloss_clean.clean(o, w)), len(drop))
    # ③ 🔴 清洗器只许**减**不许**增**：新值必须是旧值去掉若干片段的结果。
    #    判据 = 新值的每个字符按顺序都能在旧值里找到（子序列）。
    #    这一条盯的是"清洗器有没有自己写字"，`[[context-you-give-leaks-into-output]]`。
    def subseq(new, old):
        it = iter(old)
        return all(c in it for c in new)
    g("③ 新值是旧值的子序列（只删不写）",
      sum(1 for s, k, q, w, o, n in upd if not subseq(n, " ".join(o.split()))),
      len(upd))
    # ④ 删完一条 gloss 都不剩的义项 —— 必须能被藏起来，且本来就没有中文/英文
    lost = set()
    for sid, kind, seq, w, o, n in drop:
        tot = con.execute("SELECT COUNT(*) FROM sense_gloss WHERE sense_id=?",
                          (sid,)).fetchone()[0]
        gone = sum(1 for x in drop if x[0] == sid)
        if tot - gone <= 0:
            lost.add(sid)
    withzh = sum(1 for sid in lost if con.execute(
        "SELECT COUNT(*) FROM sense_gloss WHERE sense_id=? AND lang<>'fr'",
        (sid,)).fetchone()[0])
    g("④ 删空的义项里带着中文/英文的（那就不能删）", withzh, len(lost))
    vis = sum(1 for sid in lost if con.execute(
        "SELECT hidden FROM sense WHERE id=?", (sid,)).fetchone()[0] == 0)
    print("  ℹ️ 删空的义项 %s 条，其中当前可见 %s 条 ⇒ 落库时置 hidden=1"
          % (f(len(lost)), f(vis)))
    return ok, sorted(lost)


def show(upd, drop):
    c = Counter()
    for sid, kind, seq, w, o, n in upd:
        c["改"] += 1
    for sid, kind, seq, w, o, n in drop:
        c["删"] += 1
    print("■ 改 %s ｜ 删 %s\n" % (f(c["改"]), f(c["删"])))
    print("── 改（全部 %s 条，逐条读）──" % f(len(upd)))
    for sid, kind, seq, w, o, n in upd:
        print("   %-22s %r\n   %-22s → %r" % (w, " ".join(o.split())[:80], "", n[:80]))
    print("\n── 删（前 20 / %s）──" % f(len(drop)))
    for sid, kind, seq, w, o, n in drop[:20]:
        print("   %-22s %r" % (w, " ".join(o.split())[:80]))


def undo():
    if not BEFORE.exists():
        print("🔴 没有 %s，撤不了" % BEFORE)
        return 1
    rows = [json.loads(x) for x in BEFORE.read_text(encoding="utf-8").splitlines()]
    with dbtool.session("keep-v3-reclean-undo", expect={}) as s:
        for r in rows:
            s.execute("INSERT OR REPLACE INTO sense_gloss"
                      "(sense_id,lang,kind,seq,text,src) VALUES(?,'fr',?,?,?,?)",
                      (r["sense_id"], r["kind"], r["seq"], r["text"], r["src"]))
        for sid in {r["sense_id"] for r in rows if r.get("hid")}:
            s.execute("UPDATE sense SET hidden=0 WHERE id=?", (sid,))
    print("✓ 已撤回 %s 条" % f(len(rows)))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo", action="store_true")
    a = ap.parse_args()
    if a.undo:
        return undo()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    upd, drop = plan(con)
    show(upd, drop)
    print("\n══ 闸 ══")
    ok, lost = gates(con, upd, drop)
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 闸未过，**不写库**")
        return 1

    src_of = dict(con.execute(
        "SELECT sense_id || '\x1f' || kind || '\x1f' || seq, src "
        "FROM sense_gloss WHERE lang='fr'"))
    lost_set = set(lost)
    with BEFORE.open("w", encoding="utf-8") as fh:
        for sid, kind, seq, w, o, n in upd + drop:
            fh.write(json.dumps({
                "sense_id": sid, "kind": kind, "seq": seq, "text": o,
                "src": src_of.get("%d\x1f%s\x1f%d" % (sid, kind, seq)),
                "hid": sid in lost_set,
            }, ensure_ascii=False) + "\n")

    with dbtool.session("keep-v3-reclean-fr-defs",
                        expect={"#sense_gloss": -len(drop)}) as s:
        s.executemany(
            "UPDATE sense_gloss SET text=? WHERE sense_id=? AND lang='fr' "
            "AND kind=? AND seq=?",
            [(n, sid, kind, seq) for sid, kind, seq, w, o, n in upd])
        s.executemany(
            "DELETE FROM sense_gloss WHERE sense_id=? AND lang='fr' "
            "AND kind=? AND seq=?",
            [(sid, kind, seq) for sid, kind, seq, w, o, n in drop])
        s.executemany("UPDATE sense SET hidden=1 WHERE id=?",
                      [(sid,) for sid in lost])
    print("✓ 写入完成（改 %s、删 %s、藏 %s）" % (f(len(upd)), f(len(drop)), f(len(lost))))
    print("  原文已落 %s（--undo 可原样写回）" % BEFORE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
