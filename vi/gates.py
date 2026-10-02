#!/usr/bin/env python3
"""**写库之后哪几道闸过期了** —— 名单、依赖、欠账状态，都在这一个文件里。vi，2026-09-28。

机制照搬 ko 的 **K31**（那部分与语言无关）。它为什么存在，一句话：
2026-09-26 发现 ko 有两道外锚闸**从前一天起一直红着**，两条都不是新缺陷，
是「修了数据没跟着重跑闸」—— 而流程里**没有任何一条机制逼人重跑**。
`[[lesson-must-become-mechanism]]`：**做成机制的全守住了，写成文字的一条没守住。**

═══ ⭐ vi 与 ko 的差别：这张名单现在**很短，而那是诚实的** ═══
ko 那份有 11 道闸，是九个阶段攒出来的。vi 刚做完阶段 1，真正存在的闸只有两道。
🔴 **别为了让名单好看而把不存在的闸写进去** —— 那正是 `self_check()` ③ 要拦的事
（ko 的教训：文件在、八门都写了、`package.json` 里没有入口，谁也没跑过）。
名单会随阶段长，长的时候每一道都要带 `why`。

═══ 判据：依赖写成「这道闸读了哪些表」，且**有意偏宽** ═══
🔴 `dict` 几乎被所有查询连着，动 `dict` 会脏掉几乎所有闸。
   宽的代价是多跑几分钟；窄的代价是漏跑（ko 那两条红了一整天）。
   **这一处宽是有意的，这句话本身就是判据的一部分，别哪天当成 bug「修窄」。**
"""
import datetime
import json
import subprocess
import sys
from pathlib import Path

import paths

ROOT = paths.ROOT
# 欠账状态跟**这个库**走，所以放在库边上而不是代码目录里
#（库不在 git 里，欠账也不该在 —— 换台机器就是另一个库、另一份欠账）。
PENDING = paths.DATA / "db" / ".vi-gates-pending.json"


