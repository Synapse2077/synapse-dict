#!/usr/bin/env python3
"""收尾单 C39 的**改正**：那不是「源头噪声」，是葡语的**单复同形**。2026-08-31。

═══ 我先把它记错了 ═══
2026-08-31 全表复核时，我圈出「38 条义项的葡语原文指向自己」，判为源头噪声、
准备照 C21b 的先例隐掉。**两步都错**：

  🔴 ① 判据又宽了（同一形状第 N 次）。我写的是
     `tgt == w or tgt.endswith(" "+w) or tgt.startswith("plural de "+w)`，
     而 `referent()` 对这一族**根本没解析成功**、原样返回了整串 `"plural de Adães"`
     ⇒ 第三个条件把一堆**真释义**也圈了进来：
         cimão      → forma parte da locução de cimão, baixo o braço   ← 真释义
         gebre      → usado na locução em gebre                        ← 真释义
         azinhavrar → infinitivo impessoal do verbo azinhavrar         ← 葡语真事实（C9 同族）
     38 条里 **16 条不是自指**。

  🔴 ② 剩下 22 条**不是噪声，是真信息**。回源核（`ptwiktionary.jsonl.gz`）：

         Dóris  [noun] glosses: ['prenome feminino']            ← 一个词条
         Dóris  [noun] glosses: ['plural de Dóris']             ← **另一个词条**

     源头给不变复数**单开一页**。以 -s 结尾的葡语姓名（Adães/Anes/Clóvis/Dóris…）
     复数与单数同形，这一页就是在说这件事。**隐掉＝删掉真信息。**
     ⇒ 处置从「隐」改成「补中文」。

⚠️ **`fura-filas` 是唯一的例外，有意排除**：同一页的另一条义项写着
   `forma plural de fura-fila`（带 `form_of`），**真正的原形是 fura-fila**，
   自指那条是源头笔误。判据：**同一个词下已有指向别的原形的复数指针 ⇒ 不补**。

═══ 判据（按含义，三条都要）═══
① 原文**字面**是 `<关系词> de <本词>`（不做归一、不做模糊匹配 —— 葡语变音符是区别性的）
② 这个词**没有**指向别的原形的复数指针（排除源头笔误那一类）
③ 词尾是 -s/-x/-z —— **单复同形只发生在这里**。不满足就不补，宁可少补
   （`[[criteria-from-meaning-not-form]]`：判据从含义出发，这一条就是葡语构词法本身）

用法（在 pt/ 目录下）：
    python3 fixes/fill_invariant_plural_zh.py
    python3 fixes/fill_invariant_plural_zh.py --apply
"""
import argparse
import collections
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from fill_xref_zh import REF_PATTERNS   # noqa: E402  ⭐ 判据只许一份

SRC = "invariant-plural"
KIND = {"plural": "复数", "forma plural": "复数", "feminino": "阴性", "masculino": "阳性"}
SELF = re.compile(r"^\s*(plural|forma plural|feminino|masculino)\s+de\s+(.+?)\s*\.?\s*$", re.I)
# ③ 单复同形只发生在词尾 -s/-x/-z（葡语构词法）
INVARIANT_END = ("s", "x", "z")

# ⭐ 负控 = 我今天误圈过的那 16 条真释义，一条都不许被判为自指。
NEG = ["forma parte da locução de cimão, baixo o braço",
       "usado na locução em gebre",
       "usado na expressão voltar à vaca-fria",
       "infinitivo impessoal do verbo azinhavrar",
       "empregue na locução adverbial a desoras",
       "de modo minimalisticamente"]


def selfref(word, text):
    """原文字面在说「本词的复数/阴性就是本词自己」⇒ (关系词中文) 或 None。"""
    m = SELF.match(text or "")
    if not m or m.group(2).strip() != word:
        return None
    return KIND[m.group(1).lower()]


