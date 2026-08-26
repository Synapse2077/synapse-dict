#!/usr/bin/env python3
"""回归闸：**过去每一个修复，现在还在不在**。fr 版，2026-08-26（阶段 7）。

═══ 为什么必须有这个 ═══
用户 2026-08-11（es 上）：「同一个问题你修了，隔天修其他问题，你又发现之前的问题
又出现了。这才是我抱怨的。这也才是导致无穷无尽的根本原因。」

修复消失有**三种**机制，后两种极隐蔽：

  ❌ **被抹掉**：修复写在某张表上，而某个 build 脚本 DROP 重建 ⇒ 修复没了。
  ⚠️ **被绕过（换读取路径）**：数据还在、查那一列一切正常，
     但展示层改读别的地方了。**只查修复写入的那一列，永远发现不了。**
  ⚠️ **被绕过（A 层搬到 B 层）** —— fr 2026-08-25 亲身撞到：
     四个清洗脚本全改 `sense_gloss`，而裁决是把 `sense_src` 的文本**搬进来** ⇒
     4,049 条脚注残渣原样搬回。**当时四道闸没一道看得见**，是打样时肉眼发现的。
     ⇒ 本闸对每条文本判据**同时查证据层 `sense_src` 和出版层 `sense_gloss`**。

🔴🔴 **fr 现在处在「被绕过」的最大值上**：`packages/dict-core/src/french.ts` 只有 299 行，
   还在读老扁平列 `dict.ipa / dict.translation / dict.definition`，
   v3 那套表（sense / sense_gloss / pronunciation / example）**一张都没接**。
   ⇒ 阶段 1.5–5 做的东西，用户现在一个字都看不到。
   本闸的 **L 组**专门盯这笔「阶段 8 债务」：它现在是**故意红的**，
   阶段 8 切完读取路径才该变绿。**别为了让闸好看去调它的基线。**

═══ 判据从哪来 ═══
**直接 import 各修复脚本自己的判据**（正则/函数原样拿来用），不另写一套。
`[[fix-regression-and-gate]]` 第三种机制：**闸与它守的那段逻辑用两个不同判据 ⇒
闸在报自己的 bug**（fr 2026-08-25 一天撞两次：音标闸⑤查的是我已废掉的形式判据，
报 1,085 条假红）。**判据只许一份。**

═══ 怎么用 ═══
    python3 tests/test_no_regression.py            # 出清单
    python3 tests/test_no_regression.py --trace    # 逐条计时（卡住时看是哪条）
    python3 tests/test_no_regression.py --mutate   # 变异验证：闸本身是不是恒真的

🔴 **每加一个修复脚本，必须在 CHECKS 里加一行。** 没有断言的修复 ＝ 下一次静默回归。
🔴 **每条非零都必须在 ACCEPT 里带理由。** 没有基线的闸永远是红的，久了没人看。
   调高任何一个基线都要写清为什么 —— 否则这就成了掩盖回归的开关。
"""
import argparse
import shutil
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "fixes"))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import paths                                              # noqa: E402
# ⭐ 判据一律 import 生成/修复侧那一份，**不另抄**
import strip_citation_tails as _cit                       # noqa: E402
import strip_editorial_residue as _res                    # noqa: E402
import strip_footnote_refs as _foot                       # noqa: E402
import tidy_gloss_punctuation as _tidy                    # noqa: E402
import build_pronunciation_layer as _pron                 # noqa: E402
from intake_fr_words import norm_apos                     # noqa: E402

f = lambda n: format(n, ",")

# ══════════════════════════════════════════════════════════════════════════
#  两条取数路径：**修复写在哪** vs **它会被从哪读走**
#  🔴 fr 的特殊之处：清洗做在出版层 `sense_gloss`，而**证据层 `sense_src` 没洗**，
#     裁决/推广脚本会把证据层的文本搬进出版层 ⇒ 证据层必须一起查。
# ══════════════════════════════════════════════════════════════════════════
FR_PUB = ("SELECT g.text FROM sense s JOIN sense_gloss g ON g.sense_id=s.id "
          "AND g.lang='fr' WHERE COALESCE(s.hidden,0)=0")
FR_EVI = "SELECT text FROM sense_src"          # ← 会被搬进出版层的那一侧
ZH_PUB = ("SELECT g.text FROM sense s JOIN sense_gloss g ON g.sense_id=s.id "
          "AND g.lang='zh' WHERE COALESCE(s.hidden,0)=0")