# ── 闸名单 ──────────────────────────────────────────────────────────────────
# deps=None ＝ **已声明「动数据不会让它过期」**，必须同时写清为什么。
#   （与 `session(invalidates=[])` 同一个设计：空和没填要在结构上分得开。）
GATES = [
    dict(
        name="骨架闸",
        cmd="python3 -u vi/tests/test_skeleton.py",
        file="vi/tests/test_skeleton.py",
        deps=frozenset({"dict", "entry"}),
        why="阶段 1 的 15 条不变量。**它们原本只写在 `build.py --apply` 分支里** ——"
            "只在建库那一刻跑过一次，之后谁改坏了库都没人说话。"
            "其中一条是**读者口径**（`dict.pos` 的每个斜杠段），治的是 ko 的 K31。",
    ),
    dict(
        name="汉字层闸",
        cmd="python3 -u vi/tests/test_han_layer.py",
        file="vi/tests/test_han_layer.py",
        deps=frozenset({"dict", "entry", "han_spelling", "nom_spelling"}),
        why="阶段 2 的 9 条不变量。⭐ 其中 **H6 盯的是我的判据会不会过期** —— "
            "`is_ideograph` 的兜底码位表锚在一份会更新的外部数据（Unicode）上，"
            "库里出现连兜底都兜不住的字符就红。实测兜底当下救回 **286 个字符**，"
            "全是 Python 的 `unicodedata` 14.0 还不认识的扩展 H 喃字。",
    ),
    dict(
        name="音标层闸",
        cmd="python3 -u vi/tests/test_pron_layer.py",
        file="vi/tests/test_pron_layer.py",
        deps=frozenset({"dict", "pronunciation"}),
        why="阶段 3 的 10 条不变量。⭐ 其中 **P5 是读者口径的覆盖率下限**，"
            "而它是这套闸里**唯一会被「收词」弄红的一条** —— 行数闸对稀释结构性失明。"
            "P3 的判据**必须 GLOB 不能 LIKE**（LIKE 不认方括号字符类 ⇒ 永远不响）。"
            "P8 把「西贡音藏在 note 里」那次栽跤做成了闸。",
    ),
    dict(
        name="义项层闸",
        cmd="python3 -u vi/tests/test_sense_layer.py",
        file="vi/tests/test_sense_layer.py",
        deps=frozenset({"dict", "entry", "sense", "sense_src", "sense_gloss",
                        "han_spelling", "nom_spelling"}),
        why="阶段 5a 的 11 条不变量。⭐ **E9 是 W2 那条判据的落点**："
            "出版层里不许出现「中文释义就是该词的汉字表记」—— 那是 69.2% 的 zh gloss。"
            "E7 守「证据层永不编辑」：被隐藏的 33,615 条必须还在 `sense_src` 里。"
            "⚠️ 依赖里带 `han_spelling`/`nom_spelling` 是**有意的** —— "
            "W2 的判据拿表记当尺子，表记层一变这道闸的答案就变。",
    ),
    dict(
        name="例句层闸",
        cmd="python3 -u vi/tests/test_example_layer.py",
        file="vi/tests/test_example_layer.py",
        deps=frozenset({"dict", "sense", "example", "example_gloss"}),
        why="阶段 6a 的 14 条不变量。🔴 **X7 是这一层最该守的那条**："
            "vi 版的 `example.translation` 里**一条真译文都没有**"
            "（214 条整串是 `.`，290 条是 `(tục ngữ)` 这种出处）—— 照字段名收"
            "读者就会看见「译文：.」。X7 查出版层没有 vi 语译文，收回来当场红。"
            "X8 守「隐藏的例句不带译文」—— 阶段 6d 若去买翻译是按「有没有译文」挑行的，"
            "钱会花在不出版的行上（ko 的 6d 正是这个口径）。"
            "X12 查**十二份切片都有例句落进来**，只查「表非空」的话少收十一版也全绿。",
    ),
    dict(
        name="关系与量词闸",
        cmd="python3 -u vi/tests/test_relation_layer.py",
        file="vi/tests/test_relation_layer.py",
        deps=frozenset({"dict", "sense", "sense_relation", "noun_classifier"}),
        why="阶段 6b/6c 的 20 条不变量。🔴 **R8/R9/R10 三条一起守 B17**，而守的是"
            "**正确那一版判据**：naive 版（兜底 `related` 撞上任何别的 kind）命中 14,547 对，"
            "正确版（撞上**语义**更具体的 kind）只有 1,317 对 —— 差 11 倍，"
            "差的全是 `paronym+related`，而 paronym 是**语音**关系不蕴含语义相关。"
            "只查「隐藏了多少」挡不住判据被放宽；R9 是上限、R10 是反向断言。"
            "⚠️ R19 2026-10-01 **逮到一个真缺陷**（155 个纯表意词形躺在 dict 里），"
            "根因是 `is_ideograph` 当时有两份实现而收词用的是没兜底那份。",
    ),
    dict(
        name="录音层闸",
        cmd="python3 -u vi/tests/test_audio_layer.py",
        file="vi/tests/test_audio_layer.py",
        deps=frozenset({"dict", "audio"}),
        why="阶段 6d 的 12 条不变量。🔴🔴 **A4 是这道闸存在的理由**："
            "schema 的 `UNIQUE(word_id, url)` **挡不住 B12** —— 同一个 Commons 文件在"
            "各版里有不同的 url（各维基内嵌转码后的 mp3），按 url 去重只能并到 4,560，"
            "按 `commons_key` 并才到 3,110 ⇒ **1,450 行重复会落库**，"
            "页面上两个按钮播同一个文件。这一条**不是 DDL 保证的**。"
            "A8 盯着跨版收割（去重后净增只有 654 条 +26.6%，删掉它总行数只掉两成）。",
    ),
    dict(
        name="词源层闸",
        cmd="python3 -u vi/tests/test_etymology_layer.py",
        file="vi/tests/test_etymology_layer.py",
        deps=frozenset({"dict", "entry", "etymology", "etymology_gloss", "han_spelling"}),
        why="阶段 7a 的 17 条不变量。🔴🔴 **Y5 是这道闸存在的理由**："
            "zh 版 26,230 段「词源」里 **21,239 段整段只是 `thư viện［書院］`** —— "
            "那是汉字表记不是词源，归阶段 2。收进词源栏 ⇒ 读者在「词源」里看见一串汉字，"
            "而页面上方「汉字表记」栏印着同一串（W2 那个病换了个栏目）。"
            "Y5 查的是**出版层里有没有**，不是「跳过了多少段」—— 后者在判据被改宽时仍为真。"
            "Y7 治的是 **5,390 段内嵌 `__NOEDITSECTION__`**（vi 版可出版段的 64.7%），"
            "⭐ 那是 `sample_check` 的抽样反验逮到的，形状检查看不见（这段**该收，只是脏**）。"
            "⚠️ 依赖里带 `han_spelling` 是**有意的** —— Y5 的变异拿表记当素材。",
    ),
    dict(
        name="外锚闸·例句/关系/词源/录音/量词",
        cmd="python3 -u vi/pipeline/verify_layers_vs_dump.py",
        file="vi/pipeline/verify_layers_vs_dump.py",
        deps=frozenset({"dict", "entry", "sense_src", "example", "example_gloss",
                        "sense_relation", "etymology", "audio", "noun_classifier"}),
        why="**五层 vs dump 的三向恒等式**（源头缺／库里多／**键对上而内容不一样**）。"
            "前八道闸锚的都是库自己 ⇒ 对「收割器整批漏抽」失明；这一道锚外部 dump ⇒ "
            "`[[external-anchor-gates]]` **永不过期**。"
            "⭐ 它**一个判据都不重写**，五层各 import 收割器的 `collect()` —— 为此把四个"
            "收割器埋在 `main()` 里的逻辑抽成了 `index()`/`collect()`。"
            "🔴 ko 那道同名闸判据写错过两次（例句太宽报 3 万假缺、读音太细报 7,163 假缺），"
            "根因都是「闸自己重写了收割器的判据」。"
            "🔴🔴 **而这一道第一次跑就逮到我自己两条**：`src.endswith('-edition')` 认不出 "
            "`zh-edition-trad`（690 条真译文被判成第三类）／「哪些行才真的落库」我又写了一遍"
            "（漏掉「可出版」那半句，458 条假缺）⇒ **import 判据还不够，落库口径也要共用一个函数**。"
            "⚠️ 依赖故意写得宽（带 `dict`/`entry`/`sense_src`）：它们是收割的索引，"
            "动了它们恒等式的答案就变。⚠️ 跑一趟要扫 12 份 dump × 5 层（分钟级）—— "
            "**所以它不在写库后自动跑的那几道里**，靠 `gates.mark()` 记账＋账的闸拦着（ko 的 K31 机制）。",
    ),
    dict(
        name="表结构闸",
        cmd="python3 -u vi/pipeline/build_v3_schema.py --check",
        file="vi/pipeline/build_v3_schema.py",
        deps=None,
        why="⚠️ **有意没有数据依赖**：它比的是 DDL（25 个对象在不在、"
            "以及**有意不建的三张表有没有偷偷出现**），一行数据都不读。"
            "插多少行都不会让它过期，**建表/删表**才会 —— 而那不走 `session()`。"
            "⇒ 它进这张名单不是为了「写库后跑」，而是为了 `run_gates.py --all` "
            "和 `self_check()` 管得到它。写成 `deps=None` 而不是空集合，"
            "是为了让「想过了」和「忘了填」分得开。",
    ),
]

