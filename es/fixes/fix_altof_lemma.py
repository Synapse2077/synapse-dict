#!/usr/bin/env python3
"""异体拼写被误判成变形层 —— 3,890 个词。2026-08-06。

═══ 缺陷 ═══
`build.py:147` 的 `is_infl_sense()` 把 `alt_of` 和 `form_of` 当成同一回事：

    def is_infl_sense(s) -> bool:
        if s.get("form_of") or s.get("alt_of"):   # 🔴 alt_of 不是变形
            return True

`form_of` 是**变形**（hablas 是 hablar 的一个形态），`alt_of` 是**异体拼写**
（Méjico 和 México 是同一个词的两种写法）。异体拼写是独立词条，不是谁的形态。

判成变形之后走 `compose(tags)` 造标签，而 alt_of 条目身上带的是性别标签，
于是造出了**事实错误**的指针：

    词          源头 gloss                              我们造的
    Méjico      alternative spelling of México          México 的 阳性
    Iraq        superseded spelling of Irak, …          Irak 的 阳性
    zebra       obsolete spelling of cebra              cebra 的 阴性
    checar      alternative form of chequear            chequear 的 变位形式
    acceptable  archaic form of aceptable               aceptable 的 阴/阳性

「México 的阳性」这句话没有意义 —— México 本来就是阳性，它没有阴阳两个形态。
🔴 这是框架第一条判据「错比缺更伤权威」的实例：源头把话说得清清楚楚
   （alternative / obsolete / superseded / misspelling），我们把它丢掉，
   换上一个自己编的、说错了的语法标签。而且因为 `is_lemma=0`，
   这些词在界面上**一条释义都没有**。

═══ 范围（确定性，回源算出，不问模型）═══
判据：该词头在 kaikki 西语切片里的义项**全部**是 `alt_of`
      —— 没有 form_of、没有 prose 变形、没有真义。

    纯 alt_of 词头                4,940
      已是 lemma（abbr 闸门救下）      899   ← SHCP/TLCAN 这类，tags 带 abbreviation
      库里没这个词                   151
      **误判成变形层**             3,890   ← 本脚本修的就是这批，共 4,148 条义项

⭐ 那 899 个是**现成的正确终态样板**：`build.py:248` 的 `is_abbr` 闸门恰好把
   带 abbreviation/initialism 标签的 alt_of 放行了，于是 SHCP 长成了
   `is_lemma=1` + `definition`=源头 gloss + 中文 + meta。本脚本就是把
   剩下 3,890 个补成同样的形状 —— 不是发明新规则，是补一个漏掉的分支。

═══ 中文为什么用模板生成，不送模型 ═══
铁律「能确定性回源比对的根本别问模型」的正面用例：这批 gloss 高度模板化，
99.9% 命中 `<修饰语> form/spelling of <base>` 这一个句式。模板输出
`México 的异体拼写`，比模型翻译更稳、可复算、零成本。

⚠️ 模板会丢掉 base 之后的补充说明（`Iraq` 那条的「2010 年被西班牙皇家语言学院
   废止」）。英文原文完整保留在 `definition` 列里，没有丢数据；要不要把这部分
   也翻成中文是**另一个决定**，本脚本不做。

═══ 🔴 展示层的隐式契约：中文里不能出现半角空格包着的「的」═══
`App.tsx:529` 用 `/^.+ 的 \\S+$/` 判断「这条是变形指针不是释义」，
匹配上就**不显示**。我们生成的 `México 的异体拼写`「的」后面没有空格，
所以不会被吃掉 —— 但这是个巧合级别的契约，靠读代码发现不了。
⇒ 本脚本把它变成**断言**：任何一条生成的中文命中该正则就中止，不写库。

═══ 闸门 ═══
`is_lemma` 与 `translation_src` 都不在 `dbtool.TRACK` 里（前者 NOT NULL，
非空计数恒定，闸门天生看不见），所以本脚本自己做写后核对。

用法（在仓库根）：
    python3 -m es.fixes.fix_altof_lemma            # 只分析 + 抽样，不写库
    python3 -m es.fixes.fix_altof_lemma --apply
"""
import argparse
import collections
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
# 判据与 meta 构造直接复用建库脚本，不重写一遍 —— 重写就会漂移
from pipeline.build import PROSE_INFL, STRIP_COMBINED, meta_of  # noqa: E402

