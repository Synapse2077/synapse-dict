#!/usr/bin/env python3
"""英文版活用表的**表结构修复**。2026-09-19。零模型调用。

═══ 为什么需要这一层 ═══
`build_inflection_layer.scan()` 原来是**扁平地**遍历 `forms`：一行一行看 tag、拼中文。
但英文版的活用行不是平的，是 wiktextract 解析维基 `ja-conj` 模板**渲染出来的表格**，
而它在**行、列两个方向上都有表头识别失败**。扁平遍历看不见表，于是把源头的错原样印上了页面：

  ① 行方向：认不出的表头，整组**继承上一组**的 tag
        意志形组   → `imperative`      `食べましょう` 印成「敬体命令形」
        使役被动组 → `conditional`     `食べさせられます` 印成「敬体条件形」
        进行体组   → `desiderative`    `食べています` 印成「愿望敬体」
        已然形+ば  → `causative`       `食ぶれば` 印成「使役」（在文語表里）
     ⚠️ `desiderative` 这个 tag 在成品库里**真阳性是 0**：480 行全部是进行体，
        而真正的愿望形（`食べたい`）带着 ③ 的报错标记被整行丢掉了。

  ② 列方向：丢 `past` 这一维
        `食べます` 与 `食べました` 的 tag 集**完全相同**（都只有 `polite`），
        两行在页面上印着同一个「敬体」，读者无法区分。108 个词无一幸免。

  ③ 认不出的格子打 `error-unrecognized-form`，原来整行丢弃
        丢掉的正好是**普通体那几列** —— `食べる` 页上有「食べます」没有「食べない」。
        英文版 conjugation 行的 10.3%（6,616 行）是这样没的。

═══ 🔴 判据全部来自源头自己给的东西，不引入外部词表 ═══
- **列维度**从词形形态读：`ました` 就是敬体过去。这是**定义**不是形式代理
  （`[[criteria-from-meaning-not-form]]` 挡的是「拿形式当内容的代理」；
   活用后缀本身就是那个内容）。
- **三个合并组的分界**也从形态读，且两侧**不相交**：
  意志形收 `う`／条件形收 `ば`,`ら`,`きゃ`／愿望形含 `たい`,`たく`。
- **已然形+ば 与 未然形+ば** 用**同一块里的词干**分开（`見れ` vs `見`），不靠猜。

═══ ⭐ 每条判据都在源头标对了的格子上验过，才用到标错的格子上 ═══
- 列维度读取器：3,748 个「源头没打报错标记」的格子里，
  **唯一的分歧就是 `ました`/`ませんでした` 那 236 个** —— 即本 bug 本身。
  源头把 `食べます` 和 `食べました` 标成同一个 tag 集，两者不可能都对。
- 三处分界的连续性：118 张现代表 **118/118 全部连续，零例外**。
  （不连续就意味着我的判据和表的真实分组漂开了 —— `check()` 会大声报。）

自检：python3 ja/pipeline/infl_table.py
"""
import re

JA = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")
# 源头把限定语写在格子里：`short form: 食べさす`、`colloquial: 書かされ`。
# 🔴 这不是噪声，是**真信息**（标准形 vs 口语形、书面命令 vs 口头命令），要变成 tag 不是丢掉。
QUALIFIER = {
    "contraction": "contraction", "colloquial": "colloquial",
    "short form": "short-form", "standard": "standard",
    "written": "written", "spoken": "spoken",
}
_PRE = re.compile(r"^([^:：]{1,14})[:：]\s*(.+)$")
# 🔴 英文版把**词形和转写写在同一个单元格**里：`'食べれます [taberemasu]'`。
#    词形归词形、转写进 `inflection.romaji` —— 判据同 `build_inflection_layer.split_romaji`：
#    整串结尾是一个方括号组，且括号内不含方括号、不含日文字符。
_ROM = re.compile(r"^(.*?)\s*\[([^\[\]]*)\]$")