# ── 没有任何闸盯着的表：**必须在这儿逐张说明，并且带一个会失效的条件** ──────
# 🔴 这不是豁免清单，是**带锁的豁免**：条件写成「还是 0 行」，
#    哪天有人往里写了第一行，`self_check()` 当场红，逼人去登记一道闸。
#    光写一句「以后再说」＝ ja 的 `sense_tag` 空了整个项目而阶段表全 ✅。
_LATER = "（0 行）。落第一行之前必须先登记一道闸 —— 要验的是覆盖率与内容对不对，不是行数。"
UNCLAIMED = {
    "sense_tag":        "义项标签" + _LATER,
    "etymology_gloss":  "词源正文的中文" + _LATER,
    "field_src":        "字段来源登记" + _LATER,
}
# ⭐ **2026-10-01：五张表从这张名单里毕业了** —— `example` / `example_gloss` /
#    `sense_relation` / `noun_classifier` / `audio`。
#    这个「带锁的豁免」机制当天验过一次真的：四次写库，每次落第一行
#    `self_check()` 都当场判红、逼我去登记闸，一次都没让我往下走。
#    ⚠️ 它们原来各自带着一句「哪道闸该管它」（B17 归关系闸、B12 归录音闸）——
#      那两句话现在真的变成了 R8/R9/R10 与 A4。**写在名单里的提醒兑现了才算数。**
# ⭐ **2026-10-02：`etymology` 也毕业了**（阶段 7a）。它原来带的那句是
#    「B18（词源正文对读者不可见）要在那道闸里」—— ⚠️ **这一句只兑现了一半**：
#    数据层的闸（Y1–Y17）建了，而 B18 问的是**读者看不看得见**，那要等阶段 9 的
#    展示层契约闸。⇒ B18 现在是一笔**真欠账**（之前库里 0 行，它连欠账都算不上）。


