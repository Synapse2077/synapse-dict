#!/usr/bin/env python3
"""「这个词形点进去有没有东西看」—— **判据只写一份**。vi，2026-10-02。

═══ 为什么单开一个文件 ═══
ko 那份的文件头记着：这条判据**一天之内写了三遍，而且第一遍就是错的**。
它是**验收要看的那个数**，所以不许散落在各个回核里。

═══ 什么算「有东西看」（vi 的九条）═══
    ① 有**可出版**义项            `sense.hidden=0`
    ② 有音标                      `pronunciation`
    ③ 有汉越字表记                `han_spelling`
    ④ 有喃字表记                  `nom_spelling`
    ⑤ 有**可出版**关系            `sense_relation.hidden=0`
    ⑥ 有**可出版**例句            `example.hidden=0`
    ⑦ 有词源正文                  `etymology`
    ⑧ 有量词                      `noun_classifier`
    ⑨ 有**可出版**录音            `audio.hidden=0`

🔴 **①⑤⑥⑨ 都带 `hidden=0`，而 ko 那份的 ① 没带。** 这不是抄漏，是口径不同：
   ko 的 ① 问「`sense` 行存不存在」，而 vi 这边 W12 把 141 条纯标点释义、
   45 条词典标记缩写标成了 `hidden=1` —— 一个只有这些的页面，**读者看到的是空白**。
   既然这个数的用途是「读者口径」，它就必须按读者看得见的那一层问。

🔴🔴 **vi 比 ko 少一条，而那一条的缺席是有理由的。**
   ko 有「这个汉字读什么」的**反向**查（`hanja_reading.hanja = d.word`），
   因为 ko 的 `dict` 里有汉字词头。vi 的 `dict` **按用户 2026-09-28 的决定不收纯表意词头**
   （R19 逮到过 155 个漏网的，已清），⇒ 反向那条在 vi 上恒为假，加了等于没加。
   ⚠️ 这句话本身是判据的一部分：哪天 vi 决定收汉字词头，这里要补一条。

═══ 🔴🔴 这个数**对「源头没给」和「我们没印」结构性失明** ═══
2026-10-02 实测：**222 个空白页，证据层里 222 个都有指针义项**（`sense_src.sense_id IS NULL`）——

    UBND = Ủy ban Nhân dân（缩写）   giấu diếm / dấu diếm（正字法异写）
    ôtô · micrô · glucôzơ（外来词异写）  São Tomé · Trinidad（地名）

源头明明说了「X 是 Y 的异写/缩写」，**而那正是读者要看的那句话**。
真正「源头也没给」的是 **0 个**。
⇒ `[[dont-say-source-lacks-what-we-skipped]]`：这两类必须在结构上分开，
  所以本文件提供 `blank_split()` —— 它返回两个数，而不是一个。
  只报一个总数的话，「我们没印」会被当成「源头没有」，而那是会写进验收报告的谎。
📋 欠账 **W15**：这 222 个的修法在**展示层**（把指针印成链接），归阶段 9。

⚠️ **每加一条判据，空白页数都会降 —— 那不是"修好了"，是口径变了**
   （`[[ledger-numbers-lie]]`）。实测逐条加进来的降幅：
       义项 16,307 → 音标 511 → 汉越字 318 → 喃字 318（一个没降）→ 关系 262
       → 例句 240 → 词源 227 → 量词 223 → 录音 222
   ⭐ **「喃字」那条加进去一个都没降**，而我仍然留着它：它是真实的内容来源，
     只是恰好与「有汉越字表记」完全重叠。留着是为了哪天重叠不再成立时它还在。
   ⇒ 改基线时**必须同时写明是哪条口径变了**，否则下一个人会以为是哪次修复的功劳。
"""

_HAVE = (
    ("有可出版义项",  "SELECT 1 FROM sense          WHERE word_id=d.id AND hidden=0"),
    ("有音标",        "SELECT 1 FROM pronunciation  WHERE word_id=d.id"),
    ("有汉越字表记",  "SELECT 1 FROM han_spelling   WHERE word_id=d.id"),
    ("有喃字表记",    "SELECT 1 FROM nom_spelling   WHERE word_id=d.id"),
    ("有可出版关系",  "SELECT 1 FROM sense_relation WHERE word_id=d.id AND hidden=0"),
    ("有可出版例句",  "SELECT 1 FROM example        WHERE word_id=d.id AND hidden=0"),
    ("有词源",        "SELECT 1 FROM etymology      WHERE word_id=d.id"),
    ("有量词",        "SELECT 1 FROM noun_classifier WHERE word_id=d.id"),
    ("有可出版录音",  "SELECT 1 FROM audio          WHERE word_id=d.id AND hidden=0"),
)
_WHERE = " AND ".join("NOT EXISTS (%s)" % sql for _n, sql in _HAVE)

BLANK_SQL = "SELECT COUNT(*) FROM dict d WHERE " + _WHERE
BLANK_LIST_SQL = "SELECT d.id, d.word, d.pos FROM dict d WHERE " + _WHERE

# 🔴 **「我们没印」的判据**：证据层有指针义项（`sense_id IS NULL` ＝ 阶段 5a 的
#    指针专用路径，闸 E7 守着它们必须还在）。有它 ⇒ 源头是给了内容的。
_HAS_EVIDENCE = "EXISTS (SELECT 1 FROM sense_src WHERE word_id=d.id)"
BLANK_SOURCE_EMPTY_SQL = ("SELECT COUNT(*) FROM dict d WHERE " + _WHERE
                          + " AND NOT " + _HAS_EVIDENCE)


def blank_pages(con):
    """→ 空白页词形数（总数）。⚠️ **单独用这个数做验收是不诚实的**，见 `blank_split`。"""
    return con.execute(BLANK_SQL).fetchone()[0]


def blank_split(con):
    """→ (总数, 源头也没给的, 我们没印的)。**两类必须分开报。**"""
    total = blank_pages(con)
    src_empty = con.execute(BLANK_SOURCE_EMPTY_SQL).fetchone()[0]
    return total, src_empty, total - src_empty


def blank_sample(con, n=20):
    return list(con.execute(BLANK_LIST_SQL + " LIMIT %d" % n))


def ladder(con):
    """逐条加判据看降幅 → [(判据名, 加上它之后的空白页数)]。

    ⭐ 它的用途不是报数，是**让「口径变了」看得见**：某条判据哪天被改宽，
      这张梯子的形状会变，而总数可能只动一点点。
    """
    out, used = [], []
    for name, sql in _HAVE:
        used.append(sql)
        q = ("SELECT COUNT(*) FROM dict d WHERE "
             + " AND ".join("NOT EXISTS (%s)" % s for s in used))
        out.append((name, con.execute(q).fetchone()[0]))
    return out
