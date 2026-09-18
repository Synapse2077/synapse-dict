#!/usr/bin/env python3
"""回归闸：**过去每一个修复，现在还在不在**。ja 版，2026-09-16（阶段 7）。

═══ 为什么必须有这个 ═══
用户 2026-08-11（es 上）：「同一个问题你修了，隔天修其他问题，你又发现之前的问题
又出现了。这才是我抱怨的。这也才是导致无穷无尽的根本原因。」

修复消失有**四种**机制，后三种极隐蔽（`[[fix-regression-and-gate]]`）：
  ❌ **被抹掉**：某个 build 脚本 DROP 重建那张表。
  ⚠️ **被绕过（换读取路径）**：数据还在，但展示层改读别的地方了。
  ⚠️ **被绕过（A 层搬到 B 层）**：修复写在 A 层，而后一步把 B 层的文本搬进 A 层。
  ⚠️ **闸没坏，是没人再看它了**：ACCEPT 按名字豁免 ⇒「已接受」＝「不再看」。
     ⇒ 本文件的 ACCEPT **锁数字**：超了红，低了要求收紧（结尾单独汇总）。

═══ 🔴 判据一律 import 生成侧那一份，绝不在闸里重写 ═══
闸与它守的那段逻辑用两个不同判据 ⇒ **闸在报自己的 bug**。
de 建这个文件当天 33 条里 8 条红、**7 条是断言的错**。
ja 这一轮自己也演过同一出：阶段 1 的罗马字断言写成 `romaji LIKE '% kanji'`，
报 6 条红全是真词真罗马字 —— 断言和抽取器用了两条不同的规则。

⇒ 下面凡是能 import 的判据都 import：
   `romaji_of` / `GRADE_LABEL`（阶段 1）、`KIND` / `clean_target` / `JA`（阶段 5b）、
   `simplified_only`（阶段 5a）、`_same`（阶段 5c）、`PURE_KANA`（阶段 4b）。

═══ ⚠️ 这门语言特有的「判据不能照抄」清单 ═══
① `.lower()` / `COLLATE NOCASE` / `LIKE` 在日语上**只折 ASCII**，等于空操作。
② 「词出现在例句里」不成立 —— 用言会活用、假名词头的例句用汉字写。
③ 「没有假名 ⇒ 是中文」不成立 —— `青空。``核兵器``二時間` 都是纯汉字的正经日语。
④ 纯汉字串**字形上分不出中日**，要按来源判（`dbtool.is_chinese_text` 拿不到 src 就抛异常）。

用法（在仓库根）：
    python3 -u ja/tests/test_no_regression.py
    python3 -u ja/tests/test_no_regression.py --mutate
"""
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import paths                                          # noqa: E402
# 🔴 判据只许一份 —— 下面这些全是**生成侧那一份**
from build_entry_layer import GRADE_LABEL             # noqa: E402
from harvest_relations import KIND, clean_target, JA  # noqa: E402
from harvest_examples import simplified_only          # noqa: E402
from fill_freq import _same                           # noqa: E402
from backfill_kana import PURE_KANA                   # noqa: E402
from build import norm_ja                             # noqa: E402
from intake_edition_words import SECTION              # noqa: E402
# 阶段 4c 汉字音訓読み层 —— 判据 import 生成侧那一份，闸里不重写
from build_kanji_reading import KIND as KR_KIND, split_okuri   # noqa: E402
sys.path.insert(0, str(HERE.parent / "fixes"))
from fix_gloss_residue import ONLY_BRACKET            # noqa: E402

f = lambda n: format(n, ",")

# v3 的十四张表。少一张就是被 DROP 重建了。
TABLES = ("entry", "sense_src", "sense", "sense_gloss", "sense_tag", "sense_relation",
          "pronunciation", "inflection", "example", "example_gloss", "collocation",
          "collocation_gloss", "audio", "field_src",
          # 阶段 4c（2026-09-18）：汉字音訓読み层，日语独有
          "kanji_reading")


