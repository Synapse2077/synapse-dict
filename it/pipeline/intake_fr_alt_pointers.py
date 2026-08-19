#!/usr/bin/env python3
"""收法语版的异体拼写指针（阶段 3 收尾）。2026-08-17。

═══ 是什么 ═══
`verify_vs_dump.py` 报的 fr 缺词形 **89 个**（收录范围内最后的缺口）。逐条查完，
**没有一个是漏收，全是当初有意跳过的**，但其中一族值得改主意：

    61 个  异体拼写指针，目标词在 dump 的 `alt_of` 里直接给了
              kilonewton → chilonewton    （意语标准前缀是 chilo- 不是 kilo-）
              Irak → Iraq   ioga → yoga   krypton → kripton   Panamá → Panama
    28 个  法语版自己标「缺定义」，且大多是**英语音乐流派名**
              world fusion music / blackened melodic death metal / ragga-pop / electrogaze
     1 个  `’` 一个孤零零的排版撇号（pos = typographic variant）

⇒ 收那 61 个。`intake_fr_words` 当初的规则是「非纯指针的词形」才收，
  但 `recover_alt_of` 早就确立了相反的先例：指针型词条**不收就等于用户划到它
  只能看到空白**（那次救回英文版 7,028 个词形）。`Irak` `krypton` `ioga` 是真会被划到的词。
  后 29 个记账不收（无源可查 + 不是意语词），已写进 `verify_vs_dump.SOURCES` 的接受基线。

═══ 中文标签用模板确定性生成，不调模型 ═══
法语版的措辞只有两种（全量扫过，不是抽样）：

    Variante de X                  → 「X 的异体」
    Variante orthographique de X   → 「X 的异体拼写」

⚠️ 目标词取 dump 的 `alt_of` 字段，**不解析法语散文** —— 散文里 `de` 后面可能跟修饰语。
⚠️ 措辞表与 `recover_alt_of.ZH` 分开：那张表是英文版的 gloss 头（`alternative spelling of`），
   两边语言不同，硬塞进一张表会让键的语言混起来（`dict-labels` 那次的教训）。

用法（在 it/ 目录下）：
    python3 pipeline/intake_fr_alt_pointers.py            # 干跑
    python3 pipeline/intake_fr_alt_pointers.py --apply
    python3 pipeline/intake_fr_alt_pointers.py --verify
    python3 pipeline/intake_fr_alt_pointers.py --mutate
"""
import argparse
import gzip
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from build import POS_MAP                    # noqa: E402
from split_case_forms import norm            # noqa: E402

SRC = "fr-edition"
# 法语版的指针措辞 → 中文模板。全量扫过，只有这两种。
ZH_FR = {"Variante orthographique de": "%s 的异体拼写",
         "Variante de": "%s 的异体"}


def zh_label(gloss, target):
    """→ (中文标签, 用到的措辞) 或 (None, None)。判据与写入共用这一个函数。"""
    for head in sorted(ZH_FR, key=len, reverse=True):    # 长的先匹配
        if (gloss or "").startswith(head):
            return ZH_FR[head] % target, head
    return None, None