ZH_ALL = "SELECT text FROM sense_gloss WHERE lang='zh'"
# 音标：写在 `pronunciation`，展示层（阶段 8 后）读 is_primary 那条
IPA_ALL = "SELECT ipa FROM pronunciation"
IPA_PRIM = "SELECT ipa FROM pronunciation WHERE is_primary=1"
# 例句
EX_ALL = "SELECT text FROM example"
EX_VIS = ("SELECT e.text FROM example e JOIN sense s ON s.id=e.sense_id "
          "WHERE COALESCE(s.hidden,0)=0")
EXZH_ALL = "SELECT text FROM example_gloss WHERE lang='zh'"
EXZH_VIS = ("SELECT g.text FROM example_gloss g JOIN example e ON e.id=g.example_id "
            "JOIN sense s ON s.id=e.sense_id WHERE g.lang='zh' AND COALESCE(s.hidden,0)=0")


def texts(con, sql):
    return [t for (t,) in con.execute(sql) if t]


# ══════════════════════════════════════════════════════════════════════════
#  🔴 已接受基线 —— 每一条都是**已经裁决过、决定不修**的残留，附理由
# ══════════════════════════════════════════════════════════════════════════
ACCEPT = {
    # ── B 组：证据层**有意不洗** ────────────────────────────────────────
    # 🔴 `sense_src` 存的是**逐字原文**（`[[two-layer-sense-model]]`），洗它会让
    #    外锚闸 `verify_vs_dump.py` 对不上 dump。清洗的正确位置是**推广那一步**
    #    （`pipeline/gloss_clean.py`）。所以证据侧非零是**设计**，不是回归。
    #    ⚠️ 但出版侧必须是 0 —— 那才是用户看得见的地方。
    #    基线在首次建闸时实测填入，**涨了就说明推广时漏洗了**。
    "B1:evi": None, "B2:evi": None, "B3:evi": None, "B4:evi": None,
    "B5:evi": None, "B6:evi": None,
    "B1:bypass": "ok", "B2:bypass": "ok", "B3:bypass": "ok", "B4:bypass": "ok",
    "B5:bypass": "ok", "B6:bypass": "ok",

    # 📋 B6 出版侧剩 2 条是**有意留的**（`fixes/fix_gate_reds.py` 的 B6_PLAN keep 名单）：
    #    érasure          —— 定义在讲方括号这个符号本身，`[[abc]]` 是它举的例子
    #    rouge de méthyle —— `2-[[4-…)phenyl]diazenyl]benzoique` 是化学命名法
    #    ⚠️ 这两条**盲扫会改坏**。数字涨了说明来了新的、没判过的。
    "B6:pub": 2,
    # ── C 组 ─────────────────────────────────────────────────────────
    # 📋 C1 收窄后剩 20 条：`D6`→`D6`、`LaTeX`→`LaTeX`、`DNSSEC`→`DNSSEC`
    #    —— 型号、软件名、协议缩写的中文**就是原文**，判定为正确，不修。
    #    ⚠️ 数字**涨了**说明来了新的、没判过的。
    "C1:all": 20, "C1:vis": 20,
    # 📋 C2 剩 2 条是**假红**：`sic` 和 `en français dans le texte` 的中文
    #    **就是**「原文如此」—— 判据逮到了词头自己的含义，不是元话语泄漏。
    #    ⚠️ 涨了说明来了真的元话语。
    "C2:all": 2, "C2:vis": 2,
    # 📋 C3 收窄后剩 2 条：`gérondif`→「（法语）副动词」、
    #    `français langue commune`→「魁北克唯一通用语言（法语）」
    #    —— 这两条里「（法语）」是**释义本身需要的限定**，不是泄漏。判定不修。
    "C3:all": 2, "C3:vis": 2,

    # ── E 组：例句 ────────────────────────────────────────────────────
    # 📋 E2 收窄后 281 条：`e^π≈23,14069263`、`demain → 2main`（短信体）、
    #    `g 1 prob, viens stp!`（火星文）—— 本来就没有可翻的东西。2026-08-26 判定不修。
    "E2:all": 281, "E2:vis": 281,

    # ── F 组：stage-2a 遗留（`docs/FR_PLAN.md` 已记账）────────────────
    # 📋 F2 1,037 条证据行指向隐藏义项：隐藏是**可逆**的（写 hidden 不删行），
    #    证据保留是有意的。读取侧必须 0 —— 那才是用户看得见的地方。
    #    2026-08-26 由 1,037 调到 1,052：`fixes/fix_gate_reds.py` 隐掉了 15 条
    #    「释义只剩 … 且无中文」的义项，它们的证据行随之指向隐藏义项。
    #    ⚠️ 这是**我自己那次修复的已知后果**，不是回归 —— 调基线必须像这样写清来源。
    "F2:all": 1052,
    # 📋 F3 622 条可见义项 pos 为空：stage-2a 建表时的遗留，已记账。
    #    ⚠️ 这条**没修**是因为规模小且不影响展示（pos 空就不显示词性徽标）。
    "F3:all": 622, "F3:vis": 622,

    # ── E 组：例句 ────────────────────────────────────────────────────
    # 📋 456 行（0.06%）根本不是例句，全来自英文版：451 条同义词标注行
    #    （`Near-synonym: abandon`）、2 条 `(Can we date this quote?)`、
    #    3 条 `(please add an English translation…)`。
    #    2026-08-26 判定：规模太小、且是**源头内容**不是我们弄坏的，归阶段 8 展示时过滤。
    "E1:all": 456, "E1:vis": 456,
    # 📋 787 条例句没有中文（705 条模型判定翻不了 + 2 条重试到顶 + 空串）。0.1%，不动。
    "E3:all": 787, "E3:vis": 787,

    # ── L 组：阶段 8 债务 —— **故意红着** ──────────────────────────────
    # 🔴 这一组不是「缺陷」，是「App 还没接 v3」。基线一律 0，
    #    意味着它现在必然红。**阶段 8 切完读取路径才该变绿。**
    #    🔴 谁要是为了让闸好看把这里调高，那就正好把这道闸变成了它要防的东西。
}

