#!/usr/bin/env python3
"""回归闸：**过去每一个修复，现在还在不在**。pt 版，2026-08-30（阶段 7）。

═══ 为什么必须有这个 ═══
用户 2026-08-11（es 上）：「同一个问题你修了，隔天修其他问题，你又发现之前的问题
又出现了。这才是我抱怨的。这也才是导致无穷无尽的根本原因。」

修复消失有**三种**机制，后两种极隐蔽：

  ❌ **被抹掉**：修复写在某张表上，而某个 build 脚本 DROP 重建 ⇒ 修复没了。
  ⚠️ **被绕过（换读取路径）**：数据还在、查那一列一切正常，
     但展示层改读别的地方了。**只查修复写入的那一列，永远发现不了。**
  ⚠️ **被绕过（A 层搬到 B 层）** —— fr 2026-08-25 亲身撞到：
     四个清洗脚本全改 `sense_gloss`，而裁决是把 `sense_src` 的文本**搬进来** ⇒
     4,049 条脚注残渣原样搬回，**四道闸没一道看得见**。
     ⇒ 本闸对每条文本判据**同时查证据层与出版层**。

🔴🔴 **pt 现在处在「被绕过」的最大值上**：`packages/dict-core/src/portuguese.ts`
   287 行还在读老扁平列（`dict.translation` / `dict.definition` / `dict.ipa_br`），
   v3 那 11 张表**一张都没接**。⇒ 阶段 0–6 做的东西用户现在一个字都看不到。
   本闸的 **L 组**专门盯这笔「阶段 8 债务」：它现在是**故意红的**，
   阶段 8 切完读取路径才该变绿。**别为了让闸好看去调它的基线。**

═══ 判据从哪来 ═══
**直接 import 各脚本自己的判据**（正则/函数原样拿来用），不另写一套。
`[[fix-regression-and-gate]]` 第三种机制：**闸与它守的那段逻辑用两个不同判据 ⇒
闸在报自己的 bug**（fr 一天撞两次，音标闸⑤报了 1,085 条假红）。**判据只许一份。**

⚠️ 本文件今天（2026-08-30）就在 pt 上验证过这条：闸红了四次，
   **四次全是断言的问题，不是数据的问题** ——
   两次写死行数（`400330`／`7947`，被字面量闸逮到）、
   一次范围比该管的宽（查了阶段 2b 的老账）、
   一次断言对葡语根本不成立（「变形不许指向自己」，而葡语规则动词的
   **人称不定式与虚拟式将来时同形于不定式**）。
   ⇒ **闸红了先问「数据错了还是断言过期」。**

═══ 怎么用 ═══
    python3 tests/test_no_regression.py            # 出清单
    python3 tests/test_no_regression.py --trace    # 逐条计时
    python3 tests/test_no_regression.py --mutate   # 变异验证：闸本身是不是恒真的

🔴 **每加一个修复脚本，必须在 CHECKS 里加一行。** 没有断言的修复 ＝ 下一次静默回归。
🔴 **每条非零都必须在 ACCEPT 里带理由。** 调高任何一个基线都要写清为什么 ——
   否则这就成了掩盖回归的开关。
"""
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))
sys.path.insert(0, str(HERE.parent / "fixes"))

import paths                                          # noqa: E402
# ⭐ 判据一律 import，不抄。下面每一个都是某个脚本里那一份唯一的判据。
from build_freq_layer import measurable               # noqa: E402
from fix_colloc_separator import roundtrip            # noqa: E402
from fix_ipa_delimiters import split_ipa              # noqa: E402
from harvest_pronunciation import has_delim, is_sampa  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))
from fix_stress_position import fix as stress_fix   # noqa: E402
from fix_example_field_swap import broken, load_forms, SWAP_SRC   # noqa: E402
from fix_example_near_dup import same_sentence   # noqa: E402
_SAME_SQL = "same_sentence(text)"
from ingest_audio import region_of as audio_region    # noqa: E402
from ingest_examples import clean_bold                # noqa: E402
from ingest_relations import SEM, SKIP                # noqa: E402
from link_table_forms import BARE_TABLE_CELL          # noqa: E402
from translate_examples import is_formula             # noqa: E402

