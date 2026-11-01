#!/usr/bin/env python3
"""写库闸门的「小改动模式」：不复制整库，写之前把要动的行原样存进撤销文件。2026-10-31。

═══ 为什么 ═══
`dbtool.session` 每次写库先 `shutil.copy` 整库（en 5.2 GB），再按预算清旧备份 ——
**几十行的小修也打整库备份，把更早、更有价值的回滚点挤掉**（10-30/31 en 修乱码 41 行挤掉一个 4.8 GB 的，
ja 7 行、ko 5 行各挤掉一个）。用户 2026-10-31：「30 行改动，小备份就行吧？」

═══ 怎么做 ═══
`session(..., small=N)` 才启用（默认行为一字不变）。每条写语句**执行之前**：
  · `UPDATE t SET … WHERE w` ／ `DELETE FROM t WHERE w` ⇒ 用同一个 `WHERE` 先 `SELECT rowid, *`，前像存下
  · `INSERT [OR IGNORE] INTO t (…)` ⇒ 第一次碰 t 时记下 `MAX(rowid)`（撤销＝删掉比它大的行）
撤销：先删新插入的行，再把前像按 rowid 原样写回（`INSERT OR REPLACE`）；
      rowid 大于插入前最大值的前像是本次自己插的行，不写回。
🔴 **看不懂、或撤不干净的一律拒绝**（抛错 ⇒ 事务回滚、库不动），提示去掉 `small=` 用整库备份：
   DDL／`executescript`／`addcolumn`、`INSERT OR REPLACE`／`REPLACE`（会静默删冲突行）、没有 `WHERE` 的 UPDATE/DELETE、
   插入时显式写了 rowid 别名列（新行可能落在旧最大值以下）、`WITHOUT ROWID` 表、前像超过上限 N。

用法：
    python3 scripts/small_undo.py <撤销文件>            # 只核对：文件里的库还在、每张表的插入/前像数
    python3 scripts/small_undo.py <撤销文件> --apply    # 还原（走它自己的事务）
"""
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

_UPD = re.compile(r"^\s*UPDATE\s+(?:OR\s+\w+\s+)?([\"\w]+)\s+SET\s+(.*?)\s+WHERE\s+(.*)$", re.I | re.S)
_DEL = re.compile(r"^\s*DELETE\s+FROM\s+([\"\w]+)\s+WHERE\s+(.*)$", re.I | re.S)
_INS = re.compile(r"^\s*INSERT\s+(OR\s+(\w+)\s+)?INTO\s+([\"\w]+)\s*\(([^)]*)\)", re.I | re.S)


class Refuse(RuntimeError):
    pass


def _q(sql_part):
    """一段 SQL 里有几个 `?`（不数引号里的）。"""
    return len(re.findall(r"\?", re.sub(r"'(?:[^']|'')*'", "''", sql_part)))


