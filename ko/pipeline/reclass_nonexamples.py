#!/usr/bin/env python3
"""K33：例句层里那批**根本不是例句**的行 —— 按源文形状分六类，一类一条判据。2026-09-27。

═══ 这批是什么 ═══
2026-09-26 清 K16（例句半翻译）时分出来的残渣：有一批行**没有可译的东西**，
因为它们压根不是句子。账上按初测记的是 252 条 / 0.67%，并写明「**是下界不是上界**」。
重量之后是 **1,041 条 / 2.78%**，那句话自己应验了 —— 差 4 倍，而差的那 3 倍
不是我漏数，是**漏了两种记法和一整类**（见下面 ① 的收宽史与 ⑥）。

🔴 **不是「白花了钱」那么简单**：这些行全都有中文（`example_gloss.lang='zh'`），
其中一部分译文**是对的且有用**（`≈ 파 (pa)` → `≈ 派 (pa)`、`기적소리` → `汽笛声`）。
坏的是**它们被印在「例句」这个标题底下** ⇒ 这是**分类问题**，不是翻译问题。
按 `[[dont-recast-deliverables-as-junk]]`／用户 2026-09-24「我倾向保留数据」：
**一行都不 DELETE**，一律 `hidden=1` ＋ `hidden_why`，能迁进关系层的先迁。

═══ 六条判据，一类一条（🔴 不许一条正则通吃六类）═══
判据按**源文的形状**写，不按「有没有中文」写 —— 后者是 K16 的口径，
而 K16 的残渣里既有这六类、也有真的翻译缺陷，混在一起两堆都看不见
（`[[ko-dict-pipeline]]`：形状检查报出来的要分两堆读）。

    ① `HANJA_TABLE`   整条由 `漢字/한글` 组构成（`臣僚/신료, 臣民/신민, …`）   263 ＋ 手判 7
    ② `REL_POINTER`   以关系标记开头（`⇒`／`≈`／`Coordinate term:`／`비슷한 속담:`）  37
    ③ `DERIV_ARROW`   `A > B`（可多级）且两边都是词，没有句子成分                  6
    ④ `WIKITEXT`      残留 `{{`／`}}`／`[[`／`]]`                              3
    ⑤ `BIBLIO`        书目引文（`(2017), “New Face”, in …`）                    1
    ⑥ `WORD_LIST`     整条是**词表**：每段都是一个无内部空格的词形、全条无句末标点   727

⚠️ **与 K15 同形但不同类**：K15 认的是**谚语词条**的成分拆解（339 条，已 hidden），
   这里认的是**源文的形状**。两笔账判据不共用，这一条是账上写明的。

⚠️ ⑥ **不是「其他」桶**（`[[residual-bucket-is-not-evidence]]`）：它有自己的正面定义
   （「每一段都是一个词形」＋「全条没有句末标点/终结词尾」），
   只是 ① 是它的一种特殊记法，所以判定时 ①–⑤ 先认领。去掉 ①–⑤，⑥ 自己照样成立。

═══ ① 的收宽史：判据比它要描述的东西窄了两次 ═══
第一版「每段都是 `漢字+/한글+`」命中 245。查近似漏网（≥50% 的段合格而整条没命中）
发现 **23 条同类**，卡在四种源头写法上：
    · 装饰前缀 `* `／`파생어 - `／`(불) `／`(부) `
    · 三段异体   `沙魚/鯊魚/사어`、`煉丹/鍊丹/연단`
    · 双读音     `行列/행렬·항렬`
    · 谚文侧为空 `便癰/`（源头自己写坏了）
收宽后 263。**再查一轮**，剩 7 条仍然漏，而它们各自是**一种不同的源头缺陷**
（少斜杠／少逗号／顺序颠倒／只有汉字没读音）⇒ 不再收宽判据，
改成 `HAND_TABLE` 逐条手判（`[[criteria-narrower-than-you-think]]`：
收宽到第三轮还在漏，说明剩下的不是同一个形状）。

═══ ⑥ 的反向证据（这一类最容易误伤，所以查得最细）═══
风险子集＝「词形不含挂载词条、也不被它含」共 **45 行**，**逐条读完**：
    · 真的例句 **4 行** —— 全是**语言学范畴名词条**，它的「例句」是这个范畴的实例：
      `의성어`（拟声词）→ `땡, 멍멍, 퐁당퐁당`；`첩어`（叠语）→ `꼭꼭, 누구누구`；
      `한자 합성어` → `씨족사회, 가내공업`；`줄임말` → `두쫀쿠`
      ⇒ 进 `NOT_A_LIST`，**有意不藏**。
    · 另外 41 行仍然不是例句：词形示例（`괜찮다` → `괜찮아` 是活用形，该在变形层）、
      标签泄漏（`기` → `관용구`、`삼산` → `출전`）、近义词（`또` → `다시, 거듭`）、
      派生词（`고개` → `고갯길`、`敢` → `감히`）。
🔴 **命中行里带句末标点/终结词尾的：0 / 1,041**（判据自带的反向断言，见 `SENTENCE`）。
⭐ **第二个独立信号**：源头自己的 `src_gloss` 说「합성어／파생어／한자 표기」的，
   在 ① 里占 136/263；反过来信号②说是而 ① 没命中的 61 条**逐条读过**，
   里面既有 ①（那 7 条手判）也有 ⑥，也有真例句（`사이시옷` 的语法说明）
   ⇒ **信号②比信号①噪**，不能拿它当判据，只能拿它当背书。
"""
import re

