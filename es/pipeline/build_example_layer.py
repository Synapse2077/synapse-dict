#!/usr/bin/env python3
"""建 `example_gloss`，并把例句从「挂在词上」升级成「挂在义项上」。2026-08-07。

见 `docs/SCHEMA.md` §7.2。这是 v2 三处「目标语言出口」的第三处，也是最后一处
（`sense_gloss` ✅ / `collocation_gloss` ✅ / 本文件）。做完之后
「**加一门语言 = 往这三张表加行，别的地方一个字节不动**」这个验收标准才真正成立。

═══ 两件事 ═══
① **`example_gloss(example_id, lang, text, src)`**
   例句译文从 `example.zh` 那一列搬到独立表 —— 否则加越南语又要加一列。
   ⚠️ 现在 `example.zh` **50,766 条一条中文都没有**，所以这次搬的是空的，
      但结构必须先对，翻译才有地方落。

② **`example.sense_id`**：例句挂到义项上
   `escalera` 的例句「Anna Politkóvskaia 在她公寓的**楼梯**上被击毙」
   明显属于「建筑构件」那条义项，不是「扑克顺子」那条。

   ⭐ **挂载判据是确定性的，不问模型**：`example.src_gloss` 记录该例句在源头
      挂在哪条义项下（覆盖 100.0%），拿它与 `sense_src.text` 精确匹配即可。
      实测 **40,113 条（79.0%）精确命中**。

   匹配不上的 10,634 条多是变形条目（`Forma del plural de gracia.`）——
   那是**指针不是义项**，本来就没有义项可挂，留 NULL 是正确的，不是缺陷。

═══ 三道闸 ═══
① 可逆性回核：每条 `example_gloss` 与 `example.zh` 逐字节比对；
   每条 `sense_id` 反查 `sense_src.text` 必须等于该例句的 `src_gloss`
② 不变量断言：不新增/不丢例句、主键无重、无孤儿
③ 抽样：挂载是确定性匹配，无需判断

用法（在仓库根）：
    python3 -m es.pipeline.build_example_layer
    python3 -m es.pipeline.build_example_layer --apply
"""
import argparse
import collections
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

DDL_GLOSS = """CREATE TABLE IF NOT EXISTS example_gloss (
  example_id INTEGER NOT NULL,
  lang       TEXT NOT NULL,       -- zh / vi …（加语言只往这里加行）
  text       TEXT NOT NULL,
  src        TEXT,
  PRIMARY KEY(example_id, lang)
)"""
IDX = ["CREATE INDEX IF NOT EXISTS idx_exg_lang ON example_gloss(lang)",
       "CREATE INDEX IF NOT EXISTS idx_ex_sense ON example(sense_id)"]


def plan(con):
    """→ (sense_id 挂载计划, 译文搬迁计划, 统计)"""
    # 词 → {sense_src 原文: sense_id}。同一原文可能来自多条证据，取第一条。
    idx = collections.defaultdict(dict)
    for w, txt, sid in con.execute(
            "SELECT d.word, sr.text, sr.sense_id FROM sense_src sr "
            "JOIN dict d ON d.id = sr.word_id"):
        idx[w].setdefault(txt.strip(), sid)

    attach, glosses, stat = [], [], collections.Counter()
    for eid, w, sg, zh, zsrc in con.execute(
            "SELECT id, word, src_gloss, zh, zh_src FROM example"):
        if zh:
            glosses.append((eid, "zh", zh, zsrc or "unknown"))
        sid = idx.get(w, {}).get((sg or "").strip()) if sg else None
        if sid is not None:
            attach.append((sid, eid))
            stat["✅ 挂到义项（src_gloss 精确命中）"] += 1
        elif not sg:
            stat["无 src_gloss，留 NULL"] += 1
        else:
            stat["匹配不上，留 NULL（多为变形条目的指针）"] += 1
    return attach, glosses, stat


