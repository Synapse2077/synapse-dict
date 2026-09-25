#!/usr/bin/env python3
"""「这个词形点进去有没有东西看」—— **判据只写一份**。2026-09-21。

🔴 这条判据一天之内写了三遍（`build_relation_layer` 回核、`fill_eumhun` 回核、
   手查），而且**第一遍就是错的**：漏了 `inflection.base_id`。
   `어그러지다` 有整套活用形，但它在 `inflection` 里是 **base**（`base_id` 列），
   `word_id` 列装的是变形形 `어그러져` —— 于是原形被判成"空白页"。
   ⇒ 三份判据迟早漂开，而这一条正是**验收要看的那个数**。集中到这儿。

═══ 什么算「有东西看」 ═══
    ① 有出版义项                      `sense`
    ② 是某个词的变形形                 `inflection.word_id`
    ③ **是某个变形形的原形**           `inflection.base_id`   ← 第一版漏的就是这条
    ④ 这个谚文音节对应哪些汉字          `hanja_reading.word_id`
    ⑤ **这个汉字读什么、训什么**        `hanja_reading.hanja`  ← 反向，靠 idx_hanja_char
    ⑥ 有关系（谚文对应/异体/同义…）     `sense_relation.word_id`
    ⑦ 有读音                          `pronunciation.word_id`   ← 阶段 3 做完后加的
    ⑧ 有词源正文                       `etymology.word_id`       ← 阶段 7 做完后加的
      ⭐ **加它之后空白页仍然是 6，一个都没降** —— 那 6 个确实连词源也没有。
        这条记下来是因为「加了一条判据而数字不动」本身就是证据：
        它说明剩下的 6 个是真的空，不是被口径遮住的。

🔴🔴🔴 **2026-09-24：这个数对「有 gloss 行但没有释义」结构性失明。**
   条件 ① 问的是 `sense` 行存不存在，而 195,030 个词形的唯一"义项"装的是
       `汉字或谚汉混合表记：환면상송（換面相訟）`
   —— 讲的是这个词**怎么写**，不是它**什么意思**。它们靠 ① ＋ ⑦ 双双合法地绿着，
   于是这个数报 **6**，而**四分之三的词元没有任何释义**。
   ⚠️ **判据本身没写错**（它问的是"有没有东西看"，这些页确实有汉字行和读音），
     错在**这个数被当成了验收口径**。⇒ 不改这条的含义，另加一条更严的读者口径：
     `test_plan_ledger.COVERAGE` 的「词元里**有释义**的占比」（实测 23.36%）。
   `[[correct-steps-can-compose-a-hole]]`：每步都对，跨步假设失效＝谁都没负责的洞。

⚠️ **词源（阶段 7）还没算进来**，那一层建完要再加一条。
🔴🔴 **每加一条，空白页数都会降 —— 那不是"修好了"，是口径变了**
   （`[[ledger-numbers-lie]]`）。加 ⑦ 的那次：23 → 见 `test_no_regression.R1` 的基线。
   ⇒ 改基线时**必须同时写明是哪条口径变了**，否则下一个人会以为是哪次修复的功劳。
"""

BLANK_SQL = """
SELECT COUNT(*) FROM dict d
 WHERE NOT EXISTS (SELECT 1 FROM sense          WHERE word_id = d.id)
   AND NOT EXISTS (SELECT 1 FROM inflection     WHERE word_id = d.id)
   AND NOT EXISTS (SELECT 1 FROM inflection     WHERE base_id = d.id)
   AND NOT EXISTS (SELECT 1 FROM hanja_reading  WHERE word_id = d.id)
   AND NOT EXISTS (SELECT 1 FROM hanja_reading  WHERE hanja   = d.word)
   AND NOT EXISTS (SELECT 1 FROM sense_relation WHERE word_id = d.id)
   AND NOT EXISTS (SELECT 1 FROM pronunciation   WHERE word_id = d.id)
   AND NOT EXISTS (SELECT 1 FROM etymology       WHERE word_id = d.id)
"""

BLANK_LIST_SQL = BLANK_SQL.replace("COUNT(*)", "d.word, d.pos")


def blank_pages(con):
    """→ 空白页词形数。**验收要看的就是这个数。**"""
    return con.execute(BLANK_SQL).fetchone()[0]


def blank_sample(con, n=20):
    return list(con.execute(BLANK_LIST_SQL + " LIMIT %d" % n))
