#!/usr/bin/env python3
"""意大利语写库闸门 —— 备份 / 保留策略 / 不变量核对 / 抽样反验。it 专用，不 import 其他语种。

═══ 为什么有这个文件（2026-08-01 立，2026-08-12 按 es 一个月的教训重做）═══
实查：123 个脚本里 **31 个会写库**，每个都自己写了一遍 `shutil.copy2` 备份，
但**只有 4 个做写后不变量核对** —— 等于 27 次写库是没有验收的。
→ 从此写库必须走同一道闸：**备份 → 写 → 不变量核对 → 抽样反验**，缺一不可。

⚠️ `PLAYBOOK` 1.4：「不能推后。es 是先修了一周数据才有闸门的，那一周的写库全部无法追溯。」
   it 的结构重构（阶段 0 起）一次写库动几十万行，闸门必须在**第一次写库之前**就位。

═══ 🔴 最关键的一条：未声明的列必须零变化 ═══
`expect` 里没写的列，写库前后非空计数**必须完全相同**，否则报错退出。
这是唯一能自动发现"我以为只动了 A，其实把 B 也改了"的机制 —— 靠人眼看 UPDATE 语句发现不了。

用法：
    import dbtool

    plan = [(new_val, rid), ...]
    with dbtool.session("ipa-fill", expect={"ipa": +196368}) as s:
        s.executemany("UPDATE dict SET ipa=? WHERE id=?", plan)
    # 退出时自动核对；不符即抛错并打印回滚命令（已备份，可直接 cp 回去）

    with dbtool.session("试跑", dry=True) as s:   # 只看快照，不备份不写

    # 结构大改之前用 keep 前缀，该备份永不被保留策略淘汰：
    with dbtool.session("keep-v2-schema", expect={...}) as s: ...

只读快照：
    python3 dbtool.py
自检（变异验证，不碰真库）：
    python3 tests/verify_gate.py
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
# 追踪的列：写库前后都会计数。**不在这张表里的列，出了问题不会被发现** —— 新增重要字段记得加进来。
#
# 🔴 2026-08-12 重列。旧版只追 6 列，`definition` / `meta` / 三个 `_src` 全在外面 ——
#    而阶段 0/1 要做的恰恰是把 `definition` 拆成义项层，闸门当时是瞎的。
#    判据：**凡是承载值的列全部进来**，只有 id / word / word_norm / is_lemma 这四个
#    身份列不进（它们 NOT NULL，非空计数恒等于总行数，计了也是常数）。
#    2026-08-12 阶段 0 之后：`definition`/`translation`/`translation_src`/`meta`/
#    `collocation`/`example`/`flag` 七列已迁出并删除，内容改由下面的 TRACK_TABLES 守。
TRACK = ['ipa', 'ipa_src', 'pos', 'freq_zipf',
         'aux', 'conj', 'transitivity', 'pronominal',
         'gender', 'gender_src', 'plural', 'plural_gender', 'number_note',
         'infl', 'exchange', 'level']

# 🔴 v2 之后数据的主体不在 `dict` 上了 —— 只盯着 `dict` 的闸门是**瞎的**。
#    [[fix-regression-and-gate]]：es 的整轮音标修复就是被"换了读取路径"绕过的，
#    查原列永远绿、用户看到的是错的。所以出版层这十一张表的行数一并进快照：
#    **没在 expect 里显式声明的表，行数必须零变化**，删表 / 重建 / 少插一批都会当场报错。
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
    反过来阶段 0 要**删列**（30→21），被删的列只在 before 里有，同理。"""
    keys = set(before) | set(after)
    return {k: after.get(k, 0) - before.get(k, 0) for k in keys
            if after.get(k, 0) != before.get(k, 0)}


#  ── 保留策略（2026-08-11 在 es 上立，it 开工即带）─────────────────────────
#  es 上每次写库前全量复制 697 MB，十天攒了 118 个备份、**56 GB**，
#  其中大量是同一天同一个 tag 隔一两分钟的重复。当天清掉 120 个、释放 50.9 GB。
#  不加策略的话两周后原样复发 —— 清理是一次性的，产生速度不是。
#
#  🔴 里程碑用文件名豁免，不靠"记得手动留"：
#     tag 里带 `keep` 的（`dbtool.session("keep-v2-schema")`）永不淘汰。
#     结构大改之前请用这个前缀 —— 那种备份删了就真回不去了。
KEEP_TAG = "keep"
MAX_BACKUPS = 12          # 同一语种保留的非豁免备份数上限


