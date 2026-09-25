#!/usr/bin/env python3
"""阶段 6b —— `examples` 里混着的关系数据 → `sense_relation`。零模型调用。2026-09-24。

═══ 这批数据是哪来的 ═══
五个版本的 `examples` 字段里混着 **9,967 行不是例句的东西**，形如 `标签: 内容`：

    동사: 패배하다   약자: 臥竜   近义词：추   준말: 막   센말: 따뜻하다

`harvest_examples.py` 把它们挑出来落账在 `data/work/ko/example_labeled_rows.tsv`，
本脚本把它们接进关系层。🔴 **阶段 2d 整路漏收了这些** ——
中文简体片当初只给了关系层 275 条，而它的 `examples` 里就藏着上千条边。

═══ 🔴🔴 两家外审的四条具体断言，实测**三条是错的** ═══
按 `[[consult-two-models-on-rules]]` 的规矩，每条建议都在数据上量过：

    断言                                          谁说的      实测
    中/日文词性标签的目标是「中文对译」不是韩语词      v4pro    **100% 含谚文，纯汉字 0 个**  ❌
    固定「词条→目标」会让 ≥35% 的边反向             两家     **1.7%**（118/6,800）        ❌量级
    약자/정자 里约 20% 目标是谚文                   豆包     **1.3%**（14 条）             ❌量级
    관형사 标签下混着活用形、不是独立词条             豆包     **99.1% 是独立词元**          ❌

这是**第四次「两家给出具体数字而数字都错」**（前三次：es `pronunciation_entry` 量级、
ja JLPT 授权、ko 26항 误伤）。⭐ **收敛不是证据，数才是。**

🔴🔴 最值钱的一条两家都没看见：v4pro 提的方向规则是
「若 `target==词条+后缀` 则正向，若 `词条==target+后缀` 则反向，**两者都不满足就降为 related**」。
实测「两者都不满足」占 **41.8%（2,840 个目标）**，而拆开看：

    81.0%  目标以词条开头     동 → 동동（叠词）、해 → 해치다      ← **正向派生**
    15.5%  无字面包含关系但目标是独立词元  가르치다 → 가르침、걷다 → 걸음  ← **正向派生**（不规则名词化）
     2.7%  目标不在 dict      따듯이、선히、상스레               ← 真词，是我们收词的缺口
     0.5%  词条以目标开头     꾀부리다 → 꾀                     ← 反向

⇒ 照 v4pro 那条规则做会**把 2,739 条真派生边降级成 related：修好 0、弄坏 2,739**。
真正的规则是量出来的：**默认正向，只有「词条 ＝ 目标 ＋ 后缀」时才反向**（133 条，2.0%）。

═══ 采纳的与否掉的 ═══
✅ 采纳：方向要判（但按实测的形状，不按它们给的阈值）／`sound_variant` 新建／
   북한·남한 **不进 `dialectal`**（是标准变体不是地域方言，两家都指出，语言学上也对）／
   `준말`·`본말` 用**一个** kind＋统一方向（豆包的理由更硬：两个 kind 会让人录反）
❌ 否掉：「中日文词性标签不收」（实测目标全是韩语词）／「两者都不满足降 related」（见上）／
   「관형사 整组剔除」（实测 99.1% 是独立词元）

跑（在仓库根）：
    python3 -u ko/pipeline/harvest_relations_from_examples.py
    python3 -u ko/pipeline/harvest_relations_from_examples.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import json
import re
import sqlite3

import dbtool
import paths

f = lambda n: format(n, ",")
BATCH = 20000
HANGUL = re.compile(r"[가-힣]")
CJK = re.compile(r"[一-鿿㐀-䶿]")

# ── 标签 → (kind, tag)。**方向统一是「基式 → 衍生式」**，见文件头。──
M = {}
def _m(kind, tag, *labels):
    for l in labels:
        M[l] = (kind, tag)

_m("derived", None, "동사", "부사", "형용사", "명사", "관형사", "명사형", "동사형",
   "动词", "動詞", "名词", "名詞", "形容词", "形容詞", "副词", "副詞",
   "派生词", "派生詞", "派生", "派生語",
   # 副词的细分标签，与 `부사` 同类（dry 跑报出来的残差，逐个看过样本）
   "접속부사", "양태부사", "부정부사", "성상부사", "지시부사")
_m("derived", "compound", "합성어")
_m("derived", "passive", "피동사", "被动形")
_m("derived", "causative", "사동사", "使役形")
_m("derived", "active", "능동사")
_m("synonym", None, "유의어", "유의어s", "비슷한말", "동의어", "동의어s", "유사어",
   "유의가", "同義語", "近义词", "近義詞", "近义詞", "近义", "相近词汇", "类似词汇",
   "類似詞彙")
_m("synonym", "hanja-native", "汉字词", "고유어", "固有词")
_m("antonym", None, "반의어", "반의어s", "상대어", "反义词", "反義詞", "反义詞", "对比")
_m("hypernym", None, "상위어")
_m("related", None, "참조", "참고", "관련어", "関連語", "参照", "相关词汇", "相關詞彙",
   "相关", "相關", "相关动词", "同源詞")
_m("related", "root", "어근")
_m("abbreviation", None, "준말", "略词", "略詞", "약칭")
_m("abbreviation", "reverse", "본말")          # 🔴 词条是缩略形 ⇒ **反向存**
_m("sound_variant", "weak", "여린말")
_m("sound_variant", "strong", "센말")
_m("sound_variant", "aspirated", "거센말")
_m("sound_variant", "big", "큰말")
_m("sound_variant", "small", "작은말")
_m("dialectal", None, "사투리", "방언", "지역어(방언)", "方言")
# 🔴 북한/남한 **不是方言**，是同一语言的两套标准（문화어 / 표준어）。
#    两家外审都指出了这一条，语言学上也对 ⇒ `alternative` ＋ variety tag。
_m("alternative", "variety-kp", "北韩", "北韓", "北韓語", "朝鲜文化语")
_m("alternative", "variety-kr", "南韩", "南韓")
_m("alternative", "honorific", "높임말", "敬語", "敬称")
_m("alternative", "slang", "속어", "俗语", "俗語", "俗稱", "隱語")
_m("alt_of", "archaic", "옛말")
_m("alternative", "allomorph", "이형태")      # 形态变体（이형태＝allomorph）
_m("hanja_spelling", None, "한자")            # 谚文词 → 它的汉字表记，与昨天那 5.1 万条同一层
_m("alt_hanja", None, "약자", "정자", "간체", "이체자")
_m("alt_hanja", "variant-form", "異表記・別形")   # 谚文的那几条会在下面改判成 alternative

DROP = {"학명", "화학식", "위키데이터", "위키백과", "부록", "(부록", "제목", "본명",
        "구성", "고빈도어", "원문", "갑", "일본어", "현대일본어", "현대한국어",
        "러시아어(ru)", "번역", "かく", "请参考", "西式香肠", "季节",
        "常见搭配", "常見搭配", "其他词形", "误词", "誤詞", "对音词", "近音詞",
        "外来语", "限定词", "叠词", "异序词", "类似后缀", "相近后缀", "相關後綴",
        "相近词尾", "相近助词", "大词", "小词", "复수표준어", "복수표준어",
        "使役形s", "固有語", "動詞化", "音訓混ざる式", "対義語", "synonym"}

# 🔴 后缀表用于**方向判断**，不是用于判断"是不是派生"。
#    实测：默认正向对 98.0% 成立，只有「词条 ＝ 目标 ＋ 后缀」这 2.0% 要反向。
SUF = ("하다", "되다", "시키다", "스럽다", "롭다", "답다", "거리다", "대다",
       "이다", "히다", "기", "음", "히", "이")
SPLIT = re.compile(r"[，,、；;/]|\s-\s|｜")


def clean(t):
    """→ 干净的目标词，或 None。

    ⚠️ `어두움 > 어둠` 这种源头自带的「旧形 > 新形」记法要取**后者**（现行形）。
    """
    t = re.sub(r"[（(\[【].*?[)\]）】]", "", t)
    if ">" in t:
        t = t.split(">")[-1]
    t = t.split("(")[0].strip().strip("。.?？!！·…，,、 ")
    t = re.sub(r"\s*<[^>]*>\s*", "", t).strip()
    return t or None


def load_rows():
    p = paths.WORK / "example_labeled_rows.tsv"
    if not p.exists():
        raise SystemExit("🔴 %s 不在 —— 先跑 harvest_examples.py" % p)
    out = []
    for line in open(p, encoding="utf-8"):
        if line.startswith("#"):
            continue
        c = line.rstrip("\n").split("\t")
        if len(c) >= 4:
            out.append(c)
    return out


def build(con):
    indict = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    have = {(w, k, t) for w, k, t in con.execute(
        "SELECT word_id, kind, target FROM sense_relation")}
    edges, stat, unknown = [], collections.Counter(), collections.Counter()
    seen = set()
    for src, word, lab, payload in load_rows():
        if lab in DROP:
            stat["丢弃·不是词间关系·" + lab if stat["丢弃·不是词间关系"] < 0 else "丢弃·不是词间关系"] += 1
            continue
        if lab not in M:
            unknown[lab] += 1
            continue
        kind, tag = M[lab]
        wid = indict.get(word)
        if wid is None:
            stat["跳过·词条不在 dict"] += 1
            continue
        for raw in SPLIT.split(payload):
            t = clean(raw)
            if not t or not (HANGUL.search(t) or CJK.search(t)):
                continue
            if t == word:
                stat["跳过·目标就是词条自己"] += 1
                continue
            a, b, k, g = word, t, kind, tag
            # ── 方向 ──
            if kind == "derived" and any(word == t + s for s in SUF):
                a, b = t, word            # 词条是派生形 ⇒ 反向：目标才是基式
                stat["⇄ 方向反转·derived"] += 1
            if kind == "abbreviation" and tag == "reverse":
                a, b, g = t, word, None   # 본말：目标是全称 ⇒ 全称 → 缩略（词条）
                stat["⇄ 方向反转·본말"] += 1
            # ── 语体标签（敬语/俗语）不是"同一个词的异形"，抽样当场逮到两条 ──
            #   `귀 → 귀때기`（俗语派生，目标是词条加后缀）⇒ `derived`
            #   `있다 → 계시다`（补充法敬语，是**另一个词位**）⇒ `synonym`
            # 豆包提的这一条，抽样验证成立；判据用**字面包含**（可证伪），不靠语感。
            if k == "alternative" and g in ("honorific", "slang"):
                k = "derived" if b.startswith(a) else "synonym"
                stat["细分·语体 → " + k] += 1
            # ── 异体：谚文的那几条不是汉字异体 ──
            if k == "alt_hanja" and (HANGUL.search(a) or HANGUL.search(b)):
                k, g = "alternative", "spelling"
                stat["改判·谚文异写不算汉字异体"] += 1
            aid = indict.get(a)
            if aid is None:
                stat["跳过·边的起点不在 dict"] += 1
                continue
            key = (aid, k, b)
            if key in seen:
                stat["跳过·本批内重复"] += 1
                continue
            seen.add(key)
            if key in have:
                stat["跳过·库里已有这条边"] += 1
                continue
            edges.append((aid, None, k, b,
                          json.dumps([g], ensure_ascii=False) if g else None,
                          src, "%s:%s:rel:%s:%s" % (src, a, k, b)))
            stat["✅ 新边·" + k] += 1
    return edges, stat, unknown


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    edges, stat, unknown = build(con)
    print("■ 从带标签的行拆出的关系边")
    for k, v in sorted(stat.items()):
        print("   %-34s %8s" % (k, f(v)))
    print("   %-34s %8s" % ("── 要写的新边合计", f(len(edges))))
    if unknown:
        print("\n⚠️ 既不在映射表也不在丢弃表的标签（**报出来，不静默**）：%d 种"
              % len(unknown))
        print("   " + "  ".join("%s=%d" % kv for kv in unknown.most_common(18)))
    before = con.execute("SELECT COUNT(*) FROM sense_relation").fetchone()[0]
    con.close()
    if not a.apply:
        print("\n（这是 dry 跑。加 --apply 才写库）")
        return
    kinds = collections.Counter(e[2] for e in edges)
    with dbtool.session(
            "ko-relations-from-examples",
            expect={"#sense_relation": len(edges),
                    "sense_relation.target": len(edges)},
            invalidates=[
                "关系层新增三个 kind：`abbreviation` / `sound_variant`，"
                "以及 `alt_hanja` 首次有行 ⇒ **展示层要给它们中文标签**，"
                "否则会像 it 那轮一样直接把英文 kind 名印在页面上",
                "🔴 `sound_variant` 的 tag（强/弱/送气/大/小）是它存在的全部理由 —— "
                "展示层只印「异形」就等于没建这个 kind",
            ]) as s:
        for i in range(0, len(edges), BATCH):
            s.executemany(
                "INSERT OR IGNORE INTO sense_relation "
                "(word_id, sense_id, kind, target, tags, src, src_ref)"
                " VALUES (?,?,?,?,?,?,?)", edges[i:i + BATCH])
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda sql: con.execute(sql).fetchone()[0]
    print("\n■ 写后回核（从库里重算）")
    red = 0
    for name, got, want in [
            ("sense_relation 行数", q("SELECT COUNT(*) FROM sense_relation"),
             before + len(edges)),
            ("abbreviation 边", q("SELECT COUNT(*) FROM sense_relation "
                                 "WHERE kind='abbreviation'"), kinds["abbreviation"]),
            ("sound_variant 边", q("SELECT COUNT(*) FROM sense_relation "
                                  "WHERE kind='sound_variant'"), kinds["sound_variant"]),
            ("alt_hanja 边", q("SELECT COUNT(*) FROM sense_relation "
                              "WHERE kind='alt_hanja'"), kinds["alt_hanja"]),
            ("🔴 目标是空串的边", q("SELECT COUNT(*) FROM sense_relation "
                              "WHERE target=''"), 0),
            ("🔴 起点不在 dict 的边",
             q("SELECT COUNT(*) FROM sense_relation r WHERE NOT EXISTS"
               "(SELECT 1 FROM dict d WHERE d.id=r.word_id)"), 0)]:
        mark = "✅" if got == want else "🔴"
        red += got != want
        print("   %s %-30s %9s  期望 %9s" % (mark, name, f(got), f(want)))
    con.close()
    if red:
        raise SystemExit("🔴 回核 %d 条红" % red)


if __name__ == "__main__":
    main()
