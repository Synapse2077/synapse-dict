#!/usr/bin/env python3
"""es 归一化的金标准测试。跑：`cd es && python3 -m unittest test_ipa_norm -v`

⭐ **期望值不是我推出来的，是从西语版 dump 取的真值**（`es-edition-extract.jsonl.gz`）。
   这是纪律 ⑪ 的落实：跨源比对先跑"已知必须一致"的对照组 ——
   本文件里 `西语版对照` 那一组就是那个对照组，且它验的是**权威源**而不是我的推理。
"""
import unittest

import ipa_norm as N


class 记法层(unittest.TestCase):
    def test_空值安全(self):
        for x in (None, ""):
            self.assertEqual(N.normalize("x", x), x)

    def test_音位式与严式拼一起时只取音位式(self):
        """`gracias` 的 kaikki 原值是 `/ˈɡɾaθjas/ [ˈɡɾa.θjas]` 整串。"""
        self.assertEqual(N.normalize("gracias", "ˈɡɾaθjas [ˈɡɾa.θjas]"), "ˈɡɾaθjas")

    def test_去连结弧音节点长音符与升降符(self):
        self.assertEqual(N.basic("ˈt͡ʃiko"), "ˈtʃiko")       # 连结弧
        self.assertEqual(N.basic("ˈɡɾa.θjas"), "ˈɡɾaθjas")   # 音节点
        self.assertEqual(N.basic("ˈkaːsa"), "ˈkasa")         # 长音符
        self.assertEqual(N.basic("ˈaw̝to"), "ˈawto")          # 升符 ̝
        self.assertEqual(N.basic("ˈliβ̞ɾo"), "ˈliβɾo")        # 降符 ̞（尚未归塞音）

    def test_多词条目的空格保留(self):
        """`FBI` → `ˌefe ˌbe ˈi`：分词空格是内容，归一化不许吃掉。"""
        self.assertEqual(N.normalize("FBI", "ˌefe ˌbe ˈi"), "ˌefe ˌbe ˈi")

    def test_擦音变体归音位(self):
        """库内约 1.2 万行把同位异音写进了音位式格子，RAE 教学式写 /b d ɡ n/。"""
        self.assertEqual(N.normalize("libro", "ˈliβɾo"), "ˈlibɾo")
        self.assertEqual(N.normalize("jugo", "ˈxuɣo"), "ˈxuɡo")
        self.assertEqual(N.normalize("inconfortable", "iŋkonfoɾˈtable"), "inkonfoɾˈtable")