# ══════════════════════════════════════════════════════════════════
# 允许的非零基线：`断言名 → (期望值, 理由)`。**锁数字不锁名字。**
ACCEPT = {
    "A1 义项没有中文": (
        3_139,   # 2026-09-18 从 3,202 收紧：3b 那批多层 gloss 的中文回填
                 # （`translate_hier_gloss` → `fix_hierarchical_gloss --load`）
                 # 又补上 63 条。**闸报「⬇ 该收紧」报了两轮我才来改** ——
                 # 不收紧的代价是这 63 条哪天掉回去它一声不响。
                 # 2026-09-16 从 3,213 → 3,202：`fix_gloss_residue` 删掉 31 条
                 # 「整条只是【异写列表】」的义项，其中 11 条本来就没中文。
        "3,139 / 296,549 ＝ 1.06%。两批付费翻译（1.5b 英译中、3b 日译中）跑完之后的残余，"
        "其中绝大多数是控制组 E0「模型判定给不出」那一类 —— **是缺不是错**，"
        "读者看到的是没有中文，不是看到错的中文（`docs/FRAMEWORK.md`：错比缺更伤权威）。"),
    "B4 词元没有假名读音（读者口径）": (
        41_964,  # 🔴 41,996 是我**估的**（140,105 - 98,224 那一减），41,964 是**量的**。
                 # 差 32 是因为收词补的那批里有些词形本来就有别的 entry 带读音。
                 # 写估算值当基线＝给自己留 32 条的静默余量。
        "按 `entry` 的 word_id 去重算，覆盖 81.5%。缺口三块，逐块对得上账："
        "①`pos=kanji` 单字 12,833 —— **汉字作为「字」本来就没有单一读音**，不是缺陷；"
        "②`unknown` 13,321 —— `あか抜ける` 这类假名汉字混排，三版都没给读音；"
        "③425 条**盲文**（⠁⠷⠵），正确地没有假名读音。"
        "🔴 阶段 4b 之前这个数是 140,105（覆盖 39.8%）—— 那是阶段 3a 收词之后"
        "**没人重跑读音层**造成的，账的闸 P6 现在按覆盖率盯着它。"),
    "C1 变形悬空原形（base_id 为空）": (
        995,     # 🔴 2026-09-16 从 988 上调 7：`fixes/recover_pointer_senses.py` 从
                 #    英文版指针正文里补了 375 条活用（`見た` ← `見る 过去`），
                 #    其中 7 条的原形连三版都没有独立条目。
                 #    **上调基线必须写清多出来的是什么**，否则它就是个掩盖回归的开关。
        "988 / 567,717 ＝ 0.17%。`base` 文本都在，只是原形词头连三版都没有独立条目。"
        "🔴 阶段 2 建完变形层时这个数是 **221,135**，阶段 3a 收词后重连了 220,147 行。"
        "**pt 正是栽在这个顺序上**（变形层建在收词之前 ⇒ 46.2% 空白页）。"
        "⚠️ 展示层查变形**必须走 `inflection.word_id`，别走 `base_id`**。"),
    "C3 空白页词形（无义项、无变形、无指针）": (
        9_765,   # 🔴 2026-09-16 二次收紧 12,206 → 9,765：`recover_pointer_senses.py`
                 #    把英文版指针正文里的 3,812 条关系 + 375 条活用落了库。
                 #    **是闸自己报「⬇ 该收紧」我才来改的** —— 不改就等于
                 #    默许它下次涨回 12,206 而一声不吭。
        "12,248 / 710,264 ＝ 1.72%（对照 pt 那轮 46.2%、fr 1.8%）。"
        "主要是阶段 2 收进来的变形词形里，原形不在库、自己也没有义项的那批。"),
    "D2 有声调标记但推不出重音核": (
        11,      # 实测 11（阶段 4 当时记的 12 里有 1 条后来被去重掉了）
        "12 / 27,487 ＝ 0.04%。核位置由「假名拍数 + roman 标记」推，"
        "与源头的类型标签（Heiban/Nakadaka/…）一致 27,475 条 ＝ 99.96%；"
        "**不一致的这 12 条只存 `pitch_mark` 不存 `pitch_pos`** —— "
        "推不准就留空，不写一个看起来像数据的猜测。"),
    "B5 假名词头的读音不等于它自己（已折字体）": (
        68,
        "68 条，两类都是**真数据不是缺陷**：<br>"
        "①`ヶ`/`ケ` 读作 か/が/こ（4 条）—— 这个字是**记号不是表音假名**"
        "（`一ヶ月`＝いっかげつ），它的读音本来就不是它自己；<br>"
        "②**长音写法变体**（`ぐう`→`グー`、`にゃあ`→`ニャー`、`ぷうぷう`→`ぷーぷー`、"
        "`サンキュー`→`さんきゅう`）—— 源头 `head_templates` 给的是另一种同音写法。"
        "折字体能消掉 1,312 条片假名/平假名互写，长音这一档折不掉，也不该折："
        "`ー` 和 `う` 在别的词上是不同的音。<br>"
        "🔴 **推翻它需要**：出现 `kana_src='identity'` 的行落进这一桶 —— "
        "那批是阶段 4b 按同义反复写的，字面必须相等，一条都不许有。"),
    "G3 词元没有频次": (
        181_102,
        "181,102 / 248,983 ＝ 72.7% 没有频次，**有意的**。"
        "wordfreq 的日语通路对多 token 词形返回的是**由部件组合估算**的值，方向固定偏高："
        "`分親` 4.90、`情報管理システム` 4.81，而 `愛する` 才 4.26 ⇒ "
        "**生僻复合词会被系统性顶到常用词上面**。频次的下游用途正是排序和挑核心词，"
        "**在这个方向上说谎的尺子比没有尺子更坏** ⇒ 只给单 token 且 token 就是它自己的词形落数。"
        "⚠️ 代价：核心词挑选只能在这 27.3% 里做，§四.2 的分母要按这个口径说。"),
    "H1 常用 500 词里没有真人录音的": (
        419,
        "419 / 500 ＝ 81.8% 的常用词没有真人录音。Commons 上日语发音总共约 1,500 个文件"
        "（LinguaLibre 1,043），对照法语 436,115 —— **日语在维基生态里确实被录得极少**。"
        "方针④是三级兜底（真人 > 工具生成 > 浏览器 TTS），不要求真人全覆盖。"
        "⚠️ 合成音不做：it 那轮用户试听判定质量不够（`[[it-tts-layer]]`）。"
        "🔴 **推翻它需要**：Commons 日语发音文件数显著增长（比如 LinguaLibre 超过 5,000），"
        "或出现新的开放真人录音源。"),
}


