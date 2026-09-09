#!/usr/bin/env python3
"""en 工具的金标准测试 —— 写库闸门本身的行为，逐条固化成断言。

═══ 为什么有这个文件 ═══
闸门自己坏了是**最坏的一类故障**：它不报错，只是不再拦任何东西。
de 阶段 7 实测过两条「恒真断言」（`GLOB '[/[\\]]*'` 里方括号中 `\\` 不是转义符 ⇒ 模式恒假；
判据 import 对了却喂错了对象 ⇒ 恒等）——**一条永远通过的检查等于没检查**。
所以闸门的每一条规则都要有一个「它确实会红」的反例。

en 独有的一道是**冻结表**（`FROZEN_TABLES`），下面那组测试是它的全部依据。

跑：  python3 -m unittest test_tools -v      （在 en/tests/ 目录下）
或：  python3 tests/test_tools.py            （在 en/ 目录下）
"""

import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))   # dbtool/paths 在上一层

import sqlite3
import unittest

import dbtool


class 冻结表(unittest.TestCase):
    """`stardict` / `legacy_dict` 是老库的只读底片（`EN_PLAN` §2.1「一个字节不动」）。

    🔴 判据是**写入目标**，不是"提到了这张表"——
       `INSERT INTO dict SELECT … FROM stardict` 是阶段 0 的正常动作，拦了它就没法迁移。
    """

    def hit(self, sql, allowed=()):
        return dbtool._frozen_hit(sql, set(allowed))

    def test_六种写语句全部拦住(self):
        for sql in (
            "UPDATE stardict SET translation=? WHERE id=?",
            "INSERT INTO stardict (word) VALUES (?)",
            "INSERT OR IGNORE INTO stardict (word) VALUES (?)",
            "REPLACE INTO legacy_dict (word) VALUES (?)",
            "DELETE FROM stardict WHERE id=?",
            "DROP TABLE stardict",
            "DROP TABLE IF EXISTS legacy_dict",
            "ALTER TABLE stardict ADD COLUMN x TEXT",
        ):
            with self.subTest(sql=sql):
                self.assertIsNotNone(self.hit(sql), "没拦住：" + sql)

    def test_大小写与多余空白不影响(self):
        self.assertEqual(self.hit("  update\n\t stardict\n SET a=1"), "stardict")
        self.assertEqual(self.hit('insert into "stardict" (word) values (?)'), "stardict")

    def test_读它不受限(self):
        """🔴 这一组是本文件最重要的 —— 拦错了会让阶段 0 根本做不成。"""
        for sql in (
            "SELECT * FROM stardict WHERE word=?",
            "INSERT INTO dict (word, exam_tag) SELECT word, tag FROM stardict",
            "UPDATE dict SET exam_tag=(SELECT tag FROM stardict s WHERE s.id=dict.id)",
            "CREATE TABLE legacy_dict_idx AS SELECT id FROM stardict",
        ):
            with self.subTest(sql=sql):
                self.assertIsNone(self.hit(sql), "误拦：" + sql)

    def test_unfreeze放行且只放行指定的那张(self):
        sql = "ALTER TABLE stardict RENAME TO legacy_dict"
        self.assertEqual(self.hit(sql), "stardict")
        self.assertIsNone(self.hit(sql, {"stardict"}))
        # 放行 stardict 不等于放行 legacy_dict
        self.assertEqual(self.hit("DELETE FROM legacy_dict", {"stardict"}), "legacy_dict")

    def test_多语句脚本里的任意一条都要逮到(self):
        """`executescript` 会一次送进来一整段建表脚本。"""
        script = ("CREATE TABLE dict (id INTEGER PRIMARY KEY);\n"
                  "INSERT INTO dict SELECT id FROM stardict;\n"
                  "DELETE FROM stardict WHERE id > 100;\n")
        self.assertEqual(self.hit(script), "stardict")

    def test_会话句柄真的会抛(self):
        """判据写对了还不够，得确认它接在写库入口上（de 阶段 7 那条『喂错了对象』）。"""
        conn = sqlite3.connect(":memory:")
        s = dbtool._S(conn)
        with self.assertRaises(RuntimeError):
            s.execute("DELETE FROM stardict")
        with self.assertRaises(RuntimeError):
            s.executemany("UPDATE stardict SET a=?", [(1,)])
        with self.assertRaises(RuntimeError):
            s.executescript("DROP TABLE stardict;")
        conn.close()

    def test_冻结表名与追踪清单一致(self):
        """漂移守卫：冻结的表必须同时被行数快照看着，否则整表被删都没人报。"""
        for t in dbtool.FROZEN_TABLES:
            self.assertIn(t, dbtool.TRACK_TABLES, "%s 冻结了却不在 TRACK_TABLES 里" % t)