# 🔴 长的在前 —— 选择支顺序就是判据，短的挡长的会把「ませんでした」读成「ません」
#    （`[[regex-alternation-order]]`：同一个 bug 犯过三次）。
COLUMN = [
    ("ませんでした", ("negative", "polite", "past")),
    ("ました",       ("polite", "past")),
    ("ません",       ("negative", "polite")),
    ("ましょう",     ("polite",)),          # 意志形敬体，`past` 不能沾
    ("ます",         ("polite",)),
    ("なかったら",   ()),                    # たら条件形，不是过去
    ("なかった",     ("negative", "past")),
    ("なければ",     ()),
    ("なきゃ",       ()),
    ("ないでください", ("negative",)),
    ("ないで",       ("negative",)),
    ("なくて",       ("negative",)),
    ("ない",         ("negative",)),
    ("ず",           ("negative",)),
    ("ざる",         ("negative",)),
    ("たら",         ()),                    # 条件形
    ("だら",         ()),
    ("たり",         ()),
    ("た",           ("past",)),
    ("だ",           ("past",)),
]
COL_TAGS = {"polite", "negative", "past"}

# 合并组的**第一组**怎么认（剩下的就是被继承 tag 的第二组）。
# 判据写成「第一组是什么」而不是「第二组是什么」：第一组的形态是封闭的，
# 第二组是残差 —— `[[residual-bucket-is-not-evidence]]`，残差不能当判据，只能当结论。
# 命令形那一组，源头把四件事打成同一个 `imperative`：
#     食べろ/食べよ 命令　食べてください 依頼　食べなさい 丁寧な命令　食べるな 禁止
# 结果 `食べないでください` 与 `食べるな` 在页面上同印「否定命令形」。
# 🔴 判据是**格子文本自己**（〜てください＝依頼，是定义不是代理），加成括号限定语。
IMPERATIVE_QUAL = (
    ("でください", "request"),
    ("てください", "request"),
    ("なさい",     "nasai"),
    ("な",         "prohibitive"),
)

SPLIT = {
    "imperative":   (lambda f: not f.endswith("う"),                 ("volitional",)),
    "conditional":  (lambda f: f.endswith(("ば", "ら", "きゃ")),      ("causative", "passive")),
    "desiderative": (lambda f: "たい" in f or "たく" in f,            ("progressive",)),
}


def clean(form):
    """`'short form: 食べさす [tabesasu]'` → `('short-form', '食べさす', 'tabesasu')`。"""
    s = (form or "").strip()
    q = None
    m = _PRE.match(s)
    # ⚠️ 限定语必须是**纯拉丁**的，否则 `頭に来る` 这种带「に」的词形会被当成 `頭:` 切掉
    if m and not JA.search(m.group(1)):
        q = QUALIFIER.get(m.group(1).strip().lower())
        if q:
            s = m.group(2)
    rom = None
    m = _ROM.match(s)
    if m and not JA.search(m.group(2)):
        s, rom = m.group(1).strip(), m.group(2).strip() or None
    return q, s, rom


def column_tags(form):
    for suf, tags in COLUMN:
        if form.endswith(suf):
            return set(tags)
    return set()


# 🔴 只有这两张表的结构被逆出来了。其余模板（`inflection-table-top` 78 张 —— 形容词/
#    名词＋コピュラ 的 `COOLじゃない` 那类、`ja-see` 6 张）**原样走扁平老路**。
#    第一版我让扁平路径跳过了所有 `source=='conjugation'` 行，于是这 78 张表被整块丢掉，
#    干跑时 1,896 条「消失的词形」说不出理由 —— 风险方向上的检查逮到的。
HANDLED = {"ja-conj-ex", "ja-conj-bungo"}


def blocks(entry):
    """一个 dump 条目 → `[(模板名, [(下标, 格子), …]), …]`。表结构只在英文版里有。"""
    out, cur = [], None
    for i, f in enumerate(entry.get("forms") or []):
        if f.get("source") != "conjugation":
            continue
        t = f.get("tags") or []
        if "inflection-template" in t:
            cur = (f["form"], [(i, f)])
            out.append(cur)
        elif cur is not None:
            cur[1].append((i, f))
    return out


def consumed(entry):
    """表修复路径**真正消费掉**的 `forms` 下标；其余的必须留给扁平路径。"""
    return {i for name, cells in blocks(entry) if name in HANDLED for i, _ in cells}