f = lambda n: format(n, ",")
TS = str  # 占位，保持行短

# ══════════════════════════════════════════════════════════════════
# 允许的非零基线。**每一条都要写清为什么**，否则就是掩盖回归的开关。
ACCEPT = {
    "B4 阶段 2b 的变形关系按词性各存一份":
        "1,370 组 / 2,766 行，收尾单 C8。数据不算错（`entry_id` 不同），"
        "展示层去重，归阶段 8。",
    "B5 阶段 2b 有变形指向自己":
        "20 条，收尾单 C9。**葡语规则动词的人称不定式与虚拟式将来时同形于不定式**"
        "（`que eu orlar`）、`-e` 结尾形容词阴阳同形 ⇒ **大部分是对的，不是缺陷**。",
    "A2 读者可见的义项没有中文":
        "2,888 条，收尾单 C20/C21。拆开是：**交叉引用族 1,800**（`o mesmo que X`／`sigla de X`，"
        "能从库里**免费取被引词的中文**，是补不是删 —— 反向查证明这一族有 1,379 条"
        "模型给出了有用中文，绝不能当指针隐掉）＋ **判据够不着的 1,094 条**"
        "（`plural de X`／`feminino de X`／源头残渣`transitivo:`）。"
        "变位指针族 1,746 条已 `hidden=1`。",
    "F3 例句里的词缀构词式（不该翻，交阶段 8 决定渲染）":
        "539 条，收尾单 C13。**数据一个字节没动**（照 fr 先例「别在数据里砍」），"
        "已排除出翻译池。",
}


