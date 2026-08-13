#!/usr/bin/env python3
"""写库闸门的**变异验证** —— 故意改坏，闸必须报出来。

═══ 为什么要有这个文件 ═══
`IT_PLAN` 阶段 -2 的验收判据不是"跑通就算"，而是「故意改一个未声明的列 → 必须报错」。
理由（es 一个月的教训）：**一条永远通过的检查等于没检查**。
es 上写过一版 7 条的验收，实测其中 2 条是白给的 —— 不管数据对不对都绿，
而整套结果伪装成"全绿"。所以闸写完必须反过来证明它**能红**。

不碰真库：每个用例都在临时目录里现建一个同构的小 `dict` 表，
把 `dbtool.DB` / `paths.BACKUPS` 指过去。真库一个字节都不动。

跑：  python3 tests/verify_gate.py        （在 it/ 目录下）
"""
import sys
import pathlib
import shutil
import sqlite3
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import paths
import dbtool

# 与真库同构（列名一致，够覆盖 TRACK 就行；snapshot 会跳过不存在的列）
SCHEMA = """
CREATE TABLE dict (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  word TEXT NOT NULL, word_norm TEXT NOT NULL, is_lemma INTEGER NOT NULL,
  ipa TEXT, ipa_src TEXT, pos TEXT, gender TEXT, gender_src TEXT,
  definition TEXT, translation TEXT, translation_src TEXT, meta TEXT,
  infl TEXT, level TEXT
);
CREATE TABLE sense (id INTEGER PRIMARY KEY AUTOINCREMENT, word_id INTEGER, rank INTEGER);
CREATE TABLE sense_gloss (sense_id INTEGER, lang TEXT, text TEXT);
INSERT INTO sense (word_id, rank) VALUES (1,1),(1,2),(2,1);
INSERT INTO sense_gloss VALUES (1,'zh','猫'),(2,'zh','猫科动物'),(3,'zh','狗');
"""
ROWS = [("gatto", "gatto", 1, "ˈɡat.to", "kaikki", "noun", "m", None,
         "cat", "猫", None, "{}", None, "A1"),
        ("cane", "cane", 1, "ˈka.ne", "kaikki", "noun", "m", None,
         "dog", "狗", None, "{}", None, "A1"),
        ("fare", "fare", 1, "ˈfa.re", "kaikki", "verb", None, None,
         "to do", "做", None, "{}", None, "A1"),
        ("gatti", "gatti", 0, None, None, "noun", None, None,
         None, "gatto 的 复数", None, None, "{}", None)]

FAILED = []


def fresh(tmp):
    """现建一个干净的临时库，并把 dbtool 指过去。"""
    db = pathlib.Path(tmp) / "synapse-dict-it.sqlite"
    if db.exists():
        db.unlink()
    c = sqlite3.connect(db)
    c.executescript(SCHEMA)
    c.executemany("INSERT INTO dict (word,word_norm,is_lemma,ipa,ipa_src,pos,gender,"
                  "gender_src,definition,translation,translation_src,meta,infl,level)"
                  " VALUES (%s)" % ",".join("?" * 14), ROWS)
    c.commit()
    c.close()
    dbtool.DB = db
    paths.BACKUPS = pathlib.Path(tmp) / "backups"
    paths.BACKUPS.mkdir(exist_ok=True)
    for p in paths.BACKUPS.glob("*.bak"):        # 用例之间互不干扰
        p.unlink()
    return db


def case(name, expect_red, fn):
    """expect_red=True 表示"这次操作必须被闸拦下"。"""
    try:
        fn()
        red = False
    except SystemExit:
        red = True
    except AssertionError as e:                  # 用例自带的断言不通过 = 这条没过
        print("   🔴  %-46s 断言失败：%s" % (name, e))
        FAILED.append(name)
        return
    ok = (red == expect_red)
    print("   %s  %-46s 闸%s（期望%s）"
          % ("✓" if ok else "🔴", name, "报错" if red else "放行",
             "报错" if expect_red else "放行"))
    if not ok:
        FAILED.append(name)


