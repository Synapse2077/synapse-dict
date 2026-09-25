#!/usr/bin/env python3
"""阶段 2c：收变形词形 ＋ 建 `inflection` 层。**一步做完，不分开。** 2026-09-21。

═══ 🔴🔴 为什么收词形和建链必须在同一步 ═══
`PLAYBOOK` 四：pt 把变形层建在收词**之前**，收进来的 35.7 万个词形
**从此没人给它们连过线** ⇒ **355,605 个词形（46.2%）既无义项也无变形链
＝搜得到、点进去空白页**。而且「没有人会回头重跑」。
⇒ 本脚本在**同一个事务**里插 `dict` 和 `inflection`：要么都有，要么都没有。

═══ 盘子 ═══
    583,533 个 form  ——  `infl_tags.classify()` 分五类（判据见那份文件）
      ├ inflection  437,001   ← 本步
      ├ script      116,159   汉字/谚文/罗马字，另有去处
      ├ meta         28,590   活用表的元数据（已进 `entry.conj_class`）
      ├ relation      1,593   异体/方言/量词 → 阶段 2d 关系层
      └ (None)          190   旧模板残留（表头文字 `해라체`、旧拼写 `가까와`）⇒ 落账不收

    435,757 个 (原形, 变形形) 对   →   322,693 个不同的变形词形
                                        其中 321,827 个**不在 `dict` 里**
    ⇒ `dict` 57,110 → 378,937
    ⚠️ 这几个数比「按 tag 黑名单粗筛」时少 2 万 —— 差额是 `infl_tags` 把
       MR/revised/Yale/eumhun（罗马字与汉字训读）和 counter（量词）分流走了。
       **两个数不一致时，以分类表那份为准**：黑名单只挡得住我想到的。

═══ 为什么变形形要进 `dict` 而不是只留在 `inflection` ═══
`dict` 是**搜索与身份单位**（`SCHEMA` §1）。用户搜 `가까워` 必须找得到 `가깝다` ——
不进 `dict` 就搜不到。es（113 万行，86% 是词形）、ja、fr 全是这么做的。
🔴 它们 `is_lemma=0`、没有义项，但**不是空白页**：点进去有「`가깝다` 的非格式体尊敬过去」
   这条链。**空白页的定义是"既无义项又无变形链"**，不是"没有义项"。

═══ `entry_id` 的语义（`SCHEMA` §10.3，it 阶段 8 定死）═══
= **原形的那个 entry**，即「这个变形形属于原形的哪一个词条」。
🔴 判据不是偏好，是**哪个读法带信息**：变形形自己的 entry 从 `word_id` 一查就有（冗余），
   而「`가까워` 是 `가깝다`（形容词）的形」推不出来，只有源头知道。

跑（在仓库根）：
    python3 -u ko/pipeline/build_inflection_layer.py
    python3 -u ko/pipeline/build_inflection_layer.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import json
import sqlite3
import unicodedata

import dbtool
import paths
from infl_tags import classify, label_zh, UnknownTag

SRC = "en-edition"
BATCH = 50000


def norm_ko(s):
    """与 `build.py` 同一条归一。**不另写一份实现**。"""
    return unicodedata.normalize("NFC", s or "")


def is_korean_form(fw):
    """这串是不是一个**韩语词形**。去掉词间空格与连接号后必须全是谚文或汉字。

    🔴 判据按**内容**写（"韩语词形长什么样"），不按"含不含某个坏字符"——
       后者是黑名单，只挡得住我想到的那几种。
    实测：435,574 条通过 / **183 条不通过**，而那 183 条正好是三类脏数据：
        模板残留 50   `{{{stem1}}}다 ({{{stem1_r}}}da)`   wiktextract 没展开维基模板参数
        纯英文   48   `interrogative` `assertive` `cause`  **表头文字被当成词形**
        混排     85   `past: 가까왔다`                      表头前缀粘在词形上
    ⭐ **零误伤**：1,777 个含空格的真词形（`-었으면 하겠다` 这类语法结构）全部通过。
    ⚠️ 三类全部来自**旧模板** `ko-conj-adj`/`ko-conj-verb` 的解析残留 ——
       与 ja 阶段 2「扁平遍历 forms 看不见表、表头混进词形」是同一个病
       （ja 那次 108 个词无一幸免）。
    """
    core = fw.replace(" ", "").replace("-", "").replace("·", "") \
             .replace("~", "").replace("—", "")
    if not core:
        return False
    for c in core:
        if "가" <= c <= "힣" or "ㄱ" <= c <= "ㆎ" or "ᄀ" <= c <= "ᇿ":
            continue                                   # 谚文
        if dbtool.has_han_char(c):
            continue                                   # 汉字（汉字词的变形）
        return False
    return True


def iter_forms():
    """扫一遍 dump，吐出每个**变形** form 及其归属。两遍扫描共用它，
    保证「收哪些词形」和「建哪些链」出自**同一条判据**——
    两份判据迟早漂开，而症状是「收了词形却没有链」（pt 的空白页）。

    🔴 **同一条变形事实只吐一次。** wiktextract 会把同一张活用表解析多遍：
       实测 `(原形, 变形形, tags)` 完全相同的冗余行 **31,896 条（7.3%）**，
       `요요하다` 的每个变形出现了 **11 次**（它有 11 个 entry，各带一张完整的表）。
       去重键用 `(原形, 变形形, tags)`，保留**第一个**（entry seq 最小的那个）——
       11 个 entry 都是同一个词的，哪个都对，存 11 份只是冗余。
    """
    seen_entry = collections.Counter()
    seen_fact = set()
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
        seq = seen_entry[k]
        seen_entry[k] += 1
        eref = "kk-ko:%s:%s:%s:%d" % (w, praw, etym, seq)
        for i, f in enumerate(o.get("forms") or []):
            tags = f.get("tags") or []
            if classify(tags) != "inflection":
                continue
            fw = (f.get("form") or "").strip()
            if not fw or fw in ("-", "—") or fw == w:
                continue
            if not is_korean_form(fw):
                continue                     # 表头文字 / 模板残留 —— 见 `is_korean_form`
            fact = (w, fw, tuple(sorted(tags)))
            if fact in seen_fact:
                continue                     # 同一张表被解析了多遍
            seen_fact.add(fact)
            yield w, eref, fw, tags, i


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    indict = {r[1]: r[0] for r in con.execute("SELECT id, word FROM dict")}
    inentry = {r[1]: r[0] for r in con.execute("SELECT id, src_ref FROM entry")}
    have = con.execute("SELECT COUNT(*) FROM inflection").fetchone()[0]
    max_id_before = con.execute("SELECT MAX(id) FROM dict").fetchone()[0]
    con.close()
    if have:
        raise SystemExit("🔴 inflection 非空（%d 行）—— 本步是首建。" % have)

    # ── 第一遍：这一步要新收哪些词形 ──
    stat = collections.Counter()
    newforms, allforms, pairs = set(), set(), 0
    labels = collections.Counter()
    try:
        for w, eref, fw, tags, i in iter_forms():
            pairs += 1
            allforms.add(fw)
            if fw not in indict:
                newforms.add(fw)
            labels[label_zh(tags)] += 1
    except UnknownTag as e:
        raise SystemExit("🔴 %s\n   ⇒ 先把它分类进 `infl_tags.py`，别让它默默落进变形层" % e)

    print("■ 扫 %s" % paths.KK.name)
    print("   %-30s %9s" % ("(原形,变形形) 对", format(pairs, ",")))
    print("   %-30s %9s" % ("其中已在 dict 里的",
                            format(len(allforms) - len(newforms), ",")))
    print("   %-30s %9s" % ("不同的变形词形", format(len(allforms), ",")))
    print("   %-30s %9s" % ("🔴 要新收进 dict 的词形", format(len(newforms), ",")))
    print("   %-30s %9s" % ("label_zh 的种类", format(len(labels), ",")))
    print("   %-30s %9s" % ("🔴 生成不出 label_zh 的", format(labels.get("", 0), ",")))
    if labels.get("", 0):
        raise SystemExit("🔴 有变形生成不出中文标签 —— `infl_tags.LABEL_ZH` 缺条目")
    print("   dict: %s → %s" % (format(len(indict), ","),
                                format(len(indict) + len(newforms), ",")))
    print("\n   label_zh top 8: %s" % labels.most_common(8))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    newlist = sorted(newforms)
    with dbtool.session(
            "build-ko-inflection",
            expect={"__rows__": len(newlist), "pos": 0,
                    "#inflection": pairs,
                    "inflection.base_id": pairs,
                    "inflection.label_zh": pairs},
            invalidates=[
                "义项覆盖率：分母从 57,110 涨到 %s（分子不变）—— **不是回归**"
                % format(len(indict) + len(newlist), ","),
                "阶段 3 读音层：新收的 32.7 万变形词形没有读音，覆盖率要按**词元**算不按全库算",
                "搜索层（阶段 9）：`search_prefix` 要在这批之后重建",
            ]) as s:
        # 🔴 `pos` 留 NULL：变形形的词性是**原形的**，写在这儿就是第二份真值
        #    （`SCHEMA` §10.4 的同一条：派生值不与真值各存一份）。
        #    ⇒ `expect` 里 `pos: 0`，闸会盯着"没人偷偷给它们填词性"。
        s.executemany(
            "INSERT INTO dict (word, word_norm, is_lemma, pos) VALUES (?,?,0,NULL)",
            [(w, norm_ko(w)) for w in newlist])
        # 拿新 id：按**本次写库的边界**取，不靠"最大的 N 个"
        for r in s.execute("SELECT id, word FROM dict WHERE id > ?", (max_id_before,)):
            indict[r[1]] = r[0]

        buf = []
        n = 0
        for w, eref, fw, tags, i in iter_forms():
            wid = indict.get(fw)
            bid = indict.get(w)
            eid = inentry.get(eref)
            buf.append((wid, eid, "inflection", w, bid, label_zh(tags),
                        " ".join(sorted(tags)),
                        json.dumps(sorted(tags), ensure_ascii=False),
                        SRC, "%s#form:%d" % (eref, i)))
            if len(buf) >= BATCH:
                s.executemany(
                    "INSERT INTO inflection (word_id, entry_id, kind, base, base_id, "
                    "label_zh, desc_en, tags, src, src_ref) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    buf)
                n += len(buf)
                buf = []
                print("   …已写 %s 行" % format(n, ","))
        if buf:
            s.executemany(
                "INSERT INTO inflection (word_id, entry_id, kind, base, base_id, "
                "label_zh, desc_en, tags, src, src_ref) VALUES (?,?,?,?,?,?,?,?,?,?)",
                buf)

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("inflection 行数", q("SELECT COUNT(*) FROM inflection"), pairs),
        ("dict 行数", q("SELECT COUNT(*) FROM dict"), len(indict)),
        ("word_id 都指得到",
         q("SELECT COUNT(*) FROM inflection i LEFT JOIN dict d ON d.id=i.word_id "
           "WHERE d.id IS NULL"), 0),
        ("base_id 都指得到",
         q("SELECT COUNT(*) FROM inflection i LEFT JOIN dict d ON d.id=i.base_id "
           "WHERE d.id IS NULL"), 0),
        ("entry_id 都指得到",
         q("SELECT COUNT(*) FROM inflection i LEFT JOIN entry e ON e.id=i.entry_id "
           "WHERE e.id IS NULL"), 0),
        ("label_zh 都非空",
         q("SELECT COUNT(*) FROM inflection WHERE label_zh=''"), 0),
        # 🔴🔴 **这一条是本步存在的理由**：新收的词形必须条条有链。
        #    pt 正是这一条没守住 ⇒ 46.2% 空白页。
        ("新收的词形条条有变形链",
         q("SELECT COUNT(*) FROM dict d WHERE d.id > %d "
           "  AND NOT EXISTS (SELECT 1 FROM inflection i WHERE i.word_id=d.id)"
           % max_id_before), 0),
        # 变形形不许被写上词性（那是原形的属性）
        ("新收的词形 pos 全空",
         q("SELECT COUNT(*) FROM dict WHERE id > %d AND pos IS NOT NULL"
           % max_id_before), 0),
        # 🔴🔴 下面两条是**第一版漏掉、靠抽样才发现**的，补成回核让它们自己响：
        #   ① 同一条变形事实不许存多份（第一版有 31,896 行冗余＝7.3%，
        #      `요요하다` 的每个变形存了 11 遍，而八条回核**一条都没红**）
        ("没有冗余的变形行",
         q("SELECT COUNT(*) FROM (SELECT 1 FROM inflection "
           "GROUP BY base, word_id, tags HAVING COUNT(*)>1)"), 0),
        #   ② 词形必须是韩语（第一版把 `past: 가까왔다`、`interrogative`、
        #      `{{{stem1}}}다` 写进了 `dict.word`）
        ("新收的词形都是韩语",
         sum(1 for r in con.execute(
             "SELECT word FROM dict WHERE id > %d" % max_id_before)
             if not is_korean_form(r[0])), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-26s %10s（期望 %s）" % ("✅" if good else "🔴", name,
                                              format(got, ","), format(want, ",")))
    # 抽样：拿已知的用言看链对不对
    print("\n■ 抽样：`가깝다`（ㅂ불규칙）的变形链")
    for r in con.execute(
            "SELECT d.word, i.label_zh FROM inflection i JOIN dict d ON d.id=i.word_id "
            "WHERE i.base=? ORDER BY i.id LIMIT 8", ("가깝다",)):
        print("     %-12s %s" % r)
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