class Coda清音(unittest.TestCase):
    """🔴 期望值全部取自西语版 dump（RAE 标准），不是我推的。"""

    # (词形, 库内英文版值, 西语版真值)
    GOLD = [
        ("acto",       "ˈaɡto",        "ˈakto"),
        ("apto",       "ˈabto",        "ˈapto"),
        ("óptimo",     "ˈobtimo",      "ˈoptimo"),
        ("doctor",     "doɡˈtoɾ",      "dokˈtoɾ"),
        ("efecto",     "eˈfeɡto",      "eˈfekto"),
        ("raptor",     "rabˈtoɾ",      "rapˈtoɾ"),
        ("ritmo",      "ˈridmo",       "ˈritmo"),
        ("técnico",    "ˈteɡniko",     "ˈtekniko"),
        ("septiembre", "sebˈtjembɾe",  "sepˈtjembɾe"),
    ]

    def test_与西语版逐字一致(self):
        for w, src, gold in self.GOLD:
            self.assertEqual(N.normalize(w, src), gold, w)

    def test_一个词里派生浊音与原生浊音并存(self):
        """`septiembre` 的第一个 b 来自 `pt` 的 p（要清化），第二个来自 `br` 的 b（不能动）。
        按序对齐才能分开处理；第一版没做对齐，整条被跳过。"""
        self.assertEqual(N.normalize("septiembre", "sebˈtjembɾe"), "sepˈtjembɾe")

    def test_原生浊音不许被动(self):
        """`abdicar` 的 b、d 都是词形自带的，清化就错了。"""
        self.assertEqual(N.normalize("abdicar", "abdiˈkaɾ"), "abdiˈkaɾ")

    def test_塞音加滑音不算候选(self):
        """`tj`（tiem-）是音节起始，不是 coda。
        这是 `septiembre` 当初对不齐的**真正**原因（我一度误以为是流音，见下一个用例）。"""
        self.assertNotIn(4, N._coda_stop_positions("sebˈtjembɾe"))   # 位置 4 的 t 在 j 前

    def test_塞音加流音要算候选_但结果不变(self):
        """⚠️ 流音曾被排除，那是多余的（2026-08-01 去掉）。

        `libro` / `padre` / `otro` 的塞音**本来就与字母清浊一致**，
        算进候选后替换成自己，端到端结果不变 —— 所以排除它没有收益；
        而排除它会漏掉整个 `tl`/`dl` 族（见下一个用例）。
        本用例断言的是**端到端不变**，不是内部序列长什么样：
        内部形态是实现细节，把它写死进断言会让正确的重构失败。
        """
        self.assertEqual(N.normalize("libro", "ˈliβɾo"), "ˈlibɾo")
        self.assertEqual(N.normalize("padre", "ˈpaðɾe"), "ˈpadɾe")
        self.assertEqual(N.normalize("otro", "ˈotɾo"), "ˈotɾo")
        self.assertEqual(N.normalize("septiembre", "sebˈtjembɾe"), "sepˈtjembɾe")

    def test_tl与dl族要被修正(self):
        """🔴 由豆包评审提出、回西语版 dump 确定性核实后采纳。
        `atleta` 库内 `adˈleta`（英文版的浊化写法），**西语版写 `aˈtleta`**。
        豆包给的理由（tl 不是合法起始丛）其实不对 —— 西语版切成 a.tle.ta，t 是起始；
        但结论对：**字母是 t，音就该是 t，与音节归属无关。**"""
        self.assertEqual(N.normalize("atleta", "adˈleta"), "atˈleta")
        self.assertEqual(N.normalize("nahuatlatos", "naw̝adˈlatos"), "nawatˈlatos")

    def test_tl不动(self):
        """`atlas` 库内已是 `ˈatlas`（正确），归一化不该把它改坏。"""
        self.assertEqual(N.normalize("atlas", "ˈatlas"), "ˈatlas")

    def test_音标侧为空时跳过(self):
        """真实案例（取自全量普查 2,985 条"长度不等"的行）：
        缩写按字母名读（`KGB` → `ˌka ˌxe ˈbe`）、静音字母（`gnosis` → `ˈnosis`）、
        外来词（`stock` → `ˈstok`）—— 拼写给出的 coda 塞音在音位式里根本不存在。"""
        for w, s in (("KGB", "ˌka ˌxe ˈbe"), ("gnosis", "ˈnosis"),
                     ("stock", "ˈstok"), ("pseudo-", "seudo")):
            self.assertTrue(N._coda_stops_from_spelling(w), w)          # 拼写确实要求了
            self.assertEqual(N._coda_stop_positions(s), [], w)          # 但音标侧没有
            self.assertEqual(N.devoice_coda(w, s), s, w)                # 所以不动

    def test_两边都非空但长度不等时也必须跳过(self):
        """🔴 这才是真正会伤到数据的一类，**899 行，几乎全是外来词**（已知雷区）。
        上一个用例的 pos 全是空表，把 want 截断到 0 长度等于什么都没做 ——
        变异测试第一次没被拦住就是因为这个，用例形同虚设。
        这里的案例两侧都非空，强行对齐会真的改错字符：
            expectorate  拼写要 ['k']            音标有 ['ɡ','ɡ']（第一个 ɡ 其实来自 x→/ks/）
            backgammon   拼写要 ['k','k']        音标有 ['ɡ']
            rights       拼写要 ['t']            音标有 ['ɡ','d']
        """
        for w, s in (("expectorate", "eɡspeɡtoˈɾate"),
                     ("backgammon", "baɡˈɡamon"),
                     ("rights", "ˈriɡds"),
                     ("blackjack", "ˈblaɡʝak")):
            want = N._coda_stops_from_spelling(w)
            pos = N._coda_stop_positions(s)
            self.assertTrue(want and pos, w)                            # 两边都非空
            self.assertNotEqual(len(want), len(pos), w)                 # 但长度不等
            self.assertEqual(N.devoice_coda(w, s), s, w)                # 一个字符都不许改

    def test_ch二合字母绝不能被当成coda(self):
        """🔴 全量普查逮到的严重错误（测试里一个 ch 词都没有，只跑测试发现不了）：
        西语 `ch` = /t͡ʃ/。库内存带连结弧的 `t͡ʃ`，`basic()` 去弧后成 `tʃ`，
        看起来像"t 后面跟辅音"；而拼写 `derecho` 的 `c` 后面跟着 `h`。
        两边一凑，第一版把 `deˈɾet͡ʃo` 改成了 `deˈɾekʃo`。"""
        self.assertEqual(N.normalize("derecho", "deˈɾet͡ʃo"), "deˈɾetʃo")
        self.assertEqual(N.normalize("mucho", "ˈmut͡ʃo"), "ˈmutʃo")
        self.assertEqual(N.normalize("chiapaneco", "t͡ʃjapaˈneko"), "tʃjapaˈneko")
        self.assertEqual(N.normalize("SHCP", "ˌese ˌat͡ʃe ˌθe ˈpe"), "ˌese ˌatʃe ˌθe ˈpe")
        self.assertEqual(N._coda_stops_from_spelling("derecho"), [])
        self.assertEqual(N._coda_stop_positions("deˈɾetʃo"), [])