def by_name(name):
    for g in GATES:
        if g["name"] == name:
            return g
    return None


# ── 从一次写库的 diff 算出过期的闸 ──────────────────────────────────────────
def table_of(key):
    """`diff()` 的键 → 它属于哪张表。

    键有三种形状（见 `dbtool.snapshot`）：`__rows__` / `表.列` / `#表`。
    裸列名（`pos`、`freq_zipf`）属于主表 `dict`。
    """
    import dbtool
    if key == "__rows__":
        return dbtool.TABLE
    if key.startswith("#"):
        return key[1:]
    return key.split(".", 1)[0] if "." in key else dbtool.TABLE


def dirty(d, extra_tables=()):
    """→ (过期的闸名列表, 动过的表集合)。

    🔴🔴 **`d`（计数差）和 `extra_tables`（从 SQL 抠的表名）两个都要，后者是主的。**
       ko 的第一版只看 `d`，当天就被一次纯内容 `UPDATE` 穿过去：
       20 条例句译文改了、所有计数一个没变、欠账是空的。
       `[[primary-key-is-not-enough]]`：**计数型判据对内容改动结构性失明。**
       留着 `d` 是因为它能认出**加列**这种 SQL 里看不出表名的变化。
    """
    touched = {table_of(k) for k in d} | {str(t).lower() for t in extra_tables}
    out = [g["name"] for g in GATES
           if g["deps"] is not None and (g["deps"] & touched)]
    return sorted(out), touched


# ── 欠账状态 ────────────────────────────────────────────────────────────────
def load():
    """→ {闸名: {"tag":…, "when":…, "tables":[…]}}。

    🔴 文件不存在 ＝ 没欠账（初始状态，安全）。
       文件**读不动** ≠ 没欠账 —— 那种时候抛，别静默当空。
    """
    if not PENDING.exists():
        return {}
    try:
        obj = json.loads(PENDING.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise SystemExit("🔴 欠账文件读不动（%s）：%s\n"
                         "   **不许当成「没欠账」** —— 手动查明，或删掉它并把所有闸跑一遍。"
                         % (e, PENDING))
    if not isinstance(obj, dict):
        raise SystemExit("🔴 欠账文件不是对象：%s" % PENDING)
    return obj


def _save(obj):
    PENDING.parent.mkdir(parents=True, exist_ok=True)
    PENDING.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True),
                       encoding="utf-8")


def mark(names, tag, tables=()):
    """记上欠账。已经欠着的保留**最早**那次的 tag（谁弄脏的才是线索）。"""
    if not names:
        return {}
    cur = load()
    now = datetime.datetime.now().isoformat(timespec="seconds")
    for n in names:
        if n not in cur:
            cur[n] = {"tag": tag, "when": now, "tables": sorted(tables)}
    _save(cur)
    return cur


def clear(name):
    """划掉一笔。**只该由「闸真的退出码 0」调用**（见 `run_gates.py`）。"""
    cur = load()
    if name in cur:
        del cur[name]
        _save(cur)
        return True
    return False


def clear_all():
    if PENDING.exists():
        PENDING.unlink()


def announce(cur=None, out=None):
    """把欠账大声说出来。**说在写库输出的最末尾** —— 那是人还在看屏幕的时候。"""
    out = out or sys.stdout
    cur = load() if cur is None else cur
    if not cur:
        return 0
    print("\n🔴🔴 **以下闸已过期，必须重跑**", file=out)
    for n in sorted(cur):
        v = cur[n]
        print("     · %-20s ← %s（%s）" % (n, v.get("tag", "?"), v.get("when", "?")), file=out)
    print("   ⇒ 一条命令跑完欠的那几道：**python3 vi/run_gates.py**", file=out)
    print("      （每道跑绿才划掉自己那一笔；跑不绿的留着，账的闸 **V9** 会一直红）", file=out)
    return len(cur)


