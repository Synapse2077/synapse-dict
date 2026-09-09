#!/usr/bin/env python3
"""英语写库闸门 —— 备份 / 保留策略 / 不变量核对 / 冻结表 / 抽样反验。en 专用，不 import 其他语种。

═══ 为什么重做（2026-08-01 立，2026-09-06 阶段 -2 按 de 的形状重做）═══
本文件是 `de/dbtool.py` 的**拷贝 + 改语种特有部分**，不是 import ——
铁律①「按本质设计，按语种解耦，互不引用；宁可重复不要耦合」。

八月那版 194 行，`TABLE = "stardict"`、`TRACK` 只有 8 个音标/释义列，
而且**没有保留策略、没有三道自检闸** —— 那是 ECDICT 形状下够用的闸门。
v3 重构一次写库动几十万到几百万行，`docs/EN_PLAN.md` 阶段 -2 要求先把闸门补齐。

⚠️ `PLAYBOOK` 1.4：「不能推后。es 是先修了一周数据才有闸门的，那一周的写库全部无法追溯。」

═══ 🔴 最关键的一条：未声明的列 / 表必须零变化 ═══
`expect` 里没写的列与表，写库前后计数**必须完全相同**，否则报错退出。
这是唯一能自动发现"我以为只动了 A，其实把 B 也改了"的机制 —— 靠人眼看 UPDATE 发现不了。

═══ 🔴 en 独有的第四道：冻结表 ═══
`stardict`（→ 阶段 0 改名 `legacy_dict`）是**老库的只读底片**，
`EN_PLAN` §2.1 承诺"一个字节不动"。写在文档里的承诺守不住
（`[[lesson-must-become-mechanism]]`），所以做成机制：**任何以它为写入目标的
SQL 直接抛错**，除非显式 `session(..., unfreeze={"stardict"})`。

⚠️ 为什么不是"数它的列有没有变"：实测（2026-09-06）`stardict` 21 列的非空计数
   一次要 **13.82 秒**，一次 session 要取前后两次快照 ＝ 每次写库白等 28 秒。
   而且计数**看不见等量替换**（把 A 的译文换成 B 的，非空数不变）。
   SQL 层拦截既便宜（字符串匹配）又严格（拦的是动作不是后果）。
   ⭐ 判断闸该建在哪一层：**能拦动作就别去数后果。**

用法：
    import dbtool

    with dbtool.session("ipa-fill", expect={"ipa": +239513}) as s:
        s.executemany("UPDATE dict SET ipa=? WHERE id=?", plan)

    with dbtool.session("试跑", dry=True) as s:      # 只看快照，不备份不写
    with dbtool.session("keep-v3-schema", expect={...}) as s:   # 结构大改用 keep 前缀

只读快照：      python3 dbtool.py
自检：          python3 tests/test_prune_backups.py
"""
import os
import re
import shutil
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB

# 🔴 主干表是 `dict`（v3），**现在还不存在** —— 阶段 0 才建。
#    快照对不存在的表/列一律跳过，所以"先声明、后建出来"的顺序是安全的：
#    建出来的那一刻闸自动开始守，不靠"记得回来加"。
#    ⚠️ 别为了"现在能跑"把它改回 `stardict` —— 那样阶段 0 之后闸会静默守着一张
#       只读底片，而真正在动的 `dict` 没人看着。
TABLE = "dict"

# 追踪的列：写库前后都会计数。**不在这张表里的列，出了问题不会被发现**。
#
# 判据同 de/fr/it/pt：**凡是承载值的列全部进来**，只有 id / word / word_norm / is_lemma
# 四个身份列不进（它们 NOT NULL，非空计数恒等于总行数，计了也是常数）。
#
# 🔴 **与 `pipeline/build_v3_schema.py` 的 `DDL_DICT` 一一对应**（阶段 0 定稿后对齐）。
#    第一版照 de 预写了 `phonetic_*`/`definition`/`translation`/`meta`/`infl`/`collocation`…
#    —— 那是**迁移式阶段 0** 的列表，而 en 的阶段 0 是新建，那批列**有意不建**
#    （理由见 build_v3_schema 文件头①②：de 的 `dict.ipa` 就是收尾单 C41 那个病）。
#    留着它们会传递一个错的意思：好像将来往 `dict` 里写 translation 是预期之内的。
TRACK = [
    'pos',
    # 🔴 **词频与考纲**：五门都没有，挂得上率 98.2–100%（`EN_PLAN` §1.5①）。
    #    它们是**尺子**，阶段 3 收词 / 1.5 买多少 / 9 排序全靠它 ⇒ 被改动必须当场知道。
    'collins', 'oxford', 'exam_tag', 'bnc', 'freq_rank',
    'freq_zipf',                       # 阶段 5
]

