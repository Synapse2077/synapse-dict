#!/usr/bin/env python3
"""fr 工具的金标准测试 —— 把 2026-08-01 翻过的车逐条固化成断言。

═══ 为什么有这个文件 ═══
2026-08-01 一天内在**解析与归一化**上翻了八次车，每一次都是先得出一个错误结论、
再基于错误结论做决策。代价举例：
  · espeak 重音率从 62.3% 报到 86.2%（归一化漏了长辅音 Cː、ɪ/ʊ、ɾ/r）
  · 西语版覆盖从 0.0% 报到 61.0%（只认 `/…/` 定界符）
  · pt 巴葡从"补不上"变成"+17.9 万行"（`sounds` 只取了第一个）
  · 葡语版可用音标从 193 词修正到 30,618 词（把 X-SAMPA 标签当成了字符串格式）
**每一个都是一行断言能拦住的。**跑一次不到一秒。

跑：  python3 -m unittest test_tools -v      （在 fr/ 目录下）
"""
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

    def test_法语版反斜杠定界符(self):
        """2026-08-01：只认 /…/ 导致整个法语版被读成空。"""
        self.assertEqual(K.parse_ipa("\\bɔ̃.ʒuʁ\\"), "bɔ̃.ʒuʁ")
        self.assertEqual(K.parse_ipa("\\lˈi.vɾɨ\\"), "lˈi.vɾɨ")


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