HANJA = r"[一-鿿㐀-䶿]"
HANGUL = r"[가-힣]"

_SPLIT = re.compile(r"[,，、]")
# 🔴 命中的行里**不许**有句末标点 —— 判据自带的反向断言，`self_check()` 在全库上跑它。
#    ⚠️ 只查标点，**不查终结词尾**：第一版写了 `[다요까죠네](?:\.|$)`，
#      而 `무시당하다`／`깨뜨리다` 末尾的 `다` 是**词典形**，当场误报 10 条。
#      韩语「词典形」与「终结形」同形，光看末字分不开 —— 这一条只能靠标点。
SENTENCE = re.compile(r"[.。!?！？…]")
# 断言只作用在**词表那一族**（①③⑥）：②⑤ 的正文里合法地带句点
# （书目引文 `in PSY 8th 4X2=8 (…)`）。断言的适用范围本身也是判据的一部分。
SENTENCE_FREE = ("HANJA_TABLE", "DERIV_ARROW", "WORD_LIST")

# ── ① 汉字构词表 ────────────────────────────────────────────────
# 组内允许：多个汉字异体（`沙魚/鯊魚/사어`）＋ 多个谚文读音（`行列/행렬·항렬`）
# ＋ 谚文侧为空（源头自己写坏了：`便癰/`）。**收宽是量出来的**，见文件头。
_HANJA_RUN = re.compile(r"^%s+$" % HANJA)
_HANGUL_RUN = re.compile(r"^%s+(?:·%s+)*$" % (HANGUL, HANGUL))
# 行首那几种装饰前缀，逐个从数据里读出来的：`* `／`파생어 - `／`(불) `
_DECOR = re.compile(r"^\s*(?:\*|파생어\s*[-–]|[(（]%s+[)）])\s*" % HANGUL)


def _group_ok(g):
    ps = [x.strip() for x in g.split("/")]
    if len(ps) < 2:
        return False, False
    han, kor = ps[:-1], ps[-1]
    if not all(_HANJA_RUN.match(x) for x in han):
        return False, False
    if kor == "":
        return True, False                      # 形状对，但没有谚文（不算「有内容的组」）
    return bool(_HANGUL_RUN.match(kor)), True


def c_hanja_table(t):
    t = _DECOR.sub("", t or "")
    parts = [p.strip() for p in _SPLIT.split(t) if p.strip()]
    if not parts:
        return False
    flags = [_group_ok(p) for p in parts]
    return all(ok for ok, _ in flags) and any(has for _, has in flags)


# 🔴 判据收宽三轮之后仍漏的 7 条 —— 每条卡在**一种不同的源头缺陷**上，逐条读过。
#    不再为它们收宽判据：七种缺陷收进一条正则，那条正则就通吃了。
HAND_TABLE = {
    12991: "混着没给读音的裸汉字（`特技兵`／`派兵`／`憲兵`）",
    13519: "少一个逗号：`後身/후신 後室/후실` 是两组挤在一格",
    14342: "顺序颠倒：`자문/自問` 是谚文在前",
    14754: "用逗号当了斜杠：`滯在, 체재`",
    17507: "混着没给读音的裸汉字（`合衆国`／`會衆`／`民衆`）",
    18227: "少一个斜杠：`述而不作술이부작`",
    24309: "少一个逗号：`轉移/전이 推移/추이`",
    # 这两条是 ⑥ 的复核逮出来的：形状上被 ⑥ 认领了，而它们其实是 ① 的
    # 「裸汉字混着」缺陷（与 12991／17507 同形）⇒ 归到 ① 才对。
    14518: "混着没给读音的裸汉字（`和暢`／`共和`／`附和雷同`）",
    21704: "混着没给读音的裸汉字（`追窮`／`追記`／`追納`）",
}

# ══════════════════════════════════════════════════════════════════
# ⑥ 的人工复核名单
# ══════════════════════════════════════════════════════════════════
# 🔴 **形式信号「每个词形都含本词条」在这一层会机械性失效**，所以它只当
#    「要人看一眼」的标记，不当判据。787 行里它报 60 行，**全部逐条读过**。
#    失效的两个机械原因：
#      · 汉字在括号里 —— `비음(鼻音)` 剥括号后是 `비음`，不含 `鼻`，而它确实是派生词
#      · 사이시옷／音变 —— `고개` → `고갯길`、`색시` → `색싯집`
#    ⇒ 60 行里真正要改判的是下面三堆（共 25 行），其余 35 行按 ⑥ 原样迁 `derived`。