# 🔴 **`dict` 上永远不许出现的列。**
#    音标只有 `pronunciation` 一个家、释义只有 `sense` 层一个家。
#    这不是风格问题：de 的 `dict.ipa` 在阶段 8 换读取路径之后读者就看不见了，
#    而闸查原列永远绿（收尾单 C41）。en 新建，从结构上不长这个器官。
#    ⇒ `tests/test_tools.py` 有一条常驻断言盯着它，不是靠记性。
DICT_FORBIDDEN = ('ipa', 'phonetic', 'phonetic_uk', 'phonetic_us',
                  'definition', 'translation', 'meta', 'collocation', 'example')

# 🔴 阶段 0 之后数据主体就不在 `dict` 上了 —— 只盯着一张表的闸门是**瞎的**。
#    [[fix-regression-and-gate]]：es 的整轮音标修复就是被"换了读取路径"绕过的。
#    ⇒ 出版层各表行数一并进快照：**没在 expect 里显式声明的表，行数必须零变化。**
TRACK_TABLES = ['entry', 'sense', 'sense_src', 'sense_gloss', 'sense_tag', 'sense_relation',
                'inflection',
                'pronunciation', 'pronunciation_entry', 'example', 'example_gloss',
                'collocation', 'collocation_gloss', 'audio',
                'search_prefix', 'search_prefix_meta', 'field_src',
                # ⬇ en 独有的两张，见 FROZEN_TABLES
                'stardict', 'legacy_dict']

# 🔴 `pronunciation_entry` 列在这里**不代表决定要建**（`EN_PLAN` §2.2② 还没量）。
#    列进清单只有一个效果：万一建了，闸立刻开始守。

# ══════ en 独有：冻结表 ══════
# 老库那张表是**只读底片**，不是数据源也不是主干（`EN_PLAN` §1.6 三层「源」）。
# 阶段 0 会把 `stardict` 改名成 `legacy_dict`，之后永远只读。
# ⚠️ **读它随便读**（`INSERT INTO dict SELECT … FROM stardict` 是阶段 0 的正常动作），
#    拦的只有**以它为写入目标**的语句。
FROZEN_TABLES = {"stardict", "legacy_dict"}

_WRITE_TARGET = re.compile(
    r"""(?ix)                 # 忽略大小写 + 可读排版
    \b(?:
        update \s+ (?:or \s+ \w+ \s+)?        |   # UPDATE [OR REPLACE] tbl
        insert \s+ (?:or \s+ \w+ \s+)? into \s+ |   # INSERT [OR IGNORE] INTO tbl
        replace \s+ into \s+                  |
        delete \s+ from \s+                   |
        drop \s+ table \s+ (?:if \s+ exists \s+)? |
        alter \s+ table \s+
    )
    ["'`\[]? (\w+)            # 目标表名（可能被引号/方括号包着）
    """)


def _frozen_hit(sql, allowed):
    """这条 SQL 是否以冻结表为写入目标。→ 命中的表名 or None"""
    for m in _WRITE_TARGET.finditer(sql or ""):
        t = m.group(1)
        if t in FROZEN_TABLES and t not in allowed:
            return t
    return None


def _cols(conn, table=None):
    return {r[1] for r in conn.execute("PRAGMA table_info(%s)" % (table or TABLE))}


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


