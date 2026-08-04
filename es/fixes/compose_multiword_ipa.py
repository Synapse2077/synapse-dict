#!/usr/bin/env python3
"""多词词条的音标：由组成词拼出来，不问模型。2026-08-03。

═══ 为什么不问模型 ═══
缺音标的 4,303 行里 **4,038 行是多词词条**（`bienes raíces` / `status quo` /
`medula espinal`）。它们的组成词**库里都已经有人工音标**，拼接是确定性的 ——
纪律⑩：能确定性做的根本别问模型。

═══ 约定从库里已有的 22,204 条多词音标读出来 ═══
    uña de gato     → ˈuɲa de ˈɡato       **每个实词保留自己的主重音**（多数写法）
    a la            → a la                虚词不带重音符
    San Marino      → ˌsam maˈɾino        连音同化：san + m → sam
    en cuerpo y alma→ … i ˈalma           连词 y 在词组里读 /i/，不是单读的 /ʝ/

🔴 **我第一版归纳错了**：照着 `Costa Rica`→`ˌkosta ˈrika`、`América Latina`→
   `aˌmeɾika laˈtina` 定了"非末词主重音降为次重音"，留出验证一测 **逐字一致只有 38%**
   —— 那几条是地名，是少数派。改成不降级后 47.9%。
   **归纳出来的规则必须拿留出集验，眼缘看几条就定规则是要翻车的。**

🔴 **本脚本自带留出验证**：库里那 22,204 条多词词条**已经有音标**，
   拿它们当真值 —— 用同一套规则从组件拼一遍，比对逐字一致率。
   对不上就说明规则不对，**先别落库**。这是唯一能证明"我拼的和人写的是一回事"的办法。

用法（在 es/ 目录）：
    python3 fixes/compose_multiword_ipa.py            # 留出验证 + 试算
    python3 fixes/compose_multiword_ipa.py --apply
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import re
import sqlite3

import dbtool
import paths

# 不带自身重音的虚词（库里 `a la` 这类就是不带重音符存的）
CLITIC = {
    "a", "la", "el", "los", "las", "de", "del", "al", "en", "con", "por", "para",
    "y", "e", "o", "u", "que", "se", "me", "te", "le", "les", "lo", "nos", "os",
    "un", "una", "su", "mi", "tu", "sin", "si", "no", "ni", "más",
}


# 连词单独读时是 /ʝ/、/o/，在词组里读 /i/、/o/。
# 不处理的话 `en cuerpo y alma` 会拼成 `… ʝ ˈalma`，库里是 `… i ˈalma`。
CONJ = {"y": "i", "o": "o", "e": "e", "u": "u"}


def sandhi(prev, nxt):
    """词尾鼻音在后词首辅音前的同化。库里 `San Marino` → `ˌsam maˈɾino` 就是这条。

    只做**最保守的一条**：词尾 n 在双唇音 /b p m/ 前变 m。
    ŋ 不做 —— 本词典存裸音位，ŋ 归 n（见 ipa-bare-storage-convention）。
    """
    if prev.endswith("n") and nxt[:1] in ("b", "p", "m"):
        return prev[:-1] + "m"
    return prev


def compose(word, ipa_of):
    """整条多词词条的音标；任一组件查不到音标就返回 None（宁可留空）。"""
    parts = word.split()
    if len(parts) < 2:
        return None
    got = []
    for p in parts:
        key = p.strip(".,;:¡!¿?«»\"'()").lower()
        if key in CONJ:
            got.append((key, CONJ[key]))
            continue
        ip = ipa_of.get(key)
        if not ip:
            return None
        got.append((key, ip))
    # 🔴 **每个词保留自己的主重音，不降级。**
    #    我先按 `Costa Rica`→`ˌkosta ˈrika`、`San Marino`→`ˌsam maˈɾino` 归纳出
    #    "非末词降次重音"，留出验证一测**逐字一致只有 38%** —— 那几条是地名，是少数派。
    #    库里的多数写法是 `uña de gato`→`ˈuɲa de ˈɡato`、`onda verde`→`ˈonda ˈbeɾde`。
    #    改成不降级后 48.5%，音段一致率 87.9%。**归纳规则必须拿留出集验，不能靠眼缘。**
    out = []
    for w, ip in got:
        out.append(ip.replace("ˈ", "").replace("ˌ", "") if w in CLITIC else ip)
    for i in range(len(out) - 1):
        out[i] = sandhi(out[i], out[i + 1])
    return " ".join(out)


def load(conn):
    ipa_of = {}
    for w, p in conn.execute(
            "SELECT word, phonetic FROM dict WHERE TRIM(COALESCE(phonetic,''))<>'' "
            "AND word NOT LIKE '% %'"):
        ipa_of.setdefault(w.lower(), p)
    return ipa_of


def holdout(conn, ipa_of):
    """留出验证：库里已有音标的多词词条，用规则重拼一遍，和真值比。"""
    rows = conn.execute(
        "SELECT word, phonetic FROM dict WHERE word LIKE '% %' "
        "AND TRIM(COALESCE(phonetic,''))<>''").fetchall()
    st, diff = collections.Counter(), []
    for w, truth in rows:
        got = compose(w, ipa_of)
        if got is None:
            st["组件查不全（本方法覆盖不到）"] += 1
            continue
        if got == truth:
            st["逐字一致"] += 1
        elif got.replace("ˌ", "").replace("ˈ", "") == truth.replace("ˌ", "").replace("ˈ", ""):
            st["仅重音符位置不同（音段相同）"] += 1
        else:
            st["不一致"] += 1
            if len(diff) < 400:
                diff.append((w, truth, got))
    n = st["逐字一致"] + st["仅重音符位置不同（音段相同）"] + st["不一致"]
    print("■ 留出验证（分母＝库里已有音标的多词词条 {:,}）".format(len(rows)))
    for k, v in st.most_common():
        print("   {:26} {:7,}".format(k, v))
    print("   → 能拼的 {:,} 条里，逐字一致 {:.1f}%，**音段一致 {:.1f}%**".format(
        n, 100 * st["逐字一致"] / max(n, 1),
        100 * (st["逐字一致"] + st["仅重音符位置不同（音段相同）"]) / max(n, 1)))
    return st, diff


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ipa_of = load(conn)
    st, diff = holdout(conn, ipa_of)
    dbtool.sample_check(diff, n=14, cols=("词", "库内人工值", "我拼的"))

    rows = conn.execute(
        "SELECT id, word FROM dict WHERE word LIKE '% %' "
        "AND TRIM(COALESCE(phonetic,''))=''").fetchall()
    conn.close()
    plan, samples = [], []
    for rid, w in rows:
        got = compose(w, ipa_of)
        if not got:
            continue
        plan.append((got, got, "compose-multiword", rid))
        samples.append((w, got))
    print("\n■ 缺音标的多词词条 {:,}，能拼出 {:,}（{:.1f}%）".format(
        len(rows), len(plan), 100 * len(plan) / max(len(rows), 1)))
    dbtool.sample_check(samples, n=14, cols=("词", "拼出的音标"))

    if not a.apply:
        print("\n(试算完毕。加 --apply 落库)")
        return
    with dbtool.session("compose-multiword-ipa",
                        expect={"phonetic": len(plan), "phonetic_raw": len(plan),
                                "phonetic_src": len(plan)}) as s:
        s.executemany(
            "UPDATE dict SET phonetic=?, phonetic_raw=?, phonetic_src=? WHERE id=?",
            plan)


if __name__ == "__main__":
    main()
