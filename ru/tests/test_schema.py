#!/usr/bin/env python3
"""**结构闸** —— ru 阶段 0 的交付物。2026-10-07。

它查的不是数据，是**结构本身**：声明要建的对象在不在、后补的列在不在、
**有意不建的有没有偷偷出现**、两条值域/唯一性断言成不成立。

═══ 🔴 为什么结构也需要一道闸 ═══
`CREATE TABLE IF NOT EXISTS` 对已存在的表是**空操作** ——
改了 `build_v3_schema.py` 的建表语句，**老库上一个字都不会变**，
而只数对象名的核对会照样报全绿。那正是 **B7** 的形状（只审计表、不审计列），
`dbtool._track_audit` 为此修过一次，**建表这一侧当时没修**。

═══ 🔴🔴 判据一个都不重写 ═══
五条判据全部 `import build_v3_schema` 取用 —— 本文件**不自己写一版 SQL**。
vi 的 R19/S6 栽过：闸自己手写一版近似判据，**同时更宽又更窄**；
更狠的是 vi 阶段 6「同一个谓词两份实现只修了一份」⇒
**断言和被断言的用同一个坏判据，双方一致报全绿**。

═══ 变异验证：**在库的副本上做，真库一个字节不动** ═══
🔴 `[[prefer-reversible-designs]]`。五条变异逐条打掉一条判据，每条都必须让闸红；
   **而且报的必须是那一条**，不是「别的地方也红了」。
⚠️ 变异要**注入自己的前提**，不许寄托在现状上（`BACKLOG` **B20**：
   48 小时内四次「现状推进后变异静默失效」）。所以 M4/M5 自己插行，
   不依赖库里恰好有数据 —— 现在库是空的，而它们照样逮得到。

用法：
    python3 ru/tests/test_schema.py
    python3 ru/tests/test_schema.py --mutate
"""
import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                                    # noqa: E402
from pipeline import build_v3_schema as schema                  # noqa: E402

# 🔴 **花名册**：本文件该有几条检查，**独立声明，不从代码里数出来**。
#    `[[expectation-must-be-declared]]`：拿现状推期望，现状坏了期望跟着坏。
#    而 vi 的 2026-10-05 实证更直接：我整段替换时把夹在中间的两条检查切走了，
#    **正常跑报「全绿」，只有 `--mutate` 报了出来，因为没有任何东西数过输出该有几条**。
ROSTER = ("S1-对象齐全", "S2-后补列齐全", "S3-有意不建没出现",
          "S4-aspect值域", "S5-stress唯一主行", "S6-建表语句对账")


def checks():
    """→ [(编号, 是否通过, 说明)]。**判据全部来自 `build_v3_schema`，这里只分类。**

    🔴 为什么要「分类」这一步：`schema.check()` 返回一个扁平的字符串列表，
       而花名册要能逐条对账。分类靠**它自己打印的前缀**，不靠行号。
    """
    bad = schema.check(verbose=False)
    buckets = {
        "S1-对象齐全":      [b for b in bad if b.startswith("缺对象")],
        "S2-后补列齐全":    [b for b in bad if b.startswith("缺列")],
        "S3-有意不建没出现": [b for b in bad if "有意不建的" in b],
        "S4-aspect值域":    [b for b in bad if "entry.aspect" in b],
        "S5-stress唯一主行": [b for b in bad if "is_primary" in b],
        # 🔴 S6 是被一次变异的 `IntegrityError` 撞出来的：改了 DDL 的唯一键，
        #    而 `CREATE TABLE IF NOT EXISTS` 对已存在的表是空操作 ⇒ 库里还是旧的，
        #    **而原来的五条判据全绿**（它们只数对象名和列名）。
        "S6-建表语句对账": [b for b in bad if "建表语句与 DDL 不一致" in b],
    }
    rest = [b for b in bad
            if not any(b in v for v in buckets.values())]
    out = [(k, not v, v[0] if v else "") for k, v in buckets.items()]
    # 🔴 **认不出的那些必须单独报**，不许归进任何一桶 ——
    #    残差桶是残差不是度量（`[[residual-bucket-is-not-evidence]]`），
    #    而这里更要紧：认不出就说明 `schema.check()` 加了新判据而花名册没跟上。
    if rest:
        out.append(("S?-花名册漏了的新判据", False,
                    "`schema.check()` 报了 %d 条本文件归不了类的：%s"
                    % (len(rest), rest[0][:70])))
    return out