def plan(con):
    # ② 已有指向**别的**原形的复数指针的词，整词排除（fura-filas 那类源头笔误）。
    #    🔴 第一版查的是**变形层** —— 漏掉了 `fura-filas`，因为那条
    #    `forma plural de fura-fila` 从没进过变形层，它躺在**同一个词的另一条义项**里。
    #    ⇒ 证据在哪一层，判据就查哪一层。两层都查。
    other = {r[0] for r in con.execute(
        "SELECT i.word_id FROM inflection i JOIN dict d ON d.id=i.word_id "
        " WHERE i.base<>d.word")}
    #    🔴 第二版还是漏了 `fura-filas`：它的兄弟义项写的是 `o mesmo que fura-fila`
    #    —— 不是复数指针，是**异体指针**。真正的信号是「这个词本身指向另一个词」。
    #    🔴 第三版拿整个 `referent()` 去判，**反过来排除了 21 条**：它带一个**裸词兜底**分支，
    #    `sobrenome`（"姓氏"）也被当成了指向 `sobrenome` 这个词的指针。
    #    那个兜底本来只该跑在**已知是指针**的串上（`[[criteria-narrower-than-you-think]]`：
    #    import 对了不等于用对了，要问「这判据当初为了回答哪个问题」）。
    #    ⇒ 只用 `REF_PATTERNS` 那几条**显式引用**（`o mesmo que X`／`ver X`／`vide X`），
    #      不用兜底分支。判据仍然只有一份，来自同一个文件。
    for wid, w, t in con.execute(
            "SELECT s.word_id, d.word, g.text FROM sense s JOIN dict d ON d.id=s.word_id "
            "  JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='pt'"):
        for pat in REF_PATTERNS:
            m = pat.match(t or "")
            if m and m.group(1).strip().strip("«»\"'“”") != w:
                other.add(wid)
                break
    rows = con.execute(
        "SELECT s.id, s.word_id, d.word, g.text FROM sense s "
        "  JOIN dict d ON d.id=s.word_id "
        "  JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='pt' "
        " WHERE COALESCE(s.hidden,0)=0 "
        "   AND NOT EXISTS(SELECT 1 FROM sense_gloss z "
        "                   WHERE z.sense_id=s.id AND z.lang='zh')").fetchall()
    hit, stat = [], collections.Counter()
    for sid, wid, w, t in rows:
        lab = selfref(w, t)
        if not lab:
            continue
        if wid in other:
            stat["② 同词下另有指向别的原形的指针（源头笔误，不补）"] += 1
            continue
        if not w.lower().endswith(INVARIANT_END):
            stat["③ 词尾不是 -s/-x/-z（单复同形不成立，不补）"] += 1
            continue
        stat["✅ 可补"] += 1
        hit.append((sid, w, t, "%s 的%s（与单数同形）" % (w, lab)))
    return hit, stat


def main(a):
    print("■ 负控：我今天误圈过的 %d 条真释义，必须一条都判不出自指" % len(NEG))
    bad = 0
    for t in NEG:
        got = selfref(t.split()[-1], t)
        bad += bool(got)
        print("   %s %s" % ("🔴 被误圈" if got else "✅", t[:56]))
    if bad:
        print("🔴 负控不过，不动库")
        return 1
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    hit, stat = plan(con)
    print("\n■ 分桶：")
    for k, v in stat.most_common():
        print("   %5d  %s" % (v, k))
    print("\n■ 全部 %d 条（人眼逐条核，量小到能读完）：" % len(hit))
    for _sid, w, t, zh in hit:
        print("   %-20s %-26s → %s" % (w[:20], t[:26], zh))
    con.close()
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("fill-pt-invariant-plural",
                        expect={"#sense_gloss": len(hit)}) as s:
        s.executemany("INSERT INTO sense_gloss(sense_id, lang, kind, seq, text, src) "
                      "VALUES(?,'zh','equivalent',1,?,?)",
                      [(sid, zh, SRC) for sid, _w, _t, zh in hit])
    print("\n✓ 补 %d 条（`src='%s'`，一条 SQL 可全撤）" % (len(hit), SRC))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    sys.exit(main(ap.parse_args()))