def build(con):
    """→ [(组, 名字, 计数)]。计数 > ACCEPT 里的期望值就红。"""
    q = lambda s: con.execute(s).fetchone()[0]
    simp = simplified_only(con)
    C = []
    a = C.append

    # ── L 结构：表还在不在 ──
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    a(("L", "L1 v3 的表被 DROP 掉了", len([t for t in TABLES if t not in have])))

    # ── A 义项与释义 ──
    a(("A", "A1 义项没有中文", q(
        "SELECT COUNT(*) FROM sense s WHERE NOT EXISTS("
        "  SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='zh')")))
    # 阶段 3b 收尾修的：拆编号义项后剩空串
    a(("A", "A2 释义是空串", q(
        "SELECT COUNT(*) FROM sense_gloss WHERE TRIM(text)=''")))
    a(("A", "A3 义项一条 gloss 都没有", q(
        "SELECT COUNT(*) FROM sense s WHERE NOT EXISTS("
        "  SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id)")))
    # 阶段 3a `clean_gloss` v3 / 阶段 7 `fix_gloss_residue` 修的：释义里的结构残渣。
    # 🔴 **拆成两条，判据各自 import 那一份。** 第一版我写成一条大 SQL
    #    「含 `==` 或 `【】` 或汉字等级」，报 71 条，逐条读之后**只有 62 条是真的**——
    #    另外 385 条是中文版的**正当写法** `【decilitre】分升。`（【英文原词】中文释义）。
    #    判据比它要描述的东西宽，报红报绿都说明不了问题。
    glosses = [t or "" for (t,) in con.execute("SELECT text FROM sense_gloss")]
    a(("A", "A4a 释义里残留 ==章节== 标记", sum(
        1 for t in glosses if SECTION.search(t))))
    a(("A", "A4b 整条释义只是一个【异写列表】", sum(
        1 for t in glosses if ONLY_BRACKET.match(t))))
    a(("A", "A4c 释义整条只是汉字等级标注", sum(
        1 for t in glosses if t.strip() in ("（常用漢字）", "（表外漢字）",
                                            "（人名用漢字）", "（教育漢字）"))))

    # 🔴 繁简：阶段 9 之后修的（欠账 7）。中文版收来的释义/例句译文原样落库，
    #    而中文版维基繁简混排 ⇒ 页面上两种字形。
    # ⚠️ **确定性抽样**（每 15 行取 1，约 2 万条，0.25 秒）。全量那份 3.7 秒，
    #    对每次写库太贵，留在 `ja/fixes/fix_traditional_to_simplified.py` 自己的闸里。
    #    抽样够用的理由：**回归只会由「重跑某个建库步骤」造成，那是成千上万条，不是 2 条。**
    try:
        import opencc as _oc
        sys.path.insert(0, str(HERE.parent / "fixes"))
        from fix_traditional_to_simplified import convert as _t2s
        _cv = _oc.OpenCC("t2s").convert
        trad = 0
        for tbl in ("sense_gloss", "example_gloss"):
            for (t,) in con.execute(
                    "SELECT text FROM %s WHERE lang='zh' AND rowid %% 15 = 0" % tbl):
                trad += (_t2s(t or "", _cv)[0] != t)
        a(("A", "A5 中文释义/译文里还有繁体（抽样 1/15）", trad))
        # 🔴 反向断言：**日文词形（【】内）的原字必须还在**。
        #    它为 0 说明保护段失效了 —— 那时 A5 反而会是绿的，
        #    因为"全转成简体"正是 A5 想要的。**两条断言必须一起看。**
        from fix_traditional_to_simplified import BRACKET_JA as _BR
        kept = sum(1 for (t,) in con.execute(
            "SELECT text FROM sense_gloss WHERE lang='zh' AND text LIKE '%【%'")
            for m in _BR.finditer(t or "") if _cv(m.group(0)) != m.group(0))
        a(("A", "A6 日文词形（【】内）的原字被一起转成简体了", 0 if kept else 1))
    except ImportError:
        pass

    # 🔴 A7：台湾说法。判据 import 修复侧那一份（**手工清单，判据只许一份**）。
    #    ⚠️ 这是一张手工表，**清单漏掉的下次不会有人发现** —— 它守的只是
    #      「已知的这些不会回潮」，不是「没有台湾说法了」。别把它当后者。
    try:
        sys.path.insert(0, str(HERE.parent / "fixes"))
        from fix_tw_vocab import apply_row as _tw
        a(("A", "A7 已知的台湾说法回潮了（网路/影印机/资讯/义大利/计程车）", sum(
            1 for tbl in ("sense_gloss", "example_gloss")
            for (t,) in con.execute("SELECT text FROM %s WHERE lang='zh'" % tbl)
            if _tw(t or "") != t)))
    except ImportError:
        pass

    # ── B 词条层与读音 ──
    # 🔴 判据 import 自 `build_entry_layer` —— 阶段 1 的断言正是因为**自己重写了一条**
    #    （`romaji LIKE '% kanji'`）报了 6 条假红。
    bad_romaji = sum(1 for r, k in con.execute(
        "SELECT romaji, kana FROM entry WHERE romaji IS NOT NULL")
        if GRADE_LABEL.match(r) and not k)
    a(("B", "B1 罗马字其实是汉字等级标签", bad_romaji))
    a(("B", "B2 kana 里混进汉字或拉丁字母", q(
        "SELECT COUNT(*) FROM entry WHERE kana GLOB '*[一-鿿]*'"
        " OR kana GLOB '*[A-Za-z]*'")))
    a(("B", "B3 kana 非空却没有 kana_src", q(
        "SELECT COUNT(*) FROM entry WHERE kana IS NOT NULL"
        " AND (kana_src IS NULL OR kana_src='')")))
    a(("B", "B4 词元没有假名读音（读者口径）", q(
        "SELECT COUNT(DISTINCT word_id) FROM entry WHERE word_id NOT IN"
        " (SELECT word_id FROM entry WHERE kana IS NOT NULL)")))
    # 阶段 4b 的同义反复：词头是纯假名 ⇒ 读音必须等于它自己
    # 🔴 同义反复是「等于它自己 **up to 字体**」，不是字面相等。
    #    第一版写字面相等，报 1,380 条，其中 **1,312 条是片假名/平假名互写**
    #    （`あか`→`アカ`、`タバコ`→`たばこ`）—— 同一个读音的另一种写法，正当数据。
    #    ⇒ 两边过一遍 `norm_ja`（NFKC + 片假名→平假名），用**生成侧那一份**。
    a(("B", "B5 假名词头的读音不等于它自己（已折字体）", sum(1 for w, k in con.execute(
        "SELECT d.word, e.kana FROM entry e JOIN dict d ON d.id=e.word_id"
        " WHERE e.kana IS NOT NULL")
        if PURE_KANA.match(w) and norm_ja(k) != norm_ja(w))))

    # ── K 汉字音訓読み层（阶段 4c，2026-09-18）──
    # 🔴 这一层是补一条**写滑了的判据**才有的：JA_PLAN §二.4 从「汉字没有**单一**读音」
    #    推到了「不用补」，而汉字有的是一组**分类**读音，日语版写了我们没抽
    #    （`[[dont-say-source-lacks-what-we-skipped]]`）。闸盯着它别再掉回去。
    # 🔴🔴 **表不在就跳过整组，别抛异常。** M27（DROP 掉这张表）第一版让 build()
    #    当场崩溃 —— 而 L1「表被 DROP 掉了」明明已经算出来了，却因为下面这句
    #    抛异常而永远打不到屏幕上。**崩溃比报红危险**：它看起来像环境问题，
    #    而不是「有人把一层数据删了」。分工是 L1 管「在不在」、K 组管「对不对」，
    #    K 组崩溃等于把 L1 的话也堵死了（`[[correct-steps-can-compose-a-hole]]`）。
    kr = list(con.execute("SELECT kana, kana_stem, okurigana, kind, subkind,"
                          " is_joyo, entry_id FROM kanji_reading")
              ) if "kanji_reading" in have else []
    # K1/K2 值域 —— **值域从生成侧的 KIND 表算**，不在闸里手抄一份
    a(("K", "K1 音训读的 kind 越界", sum(
        1 for r in kr if r[3] not in {k for k, _ in KR_KIND.values()})))
    a(("K", "K2 音训读的 subkind 越界", sum(
        1 for r in kr if r[4] is not None
        and r[4] not in {s for _, s in KR_KIND.values() if s})))
    # 🔴 K3 是**可逆性回核（100%，非抽样）**，不是计数：拿存下来的 `kana` 重跑
    #    生成侧的 `split_okuri`，和存下来的 stem/okuri 逐条比。计数型判据对
    #    「拆错了但条数对」结构性失明（`[[primary-key-is-not-enough]]`）。
    a(("K", "K3 送假名拆分与生成侧对不上（可逆性回核）", sum(
        1 for r in kr if split_okuri(r[0]) != (r[1], r[2]))))
    # K4 跨字段矛盾：细分必须属于它那个大类
    a(("K", "K4 subkind 不属于它的 kind", sum(
        1 for r in kr if r[4] is not None and KR_KIND.get(r[4], (None,))[0] != r[3])))
    a(("K", "K5 名乗り被并进訓読み", sum(
        1 for r in kr if r[3] == "kun" and r[4] == "nanori")))
    # K6 挂载：必须挂在 `character` 条目上，挂到词条目上等于把「字的读音」
    #    说成「词的读音」——那正是这一层要区分的东西
    a(("K", "K6 音训读挂到了非 character 条目", q(
        "SELECT COUNT(*) FROM kanji_reading k JOIN entry e ON e.id=k.entry_id"
        " WHERE e.pos_raw<>'character'") if "kanji_reading" in have else 0))
    a(("K", "K7 音训读孤儿（word_id 不在 dict）", q(
        "SELECT COUNT(*) FROM kanji_reading k LEFT JOIN dict d"
        " ON d.id=k.word_id WHERE d.id IS NULL") if "kanji_reading" in have else 0))

    # ── C 变形层 ──
    a(("C", "C1 变形悬空原形（base_id 为空）", q(
        "SELECT COUNT(*) FROM inflection WHERE base_id IS NULL")))
    a(("C", "C2 变形指向自己", q(
        "SELECT COUNT(*) FROM inflection i JOIN dict d ON d.id=i.word_id"
        " WHERE d.word=i.base")))
    a(("C", "C3 空白页词形（无义项、无变形、无指针）", q(
        "SELECT COUNT(*) FROM dict d WHERE NOT EXISTS("
        "  SELECT 1 FROM sense s WHERE s.word_id=d.id) AND NOT EXISTS("
        "  SELECT 1 FROM inflection i WHERE i.word_id=d.id) AND NOT EXISTS("
        "  SELECT 1 FROM sense_relation r WHERE r.word_id=d.id"
        "   AND r.kind IN ('alt_of','see_also'))")))

    # ── D 声调 ──
    a(("D", "D1 重音核超出拍数范围", q(
        "SELECT COUNT(*) FROM pronunciation WHERE pitch_pos IS NOT NULL"
        " AND pitch_pos < 0")))
    a(("D", "D2 有声调标记但推不出重音核", q(
        "SELECT COUNT(*) FROM pronunciation WHERE pitch_mark IS NOT NULL"
        " AND pitch_pos IS NULL")))

    # ── E 例句 ──
    a(("E", "E1 例句挂到了别的词的义项上", q(
        "SELECT COUNT(*) FROM example e JOIN sense s ON s.id=e.sense_id"
        " JOIN dict d ON d.id=s.word_id WHERE d.word<>e.word")))
    a(("E", "E2 example_gloss 指向不存在的例句", q(
        "SELECT COUNT(*) FROM example_gloss g LEFT JOIN example e"
        " ON e.id=g.example_id WHERE e.id IS NULL")))
    # 🔴 判据与抽取器同源同范围：只管中文版**没给译文**的那批
    a(("E", "E3 中文版无译文的例句里混着中文句子", sum(
        1 for (t,) in con.execute(
            "SELECT text FROM example WHERE src='zh-edition'"
            " AND src_translation IS NULL")
        if any(c in simp for c in t))))

    # ── F 关系 ──
    a(("F", "F1 关系 kind 在值域外", q(
        "SELECT COUNT(*) FROM sense_relation WHERE kind NOT IN (%s)"
        % ",".join("'%s'" % k for k in (*KIND.values(), "alt_of", "see_also",
                                              # 2026-09-16 加：从英文版指针正文里
                                              # 抽出的「旧字体/新字体」关系
                                              "kyujitai")))))
    a(("F", "F2 关系指向自己", q(
        "SELECT COUNT(*) FROM sense_relation r JOIN dict d ON d.id=r.word_id"
        " WHERE d.word=r.target")))
    # 🔴 §二.5：一个词形不许被断言成 ≥2 个不同词的异体
    a(("F", "F3 同音索引页混进了异表记", q(
        "SELECT COUNT(*) FROM (SELECT word_id FROM sense_relation"
        " WHERE kind='alt_of' GROUP BY word_id HAVING COUNT(DISTINCT target)>1)")))
    # 🔴 判据 import 自 `harvest_relations.clean_target`
    a(("F", "F4 关系目标是英文释义不是词", sum(
        1 for (t,) in con.execute("SELECT DISTINCT target FROM sense_relation")
        if clean_target(t) != t or (not JA.search(t) and " " in t))))

    # ── 🔴 2026-09-17 关系层清洗（`ja/fixes/fix_relation_kind_and_targets.py`）──
    #    判据 import 自修复侧那一份 —— 自己重写一条会和它慢慢长歪
    #    （`[[etymology-layer-acceptance]]`：同一个假设写在两处，只改一处三层全绿）。
    from fixes.fix_relation_kind_and_targets import clean as _rel_clean
    a(("F", "F5 关系目标还带残渣（振假名括号/英文标签/罗马字回显/冒号）", sum(
        1 for (t,) in con.execute("SELECT DISTINCT target FROM sense_relation")
        if _rel_clean(t) != t)))
    # 🔴🔴 F6/F7 **必须成对看**，单看任何一条都会反过来：
    #    ja 版 `proverbs` 装的是「熟語」不是谚语（实测目标 ≤4 字 94.9%），
    #    已归位到 `derived`；而 en 版那 384 条是**真谚语**（逐条读过）。
    #    只查 F6 的话，「把两版一起删光」会显示成修得很干净 ——
    #    与 `fix_traditional_to_simplified` 的 A5/A6 同一个形状。
    a(("F", "F6 ja 版的「熟語」又被当成谚语收进来了", q(
        "SELECT COUNT(*) FROM sense_relation WHERE kind='proverb' AND src='ja-edition'")))
    # 🔴 **这一条不问数量，只问在不在。** 第一版写的是 `384 - count`，
    #    被字面量闸当场打红（`test_no_literal_counts.py`）—— 它是对的：
    #    384 是**这一版 dump 的数**，换一份 dump 它就过期，而过期的断言会一直绿。
    #    F7 要守的不是「还是 384 条」，是「**别整批消失**」⇒ 判据写成存在性。
    a(("F", "F7 en 版的真谚语整批没了（只问在不在，不问几条）",
       0 if q("SELECT COUNT(*) FROM sense_relation"
              " WHERE kind='proverb' AND src='en-edition'") else 1))
    # 🔴 F8/F9 成对：转写从词形里拆出来之后，**两边都要守**。
    #    只查 F8 的话，「把转写整列丢掉」同样让 F8 全绿 —— 而那是把源头给的事实扔了
    #    （`[[dont-say-source-lacks-what-we-skipped]]`）。
    from fixes.fix_inflection_form_romaji import SHAPE as _form_shape
    a(("F", "F8 词形字面里又长回了 [罗马字]（英文版活用表的单元格格式）", sum(
        1 for (w,) in con.execute("SELECT word FROM dict WHERE word LIKE '% [%]'")
        if _form_shape.match(w))))
    a(("F", "F9 拆出来的转写整列没了（只问在不在，不问几条）",
       0 if q("SELECT COUNT(*) FROM inflection WHERE romaji IS NOT NULL") else 1))

    # ── G 频次 ──
    from wordfreq import tokenize
    a(("G", "G1 有频次的词形不是单 token 或分词后变了样", sum(
        1 for (w,) in con.execute(
            "SELECT word FROM dict WHERE freq_zipf IS NOT NULL")
        if len(tokenize(w, "ja")) != 1 or not _same(w, tokenize(w, "ja")[0]))))
    a(("G", "G2 变形词形被写上了频次", q(
        "SELECT COUNT(*) FROM dict WHERE is_lemma=0 AND freq_zipf IS NOT NULL")))
    a(("G", "G3 词元没有频次", q(
        "SELECT COUNT(*) FROM dict WHERE is_lemma=1 AND freq_zipf IS NULL")))

    # ── S 搜索预计算（阶段 9）──
    # 🔴 预计算表会随**收词**静默陈旧：`dict` 一变，排好的 id 序列就可能不对，
    #    而查询照样返回旧顺序、不报错。⇒ 这里抽 8 个前缀**逐位**回核。
    # ⚠️ 不抽全部 63 个：指纹的全量回核在 `build_search_prefix.py --verify` 里，
    #    这道闸每次写库都跑，要便宜。抽 8 个足以逮到"收词之后没重跑"。
    try:
        from build_search_prefix import LIVE, TOPN
        pres = [r[0] for r in con.execute(
            "SELECT DISTINCT prefix FROM search_prefix ORDER BY prefix LIMIT 8")]
        mism = 0
        for pre in pres:
            cached = [r[0] for r in con.execute(
                "SELECT word_id FROM search_prefix WHERE prefix=? ORDER BY rank", (pre,))]
            live = [r[0] for r in con.execute(LIVE, (pre, pre + "￿", TOPN))]
            mism += (cached != live)
        a(("S", "S1 搜索预计算表与实时查询对不上（收词后没重跑？）", mism))
    except Exception:
        # 表还不存在（阶段 9 没跑）⇒ 不是回归，跳过。
        pass

    # ── H 录音 ──
    a(("H", "H1 常用 500 词里没有真人录音的", q(
        "SELECT COUNT(*) FROM (SELECT word FROM dict WHERE freq_zipf IS NOT NULL"
        " ORDER BY freq_zipf DESC LIMIT 500) t"
        " WHERE NOT EXISTS(SELECT 1 FROM audio a WHERE a.word=t.word)")))
    a(("H", "H2 录音的词形不在库里", q(
        "SELECT COUNT(*) FROM audio a LEFT JOIN dict d ON d.word=a.word"
        " WHERE d.id IS NULL")))
    a(("H", "H3 录音 kind 不是 human（本版不产合成音）", q(
        "SELECT COUNT(*) FROM audio WHERE kind<>'human'")))
    a(("H", "H4 录音一个可播 URL 都没有", q(
        "SELECT COUNT(*) FROM audio WHERE COALESCE(url_ogg,url_wav,url_other,url_mp3)"
        " IS NULL")))
    return C


