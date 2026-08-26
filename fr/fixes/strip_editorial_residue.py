#!/usr/bin/env python3
"""清掉法语释义里的**编者残渣**（「定义待补充」占位符等）。2026-08-24。

    Définition manquante ou à compléter. (Ajouter)                    → 整条无内容 ⇒ 隐藏义项
    Définition manquante ou à compléter. (Ajouter) Variante de farmer. → `Variante de farmer.`

═══ 🔴 我的第一版判据是「以占位符开头就整条排除」，那会扔掉 45 条真释义 ═══
878 条**以**占位符开头，但其中 45 条占位符**后面还跟着真定义**
（`(Ajouter) Variante de farmer.` / `(Ajouter) (Ésotérisme) Processus symbolique…`）；
另有 80 条占位符**长在句中**（`Ancienne unité de mesure. Définition manquante…`）。
⇒ 判据必须是「**先剥、再看剩下什么**」，不是「看开头长什么样」。
   `[[criteria-narrower-than-you-think]]` 的同一个形状，这次是**判据比对象更宽**。

═══ 剥完为空的怎么办：隐藏义项，不删行 ═══
864 条剥完什么都不剩。实测这 864 个义项**零内容**：
无 `sense_tag` / 无 `example` / 无 `sense_relation` / 无中文。
⇒ `sense.hidden=1`。**不删行、不动 text**，清掉 flag 就完全恢复
   （`[[prefer-reversible-designs]]`）。
⚠️ 其中 483 个是该词**唯一**的义项 ⇒ 隐藏后那 483 个词只剩音标/词性/变形、没有释义行。
   这是对的（词典里写「定义缺失」比不写更伤），但**阶段 8 必须能渲染"零可见义项"的词条**。

═══ 为什么在翻译**之前**做 ═══
不做的话这 864 条会被送模型，翻回来是「定义缺失或待补充」——
花钱买一条不该上架的中文。承 `strip_footnote_refs.py` 的同一条理由。

用法（在 fr/ 目录下）：
    python3 fixes/strip_editorial_residue.py           # 干跑
    python3 fixes/strip_editorial_residue.py --apply
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

# 全库逐条看过取值才定的判据（含残渣共 987 条，无一例外落在这八种里）
RESIDUE = [
    r"D[ée]finition manquante ou [àa] compl[ée]ter\.?",     # 931
    r"Exemple d[’']utilisation manquant\.?",                #  28
    r"\(Ajouter\)",                                         # 959（总是跟在上面两种后面）
    r"\(d[ée]finition [àa] v[ée]rifier\)",                  #  12  编者存疑
    r"\(\?+\)",                                             #  16  编者存疑 `(?)` / `(??)`
    r"Voir Discussion\s*:\S*",                              #   1
    r"!!.*?!!",                                             #   1（编者给自己留的待办）
    r"\(cf\. les citations ci-dessous[^)]*\)",              #   1
    # 全量翻完之后才发现的一族：**词源**占位符也混进了释义字段（模型对它全部留空）
    r"[ÉE]tymologie manquante ou incompl[èe]te\.?"
    r"(?:\s*Si vous (?:la |le )?connaissez[^.]*\.)?",       #   4
]
RX = re.compile("|".join(RESIDUE))

# 🔴 `[àa] v[ée]rifier` 全库 40 条，其中 28 条是**正常法语**
#    （`Test destiné à vérifier le comportement…`）⇒ 判据必须带括号，只认 `(définition à vérifier)`。


def tidy(s):
    """收拾**剥完之后**留下的标点残渣。只删标点，不碰字母数字（有断言保证）。"""
    s = " ".join(s.split())
    s = re.sub(r"\s+([\.,])(?![\.…])", r"\1", s)   # `très étonnant .` → `très étonnant.`
    s = re.sub(r"^[\.,;:…\-–—}\s]+", "", s)        # `. Personne qui…` / `} Photographie…`
    s = re.sub(r"\.\s*[\.…]+", ".", s)             # `Une matière plastique. …` → `…plastique.`
    s = re.sub(r"\s+\)", ")", s)                   # `(Bordelais )` ← 剥掉了里面的 `(?)`
    return s.strip()


# 剥完只剩一个**吊着的介词/冠词**，语义为零。全库就这 2 条，写死，不造「像不像残句」的判据
# —— `[[criteria-from-meaning-not-form]]`：2 条的规模不值得发明一个形式代理。
STUB = {
    "Geste consistant à",
    "Habitant de",
}

# ⚠️ **不动**的近亲，写在这里免得以后有人顺手加进去：
#   `(Note : …)` 52 条 —— 是**真内容**（「Note : 这个词在该行业消失前一直在用」）
#   `à préciser` 9 条 —— 多数是正常法语（`Déterminant servant à préciser…`）
KEEP_RX = re.compile(r"\(Note\s*:|[àa] pr[ée]ciser")

# 另一族：wiktextract 的花括号模板残渣，全库just 2 条，逐条写死改法
BRACE = {
    356567: ("Pluriel de {{lien|prestolet|fr}.", "Pluriel de prestolet."),
    645976: ("}} Relatif à une anatopie ; propre à un monde fictif formant l'équivalent "
             "différentiel du monde réel.",
             "Relatif à une anatopie ; propre à un monde fictif formant l'équivalent "
             "différentiel du monde réel."),
}

# 剥完只剩这些字符 ⇒ 视为空
EMPTY = re.compile(r"^[\s\.…·、,;:！!？?\-–—]*$")


def plan(con):
    """→ (改文本的, 要隐藏的)。两者互斥。"""
    edit, hide = [], []
    for sid, lang, kind, seq, t in con.execute(
            "SELECT sense_id, lang, kind, seq, text FROM sense_gloss WHERE lang='fr'"):
        if sid in BRACE:
            before, after = BRACE[sid]
            if " ".join(t.split()) == before:
                edit.append((sid, lang, kind, seq, t, after))
            continue
        if not RX.search(t):
            continue
        new = tidy(RX.sub(" ", t))
        if EMPTY.match(new) or new.rstrip(".…") in STUB:
            hide.append((sid, t))
        else:
            edit.append((sid, lang, kind, seq, t, new))
    return edit, hide


def invariants(con, edit, hide):
    bad = {}
    # ① 改完不许还剩残渣
    bad["改完仍含残渣"] = sum(1 for *_x, n in edit if RX.search(n))
    # ② 该保留的近亲一条都不许被碰
    bad["误伤 (Note:/à préciser)"] = sum(
        1 for *_x, t, n in edit
        if len(KEEP_RX.findall(t)) != len(KEEP_RX.findall(n)))
    # ③ 除被剥掉的残渣外，**一个字母/数字都不许动**（`tidy` 只许删标点和空白）。
    #    这条比"逐字相等"松一点、但比"长度相等"严 —— 它精确地表达了 `tidy` 的契约。
    word = lambda x: re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ]", "", x)      # noqa: E731
    bad["tidy 动了字母数字"] = sum(
        1 for sid, _l, _k, _q, t, n in edit
        if sid not in BRACE and word(RX.sub(" ", t)) != word(n))
    # ③' 改完不许留下我自己造的标点残渣
    bad["改完仍有 ' .' 或首标点"] = sum(
        1 for *_x, n in edit if re.search(r"\s[\.,](?![\.…])", n) or re.match(r"^[\.,;:…}]", n))
    # ④ 要隐藏的必须真的**零内容** —— 隐藏是有代价的，判据必须比"看着像空"硬
    if hide:
        ids = [s for s, _t in hide]
        q = ",".join("?" * len(ids))
        for tbl, col in (("sense_tag", "sense_id"), ("example", "sense_id"),
                         ("sense_relation", "sense_id")):
            bad["要隐藏的却有 " + tbl] = con.execute(
                "SELECT count(*) FROM %s WHERE %s IN (%s)" % (tbl, col, q), ids).fetchone()[0]
        bad["要隐藏的却有中文"] = con.execute(
            "SELECT count(*) FROM sense_gloss WHERE lang='zh' AND sense_id IN (%s)" % q,
            ids).fetchone()[0]
    # ⑤ 两组不许有交集
    bad["同一 sense 既改又隐"] = len({s for s, *_x in edit} & {s for s, _t in hide})
    return {k: v for k, v in bad.items() if v}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    edit, hide = plan(con)
    print("■ 剥完仍有内容 → 改文本 %s 条" % format(len(edit), ","))
    print("■ 剥完为空     → 隐藏义项 %s 条" % format(len(hide), ","))

    bad = invariants(con, edit, hide)
    print("\n── 不变量 ──")
    if bad:
        print("🔴 红了，**不写**：%s" % bad)
        return 1
    print("   ①改完无残渣 ②(Note:) 未误伤 ③非残渣字符未动 ④待隐藏项零内容 ⑤两组无交集 —— 全绿")

    only = con.execute("""SELECT count(*) FROM sense s WHERE s.id IN (%s)
        AND (SELECT count(*) FROM sense s2 WHERE s2.word_id=s.word_id AND s2.hidden=0)=1"""
                       % ",".join("?" * len(hide)), [s for s, _t in hide]).fetchone()[0]
    print("\n⚠️ 隐藏后**一个可见义项都不剩**的词：%s 个（阶段 8 要能渲染这种词条）"
          % format(only, ","))

    print("\n── 改文本样本 10 条 ──")
    for *_x, t, n in edit[:10]:
        print("   %-88s\n   → %s" % (" ".join(t.split())[:88], n[:88]))

    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0

    bak = paths.WORK / "fr_editorial_residue_before.jsonl"
    bak.parent.mkdir(parents=True, exist_ok=True)
    bak.write_text("\n".join(
        [json.dumps({"op": "edit", "sense_id": s, "lang": l, "kind": k, "seq": q, "before": t},
                    ensure_ascii=False) for s, l, k, q, t, _n in edit] +
        [json.dumps({"op": "hide", "sense_id": s, "text": t}, ensure_ascii=False)
         for s, t in hide]), encoding="utf-8")
    print("\n■ 改前原文已留痕 → %s" % bak)

    with dbtool.session("keep-v3-editorial", expect={}) as s:
        s.executemany(
            "UPDATE sense_gloss SET text=? WHERE sense_id=? AND lang=? AND kind=? AND seq=?",
            [(n, sid, l, k, q) for sid, l, k, q, _t, n in edit])
        s.executemany("UPDATE sense SET hidden=1 WHERE id=?", [(s_,) for s_, _t in hide])
    print("✓ 改文本 %s 条 / 隐藏义项 %s 条"
          % (format(len(edit), ","), format(len(hide), ",")))

    con2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = sum(1 for (t,) in con2.execute(
        "SELECT text FROM sense_gloss WHERE lang='fr'") if RX.search(t))
    vis = con2.execute("""SELECT count(*) FROM sense s
        JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='fr'
        LEFT JOIN sense_gloss z ON z.sense_id=s.id AND z.lang='zh'
        WHERE z.sense_id IS NULL AND s.hidden=0""").fetchone()[0]
    print("■ 回查：仍含残渣 %d 条（应 = 隐藏的 %d 条，它们的 text 有意不动）"
          % (left, len(hide)))
    print("■ 待翻池子：%s 条" % format(vis, ","))
    return 0


if __name__ == "__main__":
    sys.exit(main())
