#!/usr/bin/env python3
"""西班牙语写库闸门 —— 备份 / 不变量核对 / 抽样反验。es 专用，不 import 其他语种。

═══ 为什么有这个文件（2026-08-01 立）═══
实查：123 个脚本里 **31 个会写库**，每个都自己写了一遍 `shutil.copy2` 备份，
但**只有 4 个做写后不变量核对** —— 等于 27 次写库是没有验收的。
而接下来要写的是 de +19.6 万 / pt +17.9 万 / fr +5.8 万 / it 4.8 万，约 **48 万行**，
其正确性完全依赖现写的归一化与取值逻辑 —— 正是 2026-08-01 一天翻了八次车的那类代码。
→ 从此写库必须走同一道闸：**备份 → 写 → 不变量核对 → 抽样反验**，缺一不可。

═══ 🔴 最关键的一条：未声明的列必须零变化 ═══
`expect` 里没写的列，写库前后非空计数**必须完全相同**，否则报错退出。
这是唯一能自动发现"我以为只动了 A，其实把 B 也改了"的机制 —— 靠人眼看 UPDATE 语句发现不了。

用法：
    import dbtool

    plan = [(new_val, rid), ...]
    with dbtool.session("ipa-fill", expect={"phonetic": +196368}) as s:
        s.executemany("UPDATE dict SET phonetic=? WHERE id=?", plan)
    # 退出时自动核对；不符即抛错并打印回滚命令（已备份，可直接 cp 回去）

    with dbtool.session("试跑", dry=True) as s:   # 只看快照，不备份不写

只读快照：
    python3 dbtool.py
"""
import json
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
TRACK = ['phonetic', 'phonetic_raw', 'phonetic_src', 'phonetic_confirm',
         'definition', 'definition_es', 'translation', 'gender', 'pos', 'infl',
         'exchange', 'level', 'meta',
         'freq_zipf', 'freq_lemma_zipf', 'freq_src']


def _cols(conn):
    return {r[1] for r in conn.execute("PRAGMA table_info(%s)" % TABLE)}


