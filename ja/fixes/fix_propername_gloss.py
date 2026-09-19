#!/usr/bin/env python3
"""修：专名义项的中文**丢掉了分类**（女性名／姓氏／地名分不出来）。2026-09-18。

═══ 怎么发现的 ═══
用户看 `桜` 的页面：rank 9/10/11 三条英文分别是 `a female given name`／`a placename`／
`a surname`，**中文全印「樱」** —— 三件不同的事在页面上长得一模一样。

═══ 🔴 这是「缺」不是「错」，但库里本来就有正确写法 ═══
同一族义项里 **1,246 条格式是对的**（`数（姓氏）`／`月（女性名）`／`女性名`），
说明格式不是没定过，是这批翻译没跟上。⇒ 按已有格式统一，不是发明新写法。

═══ 🔴 判据用正则不用枚举 —— 枚举漏了 1,293 条 ═══
第一版拿 8 个字符串精确匹配，覆盖 11,262 条；而同族的变体有一大把：

    A place name.                 ← 大写 + 句号
    歩子: a female given name      ← 带词形前缀
    an unknown-gender given name
    surname, family name

⇒ 换成正则后覆盖 **12,555 条（89.9%）**（`[[criteria-narrower-than-you-think]]`）。

⚠️ **带修饰的 1,408 条有意不碰**：`a surname from Okinawan`／
   `a male given name of historical usage`／`a transliteration of the English male
   given name James`。套模板会把「冲绳」「历史用法」「英语转写」这些**丢掉** ——
   那是拿一个缺换另一个缺。**推翻它需要**：给出能把修饰也译进去的规则。

═══ 中文侧分三档，只动第二档 ═══
    ① 已带分类（`数（姓氏）`）        → 不动
    ② 只有译名（`樱`）              → 改成 `樱（女性名）`
    ③ 中文说的是别的事              → **逐条列出来给人读**，不套模板
       （`泉水 | a surname → 庭院中的水池` 是词的字面义；
         `剣 | a female given name → 麻也香` 是模型**编了个不相干的名字**）

跑（在仓库根）：
    python3 -u ja/fixes/fix_propername_gloss.py
    python3 -u ja/fixes/fix_propername_gloss.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import re
import sqlite3

import dbtool
import paths

f = lambda n: format(n, ",")

# 🔴 只收「**整条就是纯分类**」的。带 `from X`/`of historical usage`/`character for …`
#    的一律落在外面 —— 见文件头那条「有意不碰」。
PURE = re.compile(r"""^(?:\S{1,12}:\s*)?              # 可选的「歩子: 」前缀
    (?:an?\s+)?(?:common\s+)?
    (?:(female|male|unisex|unknown[\s-]gender|male\s+or\s+female)[\s-]+)?
    (given\s+name|surname|family\s+name|place\s*name)\s*\.?$""", re.I | re.X)

CAT = {
    ("female", "given name"): "女性名",
    ("male", "given name"): "男性名",
    ("unisex", "given name"): "男女通用名",
    ("male or female", "given name"): "男女通用名",
    ("unknown gender", "given name"): "名（性别不详）",
    ("", "given name"): "名",
    ("", "surname"): "姓氏",
    ("", "family name"): "姓氏",
    ("", "place name"): "地名",
    ("", "placename"): "地名",
}
# 🔴 中文已经带了分类的判据：含分类字**且够短**。只查「含」会把
#    `庭院中的水池`（含"水"不含这三个字，但同族里有别的长句会撞上）误判成已带分类。
HAS_CAT = re.compile(r"[名姓地]")
PUNCT = re.compile(r"[。，、；：（）〈〉「」…]")

# 🔴 第三档那 10 条**逐条读过**，人工定，一条都不套模板。
#    键用 `(词形, 英文)` 不用 `sense_id` —— 主键在重建库时会变，而这两样不会。
#    值为 `None` ＝ **有意不改**。
MANUAL = {
    # 模型**编了个不相干的名字**（`剣`＝けん、`清`＝きよ，都不是「麻也香」「沙也加」）
    ("剣", "a female given name"): "剑（女性名）",
    ("清", "a female given name"): "清（女性名）",
    # 译成了这个词的**字面义**，而源头说的是"它是个姓氏/名字"
    ("泉水", "a surname"): "泉水（姓氏）",
    ("哲夫", "a male given name"): "哲夫（男性名）",
    ("良知", "a male given name"): "良知（男性名）",
    ("木本", "a surname"): "木本（姓氏）",
    ("里子", "a female given name"): "里子（女性名）",
    ("百代", "a female given name"): "百代（女性名）",
    # 中文本来就对（`そうめい` 的汉字表记是 `聰明`），只是多了个句号
    ("そうめい", "聰明: a male given name"): "聪明（男性名）",
    # 🔴 **这条有意不改**：`下の名前` 这个词的**词义本身**就是「名（相对于姓）」——
    #    英文里的 `given name` 在这里是**释义**不是分类标记。套模板会写成
    #    「名（人名中去掉姓氏的部分）（名）」，把一条正确的释义改成病句。
    #    ⚠️ 它落进第三档只是因为中文长度 13 > 12，**判据没错，是它本来就该人来看**。
    ("下の名前", "given name"): None,
}


def classify(en):
    m = PURE.match(en.strip())
    if not m:
        return None
    g1 = (m.group(1) or "").lower().replace("-", " ")
    g2 = m.group(2).lower()
    g2 = "place name" if g2.replace(" ", "") == "placename" else g2
    return CAT.get((g1, g2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute("""
        SELECT s.id, d.word, ge.text, gz.text
        FROM sense s
        JOIN dict d ON d.id = s.word_id
        JOIN sense_gloss ge ON ge.sense_id = s.id AND ge.lang='en' AND ge.kind<>'umbrella'
        JOIN sense_gloss gz ON gz.sense_id = s.id AND gz.lang='zh' AND gz.kind<>'umbrella'
        WHERE ge.text LIKE '%name%'
    """).fetchall()
    con.close()

    fix, keep, odd = [], 0, []
    manual_fix, manual_keep = [], []
    cats = collections.Counter()
    for sid, w, en, zh in rows:
        cat = classify(en)
        if cat is None:
            continue
        z = zh.strip()
        if HAS_CAT.search(z) and len(z) <= 12:
            keep += 1
            continue
        if len(z) <= len(w) + 1 and not PUNCT.search(z):
            fix.append((f"{z}（{cat}）", sid))
            cats[cat] += 1
        elif (w, en.strip()) in MANUAL:
            want = MANUAL[(w, en.strip())]
            if want is None:
                manual_keep.append((w, en, z))
            else:
                fix.append((want, sid))
                cats[cat] += 1
                manual_fix.append((w, z, want))
        else:
            odd.append((w, en, z, cat, sid))

    print("■ 英文是**纯分类**的义项：%s 条" % f(keep + len(fix) + len(odd)))
    print("   %-30s %8s" % ("① 已带分类，不动", f(keep)))
    print("   %-30s %8s" % ("② 只有译名 ⇒ 补分类", f(len(fix))))
    print("   %-30s %8s" % ("③ 中文说的是别的事 ⇒ 人工定", f(len(manual_fix)+len(manual_keep)+len(odd))))
    print("\n■ 补的分类分布")
    for k, v in cats.most_common():
        print("   %-14s %8s" % (k, f(v)))
    print("\n■ ② 样本")
    for t, sid in fix[:8]:
        print("   sense %-7d → %s" % (sid, t))
    print("\n■ 第三档：逐条人工定（%s 条改 ／ %s 条有意不改）"
          % (f(len(manual_fix)), f(len(manual_keep))))
    for w, z, want in manual_fix:
        print("   %-8s %-22s → %s" % (w, z[:22], want))
    for w, en, z in manual_keep:
        print("   %-8s %-22s → **不改**（词义本身就是它，不是分类标记）" % (w, z[:22]))
    if odd:
        print("\n■ 🔴 第三档里**人工表没覆盖**的（必须是空的，否则是新冒出来的）")
        for w, en, z, cat, sid in odd:
            print("   %-8s %-26s → %-22s  （该说的是「%s」）" % (w, en[:26], z[:22], cat))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    with dbtool.session("ja-fix-propername-gloss",
                        expect={"sense_gloss.text": 0}, invalidates=[]) as s:
        s.executemany(
            "UPDATE sense_gloss SET text=? WHERE sense_id=? AND lang='zh'"
            " AND kind<>'umbrella'", fix)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    print("\n■ 写后回核（全量，非抽样）")
    left = 0
    for sid, w, en, zh in con.execute("""
        SELECT s.id, d.word, ge.text, gz.text FROM sense s
        JOIN dict d ON d.id=s.word_id
        JOIN sense_gloss ge ON ge.sense_id=s.id AND ge.lang='en' AND ge.kind<>'umbrella'
        JOIN sense_gloss gz ON gz.sense_id=s.id AND gz.lang='zh' AND gz.kind<>'umbrella'
        WHERE ge.text LIKE '%name%'"""):
        if classify(en) and not HAS_CAT.search(zh):
            left += 1
    # 🔴 **回核只许查「我改的那批」，不许查全库。** 第一版三条全红，
    #    而**三条都是判据写宽了、数据是对的**（`[[criteria-narrower-than-you-think]]`）：
    #      ①「仍无分类的」期望值算成 1 —— `下の名前` 的中文含「名」本来就不计入 ⇒ 0
    #      ②「括号没配对」查全库 ⇒ 逮到 `…如左括号「（」或左引号…`，
    #         那是一条**正在讲「左括号」这个符号**的正常释义
    #      ③「只剩括号」查全库以「（」开头的 ⇒ 逮到 709 条 `（非正式）我爱你`
    #         这类既有格式，而我改的那批**一条都不在里面**（精确查返回 0）
    #    ⇒ 判据一律收窄成「形如 `X（分类）`」。
    CATS = "','".join(sorted(set(CAT.values())))
    suffix = " OR ".join("text LIKE '%%（%s）'" % c for c in sorted(set(CAT.values())))
    for name, got, want in [
        ("纯分类义项里中文仍无分类的", left, len(odd)),
        ("补出来的括号没配对",
         q("SELECT COUNT(*) FROM sense_gloss WHERE lang='zh' AND (%s)"
           " AND length(text)-length(replace(text,'（',''))"
           "  <> length(text)-length(replace(text,'）',''))" % suffix), 0),
        ("补出来的中文成了空壳（译名那半是空的）",
         q("SELECT COUNT(*) FROM sense_gloss WHERE lang='zh' AND (%s)"
           " AND text LIKE '（%%'" % suffix), 0),
        ("补出来的分类后缀总数",
         q("SELECT COUNT(*) FROM sense_gloss WHERE lang='zh' AND (%s)" % suffix), None),
    ]:
        if want is None:
            print("   ⭐ %-32s %8s" % (name, f(got)))
            continue
        print("   %s %-32s %8s（期望 %s）" % ("✅" if got == want else "🔴", name,
                                            f(got), f(want)))
    con.close()


if __name__ == "__main__":
    main()