# ① **有意不藏**：这些是活用形/用例示例，源头拿一个真实词形来演示这个词条。
#    单个词形印在「例句」下面算不算例句，是个边界；**我判它算** ——
#    藏掉它等于让这些词缀页与形容词页一条示例都没有，而它们没有别的可印。
#    `[[dict-framework-doc]]`：错比缺更伤权威，但这里不存在「错」，只有「弱」。
WL_KEEP = {
    606: "`사랑하다` → `사랑해`（活用形）",
    1876: "`고맙다` → `고맙습니다`",
    2748: "`괜찮다` → `괜찮아`",
    2749: "`괜찮다` → `괜찮으시다면`",
    3826: "`따라하다` → `따라하세요`",
    3828: "`죄송하다` → `죄송합니다`",
    3847: "`수고하다` → `수고하세요`",
    4156: "`지랄하다` → `지랄하네`",
    6597: "`-으나` → `기나길다`（词缀页唯一的示例）",
    6911: "`-으옵-` → `하오니`（同上）",
    6993: "`-ㅇ` → `감사합니당`（同上，网络语尾只能靠实例演示）",
    6994: "`-ㅇ` → `안녕하세용`",
    35581: "🔴 `그럼, 알겠어` **是一句真话**（「当然，知道了」）—— "
           "两段都是无空格词形、又没有句末标点，于是被 ⑥ 认了。"
           "这一条是判据的真误伤，不是边界",
}

# ② 关系不是「派生」：源头给的是同义/同类词表。**照 `derived` 落就是断言错了方向**。
WL_KIND = {
    6069: ("coordinate_term", "`하나, 둘, 서이, 너이` 是数词序列，`하나` 不是从 `서이` 派生的"),
    13919: ("synonym", "`또` → `다시, 거듭` 是同义词"),
    16567: ("synonym", "`씹다` → `욕하다, 비난하다, 비방하다`"),
    16659: ("synonym", "`대다` → `접촉하다`"),
    24453: ("coordinate_term", "`남진` → `북진` 是方向对举"),
    25530: ("related", "`진격` → `북진, 남침, 진서` 是下属方式，不是派生"),
    33135: ("synonym", "`등` → `들、따위、기타`"),
    33136: ("synonym", "`등`（灯）→ `등잔、호롱`"),
}

# ③ 藏的理由不是「词表」，是**标签泄漏** —— 源头那一格只有栏目名。
#    这一类 `fix_nonexample_rows.py` 2026-09-24 已经收过 46 条（`占位标签`），
#    它的判据当时漏了**不带冒号也不在 `LABEL_KEEP` 里**的这 4 个。
WL_WHY = {
    10289: "占位标签",
    12667: "占位标签",
    14384: "占位标签",
    30230: "占位标签",
}

# ④ 只藏不迁：这一行里混着与本词条无关的词，逐词判太碎，迁过去会造错边。
WL_HIDE_ONLY = {
    28934: "`움집, 움막, 움푹, 막` —— `막` 与 `움` 无关，`움푹` 是副词不是派生词",
}

# ── ② 关系指针 ───────────────────────────────────────────────────
# 🔴 值域是**从数据里枚举出来的**（扫全部可见例句的行首符号与 `XXX:` 标签词），
#    不是我想出来的 —— 第一版我凭印象写了 `Synonym|유의어|참고|준말|본말` 一串，
#    数据里一条都没有，反而漏掉了 `문화어 속담`／`비규범 표기`（30 vs 37）。
_PTR = re.compile(
    r"^\s*(?:[⇒≈]"
    r"|(?:Coordinate term|Near-synonym|See also"
    r"|비슷한\s*속담|문화어\s*속담|비규범\s*표기)\s*[:：])")


def c_rel_pointer(t):
    return bool(_PTR.match(t or ""))


# ── ③ 派生记法 ───────────────────────────────────────────────────
_DERIV = re.compile(r"^\s*[%s%s]+(?:\s*>\s*[%s%s]+)+\s*$"
                    % (HANGUL[1:-1], HANJA[1:-1], HANGUL[1:-1], HANJA[1:-1]))


def c_deriv_arrow(t):
    return bool(_DERIV.match(t or ""))


# ── ④ wikitext 碎片 ─────────────────────────────────────────────
_WIKI = ("{{", "}}", "[[", "]]")


def c_wikitext(t):
    return any(x in (t or "") for x in _WIKI)


# ── ⑤ 书目引文 ───────────────────────────────────────────────────
_BIB = re.compile(r"\(\d{4}\)\s*,\s*[“\"']")


def c_biblio(t):
    return bool(_BIB.search(t or ""))


# ── ⑥ 词表 ──────────────────────────────────────────────────────
# 每一段是一个**无内部空格**的词形（可带一个括号注、可带 `/` 异写），全条无句末标点。
_TOKEN = re.compile(r"^[%s%sA-Za-z0-9·]+(?:[(（][^)）]*[)）])?(?:/[^,，、\s]+)*$"
                    % (HANGUL[1:-1], HANJA[1:-1]))

