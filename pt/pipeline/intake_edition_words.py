#!/usr/bin/env python3
"""阶段 3b：从各版收词 —— `dict` 词形层 + `entry` 词条层。2026-08-29。

用户 2026-08-22 在 fr 上定的方针沿用：**全收**（`[[dict-scope-four-rules]]` 第①条
「词汇尽量全」）。pt 这一轮几乎是白送的 —— 新增 643,117 个词形里 **92.6% 是变形**，
走 `infl_compose` 确定性生成中文，**零模型调用**；花钱的真词头只有 47,581 个。

═══ 为什么是一份带 `--edition` 参数的脚本，不是每版一份 ═══
fr 那轮写了 `intake_fr_words.py`（法文版）+ `intake_other_editions.py`（其余版）两份。
pt 的分工不同 —— **两版都是主力**：

    葡语版  给**真词头** 42,033（独有 165,605）
    法语版  给**变形**   394,064（独有 324,329）
    英文版  的 `forms` 再给变形 94,267

各版的处理逻辑逐字相同，只差「读哪个文件、按不按 lang_code 筛、src 标什么」。
⇒ 参数化。**这不违反铁律①**（那条说的是"按语种解耦、不跨语种 import"，
   pt 内部按版本参数化恰恰是「不要在同一文件里手抄第二份」——
   `[[regex-alternation-order]]`：抽了常量却在另一文件又手抄一份窄的，坏了 43 条）。

═══ 🔴 pt 必须做、而 fr 不需要做的一件事：收 `forms` 数组 ═══
**法语维基给每个屈折形式单独建页** ⇒ 顶层 `word` 就抓得到 `mangeraient`。
**葡语维基不建那些页** ⇒ 变位形只活在词条内部的 `forms` 变位表里。
实测每条目 forms 条数：葡语版 **51.9**（完整动词变位表；葡语还多出**人称不定式**
和**将来虚拟式**两个西/法都没有的时态）、英文版 9.1。
⇒ 只收顶层会漏掉整个变位层：并集残差 219,756 → **643,117**（差 2.9 倍）。
（这个洞是用户 2026-08-29 问「pt 词汇量没过百万，正常吗」问出来的。）

═══ 落点预检的五个结论（`docs/lang/pt-CONVENTIONS.md` §四之二）═══

**① 撇号：pt 上不是问题，但仍归一。** 库 156:1 ／ 葡语版 105:6 ／ 法语版 0:8。
   归一只影响 14 条（fr 那轮是 20,198:23 的约定相反、影响两万条）。
   仍然做，是因为成本近零而收益是避免 `l'` 类分裂成两个词条。

**② 大小写一律原样收，不折叠。** 阶段 3a 刚证明 `abissínia`/`Abissínia` 是不同的词。
   `build.py:340` 当年的 `key = word.lower()` 是缺陷，不复刻。

**③ 重音符差异照收（2,222 个）。** 🔴 葡语比法语更硬：
   `avo`（分数）/ `avó`（祖母）/ `avô`（祖父）**是三个不同的词**，不是编码问题。

**④ 🔴 葡语版和法语版都没有 `etymology_number`**（实测各 0 条；英文版有 10,864）。
   ⇒ `src_ref` 不能照抄英文版的 `kk-en:<词形>:<词性>:<词源号>:<seq>`，
      改用 `kk-<版>:<词形>:<词性>#<该键第几条JSON>`。fr/it 两轮对非英文版同样处理。

**⑤ 两个 `POS_MAP` 盖不到的词性，逐个显式映射。**
🔴 **一个都不用默认值填平** —— `[[prompt-self-harm-two-patterns]]`：
   `pos or "v"` 把分类名、缩写、词缀全说成动词，落库 404 行。

    abbrev  1,344  → **原样**（`dict-labels/common.ts:50` 已有 `abbrev: '缩写'`，
                     不造新短码 —— 共享包的收益就在这里）
    root        1  → **原样**（`abelh-` = abelha 的词根；映射成 `pref` 是错的，
                     词根不是前缀）。共享包已补 `root: '词根'`。

═══ 本步只收「词形 + 词条」，不收义项 ═══
葡语版的 **155,329 条真释义**归阶段 1.5。变形的中文说明归 3b 之后的 `infl_compose`。
一次只动一样东西（`[[one-problem-at-a-time]]`）。

═══ 闸 ═══
① `dbtool` 的 expect 闸：插行时**所有列的非空计数都会跟着涨**，必须逐列显式声明，
   闸门才拦得住"多写了一列"。未声明的列变了就报错。
② 不变量断言：新词形不在旧库里 / `word_norm` 非空 / entry 无孤儿 / `src_ref` 无重复 /
   撇号归一后库内不再有弯撇。
③ 抽样反验：随机打印新收的词形供人眼核（确定性收词，但**新词形对不对**只有人看得出来）。

用法（在 pt/ 目录下）：
    python3 pipeline/intake_edition_words.py --edition pt            # 干跑
    python3 pipeline/intake_edition_words.py --edition pt --apply
    python3 pipeline/intake_edition_words.py --edition fr --apply
"""
import argparse
import gzip
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from build_entry_layer import POS_MAP as POS_EN   # noqa: E402