class 快照与差分(unittest.TestCase):
    def test_diff只报变化的键(self):
        self.assertEqual(dbtool.diff({"a": 1, "b": 2}, {"a": 1, "b": 5}), {"b": 3})
        self.assertEqual(dbtool.diff({"a": 1}, {"a": 1}), {})

    def test_diff取并集而非只遍历before(self):
        """🔴 会话中途 ALTER 出来的新列只在 after 里有；阶段 0 要删列则只在 before 里有。
        只遍历 before 的话，新列从 0 涨到 15 万看不见。"""
        self.assertEqual(dbtool.diff({}, {"新列": 150000}), {"新列": 150000})
        self.assertEqual(dbtool.diff({"旧列": 42}, {}), {"旧列": -42})

    def test_主干表不存在时快照不炸(self):
        """en 阶段 -2 到阶段 0 之间就处在这个状态：`dict` 还没建。"""
        s = dbtool.snapshot()
        self.assertIn("__rows__", s)
        self.assertIsInstance(s["__rows__"], int)

    def test_冻结表的行数在快照里(self):
        s = dbtool.snapshot()
        live = [t for t in dbtool.FROZEN_TABLES if "#" + t in s]
        self.assertTrue(live, "两张冻结表一张都不在库里 —— 老数据丢了？")

    def test_追踪的列在库里真实存在(self):
        """schema 漂移守卫：`TRACK` 写错列名会让不变量核对**静默失效**。

        ⚠️ `dict` 阶段 0 才建。**建出来的那一刻这条断言自动开始生效** ——
           所以这里是 skip 不是放宽，`TRACK` 里的列名到时候必须对得上。
        """
        c = sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)
        have = {r[1] for r in c.execute("PRAGMA table_info(%s)" % dbtool.TABLE)}
        c.close()
        if not have:
            self.skipTest("主干表 %s 阶段 0 才建（EN_PLAN 阶段表）" % dbtool.TABLE)
        self.assertEqual([x for x in dbtool.TRACK if x not in have], [])

    def test_dict上不许长出音标列和释义列(self):
        """🔴 en 的结构承诺：音标只有 `pronunciation` 一个家、释义只有 `sense` 层一个家。

        de 的 `dict.ipa` 在阶段 8 换读取路径之后读者就看不见了，而闸查原列永远绿
        —— 收尾单 C41。en 是新建，**从结构上不长这个器官**；这条断言是那个承诺的机械形式
        （`[[lesson-must-become-mechanism]]`：写在文件头的守不住）。
        """
        c = sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)
        have = {r[1] for r in c.execute("PRAGMA table_info(%s)" % dbtool.TABLE)}
        c.close()
        if not have:
            self.skipTest("主干表 %s 阶段 0 才建" % dbtool.TABLE)
        self.assertEqual([x for x in dbtool.DICT_FORBIDDEN if x in have], [],
                         "dict 上长出了本该只属于 pronunciation / sense 层的列")

    def test_TRACK与禁列表不重叠(self):
        """判据自洽：不能一边追踪它、一边禁止它存在。"""
        self.assertEqual(sorted(set(dbtool.TRACK) & set(dbtool.DICT_FORBIDDEN)), [])


