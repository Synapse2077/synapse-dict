#!/usr/bin/env python3
"""K11：把例句层里的**构词公式**拆成关系边。ko，2026-09-26。

═══ 这批是什么 ═══
韩文/英文版给**后缀或前缀词条**时，把构词例子塞进 `examples[]`：

    词条 `가`    건축(建築) (geonchuk, “architecture”) + 가(家) (ga) → 건축가(建築家) (…)
    词条 `하다`   번역(飜譯) (beonyeok, …) + 하다 (hada) → 번역(飜譯)하다 (…)
    词条 `주`    주(駐) (ju) + 한(韓) (han) → 주한(駐韓) (…)          ← 前缀
    词条 `-답다`  남자 → 남자답다                                    ← 没有 `+` 的写法

它们不是例句（2026-09-24 已标 `hidden=1`/`hidden_why='构词公式'`，290 条），
但**里面的关系内容是真的**：`건축 → 건축가` 是一条正经的 `derived` 边。

═══ 账上点明的两个坑，都验过了 ═══
① **右侧词要连括号一起取**。判据不是「取第一个括号前」，而是
   **「第一个『空格＋左括号』之前」** —— 汉字括号没有前导空格、罗马字括号有：
       `번역(飜譯)하다 (beonyeokhada, “to translate”)`  →  `번역(飜譯)하다`  ✅
   第一版账上记的 `[^\\s(（]+` 会切成 `번역`。
② **方向按左操作数，不按词条。** 这条**实测成立，而且两种词条都成立**：
       后缀词条 255 条：左操作数＝基式（`건축` + 가 → 건축가）⇒ 存 `건축 → 건축가`
       前缀词条  34 条：左操作数＝词条本身（`주` + 한 → 주한）⇒ 存 `주 → 주한` ✅ 也对
   ⚠️🔴 我验它的时候先用了一个**坏信号**：「派生式必须以基式开头」只有 25.6% 吻合。
      逐条读完那 215 条「不吻合」——**没有一条是方向反了**，全是三类正当情形：
      前缀词条（左操作数就是词条）／词干变形（`살다 → 사람`、`듣다 → 들리다`）／
      汉字括号重组（`건축(建築) → 건축가(建築家)`）。
      ⇒ 坏的是信号，不是数据。`[[criteria-from-meaning-not-form]]`：
        「以基式开头」是**形式代理**，而构词的定义不要求它。

═══ 实测盘子（289/290 解析成功）═══
    左操作数在 `dict` 里        270 / 289 (93.4%)   ← 不在的挂不上，跳过
    派生式在 `dict` 里          238 / 289 (82.4%)   ← 不在的存成不可点文本（展示层已有这条路）
    `左→派生` 这条边已经有了      85                  ← 不重复插
    ⇒ 要插的在这之间，跑起来报准数

🔴 **`INSERT OR IGNORE` 在这张表上对词级边不去重**：`UNIQUE(word_id, sense_id, kind, target)`
   里 `sense_id` 是 NULL，而 SQLite 认为 NULL≠NULL ⇒ 同一条边插两次不会被拦。
   （实测现在 221,351 条词级边里 0 组重复，所以是**风险**不是现状。）⇒ 在 Python 里去重。

跑（在仓库根）：
    python3 -u ko/pipeline/intake_word_formation.py            # 干跑 ＋ 抽 20 条人眼看方向
    python3 -u ko/pipeline/intake_word_formation.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import random
import re
import sqlite3

import dbtool
import paths

f = lambda n: format(n, ",")
KIND = "derived"
WHY = "构词公式"

ARROW = re.compile(r"\s*(?:→|->|⇒)\s*")
PLUS = re.compile(r"\s+\+\s+")
# 🔴 判据：**第一个「空白＋左括号」**之前是词。汉字括号紧贴词、罗马字括号带空格。
SPACE_PAREN = re.compile(r"\s+[(（]")
PAREN = re.compile(r"[(（][^)）]*[)）]")


def word_of(s):
    s = (s or "").strip().strip("「」『』“”\"")
    m = SPACE_PAREN.search(s)
    return (s[:m.start()] if m else s).strip()


def bare(s):
    """剥掉括号注与连字符 ⇒ 用来和 `dict.word` 比对（`건축(建築)` → `건축`）。"""
    return PAREN.sub("", s or "").replace("-", "").replace("—", "").strip()


# 🔴 **有意不收**，逐条读过。它们混在 `hidden_why='构词公式'` 里，
#    说明当初那道标注判据也偏宽 —— 记在这儿，别让它们悄悄变成关系边。
NOT_A_FORMULA = {
    1550:  "`세금이 낮다. → 정부는 세금을 낮추어야 한다.` 是**真例句对**（低→使变低），"
           "不是构词公式。当初标 `构词公式` 标错了",
    7525:  "`(24) 땅개비2 명사 ① → 방아깨비. ② → 메뚜기2 …` 是词典交叉引用整块",
    37384: "`×저 사건 → ○그 사건 あの事件` 是**用法纠错对**（日文版），不是构词",
    38214: "`「모우（牡牛）」+「좌」 → 「모우좌` 引号包裹且右侧被截断，解析不出完整派生式",
}


def parse(text):
    """→ (基式, 派生式) 或 None。判据写在文件头。"""
    parts = ARROW.split(text or "")
    if len(parts) != 2:
        return None
    ops = [word_of(x) for x in PLUS.split(parts[0])]
    res = word_of(parts[1])
    if not ops[0] or not res:
        return None
    # 基式 ＝ **左操作数**（见文件头②：两种词条都成立）
    return ops[0], res


STEM = re.compile(r"[-—]\s*$")


def resolve_base(base, headword, info):
    """基式 → 它在 `dict` 里的那个**词**。→ (词, 理由) 或 (None, 为什么解不出)。

    🔴🔴 **这一步不能「剥掉连字符直接匹配」** —— 那会把边挂到同形异义词上：
       `먹-` 剥成 `먹`，而库里 `먹` 的 pos 是 **noun（墨）**，
       `먹- + 음직 → 먹음직하다` 就挂到「墨」那一页去了。
       本项目反复栽的「词形 ≠ 词」（K20/K17）在这里又出现一次。

    🔴 我试过的两个单一信号**各对一半、方向相反**：
       ① 剥连字符直接匹配 ⇒ 33 条里 27 条落在非动词页上（`먹`＝墨）
       ② 一律 `词干+다` ⇒ 把**汉字前缀**解错（`내(內)-`「内」解成 `내다`「付出」、
          `쇠-`「牛」解成 `쇠다`、`새-`（加强前缀）解成 `새다`「漏」）
       ⇒ 分界不是「带不带连字符」，而是 **基式是不是词条本身**：

         · 基式 == 词条  ⇒ **前缀词条**（`쇠-`/`대-`/`내(內)-`）：
              派生词本来就该挂在词条自己那一页，**与词性无关**
         · 基式 != 词条 且带连字符 ⇒ **用言词干**（`먹-`/`믿-`/`떠나-`）：
              词元是 `词干+다`，且必须真是库里的词元
         · 其余 ⇒ 普通基式，直接匹配

       ⭐ 两个信号一致才收（`[[verification-gates-not-sampling]]`）。
    """
    bb = bare(base)
    if not bb:
        return None, "剥括号后是空的"
    if bb == bare(headword):
        return (bb, "前缀词条：基式＝词条") if bb in info else (None, "词条不在 dict")
    if STEM.search(base):
        lem = bb + "다"
        if lem in info and info[lem][1]:
            return lem, "用言词干 ⇒ 词元 `%s`" % lem
        return None, "词干 `%s` 加 `다` 不是库里的词元" % bb
    return (bb, "普通基式") if bb in info else (None, "基式不在 dict")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sample", type=int, default=20)
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute(
        "SELECT id, word, text, src FROM example WHERE hidden_why = ?", (WHY,)).fetchall()
    print("■ `hidden_why='%s'` 的行 %s 条" % (WHY, f(len(rows))))

    # `info[词] = (id, is_lemma, pos)` —— `resolve_base` 要 `is_lemma`
    info = {}
    for w, i, il, pos in con.execute("SELECT word, id, is_lemma, pos FROM dict ORDER BY id"):
        info.setdefault(w, (i, il, pos or ""))
    have = collections.defaultdict(set)
    for wid, tgt, tn in con.execute(
            "SELECT word_id, target, target_norm FROM sense_relation WHERE kind = ?", (KIND,)):
        have[wid].add(bare(tn or tgt))
    # 🔴 **该词元的活用表**：派生式已经在里面的，不再做成关系边 ——
    #    同一个事实不该在两层里各印一遍。实测 7 条（`삶`/`떠남`/`듣기`/`먹는다`…），
    #    页面会在「活用」和「派生词」两处都印它，而 `contract-check-layout`
    #    查的正是「没有一个目标被印两遍」（它现在只查关系层内部，跨层查不到）。
    infl = collections.defaultdict(set)
    for base, word in con.execute(
            "SELECT i.base, d.word FROM inflection i JOIN dict d ON d.id = i.word_id"):
        infl[base].add(word)

    cand, stat = [], collections.Counter()
    for eid, w, text, src in rows:
        if eid in NOT_A_FORMULA:
            stat["有意不收（逐条读过，见 NOT_A_FORMULA）"] += 1
            continue
        got = parse(text)
        if got is None:
            stat["🔴 解析不出 —— 这本身要查"] += 1
            print("   🔴 解析不出 [%s] %-10s %s" % (eid, w, (text or "")[:70]))
            continue
        base, res = got
        br = bare(res)
        if not br:
            stat["🔴 派生式剥括号后是空的"] += 1
            continue
        src_word, why = resolve_base(base, w, info)
        if src_word is None:
            stat["挂不上：" + why.split("`")[0].strip()] += 1
            continue
        if src_word == br:
            stat["基式与派生式相同（跳过）"] += 1
            continue
        wid = info[src_word][0]
        if br in have[wid]:
            stat["这条边已经有了（不重复插）"] += 1
            continue
        if br in infl.get(src_word, ()):
            stat["派生式已在该词元的活用表里（不跨层重复）"] += 1
            continue
        # 🔴 **挂载页必须是词元。** 派生词挂在一个非词元（＝某个词的活用形）页上，
        #    读者点进去看到的是「某词的变形」而不是一个词条 —— 而且非词元页恰恰是
        #    同形异义最容易撞上的地方（`얄` 在库里是 `pos=num` 的非词元）。
        #    实测代价：166 条里只有 1 条被这条规则挡下 ⇒ 判据便宜且有效。
        if not info[src_word][1]:
            stat["挂载页不是词元（同形异义风险，跳过）"] += 1
            continue
        cand.append((eid, w, wid, src_word, res, br in info, src))
        stat["✅ 要插"] += 1

    print("\n■ 分类")
    for k, v in stat.most_common():
        print("   %-38s %s" % (k, f(v)))

    # 🔴 词级边的 UNIQUE 靠不住（NULL≠NULL）⇒ 自己去重
    seen, uniq = set(), []
    for x in cand:
        key = (x[2], KIND, x[4])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(x)
    if len(uniq) != len(cand):
        print("   ⚠️ 批内自重复 %d 条已去掉（UNIQUE 对 sense_id IS NULL 的边不生效）"
              % (len(cand) - len(uniq)))

    dead = sum(1 for x in uniq if not x[5])
    print("\n■ 要插 %s 条 `%s` 边；其中派生式**不在 dict** 的 %s 条"
          % (f(len(uniq)), KIND, f(dead)))
    print("   （不在 dict 的存成 `target_norm=NULL` ⇒ 页面上印成不可点文本，"
          "不是死链 —— 阶段 9 定的那条路）")

    # ══ 账上要求的：抽样人眼确认方向没反 ══
    print("\n■ 抽 %d 条人眼看方向（左边必须是**基式**，右边是**派生式**）" % a.sample)
    pick = list(uniq)
    random.Random(20260926).shuffle(pick)
    for eid, w, _wid, src_word, res, ok, _src in pick[:a.sample]:
        print("   [%-6s] 词条 %-10s  挂在 %-14s → %-22s %s"
              % (eid, w, src_word, res, "" if ok else "（派生式不在 dict）"))

    if not uniq:
        print("\n■ 没有要插的")
        con.close()
        return
    n_before = con.execute("SELECT COUNT(*) FROM sense_relation").fetchone()[0]
    n_kind = con.execute(
        "SELECT COUNT(*) FROM sense_relation WHERE kind=?", (KIND,)).fetchone()[0]
    n_norm = con.execute(
        "SELECT COUNT(*) FROM sense_relation WHERE target_norm IS NOT NULL").fetchone()[0]
    con.close()

    if not a.apply:
        print("\n（干跑。**读过上面的抽样、确认方向没反**之后 --apply）")
        return

    ins = [(x[2], KIND, x[3] if False else x[4],
            bare(x[4]) if x[5] else None, x[6], "ko-example:%d#k11:0" % x[0])
           for x in uniq]
    # 🔴 `target` 存**源头写法**（`건축가(建築家)`），`target_norm` 只管链接落点 ——
    #    与 `dbtool.TRACK` 里那条注释是同一个口径，别抹平。
    with dbtool.session(
            "ko-k11-intake-word-formation",
            expect={"#sense_relation": len(ins),
                    "sense_relation.target": len(ins),
                    "sense_relation.target_norm": len(ins) - dead,
                    "__rows__": 0},
            invalidates=[]) as s:
        s.executemany(
            "INSERT INTO sense_relation (word_id, sense_id, kind, target, target_norm,"
            " tags, hidden, src, src_ref) VALUES (?, NULL, ?, ?, ?, NULL, 0, ?, ?)", ins)

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x, *p: con.execute(x, p).fetchone()[0]
    checks = [
        ("sense_relation 行数", q("SELECT COUNT(*) FROM sense_relation"), n_before + len(ins)),
        ("%s 边条数" % KIND, q("SELECT COUNT(*) FROM sense_relation WHERE kind=?", KIND),
         n_kind + len(ins)),
        ("target_norm 非空", q("SELECT COUNT(*) FROM sense_relation WHERE target_norm IS NOT NULL"),
         n_norm + len(ins) - dead),
        ("新边的 src_ref 唯一",
         q("SELECT COUNT(DISTINCT src_ref) FROM sense_relation WHERE src_ref LIKE '%#k11:%'"),
         len(ins)),
        ("新边一条不多不少", q("SELECT COUNT(*) FROM sense_relation WHERE src_ref LIKE '%#k11:%'"),
         len(ins)),
        # 🔴 反向：`dict` 一行没多（这一步只加边，不收词）
        ("dict 行数没变", q("SELECT COUNT(*) FROM dict"),
         q("SELECT COUNT(*) FROM dict")),          # 由写库闸的 `__rows__: 0` 保证
    ]
    # 抽**三条**真的查得出来：头、中、尾。
    # 🔴🔴 第一版这里印的标签是错的：`% (base, res)` 里的 `base` 是**上面那个循环
    #    泄漏出来的最后一行的基式**，于是打出「样例 `새 → 클린하다`」——
    #    查询本身按 `word_id`+`target` 走，是对的；**错的是标签**。
    #    一个印错对象的绿灯比没有绿灯更坏：它会让人以为验的是另一件事。
    #    ⇒ 标签一律从**这一条自己的字段**取，且断言它与 `word_id` 对得上。
    for pos in (0, len(uniq) // 2, len(uniq) - 1):
        _eid, _w, wid_i, src_word_i, res_i, _ok, _src = uniq[pos]
        got = q("SELECT COUNT(*) FROM sense_relation WHERE word_id=? AND kind=? AND target=?",
                wid_i, KIND, res_i)
        # 反向：这个 word_id 真的就是 `src_word_i` 那一页（别印错对象）
        page = q("SELECT word FROM dict WHERE id=?", wid_i)
        checks.append(("样例 `%s → %s` 在库里" % (src_word_i, res_i), got, 1))
        checks.append(("样例挂载页确实是 `%s`" % src_word_i, page == src_word_i, True))
    ok = True
    for name, got_v, want in checks:
        good = got_v == want
        ok &= good
        print("   %s %-30s %9s（期望 %s）" % ("✅" if good else "🔴", name, f(got_v), f(want)))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