def roster_check(rows):
    """🔴 **闸自己的闸**：输出的条数与花名册对不对得上。"""
    got = {cid for cid, _, _ in rows}
    bad = []
    for cid in ROSTER:
        if cid not in got:
            bad.append("花名册里的 %s **没有出现在输出里** —— 检查被删掉了？"
                       "（vi 2026-10-05 实证：整段替换切走两条检查，正常跑报全绿）" % cid)
    for cid in sorted(got - set(ROSTER)):
        bad.append("输出里有花名册没登记的 %s —— 加检查要同时动花名册，"
                   "那个手工动作就是这道闸的价值" % cid)
    return bad


def report(rows):
    print("■ 结构闸（ru 阶段 0）")
    for cid, ok, why in rows:
        print("   %s %-22s %s" % ("✅" if ok else "🔴", cid, why))
    rb = roster_check(rows)
    for b in rb:
        print("   🔴🔴 花名册自检：" + b)
    red = [r for r in rows if not r[1]]
    print("■ %s（%d/%d 通过%s）"
          % ("全绿 ✓" if not red and not rb else "有红",
             len(rows) - len(red), len(rows),
             "；花名册 %d 条问题" % len(rb) if rb else "、花名册对得上"))
    return len(red) + len(rb)


# ══════════════════════════════════════════════════════════════════════════
# 变异验证
# ══════════════════════════════════════════════════════════════════════════
def _mutations():
    """每条返回 (编号, 说明, 在副本上执行的 SQL 列表)。

    🔴 **每条变异都自带前提**（B20）：M4/M5 自己插出要被检查的那一行，
       不依赖「库里恰好有数据」。现在库是空的，它们照样逮得到。
    """
    return [
        ("S1-对象齐全", "删掉 `stress` 表", ["DROP TABLE stress"]),
        ("S2-后补列齐全", "删掉派生展示列 `entry.stressed`",
         ["ALTER TABLE entry DROP COLUMN stressed"]),
        ("S3-有意不建没出现", "偷偷建出有意不建的 `pronunciation_entry`",
         ["CREATE TABLE pronunciation_entry (id INTEGER PRIMARY KEY)"]),
        # 🔴🔴 **这两条第一版把 id 写死成 9001/9002，而那是库还空着时写的。**
        #    阶段 1 落库之后 `dict` 有 976,762 行、9001 已被占用 ⇒
        #    `UNIQUE constraint failed: dict.id` **当场炸**，两条变异一条都没跑。
        #    ⭐ 这正是 `BACKLOG` **B20**：**变异把前提寄托在现状上，现状一推进就失效**，
        #      而它**只在事情做对之后才发作**（库真的建起来了才撞上）。
        #      ⚠️ 这次的失败模式是「当场炸」—— B20 的笔记里写着那是**最好的那一种**，
        #      另两种是报「没逮到」，会把人引去修判据，**而判据没坏**。
        #    ⇒ 改用**负数 id**：显然是人造的，`INTEGER PRIMARY KEY` 允许负值，
        #      与「库里现在有多少行」彻底脱钩（B20 要的「变异自带前提」）。
        # 🔴🔴 **而同一条变异在同一天第二次栽在 B20 上。** 修了 id 之后它插的词是
        #    `наследовать` —— **那是个真俄语动词**，阶段 1 落库后它已经在 `dict` 里，
        #    于是 `UNIQUE(word)` 又炸一次。⇒ 词头也要加 `«变异»` 前缀，
        #    **让它在任何真数据里都不可能存在**。
        #    ⭐ 两次的根子是同一句话：**「我造的那一行不会撞」本身就是一个关于现状的假设**，
        #      而现状会变。变异要自带前提 ＝ 连「不会撞」也要自带。
        ("S6-建表语句对账", "把 `dict` 换成一张唯一键不同的同名表（模拟「改了 DDL 没迁移」）",
         ["CREATE TABLE _d2 AS SELECT * FROM dict",
          "DROP TABLE dict",
          "CREATE TABLE dict (id INTEGER PRIMARY KEY, word TEXT NOT NULL, "
          "word_norm TEXT NOT NULL, entry_type TEXT NOT NULL DEFAULT 'word', "
          "is_lemma INTEGER NOT NULL DEFAULT 1, pos TEXT, freq_zipf REAL, "
          "UNIQUE(word, entry_type))",
          "INSERT INTO dict SELECT * FROM _d2",
          "DROP TABLE _d2"]),
        ("S4-aspect值域", "插一行 `aspect='perfect'`（ru 版源头的原词，未归一）",
         ["INSERT INTO dict(id,word,word_norm) VALUES (-9001,'«变异»наследовать','«变异»наследовать')",
          "INSERT INTO entry(id,word_id,pos,aspect,src,src_ref) "
          "VALUES (-9001,-9001,'verb','perfect','ru-edition','mut-s4')"]),
        ("S5-stress唯一主行", "给同一个 entry 插两行 `is_primary=1`",
         ["INSERT INTO dict(id,word,word_norm) VALUES (-9002,'«变异»орган','«变异»орган')",
          "INSERT INTO entry(id,word_id,pos,src,src_ref) "
          "VALUES (-9002,-9002,'noun','en-edition','mut-s5')",
          "INSERT INTO stress(word_id,entry_id,stressed,is_primary,src,src_ref) "
          "VALUES (-9002,-9002,'о́рган',1,'en-canonical','mut-s5a')",
          "INSERT INTO stress(word_id,entry_id,stressed,is_primary,src,src_ref) "
          "VALUES (-9002,-9002,'орга́н',1,'en-canonical','mut-s5b')"]),
    ]