class 不变量闸变异(unittest.TestCase):
    """🔴🔴 **闸最坏的坏法是「它不报错，只是不再拦任何东西」。**

    上面那些测试验的是判据本身；这一组验的是**判据接在写库入口上、并且真的会红**。
    de 阶段 7 实测过两条恒真断言（`GLOB '[/[\\]]*'` 里方括号中 `\\` 不是转义符 ⇒ 模式恒假；
    判据 import 对了却喂错了对象 ⇒ 恒等）——**一条永远通过的检查等于没检查。**

    在临时库上跑真会话（真备份、真 commit、真核对），不碰生产库。
    """

    def setUp(self):
        import tempfile
        self.d = _pl.Path(tempfile.mkdtemp())
        db = self.d / "synapse-dict-tst.sqlite"
        c = sqlite3.connect(db)
        # ⚠️ 夹具的列必须用**真的 v3 `dict` 列**（`dbtool.TRACK` 里的），不能自己编。
        #    2026-09-07 踩到：夹具原来用 `translation`/`definition`/`frq`，而阶段 0 定稿后
        #    `dict` 上没有前两个、第三个改叫 `freq_rank` ⇒ 闸不再追踪它们，
        #    「改了没声明的列必须红」于是**静默变成永远绿** —— 又一条恒真断言。
        c.executescript("""
            CREATE TABLE dict (id INTEGER PRIMARY KEY, word TEXT,
                               pos TEXT, exam_tag TEXT, freq_rank INTEGER);
            INSERT INTO dict (word, pos, exam_tag, freq_rank)
                 VALUES ('a','n','cet4',1),('b','v','cet6',2),('c','adj','gre',3);
            CREATE TABLE stardict (id INTEGER PRIMARY KEY, word TEXT);
            INSERT INTO stardict (word) VALUES ('x'),('y');
        """)
        c.commit()
        c.close()
        self.old = (dbtool.DB, dbtool.paths.BACKUPS)
        dbtool.DB, dbtool.paths.BACKUPS = db, self.d

    def tearDown(self):
        import shutil
        dbtool.DB, dbtool.paths.BACKUPS = self.old
        shutil.rmtree(self.d, ignore_errors=True)

    def write(self, expect=None, sql=None, args=None, unfreeze=()):
        with dbtool.session("变异", expect=expect, verbose=False, unfreeze=unfreeze) as s:
            s.executemany(sql, args)

    def test_声明了且数对_通过(self):
        """负控：闸不能是「永远红」—— 那和永远绿一样没用。"""
        self.write(expect={"exam_tag": 0},
                   sql="UPDATE dict SET exam_tag=? WHERE id=?", args=[("ky", 1)])

    def test_改了没声明的列_必须红(self):
        """**唯一能自动发现「我以为只动了 A，其实把 B 也改了」的机制。**"""
        with self.assertRaises(SystemExit):
            self.write(sql="UPDATE dict SET exam_tag=? WHERE id=?", args=[("", 1)])

    def test_声明了但数不对_必须红(self):
        with self.assertRaises(SystemExit):
            self.write(expect={"exam_tag": -2},
                       sql="UPDATE dict SET exam_tag=? WHERE id=?", args=[("", 1)])

    def test_偷插一行没声明_必须红(self):
        """总行数默认必须为 0；要插行就得显式写出增量。"""
        with self.assertRaises(SystemExit):
            self.write(sql="INSERT INTO dict (word) VALUES (?)", args=[("d",)])

    def test_动了没声明的表_必须红(self):
        """🔴 阶段 0 之后数据主体不在 `dict` 上 —— 只盯一张表的闸门是瞎的。"""
        with self.assertRaises(SystemExit):
            self.write(unfreeze={"stardict"},
                       sql="INSERT INTO stardict (word) VALUES (?)", args=[("z",)])

    def test_DDL会话抛错后必须真的回滚(self):
        """🔴🔴 **2026-09-07 en 阶段 0 第一次 `--run` 踩到的真 bug。**

        Python 的 sqlite3 传统模式**只为 DML 隐式开事务，DDL 走 autocommit** ⇒
        `conn.rollback()` 撤不掉 `CREATE TABLE` / `ALTER TABLE`。
        当时闸打印了「已 rollback」、还把备份当冗余删了，而 13 张表和一次表改名**全已落库**。
        （de/pt/fr 的同一份代码都有这个洞，只是它们的阶段 0 没抛过错。）

        ⇒ 这条断言钉死两件事：DDL 真的被撤销了 ／ 撤销失败时备份必须留着。
        """
        n0 = len(self._tables())
        with self.assertRaises(sqlite3.OperationalError):
            with dbtool.session("ddl变异", verbose=False) as s:
                s.execute("CREATE TABLE 新表 (id INTEGER PRIMARY KEY)")
                s.execute("ALTER TABLE dict RENAME TO dict2")
                s.execute("这不是合法 SQL")          # 抛错，触发回滚
        self.assertEqual(len(self._tables()), n0, "DDL 没被回滚 —— 表数变了")
        self.assertIn("dict", self._tables(), "dict 被改名了却没回滚")
        self.assertNotIn("新表", self._tables(), "建出来的表没被回滚")

    def test_回滚成功才允许删备份(self):
        """负控：正常的 DML 异常回滚之后，备份确实该删（不能变成永远不删）。"""
        with self.assertRaises(sqlite3.IntegrityError):
            with dbtool.session("dml变异", verbose=False) as s:
                s.executemany("INSERT INTO dict (id, word) VALUES (?,?)", [(1, "撞主键")])
        self.assertEqual(list(self.d.glob("*.bak")), [], "回滚成功，冗余备份该删掉")

    def _tables(self):
        c = sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)
        try:
            return {r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            c.close()


class 保留策略(unittest.TestCase):
    def test_普通备份的floor必须是0(self):
        """🔴 `_thin` 的 `floor` 默认 2 是给里程碑的；普通备份是例行 pre-state，
        预算被里程碑占满时该让干净。de 那轮测试当场逮到过「该砍光却留了 2 个」。"""
        class P:
            def __init__(self, n, size):
                self.n, self._s = n, size

            def stat(self):
                return type("st", (), {"st_size": self._s})()

            def __repr__(self):
                return "P%d" % self.n
        items = [P(i, 100) for i in range(5)]
        when = {p: p.n for p in items}
        live, cut = dbtool._thin(items, when, budget=0, floor=0)
        self.assertEqual(live, [], "普通备份该砍光")
        live2, _ = dbtool._thin(items, when, budget=0, floor=2)
        self.assertEqual(len(live2), 2, "里程碑要保住首尾各一个")
        self.assertEqual([p.n for p in live2], [0, 4], "保住的必须是首和尾")

    def test_预算随完结状态变(self):
        """判据是计划表里那一行，不是手工开关。"""
        self.assertLess(dbtool.DONE_BACKUP_BYTES, dbtool.MAX_BACKUP_BYTES)
        self.assertIsInstance(dbtool._language_is_done(), bool)


if __name__ == "__main__":
    unittest.main(verbosity=2)