def check_brief(db=None):
    """给 `dbtool` 挂钩用：静默跑，只回报超基线的。"""
    con = sqlite3.connect("file:%s?mode=ro" % (db or paths.DB), uri=True)
    try:
        C = build(con)
    finally:
        con.close()
    return [(g, n, f(v)) for g, n, v in C
            if v and v > ACCEPT.get(n, (0, ""))[0]]


def report(db=None, verbose=True):
    con = sqlite3.connect("file:%s?mode=ro" % (db or paths.DB), uri=True)
    try:
        C = build(con)
    finally:
        con.close()
    red, loose = [], []
    for g, name, v in C:
        exp, why = ACCEPT.get(name, (0, ""))
        if v > exp:
            red.append((g, name, v, exp, why))
        elif v < exp:
            loose.append((name, v, exp))
        if verbose:
            mark = "🔴" if v > exp else ("⬇" if v < exp else ("✅" if not v else "⚪"))
            print("   %s %-2s %-46s %10s%s"
                  % (mark, g, name[:46], f(v),
                     "  （基线 %s）" % f(exp) if exp else ""))
    if verbose:
        for g, name, v, exp, why in red:
            print("\n🔴 %s：实际 %s > 基线 %s\n   %s" % (name, f(v), f(exp), why[:200]))
        # 🔴 **低于基线也要说** —— pt 那轮 ACCEPT 按名字豁免，基线从 539 涨到 643
        #    一声没吭。锁数字的另一半是：修好了就要求把基线收紧，否则下次涨回来没人管。
        if loose:
            print("\n⬇ 比基线低，**去把基线收紧并改理由文案**（不改＝下次涨回来它不会响）：")
            for name, v, exp in loose:
                print("   %-46s %s → %s" % (name[:46], f(exp), f(v)))
        print("\n   %s（%d 条断言，%d 条带基线）"
              % ("🔴 %d 条回归" % len(red) if red else "✅ 全部在基线内",
                 len(C), sum(1 for _g, n, v in C if v and n in ACCEPT)))
    return red


