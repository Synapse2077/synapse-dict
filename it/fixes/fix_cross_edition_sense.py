#!/usr/bin/env python3
"""跨版义项合并造成的四条内容错误。2026-08-21（点测评审）。

═══ 一个共同的形状 ═══
出版层一条 `sense` 上同时挂着英文版和意语版的原文。**多数情况下两版说的是一回事**
（全库 53,000 条 en+it 并存），但有一小撮两版说的根本不是一个意思，而中文
**只跟了其中一支** —— 用户看到的中文与它下面并排显示的另一版原文互相矛盾。

    treno  en=train (connected sequence of people or things)   it=veicolo che viaggia su rotaie…
           zh=（人或物的）系列，行列        ← 跟了 en，**把「火车」整个丢了**
    libro  en=phloem; foliage             it=…in fusti, rami e radici（茎/枝/根，没有叶）
           zh=韧皮部，叶片                 ← 跟了 en 的错义支
    fare   en=to gift（给出）              it=in romanesco significa ricevere un regalo（收到）
           zh=赠送，馈赠                   ← 两版方向相反
    dei    en=alternative form of dey（阿尔及尔总督）  it=variante di dèi（众神）
           zh=dey 的异体形式               ← 两版是**完全不同的两个词**

🔴 这个面**无法确定性判定**：判「en 与 it 语义是否一致」要么人读要么送模型。
   53,000 是上界不是缺陷数，已记账。本脚本只动**外审指出、我逐条回源证实**的四条。

═══ 裁决依据 ═══
· treno / libro：以**意语版**为准。它是意语版自己给意语词写的定义（A2 的精神），
  而 en 那两条是英文版编者选的英文对应词，`foliage`（叶）与意语原文的
  「茎、枝、根中的组织」直接冲突，`connected sequence` 丢掉了最常用的「火车」。
  ⚠️ treno 的中文**同时给出两义**：意语原文是火车，而 en 的「一串」也确实是 treno 的
  引申义（下面 rank=16 另有一条「时间上紧密相连的序列」）—— 首义必须先说火车。
· fare：以意语版为准，但**这条我把握最低**。理由：it 原文带明确的方言限定
  （`in romanesco`）和完整描述，en 的 `to gift` 只有两个词、无限定；意语版对自己
  语言的方言用法更可能是对的。⚠️ 若日后回源发现 en 对，这条要翻回来。
· dei：**两支都是真的，拆成两条**，不是删掉一支。英文版那条 dey（阿尔及尔总督的
  异体拼写）不是假数据。⇒ it 那支挪到 `dei` 那个**本来就空着的 noun 词条**上
  （entry 176965 = dio 复数那一支，之前 0 条义项），顺带把空词条填上。

用法（在 it/ 目录下）：
    python3 fixes/fix_cross_edition_sense.py            # 干跑
    python3 fixes/fix_cross_edition_sense.py --apply
    python3 fixes/fix_cross_edition_sense.py --verify
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

f = lambda n: format(n, ",")

# ── 改中文（sense_id → (词, 旧中文, 新中文, 理由)）─────────────────────────
REWRITE = {
    12064: ("treno", "（人或物的）系列，行列", "火车，列车；（连成一串的人或物）行列",
            "意语原文 veicolo che viaggia su rotaie = 火车；例句 salire sul treno 也是上火车"),
    936:   ("libro", "韧皮部，叶片", "韧皮部",
            "意语原文只说 fusti/rami/radici（茎枝根），没有叶；foliage 是 en 的错义支"),
    1561:  ("fare", "赠送，馈赠", "（罗马方言）收受贵重礼物",
            "意语原文 ricevere un regalo importante = 收到，与 en 的 to gift 方向相反"),
}

# ── 拆义项：把某条 gloss 挪到一个新 sense 上 ───────────────────────────────
SPLIT = {
    198269: dict(
        word="dei", lang="it", target_entry=176965,
        zh="dèi 的异体形式（dio「神」的复数）",
        why="en=dey（阿尔及尔总督）与 it=dèi（众神）是两个不同的词；"
            "两支都真，拆开而不是删。目标 entry 是 dei 本来就空着的 noun 词条"),
}


def scan(con):
    rew, spl = [], []
    for sid, (w, old, new, why) in REWRITE.items():
        cur = con.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang='zh' AND seq=0",
                          (sid,)).fetchone()
        if not cur:
            raise SystemExit("🔴 sense %d 没有中文" % sid)
        if cur[0] != old:
            raise SystemExit("🔴 sense %d 中文已变：期望 %r，实际 %r —— 先回头核对" % (sid, old, cur[0]))
        rew.append((sid, w, old, new, why))
    for sid, spec in SPLIT.items():
        g = con.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang=? AND seq=0",
                        (sid, spec["lang"])).fetchone()
        if not g:
            raise SystemExit("🔴 sense %d 没有 %s 原文" % (sid, spec["lang"]))
        n = con.execute("SELECT COUNT(*) FROM sense WHERE entry_id=?",
                        (spec["target_entry"],)).fetchone()[0]
        if n:
            raise SystemExit("🔴 目标 entry %d 已经有 %d 条义项了，不能当空位用"
                             % (spec["target_entry"], n))
        spl.append((sid, spec, g[0]))
    return rew, spl


def gate(con):
    ok = True
    for sid, (w, old, new, _why) in REWRITE.items():
        cur = con.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang='zh' AND seq=0",
                          (sid,)).fetchone()
        good = cur and cur[0] == new
        ok &= bool(good)
        print("   %s %-8s %s" % ("✅" if good else "🔴", w, cur[0] if cur else "(无)"))
    for sid, spec in SPLIT.items():
        n = con.execute("SELECT COUNT(*) FROM sense WHERE entry_id=?",
                        (spec["target_entry"],)).fetchone()[0]
        left = con.execute("SELECT COUNT(*) FROM sense_gloss WHERE sense_id=? AND lang=?",
                           (sid, spec["lang"])).fetchone()[0]
        good = n == 1 and left == 0
        ok &= good
        print("   %s %-8s 新词条义项=%d，原义项上残留的 %s 原文=%d"
              % ("✅" if good else "🔴", spec["word"], n, spec["lang"], left))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        ok = gate(ro)
        ro.close()
        return 0 if ok else 1
    rew, spl = scan(ro)
    ro.close()
    print("■ 改中文 %d 条" % len(rew))
    for sid, w, old, new, why in rew:
        print("     %-8s %r\n              → %r\n              理由：%s" % (w, old, new, why))
    print("■ 拆义项 %d 条" % len(spl))
    for sid, spec, text in spl:
        print("     %-8s 把 %s 原文 %r 挪到 entry %d，新中文 %r"
              % (spec["word"], spec["lang"], text, spec["target_entry"], spec["zh"]))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("fix-cross-edition-sense",
                        expect={"__rows__": 0, "#sense": len(spl), "#sense_gloss": len(spl)}) as s:
        for sid, w, old, new, _why in rew:
            # `src` 标上人工裁决，防下一轮重译把它盖回去（`replay-scripts-undo-fixes`）
            s.execute("UPDATE sense_gloss SET text=?, src=COALESCE(src,'')||'+fix:cross-edition' "
                      "WHERE sense_id=? AND lang='zh' AND seq=0", (new, sid))
        for sid, spec, _text in spl:
            wid, rank = s.execute("SELECT word_id, rank FROM sense WHERE id=?", (sid,)).fetchone()
            cur = s.execute("SELECT MAX(rank) FROM sense WHERE word_id=?", (wid,)).fetchone()[0]
            s.execute("INSERT INTO sense (word_id, rank, pos, entry_id, hidden) VALUES (?,?,?,?,0)",
                      (wid, (cur or 0) + 1, "n", spec["target_entry"]))
            new_sid = s.execute("SELECT last_insert_rowid()").fetchone()[0]
            # 把那一支原文**挪**过去（不是复制），再给新义项配中文
            s.execute("UPDATE sense_gloss SET sense_id=? WHERE sense_id=? AND lang=?",
                      (new_sid, sid, spec["lang"]))
            s.execute("INSERT INTO sense_gloss (sense_id, lang, kind, seq, text, src) "
                      "VALUES (?,'zh','equivalent',0,?,'fix:cross-edition')",
                      (new_sid, spec["zh"]))
        s.written = len(rew) + len(spl)
    print("\n■ 已改 %s 条中文、拆出 %s 条义项" % (f(len(rew)), f(len(spl))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