D = paths.DUMPS
# (键, 文件, 是否按 lang_code 筛)
EDITIONS = {
    "pt": (D / "ptwiktionary.jsonl.gz", True),
    "fr": (D / "frwiktionary.jsonl.gz", True),
    "en": (D / "kaikki.org-dictionary-Portuguese.jsonl", False),
    "zh": (D / "zhwiktionary.jsonl.gz", True),
    "de": (D / "dewiktionary.jsonl.gz", True),
    "es": (D / "eswiktionary.jsonl.gz", True),
    "it": (D / "itwiktionary.jsonl.gz", True),
    # ══════ 2026-08-30 补下的八个 per-language 切片 ══════
    # 🔴 用户问「每门语言所需的 dump 应该都不一样吧，这个你确认过吗」时补的。
    #    阶段 -1 的记账①写着「先不下，**等阶段 3 有残差缺口再议**」——
    #    阶段 3 早就完了，我没回头议。**带触发条件的决定最容易死在原地。**
    #
    # ⭐ `scripts/probe_editions.py` 读索引页（零下载）量出来：**pt 的版本排名与 fr 完全不同**
    #       对 fr 收益最大的 el(16,148)/tr(14,109)，对 pt 只有 3,181/2,068 —— **差 100 倍**
    #       对 pt 存量最大的是 ja 18,670 / ru 14,669 / pl 13,716，而 fr 那轮 ja 版几乎白下
    #    ⇒ **照抄别的语种的源清单就会下错源。**
    #
    # ⚠️ 顺手补了 `probe_editions.NAMES` 里葡语的土耳其名 `Portekizce` 与捷克名
    #    `portugalština` —— 与该文件里 `it` 那条注释是**同一个坑的第二次**
    #    （土耳其语的 `İtalyanca` 曾差点漏掉 154,681 条意语义项）。
    #
    # 🔴 **落点一量，故事就变了**（`[[measure-landing-not-source]]`）：
    #       源头 ja 音标 13,016 (93.6%)  →  真能补音标的词形只有 138
    #       源头 pl 录音  6,585 (56.2%)  →  真能补录音的词形     718
    #       八版并集：新词形 2,508 ／ 补音标 254 ／ **补录音 814（+15.9%）**
    #    ⇒ 唯一有分量的是**录音**，而录音正是 pt 全库最薄的一层。
    #
    # 这些切片已按语种切好，`lang_code` 实测 100% 是 pt ⇒ 无需再筛。
    "ja": (D / "kaikki.org-jawiktionary-Portuguese.jsonl.gz", False),
    "ru": (D / "kaikki.org-ruwiktionary-Portuguese.jsonl.gz", False),
    "pl": (D / "kaikki.org-plwiktionary-Portuguese.jsonl.gz", False),
    "el": (D / "kaikki.org-elwiktionary-Portuguese.jsonl.gz", False),
    "ko": (D / "kaikki.org-kowiktionary-Portuguese.jsonl.gz", False),
    "tr": (D / "kaikki.org-trwiktionary-Portuguese.jsonl.gz", False),
    "nl": (D / "kaikki.org-nlwiktionary-Portuguese.jsonl.gz", False),
    "cs": (D / "kaikki.org-cswiktionary-Portuguese.jsonl.gz", False),
}

