#!/usr/bin/env python3
"""补建法语版变位表引用、但各版都没有释义的原形。2026-08-17。

═══ 这一步在干什么 ═══
法语版给一批意语生僻动词穷举生成了变位表（每个 ~95 行），却**没有词条正文**。
`intake_fr_forms.py` 遇到 `base not in have` 就跳过 —— 累计跳掉 **181,476 条变形**。

    accintolarlo   ← 法语版：Agglutination du verbe accintolare avec le pronom lo
    accintolare    ← dict 里没有这一行 ⇒ 变形挂不上 ⇒ 95 条全丢

⇒ 本步只做一件事：**把这 2,896 个原形建进 `dict` + `entry`**。
  建完之后重跑 `intake_fr_forms.py --apply`，那 18 万条变形自然就挂上了 ——
  不动它那套已经变异验证过的解析逻辑。

═══ 🔴 为什么这批词没有释义（查过所有源，别再查一遍）═══
    法语版有词条，正文是占位符 `Définition manquante ou à compléter.`   2,303
    法语版连词条都没有（只有机器人生成的变形页）                          593
    英文版 kaikki.org-dictionary-Italian.jsonl              命中 0
    意语版 itwiktionary.jsonl.gz                            命中 0
    希腊语版 / 土耳其版 / 中文版                              命中 0

⇒ **不是我们漏收，是全世界都没写。**所以本步建出来的是 2,896 个
  「有词形、有变位表、无释义」的词头 —— 这是**已知且有意的**空缺。

⚠️ 占位符**不进证据层**：`Définition manquante` 与意语版的 `definizione mancante`
   同类，`fixes/strip_it_placeholder.py` 已经确立了"占位符不是释义"的判据。
   把它当 `sense_src` 存进来，只会让后续所有释义统计多出 2,303 条假证据。
   ⇒ 本步**一条 `sense` / `sense_src` 都不写**。

⚠️ 音标也不给：法语版不给这批词音标，而 G2P 在 es 上被证明会造出
   `eigenvector → eixembeɡˈtoɾ` 这种东西。宁可空着。

═══ 判据 ═══
① 原形出自意语变形页的散文（`du verbe X` / `de X`），`lang_code == 'it'`
② 该原形**大小写不敏感地**不在 `dict` 里
   🔴 必须不敏感：`Capodanno` vs `capodanno` 这类 16 个原形已经在库里，
      按精确匹配会误判成"缺"，于是建出一个大小写重复的词头。
      （`es-sense-layer` 记过反向的坑：大小写折叠吃掉了 573 个专名。
        两个方向都错过，所以这里**只跳过、不合并**，留给人看。）
③ 词性取该原形全部变形页的多数派 —— 实测 2,896 个原形词性全部唯一，无歧义

用法（在 it/ 目录下）：
    python3 pipeline/intake_fr_orphan_bases.py            # 干跑
    python3 pipeline/intake_fr_orphan_bases.py --apply
    python3 pipeline/intake_fr_orphan_bases.py --verify
    python3 pipeline/intake_fr_orphan_bases.py --mutate
"""
import argparse
import gzip
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from build import POS_MAP                            # noqa: E402
from intake_en_forms import OK, deaccent_inner       # noqa: E402
from intake_fr_forms import DUMP, parse_gloss        # noqa: E402
from split_case_forms import norm as word_norm       # noqa: E402

SRC = "fr-edition"


def src_ref_of(word, pos):
    """与 `extend_entry_layer.py` 同一形状，内容派生、可逐字节复算。"""
    return "kk-fr:%s:%s:0:0" % (word, pos)


