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
    ]


def special(con, trace=False):
    """判据需要「文本 + 别的列」才成立的，单独查；同样跑写入侧与读取侧两遍。"""
    out = []

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
        bypass = nr > nw
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


def mutate():
    """⭐ 变异验证：在**备份副本**上把每一族缺陷各造一条，闸必须逐条报出来。

    一条永远通过的检查等于没检查 —— 这里就是证明它会失败的地方。
    """
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "m.sqlite"
    muts = [
        ("A1 音标里塞回定界符",
         "UPDATE dict SET ipa='/ˈka.sa/' WHERE word='casa'"),
        ("A3 音标里塞拉丁 g",
         "UPDATE dict SET ipa='ˈgat.to' WHERE word='gatto'"),
        ("A4 撇号冒充重音符（读取侧）",
         "UPDATE pronunciation SET ipa='''kaza' WHERE id=(SELECT id FROM pronunciation "
         "WHERE is_primary=1 LIMIT 1)"),
        ("A5 音节切分残渣（读取侧）",
         "UPDATE pronunciation SET ipa='su' WHERE id=(SELECT p.id FROM pronunciation p "
         "JOIN dict d ON d.id=p.word_id WHERE d.word='sudanese' LIMIT 1)"),
        ("B1 中文写成拉丁字母",
         "UPDATE sense_gloss SET text='house' WHERE rowid=(SELECT g.rowid FROM sense_gloss g "
         "JOIN sense s ON s.id=g.sense_id WHERE g.lang='zh' AND g.kind='equivalent' "
         "AND g.seq=0 AND COALESCE(s.hidden,0)=0 LIMIT 1)"),
        # ⚠️ 这条变异必须挑**词性确实是 adj** 的义项 —— 判据是「标签＝本义项词性」，
        #    随便挑一条加「（形容词）」造不出缺陷，第一版就是这么把变异做废的（9/10）。
        ("B2 释义带回词性标签（挑 adj 义项）",
         "UPDATE sense_gloss SET text=text||'（形容词）' WHERE rowid=(SELECT g.rowid "
         "FROM sense_gloss g JOIN sense s ON s.id=g.sense_id WHERE g.lang='zh' "
         "AND g.kind='equivalent' AND g.seq=0 AND COALESCE(s.hidden,0)=0 "
         "AND s.pos='adj' LIMIT 1)"),
        ("B3 占位符回到出版层",
         "UPDATE sense_gloss SET text='definizione mancante; se vuoi, aggiungila tu' "
         "WHERE rowid=(SELECT g.rowid FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
         "WHERE g.lang='it' AND g.kind='definition' AND COALESCE(s.hidden,0)=0 LIMIT 1)"),
        ("C1 sense.pos 写回长写法",
         "UPDATE sense SET pos='adjective' WHERE id=(SELECT id FROM sense WHERE pos IS NOT NULL LIMIT 1)"),
        ("C3 塞一条构词公式当例句",
         "INSERT INTO example (word,text,src) VALUES ((SELECT word FROM example LIMIT 1),"
         "'ragazzo (“boy”) + -one → ragazzone (“big boy”)','en-edition')"),
        ("C5 word_norm 改坏一行",
         "UPDATE dict SET word_norm='ZZZ' WHERE word='casa'"),
        ("C8 变形层 entry_id 指回变形形自己",
         "UPDATE inflection SET entry_id=(SELECT e.id FROM entry e WHERE e.word_id="
         "inflection.word_id LIMIT 1) WHERE id=(SELECT i.id FROM inflection i "
         "WHERE i.base_id IS NOT NULL AND EXISTS(SELECT 1 FROM entry e WHERE "
         "e.word_id=i.word_id) LIMIT 1)"),
        ("C7 wiktextract 残渣放回出版层",
         "UPDATE sense SET hidden=0 WHERE id=(SELECT s.id FROM sense s JOIN sense_gloss g "
         "ON g.sense_id=s.id WHERE g.lang='en' AND g.text LIKE 'see %' AND s.hidden=1 LIMIT 1)"),
        ("🔴 被绕过：写入列干净、读取路径有货",
         "UPDATE pronunciation SET ipa='/ˈka.sa/' WHERE is_primary=1 AND word_id="
         "(SELECT id FROM dict WHERE word='casa')"),
    ]
    print("═══ 变异验证：每族各造一条，闸必须报出来 ═══")
    caught = 0
    for name, sql in muts:
        shutil.copy(paths.DB, tmp)
        c2 = sqlite3.connect(tmp)
        c2.execute(sql)
        c2.commit()
        red = report(c2, verbose=False)
        c2.close()
        got = bool(red)
        caught += got
        print("   %s %s" % ("✅ 逮住" if got else "🔴 没逮住", name))
    print("\n   变异验证 %s（%d/%d）"
          % ("通过" if caught == len(muts) else "🔴 有闸是摆设", caught, len(muts)))
    return caught == len(muts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    red = report(con, trace=True)
    con.close()
    return 0 if not red else 1


if __name__ == "__main__":
    sys.exit(main())