# ⚠️ ACCEPT 里值为 None ＝「这条不设上限」（证据层那种有意不洗的）。
#    **只有带理由的才允许写 None。**


def checks():
    """→ [(编号, 来源脚本, 日期, 缺陷名, 写入侧SQL, 读取侧SQL, 命中判据)]

    命中判据是函数：拿到一条文本，返回 True 表示「这条是缺陷」。
    """
    # ⭐ 判据全部来自修复脚本本身，见文件头「判据只许一份」
    return [
        # ── A 组：音标（写 pronunciation / 读 is_primary）────────────────
        ("A1", "build_pronunciation_layer", "08-25", "音标里残留定界符 / \\ [ ]",
         IPA_ALL, IPA_PRIM, lambda t: any(ch in t for ch in "/\\[]")),
        ("A2", "build_pronunciation_layer", "08-25", "音标首尾有空白",
         IPA_ALL, IPA_PRIM, lambda t: t != t.strip()),
        ("A3", "build_pronunciation_layer", "08-25", "拉丁小写 g（应为 IPA ɡ U+0261）",
         IPA_ALL, IPA_PRIM, lambda t: "g" in t),
        ("A4", "build_pronunciation_layer", "08-25", "键盘撇号冒充重音符（fr/it 版惯犯）",
         IPA_ALL, IPA_PRIM, lambda t: "'" in t or "ʼ" in t),
        # 🔴 A5 第一版我直接用了生成侧的 `BARE_BAD` —— **用错了地方，报 6,140 条假红**。
        #    `BARE_BAD` 的职责是「这个**裸串**像不像音标」（筛 el 版的无定界符候选），
        #    不是「这条音标有没有毛病」。拿它一查，`ɛ̃.plo.z(ə.)ʁa` 全中招 ——
        #    而那个括号是**法语可选中央元音的标准写法**，一条都不该报。
        #    ⇒ 这正是本文件头写的「闸与它守的逻辑用两个不同判据」，我在同一个文件里当场又犯。
        #    收窄成按含义：**IPA 里不该出现大写拉丁字母**。逮到的是 X-SAMPA 冒充 IPA
        #    （`absOlysjO~` = `absɔlysjɔ̃`、`libR` = `libʁ`、`fRHi` = `fʁɥi`）——
        #    与 `[[dbtool-and-golden-tests]]` 记的葡语 X-SAMPA 坑同一族。
        ("A5", "build_pronunciation_layer", "08-25", "X-SAMPA 冒充 IPA（大写字母）",
         IPA_ALL, IPA_PRIM, lambda t: bool(_XSAMPA.search(t))),

        # ── B 组：释义清洗（写 sense_gloss / **证据层会被搬回来**）────────
        ("B1", "strip_footnote_refs", "08-23", "脚注引用残渣 ^([1])",
         FR_EVI, FR_PUB, lambda t: bool(_foot.REF.search(t)) and not _foot.KEEP.search(t)),
        ("B2", "strip_citation_tails", "08-24", "引文出处尾巴 —（…）",
         FR_EVI, FR_PUB, lambda t: bool(_cit.CIT.search(t)) and not _cit.KEEP.search(t)),
        ("B3", "strip_editorial_residue", "08-23", "编辑残渣（模板/维护标记）",
         FR_EVI, FR_PUB, lambda t: bool(_res.RX.search(t)) and not _res.KEEP_RX.search(t)),
        ("B4", "strip_editorial_residue", "08-23", "洗完只剩标点/空壳",
         FR_EVI, FR_PUB, lambda t: bool(_res.EMPTY.match(t)) or t in _res.STUB),
        ("B5", "tidy_gloss_punctuation", "08-23", "标点没收拾（前导标点/重复逗号/空格+句点）",
         FR_EVI, FR_PUB,
         lambda t: bool(_tidy.LEAD.match(t) or _tidy.DUP.search(t) or _tidy.SPACE_PUNCT.search(t))),
        ("B6", "gloss_clean", "08-25", "花括号/方括号模板残渣",
         FR_EVI, FR_PUB, lambda t: "{{" in t or "}}" in t or "[[" in t or "]]" in t),

        # ── C 组：中文释义 ────────────────────────────────────────────
        # 🔴 C1 第一版写的是「一个汉字都没有」，报 103 条**全是假红**：
        #    `octante-quatre`→`84`、`YouTube`→`YouTube`、`SINE`→`SINE`
        #    —— 数字、品牌名、缩写的中文**本来就长这样**。
        #    ⇒ 按含义改：**中文栏原样抄了法语词形**才是缺陷。见 `[[criteria-narrower-than-you-think]]`。
        ("C1", "gloss_translate", "08-24", "中文栏原样抄了法语词形（没翻）",
         None, None, None),                                   # → special()，要拿词形比
        ("C2", "gloss_translate", "08-24", "中文里混进元话语/译注",
         ZH_ALL, ZH_PUB,
         lambda t: any(k in t for k in ("这句话的意思", "字面意思是", "译注", "原文如此"))),
        # 🔴 C3 第一版把 `（法语）` 和 `（法国）` 混成一件事，报 105 条。
        #    `卡尔瓦多斯省（法国）` 是**正当的地理限定**，对中文读者是有用信息。
        #    真正会漏进来的是语言标签 `（法语）`（`[[context-you-give-leaks-into-output]]`）。
        ("C3", "slot_translate", "08-23", "中文里残留「（法语）」这个我给的上下文标签",
         ZH_ALL, ZH_PUB, lambda t: "（法语）" in t),

        # ── D 组：撇号归一（全库约定）──────────────────────────────────
        ("D1", "normalize_apostrophes", "08-22", "词形里有未归一的弯撇号",
         "SELECT word FROM dict", "SELECT DISTINCT word FROM example",
         lambda t: t != norm_apos(t)),
        ("D2", "normalize_apostrophes", "08-22", "变形表 base 未归一",
         "SELECT base FROM inflection", "SELECT base FROM inflection",
         lambda t: t != norm_apos(t)),

        # ── E 组：例句 ────────────────────────────────────────────────
        ("E1", "ingest_examples", "08-25", "根本不是例句（同义词标注行/维护残桩）",
         EX_ALL, EX_VIS,
         lambda t: bool(_NOT_EX.search(t))),
        # 🔴 E2 第一版也是「一个汉字都没有」，报 344 条假红：
        #    `bleu + -s → bleus`（构词式）、`CH₃-CH(CH₃)-CH-CH₂(OH)`（分子式）
        #    —— 那些**本来就不该翻**。按含义改：中文与法语原句**逐字相同** ＝ 没翻。
        ("E2", "translate_examples", "08-26", "例句中文与法语原句逐字相同（没翻）",
         None, None, None),                                   # → special()
        ("E3", None, None, None, None, None, None),           # → special()
    ]