class 流水线(unittest.TestCase):
    def test_幂等(self):
        """归一化跑第二遍必须不再变化 —— 否则展示层的幂等兜底会把数据改坏。"""
        for w, src, _ in Coda清音.GOLD:
            once = N.normalize(w, src)
            self.assertEqual(N.normalize(w, once), once, w)

    def test_顺序是判据_擦音要先归塞音(self):
        """`devoice_coda` 只认 b/d/ɡ。若在 `spirants_to_stops` 之前跑，
        `aβ̞ð̞ukˈtoɾ` 这类还是 β/ð 形态，coda 的 ɣ→k 就会被漏掉。"""
        self.assertEqual(N.normalize("abductor", "aβ̞ð̞uɣˈtoɾ"), "abdukˈtoɾ")


class 叠塞音闸(unittest.TestCase):
    """🔴 全量普查（第二次）逮到的第二类错误：664 行外来词被改出了西语不存在的叠塞音。

    `vedette` `yuppie` `sketches` `rockers` `tickets` 这类词，拼写里的 tt/pp/ck
    撞上本规则会变成 /tt/ /pp/ /kk/ —— 西语音系不允许。
    外来词是本项目反复栽跟头的雷区，这里不试图修，只保证不改得更糟。
    """

    GOLD = [("vedette", "beˈdedte"), ("yuppie", "ˈʝubpje"), ("sketches", "ˈskedt͡ʃes"),
            ("rockers", "ˈroɡkeɾs"), ("tickets", "ˈtiɡkeds"), ("vendetta", "benˈdedta")]

    def test_改出叠塞音就整条不动(self):
        for w, src in self.GOLD:
            base = N.spirants_to_stops(N.basic(N.strip_narrow(src)))
            self.assertEqual(N.devoice_coda(w, base), base, w)

    def test_源值自带叠塞音时闸门不误伤(self):
        """闸门只拦**新产生的**叠塞音。`atto-` 的源值本来就是 `ˈatto`，
        规则对它是零改动，不该因为"结果里有叠塞音"就被当成异常。"""
        self.assertEqual(N.normalize("atto-", "ˈatto"), "ˈatto")

    def test_正常coda不受叠塞音闸影响(self):
        self.assertEqual(N.normalize("acto", "ˈaɡto"), "ˈakto")
        self.assertEqual(N.normalize("raptor", "rabˈtoɾ"), "rapˈtoɾ")


if __name__ == "__main__":
    unittest.main(verbosity=2)
