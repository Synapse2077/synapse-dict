#!/usr/bin/env python3
"""回归闸：**过去每一个修复，现在还在不在**。it 版，2026-08-18（阶段 7）。

═══ 为什么必须有这个 ═══
用户 2026-08-11（es 上）：「同一个问题你修了，隔天修其他问题，你又发现之前的问题
又出现了。这才是我抱怨的。这也才是导致无穷无尽的根本原因。」

修复消失有**两种**机制，第二种极隐蔽：

  ❌ **被抹掉**：修复写在 `sense_gloss` 上，而某个 build 脚本 DROP 重建 ⇒ 修复没了。
  ⚠️ **被绕过**：数据还在、查那一列一切正常，但**展示层改读别的地方了**。
     es 的原案：7-31~8-03 整轮音标修复写在 `dict.phonetic`；8-07 新建 `pronunciation`
     表**从 dump 原样重建**、展示层跟着切过去 ⇒ 旧列里好端端写着修好的值，
     用户看到的却是没修的那个。**只查修复写入的那一列，永远发现不了。**

🔴 it 现在**正处在同一个路口**：2026-08-18 建好了 `pronunciation`（120 万行），
   而展示层还在读 `dict.ipa`。等阶段 8 切过去，任何只查 `dict.ipa` 的断言都会变瞎。
⇒ 本闸的核心设计：**每条断言同时在「修复写入的地方」和「App 实际读取的地方」跑一遍**，
   两边数字不同，就是「被绕过」。

═══ 判据从哪来 ═══
**直接 import 各修复脚本自己的判据**（正则/函数原样拿来用），不另写一套。
判据是对「缺陷长什么样」的定义，属于数据的性质；拿它去查另一条读取路径，
不构成"用代码核代码"。

═══ 怎么用 ═══
    python3 tests/test_no_regression.py            # 出清单
    python3 tests/test_no_regression.py --mutate   # 变异验证：闸本身是不是恒真的

🔴 **每加一个修复脚本，必须在 CHECKS 里加一行。** 没有断言的修复 ＝ 下一次静默回归。
🔴 **每条非零都必须在 ACCEPT 里带理由。** 没有基线的闸永远是红的，久了没人看
   （`PITFALLS` E 组）。调高任何一个基线都要写清为什么 —— 否则这就成了掩盖回归的开关。
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "fixes"))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import paths                                              # noqa: E402
from fix_untranslated_zh import LATIN_ONLY                # noqa: E402
from ingest_examples import is_not_an_example             # noqa: E402
from drop_hyphenation_fragments import is_fragment        # noqa: E402
from ipa_variants import STRESS_ALIASES, cmp_key           # noqa: E402
from normalize_sense_pos import SHORT                     # noqa: E402
from split_case_forms import APOSTROPHES, norm            # noqa: E402
from strip_it_placeholder import PLACEHOLDER              # noqa: E402
from fix_geo_parent_zh import DESC_PARENT, LAT           # noqa: E402
from strip_pos_label_in_gloss import LAB, TAIL           # noqa: E402
from fix_unclosed_paren import classify as paren_class   # noqa: E402
from hide_junk_pronunciation import is_junk_ipa            # noqa: E402
from fix_cross_edition_sense import REWRITE as XED_REWRITE  # noqa: E402

f = lambda n: format(n, ",")

# ══════════════════════════════════════════════════════════════════════════
#  两条取数路径：**修复写在哪** vs **App 从哪读**
#  App 侧的 SQL 形状抄自 `packages/dict-core/src/italian.ts`（sensesQuery / exactQuery），
#  不是我另编的 —— 抄错了这道闸就白设。
# ══════════════════════════════════════════════════════════════════════════
ZH_WRITE = ("SELECT g.text FROM sense_gloss g WHERE g.lang='zh'")
ZH_READ = ("SELECT g.text FROM sense s JOIN sense_gloss g ON g.sense_id=s.id "
           "AND g.lang='zh' AND g.kind='equivalent' AND g.seq=0 "
           "WHERE COALESCE(s.hidden,0)=0")
IT_WRITE = "SELECT g.text FROM sense_gloss g WHERE g.lang='it'"
IT_READ = ("SELECT g.text FROM sense s JOIN sense_gloss g ON g.sense_id=s.id "
           "AND g.lang='it' AND g.kind='definition' AND g.seq=0 "
           "WHERE COALESCE(s.hidden,0)=0")
# 🔴 音标：写在 `dict.ipa`，阶段 8 之后 App 读 `pronunciation` 的 is_primary 那条。
IPA_WRITE = "SELECT ipa FROM dict WHERE TRIM(COALESCE(ipa,''))<>''"
IPA_READ = "SELECT ipa FROM pronunciation WHERE is_primary=1"


def texts(con, sql):
    return [t for (t,) in con.execute(sql) if t]


# ══════════════════════════════════════════════════════════════════════════
#  🔴 已接受基线 —— 每一条都是**已经裁决过、决定不修**的残留，附理由
# ══════════════════════════════════════════════════════════════════════════
ACCEPT = {
    # B5：`fix_surgical_suffix.BY_HAND` 里**逐条判定为"原文正确、不改"**的三个：
    #   ovariotomia —— ovariotomy 历史上就指摘除卵巢
    #   lobotomia   —— 中文已含「切断」，另一半「额叶切除术」是通行别名
    #   sequestrotomia —— 死骨本就是取出，通行译名如此
    # ⚠️ 这三个是**判过的**，不是没看的。数字变大就说明来了新的、没判过的。
    "B5:write": 3, "B5:read": 3,
    # ── D 组（2026-08-21 点测评审）的已接受基线 ──────────────────────────
    # 🔴 D1 写入侧 602 = `fix_unclosed_paren` **藏起来**的切碎说明片段。行留在表里是
    #    有意的（可逆，且收录脚本重放时 INSERT OR IGNORE 不会覆盖 hidden）。
    #    读取侧必须是 0 —— 那才是用户看得见的地方。
    "D1:write": 602,
    # 🔴 D3–D6 的修复**做在展示层**，SQL 查不到，所以这里的数字不会因修复而变。
    #    ⚠️ 这意味着**这四条在回归闸里守不住** —— 谁把 `italian.ts`/`App.tsx` 的守卫
    #       删掉，这里照样是绿的，正是文件头说的第二种机制「被绕过」。
    #    ⇒ 真正守它们的是 `apps/web/src/contract-check.tsx`（**先渲染再断言**）。
    #       这里留基线只是为了记住数据层长什么样：数字**涨了**说明数据层来了新的。
    "D3:write": 431, "D3:read": 2428,     # 变形提示：投影后重复，inflNotes 去重挡住
    # 读取侧 > 写入侧是这条判据**天生的形状**（全列判重 vs 投影两列判重），不是被绕过。
    "D3:bypass": "ok",
    "D4:write": 326, "D4:read": 326,      # 搭配重复：colsQuery 按 text 去重挡住
    # 3,844 = 判据两次收窄后的真值（16,599 → 7,527 → 3,844，见 special() 里的说明）。
    "D5:write": 3844, "D5:read": 3844,    # 词头徽标：posWithSenses 守卫挡住
    "D6:write": 1418, "D6:read": 1418,    # 自反措辞：reflexiveOf 分叉挡住
    # 🔴 D7 写入侧 4 = `hide_junk_pronunciation` 藏起来的 `*`×3 与 `ː`×1。
    #    读取侧必须是 0。（另 4 条 fr 版词尾残片是**合法音标只是错**，不归 D7 判据。）
    "D7:write": 4,
    # C7：交叉引用义项里，**藏了这个词就一片空白**的三条（`fieri` / `drin` / `parteddietro`）。
    # `unhide_orphan_senses` 立的规矩：宁可显示一条弱内容，也不要显示空白。
    # 这三条在 `hide_see_also_residue.scan` 的 keep 侧，闸只盯 hide 侧，所以这里是 0；
    # 留这条注释是为了说明"为什么 22 条只处理了 10 条"。
}


def checks():
    """→ [(编号, 修复脚本, 日期, 缺陷名, 写入侧取数, 读取侧取数, 命中判据)]

    命中判据是一个函数：拿到一条文本，返回 True 表示"这条是缺陷"。
    """
    long_pos = lambda p: p and p not in SHORT

    return [
        # ── A 组：音标（写 dict.ipa / 读 pronunciation.is_primary）──────────
        ("A1", "阶段 4 约定 A5", "08-17", "音标里残留定界符 / 或 [",
         IPA_WRITE, IPA_READ, lambda t: "/" in t or "[" in t),
        ("A2", "阶段 4 约定 A5", "08-17", "音标首尾有空白",
         IPA_WRITE, IPA_READ, lambda t: t != t.strip()),
        ("A3", "build_pronunciation_layer", "08-17", "拉丁小写 g（应为 IPA ɡ U+0261）",
         IPA_WRITE, IPA_READ, lambda t: "g" in t),
        # 🔴 2026-08-18 阶段 8 新增。与 A3 同一族（键盘字符冒充 IPA 符号），
        #    但**不是闸报出来的，是接上展示层看渲染结果才发现的** ——
        #    `pesca` 一个词并排显示四条读音，其中两条只是把 ˈ 写成了 '。
        #    ⇒ 判据来自 `ipa_variants.STRESS_ALIASES`，与归一函数共用一份，不另写。
        ("A4", "normalize_ipa_stress_mark.py", "08-18", "撇号冒充重音符（应为 ˈ U+02C8）",
         IPA_WRITE, IPA_READ, lambda t: any(ch in t for ch in STRESS_ALIASES)),
        # A5（音节切分残渣）判据要同时看词形与音标 ⇒ 见 special()

        # ── B 组：中文释义（写 sense_gloss / 读 App 可见集）────────────────
        ("B1", "fix_untranslated_zh.py", "08-15", "「中文」整条是拉丁字母",
         ZH_WRITE, ZH_READ, lambda t: bool(LATIN_ONLY.match(t))),
        # B2 / B4 见 special()：判据要看别的列，且必须与修复脚本**同一个**条件 ——
        # 第一版我把 B2 写成「凡是尾部有词类名就算」，报 30 条，而修复脚本的判据是
        # **词类名等于本义项自己的词性**（`coniugato` 的「（动词）变位的」里那个"动词"
        # 是限定语、不是标签，脚本逐条读过后有意留着）。**闸比修复更严 = 假红**。
        ("B3", "strip_it_placeholder.py", "08-13", "意语「缺定义」占位符进了出版层",
         IT_WRITE, IT_READ, lambda t: bool(PLACEHOLDER.search(t))),
        ("B5", "fix_surgical_suffix.py", "08-16", "-ectomia 译成「切开」/ -tomia 译成「切除」",
         ZH_WRITE, ZH_READ, None),        # 需要词形，单独处理，见 special()

        # ── C 组：结构（各自的写入表 / App 读取形状）──────────────────────
        ("C1", "normalize_sense_pos.py", "08-15", "sense.pos 用了 kaikki 长写法",
         "SELECT pos FROM sense WHERE pos IS NOT NULL",
         "SELECT s.pos FROM sense s WHERE s.pos IS NOT NULL AND COALESCE(s.hidden,0)=0",
         long_pos),
        ("C2", "trim_pointer_notes.py", "08-16", "指针目标位混着英文用法说明",
         "SELECT target FROM sense_relation WHERE kind='alt_of'",
         "SELECT target FROM sense_relation WHERE kind='alt_of'",
         lambda t: bool(re.match(r"^(?:used|sometimes|often|usually|only when|as in)\b", t, re.I))),
        ("C3", "drop_non_examples.py", "08-18", "例句表里混着「根本不是例句」的行",
         "SELECT text FROM example",
         "SELECT text FROM example",     # App 直接读 example，写=读
         lambda t: is_not_an_example(t, None)),

        # ── D 组：2026-08-21 点测评审（12 词渲染成品送两家外审）逮到的 ──────
        # 🔴 这一组的来历值得记：**两家模型都判 `gatto`「无问题」**，而 `gatto` 的
        #    下位词里躺着 6 条 `( Felis chaus` 这样的断括号。模型看语言学，
        #    形式特征明确的残渣反而是确定性判据的活儿 —— 两者互补，不能互相替代。
        # D1 见 special()：读取侧要按 `hidden` 列过滤，而那一列是修复脚本建的 ——
        # checks() 拿不到连接、判断不了 schema 在不在，写死 SQL 会在建列前直接抛错。
        ("D2", "clean_inflection_base.py", "08-21", "变形原形里混着英文 and",
         "SELECT base FROM inflection",
         # 读取侧＝`inflQuery`（italian.ts:406）—— App 把它渲染成「avere and 的 …」
         "SELECT base FROM inflection",
         lambda t: " and " in t or t.endswith(" and")),
    ]


def special(con, trace=False):
    """判据需要「文本 + 别的列」才成立的，单独查；同样跑写入侧与读取侧两遍。"""
    out = []

    # F1 搜索预计算表的**陈旧性**（2026-08-20）。`search_prefix` 是派生数据，
    #    头号风险不是算错，是「算对了然后 dict 变了没人重算」—— 那时页面上的
    #    搜索下拉给的是旧结果，而查表本身一切正常，正是「被绕过」的形状。
    #    ⚠️ 这里只比**指纹**（两个 COUNT，毫秒级）。逐前缀 13,442 条的全量比对
    #       在 `pipeline/build_search_prefix.py` 自己的闸里，那个要跑二十几秒。
    #    写入侧＝表在不在，读取侧＝指纹对不对（`italian.ts` 就是靠它给结果的）。
    try:
        fp = con.execute("SELECT v FROM search_prefix_meta "
                         "WHERE k='dict_fingerprint'").fetchone()
        now = "%d:%d" % con.execute(
            "SELECT COUNT(*), COALESCE(MAX(id),0) FROM dict").fetchone()
        miss = 0 if fp else 1
        stale = 0 if (fp and fp[0] == now) else 1
    except sqlite3.Error:
        miss = stale = 1
    out.append(("F1", "build_search_prefix.py", "08-20",
                "搜索预计算表缺失/陈旧（dict 变了没重算）", miss, stale))

    # A5：音节切分残渣冒充音标 —— 判据**照抄 `drop_hyphenation_fragments.is_fragment`**，
    #     它要同时看词形与音标（「这串音标是词形拼写的一个片段」）。
    #     🔴 写入侧＝`dict.ipa` 那一列，读取侧＝`pronunciation` 全表 ——
    #        当初就是「列里 0 条、表里 228 条」，正是被绕过的形状。
    if trace:
        print("      · A5 音节切分残渣…", flush=True)
    def frag(sql):
        return sum(1 for w, ipa in con.execute(sql) if ipa and is_fragment(w, ipa))
    out.append(("A5", "drop_hyphenation_fragments.py", "08-18", "音节切分残渣冒充音标",
                frag("SELECT word, ipa FROM dict WHERE TRIM(COALESCE(ipa,''))<>''"),
                frag("SELECT d.word, p.ipa FROM pronunciation p "
                     "JOIN dict d ON d.id=p.word_id")))

    # B5：手术后缀译反 —— 判据要同时看词形与中文（`fix_surgical_suffix` 的原判据）
    def surgical(sql_extra):
        return con.execute("""
            SELECT count(*) FROM sense s JOIN dict d ON d.id=s.word_id
              JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh'
             WHERE ((d.word LIKE '%ectomia' AND g.text LIKE '%切开%')
                 OR (d.word LIKE '%tomia' AND d.word NOT LIKE '%ectomia'
                     AND g.text LIKE '%切除%')) """ + sql_extra).fetchone()[0]
    if trace:
        print("      · B5 手术后缀…", flush=True)
    out.append(("B5", "fix_surgical_suffix.py", "08-16", "-ectomia/-tomia 译反",
                surgical(""), surgical("AND COALESCE(s.hidden,0)=0 "
                                       "AND g.kind='equivalent' AND g.seq=0")))

    # B2：释义带词性标签 —— **判据照抄 `strip_pos_label_in_gloss` 的两个条件**：
    #     ① 词类名在**串尾** ② 且**等于本义项自己的词性**。少一个条件就会误报
    #     （`coniugato` 的「（动词）变位的」里"动词"是限定语，脚本逐条读过后有意留着）。
    if trace:
        print("      · B2…", flush=True)
    def pos_label(sql_where):
        n = 0
        for text, pos in con.execute(
                "SELECT g.text, s.pos FROM sense s JOIN sense_gloss g ON g.sense_id=s.id "
                "AND g.lang='zh' WHERE 1=1 " + sql_where):
            m = TAIL.search(text or "")
            if m and pos and LAB.get(m.group(1)) == pos:
                n += 1
        return n
    out.append(("B2", "strip_pos_label_in_gloss.py", "08-16", "释义尾部带词性标签且与本义项同词性",
                pos_label(""), pos_label("AND COALESCE(s.hidden,0)=0 "
                                         "AND g.kind='equivalent' AND g.seq=0")))

    # B4：地名释义里母地名没音译 —— 判据照抄 `fix_geo_parent_zh`：
    #     是「…的村庄/城镇」这类**从属地名描述**，且描述里还留着拉丁字母。
    #     ⚠️ 第一版我写成「中文里出现 4 个以上连续拉丁字母」，报 42,538 条 ——
    #        `DNA 检测`、`IDM 音乐` 全被算成缺陷。**尺子错，不是数据错**（A33）。
    if trace:
        print("      · B4…", flush=True)
    def geo_latin(sql_where):
        n = 0
        for (text,) in con.execute(
                "SELECT g.text FROM sense s JOIN sense_gloss g ON g.sense_id=s.id "
                "AND g.lang='zh' WHERE 1=1 " + sql_where):
            if text and DESC_PARENT.search(text) and LAT.search(text):
                n += 1
        return n
    out.append(("B4", "fix_geo_parent_zh.py", "08-16", "从属地名描述里母地名没音译",
                geo_latin(""), geo_latin("AND COALESCE(s.hidden,0)=0 "
                                         "AND g.kind='equivalent' AND g.seq=0")))

    # C4：撇号异写又分家了（`merge_apostrophe_variants` 的判据）
    # 🔴 **必须在 Python 里用字典做，不能写 SQL 自连接。**
    #    原来写的是 `JOIN dict b ON replace(a.word,…)=replace(b.word,…)` ——
    #    两侧都是函数结果，**没有任何索引能服务** ⇒ 149 万 × 149 万，十分钟不出结果。
    #    今天这是同一个坑的第三次（`lower()` 自连接跑过 33 分钟、`LIKE '%x'` 一次）。
    #    ⇒ 一次全表扫进字典，O(n)，实测 6 秒。
    if trace:
        print("      · C4…", flush=True)
    has_sense = {i for (i,) in con.execute("SELECT DISTINCT word_id FROM sense")}
    folded = {}
    for wid, w in con.execute("SELECT id, word FROM dict"):
        folded.setdefault(w.translate(APOSTROPHES), []).append((wid, w))
    n = sum(1 for ids in folded.values()
            if len(ids) > 1
            and sum(1 for wid, w in ids if wid in has_sense) > 1
            and any("’" in w for wid, w in ids))
    out.append(("C4", "merge_apostrophe_variants.py", "08-17", "撇号异写的两行又都带义项",
                n, n))

    # C5：`word_norm` 没按现行规则归一（`backfill_word_norm` 的判据 = 重算一遍）
    if trace:
        print("      · C5…", flush=True)
    bad = sum(1 for w, wn in con.execute("SELECT word, word_norm FROM dict") if norm(w) != wn)
    out.append(("C5", "backfill_word_norm.py", "08-17", "word_norm 与现行归一规则对不上",
                bad, bad))

    # C6：词头 gender=mf 而义项只有单一性别（`fix_folded_gender` 的判据）
    if trace:
        print("      · C6…", flush=True)
    n2 = con.execute("""
        SELECT count(*) FROM dict d WHERE d.gender='mf' AND (
          SELECT count(DISTINCT COALESCE(s.gender,'')) FROM sense s
           WHERE s.word_id=d.id AND s.gender IS NOT NULL)=1
          AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id AND s.gender='mf')
        """).fetchone()[0]
    out.append(("C6", "fix_folded_gender.py", "08-17", "词头 mf 而义项只有单一性别",
                n2, n2))

    # C7：wiktextract 的交叉引用义项又露出来了
    # 🔴 判据**必须与修复脚本共用**（`hide_see_also_residue.scan`）：
    #    「以 see 开头」这种写法会误伤真释义 —— `sede` 的 `see (of a bishop)`（主教教区）、
    #    `a più tardi` 的 `see you later`。可验证的判据是「See X 里的 X 确实是库里的词形」。
    if trace:
        print("      · C7…", flush=True)
    from hide_see_also_residue import scan as see_scan
    hide, keep = see_scan(con)
    n3 = len(hide)
    out.append(("C7", "hide_see_also_residue.py", "08-18", "交叉引用义项又露在出版层",
                n3, n3))

    # C8：`inflection.entry_id` 的语义 —— **必须指向原形的那个词条**（阶段 8 定死）。
    # 🔴 这一列曾经按来源分裂成两套语义（en 版指变形形自己、fr 版指原形），
    #    展示层当时还不读它 ⇒ 查库看不出任何异常。断言写成结构性的：
    #    非空的 entry_id 只要有一条不属于 `base_id`，就是又分裂了。
    #    写入侧＝全表，读取侧＝将来展示层要用的那批（原形有多个词条、必须区分的）。
    if trace:
        print("      · C8 变形层 entry_id 语义…", flush=True)
    wrong = lambda extra: con.execute(
        "SELECT count(*) FROM inflection i JOIN entry e ON e.id=i.entry_id "
        "WHERE e.word_id <> i.base_id " + extra).fetchone()[0]
    out.append(("C8", "repoint_inflection_entry.py", "08-18", "变形层 entry_id 不指向原形词条",
                wrong(""),
                wrong("AND (SELECT count(*) FROM entry e2 WHERE e2.word_id=i.base_id) > 1")))

    # ══ D 组：2026-08-21 点测评审 ═════════════════════════════════════════
    # D1 关系目标里的括号残渣。判据 **import `fix_unclosed_paren.classify`**，不另写。
    # 🔴 读取侧要按 `hidden` 过滤，而那列是修复脚本 ALTER 出来的 ⇒ 先探 schema 再取数，
    #    否则建列之前这道闸自己会抛 OperationalError（闸挂了比闸红了更糟）。
    if trace:
        print("      · D1 括号残渣…", flush=True)
    rel_cols = {r[1] for r in con.execute("PRAGMA table_info(sense_relation)")}
    read_sql = ("SELECT target FROM sense_relation WHERE COALESCE(hidden,0)=0"
                if "hidden" in rel_cols else "SELECT target FROM sense_relation")
    out.append(("D1", "fix_unclosed_paren.py", "08-21", "关系目标里的括号残渣（切分切碎的）",
                sum(1 for t in texts(con, "SELECT target FROM sense_relation") if paren_class(t)),
                sum(1 for t in texts(con, read_sql) if paren_class(t))))

    # D3 变形提示重复。🔴 **写入侧与读取侧必然不同，这正是要点**：
    #    `inflQuery`（italian.ts:406）只投影 `base, label_zh` 两列 —— 别的列不一样、
    #    这两列一样的行，落到页面上就是**一模一样的三行**（`una` 的「uno 的 单数」×3）。
    #    ⇒ 读取侧只按投影后的两列判重，写入侧按全列。读取侧必然 ≥ 写入侧。
    if trace:
        print("      · D3 变形提示重复…", flush=True)
    dup_write = con.execute("""
        SELECT COALESCE(SUM(k-1),0) FROM (
          SELECT COUNT(*) k FROM inflection
           GROUP BY word_id, base, base_id, label_zh, desc_en, tags, src
          HAVING k>1)""").fetchone()[0]
    dup_read = con.execute("""
        SELECT COALESCE(SUM(k-1),0) FROM (
          SELECT COUNT(*) k FROM inflection
           GROUP BY word_id, base, label_zh HAVING k>1)""").fetchone()[0]
    out.append(("D3", "dedupe_inflection.py", "08-21", "变形提示在页面上重复成多行",
                dup_write, dup_read))

    # D4 搭配重复（`colsQuery` italian.ts:438 按 word_id 取 text）
    if trace:
        print("      · D4 搭配重复…", flush=True)
    col_dup = con.execute("""
        SELECT COALESCE(SUM(k-1),0) FROM (
          SELECT COUNT(*) k FROM collocation GROUP BY word_id, text HAVING k>1)""").fetchone()[0]
    out.append(("D4", "dedupe_collocation.py", "08-21", "同一个词的搭配重复出现",
                col_dup, col_dup))

    # D5 词头徽标属性归属不明却照显示。
    # 🔴 这条是**纯展示层**缺陷：数据本身没错，`la` 作名词（音名「拉」）确实是阳性。
    #    错在 `dict.pos` 是**词形级**的斜杠串（`contr/n/v`），`App.tsx:1685` 的
    #    `isNoun = entry.pos.split('/').some(p => p==='n')` 只要有一个名词用法就为真，
    #    于是把只对某一个词条成立的性/复数顶到了整词的头上。
    #    ⇒ **修法在读取侧**（多词性就不显示），所以写入侧会一直非零、必须进 ACCEPT；
    #      读取侧修完应当归零。这正是「写入列 vs 读取路径」两侧分开量的价值。
    if trace:
        print("      · D5 词头徽标归属…", flush=True)
    # 判据经过**两次收窄**，两次都是被更严的证据打回来的：
    #   ① 「`dict.pos` 斜杠串有 ≥2 个成分」→ 16,599。太宽：`acqua` 的 `n/v` 里那个 v
    #      来自 `acquare` 的变位形、一条可见义项都没有，它的「阴性 复数 acque」是对的。
    #   ② 「**有可见义项**的词条覆盖 ≥2 种词性」→ 7,527。**还是太宽**：契约闸逮到 92 处
    #      回归 —— `cecchino`(noun+name)、`sagro`(adj+noun) 的复数形全没了。意语里
    #      **名词/专名/形容词共享性数系统**，它们之间不冲突。
    # ⇒ 现在的定义（与 `App.tsx` 的守卫逐字对应）：
    #      性/复数/单复同形：`scope` 非空且**混进了非 NOMINAL 词类**才算归属不明
    #      助动词/变位类：只可能属于动词 ⇒ `scope` 非空且**不含 verb** 才算
    NOMINAL = {"noun", "name", "adj"}
    scope = {}
    for wid, pos in con.execute("""
            SELECT e.word_id, e.pos FROM entry e
             WHERE EXISTS(SELECT 1 FROM sense s
                           WHERE s.entry_id=e.id AND COALESCE(s.hidden,0)=0)"""):
        scope.setdefault(wid, set()).add(pos)
    n5 = 0
    for wid, gender, plural, note, aux, conj in con.execute(
            "SELECT id, gender, plural, number_note, aux, conj FROM dict"):
        sc = scope.get(wid)
        if not sc:
            continue                       # 没有自己的义项（纯变形形）⇒ 无冲突证据
        if (gender or plural or note) and not sc <= NOMINAL:
            n5 += 1
        elif (aux or conj) and "verb" not in sc:
            n5 += 1
    out.append(("D5", "App.tsx 词头徽标守卫", "08-21", "词头徽标属性归属不明却照显示",
                n5, n5))

    # D6 自反形式被说成「不是同一个词」。
    #    `sentirsi` 就**是** `sentire` 的自反形式（tags 里明写 form-of/reflexive），
    #    而变位区块的开场白是「下面这些与上面的释义**不是同一个词**」—— 措辞与数据矛盾。
    #    判据取 tags 而不是 desc_en：tags 是结构化的，desc_en 是自由文本。
    if trace:
        print("      · D6 自反形式措辞…", flush=True)
    refl = con.execute("""
        SELECT COUNT(*) FROM inflection
         WHERE tags LIKE '%"reflexive"%' AND tags LIKE '%"form-of"%'""").fetchone()[0]
    out.append(("D6", "App.tsx 变位区块措辞", "08-21", "自反形式被写成「不是同一个词」",
                refl, refl))

    # D7 音标位上根本不是音标的值（`*` / 只剩一个 `ː`）。
    # 🔴 其中 3 条是**主音标**，用户直接看到 `/*/`。判据 import 修复脚本那一份 ——
    #    它是**反着定义**的（列标记符号，不列音段白名单）：第一版用白名单
    #    漏掉了 ɾ/ʔ/ə/ɜ，把 `r`→`ɾ`、`ah`→`ʔ` 这些真音标判成垃圾，17 条里误伤 9 条。
    if trace:
        print("      · D7 音标位上的垃圾…", flush=True)
    pron_cols = {r[1] for r in con.execute("PRAGMA table_info(pronunciation)")}
    pr_read = ("SELECT ipa FROM pronunciation WHERE COALESCE(hidden,0)=0"
               if "hidden" in pron_cols else "SELECT ipa FROM pronunciation")
    out.append(("D7", "hide_junk_pronunciation.py", "08-21", "音标位上不是音标的值",
                sum(1 for t in texts(con, "SELECT ipa FROM pronunciation") if is_junk_ipa(t)),
                sum(1 for t in texts(con, pr_read) if is_junk_ipa(t))))

    # D8 有可见读音、却没有（或有多条）默认读音 —— 藏掉主音标后忘了重选就会这样，
    #    展示层 `readings.find(isPrimary)` 落空，整个词的音标行消失。
    if trace:
        print("      · D8 默认读音唯一性…", flush=True)
    if "hidden" in pron_cols:
        n8 = con.execute("""
            SELECT COUNT(*) FROM (
              SELECT word_id, SUM(CASE WHEN is_primary=1 THEN 1 ELSE 0 END) k
                FROM pronunciation WHERE COALESCE(hidden,0)=0 GROUP BY word_id HAVING k<>1)
            """).fetchone()[0]
    else:
        n8 = 0
    out.append(("D8", "hide_junk_pronunciation.py", "08-21", "有可见读音却没有唯一的默认读音",
                n8, n8))

    # D9 人工裁决过的中文被盖回去了。
    # 🔴 这四条是**逐条回源证实**的跨版错配修正（`treno` 首义漏「火车」、`libro` 的
    #    「叶片」、`fare` 的「赠送」方向反了）。它们写在 `sense_gloss` 上，
    #    而重译脚本会整批覆盖那一列 —— `replay-scripts-undo-fixes` 记的正是这个形状：
    #    `UNIQUE` 保证不重复，**不保证不倒退**。
    # 判据 import 修复脚本的名单，不另抄一份。
    if trace:
        print("      · D9 人工裁决的中文…", flush=True)
    def xed(where):
        n = 0
        for sid, (w, _old, new_zh, _why) in XED_REWRITE.items():
            row = con.execute(
                "SELECT g.text FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
                "WHERE g.sense_id=? AND g.lang='zh' AND g.seq=0 " + where, (sid,)).fetchone()
            if not row or row[0] != new_zh:
                n += 1
        return n
    out.append(("D9", "fix_cross_edition_sense.py", "08-21", "人工裁决过的中文被盖回去了",
                xed(""), xed("AND COALESCE(s.hidden,0)=0 AND g.kind='equivalent'")))
    return out


def run(con, trace=False):
    """跑全部断言。`trace=True` 时逐条打进度 —— 卡住时能直接看出是哪一条。

    ⚠️ 2026-08-18 加 trace 就是因为吃过这个亏：整个脚本十分钟不出结果，
       而每条判据单独计时都只要 1 秒。没有进度输出时，"卡在哪"只能靠猜。
    """
    import time
    rows = []
    for cid, script, date, name, wsql, rsql, hit in checks():
        if hit is None:
            continue                     # 交给 special()
        t0 = time.time()
        nw = sum(1 for t in texts(con, wsql) if hit(t))
        nr = sum(1 for t in texts(con, rsql) if hit(t))
        if trace:
            print("      · %-4s %-30s %5.1fs" % (cid, name[:30], time.time() - t0), flush=True)
        rows.append((cid, script, date, name, nw, nr))
    t0 = time.time()
    sp = special(con, trace=trace)
    if trace:
        print("      · special() 合计 %.1fs" % (time.time() - t0), flush=True)
    for cid, script, date, name, nw, nr in sp:
        rows.append((cid, script, date, name, nw, nr))
    return sorted(rows)


def report(con, verbose=True, trace=False):
    """→ [(编号, 名称, 说明)]，只含**超出基线**的。"""
    red = []
    if verbose:
        print("═══ 回归闸：过去的修复现在还在不在 ═══")
        print("   %-5s %-34s %10s %10s" % ("", "缺陷", "写入侧", "读取侧"))
    for cid, script, date, name, nw, nr in run(con, trace=trace):
        base_w = ACCEPT.get(cid + ":write", 0)
        base_r = ACCEPT.get(cid + ":read", 0)
        bad_w = base_w is not None and nw > base_w
        bad_r = base_r is not None and nr > base_r
        # 🔴 「被绕过」的形状：写入侧干净、读取侧有货
        # ⚠️ 少数断言的读取侧**天然**比写入侧大，那不是被绕过，是判据本身的形状：
        #    D3 的写入侧按全列判重（431），读取侧按 `inflQuery` 投影后的两列判重（2,428）——
        #    「别的列不同、页面上却是同一句话」正是它要查的东西。这类要**显式豁免**，
        #    不能靠把两侧的判据改成一样来消红（那会把真正的信息抹掉）。
        bypass = nr > nw and ACCEPT.get(cid + ":bypass") != "ok"
        mark = "🔴" if (bad_w or bad_r or bypass) else "✅"
        if verbose:
            print("   %s %-5s %-34s %10s %10s%s"
                  % (mark, cid, name[:34], f(nw), f(nr), "  ← 写入侧干净但读取侧有货！" if bypass else ""))
        if bad_w or bad_r:
            red.append((cid, name, "写入侧 %s / 读取侧 %s（基线 %s / %s）"
                        % (f(nw), f(nr), base_w, base_r)))
        elif bypass:
            red.append((cid, name, "🔴 被绕过：写入侧 %s、读取侧 %s" % (f(nw), f(nr))))
    if verbose:
        print("\n   %s" % ("✅ 全部通过" if not red else "🔴 %d 条要看" % len(red)))
    return red


def check_brief():
    """给 `dbtool._regression_check` 用：静默跑，只回报红的。"""
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    try:
        return report(con, verbose=False)
    finally:
        con.close()


def mutate(only=()):
    """⭐ 变异验证：在**备份副本**上把每一族缺陷各造一条，闸必须逐条报出来。

    `only`：只跑这几条（如 `("D4","D5")`）。每条变异都要复制 1.1 GB 的库再跑全部判据，
    全量一轮二十多分钟 —— 修好一条变异就为它重跑全部，是不必要的等待。
    ⚠️ 但**合入前必须完整跑一遍**：`only` 是调试用的，不是验收口径。

    一条永远通过的检查等于没检查 —— 这里就是证明它会失败的地方。

    🔴 2026-08-21 重写判据。原来是 `got = bool(report(...))` ——「跑完还有红的就算逮住」。
       那在**全部断言基线都是 0** 时成立；D 组进来之后有 6 条常红（缺陷还没修），
       于是无论造什么变异、哪怕造在完全无关的表上，`bool(red)` 都为真 ⇒ **13/13 全过，
       而且是假的**。这与「闸写完必须变异验证」是同一个道理：变异验证自己也会变成摆设。
    ⇒ 改成**逐条比对**：每个变异声明它该触发哪条断言，只看**那一条**的数字有没有变大。
       顺带还能抓出「变异触发了别的断言」——那说明判据之间有串扰。
    """
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "m.sqlite"
    muts = [
        ("A1", "A1 音标里塞回定界符",
         "UPDATE dict SET ipa='/ˈka.sa/' WHERE word='casa'"),
        ("A3", "A3 音标里塞拉丁 g",
         "UPDATE dict SET ipa='ˈgat.to' WHERE word='gatto'"),
        ("A4", "A4 撇号冒充重音符（读取侧）",
         "UPDATE pronunciation SET ipa='''kaza' WHERE id=(SELECT id FROM pronunciation "
         "WHERE is_primary=1 LIMIT 1)"),
        ("A5", "A5 音节切分残渣（读取侧）",
         "UPDATE pronunciation SET ipa='su' WHERE id=(SELECT p.id FROM pronunciation p "
         "JOIN dict d ON d.id=p.word_id WHERE d.word='sudanese' LIMIT 1)"),
        ("B1", "B1 中文写成拉丁字母",
         "UPDATE sense_gloss SET text='house' WHERE rowid=(SELECT g.rowid FROM sense_gloss g "
         "JOIN sense s ON s.id=g.sense_id WHERE g.lang='zh' AND g.kind='equivalent' "
         "AND g.seq=0 AND COALESCE(s.hidden,0)=0 LIMIT 1)"),
        # ⚠️ 这条变异必须挑**词性确实是 adj** 的义项 —— 判据是「标签＝本义项词性」，
        #    随便挑一条加「（形容词）」造不出缺陷，第一版就是这么把变异做废的（9/10）。
        ("B2", "B2 释义带回词性标签（挑 adj 义项）",
         "UPDATE sense_gloss SET text=text||'（形容词）' WHERE rowid=(SELECT g.rowid "
         "FROM sense_gloss g JOIN sense s ON s.id=g.sense_id WHERE g.lang='zh' "
         "AND g.kind='equivalent' AND g.seq=0 AND COALESCE(s.hidden,0)=0 "
         "AND s.pos='adj' LIMIT 1)"),
        ("B3", "B3 占位符回到出版层",
         "UPDATE sense_gloss SET text='definizione mancante; se vuoi, aggiungila tu' "
         "WHERE rowid=(SELECT g.rowid FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
         "WHERE g.lang='it' AND g.kind='definition' AND COALESCE(s.hidden,0)=0 LIMIT 1)"),
        ("C1", "C1 sense.pos 写回长写法",
         "UPDATE sense SET pos='adjective' WHERE id=(SELECT id FROM sense WHERE pos IS NOT NULL LIMIT 1)"),
        ("C3", "C3 塞一条构词公式当例句",
         "INSERT INTO example (word,text,src) VALUES ((SELECT word FROM example LIMIT 1),"
         "'ragazzo (“boy”) + -one → ragazzone (“big boy”)','en-edition')"),
        ("C5", "C5 word_norm 改坏一行",
         "UPDATE dict SET word_norm='ZZZ' WHERE word='casa'"),
        ("C8", "C8 变形层 entry_id 指回变形形自己",
         "UPDATE inflection SET entry_id=(SELECT e.id FROM entry e WHERE e.word_id="
         "inflection.word_id LIMIT 1) WHERE id=(SELECT i.id FROM inflection i "
         "WHERE i.base_id IS NOT NULL AND EXISTS(SELECT 1 FROM entry e WHERE "
         "e.word_id=i.word_id) LIMIT 1)"),
        ("C7", "C7 wiktextract 残渣放回出版层",
         "UPDATE sense SET hidden=0 WHERE id=(SELECT s.id FROM sense s JOIN sense_gloss g "
         "ON g.sense_id=s.id WHERE g.lang='en' AND g.text LIKE 'see %' AND s.hidden=1 LIMIT 1)"),
        ("A1", "🔴 被绕过：写入列干净、读取路径有货",
         "UPDATE pronunciation SET ipa='/ˈka.sa/' WHERE is_primary=1 AND word_id="
         "(SELECT id FROM dict WHERE word='casa')"),
        # ── D 组（2026-08-21）──────────────────────────────────────────
        # ⚠️ 变异必须挑**目前不在缺陷集里**的行。第一版 `LIMIT 1` 取到的那行本来
        #    就带断括号，改成另一个断括号后数字纹丝不动 ⇒ 报「没逮住」，而闸是好的。
        #    这是「变异没造出新缺陷」，不是「闸是摆设」—— 两者报出来一模一样，
        #    所以变异没触发时**先查变异对不对**。
        ("D1", "D1 关系目标塞一个断括号",
         "UPDATE sense_relation SET target='kiwi australe (' WHERE id="
         "(SELECT id FROM sense_relation WHERE kind<>'alt_of' "
         " AND target NOT LIKE '%(%' AND target NOT LIKE '%)%' LIMIT 1)"),
        ("D2", "D2 变形原形塞回英文 and",
         "UPDATE inflection SET base='avere and' WHERE id="
         "(SELECT id FROM inflection WHERE base NOT LIKE '% and%' LIMIT 1)"),
        # ⚠️ D3 的变异必须**照抄投影后的两列**再插一行：只改 desc_en/src 之类
        #    不参与 `inflQuery` 投影的列，页面上根本看不出重复，也就造不出这个缺陷。
        # 🔴 `src_ref` 有 UNIQUE 约束，照抄会 IntegrityError ⇒ 给它一个新值。
        #    这反而更贴近真实：**写入侧（全列判重）不会涨、只有读取侧涨** ——
        #    正是「其他列不同、投影后一样」那 1,997 行的形状。
        ("D3", "D3 复制一行变形提示（word_id/base/label_zh 全同，src_ref 另给）",
         "INSERT INTO inflection (word_id,entry_id,base,base_id,label_zh,desc_en,tags,src,src_ref) "
         "SELECT word_id,entry_id,base,base_id,label_zh,desc_en,tags,src,src_ref||':mut' "
         "FROM inflection WHERE label_zh IS NOT NULL AND label_zh<>'' LIMIT 1"),
        # 🔴 `collocation` 有 UNIQUE(word_id, rank)，照抄 rank 会 IntegrityError ⇒ 另给一个。
        ("D4", "D4 复制一条搭配（rank 另给）",
         "INSERT INTO collocation (word_id,sense_id,text,rank) "
         "SELECT word_id,sense_id,text,9999 FROM collocation "
         "WHERE NOT EXISTS(SELECT 1 FROM collocation c2 WHERE c2.word_id=collocation.word_id "
         "AND c2.rank=9999) LIMIT 1"),
        # ⚠️ 变异必须打在**判据真正读的东西**上。第一版改的是 `dict.pos`，
        #    而收窄后的判据看的是「有可见义项的 entry.pos 集合」，压根不读 dict.pos
        #    ⇒ 改了也不动数字。判据一变，它的变异就得跟着变，否则闸又变成摆设。
        #    这里挑一个**目前 scope 全是名词**、且带 gender 的词，把它的 entry
        #    改成动词 ⇒ scope 混进非 NOMINAL，性/复数徽标立刻归属不明。
        ("D5", "D5 让一个纯名词词的词条变成动词（性/复数归属立刻不明）",
         "UPDATE entry SET pos='verb' WHERE id=(SELECT e.id FROM entry e "
         "JOIN dict d ON d.id=e.word_id "
         "WHERE d.gender IS NOT NULL AND d.gender<>'' "
         "AND EXISTS(SELECT 1 FROM sense s WHERE s.entry_id=e.id AND COALESCE(s.hidden,0)=0) "
         "AND (SELECT COUNT(DISTINCT e2.pos) FROM entry e2 WHERE e2.word_id=d.id "
         "     AND e2.pos IN ('noun','name','adj') "
         "     AND EXISTS(SELECT 1 FROM sense s2 WHERE s2.entry_id=e2.id "
         "                AND COALESCE(s2.hidden,0)=0))=1 "
         "AND NOT EXISTS(SELECT 1 FROM entry e3 WHERE e3.word_id=d.id "
         "               AND e3.pos NOT IN ('noun','name','adj') "
         "               AND EXISTS(SELECT 1 FROM sense s3 WHERE s3.entry_id=e3.id "
         "                          AND COALESCE(s3.hidden,0)=0)) LIMIT 1)"),
        ("D7", "D7 把一条主音标改成 *",
         "UPDATE pronunciation SET ipa='*' WHERE id=(SELECT id FROM pronunciation "
         "WHERE is_primary=1 AND COALESCE(hidden,0)=0 LIMIT 1)"),
        # ⚠️ 造「没有默认读音」要挑**还有别的可见读音**的词，否则藏完那个词一条都不剩、
        #    分母是 0，`HAVING k<>1` 也就不会命中。
        ("D8", "D8 把一个词的默认读音降级（该词还有别的读音）",
         "UPDATE pronunciation SET is_primary=0 WHERE id=(SELECT p.id FROM pronunciation p "
         "WHERE p.is_primary=1 AND COALESCE(p.hidden,0)=0 AND (SELECT COUNT(*) FROM pronunciation q "
         "WHERE q.word_id=p.word_id AND COALESCE(q.hidden,0)=0)>1 LIMIT 1)"),
        ("D9", "D9 把人工裁决过的中文盖回旧值",
         "UPDATE sense_gloss SET text='（人或物的）系列，行列' "
         "WHERE sense_id=12064 AND lang='zh' AND seq=0"),
        ("D6", "D6 给一行变形打上 reflexive 标签",
         "UPDATE inflection SET tags='[\"form-of\", \"reflexive\"]' WHERE id="
         "(SELECT id FROM inflection WHERE tags NOT LIKE '%reflexive%' LIMIT 1)"),
    ]
    if only:
        muts = [m for m in muts if m[0] in only]
        print("⚠️ 只跑 %s —— 这是调试口径，合入前要完整跑一遍" % ",".join(only))
    print("═══ 变异验证：每族各造一条，闸必须报出来 ═══")
    con0 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    base = {cid: (nw, nr) for cid, _s, _d, _n, nw, nr in run(con0)}
    con0.close()
    caught = 0
    for cid, name, sql in muts:
        shutil.copy(paths.DB, tmp)
        c2 = sqlite3.connect(tmp)
        c2.execute(sql)
        c2.commit()
        after = {c: (w, r) for c, _s, _d, _n, w, r in run(c2)}
        c2.close()
        # 🔴 只看**声明的那一条**有没有变大：基线非零时 `bool(red)` 恒真、等于没测。
        got = after.get(cid, (0, 0)) > base.get(cid, (0, 0))
        caught += got
        others = [c for c in after if c != cid and after[c] > base.get(c, (0, 0))]
        print("   %s %-52s %s→%s%s"
              % ("✅ 逮住" if got else "🔴 没逮住", name,
                 base.get(cid), after.get(cid),
                 ("  ⚠️ 同时触发 " + ",".join(others)) if others else ""))
    print("\n   变异验证 %s（%d/%d）"
          % ("通过" if caught == len(muts) else "🔴 有闸是摆设", caught, len(muts)))
    return caught == len(muts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", default="", help="只跑这几条变异，逗号分隔（调试用）")
    a = ap.parse_args()
    if a.mutate:
        only = tuple(x.strip() for x in a.only.split(",") if x.strip())
        return 0 if mutate(only) else 1
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    red = report(con, trace=True)
    con.close()
    return 0 if not red else 1


if __name__ == "__main__":
    sys.exit(main())
