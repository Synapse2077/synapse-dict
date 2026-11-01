#!/usr/bin/env python3
"""建表语句对账的判据（B24，2026-10-31）：库里 `sqlite_master.sql` 与建表脚本声明的 DDL 逐表比。九门共用这一份。

═══ 为什么 ═══
`CREATE TABLE IF NOT EXISTS` 对已存在的表是**空操作** ⇒ 改了建表脚本，老库一个字都不会变；
反过来，后来的脚本 `ALTER TABLE … ADD COLUMN`／整表重建换了唯一键，建表脚本也不会跟着变。
原来八门的结构核对只数「对象在不在」「列名在不在」，**对约束/唯一键/类型变了结构性失明**
（ru 2026-10-08 是被一次变异的 `IntegrityError` 撞出来的）。

═══ 判据（从 ru 的 S6 搬来，ru 改为 import 本文件）═══
归一**只做三件事**：去 `--` 注释、去 `IF NOT EXISTS`、压空白（绝不调业务转换器）。
建表语句按**顶层逗号**切成「列定义集合」与「约束集合」分别比 ——
不比整串：`ALTER TABLE` 加的列被 SQLite 插在最后一个列定义之后、约束之前，比整串会假红。
期望的列 ＝ DDL 的列 ∪ 这张表登记在 `ADD_COLUMNS` 里的后补列。
"""
import re

_CONSTRAINT_KW = ("unique", "primary key", "foreign key", "check", "constraint")


def norm_sql(s):
    s = re.sub(r"--[^\n]*", " ", s or "")
    s = re.sub(r"\bIF\s+NOT\s+EXISTS\b", " ", s, flags=re.I)
    s = re.sub(r"\s+", " ", s)
    return s.strip().rstrip(";").lower()


def split_table(sql):
    """建表语句 → (列定义集合, 约束集合)。按顶层逗号切（`NUMERIC(10,2)` 括号里的逗号不切）。"""
    s = norm_sql(sql)
    i = s.index("(")
    body = s[i + 1:s.rindex(")")]
    items, buf, depth = [], [], 0
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            items.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    items.append("".join(buf).strip())
    cols, cons = set(), set()
    for it in items:
        if it:
            (cons if it.startswith(_CONSTRAINT_KW) else cols).add(it)
    return cols, cons


_CREATE = re.compile(r"CREATE\s+TABLE[^;]*?\([\s\S]*?\)\s*(?:WITHOUT\s+ROWID)?\s*(?=;|$)", re.I)
_NAME = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w\"]+)", re.I)


def create_statements(module):
    """建表脚本模块里声明的全部 `CREATE TABLE`（不管装在 DDL／TABLES／元组里）→ {表名: 语句}。
    九门写法不一（de/fr/pt/ko/ja 的 DDL 是字符串列表、ru/vi 是二元组、en 叫 TABLES）⇒ 扫模块里所有大写名字。"""
    out = {}

    def walk(x):
        if isinstance(x, str):
            for q in _CREATE.findall(x):
                out.setdefault(_NAME.match(q).group(1).strip('"'), q)
        elif isinstance(x, (list, tuple)):
            for y in x:
                walk(y)
        elif isinstance(x, dict):
            for y in x.values():
                walk(y)
    for k, v in vars(module).items():
        if k.isupper():
            walk(v)
    return out


def added_columns(module):
    """`ADD_COLUMNS`：[(表, 列, 类型声明)] → {表: {归一后的列定义}}。"""
    out = {}
    for t, c, decl in getattr(module, "ADD_COLUMNS", []):
        out.setdefault(t, set()).add(norm_sql("%s %s" % (c, decl)))
    return out


def drift(live_sql, stmts, added):
    """live_sql：{表: 库里的建表语句}。→ [(表, 说明)]；空＝一致。声明了而库里没有的表也报。"""
    bad = []
    for name, sql in sorted(stmts.items()):
        if name not in live_sql:
            bad.append((name, "声明了而库里没有这张表"))
            continue
        lc, lk = split_table(live_sql[name])
        wc, wk = split_table(sql)
        wc = wc | added.get(name, set())
        if lc == wc and lk == wk:
            continue
        diff = []
        for lab, lv, wv in (("列", lc, wc), ("约束", lk, wk)):
            if lv - wv:
                diff.append("库里多的%s %s" % (lab, sorted(lv - wv)))
            if wv - lv:
                diff.append("声明有而库里没有的%s %s" % (lab, sorted(wv - lv)))
        bad.append((name, "；".join(diff)))
    return bad