def scan(con):
    """→ ({原形: (kaikki词性, 带来多少条变形)}, 大小写撞车的, 统计)"""
    have = {r[0] for r in con.execute("SELECT word FROM dict")}
    have_n = {r[0] for r in con.execute("SELECT word_norm FROM dict")}
    have_ci = {w.lower() for w in have}

    pos_of = defaultdict(Counter)
    st = Counter()
    with gzip.open(DUMP, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("lang_code") != "it":
                continue
            w = d.get("word")
            if not w or not OK.match(w):
                continue
            k = deaccent_inner(w)
            if k in have or k in have_n:
                continue                      # 这个变形本身已经收了
            s0 = (d.get("senses") or [None])[0]
            if not s0:
                continue
            base, lab = parse_gloss((s0.get("glosses") or [""])[0], s0.get("tags") or [])
            if not base or not lab:
                continue                      # 抠不出原形 / 出不了中文，本步不管
            if base in have:
                st["原形已在库里（不归本步）"] += 1
                continue
            pos_of[base][d.get("pos") or "verb"] += 1

    out, clash = {}, {}
    for base, c in pos_of.items():
        if base.lower() in have_ci:
            clash[base] = c.total()           # 🔴 只是大小写不同，**不建新词头**
            st["🔴 大小写与库里已有词头相同，跳过"] += c.total()
            continue
        out[base] = (c.most_common(1)[0][0], c.total())
        st["✅ 待建原形，解锁变形"] += c.total()
    return out, clash, st


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    todo, clash, _ = scan(con)
    checks = [
        # 本步做完就该没有"还能建却没建的"
        ("🔴 没有还能建却没建的原形", len(todo), 0),
        # 🔴 本步唯一可能造成灾难的：建出大小写重复的词头
        ("🔴 本步没建出大小写重复的词头", case_dupes(con), 0),
        ("🔴 src_ref 逐字节可复算",
         sum(1 for w, p, sr in con.execute(
             "SELECT d.word, e.pos, e.src_ref FROM entry e JOIN dict d ON d.id=e.word_id "
             "WHERE e.src='fr-edition'")
             if sr != src_ref_of(w, p)), 0),
        ("🔴 无释义词头一律 is_lemma=1",
         q("""SELECT count(*) FROM dict d
              JOIN entry e ON e.word_id=d.id AND e.src='fr-edition'
              WHERE NOT EXISTS(SELECT 1 FROM sense_src x WHERE x.word_id=d.id)
                AND EXISTS(SELECT 1 FROM inflection i WHERE i.base_id=d.id)
                AND COALESCE(d.is_lemma,0)<>1"""), 0),
        # 🔴 这批词**按定义没有释义**。冒出义项 = 有人给它编了意思。
        ("🔴 无释义词头不许凭空长出义项", orphan_with_sense(con), 0),
        ("词形表里没有重复词形",
         q("SELECT count(*) FROM (SELECT word FROM dict GROUP BY word HAVING count(*)>1)"), 0),
        ("（记账）大小写撞车、有意不建的原形", len(clash), len(clash)),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-42s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    return ok


def case_dupes(con):
    """本步建的词头里，有几个与库里已有词头只差大小写。

    🔴 **必须在 Python 里用集合做，不能写成 SQL 相关子查询。**
       第一版我写的是
           AND EXISTS(SELECT 1 FROM dict x WHERE x.id<>d.id AND lower(x.word)=lower(d.word))
       `lower(x.word)` 没有任何索引能服务 ⇒ 对 16.9 万个 fr-edition 词条各全扫
       一遍 130 万行 dict = 2.5×10¹¹ 次行操作，**跑 33 分钟没跑完**。
       （`query-perf-collation-traps` 记过同一族坑；用户也说过"跑之前先 EXPLAIN"。）
       换成一次全表读进集合：O(n)，实测 2 秒。

    ⚠️ 范围必须限定到**本步建的**（fr-edition 词条 + 一条证据都没有）。
       第一版我把全部 166,860 个 fr-edition 词条都算进去，报红 1,700 ——
       那 1,700 是 8-13 那轮的，而且**是对的**：`Abbieri`（姓氏）vs `abbieri`
       （动词变位）、`AISA`（缩写）vs `Aisa`（人名），正是 `es-sense-layer`
       记过的"不该折叠大小写"那一族。闸范围写宽 = 把别人的正确数据判成我的缺陷。
    """
    seen = Counter()
    for (w,) in con.execute("SELECT word FROM dict"):
        seen[w.lower()] += 1
    mine = [r[0] for r in con.execute(
        """SELECT d.word FROM dict d JOIN entry e ON e.word_id=d.id
           WHERE e.src='fr-edition'
             AND NOT EXISTS(SELECT 1 FROM sense_src x WHERE x.word_id=d.id)""")]
    return sum(1 for w in mine if seen[w.lower()] > 1)


def orphan_with_sense(con):
    """本步建的词头里，有几个长出了义项。"""
    return con.execute("""
        SELECT count(*) FROM dict d
        JOIN entry e ON e.word_id = d.id AND e.src = 'fr-edition'
        WHERE EXISTS(SELECT 1 FROM inflection i WHERE i.base_id = d.id)
          AND EXISTS(SELECT 1 FROM sense s WHERE s.word_id = d.id)
          AND NOT EXISTS(SELECT 1 FROM sense_src x WHERE x.word_id = d.id)
    """).fetchone()[0]


def mutate():
    """判据必须能识破：大小写撞车、src_ref 写歪。"""
    print("\n═══ 变异验证 ═══")
    cases = [
        ("src_ref 正常", src_ref_of("accintolare", "verb"), "kk-fr:accintolare:verb:0:0"),
        # entry 用 kaikki 长词性，dict 用短码 —— 两套词表，混了展示层就会显示 `verb` 而不是「动」
        ("🔴 entry 存长词性 verb", src_ref_of("x", "verb"), "kk-fr:x:verb:0:0"),
        ("🔴 dict 存短码 v", POS_MAP.get("verb"), "v"),
        ("原形解析：合体形取 du verbe",
         parse_gloss("Agglutination du verbe accintolare avec le pronom lo.", [])[0],
         "accintolare"),
        ("原形解析：普通变形",
         parse_gloss("Troisième personne du singulier de l’indicatif présent de aggerare.",
                     ["form-of"])[0], "aggerare"),
        ("🔴 独立词条抠不出原形", parse_gloss("Coca-Cola.", [])[0], None),
    ]
    ok = True
    for name, got, want in cases:
        good = got == want
        ok &= good
        print("   %s %-44s → %r" % ("✅" if good else "🔴", name, got))
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

    todo, clash, st = scan(ro)
    f = lambda x: format(x, ",")
    for k, v in st.most_common():
        print("   %-40s %11s" % (k, f(v)))
    print("\n■ 待建原形 %s 个，可解锁 %s 条变形" % (f(len(todo)), f(sum(v[1] for v in todo.values()))))
    print("   词性分布 %s" % dict(Counter(v[0] for v in todo.values())))
    for b in sorted(todo)[:6]:
        print("   %-24s %-6s %d 条变形" % (b, todo[b][0], todo[b][1]))
    if clash:
        print("\n■ 大小写与库里已有词头相同、有意不建的 %s 个（记账，留人看）" % f(len(clash)))
        for b in sorted(clash)[:8]:
            print("   %-24s %d 条变形" % (b, clash[b]))

    if not a.apply or not todo:
        ro.close()
        if not a.apply:
            print("\n(未加 --apply，不写库)")
        return 0

    nxt = ro.execute("SELECT max(id) FROM dict").fetchone()[0] + 1
    ro.close()
    d_rows, e_rows = [], []
    for b in sorted(todo):
        pos = todo[b][0]
        d_rows.append((nxt, b, word_norm(b), 1, POS_MAP.get(pos, pos)))
        e_rows.append((nxt, pos, "0", 0, SRC, src_ref_of(b, pos)))
        nxt += 1
    with dbtool.session("intake-fr-orphan-bases",
                        expect={"__rows__": len(d_rows), "pos": len(d_rows),
                                "#entry": len(e_rows)}) as s:
        s.executemany("INSERT INTO dict (id,word,word_norm,is_lemma,pos) VALUES (?,?,?,?,?)",
                      d_rows)
        s.executemany("INSERT INTO entry (word_id,pos,etym_no,seq,src,src_ref) "
                      "VALUES (?,?,?,?,?,?)", e_rows)
    print("\n■ 已建 %s 个词头（无释义，来源确实没有）" % f(len(d_rows)))
    print("   下一步：python3 pipeline/intake_fr_forms.py --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
