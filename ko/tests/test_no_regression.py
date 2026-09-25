#!/usr/bin/env python3
"""ko 回归闸 —— 过去每个修复现在还在不在。2026-09-21。

`dbtool._regression_check()` **每次写库之后自动调用** `check_brief()`。
⚠️ 它只报不拦（写库已经 commit，回归闸要读最终状态才准），
   但它让回归在**产生它的那次写库**上报出来，而不是十天后偶然撞见。

═══ 🔴 为什么阶段 2 就建，而计划表写的是阶段 8 ═══
`PLAYBOOK` 7.4：**闸和修复同时做**。阶段 2 这一轮里，有四条缺陷
**全部是抽样或手查逮到的，回核一条都没响**：

    · 变形层 31,896 行冗余（`요요하다` 的每个变形存了 11 遍）—— 八条回核全绿
    · `past: 가까왔다` / `interrogative` 这类**表头文字**写进了 `dict.word`
    · `hanja_reading` 同样的冗余 3,114 行（同一个病、我只在变形层修了）
    · 无 gloss 义项上的 313 条关系被整条跳过

⇒ 把它们**逐条钉死**在这儿。一条永远通过的检查等于没检查，所以每条都写明
  「它当初是怎么坏的」，改判据时能对照着想清楚。

跑：`python3 ko/tests/test_no_regression.py`
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import re
import sqlite3

import paths
from coverage import BLANK_SQL, blank_sample


# (编号, 名称, SQL, 期望值, 当初是怎么坏的)
CHECKS = [
    # 🔴 **已接受基线 6**。基线变过一次，**原因必须写明白**：
    #
    #    23 → 6 不是"修好了 17 个"，是**口径变了** —— 阶段 3 做完之后，
    #    `coverage.py` 的判据里加进了第 ⑦ 条「有读音」，于是那 17 个
    #    「只有 sounds 的谚文词」（되넘기 모전 위주 지게문…）不再算空白页。
    #    ⚠️ 若不写这句，下一个人会以为是哪次修复的功劳（`[[ledger-numbers-lie]]`）。
    #
    #    剩下的 6 个，逐个说得清（🔴 2026-09-24 **改正了成员名单**，见下）：
    #      5 个汉字（㐹 䎚 乜 寭 醯）—— eumhun 的音节不在 dict 里（48 条那批）
    #      1 个 `靈棋經`（`pos=name`，中文版收来的汉字书名）
    #
    #    🔴🔴 **这段注释原来写的第 6 个是 `國際收支`，那是错的**（2026-09-24 逐条回库查出）。
    #    它有一条 `hanja_form_of → 국제수지` 的边，`src_ref` 是 `ko-edition:…#ptr:0`
    #    ——**来自阶段 4a 的指针收割**，也就是说写下这段注释的时候它就已经不空白了。
    #    数字（6）一直是对的，**解释是错的** —— 而错的解释比没有解释更坏：
    #    下一个人会拿着 `國際收支` 去找原因，找不到，然后怀疑这道闸
    #    （`[[ledger-numbers-lie]]`：账本上的数字与它的解释要分别核）。
    #    ⇒ 改基线时不只核数字，**成员名单也要当场重取一遍**。
    #    ⭐ **基线锁数字不锁名字**（`[[fix-regression-and-gate]]`）：变成 7 就红，
    #      哪怕换了一批词。**阶段 7（词源）做完要再降一次**，那时这段注释也要跟着改。
    ("R1", "空白页不超过已接受基线（点进去什么都没有的词形）", BLANK_SQL, 6,
     "阶段 2a 收了 5,955 个汉字词形，而它们的内容（hangeul 对应）要到 2d 才进库 ——"
     "中间那段时间库里有 5,952 个真空白页。判据见 `pipeline/coverage.py`，"
     "🔴 第一版漏了 `inflection.base_id`（原形被判成空白页）"),

    ("R2", "变形层没有冗余行",
     "SELECT COUNT(*) FROM (SELECT 1 FROM inflection "
     "GROUP BY base, word_id, tags HAVING COUNT(*)>1)", 0,
     "wiktextract 把同一张活用表解析多遍：第一版落库 31,896 行冗余（7.3%），"
     "`요요하다` 的每个变形存了 11 遍 —— **而八条写后回核一条都没红**"),

    ("R3", "汉字音层没有 (音节,汉字) 重复",
     "SELECT COUNT(*) FROM (SELECT 1 FROM hanja_reading "
     "GROUP BY word_id, hanja HAVING COUNT(*)>1)", 0,
     "与 R2 **同一个病**（同一块内容被解析多遍），3,114 行冗余。"
     "🔴 当时我只在变形层修了，这一层静静留着 —— 同一条判据要在所有层上一致"),

    ("R4", "`dict.word` 里没有表头文字/模板残留",
     "SELECT COUNT(*) FROM dict WHERE word LIKE '%{{{%' OR word LIKE '%: %' "
     "OR word GLOB '*[a-zA-Z]*' AND id > 57110", 0,
     "旧模板 `ko-conj-adj` 的解析残留：`past: 가까왔다`（表头前缀粘在词形上）、"
     "`interrogative`（表头文字当词形）、`{{{stem1}}}다`（模板变量没展开）。"
     "与 ja 阶段 2「扁平遍历 forms 看不见表」同形"),

    # 🔴🔴 这条第一版**判据写宽了，当场误伤 107 个真词条**：
    #    原判据是「有 pos ＋ 是某个词的变形形 ＋ 自己没有出版义项」，
    #    而 `귀여운`（`귀엽다` 的冠形形）、`걸어`、`가실` 这些**本身就是词条**
    #    （有 entry、有 sense_src），只是义项全是指针所以没有出版 `sense`。
    #    ⇒ 判据按**含义**重写：`pos` 是**词条**的属性，没有词条就不该有 pos。
    #      新判据命中 0，而它要守的东西一点没少。
    ("R5", "没有词条的词形不许有词性",
     "SELECT COUNT(*) FROM dict d WHERE d.pos IS NOT NULL "
     "AND NOT EXISTS(SELECT 1 FROM entry WHERE word_id=d.id)", 0,
     "变形形的词性是**原形的**，写在变形形上就是第二份真值（`SCHEMA` §10.4）。"
     "🔴 判据不能写成「是变形形且没义项」—— 那会误伤"
     "「本身是词条、恰好也是别人的变形形」的 107 个真词"),

    ("R6", "义项级关系确实取到了（不是只取词级）",
     "SELECT CASE WHEN (SELECT COUNT(*) FROM sense_relation "
     "  WHERE sense_id IS NOT NULL AND kind NOT IN ('hanja_form_of','alt_of')) "
     "  > 30000 THEN 0 ELSE 1 END", 0,
     "kaikki 把关系同时放在词级和义项级，ko 上义项级 46,492 条比词级还多。"
     "es 只取词级漏了 20,193 条，靠外锚闸才发现"),

    ("R7", "`sense_src` 的认领没有被清空",
     "SELECT CASE WHEN (SELECT COUNT(*) FROM sense_src WHERE sense_id IS NOT NULL) "
     "  > 40000 THEN 0 ELSE 1 END", 0,
     "ja 拖到阶段 1e 才回填这一列（此前两版全 NULL）。ko 从建库起就写，"
     "它被清空时这条会红"),

    # 🔴🔴 阶段 3 的真缺陷：第一版把 `entry_id`/`notation` 放进了背书聚合键，
    #    结果 `읽다` 的同一个读音存了 3 遍、**跨版背书整个失效**（只有 ko+zh 碰得到，
    #    因为它俩的 entry_id 都是 NULL）。修完 84,551 → 54,211 行，
    #    有跨版背书的 20,494 条（37.8%）。这条钉住"背书没有再次失效"。
    ("R9", "跨版背书有效（不是每版各存一行）",
     "SELECT CASE WHEN (SELECT COUNT(*) FROM pronunciation WHERE src LIKE '%+%') "
     "  > 15000 THEN 0 ELSE 1 END", 0,
     "背书是 `PLAYBOOK` 3.1 的核心（用本语种版给库内音标背书，不改值只记谁也这么写）。"
     "聚合键一旦含 `entry_id` 或 `notation`，跨版读音永远碰不到一起"),

    ("R10", "读音裸存（库里不许有定界符）",
     "SELECT COUNT(*) FROM pronunciation WHERE ipa LIKE '[%' OR ipa LIKE '/%'", 0,
     "八语种统一约定：裸存，展示层读 `notation` 决定加 [ ] 还是 / /。"
     "库里留定界符 ⇒ 页面上套两层括号"),

    ("R11", "读音层没有混进日语假名",
     "SELECT COUNT(*) FROM pronunciation WHERE hangeul_phonetic GLOB "
     "'*[ぁ-ゖァ-ヺ]*' OR ipa GLOB '*[ぁ-ゖァ-ヺ]*'", 0,
     "判据 7：韩文版的 `sounds[].other` 52 条 100% 是日语假名"
     "（`無料`→`むりょー`）。库里出现假名就是读错了字段"),

    # 🔴🔴 2026-09-25 阶段 9 接展示层时逮到的。**不是闸逮的，是把数据渲染出来看见的**：
    #    `를` 的读音印出来是 `4mL`` —— 那是 `ɾɯɭ` 的 **X-SAMPA**（用 ASCII 表 IPA）。
    #    日文版的 `sounds.ipa` 里混着这一套，收割器照单全收，98 行。
    #    ⚠️ 五道闸当时全绿，外锚闸双向恒等 —— **因为源头确实就这么写**。
    #      恒等式问「我们收得对不对」，问不了「源头给的是不是 IPA」。
    #    🔴 **fr 那轮逮到过 150 条一模一样的**（`absOlysjO~` = `absɔlysjɔ̃`），
    #      只修了 fr，教训没跨语种传过来 ⇒ 另六门落账 `BACKLOG` B10。
    #    ⭐ 判据必须用 `GLOB`：SQL 的 `LIKE '%_%'` 里 `_` 是通配符，
    #      我第一版用 LIKE，当场"命中"整库 298,951 行。
    ("R12", "读音层没有混进 X-SAMPA（冒充 IPA 的 ASCII 转写）",
     "SELECT COUNT(*) FROM pronunciation WHERE ipa GLOB '*[0-9`\\_]*'", 0,
     "IPA 不用 ASCII 数字/反引号/反斜杠/下划线，X-SAMPA 这四样全用。"
     "98 行已删（全部 `ja-edition`，且每个词形都另有正确 IPA 兜底）"),

    # 🔴 **渲染逮到的，闸一条都没响**：四套罗马字齐全、非空、全 ASCII、
    #    与词形一一对应 —— 所有**形式**判据都满足，只有**内容**是错的
    #    （`하다` 的罗马字与读音里存的是共享资源上那条录音的文件名）。
    #    源头就这么写（ko 版 16 条 sounds，只此一词），收割器原样收了。
    # 🔴🔴 **这条判据的范围改过一次**：第一版只查 `entry.roman_*` 四列，
    #    修完报绿 —— 然后把 `하다` 渲染出来，读音那行印着 `Ko[ha̠da̠].oga`。
    #    `pronunciation.ipa` 与 `hangeul_phonetic` 里躺着同一个文件名。
    #    **判据的范围跟着"我修了哪几列"走，而不是跟着"这个缺陷会落在哪儿"走**
    #    （`[[decision-not-propagated-across-editions]]`）。⇒ 改成扫**全库文本列**。
    # ⚠️ `audio` 表除外 —— 那里放文件名是对的。
    # ⚠️ R10「读音裸存」也没逮到它：R10 查的是以定界符**开头**，而它是 `Ko[…].oga`。
    ("R13", "音频文件名没有漏进内容列（全库文本列）", "@audio_filename_leak", 0,
     "`하다`（韩语最常用的动词）的罗马字曾是 `Ko-hada.oga`、读音曾是 `Ko[ha̠da̠].oga`。"
     "罗马字的正确值由库内 8,567 个 `*하다` 参照词定出（rr/translit/mr=hada、yale=hata）；"
     "读音那一行整条删掉（没有正确值可填，且 `하다` 另有跨三版背书的 `ha̠da̠`）"),

    # 🔴 **一个音频文件挂在多个词形上，而这些词的韩语读音没有交集 ⇒ 它不是其中任何一个的录音。**
    #    源头（中文版简繁两片）把 `Y.mp3` 挂在 **45 个**常用韩语词上（가다/학교/그리고…），
    #    另有 13 行是汉语/日语读音挂在汉字条目上（读者点 `士` 听到普通话 `shì`）。
    #    `[[dict-framework-doc]]`：**错比缺更伤权威** —— 宁可没有录音。
    # ⚠️ 判据**必须**写成「读音没有交集」而不是「挂在多个词形上」：后者会误伤三族
    #    正确的共用 —— `Ko-가.ogg.mp3` 挂在 7 个**韩语都读 가** 的汉字上（假價加可歌街駕）、
    #    `Ko-안따` 挂在同音词 안다/앉다 上、`Ko-있다` 挂在 잇다/잊다 上。
    #    第一版写成「非 `Ko-` 前缀就删」，**会误伤 969 行 Lingua Libre 韩语录音**（全库 58%）。
    ("R14", "没有张冠李戴的录音（一文件多词形且韩语读音无交集）",
     "@wrong_audio", 0,
     "`Y.mp3` 曾挂在 45 个常用词上；13 行汉语/日语读音曾挂在汉字条目上。"
     "删完有 13 个汉字条目一条录音都没有 —— 有意如此"),

    # 🔴 **一条释义里没有任何字母/数字 ⇒ 它不是释义。**
    #    日文版有 18 条 gloss 是空的维基内链 `[[]]。`，模型照规矩原样保留，
    #    于是页面上印出 `[[]]` 当释义 —— **比没有释义更糟**。
    #    另有 ko 版源头自带的 `?` / `.` 3 条、en/ko 那批译文 2 条，共 23 条。
    # ⚠️ 判据**交给 Unicode 答**（类别 `L*`/`N*`），不许手抄字符范围：
    #    我手写的那版漏掉 **CJK 扩展平面**，差点删掉 5 条正确的释义
    #    （`두브늄`→`𨧀`、`시보르귬`→`𨭎` —— 化学元素的汉字名，一个字就是完整释义）。
    ("R15", "出版层没有「没内容的释义」", "@empty_gloss", 0,
     "跑批 927/927、失败 0、定题 3/3、逐 id 点名一条不差 —— 过程指标全绿，"
     "而其中 18 条的**内容**是空的。闸问「有没有」，判官问「对不对」"),

    ("R8", "`entry.hanja` 没有被搬到 `dict` 上",
     "SELECT COUNT(*) FROM pragma_table_info('dict') WHERE name='hanja'", 0,
     "1,944 个词形对应 ≥2 个不同汉字（`양` → 壤/兩/良/陽/孃/洋/量/羊），"
     "放 `dict` 上等于对这 1,944 个词说谎"),
]


# 🔴 回归闸应该有多少条。**这个数是声明，不是数出来的** —— 见 `_audit_checks`。
R_ROSTER = 15


def _audit_checks():
    """🔴🔴 **闸自己的闸**：编号必须从 R1 起连续无缺口。

    2026-09-21 真事：改 R1 的基线时，一次字符串替换**把 R1 整条删掉了**，
    而闸照样报「全绿 10 条」—— **闸变绿是因为检查消失了，不是问题解决了**。
    ⚠️ 第一版判据是「编号从 1 起连续」，**逮不到删掉编号最大的那一条** ——
       少一条，上界跟着降，缺口自己消失。而末尾那条恰恰最容易被删。
       是 `test_plan_ledger` 的 P0 变异验证暴露的：同一个写法、同一个盲区。
       ⇒ 期望值必须**独立声明**（`R_ROSTER`），不能从现状推：
         拿现状推期望，现状坏了期望跟着坏。
    """
    # 🔴🔴 2026-09-21 二次修：原来写的是 `want = range(1, len(nums)+1)` ——
    #    **它逮不到删掉编号最大的那一条**（少一条，上界跟着降，缺口自己消失）。
    #    是 `test_plan_ledger` 的 P0 变异验证暴露的：同一个写法、同一个盲区。
    #    ⚠️ 而末尾那条恰恰最容易被删。⇒ 期望值必须**独立声明**，不能从现状推。
    nums = sorted(int(c[0][1:]) for c in CHECKS)
    want = list(range(1, R_ROSTER + 1))
    return [] if nums == want else [
        ("R0", "闸自己的条目有缺口",
         "现有编号 %s，应为 R1..R%d 连续 —— **有检查被删掉了**"
         % (["R%d" % n for n in nums], R_ROSTER))]


# 🔴 判据是 Python 正则，不是 SQL —— SQL 里把它翻译成 GLOB 字符类曾经**变宽**，
#    当场把 `창가림막` 的 `cʰaŋ.ga.rim.mag`（正确的按音节分隔 IPA）判成文件名。
#    ⇒ SQL 只做粗筛（`GLOB '*.*'`），**最终裁决由原判据做**。
_AUDIO_EXT = re.compile(r"\.(oga|ogg|mp3|wav|flac|m4a|opus)$", re.I)


def _audio_filename_leak(con):
    """全库文本列里有几处是音频文件名。`audio` 表除外（那里放文件名是对的）。"""
    n = 0
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        if t == "audio":
            continue
        for c in con.execute("PRAGMA table_info(%s)" % t):
            if not (c[2] or "").upper().startswith("TEXT"):
                continue
            try:
                rows = con.execute(
                    "SELECT %s FROM %s WHERE %s GLOB '*.*'" % (c[1], t, c[1]))
            except sqlite3.Error:
                continue
            n += sum(1 for r in rows if r[0] and _AUDIO_EXT.search(r[0]))
    return n


_FOREIGN_AUDIO = re.compile(r"^(Zh|Ja|En|Vi|Th|Yue|Cmn)-", re.I)
_AUDIO_NOISE = re.compile(r"[()\u02D0\u00B7\s]")


def _wrong_audio(con):
    """张冠李戴的录音有几行。判据与 `pipeline/fix_wrong_audio.py` 同一条。"""
    import collections
    rows = con.execute("SELECT id, word, file FROM audio").fetchall()
    bad = {i for i, _w, fn in rows if _FOREIGN_AUDIO.match(fn)}
    by = collections.defaultdict(list)
    for r in rows:
        by[r[2]].append(r)

    def readings(w):
        r = {x[0] for x in con.execute(
            "SELECT p.hangeul_phonetic FROM pronunciation p JOIN dict d ON d.id=p.word_id"
            " WHERE d.word_norm=? AND p.hangeul_phonetic IS NOT NULL", (w,))}
        r |= {x[0] for x in con.execute(
            "SELECT d.word FROM hanja_reading h JOIN dict d ON d.id=h.word_id"
            " WHERE h.hanja=?", (w,))}
        return {_AUDIO_NOISE.sub("", x) for x in r if x}

    for fn, rs in by.items():
        ws = {r[1] for r in rs}
        if len(ws) < 2:
            continue
        sets = [readings(w) for w in ws]
        if not (all(sets) and set.intersection(*sets)):
            bad |= {r[0] for r in rs}
    return len(bad)


def _empty_gloss(con):
    """出版层里「没有任何字母/数字」的释义有几条。判据与 `fix_empty_markup_gloss` 同一条。"""
    import unicodedata
    return sum(1 for r in con.execute("SELECT text FROM sense_gloss")
               if not any(unicodedata.category(c)[0] in ("L", "N")
                          for c in (r[0] or "")))


_FUNCS = {"@audio_filename_leak": _audio_filename_leak,
          "@wrong_audio": _wrong_audio,
          "@empty_gloss": _empty_gloss}


def check_brief():
    """→ [(编号, 名称, 说明), ...]，空列表＝全绿。`dbtool` 写库后调用它。"""
    gap = _audit_checks()
    if gap:
        return [(g[0], g[1], g[2]) for g in gap]
    if not paths.DB.exists():
        return []
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    red = []
    try:
        for cid, name, sql, want, why in CHECKS:
            try:
                got = (_FUNCS[sql](con) if sql in _FUNCS
                       else con.execute(sql).fetchone()[0])
            except sqlite3.Error as e:
                red.append((cid, name, "闸自己跑不起来：%s" % e))
                continue
            if got != want:
                red.append((cid, name, "得 %s，期望 %s —— %s" % (got, want, why)))
    finally:
        con.close()
    return red


if __name__ == "__main__":
    red = check_brief()
    if not red:
        print("■ ko 回归闸全绿 ✓（%d 条）" % len(CHECKS))
        sys.exit(0)
    print("🔴 ko 回归闸：%d 条红" % len(red))
    for cid, name, why in red:
        print("   %-4s %s\n        %s" % (cid, name, why))
    if any(c[0] == "R1" for c in red):
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        print("\n   空白页样本：%s" % blank_sample(con, 12))
        con.close()
    sys.exit(1)
