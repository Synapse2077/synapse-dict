#!/usr/bin/env python3
"""小改动模式（`scripts/small_undo.py`）的闸：撤销必须把库还原到**逐行一致**；撤不干净的语句必须拒绝。2026-10-31。

全在临时库上做（`tempfile`），一个真库字节都不碰。每个场景：建表灌数 → 取全表指纹 → 记前像并执行 → 撤销 → 指纹必须相等。
另有一条反控：**不撤销**时指纹必须不等（否则「相等」说明不了任何事）。
"""
import hashlib
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from small_undo import Refuse, Undo, restore  # noqa: E402


_TMP = []          # 本次建的临时目录；main() 结束时一律删掉（原来不删，每跑一次留二十多个目录）


def fresh():
    d = tempfile.mkdtemp(prefix="small-undo-")
    _TMP.append(d)
    c = sqlite3.connect(str(Path(d) / "t.sqlite"))
    c.isolation_level = None
    c.executescript("""
        CREATE TABLE tag (sense_id INTEGER NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL,
                          PRIMARY KEY(sense_id, kind, value));
        CREATE TABLE gloss (id INTEGER PRIMARY KEY AUTOINCREMENT, sense_id INTEGER, text TEXT, UNIQUE(sense_id, text));
        CREATE TABLE wr (k TEXT PRIMARY KEY, v TEXT) WITHOUT ROWID;
    """)
    c.executemany("INSERT INTO tag VALUES (?,?,?)", [(i, "region", "East" if i % 3 else "Africa") for i in range(1, 40)])
    c.executemany("INSERT INTO gloss (sense_id, text) VALUES (?,?)", [(i, "释义%d" % i) for i in range(1, 40)])
    return c


def fp(c):
    h = hashlib.sha256()
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        h.update(t.encode())
        for r in sorted(c.execute('SELECT * FROM "%s"' % t).fetchall(), key=repr):
            h.update(repr(r).encode())
    return h.hexdigest()


def run(ops, limit=1000, undo_it=True):
    c = fresh()
    base = fp(c)
    c.execute("BEGIN")
    u = Undo(c, limit)
    for sql, p, many in ops:
        if many:
            u.statements(sql, p)
            c.executemany(sql, p)
        else:
            u.statement(sql, p)
            c.execute(sql, p)
    c.execute("COMMIT")
    changed = fp(c) != base
    if undo_it:
        data = {"maxrow": u.maxrow, "before": {t: list(v.values()) for t, v in u.before.items()}}
        c.execute("BEGIN")
        restore(c, data)
        c.execute("COMMIT")
    return changed, fp(c) == base


CASES = [
    ("UPDATE 带 WHERE", [("UPDATE gloss SET text=? WHERE sense_id=?", ("改了", 5), False)]),
    ("DELETE 带 WHERE（多行）", [("DELETE FROM tag WHERE value=?", ("Africa",), False)]),
    ("INSERT 新行（无 rowid 别名的复合主键表）", [("INSERT INTO tag (sense_id, kind, value) VALUES (?,?,?)",
                                          [(1, "region", "Middle-East"), (2, "register", "Late")], True)]),
    ("INSERT 新行（自增主键表，不写 id）", [("INSERT INTO gloss (sense_id, text) VALUES (?,?)", [(99, "新"), (100, "新2")], True)]),
    ("B1 原样：补 2 行 ＋ 撤 2 行", [
        ("INSERT INTO tag (sense_id, kind, value) VALUES (?,?,?)", [(1, "region", "Middle-East"), (2, "region", "Middle-East")], True),
        ("DELETE FROM tag WHERE sense_id=? AND kind=? AND value=?", [(1, "region", "East"), (2, "region", "East")], True)]),
    ("先插再改同一行（自己插的行不许写回）", [
        ("INSERT INTO gloss (sense_id, text) VALUES (?,?)", (200, "a"), False),
        ("UPDATE gloss SET text=? WHERE sense_id=?", ("b", 200), False)]),
    ("同一行改两次（前像只记第一次）", [
        ("UPDATE gloss SET text=? WHERE sense_id=?", ("x1", 7), False),
        ("UPDATE gloss SET text=? WHERE sense_id=?", ("x2", 7), False)]),
    ("SET 里也有 ? 的 UPDATE（参数切分）", [("UPDATE gloss SET text=?, sense_id=sense_id WHERE sense_id IN (?, ?)", ("y", 8, 9), False)]),
]