# ══════ 「这段文本含中文吗」—— 判据只许这一份 ══════
# 🔴 只查基本区 U+4E00–U+9FFF **会把真中文判成不是中文**：`𬭊`/`𬭶` 是化学元素字
#    （扩展 F 区 U+2A700+），`䳍`（鹬鸵）在扩展 A 区，`𩽾𩾌`（鮟鱇）在扩展 B 区。
#    词典里恰恰大量出现这类字（元素名、鸟名、鱼名），基本区判据必然误伤。
_HAN_RANGES = (
    (0x3400, 0x4DBF),      # 扩展 A
    (0x4E00, 0x9FFF),      # 基本区
    (0xF900, 0xFAFF),      # 兼容表意
    (0x20000, 0x2FA1F),    # 扩展 B–F + 兼容补充
)


def has_han(s):
    return any(any(a <= ord(c) <= b for a, b in _HAN_RANGES) for c in s or "")


def snapshot(conn=None):
    """当前不变量：`dict` 总行数 + 各追踪列的非空行数 + 各表的行数（键前缀 `#`）。

    TRACK / TRACK_TABLES 里还不存在的列或表跳过。
    ⚠️ **主干表 `dict` 本身现在也还不存在** —— 那时 `__rows__` 记 0、TRACK 全跳过，
       但 `#stardict` 照常记得住。en 的阶段 -2 与阶段 0 之间就处在这个状态。
    """
    own = conn is None
    if own:
        conn = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    try:
        tabs = _tables(conn)
        out = {"__rows__": 0}
        if TABLE in tabs:
            out["__rows__"] = conn.execute("SELECT COUNT(*) FROM %s" % TABLE).fetchone()[0]
            have = _cols(conn)
            for c in TRACK:
                if c not in have:
                    continue
                out[c] = conn.execute(
                    "SELECT COUNT(*) FROM %s WHERE TRIM(COALESCE(%s,''))<>''" % (TABLE, c)
                ).fetchone()[0]
        for t in TRACK_TABLES:
            if t in tabs:
                out["#" + t] = conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        return out
    finally:
        if own:
            conn.close()


def diff(before, after):
    """两次快照之差。**必须取两边键的并集** —— 会话中途 ALTER 出来的新列只在 after 里有，
    只遍历 before 的话它从 0 涨到 15 万也看不见；阶段 0 要删列，同理反向。"""
    keys = set(before) | set(after)
    return {k: after.get(k, 0) - before.get(k, 0) for k in keys
            if after.get(k, 0) != before.get(k, 0)}


#  ── 保留策略（2026-08-11 在 es 上立，五次咬人后的现行版）─────────────────────
#  🔴 **策略要在库还小的时候就装上。** en 现在 640 MB 看着无所谓 ——
#     de 开工时 111 MB、做完 3.4 GB；fr 开工 96 MB、做完 2.9 GB。
#     等它长大再装，已经堆了几十 GB（es 十天攒过 56 GB）。
KEEP_TAG = "keep"
KEEP_PLAIN = 2              # 普通（非 keep）备份只留最近这么多个
# 同一语种**全部**备份的总量上限，**keep 也计入**（豁免名单本身会变成问题）。
# 超了按**稀疏度**淘汰（见 `_thin`），首尾永不删 —— 不按时间从老到新砍，
# 那样永远砍在最不该砍的地方（实测挤掉过不可再生的迁移锚点）。
MAX_BACKUP_BYTES = 8 * 1024 ** 3
# 完结之后预算收紧：留下的正好是最老那个（整轮重构之前，不可再生）和最新那个（回滚上一步）。
DONE_BACKUP_BYTES = 1.5 * 1024 ** 3

# 判据是**计划表里那一行**，不是手工开关 —— 那是「写着已修」和「真的修了」的老毛病。
PLAN_DOC = paths.ROOT / "docs" / "EN_PLAN.md"


def _language_is_done():
    """本语种是否已在计划表里标注完结。读不到文件一律按**未完结**（预算宽松）——
    删数据的默认值必须偏保守。"""
    try:
        return bool(re.search(r"^#+\s*✅\s*en\s*完结", PLAN_DOC.read_text("utf-8"), re.M))
    except OSError:
        return False


