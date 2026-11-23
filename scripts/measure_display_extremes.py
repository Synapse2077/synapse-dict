#!/usr/bin/env python3
"""量「哪些词会把页面撑爆」：各展示块的分布 + 最狠的三个词。2026-09-14。

产出喂给 `docs/DISPLAY_EXTREMES.md` —— 那份文档是给**界面美化那一轮**看的，
所以数字必须能随时重算，不能是一次性贴进文档就烂掉的快照。

只读，不写库。用法（仓库根）：
    python3 scripts/measure_display_extremes.py
"""
import sqlite3
LANGS=['en','es','it','fr','pt','de','ja','ko','vi','ru']
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
 # 🔴 2026-11-23：`base_id IS NULL` 的 960 行会被当成一组（en 实测），
 #    于是「最大」报 960，而 top 的 join 一滤就只剩 be(38) —— 分布与最狠的例子自相矛盾。
 '变形形': ("SELECT COUNT(*) FROM inflection WHERE base_id IS NOT NULL GROUP BY base_id",
          "SELECT d.word, COUNT(*) n FROM inflection i JOIN dict d ON d.id=i.base_id GROUP BY i.base_id ORDER BY n DESC LIMIT 3"),
 '真人录音': ("SELECT COUNT(*) FROM audio GROUP BY word",
          "SELECT word, COUNT(*) n FROM audio GROUP BY word ORDER BY n DESC LIMIT 3"),
 '读音': ("SELECT COUNT(*) FROM pronunciation GROUP BY word_id",
          "SELECT d.word, COUNT(*) n FROM pronunciation p JOIN dict d ON d.id=p.word_id GROUP BY p.word_id ORDER BY n DESC LIMIT 3"),
}
def adapt(c, B):
    """按本门真实的列改三条 SQL。2026-11-23 扩十门时补。

    🔴 写死六门形状会让 vi/ru **静默跳过整块**，而输出与「这门很干净」一模一样。
       `example`/`audio`：六门按 `word` 文本，vi/ru 按 `word_id`；
       `inflection`：六门按 `base_id`，ru 按 `entry_id`，vi 没有表。
    改不了就把这一块从字典里删掉，让调用方打印「没有这张表」，不冒充 0。
    """
    B=dict(B)
    def has(t,col):
        try: return col in [r[1] for r in c.execute(f'PRAGMA table_info({t})')]
        except Exception: return False
    if has('example','word_id'):
        B['例句']=("SELECT COUNT(*) FROM example GROUP BY word_id",
                  "SELECT d.word, COUNT(*) n FROM example e JOIN dict d ON d.id=e.word_id "
                  "GROUP BY e.word_id ORDER BY n DESC LIMIT 3")
    elif not has('example','word'):
        B.pop('例句', None)
    if has('inflection','base_id'):
        pass
    elif has('inflection','entry_id'):
        # 页面是按**词条**合并变形（一个词形可能有多个 entry）⇒ 分布与 top 都按 word_id 分组，
        # 不能一个按 entry_id、一个按 word_id（第一版就是这么写的：分布最大 104、top 却是 262）。
        B['变形形']=("SELECT COUNT(*) FROM inflection i JOIN entry en ON en.id=i.entry_id GROUP BY en.word_id",
                    "SELECT d.word, COUNT(*) n FROM inflection i JOIN entry en ON en.id=i.entry_id "
                    "JOIN dict d ON d.id=en.word_id GROUP BY en.word_id ORDER BY n DESC LIMIT 3")
    else:
        B.pop('变形形', None)
    # 词源：`edition` 只有六门有；vi/ru 只有 `etym_no`（第一版直接判成「没有这张表」——假象）。
    if not has('etymology','edition'):
        if has('etymology','etym_no'):
            B['词源支']=("SELECT COUNT(DISTINCT etym_no) FROM etymology GROUP BY word_id",
                        "SELECT d.word, COUNT(DISTINCT e.etym_no) n FROM etymology e JOIN dict d ON d.id=e.word_id "
                        "GROUP BY e.word_id ORDER BY n DESC LIMIT 3")
        else:
            B['词源支']=("SELECT COUNT(*) FROM etymology GROUP BY word_id",
                        "SELECT d.word, COUNT(*) n FROM etymology e JOIN dict d ON d.id=e.word_id "
                        "GROUP BY e.word_id ORDER BY n DESC LIMIT 3")
    if has('audio','word_id'):
        B['真人录音']=("SELECT COUNT(*) FROM audio GROUP BY word_id",
                     "SELECT d.word, COUNT(*) n FROM audio a JOIN dict d ON d.id=a.word_id "
                     "GROUP BY a.word_id ORDER BY n DESC LIMIT 3")
    elif not has('audio','word'):
        B.pop('真人录音', None)
    return B


for name in BLOCKS:
    print(f'\n══ {name} ══')
    print(f"{'':4} {'词数':>9} {'中位':>5} {'90%':>5} {'99%':>6} {'最大':>7}   最狠的三个")
    for L in LANGS:
        c=sqlite3.connect(f"file:data/db/synapse-dict-{L}.sqlite?mode=ro",uri=True)
        B=adapt(c, BLOCKS)
        if name not in B:
            print(f"{L:4}        —（没有这张表）")
            c.close(); continue
        dist_sql, top_sql = B[name]
        s=stat(q(c,dist_sql))
        if s:
            t=top(c,top_sql)
            print(f"{L:4} {s[0]:>9,} {s[1]:>5} {s[2]:>5} {s[3]:>6} {s[4]:>7}   " +
                  ' '.join(f'{w}({n})' for w,n in t))
        else:
            print(f"{L:4}        —（没有这张表或为空）")
        c.close()
