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
import os
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
from harvest_relations import clean_targets            # noqa: E402
from harvest_examples import simplified_only          # noqa: E402
from fill_freq import _same                           # noqa: E402
from backfill_kana import PURE_KANA                   # noqa: E402
from build import norm_ja                             # noqa: E402
from intake_edition_words import SECTION              # noqa: E402
# 阶段 4c 汉字音訓読み层 —— 判据 import 生成侧那一份，闸里不重写
from build_kanji_reading import KIND as KR_KIND, split_okuri   # noqa: E402
# 阶段 2 活用表结构（2026-09-19）—— 判据 import 生成侧那一份
from infl_table import SPLIT as IT_SPLIT, column_tags as it_column_tags  # noqa: E402
from infl_table import mark_ranuki as it_mark_ranuki  # noqa: E402
sys.path.insert(0, str(HERE.parent / "fixes"))
from fix_gloss_residue import ONLY_BRACKET            # noqa: E402
# 专名分类（2026-09-18）—— 判据 import 生成侧那一份
from fix_propername_gloss import classify as pn_classify, HAS_CAT as PN_HAS_CAT  # noqa: E402

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
    "Y2 可见的关系目标是中文词（不是日语）": (
        14,      # 🔴 2026-09-19 建闸即带基线，因为**这 14 条我逐条读过、不是一类**：
                 #    11 条是真中文（`七七事变`／`黑历史`／`相岛`／`报告書`／`时计`），
                 #    **3 条其实是日语**（`唖呕` 是拡張新字体、`蓬蔂`、`兵馬倥偬` 是四字熟語）。
                 #    ⇒ 再收窄判据到 0 就会误伤那 3 条 —— 拿「错」换「错」。
        "生成侧的判据（`is_chinese_target`）看的是 dump 里有没有 `roman`/`ruby`，"
        "这 14 条**带着** roman/ruby 所以躲过了它；这里按落点查只能叠三个信号，"
        "分不开最后这一档。🔴 **要清零需要的不是更狠的判据，是逐条裁决** —— "
        "11 条该挂起、3 条该留。⚠️ 涨上去才是回归：说明清洗那两轮被撤销了，或源头又灌进来一批。"),
    "C1 变形悬空原形（base_id 为空）": (
        863,     # 🔴 2026-09-19 收紧 995 → 863：修活用表结构那轮补回了普通体各列，
                 #    新插的 4,351 个词形里有一批正好是原来悬空的原形。
                 #    **是闸自己报「⬇ 该收紧」我才来改的** —— 不改就等于默许它
                 #    下次涨回 995 而一声不吭。
                 # 🔴 2026-09-16 曾从 988 上调 7：`fixes/recover_pointer_senses.py` 从
                 #    英文版指针正文里补了 375 条活用（`見た` ← `見る 过去`），
                 #    其中 7 条的原形连三版都没有独立条目。
        "863 / 573,105 ＝ 0.15%。`base` 文本都在，只是原形词头连三版都没有独立条目。"
        "🔴 阶段 2 建完变形层时这个数是 **221,135**，阶段 3a 收词后重连了 220,147 行。"
        "**pt 正是栽在这个顺序上**（变形层建在收词之前 ⇒ 46.2% 空白页）。"
        "⚠️ 展示层查变形**必须走 `inflection.word_id`，别走 `base_id`**。"),
    "C3 空白页词形（无义项、无变形、无指针）": (
        9_763,   # 🔴 2026-09-19 三次收紧 9,765 → 9,763（修活用表结构，普通体各列回来了）。
                 # 🔴 2026-09-16 二次收紧 12,206 → 9,765：`recover_pointer_senses.py`
                 #    把英文版指针正文里的 3,812 条关系 + 375 条活用落了库。
                 #    **是闸自己报「⬇ 该收紧」我才来改的** —— 不改就等于
                 #    默许它下次涨回 12,206 而一声不吭。
        "9,763 / 714,173 ＝ 1.37%（对照 pt 那轮 46.2%、fr 1.8%）。"
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

    # ── A8 专名义项的中文必须带分类（2026-09-18）──
    # 🔴 用户看 `桜` 的页面发现的：rank 9/10/11 英文分别是 `a female given name`／
    #    `a placename`／`a surname`，**中文全印「樱」** —— 三件不同的事长得一模一样。
    #    修的时候是 10,496 条。判据 `classify` import 生成侧那一份，
    #    源头将来多一种模板（`a nickname`…）它会跟着变。
    # ⚠️ 基线 1 是 `下の名前`：那个词的**词义本身**就是「名（相对于姓）」，
    #    英文的 `given name` 在那条上是释义不是分类标记 ⇒ **有意不改**。
    #    ⚠️ 它的中文含「名」，所以其实不会落进这条断言 —— 基线写 0。
    a(("A", "A8 专名义项的中文丢了分类（女性名/姓氏/地名分不出）", sum(
        1 for en, zh in con.execute(
            "SELECT ge.text, gz.text FROM sense s"
            " JOIN sense_gloss ge ON ge.sense_id=s.id AND ge.lang='en' AND ge.kind<>'umbrella'"
            " JOIN sense_gloss gz ON gz.sense_id=s.id AND gz.lang='zh' AND gz.kind<>'umbrella'"
            " WHERE ge.text LIKE '%name%'")
        if pn_classify(en) and not PN_HAS_CAT.search(zh))))

    # ── J 证据层→出版层的认领（2026-09-18 回填 ja/zh 两版）──
    # 🔴 **J1 是这一族里唯一非计数的那条**：悬空引用 = 认领指向一条已经被删掉的义项。
    #    回填 ja/zh 时的写后回核逮到全库有 1 条（en-edition 的历史遗留，
    #    `kk-ja:和:character:2:0#0`，文本是 wikitext 残渣）—— 它躺了整整一个项目，
    #    因为**此前没有任何一条断言问过「认领指向的义项还在不在」**。
    #    义项清洗（`fix_gloss_residue` 那类）会删 `sense`，删了不清引用就又是一条。
    a(("J", "J1 认领指向已删除的义项（悬空引用）", q(
        "SELECT COUNT(*) FROM sense_src x LEFT JOIN sense s ON s.id=x.sense_id"
        " WHERE x.sense_id IS NOT NULL AND s.id IS NULL")))
    # 🔴 J2 是**错配**那一面：认领得上不代表配对对（`[[primary-key-is-not-enough]]`）。
    #    证据行与它认领的义项必须属于同一个词形 —— 跨词认领是灾难性的错配。
    a(("J", "J2 认领到了别的词的义项", q(
        "SELECT COUNT(*) FROM sense_src x JOIN sense s ON s.id=x.sense_id"
        " WHERE s.word_id <> x.word_id")))
    # ⚠️ J3 锁的是**这一层没有整批消失**。ja/zh 回填之前这两版全是 NULL，
    #    那种状态下 J1/J2 恒为 0 —— 两条都绿，而桥根本不存在。
    a(("J", "J3 ja/zh 两版的认领整批没了（只问在不在，不问几条）", q(
        "SELECT COUNT(*)=0 FROM sense_src WHERE src IN ('ja-edition','zh-edition')"
        " AND sense_id IS NOT NULL")))

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

    # ── I 活用表的**表结构**（2026-09-19）──
    # 🔴 起因：用户拿 `食べる` 的成品页去外审，模型挑出「`食べましょう` 不是敬体命令形」。
    #    回源查下来不是孤例，是 wiktextract 解析维基 `ja-conj` 模板时**行列两个方向的
    #    表头识别失败**，我们扁平遍历 `forms` 看不见表，把源头的错原样印上了页面。
    #    判据与验证见 `pipeline/infl_table` 文件头；这里的断言全部 import 那一份。
    # 🔴 `tags` 解析不了时**返回哨兵而不是抛异常** —— 闸崩掉等于这一整族断言
    #    一条都没跑，而调用方只看见一个堆栈。M27（DROP TABLE 让闸崩掉、L1 没机会报）
    #    是同一个形状，这里提前把它堵上：坏的 tags 由 I0 报出来。
    def _tags(x):
        try:
            return json.loads(x or "[]")
        except ValueError:
            return None
    infl = [(w, b, lab, _tags(tg), ref) for w, b, lab, tg, ref in con.execute(
        "SELECT d.word, i.base, i.label_zh, i.tags, i.src_ref"
        " FROM inflection i JOIN dict d ON d.id=i.word_id")]
    a(("I", "I0 inflection.tags 不是合法 JSON", sum(1 for x in infl if x[3] is None)))
    infl = [x for x in infl if x[3] is not None]
    # 🔴 **现代活用表那批**单列出来：`it_column_tags` 是只在这张表的格子上验过的
    #    （3,748 个格子，唯一分歧就是源头丢的 `past`）。把它用到全表会误伤 ——
    #    第一版 I2 就是全表跑的，报出 767 条，其中 645 条根本不是活用表的行：
    #    `きたなかった`（形容词过去）撞上后缀 `なかった` 被读成「否定过去」、
    #    `明らかだ` 的だ被读成「过去」。**判据只在它被验过的域里有效**
    #    （`[[criteria-narrower-than-you-think]]`）。
    modern = [x for x in infl if ":ja-conj-ex#" in x[4]]

    # 🔴 I1 是这一族里最该有的一条：修之前 `desiderative` 这个 tag 在库里的
    #    **真阳性是 0** —— 480 行全是进行体（`食べています` 印成「愿望敬体」），
    #    而真正的愿望形（`食べたい`）带着源头的报错标记被整行丢掉了。
    #    判据 import 生成侧的「什么才算愿望形」，源头哪天改了它跟着改。
    a(("I", "I1 印着「愿望」的其实是进行体", sum(
        1 for w, _b, _l, tg, _r in infl
        if "desiderative" in tg and not IT_SPLIT["desiderative"][0](w))))

    # 🔴 I2 逮的是**读者在页面上看见两行印着同一个说明**：修之前 `食べます` 与
    #    `食べました` 的 tag 集完全相同（源头丢了 `past` 这一维），108 个词无一幸免。
    #    ⚠️ 判据不能是「同一原形下有重名的说明」—— `書け`／`かけ` 是同一个形的
    #    汉字与假名两种写法，本来就该同名（页面用 ／ 合并）。真判据是
    #    **说明相同但形态上并不相同**：拿生成侧的列读取器重算，不一致就是没区分开。
    seen = {}
    dupe = 0
    for w, b, lab, _tg, _r in modern:
        k = (b, lab)
        c0 = frozenset(it_column_tags(w))
        if k in seen and seen[k] != c0:
            dupe += 1
        seen.setdefault(k, c0)
    a(("I", "I2 同一原形下两个形态不同的词形印着同一个说明", dupe))

    # ⚠️ I3/I4 锁的是**这两层没有整批消失**（只问在不在，不问几条 —— 同 J3）。
    #    修之前普通体那几列是 0 行，那种状态下 I1/I2 也能全绿。
    a(("I", "I3 现代活用表的普通体整批没了（`食べない` 那几列）", q(
        "SELECT COUNT(*)=0 FROM inflection"
        " WHERE src_ref LIKE '%:ja-conj-ex#%' AND tags='[\"negative\"]'")))
    a(("I", "I4 文語形的 `bungo` 标记整批没了（又混进现代活用里印）", q(
        "SELECT COUNT(*)=0 FROM inflection"
        " WHERE src_ref LIKE '%:ja-conj-bungo#%' AND tags LIKE '%bungo%'")))
    # 🔴 I5：文語表里**已然形+ば**（`食ぶれば`，順接確定条件）被源头标成了 `causative`，
    #    页面上印「使役」。同一块里有已然形词干可以把它和未然形+ば 分开。
    a(("I", "I5 文語的「～ば」又被印成使役", sum(
        1 for w, _b, _l, tg, r in infl
        if "causative" in tg and "bungo" in tg and w.endswith("ば"))))
    # 🔴 I6 是**可逆性回核**，不是另写一遍判据：把库里的 tag 集抹掉 `ra-nuki`
    #    重跑生成侧的 `mark_ranuki`，标出来的必须和库里的**逐条一致**。
    #    ⚠️ 第一版我在闸里按记忆重写了一遍判据（「同原形下有られ对照」），
    #    生成侧收窄成派生关系之后它就开始误报 16 条 —— 本文件头那条
    #    「判据一律 import 生成侧、绝不在闸里重写」，我自己违反了一次。
    #    `食べれる` 与 `食べられる` 并列印着，不标出来读者会当成两套都规范的可能形。
    redo = [(w, b, {x for x in tg if x != "ra-nuki"}) for w, b, _l, tg, _r in infl]
    it_mark_ranuki(redo)
    a(("I", "I6 ら抜き标注与生成侧对不上（可逆性回核）", sum(
        1 for (w, b, again), (_w, _b, _l, tg, _r) in zip(redo, infl)
        if ("ra-nuki" in again) != ("ra-nuki" in tg))))
    # 🔴 I7：`src_ref` 是这张表与 dump 之间唯一的认领凭据，原来的格式少了
    #    「同 (词,词性) 的第几条」，5,155 组撞在一起（`[[primary-key-is-not-enough]]`）。
    a(("I", "I7 src_ref 不唯一（认领凭据撞车）", q(
        "SELECT COUNT(*) FROM (SELECT src_ref FROM inflection"
        " GROUP BY src_ref HAVING COUNT(*)>1)")))

    # ── X 核心词等级（2026-09-19）──
    # 🔴🔴 这一列**不是权威难度，是内部尺子**：JLPT 官方自 2010 年改制后不再公布
    #    词汇表，我们用的是民间重建的 Waller 表（CC BY），整理者自己写着
    #    「essentially an educated guess」。见 `data/refs/jlpt-waller/README.md`。
    a(("X", "X1 core_level 越界（只许 1–5，1=N5）", q(
        "SELECT COUNT(*) FROM dict WHERE core_level IS NOT NULL"
        " AND core_level NOT BETWEEN 1 AND 5")))
    a(("X", "X2 有等级却没记出处（CC BY 的溯源断了）", q(
        "SELECT COUNT(*) FROM dict WHERE core_level IS NOT NULL"
        " AND (core_src IS NULL OR core_src='')")))
    # 🔴🔴 X3 是这一族里最要紧的一条，而且它**不查数据、查源码**：
    #    「不上页面」是个决定，决定必须有东西替它站岗，否则哪天有人接上去没人会知道。
    #    ⚠️ 判据是「展示层源码里不许出现这两个列名」—— 真接上去了必然要写列名。
    #    改主意（决定要印）时**先改这条断言**，那一步就是在逼自己重读上面那段警告。
    # ⚠️ 这个环境变量是**给变异用的唯一口子**，而且**读一次就自清**（`pop`）——
    #    否则它会渗到后面每一条变异里，把别的断言一起染红。
    ovr = os.environ.pop("JA_X3_SRC_OVERRIDE", "")
    src_files = ([Path(x) for x in ovr.split(",") if x] if ovr else
                 [HERE.parent.parent / "packages/dict-core/src/japanese.ts",
                  HERE.parent.parent / "apps/web/src/App.tsx"])
    a(("X", "X3 核心词等级被接进了展示层（它是内部尺子，不是可印的难度标签）", sum(
        1 for f in src_files if f.exists()
        and ("core_level" in f.read_text(encoding="utf-8")
             or "core_src" in f.read_text(encoding="utf-8")))))
    # ⚠️ X4 只问在不在，不问几条（同 J3）：这一列整批被清空时 X1/X2 恒为 0。
    a(("X", "X4 核心词等级整批没了（只问在不在）", q(
        "SELECT COUNT(*)=0 FROM dict WHERE core_level IS NOT NULL")))

    # ── X5 规划器的统计信息（2026-09-20）──
    # 🔴🔴 **阶段 9 的头号性能修复是手敲跑的一次 `ANALYZE`，没做成步骤。**
    #    于是整个仓库里 `ANALYZE` 只出现在一句注释里，没有任何代码会执行它 ——
    #    加完词源层一查：`sqlite_stat1` 里 dict 写着 710,264（实际 714,173）、
    #    `sense_relation` 差 -5,316、**`etymology` 整张表压根没有统计信息**。
    #    ⚠️ 而阶段 9 的账查的是「`sqlite_stat1` **存不存在**」—— 对**陈旧**结构性失明
    #    （`[[fix-regression-and-gate]]`：行数型判据挡不住"东西在但是坏的"）。
    # 🔴 判据 **import 生成侧那一份**（`run_analyze.survey`），不在这儿另写一遍口径 ——
    #    否则两边会漂移，正是阶段 7 定下的规矩。
    # ⚠️ 容忍 0.5%：统计信息本来就是抽样估算，要求逐字相等会因为一次小写库就假红。
    # 🔴 **名字必须是静态的**：变异按名字指向断言，名字里拼进表名就等于每次跑
    #    都换一个名字 ⇒ 变异全变成「指向不存在的断言」而被静默跳过
    #    （`mutate()` 开头那段 ghost 检查就是为这个写的，我差点当场触发它）。
    from run_analyze import survey as _survey          # noqa: PLC0415
    _stale = [t for t, real, st in _survey(con)
              if st is None or abs(real - st) * 200 > real]
    a(("X", "X5 规划器的统计信息比库陈了（建表/收词之后没重跑 ANALYZE）", len(_stale)))

    # ── Y 关系目标的成词性（2026-09-19，欠账 15/16）──
    # 🔴 Y1 是**可逆性回核**，不是另写一遍判据：把库里每个**可见**目标重跑生成侧的
    #    `clean_targets()`，必须原样返回自己。这一条同时守住三件事 ——
    #    含空格的没了、罗马字回显剥干净了、并列表拆开了。
    #    ⚠️ 它逮到过我自己引入的 bug：并列表规则一度把顿号也当分隔符，
    #    于是 `井の中の蛙、大海を知らず` 会被拆成两条 —— **50 多条谚语**。
    a(("Y", "Y1 可见的关系目标重跑生成侧判据会变（含空格/罗马字回显/并列表没拆）", sum(
        1 for (t,) in con.execute(
            "SELECT DISTINCT target FROM sense_relation WHERE hidden=0 AND target IS NOT NULL")
        if clean_targets(t) != [t])))
    # 🔴 Y2 查的是**中文词印在日语页上**。判据只能按落点查（生成侧那条要看 dump 里的
    #    `roman`/`ruby`，这里没有）⇒ 三个信号叠加：来自中/日版 ＋ 含简体专用字 ＋ 自己不是词条。
    #    ⚠️ **英文版不算**：那批 `呕唖`/`丰容` 是拡張新字体不是中文（我误判过一次）。
    simp = simplified_only(con)
    a(("Y", "Y2 可见的关系目标是中文词（不是日语）", sum(
        1 for t, src in con.execute(
            "SELECT r.target, r.src FROM sense_relation r WHERE r.hidden=0"
            " AND r.src IN ('zh-edition','ja-edition')"
            " AND NOT EXISTS(SELECT 1 FROM dict d WHERE d.word=r.target)")
        if any(ch in simp for ch in (t or "")))))
    # ⚠️ Y3 只问在不在（同 J3）：这两轮清洗整批回滚时 Y1/Y2 恒为 0。
    a(("Y", "Y3 被挂起的关系整批没了（清洗回滚了）", q(
        "SELECT COUNT(*)=0 FROM sense_relation WHERE hidden=1")))

    # ── Z 词源层（2026-09-20）──
    # 🔴🔴 这一层**整个缺席过**：`scripts/ingest_etymology.py` 2026-09-14 就有，
    #    ja 09-15 开建却没被加进它的语种名单，库里连 `etymology` 表都没有，
    #    而阶段表全 ✅、三道闸全绿 —— **「阶段表说完成」对没列进阶段表的层结构性失明。**
    #    是收尾整理文档时逐个点名核对六门共有的层才看见的。
    a(("Z", "Z1 etymology 表整批没了（只问在不在）", q(
        "SELECT COUNT(*)=0 FROM etymology")))
    a(("Z", "Z2 词源行的 word_id 悬空", q(
        "SELECT COUNT(*) FROM etymology e LEFT JOIN dict d ON d.id=e.word_id"
        " WHERE d.id IS NULL")))
    # 🔴🔴 Z3 查的是**拼接点**，不是任何一侧。我刚栽在这儿：
    #    展示层的 etymKey 取裸词源号（`1`），而 `etymology.edition` 写的是 `en-edition`
    #    ⇒ 键是 `en-edition:1`，两边**各自自洽、拼起来对不上**，
    #    入库对齐闸全绿、写后回核全绿、tsc 全绿，**而页面上一条词源都印不出来且一声不吭**
    #    （`[[correct-steps-can-compose-a-hole]]`：每步都对、跨步假设失效＝谁都没负责的洞）。
    #    ⇒ 判据必须是「词源行能不能被义项那一侧的键找到」。
    a(("Z", "Z3 词源正文与义项对不上（键拼起来查不到，页面静默空白）", q(
        "SELECT COUNT(*) FROM etymology e WHERE NOT EXISTS("
        "  SELECT 1 FROM sense s JOIN entry en ON en.id=s.entry_id"
        "   WHERE s.word_id=e.word_id AND en.src=e.edition AND en.etym_no=e.etym_no)")))

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
def _wire_core_level(con):
    """模拟「有人把 `core_level` 接进了展示层」。

    🔴 X3 查的是**源码**不是数据，所以这条变异不动库，而是把 X3 的扫描目标
       临时指向一个确实写着 `core_level` 的文件（生成侧那个脚本本身）。
       口子读一次就自清，不会渗到后面的变异。
    """
    os.environ["JA_X3_SRC_OVERRIDE"] = str(HERE.parent / "pipeline" / "intake_core_level.py")


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

    ("M31", "🔴 A8 专名义项的中文被压回只剩译名（用户在 `桜` 页上看见的那个）",
     ["UPDATE sense_gloss SET text=REPLACE(REPLACE(REPLACE(text,'（女性名）',''),"
      "'（姓氏）',''),'（地名）','') WHERE lang='zh' AND (text LIKE '%（女性名）'"
      " OR text LIKE '%（姓氏）' OR text LIKE '%（地名）')"],
     "A8 专名义项的中文丢了分类（女性名/姓氏/地名分不出）"),
    ("M28", "🔴 J1 清洗删掉义项、认领引用没跟着清（悬空）",
     ["DELETE FROM sense WHERE id IN (SELECT sense_id FROM sense_src"
      " WHERE sense_id IS NOT NULL LIMIT 3)"],
     "J1 认领指向已删除的义项（悬空引用）"),
    ("M29", "🔴 J2 认领错配到别的词（计数型闸对此结构性失明）",
     ["UPDATE sense_src SET sense_id=(SELECT id FROM sense WHERE word_id<>sense_src.word_id"
      " LIMIT 1) WHERE id IN (SELECT id FROM sense_src WHERE sense_id IS NOT NULL LIMIT 3)"],
     "J2 认领到了别的词的义项"),
    ("M30", "🔴 J3 ja/zh 的认领整批被清回 NULL（回到回填之前，J1/J2 恒绿）",
     ["UPDATE sense_src SET sense_id=NULL WHERE src IN ('ja-edition','zh-edition')"],
     "J3 ja/zh 两版的认领整批没了（只问在不在，不问几条）"),
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
    # ── 活用表结构（2026-09-19）。每一条都对应一个**真发生过**的症状 ──
    # ⚠️ I0 本身就是**从一次崩溃里长出来的**：M35 第一版的 REPLACE 留下了 `["adverbial", ]`，
    #    闸直接抛 JSONDecodeError —— 整族断言一条都没跑，调用方只看见一个堆栈。
    #    这条变异锁住「坏数据要报红，不要崩」。
    # ── 统计信息陈旧（2026-09-20）──
    # 🔴 变异**删掉 `etymology` 的统计行** —— 这正是 9-20 的真现场：建了新表、没重跑
    #    `ANALYZE`，于是规划器对这张表一无所知。删一行比改数字更贴近真实失效方式
    #    （新表根本不会**有**统计行，而不是有一个错的）。
    ("M50", "🔴🔴 X5 新建的表没有统计信息（阶段 9 的 ANALYZE 是手敲的、没做成步骤）",
     ["DELETE FROM sqlite_stat1 WHERE tbl='etymology'"],
     "X5 规划器的统计信息比库陈了（建表/收词之后没重跑 ANALYZE）"),
    # ── 核心词等级（2026-09-19）──
    ("M40", "X1 core_level 冒出值域外的级别",
     ["UPDATE dict SET core_level=6 WHERE id IN"
      " (SELECT id FROM dict WHERE core_level=1 LIMIT 4)"],
     "X1 core_level 越界（只许 1–5，1=N5）"),
    ("M41", "X2 出处被抹掉（CC BY 的溯源断了）",
     ["UPDATE dict SET core_src=NULL WHERE core_level IS NOT NULL"],
     "X2 有等级却没记出处（CC BY 的溯源断了）"),
    ("M42", "🔴 X3 有人把核心词等级接进了展示层（源码里出现了列名）",
     [_wire_core_level],
     "X3 核心词等级被接进了展示层（它是内部尺子，不是可印的难度标签）"),
    ("M43", "🔴 X4 这一列整批被清空（X1/X2 那时恒为 0）",
     ["UPDATE dict SET core_level=NULL, core_src=NULL"],
     "X4 核心词等级整批没了（只问在不在）"),
    # ── 词源层（2026-09-20）──
    ("M47", "🔴 Z1 词源层整批没了（这一层曾经根本不存在，而所有闸全绿）",
     ["DELETE FROM etymology"],
     "Z1 etymology 表整批没了（只问在不在）"),
    ("M48", "Z2 词源行指向不存在的词",
     # ⚠️ 只改一行：`UNIQUE(word_id, edition, etym_no)` 下把多行改成同一个 word_id 会撞键
     ["UPDATE etymology SET word_id=-1 WHERE id=(SELECT MIN(id) FROM etymology)"],
     "Z2 词源行的 word_id 悬空"),
    ("M49", "🔴🔴 Z3 键的两侧各自改一个字（各自自洽、拼起来对不上、页面静默空白）",
     ["UPDATE etymology SET edition='kk-ja' WHERE edition='en-edition'"],
     "Z3 词源正文与义项对不上（键拼起来查不到，页面静默空白）"),
    # ── 关系目标的成词性（2026-09-19，欠账 15/16）──
    ("M44", "🔴 Y1 关系目标里又长回了空格（罗马字回显/并列表没拆）",
     ["UPDATE sense_relation SET target=target||' (mut)' WHERE id IN"
      " (SELECT id FROM sense_relation WHERE hidden=0 LIMIT 3)"],
     "Y1 可见的关系目标重跑生成侧判据会变（含空格/罗马字回显/并列表没拆）"),
    ("M45", "🔴 Y2 中文词又露到页面上（清洗被撤销）",
     ["UPDATE sense_relation SET hidden=0 WHERE hidden=1"
      " AND src IN ('zh-edition','ja-edition')"],
     "Y2 可见的关系目标是中文词（不是日语）"),
    ("M46", "🔴 Y3 两轮清洗整批回滚（那时 Y1/Y2 里的行全都变回可见）",
     ["UPDATE sense_relation SET hidden=0"],
     "Y3 被挂起的关系整批没了（清洗回滚了）"),
    ("M39", "🔴 I0 tags 变成非法 JSON（闸要报红，不许崩掉整族断言）",
     ["UPDATE inflection SET tags='[\"adverbial\", ]' WHERE id IN"
      " (SELECT id FROM inflection ORDER BY id LIMIT 3)"],
     "I0 inflection.tags 不是合法 JSON"),
    ("M32", "🔴 I1 进行体又被标回 desiderative（`食べています` 印「愿望敬体」）",
     ["UPDATE inflection SET tags=REPLACE(tags,'progressive','desiderative'),"
      " label_zh=REPLACE(label_zh,'进行体','愿望') WHERE tags LIKE '%progressive%'"],
     "I1 印着「愿望」的其实是进行体"),
    ("M33", "🔴 I2 列方向又丢了 past（`食べます` 与 `食べました` 同印「敬体」）",
     ["UPDATE inflection SET label_zh='敬体' WHERE label_zh='敬体过去'"],
     "I2 同一原形下两个形态不同的词形印着同一个说明"),
    ("M34", "🔴 I3 普通体那几列又被当成源头报错整行丢掉",
     ["DELETE FROM inflection WHERE src_ref LIKE '%:ja-conj-ex#%'"
      " AND tags='[\"negative\"]'"],
     "I3 现代活用表的普通体整批没了（`食べない` 那几列）"),
    # ⚠️ 三个 REPLACE 缺一不可：tags 是排序后的 JSON 数组，`bungo` 可能在头、
    #    在尾、或独占一条（`["adverbial", "bungo"]` 里它在尾）。第一版只写了
    #    「在头」和「独占」，尾部那种留下 `["adverbial", ]` —— **非法 JSON，闸直接崩**
    #    而不是报红。变异本身也要能跑通，否则它测不出任何东西。
    ("M35", "🔴 I4 文語表的分隔符又被丢掉（文語形混进现代活用里印）",
     ["UPDATE inflection SET tags=REPLACE(REPLACE(REPLACE(tags,', \"bungo\"',''),"
      "'\"bungo\", ',''),'\"bungo\"','') WHERE tags LIKE '%bungo%'"],
     "I4 文語形的 `bungo` 标记整批没了（又混进现代活用里印）"),
    ("M36", "I5 文語的已然形+ば 又被印成使役",
     ["UPDATE inflection SET tags='[\"bungo\", \"causative\"]', label_zh='文語使役'"
      " WHERE src_ref LIKE '%:ja-conj-bungo#%' AND label_zh='文語已然形条件形'"],
     "I5 文語的「～ば」又被印成使役"),
    ("M37", "I6 ら抜き标注被整批抹掉（与规范可能形并列印着）",
     ["UPDATE inflection SET tags=REPLACE(REPLACE(tags,', \"ra-nuki\"',''),"
      "'\"ra-nuki\", ','') WHERE tags LIKE '%ra-nuki%'"],
     "I6 ら抜き标注与生成侧对不上（可逆性回核）"),
    ("M38", "🔴 I7 src_ref 又撞车（认领凭据不唯一，删旧行时会误伤别的条目）",
     ["UPDATE inflection SET src_ref=(SELECT src_ref FROM inflection ORDER BY id LIMIT 1)"
      " WHERE id=(SELECT id FROM inflection ORDER BY id LIMIT 1 OFFSET 1)"],
     "I7 src_ref 不唯一（认领凭据撞车）"),
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
