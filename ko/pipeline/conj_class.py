#!/usr/bin/env python3
"""**韩语活用类的判据，唯一的家。** 2026-09-24（阶段 8 后补）。

═══ 为什么要有这个文件 ═══
`entry.conj_class` 这一列原来存的是源头的 `table-tags`，值域只有两个：
    irregular 2,824 ／ no-table-tags 1,873
拿教科书词一验就看出来它不是活用类：

    걷다(ㄷ)  곱다(ㅂ)  낫다(ㅅ)  푸르다(러)  하다(여)   → 五个都是 `irregular`
    먹다(规则)                                  → `no-table-tags`

🔴 **存源头原词是对的**（`dbtool.py` 的注释早写了「`no-table-tags` 读成"规则"是推断」），
   错的是**列名承诺了「活用类」**，然后计划表和账的闸都拿它当活用类覆盖率在数 ——
   **数的是"有值的行"，不是"有信息的行"**。
   与 K10（20 万条中文释义其实是元描述）**同一个签名，本项目第二次**。
⇒ 源头原词改名叫 `conj_table_tag`（它是什么就叫什么），
  真正的活用类由本文件算出来，落进 `conj_class`。

═══ 两条互相独立的判据，这一点是要害 ═══
① `derive_from_forms()` —— 从**实际活用形**反推。证据是库里 403,687 行变形。
② `by_suffix()`         —— 从**构词后缀**推。规则表见 `SUFFIX`。

🔴🔴 **两条独立 ⇒ 可以互相当闸**：同一个词两边都能算而结论不同，就是数据坏了。
   全量跑只报 2 个（`짝짓다`/`한숨짓다`），回源确认是**源头生成了错的活用表**，
   库里那 92 个词形（`짝짓어`…）**韩语里不存在** —— 已由
   `fix_bad_inflected_forms.py` 修正。**零假阳性。**
   ⚠️ 这是第三个独立信号逮到的；外锚闸报变形层 403,687/403,687 双向恒等**且它是对的**
      —— 恒等式问「我们收得对不对」，问不了「源头对不对」。

═══ `SUFFIX` 这张表是怎么定下来的 ═══
2026-09-24 问了外审（v4pro；**豆包那一路挂了，所以这一轮没有两家交叉**），
它给了 13 条判断 ＋ 12 条补充。**我没有采信，是拿库里 4,592 个带活用表的原形逐条验的**：

    25 条断言 → 24 条被数据证实；剩下 1 条（`-짓다` 无反例）与数据冲突
    → 回源 → **是数据错不是规则错**（见上）⇒ 25 条全部成立。

🔴 **所以这张表的效力来自那次实测，不来自"模型说的"**
   （`[[verify-before-claiming-confirmed]]`：模型共识不是证据；何况这次只有一家）。
   ⚠️ 每加一条后缀，必须先在**带活用表的那批**上跑一遍 `cross_check()`。

═══ 不猜的那一档 ═══
两条判据都不适用的，`conj_class` 留 **NULL**。实测 220 个词形落在这儿，
抽样是 `보다`/`맞다`/`타다`/`치다`/`들다`/`푸다` 这类**最常用的基本动词** ——
它们恰恰是拼写决定不了的那种（`묻다` 问/埋、`걷다` 走/卷 分属不同类）。
🔴 **填一个猜的值比留空更伤**：`[[dict-framework-doc]]` 错比缺更伤权威。
"""
import unicodedata

# 活用类的值域。**用韩语术语原词**，不自造编码。
CLASSES = ("규칙", "여불규칙", "ㅂ불규칙", "ㄷ불규칙", "ㅅ불규칙", "ㅎ불규칙",
           "르불규칙", "러불규칙", "ㄹ탈락", "으탈락")

# 后缀 → 活用类。**每一条都在库里 4,592 个带活用表的原形上验过**（见文件头）。
# ⚠️ 顺序有意义：**长的在前**（`-스럽다` 要挡在 `-없다`… 之类前面）。
#    `[[regex-alternation-order]]`：同一 bug 犯过三次 —— 短的挡长的。
SUFFIX = [
    ("스럽다", "ㅂ불규칙"), ("롭다", "ㅂ불규칙"), ("답다", "ㅂ불규칙"),
    ("짓다", "ㅅ불규칙"),
    ("하다", "여불규칙"),
    ("거리다", "규칙"), ("트리다", "규칙"), ("뜨리다", "규칙"), ("시키다", "규칙"),
    ("대다", "규칙"), ("되다", "규칙"), ("없다", "규칙"), ("있다", "규칙"),
    ("받다", "규칙"), ("내다", "규칙"), ("나다", "규칙"), ("히다", "규칙"),
    ("기다", "규칙"), ("리다", "규칙"), ("우다", "규칙"), ("치다", "규칙"),
    ("먹다", "규칙"), ("잡다", "규칙"), ("지다", "규칙"), ("이다", "규칙"),
]


def _dec(ch):
    if not ("가" <= ch <= "힣"):
        return None
    n = ord(ch) - 0xAC00
    return n // 588, (n % 588) // 28, n % 28


def _comp(cho, jung, jong):
    return chr(0xAC00 + cho * 588 + jung * 28 + jong)