def _thin(items, when, budget, floor=2):
    """总字节超预算时，反复删掉**时间上最"挤"**的那个。→ (留下的, 删掉的)

    "挤" = 它与前后邻居的时间跨度最小 ⇒ 删了它，时间轴上留下的空洞最小。
    效果是**密集簇被抽稀、稀疏的老锚点自然存活**。

    🔴 `floor` = 最少留几个，首尾优先保住。里程碑用 floor=2；
       **普通备份必须 floor=0** —— 它们不是锚点，预算被里程碑占满时该让干净。
    """
    live = sorted(items, key=lambda p: when[p])
    total = sum(p.stat().st_size for p in live)
    out = []
    while total > budget and len(live) > max(floor, 0):
        if len(live) <= 2:                       # 只剩首尾，按从老到新让
            i = 0
        else:
            i = min(range(1, len(live) - 1),
                    key=lambda j: when[live[j + 1]] - when[live[j - 1]])
        p = live.pop(i)
        total -= p.stat().st_size
        out.append(p)
    return live, out


def _backup_time(p, day, hms):
    """备份时间取**文件名里的时间戳**，不取 mtime。

    🔴 `backup()` 用 `shutil.copy2`，**它连源库的 mtime 一起搬过来** ⇒ `.bak` 的 mtime
       是「这个库最后一次被写」的时刻，不是「备份什么时候打的」。es 上实测差过 9 天。
       规则①②都按时间排队，用错时钟会把**刚打的里程碑排成最老的**先删掉。
    ⚠️ 时分秒有 4 位和 6 位两种写法，补零到 6 位再解析；解析不了退回 mtime。
    """
    try:
        return time.mktime(time.strptime(day + hms.ljust(6, "0"), "%Y%m%d%H%M%S"))
    except ValueError:
        return p.stat().st_mtime


def prune_backups(verbose=True, dry=False):
    """三条规则依次收紧：
    ① 同一 tag 同一天只留一个 —— 普通留**最新**，keep 留**最早**（真正的 pre-state）
    ② 普通备份只留最近 KEEP_PLAIN 个
    ③ 总字节封顶（**keep 也计入**）：先砍普通的，还超就按稀疏度抽稀 keep

    `dry=True` 只列不删 —— **改这个函数之后先 dry 跑一遍**。
    它是本仓库里唯一一个会自动删数据的地方，写错了没有第二次机会。
    """
    pat = re.compile(r"^%s\.pre-(.+)-(\d{8})-(\d{4,6})\.bak$" % re.escape(DB.stem))
    rows, when = [], {}
    for p in paths.BACKUPS.glob("%s.pre-*.bak" % DB.stem):
        m = pat.match(p.name)
        if m:
            rows.append((p, m.group(1), m.group(2)))
            when[p] = _backup_time(p, m.group(2), m.group(3))
    exempt, drop = set(), []
    # ① 同 (tag, 日期) 只留一个。
    #    普通留最新（离现在最近的可恢复状态）；**keep 留最早** ——
    #    里程碑的意义是「操作 X **之前**的状态」，同一天同 tag 跑三次，
    #    第一个才是真 pre-state，后两个是改到一半的中间态，作为回滚锚点严格更差。
    newest, oldest = {}, {}
    for p, tag, day in rows:
        if KEEP_TAG in tag:
            k = (tag, day)
            if k not in oldest or when[p] < when[oldest[k]]:
                if k in oldest:
                    drop.append(oldest[k])
                oldest[k] = p
            else:
                drop.append(p)
            continue
        k = (tag, day)
        if k not in newest or when[p] > when[newest[k]]:
            if k in newest:
                drop.append(newest[k])
            newest[k] = p
        else:
            drop.append(p)
    exempt = set(oldest.values())              # 过了 ① 的 keep
    # ② 普通备份只留最近 KEEP_PLAIN 个。
    plain = sorted(newest.values(), key=lambda p: -when[p])
    drop += plain[KEEP_PLAIN:]
    plain = plain[:KEEP_PLAIN]

    # ③ 总字节封顶（keep 也计入），超了按稀疏度抽稀。先砍普通的（更不值钱）。
    done = _language_is_done()
    budget = DONE_BACKUP_BYTES if done else MAX_BACKUP_BYTES
    used = sum(p.stat().st_size for p in exempt)
    plain, cut = _thin(plain, when, max(budget - used, 0), floor=0) if plain else ([], [])
    drop += cut
    used += sum(p.stat().st_size for p in plain)
    if used > budget:
        survive_keep, cut_keep = _thin(list(exempt), when, budget - sum(
            p.stat().st_size for p in plain))
        drop += cut_keep
        exempt = set(survive_keep)
    keep = set(plain) | exempt

    # 删 keep 有两条路径，分开打（合并 = 信息淹没在噪声里）。
    by_group = {}
    for p, tag, day in rows:
        if KEEP_TAG in tag:
            by_group.setdefault((tag, day), []).append(p)
    survivors = {k for k, ps in by_group.items() if any(p in keep for p in ps)}
    for p in drop:
        if KEEP_TAG not in p.name:
            continue
        m = pat.match(p.name)
        grp = (m.group(1), m.group(2)) if m else None
        if grp in survivors:
            print("   · 清理同标签同日的重试快照：%s（该里程碑仍保留最早的一个）" % p.name)
        else:
            # ⚠️ 文案必须跟着规则改：稀疏度淘汰是**预期行为**，再打 🔴 就是狼来了。
            print("   %s：%s" % (
                "· 已完结，楼梯收干净（预算 %.1f GB）" % (budget / 1024 ** 3) if done
                else "⚠️ 淘汰里程碑（总量超 %.0f GB，抽稀掉这个时间点）" % (budget / 1024 ** 3),
                p.name))

    gone = sorted("%s@%s" % k for k in by_group if k not in survivors)
    if gone:
        print("   （被抽稀掉的里程碑标签：%s）" % ", ".join(gone))

    freed = sum(p.stat().st_size for p in drop)
    if dry:
        print("■ 试算：会保留 %d 个、删 %d 个（%.1f GB）" % (len(keep), len(drop), freed / 1024 ** 3))
        for p in sorted(keep):
            print("   保留  " + p.name)
        for p in sorted(drop):
            print("   删除  " + p.name)
        return len(drop), freed
    for p in drop:
        p.unlink()
    if verbose and drop:
        print("■ 备份保留策略：清掉 %d 个旧备份，释放 %.1f GB（保留 %d 个）"
              % (len(drop), freed / 1024 ** 3, len(keep)))
    return len(drop), freed


