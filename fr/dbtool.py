#!/usr/bin/env python3
"""法语写库闸门 —— 备份 / 保留策略 / 不变量核对 / 抽样反验。fr 专用，不 import 其他语种。

═══ 为什么有这个文件（2026-08-01 立，2026-08-21 按 es 一个月 + it 八天的教训重做）═══
实查：123 个脚本里 **31 个会写库**，每个都自己写了一遍 `shutil.copy2` 备份，
但**只有 4 个做写后不变量核对** —— 等于 27 次写库是没有验收的。
→ 从此写库必须走同一道闸：**备份 → 写 → 不变量核对 → 抽样反验**，缺一不可。

⚠️ `PLAYBOOK` 1.4：「不能推后。es 是先修了一周数据才有闸门的，那一周的写库全部无法追溯。」
   fr 的结构重构一次写库动几十万行，闸门必须在**第一次写库之前**就位。

═══ 🔴 最关键的一条：未声明的列必须零变化 ═══
`expect` 里没写的列，写库前后非空计数**必须完全相同**，否则报错退出。
这是唯一能自动发现"我以为只动了 A，其实把 B 也改了"的机制 —— 靠人眼看 UPDATE 语句发现不了。

用法：
    import dbtool

    plan = [(new_val, rid), ...]
    with dbtool.session("ipa-fill", expect={"ipa": +68174}) as s:
        s.executemany("UPDATE dict SET ipa=? WHERE id=?", plan)
    # 退出时自动核对；不符即抛错并打印回滚命令（已备份，可直接 cp 回去）

    with dbtool.session("试跑", dry=True) as s:   # 只看快照，不备份不写

    # 结构大改之前用 keep 前缀（阶段 0 / 阶段 3 这种）：
    with dbtool.session("keep-v2-schema", expect={...}) as s: ...

只读快照：
    python3 dbtool.py
自检（保留策略的行为测试，不碰真备份）：
    python3 tests/test_prune_backups.py
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
TABLE = "dict"

# 追踪的列：写库前后都会计数。**不在这张表里的列，出了问题不会被发现**。
#
# 🔴 2026-08-21 重列。旧版只追 6 列（ipa/translation/gender/pos/infl/level），
#    法语最本质的那批字段全在闸外面 —— `aux`(avoir/être)、`pp`(过去分词)、
#    `feminine`(阴性形)、`vgroup`(动词三组) 恰恰是 `docs/lang/fr-DESIGN.md` §0
#    列为"一等公民"的四个，闸却看不见它们变没变。
#    判据同 it：**凡是承载值的列全部进来**，只有 id / word / word_norm / is_lemma
#    四个身份列不进（它们 NOT NULL，非空计数恒等于总行数，计了也是常数）。
TRACK = ['ipa', 'ipa_src', 'pos', 'level',
         'aux', 'vgroup', 'transitivity', 'pronominal', 'pp',
         'gender', 'gender_src', 'plural', 'feminine', 'invariable',
         'adj_pos', 'government', 'comparative',
         'definition', 'translation', 'translation_src', 'meta',
         'infl', 'exchange', 'collocation', 'example', 'flag']

# 🔴 阶段 0 之后数据的主体就不在 `dict` 上了 —— 只盯着 `dict` 的闸门是**瞎的**。
#    [[fix-regression-and-gate]]：es 的整轮音标修复就是被"换了读取路径"绕过的，
#    查原列永远绿、用户看到的是错的。所以出版层各表的行数一并进快照：
#    **没在 expect 里显式声明的表，行数必须零变化**，删表 / 重建 / 少插一批都会当场报错。
#
# ⚠️ 现在 fr 库里只有 `dict` 一张表，下面这些**都还不存在** —— 快照会静默跳过不存在的表。
#    先写进清单是有意的：等阶段 0/1 把表建出来，闸自动开始守，不用"记得回来加"。
TRACK_TABLES = ['entry', 'sense', 'sense_src', 'sense_gloss', 'sense_tag', 'sense_relation',
                'inflection',
                'pronunciation', 'example', 'example_gloss',
                'collocation', 'collocation_gloss', 'audio']


def _cols(conn):
    return {r[1] for r in conn.execute("PRAGMA table_info(%s)" % TABLE)}


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def snapshot(conn=None):
    """当前不变量：`dict` 总行数 + 各追踪列的非空行数 + 各出版层表的行数（键前缀 `#`）。

    TRACK / TRACK_TABLES 里还不存在的列或表跳过 —— 这样"先写进清单、再由脚本建出来"
    的顺序是安全的（前后各取一次快照，它在中途出现，前快照没有、后快照有）。
    """
    own = conn is None
    if own:
        conn = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    try:
        have = _cols(conn)
        out = {"__rows__": conn.execute("SELECT COUNT(*) FROM %s" % TABLE).fetchone()[0]}
        for c in TRACK:
            if c not in have:
                continue
            out[c] = conn.execute(
                "SELECT COUNT(*) FROM %s WHERE TRIM(COALESCE(%s,''))<>''" % (TABLE, c)
            ).fetchone()[0]
        tabs = _tables(conn)
        for t in TRACK_TABLES:
            if t in tabs:
                out["#" + t] = conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        return out
    finally:
        if own:
            conn.close()


def diff(before, after):
    """两次快照之差。**必须取两边键的并集** —— 会话中途 ALTER 出来的新列只在
    after 里有，只遍历 before 的话它从 0 涨到 15 万也看不见；
    反过来阶段 0 要**删列**，被删的列只在 before 里有，同理。"""
    keys = set(before) | set(after)
    return {k: after.get(k, 0) - before.get(k, 0) for k in keys
            if after.get(k, 0) != before.get(k, 0)}


#  ── 保留策略（2026-08-11 在 es 上立，fr 开工即带）─────────────────────────
#  es 上每次写库前全量复制 697 MB，十天攒了 118 个备份、**56 GB**，
#  其中大量是同一天同一个 tag 隔一两分钟的重复。当天清掉 120 个、释放 50.9 GB。
#  不加策略的话两周后原样复发 —— 清理是一次性的，产生速度不是。
#  🔴 fr 现在的库只有 96 MB，看着无所谓；it 开工时是 155 MB，做完是 1.14 GB。
#     **策略要在库还小的时候就装上**，等它长大再装就已经堆了几十 GB。
#
#  🔴 里程碑用文件名豁免，不靠"记得手动留"：
#     tag 里带 `keep` 的（`dbtool.session("keep-v2-schema")`）不被"最旧"淘汰。
#     结构大改之前请用这个前缀 —— 那种备份删了就真回不去了。
KEEP_TAG = "keep"
#  🔴 2026-08-21：`keep` **只豁免 ①③，计入 ②**。
#     当天清盘发现自动淘汰一个都没删而 backups 已 9.8 GB：es 9 个备份里 6 个带 keep
#     全豁免，剩 3 个非豁免的字节数又刚好没到上限 ⇒ **堆积的不是普通备份，是豁免名单本身**。
#     （当时的修法是"把 keep 计入条数"—— 治标，2026-08-25 已被下面那条取代。）
#  🔴 2026-08-25 第四次咬人之后**换方向，不再调参数**：条数上限整个删掉。
#     它刚刚挤掉了 `keep-v3-infl@20260822`（不可再生的迁移锚点），而当天我打了
#     7 个彼此只差一次小改动的 1.8 GB 里程碑 —— **该删的是那 7 个里的中间几个，
#     不是最老的那个**。条数上限没有"哪个更值钱"的概念，只会按时间从老到新砍，
#     于是永远砍在最不该砍的地方。
#     ⇒ 新规则见 `prune_backups`：**按字节封顶（含 keep）+ 按稀疏度淘汰**。
KEEP_PLAIN = 2              # 普通（非 keep）备份只留最近这么多个 —— 例行 pre-state，
#                             下一个备份一出现，上一个的价值立刻衰减
# 同一语种**全部**备份的总量上限，**keep 也计入**。
# 🔴 keep 从前不计入字节 ⇒ 唯一约束它的是条数，而 fr 一个备份 1.8 GB、上限 24 个
#    ＝ 43 GB 的隐性预算，实测已经涨到 37 GB。豁免名单本身就是问题
#    （2026-08-21 在 es 上已经诊断过一次，当时的修法是"把 keep 计入条数"——治标）。
# ⇒ keep 计入字节，超了按**稀疏度**淘汰（见 `_thin`），首尾永不删。
MAX_BACKUP_BYTES = 8 * 1024 ** 3


def _thin(items, when, budget, floor=2):
    """总字节超预算时，反复删掉**时间上最"挤"**的那个。→ (留下的, 删掉的)

    "挤" = 它与前后邻居的时间跨度最小 ⇒ 删了它，时间轴上留下的空洞最小。
    效果是**密集簇被抽稀、稀疏的老锚点自然存活** —— 正好是按时间从老到新砍的反面。

    🔴 `floor` = 最少留几个，首尾优先保住：最新的是「回滚上一步」，
       最老的是「回到起点」，这两个的价值不随邻居多少衰减 ⇒ 里程碑用 floor=2。
    ⚠️ **普通备份不能用这个下限**：它们不是锚点，只是例行 pre-state，
       预算被里程碑占满时该让干净（floor=0）。第一版把 floor 写死成 2，
       测试当场逮到「普通的该砍光却留了 2 个」。
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

    🔴 2026-08-21：`backup()` 用 `shutil.copy2` 复制，**它连源库的 mtime 一起搬过来**
       ⇒ `.bak` 的 mtime 是「这个库最后一次被写」的时刻，**不是「备份是什么时候打的」**。
       两者能差很远：es 上实测最狠的 `pre-keep-v3-entry-20260820-140712.bak`
       mtime 是 **8-11、差 9 天**（库封版后一直没动，9 天后才打的这个备份）。
       规则①②都按时间排队，用错时钟会把**刚打的里程碑排成最老的**先删掉。
    ⚠️ 文件名时分秒有 4 位（`-1421`）和 6 位（`-140712`）两种写法，补零到 6 位再解析。
       解析不了就退回 mtime —— 宁可排序差一点，也不能因为一个怪名字就抛异常。
    """
    try:
        return time.mktime(time.strptime(day + hms.ljust(6, "0"), "%Y%m%d%H%M%S"))
    except ValueError:
        return p.stat().st_mtime


def prune_backups(verbose=True, dry=False):
    """三条规则依次收紧：
    ① 同一 tag 同一天只留一个   —— 普通留**最新**，keep 留**最早**（真正的 pre-state）
    ② 普通备份只留最近 KEEP_PLAIN 个
    ③ 总字节封顶 MAX_BACKUP_BYTES（**keep 也计入**）：先砍普通的，
       还超就按**稀疏度**抽稀 keep（`_thin`）—— 密集簇的中间点先走，首尾永不删

    🔴 2026-08-25 用 ③ 的稀疏度淘汰**换掉了**原来的条数上限。
       条数上限只会按时间从老到新砍，而"该砍的"恰恰是同一天连打的那几个近乎重复的
       快照 —— 它砍在了最不该砍的地方，实测挤掉 `keep-v3-infl@20260822`。

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
    #
    #    普通备份留**最新**：它是离现在最近的可恢复状态。
    #
    #    🔴 2026-08-23：keep 原来完全豁免这一条，**代价当天就付了** ——
    #    我把 `strip-footnote` 判据改窄了两次、重试三次，留下 3 个同标签同日的
    #    1.8 GB 快照（`apos` 更狠，4 个），条数配额被占满，规则② 挤掉了
    #    `pre-keep-v3-altof` 这个**阶段 2 的真里程碑**。
    #    ⇒ keep 也进这一条，但方向**相反：留最早的那个**。
    #      理由：里程碑的意义是「操作 X **之前**的状态」。同一天同一个 tag 跑了三次，
    #      第一个才是真正的 pre-state，后两个是我改到一半的中间态 ——
    #      作为回滚锚点严格地更差。
    #    ⚠️ 代价说明白：如果同一天把同一个 tag 复用给了两个**不同**的操作，
    #      留最早 = 回滚会多退一步。仍然可恢复，只是退得更远。
    #      （这比「里程碑被重试快照挤掉」——直接不可恢复——好。）
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
    #    它们是例行的 pre-state，下一个备份一出现，上一个基本就没人会回去了；
    #    而里程碑不一样，它标的是「某次结构变更之前」，隔多久都可能要回去。
    plain = sorted(newest.values(), key=lambda p: -when[p])
    drop += plain[KEEP_PLAIN:]
    plain = plain[:KEEP_PLAIN]

    # ③ 总字节封顶（**keep 也计入**），超了按稀疏度抽稀。
    #    先砍普通的（更不值钱），还超再抽稀 keep。
    budget = MAX_BACKUP_BYTES
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

    # 🔴 删 keep 有**两条**路径，仍然分开打（合并打印 = 信息淹没在噪声里）：
    #    ①' 同标签同日的重试快照 —— 该组仍留着最早那个，没丢回滚能力
    #    ③  预算超了被抽稀 —— 该标签整个消失
    # ⚠️ 2026-08-25：③ 从前是「条数上限从最老开始砍」＝**意外**，所以用 🔴 报警；
    #    换成稀疏度淘汰之后它是**预期行为**（密集簇本来就该抽稀），
    #    再打 🔴 就是狼来了。降级成陈述句，但仍逐条列出来，不许静默。
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
            print("   ⚠️ 淘汰里程碑（总量超 %.0f GB，抽稀掉这个时间点）：%s"
                  % (MAX_BACKUP_BYTES / 1024 ** 3, p.name))

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

    ⚠️ 2026-08-01 重构后一度仍用 `DB.with_name(...)`，于是备份被写进了 `data/db/`，
       和成品库混在一起 —— 目录分工形同虚设。改用 paths.BACKUPS。
    """
    paths.BACKUPS.mkdir(parents=True, exist_ok=True)
    dst = paths.BACKUPS / ("%s.pre-%s-%s.bak" % (DB.stem, tag, time.strftime("%Y%m%d-%H%M%S")))
    shutil.copy2(DB, dst)
    # 🔴 淘汰放在**复制之后**：万一复制失败就抛异常了，不会先把旧的删掉再发现新的没建成。
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
    """会话句柄。只暴露写库入口，强制所有写操作被计数。"""

    def __init__(self, conn):
        self.conn = conn
        self.written = 0

    def executemany(self, sql, seq):
        seq = list(seq)
        self.conn.executemany(sql, seq)
        self.written += len(seq)
        return len(seq)

    def addcolumn(self, name, decl="TEXT"):
        """幂等加列。加列本身不改任何行，不计入 written。"""
        if name in _cols(self.conn):
            return False
        self.conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (TABLE, name, decl))
        return True

    def execute(self, sql, args=()):
        return self.conn.execute(sql, args)


@contextmanager
def session(tag, expect=None, dry=False, verbose=True):
    """写库闸门。

    expect: {列名: 期望的非空计数变化}；表用 `"#表名"`。
        · 显式写出的列：变化必须**恰好等于**期望值；写 None 表示"允许变但不校验数值"。
        · **没写出的列 / 表：变化必须为 0。**
        · 总行数 `__rows__` 默认必须为 0；要插行就得**显式**写出期望的增量，
          写不对就报错退出。
          🔴 es 2026-08-03 才放开这一条：此前所有写库都是原地更新，闸门直接写死
          "行数不许变"。收词要插 36.9 万行 —— 但**不能因此把这道闸拆掉**，
          只能从"永远 0"改成"必须显式声明具体数字"。插行时所有列的非空计数都会
          跟着涨，所以那一批列也必须逐个写进 expect，闸门才拦得住"多写了一列"。
          ⚠️ fr 的阶段 3 收词是本项目至今最大的一次插行（法文版有 203 万个法语词形，
             我们现在只有 38.5 万），这条尤其要认真写。
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
            yield _S(conn)
        finally:
            conn.close()
        return

    bak = backup(tag)
    if verbose:
        print("■ 已备份 → " + bak.name)
    conn = sqlite3.connect(DB)
    s = _S(conn)
    try:
        yield s
        conn.commit()
    except BaseException:
        conn.rollback()
        conn.close()
        # 🔴 2026-08-22：**rollback 成功 ⇒ 这份备份是冗余的，当场删掉。**
        #    事务回滚后库就是备份拍下的那个状态，留着它只是噪声 —— 而噪声会挤掉里程碑：
        #    当天 `keep-v3-apos` 那个 7 行的小改动失败重试三次，留下 4 份内容几乎相同的备份，
        #    把 `keep-v3-schema` 和 `keep-v3-entry` 两个**不可再生的迁移锚点**挤出了条数上限。
        #    ⚠️ 只删「异常回滚」这一路。**闸核对未通过那一路不能删** ——
        #       那时数据已经在库里，备份是唯一的回滚点。
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
                bad.append("{} 行数变化 {:+,}，期望 {:+,}".format(t, got, want))
        elif got:
            bad.append("🔴 未声明的表 {} 行数变了 {:+,} —— 动到了不该动的表".format(t, got))
    if verbose:
        print("■ 写入 {:,} 条".format(s.written))
        print("■ 写库后不变量：" + _line(after, d))
    if bad:
        # 🔴 2026-08-17：核对失败的红字原来只走 stderr，我两次用 grep 过滤输出
        #    就把它滤掉了，只看到「已收 N 条」就往下走 —— 数据已经 commit 了却不知道。
        #    ⇒ 同时打到 stdout，并在**最后一行**再重复一次结论，让它难被漏读。
        for out in (sys.stderr, sys.stdout):
            print("\n🔴 不变量核对未通过：", file=out)
            for b in bad:
                print("   " + b, file=out)
            print("   回滚：cp '%s' '%s'" % (bak, DB), file=out)
            print("🔴🔴🔴 本次写库未通过，**数据已在库中**，要么按上面的命令回滚，"
                  "要么确认这些变化是预期的并补进 expect。", file=out)
        raise SystemExit(1)
    if verbose:
        print("■ 不变量核对通过 ✓")
    _regression_check(verbose)


