#!/usr/bin/env python3
"""族J：例句和出处装反了。2026-08-30。

═══ 怎么发现的 ═══
外审说 `godo` 的例句原文重复了两遍。渲染出来一看不是重复，是**字段装反**：

    example.text = "Papéis avulsos"                      ← 这是**书名**
    example.ref  = "Alguns cronistas crêem que Simão…"   ← 这才是例句

而且我们**把书名翻成中文当例句译文上架了**（`散篇`）。

顺着查下去发现日文版/中文版更彻底 —— 它们把**译文**放在 text、把葡语原句放在 ref：

    【em】  text: 12月に          ref: em dezembro
    【eis】 text: 这是你的礼物。   ref: Eis o seu presente.

═══ 判据（按含义，两条都要）═══
① **例句必须包含它的词头或词头的某个变形** —— 不含就不是这个词的例句；
② **而出处里含** —— 这是「内容装在了错的字段」的**正面证据**，不只是"缺了什么"。

🔴 只有 ① 的那一桶（3,532 条）**被抽样打回了**：22 条里大部分是**真例句**，
   只是我的变形表匹配不到 ——
       dar uma força → "Me dê uma força…"   多词表达被变位
       empandorgado  → "empandorgada"        分词的阴性形不在变形表里
       pau no cu de  → "pau no cu do…"       de+o 缩合
       bicho-geográfico → "bicho geográfico" 连字符
   ⇒ **缺席不是证据，在场才是**。只动同时满足①②的 1,200 条。

═══ 三种来源三种处理 ═══
  pt-edition 1,175  text=书名 / ref=例句     → 对调（对调后 ref 就是正常的出处）
  ja/zh/fr      25  text=译文 / ref=例句     → text←ref，ref 置空（译文不是出处）
                                              🔴 zh 版那 6 条的 text **本来就是中文** ⇒
                                                 正好当译文用，白捡 6 条
  en-edition    14  text=**外语原著引文**     → **不对调**（ref 是正常的文献出处，
                                              词头只是碰巧出现在书名里，如 `corvo` /「O Corvo」）
                                              这 14 条是「原文不是葡语」，隐掉

⚠️ 对调后有 7 条会撞 `UNIQUE(word, text)` —— 说明正确的那条**本来就在库里**，
   坏的这条是重复 ⇒ 删掉，不是保留。

⚠️ **1,193 条里约 342 条其实是「一句话被拆到两个字段」**（`reificação`：
   `…como uma mercadoria (` ⊕ `commodity) exemplifica a reificação…`），
   不是装反。两种形状我分不可靠（书名和半句话都会让 ref 以小写开头）。
   但**对调不丢数据** —— pt 版旧 text 原样保留在 ref 里 ⇒ 前半句还在行内，
   随时能恢复（`[[prefer-reversible-designs]]`）。先让读者看到可用的例句，
   拼回整句记账（C31）。

⚠️ 原有的中文译文翻的是**旧 text**（书名/日文），对调后全部作废 ⇒ 删。
   对调后的例句暂时没有中文；库里本来就有 1,827 条（3.6%）可见例句没有中文，
   **保持可见**比隐掉好：读者看到的是一条正确的葡语例句，而不是空白。补中文另记账。

用法（在 pt/ 目录下）：
    python3 fixes/fix_example_field_swap.py
    python3 fixes/fix_example_field_swap.py --apply
"""
import argparse
import collections
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

SWAP_SRC = {"pt-edition", "ja-edition", "zh-edition", "fr-edition"}
# 对调后 ref 该留什么：pt 版原来的 text 是书名（留作出处）；其余版原来的 text 是译文（丢）
KEEP_OLD_TEXT_AS_REF = {"pt-edition"}
HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
# 🔴 zh 版旧 text 是**繁体**（`小貓…打著`）。第一轮才用 OpenCC 修过 466 条，
#    这里直接插进去等于自己打脸自己的闸 ⇒ 走同一条路径转简。
from opencc import OpenCC   # noqa: E402

_CC = OpenCC("t2s")


def fold(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower())
                   if not unicodedata.combining(c))


def contains_word(hay, needle):
    """hay 里有没有 needle 这个**词**（不是子串）。

    🔴 必须按词边界匹配。子串匹配对短词头完全失效 —— `fold` 去掉变音符后
       `ê` → `e`，于是「Orientações de acessibilidade…」里"找得到" `ê`；
       `pa` 在「Pânico」里也"找得到" ⇒ 三条真装反被静默放过（闸红了才发现，
       而闸用的是不带 fold 的 `LOWER()` —— **闸和修复用了两个不同判据**，
       `[[fix-regression-and-gate]]` 那条）。
    """
    if not needle:
        return False
    return re.search(r"(?<![0-9A-Za-z])%s(?![0-9A-Za-z])" % re.escape(fold(needle)),
                     fold(hay)) is not None


