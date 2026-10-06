#!/usr/bin/env python3
"""**义项层闸（vi）** —— `sense_src` / `sense` / `sense_gloss` 对不对。2026-10-01。

判据 import 自 `criteria.py`，一条都不重写。

═══ ⭐ E5 是**读者口径**的那一条 ═══
「库里有 10 万条义项」说明不了读者打开一个词能不能看见释义。
E5 量的是**有多少词形至少有一条可出版释义**，下限锁住当前水平。

═══ 🔴 E7：证据层永不编辑 ═══
`[[two-layer-sense-model]]`：`sense_src` 是证据，`sense` 是出版。
被判为「只是汉字表记 / 指针 / 不是释义」的 33,615 条**必须还在 `sense_src` 里**，
只是 `sense_id` 为空。删掉它们＝判据哪天翻案也再找不回来。

═══ 🔴 E8：W2 那条判据必须**真的在起作用** ═══
`same-as-han-spelling` 隐藏了 22,225 条。如果这个数掉到 0，
意味着判据被改坏或汉字表记层空了 —— 而两种都会让中文释义栏开始印
页面上方早印着的那串汉字。**下限不是 0，是量级。**

用法：
    python3 vi/tests/test_sense_layer.py
    python3 vi/tests/test_sense_layer.py --mutate
"""
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import paths                                              # noqa: E402
from build_sense_layer import (HIDDEN_SPELLING, HIDDEN_POINTER,   # noqa: E402
                               HIDDEN_NOT_GLOSS)
from criteria import (gloss_has_content, is_vi_markup_gloss,       # noqa: E402
                      norm_vi, dup_sense_groups, DUP_SENSE_WHY)

_ABBREV = re.compile(r"^[A-Za-zÀ-ỹ]{1,5}\.$")
# 🔴 上界按 2026-10-02 实测写死：形式判据命中 30 条，其中 25 条进了枚举表、
#    剩 5 条是**真释义**（`Wien.` `Cuba.` `Tokyo.` `Ôtôca.` 与两条源头乱码）。
#    涨上去就说明源头加了新缩写 ⇒ 去读一眼再决定进不进表。
NEW_ABBREV_CEIL = 12

# 🔴 下限按 2026-10-01 实测写死，并注明是哪天、按什么量的（ACCEPT 锁数字不锁名字）
GLOSS_COVER_FLOOR = 75.0        # 实测 75.3%（50,204 / 66,657 个词形有可出版释义）
SPELLING_HIDDEN_FLOOR = 20000   # 实测隐藏 22,225 条「只是汉字表记」


def _markup_glosses(c):
    """🔴 判据 import 自 `criteria`（枚举表住在那儿）。"""
    return sum(1 for (t,) in c.execute(
        "SELECT g.text FROM sense s JOIN sense_gloss g ON g.sense_id=s.id "
        "WHERE s.hidden=0 AND g.lang='vi'") if is_vi_markup_gloss(t))


def _new_abbrev(c):
    """→ True ＝ 没有新的句点缩写型释义。**形式判据只用来发现，不用来删。**"""
    lex = {wn for (wn,) in c.execute("SELECT word_norm FROM dict")}
    n = 0
    for (t,) in c.execute("SELECT g.text FROM sense s JOIN sense_gloss g "
                          "ON g.sense_id=s.id WHERE s.hidden=0 AND g.lang='vi'"):
        parts = (t or "").strip().split()
        if not parts or not all(_ABBREV.match(x) for x in parts):
            continue
        if any(norm_vi(x.rstrip(".")) in lex for x in parts):
            continue
        if is_vi_markup_gloss(t):
            continue                       # 已在枚举表里，已处理
        n += 1
    return n <= NEW_ABBREV_CEIL


def _punct_glosses(c):
    """🔴 判据 import 自 `criteria`，不在 SQL 里手写字符类。"""
    return sum(1 for (t,) in c.execute(
        "SELECT g.text FROM sense s JOIN sense_gloss g ON g.sense_id=s.id "
        "WHERE s.hidden=0") if not gloss_has_content(t))


def _cover(c):
    n = c.execute(
        "SELECT COUNT(DISTINCT s.word_id) FROM sense s "
        "JOIN sense_gloss g ON g.sense_id=s.id WHERE s.hidden=0").fetchone()[0]
    t = c.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
    return 100.0 * n / max(t, 1)