import re                                                # noqa: E402
# A5：IPA 里**不该出现大写拉丁字母**。X-SAMPA 用大小写区分音位，一查一个准。
_XSAMPA = re.compile(r"[A-Z«»]|\s{2}")
# E1 的判据：抄自阶段 5 补记里实测出来的三族（**只有这三族**，别放宽）
_NOT_EX = re.compile(
    r"^\s*(?:Near-|Coordinate |Informal )?"
    r"(?:Synonym|Antonym|Hypernym|Hyponym|Meronym|term)s?\s*:"
    r"|Can we date this quote"
    r"|please add an English translation|Can we find and add a quotation", re.I)


def special(con, trace=False):
    """判据不是「一条文本」形状的断言 —— 结构不变量、跨表关系。"""
    out = []

    def one(cid, script, date, name, nw, nr):
        if trace:
            print("      · %-4s %-34s" % (cid, name[:34]), flush=True)
        out.append((cid, script, date, name, nw, nr))

    q = lambda s: con.execute(s).fetchone()[0]

    # C1：中文栏原样抄了法语词形（要拿两列比，不是单条文本的判据）
    n = nv = 0
    for w, t, hid in con.execute(
            "SELECT d.word, g.text, COALESCE(s.hidden,0) FROM sense_gloss g "
            "JOIN sense s ON s.id=g.sense_id JOIN entry e ON e.id=s.entry_id "
            "JOIN dict d ON d.id=e.word_id WHERE g.lang='zh'"):
        if t and w and t.strip().lower() == w.strip().lower():
            n += 1
            nv += (not hid)
    one("C1", "gloss_translate", "08-24", "中文栏原样抄了法语词形（没翻）", n, nv)

    # E2：例句中文与法语原句逐字相同
    n = nv = 0
    for t, z, sid, hid in con.execute(
            "SELECT e.text, g.text, e.sense_id, COALESCE(s.hidden,1) "
            "FROM example_gloss g JOIN example e ON e.id=g.example_id "
            "LEFT JOIN sense s ON s.id=e.sense_id WHERE g.lang='zh'"):
        if t and z and t.strip() == z.strip():
            n += 1
            nv += (sid is not None and not hid)
    one("E2", "translate_examples", "08-26", "例句中文与法语原句逐字相同（没翻）", n, nv)

    # E3：例句没有中文
    n = q("SELECT COUNT(*) FROM example e WHERE NOT EXISTS("
          "SELECT 1 FROM example_gloss g WHERE g.example_id=e.id AND g.lang='zh')")
    nv = q("SELECT COUNT(*) FROM example e JOIN sense s ON s.id=e.sense_id "
           "WHERE COALESCE(s.hidden,0)=0 AND NOT EXISTS("
           "SELECT 1 FROM example_gloss g WHERE g.example_id=e.id AND g.lang='zh')")
    one("E3", "translate_examples", "08-26", "例句没有中文译文", n, nv)

    # ── F 组：结构不变量（**这些必须恒为 0**）────────────────────────────
    # 🔴 F1 是 2026-08-26 `attach_orphan_examples` 立的硬不变量：例句的词 == 义项的词
    n = q("SELECT COUNT(*) FROM example e JOIN sense s ON s.id=e.sense_id "
          "JOIN entry en ON en.id=s.entry_id JOIN dict d ON d.id=en.word_id "
          "WHERE d.word <> e.word")
    one("F1", "attach_orphan_examples", "08-26", "🔴 跨词挂载（例句词≠义项所属词）", n, n)

    # F2：可见义项挂在隐藏义项上是矛盾；证据层指向隐藏义项是**已知的 stage-2a 遗留**
    n = q("SELECT COUNT(*) FROM sense_src ss JOIN sense s ON s.id=ss.sense_id WHERE s.hidden=1")
    one("F2", "stage-2a 遗留", "08-22", "证据行指向隐藏义项", n, 0)

    # F3：义项没有 pos（stage-2a 遗留）
    n = q("SELECT COUNT(*) FROM sense WHERE COALESCE(pos,'')='' AND COALESCE(hidden,0)=0")
    one("F3", "stage-2a 遗留", "08-22", "可见义项 pos 为空", n, n)

    # F4：每个词形最多一条 is_primary 读音
    n = q("SELECT COUNT(*) FROM (SELECT word_id FROM pronunciation WHERE is_primary=1 "
          "GROUP BY word_id HAVING COUNT(*)>1)")
    one("F4", "build_pronunciation_layer", "08-25", "🔴 一个词形多条主读音", n, n)

    # ── L 组：阶段 8 债务 —— App 还在读老扁平列 ─────────────────────────
    # 🔴 这不是数据缺陷，是**读取路径没切**。故意红着，见文件头。
    n = q("SELECT COUNT(*) FROM dict d WHERE COALESCE(d.ipa,'')='' "
          "AND EXISTS(SELECT 1 FROM pronunciation p WHERE p.word_id=d.id)")
    one("L1", "阶段 8 待切", "08-26",
        "🔴 老列无音标、音标层有（App 读老列 ⇒ 用户看不到）", n, n)
    n = q("SELECT COUNT(*) FROM example")
    one("L2", "阶段 8 待切", "08-26",
        "🔴 例句一条都没接进展示层（french.ts 无 example 查询）", n, n)
    return out