def _runs(cells):
    """按「主 tag」（去掉列维度与报错标记）切成连续段 —— 表的行分组就是这个。"""
    out, prev = [], object()
    for c in cells:
        if c["primary"] != prev:
            out.append((c["primary"], []))
            prev = c["primary"]
        out[-1][1].append(c)
    return out


def _parse(block_cells):
    cells = []
    for _i, f in block_cells:
        t0 = f.get("tags") or []
        if "inflection-template" in t0 or "table-tags" in t0:
            continue                  # 模板名/表级标记行，不是词形
        q, s, rom = clean(f.get("form"))
        if not JA.search(s):          # 占位符 `-`、`For other desiderative forms`
            continue
        raw = set(f.get("tags") or [])
        clean_tags = {x for x in raw if not x.startswith("error-")}
        cells.append({
            "form": s, "qual": q, "romaji": rom,
            # `primary` 只留行方向（语态/体/活用形），列方向单独拿
            "primary": frozenset(clean_tags) - COL_TAGS,
            "col_src": frozenset(clean_tags & COL_TAGS),
        })
    return cells


def _col(cell):
    """列维度＝**源头给的 ∪ 从形态读出来的**。

    🔴 取并集不是保守，是**验过的**：3,866 个「源头没打报错标记」的格子里，
       源头的列 tag 永远是推导结果的子集（差的那 236 个正是源头丢掉的 `past`）。
       ⇒ 并集对现代表与「只用推导」等价；而文語表没进过那轮验证，并集才不会丢
       （`食べき` 的 `past`、`食べるな` 的 `negative` 都只有源头写了）。
    """
    return set(cell["col_src"]) | column_tags(cell["form"])


def repair_modern(block_cells):
    """现代活用表 → `[(词形, tag 集, 罗马字), …]`。词干格子丢弃（见下）。"""
    cells = _parse(block_cells)
    for primary, items in _runs(cells):
        key = next((k for k in SPLIT if k in primary), None)
        if key:
            is_first, second_tags = SPLIT[key]
            n = sum(1 for c in items if is_first(c["form"]))
            for i, c in enumerate(items):
                c["primary"] = primary if i < n else frozenset(second_tags)
        # 命令形那一组加限定语（意志形那一半已经在上面换成 volitional 了，不会被误加）
        if "imperative" in primary:
            for c in items:
                if "imperative" not in c["primary"]:
                    continue
                for suf, qual in IMPERATIVE_QUAL:
                    if c["form"].endswith(suf):
                        c["qual"] = c["qual"] or qual
                        break
    out = []
    for i, c in enumerate(cells):
        # 词干格子：**是下一个格子的真前缀**（`食べられ` → `食べられる`）。
        # 它不是读者能用的形，和修复前一样丢弃 —— 这一条不改行为。
        if i + 1 < len(cells) and cells[i + 1]["form"].startswith(c["form"]) \
                and cells[i + 1]["form"] != c["form"] \
                and cells[i + 1]["primary"] == c["primary"]:
            continue
        t = set(c["primary"]) | _col(c)
        if c["qual"]:
            t.add(c["qual"])
        out.append((c["form"], t, c["romaji"]))
    return out


def repair_bungo(block_cells):
    """文語表 → `[(词形, tag 集, 罗马字), …]`，每行加 `bungo`。

    🔴 源头把**已然形+ば**标成了 `causative`（`見れば` 印成「使役」）。
       同一块里就有已然形词干（`realis`+`stem` ⇒ `見れ`）和未然形词干（`irrealis` ⇒ `見`），
       用词干把两个「～ば」分开，不引入外部知识。
    """
    cells = _parse(block_cells)
    realis = {c["form"] for c in cells if {"realis", "stem"} <= set(c["primary"])}
    out = []
    for c in cells:
        t = set(c["primary"]) | _col(c) | {"bungo"}
        if "causative" in t and c["form"].endswith("ば"):
            t.discard("causative")
            t |= {"realis-conditional"} if any(
                c["form"].startswith(r) for r in realis) else {"conditional"}
        if c["qual"]:
            t.add(c["qual"])
        out.append((c["form"], t, c["romaji"]))
    return out