def verify(con) -> None:
    """闸① 每条挂载都必须能反查回它的 src_gloss（100%，非抽样）。"""
    print("\n═══ 闸① 可逆性回核（全量，非抽样）═══")
    src = collections.defaultdict(set)
    for sid, txt in con.execute("SELECT sense_id, text FROM sense_src"):
        src[sid].add(txt.strip())
    bad, n, ex = 0, 0, []
    for eid, sg, sid in con.execute(
            "SELECT id, src_gloss, sense_id FROM example WHERE sense_id IS NOT NULL"):
        n += 1
        if (sg or "").strip() not in src.get(sid, ()):
            bad += 1
            if len(ex) < 5:
                ex.append((eid, sg, sorted(src.get(sid, ()))[:1]))
    print(f"  反查 {n:,} 条挂载：src_gloss 与该义项的证据原文对不上的 {bad}")
    for eid, sg, s in ex:
        print(f"    example:{eid}\n      src_gloss={sg!r}\n      义项证据={s}")
    # 🔴 这道闸原本是「`example_gloss` 与 `example.zh` 逐字节一致」。它**过期了**，
    #    而且和它保护的代码犯的是同一个错：建表那天中文确实在 `example.zh` 里，
    #    2026-08-07 `translate_examples.py` 把 50,289 条中文写进 `example_gloss`
    #    之后，`example.zh` 就一直是空的 ⇒ 旧闸会报 50,289 条「不一致」，
    #    或者（在译文被删光时）因为两边**都空**而一路绿灯。
    #    「一条永远通过的检查等于没检查」，这是它的另一副面孔：
    #    **闸的前提跟着数据一起过期，它就从检查变成了背书。**
    # ⇒ 改成核对真正的不变量：每条 example_gloss 必须挂在存在的 example 上，
    #    且 `example.zh` 非空时两者必须一致（迁移完成后 `example.zh` 恒空，该条自然空过）。
    orphan = con.execute(
        "SELECT COUNT(*) FROM example_gloss g "
        "WHERE NOT EXISTS (SELECT 1 FROM example e WHERE e.id = g.example_id)").fetchone()[0]
    zh_bad = con.execute(
        "SELECT COUNT(*) FROM example e JOIN example_gloss g "
        "ON g.example_id = e.id AND g.lang='zh' "
        "WHERE TRIM(COALESCE(e.zh,'')) <> '' AND e.zh <> g.text").fetchone()[0]
    n_g = con.execute("SELECT COUNT(*) FROM example_gloss WHERE lang='zh'").fetchone()[0]
    print(f"  example_gloss 悬空（指向不存在的 example）：{orphan}")
    print(f"  example.zh 非空却与 example_gloss 不一致的：{zh_bad}")
    print(f"  例句中文合计 {n_g:,} 条")
    assert bad == 0 and zh_bad == 0 and orphan == 0
    print("  ✅ 闸① 通过")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    has_col = any(r[1] == "sense_id" for r in con.execute("PRAGMA table_info(example)"))
    attach, glosses, stat = plan(con)
    n_ex = con.execute("SELECT COUNT(*) FROM example").fetchone()[0]
    con.close()

    print(f"例句 {n_ex:,} 条   （`example.sense_id` 列{'已存在' if has_col else '待新建'}）")
    for k, v in stat.most_common():
        print(f"  {k:<34}{v:>7,}  {v/n_ex*100:5.1f}%")
    print(f"\n待挂载 {len(attach):,}   待搬迁译文 {len(glosses):,}"
          f"（`example.zh` 现在是空的，结构先建好）")

    if not args.apply:
        print("\n未加 --apply，不写库。")
        return

    with dbtool.session("build-example-layer", expect={}) as s:
        if not has_col:
            s.execute("ALTER TABLE example ADD COLUMN sense_id INTEGER")
        s.execute(DDL_GLOSS)
        for i in IDX:
            s.execute(i)
        s.execute("UPDATE example SET sense_id = NULL")     # 幂等：先清再挂
        s.executemany("UPDATE example SET sense_id=? WHERE id=?", attach)
        # 🔴 **绝不能无条件 `DELETE FROM example_gloss`**（2026-08-10 血的教训）。
        #    本脚本建表时，中文还在 `example.zh` 这一列里，所以「清空重灌」是安全的。
        #    但 2026-08-07 `translate_examples.py` 把 50,289 条中文写进了
        #    `example_gloss` 之后，`example.zh` 就**一直是空的** ——
        #    再跑一次本脚本 = `glosses` 算出来是空的 + 无条件 DELETE
        #    = **静默删光全部例句中文**。2026-08-10 我就这么删了一次，靠备份还原的。
        #    这是 [[replay-scripts-undo-fixes]] 的第 N 次：重放脚本从一个
        #    **已经不再持有数据的源**重建，UNIQUE / 幂等都保护不了你。
        # ⇒ 只在真有东西可灌时才清；否则原样不动，并把这件事说出来。
        if glosses:
            s.execute("DELETE FROM example_gloss")
            s.executemany("INSERT INTO example_gloss (example_id,lang,text,src) "
                          "VALUES (?,?,?,?)", glosses)
        else:
            kept = s.execute("SELECT COUNT(*) FROM example_gloss").fetchone()[0]
            print(f"\n⚠️ `example.zh` 为空（中文早已搬进 `example_gloss`）⇒ "
                  f"**不清空**，原样保留 {kept:,} 条译文。")

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    q = lambda x: con.execute(x).fetchone()[0]          # noqa: E731
    print("\n落库核对：")
    print(f"  example              {q('SELECT COUNT(*) FROM example'):>8,}"
          f"（应为 {n_ex:,}，一条不增不减）")
    print(f"  挂到义项的           {q('SELECT COUNT(*) FROM example WHERE sense_id IS NOT NULL'):>8,}")
    print(f"  example_gloss        {q('SELECT COUNT(*) FROM example_gloss'):>8,}")
    print(f"  悬空 sense_id        {q('SELECT COUNT(*) FROM example WHERE sense_id IS NOT NULL AND sense_id NOT IN (SELECT id FROM sense)')}")
    assert q("SELECT COUNT(*) FROM example") == n_ex
    verify(con)
    print("\n⭐ 三处目标语言出口now全部就位："
          "sense_gloss / collocation_gloss / example_gloss")
    con.close()


if __name__ == "__main__":
    main()