def prune_backups(verbose=True, dry=False):
    """同一 tag 同一天只留最新的一个；再按时间保留最近 MAX_BACKUPS 个。带 keep 的豁免。

    `dry=True` 只列不删 —— **改这个函数之后先 dry 跑一遍**。
    它是本仓库里唯一一个会自动删数据的地方，写错了没有第二次机会。
    """
    pat = re.compile(r"^%s\.pre-(.+)-(\d{8})-(\d{4,6})\.bak$" % re.escape(DB.stem))
    rows = []
    for p in paths.BACKUPS.glob("%s.pre-*.bak" % DB.stem):
        m = pat.match(p.name)
        if m:
            rows.append((p, m.group(1), m.group(2)))
    keep, drop = set(), []
    # ① 同 (tag, 日期) 只留最新
    newest = {}
    for p, tag, day in rows:
        if KEEP_TAG in tag:
            keep.add(p)
            continue
        k = (tag, day)
        if k not in newest or p.stat().st_mtime > newest[k].stat().st_mtime:
            if k in newest:
                drop.append(newest[k])
            newest[k] = p
        else:
            drop.append(p)
    # ② 剩下的按时间取最近 MAX_BACKUPS 个
    rest = sorted(newest.values(), key=lambda p: -p.stat().st_mtime)
    keep |= set(rest[:MAX_BACKUPS])
    drop += rest[MAX_BACKUPS:]

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

    expect: {列名: 期望的非空计数变化}
        · 显式写出的列：变化必须**恰好等于**期望值；写 None 表示"允许变但不校验数值"。
        · **没写出的列：变化必须为 0。**
        · 总行数 `__rows__` 默认必须为 0；要插行就得**显式**写出期望的增量，
          写不对就报错退出。
          🔴 es 2026-08-03 才放开这一条：此前所有写库都是原地更新，闸门直接写死
          "行数不许变"。收词要插 36.9 万行 —— 但**不能因此把这道闸拆掉**，
          只能从"永远 0"改成"必须显式声明具体数字"。插行时所有列的非空计数都会
          跟着涨，所以那一批列也必须逐个写进 expect，闸门才拦得住"多写了一列"。
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
        #    （不改成自动回滚：快照必须读已提交状态才准，这是设计取舍；
        #      但"报了而没人看见"是纯粹的可用性问题，能改。）
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
    根因是修复写在**输出层**，而输出层会被 DROP 重建 —— es 上已知三次：
      · `split_case_homographs` 的 4,501 条归属被 `build_sense_layer` 重建抹掉；
      · `example_gloss` 的 50,289 条译文被 `build_example_layer` 删光；
      · 7-31~8-03 整轮音标修复被 8-07 新建的 `pronunciation` 表**绕过**
        （数据还在 `dict.phonetic`，但展示层改读新表了）。
    三次全是**事后偶然撞见**的，间隔一周到十天。上面那两道不变量闸拦不住它们：
    行数没变、列的非空计数没变，**变的是内容对不对**。
    ⇒ 这里必须跑一遍「过去每个修复现在还在不在」，让回归在**产生它的那次写库**上报出来。

    ⚠️ 它**只报不拦**。理由：写库已经 commit 了（回归闸要读最终状态才准），
       而且不是每次红都该回滚 —— 有些是这次写库有意为之。报出来 + 备份路径就够决策了。
    不想跑：`SKIP_REGRESSION_CHECK=1`。

    it 的回归闸文件在阶段 7 才建（现在还没有任何"过去的修复"要守）。
    **文件不存在 = 静默跳过；文件在但跑不起来 = 必须喊** —— 后者是闸自己坏了。
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
        return
    print("\n🔴 回归闸报警：有 %d 条过去的修复现在失效了" % len(red), file=sys.stderr)
    for cid, name, why in red:
        print("   %-5s %-38s %s" % (cid, name, why), file=sys.stderr)
    print("   明细：python3 tests/test_no_regression.py", file=sys.stderr)


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