# App.tsx:529 —— 命中它的中文会被当成变形指针，在界面上隐藏
ES_INFL_LABEL = re.compile(r"^.+ 的 \S+$")

# gloss 前缀 → 中文修饰语。键按长度降序匹配，避免 "form of" 抢在 "alternative form of" 前面。
PREFIX_ZH = {
    "alternative letter-case form of": "大小写变体",
    "pronunciation spelling of": "读音拼写",
    "eye dialect spelling of": "方音拼写",
    "superseded spelling of": "旧拼写（已废止）",
    "nonstandard spelling of": "非标准拼写",
    "alternative spelling of": "异体拼写",
    "alternative form of": "异体拼写",
    "nonstandard form of": "非标准拼写",
    "obsolete spelling of": "已废拼写",
    "archaic spelling of": "古拼写",
    "informal spelling of": "非正式拼写",
    "obsolete form of": "已废拼写",
    "archaic form of": "古拼写",
    "rare spelling of": "罕见拼写",
    "standard form of": "标准拼写",
    "dated form of": "过时拼写",
    "misspelling of": "常见误拼",
    "initialism of": "首字母缩写",
    "abbreviation of": "缩写",
    "acronym of": "首字母缩略词",
    "clipping of": "截短形式",
    "contraction of": "缩合形式",
    # 地区限定式（`Rioplatense form of`）用兜底分支处理，见 zh_of()
}
_KEYS = sorted(PREFIX_ZH, key=len, reverse=True)
# 兜底：`<地区/时代> form|spelling of <base>` —— 前面那截原样保留在英文里，中文只说「变体拼写」
FALLBACK = re.compile(r"^(.+?)\s+(?:form|spelling)\s+of\b", re.I)

# ═══ 逐条裁决的 6 个例外（模板一个都套不上，逐条看过原文）═══
# 🔴 看这一栏的理由：项目头号教训是「统计里『跳过』那栏必须逐条看」。看下来发现的
#    不是零头，而是**另一类缺陷** —— wiktextract 自己把 alt_of 用错了：
#
#    · cu / ka / i griega：gloss 是真定义（「字母 q 的名称」），alt_of 是 wiktextract
#      硬塞的。我们照单全收，造出「q 的 阴性」—— cu 是字母 q 的**名称**，不是 q 的阴性。
#    · nivel de vida：alt_of 指向 **英文词 `living`**。源头那条 gloss「standard of living」
#      是英文译文，被解析成 standard(tag) + of living(alt_of)。
#      `nivel de vida`（生活水平）是个再正常不过的西语名词短语，却被当成了 living 的变形。
#      ⇒ 它的 `exchange='0:living'` 也必须清掉，见下面 CLEAR_EXCHANGE。
#    · malir sal：salir mal 的音节互换戏谑写法。
#    · ésto 的第二条（misconstruction of éste）：另一条已由模板命中，只补这条。
MANUAL = {
    ("cu", "Name of the letter q"): "字母 q 的名称",
    ("ka", "Name of the letter k"): "字母 k 的名称",
    ("i griega", "Name of the letter y"): "字母 y 的名称",
    ("nivel de vida", "standard of living"): "生活水平",
    ("malir sal", "deliberate misspelling of salir mal (go wrong)"): "salir mal 的戏谑误拼",
    ("ésto", "misconstruction of éste"): "éste 的误用",
}
# alt_of 指向的根本不是西语原形 ⇒ 连 exchange 里的指针一起清掉
CLEAR_EXCHANGE = {"nivel de vida"}