def backup(tag):
    """备份落在 `data/backups/`，并顺手执行保留策略。

    ⚠️ 别用 `DB.with_name(...)` —— 它跟着 DB 走会把备份写进 `data/db/`，与成品库混在一起。
    """
    paths.BACKUPS.mkdir(parents=True, exist_ok=True)
    dst = paths.BACKUPS / ("%s.pre-%s-%s.bak" % (DB.stem, tag, time.strftime("%Y%m%d-%H%M%S")))
    shutil.copy2(DB, dst)
    # 🔴 淘汰放在**复制之后**：万一复制失败就抛异常了，不会先删旧的再发现新的没建成。
    prune_backups()
    return dst


def _line(snap, d=None):
    parts = ["总行 {:,}".format(snap["__rows__"])]
    for c in TRACK + ["#" + t for t in TRACK_TABLES]:
        if c not in snap:
            continue
        s = "{} {:,}".format(c, snap[c])
        if d and c in d:
            s += " ({:+,})".format(d[c])
        parts.append(s)
    return " | ".join(parts)


class _S:
    """会话句柄。只暴露写库入口，强制所有写操作被计数、且过冻结表这道闸。"""

    def __init__(self, conn, unfreeze=()):
        self.conn = conn
        self.written = 0
        self.unfreeze = set(unfreeze or ())

    def _guard(self, sql):
        t = _frozen_hit(sql, self.unfreeze)
        if t:
            raise RuntimeError(
                "🔴 冻结表被写：`%s` 是老库的只读底片（EN_PLAN §2.1「一个字节不动」）。\n"
                "   语句：%s\n"
                "   读它不受限（INSERT INTO dict SELECT … FROM %s 是允许的），"
                "拦的只有以它为写入目标的语句。\n"
                "   确实要动（例如阶段 0 改名）：session(..., unfreeze={%r})"
                % (t, " ".join((sql or "").split())[:160], t, t))

    def executemany(self, sql, seq):
        self._guard(sql)
        seq = list(seq)
        self.conn.executemany(sql, seq)
        self.written += len(seq)
        return len(seq)

    def addcolumn(self, name, decl="TEXT", table=None):
        """幂等加列。加列本身不改任何行，不计入 written。"""
        tbl = table or TABLE
        self._guard("ALTER TABLE %s" % tbl)
        if name in _cols(self.conn, tbl):
            return False
        self.conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (tbl, name, decl))
        return True

    def execute(self, sql, args=()):
        self._guard(sql)
        return self.conn.execute(sql, args)

    def executescript(self, sql):
        """建表脚本入口（阶段 0 要用）。整段一起过闸。"""
        self._guard(sql)
        return self.conn.executescript(sql)