# ── 闸自己的闸 ──────────────────────────────────────────────────────────────
def self_check():
    """→ 问题列表（空 ＝ 通过）。这道自检查的是**名单本身**对不对。"""
    import sqlite3
    bad = []
    seen, claimed = set(), set()
    for g in GATES:
        if g["name"] in seen:
            bad.append("闸名重复：%s" % g["name"])
        seen.add(g["name"])
        if not (ROOT / g["file"]).exists():
            bad.append("闸文件不存在：%s（%s）" % (g["file"], g["name"]))
        if not g.get("why", "").strip():
            bad.append("%s 没写 why —— 依赖为什么是这些，得说得出来" % g["name"])
        if g["deps"] is not None:
            if not g["deps"]:
                bad.append("%s 的 deps 是**空集合** —— 想过了要写 `deps=None` 并说明，"
                           "空集合分不清「没依赖」和「忘了填」" % g["name"])
            claimed |= g["deps"]

    # ① 每张追踪中的表，至少要有一道闸盯着
    import dbtool
    tables = set(dbtool.TRACK_TABLES) | {dbtool.TABLE}
    for t in sorted(tables - claimed - set(UNCLAIMED)):
        bad.append("🔴 表 `%s` **没有任何闸盯着** —— 动了它一道闸都不会脏。"
                   "登记一道闸，或写进 UNCLAIMED 并带一个会失效的条件" % t)

    # ② UNCLAIMED 里的表必须**还是 0 行**（带锁的豁免，不是永久豁免）
    if paths.DB.exists():
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        try:
            live = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            for t, why in sorted(UNCLAIMED.items()):
                if t not in tables:
                    bad.append("UNCLAIMED 里的 `%s` 不在追踪名单里 —— 名单漂了" % t)
                    continue
                if t not in live:
                    continue
                n = con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
                if n:
                    bad.append(
                        "🔴🔴 `%s` 已经有 **%s 行**，而它还挂在 UNCLAIMED（理由写的是"
                        "「%s」）—— 豁免的条件已经不成立，**去登记一道闸盯着它**"
                        % (t, format(n, ","), why[:40]))
        finally:
            con.close()
    else:
        bad.append("库不存在，UNCLAIMED 的「还是 0 行」这一条查不了：%s" % paths.DB)

    # ③ 每道闸都得在账的闸的交付物名单里（登记了，被删掉才会有人说话）
    try:
        sys.path.insert(0, str(ROOT / "vi"))
        from tests.test_plan_ledger import FILES
        listed = {p for items in FILES.values() for _n, p in items}
        for g in GATES:
            if g["file"] not in listed:
                bad.append("%s（%s）**不在账的闸的交付物名单里** —— "
                           "它被删掉不会有人说话" % (g["name"], g["file"]))
    except Exception as e:                       # noqa: BLE001
        bad.append("读不到 test_plan_ledger.FILES（%s）—— 那本身要查" % e)

    # ④ npm 入口的闸，`package.json` 里真有那个 script（B15：文件在而没人跑得动它）
    try:
        pj = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        scripts = pj.get("scripts", {})
        for g in GATES:
            if g["cmd"].startswith("npm run"):
                key = g["cmd"].split()[-1]
                if key not in scripts:
                    bad.append("%s 的入口 `npm run %s` **在 package.json 里不存在**（B15）"
                               % (g["name"], key))
    except Exception as e:                       # noqa: BLE001
        bad.append("读不到 package.json（%s）" % e)
    return bad


def run(name, verbose=True):
    """跑一道闸。→ True/False。**绿了才划账**，而「绿」的定义是退出码 0。"""
    g = by_name(name)
    if g is None:
        raise SystemExit("🔴 没有这道闸：%r" % name)
    if verbose:
        print("\n── %s\n   $ %s" % (name, g["cmd"]))
    r = subprocess.run(g["cmd"], shell=True, cwd=str(ROOT))
    ok = r.returncode == 0
    if ok:
        clear(name)
    else:
        # 🔴 **跑红了也要记一笔** —— 哪怕它本来不在欠账里。
        #    只做「绿了划账」的话，一道**本来就红着**的闸（没有任何写库弄脏它）
        #    跑出红之后欠账还是空的、账的闸照样绿 ——
        #    那正是 ko 那两条的处境：**红着而没有任何东西记得它红。**
        mark([name], "run-red（跑出红，不是写库弄脏的）", ("（跑红）",))
    if verbose:
        print("   %s %s（退出码 %d）" % ("✅" if ok else "🔴", name, r.returncode))
    return ok


if __name__ == "__main__":
    bad = self_check()
    print("■ vi 闸名单自检：%d 道闸" % len(GATES))
    for b in bad:
        print("   🔴 " + b)
    print("   %s" % ("✅ 通过" if not bad else "🔴 %d 个问题" % len(bad)))
    n = announce()
    if not n:
        print("\n■ 当前没有欠跑的闸 ✓")
    raise SystemExit(1 if (bad or n) else 0)
