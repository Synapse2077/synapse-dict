#!/usr/bin/env python3
"""补回 1 条被残渣判据误删的读音。2026-08-18（阶段 8 收尾）。

═══ 顺序错了：归一必须跑在残渣判据**之前** ═══
阶段 8 当天按这个顺序动的库：

    ① drop_hyphenation_fragments.py   删「音标其实是词形拼写的一个音节」的 228 行
    ② normalize_ipa_stress_mark.py    把撇号式重音符 `'` 归一成 `ˈ`

跑 ① 的时候，撇号还没归一。**意语版**给 `assistente sociale` 的是一条**定界符写坏**的音标：

    "/assi'sten'te/socia'le"          ← `/…/` 在 te 后就闭合了，socia'le 掉在外面

⚠️ 我第一版把它记成英文版的，是因为诊断脚本里把 `paths.EDITION`（= itwiktionary）
   当成了英文版切片 —— 补回去的行 `src` 就写错了版，**正向外锚闸当场报红**
   （"表里标了某版、而那版 dump 里查不到"）。闸两个方向都查，写错一个方向就露馅。

解析出来是 `assi'sten'te`。而 `is_fragment` 的第一条判据是「整串没有任何 IPA 专有符号」——
那会儿 `'` 还没变成 `ˈ`，于是这串在判据眼里就是**纯拉丁字母**、又正好是词形拼写的子串
（`assistente` ⊂ `assistentesociale`）⇒ 被当成音节残渣删掉了。

归一之后它是 `assiˈstenˈte`，带两个 `ˈ`，判据一眼就放行 —— **同一个判据，同一条数据，
只因为跑的顺序不同，结论相反**。

🔴 **是外锚闸逮到的，不是我看出来的**：`build_pronunciation_layer` 闸⑤
（dump 有、表里没有）从 228 降到 1，剩的这 1 就是它。库内不变量、回归闸、
展示层契约闸**全都是绿的** —— 少一条读音在库里长得跟"源头本来就没有"一模一样。
⇒ 这正是 `external-anchor-gates` 那条的用处：锚外部 dump 的闸永不过期。

⚠️ 以后再动这一族：**先归一，后判残渣**。判据顺序在 `norm_ipa` 里也踩过一次（A71）。

用法（在 it/ 目录下）：
    python3 fixes/restore_stress_alias_reading.py            # 干跑
    python3 fixes/restore_stress_alias_reading.py --apply
    python3 fixes/restore_stress_alias_reading.py --verify
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool                              # noqa: E402
import paths                               # noqa: E402
from ipa_variants import is_fragment       # noqa: E402

WORD = "assistente sociale"
IPA = "assiˈstenˈte"          # norm_ipa("assi'sten'te")，见文件头
SRC = "it-edition"
REF = "kk-it:assistente sociale:noun:0#0"


def missing(con):
    """→ 这条读音还缺不缺。判据用词形+串，不用 id（id 是易变的）。"""
    n = con.execute(
        "SELECT count(*) FROM pronunciation p JOIN dict d ON d.id=p.word_id "
        "WHERE d.word=? AND p.ipa=?", (WORD, IPA)).fetchone()[0]
    return n == 0


def gate(con):
    print("\n═══ 闸 ═══")
    checks = [
        ("🔴 那条读音已经回到表里", 0 if not missing(con) else 1, 0),
        # 🔴 回归判据：归一之后它**不该**再被残渣判据认成片段
        ("🔴 归一后的串不再被判成音节残渣",
         1 if is_fragment(WORD, IPA) else 0, 0),
        # ⚠️ 反向：归一**之前**那个串确实会被判成片段 —— 这条断言证明"顺序是判据"
        ("·  （对照）未归一的串确实会被判成片段",
         1 if is_fragment(WORD, "assi'sten'te") else 0, 1),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-42s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    row = ro.execute("SELECT id FROM dict WHERE word=?", (WORD,)).fetchone()
    ent = ro.execute("SELECT id FROM entry WHERE word_id=? AND pos='noun' AND etym_no='0'",
                     (row[0],)).fetchone()
    gone = missing(ro)
    ro.close()
    print("■ %s 的 %s：%s" % (WORD, IPA, "缺，要补回" if gone else "已经在表里，无需处理"))
    if not a.apply or not gone:
        print("\n(未加 --apply，不写库)" if gone else "")
        return 0
    with dbtool.session("restore-stress-alias-reading",
                        expect={"__rows__": 0, "#pronunciation": 1}) as s:
        # is_primary=0：该词形已有一条 fr 版主读音（完整的两词转写），
        # 这条是意语版那个写坏了的半截，补回来是为了**可回源**，不是为了展示。
        s.execute("INSERT INTO pronunciation (word_id, entry_id, ipa, notation, region, tags,"
                  " is_primary, src, src_ref) VALUES (?,?,?,?,NULL,NULL,0,?,?)",
                  (row[0], ent[0] if ent else None, IPA, "phonemic", SRC, REF))
        s.written = 1
    print("\n■ 已补回 1 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
