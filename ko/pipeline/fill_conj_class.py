#!/usr/bin/env python3
"""阶段 2b：补 `entry.conj_table_tag` / `entry.stem_class` —— 源头活用表的原始标签。2026-09-21。

═══ 🔴🔴 这一步是**翻案**：阶段 0 的决定⑤写错了 ═══
`build_v3_schema.py` 文件头⑤当时写：

> **不建 `entry.vclass`**（活用类）
>   量出来多少：**英文版 0 条**（5,351 个用言条目，一条标记都没有）

**那个 0 是假的 —— 我的判据查错了字段。**
我查的是 `forms[].tags` 里有没有 `irregular` 这个**标签名**，
而源头是：**标签名叫 `table-tags`，`irregular` 是它的「值」**：

    {"form": "irregular",      "tags": ["table-tags"]}
    {"form": "consonant-stem", "tags": ["class"]}
    {"form": "ko-conj/verb",   "tags": ["inflection-template"]}

实测英文版给了 **9,379 条**这样的元数据，覆盖用言条目的 **88.7%**：

    table-tags   irregular 5,635 ／ no-table-tags 3,744
    class        vowel-stem 7,761 ／ consonant-stem 1,610

对照我当时引用的"韩文版只有 452 条（4.3%）"—— **英文版这份好 20 倍**，
而我用一条查错字段的判据把它整个判成了 0。
⚠️ 与同一周的另外两次是同一个病：`§4.3` 量错了对象（汉字音不在 `한자` 切片里）、
   元描述 gloss 的 `startswith` 只逮到 6%。
   **三次都不是"数错了"，是"问错了地方"** —— 而三次都是**抽样/回源**逮到的，
   没有一次是闸逮到的。

═══ 判据验过了（拿语法书当外部标尺，不是自证）═══
取 10 个韩语教学上已知规则/不规则的用言，对源头的 `table-tags`：

    먹다(规则) → no-table-tags      듣다(ㄷ불규칙) → irregular
    좋다(规则) → no-table-tags      돕다(ㅂ불규칙) → irregular
                                    짓다(ㅅ불규칙) → irregular
                                    하다(여불규칙) → irregular
                                    빨갛다(ㅎ불규칙) → irregular
                                    모르다(르불규칙) → irregular
                                    살다(ㄹ탈락)   → irregular
    ⚠️ 가다 → irregular，而多数语法书把它算规则（它的命令形 `가거라` 是 거라 불규칙）
       —— **边界情况，不是错**，但它正好说明下面这条：

🔴 **存源头原值，不改写成 `regular`/`irregular` 的布尔。**
   `no-table-tags` 的字面意思是「这张表没有标签」，把它读成「规则」是**我的推断**；
   而 `가다` 说明源头的标准与语法书本来就不完全重合。
   ⇒ 值一律用源头原词（`SCHEMA` §10.4.1 推翻①的同一条规矩），
     怎么说给读者听是展示层的事（`[[dict-labels-package]]`）。

🔴 **不存 `inflection-template`**（`ko-conj/verb` / `ko-conj/adj`）：
   它与 `pos` 是同一个信息的两种写法（verb↔/verb、adj↔/adj），
   落列就是同一个事实存两份（`[[refactor-mindset-code-quality]]`）。

跑（在仓库根）：
    python3 -u ko/pipeline/fill_conj_class.py
    python3 -u ko/pipeline/fill_conj_class.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import json
import sqlite3

import dbtool
import paths

# 源头的标签名 → 我们的列名。**值不映射**，原样存。
# 🔴 2026-09-24 改名：这一列存的是源头的 `table-tags`（值域 irregular/no-table-tags），
#    **那不是活用类** —— 五种不同的不规则共用一个 `irregular`。
#    ⇒ 它现在叫 `conj_table_tag`（它是什么叫什么），真正的活用类由
#      `derive_conj_class.py` 算出来落进 `conj_class`（见 `conj_class.py`）。
#    ⚠️ **本脚本不许再写 `conj_class`** —— 一个字段一个写入方。
META = {"table-tags": "conj_table_tag", "class": "stem_class"}


def scan(inentry):
    seen = collections.Counter()
    out = {}                                   # entry_id → {列: 值}
    stat = collections.Counter()
    conflict = []
    for line in open(paths.KK, encoding="utf-8"):
        o = json.loads(line)
        praw = o.get("pos")
        if praw == "romanization":
            continue
        w = o.get("word")
        if not w or not w.strip():
            continue
        en_ = o.get("etymology_number")
        etym = str(en_) if en_ is not None else "0"
        k = (w, praw, etym)
        seq = seen[k]
        seen[k] += 1
        eid = inentry.get("kk-ko:%s:%s:%s:%d" % (w, praw, etym, seq))
        if eid is None:
            continue
        for f in (o.get("forms") or []):
            tags = f.get("tags") or []
            for src_tag, col in META.items():
                if src_tag not in tags:
                    continue
                v = (f.get("form") or "").strip()
                if not v:
                    continue
                cur = out.setdefault(eid, {})
                if col in cur and cur[col] != v:
                    # 🔴🔴 同一个 entry 两个不同值 —— 实测 4 条（`가깝다` `고맙다`），
                    #    原因是源头**并排放了两套活用表**：
                    #        旧模板 `ko-conj-adj`  → table-tags=`no-table-tags`，无 `class`
                    #        新模板 `ko-conj/adj`  → table-tags=`irregular` ＋ class=`consonant-stem`
                    #    两个词都是 ㅂ 불규칙，实际变形形 `가까워`/`고마워`（不是 가까와）
                    #    **证明 `irregular` 才是对的**。
                    #
                    # 判据：`no-table-tags` 的字面意思是「这张表没有标签」＝**信息缺失**，
                    #      `irregular` 是**信息存在** ⇒ 冲突时信息存在的胜出。
                    # 🔴 **不靠 forms 里的前后顺序去配对模板** —— 那正是 ja 的
                    #    `infl_table` 栽过的地方（扁平遍历看不见表，行列表头识别失败，
                    #    六个症状、108 个词无一幸免）。顺序是形式，"哪个有信息"是内容。
                    if {cur[col], v} == {"no-table-tags", "irregular"}:
                        cur[col] = "irregular"
                        stat["两套表并排 ⇒ 取 irregular（弃 no-table-tags）"] += 1
                        continue
                    # 别的组合没见过 ⇒ 报出来，**不许静默挑一个**
                    conflict.append((w, praw, col, cur[col], v))
                    stat["🔴 没见过的多值组合"] += 1
                    continue
                cur[col] = v
                stat["%s=%s" % (col, v)] += 1
    return out, stat, conflict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    cols = {r[1] for r in con.execute("PRAGMA table_info(entry)")}
    inentry = {r[1]: r[0] for r in con.execute("SELECT id, src_ref FROM entry")}
    con.close()
    need = [c for c in ("conj_table_tag", "stem_class") if c not in cols]
    print("■ entry 缺的列：%s" % (need or "（都已存在）"))

    out, stat, conflict = scan(inentry)
    for k, v in stat.most_common():
        print("   %-34s %9s" % (k, format(v, ",")))
    print("   %-34s %9s" % ("要写的 entry 数", format(len(out), ",")))
    if conflict:
        print("\n🔴 **没见过的多值组合** %d 条 —— 判据够不着，先看清再写代码："
              % len(conflict))
        for c in conflict[:6]:
            print("     %s" % (c,))
        raise SystemExit("🔴 出现了判据没覆盖的多值组合，停在这儿")

    # 两列的共现：只有一个值的 entry 说明源头本身不全，要能说出来
    both = sum(1 for v in out.values() if len(v) == 2)
    print("   %-34s %9s" % ("两列都有的 entry", format(both, ",")))
    print("   %-34s %9s" % ("只有一列的 entry", format(len(out) - both, ",")))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    rows_conj = [(v["conj_table_tag"], eid) for eid, v in out.items()
                 if "conj_table_tag" in v]
    rows_stem = [(v["stem_class"], eid) for eid, v in out.items() if "stem_class" in v]

    with dbtool.session("fill-ko-conj-class",
                        expect={"entry.conj_table_tag": len(rows_conj),
                                "entry.stem_class": len(rows_stem)},
                        invalidates=[]) as s:
        for c in need:
            s.execute("ALTER TABLE entry ADD COLUMN %s TEXT" % c)
        s.executemany("UPDATE entry SET conj_table_tag=? WHERE id=?", rows_conj)
        s.executemany("UPDATE entry SET stem_class=? WHERE id=?", rows_stem)

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    dom_c = [r[0] for r in con.execute(
        "SELECT DISTINCT conj_table_tag FROM entry WHERE conj_table_tag IS NOT NULL")]
    dom_s = [r[0] for r in con.execute(
        "SELECT DISTINCT stem_class FROM entry WHERE stem_class IS NOT NULL")]
    checks = [
        ("conj_table_tag 非空",
         q("SELECT COUNT(*) FROM entry WHERE conj_table_tag IS NOT NULL"),
         len(rows_conj)),
        ("stem_class 非空", q("SELECT COUNT(*) FROM entry WHERE stem_class IS NOT NULL"),
         len(rows_stem)),
        # 🔴 **闸自证**：值域必须就是源头那几个词。多出别的值 = 解析跑偏了
        ("conj_table_tag 值域", sorted(dom_c), sorted(["irregular", "no-table-tags"])),
        ("stem_class 值域", sorted(dom_s), sorted(["vowel-stem", "consonant-stem"])),
        # 这两列只该出现在用言上（源头 99.7% 落在 verb/adj）
        ("非用言带 conj_table_tag 的比例 <1%",
         q("SELECT COUNT(*) FROM entry WHERE conj_table_tag IS NOT NULL "
           "AND pos_raw NOT IN ('verb','adj')") * 100 // max(len(rows_conj), 1), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        gs = got if isinstance(got, list) else format(got, ",")
        ws = want if isinstance(want, list) else format(want, ",")
        print("   %s %-30s %s（期望 %s）" % ("✅" if good else "🔴", name, gs, ws))
    # 抽样：拿已知的规则/不规则动词回核
    print("\n■ 拿语法书已知的用言回核（外部标尺，不是自证）：")
    for w in ("먹다", "좋다", "듣다", "돕다", "하다", "모르다", "가다"):
        r = con.execute(
            "SELECT e.conj_table_tag, e.stem_class FROM entry e JOIN dict d ON d.id=e.word_id "
            "WHERE d.word=? AND e.pos_raw IN ('verb','adj') LIMIT 1", (w,)).fetchone()
        print("     %-6s %s" % (w, r or "—"))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
