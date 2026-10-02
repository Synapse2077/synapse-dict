#!/usr/bin/env python3
"""阶段 1（下半）：建 `entry` 层 —— 词条 = (词形, 词性, 词源号, seq)。2026-09-28。

`entry` 是夹在 `dict`（词形/搜索单位）与 `sense`（义项）之间的**源头自己的单位**。
`VI_PLAN` §4.1 定：**两版都有的词，entry 切分与 pos 跟英文版**。本步只建英文版这一侧。

═══ 🔴🔴 **不合并重复键，全部用 seq 分开 —— 而且这次理由与 ko 不同** ═══
ja 的做法是：`(词形,词性,词源号)` 重复时，**若音标相同就合并**。
ko 上这条判据**失效了，而且是最难发现的那种** —— 178 组里 127 组（73%）
「音标相同」其实是**两边都没有音标**，判据在比两个空集。

vi 上我重量了一遍，结论**反过来**：

    重复键 118 组（多出 124 条）
      ├ 两边都没有音标（判据比空集）  **1** 组   ← ko 上是 127 组
      ├ 真的有音标且相同            117 组
      └ 音标不同                      0 组

**⇒ 在 vi 上 ja 那条判据是有意义的、不空转的。** 但本步**仍然不合并**，理由是另一条：
**分开可逆、合并不可逆**（`[[prefer-reversible-designs]]`）。
真有切分伪影，将来拿更好的判据再合并得了；合并错了就再也分不开。
⚠️ **什么会推翻**：拿到一条能证明这 117 组是 wiktextract 切分伪影的判据
（例如回维基页面核到它们同属一个章节），且代价大到值得做。

⭐ 这一条是 `[[criteria-narrower-than-you-think]]` 的镜像：判据本身没写错，
   **它默认成立的那个前提在换语种时变了**。⇒ 换语种照搬的不只是判据，还有它的前提 ——
   所以这里的做法是**把 ko 的那个量重做一遍**，而不是抄 ko 的结论。

═══ 🔴🔴 `pos`：**一个值域，不造第二套短码** ═══
ko 的 **K31** 是这么栽的：`entry.pos` 存短码（`n`/`v`）、`dict.pos` 存长码加斜杠，
而映射表只维护短码 ⇒ **两边一致地报全绿，而每个徽标都是空的**。

本步**不建 `POS_MAP`**。`dict.pos` 与 `entry.pos` 用的是**同一个值域** ——
kaikki 自己的 25 个原子词性。实测：

    `dict.pos` 有 **464 种取值**，其中 441 种是斜杠组合（3,630 行，11.8%）
    拆开后**原子词性只有 25 种**

⇒ 约定写死：**`dict.pos` 是 `entry.pos` 值域的「/」连接多值**，
  展示层读 `dict.pos` 必须先 `split('/')`，`packages/dict-labels` 只需维护那 25 个。
  本脚本的回核里有一条就是查这件事（每个斜杠段都必须落在 25 个原子值里）。

═══ `etym_type`：本步**一列都不填** ═══
`entry.etym_type`（sino_vietnamese / native / borrowed / mixed）要从词源正文判，
那是阶段 7 的活。**有意不填** —— 先填一套再被覆盖 ＝ 同一个字段两个写入方，
ja 的 `inflection` 正是这么栽的。**一个字段一个写入方。**

跑（在仓库根）：
    python3 -u vi/pipeline/build_entry_layer.py
    python3 -u vi/pipeline/build_entry_layer.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import gzip
import json
import sqlite3

import dbtool
import paths

SRC = "en-edition"

# kaikki 英文版的原子词性值域。**这就是全部** —— `dict.pos` 是它的「/」连接多值。
# 🔴 这张表只许有一份，后续脚本一律 `from build_entry_layer import POS_DOMAIN`。
POS_DOMAIN = {
    "adj", "adv", "affix", "character", "classifier", "combining_form", "conj",
    "counter", "det", "intj", "name", "noun", "num", "particle", "phrase",
    "prefix", "prep", "pron", "proverb", "punct", "romanization", "suffix",
    "syllable", "symbol", "verb",
    # ── 🔴 阶段 4 收词（2026-09-28）撑进来的两个，**显式登记而不是默默接受** ──
    #    en 版没有这两个值，它们来自越南文版与中文版：
    #      `unknown` —— 源页面**压根没写词性**（`pos_title` 是 `Định nghĩa`/`釋義`）。
    #        🔴 存成 `unknown` 而**不是 NULL**：`[[dont-say-source-lacks-what-we-skipped]]`
    #           「源头没写」和「我们没抽」要在结构上分得开，NULL 两种都像。
    #        ⚠️ 它是**大头**（收进来的新词形里一半以上只有这个词性），
    #           读者口径上等于「这个词没有词性徽标」—— 记在 `VI_PLAN` §3.5，
    #           阶段 9 展示层要明说「源头未标注词性」，不许印成空白。
    #      `abbrev`  —— 缩写，只有 16 条。
    "unknown", "abbrev",
}


def scan(indict):
    """扫英文版切片 → entry 行。`dict` 里没有的词形不建 entry。"""
    seen = collections.Counter()
    rows, stat = [], collections.Counter()
    dup_samples = collections.defaultdict(list)
    with gzip.open(paths.KK, "rt", encoding="utf-8") as f:
        for line in f:
            o = json.loads(line)
            w = (o.get("word") or "").strip()
            if w not in indict:
                stat["跳过·词形不在 dict 里"] += 1
                continue
            pos = o.get("pos")
            etym_no = str(o.get("etymology_number", "0") or "0")
            k = (w, pos, etym_no)
            seq = seen[k]
            seen[k] += 1
            if seq:
                stat["重复键 → 用 seq 分开（不合并）"] += 1
                if len(dup_samples[k]) < 1:
                    g = (o.get("senses") or [{}])[0].get("glosses") or [""]
                    dup_samples[k].append(g[0][:50])
            # src_ref 是**内容派生的主键**，永远不用行号（`SCHEMA` 的铁律）
            src_ref = "kk-en:%s:%s:%s:%d" % (w, pos, etym_no, seq)
            rows.append((indict[w], pos, etym_no, seq, SRC, src_ref))
            stat["建 entry"] += 1
    stat["不同的键"] = len(seen)
    return rows, stat, dup_samples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    indict = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    con.close()
    print("■ dict 里有 %s 个词形" % format(len(indict), ","))

    rows, stat, dup = scan(indict)
    for k in ("跳过·词形不在 dict 里", "不同的键", "建 entry", "重复键 → 用 seq 分开（不合并）"):
        print("   %-34s %9s" % (k, format(stat[k], ",")))

    print("\n■ 重复键 %s 组的样本（**有意不合并**，理由见文件头）：" % format(len(dup), ","))
    for k, v in list(dup.items())[:5]:
        print("   %-34s %s" % (str(k), v))

    # pos 值域自证：一个都不许在 25 个原子值之外
    bad = sorted({p for _, p, _, _, _, _ in rows} - POS_DOMAIN)
    print("\n■ `entry.pos` 值域：%d 种，落在 POS_DOMAIN 之外的：%s"
          % (len({p for _, p, _, _, _, _ in rows}), bad or "无 ✅"))

    dbtool.sample_check([(r[5], r[1], r[2], r[3]) for r in rows], 8,
                        ("src_ref", "词性", "词源号", "seq"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    n = len(rows)
    # 🔴 `entry.etym_type` **有意不在 expect 里** —— 本步一列都不填（阶段 7 才填）。
    #    它要是涨了，说明有人在这一步偷偷开了第二个写入方。
    # 🔴 **这道闸第二次红也是对的**：`__rows__` 量的是 `dict` 的行数（`TABLE` 那张主表），
    #    **不是全库总行**。本步一行 `dict` 都不插 ⇒ `__rows__` 必须是 **0**，
    #    entry 的增量要写成表计数键 `#entry`。
    #    ⚠️ 写成 `__rows__: n` 会在两个方向同时错：既漏报 `#entry`，
    #       又声称 `dict` 会涨 36,549 行 —— 而闸把两条都报了出来。
    with dbtool.session("build-vi-entry-layer",
                        expect={"__rows__": 0, "#entry": n,
                                "entry.pos": n, "entry.etym_no": n},
                        invalidates=[]) as s:
        s.executemany(
            "INSERT INTO entry (word_id, pos, etym_no, seq, src, src_ref) VALUES (?,?,?,?,?,?)",
            rows)

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    # 🔴 **读者口径的一条**：展示层读 `dict.pos` 要 split('/')，
    #    所以闸必须查「每个斜杠段都在值域里」，而不是只查 `entry.pos`。
    #    ko 的 K31 就是两边各查各的、一致报全绿而徽标全空。
    seg_bad = sum(1 for (p,) in con.execute("SELECT DISTINCT pos FROM dict WHERE pos IS NOT NULL")
                  if any(x not in POS_DOMAIN for x in p.split("/")))
    checks = [
        ("entry 行数", q("SELECT COUNT(*) FROM entry"), n),
        ("src_ref 唯一", q("SELECT COUNT(*) FROM (SELECT src_ref FROM entry GROUP BY src_ref "
                           "HAVING COUNT(*)>1)"), 0),
        ("每个 entry 都有 dict",
         q("SELECT COUNT(*) FROM entry e LEFT JOIN dict d ON d.id=e.word_id WHERE d.id IS NULL"), 0),
        ("entry.pos 在值域内",
         q("SELECT COUNT(*) FROM entry WHERE pos NOT IN (%s)"
           % ",".join("'%s'" % p for p in sorted(POS_DOMAIN))), 0),
        ("🔴 dict.pos 每个斜杠段都在值域内（读者口径）", seg_bad, 0),
        ("etym_type 本步一列都没填", q("SELECT COUNT(*) FROM entry WHERE etym_type IS NOT NULL"), 0),
        # dict 里每个词形至少一条 entry —— 否则就是「搜得到、点进去没有词条」
        ("没有 entry 的词形",
         q("SELECT COUNT(*) FROM dict d LEFT JOIN entry e ON e.word_id=d.id WHERE e.id IS NULL"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-34s %10s（期望 %s）" % ("✅" if good else "🔴", name,
                                              format(got, ","), format(want, ",")))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
