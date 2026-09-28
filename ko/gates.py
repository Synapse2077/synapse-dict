#!/usr/bin/env python3
"""**写库之后哪几道闸过期了** —— 名单、依赖、欠账状态，都在这一个文件里。K31，2026-09-26。

═══ 这个文件为什么存在 ═══
2026-09-26 做 K12 时顺手跑了一遍全量闸，发现**两道外锚闸从 09-25 起一直红着**：

    ① `verify_vs_dump.py`       拿已经作废的方针（「日文版整版不进」）报红
    ② `verify_layers_vs_dump.py` 报 `('하다','Ko[ha̠da̠].oga','bare')` 缺失，
                                 而那正是 09-25 `fix_audio_filename_leak.py` 修掉的东西

两条都**不是新缺陷**，是「修了数据没跟着登记」。红了整整一天没人知道，
因为 `dbtool.session` 写后只自动跑**回归闸 ＋ 账的闸 ＋ 字面量闸**，
而外锚闸和契约闸**要手动跑**，靠的是我记得。

⇒ 真正的欠账不是那两条红，是**流程里没有一条机制逼人重跑相关的闸**。
  账上把结清条件写成：「⚠️ 不许只在文档里写『记得跑』」——
  `[[lesson-must-become-mechanism]]`：**做成机制的全守住了，写成文字的一条没守住。**

═══ 为什么不是「写后直接全跑」 ═══
外锚闸要逐行扫 5 份 dump（合计 340 MB，单趟分钟级），契约闸要起 tsx。
写库脚本一轮常常连写好几次 —— 全跑会让人**关掉它**，那比不装还糟。
⇒ 改成**记账 + 拦着不放过**：

    写库 →（按这次动了哪些表）算出过期的闸 → 落到欠账文件 → 屏幕上大声说
      ↓
    欠账非空时，**账的闸报红**（P10）—— 而账的闸每次写库都自动跑
      ↓
    `python3 ko/run_gates.py` 跑欠的那几道，**每道跑绿才划掉自己那一笔**

关键在最后一步：划账的动作**只由「闸真的退出码 0」触发**，不由人声称。

═══ 判据：依赖写成「这道闸读了哪些表」 ═══
🔴 有意**偏宽**：`dict` 被 12 张表的查询连着，动 `dict` 几乎会脏掉所有闸。
   宽的代价是多跑几分钟；窄的代价是漏跑（就是 09-25 那两条）。
   `[[criteria-narrower-than-you-think]]` 的教训方向在这里是反的 ——
   **这一处宽是有意的，且这句话本身就是判据的一部分，别哪天当成 bug「修窄」。**
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import paths

ROOT = paths.ROOT
# 欠账状态跟**这个库**走，所以放在库边上而不是代码目录里。
# （库不在 git 里，欠账也不该在 —— 换台机器就是另一个库、另一份欠账。）
PENDING = paths.DATA / "db" / ".ko-gates-pending.json"

# ── 服务层读了哪些表：**从 `korean.ts` 抠**，不在这儿手抄一份 ────────────────
#    理由是「读者口径」（`[[correct-steps-can-compose-a-hole]]`）：契约闸走服务层，
#    它脏不脏取决于 `korean.ts` SELECT 了什么，而不取决于我记得多少张表。
#    🔴 但扫源码的判据会**静默变空** —— 正则哪天对不上就变成「永远不脏」，
#       那正是 K31 要治的病本身。⇒ 锁一个下界常量，扫不到就红。
#       `[[fix-regression-and-gate]]`：**锁数字不锁名字。**
SERVICE_TS = ROOT / "packages" / "dict-core" / "src" / "korean.ts"
SERVICE_TABLES_FLOOR = 12      # 2026-09-26 实测 12 张；少于这个数 ⇒ 扫描本身坏了

_SQL_TABLE = re.compile(r"\b(?:FROM|JOIN|UPDATE|INTO)\s+([a-z_][a-z0-9_]*)", re.I)


def _known_tables():
    """追踪中的出版层表 ＋ `dict`。**从 `dbtool` 读，不手抄。**"""
    import dbtool                       # 延迟导入：dbtool 要 import 本文件
    return set(dbtool.TRACK_TABLES) | {dbtool.TABLE}


def service_tables():
    """→ 服务层真读了的表。扫不动就抛（不许退化成空集）。"""
    txt = SERVICE_TS.read_text(encoding="utf-8")
    tabs = {m.group(1).lower() for m in _SQL_TABLE.finditer(txt)} & _known_tables()
    if len(tabs) < SERVICE_TABLES_FLOOR:
        raise SystemExit(
            "🔴 从 %s 只抠出 %d 张表（下界 %d）——**扫描判据坏了**，\n"
            "   而它坏了的后果是「契约闸永远不脏」，正是 K31 要治的病。\n"
            "   扫到的：%s" % (SERVICE_TS.name, len(tabs), SERVICE_TABLES_FLOOR,
                              " ".join(sorted(tabs)) or "（空）"))
    return frozenset(tabs)


# ── 闸名单 ──────────────────────────────────────────────────────────────────
# deps=None ＝ **已声明「动数据不会让它过期」**，必须同时写清为什么。
#   （与 `session(invalidates=[])` 同一个设计：空和没填要在结构上分得开。）
GATES = [
    dict(
        name="外锚闸·义项",
        cmd="python3 -u ko/pipeline/verify_vs_dump.py",
        file="ko/pipeline/verify_vs_dump.py",
        deps=frozenset({"dict", "sense", "sense_src", "sense_gloss"}),
        why="源头有而库里没有的义项还剩多少。锚 5 份 dump ⇒ 永不过期，"
            "但**库变了它的答案就变了**。09-25 红了一天的第一条。",
    ),
    dict(
        name="外锚闸·例句/变形/读音",
        cmd="python3 -u ko/pipeline/verify_layers_vs_dump.py",
        file="ko/pipeline/verify_layers_vs_dump.py",
        deps=frozenset({"dict", "example", "inflection", "pronunciation",
                        "sense_relation"}),
        why="三层双向恒等式。09-25 红了一天的第二条（录音文件名冒充 IPA 修掉了，"
            "而源头侧判据没跟着登记）。",
    ),
    dict(
        name="展示层值域覆盖闸",
        cmd="python3 -u ko/tests/test_display_labels.py",
        file="ko/tests/test_display_labels.py",
        deps=frozenset({"dict", "entry", "sense_relation"}),
        why="映射表 vs 库里实际值域，两个方向。新值进库＝页面上一个空徽标。",
    ),
    dict(
        name="展示层契约闸·ko",
        cmd="npm run --silent gate:ko-display",
        file="apps/web/src/contract-check-ko.tsx",
        deps=None,      # 占位，`_fill()` 里换成 `service_tables()`
        why="真渲染 → 盯可见文字。阶段 9 逮到的六个缺陷里五个只有它看得见"
            "（`[[it-display-layer-stage8]]`）。",
    ),
    dict(
        name="词源展示契约闸",
        cmd="npm run --silent gate:etym-display",
        file="apps/web/src/contract-check-etym.tsx",
        deps=frozenset({"dict", "etymology", "sense"}),
        why="K26 逮到 38,796 条词源一条都到不了读者眼前。"
            "🔴 2026-09-26 之前它**在 package.json 里没有入口** —— "
            "文件在、八门都写了，而没人跑得动它。",
    ),
    dict(
        name="录音标签闸",
        cmd="npm run --silent gate:audio-labels",
        file="apps/web/src/contract-check-audio.tsx",
        deps=frozenset({"dict", "audio"}),
        why="同一个词的录音按钮标签两两不同（K23，八门 3,563 个词）。",
    ),
    dict(
        name="录音重复闸",
        cmd="python3 -u scripts/test_audio_dup_gate.py",
        file="scripts/test_audio_dup_gate.py",
        deps=frozenset({"audio"}),
        why="同一条录音存成两行（转码名 vs 原始名）。ko 的配额是 0。",
    ),
    dict(
        name="查询计划闸",
        cmd="python3 -u ko/probes/query_plans.py",
        file="ko/probes/query_plans.py",
        deps=frozenset({"dict", "sense", "inflection", "pronunciation"}),
        why="判据从 `korean.ts` 抠真 SQL。**大批写库会让 `ANALYZE` 的统计过期** ⇒ "
            "热查询从 0.04ms 掉回 51ms 而五道数据闸全绿。",
    ),
    # ── 下面两道是**建这张名单的当天才发现的**：文件在、八门都写了、
    #    `package.json` 里没有入口，谁也没跑过。
    #    🔴🔴 而 `css-audit` 当时**正红着，退出码 1** —— 从 `KoreanEntryView`
    #    进 `App.tsx` 那天（09-25）起就红着。这是 K31 那个病的第三例，
    #    也是「名单是按我知道的闸建的，所以名单比现实窄」的又一次。
    dict(
        name="块序/关系分级契约闸",
        cmd="npm run --silent gate:layout",
        file="apps/web/src/contract-check-layout.tsx",
        deps=None,      # 占位，`_fill()` 里换成 `service_tables()`
        why="八门义项内块序必须是同一个规范序列的子序列。2026-09-26 之前 **ko 不在它的"
            "名单里**（第四次漏登记语种），补 ko 之后 42 条义项合规。",
    ),
    dict(
        name="样式孤儿闸",
        cmd="npm run --silent gate:css-audit",
        file="apps/web/src/css-audit.ts",
        deps=None,
        why="⚠️ **有意没有数据依赖**：它比的是 `App.tsx` 用了哪些类名 vs `styles.css` "
            "定义了哪些 —— 两边都是**源码**，一行库都不读。改数据不会让它过期，"
            "改视图或改样式才会。⇒ 它进这张名单不是为了「写库后跑」，"
            "而是为了 `run_gates.py --all` 和账的闸 P12 的名单自检管得到它 —— "
            "它红了一整天没人知道，正因为没有任何名单收着它。",
    ),
    dict(
        name="G2P 外锚闸",
        cmd="python3 -u ko/tests/test_g2p_rules.py",
        file="ko/tests/test_g2p_rules.py",
        deps=None,
        why="⚠️ **有意没有数据依赖**：它锚在 표준발음법 的条文例词上，测的是 `g2p.py` "
            "这个**纯函数**，一行库都不读。改数据不会让它过期，改 `g2p.py` 才会 —— "
            "而那由 `ablate_g2p.py` 与它自己的 4 条变异管。"
            "写成 `deps=None` 而不是空集合，是为了让「想过了」和「忘了填」分得开。",
    ),
]

# ── 没有任何闸盯着的表：**必须在这儿逐张说明，并且带一个会失效的条件** ──────
# 🔴 这不是豁免清单，是**带锁的豁免**：条件写成「还是 0 行」，
#    哪天有人往里写了第一行，`self_check()` 当场红，逼人去登记一道闸。
#    光写一句「以后再说」＝ ja 的 `sense_tag` 空了整个项目而阶段表全 ✅。
UNCLAIMED = {
    "sense_tag":        "ko 一条标签都没抽（0 行）。要收的那天先登记闸再收。",
    "collocation":      "搭配层 ko 没做（0 行）。前五门那层 99.3% 是模型凭记忆写的，"
                        "ko 有意不做（`[[collocation-layer-is-llm-generated]]`）。",
    "collocation_gloss": "同上（0 行）。",
    # 🔴 2026-09-27 建表当天登记。表建了、`build_v3_schema.py` 与 `TRACK_TABLES` 都同步了，
    #    而**一道闸都没有** —— 这条自检当场把它拦下来了（K31 的机制第一次拦到我自己）。
    #    目标：词源正文的中文。两个来源，都还没落一行：
    #      ① 中文两片白送的 **6,942 条现成中文词源**（`src='zh-edition-*'`）
    #      ② 模型译文（`src='model:*'`）—— 而它是**跨门决定**（八门都没有译文），
    #         已记 `docs/BACKLOG.md` 的 B18，不是 ko 单独能定的
    #    ⚠️ 条件是「还是 0 行」：落第一行的那天这条自检就红，逼人先建
    #      「词源中文覆盖率 ＋ 引用形式没被改写」那道闸再入库。
    "etymology_gloss":  "词源正文的中文（0 行）。2026-09-27 建表，入库前必须先登记闸 —— "
                        "要验的是「覆盖率」和「被引用的语言形式一个字符都没改」"
                        "（古谚文结合型字母与声点最容易被模型顺手规范化）。",
}


def _fill():
    """把占位的 deps 换成真值。**只在真要用的时候算** —— `service_tables()` 会抛。"""
    for g in GATES:
        if g["name"] in ("展示层契约闸·ko", "块序/关系分级契约闸") and g["deps"] is None:
            g["deps"] = service_tables()
    return GATES


def by_name(name):
    for g in _fill():
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

    `d` 是 `dbtool.diff()` 的结果（**计数**差）；
    `extra_tables` 是 `dbtool` 从这次写库的 SQL 里抠出来的表名。

    🔴🔴 **两个都要**，而且 `extra_tables` 是主的。第一版只看 `d`，当天就被
       K16 的纯内容 UPDATE 穿过去：20 条例句译文改了、所有计数一个没变、
       `d` 是空的、欠账是空的。
       `[[primary-key-is-not-enough]]`：**计数型判据对内容改动结构性失明。**
       留着 `d` 是因为它能认出**加列**这种 SQL 里看不出表名的变化。
    """
    touched = {table_of(k) for k in d} | {str(t).lower() for t in extra_tables}
    out = [g["name"] for g in _fill()
           if g["deps"] is not None and (g["deps"] & touched)]
    return sorted(out), touched


