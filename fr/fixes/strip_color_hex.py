#!/usr/bin/env python3
"""收尾单 A3 — 法语定义尾巴上的 `#RRGGBB` 色值残渣。2026-08-27。

═══ 什么东西 ═══
法文版给颜色词条附了色值，wiktextract 把它原样留在定义文本末尾：

    fraise écrasée   D'une couleur rouge profond, rappelant celle du fruit. #A42424
    bleu de France   Bleu roi. #318CE7
    papier bulle     De la couleur du papier bulle (papier jaunâtre grossier) — #EDD38C

读者看到的是定义后面挂着一串十六进制 —— 那不是释义的一部分。

═══ 判据要窄：`#` 在法语里是有内容的 ═══
含 `#` 的法语定义 434 条，其中 **394 条是色值**，另外 **40 条 `#` 是内容本身**：

    hashtag      Signe #, caractère informatique de code ASCII 35…      ← 讲的就是这个符号
    dièse        Le symbole #, dont l'autre nom est croisillon…
    croisillon   Signe #, symbole numéro…
    shebang      En-tête d'un fichier texte représenté par les deux caractères #!…
    Catwoman     Personnage crée par Bill Finger… dans Batman #1 en 1940.  ← 期号
    téléoptile   … → voir téléoptile#fr-nom                              ← 维基锚点

⇒ 判据不是「含 `#`」，是「**`#` 后面跟 3 或 6 位十六进制、且位于文本末尾**」。
   上面这 40 条就是负控（`[[criteria-from-meaning-not-form]]`：
   负控用例 = 上一版判据会误杀的数据）。

⚠️ **只砍尾巴，不动正文。** `Vantablack` 那条是
   `…supérieur à 99% #0000` —— `#0000` 是 4 位，不匹配 3/6 位，**本轮不碰**，
   宁可漏一条也不放宽判据。

═══ 与 `gloss_clean` 的关系 ═══
`pipeline/gloss_clean.py` 是**出版层的清洗判据**，这一族本该长在那儿。
但那个模块的 `clean()` 有一条硬不变量：**只许删、不许改写**，且已被
`reclean_published_fr_defs.py` 全量跑过并留了子序列闸。
本步同样只删（砍掉尾部色值），所以判据放进 `gloss_clean`、由这里调用 ——
**判据只许一份**（`[[fix-regression-and-gate]]`）。

用法（在 fr/ 目录下）：
    python3 -u fixes/strip_color_hex.py            # 只报数
    python3 -u fixes/strip_color_hex.py --apply
    python3 -u fixes/strip_color_hex.py --mutate
"""
import argparse
import random
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import dbtool                                   # noqa: E402
import paths                                    # noqa: E402

f = lambda n: format(n, ",")

# 尾部色值：可选的分隔（空格 / 破折号）+ `#` + 3或6位十六进制，**可连续多个**，直到文本末尾。
# 🔴 `\Z` 而不是 `$` —— `$` 在多行文本里会匹配每一行末尾。
# 🔴 `+` 不能省：闸③（幂等）当场逮到 19 条**一行挂着好几个色值**的 ——
#    `rose vif` 是 `#FF90C0 #EA70A0 #D44E81 #BE2764`、`bleu charron` 是两个。
#    第一版只砍一个 ⇒ 砍完还剩，而"砍不干净"和"没砍"一样是缺陷。
TAIL_HEX = re.compile(
    r"(?:\s*[—–-]?\s*#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3}))+\s*\Z")


def strip_hex(t):
    """判据本体（写入侧与闸共用这一份）。→ 砍掉尾部色值后的文本。

    只砍**末尾**的一处；正文里的 `#` 一个都不碰。
    """
    if not t:
        return t
    out = TAIL_HEX.sub("", t)
    return out.rstrip() if out != t else t


def plan(con):
    """→ [(键, 词, 原文, 新文, hidden)]。

    ⚠️ `sense_gloss` **没有 `id` 列**，主键是 `(sense_id, lang, kind, seq)` ——
       定位必须用这个复合键，不能凭印象写 `g.id`。
    """
    rows = []
    for sid, kind, seq, w, t, hid in con.execute(
            "SELECT g.sense_id, g.kind, g.seq, d.word, g.text, s.hidden FROM sense_gloss g "
            "JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id "
            "WHERE g.lang='fr' AND g.text LIKE '%#%'"):
        n = strip_hex(t)
        if n != t:
            rows.append(((sid, kind, seq), w, t, n, hid))
    return rows