def _regression_check(verbose=True):
    """写库之后跑一遍回归闸。

    ═══ 为什么这道闸必须在这里，而不是"记得跑一下" ═══
    用户 2026-08-11：「同一个问题你修了，隔天修其他问题，你又发现之前的问题又出现了。」
    根因是修复写在**输出层**，而输出层会被 DROP 重建 —— es 上已知三次，
    三次全是**事后偶然撞见**的，间隔一周到十天。上面两道不变量闸拦不住它们：
    行数没变、列的非空计数没变，**变的是内容对不对**。
    ⇒ 这里必须跑一遍「过去每个修复现在还在不在」，让回归在**产生它的那次写库**上报出来。

    ⚠️ 它**只报不拦**。理由：写库已经 commit 了（回归闸要读最终状态才准），
       而且不是每次红都该回滚 —— 有些是这次写库有意为之。报出来 + 备份路径就够决策了。
    不想跑：`SKIP_REGRESSION_CHECK=1`。

    ✅ fr 的回归闸已于 2026-08-26（阶段 7）建好，从此每次写库都会跑。
    **文件不存在 = 静默跳过；文件在但跑不起来 = 必须喊** —— 后者是闸自己坏了。

    ⚠️ 闸里的 **L 组是故意红的**（App 还在读老扁平列，v3 那套表一张没接）。
       阶段 8 切完读取路径才该变绿 —— **别为了让写库输出好看去调它的基线。**
    """
    if os.environ.get("SKIP_REGRESSION_CHECK") == "1":
        return
    if not (HERE / "tests" / "test_no_regression.py").exists():
        return                                   # 阶段 7 之前：这道闸还没建，不是坏了
    try:
        sys.path.insert(0, str(HERE))
        from tests.test_no_regression import check_brief
        red = check_brief()
    except Exception as e:                      # 闸自己坏了不能挡住写库，但必须喊出来
        print("\n⚠️ 回归闸没跑起来（%s）—— 这本身要查" % e, file=sys.stderr)
        return
    if not red:
        if verbose:
            print("■ 回归闸通过 ✓（过去的修复都还在）")
    else:
        print("\n🔴 回归闸报警：有 %d 条过去的修复现在失效了" % len(red), file=sys.stderr)
        for cid, name, why in red:
            print("   %-5s %-38s %s" % (cid, name, why), file=sys.stderr)
        print("   明细：python3 tests/test_no_regression.py", file=sys.stderr)
    _ledger_gate(verbose)