# 🔴 **有意不藏**：词条本身是一个语言学范畴名，它的「例句」就是这个范畴的实例
#    —— 那是正经例句。45 行风险子集逐条读出来的，只有这 4 行。
NOT_A_LIST = {
    10827: "`의성어`（拟声词）的实例 `땡, 멍멍, 퐁당퐁당, 쾅쾅` 就是它的例句",
    10828: "`첩어`（叠语）的实例 `꼭꼭, 누구누구, 옹기종기`",
    11151: "`한자 합성어` 的实例 `씨족사회, 가내공업, 정신통일`",
    14422: "`줄임말`（缩略语）的实例 `두쫀쿠`",
}


def c_word_list(t):
    t = (t or "").strip()
    if not t or SENTENCE.search(t):
        return False
    parts = [p.strip() for p in _SPLIT.split(t) if p.strip()]
    return bool(parts) and all(_TOKEN.match(p) for p in parts)


CLASSES = (
    ("HANJA_TABLE", "汉字构词表", c_hanja_table),
    ("REL_POINTER", "关系指针", c_rel_pointer),
    ("DERIV_ARROW", "派生记法", c_deriv_arrow),
    ("WIKITEXT", "wikitext 碎片", c_wikitext),
    ("BIBLIO", "书目引文", c_biblio),
    ("WORD_LIST", "词表", c_word_list),          # 🔴 必须排在最后：① 是它的特殊记法
)
NAME = {k: zh for k, zh, _ in CLASSES}


def classify(eid, text):
    """→ (key, 中文名) 或 (None, None)。手判名单优先于正则。"""
    if eid in NOT_A_LIST or eid in WL_KEEP:
        return None, None
    if eid in HAND_TABLE:
        return "HANJA_TABLE", NAME["HANJA_TABLE"]
    for k, zh, fn in CLASSES:
        if fn(text):
            return k, zh
    return None, None


def plan(con):
    """库里**还可见**的非例句行。R24 的判据只有这一份家。"""
    out = []
    for eid, word, text, sg, src in con.execute(
            "SELECT id, word, text, src_gloss, src FROM example "
            "WHERE COALESCE(hidden,0)=0 ORDER BY id"):
        k, zh = classify(eid, text)
        if k:
            out.append((eid, word, text, k, zh, sg, src))
    return out


def tokens(text):
    """把一条词表/构词表拆成词形。括号注剥掉（`비행기(飛行機)` → `비행기`）。"""
    out = []
    for p in _SPLIT.split(_DECOR.sub("", text or "")):
        p = p.strip()
        if not p:
            continue
        p = re.sub(r"[(（][^)）]*[)）]", "", p).strip()
        if not p:
            continue
        if "/" in p:                             # `臣僚/신료` → 取谚文侧，可能有 `·` 多读音
            kor = p.split("/")[-1].strip()
            out.extend(x for x in kor.split("·") if x)
        else:
            out.append(p)
    return out


def self_check(con):
    """判据自己的闸。🔴 任何一条命中带句末标点 ⇒ 说明判据伸进了真句子。"""
    rows = plan(con)
    bad = [(r[0], r[2]) for r in rows
           if r[3] in SENTENCE_FREE and SENTENCE.search(r[2])]
    if bad:
        raise AssertionError("🔴 %d 条命中带句末标点，判据伸进真句子了：%r" % (len(bad), bad[:3]))
    # 手判名单里的 id 必须真的存在且真的可见（`[[expectation-must-be-declared]]`）
    ids = {r[0] for r in rows}
    for eid in HAND_TABLE:
        if eid not in ids:
            raise AssertionError("🔴 HAND_TABLE 的 %d 不在命中集里（行被改过或已藏）" % eid)
    seen = {eid for (eid,) in con.execute(
        "SELECT id FROM example WHERE COALESCE(hidden,0)=0")}
    for eid in NOT_A_LIST:
        if eid not in seen:
            raise AssertionError("🔴 NOT_A_LIST 的 %d 已经不可见了" % eid)
        if eid in ids:
            raise AssertionError("🔴 NOT_A_LIST 的 %d 仍被判为非例句" % eid)
    # ⑥ 的三份手判名单同样要钉住：id 必须真的在库里，而且落在它该落的那一边。
    for eid in WL_KEEP:
        if eid not in seen:
            raise AssertionError("🔴 WL_KEEP 的 %d 已经不可见了" % eid)
        if eid in ids:
            raise AssertionError("🔴 WL_KEEP 的 %d 仍被判为非例句" % eid)
    for name, d in (("WL_KIND", WL_KIND), ("WL_WHY", WL_WHY),
                    ("WL_HIDE_ONLY", WL_HIDE_ONLY)):
        for eid in d:
            if eid not in ids:
                raise AssertionError("🔴 %s 的 %d 不在命中集里" % (name, eid))
    overlap = (set(WL_KEEP) | set(NOT_A_LIST)) & (set(WL_KIND) | set(WL_WHY) | set(WL_HIDE_ONLY))
    if overlap:
        raise AssertionError("🔴 手判名单互相打架：%s" % sorted(overlap))
    return rows