@contextmanager
def session(tag, expect=None, dry=False, verbose=True, unfreeze=()):
    """写库闸门。

    expect: {列名: 期望的非空计数变化}；表用 `"#表名"`。
        · 显式写出的列：变化必须**恰好等于**期望值；写 None 表示"允许变但不校验数值"。
        · **没写出的列 / 表：变化必须为 0。**
        · 总行数 `__rows__` 默认必须为 0；要插行就得**显式**写出期望的增量。
          🔴 这条不许拆掉，只能从"永远 0"改成"必须显式声明具体数字"。
          ⚠️ en 阶段 3 是本项目至今最大的一次插行（0 → 一百多万，再加 ECDICT 补充 260 万），
             插行时所有列的非空计数都会跟着涨，那批列必须逐个写进 expect，
             闸门才拦得住"多写了一列"。

    unfreeze: 本次会话允许写入的冻结表集合，例如阶段 0 的 `{"stardict"}`。
        🔴 **不要图省事常开** —— 它一开，`EN_PLAN` 承诺的"老表一个字节不动"就没人守了。
    """
    expect = dict(expect or {})
    before = snapshot()
    if verbose:
        print("■ 写库前不变量：" + _line(before))
    if dry:
        if verbose:
            print("(dry：不备份、不写库)")
        conn = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
        try:
            yield _S(conn, unfreeze)
        finally:
            conn.close()
        return

    bak = backup(tag)
    if verbose:
        print("■ 已备份 → " + bak.name)
    conn = sqlite3.connect(DB)
    # 🔴🔴 **必须自己控事务，不能用 Python 的默认模式。**
    #    2026-09-07 en 阶段 0 第一次 `--run` 当场踩到：`CREATE INDEX` 撞名抛错，
    #    异常分支 `conn.rollback()` 打印了"已 rollback"、还把备份当冗余删了 ——
    #    **而 13 张表和 `ALTER TABLE RENAME` 全都已经落库了。**
    #    根因：Python 的 sqlite3 传统模式**只为 DML(INSERT/UPDATE/DELETE) 隐式开事务**，
    #    DDL 走 autocommit ⇒ rollback 撤不掉。SQLite 本身是支持事务性 DDL 的，
    #    坏的是 Python 这层包装。⇒ `isolation_level=None` + 显式 BEGIN。
    #    ⚠️ de/pt/fr 的同一份代码都有这个洞，只是它们的阶段 0 没抛过错，没暴露。
    conn.isolation_level = None
    conn.execute("BEGIN")
    s = _S(conn, unfreeze)
    try:
        yield s
        conn.execute("COMMIT")
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        # 🔴 **不许把"调用过 rollback"当成"回滚成功了"。**
        #    上面那次就是这么丢掉退路的。⇒ 回滚之后**重新取一次快照与 before 比**，
        #    只有真的复原了才敢说备份是冗余的。
        try:
            restored = snapshot(conn) == before
        except sqlite3.Error:
            restored = False
        conn.close()
        if not restored:
            print("\n🔴🔴 写库异常，且**回滚没有把库复原**（DDL 可能已落库）。"
                  "\n   备份保留：%s"
                  "\n   回滚：cp '%s' '%s'" % (bak.name, bak, DB), file=sys.stderr)
            raise
        # 🔴 **rollback 成功 ⇒ 这份备份是冗余的，当场删掉。**
        #    留着它只是噪声，而噪声会挤掉里程碑（es 上实测挤掉过两个迁移锚点）。
        # ⚠️ 只删「异常回滚」这一路。**闸核对未通过那一路不能删** ——
        #    那时数据已经在库里，备份是唯一的回滚点。
        try:
            bak.unlink()
            print("\n🔴 写库异常，已 rollback；本次备份是冗余的，已删除（%s）"
                  % bak.name, file=sys.stderr)
        except OSError:
            print("\n🔴 写库异常，已 rollback。备份仍在：" + bak.name, file=sys.stderr)
        raise
    after = snapshot(conn)
    conn.close()

    d = diff(before, after)
    bad = []
    want_rows = expect.get("__rows__", 0)
    if d.get("__rows__", 0) != want_rows:
        bad.append("总行数变了 {:+,}，期望 {:+,}".format(d.get("__rows__", 0), want_rows))
    for c in TRACK:
        got = d.get(c, 0)
        if c in expect:
            want = expect[c]
            if want is not None and got != want:
                bad.append("{} 变化 {:+,}，期望 {:+,}".format(c, got, want))
        elif got:
            bad.append("🔴 未声明的列 {} 变了 {:+,} —— 改到了不该改的地方".format(c, got))
    for t in TRACK_TABLES:                       # 出版层表的行数，判据同上
        key = "#" + t
        got = d.get(key, 0)
        if key in expect:
            want = expect[key]
            if want is not None and got != want:
                msg = "{} 行数变化 {:+,}，期望 {:+,}".format(t, got, want)
                # ⭐ 认出「声明了总数而不是增量」这个形状，直接说人话。
                #    `expect={"#tbl": len(rows)}` 里 rows 是整轮扫描的产物，
                #    而 `INSERT OR IGNORE` 只插新的 ⇒ 期望值等于写库后的总数。
                if want == after.get(key, 0):
                    msg += ("\n      ⭐ 期望值恰好等于**写库后的总行数** ⇒ "
                            "多半是把 `expect` 写成了总数。它比的是**增量**：\n"
                            "         增量 = 这批 rows 里、键还不在库里的那些"
                            "（`INSERT OR IGNORE` 只插新的）")
                bad.append(msg)
        elif got:
            bad.append("🔴 未声明的表 {} 行数变了 {:+,} —— 动到了不该动的表".format(t, got))
    if verbose:
        print("■ 写入 {:,} 条".format(s.written))
        print("■ 写库后不变量：" + _line(after, d))
    if bad:
        # 🔴 核对失败的红字**必须同时走 stdout** —— 只走 stderr 时被 grep 一滤就看不见了，
        #    而数据已经 commit 了。结论在最后一行再重复一次，让它难被漏读。
        for out in (sys.stderr, sys.stdout):
            print("\n🔴 不变量核对未通过：", file=out)
            for b in bad:
                print("   " + b, file=out)
            # 🔴 **回滚命令必须先确认那个文件还在。说得出的回滚点必须是存在的回滚点。**
            if bak.exists():
                print("   回滚：cp '%s' '%s'" % (bak, DB), file=out)
            else:
                print("   🔴🔴 **没有回滚点** —— 本次备份 %s 已不在（被保留策略清掉，"
                      "或上一次异常回滚时自删）。只能向前修。" % bak.name, file=out)
            print("🔴🔴🔴 本次写库未通过，**数据已在库中**，要么按上面的命令回滚，"
                  "要么确认这些变化是预期的并补进 expect。", file=out)
        raise SystemExit(1)
    if verbose:
        print("■ 不变量核对通过 ✓")
    # 🔴 三道闸**各叫各的，谁也不挂在谁末尾** ——
    #    fr 那份把账的闸挂在回归闸末尾，而回归闸在文件不存在时提前 return，
    #    于是账的闸从建好起就是死的。一道闸的执行不许由另一道闸的存在与否决定。
    _regression_check(verbose)
    _ledger_gate(verbose)
    _literal_gate(verbose)