def build(con):
    q1 = lambda s, *a: con.execute(s, *a).fetchone()[0]
    C = []
    add = lambda g, name, got: C.append((g, name, got))

    # ── A 组：阶段 0 表结构与可逆性 ─────────────────────────────
    add("A", "A1 搭配分隔符不可逆（`fix_colloc_separator` 的判据）",
        sum(1 for (t,) in con.execute("SELECT text FROM collocation") if roundtrip(t) != t))
    # 🔴 判据要问的是「**读者会看到空行吗**」：
    #    ① 只算 `hidden=0` 的（隐掉的义项读者看不见）
    #    ② 第一版还带了个写死的 `- 45` 基线 —— 字面量闸看不见它（藏在算式里），
    #       今天第二次犯（`link_table_forms` 的 400330 是第一次）。基线进 ACCEPT，不进算式。
    add("A", "A2 读者可见的义项没有中文",
        q1("SELECT COUNT(*) FROM sense s WHERE COALESCE(s.hidden,0)=0 AND NOT EXISTS"
           "(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='zh')"))
    add("A", "A3 v3 的 11 张表少了任何一张",
        11 - q1("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
                "('sense_src','sense','sense_gloss','sense_tag','sense_relation',"
                "'pronunciation','example','example_gloss','collocation',"
                "'collocation_gloss','audio')"))

    # ── B 组：阶段 1/2/2c 词条层与变形层 ────────────────────────
    add("B", "B1 entry 孤儿（word_id 不在 dict）",
        q1("SELECT COUNT(*) FROM entry e WHERE NOT EXISTS"
           "(SELECT 1 FROM dict d WHERE d.id=e.word_id)"))
    # 🔴 第一版写成 `max(0, 7948 - COUNT(*))` —— **又是写死行数**，实际 7,947，差 1 就红。
    #    （字面量闸看不见它：它藏在算式里，不在断言三元组里。）
    #    ⇒ 改成按**含义**断言阶段 2a 真正修的那件事：
    #      「6,518 个词形因 `alt_of` 被当成变形而零释义」——
    #      所以**带 alt_of 关系的词形必须有可见义项**。这条永远不会过期。
    add("B", "B2 🔴 阶段 2a 的修复丢了：带 alt_of 的词形又变回零释义",
        q1("SELECT COUNT(DISTINCT r.word_id) FROM sense_relation r "
           "WHERE r.kind='alt_of' AND NOT EXISTS("
           "  SELECT 1 FROM entry e JOIN sense s ON s.entry_id=e.id "
           "  WHERE e.word_id=r.word_id)"))
    add("B", "B3 🔴 单独成格的小品词被当成变形（`BARE_TABLE_CELL`）",
        q1("SELECT COUNT(*) FROM inflection i JOIN dict d ON d.id=i.word_id "
           "WHERE d.word IN (%s)" % ",".join("'%s'" % x for x in BARE_TABLE_CELL)))
    add("B", "B4 阶段 2b 的变形关系按词性各存一份",
        q1("SELECT COUNT(*) FROM (SELECT word_id,base,label_zh FROM inflection "
           "WHERE src='en-edition' GROUP BY 1,2,3 HAVING COUNT(*)>1)"))
    add("B", "B5 阶段 2b 有变形指向自己",
        q1("SELECT COUNT(*) FROM inflection i JOIN dict d ON d.id=i.word_id "
           "WHERE d.word=i.base AND i.src='en-edition'"))
    # 🔴 判据按**含义**：「读者会不会看到同一行两遍」，与这行是哪个版本写的无关。
    #    旧版写的是 `COUNT(DISTINCT src LIKE '%-edition-forms')>1`（只算跨来源），
    #    `en-edition + en-edition` 自己撞的 1,322 组从建成那天起就看不见（族G，已修）。
    add("B", "B6 🔴 变位行方向错（指向自己）或读者看到同一行两遍",
        q1("SELECT COUNT(*) FROM inflection i JOIN dict d ON d.id=i.word_id "
           "WHERE d.word=i.base AND i.src LIKE '%-edition-forms'")
        + q1("SELECT COUNT(*) FROM (SELECT word_id,base,label_zh FROM inflection "
             "GROUP BY 1,2,3 HAVING COUNT(*)>1)"))
    # 族E：时态标签不许再出现「两个时态用斜杠并列」——除了真同形那一种。
    # 判据 import 自 `infl_compose`，**不在这里再写一份**（判据只许一份）。
    add("B", "B8 🔴 时态标签把复合时态名拆成了「A/B」（族E）",
        q1("SELECT COUNT(*) FROM inflection WHERE ("
           "label_zh LIKE '%现在时/将来时%' OR label_zh LIKE '%简单过去时/未完成过去时%' "
           "OR label_zh LIKE '%陈述式/条件式%')"))
    add("B", "B7 🔴 假词 `metaphonic` 又回来了（阶段 3 漏网，已删）",
        q1("SELECT COUNT(*) FROM dict WHERE word='metaphonic'"))

    # ── C 组：阶段 4 音标层（存裸约定 + X-SAMPA 排除）───────────
    add("C", "C1 🔴 `dict` 的音标列里又出现粘连的两个音标（`split_ipa`）",
        sum(1 for r in con.execute(
            "SELECT ipa_br, ipa_pt FROM dict WHERE ipa_br IS NOT NULL OR ipa_pt IS NOT NULL")
            for v in r if split_ipa(v)))
    # 判据 import 自 `harvest_pronunciation.has_delim`，**不在这里再写一份 SQL**。
    # （第一版就是自己写了一版 GLOB，语法理解错 ⇒ 恒真的假绿，变异验证逮到。）
    add("C", "C2 🔴 `pronunciation.ipa` 违反「DB 存裸」约定（含定界符）",
        sum(1 for (v,) in con.execute("SELECT ipa FROM pronunciation") if has_delim(v)))
    # 族H：重音符必须在音节开头（音节必须有元音核）。
    # 🔴 判据 **import `fix_stress_position.fix`**，不在这里再写一份 —— 它前后被数据
    #    打回两次（第一版差点毁掉 34.7 万条对的），抄一份等于把那两次教训也抄错一遍。
    add("C", "C4 🔴 重音符夹在声母与韵核之间（族H）",
        sum(1 for (v,) in con.execute("SELECT ipa FROM pronunciation") if stress_fix(v) != v))
    add("C", "C3 🔴 X-SAMPA 冒充 IPA（`is_sampa` 的判据）",
        sum(1 for (v,) in con.execute("SELECT ipa FROM pronunciation")
            if is_sampa({"ipa": v})))
    add("C", "C4 pronunciation 的 word_id 不在 dict",
        q1("SELECT COUNT(*) FROM pronunciation p WHERE NOT EXISTS"
           "(SELECT 1 FROM dict d WHERE d.id=p.word_id)"))
    add("C", "C5 region 不是 pt-BR/pt-PT/NULL",
        q1("SELECT COUNT(*) FROM pronunciation WHERE region IS NOT NULL "
           "AND region NOT IN ('pt-BR','pt-PT')"))

    # ── D 组：阶段 5a 频次层（判据本体全量复算）──────────────────
    bad = miss = 0
    for w, v in con.execute("SELECT word, freq_zipf FROM dict WHERE freq_zipf IS NOT NULL"):
        if not measurable(w):
            bad += 1
    for (w,) in con.execute("SELECT word FROM dict WHERE freq_zipf IS NULL"):
        if measurable(w):
            miss += 1
    add("D", "D1 🔴 给了频次却过不了 tokenize 判据（词缀被静默剥掉那族）", bad)
    add("D", "D2 🔴 明明量得了却留空（0.0 与 NULL 不许混）", miss)
    add("D", "D3 频次值越界（0–8 之外）",
        q1("SELECT COUNT(*) FROM dict WHERE freq_zipf IS NOT NULL "
           "AND (freq_zipf<0 OR freq_zipf>8)"))

    # ── E 组：阶段 5b 关系层 ────────────────────────────────────
    kinds = "','".join(SEM.values())
    add("E", "E1 🔴 收了不该收的族（%s）" % "/".join(SKIP),
        q1("SELECT COUNT(*) FROM sense_relation WHERE kind IN "
           "('derived','related','proverb')"))
    add("E", "E2 kind 不在白名单",
        q1("SELECT COUNT(*) FROM sense_relation WHERE kind NOT IN ('%s','alt_of')" % kinds))
    add("E", "E3 sense_id 非空但不在 sense",
        q1("SELECT COUNT(*) FROM sense_relation r WHERE r.sense_id IS NOT NULL "
           "AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.id=r.sense_id)"))

    # ── H 组：**表结构本身的陷阱**（不是某一次修复，是一类缺陷）───────
    # 🔴🔴 2026-08-30 逮到：`UNIQUE(word_id, sense_id, kind, target)` 里 `sense_id` 可空，
    #    而 **SQL 里 `NULL != NULL`** ⇒ 该约束对 NULL 行**完全不生效**。
    #    词条级关系正好全是 NULL ⇒ 重跑一次收割器就复制一整份（231,330 里 77,867 是重复）。
    #    ⚠️ **收割器内存里的去重集合防不住它** —— 那只保证单次运行内不重复。
    #      「我这边去过重了」不等于「库里不会重」。
    #    ⇒ 这一条**通查所有表**，不只 sense_relation —— 同类陷阱会在下一张表上重演。
    import re as _re
    nullable_unique = []
    for tname, tsql in con.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND sql LIKE '%UNIQUE%'"):
        cols = {r[1]: r[3] for r in con.execute("PRAGMA table_info(%s)" % tname)}
        for m in _re.finditer(r"UNIQUE\s*\(([^)]+)\)", tsql or ""):
            us = [x.strip() for x in m.group(1).split(",")]
            if any(cols.get(u, 1) == 0 for u in us):
                # 有表达式唯一索引兜底的不算（`COALESCE(...)` 把 NULL 变成了真值）
                idx = con.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND tbl_name=? "
                    "AND sql LIKE '%UNIQUE%' AND sql LIKE '%COALESCE%'", (tname,)).fetchone()[0]
                if not idx:
                    nullable_unique.append(tname)
    add("H", "H1 🔴 有表的 UNIQUE 含可空列且无 COALESCE 兜底索引（NULL≠NULL ⇒ 约束失效）",
        len(set(nullable_unique)))
    add("H", "H2 🔴 sense_relation 出现内容重复（只差 sense_id 的 NULL）",
        q1("SELECT COALESCE(SUM(n),0) FROM (SELECT COUNT(*)-1 n FROM sense_relation "
           "GROUP BY word_id, COALESCE(sense_id,-1), kind, target HAVING COUNT(*)>1)"))

    # ── F 组：阶段 5c/5d 例句层 ─────────────────────────────────
    add("F", "F1 🔴 bold 坐标不属于这段文本（`clean_bold` 的判据）",
        sum(1 for t, b in con.execute(
            "SELECT text, bold FROM example WHERE bold IS NOT NULL")
            if clean_bold(t, json.loads(b)) is None))
    add("F", "F2 🔴 出版层混进了中英之外的语言（方针 A3）",
        q1("SELECT COUNT(*) FROM example_gloss WHERE lang NOT IN ('zh','en')"))
    add("F", "F3 例句里的词缀构词式（不该翻，交阶段 8 决定渲染）",
        sum(1 for w, t in con.execute("SELECT word, text FROM example")
            if is_formula(w, t)))
    add("F", "F4 🔴 证据层的译文语言写成了中/英（该进出版层）",
        q1("SELECT COUNT(*) FROM example WHERE src_lang IN ('zh','en')"))
    # 🔴 2026-08-30 闸自己照出来的：删例句行没删它的译文行 ⇒ 留孤儿。
    #    当时是「未声明的表 example_gloss 行数变了」报的，那条问的是别的事
    #    —— 孤儿这件事没有任何一道闸在问。
    add("F", "F6 🔴 译文挂在已不存在的例句上（孤儿）",
        q1("SELECT COUNT(*) FROM example_gloss g "
           " WHERE NOT EXISTS(SELECT 1 FROM example e WHERE e.id=g.example_id)"))
    # 族J：例句里必须有它的词头或词头的某个变形，**而出处里没有**。
    # ⚠️ 只查「出处里有」这个正面证据的那一半 —— 光"例句里没有"会误伤 3,532 条真例句
    #    （多词表达被变位 / 分词阴性形 / de+o 缩合 / 连字符），抽样打回过。
    # 🔴 判据 **import `fix_example_field_swap.broken`**，不在这里用 SQL 再写一份。
    #    第一版就是自己写了一版 `INSTR(LOWER(...))`，与修复脚本的 `fold()`（去变音符）
    #    **不是同一个判据** ⇒ 闸报 5 条红，其中 3 条是修复脚本漏掉的真缺陷、
    #    2 条是闸自己的假红。统一成词边界匹配后两边都对（`[[fix-regression-and-gate]]`）。
    _forms = load_forms(con)
    add("F", "F7 🔴 例句和出处装反了（词头在出处里、不在例句里）",
        sum(1 for w, t, r, src in con.execute(
                "SELECT word, text, ref, src FROM example "
                " WHERE COALESCE(hidden,0)=0 AND ref IS NOT NULL")
            if src in SWAP_SRC and broken(w, t, r, _forms)))
    # 族K：同一段引文从两个版本各收一遍。判据 import 生成侧那份，不再写一遍。
    add("F", "F8 🔴 同一个词下躺着同一句话的两个抄本（`UNIQUE(word,text)` 挡不住）",
        q1("SELECT COUNT(*) FROM (SELECT 1 FROM example WHERE COALESCE(hidden,0)=0 "
           "GROUP BY word, %s HAVING COUNT(*)>1)" % _SAME_SQL))
    add("F", "F5 example.word 不在 dict",
        q1("SELECT COUNT(*) FROM (SELECT DISTINCT word FROM example "
           "EXCEPT SELECT word FROM dict)"))

    # ── G 组：阶段 6 录音层 ─────────────────────────────────────
    add("G", "G1 🔴 kind 不是 human（本步不做 TTS）",
        q1("SELECT COUNT(*) FROM audio WHERE kind<>'human'"))
    add("G", "G2 🔴 URL 不指向 Wikimedia Commons",
        q1("SELECT COUNT(*) FROM audio WHERE COALESCE(url_ogg,url_mp3,url_wav,url_other) "
           "NOT LIKE 'https://%.wikimedia.org/%'"))
    add("G", "G3 region 不是 pt-BR/pt-PT/NULL",
        q1("SELECT COUNT(*) FROM audio WHERE region IS NOT NULL "
           "AND region NOT IN ('pt-BR','pt-PT')"))
    add("G", "G4 🔴 有 region 却没有 region_src（说不出这个地区是哪来的）",
        q1("SELECT COUNT(*) FROM audio WHERE region IS NOT NULL AND region_src IS NULL"))

    # ── L 组：阶段 8 债务（**现在故意红**）────────────────────────
    ts = ROOT / "packages" / "dict-core" / "src" / "portuguese.ts"
    src = ts.read_text(encoding="utf-8") if ts.exists() else ""
    # 🔴 第一版找的是 `dict.translation` 这种带表名的写法，而 `portuguese.ts` 写的是
    #    `SELECT id, word, is_lemma, pos, translation, definition FROM dict` —— **裸列名**，
    #    于是这条判据报 0（假绿）。判据比它要描述的东西**窄**了。
    #    ⇒ 按含义写：**内容列还在从扁平表 `dict` 取**。
    # 🔴 第二版：**子串匹配误报**。`infl` 命中了 `inflection`、`collocation` 命中了**表名**
    #    `FROM collocation c` —— 阶段 8 切完之后 L1 仍报 4，全是假的。
    #    ⇒ 加词边界，且列表只留**没有 v3 家的老内容列**。
    # ⚠️ `ipa_br`/`ipa_pt` **不算债务**：它们是阶段 4a 的源列，服务用它们兜底 ——
    #    实测 **12 行有 `ipa_br` 却没有 `pronunciation` 行**，去掉兜底那些词的音标就没了。
    #    （收尾单 C23。）
    FLAT = ("translation", "definition", "exchange", "meta", "infl")
    add("L", "L1 展示层还在从扁平表 dict 取老内容列（阶段 8 债务）",
        sum(1 for c in FLAT if _re.search(r"\b%s\b" % c, src)) if "FROM dict" in src else 0)
    add("L", "L2 展示层没接 v3 表（阶段 8 债务）",
        sum(1 for t in ("FROM sense", "FROM pronunciation", "FROM example",
                        "FROM inflection", "FROM audio", "FROM sense_relation")
            if t not in src))
    return C