def main():
    tmp = tempfile.mkdtemp(prefix="it-gate-")
    # 🔴 用完必须把全局指回真库：本模块被 test_tools 挂进测试套件跑，
    #    留着指向已删除的临时库，同进程里后面的用例会读到一个不存在的文件。
    真库, 真备份 = dbtool.DB, paths.BACKUPS
    try:
        print("■ 不变量闸门（写库）")

        # ① 合规：声明的列、数量对得上 → 必须放行
        def c1():
            fresh(tmp)
            with dbtool.session("t", expect={"ipa": +1}, verbose=False) as s:
                s.executemany("UPDATE dict SET ipa=? WHERE word=?", [("ˈɡat.ti", "gatti")])
        case("声明 ipa +1，实际 +1", False, c1)

        # ② 🔴 核心判据：改了未声明的列 → 必须报错
        def c2():
            fresh(tmp)
            with dbtool.session("t", expect={"ipa": +1}, verbose=False) as s:
                s.executemany("UPDATE dict SET ipa=?, gender=? WHERE word=?",
                              [("ˈɡat.ti", "m", "gatti")])
        case("声明 ipa，却顺手改了 gender", True, c2)

        # ③ 数量对不上 → 必须报错（"改多了/改少了"）
        def c3():
            fresh(tmp)
            with dbtool.session("t", expect={"ipa": +2}, verbose=False) as s:
                s.executemany("UPDATE dict SET ipa=? WHERE word=?", [("ˈɡat.ti", "gatti")])
        case("声明 ipa +2，实际 +1", True, c3)

        # ④ 🔴 插行不声明增量 → 必须报错
        def c4():
            fresh(tmp)
            with dbtool.session("t", expect={"translation": +1}, verbose=False) as s:
                s.executemany("INSERT INTO dict (word,word_norm,is_lemma,level)"
                              " VALUES (?,?,?,?)", [("cani", "cani", 0, "A2")])
        case("插 1 行但没声明 __rows__", True, c4)

        # ⑤ 插行并正确声明 → 放行（收词阶段要用）
        def c5():
            fresh(tmp)
            with dbtool.session("t", expect={"__rows__": +1, "level": +1},
                                verbose=False) as s:
                s.executemany("INSERT INTO dict (word,word_norm,is_lemma,level)"
                              " VALUES (?,?,?,?)", [("cani", "cani", 0, "A2")])
        case("插 1 行且声明 __rows__ +1", False, c5)

        # ⑥ 插行声明了行数、却漏声明跟着涨的列 → 必须报错
        def c6():
            fresh(tmp)
            with dbtool.session("t", expect={"__rows__": +1}, verbose=False) as s:
                s.executemany("INSERT INTO dict (word,word_norm,is_lemma,level)"
                              " VALUES (?,?,?,?)", [("cani", "cani", 0, "A2")])
        case("插行声明了行数、漏声明 level", True, c6)

        # ⑦ 会话中途异常 → rollback，库必须原封不动
        def c7():
            db = fresh(tmp)
            before = dbtool.snapshot()
            try:
                with dbtool.session("t", expect={"ipa": None}, verbose=False) as s:
                    s.executemany("UPDATE dict SET ipa=? WHERE word=?", [("X", "gatti")])
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
            assert dbtool.snapshot() == before, "异常后没有回滚干净"
        case("会话内抛异常 → 回滚且数据不变", False, c7)

        # ⑧ 阶段 0 会加列：新列从 0 涨到 N，未声明 → 必须报错
        #    （这条专门验 diff 取的是两边键的**并集**；只遍历 before 就看不见新列）
        def c8():
            fresh(tmp)
            with dbtool.session("t", verbose=False) as s:
                s.addcolumn("exchange")
                s.executemany("UPDATE dict SET exchange=? WHERE word=?", [("x", "gatto")])
        case("中途 ALTER 出新列并写值、未声明", True, c8)

        # ⑨ 阶段 0 会删列（30→21）：被删的列只在 before 里有 → 必须报错
        def c9():
            fresh(tmp)
            with dbtool.session("t", verbose=False) as s:
                s.execute("ALTER TABLE dict DROP COLUMN level")
        case("DROP 一个未声明的列", True, c9)

        # ⑩ 删列并正确声明 → 放行
        def c10():
            fresh(tmp)
            n = dbtool.snapshot()["level"]
            with dbtool.session("t", expect={"level": -n}, verbose=False) as s:
                s.execute("ALTER TABLE dict DROP COLUMN level")
        case("DROP 列并声明 -N", False, c10)

        # ── 出版层表（2026-08-12 阶段 0 之后，数据主体已不在 dict 上）──────
        # 🔴 这三条对应 [[fix-regression-and-gate]] 里最狠的那一类事故：
        #    修复写在输出层，而输出层被 DROP 重建 —— 行数和列的非空计数都不变，
        #    只盯着 `dict` 的闸门**永远绿**，用户看到的却是错的。

        def c12():
            fresh(tmp)
            with dbtool.session("t", verbose=False) as s:
                s.executemany("INSERT INTO sense (word_id,rank) VALUES (?,?)", [(3, 1)])
        case("往未声明的 sense 表插行", True, c12)

        def c13():
            fresh(tmp)
            with dbtool.session("t", expect={"#sense": +1}, verbose=False) as s:
                s.executemany("INSERT INTO sense (word_id,rank) VALUES (?,?)", [(3, 1)])
        case("插 sense 并声明 #sense +1", False, c13)

        def c14():
            fresh(tmp)
            with dbtool.session("t", verbose=False) as s:
                s.execute("DROP TABLE sense_gloss")
                s.execute("CREATE TABLE sense_gloss (sense_id INTEGER, lang TEXT, text TEXT)")
        case("DROP 重建 sense_gloss（把内容清空）", True, c14)

        # ⑪ dry 模式不得落任何字节
        def c11():
            db = fresh(tmp)
            sig = (db.stat().st_size, dbtool.snapshot())
            with dbtool.session("t", dry=True, verbose=False) as s:
                pass
            assert (db.stat().st_size, dbtool.snapshot()) == sig, "dry 竟然改了库"
            assert not list(paths.BACKUPS.glob("*.bak")), "dry 竟然写了备份"
        case("dry 模式不写库不备份", False, c11)

        # ── 备份保留策略 ──────────────────────────────────────────────
        print("\n■ 备份保留策略")
        fresh(tmp)
        for p in paths.BACKUPS.glob("*"):
            p.unlink()
        stem = dbtool.DB.stem

        def touch(name, age):
            p = paths.BACKUPS / name
            p.write_bytes(b"x" * 1024)
            import os
            os.utime(p, (time.time() - age, time.time() - age))
            return p

        # 同 tag 同日 3 个 + keep 1 个 + 15 个不同 tag
        a1 = touch("%s.pre-fill-20260812-090000.bak" % stem, 300)
        a2 = touch("%s.pre-fill-20260812-100000.bak" % stem, 200)
        a3 = touch("%s.pre-fill-20260812-110000.bak" % stem, 100)   # 最新，留
        k1 = touch("%s.pre-keep-v2-schema-20260801-090000.bak" % stem, 99999)
        many = [touch("%s.pre-t%02d-20260810-%06d.bak" % (stem, i, 100000 + i), 1000 - i)
                for i in range(15)]
        dbtool.prune_backups(verbose=False)
        left = {p.name for p in paths.BACKUPS.glob("*.bak")}

        def chk(name, cond):
            print("   %s  %s" % ("✓" if cond else "🔴", name))
            if not cond:
                FAILED.append(name)

        chk("同 tag 同日只留最新一个", a3.name in left and a1.name not in left
            and a2.name not in left)
        chk("tag 带 keep 的永不淘汰", k1.name in left)
        chk("非豁免备份上限 %d" % dbtool.MAX_BACKUPS,
            len([n for n in left if "keep" not in n]) == dbtool.MAX_BACKUPS)
        chk("淘汰的是最旧的那几个", many[-1].name in left and many[0].name not in left)

        # dry 只列不删
        n_before = len(list(paths.BACKUPS.glob("*.bak")))
        dbtool.prune_backups(dry=True)
        chk("dry 只列不删", len(list(paths.BACKUPS.glob("*.bak"))) == n_before)
    finally:
        dbtool.DB, paths.BACKUPS = 真库, 真备份
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILED:
        print("🔴 变异验证未通过 %d 条：%s" % (len(FAILED), "、".join(FAILED)))
        return 1
    print("✓ 变异验证全部通过 —— 闸门确实能红")
    return 0


if __name__ == "__main__":
    sys.exit(main())