def run(con, trace=False):
    """跑全部断言。`trace=True` 逐条打进度 —— 卡住时能直接看出是哪一条。"""
    rows = []
    for cid, script, date, name, wsql, rsql, hit in checks():
        if hit is None:
            continue                      # 交给 special()
        t0 = time.time()
        nw = sum(1 for t in texts(con, wsql) if hit(t))
        nr = sum(1 for t in texts(con, rsql) if hit(t))
        if trace:
            print("      · %-4s %-34s %6.1fs" % (cid, name[:34], time.time() - t0), flush=True)
        rows.append((cid, script, date, name, nw, nr))
    t0 = time.time()
    for r in special(con, trace=trace):
        rows.append(r)
    if trace:
        print("      · special() 合计 %.1fs" % (time.time() - t0), flush=True)
    return sorted(rows)


def report(con, verbose=True, trace=False):
    """→ [(编号, 名称, 说明)]，只含**超出基线**的。"""
    red = []
    if verbose:
        print("═══ 回归闸（fr）：过去的修复现在还在不在 ═══")
        print("   %-5s %-38s %11s %11s" % ("", "缺陷", "写入/证据侧", "读取/出版侧"))
    for cid, script, date, name, nw, nr in run(con, trace=trace):
        bw = ACCEPT.get(cid + ":evi", ACCEPT.get(cid + ":all", ACCEPT.get(cid + ":write", 0)))
        br = ACCEPT.get(cid + ":pub", ACCEPT.get(cid + ":vis", ACCEPT.get(cid + ":read", 0)))
        bad_w = bw is not None and nw > bw
        bad_r = br is not None and nr > br
        bypass = nr > nw and ACCEPT.get(cid + ":bypass") != "ok"
        mark = "🔴" if (bad_w or bad_r or bypass) else "✅"
        if verbose:
            print("   %s %-5s %-38s %11s %11s%s"
                  % (mark, cid, name[:38], f(nw), f(nr),
                     "  ← 读取侧比写入侧还多！" if bypass else ""))
        if bad_w or bad_r:
            red.append((cid, name, "写入侧 %s / 读取侧 %s（基线 %s / %s）"
                        % (f(nw), f(nr), bw, br)))
        elif bypass:
            red.append((cid, name, "🔴 被绕过：写入侧 %s、读取侧 %s" % (f(nw), f(nr))))
    if verbose:
        print("\n   %s" % ("✅ 全部通过" if not red else "🔴 %d 条要看" % len(red)))
    return red


