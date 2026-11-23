#!/usr/bin/env python3
"""B35 全库扫描闸：十门 `example.text` 里的 wikitext 模板残渣。2026-11-23。

═══ 为什么要有这道闸 ═══
fr 契约闸的「页面上不许出现模板/脚注残渣」只覆盖**取样词**。2026-11-23 把例句改成
分页展开后它第一次看到全部例句，只报了 2 条；**全库只读扫描是 55 条**（en 12／it 1／
fr 17／pt 3／de 2／ja 1／ko 2／vi 10／ru 7）。按页取样的闸看不见其余 53 条 ——
这正是「闸绿 ≠ 没问题」的老形状。

═══ 判据 ═══
`hidden=0`（读者可见）且 `text` 含 `{{`／`}}`／`[{%`／`}]%` ⇒ 红。
`EXEMPT`（`scripts/fix_example_template_residue.py` 里的 7 条 id）是**正当内容**
（代码示例、数学式、讲模板本身的句子、希腊语注音…），按 id 白名单放行 ——
判据按含义，不按形式。

用法：
    python3 scripts/test_example_template_residue_gate.py
    python3 scripts/test_example_template_residue_gate.py --selftest   # 判据自检
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from fix_example_template_residue import EXEMPT  # noqa: E402

LANGS = ['en', 'es', 'it', 'fr', 'pt', 'de', 'ja', 'ko', 'vi', 'ru']


def _where(expr: str) -> str:
    # ⚠️ 模式串当**参数**传，不当格式串写 —— 否则 `%`／`{` 的转义会互相打架
    #    （第一版写成 `'%%[{%'`，最后那个单 `%` 直接 ValueError）。
    pats = ["%{{%", "%}}%", "%[{%", "%}]%"]
    return " OR ".join("%s LIKE '%s'" % (expr, p) for p in pats)


def residue(conn, lang: str) -> list[tuple[int, str]]:
    """本门**读者可见**的残渣行（id, 文本前 80 字），已剔除 EXEMPT。

    🔴 2026-11-23：查的是**页面实际读的那一列**。
    vi 页面读 `example.text_pub`、ru 读 `COALESCE(text_pub, text)` ——
    这两门的 `text` 是证据层（外锚闸逐字锚 dump，不许改）。
    初版一律查 `text`，把 vi 的 10 条**读者根本看不到**的残渣也算进来，
    还去改了证据层 —— 外锚闸当场红，已回滚（`vi/fixes/rollback_b35_example_text.py`）。
    没有 `text_pub` 的八门，页面读的就是 `text`。
    """
    cols = [r[1] for r in conn.execute('PRAGMA table_info(example)')]
    if not cols:
        return []
    hidden = 'COALESCE(hidden,0)=0' if 'hidden' in cols else '1=1'
    expr = 'COALESCE(text_pub, text)' if 'text_pub' in cols else 'text'
    rows = conn.execute(
        'SELECT id, %s FROM example WHERE %s AND (%s)' % (expr, hidden, _where(expr))
    ).fetchall()
    return [(i, t[:80]) for i, t in rows if (lang, i) not in EXEMPT]


def selftest() -> int:
    """判据自检：残渣报出、豁免放行、隐藏行不计、干净行不报。"""
    c = sqlite3.connect(':memory:')
    c.execute('CREATE TABLE example (id INTEGER PRIMARY KEY, text TEXT, hidden INTEGER)')
    c.executemany('INSERT INTO example VALUES (?,?,?)', [
        (1, '{{ux|en|Kilroy was here.', 0),      # 残渣 ⇒ 报
        (2, 'clean example', 0),                  # 干净 ⇒ 不报
        (3, '{{quote|x}}', 1),                    # 隐藏 ⇒ 不报
    ])
    hit = residue(c, 'en')
    ok = [i for i, _ in hit] == [1]
    # 豁免：把 id=1 塞进 EXEMPT 再看
    EXEMPT.add(('en', 1))
    hit2 = residue(c, 'en')
    EXEMPT.discard(('en', 1))
    ok = ok and hit2 == []
    c.close()
    print(f'   {"✅" if ok else "🔴"} 自检：残渣报出、干净不报、隐藏不计、豁免放行')
    return 0 if ok else 1


def main() -> int:
    if '--selftest' in sys.argv:
        return selftest()
    bad_total = 0
    print('■ B35 全库扫描：十门例句模板残渣（读者可见列、hidden=0）')
    for L in LANGS:
        p = ROOT / 'data' / 'db' / f'synapse-dict-{L}.sqlite'
        if not p.exists():
            print(f'  {L}: 缺库，跳过')
            continue
        c = sqlite3.connect(f'file:{p}?mode=ro', uri=True)
        try:
            hit = residue(c, L)
        finally:
            c.close()
        bad_total += len(hit)
        mark = '✅' if not hit else '🔴'
        print(f'  {mark} {L:2} 残渣 {len(hit)}')
        for i, t in hit[:5]:
            print(f'       {i}: {t!r}')
    print(f'\n{"✅ 全绿" if bad_total == 0 else f"🔴 共 {bad_total} 条可见残渣"}')
    return 0 if bad_total == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