# 🔴 `sense.hidden_why` 的值域。**三个值各自指向一笔账**，加新值不登记就判红。
#    W12 的两个 ＋ W25 的一个。
HIDDEN_WHY_DOM = ("gloss-is-punctuation-only",      # W12：整串是标点的释义
                  "gloss-is-source-markup",         # W12：源头的词典标记缩写
                  DUP_SENSE_WHY)                    # W25：同一个义项被两版各描述一遍


def _dup_senses(c):
    """W25 残留：同一个 entry 内还有没有「中文逐字相同」而都可出版的义项。

    判据 `criteria.dup_sense_groups()` **import，不重写** —— 它四次收窄的那些
    排除条件（跨 entry 正当／两条不同英文不许折）必须与填充器完全一致，
    否则闸会把「有意不折的 72 组」报成残留。
    """
    groups, _stat = dup_sense_groups(c)
    return sum(len(d) for _k, d in groups)


def _mute_duplicate_senses(c):
    """中文与同 entry 另一条相同、而**自己没有任何别的释义**的可出版义项。→ 条数

    这种义项在页面上只印一行中文，而那行中文旁边那条也印着同一行 ⇒
    读者看到两行一模一样的字，**没有任何线索能区分**。
    ⚠️ 判据有意**不**调 `dup_sense_groups()`：那个函数把这批算进「可折」，
       而本条要查的是「库里还有没有」—— 两者是生成侧与落点侧，不是同一个问题。
       （这也是为什么它能当 W26 那条否定结论的推翻条件。）
    """
    import collections as _c
    zh = _c.defaultdict(list)
    for wid, sid, eid, t in c.execute(
            "SELECT s.word_id, s.id, s.entry_id, g.text FROM sense s "
            "  JOIN sense_gloss g ON g.sense_id = s.id AND g.lang = 'zh' "
            " WHERE s.hidden = 0 AND s.entry_id IS NOT NULL"):
        zh[(wid, eid, (t or "").strip())].append(sid)
    dup = [s for v in zh.values() if len(v) > 1 for s in v]
    if not dup:
        return 0
    other = {s for (s,) in c.execute(
        "SELECT DISTINCT sense_id FROM sense_gloss WHERE lang IN ('en','vi') "
        "AND TRIM(text) <> '' AND sense_id IN (%s)" % ",".join(map(str, dup)))}
    return sum(1 for s in dup if s not in other)


def _merged_into_visible(c):
    """`merged_into` 指向的那条必须是**可见**义项。

    🔴 不查这一步的话，例句会从一个看不见的义项搬到**另一个看不见的义项** ——
       页面上一样是消失，而 P26 那条「例句不许挂在隐藏义项上」会在
       `merged_sense_map()` 把它解析成词条级之后**变绿**（因为解析器兜住了），
       于是「折叠指向了一个隐藏义项」这件事本身没人管。
    """
    cols = {r[1] for r in c.execute("PRAGMA table_info(sense)")}
    if "merged_into" not in cols:
        return 0
    return c.execute(
        "SELECT COUNT(*) FROM sense a JOIN sense b ON b.id = a.merged_into "
        " WHERE a.merged_into IS NOT NULL AND b.hidden = 1").fetchone()[0]