def zh_of(word: str, gloss: str, base: str) -> tuple[str, str]:
    """→ (中文, 命中的模板名)。模板名用于统计，未命中返回 ('', '')。"""
    g = gloss.strip()
    if (word, g) in MANUAL:
        return MANUAL[(word, g)], "<逐条裁决>"
    low = g.lower()
    for k in _KEYS:
        if low.startswith(k):
            return f"{base} 的{PREFIX_ZH[k]}", k
    m = FALLBACK.match(g)
    if m:
        return f"{base} 的变体拼写", f"<兜底> {m.group(1).lower()}"
    return "", ""


def collect() -> dict:
    """扫 kaikki 西语切片 → {word: {alt/form/prose/real 计数, senses}}。"""
    info = collections.defaultdict(
        lambda: {"alt": 0, "form": 0, "prose": 0, "real": 0, "senses": []})
    for line in open(paths.KK, encoding="utf-8"):
        e = json.loads(line)
        if e.get("lang_code") != "es":
            continue
        w = (e.get("word") or "").strip()
        if not w:
            continue
        r = info[w]
        pos = e.get("pos", "")
        for s in e.get("senses", []):
            g = re.sub(r"\s+", " ", (s.get("glosses") or [""])[0]).strip()
            if s.get("form_of"):
                r["form"] += 1
            elif s.get("alt_of"):
                r["alt"] += 1
                fo = s["alt_of"][0].get("word") or ""
                r["senses"].append((g, STRIP_COMBINED.sub("", fo).strip(), s, pos))
            elif PROSE_INFL.search(g):
                r["prose"] += 1
            else:
                r["real"] += 1
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    print(f"扫 dump：{paths.KK.name}")
    info = collect()
    pure = {w: r for w, r in info.items()
            if r["alt"] and not r["form"] and not r["prose"] and not r["real"]}
    print(f"纯 alt_of 词头：{len(pure):,}")

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    db = {w: (i, lem) for w, i, lem in
          con.execute("SELECT word, id, is_lemma FROM dict")}
    con.close()

    st = collections.Counter()
    plan, tmpl, skipped = [], collections.Counter(), []
    for w, r in sorted(pure.items()):
        d = db.get(w)
        if d is None:
            st["库里没这个词（不处理）"] += 1
            continue
        if d[1] == 1:
            st["已是 lemma（abbr 闸门救下）"] += 1
            continue
        st["误判成变形层 → 本次修复"] += 1

        defs, zhs, metas, seen = [], [], [], set()
        for g, base, s, pos in r["senses"]:
            if not g or g in seen:
                continue
            seen.add(g)
            zh, key = zh_of(w, g, base) if base else ("", "")
            if not zh:
                skipped.append((w, g))       # 🔴 "跳过"那栏必须逐条看得见
                continue
            tmpl[key] += 1
            defs.append(g)
            zhs.append(zh)
            metas.append(meta_of(s, pos))
        if not defs:
            st["  其中一条都没生成出来（不写）"] += 1
            continue
        plan.append((d[0], w, "\n".join(defs), "\n".join(zhs),
                     json.dumps(metas, ensure_ascii=False)))

    for k, v in st.most_common():
        print(f"  {k:<28}{v:>7,}")
    print(f"\n待写 {len(plan):,} 个词，{sum(len(p[2].split(chr(10))) for p in plan):,} 条义项")

    print("\n模板命中分布：")
    tot = sum(tmpl.values())
    for k, v in tmpl.most_common():
        print(f"  {v:>6,} {v/tot*100:5.1f}%  {k}")

    print(f"\n🔴 未命中任何模板、被跳过的义项：{len(skipped)}")
    for w, g in skipped[:20]:
        print(f"    {w:<20} {g[:70]}")

    # ═══ 断言①：生成的中文不能被展示层当成变形指针吃掉 ═══
    hidden = [(p[1], z) for p in plan for z in p[3].split("\n")
              if ES_INFL_LABEL.match(z)]
    print(f"\n断言① 会被 App.tsx:529 隐藏的中文：{len(hidden)}")
    for w, z in hidden[:5]:
        print(f"    🔴 {w}  {z!r}")
    assert not hidden, "生成的中文命中变形指针正则，写进去也看不见"

    # ═══ 断言②：definition / translation / meta 三列行数必须一一对应 ═══
    bad = [p[1] for p in plan
           if not (len(p[2].split("\n")) == len(p[3].split("\n")) == len(json.loads(p[4])))]
    print(f"断言② 三列行数不齐的词：{len(bad)}  {bad[:5]}")
    assert not bad, "definition/translation/meta 行号对不齐 —— novia 那个坑"

    dbtool.sample_check(
        [(p[1], p[2].split("\n")[0][:44], p[3].split("\n")[0][:26]) for p in plan[:12]],
        12, ("词", "源头 gloss", "生成的中文"))

    if not args.apply:
        print("\n未加 --apply，不写库。")
        return

    # 写前留底：这批行改动前长什么样，便于事后核对/回滚定位
    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    ids = [p[0] for p in plan]
    before = {r[0]: r for r in con.execute(
        "SELECT id, word, is_lemma, infl, exchange, translation FROM dict "
        f"WHERE id IN ({','.join('?' * len(ids))})", ids)}
    con.close()
    out = paths.WORK / "altof_lemma_before.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for r in before.values():
            f.write(json.dumps(dict(zip(
                ("id", "word", "is_lemma", "infl", "exchange", "translation"), r)),
                ensure_ascii=False) + "\n")
    print(f"\n改动前快照 → {out}")

    n_def = sum(1 for p in plan if p[2])          # definition 全部由 NULL 变非空
    n_infl = len(plan)                            # infl 全部由非空变 NULL
    n_exch = sum(1 for p in plan if p[1] in CLEAR_EXCHANGE)
    with dbtool.session("fix-altof-lemma", expect={
            "definition": +n_def,
            "meta": +len(plan),
            "infl": -n_infl,
            "exchange": -n_exch,                  # 只有 nivel de vida 那条指向英文词的
            "translation": 0,                     # 原本就非空（放的是错指针），只改内容
    }) as s:
        s.executemany(
            "UPDATE dict SET is_lemma=1, definition=?, translation=?, "
            "translation_src='template-altof', meta=?, infl=NULL WHERE id=?",
            [(p[2], p[3], p[4], p[0]) for p in plan])
        for p in plan:
            if p[1] in CLEAR_EXCHANGE:
                s.execute("UPDATE dict SET exchange=NULL WHERE id=?", (p[0],))

    # ═══ 写后核对：is_lemma / translation_src 不在 dbtool.TRACK 里，自己验 ═══
    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    q = lambda sql: con.execute(sql, ids).fetchone()[0]          # noqa: E731
    ph = ",".join("?" * len(ids))
    print("\n写后核对（本批 %d 行）：" % len(ids))
    print("  is_lemma=1        ", q(f"SELECT COUNT(*) FROM dict WHERE id IN ({ph}) AND is_lemma=1"))
    print("  definition 非空   ", q(f"SELECT COUNT(*) FROM dict WHERE id IN ({ph}) AND definition IS NOT NULL"))
    print("  infl 已清空       ", q(f"SELECT COUNT(*) FROM dict WHERE id IN ({ph}) AND infl IS NULL"))
    print("  exchange 保留     ", q(f"SELECT COUNT(*) FROM dict WHERE id IN ({ph}) AND exchange IS NOT NULL"))
    print("  translation_src   ", q(f"SELECT COUNT(*) FROM dict WHERE id IN ({ph}) AND translation_src='template-altof'"))
    lem = con.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1").fetchone()[0]
    con.close()
    print(f"  全库 lemma 数     {lem:,}  (应为 162,169 + {len(ids):,} = {162169 + len(ids):,})")
    assert q(f"SELECT COUNT(*) FROM dict WHERE id IN ({ph}) AND is_lemma=1") == len(ids)


if __name__ == "__main__":
    main()