def _ledger_gate(verbose=True):
    """**账的闸** —— 计划表和收尾单说的话，与库里的事实对不对得上。

    🔴 起因：用户 2026-08-27「你自己定的规矩，自己的经验教训，你自己为什么不执行呢」。
       查会话自己的记录，形状很干净：**做成机制的全守住了，写成文字的一条没守住**
       （`think=False` 硬默认 / `DOUBAO_DISABLED` / 本文件的 `expect` 闸 都守住了；
       `[[ship-dont-measure-in-circles]]` 这类 prose 一条没守住）。
       ⇒ 不再往记忆里写"要记得 X"，写会自己响的东西。

    它逮的是**账**不是数据：阶段表标着 ✅ 而交付物是 0（阶段 5 的关系层/频次层
    就是这么漏了七天的）、收尾单不存在或记账又散开。
    与回归闸同样**只报不拦**。
    """
    p = HERE / "tests" / "test_plan_ledger.py"
    if not p.exists():
        return
    try:
        from tests.test_plan_ledger import check_brief as _lb
        red = _lb()
    except Exception as e:
        print("\n⚠️ 账的闸没跑起来（%s）—— 这本身要查" % e, file=sys.stderr)
        return
    if not red:
        if verbose:
            print("■ 账的闸通过 ✓（计划表与收尾单和库对得上）")
        return
    print("\n🔴 账的闸报警：%d 条" % len(red), file=sys.stderr)
    for cid, why in red:
        print("   %-4s %s" % (cid, why), file=sys.stderr)
    print("   明细：python3 tests/test_plan_ledger.py", file=sys.stderr)


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
    print("%s  表 %s" % (DB.name, TABLE))
    print("  总行 {:,}".format(s["__rows__"]))
    for c in TRACK:
        if c not in s:
            print("  {:16}{:>12}".format(c, "(列不存在)"))
            continue
        print("  {:16}{:>12,}  {:>6.2f}%".format(c, s[c], 100 * s[c] / max(s["__rows__"], 1)))
    print("\n出版层各表行数")
    for t in TRACK_TABLES:
        k = "#" + t
        print("  {:20}{:>12}".format(t, "{:,}".format(s[k]) if k in s else "(表不存在)"))