def _run_gate(fname, modname, title, fmt, verbose):
    """三道自检闸共用的跑法。

    **文件不存在 = 静默跳过**（那道闸还没建，不是坏了）；
    **文件在但跑不起来 = 必须喊**（闸自己坏了）。
    三道闸一律**只报不拦**：写库已经 commit 了，报出来 + 备份路径就够决策。
    """
    if not (HERE / "tests" / fname).exists():
        return
    try:
        sys.path.insert(0, str(HERE))
        mod = __import__("tests." + modname, fromlist=["check_brief"])
        red = mod.check_brief()
    except Exception as e:
        print("\n⚠️ %s没跑起来（%s）—— 这本身要查" % (title, e), file=sys.stderr)
        return
    if not red:
        if verbose:
            print("■ %s通过 ✓" % title)
        return
    print("\n🔴 %s报警：%d 条" % (title, len(red)), file=sys.stderr)
    for r in red[:8]:
        print("   " + fmt(r), file=sys.stderr)
    print("   明细：python3 tests/%s" % fname, file=sys.stderr)


def _regression_check(verbose=True):
    """回归闸 —— 过去每个修复现在还在不在。

    用户 2026-08-11：「同一个问题你修了，隔天修其他问题，你又发现之前的问题又出现了。」
    根因是修复写在**输出层**，而输出层会被 DROP 重建。上面两道不变量闸拦不住它们：
    行数没变、非空计数没变，**变的是内容对不对**。
    ⇒ 让回归在**产生它的那次写库**上报出来，而不是隔一周偶然撞见。

    📋 en 的回归闸在**阶段 7** 建，现在还不存在。
    """
    if os.environ.get("SKIP_REGRESSION_CHECK") == "1":
        return
    _run_gate("test_no_regression.py", "test_no_regression", "回归闸",
              lambda r: "%-5s %-38s %s" % r, verbose)