REFUSE = [
    ("INSERT OR REPLACE", "INSERT OR REPLACE INTO tag (sense_id, kind, value) VALUES (?,?,?)", (1, "region", "East")),
    ("没有 WHERE 的 UPDATE", "UPDATE gloss SET text=?", ("全改",)),
    ("没有 WHERE 的 DELETE", "DELETE FROM tag", ()),
    ("显式写自增主键", "INSERT INTO gloss (id, sense_id, text) VALUES (?,?,?)", (3, 3, "z")),
    ("UPDATE 改 rowid 别名列", "UPDATE gloss SET id=? WHERE sense_id=?", (999, 1)),
    ("WITHOUT ROWID 表", "INSERT INTO wr (k, v) VALUES (?,?)", ("a", "b")),
    ("DDL", "ALTER TABLE tag ADD COLUMN x TEXT", ()),
]


LANGS = ("en", "es", "it", "fr", "pt", "de", "ja", "ko", "vi", "ru")
ROOT = Path(__file__).resolve().parent.parent
_WIRING = r'''
import sqlite3, sys, tempfile, hashlib
from pathlib import Path
import dbtool
import atexit, shutil
d = Path(tempfile.mkdtemp(prefix="small-undo-wiring-"))
atexit.register(shutil.rmtree, d, True)          # 用完即删（含小库的整库备份）
db = d / ("synapse-dict-%s.sqlite" % sys.argv[1]); bk = d / "backups"; bk.mkdir()
c = sqlite3.connect(db)
c.executescript("CREATE TABLE dict (id INTEGER PRIMARY KEY, word TEXT); CREATE TABLE sense_tag (sense_id INTEGER, kind TEXT, value TEXT, PRIMARY KEY(sense_id, kind, value));")
c.executemany("INSERT INTO sense_tag VALUES (?,?,?)", [(i, "region", "East") for i in range(1, 6)]); c.commit(); c.close()
dbtool.DB = db; dbtool.paths.DB = db; dbtool.paths.BACKUPS = bk
for name in dir(dbtool):                       # 写库后的闸读的是真库，与接线无关 ⇒ 换成空操作
    if name.startswith(("_regression", "_ledger", "_literal", "_gate_debt", "_track_audit", "_announce")):
        setattr(dbtool, name, lambda *a, **k: None)
def fp():
    con = sqlite3.connect(db); h = hashlib.sha256()
    for r in sorted(con.execute("SELECT * FROM sense_tag").fetchall()): h.update(repr(r).encode())
    con.close(); return h.hexdigest()
base = fp()
exp = {"#sense_tag": 1} if "sense_tag" in getattr(dbtool, "TRACK_TABLES", ()) else {}
with dbtool.session("wiring", expect=exp, small=20, verbose=False) as s:
    s.executemany("INSERT INTO sense_tag (sense_id, kind, value) VALUES (?,?,?)", [(1, "region", "Middle-East"), (2, "region", "Middle-East")])
    s.execute("DELETE FROM sense_tag WHERE sense_id=? AND kind=? AND value=?", (1, "region", "East"))
undo = sorted(bk.glob("*.undo-*.json")); full = sorted(bk.glob("*.bak"))
assert len(undo) == 1, "撤销文件 %d 个" % len(undo)
assert not full, "小改动模式却打了整库备份"
assert fp() != base, "写入没有生效"
sys.path.insert(0, sys.argv[2]); import small_undo, json
con = sqlite3.connect(db); con.isolation_level = None; con.execute("BEGIN")
small_undo.restore(con, json.loads(undo[0].read_text())); con.execute("COMMIT"); con.close()
assert fp() == base, "撤销后与写入前不一致"
try:
    with dbtool.session("wiring-ddl", small=20, verbose=False) as s:
        s.execute("ALTER TABLE sense_tag ADD COLUMN x TEXT")
    raise SystemExit("小改动模式没拒绝 DDL")
except small_undo.Refuse:
    pass
except dbtool.Refuse:
    pass
assert fp() == base and "x" not in [r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(sense_tag)")], "拒绝之后库变了"
import types                                   # B14②：写完要调展示层台账的 notice()（换成计数器，不碰真台账）
_called = []
sys.modules["display_stamp"] = types.SimpleNamespace(notice=lambda: _called.append(1))
with dbtool.session("wiring-full", expect=exp, verbose=True) as s:
    s.execute("INSERT INTO sense_tag (sense_id, kind, value) VALUES (?,?,?)", (9, "region", "x"))
assert sorted(bk.glob("*.bak")), "不带 small 时没有打整库备份（默认行为变了）"
assert len(_called) == 1, "写完没有报展示层台账（display_stamp.notice 调了 %d 次）" % len(_called)
import intake_layers as IL                       # B3：收词闸 rerun= ——拒／记账／销账（欠账文件指到临时目录）
IL.PENDING = d / "intake-pending.json"
lang = sys.argv[1]
lay = next(x for x in IL.LAYERS[lang] if x["tags"])
try:
    with dbtool.session("wiring-intake", expect={"__rows__": 1}, small=20, verbose=False) as s:
        s.execute("INSERT INTO dict (word) VALUES ('neu')")
    raise SystemExit("插新词形没声明 rerun 却放行了")
except SystemExit as e:
    if "却放行了" in str(e):
        raise
assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM dict WHERE word='neu'").fetchone()[0] == 0, "被拒之后库里还是多了词形"
with dbtool.session("wiring-intake", expect={"__rows__": 1}, small=20, verbose=False, rerun=[lay["layer"]]) as s:
    s.execute("INSERT INTO dict (word) VALUES ('neu')")
assert lay["layer"] in json.loads(IL.PENDING.read_text())[lang], "声明了 rerun 却没记欠账"
with dbtool.session(lay["tags"][0] + "wiring", expect=exp, small=20, verbose=False) as s:
    s.execute("INSERT INTO sense_tag (sense_id, kind, value) VALUES (?,?,?)", (50, "region", "z"))
assert lang not in json.loads(IL.PENDING.read_text()), "重跑那一层的写库没有销账"
print("OK")
'''