def mutate():
    """逐条变异。**真库不动** —— 复制到临时目录，改 `paths.DB` 指向副本。"""
    if not paths.DB.exists():
        print("🔴 库不存在，变异验证没法做：%s" % paths.DB)
        return 1
    base = report(checks())
    if base:
        print("\n🔴 基线就不绿，先修基线再做变异验证（否则分不清是变异还是旧红）")
        return 1
    print("\n■ 变异验证（%d 条，跑在库的副本上，真库一个字节不动）" % len(_mutations()))
    real = paths.DB
    fails = []
    for cid, why, sqls in _mutations():
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / real.name
            shutil.copy2(real, cp)
            paths.DB = cp
            schema.paths.DB = cp
            try:
                con = sqlite3.connect(cp)
                try:
                    for q in sqls:
                        con.execute(q)
                    con.commit()
                finally:
                    con.close()
                rows = checks()
                got = {c for c, ok, _ in rows if not ok}
                if cid in got:
                    print("   ✅ %-22s %s" % (cid, why))
                elif got:
                    # 🔴 **两种失败要分开印**（vi 的教训：命中了却印「没逮到」，
                    #    以及空操作的变异印「没逮到」—— 看起来一样，成因完全不同）。
                    print("   🔴 %-22s 红了，但红的是 %s，不是它自己 —— %s"
                          % (cid, sorted(got), why))
                    fails.append(cid)
                else:
                    print("   🔴🔴 %-22s **一条都没红** —— 这条判据是假的，或变异是空操作：%s"
                          % (cid, why))
                    fails.append(cid)
            finally:
                paths.DB = real
                schema.paths.DB = real
    # 反控制：还原之后基线必须还是绿的
    if report(checks()):
        print("\n🔴🔴 反控制失败：变异跑完之后真库的基线不绿了 —— **副本隔离破了**")
        return 1
    print("\n%s" % ("■ 变异验证全过 ✓（%d 条），反控制：真库基线仍全绿"
                    % len(_mutations()) if not fails
                    else "🔴 %d 条变异没逮到：%s" % (len(fails), fails)))
    return 1 if fails else 0


def check_brief():
    """给 `dbtool` 用的简表 → [(编号, 说明)]，只含红的。"""
    return [(c, w) for c, ok, w in checks() if not ok]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()
    raise SystemExit(mutate() if a.mutate else (1 if report(checks()) else 0))


if __name__ == "__main__":
    main()
