#!/usr/bin/env python3
"""给「各版都没有释义」的词头按构词推中文释义。2026-08-17。

═══ 🔴 先读这一段：这批数据的错误率是已知且很高的 ═══
`probes/blind_gloss_pilot.py` 盲测（200 条有真值的同类词，我逐条读）：

    flash 关思考   对 49%  不准 25%  🔴错 25%   假词被编释义  7/30
    flash 开思考    —       —      ~16%      （贵 13 倍）  6/30
    豆包 pro       对 61%  不准  8%  🔴错 24%              16/30

**三家的真错率都卡在 24–25%，换模型/开思考都不动** —— 非复合词的意思不在词形里。
模型自报的把握度 `c` 也不能当过滤器（c=2 那批仍有 18.5% 是错的）。

⇒ 我的建议是不填、留空白（对照：本词典其余部分实测加权错误率 **1.2%**）。
  **用户 2026-08-17 两次明确要求全部填上**，本脚本执行该决定。

🔴 因此本步产出必须**整批可撤回**：`sense_gloss.src` 一律
   `deepseek-v4-flash:blind-morph:c<把握度>`，一条 SQL 就能筛出或删掉：

       DELETE FROM sense_gloss WHERE src LIKE 'deepseek-v4-flash:blind-morph%';
       -- 只留高把握度：… AND src LIKE '%:c1'   ← 删掉低把握度那批

═══ 为什么不给词根义项表（试过了，更差）═══
`ri-` 复合那族我做过对照：把词根的全部中文义项喂进去，让模型挑一支。
同 34 条实测 **盲测错 14.7% / 给义项表错 17.6%** —— 没有改进，反而把模型
锚死在词根第一支（`rinfrangere` 盲测答对「使光折射」，给了表反而答「再次打碎」）。
⇒ 统一走盲测一条路，不搞两套。（`prompt-beats-model-choice`：改法也要能量出来。）

用法（在 it/ 目录下）：
    python3 pipeline/fill_blind_gloss.py            # 干跑
    python3 pipeline/fill_blind_gloss.py --apply
    python3 pipeline/fill_blind_gloss.py --verify
"""
import argparse
import asyncio
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "probes"))

import dbtool     # noqa: E402
import ds_batch   # noqa: E402
import paths      # noqa: E402
from build import POS_MAP   # noqa: E402
from blind_gloss_pilot import SYS   # noqa: E402  🔴 与盲测**同一条 prompt**，否则那把尺子不作数

# ═══ 🔴 2026-08-17 第二轮：SYS 的两处自伤（第一轮弃权 446 条，消融实验分离出来的）═══
#
#   A 原样                 6 个样本全部弃权
#   B 单条送（批大小 1）      全部弃权            ⇒ 不是批量的问题
#   C 只删「可能有假词」那条   galvanizzzato ✅ shreddare ✅
#   D 只改「不强转动词」      Falconidi ✅ SARS ✅ -coltura ✅ shreddare ✅
#
# 因① `scan()` 里 `pos or "v"` 把 `dict.pos` 为空的 154 个词（分类学名/缩写/词缀）
#      都告知模型"这是动词"。模型看出矛盾就按规则弃权。
# 因② 我为负控写的规则「输入里可能混有并不存在的词」把**拼写错误的真词**一起挡了：
#      `galvanizzzato`（三个 z，其实是 galvanizzato 的误写）长得就像我编的假词。
#
# ⚠️ 不能直接换成"朴素提问"：实测那样会把 `shreddare` 瞎猜成「应为 stridere」。
#    防编造要留着，只是把"假词"和"拼错的真词"分开说。
# ⚠️ 本 SYS **与盲测那把尺子不是同一条**（那条量的是动词族，25% 错率仍以它为准）。
#    残差 446 条数量小，直接由我逐条读验收。
SYS_V2 = SYS.replace(
    "5. **输入里可能混有并不存在的词**。遇到推不出、也不像真词的，必须 c=0、zh 留空。",
    "5. 输入里可能有**拼写错误的真词**（如 `galvanizzzato` 是 `galvanizzato` 的误写），\n"
    "   按最可能对应的正确词条解释，并在 m 里注明「拼写错误，应为 X」。\n"
    "6. 输入里也可能混有**并不存在的词**。既推不出、也找不到对应真词的，必须 c=0、zh 留空。\n"
    "   ⚠️ 只是生僻、或只是拼错，都**不算**不存在。",
).replace("6. 严格只返回", "7. 严格只返回")
SYS_V2 = SYS_V2.replace(
    "下面每一行是一个意大利语词条，只给出词形和词性，**没有任何释义来源**。",
    "下面每一行是一个意大利语词条，给出词形和词性，**没有任何释义来源**。\n"
    "词性可能是 `unknown`（源头没标），那时**不要假定它是动词** —— 它可能是"
    "生物分类名（`Falconidi` 隼科）、缩写（`SARS`）、词缀（`-coltura`）或专名。")

WORK = paths.DATA / "work" / "it"
OUT = WORK / "blind_gloss_fill.jsonl"
SRC = "deepseek-v4-flash:blind-morph"