def by_suffix(base):
    """构词后缀 → 活用类。判不出返回 None。**不看任何活用形。**"""
    for suf, cls in SUFFIX:
        if base.endswith(suf) and len(base) > len(suf):
            return cls
    return None


def derive_from_forms(base, forms):
    """从**实际活用形**反推活用类。`forms` 是这个原形的全部变形词形。

    判据是「**词干变没变、怎么变的**」，不是查表：
      ㄷ불규칙  걷다 → 걸어    收音 ㄷ→ㄹ
      ㅂ불규칙  곱다 → 고와    收音 ㅂ 脱落（后接 오/우）
      ㅅ불규칙  낫다 → 나아    收音 ㅅ 脱落
      ㅎ불규칙  빨갛다 → 빨개  收音 ㅎ 脱落
      르불규칙  빠르다 → 빨라  前一音节补 ㄹ 收音
      러불규칙  푸르다 → 푸르러 词干原样 ＋ 러
      ㄹ탈락    놀다 → 노니    收音 ㄹ 脱落
      으탈락    쓰다 → 써      词干元音 ㅡ 脱落
    ⚠️ **先看词干末字母再看形式**。外审给的反例（`그렇다`/`그러다` 的
       `-아/어`、`-(으)니` 完全同形）咬不到这条判据，因为它不是只看那两个形式；
       外审自己也写了前提「必须已有词条原形」，而我们有。实测两个都判对。
    🔴 兜底返回 `규칙` ——**这是个推断，不是源头的话**。所以：
       · 没有 `forms` 时**不要调用本函数**（会把"没证据"读成"规则"）
       · `짝짓다` 那次正是兜底给出了错误的肯定答案，由 `cross_check()` 逮到
    """
    if not forms:
        return None
    stem = base[:-1]
    if not stem:
        return None
    if base.endswith("하다"):
        return "여불규칙"
    d = _dec(stem[-1])
    if d is None:
        return None
    cho, jung, jong = d
    head = stem[:-1]
    if stem.endswith("르") and len(stem) >= 2:
        if any(f.startswith(stem + "러") for f in forms):
            return "러불규칙"
        p = _dec(stem[-2])
        if p and any(f.startswith(stem[:-2] + _comp(p[0], p[1], 8)) for f in forms):
            return "르불규칙"
        return "규칙"
    if jong == 7 and any(f.startswith(head + _comp(cho, jung, 8)) for f in forms):
        return "ㄷ불규칙"
    if jong == 17 and any(f.startswith(head + _comp(cho, jung, 0)) for f in forms):
        return "ㅂ불규칙"
    if jong == 19 and any(f.startswith(head + _comp(cho, jung, 0)) for f in forms):
        return "ㅅ불규칙"
    if jong == 27 and any(f.startswith(head) and not f.startswith(stem) for f in forms):
        return "ㅎ불규칙"
    if jong == 8 and any(f.startswith(head + _comp(cho, jung, 0)) for f in forms):
        return "ㄹ탈락"
    if jong == 0 and jung == 18 and any(
            f.startswith(head) and not f.startswith(stem) for f in forms):
        return "으탈락"
    return "규칙"


# 🔴 对照组：**判据的交付物之一**，不是注释。改判据必须先让它全绿。
#    `[[validate-criterion-where-source-is-right]]`：拿规则去改源头之前，
#    先在源头没错的那批上验。
GOLD = {
    "걷다": "ㄷ불규칙", "곱다": "ㅂ불규칙", "낫다": "ㅅ불규칙", "빨갛다": "ㅎ불규칙",
    "푸르다": "러불규칙", "빠르다": "르불규칙", "따르다": "규칙", "놀다": "ㄹ탈락",
    "쓰다": "으탈락", "하다": "여불규칙", "먹다": "규칙", "짓다": "ㅅ불규칙",
    "덥다": "ㅂ불규칙", "입다": "규칙", "좁다": "규칙",
    # 🔴 外审给的两条"会判错"的反例，收进对照组**当作回归**：
    #    它说只看 `-아/어`＋`-(으)니` 会把这两个混淆。本判据先看词干末字母，实测分得开。
    "그렇다": "ㅎ불규칙", "그러다": "규칙",
    # 同上：`걷다`(走) vs `걸다`(挂)、`낫다`(好转) vs `나다`(出现)
    "걸다": "ㄹ탈락", "나다": "규칙",
}


def check_gold(byform):
    """→ [(词, 期望, 实得), ...] 只返回**对不上的**。`byform` 是 {原形: {变形形}}。"""
    bad = []
    for w, want in GOLD.items():
        got = derive_from_forms(w, byform.get(w, set()))
        if got != want:
            bad.append((w, want, got))
    return bad


def cross_check(byform):
    """两条独立判据的交叉闸 → [(原形, 后缀判的, 形式反推的), ...]。

    🔴 **不一致就是数据坏了**，不是判据要放宽。2026-09-24 全量跑报 2 个，
       回源确认两个都是源头生成了错的活用表（零假阳性）。
    """
    bad = []
    for b, fs in byform.items():
        s = by_suffix(b)
        if not s:
            continue
        d = derive_from_forms(b, fs)
        if d and d != s:
            bad.append((b, s, d))
    return bad