CHECKS = [
    ("E1", "sense_src 非空", lambda c: c.execute(
        "SELECT COUNT(*) FROM sense_src").fetchone()[0] > 0, True),
    # ⚠️ 连带 E14 已声明：E14（没有一条可出版义项缺中文）是**很宽的不变量** ——
    #    任何「新增或放出一条没有中文的可出版义项」都会碰到它。那是它该有的灵敏度。
    ("E2", "每条 sense 都有至少一条 gloss", lambda c: c.execute(
        "SELECT COUNT(*) FROM sense s LEFT JOIN sense_gloss g ON g.sense_id=s.id "
        "WHERE g.id IS NULL").fetchone()[0], 0),
    ("E3", "gloss 只有三语（`[[gloss-three-languages]]`）", lambda c: c.execute(
        "SELECT COUNT(*) FROM sense_gloss WHERE lang NOT IN ('zh','vi','en')"
    ).fetchone()[0], 0),
    ("E4", "gloss 文本非空", lambda c: c.execute(
        "SELECT COUNT(*) FROM sense_gloss WHERE TRIM(text)=''").fetchone()[0], 0),
    ("E5", "⭐ 读者口径：有可出版释义的词形占比不低于下限",
     lambda c: _cover(c) >= GLOSS_COVER_FLOOR, True),
    ("E6", "每条都挂得上 dict", lambda c: c.execute(
        "SELECT (SELECT COUNT(*) FROM sense_src x LEFT JOIN dict d ON d.id=x.word_id "
        "        WHERE d.id IS NULL)"
        "     + (SELECT COUNT(*) FROM sense s LEFT JOIN dict d ON d.id=s.word_id "
        "        WHERE d.id IS NULL)").fetchone()[0], 0),
    # 🔴 证据层永不编辑：隐藏的那批必须还在，只是 sense_id 为空
    ("E7", "🔴 被隐藏的证据还在 sense_src 里（sense_id 为空）", lambda c: c.execute(
        "SELECT COUNT(*) FROM sense_src WHERE sense_id IS NULL").fetchone()[0] > 0, True),
    # 🔴 W2 的判据必须真的在起作用 —— 掉到量级以下说明它被改坏了
    ("E8", "🔴 W2 判据在起作用（`same-as-han-spelling` 的量级）", lambda c: c.execute(
        "SELECT COUNT(*) FROM sense_src WHERE sense_id IS NULL "
        "AND text IN (SELECT han FROM han_spelling UNION SELECT nom FROM nom_spelling)"
    ).fetchone()[0] >= SPELLING_HIDDEN_FLOOR, True),
    # 🔴 出版层里**不许**出现「只是汉字表记」的中文 gloss —— 那正是 W2 要治的病
    #
    # ⚠️ **2026-10-02 收窄到 `src LIKE 'zh-%'`，而这次收窄是有依据的，不是为了变绿。**
    #    5b 落库后这条报红 1,183 条。逐条读了 14 条：**译文全都是对的** ——
    #      `công nhân` ← `Người lao động chân tay…`（体力劳动者）→ 工人
    #      `bán nguyệt san` ← `Tạp chí nửa tháng ra một kì`（半月一期的杂志）→ 半月刊
    #    它们是**汉越词**，正确的中文对译就等于它的汉字表记。
    #
    # 🔴 这与 W2 是**两件事，表面形状相同**：
    #      W2（源头的 zh gloss）  源头**根本没给释义**，释义槽里塞的是个拼写 ⇒ 隐藏是对的
    #      5b（模型译文）        源头给了完整释义，只是**中文对译恰好等于表记** ⇒
    #                           隐藏它＝让这 1,183 个词**一条中文释义都没有**，严格更差
    #    ⇒ E9 守住它本来守的那半（源头侧），模型侧另算。
    # ⇒ 代价**不许就这么消失**：读者确实会看到「汉字表记 道德 ／ 中文释义 道德」。
    #   那是**展示层**的冗余，归阶段 9，已记欠账 **W13**（与 W6/W7/W10 同一族）。
    ("E9", "🔴 出版的**源头**中文 gloss 不是该词的汉字表记（W2 的落点）", lambda c: c.execute(
        "SELECT COUNT(*) FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
        "WHERE g.lang='zh' AND g.src LIKE 'zh-%' AND EXISTS ("
        "  SELECT 1 FROM han_spelling h WHERE h.word_id=s.word_id AND h.han=g.text "
        "  UNION SELECT 1 FROM nom_spelling n WHERE n.word_id=s.word_id AND n.nom=g.text)"
    ).fetchone()[0], 0),
    # ⚠️ 模型侧**只报数并设上界**（不是 0）：1,183 条是汉越词的正确对译，
    #    但涨上去就说明模型开始拿表记当译文偷懒 ⇒ 那时要回来重判。欠账 W13。
    ("E9b", "⚠️ 模型译文等于汉字表记的条数没有变多（上界看守，不删）",
     lambda c: c.execute(
         "SELECT COUNT(*) FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
         "WHERE g.lang='zh' AND g.src='model:deepseek-v4-flash' AND EXISTS ("
         "  SELECT 1 FROM han_spelling h WHERE h.word_id=s.word_id AND h.han=g.text "
         "  UNION SELECT 1 FROM nom_spelling n WHERE n.word_id=s.word_id "
         "    AND n.nom=g.text)").fetchone()[0] <= 1600, True),
    ("E10", "entry_id 要么为空要么真指向一条 entry", lambda c: c.execute(
        "SELECT COUNT(*) FROM sense_src x LEFT JOIN entry e ON e.id=x.entry_id "
        "WHERE x.entry_id IS NOT NULL AND e.id IS NULL").fetchone()[0], 0),
    # 🔴🔴 **E4 查的是 `TRIM(text)=''`，而 `.` 不是空串** ⇒ 141 条整串是标点的释义
    #    一直在出版层里（2026-10-02 准备花 5b 的钱时抽样看见的）。
    #    ⚠️ 同一种源头残渣在**三个层**上各出现过一次（例句 214／词源 122／义项 141），
    #       前两次我都只在本层挡掉、没把判据收进 `criteria` ⇒ 下一层照样中。
    #    ⚠️ 判据只判「有没有字母/数字/表意文字」，**不判长短** ——
    #       按「短于 2 字符」清会删掉 503 条正确释义（`năm → 五`、`bần đạo → I`），
    #       而手抄 `\u4e00-\u9fff` 会再删掉 10 条**扩展平面的化学元素汉字名**
    #       （`rơzơfođi → 𬬻`）—— ko 记过同一个坑、同一类内容。
    # ⚠️ 连带 E14 已声明：E14（没有一条可出版义项缺中文）是**很宽的不变量** ——
    #    任何「新增或放出一条没有中文的可出版义项」都会碰到它。那是它该有的灵敏度。
    ("E12", "🔴 出版的释义里有「内容」（不是整串标点）", _punct_glosses, 0),
    # ⚠️ 连带 E14 已声明：E14（没有一条可出版义项缺中文）是**很宽的不变量** ——
    #    任何「新增或放出一条没有中文的可出版义项」都会碰到它。那是它该有的灵敏度。
    ("E12b", "🔴 出版的 vi 释义不是源头的词典标记缩写（`Trgt.`/`Ph.`/`X.`）",
     _markup_glosses, 0),
    # ⚠️ **只报数的探测器**，不是删除判据 —— 它用那条 90% 准的形式判据扫，
    #    把**不在枚举表里**的命中打出来，逼人去读一眼再决定进不进表。
    #    与词源闸 Y17（看守上界）同一个形状：枚举负责动手，形式判据负责发现漏的。
    # ⚠️ 连带 E14 已声明：E14（没有一条可出版义项缺中文）是**很宽的不变量** ——
    #    任何「新增或放出一条没有中文的可出版义项」都会碰到它。那是它该有的灵敏度。
    ("E13", "⚠️ 没有新出现的「句点缩写型」释义（只报数，上界看守）",
     _new_abbrev, True),
    # ⭐ 阶段 5b 的落点。**这一条是 0 不是比例** —— 每一条可出版义项都该有中文。
    # 🔴 它同时是「收词会让覆盖率静默掉下来」的守卫：以后再收词，新义项没中文它当场红。
    #    那正是 pt/ja 栽的那一步（收词后没重跑依赖层，覆盖率静默掉）。
    ("E14", "⭐ 没有一条可出版义项缺中文（阶段 5b 的落点）", lambda c: c.execute(
        "SELECT COUNT(*) FROM sense s WHERE s.hidden=0 AND NOT EXISTS("
        "SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='zh')"
    ).fetchone()[0], 0),
    # 🔴 机器译文与白送的 zh 版释义必须在 `src` 上分得开 —— 读者要知道哪条是机器译的
    #    （欠账：阶段 9 的展示层要印出来）
    # 🔴 **这条第一版写的是 `COUNT(DISTINCT src)>=2`，而它逮不到自己的变异** ——
    #    把模型 src 抹成 `zh-edition-trad` 之后还剩 trad+simp 两种，断言照样成立。
    #    `COUNT(DISTINCT …)` 对「某一个特定来源整档消失」结构性失明。
    #    ⇒ 改成**两档各自点名**：模型译文在、源头中文也在。
    ("E15", "🔴 模型译文与源头中文**各自都在**（读者要分得出哪条是机器译的）",
     lambda c: (c.execute("SELECT COUNT(*) FROM sense_gloss WHERE lang='zh' "
                          "AND src='model:deepseek-v4-flash'").fetchone()[0] > 50000
                and c.execute("SELECT COUNT(*) FROM sense_gloss WHERE lang='zh' "
                              "AND src LIKE 'zh-%'").fetchone()[0] > 5000), True),
    # ── 🔴🔴 **E16：`hidden_why` 值域 —— 这一条本该三天前就有。** ──
    #    例句层有 **X13**、关系层有 **R22**（R22 当初就是因为「同一条检查在一层有、
    #    在另一层没有，而两层各自都是绿的」补的），**唯独义项层没有**。
    #    ⇒ 2026-10-05 我往 `sense.hidden_why` 写了一个全新的值
    #      （W25 的 `duplicate-sense-in-entry`，1,631 行），**三道闸一道都没响**。
    #    ⭐ `[[decision-not-propagated-across-editions]]` 的同语言版第二例：
    #      一层做对了，别的层照旧缺着，而每层自己都是绿的。
    ("E16", "🔴 hidden_why 都在值域里（例句层有 X13、关系层有 R22，这里原先没有）",
     lambda c: c.execute(
         "SELECT COUNT(*) FROM sense WHERE hidden_why IS NOT NULL AND hidden_why "
         "NOT IN (%s)" % ",".join("'%s'" % w for w in sorted(HIDDEN_WHY_DOM))
     ).fetchone()[0], 0),
    # ── 🔴 **E17：读者口径 —— 同一个 entry 内不许有两条中文一模一样的可出版义项。** ──
    #    这是 W25 的残留型断言：判据再跑一遍，还能命中的必须是 0。
    #    ⭐ 残留型比基线型强两点：期望值天然是 0（不用我去推）；
    #      它与填充器**调同一个函数**，判据被删掉它当场变红。
    ("E17", "🔴 W25：同一个 entry 内没有中文逐字相同的可出版义项（残留）", _dup_senses, 0),
    # ── 🔴 E18：折叠的去向必须是可见义项（见函数注释里那条「解析器会把它兜绿」）──
    ("E18", "🔴 W25：`merged_into` 指向的是**可见**义项", _merged_into_visible, 0),
    # ── 🔴🔴 **E19：W26 的否定结论做成闸。** ──
    # 用户 2026-10-05 问「是之前翻译质量不行吗」—— **不是**。`理发` 翻
    # `to give a haircut` 和 `to get a haircut` 都对，中文的「理发」本身覆盖两边；
    # 而**页面上已经分得开**（展示层印 `vi-en`，`công quốc` 连例句「摩纳哥／卢森堡
    # 大公国」都把区别点明了）⇒ 76 组不用花钱，W26 是一条**否定结论**。
    # ⭐ 而「什么会推翻它」是**可查的**：只要每条义项除了那条共享中文之外
    #   还有**至少一个**能区分的释义（英文或越南语），读者就分得开。
    #   ⇒ 否定结论因此变成一条闸，而不是一句话（`[[record-the-negative-decision]]`：
    #     否定结论光落账不够，而**闸天然管不到否定结论** —— 除非像这样把它翻译成断言）。
    # 🔴 建这条闸的时候当场逮到 **3 条**违例（`tiếng Việt`/`đá lửa`/`bảng cửu chương`，
    #    全来自中文版 —— 它只给中文）⇒ 已折进有区别的那条。
    ("E19", "🔴 W26：中文相同的可出版义项，每条都要有能区分它的释义（否则读者分不开）",
     _mute_duplicate_senses, 0),
    ("E11", "src_ref 唯一", lambda c: c.execute(
        "SELECT COUNT(*) FROM (SELECT src_ref FROM sense_src GROUP BY src_ref "
        "HAVING COUNT(*)>1)").fetchone()[0], 0),
]
ROSTER = ("E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9", "E10", "E11",
          "E12", "E12b", "E13", "E14", "E15", "E9b",
          # 2026-10-05：E16 值域（本该三天前就有）／E17 W25 残留型／E18 折叠去向
          "E16", "E17", "E18", "E19")