def check_brief():
    """`dbtool.session` 每次写库后调这个。→ [(组, 名称, 数值)]，只含**没有理由的红**。

    ⚠️ 它**只报不拦**（见 `dbtool._regression_check` 的文档）：写库已经 commit 了，
       而且不是每次红都该回滚 —— 有些是这次写库有意为之。报出来 + 备份路径够决策。
    """
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    # 🔴 判据本体是 `fix_example_near_dup.same_sentence`，**注册成 SQL 函数**，
    #    不在 SQL 里重写一版 —— 上一条 F7 就是因为"闸自己写一版"报了 5 条红。
    con.create_function("same_sentence", 1, same_sentence)
    try:
        C = build(con)
    finally:
        con.close()
    return [(g, n, f(v)) for g, n, v in C if v and n not in ACCEPT]


def run(trace=False):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    # 🔴 判据本体是 `fix_example_near_dup.same_sentence`，**注册成 SQL 函数**，
    #    不在 SQL 里重写一版 —— 上一条 F7 就是因为"闸自己写一版"报了 5 条红。
    con.create_function("same_sentence", 1, same_sentence)
    t0 = time.time()
    C = build(con)
    con.close()
    if trace:
        print("   （全部 %d 条，用时 %.1fs）" % (len(C), time.time() - t0))
    print("═══ 回归闸（pt）：过去每一个修复，现在还在不在 ═══\n")
    red = 0
    for g, name, got in C:
        if got == 0:
            print("   ✅ %-58s %8s" % (name, f(got)))
        elif name in ACCEPT:
            print("   🟡 %-58s %8s  ← 已接受" % (name, f(got)))
            print("        理由：%s" % ACCEPT[name])
        else:
            red += 1
            print("   🔴 %-58s %8s" % (name, f(got)))
    print("\n%s" % ("✅ 没有回归（%d 条断言，%d 条带理由的已接受基线）"
                    % (len(C), sum(1 for _g, n, v in C if v and n in ACCEPT))
                    if not red else "🔴 %d 条红" % red))
    return 1 if red else 0


