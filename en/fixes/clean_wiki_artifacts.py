#!/usr/bin/env python3
"""清掉渲染出来会被读者看见的两族 wikitext 残渣。2026-09-09（阶段 7 外审前）。

═══ 怎么发现的 ═══
外审第一步是**把词条渲染成读者看到的文字**。`cat` 一渲染就露出两样东西：

    近义词 felid feline panther[Panthera pantherine[Pantherinae   ← A 族
    2011, Karl Kruszelnicki, Brain Food, →ISBN, page 53:          ← B 族

⚠️ **第一版我差点报错案**：渲染成 `近义词felidfelinepanther` 时我以为关系项粘连是数据缺陷，
   查库发现 target 是干净的 —— 是我的 `toText()` 去标签时没补空格。**渲染器的假象**。
   补上空格再看，`panther[Panthera` 还在 ⇒ 那才是真的。
   ⇒ **自己的工具先自证清白，再去怀疑数据。**

═══ A 族：`sense_relation.target` 的 wikitext 切分损伤（350 条）═══
判据是**方括号不配对**。配对的 189 条是源头本来就有的内容，**一条不动**：
    polyandry [1680] ／ accidental death and dismemberment [insurance]
    with roots meaning glen[-adorned] hill ／ Colony of Virginia [1606–1775]

不配对的 350 条分两种，**能不能还原决定怎么处理**：
  · `X[Appendix:…`（300 条）→ `Appendix:` 是维基命名空间页，**目标一定是 X** ⇒ 截断
  · 其余 50 条（`fib[re`／`Kln[Kowloon`／`more at [[CXO`／`er] reinforced cement`）
    → **还原不了**：`fib[re` 的真值是 `fibre` 还是 `fiber` 取决于源头怎么写的，
      `[[A|B]]` 谁是目标也拿不准 ⇒ **`hidden=1`**。
    🔴 判据：**知道它坏、但不知道它该是什么 ⇒ 不显示，而不是显示一个猜的**。
      印 `panther[Panthera` 是错，不印是缺；**错比缺更伤权威**。

═══ B 族：`example.ref` 里的 `→ISBN`／`→OCLC` 模板标记（约 25 万处）═══
这些是维基词典模板生成的「此书有 ISBN」标记，对读者是纯噪声。
🔴 **只认「`→` 紧跟已知标识符名」** —— 全库扫过，`→` 后面跟空格的只有 **3 条**，
   而那 3 条是**真内容**（Usenet 标题 `DEC vt320 → linux boxen`、歌名 `Love → Building On Fire`）。
   一刀切删所有 `→` 就会毁掉它们。闸里给这 3 条留了负控。

⚠️ **`[…]` 一律不动**：正文里 75,530 处、`ref` 里 65,981 处，
   那是**合法的省略号**（告诉读者此处有删节），不是残渣。

    cd en && python3 -u fixes/clean_wiki_artifacts.py
    cd en && python3 -u fixes/clean_wiki_artifacts.py --run
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import re
import sqlite3

import dbtool
import paths

# 只认这些标识符名，别的 `→` 一律不碰（见文件头那 3 条真内容）
IDENT = ("OCLC", "ISBN", "ISSN", "DOI", "LCCN", "OL", "JSTOR", "PMID",
         "PMCID", "Bibcode", "Goodreads", "vgmdb")
ARROW = re.compile(r"\s*,?\s*→(?:%s)\b" % "|".join(IDENT))
APPENDIX = re.compile(r"\[Appendix:")


def unbalanced(t):
    return (t or "").count("[") != (t or "").count("]")


def clean_ref(r):
    """去掉标识符标记，并把它留下的标点空洞补平。"""
    s = ARROW.sub("", r or "")
    s = re.sub(r",\s*,", ",", s)          # 删中间项留下的双逗号
    s = re.sub(r"\s{2,}", " ", s)
    s = re.sub(r"[,\s]+([,:])", r"\1", s)  # `, :` → `:`
    return s.strip()


def collect(con):
    """→ (要截断的, 要藏的, 要清出处的)

    🔴🔴 `sense_relation` 上有 `UNIQUE(word_id, sense_id, kind, target)` ——
       截断之后 `abbreviation[Appendix:Glossary` 会与**同一义项下已有的**
       `abbreviation` 撞车，直接 `IntegrityError`（dbtool 回滚干净）。
       ⇒ 撞车的那条是**冗余重复**（干净版已在库里）⇒ 藏，不是截断。
       与 `split_quote_ref.py` 那次同一条判据 —— **改主键成分的列，先想撞车**。
    """
    trunc, hide, refs = [], [], []
    seen = set()
    for k in con.execute("SELECT word_id, sense_id, kind, target FROM sense_relation"):
        seen.add(k)
    for rid, wid, sid, kind, t in con.execute(
            "SELECT id, word_id, sense_id, kind, target FROM sense_relation "
            "WHERE hidden=0 AND (target LIKE '%[%' OR target LIKE '%]%')"):
        if not unbalanced(t):
            continue                      # 配对的是源头内容，不动
        if APPENDIX.search(t):
            new = t.split("[")[0].strip()
            key = (wid, sid, kind, new)
            if new and key not in seen:
                seen.add(key)
                trunc.append((new, rid))
                continue
        hide.append(rid)                  # 还原不了、或截断后与已有的重复 ⇒ 不显示
    for eid, r in con.execute(
            "SELECT id, ref FROM example WHERE hidden=0 AND ref LIKE '%→%'"):
        new = clean_ref(r)
        if new != r:
            refs.append((new, eid))
    return trunc, hide, refs


def gates(con, before, n_tr, n_hi, n_ref):
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    still = [t for (t,) in con.execute(
        "SELECT target FROM sense_relation WHERE hidden=0 "
        "AND (target LIKE '%[%' OR target LIKE '%]%')") if unbalanced(t)]
    checks = [
        ("可见关系里没有断掉的方括号", len(still), 0),
        ("🔴 ref 里没有标识符标记残留",
         q("SELECT COUNT(*) FROM example WHERE hidden=0 AND (%s)"
           % " OR ".join("ref LIKE '%%→%s%%'" % i for i in IDENT)), 0),
        # 🔴 负控①：配对的方括号是源头内容，一条都不许动
        ("🔴 负控 配对的方括号还在",
         len([1 for (t,) in con.execute(
             "SELECT target FROM sense_relation WHERE hidden=0 "
             "AND (target LIKE '%[%' OR target LIKE '%]%')") if not unbalanced(t)]),
         before["balanced"]),
        # 🔴 负控②：`→` 后面跟空格的 3 条真内容（Usenet 标题、歌名）不许被删
        ("🔴 负控 真内容里的箭头还在",
         q("SELECT COUNT(*) FROM example WHERE hidden=0 AND ref LIKE '%→ %'"),
         before["arrow_real"]),
        # 🔴 负控③：`[…]` 是合法省略号，正文与 ref 都不许动
        ("🔴 负控 省略号 […] 没被误删（正文）",
         q("SELECT COUNT(*) FROM example WHERE hidden=0 AND text LIKE '%[…]%'"),
         before["ellipsis_text"]),
        ("🔴 负控 省略号 […] 没被误删（出处）",
         q("SELECT COUNT(*) FROM example WHERE hidden=0 AND ref LIKE '%[…]%'"),
         before["ellipsis_ref"]),
        ("关系总行数没变（截断/藏，不删行）",
         q("SELECT COUNT(*) FROM sense_relation"), before["rel"]),
        ("🔴 负控 cat 的近义词没被清空",
         q("""SELECT COUNT(*) FROM sense_relation r JOIN dict d ON d.id=r.word_id
              WHERE d.word='cat' AND r.kind='synonym' AND r.hidden=0""") > 0, True),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-34s %s / %s" % ("✅" if ok else "🔴", name, got, want))
    return bad


def main(run=False):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = con.execute
    trunc, hide, refs = collect(con)
    before = {
        "rel": q("SELECT COUNT(*) FROM sense_relation").fetchone()[0],
        "balanced": len([1 for (t,) in q(
            "SELECT target FROM sense_relation WHERE hidden=0 "
            "AND (target LIKE '%[%' OR target LIKE '%]%')") if not unbalanced(t)]),
        "arrow_real": q("SELECT COUNT(*) FROM example WHERE hidden=0 "
                        "AND ref LIKE '%→ %'").fetchone()[0],
        "ellipsis_text": q("SELECT COUNT(*) FROM example WHERE hidden=0 "
                           "AND text LIKE '%[…]%'").fetchone()[0],
        "ellipsis_ref": q("SELECT COUNT(*) FROM example WHERE hidden=0 "
                          "AND ref LIKE '%[…]%'").fetchone()[0],
    }
    print("═══ wikitext 残渣清理 ═══")
    print("   A 关系 target 截断（[Appendix: 一族）  %6s" % format(len(trunc), ","))
    print("   A 关系 target 藏起来（还原不了）        %6s" % format(len(hide), ","))
    print("   B 出处去标识符标记                    %6s" % format(len(refs), ","))
    print("   ⚠️ 有意不动：配对的方括号 %s ／ 真内容箭头 %s ／ 省略号 […] 正文 %s"
          % (format(before["balanced"], ","), before["arrow_real"],
             format(before["ellipsis_text"], ",")))
    print("\n   样本：")
    for new, rid in trunc[:3]:
        old, = q("SELECT target FROM sense_relation WHERE id=?", (rid,)).fetchone()
        print("      %r → %r" % (old, new))
    for new, eid in refs[:3]:
        old, = q("SELECT ref FROM example WHERE id=?", (eid,)).fetchone()
        print("      %s\n        → %s" % (old[:78], new[:78]))
    con.close()
    if not run:
        print("\n(干跑。加 --run 才写库)")
        return 0
    with dbtool.session("keep-v3-clean-wiki-artifacts", expect={}) as s:
        s.executemany("UPDATE sense_relation SET target=? WHERE id=?", trunc)
        s.executemany("UPDATE sense_relation SET hidden=1 WHERE id=?",
                      [(i,) for i in hide])
        s.executemany("UPDATE example SET ref=? WHERE id=?", refs)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸② ═══")
    bad = gates(con, before, len(trunc), len(hide), len(refs))
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    _sys.exit(main(run="--run" in _sys.argv))