# ══════ 🔴 这两版**不收词形**（音标/录音照收）══════
# 2026-08-30 抽样反验逐版看出来的。**收不收词形是逐版判断，不是整批判断** ——
# 同一批下载里六版干净、两版脏。
#
#   ja  日语版的变位表在**机器生成比较级构式**：
#         `o mais frequentemente`（「最…地」是句法构式不是词形）／`o mais meio`（无意义）
#         `poréms`（`porém` 是连词，没有复数）／`tears`（英语）
#         🔴 `orientação sexuals` —— **复数变错了**（该是 `orientações sexuais`）
#   cs  捷克语版的表里塞了**同源词对照**，外语直接混进来：
#         `mintieren`（德）／`brandierais`（法）／`quiere`（西）／`pulcrissimo`（意）
#       ⚠️ 这两版的 `lang_code` **实测 100% 是 pt** —— 语种标签是对的，
#          脏的是 `forms` 数组的内容。**标签对不等于内容对。**
#
# ⇒ 它们的价值在音标与录音（挂在已有词上，没有假词风险），不在词形。
#   `harvest_pronunciation` / `ingest_audio` 照扫这两版，只有本文件跳过。
INTAKE_SKIP = {
    "ja": "变位表机器生成比较级构式 + 复数变错（`orientação sexuals`）",
    "cs": "forms 里混着德/法/西/意语同源词",
}

# 🔴 收词的撇号约定。改这里等于改全库的词形，动之前先读上面 ① 那段。
APOS = {"’": "'", "ʼ": "'", "‘": "'"}

# 英文版的映射 + 葡语版独有的两个（见 ⑤）。两个都是**原样**，写出来是为了
# 「显式声明过」而不是"默认值兜住了"——下次有人加第三个时能看见这条规矩。
POS_MAP = dict(POS_EN)
POS_MAP.update({"abbrev": "abbrev", "root": "root"})

# `forms` 数组里不是词形的行。判据只在 `_real_forms()` 一处。
#
# 🔴 2026-08-29 第一版的过滤太松，**抽样反验当场逮到**：
#       tinchamos¹ /
#       tinchámos²          ← 一个表格单元格塞了两个形式 + 脚注标记 + 换行
#    这正是抽样存在的理由 —— 不变量只能证明"没改到不该改的范围"，
#    证明不了"改对了内容"，后者只有人眼看得出来（`dbtool.sample_check` 的文档原话）。
#
# 逐类量过之后的判据（每一条都读过样本，不是看形状猜的）：
#
#   含句点 `.`      2,041  **全是音节划分或注记**，一条真词形都没有 ——
#                          `gre.go`（grego 的音节划分）/ `praxologia [ pra.xo.lo.gi.a ]` /
#                          `bacial || ba.ci.al` / `Nota: Verbos unipessoais…`。
#                          ⚠️ 判据是"含点就不是屈折形式"（葡语屈折形式不含句点），
#                          不是"去点等于词头"——后者漏掉 54 条残缺写法。
#   一格多形 1,025  `triplicamos¹ /\ntriplicámos²`（巴葡/欧葡两拼写）、`adequo / adéquo`
#                          ⇒ **拆开**，不是丢掉。拆完每片再过一遍全部规则。
#   空占位     720  `-` `—` `–` `?` `−`（en dash 第一版没挡住）
#   注记        17  以 `(` 开头：`(Vocábulo com dupla grafia: bissetriz)`
#
# ⚠️ **含空格的 39,166 条是真词形，绝不能丢** —— `não ababalhes` 是葡语的否定命令式
#    （não + 虚拟式），多词形式在葡语里就是正当的屈折形式。
_FORM_JUNK_TAGS = {"table-tags", "inflection-template", "class"}
_PLACEHOLDER = {"-", "—", "–", "−", "?", ""}
_FOOTNOTE = str.maketrans("", "", "¹²³⁴⁵⁶⁷⁸⁹⁰*†‡")