# ── 欠账状态 ────────────────────────────────────────────────────────────────
def load():
    """→ {闸名: {"tag":…, "when":…, "tables":[…]}}。

    🔴 文件不存在 ＝ 没欠账（初始状态，安全）。
       文件**读不动** ≠ 没欠账 —— 那种时候抛，别静默当空
       （`[[residual-bucket-is-not-evidence]]` 的同一个形状：
        残差桶少一条消去器就虚胖，这里是「状态读不到就报没事」）。
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
    import datetime
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
    print("\n🔴🔴 **以下闸已过期，必须重跑**（K31 的机制；09-25 那两条红了一天"
          "就是因为这里什么都不说）", file=out)
    for n in sorted(cur):
        v = cur[n]
        print("     · %-26s ← %s（%s）" % (n, v.get("tag", "?"), v.get("when", "?")),
              file=out)
    print("   ⇒ 一条命令跑完欠的那几道：**python3 ko/run_gates.py**", file=out)
    print("      （每道跑绿才划掉自己那一笔；跑不绿的留着，账的闸 **P12** 会一直红）",
          file=out)
    return len(cur)


# ── 闸自己的闸 ──────────────────────────────────────────────────────────────
def self_check():
    """→ 问题列表（空 ＝ 通过）。这道自检查的是**名单本身**对不对。"""
    bad = []
    seen = set()
    claimed = set()
    for g in _fill():
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
    orphan = tables - claimed - set(UNCLAIMED)
    for t in sorted(orphan):
        bad.append("🔴 表 `%s` **没有任何闸盯着** —— 动了它一道闸都不会脏。"
                   "登记一道闸，或写进 UNCLAIMED 并带一个会失效的条件" % t)

    # ② UNCLAIMED 里的表必须**还是 0 行**（带锁的豁免，不是永久豁免）
    import sqlite3
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
                        % (t, format(n, ","), why))
        finally:
            con.close()
    else:
        bad.append("库不存在，UNCLAIMED 的「还是 0 行」这一条查不了：%s" % paths.DB)

    # ③ 每道闸都得在账的闸的交付物名单里（登记了才删得掉会响）
    try:
        sys.path.insert(0, str(ROOT / "ko"))
        from tests.test_plan_ledger import FILES
        listed = {p for items in FILES.values() for _n, p in items}
        for g in _fill():
            if g["file"] not in listed:
                bad.append("%s（%s）**不在账的闸的交付物名单里** —— "
                           "它被删掉不会有人说话" % (g["name"], g["file"]))
    except Exception as e:
        bad.append("读不到 test_plan_ledger.FILES（%s）—— 那本身要查" % e)

    # ④ npm 入口的闸，`package.json` 里真有那个 script
    pj = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    scripts = pj.get("scripts", {})
    for g in _fill():
        if g["cmd"].startswith("npm run"):
            key = g["cmd"].split()[-1]
            if key not in scripts:
                bad.append("%s 的入口 `npm run %s` **在 package.json 里不存在**"
                           % (g["name"], key))
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
        #    第一版只做「绿了划账」：于是一道**本来就红着**的闸（没有任何写库弄脏它，
        #    比如 `css-audit` 那种只读源码的）跑出红之后，欠账还是空的、P12 照样绿。
        #    那正好是 09-25 的处境：**红着而没有任何东西记得它红。**
        #    ⇒ 红也是一笔账，绿了才划掉。
        mark([name], "run-red（跑出红，不是写库弄脏的）", ("（跑红）",))
    if verbose:
        print("   %s %s（退出码 %d）" % ("✅" if ok else "🔴", name, r.returncode))
    return ok


if __name__ == "__main__":
    bad = self_check()
    print("■ 闸名单自检：%d 道闸" % len(GATES))
    for b in bad:
        print("   🔴 " + b)
    print("   %s" % ("✅ 通过" if not bad else "🔴 %d 个问题" % len(bad)))
    n = announce()
    if not n:
        print("\n■ 当前没有欠跑的闸 ✓")
    raise SystemExit(1 if (bad or n) else 0)