UNMUTABLE = {
    "E1": "要变异就得清空整张表；它拦的是「表空了而所有 0 值检查全绿」。",
    "E11": "DDL 上有 `UNIQUE(src_ref)`，注不进去（与骨架闸 S2 同一情形，恒绿已登记）。",
}


def run(con):
    red = []
    have = tuple(c[0] for c in CHECKS)
    if set(have) != set(ROSTER):
        red.append(("E0", "检查表与花名册对不上：少了 %s，多了 %s"
                    % (sorted(set(ROSTER) - set(have)) or "无",
                       sorted(set(have) - set(ROSTER)) or "无")))
    for cid, name, fn, want in CHECKS:
        try:
            got = fn(con)
        except sqlite3.Error as e:
            red.append((cid, "%s —— 查不了：%s" % (name, e)))
            continue
        if got != want:
            red.append((cid, "%s：得到 %s，期望 %s" % (name, got, want)))
    return red


MUTATIONS = [
    ("E2", "插一条没有 gloss 的 sense",
     "INSERT INTO sense(word_id,rank,hidden) VALUES((SELECT MIN(id) FROM dict),0,0)",
     {"E14": "插的 sense 没有任何 gloss ⇒ 当然缺中文"}),
    ("E3", "写一条第四种语言的 gloss",
     "UPDATE sense_gloss SET lang='ja' WHERE id=(SELECT MIN(id) FROM sense_gloss)", {}),
    # ⚠️ 连带 E12 是声明过的：空串当然也「没有内容」—— E4 与 E12 是**包含关系**
    #    （E12 的判据比 E4 宽：空串 ⊂ 整串无内容）。两条都留着，因为 E4 的消息更准，
    #    而 E12 能逮到 E4 逮不到的那 141 条 `.`。
    ("E4", "把一条 gloss 文本清空",
     "UPDATE sense_gloss SET text='' WHERE id=(SELECT MIN(id) FROM sense_gloss)",
     {"E12": "空串也「没有内容」—— E4 ⊂ E12，这是包含关系不是重复"}),
    ("E5", "⭐ 把九成义项隐藏掉（模拟判据写太宽）",
     "UPDATE sense SET hidden=1 WHERE id % 10 <> 0",
     # 🔴 2026-10-05 新出现的连带，**而它是真的**：九成义项被隐藏之后，
     #    一批折叠的去向（`merged_into`）也跟着成了隐藏义项 ⇒ E18 报出来。
     #    ⭐ 这正是 E18 存在的意义 —— 它不只盯「我这次折得对不对」，
     #      还盯「后来有人把去向弄没了」。
     {"E18": "九成义项被隐藏 ⇒ 一批 merged_into 指向了隐藏义项"}),
    ("E6", "让一条 sense_src 指向不存在的 dict",
     "UPDATE sense_src SET word_id=99999999 WHERE id=(SELECT MIN(id) FROM sense_src)", {}),
    ("E7", "🔴 把被隐藏的证据**删掉**（＝证据层被编辑了）",
     "DELETE FROM sense_src WHERE sense_id IS NULL",
     {"E8": "W2 那批也在被删的行里"}),
    ("E8", "🔴 把 W2 隐藏的那批放出来（判据被改坏的样子）",
     "DELETE FROM sense_src WHERE sense_id IS NULL AND text IN "
     "(SELECT han FROM han_spelling UNION SELECT nom FROM nom_spelling)", {}),
    ("E9", "🔴 往出版层塞一条「中文释义就是汉字表记」",
     "INSERT INTO sense(word_id,rank,hidden) "
     "SELECT word_id,0,0 FROM han_spelling LIMIT 1;"
     "INSERT INTO sense_gloss(sense_id,lang,text,src) "
     "SELECT (SELECT MAX(id) FROM sense),'zh',(SELECT han FROM han_spelling LIMIT 1),"
     "       'zh-edition-trad'",
     {"E14": "新插的 sense 没有中文之外的…它本身带 zh，但 E14 查的是「缺中文」——"
             "插的这条 sense 自带 zh gloss，所以不连带；留此声明以防判据将来变"}),
    ("E10", "让 entry_id 指向不存在的 entry",
     "UPDATE sense_src SET entry_id=99999999 WHERE id=(SELECT MIN(id) FROM sense_src)", {}),
    ("E12", "🔴 把那 141 条「整串是标点」的释义放回出版层",
     "UPDATE sense SET hidden=0, hidden_why=NULL "
     "WHERE hidden_why='gloss-is-punctuation-only'",
     {"E14": "放回出版层的 141 条纯标点义项没有中文译文"}),
    # ⚠️ E13 是只报数的上界看守 —— 变异注入一批**新**的句点缩写（不在枚举表里），
    #    它必须报出来。这验的是「漏的能被发现」，不是「它会删东西」。
    ("E9b", "⚠️ 让模型译文大批等于汉字表记（模型拿表记当译文偷懒的样子）",
     "UPDATE sense_gloss SET text=(SELECT h.han FROM han_spelling h "
     "  JOIN sense s2 ON s2.id=sense_gloss.sense_id WHERE h.word_id=s2.word_id LIMIT 1) "
     "WHERE lang='zh' AND src='model:deepseek-v4-flash' AND EXISTS("
     "  SELECT 1 FROM han_spelling h JOIN sense s2 ON s2.id=sense_gloss.sense_id "
     "  WHERE h.word_id=s2.word_id)",
     # 🔴 2026-10-05 新出现的连带，**而它是真的**：把大批译文改成同一个表记串，
     #    当然会造出「同一个 entry 内中文逐字相同」的义项 ⇒ E17 报残留。
     #    ⭐ **连带声明要跟着检查表一起长。**
     {"E17": "大批译文变成同一个表记串 ⇒ 中文相同的义项成片出现"}),
    # ── 🔴 三条新检查的变异（2026-10-05，W25）──
    ("E16", "🔴 往 `sense.hidden_why` 写一个值域外的值（X13/R22 早就有、这里刚补）",
     "UPDATE sense SET hidden=1, hidden_why='mutant-reason' "
     "WHERE id=(SELECT MIN(id) FROM sense WHERE hidden=0)",
     # 隐藏一条可出版义项 ⇒ E5 的读者口径覆盖降一点点（不至于破下限）；
     # 它若带中文，E14「没有一条可出版义项缺中文」不受影响（它是被隐藏了不是缺中文）
     {}),
    ("E17", "🔴 把一条被折叠的义项放回出版层（W25 的判据被关掉的样子）",
     "UPDATE sense SET hidden=0, hidden_why=NULL "
     "WHERE id=(SELECT MIN(id) FROM sense WHERE hidden_why='duplicate-sense-in-entry')",
     # ⚠️ **有意不清 `merged_into`** —— 放回出版层而去向还指着别人，
     #    正好同时验到 E18 那条「折叠的去向必须是可见义项」的反面：
     #    这里 `merged_into` 指向的仍是可见义项，所以 E18 不该响。
     {}),
    ("E19", "🔴 放回一条「只有共享中文、别的一个字都没有」的义项（W26 的推翻条件）",
     "UPDATE sense SET hidden=0, hidden_why=NULL, merged_into=NULL WHERE id="
     "(SELECT a.id FROM sense a JOIN sense b ON b.id=a.merged_into "
     "  WHERE a.hidden_why='duplicate-sense-in-entry' "
     "    AND NOT EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=a.id "
     "                   AND g.lang IN ('en','vi') AND TRIM(g.text)<>'') LIMIT 1)",
     # ⚠️ 放回来之后它既是「中文重复又没有区分释义」（E19），又重新可出版（E5 的覆盖
     #    动一点点、E17 报它可折）。两条都声明。
     {"E17": "放回来的那条中文与同 entry 另一条相同 ⇒ 它又成了「可折的残留」"}),
    ("E18", "🔴 让一条折叠的去向指向**隐藏的**义项（例句会搬到另一个看不见的地方）",
     "UPDATE sense SET merged_into=(SELECT MIN(id) FROM sense WHERE hidden=1 "
     "  AND hidden_why='gloss-is-punctuation-only') "
     "WHERE id=(SELECT MIN(id) FROM sense WHERE hidden_why='duplicate-sense-in-entry')",
     {}),
    ("E14", "⭐ 删掉一条机器译文（义项又缺中文了）",
     "DELETE FROM sense_gloss WHERE lang='zh' AND src='model:deepseek-v4-flash' "
     "AND id=(SELECT MIN(id) FROM sense_gloss WHERE lang='zh' "
     "          AND src='model:deepseek-v4-flash')", {}),
    # ⚠️ 连带 E9 已声明，而且**它本身是个好消息**：把模型译文洗成源头 src 之后，
    #    那 1,183 条「译文等于汉字表记」就变成了「源头侧的 W2 病」⇒ E9 也响。
    #    两条断言在这一点上互相印证（E9 守源头侧、E15 守两档都在）。
    ("E15", "🔴 把机器译文的 `src` 抹成与源头中文一样（读者再也分不出）",
     "UPDATE sense_gloss SET src='zh-edition-trad' "
     "WHERE lang='zh' AND src='model:deepseek-v4-flash'",
     {"E9": "洗成源头 src 之后，1,183 条「译文＝汉字表记」变成源头侧的 W2 病 ⇒ E9 也该响"}),
    ("E13", "⚠️ 塞 20 条源头没见过的句点缩写（枚举表外）—— 探测器必须报出来",
     "INSERT INTO sense(word_id,rank,hidden) "
     "SELECT id,0,0 FROM dict LIMIT 20;"
     "INSERT INTO sense_gloss(sense_id,lang,text,src) "
     "SELECT id,'vi','Zqx.','t' FROM sense ORDER BY id DESC LIMIT 20",
     {"E14": "新插的 20 条义项只有 vi gloss，没有中文"}),
    ("E12b", "🔴 把那 45 条词典标记缩写（`Trgt.`/`Ph.`）放回出版层",
     "UPDATE sense SET hidden=0, hidden_why=NULL "
     "WHERE hidden_why='gloss-is-source-markup'",
     {"E14": "放回出版层的 45 条标记义项没有中文译文"}),
]