# ══════════════════════════════════════════════════════════════════
# ⭐ 变异验证：把闸该逮的东西造出来，看它红不红。
# 🔴 每条都在**库的临时副本**上真的改数据，不是改断言。
def _unprotect(con):
    """把 `【】` 里的内容也一起 t2s —— **正是「保护段失效」本身**。"""
    import opencc
    cv = opencc.OpenCC("t2s").convert
    rows = [(rid, t) for rid, t in con.execute(
        "SELECT rowid, text FROM sense_gloss WHERE lang='zh' AND text LIKE '%【%'")]
    con.executemany("UPDATE sense_gloss SET text=? WHERE rowid=?",
                    [(cv(t), rid) for rid, t in rows if cv(t) != t])


MUT = [
    # ── K 汉字音訓読み层（阶段 4c）。每条变异重演一个**真实的**失效形状 ──
    ("M20", "K1 源头出了新分类标记，生成侧收了、值域没跟着改",
     ["UPDATE kanji_reading SET kind='onyomi' WHERE id IN"
      " (SELECT id FROM kanji_reading WHERE kind='on' LIMIT 4)"],
     "K1 音训读的 kind 越界"),
    ("M21", "K2 subkind 冒出 KIND 表里没有的值",
     ["UPDATE kanji_reading SET subkind='so-on' WHERE id IN"
      " (SELECT id FROM kanji_reading WHERE subkind='go-on' LIMIT 4)"],
     "K2 音训读的 subkind 越界"),
    # 🔴 M22 是这组里最重要的一条：**「顺手把连字符剥了」**。
    #    `い-きる` 的连字符标着「`生` 只读 `い`」，剥掉就等于说整个 `いきる` 都是字音。
    #    条数一条不少 ⇒ 计数型判据全绿，只有可逆性回核逮得到。
    ("M22", "🔴 K3 重跑时把送假名连字符剥了（条数不变，计数闸全绿）",
     ["UPDATE kanji_reading SET kana_stem=REPLACE(kana,'-',''), okurigana=NULL"
      " WHERE okurigana IS NOT NULL"],
     "K3 送假名拆分与生成侧对不上（可逆性回核）"),
    ("M23", "K4 细分挂到了别的大类下（音読み底下挂古訓）",
     ["UPDATE kanji_reading SET subkind='ko-kun' WHERE id IN"
      " (SELECT id FROM kanji_reading WHERE kind='on' LIMIT 3)"],
     "K4 subkind 不属于它的 kind"),
    ("M24", "🔴 K5 名乗り被并进訓読み（文件头明令不许并）",
     ["UPDATE kanji_reading SET kind='kun', subkind='nanori' WHERE kind='nanori'"],
     "K5 名乗り被并进訓読み"),
    ("M25", "K6 挂到词条目上（把「字的读音」说成「词的读音」）",
     ["UPDATE kanji_reading SET entry_id=(SELECT id FROM entry WHERE pos_raw='noun'"
      " LIMIT 1) WHERE id IN (SELECT id FROM kanji_reading LIMIT 3)"],
     "K6 音训读挂到了非 character 条目"),
    ("M26", "K7 word_id 悬空（收词重排 id 之后没重连）",
     ["UPDATE kanji_reading SET word_id=99999999 WHERE id IN"
      " (SELECT id FROM kanji_reading LIMIT 3)"],
     "K7 音训读孤儿（word_id 不在 dict）"),
    ("M27", "🔴 L1 整张 kanji_reading 表被 DROP 重建（另七条全部失去分母）",
     ["DROP TABLE kanji_reading"],
     "L1 v3 的表被 DROP 掉了"),

    ("M14", "F5 关系目标的振假名括号回潮",
     ["UPDATE sense_relation SET target='桜蔭(おういん)会(かい)' WHERE id IN"
      " (SELECT id FROM sense_relation WHERE kind='derived' LIMIT 3)"],
     "F5 关系目标还带残渣（振假名括号/英文标签/罗马字回显/冒号）"),
    ("M15", "F6 ja 版熟語又被挂成 proverb",
     ["UPDATE sense_relation SET kind='proverb' WHERE id IN"
      " (SELECT id FROM sense_relation WHERE src='ja-edition' AND kind='derived' LIMIT 5)"],
     "F6 ja 版的「熟語」又被当成谚语收进来了"),
    ("M16", "🔴 F7 把两版 proverb 一起删光（只看 F6 会显示成「修干净了」）",
     ["DELETE FROM sense_relation WHERE kind='proverb'"],
     "F7 en 版的真谚语整批没了（只问在不在，不问几条）"),
    ("M17", "F8 词形字面里又长回了 [罗马字]",
     ["UPDATE dict SET word=word||' [mut]' WHERE id IN"
      " (SELECT word_id FROM inflection WHERE romaji IS NOT NULL LIMIT 3)"],
     "F8 词形字面里又长回了 [罗马字]（英文版活用表的单元格格式）"),
    ("M18", "🔴 F9 把转写整列丢掉（只看 F8 会显示成「洗干净了」）",
     ["UPDATE inflection SET romaji=NULL"],
     "F9 拆出来的转写整列没了（只问在不在，不问几条）"),
    ("M1", "F3 同音索引页混进异表记",
     ["INSERT INTO sense_relation(word_id,sense_id,kind,target,hidden,src,src_ref)"
      " SELECT word_id,NULL,'alt_of',target||'㋿',0,'mut','mut:'||id"
      " FROM sense_relation WHERE kind='alt_of' LIMIT 5"],
     "F3 同音索引页混进了异表记"),
    ("M2", "B1 罗马字被写成汉字等级标签",
     ["UPDATE entry SET romaji='jōyō kanji', kana=NULL WHERE id IN"
      " (SELECT id FROM entry WHERE romaji IS NOT NULL LIMIT 3)"],
     "B1 罗马字其实是汉字等级标签"),
    ("M12", "A7 台湾说法回潮",
     ["UPDATE sense_gloss SET text='网路红人' WHERE lang='zh' AND rowid IN"
      " (SELECT rowid FROM sense_gloss WHERE lang='zh' LIMIT 3)"],
     "A7 已知的台湾说法回潮了（网路/影印机/资讯/义大利/计程车）"),
    ("M10", "A5 繁体回潮（模拟重跑建库步骤）",
     ["UPDATE sense_gloss SET text='國際標準書號' WHERE lang='zh' AND rowid % 15 = 0"
      " AND rowid < 3000"],
     "A5 中文释义/译文里还有繁体（抽样 1/15）"),
    ("M11", "🔴 A6 保护段失效：日文词形被一起转成简体", [_unprotect],
     "A6 日文词形（【】内）的原字被一起转成简体了"),
    ("M3", "A2 释义变成空串",
     ["UPDATE sense_gloss SET text='  ' WHERE rowid IN"
      " (SELECT rowid FROM sense_gloss LIMIT 4)"],
     "A2 释义是空串"),
    ("M4", "G2 变形词形被写上频次",
     ["UPDATE dict SET freq_zipf=3.0 WHERE is_lemma=0 AND freq_zipf IS NULL"
      " AND id IN (SELECT id FROM dict WHERE is_lemma=0 LIMIT 6)"],
     "G2 变形词形被写上了频次"),
    ("M5", "E1 例句挂到别的词的义项上",
     ["UPDATE example SET sense_id=(SELECT id FROM sense ORDER BY id LIMIT 1)"
      " WHERE id IN (SELECT id FROM example WHERE sense_id IS NOT NULL LIMIT 3)"],
     "E1 例句挂到了别的词的义项上"),
    ("M6", "L1 v3 的表被 DROP 掉",
     ["DROP TABLE collocation_gloss"],
     "L1 v3 的表被 DROP 掉了"),
    ("M7", "B5 假名词头的读音被改成别的",
     ["UPDATE entry SET kana='ちがう' WHERE id IN (SELECT e.id FROM entry e"
      " JOIN dict d ON d.id=e.word_id WHERE e.kana IS NOT NULL"
      " AND d.word GLOB '[ぁ-ゖ]*' AND d.word=e.kana LIMIT 3)"],
     "B5 假名词头的读音不等于它自己（已折字体）"),
    ("M9", "S1 预计算表与实时查询对不上（模拟收词后没重跑）",
     ["UPDATE search_prefix SET word_id=(SELECT id FROM dict LIMIT 1)"
      " WHERE rank=0 AND prefix IN (SELECT DISTINCT prefix FROM search_prefix"
      " ORDER BY prefix LIMIT 3)"],
     "S1 搜索预计算表与实时查询对不上（收词后没重跑？）"),
    ("M8", "H3 混进合成音",
     ["UPDATE audio SET kind='tts-tool' WHERE id IN (SELECT id FROM audio LIMIT 2)"],
     "H3 录音 kind 不是 human（本版不产合成音）"),
]