def broken(word, text, ref, forms):
    """→ 这条例句是不是「词头在出处里、不在例句里」。**判据只在这里。**"""
    if not ref:
        return False
    cand = [c for c in ({word} | forms.get(word, set())) if c]
    if any(contains_word(text, c) for c in cand):
        return False                # 例句里有词头/变形 ⇒ 正常
    return any(contains_word(ref, c) for c in cand)   # 出处里有 ⇒ 正面证据


def load_forms(con):
    f = collections.defaultdict(set)
    for b, w in con.execute("SELECT i.base, d.word FROM inflection i "
                            "JOIN dict d ON d.id=i.word_id"):
        f[b].add(w)
    return f


def plan(con):
    forms = load_forms(con)
    have = {(w, t) for w, t in con.execute("SELECT word, text FROM example")}
    swap, drop, foreign, taken = [], [], [], set()
    for i, w, t, r, src in con.execute(
            "SELECT id, word, text, ref, src FROM example "
            " WHERE COALESCE(hidden,0)=0 AND ref IS NOT NULL"):
        if not broken(w, t, r, forms):
            continue
        if src not in SWAP_SRC:
            foreign.append((i, w, t, src))             # en 版：原文是外语原著引文，隐掉
        elif (w, r) in have or (w, r) in taken:
            # 对调后重复 ⇒ 坏的这条删掉。
            # ⚠️ `taken` 是**本批已占用**的新键 —— 两条坏行可能对调到同一个 (word,text)，
            #    只查库里已有的会在 executemany 中途炸 UNIQUE（实测炸过一次）。
            drop.append((i, w, r))
        else:
            taken.add((w, r))
            swap.append((i, w, t, r, src))
    return swap, drop, foreign


def main(a):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    swap, drop, foreign = plan(con)
    f = lambda n: format(n, ",")
    print("■ 对调 text↔ref：%s 条  %s"
          % (f(len(swap)), collections.Counter(x[4] for x in swap).most_common()))
    for i, w, t, r, src in swap[:4]:
        print("     %-16s 旧text: %-38s → 新text: %s" % (w[:16], t[:38], r[:38]))
    print("■ 对调后与已有行重复 ⇒ 删坏的那条：%s" % f(len(drop)))
    print("■ en 版「原文是外语原著引文」⇒ 隐掉：%s" % f(len(foreign)))
    for i, w, t, src in foreign[:4]:
        print("     %-16s %s" % (w[:16], t[:52]))

    # 🔴 删例句行**必须连它的译文一起删**，否则留孤儿。
    #    第一版没写，闸报「未声明的表 example_gloss 行数变了」才把它照出来 ——
    #    那条闸问的是别的事，孤儿本身没有任何一道闸在问 ⇒ 已补 F6。
    did = [x[0] for x in drop]
    orphan = [(r[0], r[1]) for r in con.execute(
        "SELECT example_id, lang FROM example_gloss WHERE example_id IN (%s)"
        % ",".join("?" * len(did)), did)] if did else []
    ids = [x[0] for x in swap]
    stale = [r[0] for r in con.execute(
        "SELECT example_id FROM example_gloss WHERE lang='zh' AND example_id IN (%s)"
        % ",".join("?" * len(ids)), ids)] if ids else []
    # zh 版：旧 text 本来就是中文 ⇒ 正好当译文
    reuse = [(i, _CC.convert(t)) for i, _w, t, _r, src in swap
             if src == "zh-edition" and HAN.search(t)]
    print("■ 作废的旧中文译文（翻的是旧 text）⇒ 删：%s" % f(len(stale)))
    print("■ zh 版旧 text 本来就是中文 ⇒ 直接当译文用：%s 条" % f(len(reuse)))
    for i, t in reuse:
        print("     %s" % t[:56])
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    print("■ 被删例句连带的孤儿译文 ⇒ 一起删：%s" % f(len(orphan)))
    with dbtool.session(
            "fix-pt-example-field-swap",
            expect={"#example": -len(drop),
                    "#example_gloss": -(len(stale) + len(orphan)) + len(reuse)}) as s:
        s.executemany("DELETE FROM example WHERE id=?", [(i,) for i, _w, _r in drop])
        s.executemany("DELETE FROM example_gloss WHERE example_id=? AND lang=?", orphan)
        s.executemany("DELETE FROM example_gloss WHERE example_id=? AND lang='zh'",
                      [(i,) for i in stale])
        s.executemany(
            "UPDATE example SET text=?, ref=? WHERE id=?",
            [(r, (t if src in KEEP_OLD_TEXT_AS_REF else None), i)
             for i, _w, t, r, src in swap])
        s.executemany("UPDATE example SET hidden=1 WHERE id=?",
                      [(i,) for i, _w, _t, _s in foreign])
        s.executemany("INSERT INTO example_gloss(example_id, lang, text) VALUES(?,'zh',?)",
                      reuse)
    print("\n✓ 对调 %s ／ 删重复 %s ／ 隐外语 %s ／ 删作废译文 %s ／ zh 版白捡译文 %s"
          % (f(len(swap)), f(len(drop)), f(len(foreign)), f(len(stale)), f(len(reuse))))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    sys.exit(main(ap.parse_args()))