def snapshot(conn=None):
    """当前不变量：总行数 + 各追踪列的非空行数。

    TRACK 里还不存在的列跳过 —— 这样"先把列写进 TRACK、再由脚本 ALTER 出来"
    的顺序是安全的（加列前后各取一次快照，列在中途出现，前快照没有它、后快照有）。
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
        return out
    finally:
        if own:
            conn.close()


def diff(before, after):
    """两次快照之差。**必须取两边键的并集** —— 会话中途 ALTER 出来的新列只在
    after 里有，只遍历 before 的话它从 0 涨到 36 万也看不见。"""
    keys = set(before) | set(after)
    return {k: after.get(k, 0) - before.get(k, 0) for k in keys
            if after.get(k, 0) != before.get(k, 0)}


#  ── 保留策略（2026-08-11 加）─────────────────────────────────────────────
#  每次写库前全量复制 697 MB，十天攒了 118 个 es 备份、**56 GB**，
#  其中大量是同一天同一个 tag 隔一两分钟的重复（8-07 光 translate-examples 就 7 个）。
#  当天清掉 120 个、释放 50.9 GB（台账 data/work/_shared/backup_prune_20260811.json）。
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
    for c in TRACK:
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
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(%s)" % TABLE)}
        if name in cols:
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
          🔴 2026-08-03 才放开这一条：此前本项目所有写库都是原地更新，闸门直接
          写死"行数不许变"。西语版收词要插 36.9 万行 —— 但**不能因此把这道闸拆掉**，
          只能从"永远 0"改成"必须显式声明具体数字"。插行时所有列的非空计数都会跟着涨，
          所以那一批列也必须逐个写进 expect，闸门才拦得住"多写了一列"。
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
    if verbose:
        print("■ 写入 {:,} 条".format(s.written))
        print("■ 写库后不变量：" + _line(after, d))
    if bad:
        print("\n🔴 不变量核对未通过：", file=sys.stderr)
        for b in bad:
            print("   " + b, file=sys.stderr)
        print("   回滚：cp '%s' '%s'" % (bak, DB), file=sys.stderr)
        raise SystemExit(1)
    if verbose:
        print("■ 不变量核对通过 ✓")
    _regression_check(verbose)


def _regression_check(verbose=True):
    """写库之后跑一遍回归闸。2026-08-11 加。

    ═══ 为什么这道闸必须在这里，而不是"记得跑一下" ═══
    用户 2026-08-11：「同一个问题你修了，隔天修其他问题，你又发现之前的问题又出现了。」
    根因是修复写在**输出层**，而输出层会被 DROP 重建 —— 已知三次：
      · `split_case_homographs` 的 4,501 条归属被 `build_sense_layer` 重建抹掉；
      · `example_gloss` 的 50,289 条译文被 `build_example_layer` 删光；
      · 7-31~8-03 整轮音标修复被 8-07 新建的 `pronunciation` 表**绕过**
        （数据还在 `dict.phonetic`，但展示层改读新表了）。
    三次全是**事后偶然撞见**的，间隔一周到十天。上面那两道不变量闸拦不住它们：
    行数没变、列的非空计数没变，**变的是内容对不对**。
    ⇒ 这里必须跑一遍「过去每个修复现在还在不在」，让回归在**产生它的那次写库**上报出来。

    ⚠️ 它**只报不拦**。理由：写库已经 commit 了（回归闸要读最终状态才准），
       而且不是每次红都该回滚 —— 有些是这次写库有意为之。报出来 + 备份路径就够决策了。
    不想跑（比如批量小写循环）：`SKIP_REGRESSION_CHECK=1`。约 10 秒。
    """
    if os.environ.get("SKIP_REGRESSION_CHECK") == "1":
        return
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



ALIGN_COLS = ("definition", "definition_es", "translation")


def align_check(verbose=True, limit=8):
    """义项级逐行对齐校验：每个释义列的行数都必须 == meta 数组长度。

    🔴 2026-08-02 立。起因：从中文版补义项要同时动三列，
    **`session()` 的不变量闸门查的是"非空计数"，查不出"行数错位"** ——
    topics 那次就是列对了、义项位置错了，闸门照样放行。
    这个校验补的正是那个盲区：内容级的结构不变量。

    🔴 2026-08-03 改：原来的 WHERE 是 `definition 非空`。西语版收进来的 5.4 万个新
    lemma **`definition` 是空的**（英文版没这个词，释义在 `definition_es` 里），
    照旧写法这批新行会被整批跳过 —— 校验对最需要校验的数据静默失效。
    → 改成**以 meta 为锚**：meta 有几项，每个非空的释义列就必须有几行。
    """
    conn = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    cols = [c for c in ALIGN_COLS if c in _cols(conn)]
    rows = conn.execute(
        "SELECT word, meta, %s FROM %s WHERE is_lemma=1 "
        "AND TRIM(COALESCE(meta,''))<>''" % (",".join(cols), TABLE)).fetchall()
    conn.close()
    bad = []
    for r in rows:
        w, m = r[0], r[1]
        try:
            n_m = len(json.loads(m))
        except Exception:
            bad.append((w, "meta 不是合法 JSON", ""))
            continue
        for c, v in zip(cols, r[2:]):
            if v is None or not v.strip():
                continue
            n = len(v.split("\n"))
            if n != n_m:
                bad.append((w, c, "%d 行 vs meta %d 项" % (n, n_m)))
    if verbose:
        print("■ 义项对齐：检查 {:,} 个 lemma（列 {}），错位 {:,}".format(
            len(rows), "/".join(cols), len(bad)))
        for x in bad[:limit]:
            print("   {:22} {:16} {}".format(*x))
    return bad


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
        if c in s:
            print("  {:16}{:>12,}  {:>6.2f}%".format(
                c, s[c], 100 * s[c] / max(s["__rows__"], 1)))
