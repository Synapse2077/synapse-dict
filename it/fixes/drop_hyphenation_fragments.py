#!/usr/bin/env python3
"""意语版的**音节切分残渣**混进了 `pronunciation`。2026-08-18（阶段 8）。

═══ 怎么发现的 ═══
阶段 8 要把展示层从 `dict.ipa` 切到 `pronunciation`，切之前把「将来会显示出去的那批」
按词形长度扫了一遍，逮到这个形状：

    sudanese        su / da / né / se       ← it 版把 `su-da-né-se` 的**每个音节**
    Anopluri        A / no / plù / ri          当成一条 `sounds` 给出来了
    anestesiologia  a                       ← 只剩第一个音节
    strillozzo      lòz / zo

`ipa_variants.looks_like_ipa` 本来拦过一类残渣（判据是「拉丁字母连写块 ≥3」），
但**单音节的碎片拦不住** —— `su`、`da`、`né` 每个都只有两个字母。

🔴 **其中 115 条是 `is_primary=1`** —— 也就是说切完展示层，用户在 `sudanese`
   页面上看到的音标会是 `/su/`。这是「用户会看到错的内容」那一类，不进 backlog。

═══ 判据（三条同时成立才算）═══
① 整串**没有任何 IPA 专有符号**（ˈ ˌ ː ɛ ɔ ʃ ʒ ʎ ɲ ŋ ɡ …）⇒ 它是拼写不是音标
② 折掉重音符号/点/空格之后，它是**词形拼写的一个子串**
③ 词形比它长至少 3 个字母

⚠️ 第 ③ 条不是凑数：`a-` → `a`、`in-` → `in`、`bi-` → `bi` 这些前缀词条的音标
   本来就等于拼写，前两条判据会把它们一起圈进来（实测 15 个）。第一版没有第 ③ 条时
   误伤 15 条真读音 —— 与 `hide_see_also_residue` 里 `see (of a bishop)` 同一个形状：
   **看着像残渣的短串，往往正是短词的真值**。

═══ 处理 ═══
删行（不是改），然后**调 `build_pronunciation_layer.restamp()` 重选 `is_primary`** ——
不自己再写一遍选举判据（那是第二把尺子，迟早与写入侧打架）。
6 个词形删完就一条读音都不剩了 ⇒ 留诚实空白（`blind-gloss-inference-ceiling`）。
锚点行 0 条（`dict.ipa` 的可逆性不受影响，已在闸里断言）。

用法（在 it/ 目录下）：
    python3 fixes/drop_hyphenation_fragments.py            # 干跑，列出全部命中
    python3 fixes/drop_hyphenation_fragments.py --apply
    python3 fixes/drop_hyphenation_fragments.py --verify
    python3 fixes/drop_hyphenation_fragments.py --mutate
"""
import argparse
import sqlite3
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool                              # noqa: E402
import paths                               # noqa: E402
import build_pronunciation_layer as B      # noqa: E402

f = lambda n: format(n, ",")
LEGACY = "dict.ipa"

# 🔴 判据本体已搬进 `pipeline/ipa_variants.py`（2026-08-18 阶段 8 收尾）——
#    因为**收词入口也要用它**：只删库不挡入口，下次重扫 dump 就又灌回来，
#    而且外锚闸⑤（dump 有、表里没有）会一直红着报这 228 条"漏收"。
#    这里只保留 re-export，回归闸 A5 与本脚本 import 的是同一份。
from ipa_variants import is_fragment, _FRAG_MARGIN as MARGIN   # noqa: E402,F401


def scan(con):
    """→ [(id, 词形, 片段, src, is_primary, 是不是锚点)]"""
    out = []
    for pid, w, ipa, src, prim, ref in con.execute(
            "SELECT p.id, d.word, p.ipa, p.src, p.is_primary, p.src_ref "
            "FROM pronunciation p JOIN dict d ON d.id = p.word_id"):
        if is_fragment(w, ipa):
            out.append((pid, w, ipa, src, prim, LEGACY in ref))
    return out


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    left = scan(con)
    checks = [
        ("🔴 拼写片段（音节切分残渣）", len(left), 0),
        ("🔴 每个词形恰好一条 is_primary",
         q("SELECT count(*) FROM (SELECT word_id FROM pronunciation "
           "GROUP BY word_id HAVING sum(is_primary)<>1)"), 0),
        # 🔴 删行不许伤到可逆性：`dict.ipa` 每个非空值仍要能从表里逐字节重建
        ("🔴 可逆性：逐字节重建 dict.ipa 对不上的",
         q("SELECT count(*) FROM dict d WHERE trim(COALESCE(d.ipa,''))<>'' "
           "AND NOT EXISTS(SELECT 1 FROM pronunciation p WHERE p.word_id=d.id "
           "AND p.ipa=d.ipa AND p.src_ref LIKE '%" + LEGACY + "%')"), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-40s %s (期望 %s)" % ("✅" if got == want else "🔴", name, f(got), f(want)))
    return ok


def mutate():
    """判据变异：能不能同时做到「逮住残渣」和「不误伤短词真值」。"""
    print("═══ 变异验证：判据本体 ═══")
    cases = [
        ("🔴 音节碎片要逮住", is_fragment("sudanese", "su"), True),
        ("🔴 带重音符的碎片也要逮住", is_fragment("Anopluri", "plù"), True),
        ("🔴 长词只剩首音节", is_fragment("anestesiologia", "a"), True),
        ("前缀词条的真读音不许误伤", is_fragment("in-", "in"), False),
        ("短词的真读音不许误伤", is_fragment("bi-", "bi"), False),
        ("🔴 含 IPA 符号的一律不动", is_fragment("sudanese", "sudaˈneːse"), False),
        ("🔴 只差长度余量的边界（3 个字母）", is_fragment("abcd", "a"), True),
        ("🔴 余量不足就不动", is_fragment("abc", "a"), False),
        ("不是子串的不动", is_fragment("sudanese", "xyz"), False),
        ("🔴 j/w 是意语字母，不能当 IPA 判据", is_fragment("jazz", "jazz"), False),
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
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    hits = scan(ro)
    words = {w for _i, w, _p, _s, _pr, _l in hits}
    prim = sum(1 for h in hits if h[4])
    anchors = sum(1 for h in hits if h[5])
    print("■ 命中 %s 行 / %s 个词形；其中 is_primary %s 条、锚点 %s 条"
          % (f(len(hits)), f(len(words)), f(prim), f(anchors)))
    print("   按来源：" + "  ".join("%s %s" % (k, f(v))
                                for k, v in Counter(h[3] for h in hits).most_common()))
    for pid, w, ipa, src, p, _l in (hits if a.all else hits[:30]):
        print("     %-26s %-10s %-12s primary=%s" % (w[:26], ipa[:10], src, p))
    if not a.all and len(hits) > 30:
        print("     …（--all 看全部 %s 条）" % f(len(hits)))
    ro.close()
    if anchors:
        print("\n🔴 命中里含锚点行，会破坏 dict.ipa 的可逆性 —— 不写库，先查。")
        return 1
    if not a.apply or not hits:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("drop-hyphenation-fragments",
                        expect={"__rows__": 0, "#pronunciation": -len(hits)}) as s:
        s.execute("DELETE FROM pronunciation WHERE id IN (%s)"
                  % ",".join(str(h[0]) for h in hits))
        s.written = len(hits)
    print("\n■ 已删 %s 行，重选 is_primary…" % f(len(hits)))
    B.restamp(dry=False)          # 🔴 复用写入侧的选举判据，不另写一份
    return 0


if __name__ == "__main__":
    sys.exit(main())