def check_brief():
    """给 `dbtool` 挂钩用：静默跑，只回报红的。"""
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    try:
        return report(con, verbose=False)
    finally:
        con.close()


# ══════════════════════════════════════════════════════════════════════════
#  ⭐ 变异验证：一条永远通过的检查等于没检查
# ══════════════════════════════════════════════════════════════════════════
MUTATIONS = [
    ("A1", "INSERT INTO pronunciation (word_id,ipa,notation,is_primary,src,src_ref) "
           "VALUES ((SELECT id FROM dict LIMIT 1),'/mu.ta.sjɔ̃/','phonemic',0,'mutate','mutate')"),
    ("A3", "INSERT INTO pronunciation (word_id,ipa,notation,is_primary,src,src_ref) "
           "VALUES ((SELECT id FROM dict LIMIT 1),'mu.ta.sjɔ̃g','phonemic',0,'mutate','mutate')"),
    ("A4", "INSERT INTO pronunciation (word_id,ipa,notation,is_primary,src,src_ref) "
           "VALUES ((SELECT id FROM dict LIMIT 1),'mu'||char(700)||'ta','phonemic',0,'mutate','mutate')"),
    ("B1", "UPDATE sense_gloss SET text=text||' ^([1])' WHERE rowid="
           "(SELECT g.rowid FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
           " WHERE g.lang='fr' AND COALESCE(s.hidden,0)=0 LIMIT 1)"),
    ("B2", "UPDATE sense_gloss SET text=text||' — (Victor Hugo, 1862)' WHERE rowid="
           "(SELECT g.rowid FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
           " WHERE g.lang='fr' AND COALESCE(s.hidden,0)=0 LIMIT 1)"),
    # 🔴 C1 的变异必须跟着判据改。原来写的是 `text='no han here'`，
    #    那是给旧判据「一个汉字都没有」用的 —— 判据收窄成「中文==词形」之后，
    #    这条变异**再也触发不了它**，就成了一条永远通过的检查。
    #    ⇒ **改判据的同时必须改变异用例**，否则变异验证自己变成摆设。
    ("C1", "UPDATE sense_gloss SET text=(SELECT d.word FROM sense s "
           " JOIN entry e ON e.id=s.entry_id JOIN dict d ON d.id=e.word_id "
           " WHERE s.id=sense_gloss.sense_id) WHERE rowid="
           "(SELECT g.rowid FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
           " WHERE g.lang='zh' AND COALESCE(s.hidden,0)=0 LIMIT 1)"),
    ("C2", "UPDATE sense_gloss SET text=text||'（译注：随便写的）' WHERE rowid="
           "(SELECT g.rowid FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
           " WHERE g.lang='zh' AND COALESCE(s.hidden,0)=0 LIMIT 1)"),
    ("D1", "UPDATE dict SET word=word||char(8217)||'x' WHERE id=(SELECT id FROM dict LIMIT 1)"),
    ("E1", "UPDATE example SET text='Synonym: mutation' WHERE id="
           "(SELECT e.id FROM example e JOIN sense s ON s.id=e.sense_id "
           " WHERE COALESCE(s.hidden,0)=0 LIMIT 1)"),
    ("F1", "UPDATE example SET word=word||'ZZ' WHERE id="
           "(SELECT id FROM example WHERE sense_id IS NOT NULL LIMIT 1)"),
    ("A5", "INSERT INTO pronunciation (word_id,ipa,notation,is_primary,src,src_ref) "
           "VALUES ((SELECT id FROM dict LIMIT 1),'myta.sjO~','phonemic',0,'mutate','mutate')"),
    ("B6", "UPDATE sense_gloss SET text=text||' [[mutation]]' WHERE rowid="
           "(SELECT g.rowid FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
           " WHERE g.lang='fr' AND COALESCE(s.hidden,0)=0 LIMIT 1)"),
    # E2 判据 = 例句中文与法语原句逐字相同 ⇒ 把中文改成原句
    ("E2", "UPDATE example_gloss SET text=(SELECT e.text FROM example e "
           " WHERE e.id=example_gloss.example_id) WHERE rowid="
           "(SELECT g.rowid FROM example_gloss g JOIN example e ON e.id=g.example_id "
           " JOIN sense s ON s.id=e.sense_id WHERE g.lang='zh' "
           " AND COALESCE(s.hidden,0)=0 LIMIT 1)"),
    ("F3", "UPDATE sense SET pos='' WHERE id="
           "(SELECT id FROM sense WHERE COALESCE(hidden,0)=0 AND COALESCE(pos,'')<>'' LIMIT 1)"),
    ("F4", "UPDATE pronunciation SET is_primary=1 WHERE id=("
           "SELECT p2.id FROM pronunciation p2 WHERE p2.is_primary=0 AND EXISTS("
           "  SELECT 1 FROM pronunciation p1 WHERE p1.word_id=p2.word_id AND p1.is_primary=1)"
           " LIMIT 1)"),
]