# ══════════════════════════════════════════════════════════════════
# 迁进关系层：每一类落哪个 kind
# ══════════════════════════════════════════════════════════════════
# 🔴🔴 **值域是回数据核出来的，不是取两家外审的多数。** 2026-09-27 拿这批问了
#   豆包 pro ＋ deepseek-v4-pro（材料 `data/work/ko/consult/k33_kind_mapping.md`），
#   两家在两点上不一致，而**决定性证据两家都没有 —— 在 `tags` 列自己的值域里**：
#
#   · `문화어 속담`（朝鲜标准语版本）
#       v4pro 说 `dialectal`，豆包说 `alternative`。
#       库里既有先例：`여자 → 녀자` 是 `kind=alternative` ＋ `tags=["variety-kp"]`，**28 行**。
#       ⇒ 采 `alternative`。v4pro 的前提错了：**문화어 是朝鲜的国家标准语，不是方言**，
#         而我们 `dialectal` 的展示标签印的是「方言形」，那样印就是在误导读者。
#   · `비규범 표기`（非规范拼写）
#       两家都主张**双向存**（v4pro 两边都用 `alternative`，豆包反向用 `alt_of`）。
#       库里既有先例 **50 行**（`초콜릿 → 초콜렛`、`조지아 → 죠지아`）**只存一个方向**：
#       规范形 → 非规范形，`tags=["alternative","nonstandard"]`。
#       ⇒ 采单向。并且三条里 `섀시` 的非规范形根本不在 `dict` 里，反向边落不了地。
#   · `⇒` / `≈`（两家没问到，我自己回数据）
#       `바` 页上 `⇒ 스탠드바` 这条源头数据**已经以 `synonym` 落过一次**，
#       `≈ 파` 已经以 `related` 落过一次 —— 同一条源头被收割了两遍（一遍进关系、一遍进例句）。
#       ⇒ 直接照它自己的落法：`⇒` → `synonym`，`≈` → `related`。
#   · `Near-synonym: 걱정하다`：`걱정되다 → 걱정하다` **已经在关系层了** ⇒ 不用插，只藏。
#
# ⚠️ **不往 `tags` 里塞我自己发明的值。** 两家都建议加 `["compound"]`／`["near"]`／
#    `["similar_proverb"]`。`tags` 这一列装的是**源头的标签数组**（75 个值，`hangeul` 25,790
#    打头），我写进去的自造值会让「源头说的」和「我推的」在同一列里分不开 ——
#    那正是 **K14** 这笔账的形状。细微差别由 **kind 的选择 ＋ 留着的证据行**承载。
#    唯一的例外是 `nonstandard`／`variety-kp`：它们**本来就是源头的词汇**（50／28 行既有）。
PTR_MAP = (
    # (行首标记, kind, tags) —— 逐条读过全部 37 行之后定的
    ("Coordinate term", "coordinate_term", None),
    ("Near-synonym", "synonym", None),
    ("See also", "related", None),
    ("비규범 표기", "alternative", '["alternative", "nonstandard"]'),
    ("문화어 속담", "alternative", '["variety-kp"]'),
    ("비슷한 속담", "synonym", None),
    ("⇒", "synonym", None),
    ("≈", "related", None),
)
# 🔴 手判：`뛰는 놈 위에 나는 놈 있다` 的「문화어 속담」给的 `차 우에 차가 있다`
#    **不是同一条谚语的北方写法，是另一条意思相同的谚语**（逐条读出来的，另两条
#    `수박 껍질만 핥는다`／`의질이 병` 才是同一条的异形）⇒ 这一条按 `synonym` 落，
#    但 `tags` 仍然保留 `variety-kp`，「这是北方的说法」这个事实不许丢。
PTR_HAND = {24098: ("synonym", '["variety-kp"]',
                    "`차 우에 차가 있다` 与原谚语用词完全不同，是另一条同义谚语，不是异形")}

# 每一类落什么 `hidden_why`（展示层与闸都按这个分「为什么不显示」）
WHY = {k: zh for k, zh, _ in CLASSES}

# 这几类**只藏不迁**（迁不出关系，或者迁过去就是重复）
HIDE_ONLY = ("WIKITEXT", "BIBLIO")


def ptr_target(text):
    """② 关系指针 → (标记, kind, tags, 目标原文列表)。"""
    t = (text or "").strip()
    for mark, kind, tags in PTR_MAP:
        if t.startswith(mark):
            rest = t[len(mark):].lstrip(":：").strip()
            # 🔴 切分**必须认括号**：`놈 (nom, “bastard”)` 里那个逗号在括号里，
            #    用 `_SPLIT` 切会切出 `놈 (nom` 和 `“bastard”)` 两条垃圾边。
            #    现成的切分器就在隔壁，借来不重写（它多切 `/`，而 ② 的目标里没有斜杠）。
            from fix_relation_paren_split import split_outside_parens
            outs = [x.strip().strip("«»《》") for x in split_outside_parens(rest)]
            return mark, kind, tags, [x for x in outs if x]
    return None, None, None, []


