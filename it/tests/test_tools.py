#!/usr/bin/env python3
"""it 工具的金标准测试 —— 把 2026-08-01 翻过的车逐条固化成断言。

═══ 为什么有这个文件 ═══
2026-08-01 一天内在**解析与归一化**上翻了八次车，每一次都是先得出一个错误结论、
再基于错误结论做决策。代价举例：
  · espeak 重音率从 62.3% 报到 86.2%（归一化漏了长辅音 Cː、ɪ/ʊ、ɾ/r）
  · 西语版覆盖从 0.0% 报到 61.0%（只认 `/…/` 定界符）
  · pt 巴葡从"补不上"变成"+17.9 万行"（`sounds` 只取了第一个）
  · 葡语版可用音标从 193 词修正到 30,618 词（把 X-SAMPA 标签当成了字符串格式）
**每一个都是一行断言能拦住的。**跑一次不到一秒。

跑：  python3 -m unittest test_tools -v      （在 it/ 目录下）
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))          # 同目录的 verify_gate
import sqlite3
import unittest

import dbtool
import kaikki_util as K


class 解析(unittest.TestCase):
    def test_空值安全(self):
        for x in (None, "", "   ", "没有定界符"):
            self.assertIsNone(K.parse_ipa(x))

    def test_三种定界符都要认(self):
        """it/pt `/…/`、es/de `[…]`、fr `\…\` —— 少认一种就会把整个版本读成空。"""
        self.assertEqual(K.parse_ipa("/abc/"), "abc")
        self.assertEqual(K.parse_ipa("[abc]"), "abc")
        self.assertEqual(K.parse_ipa("\\abc\\"), "abc")

    def test_romanization等非音位式被排除(self):
        e = {"sounds": [{"ipa": "/ok/"}, {"ipa": "/x/", "tags": ["romanization"]},
                        {"ipa": "/y/", "tags": ["rhymes"]}]}
        self.assertEqual([ip for ip, _ in K.sounds_variants(e)], ["ok"])

    def test_sounds是列表而非单值(self):
        """🔴 本项目最贵的一类错误：把 `sounds` 当单值、只取第一个。
        2026-08-01 因此两次断言某个数据源『没用』，两次都是错的。"""
        e = {"sounds": [{"ipa": "/a/"}, {"ipa": "/b/"}, {"ipa": "/c/"}]}
        self.assertEqual([ip for ip, _ in K.sounds_variants(e)], ["a", "b", "c"])
        self.assertEqual(K.first_phonemic(e), "a")

    def test_变体去重但保序(self):
        e = {"sounds": [{"ipa": "/a/"}, {"ipa": "/a/"}, {"ipa": "/b/"}]}
        self.assertEqual([ip for ip, _ in K.sounds_variants(e)], ["a", "b"])

    def test_无sounds时返回空表而不是报错(self):
        self.assertEqual(K.sounds_variants({}), [])
        self.assertIsNone(K.first_phonemic({}))

    def test_录音直链三种格式(self):
        e = {"sounds": [{"audio": "x.ogg", "ogg_url": "http://o"},
                        {"audio": "y.wav", "mp3_url": "http://m", "wav_url": "http://w"},
                        {"ipa": "/z/"}]}
        self.assertEqual([u for u, _, _ in K.audio_urls(e)], ["http://o", "http://m"])

    def test_意语版斜杠(self):
        self.assertEqual(K.parse_ipa("/ˈɡat.to/"), "ˈɡat.to")

    def test_括号可选音是原文不是缺陷(self):
        """/bri.koˈla(d)ʒ/ 的括号是 kaikki 原文，不许在解析层抹掉。"""
        self.assertEqual(K.parse_ipa("/bri.koˈla(d)ʒ/"), "bri.koˈla(d)ʒ")


def _live_cols():
    c = sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)
    have = {r[1] for r in c.execute("PRAGMA table_info(%s)" % dbtool.TABLE)}
    c.close()
    return have


class 写库闸门(unittest.TestCase):
    def test_追踪的列在库里真实存在(self):
        """schema 漂移守卫：dbtool.TRACK 写错列名会让不变量核对静默失效。"""
        have = _live_cols()
        self.assertTrue(have, "表 %s 不存在" % dbtool.TABLE)
        self.assertEqual([c for c in dbtool.TRACK if c not in have], [])

    def test_承载值的列一个都不许漏出TRACK(self):
        """🔴 反向守卫。2026-08-12：旧版 TRACK 只有 6 列，`definition`/`meta`/三个 `_src`
        全在闸外 —— 而阶段 0/1 动的恰恰是 `definition`。漏一列，闸门对它就是瞎的。
        只有身份列（NOT NULL、非空计数恒等于总行数）允许不追踪。"""
        身份列 = {"id", "word", "word_norm", "is_lemma"}
        漏 = sorted(_live_cols() - 身份列 - set(dbtool.TRACK))
        self.assertEqual(漏, [], "这些列没进 TRACK，改坏了不会被发现：%s" % 漏)

    def test_快照含总行数与全部追踪列(self):
        s = dbtool.snapshot()
        self.assertIn("__rows__", s)
        have = _live_cols()
        for c in dbtool.TRACK:
            if c not in have:          # 允许"先写进 TRACK、稍后 ALTER 出来"
                continue
            self.assertIn(c, s)
            self.assertLessEqual(s[c], s["__rows__"], "%s 非空数不应超过总行数" % c)

    def test_diff只报变化的键(self):
        self.assertEqual(dbtool.diff({"a": 1, "b": 2}, {"a": 1, "b": 5}), {"b": 3})
        self.assertEqual(dbtool.diff({"a": 1}, {"a": 1}), {})

    def test_diff取两边键的并集(self):
        """🔴 只遍历 before 的话：中途 ALTER 出的新列（只在 after 里）从 0 涨到 15 万看不见，
        阶段 0 要 DROP 的列（只在 before 里）掉了也看不见。"""
        self.assertEqual(dbtool.diff({}, {"新列": 7}), {"新列": 7})
        self.assertEqual(dbtool.diff({"旧列": 9}, {}), {"旧列": -9})


class 防绕过(unittest.TestCase):
    """新脚本必须走 dbtool；七月那 11 个旧写库脚本必须带防重跑闸。"""

    def test_没有新的绕过闸门的写库路径(self):
        import re
        root = _pl.Path(__file__).resolve().parent.parent
        写库 = re.compile(r"\b(INSERT|UPDATE|DELETE|ALTER TABLE|DROP TABLE|CREATE TABLE)\b")
        坏 = []
        for p in sorted(root.rglob("*.py")):
            if p.name in ("dbtool.py", "legacy_guard.py") or "tests" in p.parts:
                continue
            t = p.read_text(encoding="utf-8", errors="ignore")
            连接 = [l for l in t.splitlines() if "sqlite3.connect" in l and "mode=ro" not in l]
            if not 连接 or not 写库.search(t):
                continue
            if "legacy_guard" in t or "dbtool.session" in t:
                continue
            坏.append(str(p.relative_to(root)))
        self.assertEqual(坏, [], "这些脚本直接写库且既不走 dbtool 也没冻结：%s" % 坏)


class 变异验证(unittest.TestCase):
    def test_闸门确实能红(self):
        """把 verify_gate.py 的 16 条变异用例挂进测试 ——
        「一条永远通过的检查等于没检查」，所以每次跑测试都重新证明闸门能失败。"""
        import io, contextlib
        import verify_gate
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = verify_gate.main()
        self.assertEqual(rc, 0, buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