def mutate():
    con = sqlite3.connect(paths.DB)
    base = run(con)
    if base:
        print("🔴 基线就不绿：")
        for c, w in base:
            print("   %s %s" % (c, w))
        return False
    ok, covered = True, set()
    print("═══ 变异验证：%d 条注入 ═══" % len(MUTATIONS))
    for cid, desc, sql, also in MUTATIONS:
        con.execute("SAVEPOINT m")
        changed = 0
        for stmt in sql.split(";"):
            if stmt.strip():
                con.execute(stmt)
                changed += con.execute("SELECT changes()").fetchone()[0]
        hit = set(c for c, _ in run(con))
        undeclared = hit - {cid} - set(also)
        good = changed > 0 and cid in hit and not undeclared
        ok &= good
        covered.add(cid)
        note = ""
        if changed == 0:
            note = "  🔴🔴 **什么都没改** —— 变异自己坏了"
        elif cid not in hit:
            note = "  🔴 没逮到"
        elif undeclared:
            note = "  🔴 **未声明的连带** %s" % sorted(undeclared)
        elif also:
            note = "  （连带 %s，已声明）" % "、".join(sorted(also))
        print("   %s %-5s %s%s" % ("✅" if good else "🔴", cid, desc, note))
        con.execute("ROLLBACK TO m")
        con.execute("RELEASE m")
    con.rollback()
    print("\n── 没有变异覆盖的（必须逐条说明）")
    for c in [x for x in ROSTER if x not in covered]:
        why = UNMUTABLE.get(c)
        if why:
            print("   ⚠️ %-5s %s" % (c, why))
        else:
            ok = False
            print("   🔴 %-5s **没有变异、也没写为什么**" % c)
    con.close()
    return ok


