#!/usr/bin/env python3
"""en 归一化的金标准测试。跑：`cd en && python3 -m unittest tests.test_ipa_norm`

⭐ 本文件一半的用例是在保护**不该动的东西**。
   en 与其他五个语种不同：它没有第二权威源可回核（维基体系只能补 0.8%），
   所以唯一的防线就是"归一后源头的陈述能否复原"这条判据，以及把它固化成断言。
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块在上一层

import unittest

import ipa_norm as N


class 记法噪声要归一(unittest.TestCase):
    def test_空值安全(self):
        for x in (None, ""):
            self.assertEqual(N.normalize(x), x)

    def test_连结弧(self):
        self.assertEqual(N.normalize("d͡ʒʌd͡ʒ"), "dʒʌdʒ")

    def test_音节点(self):
        self.assertEqual(N.normalize("əˈbleɪ.ʃən"), "əˈbleɪʃən")

    def test_非成音节符(self):
        """`eɪ̯` 与 `eɪ` 是同一个双元音，̯ 是冗余标注。"""
        self.assertEqual(N.normalize("ˈneɪ̯.tʃə"), "ˈneɪtʃə")

    def test_送气符(self):
        """英语清塞音词首必送气，写不写都一样。"""
        self.assertEqual(N.normalize("ˈkʰæti"), "ˈkæti")

    def test_暗l归一(self):
        """暗 l 只出现在 coda，位置完全可推。"""
        self.assertEqual(N.normalize("ˈkæt(ə)ɫ"), "ˈkæt(ə)l")

    def test_ASCII_g换成IPA_ɡ(self):
        self.assertEqual(N.normalize("gəʊ"), "ɡəʊ")

    def test_ɹ统一到r(self):
        """🔴 本轮最大的一块：英语 /r/ 只有一个音位，库里两种写法混用
        （uk 27,007 行用 ɹ vs 11,433 行用 r；67 行同一条里两种都有）。

        **方向是 ɹ→r**：`ɹ` 是严式记音符号、`r` 是音位写法，而本词典处处选音位式弃严式；
        且剑桥/牛津/朗文学习词典与中国教材的英语 /r/ 全部写 `r`。
        我最初定成反方向（r→ɹ），理由是"ɹ 是现代标准" —— 那是在优化语音学精确性，
        不是划词弹窗的目标。"""
        self.assertEqual(N.normalize("ˈbɹeɪkˌfɑːst"), "ˈbreɪkˌfɑːst")
        self.assertEqual(N.normalize("ˈæb.əˌtwɑː(ɹ)"), "ˈæbəˌtwɑː(r)")
        self.assertNotIn("ɹ", N.normalize("bakˈtɪə̯.ɹi.ə"))

    def test_r色化元音不受影响(self):
        """`ɚ`(butter) / `ɝ`(bird) 是**元音**不是辅音，学习词典照样使用，不动。"""
        self.assertEqual(N.normalize("ˈbʌtɚ"), "ˈbʌtɚ")
        self.assertEqual(N.normalize("bɝd"), "bɝd")


class 真信息一个字节都不许动(unittest.TestCase):
    """判据：归一之后，源头原本的陈述还能不能复原？不能就别动。"""

    def test_可选音段保留(self):
        """源头说的是「可选」。改成有或没有，都是我们替它下的结论；
        而且正确呈现取决于在看哪一列（英式非儿化 vs 美式儿化）—— 那是展示逻辑。"""
        for s in ("əˈbæn.d(ə)n.m(ə)nt", "ˈfɑː.ðə(ɹ)", "əˈbeɪ.ən(t)s"):
            self.assertIn("(", N.normalize(s), s)
            self.assertIn(")", N.normalize(s), s)

    def test_成音节辅音保留(self):
        """`əˈbleɪ.ʃn̩` 直接删 ̩ 会得到没有元音的音节；
        展开成 `ʃən` 是**另一种音节分析**，不是同一个陈述。"""
        self.assertEqual(N.normalize("əˈbleɪ.ʃn̩"), "əˈbleɪʃn̩")
        self.assertEqual(N.normalize("ˈeɪ.bl̩"), "ˈeɪbl̩")

    def test_闪音保留(self):
        """🔴 `ˈbʌɾɚ`(butter) 与 `ˈlæɾɚ`(ladder) 的 ɾ 分别来自 t 和 d，
        **闪音把两者中和了**——从音标本身还原不出是哪一个，转写就是猜。
        我一度打算做 ɾ→t，那是错的。"""
        self.assertEqual(N.normalize("ˈbʌɾɚ"), "ˈbʌɾɚ")
        self.assertEqual(N.normalize("ˈlæɾɚ"), "ˈlæɾɚ")

    def test_喉塞保留(self):
        self.assertIn("ʔ", N.normalize("ˈbʌʔn̩"))


class 非英语音位只标记不修改(unittest.TestCase):
    def test_印度英语转写会被标出(self):
        """实测越界的多是印度英语混进了英式列：卷舌 ʈ ɖ、齿龈化 t̪ʰ、小舌 χ。"""
        self.assertTrue(N.non_english("əɖvɵˈkeʈ") >= {"ɖ", "ɵ", "ʈ"})
        self.assertIn("χ", N.non_english("ˈɑːχ.mɛd"))

    def test_标记不改动原串(self):
        s = "əɖvɵˈkeʈ"
        self.assertEqual(N.normalize(s), s)      # 越界字符不在 DROP/REPLACE 里

    def test_合法音位不许被误判(self):
        """第一版的音位清单漏了这几个，于是把 1,433 + 7,773 行误判成"非英语音位" ——
        **量的是我的清单不全，不是数据脏**。补齐后真正越界的只有 318 + 353 行。
        这是 2026-08-01 第七次同类错误（自己的度量造出的数字）。"""
        for s, why in (("ˈbʌtɚ", "ɚ = r 色化 schwa，butter"),
                       ("bɝd", "ɝ = 重读 r 色化元音，bird"),
                       ("lɒx", "x = loch"),
                       ("ʍɪtʃ", "ʍ = which，保守方言"),
                       ("-əˈbɪl.ɪ.ti", "- = 词缀条目 -ability")):
            self.assertEqual(N.non_english(s), set(), why)


class 流水线(unittest.TestCase):
    def test_幂等(self):
        for s in ("æbˈd͡ʒɛk.ʃn̩", "ˈɛə̯.ɹə.pleɪ̯n", "ˈkʰæt(ə)ɫ", "ˈbreɪkˌfɑːst"):
            once = N.normalize(s)
            self.assertEqual(N.normalize(once), once, s)

    def test_归一后不再含任何噪声字符(self):
        for s in ("æbˈd͡ʒɛk.ʃn̩", "ˈkʰæt(ə)ɫ", "ˈneɪ̯.tʃə"):
            out = N.normalize(s)
            for ch in "͡.ʰ‿" + "̯" + "ɫ":
                self.assertNotIn(ch, out, f"{s} → {out} 仍含 {ch!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