class Undo:
    def __init__(self, conn, limit):
        self.conn = conn
        self.limit = int(limit)
        self.maxrow = {}        # 表 → 插入前的 MAX(rowid)
        self.before = {}        # 表 → {rowid: {列: 值}}（每个 rowid 只记第一次）
        self.cols = {}

    def _table(self, t):
        t = t.strip('"')
        if t not in self.cols:
            sql = self.conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
            if not sql:
                raise Refuse("表 `%s` 不存在" % t)
            if re.search(r"WITHOUT\s+ROWID", sql[0], re.I):
                raise Refuse("`%s` 是 WITHOUT ROWID 表，按 rowid 撤销不了" % t)
            info = self.conn.execute('PRAGMA table_info("%s")' % t).fetchall()
            self.cols[t] = ([r[1] for r in info],
                            {r[1] for r in info if r[5] == 1 and (r[2] or "").upper() == "INTEGER"
                             and sum(1 for x in info if x[5]) == 1})
        return t

    def _capture(self, t, where, params):
        n_before = sum(len(v) for v in self.before.values())
        rows = self.conn.execute('SELECT rowid, * FROM "%s" WHERE %s' % (t, where), params).fetchall()
        names = ["rowid"] + self.cols[t][0]
        slot = self.before.setdefault(t, {})
        for r in rows:
            slot.setdefault(r[0], dict(zip(names, r)))
        if n_before + len(rows) > self.limit:
            raise Refuse("前像已超过小改动上限 %d 行" % self.limit)

    def statement(self, sql, params=()):
        params = tuple(params or ())
        m = _UPD.match(sql)
        if m:
            t = self._table(m.group(1))
            setcols = {x.split("=")[0].strip().strip('"') for x in m.group(2).split(",")}
            if setcols & (self.cols[t][1] | {"rowid", "_rowid_", "oid"}):
                raise Refuse("UPDATE 改了 rowid 别名列 —— 撤销时会多留一行")
            return self._capture(t, m.group(3), params[_q(m.group(2)):])
        m = _DEL.match(sql)
        if m:
            t = self._table(m.group(1))
            return self._capture(t, m.group(2), params)
        m = _INS.match(sql)
        if m:
            if (m.group(2) or "").upper() in ("REPLACE",):
                raise Refuse("INSERT OR REPLACE 会静默删掉冲突行，撤不干净")
            t = self._table(m.group(3))
            cols = {c.strip().strip('"') for c in m.group(4).split(",")}
            alias = self.cols[t][1] | {"rowid", "_rowid_", "oid"}
            if cols & alias:
                raise Refuse("插入时显式写了 rowid 别名列 %s —— 新行可能落在旧最大值以下" % sorted(cols & alias))
            if t not in self.maxrow:
                self.maxrow[t] = self.conn.execute('SELECT COALESCE(MAX(rowid), 0) FROM "%s"' % t).fetchone()[0]
            return
        raise Refuse("小改动模式看不懂这条语句（只认带 WHERE 的 UPDATE/DELETE 与带列名的 INSERT）：%s"
                     % " ".join(sql.split())[:120])

    def statements(self, sql, seq):
        for p in seq:
            self.statement(sql, p)

    def rows(self):
        return sum(len(v) for v in self.before.values())

    def save(self, path, db, tag):
        path.write_text(json.dumps({
            "db": str(db), "tag": tag, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "maxrow": self.maxrow,
            "before": {t: list(v.values()) for t, v in self.before.items()},
        }, ensure_ascii=False))
        return path


def restore(conn, undo):
    """→ (删掉的插入行数, 写回的前像行数)。调用方负责事务。"""
    dele = put = 0
    for t, mx in undo["maxrow"].items():
        dele += conn.execute('DELETE FROM "%s" WHERE rowid > ?' % t, (mx,)).rowcount
    for t, rows in undo["before"].items():
        mx = undo["maxrow"].get(t)
        for r in rows:
            if mx is not None and r["rowid"] > mx:
                continue                      # 本次自己插的行，上面已删
            cols = list(r)
            conn.execute('INSERT OR REPLACE INTO "%s" (%s) VALUES (%s)'
                         % (t, ", ".join('"%s"' % c for c in cols), ", ".join("?" * len(cols))),
                         [r[c] for c in cols])
            put += 1
    return dele, put


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    f = Path(sys.argv[1])
    u = json.loads(f.read_text())
    print("■ 撤销文件：%s（%s，tag=%s）" % (f.name, u["time"], u["tag"]))
    print("   库：%s" % u["db"])
    for t, mx in u["maxrow"].items():
        print("   %-20s 删掉 rowid > %d 的新插入行" % (t, mx))
    for t, rows in u["before"].items():
        print("   %-20s 写回前像 %d 行" % (t, len(rows)))
    if "--apply" not in sys.argv:
        print("（只核对。加 --apply 还原）")
        return
    conn = sqlite3.connect(u["db"])
    conn.isolation_level = None
    conn.execute("BEGIN")
    try:
        d, p = restore(conn, u)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    print("■ 已还原：删掉 %d 行新插入、写回 %d 行前像" % (d, p))


if __name__ == "__main__":
    main()
