#!/usr/bin/env python3
"""量「哪些词会把页面撑爆」：各展示块的分布 + 最狠的三个词。2026-09-14。

产出喂给 `docs/DISPLAY_EXTREMES.md` —— 那份文档是给**界面美化那一轮**看的，
所以数字必须能随时重算，不能是一次性贴进文档就烂掉的快照。

只读，不写库。用法（仓库根）：
    python3 scripts/measure_display_extremes.py
"""
import sqlite3
LANGS=['en','es','it','fr','pt','de']
def q(c,sql):
    try: return [r[0] for r in c.execute(sql)]
    except Exception: return []
def stat(v):
    if not v: return None
    v=sorted(v); n=len(v)
    p=lambda x: v[min(int(n*x), n-1)]
    return (n, p(.5), p(.9), p(.99), v[-1])
def top(c,sql):
    try: return [(r[0], r[1]) for r in c.execute(sql)]
    except Exception: return []

BLOCKS = {
 '义项': ("SELECT COUNT(*) FROM sense GROUP BY word_id",
          "SELECT d.word, COUNT(*) n FROM sense s JOIN dict d ON d.id=s.word_id GROUP BY s.word_id ORDER BY n DESC LIMIT 3"),
 '关系目标': ("SELECT COUNT(*) FROM sense_relation WHERE kind<>'alt_of' GROUP BY word_id",
          "SELECT d.word, COUNT(*) n FROM sense_relation r JOIN dict d ON d.id=r.word_id WHERE r.kind<>'alt_of' GROUP BY r.word_id ORDER BY n DESC LIMIT 3"),
 '单类关系': ("SELECT COUNT(*) FROM sense_relation WHERE kind<>'alt_of' GROUP BY word_id, kind",
          "SELECT d.word||'/'||r.kind, COUNT(*) n FROM sense_relation r JOIN dict d ON d.id=r.word_id WHERE r.kind<>'alt_of' GROUP BY r.word_id, r.kind ORDER BY n DESC LIMIT 3"),
 '词源支': ("SELECT COUNT(DISTINCT edition||':'||etym_no) FROM etymology GROUP BY word_id",
          "SELECT d.word, COUNT(DISTINCT e.edition||':'||e.etym_no) n FROM etymology e JOIN dict d ON d.id=e.word_id GROUP BY e.word_id ORDER BY n DESC LIMIT 3"),
 # ⚠️ `example` 六门都是按 **`word`（文本）** 关联，不是 `word_id` ——
 #    第一版照搬 `word_id` 写法，六门一起报「没有这张表或为空」，
 #    而那看起来跟「这一层还没做」一模一样。列名要回库问，不能照抄隔壁块。
 # ⚠️ es 的 `example` 没有 `hidden` 列（其余五门有）⇒ 用 `pragma` 兜一下，
 #    别让一个列名差异把整门语言报成「空」。
 '例句': ("SELECT COUNT(*) FROM example GROUP BY word",
          "SELECT word, COUNT(*) n FROM example GROUP BY word ORDER BY n DESC LIMIT 3"),
 '搭配': ("SELECT COUNT(*) FROM collocation GROUP BY word_id",
          "SELECT d.word, COUNT(*) n FROM collocation x JOIN dict d ON d.id=x.word_id GROUP BY x.word_id ORDER BY n DESC LIMIT 3"),
 '变形形': ("SELECT COUNT(*) FROM inflection GROUP BY base_id",
          "SELECT d.word, COUNT(*) n FROM inflection i JOIN dict d ON d.id=i.base_id GROUP BY i.base_id ORDER BY n DESC LIMIT 3"),
 '真人录音': ("SELECT COUNT(*) FROM audio GROUP BY word",
          "SELECT word, COUNT(*) n FROM audio GROUP BY word ORDER BY n DESC LIMIT 3"),
 '读音': ("SELECT COUNT(*) FROM pronunciation GROUP BY word_id",
          "SELECT d.word, COUNT(*) n FROM pronunciation p JOIN dict d ON d.id=p.word_id GROUP BY p.word_id ORDER BY n DESC LIMIT 3"),
}
for name,(dist_sql, top_sql) in BLOCKS.items():
    print(f'\n══ {name} ══')
    print(f"{'':4} {'词数':>9} {'中位':>5} {'90%':>5} {'99%':>6} {'最大':>7}   最狠的三个")
    for L in LANGS:
        c=sqlite3.connect(f"file:data/db/synapse-dict-{L}.sqlite?mode=ro",uri=True)
        s=stat(q(c,dist_sql))
        if s:
            t=top(c,top_sql)
            print(f"{L:4} {s[0]:>9,} {s[1]:>5} {s[2]:>5} {s[3]:>6} {s[4]:>7}   " +
                  ' '.join(f'{w}({n})' for w,n in t))
        else:
            print(f"{L:4}        —（没有这张表或为空）")
        c.close()