def mutate():
    """⭐ 变异验证：**一条永远通过的检查等于没检查。**

    造一份库的副本、把修复反向撤销，看闸红不红。
    """
    import shutil
    import tempfile
    print("═══ 变异验证 ═══")
    ok = 0
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "m.db"
        shutil.copy(paths.DB, db)
        con = sqlite3.connect(db)

        def check(name, sql, group_name):
            nonlocal ok
            con.execute(sql)
            con.commit()
            ro = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
            hit = [v for _g, n, v in build(ro) if n == group_name and v]
            ro.close()
            good = bool(hit)
            ok += good
            print("   %s %-52s → %s" % ("✅ 逮到" if good else "🔴 **漏了**",
                                        name, hit[0] if hit else 0))
            con.execute("ROLLBACK") if False else None

        check("把假词 `metaphonic` 放回去",
              "INSERT INTO dict (id,word,word_norm,pos,is_lemma) "
              "VALUES (9999001,'metaphonic','metaphonic','n',0)",
              "B7 🔴 假词 `metaphonic` 又回来了（阶段 3 漏网，已删）")
        check("给一条音标加回定界符（违反存裸约定）",
              "UPDATE pronunciation SET ipa='/'||ipa||'/' "
              "WHERE id=(SELECT MIN(id) FROM pronunciation)",
              "C2 🔴 `pronunciation.ipa` 违反「DB 存裸」约定（含定界符）")
        check("给一个词缀填上频次（tokenize 判据该拦住它）",
              "UPDATE dict SET freq_zipf=4.68 WHERE word='anti-'",
              "D1 🔴 给了频次却过不了 tokenize 判据（词缀被静默剥掉那族）")
        check("收一条 `derived` 关系（不该收的族）",
              "INSERT INTO sense_relation (word_id,sense_id,kind,target,src,src_ref) "
              "VALUES (1,NULL,'derived','x','m','m')",
              "E1 🔴 收了不该收的族（derived/related/proverbs）")
        check("往出版层塞一条法语译文（方针 A3 只留中英）",
              "INSERT INTO example_gloss (example_id,lang,text,src) "
              "VALUES ((SELECT MIN(id) FROM example),'fr','x','m')",
              "F2 🔴 出版层混进了中英之外的语言（方针 A3）")
        check("把一条录音标成 TTS（本步只收真人）",
              "UPDATE audio SET kind='tts-tool' WHERE id=(SELECT MIN(id) FROM audio)",
              "G1 🔴 kind 不是 human（本步不做 TTS）")
        check("给一条录音留 region 却抹掉 region_src",
              "UPDATE audio SET region_src=NULL WHERE region IS NOT NULL "
              "AND id=(SELECT MIN(id) FROM audio WHERE region IS NOT NULL)",
              "G4 🔴 有 region 却没有 region_src（说不出这个地区是哪来的）")
        con.close()
    print("\n   变异 %d/7" % ok)
    return ok == 7


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    sys.exit((0 if mutate() else 1) if a.mutate else run(a.trace))