def mutate():
    import shutil
    import tempfile
    # 🔴🔴 **变异按名字指向断言 —— 改名就会静默拆掉变异。**
    #    2026-09-16 当场发生：我把 B5 改名成「…（已折字体）」，变异里还是旧名，
    #    于是它永远匹配不到，报「漏了」。我当时以为是变异本身写错了。
    #    ⇒ 开跑前先核一遍名字对不对得上。**一条指向不存在断言的变异不是变异。**
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    names = {n for _g, n, _v in build(con)}
    con.close()
    ghost = [(t, tgt) for t, _w, _s, tgt in MUT if tgt not in names]
    if ghost:
        print("   🔴 变异指向了不存在的断言（改名了？）：")
        for t, tgt in ghost:
            print("      %s → %r" % (t, tgt))
        return False
    ok = 0
    for tag, why, sqls, target in MUT:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d) / "t.sqlite"
            shutil.copy(paths.DB, tmp)
            con = sqlite3.connect(tmp)
            # 🔴 变异允许是**函数**，不只是 SQL。M11 第一版写成 10 条 REPLACE，
            #    只盖住库里 24 个受保护括号中的 9 个 ⇒ 剩下的让断言照样绿，报「漏了」，
            #    而**闸是好的、变异是假的**。真正的失效模式是「保护整个失效」，
            #    那件事 SQL 表达不了（要跑 opencc）⇒ 让变异能写代码。
            for s in sqls:
                if callable(s):
                    s(con)
                else:
                    con.execute(s)
            con.commit()
            con.close()
            got = any(n == target for _g, n, _v in check_brief(tmp))
        print("   %s %s（%s）" % (tag, "✅ 逮到" if got else "🔴 **漏了**", why))
        ok += got
    # 🔴 ACCEPT 锁的是**数字**不是名字 —— 单独打这件事，别删。
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d) / "t.sqlite"
        shutil.copy(paths.DB, tmp)
        con = sqlite3.connect(tmp)
        con.execute("DELETE FROM sense_gloss WHERE lang='zh' AND sense_id IN"
                    " (SELECT id FROM sense LIMIT 5000)")
        con.commit()
        con.close()
        got = any(n == "A1 义项没有中文" for _g, n, _v in check_brief(tmp))
    print("   %s %s（%s）" % ("M-ACCEPT", "✅ 逮到" if got else "🔴 **漏了**",
                            "带基线的条目涨过基线 —— 「已接受」不等于「不再看」"))
    ok += got
    n = len(MUT) + 1
    print("\n   变异 %d/%d" % (ok, n))
    return ok == n


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(0 if mutate() else 1)
    sys.exit(1 if report() else 0)