# ══════ 🔴 法语版特有的两类噪声（葡语版完全没有）══════
# 抽样反验在 3b-2 干跑时逮到：法语版的葡语变位表**把主语代词写进了单元格**，
# 照收就是往库里灌 30 多万条 `eu solidificarei`、`que nós amorteçamos` 这种假词形。
#
# ① **法语时态名当表头漏进 forms**：`Indicatif` 137,658 / `Présent` 132,747 /
#    `Subjonctif` 71,516 / `Imparfait` 51,282 …前 10 种就占 511,000 条。
#    它们**根本不是葡语**。封闭黑名单，不用形状判。
#
# ② **代词/连词单元格**：`você/ele/ela une` / `que eu une` / `se eu for` 共 238,556 条。
#    🔴 **实测末词与词头逐条相同的比例是 100.0%（238,556/238,556，零例外）** ——
#    法语版给变位形式也建页，页内小表标的是"这个形式出现在哪些位置"，
#    单元格只是在重复词头本身。⇒ **整格丢掉，零信息损失**（这是量出来的，不是推断）。
#
# ⚠️ 三条**不能**被这两条规则误伤，逐条验过：
#    · `não abdiques` —— 否定命令式是**真形式**（带 tags），`não` 不在代词表里 ✓
#    · `se digne` / `se dignem` —— 反身动词 `dignar-se` 的形式，`se` 是**反身代词**
#      不是连词。判据写成「`se` **后面跟主语代词**才算连词」，所以它们活着 ✓
#    · 尾部 866 种无 tags 的真词形（`colecção`/`direcção`/`tática`/`dezenove` 这些异体拼写）
#      —— 所以判据**不能**简化成"只收带 tags 的"，那会把它们一起杀掉 ✓
_FR_TABLE_LABELS = {
    "Indicatif", "Présent", "Subjonctif", "Imparfait", "Impératif", "Conditionnel",
    "Futur", "Participe", "Passé", "Gérondif", "Infinitif",
    "Passé simple", "Plus que parfait", "Infinitif personnel", "(verbe défectif)",
}
# 葡语主语代词（法语版变位表的行首）。`não` **不在这里**，它是否定命令式的一部分。
_SUBJECT = {"eu", "tu", "ele", "ela", "você", "nós", "vós", "eles", "elas", "vocês",
            "você/ele/ela", "vocês/eles/elas", "ele/ela", "eles/elas"}
_CONJ = {"que", "quando"}


def norm_apos(s):
    """把弯撇归一成直撇。

    🔴 **护栏：不含字母的词形一个字节都不碰。**
    库里有一条 `‘ ’` —— 葡语维基给这对弯引号建的**标点词条**（`pos='punct'`）。
    归一它会变成 `‘ '`，**把这个词条要讲的东西本身给毁了**。
    ⇒ 判据不是"含弯撇就归一"（那是形状代理），是"**词里的撇号**才归一" ——
      以标点为内容的词条，那些字形就是它的词义。
      （`[[criteria-from-meaning-not-form]]`；实测葡语版 6 条被归一的全是真词：
       `fim-d’águas` / `alface-d’água` / `traveler’s check`，一条标点词条都没误伤。）
    """
    if not any(c.isalpha() for c in s):
        return s
    for a, b in APOS.items():
        s = s.replace(a, b)
    return s