def preflight():
    """⭐ 廉价预检：只验每条变异 SQL 的**语法与列名**，不碰真库。

    🔴 2026-08-26 加这一步，是因为全量变异**连崩两次**，两次都是变异 SQL 自己写错
       （`pronunciation.src_ref` 是 NOT NULL 没给值；`sense_gloss` 根本没有 `id` 列），
       而每次都要先复制 2.8 GB 才发现 —— 第二次崩在第 4 条，前面 3 条白跑。
    ⇒ 做法：拿真库的 schema 建**内存空壳库**，每张表塞一行假数据，逐条 execute。
      秒级出结果，把「SQL 写错」和「闸没逮住」这两件事分开。
    """
    src = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ddl = [r[0] for r in src.execute(
        "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND type IN ('table','index')")]
    cols = {t: [(r[1], r[2], r[5]) for r in src.execute("PRAGMA table_info(%s)" % t)]
            for (t,) in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    src.close()
    bad = []
    for cid, sql in MUTATIONS:
        m = sqlite3.connect(":memory:")
        for d in ddl:
            try:
                m.execute(d)
            except Exception:
                pass
        for t, cs in cols.items():                       # 每张表塞一行，SELECT…LIMIT 1 才取得到
            names = [n for n, _ty, pk in cs if not pk]
            vals = [1 if "INT" in (ty or "").upper() else "x" for n, ty, pk in cs if not pk]
            try:
                m.execute("INSERT INTO %s (%s) VALUES (%s)"
                          % (t, ",".join(names), ",".join("?" * len(names))), vals)
            except Exception:
                pass
        try:
            m.execute(sql)
        except Exception as e:
            bad.append((cid, str(e)[:90]))
        m.close()
    for cid, e in bad:
        print("   🔴 变异 SQL 写错 %-4s %s" % (cid, e))
    return not bad


def mutate(only=()):
    """在**备份副本**上把每一族缺陷各造一条，闸必须**逐条**报出来。

    🔴 判据是**逐条比对**，不是「跑完还有红的就算逮住」——
       it 那轮吃过这个亏：D 组有 6 条常红，于是无论造什么变异
       （哪怕造在完全无关的表上）`bool(red)` 都为真 ⇒ **13/13 全过，而且是假的**。
       这里只看**声明的那一条**的数字有没有变大。
    """
    src = Path(paths.DB)
    tmp = src.with_suffix(".mutate.sqlite")
    todo = [m for m in MUTATIONS if not only or m[0] in only]
    print("═══ 变异验证：%d 条 ═══" % len(todo))
    if not preflight():                    # 🔴 先廉价验 SQL，别拷 2.8 GB 才发现写错了
        print("\n🔴 预检没过，**不跑全量**")
        return False
    # ⭐ **拷一次，每条变异跑完就 ROLLBACK**。
    #    🔴 第一版每条都重拷一次 2.8 GB 的库 —— 15 条跑了 35 分钟，
    #       其中绝大部分时间在拷贝，用户连问四次「是不是卡住了」。
    #       事务回滚给的隔离性和重拷完全一样，而且**更强**：
    #       重拷依赖「我记得删临时文件」，回滚不依赖任何东西。
    if tmp.exists():
        tmp.unlink()
    shutil.copy2(src, tmp)
    con = sqlite3.connect(tmp)
    con.isolation_level = None                       # 自己管事务
    base = {r[0]: (r[4], r[5]) for r in run(con)}
    ok = 0
    for cid, sql in todo:
        t0 = time.time()
        con.execute("BEGIN")
        con.execute(sql)
        after = {r[0]: (r[4], r[5]) for r in run(con)}
        con.execute("ROLLBACK")                      # ← 干净还原，不留痕
        b, a = base.get(cid, (0, 0)), after.get(cid, (0, 0))
        got = a[0] > b[0] or a[1] > b[1]
        print("   %s %-5s %s → %s   %.0fs"
              % ("✅" if got else "🔴 没逮住", cid, b, a, time.time() - t0), flush=True)
        ok += got
    # 🔴 回滚干净了吗？跑完再算一次基线，必须与开头**逐条相同** ——
    #    否则说明某条变异漏进了后面的比对（那会让后面的结果全不可信）。
    end = {r[0]: (r[4], r[5]) for r in run(con)}
    if end != base:
        print("   🔴 回滚没干净：%s" % [k for k in base if base[k] != end.get(k)])
        ok = -1
    con.close()
    if tmp.exists():
        tmp.unlink()
    print("\n   %d/%d" % (ok, len(todo)))
    return ok == len(todo)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate(tuple(x for x in a.only.split(",") if x)) else 1
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    red = report(con, trace=a.trace)
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