# 🔴 `target` 存源文原样，但**罗马字/英文释义那一层括号不算源文的一部分** ——
#    K30 的 `fix_relation_english_gloss.py` 立的就是这条约定：关系目标不带罗马字。
#    第一版我把 `잃다 (ilta)` 原样存进去，渲染出来页面上就多出 12 条带罗马字的目标，
#    而全库**另外 257,158 条一条都不带** ⇒ 是我引入的不一致，不是源文该保留的信息。
#    ⚠️ **只剥拉丁/罗马字那一层**：`방금(方今)` 的括号里是汉字，是给读者看的信息，
#      剥掉就把 `부인(婦人)`／`부인(否認)` 那种区别抹掉了（`resolve_relation_targets` 文件头）。
_LATIN_PAREN = re.compile(r"\s*[(（][^()（）]*[A-Za-z][^()（）]*[)）]")


def strip_latin_paren(s):
    """剥掉目标末尾/开头那些**含拉丁字母**的括号注（罗马字、英文释义）。"""
    prev = None
    cur = (s or "").strip()
    while cur != prev:
        prev = cur
        cur = _LATIN_PAREN.sub("", cur).strip()
    return cur or (s or "").strip()


def _deep_unparen(s):
    """反复剥括号直到不变。只给 ② 用；`resolve()` 自己只剥一层。"""
    from resolve_relation_targets import PAREN
    prev = None
    cur = (s or "").strip()
    while cur != prev:
        prev = cur
        cur = PAREN.sub("", cur).strip()
    return cur


def segments(key, text):
    """把一行拆成要落的边：[(展示原文, [落点候选])]。

    🔴 `target` 存**源文原样**、`target_norm` 只回答落点 —— 这个分工是
    `resolve_relation_targets.py` 文件头定的（`부인(婦人)` 与 `부인(否認)` 是两个词，
    就地改写 target 会把区别抹掉）。所以 `臣僚/신료` 原样进 `target`，
    落点取谚文侧；`비행기(飛行機)` 原样进 target，落点取 `비행기`。
    """
    out = []
    t = _DECOR.sub("", text or "")
    for seg in _SPLIT.split(t):
        seg = seg.strip().strip("«»《》")
        if not seg:
            continue
        if key == "HANJA_TABLE" and "/" in seg:
            kor = seg.split("/")[-1].strip()
            cands = [x for x in kor.split("·") if x] or []
        else:
            cands = [seg]
        out.append((seg, cands))
    return out


# ══════════════════════════════════════════════════════════════════
def build(con):
    """算出要落的边与要藏的行。**写前**就算完，写后回核比的是这里的数
    （`[[expectation-must-be-declared]]`：期望独立声明，不许从写完的现状推）。
    """
    from resolve_relation_targets import resolve, nfc   # 🔴 落点判据只有一份家

    rows = self_check(con)
    wid = {}
    for w, i, il in con.execute("SELECT word, id, is_lemma FROM dict ORDER BY id"):
        wid.setdefault(w, (i, il))
    have = {nfc(w) for w in wid}
    existing = {}
    for w, k, t, tn in con.execute(
            "SELECT word_id, kind, target, target_norm FROM sense_relation"):
        existing.setdefault((w, k), set()).add(tn or t)

    edges, stat, outcome = [], {}, {}
    bump = lambda k: stat.__setitem__(k, stat.get(k, 0) + 1)
    note = lambda eid, what: outcome.setdefault(eid, []).append(what)

    inv = {v[0]: k for k, v in wid.items()}

    def add(word_id, kind, raw, cands, tags, eid, why):
        norm = None
        for c in cands:
            g, _ = resolve(c, have)
            if g:
                norm = g
                break
        # 🔴 自环守卫：落点＝挂载页自己 ⇒ 一条「本词指向本词」的边，纯噪音。
        #    实测 3 条（`서이` 的数词序列里含它自己、`염소(가스)` 剥括号后＝`염소`）。
        if norm is not None and norm == inv.get(word_id):
            bump("自环，不插：" + why)
            note(eid, "self")
            return
        seen = existing.setdefault((word_id, kind), set())
        if (norm or raw) in seen:
            bump("已有同向边，不重复插：" + why)
            note(eid, "dup")
            return
        seen.add(norm or raw)
        note(eid, "insert")
        edges.append((word_id, kind, raw, norm, tags, eid))
        bump("要插 %s → %s" % (why, kind))

    for eid, word, text, key, zh, sg, src in rows:
        if key in HIDE_ONLY or eid in WL_HIDE_ONLY or eid in WL_WHY:
            bump("只藏不迁：" + zh)
            note(eid, "hide-only")
            continue
        host = wid.get(word)
        if host is None:
            bump("🔴 挂载词条不在 dict")
            continue
        if key == "REL_POINTER":
            mark, kind, tags, outs = ptr_target(text)
            if not mark:
                bump("🔴 ② 解析不出标记")
                continue
            if eid in PTR_HAND:
                kind, tags, _ = PTR_HAND[eid]
            for o in outs:
                # 🔴 ② 的目标里有**嵌套括号**：`걱정하다 (geokjeonghada, “to (actively) worry”)`。
                #    共用的 `resolve()` 只剥一层（`\([^()]*\)` 一次 sub），剥完还剩
                #    `걱정하다 (geokjeonghada, “to  worry”)` ⇒ 解析失败 ⇒ 落点 NULL
                #    ⇒ **去重键拿 raw 去比，比不上关系层已有的 `걱정하다`，于是要插第二遍**。
                #    逐条读这 ~50 条边时逮到的（不读就会插进去）。
                #    ⚠️ 修法是在**本地多给一个候选**，不是去改共用的 `resolve()` ——
                #      那条判据管着全库 177,007 个落点，改它是另一件事（`[[fix-regression-and-gate]]`）。
                shown = strip_latin_paren(o)
                add(host[0], kind, shown, [shown, o, _deep_unparen(o)], tags, eid, zh)
        elif key == "DERIV_ARROW":
            parts = [p.strip() for p in text.split(">") if p.strip()]
            add(host[0], "derived", parts[-1], [parts[-1]], None, eid, zh)
            # 🔴 两家外审都说：**只落 A→B，不落 B→A**（反向靠展示层反查，
            #    存了会把 `derived` 的统一方向弄脏）。我采纳。
            for a, b in zip(parts, parts[1:]):
                ha = wid.get(a)
                if ha is None:
                    bump("③ 基词不在 dict")
                    continue
                add(ha[0], "derived", b, [b], None, eid, "③ 基词→派生词")
        else:
            # ⑥ 里有 8 行源头给的**不是派生关系**（同义/同类词表）—— 逐条读出来的，
            #    照 `derived` 落就是替源头断言了一个它没说的方向。
            kind = WL_KIND.get(eid, ("derived", ""))[0]
            for raw, cands in segments(key, text):
                add(host[0], kind, raw, cands, None, eid, zh)
    return rows, edges, stat, outcome


