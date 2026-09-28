#!/usr/bin/env python3
"""K30-②：关系目标**根本不是词**的那些，藏起来（不删）。ko，2026-09-27。

═══ 先把范围收对 —— 账上把它框小了、也框偏了 ═══
账上记「11,473 条边（占未解析的 31.8%）」。重量之后范围变了两次：

① **未解析池 80,138 条里 43,987 条是 `hanja_spelling`/`alt_hanja`** ——
   那两类的 `target` 按设计就是**注不是词**（`換面相訟` 这种多字汉字串我们没有词头），
   展示层印文本不做链接，**它们不是缺陷**。⇒ 池子是剩下的 36,020 条。
② 那 36,020 里**绝大多数是「我们没有这个词」**（`월름`／`투월`／`乘用車曜日制(승용차 요일제)`）——
   那是 **K21**（已结：再收一轮只救得回 1.0%），展示层印纯文本是**已接受的正确行为**。
   ⇒ 真正「不是词」的是下面六类，合计约 1,770 条。

🔴 **我在这里又栽了一次**：先假设「`漢字(한글)` 这种带装饰的形，剥掉装饰就能解析」——
   实测 2,459 条里**只有 1 条**解得出（谚文和汉字**都不在 dict**）。
   装饰不是问题，我们没有那个词才是问题。⇒ 假设归 K21，不归本步。

═══ 六条判据，每条都带「已解析的那批证明它不误伤」的反向证据 ═══
在 **168,477 条已解析的边**上跑一遍，命中数必须是 0：

    C1 方言调查表单元格        542  ✅0   `벌거지諮諮Yeoncheon벌레諮諮Paju벌래諮諮…`
                                        英文版的方言调查表被整张压扁成一个关系目标，
                                        `諮諮`/`兪兪`/`尛尛`/`畁畁` 是它的单元格分隔符
    C2 表头                  362  ✅0   `Yang-vowel form` / `Yin-vowel form`（元音和谐表的表头）
    C3 英文说明（hanja 家族）   504  ✅0   `the hanja entry at 量 for Sino-Korean compounds of 양`
    C4 八卦符号/算式            16  ✅0   `☰` / `7+0=111+000*`（`乾` 条目那张八卦表）
    C5 wiki 标记残渣             3  ✅0   `인간(人間)[human being]]>`
    C6 全小写拉丁（≥3 字母）     442  ✅0   `sky`/`marsh`/`fire`（八卦表的英文注）、`vigor`/`design`

🔴🔴 **C6 收窄过两次，两次都是反向证据逼的**：
   · 第一版「全小写拉丁」⇒ 打到 **12 条已解析的边**（`ea`/`py`/`namu`/`saram`），
     它们的 kind 是 **`alternative`** —— 那是**罗马字冒充词形**（`paths.py` 陷阱①），
     是另一个缺陷，不是英文散文 ⇒ 排除 `alternative`。
   · 同时排除 **`descendant`**：那 165 条是 `taekwondo`/`noona`/`unnie`/`đài quyền đạo`
     —— **韩语词借进别的语言的形，完全合法**，删了就毁真数据。
   · 排除之后还剩 1 条误伤（`synonym 'n'`，单字母）⇒ 要求 **≥3 个拉丁字母**。
     （≥2 已经零误伤，**但删除是不可逆操作、风险不对称** ⇒ 取更保守的 ≥3，代价是多留 3 条垃圾。）

═══ 为什么是 `hidden=1` 而不是 `DELETE` ═══
用户 2026-09-24 定的调子：「**我倾向保留数据，用不用另一回事**」。
展示层已经在过滤 `COALESCE(r.hidden,0)=0`（`korean.ts` 第 296 行）⇒ 读者当场看不见，
数据留着、可逆（`[[prefer-reversible-designs]]`）。
⚠️ 关系层的 `hidden` **此前一行都没用过**（257,014 全是 0），本步是第一个写入方。
⇒ 同时建 `hidden_why`：`example.hidden` 背到第四种意思才被迫拆，这里**趁只有一种意思就带上原因**。

跑（在仓库根）：
    python3 -u ko/pipeline/hide_relation_nonwords.py
    python3 -u ko/pipeline/hide_relation_nonwords.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import re
import sqlite3

import dbtool
import paths

f = lambda n: format(n, ",")
ANNOT = ("hanja_spelling", "alt_hanja")      # 目标是「注」不是词，有意不解析
CJK = r"[가-힣一-鿿㐀-䶿ᄀ-ᇿ]"
# 🔴 这两个 kind 的小写拉丁目标是**合法的**，见文件头
C6_KEEP_KINDS = ("descendant", "alternative")
C6_MIN_LATIN = 3


def _strip_wiki(t):
    """去掉 wiki 标记。判据只写一份，C5 与 CLEAN 都用它。"""
    return re.sub(r"\[\[|\]\]|\{\{|\}\}|'''", "", t or "")


def _c6(kind, t):
    if kind in C6_KEEP_KINDS:
        return False
    t = (t or "").strip()
    return bool(len(re.sub(r"[^A-Za-z]", "", t)) >= C6_MIN_LATIN
                and not re.search(CJK, t)
                and re.search(r"[a-z]", t) and not re.search(r"[A-Z]", t))


CRITERIA = [
    ("C1", "方言调查表的单元格（源头把整张表压成了一个目标）",
     lambda k, t: bool(re.search(r"(諮諮|兪兪|尛尛|畁畁)", t or ""))),
    ("C2", "元音和谐表的表头",
     lambda k, t: (t or "").strip() in ("Yang-vowel form", "Yin-vowel form")),
    ("C3", "英文说明句（the/a hanja|hangul entry … 家族）",
     lambda k, t: bool(re.match(r"^\s*(the|a)\s+(hanja|hangul)\b", t or "", re.I)
                       or re.match(r"^\s*hanja with which\b", t or "", re.I))),
    ("C4", "八卦符号与算式（`乾` 条目那张表）",
     lambda k, t: bool(re.search(r"[☰-☷]", t or "")
                       or re.match(r"^\s*\d+\s*\+\s*\d+\s*=", t or ""))),
    # 🔴 C5（**只对 `hanja_spelling`/`alt_hanja`**）：target 去掉 wiki 标记之后是**空的**。
    #    实测 26 行，target 就是字面 `[[` 或 `]]`，落在 13 个词的**汉字表记区**上 ——
    #    页面上就印着 `[[` 和 `]]`。
    #    ⚠️ 这一类被我第一版的 `ANNOT` 排除**挡住了看不见**：我把
    #      `hanja_spelling`/`alt_hanja` 整类排除掉（理由是「它们的目标按设计是注」），
    #      于是连「注本身是垃圾」也一起排除了。
    #      **排除一整类的时候要问：被排除的那类里有没有另一种坏法。**
    ("C5", "汉字表记区里的纯 wiki 标记（`[[` / `]]`）",
     lambda k, t: bool(k in ANNOT and not _strip_wiki(t).strip())),
    ("C6", "英文注/散文（全小写拉丁 ≥%d 字母；排除 %s）"
           % (C6_MIN_LATIN, "/".join(C6_KEEP_KINDS)), _c6),
]


# 逐条读过的 3 条**可回收**边 —— 藏起来会丢掉真关系。
# 🔴🔴 wiki 标记与英文注缠在真词上，清掉之后目标**都在 dict 里**：
#      `인간(人間)[human being]]>` → `인간`   （真的近义词）
#      `이다[be]] (something)>`    → `이다`
#      `眞心]]/[[진심`              → `眞心`   （一条边塞了汉字形与谚文形两个目标）
# ⇒ 清 `target` ＋ 补 `target_norm`，**不藏**。
# ⚠️ 改 `target` 的先例是 **K19**（括号切断那 9 条）：`target` 的「一个字不许动」
#    防的是**改写源头的合法记法**（`경마(競馬)` / `^팔도`），不是保护抽取残渣。
#    原文在 dump 里按 `src_ref` 随时查得回来。
CLEAN = {
    416127: ("인간", "wiki 残渣 ＋ 英文注缠在真词上"),
    422232: ("이다", "同上"),
    557290: ("眞心", "一条边里塞了汉字形与谚文形两个目标，取汉字形"),
}
CLEAN_IDS = ",".join(str(i) for i in CLEAN)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    # 🔴 池子 ＝「目标本该是词」的那些 ∪「注本身是纯 wiki 标记」的那些。
    #    后者属于 `ANNOT`（目标按设计是注），但**注是垃圾也得管** —— 见 C5 的注释。
    un = con.execute(
        "SELECT id, kind, target FROM sense_relation WHERE target_norm IS NULL"
        " AND (kind NOT IN (?,?) OR TRIM(REPLACE(REPLACE(REPLACE(REPLACE("
        "   target,'[[',''),']]',''),'{{',''),'}}','')) = '')", ANNOT).fetchall()
    res = con.execute("SELECT kind, target FROM sense_relation"
                      " WHERE target_norm IS NOT NULL AND kind NOT IN (?,?)", ANNOT).fetchall()
    print("■ 池子：目标本该是词而解析不出的 %s 条（已排除 %s —— 它们的目标按设计是注）"
          % (f(len(un)), "/".join(ANNOT)))
    print("■ 反向证据基数：已解析的边 %s 条\n" % f(len(res)))

    plan, bad = {}, 0
    print("%-4s %-52s %7s %s" % ("判据", "说的是什么", "命中", "反向证据"))
    print("-" * 92)
    for cid, why, fn in CRITERIA:
        hit = [(i, k, t) for i, k, t in un if fn(k, t)]
        mis = [(k, t) for k, t in res if fn(k, t)]
        if mis:
            bad += 1
        print("%-4s %-52s %7s %s" % (cid, why[:52], f(len(hit)),
                                     ("🔴 %d 条：%s" % (len(mis), mis[:3])) if mis else "✅ 0 条"))
        for i, k, t in hit:
            plan.setdefault(i, (cid, why, k, t))
    print("-" * 92)
    print("%-4s %-52s %7s" % ("合计", "（去重）", f(len(plan))))
    if bad:
        raise SystemExit("🔴 有 %d 条判据误伤已解析的边 —— 收窄之后再来" % bad)

    print("\n■ 按 kind 分：", dict(collections.Counter(v[2] for v in plan.values())))
    print("■ 藏起来之后未解析池 %s → %s（降 %.1f%%）"
          % (f(len(un)), f(len(un) - len(plan)), 100.0 * len(plan) / len(un)))

    print("\n■ 每条判据抽 3 条（人眼确认「这确实不是词」）")
    for cid, why, _fn in CRITERIA:
        got = [(i, v) for i, v in plan.items() if v[0] == cid][:3]
        print("   %s %s" % (cid, why[:44]))
        for i, v in got:
            print("        %-16s %r" % (v[2], (v[3] or "")[:62]))

    has_col = any(c[1] == "hidden_why" for c in con.execute(
        "PRAGMA table_info(sense_relation)"))
    n_hidden = con.execute(
        "SELECT COUNT(*) FROM sense_relation WHERE COALESCE(hidden,0)=1").fetchone()[0]
    # 🔴 期望值**写前抓**，不要事后从池子大小反推 ——
    #    第一版我写的是 `len(un) + len(res) + count(ANNOT)`，而 `un` 已经把那 26 行
    #    ANNOT 纯标记纳进来了 ⇒ **重复计了 26**，回核红的是我的算术不是数据。
    #    `[[expectation-must-be-declared]]`：拿现状推期望，现状对不对都说不清。
    n_rows_before = con.execute("SELECT COUNT(*) FROM sense_relation").fetchone()[0]
    print("\n■ `sense_relation.hidden_why` 列%s；现在 hidden=1 的行 %s 条"
          % ("已存在" if has_col else "**还不存在，本步建**", f(n_hidden)))
    con.close()

    if not plan:
        print("\n■ 没有要改的")
        return
    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return

    upd = [("%s：%s" % (v[0], v[1]), i) for i, v in plan.items()]
    with dbtool.session(
            "ko-k30-hide-relation-nonwords",
            expect={"sense_relation.hidden_why": len(upd),
                    "sense_relation.target_norm": len(CLEAN),
                    "__rows__": 0},
            invalidates=[]) as s:
        if not has_col:
            s.execute("ALTER TABLE sense_relation ADD COLUMN hidden_why TEXT")
        s.executemany(
            "UPDATE sense_relation SET hidden=1, hidden_why=? WHERE id=?", upd)
        # 🔴 3 条可回收的：清 target ＋ 补 target_norm（**不藏**）
        s.executemany(
            "UPDATE sense_relation SET target=?, target_norm=? WHERE id=?",
            [(v[0], v[0], i) for i, v in CLEAN.items()])

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x, *p: con.execute(x, p).fetchone()[0]
    checks = [
        ("hidden=1 的行数", q("SELECT COUNT(*) FROM sense_relation"
                             " WHERE COALESCE(hidden,0)=1"), n_hidden + len(upd)),
        ("每一条都写了原因（R22 的不变量）",
         q("SELECT COUNT(*) FROM sense_relation WHERE COALESCE(hidden,0)=1"
           " AND (hidden_why IS NULL OR TRIM(hidden_why)='')"), 0),
        # 🔴 反向①：一行都没删（期望值是**写前抓的那个数**）
        ("关系边总数没变", q("SELECT COUNT(*) FROM sense_relation"), n_rows_before),
        # 🔴 反向②：**已解析的边一条都没被藏**（它们是好的）
        ("已解析的边一条都没被藏",
         q("SELECT COUNT(*) FROM sense_relation WHERE target_norm IS NOT NULL"
           " AND COALESCE(hidden,0)=1"), 0),
        # 🔴 反向③：`descendant`/`alternative` 一条都没被藏（合法数据）
        ("descendant/alternative 一条都没被藏",
         q("SELECT COUNT(*) FROM sense_relation WHERE kind IN (?,?)"
           " AND COALESCE(hidden,0)=1", *C6_KEEP_KINDS), 0),
        ("3 条可回收的都接通了且没被藏",
         q("SELECT COUNT(*) FROM sense_relation WHERE id IN (" + CLEAN_IDS + ")"
           " AND target_norm IS NOT NULL AND COALESCE(hidden,0)=0"), len(CLEAN)),
        ("可回收的 3 条落点都在 dict 里",
         q("SELECT COUNT(*) FROM sense_relation sr WHERE sr.id IN (" + CLEAN_IDS + ")"
           " AND NOT EXISTS (SELECT 1 FROM dict d WHERE d.word = sr.target_norm)"), 0),
        ("原因的种类数就是判据数",
         q("SELECT COUNT(DISTINCT SUBSTR(hidden_why,1,2)) FROM sense_relation"
           " WHERE hidden_why IS NOT NULL"), len(CRITERIA)),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-36s %9s（期望 %s）" % ("✅" if good else "🔴", name[:36], f(got), f(want)))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