def _ledger_gate(verbose=True):
    """**账的闸** —— 计划表说的话与库里的事实对不对得上。

    🔴 起因：用户 2026-08-27「你自己定的规矩，自己的经验教训，你自己为什么不执行呢」。
       形状很干净：**做成机制的全守住了，写成文字的一条没守住。**
       ⇒ 不再往记忆里写"要记得 X"，写会自己响的东西。

    它逮的是**账**不是数据：阶段表标着 ✅ 而交付物是 0。
    """
    _run_gate("test_plan_ledger.py", "test_plan_ledger", "账的闸",
              lambda r: "%-6s %s" % r, verbose)


def _literal_gate(verbose=True):
    """**写死行数的断言**扫描。

    🔴 起因：pt 的脚本从 fr 拷来改，fr 的断言里写死了 fr 的行数，移植当天咬了三次。
       en 这一轮要从 de/pt 拷一整套过来，**形状完全相同**，所以第一天就挂上。
    """
    _run_gate("test_no_literal_counts.py", "test_no_literal_counts", "字面量闸",
              lambda r: "%s:%d  期望 %s  ← %s" % (r[0], r[1], f"{r[3]:,}", r[2][:44]), verbose)


def sample_check(rows, n=10, cols=("词", "改前", "改后")):
    """抽样反验：随机打印 n 条改前/改后，供人眼核。

    🔴 **别跳过这一步。**不变量只能证明"没改到不该改的范围"，
    证明不了"改对了内容" —— 后者只有人眼看得出来。
    """
    import random
    rows = list(rows)
    if not rows:
        print("(无可抽样的行)")
        return
    pick = random.sample(rows, min(n, len(rows)))
    w = [max(len(str(r[i])[:40]) for r in pick + [list(cols)]) for i in range(len(cols))]
    print("\n■ 抽样 {}/{:,} 条反验：".format(len(pick), len(rows)))
    print("   " + "  ".join(str(c).ljust(w[i]) for i, c in enumerate(cols)))
    for r in pick:
        print("   " + "  ".join(str(r[i])[:40].ljust(w[i]) for i in range(len(cols))))


if __name__ == "__main__":
    s = snapshot()
    print("%s  主干表 %s%s" % (DB.name, TABLE,
                              "" if s["__rows__"] else "  ⚠️ 尚未建（阶段 0 才建）"))
    print("  总行 {:,}".format(s["__rows__"]))
    for c in TRACK:
        if c not in s:
            print("  {:18}{:>12}".format(c, "(列不存在)"))
            continue
        print("  {:18}{:>12,}  {:>6.2f}%".format(c, s[c], 100 * s[c] / max(s["__rows__"], 1)))
    print("\n各表行数")
    for t in TRACK_TABLES:
        k = "#" + t
        mark = "  ❄ 冻结" if t in FROZEN_TABLES and k in s else ""
        print("  {:22}{:>12}{}".format(t, "{:,}".format(s[k]) if k in s else "(表不存在)", mark))