def scan(con):
    """→ [(词形, kaikki词性, 目标词, 中文标签, 措辞, 法语原文)]"""
    have = {w.lower() for (w,) in con.execute("SELECT word FROM dict")}
    # 🔴 按**词形**聚合，不是按 dump 行：`iuventino` 在法语版有 adj 和 noun 两条，
    #    第一版每条各建一行 `dict` ⇒ 词形表出现重复（闸报出来的）。
    #    约定是**一个词形一行 dict，词性放 entry**（`docs/SCHEMA.md`）。
    out = {}
    with gzip.open(paths.KK_FR, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            w = d.get("word")
            if not w or w.lower() in have:
                continue
            for s in (d.get("senses") or []):
                g = (s.get("glosses") or [""])[0] or ""
                tgts = [x.get("word") for x in (s.get("alt_of") or s.get("form_of") or [])]
                if not tgts or not tgts[0]:
                    continue
                # 🔴 自指的指针要挡掉：法语版有 kilohenry 的 alt_of 指向 kilohenry 本身，
                #    收进来就是一条「kilohenry 的异体拼写」挂在 kilohenry 上，纯噪声。
                if tgts[0].lower() == w.lower():
                    continue
                lab, head = zh_label(g, tgts[0])
                if lab:
                    out.setdefault(w, []).append((d.get("pos") or "noun", tgts[0], lab, head, g))
                    break
    return out


def src_ref_of(word, pos):
    return "kk-fr:%s:%s:0:0" % (word, pos)


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    left = scan(con)
    checks = [
        ("🔴 没有还能收却没收的异体指针", len(left), 0),
        ("🔴 没有自指的 alt_of（目标 = 自己）",
         q("""SELECT count(*) FROM sense_relation r JOIN dict d ON d.id=r.word_id
              WHERE r.src='%s' AND lower(r.target)=lower(d.word)""" % SRC), 0),
        ("🔴 每条本步义项都有 alt_of 关系",
         q("""SELECT count(*) FROM sense s
              JOIN sense_gloss g ON g.sense_id=s.id AND g.src='%s:alt'
              WHERE NOT EXISTS(SELECT 1 FROM sense_relation r
                               WHERE r.sense_id=s.id AND r.kind='alt_of')""" % SRC), 0),
        # 🔴 指针的目标必须真在库里，否则用户点过去是空的
        ("🔴 每个 alt_of 目标都在库里",
         q("""SELECT count(*) FROM sense_relation r
              WHERE r.src='%s' AND NOT EXISTS(
                SELECT 1 FROM dict d WHERE d.word = r.target)""" % SRC), 0),
        ("🔴 中文标签不许为空",
         q("SELECT count(*) FROM sense_gloss WHERE src='%s:alt' "
           "AND trim(COALESCE(text,''))=''" % SRC), 0),
        ("🔴 本步收的词形一律 is_lemma=1（异体是独立词条，不是变形）",
         q("""SELECT count(*) FROM dict d JOIN sense s ON s.word_id=d.id
              JOIN sense_gloss g ON g.sense_id=s.id AND g.src='%s:alt'
              WHERE COALESCE(d.is_lemma,0)<>1""" % SRC), 0),
        ("词形表里没有重复词形",
         q("SELECT count(*) FROM (SELECT word FROM dict GROUP BY word HAVING count(*)>1)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-46s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    return ok


def mutate():
    print("\n═══ 变异验证：措辞 → 中文 ═══")
    cases = [
        ("异体拼写", zh_label("Variante orthographique de kripton.", "kripton"),
         ("kripton 的异体拼写", "Variante orthographique de")),
        ("异体", zh_label("Variante de faience.", "faience"),
         ("faience 的异体", "Variante de")),
        # 🔴 两个措辞有前缀包含关系，长的必须先匹配
        ("🔴 长措辞优先（否则 orthographique 那条会掉进短的）",
         zh_label("Variante orthographique de X.", "X")[1], "Variante orthographique de"),
        ("🔴 别的措辞不认（变形指针不归本步）",
         zh_label("Pluriel de bomba H.", "bomba H"), (None, None)),
        ("🔴 缺定义占位符不认",
         zh_label("Définition manquante ou à compléter.", "X"), (None, None)),
    ]
    ok = True
    for name, got, want in cases:
        good = got == want
        ok &= good
        print("   %s %-46s → %r" % ("✅" if good else "🔴", name, got))
        if not good:
            print("        期望 %r" % (want,))
    print("\n   变异验证 %s" % ("通过" if ok else "🔴 判据有问题"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("apply", "verify", "mutate"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    rows = scan(ro)
    flat = [(w, pos, t, lab, head, g) for w, vs in rows.items() for pos, t, lab, head, g in vs]
    print("■ 可收的异体指针 %d 个词形 / %d 条义项" % (len(rows), len(flat)))
    print("   措辞分布 %s" % dict(Counter(x[4] for x in flat)))
    have = {w for (w,) in ro.execute("SELECT word FROM dict")}
    orphan = [x for x in flat if x[2] not in have]
    print("   🔴 目标词不在库里的 %d 条%s"
          % (len(orphan), ("（%s）" % ", ".join(x[0] + "→" + x[2] for x in orphan[:5])) if orphan else ""))
    for w, pos, t, lab, head, g in flat[:10]:
        print("   %-24s %-6s → %-18s %s" % (w[:24], pos, t[:18], lab[:26]))
    if not a.apply or not rows:
        ro.close()
        if not a.apply:
            print("\n(未加 --apply，不写库)")
        return 0

    # 目标不在库里的不收（指过去是空的）
    rows = {w: [v for v in vs if v[1] in have] for w, vs in rows.items()}
    rows = {w: vs for w, vs in rows.items() if vs}
    nxt = ro.execute("SELECT max(id) FROM dict").fetchone()[0] + 1
    ro.close()
    d_rows, e_rows, todo = [], [], []
    for w in sorted(rows):
        vs = rows[w]
        # dict.pos 是跨词性的折叠列，多词性用 "/" 连（与 build.py 同约定）
        d_rows.append((nxt, w, norm(w), 1,
                       "/".join(sorted({POS_MAP.get(p, p) for p, *_ in vs}))))
        for pos, t, lab, head, g in vs:
            e_rows.append((nxt, pos, "0", 0, SRC, src_ref_of(w, pos)))
            todo.append((nxt, w, pos, t, lab, g))
        nxt += 1
    with dbtool.session("intake-fr-alt-pointers",
                        expect={"__rows__": len(d_rows), "pos": len(d_rows),
                                "#entry": len(e_rows),
                                "#sense": len(todo), "#sense_src": len(todo),
                                "#sense_gloss": len(todo),
                                "#sense_relation": len(todo)}) as s:
        s.executemany("INSERT INTO dict (id,word,word_norm,is_lemma,pos) VALUES (?,?,?,?,?)",
                      d_rows)
        s.executemany("INSERT INTO entry (word_id,pos,etym_no,seq,src,src_ref) "
                      "VALUES (?,?,?,?,?,?)", e_rows)
        rank = Counter()
        for wid, w, pos, t, lab, g in todo:
            eid = s.execute("SELECT id FROM entry WHERE src_ref=?",
                            (src_ref_of(w, pos),)).fetchone()[0]
            rank[wid] += 1
            cur = s.execute("INSERT INTO sense (word_id,rank,pos,entry_id) VALUES (?,?,?,?)",
                            (wid, rank[wid], POS_MAP.get(pos, pos), eid))
            sid = cur.lastrowid
            s.execute("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?,'zh','equivalent',0,?,?)", (sid, lab, SRC + ":alt"))
            s.execute("INSERT INTO sense_src (word_id,sense_id,src,src_ref,lang,text) "
                      "VALUES (?,?,?,?,'fr',?)",
                      (wid, sid, SRC, "kk-fr:%s:%s#0.0" % (w, pos), g))
            s.execute("INSERT INTO sense_relation (word_id,sense_id,kind,target,src,src_ref) "
                      "VALUES (?,?,'alt_of',?,?,?)",
                      (wid, sid, t, SRC, "kk-fr:%s:%s#alt.0" % (w, pos)))
    print("\n■ 已收 %d 个词形 / %d 条异体指针义项" % (len(d_rows), len(todo)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