def scan(con):
    """→ [(word_id, 词形, 展示短码词性)]，一条释义、一条证据都没有的 lemma。

    🔴 必须排掉**本身是变形**的行（`inflection.word_id` 里有它）。
       第一版没排，4,963 条里混进 `usa`(usare 的变位) / `angola`(angolare 的变位) /
       `mali`(male 的复数) / `ore`(ora 的复数) 这类 **1,377 个** —— 今天刚查明
       它们不是"缺释义"，而是变形，内容在原形那一行（见 `case-folding-contaminates-columns`）。
       给变形编一条独立释义，等于凭空造出一个词条。
    """
    rows = []
    for wid, w, pos in con.execute("""
            SELECT d.id, d.word, d.pos FROM dict d
            WHERE d.is_lemma=1
              AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)
              AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id)
              AND NOT EXISTS(SELECT 1 FROM sense_src x WHERE x.word_id=d.id)"""):
        rows.append((wid, w, pos or "unknown"))
    # 意语版占位符那批：有证据（`definizione mancante`）但没出版义项
    for wid, w, pos in con.execute("""
            SELECT d.id, d.word, d.pos FROM dict d
            WHERE d.is_lemma=1
              AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)
              AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id
                             AND COALESCE(s.hidden,0)=0)
              AND EXISTS(SELECT 1 FROM sense_src x WHERE x.word_id=d.id)"""):
        rows.append((wid, w, pos or "unknown"))
    return rows


def entry_of(con):
    e = {}
    for eid, wid, pos in con.execute("SELECT id, word_id, pos FROM entry"):
        e.setdefault(wid, (eid, POS_MAP.get(pos, pos)))
    return e


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    left = len(scan(con))
    checks = [
        ("🔴 本步中文不许为空",
         q("SELECT count(*) FROM sense_gloss WHERE src LIKE '%s%%' "
           "AND trim(COALESCE(text,''))=''" % SRC), 0),
        ("🔴 每条义项只有一条本步中文",
         q("SELECT count(*) FROM (SELECT sense_id FROM sense_gloss "
           "WHERE src LIKE '%s%%' GROUP BY sense_id HAVING count(*)>1)" % SRC), 0),
        # 🔴 整批可撤回是本步的安全绳：src 必须带把握度后缀，一条都不能漏
        ("🔴 src 一律带 :c<把握度> 后缀（撤回/分档的唯一抓手）",
         q("SELECT count(*) FROM sense_gloss WHERE src LIKE '%s%%' "
           "AND src NOT IN ('%s:c1','%s:c2')" % (SRC, SRC, SRC)), 0),
        # 🔴 不许覆盖任何已有释义
        ("🔴 没有动过别的来源写的中文",
         q("SELECT count(*) FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
           "WHERE g.src LIKE '%s%%' AND EXISTS(SELECT 1 FROM sense_gloss h "
           "WHERE h.sense_id=g.sense_id AND h.lang='zh' AND h.src NOT LIKE '%s%%')"
           % (SRC, SRC)), 0),
        ("（记账）模型弃权、仍然没有释义的词头", left, left),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-46s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("apply", "verify"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    rows = scan(ro)
    f = lambda x: format(x, ",")
    print("■ 没有任何释义的词头 %s 个" % f(len(rows)))
    print("   词性分布 %s" % dict(Counter(r[2] for r in rows).most_common(8)))
    for wid, w, pos in rows[:6]:
        print("   %-24s %s" % (w[:24], pos))
    if not a.apply or not rows:
        ro.close()
        if not a.apply:
            print("\n(未加 --apply，不写库)")
        return 0

    B = 40
    p = [{"n": wid, "w": w, "pos": pos} for wid, w, pos in rows]
    batches, meta = [], []
    for i in range(0, len(p), B):
        batches.append(p[i:i + B])
        meta.append([(str(x["n"]), x["n"]) for x in p[i:i + B]])
    print("\n■ %s 条 / %s 批 / flash 关思考" % (f(len(p)), f(len(batches))))
    tok = asyncio.run(ds_batch.run(SYS_V2, batches, meta, OUT, mode="flash",
                                   conc=10, every=10, thinking="disabled"))
    print("■ token %s" % format(tok, ","))

    ans = {}
    for line in OUT.open(encoding="utf-8"):
        r = json.loads(line)
        zh = (r.get("zh") or "").strip()
        c = r.get("c")
        if zh and c in (1, 2):
            ans[r["id"]] = (zh, c)
    print("\n■ 模型给出释义 %s / %s（其余弃权，保持空白）" % (f(len(ans)), f(len(rows))))
    print("   把握度分布 %s" % dict(Counter(c for _, c in ans.values())))
    ent = entry_of(ro)
    # 🔴 同 `fill_from_en_edition`：意语版占位符那批有 hidden=1 的义项占着 rank 1，
    #    `sense` 上是 UNIQUE(word_id, rank)，硬写 1 会 IntegrityError。
    rank = {}
    for wid, mx in ro.execute("SELECT word_id, max(rank) FROM sense GROUP BY word_id"):
        rank[wid] = mx
    ro.close()
    todo = [(wid, w, pos, ans[wid][0], ans[wid][1]) for wid, w, pos in rows if wid in ans]
    with dbtool.session("fill-blind-gloss",
                        expect={"__rows__": 0, "#sense": len(todo),
                                "#sense_gloss": len(todo)}) as s:
        for wid, w, pos, zh, c in todo:
            eid, epos = ent.get(wid, (None, pos if pos != "unknown" else None))
            rank[wid] = rank.get(wid, 0) + 1
            cur = s.execute("INSERT INTO sense (word_id, rank, pos, entry_id) "
                            "VALUES (?,?,?,?)", (wid, rank[wid], epos, eid))
            s.execute("INSERT INTO sense_gloss (sense_id, lang, kind, seq, text, src) "
                      "VALUES (?, 'zh', 'equivalent', 0, ?, ?)",
                      (cur.lastrowid, zh, "%s:c%d" % (SRC, c)))
    print("■ 已补 %s 条" % f(len(todo)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