def unaccent(s):
    """与 `build.py` 的 `word_norm` 口径逐字一致 —— 这个口径只有这一份。"""
    nfd = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _real_forms(fm, edition):
    """→ 词形列表（一个单元格可能装着多个形式）。判据见上面那段。

    `edition` 参与判据：法语版的表格约定与葡语版不同，同一个 `/` 在两版里
    含义都不一样（葡语版 `adequo / adéquo` 是两个形式；法语版 `você/ele/ela` 是一串代词）。
    ⇒ **法语版特有的两条规则先跑，跑完再进通用规则**（那时 `/` 已经不会误伤了）。
    """
    raw = fm.get("form")
    if not raw or _FORM_JUNK_TAGS & set(fm.get("tags") or []):
        return []
    if edition == "fr":
        t = raw.strip()
        if t in _FR_TABLE_LABELS:                 # ① 法语时态名，不是葡语
            return []
        p = t.split()
        if len(p) > 1:
            # ② 代词/连词单元格（实测 100% 只是重复词头）
            if p[0] in _SUBJECT or p[0] in _CONJ:
                return []
            # `se` 只有**后面跟主语代词**时才是连词；`se digne` 是反身动词的真形式
            if p[0] == "se" and p[1] in _SUBJECT:
                return []
    out = []
    # 一格多形：`/`、换行、逗号都是单元格内的分隔符
    for piece in re.split(r"[/\n,]", raw):
        x = piece.translate(_FOOTNOTE).strip()      # 剥脚注标记
        if not x or x in _PLACEHOLDER or len(x) > 60:
            continue
        if "." in x:                                # 音节划分 / 注记
            continue
        if x[0] in "([{" or "|" in x or "]" in x:   # 注记 / 表格残渣
            continue
        out.append(x)
    return out


def opener(p):
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def scan(edition, have):
    """→ (new, entries, stat)

    new[word]     = {"pos": set, "lemma": bool}   要新建的 dict 行
    entries       = [(word, pos_raw, occ)]        该版所有条目的 entry 行
    have          = 库里已有的词形（**已归一撇号**）
    """
    path, need_filter = EDITIONS[edition]
    new, entries = {}, []
    occ_of, stat = Counter(), Counter()

    with opener(path) as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                stat["坏行"] += 1
                continue
            if need_filter and e.get("lang_code") != "pt":
                continue
            w0 = (e.get("word") or "").strip()
            if not w0:
                continue
            w = norm_apos(w0)
            if w != w0:
                stat["撇号被归一的条目"] += 1
            pos_raw = e.get("pos") or ""
            key = (w, pos_raw)
            occ = occ_of[key]
            occ_of[key] += 1
            entries.append((w, pos_raw, occ))
            stat["条目"] += 1

            # 真词头 = 有 gloss 且不是 form_of/alt_of 指针
            real = any(s.get("glosses") and not (s.get("form_of") or s.get("alt_of"))
                       for s in (e.get("senses") or []))
            if w not in have:
                r = new.setdefault(w, {"pos": set(), "lemma": False})
                r["pos"].add(POS_MAP.get(pos_raw, pos_raw))
                r["lemma"] |= real
                stat["新词形（顶层）"] += 1 if len(r["pos"]) == 1 and not r["lemma"] else 0

            # 🔴 pt 特有：变位表里的形式也是词形（见文件头）
            for fm in (e.get("forms") or []):
              for x in _real_forms(fm, edition):
                x = norm_apos(x)
                stat["forms 词形"] += 1
                if x in have or x in new:
                    continue
                # 变位表里的形式**按定义是变形**：is_lemma=0，词性随本条目
                new[x] = {"pos": {POS_MAP.get(pos_raw, pos_raw)}, "lemma": False}
                stat["🔴 新词形（只在 forms 里）"] += 1
    stat["新词形（合计）"] = len(new)
    return new, entries, stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--edition", required=True, choices=sorted(EDITIONS))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="强收 INTAKE_SKIP 里的版本（先读那段注释）")
    a = ap.parse_args()
    path, _ = EDITIONS[a.edition]
    if not path.exists():
        sys.exit("🔴 dump 不存在：%s" % path)
    if a.edition in INTAKE_SKIP and not a.force:
        sys.exit("🔴 %s 版**不收词形**：%s\n"
                 "   （它的音标/录音照收，见 INTAKE_SKIP 那段。真要收传 --force）"
                 % (a.edition, INTAKE_SKIP[a.edition]))

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {norm_apos(w) for (w,) in con.execute("SELECT word FROM dict")}
    print("■ 库内词形 %s（撇号归一后 %s）"
          % (f"{con.execute('SELECT count(*) FROM dict').fetchone()[0]:,}", f"{len(have):,}"))
    con.close()

    print("■ 扫 %s-edition …" % a.edition)
    new, entries, stat = scan(a.edition, have)
    for k, v in sorted(stat.items()):
        print("   %-32s %10s" % (k, f"{v:,}"))
    n_lemma = sum(1 for r in new.values() if r["lemma"])
    print("\n   %-32s %10s" % ("→ 新 dict 行", f"{len(new):,}"))
    print("   %-32s %10s" % ("   其中真词头（is_lemma=1）", f"{n_lemma:,}"))
    print("   %-32s %10s" % ("   其中变形（is_lemma=0）", f"{len(new) - n_lemma:,}"))
    print("   %-32s %10s" % ("→ entry 行", f"{len(entries):,}"))

    print("\n── 新词形抽样 20 条 ──")
    import random
    random.seed(0)                      # 可复现
    for w in random.sample(sorted(new), min(20, len(new))):
        r = new[w]
        print("   %-28s lemma=%d pos=%s" % (w, r["lemma"], "/".join(sorted(r["pos"]))))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    return apply_(a.edition, new, entries)


