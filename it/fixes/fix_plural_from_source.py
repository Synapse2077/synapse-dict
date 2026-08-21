#!/usr/bin/env python3
"""`dict.plural` 回源重算：修掉编造的复数形。2026-08-19（阶段 8 记账项）。

═══ 根因不是数据脏，是解析器不认识 `<…>` 里的逗号 ═══
`build.py` 的 `PLURAL_ARG_RE` 用 `finditer` 在整串上扫，而 it-noun 的参数里
`<g:f>` `<l:…>` `<ref:…>` 这些修饰块**自己带逗号、而且能嵌套**：

    paro   "para<g:f><l:archaic,&,rare><ref:… Treccani on line, Istituto …<<name:trec>>>"
           按逗号裸切 → 'l:archaic' '&' 'line' 'name:trec>>>'
                                     ↑「Vocabolario Treccani on line, Istituto…」里的一个词
           而**真复数 para 被整条丢掉**

一个缺陷两种后果：**编造出不存在的复数**（页面上写着「复数 line」）+ **丢掉真复数**。

⇒ 正确的解析在 `probes/plural_audit.parse_plural_arg`：
   ① 深度 0 的 `|` 处截断（后面是 `dim=` 这类别的具名参数，`mangiare` 会被它带偏）
   ② 只在**深度 0** 的逗号处切段
   ③ 每段取第一个 `<` 之前那截当词形，`<g:x>` 单独读

═══ 判据与口径 ═══
· 真值 = 英文版 dump（`probes/plural_audit.py` 的重建结果，全量非抽样）
· **只改「库里的值不在源头任何复数形里」那批**；源头没收的词形一律不动
  （636 行来自 it 版或七月流水线，本脚本证明不了它们错，不碰）
· 选哪一个进单列：**性别与词头不同的优先**（异性复数是 `plural_gender` 的用途），
  否则取 head_template 里的第一个 —— 与 `build.extract_plural` 同一套顺序

⚠️ **改完仍有 2 条是错的，但错在源头**（改前逐条回源看过）：
   `campo minato → campati minati`（正确应为 campi minati）、
   `tocco finale → tocci finali`（应为 tocchi finali）—— 英文版原文就这么写。
   我们只负责忠实抽取；即便如此改过去仍然更好：源头的错值至少是个完整复数，
   而改之前我们存的 `minati` / `finali` **连词组都不是**。

用法（在 it/ 目录下）：
    python3 fixes/fix_plural_from_source.py            # 干跑，列出全部改动
    python3 fixes/fix_plural_from_source.py --apply
    python3 fixes/fix_plural_from_source.py --verify
    python3 fixes/fix_plural_from_source.py --mutate
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "probes"))

import dbtool                                     # noqa: E402
import paths                                      # noqa: E402
from plural_audit import parse_plural_arg, source_map   # noqa: E402

f = lambda n: format(n, ",")


def pick(forms, gender):
    """从源头给的复数形里挑一个进单列 → (复数形, 异性复数的性别 or None)。

    顺序与 `build.extract_plural` 一致：性别与词头不同的优先（那正是 `plural_gender`
    要表达的东西），否则第一个。**不发明**：源头没给性别就留 None。
    """
    for form, g in forms:
        if g and gender and g != gender:
            return form, g
    return forms[0][0], None


def plan(con, src):
    """→ [(词形, 旧值, 新值, 旧性别, 新性别)]，只含「旧值不在源头任何复数形里」的。"""
    out = []
    for w, pl, pg, gender in con.execute(
            "SELECT word, plural, plural_gender, gender FROM dict "
            "WHERE plural IS NOT NULL AND plural<>''"):
        forms = src.get(w)
        if not forms:
            continue                       # 源头没收 ⇒ 证明不了它错，不动
        if pl in {x[0] for x in forms}:
            continue                       # 一致
        new, newg = pick(forms, gender)
        out.append((w, pl, new, pg, newg))
    return out


def gate(con, src=None):
    print("\n═══ 闸 ═══")
    src = src or source_map()
    left = plan(con, src)
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("🔴 复数值不在源头任何复数形里的", len(left), 0),
        # ⚠️ **这里曾经有一条「复数不许与词头相同」的断言，是错的，已删。**
        #    实测 616 行 `plural == word`，逐条看全是**单复同形**（`gas` `samurai`
        #    `tram` `età` `martedì` `oasi`），其中 527 行还带着 `number_note='invariable'`
        #    —— 那正是正确数据。写这条断言时我把"看着可疑"当成了判据（A33 的第三种：
        #    尺子错，不是数据错）。留着这段话，是因为下一个人很可能想加同一条。
        # 🔴 `plural_gender` 的语义就是「异性复数」——与词头性别相同就不是异性复数，
        #    而展示层会照着它渲染出一个并不存在的性别变化徽标。实测 3 行
        #    （`vietnamita`/`indio`/`corista`，都是 -ista/-io 这类 m/f 通用名词）。
        ("🔴 plural_gender 与词头性别相同（那就不是异性复数）",
         q("SELECT count(*) FROM dict WHERE plural_gender IS NOT NULL "
           "AND plural_gender=gender"), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-42s %s (期望 %s)" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    return ok


def mutate():
    """判据变异：解析器本体。**这才是缺陷的所在地**，不是数据。"""
    print("═══ 变异验证：解析器判据 ═══")
    cases = [
        ("🔴 修饰块里的逗号不许切（paro）",
         parse_plural_arg("para<g:f><l:archaic,&,rare><ref:paro in Treccani.it "
                          "– Vocabolario Treccani on line, Istituto<<name:trec>>>"),
         [("para", "f")]),
        ("🔴 嵌套 <<…>> 也不许切",
         parse_plural_arg("+,rosarii<l:Latinism,and,rare><ref:<<name:dop>>>"),
         [("rosarii", None)]),
        ("🔴 深度 0 的 | 之后是别的参数（mangiare 的 dim=）",
         parse_plural_arg("~,#,+<l:chiefly><ref:x>|dim=mangiarino<q:colloquial>,"
                          "mangiaretto<q:rare>"), []),
        ("双复数两个都要拿到", parse_plural_arg("braccia<g:f>,bracci<g:m>"),
         [("braccia", "f"), ("bracci", "m")]),
        ("占位符不算复数", parse_plural_arg("+"), []),
        ("单个带性别的", parse_plural_arg("mura<g:f>"), [("mura", "f")]),
        # 🔴 挑值的顺序：异性复数优先
        ("🔴 挑值时异性复数优先", pick([("bracci", "m"), ("braccia", "f")], "m"),
         ("braccia", "f")),
        ("没有异性复数就取第一个", pick([("pari", None), ("para", "f")], None),
         ("pari", None)),
    ]
    ok = True
    for name, got, want in cases:
        good = got == want
        ok &= good
        print("   %s %-40s → %s" % ("✅" if good else "🔴", name, got))
    print("\n   变异验证 %s" % ("通过" if ok else "🔴 判据有问题"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify", "mutate", "all"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1
    print("■ 扫英文版 dump 重建复数真值…", flush=True)
    src = source_map()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro, src) else 1
    rows = plan(ro, src)
    ro.close()
    print("■ 要改 %s 行" % f(len(rows)))
    print("   %-22s %-16s %-16s" % ("词形", "旧（编造的）", "新（源头）"))
    for w, old, new, pg, newg in (rows if a.all else rows[:25]):
        print("   %-22s %-16s %-16s %s" % (w[:22], old[:16], new[:16],
                                           ("异性复数 %s" % newg) if newg else ""))
    if not a.all and len(rows) > 25:
        print("   …（--all 看全部 %s 行）" % f(len(rows)))
    if not a.apply or not rows:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("fix-plural-from-source",
                        expect={"__rows__": 0, "plural": 0}) as s:
        s.executemany("UPDATE dict SET plural=?, plural_gender=? WHERE word=?",
                      [(new, newg, w) for w, _o, new, _pg, newg in rows])
        # 顺带清掉「plural_gender == gender」那 3 行：语义是异性复数，相同就该是 NULL
        n = s.execute("UPDATE dict SET plural_gender=NULL "
                      "WHERE plural_gender IS NOT NULL AND plural_gender=gender").rowcount
        print("   顺带清掉 plural_gender==gender 的 %s 行" % f(n))
        s.written = len(rows) + n
    print("\n■ 已改 %s 行" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