def wiring(lang):
    import subprocess
    r = subprocess.run([sys.executable, "-B", "-c", _WIRING, lang, str(ROOT / "scripts")],
                       cwd=ROOT / lang, capture_output=True, text=True)
    out = r.stdout.strip().splitlines()           # 只看 stdout：DDL 被拒时闸门往 stderr 打的提示是预期内的
    if r.returncode == 0 and out and out[-1] == "OK":
        return True, "写→撤销文件（无整库备份）→还原逐行一致；DDL 被拒；不带 small 照旧整库备份；写完报展示层台账；收词闸拒／记账／销账"
    err = r.stderr.strip().splitlines()
    return False, ((err or out or ["无输出"])[-1])[:200]


def main():
    bad = 0
    print("■ 撤销后逐行一致（全表指纹）")
    for name, ops in CASES:
        try:
            changed, same = run(ops)
        except Exception as e:            # 实现坏了常常是抛错而不是指纹不等 —— 记成这一条红，别让整个闸崩掉
            bad += 1
            print("   🔴 %s（抛错：%s: %s）" % (name, type(e).__name__, e))
            continue
        ok = changed and same
        bad += not ok
        print("   %s %s%s" % ("✅" if ok else "🔴", name, "" if changed else "（🔴 这个场景没改动任何东西，验不到）"))
    changed, same = run(CASES[4][1], undo_it=False)
    ok = changed and not same
    bad += not ok
    print("   %s 反控：不撤销则指纹不等" % ("✅" if ok else "🔴"))
    print("■ 撤不干净的必须拒绝")
    for name, sql, p in REFUSE:
        c = fresh()
        try:
            Undo(c, 1000).statement(sql, p)
            ok = False
        except Refuse:
            ok = True
        bad += not ok
        print("   %s %s" % ("✅" if ok else "🔴 没拒绝：", name))
    c = fresh()
    try:
        Undo(c, 5).statement("DELETE FROM tag WHERE sense_id < ?", (20,))
        ok = False
    except Refuse:
        ok = True
    bad += not ok
    print("   %s 前像超过上限（5 行上限，删 19 行）" % ("✅" if ok else "🔴 没拒绝："))
    n = len(CASES) + 1 + len(REFUSE) + 1
    print("■ 十门的写库闸门真的接上了（临时库，真库不碰）")
    for lang in LANGS:
        ok, msg = wiring(lang)
        n += 1
        bad += not ok
        print("   %s %s %s" % ("✅" if ok else "🔴", lang, msg))
    print("\n%s 小改动模式 %d/%d" % ("🔴" if bad else "✅", n - bad, n))
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    import shutil
    try:
        main()
    finally:
        for _d in _TMP:
            shutil.rmtree(_d, ignore_errors=True)