def apply_(edition, new, entries):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    nid = con.execute("SELECT max(id) FROM dict").fetchone()[0]
    con.close()

    rows, ent_rows = [], []
    for w in sorted(new):
        nid += 1
        r = new[w]
        rows.append((nid, w, unaccent(w), "/".join(sorted(r["pos"])), 1 if r["lemma"] else 0))
    # entry 要 word_id：新旧词形都要能查到
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ids = {norm_apos(w): i for i, w in con.execute("SELECT id, word FROM dict")}
    con.close()
    ids.update({w: i for i, w, _, _, _ in rows})
    src = "%s-edition" % edition
    for w, pos_raw, occ in entries:
        wid = ids.get(w)
        if wid is None:
            continue
        ent_rows.append((wid, w, POS_MAP.get(pos_raw, pos_raw), pos_raw, "0", 0, src,
                         "kk-%s:%s:%s#%d" % (edition, w, pos_raw, occ)))

    print("\n■ 将写入：dict %s 行 ／ entry %s 行" % (f"{len(rows):,}", f"{len(ent_rows):,}"))
    # 🔴 插行时 `pos` 的非空计数会跟着涨，必须显式声明 —— 未声明的列变了就报错。
    #    `word`/`word_norm`/`is_lemma` 是身份列，不在 TRACK 里（非空计数恒等于总行数）。
    with dbtool.session("keep-v3-intake-%s" % edition,
                        expect={"__rows__": len(rows), "pos": len(rows),
                                "#entry": len(ent_rows)}) as s:
        s.executemany(
            "INSERT INTO dict (id,word,word_norm,pos,is_lemma) VALUES (?,?,?,?,?)", rows)
        s.executemany(
            "INSERT OR IGNORE INTO entry "
            "(word_id,word_src,pos,pos_raw,etym_no,seq,src,src_ref) "
            "VALUES (?,?,?,?,?,?,?,?)", ent_rows)

    return verify(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True), edition)


def verify(con, edition):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    checks = [
        ("word_norm 为空", q("SELECT count(*) FROM dict WHERE TRIM(COALESCE(word_norm,''))=''"), 0),
        ("pos 为空", q("SELECT count(*) FROM dict WHERE TRIM(COALESCE(pos,''))=''"), 0),
        # 🔴 判据同 `norm_apos()` 的护栏：只查**含字母的**词形。
        #    `‘ ’`（标点词条）里的弯撇是它的内容，不是待归一的撇号。
        ("🔴 含字母的词形里仍有弯撇（撇号归一失败）",
         sum(1 for (w,) in con.execute("SELECT word FROM dict WHERE instr(word,?)>0", ("’",))
             if any(c.isalpha() for c in w)), 0),
        ("孤儿 entry（word_id 不在 dict）",
         q("SELECT count(*) FROM entry e LEFT JOIN dict d ON d.id=e.word_id "
           "WHERE d.id IS NULL"), 0),
        ("重复词形（word 必须唯一）",
         q("SELECT count(*) FROM (SELECT word FROM dict GROUP BY word HAVING count(*)>1)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %10s  期望 %s" % ("✓" if good else "🔴", name, f"{got:,}", f"{want:,}"))
    print("\n%s" % ("✓ 闸全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