def main():
    import argparse
    import collections
    import random
    import sqlite3

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sample", type=int, default=16)
    a = ap.parse_args()

    sys_path_hack()
    import dbtool
    import paths

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows, edges, stat, outcome = build(con)
    f = lambda n: format(n, ",")
    vis = con.execute("SELECT COUNT(*) FROM example WHERE COALESCE(hidden,0)=0").fetchone()[0]
    print("■ 可见例句 %s 条，其中**不是例句** %s 条（%.2f%%）"
          % (f(vis), f(len(rows)), 100.0 * len(rows) / vis))
    for k, n in collections.Counter(r[3] for r in rows).most_common():
        print("     %-14s %s" % (k, f(n)))
    print("\n■ 分类")
    for k, n in sorted(stat.items(), key=lambda x: -x[1]):
        print("     %-38s %s" % (k[:38], f(n)))
    nnull = sum(1 for e in edges if e[3] is None)
    print("\n■ 要插 %s 条边；落点解析不出的 %s 条（%.1f%%，`target_norm=NULL` "
          "⇒ 展示层印纯文本不做链接，与 `hanja_spelling` 同一约定）"
          % (f(len(edges)), f(nnull), 100.0 * nnull / max(len(edges), 1)))
    print("     按 kind：", collections.Counter(e[1] for e in edges).most_common())

    # ── 写前代价（不是写完再看）──
    allvis = con.execute("SELECT id, word FROM example WHERE COALESCE(hidden,0)=0").fetchall()
    per = collections.Counter(w for _, w in allvis)
    kill = {r[0] for r in rows}
    kper = collections.Counter(w for i, w in allvis if i in kill)
    gone = [w for w in kper if kper[w] == per[w]]
    wid = {}
    for w, i, il in con.execute("SELECT word, id, is_lemma FROM dict ORDER BY id"):
        wid.setdefault(w, (i, il))
    addp = {e[0] for e in edges}
    naked = [w for w in gone if not (wid.get(w) and wid[w][0] in addp)]
    print("\n■ 写前代价")
    print("     受影响词条 %s；**例句区整块消失** %s 个，其中同时拿到新边的 %s 个"
          % (f(len(kper)), f(len(gone)), f(len(gone) - len(naked))))
    # 🔴 **把断言做成闸**：「这些页没拿到新边，是因为关系层早就有同向边」
    #    原来是我写在散文里的一句话。写成话它就会过期（`[[lesson-must-become-mechanism]]`）。
    kill_of = collections.defaultdict(list)
    for i, w in allvis:
        if i in kill:
            kill_of[w].append(i)
    unexplained = []
    for w in naked:
        for i in kill_of[w]:
            ways = set(outcome.get(i, []))
            if not ways or ways - {"dup", "self", "hide-only"}:
                unexplained.append((w, i, sorted(ways)))
    print("     剩下 %d 个页没拿到新边 —— 闸查过：每一行的去向都是"
          "「关系层早就有同向边／自环／只藏不迁」⇒ 零信息损失" % len(naked))
    if unexplained:
        raise SystemExit("🔴 有 %d 行说不清去向，这些页会**净损失**内容：%r"
                         % (len(unexplained), unexplained[:5]))

    pick = list(edges)
    random.Random(20260927).shuffle(pick)
    inv = {v[0]: k for k, v in wid.items()}
    print("\n■ 抽 %d 条边人眼看" % a.sample)
    for word_id, kind, raw, norm, tags, eid in pick[:a.sample]:
        print("     [%6d] %-10s --%-16s--> %-24s 落点=%-10s tags=%s"
              % (eid, (inv.get(word_id) or "?")[:10], kind, raw[:24], norm or "（纯文本）", tags))

    if not a.apply:
        print("\n（干跑。读过抽样之后 --apply）")
        return

    n_rel = con.execute("SELECT COUNT(*) FROM sense_relation").fetchone()[0]
    n_norm = con.execute(
        "SELECT COUNT(*) FROM sense_relation WHERE target_norm IS NOT NULL").fetchone()[0]
    n_tags = con.execute("SELECT COUNT(*) FROM sense_relation WHERE tags IS NOT NULL").fetchone()[0]
    n_why = con.execute(
        "SELECT COUNT(*) FROM example WHERE hidden_why IS NOT NULL AND TRIM(hidden_why)<>''"
    ).fetchone()[0]
    per_kind = dict(con.execute("SELECT kind, COUNT(*) FROM sense_relation GROUP BY 1"))
    con.close()

    ins = [(e[0], e[1], e[2], e[3], e[4], "ko-example:%d#k33" % e[5]) for e in edges]
    upd = [(WL_WHY.get(r[0], WHY[r[3]]), r[0]) for r in rows]
    with dbtool.session(
            "ko-k33-reclass-nonexamples",
            expect={"#sense_relation": len(ins),
                    "sense_relation.target": len(ins),
                    "sense_relation.target_norm": sum(1 for e in edges if e[3] is not None),
                    "example.hidden_why": len(upd),
                    "__rows__": 0},
            invalidates=[]) as s:
        s.executemany(
            "INSERT INTO sense_relation (word_id, sense_id, kind, target, target_norm,"
            " tags, hidden, src, src_ref) "
            "VALUES (?, NULL, ?, ?, ?, ?, 0, 'ko-edition', ?)", ins)
        s.executemany("UPDATE example SET hidden=1, hidden_why=? WHERE id=?", upd)

    print("\n═══ 写后回核（从库里重算，期望取自写前）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x, *p: con.execute(x, p).fetchone()[0]
    checks = [
        ("sense_relation 行数", q("SELECT COUNT(*) FROM sense_relation"), n_rel + len(ins)),
        ("target_norm 非空", q("SELECT COUNT(*) FROM sense_relation WHERE target_norm IS NOT NULL"),
         n_norm + sum(1 for e in edges if e[3] is not None)),
        ("tags 非空", q("SELECT COUNT(*) FROM sense_relation WHERE tags IS NOT NULL"),
         n_tags + sum(1 for e in edges if e[4] is not None)),
        ("新边一条不多不少", q("SELECT COUNT(*) FROM sense_relation WHERE src_ref LIKE '%#k33'"),
         len(ins)),
        ("example.hidden_why 非空",
         q("SELECT COUNT(*) FROM example WHERE hidden_why IS NOT NULL AND TRIM(hidden_why)<>''"),
         n_why + len(upd)),
        # 🔴 反向：判据再跑一遍，**可见的非例句必须是 0**
        ("可见的非例句还剩", len(plan(con)), 0),
        # 🔴 反向：没有藏错行 —— 藏的总数 ＝ 藏之前 ＋ 这次
        ("hidden=1 的例句", q("SELECT COUNT(*) FROM example WHERE COALESCE(hidden,0)=1"),
         q("SELECT COUNT(*) FROM example WHERE hidden_why IS NOT NULL "
           "AND TRIM(hidden_why)<>''")),
        # 🔴 反向：没动到别的 kind 的既有边
        ("别的来源的边一条没变",
         q("SELECT COUNT(*) FROM sense_relation WHERE src_ref NOT LIKE '%#k33' OR src_ref IS NULL"),
         n_rel),
    ]
    for kind, before in sorted(per_kind.items()):
        want = before + sum(1 for e in edges if e[1] == kind)
        checks.append(("kind=%s 条数" % kind,
                       q("SELECT COUNT(*) FROM sense_relation WHERE kind=?", kind), want))
    # 头/中/尾三条各自回读，标签从**库里**取（K11 那次从循环变量取，印错了对象）
    for pos in (0, len(edges) // 2, len(edges) - 1):
        word_id, kind, raw, norm, tags, eid = edges[pos]
        page = q("SELECT word FROM dict WHERE id=?", word_id)
        checks.append(("样例 `%s --%s--> %s` 在库里" % (page, kind, raw[:12]),
                       q("SELECT COUNT(*) FROM sense_relation WHERE word_id=? AND kind=? "
                         "AND target=? AND src_ref LIKE '%#k33'", word_id, kind, raw), 1))
        checks.append(("样例那一行例句已藏",
                       q("SELECT COALESCE(hidden,0) FROM example WHERE id=?", eid), 1))
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("     %s %-40s %11s（期望 %s）"
              % ("✅" if good else "🔴", name[:40], got, want))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


def sys_path_hack():
    import pathlib
    import sys as _s
    here = pathlib.Path(__file__).resolve().parent
    for p in (str(here.parent), str(here)):
        if p not in _s.path:
            _s.path.insert(0, p)


if __name__ == "__main__":
    sys_path_hack()
    main()