def gates(con, rows):
    print("\n═══ 闸 ═══")
    ok = True

    def g(name, got, want):
        nonlocal ok
        ok &= got == want
        print("   %s %-50s %s（期望 %s）" % ("✅" if got == want else "🔴", name, f(got), f(want)))

    g("① 改后文本必须是改前的**前缀**（只许删尾巴，不许改写）",
      sum(1 for _k, _w, o, n, _h in rows if not o.startswith(n)), 0)
    g("② 不许把整条删空", sum(1 for _k, _w, _o, n, _h in rows if not n.strip()), 0)
    g("③ 改后不许还留着尾部色值（幂等）",
      sum(1 for _k, _w, _o, n, _h in rows if strip_hex(n) != n), 0)
    # 负控：`#` 是内容的那些，一条都不许进来
    keep = [(w, t) for w, t in con.execute(
        "SELECT d.word, g.text FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
        "JOIN dict d ON d.id=s.word_id WHERE g.lang='fr' AND g.text LIKE '%#%'")
        if strip_hex(t) == t]
    print("   ℹ️ 判为「`#` 是内容」不碰的：%s 条" % f(len(keep)))
    for w, t in keep[:5]:
        print("        %-14s %s" % (w, t[:66]))
    return ok


def mutate():
    print("═══ 变异验证：判据本体 ═══")
    cases = [
        ("🔴 尾部 6 位色值", strip_hex("Bleu roi. #318CE7"), "Bleu roi."),
        ("🔴 带破折号分隔", strip_hex("De la couleur du papier — #EDD38C"),
         "De la couleur du papier"),
        ("🔴 小写十六进制", strip_hex("Couleur de ce pigment. #a91101"),
         "Couleur de ce pigment."),
        ("🔴 3 位缩写色值", strip_hex("Rouge vif. #f00"), "Rouge vif."),
        ("🔴 连排多个色值要一次砍干净（闸③逮到的 19 条）",
         strip_hex("Diverses teintes. #FF90C0 #EA70A0 #D44E81 #BE2764"),
         "Diverses teintes."),
        ("🔴 两个色值", strip_hex("Couleur du pigment. #17657D #8EA2C6"),
         "Couleur du pigment."),
        ("负控 hashtag（`#` 就是词义本身）",
         strip_hex("Signe #, caractère informatique de code ASCII 35."),
         "Signe #, caractère informatique de code ASCII 35."),
        ("负控 shebang（`#!`）",
         strip_hex("représenté par les deux caractères #!"),
         "représenté par les deux caractères #!"),
        ("负控 Batman #1（期号，且不在末尾）",
         strip_hex("Personnage crée dans Batman #1 en 1940."),
         "Personnage crée dans Batman #1 en 1940."),
        ("负控 维基锚点 #fr-nom",
         strip_hex("→ voir téléoptile#fr-nom"), "→ voir téléoptile#fr-nom"),
        ("负控 `#0000` 是 4 位，宁可漏也不放宽",
         strip_hex("coefficient supérieur à 99% #0000"),
         "coefficient supérieur à 99% #0000"),
        ("负控 正文中间的色值不碰",
         strip_hex("Le #A42424 est un rouge."), "Le #A42424 est un rouge."),
    ]
    ok = 0
    for name, got, want in cases:
        good = got == want
        ok += good
        print("   %s %-42s → %r" % ("✅" if good else "🔴", name, got[:46]))
    print("\n   变异 %d/%d" % (ok, len(cases)))
    return ok == len(cases)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--read", type=int, default=10)
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = plan(con)
    print("■ 尾部色值残渣 %s 条（可见义项 %s）"
          % (f(len(rows)), f(sum(1 for r in rows if not r[4]))))
    print("\n── 抽读 ──")
    for _k, w, o, n, _h in random.Random(6).sample(rows, min(a.read, len(rows))):
        print("   %-20s %s\n   %-20s %s" % (w, o[:74], "", "→ " + n[:74]))
    ok = gates(con, rows)
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 闸未过，**不写库**")
        return 1
    with dbtool.session("keep-v3-strip-color-hex", expect={}) as s:
        s.executemany("UPDATE sense_gloss SET text=? WHERE sense_id=? AND lang='fr' "
                      "AND kind=? AND seq=?",
                      [(n, k[0], k[1], k[2]) for k, _w, _o, n, _h in rows])
    print("✓ 砍掉 %s 条尾部色值" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