def main():
    if "--mutate" in sys.argv:
        raise SystemExit(0 if mutate() else 1)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    try:
        red = run(con)
        print("■ vi 义项层闸：%d 条检查" % (len(CHECKS) + 1))
        for cid, why in red:
            print("   🔴 %-5s %s" % (cid, why))
        if not red:
            print("   ✅ 全绿")
        q = lambda x: con.execute(x).fetchone()[0]
        print("   ── 读者口径释义覆盖 **%.1f%%**（下限 %.1f%%）" % (_cover(con), GLOSS_COVER_FLOOR))
        print("   ── 证据 %s ／ 出版 %s ／ 隐藏 %s"
              % (format(q("SELECT COUNT(*) FROM sense_src"), ","),
                 format(q("SELECT COUNT(*) FROM sense"), ","),
                 format(q("SELECT COUNT(*) FROM sense_src WHERE sense_id IS NULL"), ",")))
        for lang in ("en", "vi", "zh"):
            n = q("SELECT COUNT(DISTINCT s.word_id) FROM sense s JOIN sense_gloss g "
                  "ON g.sense_id=s.id WHERE g.lang='%s'" % lang)
            print("      %s 覆盖词形 %7s（%.1f%%）"
                  % (lang, format(n, ","), 100 * n / q("SELECT COUNT(*) FROM dict")))
    finally:
        con.close()
    raise SystemExit(1 if red else 0)


if __name__ == "__main__":
    main()
