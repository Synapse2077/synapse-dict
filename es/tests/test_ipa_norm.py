#!/usr/bin/env python3
"""es 归一化的金标准测试。跑：`cd es && python3 -m unittest test_ipa_norm -v`

⭐ **期望值不是我推出来的，是从西语版 dump 取的真值**（`es-edition-extract.jsonl.gz`）。
   这是纪律 ⑪ 的落实：跨源比对先跑"已知必须一致"的对照组 ——
   本文件里 `西语版对照` 那一组就是那个对照组，且它验的是**权威源**而不是我的推理。
"""

import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))  # 根模块 paths/kaikki_util/dbtool/ipa_norm/b_ipa 在上一层
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
            backgammon   拼写要 ['k','k']        音标有 ['ɡ']
            rights       拼写要 ['t']            音标有 ['ɡ','d']

        ⚠️ **2026-08-02：`expectorate` 从本用例移走了**（移到下面那个用例）。
           本用例原来的注释自己写着"第一个 ɡ 其实来自 x→/ks/" —— 那正是病根：
           `_coda_stops_from_spelling` 当时不认字母 x，拼写侧少算一个 k，于是长度对不上。
           给 x 补上之后拼写侧是 ['k','k']、音标侧 ['ɡ','ɡ']，**能正确对齐了**，
           该修就得修，不该继续躺在"必须跳过"的名单里。
        """
        for w, s in (("backgammon", "baɡˈɡamon"),
                     ("rights", "ˈriɡds"),
                     ("blackjack", "ˈblaɡʝak")):
            want = N._coda_stops_from_spelling(w)
            pos = N._coda_stop_positions(s)
            self.assertTrue(want and pos, w)                            # 两边都非空
            self.assertNotEqual(len(want), len(pos), w)                 # 但长度不等
            self.assertEqual(N.devoice_coda(w, s), s, w)                # 一个字符都不许改

    def test_字母x必须计入拼写侧的coda序列(self):
        """🔴 2026-08-02 修：字母 `x` = /ks/，那个 k 后面永远跟着 s，**永远是 coda**。
        拼写侧不算它，会出两种错：

        ① **跨词错位、撤销别处的修复**（实测 4 行）：
           `óxido de magnesio` 拼写侧只剩 magnesio 的 ɡ、音标侧只剩 óxido 的 k，
           长度"恰好都是 1"→ 把刚修好的 `ˈoksido` 改回 `ˈoɡsido`。
        ② **该修的修不了**：`expectorate` 因长度对不上被整条跳过，
           `ekspeɡtoˈɾate` 里 `ct` 的浊化一直没被清掉。

        ⚠️ 词首 x 读 /s/ 不是 /ks/（`xerocopia` → `seɾoˈkopja`），不计入。
        """
        self.assertEqual(N._coda_stops_from_spelling("expectorate"), ["k", "k"])
        self.assertEqual(N._coda_stops_from_spelling("examen"), ["k"])
        self.assertEqual(N._coda_stops_from_spelling("xerocopia"), [])      # 词首 x 不计
        # ① 不再被撤销
        self.assertEqual(N.devoice_coda("óxido de magnesio", "ˈoksido de maˈxnesjo"),
                         "ˈoksido de maˈxnesjo")
        # ② 现在能修了
        self.assertEqual(N.devoice_coda("expectorate", "ekspeɡtoˈɾate"), "ekspektoˈɾate")

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


class 同位异音字母(unittest.TestCase):
    """2026-08-03：西语版 36.9 万行入库后的全列字符普查逮到的第三类漏网。

    `canon_edition` 只剥 NFD 组合附加符，`ʲ`(U+02B2)、`ɱ`(U+0271) 是独立字母，
    整批漏进了音位式格子。左边是库里的现值（源值见 `phonetic_raw`），
    ⭐ **右边不是我推的，是库内同一位置的既有写法**（`ancho→ˈantʃo` 等，来自 kaikki-en）。
    """

    GOLD = [("pinchila", "pinʲˈtʃila", "pinˈtʃila"),         # n 在 ch 前腭化
            ("bolchevizar", "bolʲtʃebiˈθaɾ", "boltʃebiˈθaɾ"),  # l 在 ch 前腭化
            ("confricar", "koɱfɾiˈkaɾ", "konfɾiˈkaɾ"),        # n 在 f 前唇齿化
            ("conjunción final", "konxunˈθjoɱ fiˈnal", "konxunˈθjon fiˈnal")]

    def test_腭化与唇齿化归回n(self):
        for w, cur, want in self.GOLD:
            self.assertEqual(N.assimilated_nasals(cur), want, w)

    def test_唇音前的m不动(self):
        """🔴 `convertir→kombeɾˈtiɾ` 是全库六个来源一致的写法（7,216 行），
        本函数不许顺手改 —— 改它是产品决策，不是一致性修复。"""
        for s in ("kombeɾˈtiɾ", "um ˈpoko", "imˈmenso", "emˈbudo"):
            self.assertEqual(N.assimilated_nasals(s), s)


class 可选段落定(unittest.TestCase):
    def test_滑音前的括号是插音_整组删(self):
        """不止 (ɡ)：西语版对 /w/ 前的强化辅音一律加括号，(k)/(d)/(t) 同理。"""
        for w, cur, want in (("moyuelo", "moʝˈ(ɡ)welo", "moʝˈwelo"),
                             ("wicca", "ˈ(k)wika", "ˈwika"),
                             ("Siwady", "siˈ(d)wadi", "siˈwadi"),
                             ("Lower Hutt", "loˈ(t)weɾ ˈut", "loˈweɾ ˈut")):
            self.assertEqual(N.resolve_optional(w, cur), want, w)

    def test_拼写里真有那个辅音时_源头写在括号外_不会丢音(self):
        self.assertEqual(N.resolve_optional("Lagwira", "laɡˈ(ɡ)wiɾa"), "laɡˈwiɾa")
        self.assertEqual(N.resolve_optional("talweg", "talˈ(ɡ)weɡ"), "talˈweɡ")
        self.assertEqual(N.resolve_optional("Rackwitz", "rakˈ(k)witθ"), "rakˈwitθ")

    def test_词尾可选塞音按拼写末字母定形(self):
        """与 devoice_coda 同一判据（字母是 t，音就该是 t），只是位置在词尾。"""
        self.assertEqual(N.resolve_optional("president", "pɾesiˈden(d)"), "pɾesiˈdent")
        self.assertEqual(N.resolve_optional("Piquet", "piˈke(d)"), "piˈket")
        self.assertEqual(N.resolve_optional("Broussard", "bɾuˈsaɾ(d)"), "bɾuˈsaɾd")

    def test_其余括号_拼写里有就留没有就删(self):
        self.assertEqual(N.resolve_optional("extraño", "e(k)sˈtɾaɲo"), "eksˈtɾaɲo")  # x=/ks/
        self.assertEqual(N.resolve_optional("dseta", "ˈ(d)seta"), "ˈdseta")
        self.assertEqual(N.resolve_optional("Islas Falkland", "ˌislas ˈfo(l)kland"),
                         "ˌislas ˈfolkland")
        # 拼写里没有 e —— 那是口语加音，不进音位式
        self.assertEqual(N.resolve_optional("ftalocianina", "(e)ftaloθjaˈnina"),
                         "ftaloθjaˈnina")

    def test_括号里的塞音必须先落定再算coda(self):
        """`(ɡ)` 也是塞音。若 `devoice_coda` 先跑，"第 n 个塞音"的对位就会错。

        ⚠️ 入口值取 `canon_edition` 之后的形态（齿音符等组合附加符由它剥，不归 normalize）。
        """
        self.assertEqual(N.normalize("hardware", "aɾdˈ(ɡ)waɾe"), "aɾdˈwaɾe")


class 滑音折叠(unittest.TestCase):
    """2026-08-01 已决策（FRAMEWORK §五之二：跟英文版 `ˈeuɾo`），2026-08-03 才实现。"""

    def test_后置滑音折成元音字母(self):
        self.assertEqual(N.fold_glides("aˈxewsja"), "aˈxeusja")      # ageusia
        self.assertEqual(N.fold_glides("awɾifiˈkaɾ"), "auɾifiˈkaɾ")  # aurificar
        self.assertEqual(N.fold_glides("ˈkoktejl"), "ˈkokteil")      # cocktail
        self.assertEqual(N.fold_glides("ˈʃow"), "ˈʃou")              # show

    def test_前置滑音一个字符都不碰(self):
        """`bjen` `aɡwa` 全库六个来源写法一致（18.7 万行），折了就是自造记法。"""
        for s in ("ˈɡɾaθjas", "ˈaɡwa", "ˈbjen", "ˈtɾjunfo", "eˈkwestɾe"):
            self.assertEqual(N.fold_glides(s), s)

    def test_紧跟元音的滑音不折(self):
        """后面**紧跟**元音的 j/w 是下一音节的起始，不是降双元音的第二成分。"""
        self.assertEqual(N.fold_glides("kaˈjendo"), "kaˈjendo")
        self.assertEqual(N.fold_glides("aˈɡwanta"), "aˈɡwanta")

    def test_中间隔着重音符时要折(self):
        """⚠️ 这条我第一版写反了，回库核对才发现：全库 7 条 `V+滑音+ˈ+V`，
        每一条的滑音都是**前一个降双元音的尾巴**，不是后一音节的起始 ——
        `tau-ónicos` `krisna-ísta` `agro-urbano` `tiro-hioideo`。所以要折。"""
        self.assertEqual(N.fold_glides("tawˈonikos"), "tauˈonikos")
        self.assertEqual(N.fold_glides("kɾisnajˈista"), "kɾisnaiˈista")

    def test_与库内老约定一致(self):
        """右边是库里 kaikki-en 的现值 —— 折叠的目的就是让新收的行与它们同形。"""
        for w, src, want in (("euro", "ˈewɾo", "ˈeuɾo"), ("aire", "ˈajɾe", "ˈaiɾe"),
                             ("veinte", "ˈbejnte", "ˈbeinte"),
                             ("causa", "ˈkawsa", "ˈkausa")):
            self.assertEqual(N.normalize(w, src), want, w)


if __name__ == "__main__":
    unittest.main(verbosity=2)
