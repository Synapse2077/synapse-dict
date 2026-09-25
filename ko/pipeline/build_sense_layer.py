#!/usr/bin/env python3
"""阶段 1（第三步）：建义项三层 —— `sense_src` / `sense` / `sense_gloss`。2026-09-20。

`SCHEMA` §10.5：**entry 归属是阶段 1 的副产品** —— 阶段 1 本来就要建 `sense_src`
把每条义项锚回 dump 原文，复刻那个循环，每条义项落在哪个 entry 上就同时算出来了。
现在不算，将来要为它重新遍历一遍 dump。

═══ 盘子（英文版，已剔 romanization 条目）═══

    义项总数         81,941
      ├ 无 gloss      6,686  ( 8.2%)   不进任何表
      ├ 指针义项     17,780  (21.7%)   进 `sense_src`，**不进出版层**
      └ 🔴 真义项    57,475  (70.1%)   ← 出版、翻译的分母

🔴 **指针义项为什么进证据层、不进出版层**
韩语的指针大户是汉字表记：`犬` → "hanja form of 견（dog）"（form_of 15,768 ＋ alt_of 2,009）。
它们**不是释义**，是「这个词形指向那个词形」⇒ 内容属于关系层。
⚠️ 但这留下一个必须记账的后果：**只有指针义项的 15,871 个词形，此刻出版层是空的**
   —— `犬` 的页面要靠阶段 2 的关系层才有内容。
   这批词形正是 `BACKLOG` **B4**（词源桥只认"有已出版义项"的词条）会漏掉的那种，
   ko 做到阶段 7 时必须回来看这一条。

═══ 🔴 三个韩语特有的处理 ═══

① **层级 gloss**：5,858 条义项有 2 个 gloss（`glosses[0]` 是上位义、`glosses[-1]` 才是
   本义），2 条有 3 个。**两个都要存**（`seq` 区分）——
   `PLAYBOOK` 5.5 判据②：送模型翻译时不带上位义，`teléfono` 的 `mobile phone`
   会被译成孤零零的「手机」。丢掉上位义＝阶段 5 花钱时再也找不回来。

② 🔴🔴 **`pos_raw='syllable'` 的义项整批不进出版层 —— 它们是一张音→字对照表**

   这一条是**抽样看出来的，不是设计出来的**，过程值得记：
   第一版判据写的是「gloss 以 `More information` / `(MC reading` 开头就算元描述」，
   逮到 104 条，自以为处理完了。抽样反验时看见 `선` 的 rank 18 是
   `扇: fan\n(MC reading: 扇 (MC syen|syenH))` —— **元数据在中间，`startswith` 够不着**。
   回头全量量：

       以元数据开头（判据逮得到）      104
       🔴 元数据在中间（判据够不着）   1,713   ← 漏了 94%
       🔴 光一个汉字、没有释义         4,415   ← 这一类我压根没想到
       `汉字: 英文` 格式              2,084

   合计 **8,316 条，100% 落在 `pos=syllable` 上、100% 是单音节谚文词形**，
   集中在 343 个音节（`사` 171 条／`정` 154／`주` 131／`의` 94）。
   ⇒ 那不是义项，**是「这个音对应哪些汉字」的对照表**（한자음）。
     全放进出版层，`사` 的页面会出现 171 条只有一个汉字、没有释义的"义项"。

   **判据定成 `pos_raw == 'syllable'` 一刀切**，理由是两个方向都验过：
     · 正向：syllable 的 8,640 条义项里 **99.4% 是汉字音格式**（剩下 49 条是
       `* 且` 这种带星号前缀的同类）⇒ 一刀切**零误伤**；
     · 反向：非 syllable 条目里的汉字音格式义项只有 **18 条**（`난` 的 "亂: revolt"、
       `허` 的 "許: a surname"）——那些是**真义项**（汉字标注＋真释义），本来就该留下。
   🔴 用**源头给的 pos**，不是"gloss 长得像不像元数据"这种形式代理
     （`[[criteria-from-meaning-not-form]]`）。

   ⚠️ 代价说清楚：**42 个词形会因此变成零出版义项**（태/쾌/좌/려/끽…），
     它们只有汉字音义项。这批的页面内容来自 `hanja_reading` 表，不是空白页。

   ⚠️⚠️ 第一版判据那两个洞是同一个病的两种形态：
     `startswith` 太窄（`[[criteria-narrower-than-you-think]]`），
     而「光一个汉字」那 4,415 条**根本不在我的判据的想象范围里** ——
     抽样反验是唯一逮到它的路径。`PLAYBOOK`：不变量证明不了"改对了内容"。

③ **`sense_src.sense_id` 建库时就写**，不像 ja 拖到阶段 1e 才回填
   （ja 那时两版全是 NULL，回填花了一轮）。判据不是事后猜的：
   两张表在**同一个循环里**生成，认领关系是构造出来的，不是反解析出来的。

跑（在仓库根）：
    python3 -u ko/pipeline/build_sense_layer.py
    python3 -u ko/pipeline/build_sense_layer.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import json
import sqlite3

# 🔴 判据**只写一份**，住在 `criteria.py` —— 建外锚闸时发现它在三个文件里
#    各有一份（当时三份一样，但三份一定会漂，而闸正要靠它）。
#    `[[refactor-mindset-code-quality]]`／外锚闸必须 import 收词器用的那一份。
from criteria import is_pointer_sense, is_hanja_reading_sense  # noqa: F401

import dbtool
import paths

SRC = "en-edition"

# 🔴 汉字音条目的判据：**源头给的 pos**，不是 gloss 的形状。见文件头 ②。
#    只用于**出版层**过滤；证据层一条不少地收（`[[two-layer-sense-model]]`：证据层永不编辑），
#    并且这批会被 `build_hanja_reading.py` 抽进 `hanja_reading` 表。
HANJA_READING_POS = "syllable"




def scan(indict, inentry):
    """复刻建库那个循环 → (sense 行, sense_src 行, gloss 行, stat)。

    `inentry`: src_ref → entry.id。两张表在**同一个循环里**生成，
    所以 `sense_src` 认哪条 `sense` 是构造出来的，不是事后反解析的。
    """
    seen_entry = collections.Counter()
    rank_of = collections.Counter()            # word_id → 已分配到第几个 rank
    senses, srcs, glosses = [], [], []
    stat = collections.Counter()
    for line in open(paths.KK, encoding="utf-8"):
        o = json.loads(line)
        praw = o.get("pos")
        if praw == "romanization":
            continue
        w = o.get("word")
        if not w or not w.strip():
            continue
        wid = indict.get(w)
        if wid is None:
            continue                           # 阶段 1 推迟的无 gloss 汉字
        en_ = o.get("etymology_number")
        etym = str(en_) if en_ is not None else "0"
        k = (w, praw, etym)
        seq = seen_entry[k]
        seen_entry[k] += 1
        eref = "kk-ko:%s:%s:%s:%d" % (w, praw, etym, seq)
        eid = inentry.get(eref)
        if eid is None:
            stat["🔴 entry 认不到（不该发生）"] += 1
            continue
        for i, se in enumerate(o.get("senses") or []):
            g = se.get("glosses") or []
            if not g:
                stat["跳过·无 gloss"] += 1
                continue
            ptr = is_pointer_sense(se)
            meta = is_hanja_reading_sense(praw)
            # ── 出版层：真义项且非元描述 ──
            sid_placeholder = None
            if ptr:
                stat["指针·只进证据层"] += 1
            elif meta:
                stat["汉字音（syllable）·只进证据层"] += 1
            else:
                rank_of[wid] += 1
                sid_placeholder = len(senses)   # 先占位，插库后换成真 id
                senses.append((wid, eid, rank_of[wid], se.get("pos") or praw))
                # 文本层：层级 gloss 两条都存，`seq` 区分（0=上位义 … 末=本义）
                for j, txt in enumerate(g):
                    glosses.append((sid_placeholder, "en", "definition", j, txt, SRC))
                if len(g) > 1:
                    stat["层级 gloss（≥2 层）"] += 1
                stat["出版义项"] += 1
            # ── 证据层：**全收**，不做裁决 ──
            srcs.append((wid, sid_placeholder, SRC,
                         "%s#%d" % (eref, i), "en", g[-1],
                         json.dumps(se.get("tags") or [], ensure_ascii=False)
                         if se.get("tags") else None))
            stat["证据层"] += 1
    return senses, srcs, glosses, stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    indict = {r[1]: r[0] for r in con.execute("SELECT id, word FROM dict")}
    inentry = {r[1]: r[0] for r in con.execute("SELECT id, src_ref FROM entry")}
    have = con.execute("SELECT COUNT(*) FROM sense").fetchone()[0]
    con.close()
    print("■ dict %s 词形 ／ entry %s 条 ／ sense 现有 %s 行"
          % (format(len(indict), ","), format(len(inentry), ","), format(have, ",")))
    if have:
        raise SystemExit("🔴 sense 非空 —— 本步是首建。先确认是不是重复跑了。")

    senses, srcs, glosses, stat = scan(indict, inentry)
    print("■ 扫 %s" % paths.KK.name)
    for k, v in stat.most_common():
        print("   %-28s %9s" % (k, format(v, ",")))
    print("   %-28s %9s" % ("→ sense 行", format(len(senses), ",")))
    print("   %-28s %9s" % ("→ sense_src 行", format(len(srcs), ",")))
    print("   %-28s %9s" % ("→ sense_gloss 行", format(len(glosses), ",")))

    refs = collections.Counter(r[3] for r in srcs)
    dup = {k: c for k, c in refs.items() if c > 1}
    print("   %-28s %s" % ("sense_src.src_ref 唯一",
                           "✅" if not dup else "🔴 %d 重复 %s" % (len(dup), list(dup)[:3])))
    if dup:
        raise SystemExit("🔴 src_ref 重复")

    # rank 自证：每个词形的 rank 必须是 1..n 连续无洞
    per = collections.defaultdict(list)
    for wid, _eid, rank, _p in senses:
        per[wid].append(rank)
    bad = [w for w, rs in per.items() if sorted(rs) != list(range(1, len(rs) + 1))]
    print("   %-28s %s" % ("rank 从 1 连续无洞", "✅" if not bad else "🔴 %d 个词形不连续" % len(bad)))
    if bad:
        raise SystemExit("🔴 rank 不连续")

    # 🔴 **抽样给全量，不切片。**同一个错误今天犯了第二次（`build.py` 里刚修过）：
    #    `rows[:3000:277]` 这种写法看着像"均匀抽"，实际是**先截断再抽** ——
    #    而列表按字典序排、Unicode 里汉字（U+4E00+）全在谚文（U+AC00+）前面，
    #    于是抽出来 8 条全是生僻汉字（犭 彤 卩 珥 闈），**一个谚文词都没有**。
    #    `sample_check` 自己会 `random.sample`，喂给它全量就行。
    word_of = {i: w for w, i in indict.items()}
    gloss_of = {}
    for g in glosses:                      # 取每条义项的**末层** gloss（本义）
        if g[0] not in gloss_of or g[3] > gloss_of[g[0]][0]:
            gloss_of[g[0]] = (g[3], g[4])
    dbtool.sample_check(
        [(word_of[s[0]], s[2], gloss_of.get(idx, (0, "—"))[1][:46])
         for idx, s in enumerate(senses)],
        12, ("词形", "rank", "英文释义"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    with dbtool.session(
            "build-ko-sense",
            expect={"#sense": len(senses), "#sense_src": len(srcs),
                    "#sense_gloss": len(glosses),
                    "sense_src.sense_id": sum(1 for r in srcs if r[1] is not None)},
            invalidates=[]) as s:
        s.executemany(
            "INSERT INTO sense (word_id, entry_id, rank, pos) VALUES (?,?,?,?)", senses)
        # 占位下标 → 真 id。`sense` 是 AUTOINCREMENT 且本步是首批插入 ⇒
        # 🔴 **不靠"id 必然从 1 连续"这个假设**，回查一遍 (word_id, rank) → id
        idmap = {}
        for sid, wid, rank in s.execute("SELECT id, word_id, rank FROM sense"):
            idmap[(wid, rank)] = sid
        real = [idmap[(senses[i][0], senses[i][2])] for i in range(len(senses))]
        s.executemany(
            "INSERT INTO sense_src (word_id, sense_id, src, src_ref, lang, text, raw_tags) "
            "VALUES (?,?,?,?,?,?,?)",
            [(r[0], real[r[1]] if r[1] is not None else None, r[2], r[3], r[4], r[5], r[6])
             for r in srcs])
        s.executemany(
            "INSERT INTO sense_gloss (sense_id, lang, kind, seq, text, src) "
            "VALUES (?,?,?,?,?,?)",
            [(real[g[0]], g[1], g[2], g[3], g[4], g[5]) for g in glosses])

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("sense 行数", q("SELECT COUNT(*) FROM sense"), len(senses)),
        ("sense_src 行数", q("SELECT COUNT(*) FROM sense_src"), len(srcs)),
        ("sense_gloss 行数", q("SELECT COUNT(*) FROM sense_gloss"), len(glosses)),
        ("sense.entry_id 都指得到",
         q("SELECT COUNT(*) FROM sense s LEFT JOIN entry e ON e.id=s.entry_id "
           "WHERE e.id IS NULL"), 0),
        ("每条 sense 都有 gloss",
         q("SELECT COUNT(*) FROM sense s LEFT JOIN sense_gloss g ON g.sense_id=s.id "
           "WHERE g.sense_id IS NULL"), 0),
        # 🔴 **认领的配对要比内容，不比条数**（ja 阶段 1e 的教训：
        #    主键保证认领得上，不保证配对对）。证据层文本 = 该义项最后一层 gloss。
        ("认领配对逐条文本相同",
         q("SELECT COUNT(*) FROM sense_src ss JOIN sense_gloss g "
           "  ON g.sense_id=ss.sense_id "
           " AND g.seq=(SELECT MAX(seq) FROM sense_gloss WHERE sense_id=ss.sense_id) "
           "WHERE ss.sense_id IS NOT NULL AND ss.text<>g.text"), 0),
        ("指针义项没进出版层",
         q("SELECT COUNT(*) FROM sense_src WHERE sense_id IS NULL"),
         sum(1 for r in srcs if r[1] is None)),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-24s %10s（期望 %s）" % ("✅" if good else "🔴", name,
                                              format(got, ","), format(want, ",")))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
