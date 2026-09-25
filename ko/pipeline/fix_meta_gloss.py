#!/usr/bin/env python3
"""把「汉字表记」从释义栏搬到它该在的地方。2026-09-24。

═══ 这是在修什么 ═══
`sense_gloss` 里 `lang='zh'` 有 206,091 行，一直被当成「中文版白送的中文释义」
记在阶段表、欠账表和验收口径里。实测其中 **200,233 行（97.2%）长这样**：

    汉字或谚汉混合表记：환면상송（換面相訟）

它讲的是这个词**怎么写**，不是它**什么意思** —— 是**元描述**，不是释义。
真释义只有 5,858 条。⇒ 义项的中文覆盖率不是 74.09%，是 **2.11%**；
**195,030 个词形一条真释义都没有**（任何语言），而空白页闸报的是 6。

🔴 根因是同一个形式代理：**「有一行 gloss」被当成了「有释义」**。
   它从阶段 -2 的源盘点（「中文简体 195,265 有释义」）一路传到 4a 的记账、
   再传到阶段 5 的缺口计算 —— 三个阶段、三道闸，**没有一处问过那行 gloss 里装的是什么**。
⚠️ 逮到它的是抽样：给例句搭桥时随手打印 30 条对照，19 条是元描述
   （`[[criteria-from-meaning-not-form]]`／`[[proxy-metric-gets-optimized]]`）。

═══ 🔴 数据一条不丢 —— 这是用户 2026-09-24 的要求，也先验过了 ═══
这 200,233 行**在证据层 `sense_src` 里一字不差地存着 100%**（实测，零例外）。
⇒ 从出版层 `sense_gloss` 移走，丢失 **0 条**。两层义项模型建它就是为了这个。
但「不丢」只是底线：躺在证据层的一句散文里**没人用得上**，所以还要给它一个能被
查询、能上页面的家。

═══ 每一批的去处（一份数据一个家，不留两份真值）═══
    唯一汉字候选  182,131 → `entry.hanja` ＋ `entry.hanja_src`
        schema 决定②给它留的就是这个位置。目标 entry 由 `sense.entry_id` **指定**，
        不是推断；实测这批 entry 的 `hanja` 列**现在全是 NULL**，零覆盖零冲突。
    多候选       18,076 条 / 51,252 个候选 → `sense_relation.kind='hanja_spelling'`
        `금박（金箔 擒縛）` 是**源头自己没拆的同形异词**，不是异体字。
        🔴 决定②明文禁止在有多个候选时往单值列上断言一个 ——
          那会对读者说谎。也**不能**塞进 K2 留的 `alt_hanja`（那是同一个词的异体字）。
    动不了的         26 → 留在证据层与出版层**原样不动** ＋ 落账
                          `data/work/ko/meta_gloss_unparsed.tsv`
        7 条括号解析不出、7 条括号前的词形与词条对不上、
        **12 条是「元描述 ＋ 换行 ＋ 别的内容」，而粘着的那部分里有真释义和例句**
        （`전파탐지기 …（電波探知機）\\n雷達`）。与「134 个四样全空的不收」同一做法。

═══ 空掉的义项标 `hidden=1`，不删 ═══
元描述搬走后这 200,233 条 `sense` 一条 gloss 都没有了。**留着会在页面上渲染成
一条空的编号义项**，比没有更坏。⇒ 标 `hidden=1`（展示层契约检查已经在认这一列，
见 `apps/web/src/contract-check*.tsx` 的 `COALESCE(s.hidden,0)=0`）。
🔴 **标而不删**是有意的：`[[prefer-reversible-designs]]`。`sense_src` 那一侧的认领
   （`sense_id`）保持不动，一旦将来这些词拿到了真释义，取消 hidden 即可。

═══ 🔴 回核的期望值从**另一个来源**重算 ═══
写入侧读 `sense_gloss`，回核侧读 `sense_src` —— **同一批文本、两条独立路径**。
`[[expectation-must-be-declared]]`：拿现状推期望，现状坏了期望跟着坏；
`fill_g2p_pronunciation` 的 `--rebuild` 就是这么删了 18 万行而七条回核全绿的。

跑（在仓库根）：
    python3 -u ko/pipeline/fix_meta_gloss.py
    python3 -u ko/pipeline/fix_meta_gloss.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import re
import sqlite3

import dbtool
import paths

f = lambda n: format(n, ",")

KIND = "hanja_spelling"
BATCH = 20000

# 🔴 判据按**含义**写：这一行讲的是「这个词怎么写」。
#    源头没有任何结构标记（`tags`/`raw_tags` 全 None，逐条回源看过），
#    唯一的证据就是这个模板，所以判据只能落在文本上 —— 但**两个方向都验过**：
#      判为元描述的随机 8 条全是元描述；判为真释义的随机 12 条全是真释义。
#    ⚠️ 简/繁、「表记/表記/标记/標記」四种写法都出现过，四种都要认。
META = re.compile(r"^(汉字|漢字)[^：:]{0,12}(表记|表記|标记|標記)\s*[：:]\s*(.+)$")
# 括号有全角/半角/书名号三种：（）()〈〉
BR = re.compile(r"^(\S+?)\s*[（(〈]([^）)〉]+)[）)〉]\s*$")


def parse(word, text):
    """→ (候选汉字列表, 失败原因)。**只有两边都对得上才算解析成功。**

    🔴 `head != word` 这一条是必须的：括号前的词形必须与词条本身一致，
       否则这行讲的是**别的词**怎么写，挂在这儿就是错配
       （`[[primary-key-is-not-enough]]`：认领得上不等于配对对）。
    """
    # 🔴🔴 **多行的不算**。源头有 12 行是「元描述 ＋ 换行 ＋ 别的内容」，
    #    而粘着的那部分里**有真货**：
    #        전파탐지기 …（電波探知機）\n雷達                  ← 真中文释义
    #        욕설어    …（辱說語）\n意爲粗言猥語或用於侮辱…      ← 真中文释义
    #        수강      …（受講）\n#:: 우리는…  我們上漢語課呢。  ← 例句＋译文
    #    它们**不能删**，也不能只删一半（谁来保证切得干净）。⇒ 整条不动、落账。
    #    ⚠️ 这一条是本脚本 dry 跑时逮到的：分类判据（正则）比删除判据（LIKE）窄 12 条，
    #      而**删除用的是宽的那个** —— 又一次 `[[criteria-narrower-than-you-think]]`。
    #      ⇒ 现在删除按主键逐条删**我分类过的那些行**，不按 LIKE 扫。
    first, _, rest = text.partition("\n")
    m = META.match(first)
    if not m:
        return None, "不是元描述"
    if rest.strip():
        return None, "元描述后面粘着别的内容（里面可能有真释义或例句）"
    b = BR.match(m.group(3).strip())
    if not b:
        return None, "括号解析不出"
    if b.group(1) != word:
        return None, "括号前的词形与词条对不上"
    cands = [c for c in b.group(2).split() if c]
    return (cands, None) if cands else (None, "括号里是空的")


def load(con):
    """读出版层里的元描述行。→ (uniq, multi, bad)"""
    rows = con.execute("""
        SELECT s.id, s.word_id, s.entry_id, d.word, g.text, g.kind, g.seq,
               ss.src, ss.src_ref
          FROM sense s
          JOIN dict d        ON d.id = s.word_id
          JOIN sense_gloss g ON g.sense_id = s.id
          LEFT JOIN sense_src ss ON ss.sense_id = s.id AND ss.text = g.text
         WHERE g.lang = 'zh'
    """).fetchall()
    uniq, multi, bad = [], [], []
    for sid, wid, eid, word, text, gkind, gseq, src, sref in rows:
        cands, why = parse(word, text)
        if why == "不是元描述":
            continue
        if why:
            bad.append((word, text, why))
            continue
        if eid is None:                      # 实测 0 条，留着是因为它一旦发生就必须停
            bad.append((word, text, "sense.entry_id 是 NULL"))
            continue
        rec = (sid, wid, eid, word, gkind, gseq, src or "zh-edition", sref, cands)
        (uniq if len(cands) == 1 else multi).append(rec)
    return uniq, multi, bad


def expected_from_evidence(con):
    """🔴 **回核用的期望值，从证据层重算** —— 与写入侧读的不是同一张表。

    写入侧读 `sense_gloss`（出版层），这儿读 `sense_src`（证据层）。
    两条路径落在同一批文本上，但**不共用任何一次计算**。
    """
    n_uniq = n_multi = n_cand = n_bad = 0
    seen = set()
    for wid, word, text in con.execute("""
            SELECT ss.word_id, d.word, ss.text FROM sense_src ss
              JOIN dict d ON d.id = ss.word_id
             WHERE ss.sense_id IS NOT NULL"""):
        cands, why = parse(word, text)
        if why == "不是元描述":
            continue
        if why:
            n_bad += 1
            continue
        if len(cands) == 1:
            n_uniq += 1
        else:
            n_multi += 1
            for c in cands:
                if (wid, c) not in seen:      # 关系层有 UNIQUE(word_id,sense_id,kind,target)
                    seen.add((wid, c))
                    n_cand += 1
    return n_uniq, n_multi, n_cand, n_bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    uniq, multi, bad = load(con)

    print("■ 出版层 `sense_gloss` 里的元描述")
    print("   %-34s %9s" % ("唯一汉字候选 → entry.hanja", f(len(uniq))))
    print("   %-34s %9s" % ("多候选 → sense_relation", f(len(multi))))
    print("   %-34s %9s" % ("🔴 解析不出（留在证据层、落账）", f(len(bad))))

    # ── 多候选拆成边。去重按关系层自己的主键口径 ──
    edges, seen = [], set()
    for sid, wid, eid, word, gkind, gseq, src, sref, cands in multi:
        for i, c in enumerate(cands):
            if (wid, c) in seen:
                continue
            seen.add((wid, c))
            edges.append((wid, None, KIND, c, src,
                          "%s#hanja:%d" % (sref or "%s:%s" % (src, word), i)))
    print("   %-34s %9s" % ("↑ 拆成关系边（去重后）", f(len(edges))))

    # ── 空掉的义项 ──
    touched = {r[0] for r in uniq} | {r[0] for r in multi}
    # 🔴 「搬走之后还剩不剩东西」**必须按真正要删的那批行算**，不能再用 LIKE ——
    #    那 12 行多行的不删，它们的义项当然还留着内容。用 LIKE 算会把它们误判成空、
    #    然后 `hidden=1` 把有内容的义项藏起来。**同一个宽判据，第二处。**
    # ⚠️ 也不能写成 `IN (200,000 个参数)`（SQLite 变量数有上限，当场撞到）⇒ 全取回来求差。
    delset = {(r[0], r[4], r[5]) for r in uniq + multi}   # (sense_id, kind, seq)
    still = set()
    for sid, gkind, gseq in con.execute(
            "SELECT sense_id, kind, seq FROM sense_gloss"):
        if sid in touched and (sid, gkind, gseq) not in delset:
            still.add(sid)
    empty = sorted(touched - still)
    print("   %-34s %9s" % ("搬走后一条 gloss 都不剩 ⇒ hidden=1", f(len(empty))))
    print("   %-34s %9s" % ("↑ 其中仍留着别的释义、不动", f(len(still))))

    # ── 🔴 期望值：从证据层独立重算 ──
    e_uniq, e_multi, e_cand, e_bad = expected_from_evidence(con)
    print("\n■ 🔴 从**证据层**独立重算的期望值（写入侧读的是出版层）")
    ok = True
    for name, got, want in [("唯一候选", len(uniq), e_uniq),
                            ("多候选", len(multi), e_multi),
                            ("关系边", len(edges), e_cand),
                            ("解析不出", len(bad), e_bad)]:
        mark = "✅" if got == want else "🔴"
        ok &= got == want
        print("   %s %-12s 出版层 %8s  证据层 %8s" % (mark, name, f(got), f(want)))
    if not ok:
        raise SystemExit("🔴 两条路径对不上 —— 先查清楚再写库，别绕过去")

    before = {t: con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
              for t in ("sense_gloss", "sense_relation")}
    before_hanja = con.execute(
        "SELECT COUNT(*) FROM entry WHERE hanja IS NOT NULL").fetchone()[0]
    con.close()

    if bad:
        p = paths.WORK / "meta_gloss_unparsed.tsv"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("# 元描述解析不出的行。2026-09-24。\n")
            fh.write("# 什么会推翻「不处理」这个决定：源头把模板改成结构化字段，\n")
            fh.write("#   或这个数从 14 涨到三位数（说明模板变体不止我认的这四种）。\n")
            for w, t, why in bad:
                fh.write("%s\t%s\t%s\n" % (w, t.replace("\t", " "), why))
        print("\n■ 落账 %s（%d 行）" % (p.relative_to(paths.ROOT), len(bad)))

    if not a.apply:
        print("\n（这是 dry 跑。加 --apply 才写库）")
        return

    with dbtool.session(
            "ko-move-meta-gloss-to-hanja",
            # 🔴 **列的变化也要逐列声明**，不只是行数。
            #    第一次跑 --apply 时我只声明了两个行数，闸当场拦下三列未声明的变化
            #    （`entry.hanja` / `entry.hanja_src` / `sense_relation.target`）——
            #    已按它给的命令回滚、补声明、重跑。
            #    ⭐ 这正是这道闸存在的理由：**声明写在动手之前，不是事后补理由**
            #      （`[[expectation-must-be-declared]]`）。
            expect={"#sense_gloss": -len(uniq) - len(multi),
                    "#sense_relation": len(edges),
                    "sense_relation.target": len(edges),
                    "entry.hanja": len(uniq),
                    "entry.hanja_src": len(uniq)},
            invalidates=[
                "🔴 **义项的中文覆盖率口径变了**：74.09% 那个数是把 200,233 条元描述"
                "当成了释义。真数是 2.11%（5,858/278,155）。任何对外报数、验收、"
                "账本闸都必须用**真释义**口径（P6 已改，且它现在如实报红）",
                "🔴 **空白页那个数（6）对这批词结构性失明** —— 它们靠「有 sense 行」"
                "＋「有读音」双双合法地绿着。`coverage.py` 已写明，并另加了一条"
                "「词元里有释义的占比」（实测 23.36%）",
                "展示层（阶段 9）：汉字表记要从**两处**取 —— `entry.hanja` 有值就用它；"
                "没值但有 `hanja_spelling` 边，显示候选集并标「未定」，"
                "**不许假装我们知道是哪一个**",
                "🔴 用户 2026-09-20 定的推翻条件**已经触发**（「空白页仍 >10% 总词形"
                "就回来重议出版那一半」）：76.6% 的词元没有释义。这一条归用户定",
            ]) as s:
        # ① entry.hanja
        s.executemany(
            "UPDATE entry SET hanja=?, hanja_src=? WHERE id=? AND hanja IS NULL",
            [(r[8][0], r[6], r[2]) for r in uniq])
        s.written += len(uniq)
        # ② 多候选 → 关系层
        for i in range(0, len(edges), BATCH):
            s.executemany(
                "INSERT OR IGNORE INTO sense_relation "
                "(word_id, sense_id, kind, target, src, src_ref) VALUES (?,?,?,?,?,?)",
                edges[i:i + BATCH])
            s.written += len(edges[i:i + BATCH])
        # ③ 出版层删掉元描述。
        # 🔴 **按主键逐条删我分类过的那些行**，不用 LIKE 扫 ——
        #    dry 跑当场逮到：LIKE 比分类判据宽 12 行，而那 12 行里粘着真释义和例句。
        #    判据只写一份、两个地方用同一份，才不会一宽一窄
        #    （`[[criteria-narrower-than-you-think]]`）。
        delkeys = [(r[0], r[4], r[5]) for r in uniq + multi]   # (sense_id, kind, seq)
        for i in range(0, len(delkeys), BATCH):
            s.executemany(
                "DELETE FROM sense_gloss WHERE sense_id=? AND lang='zh'"
                " AND kind=? AND seq=?", delkeys[i:i + BATCH])
            s.written += len(delkeys[i:i + BATCH])
        # ④ 空掉的义项标 hidden
        for i in range(0, len(empty), BATCH):
            chunk = empty[i:i + BATCH]
            s.execute("UPDATE sense SET hidden=1 WHERE id IN (%s)"
                      % ",".join("?" * len(chunk)), tuple(chunk))
            s.written += len(chunk)

    # ── 写后回核：**每一个数都从库里按口径重算**，不用上面任何一个 len(...) ──
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda sql: con.execute(sql).fetchone()[0]
    left = q("SELECT COUNT(*) FROM sense_gloss WHERE lang='zh'"
             " AND (text LIKE '汉字%' OR text LIKE '漢字%')"
             " AND (text LIKE '%表记：%' OR text LIKE '%表記：%'"
             "   OR text LIKE '%标记：%' OR text LIKE '%標記：%')")
    now_hanja = q("SELECT COUNT(*) FROM entry WHERE hanja IS NOT NULL")
    now_edge = q("SELECT COUNT(*) FROM sense_relation WHERE kind='%s'" % KIND)
    now_gloss = q("SELECT COUNT(*) FROM sense_gloss")
    now_hidden = q("SELECT COUNT(*) FROM sense WHERE hidden=1")
    real_zh = q("SELECT COUNT(*) FROM sense_gloss WHERE lang='zh'")
    empty_pub = q("SELECT COUNT(*) FROM sense s WHERE COALESCE(s.hidden,0)=0"
                  " AND NOT EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id)")
    print("\n■ 写后回核（每个数都是从库里按口径重算的）")
    checks = [
        # 🔴 期望**不是 0** —— 那 26 条（7 括号解析不出 ／ 7 词形对不上 ／
        #    12 后面粘着真释义和例句）是**有意留下的**，它们照样命中 LIKE。
        #    ⚠️ 第一版这条写了 0，回核当场红 —— **红的是我的期望值，不是数据**。
        #    期望值取 `e_bad`（从证据层重算的那条路径），不是这儿现数的。
        ("出版层还剩多少元描述（＝有意留下的那批）", left, e_bad),
        ("entry.hanja 条数", now_hanja, before_hanja + e_uniq),
        ("hanja_spelling 边数", now_edge, e_cand),
        ("sense_gloss 总行数", now_gloss, before["sense_gloss"] - e_uniq - e_multi),
        ("🔴 没有任何 gloss 而仍在出版的义项", empty_pub, 0),
    ]
    red = 0
    for name, got, want in checks:
        mark = "✅" if got == want else "🔴"
        red += got != want
        print("   %s %-34s %9s  期望 %9s" % (mark, name, f(got), f(want)))
    print("   ·  %-34s %9s" % ("hidden=1 的义项", f(now_hidden)))
    print("   ·  %-34s %9s  ← **全是真释义了**"
          % ("lang='zh' 的 sense_gloss", f(real_zh)))
    con.close()
    if red:
        raise SystemExit("🔴 回核 %d 条红" % red)


if __name__ == "__main__":
    main()