def mark_ranuki(rows):
    """**ら抜き言葉**：`食べれる` 与规范的 `食べられる` 并列印着，不标出来读者会当成
    两套都规范的可能形。就地给 tag 集加 `ra-nuki`，返回标了几行。

    🔴 判据是**派生关系**：ら抜き形必须是同一原形下某个「られ」形**去掉那个「ら」**
       得到的（`食べられます` → `食べれます`）。
       ⚠️ 第一版写的是「同原形下有『られ』对照，且自己不含『られ』」—— 太宽，
       把サ変的文語可能形 `熱しえる`/`達しえる`（〜し得る）误标成了ら抜き。
       两条误标是逐条核对标注结果时看出来的，不是闸逮的
       （`[[criteria-narrower-than-you-think]]`：判据比它要描述的东西更宽，最高频自伤）。
    ⚠️ 五段动词的可能形（`書ける`）本来就不含「られ」，派生判据自然不碰它。
    ⭐ 放在这里而不是放在表修复里：ら抜き两版都有（日语版给 `得られる`/`得れる`
       是两条扁平行，没有表结构），**判据只许一份**，两份迟早漂开
       （`[[refactor-mindset-code-quality]]`）。

    rows: `[(词形, 原形, tag 集), …]`，tag 集就地改。
    """
    derived = {}
    for form, base, tags in rows:
        if "potential" in tags and "られ" in form:
            derived.setdefault(base, set()).add(form.replace("られ", "れ", 1))
    n = 0
    for form, base, tags in rows:
        if "potential" in tags and form in derived.get(base, ()):
            tags.add("ra-nuki")
            n += 1
    return n


def repair(entry):
    """一个条目 → `[(词形, tag 集, 罗马字, 模板名), …]`；非活用表的 forms 走老路。"""
    out = []
    for name, cells in blocks(entry):
        fn = {"ja-conj-ex": repair_modern, "ja-conj-bungo": repair_bungo}.get(name)
        if fn:
            out += [(f, t, r, name) for f, t, r in fn(cells)]
    return out


def check():
    """判据自检：在**源头标对了的格子**上验列读取器，并验三处分界的连续性。"""
    import json
    import sys
    import pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    import paths

    agree = disagree = 0
    known = 0            # 已知的源头错：`ました`/`ませんでした` 丢了 past
    ntab = noncontig = 0
    for line in open(paths.KK, encoding="utf-8"):
        o = json.loads(line)
        for name, cells in blocks(o):
            if name != "ja-conj-ex":
                continue
            ntab += 1
            parsed = _parse(cells)
            # 列读取器 vs 源头（只看没打报错标记的格子）
            for _i, raw in cells:
                t = set(raw.get("tags") or [])
                if "inflection-template" in t or "table-tags" in t:
                    continue
                if any(x.startswith("error-") for x in t):
                    continue
                _, s, _rom = clean(raw.get("form"))
                if not JA.search(s):
                    continue
                src, got = t & COL_TAGS, column_tags(s)
                if src == got:
                    agree += 1
                elif got == src | {"past"}:
                    known += 1
                else:
                    disagree += 1
                    print("   ✗ 列维度分歧 %s 源头=%s 读出=%s" % (s, sorted(src), sorted(got)))
            # 三处分界的连续性
            for primary, items in _runs(parsed):
                key = next((k for k in SPLIT if k in primary), None)
                if not key:
                    continue
                idx = [i for i, c in enumerate(items) if SPLIT[key][0](c["form"])]
                if idx != list(range(len(idx))):
                    noncontig += 1
                    print("   ✗ 分界不连续 %s %s %s" % (o.get("word"), key,
                                                        [c["form"] for c in items]))
    print("现代活用表 %d 张" % ntab)
    print("列维度读取器：一致 %d ｜源头丢 past（本 bug）%d ｜**无法解释的分歧 %d**"
          % (agree, known, disagree))
    print("三处合并组分界：**不连续 %d**" % noncontig)
    assert disagree == 0, "🔴 列维度读取器出现无法解释的分歧，判据和数据漂开了"
    assert noncontig == 0, "🔴 合并组分界不连续，说明分组判据与表的真实分组不一致"
    assert known == 236, "🔴 已知的 past 丢失数变了（原 236），源头 dump 换过？"
    print("✅ 判据自检通过")


if __name__ == "__main__":
    check()
