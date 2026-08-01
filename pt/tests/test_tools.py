#!/usr/bin/env python3
"""pt 工具的金标准测试 —— 把 2026-08-01 翻过的车逐条固化成断言。

═══ 为什么有这个文件 ═══
2026-08-01 一天内在**解析与归一化**上翻了八次车，每一次都是先得出一个错误结论、
再基于错误结论做决策。代价举例：
  · espeak 重音率从 62.3% 报到 86.2%（归一化漏了长辅音 Cː、ɪ/ʊ、ɾ/r）
  · 西语版覆盖从 0.0% 报到 61.0%（只认 `/…/` 定界符）
  · pt 巴葡从"补不上"变成"+17.9 万行"（`sounds` 只取了第一个）
  · 葡语版可用音标从 193 词修正到 30,618 词（把 X-SAMPA 标签当成了字符串格式）
**每一个都是一行断言能拦住的。**跑一次不到一秒。

跑：  python3 -m unittest test_tools -v      （在 pt/ 目录下）
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
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

    def test_XSAMPA是标签不是格式(self):
        """2026-08-01：把 X-SAMPA 当字符串格式判断，解析全废，
        把葡语版可用音标从 30,618 词误报成 193 词（158 倍）。

        🔴 用的必须是**真实取自 dump 的 X-SAMPA 值**：它们同样被 `/…/` 包着
        （`/pe."lu.sj@/`、`/kaws/`），所以 `parse_ipa` 一定能把它们抽出来，
        **只有按 tag 排除才拦得住**。本用例第一版用了不带定界符的假值，
        于是"通过"是因为 parse_ipa 恰好返回 None —— 假绿，被变异测试逮出来。
        """
        e = {"sounds": [{"ipa": "/bu.ˈni.tu/", "tags": ["Portugal"]},
                        {"ipa": '/pe."lu.sj@/', "tags": ["Brazil", "X-SAMPA"]},
                        {"ipa": "/kaws/", "tags": ["X-SAMPA"]}]}
        v = K.sounds_variants(e)
        self.assertEqual([ip for ip, _ in v], ["bu.ˈni.tu"])

    def test_地区标签与XSAMPA同时出现时仍须排除(self):
        """`pelúcia` 的真实标签是 ['Brazil', 'X-SAMPA'] ——
        任何"按地区标签取值"的逻辑若不先排除 X-SAMPA，就会把它直接灌进 ipa_br。"""
        e = {"sounds": [{"ipa": '/pe."lu.sj@/', "tags": ["Brazil", "X-SAMPA"]}]}
        self.assertEqual(K.sounds_variants(e), [])

    def test_欧葡与巴葡两个读音都要返回(self):
        """🔴 2026-08-01：只取第一个拿到欧葡，据此断言『巴葡补不上』——错的。
        fr 版葡语条目 ① 欧葡 ② 巴葡（独立音系判据检验 36:1），双列各能补约 17.9 万行。"""
        e = {"sounds": [{"ipa": "\\fɐ.lˈaɾ\\"}, {"ipa": "\\fa.lˈa\\"}]}
        v = [ip for ip, _ in K.sounds_variants(e)]
        self.assertEqual(v, ["fɐ.lˈaɾ", "fa.lˈa"])

    def test_地区标签保留供分列(self):
        e = {"sounds": [{"ipa": "/ˈka.zɐ/", "tags": ["Brazil"]},
                        {"ipa": "/ˈka.zɐ2/", "tags": ["Portugal"]}]}
        tg = [t for _, t in K.sounds_variants(e)]
        self.assertEqual(tg, [("Brazil",), ("Portugal",)])


class 写库闸门(unittest.TestCase):
    def test_追踪的列在库里真实存在(self):
        """schema 漂移守卫：dbtool.TRACK 写错列名会让不变量核对静默失效。"""
        c = sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)
        have = {r[1] for r in c.execute("PRAGMA table_info(%s)" % dbtool.TABLE)}
        c.close()
        self.assertTrue(have, "表 %s 不存在" % dbtool.TABLE)
        self.assertEqual([c2 for c2 in dbtool.TRACK if c2 not in have], [])

    def test_快照含总行数与全部追踪列(self):
        s = dbtool.snapshot()
        self.assertIn("__rows__", s)
        for c in dbtool.TRACK:
            self.assertIn(c, s)
            self.assertLessEqual(s[c], s["__rows__"], "%s 非空数不应超过总行数" % c)

    def test_diff只报变化的键(self):
        self.assertEqual(dbtool.diff({"a": 1, "b": 2}, {"a": 1, "b": 5}), {"b": 3})
        self.assertEqual(dbtool.diff({"a": 1}, {"a": 1}), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
