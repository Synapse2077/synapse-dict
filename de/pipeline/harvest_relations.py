#!/usr/bin/env python3
"""阶段 5c —— 收割德语版语义关系 → `sense_relation`。2026-09-03。

═══ 源头长什么样（实测 20 万条目）═══
关系挂在**条目级**，但每条带 `sense_index` 指向该条目的第几条义项：

    "synonyms": [{"word": "Gejohle", "sense_index": "1"}]

    hyponyms 188,679 ／ derived 177,156 ／ synonyms 103,025 ／ hypernyms 62,515
    coordinate_terms 47,338 ／ antonyms 44,741 ／ expressions 12,456
    meronyms 2,474 ／ proverbs 1,034 ／ related 951 ／ holonyms 250

═══ 🔴 下标怎么用才安全 ═══
`[[model-answer-files-key-by-id]]`：按「第几条」存的东西，重跑时会贴到别的义项上。
**这里可以用，因为下标不过夜**：扫描时当场把 `sense_index` 解析成
**这个条目自己的** `senses[i]`，取它的德语释义原文，再用
**(词形, 德语释义原文) 逐字节**挂回我们的库 —— 与阶段 5a 例句同一座桥。
落库存的是 `sense_id`，不是下标。

⚠️ `sense_index` 有多种写法（`"1"` / `"1-3"` / `"1, 2"` / 缺失）。
   🔴 **判不出就说判不出，不猜** —— 猜错了是把关系接到错误的义项上，
     比不挂更伤（`[[verification-gates-not-sampling]]`：错配才是真灾难）。
   ⚠️ **2026-09-04 修正：`1-3` / `1,2` 不是"猜"，是源头写清楚了的。**
     第一版只认单个纯数字，把 26,950 条**带着明确义项归属**的关系降级成词级显示 ——
     判据「不猜」是对的，但「多值＝在猜」这一步是错的。区间和列表都是确定写法，
     只有跨度 >20 那种才当"这一栏被写进了别的东西"丢掉。
     ⇒ 一条源头关系可以落成**多行**（`1-3` 说的是三条义项都有这个关系）。

═══ 🔴 关系是源头的事实，不绑在"我能不能挂上义项"上 ═══
`[[dont-gate-facts-on-my-uncertainty]]`（2026-09-01 阶段 2a 刚犯过）：
我把「写不写关系」绑在了「拼不拼得出中文」上，8 个词形的指针整个掉地上。
⇒ 这里 `sense_id` 挂不上**照样写关系行**，只是 `sense_id` 留 NULL。

═══ 判据：哪些不收 ═══
① 目标词为空。
② 目标就是词头自己（自指，没有信息量）。
③ ⚠️ **不检查目标在不在我们库里** —— 目标存原样字符串（表结构就是这么设计的：
   `target TEXT NOT NULL, -- 目标词形原样，不解析成外键`）。
   库里暂时没有的词，阶段 3 收词残差里还有，展示层查不到就不显示链接。

用法（在 de/ 目录下）：
    python3 -u pipeline/harvest_relations.py           # 干跑
    python3 -u pipeline/harvest_relations.py --apply
"""
import argparse
import gzip
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbtool                                    # noqa: E402
import paths                                     # noqa: E402
from intake_edition_words import EDITIONS         # noqa: E402

f = lambda n: format(n, ",")
SRC = "de-edition"

# 源字段 → 我们的 kind。**单数形式**，与阶段 2a 写进去的 `alt_of` 同一套值域。
KIND = {
    "synonyms": "synonym",
    "antonyms": "antonym",
    "hypernyms": "hypernym",
    "hyponyms": "hyponym",
    "holonyms": "holonym",
    "meronyms": "meronym",
    "coordinate_terms": "coordinate",
    "derived": "derived",
    "related": "related",
    "expressions": "expression",
    "proverbs": "proverb",
    "troponyms": "troponym",
}
PURE_INT = re.compile(r"^\s*(\d+)\s*$")
# `sense_index` 的多值写法：`1-3`、`1, 2`、`2、4`。**2026-09-04 之前一律"不猜"**，
# 于是 26,950 条带着明确义项归属的关系被降级成词级显示。它们不是猜的 —— 源头写得很清楚。
MULTI_INT = re.compile(r"^\s*\d+(\s*[-–,、]\s*\d+)+\s*$")


def sense_indexes(si, n):
    """`sense_index` → 0 起的义项下标列表。认不了返回 None，越界返回 []。

    🔴 **不做启发式**：只认「纯数字」「区间」「逗号/顿号列表」三种确定写法。
       区间跨度 >20 一律不认 —— 那种十有八九是把别的东西写进了这一栏。
    """
    s = str(si).strip()
    if PURE_INT.match(s):
        k = int(s) - 1
        return [k] if 0 <= k < n else []
    if not MULTI_INT.match(s):
        return None
    out = []
    for part in re.split(r"[,、]", s):
        part = part.strip()
        if "-" in part or "–" in part:
            try:
                a, b = [int(x) for x in re.split(r"[-–]", part)]
            except Exception:
                return None
            if b < a or b - a > 20:
                return None
            out += list(range(a - 1, b))
        else:
            try:
                out.append(int(part) - 1)
            except Exception:
                return None
    return [k for k in out if 0 <= k < n]


def opener(p):
    p = Path(p)
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def harvest(words, bridges):
    """→ (rows, stat)。bridges = {版本: {(词形, 该版释义原文): sense_id}}

    🔴 **两版的关系挂法不一样，判据必须分开写**（实测，不是照搬）：
        德语版  关系在**条目级**，每条带 `sense_index` 指向该条目的第几条义项
        英文版  关系**义项级**（直接挂在 sense 对象上，没有下标）＋ 条目级各一份
    ⇒ 德语版要解析下标，英文版不用；英文版的条目级那份挂不到义项，`sense_id=NULL`。

    ⭐ **两版都要收**，因为两版各自只挂得回**自己建的那批义项**：
       库里 260,828 条义项 ＝ 德语版 135,179（阶段 1.5a）＋ 英文版 125,649（七月建库）。
       只收德语版，48 万条关系挂不上义项 —— 不是数据缺，是桥不对。
    """
    rows, stat, seen = [], Counter(), {}

    def take(w, sid, kind, tgt, tags, ref, ed, hidden=0):
        if not tgt:
            stat["丢：目标为空"] += 1
            return
        if tgt == w:
            stat["丢：自指（目标就是词头）"] += 1
            return
        key = (w, sid, kind, tgt)
        if key in seen:
            # 🔴 去重键里**没有** `hidden`，而 UNIQUE 约束也没有 —— 同一个键只能留一行。
            #    ⇒ 撞键时**可见的赢**：先来一条 hidden 再来一条可见，不能因为
            #      "先到先得"就把该展示的那条挡掉（这个顺序完全取决于源头字段的遍历
            #      顺序，是个隐含契约，正是要在这里拆掉的那种）。
            i = seen[key]
            if not hidden and rows[i][5]:
                rows[i] = rows[i][:5] + (0,) + rows[i][6:]
                stat["撞键：hidden 被可见的顶掉"] += 1
            else:
                stat["重复（同词同义项同类型同目标）"] += 1
            return
        seen[key] = len(rows)
        rows.append((words[w], sid, kind, tgt,
                     json.dumps(tags, ensure_ascii=False) if tags else None,
                     hidden, "%s-edition" % ed, ref))
        stat["收下（%s 版）%s" % (ed, "・hidden" if hidden else "")] += 1

    for ed in ("de", "en"):
        path, need_filter = EDITIONS[ed]
        bridge = bridges[ed]
        print("   扫 %s 版…" % ed)
        with opener(path) as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if need_filter and e.get("lang_code") != "de":
                    continue
                w = e.get("word") or ""
                if w not in words:
                    continue
                senses = e.get("senses") or []

                # ── 条目级 ──
                for field, kind in KIND.items():
                    for j, it in enumerate(e.get(field) or []):
                        stat["源头关系条数"] += 1
                        si = it.get("sense_index")
                        tgt = (it.get("word") or "").strip()
                        ref = "kk-%s:%s:%s:%d" % (ed, w, field, j)
                        if ed != "de" or not si:
                            if ed == "de":
                                stat["  de 源头没给下标（词级显示是对的）"] += 1
                            take(w, None, kind, tgt, it.get("tags"), ref, ed)
                            continue
                        ks = sense_indexes(si, len(senses))
                        if ks is None:
                            stat["  de 下标写法认不了"] += 1
                            take(w, None, kind, tgt, it.get("tags"), ref, ed)
                            continue
                        if not ks:
                            stat["  de 下标越界"] += 1
                            take(w, None, kind, tgt, it.get("tags"), ref, ed)
                            continue
                        # 🔴 **一条源头关系可以落成多行** —— `sense_index: "1-3"` 说的是
                        #    「这三条义项都有这个关系」，不是「随便挑一条」。
                        sids = [bridge.get((w, ((senses[k].get("glosses") or [""])[0] or "").strip()))
                                for k in ks]
                        got = [x for x in sids if x]
                        if got:
                            stat["  de 下标解析成功" if len(got) == len(ks)
                                 else "  de 下标解析成功（部分义项我们没收）"] += 1
                            for sid in got:
                                take(w, sid, kind, tgt, it.get("tags"), ref, ed)
                            continue
                        # 🔴🔴 **源头说了是第 N 义的关系，而第 N 义我们没收** ⇒ `hidden=1`。
                        #    这一族 43,424 条，`Haus` 就在里面：德语版第 14 义是
                        #    「锤头的中段」，Auge/Bahn/Finne/Pinne 是锤头的其他部位 ——
                        #    完全正确的**锤子**词条内部关系。我们没收那一义，
                        #    于是页面上成了「Haus（房子）的反义词是 Auge（眼睛）」。
                        #    ⚠️ 不是删行：关系本身是源头的事实，删了就查不回来
                        #      （`[[dont-gate-facts-on-my-uncertainty]]`）。
                        #      但**「A 的第 14 义的反义词」不等于「A 的反义词」** ——
                        #      丢掉义项绑定会把一句真话变成一句假话。
                        #      ⇒ 留行、留证据、不展示。`hidden` 这一列就是为这件事建的。
                        stat["  🔴 de 下标解析了但这一义我们没收 ⇒ hidden"] += 1
                        take(w, None, kind, tgt, it.get("tags"), ref, ed, hidden=1)

                # ── 义项级（英文版才有）──
                for si_, s in enumerate(senses):
                    gl = ((s.get("glosses") or [""])[0] or "").strip()
                    sid = bridge.get((w, gl))
                    for field, kind in KIND.items():
                        for j, it in enumerate(s.get(field) or []):
                            stat["源头关系条数"] += 1
                            stat["  %s 义项级直接挂上" % ed if sid
                                 else "  %s 义项级挂不回库" % ed] += 1
                            take(w, sid, kind, (it.get("word") or "").strip(),
                                 it.get("tags"),
                                 "kk-%s:%s:s%d:%s:%d" % (ed, w, si_, field, j), ed)
    return rows, stat


def gate2(con, expect):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("sense_relation 行数 == 期望",
         q("SELECT count(*) FROM sense_relation"), expect["rows"]),
        ("🔴 孤儿（word_id 不在 dict）",
         q("SELECT count(*) FROM sense_relation r LEFT JOIN dict d ON d.id=r.word_id "
           "WHERE d.id IS NULL"), 0),
        ("🔴 sense_id 指向不存在的义项",
         q("SELECT count(*) FROM sense_relation r LEFT JOIN sense s ON s.id=r.sense_id "
           "WHERE r.sense_id IS NOT NULL AND s.id IS NULL"), 0),
        ("🔴 挂上的义项不属于这个词",
         q("SELECT count(*) FROM sense_relation r JOIN sense s ON s.id=r.sense_id "
           "WHERE s.word_id<>r.word_id"), 0),
        ("🔴 目标为空", q("SELECT count(*) FROM sense_relation WHERE TRIM(target)=''"), 0),
        ("🔴 自指（目标就是词头）",
         q("SELECT count(*) FROM sense_relation r JOIN dict d ON d.id=r.word_id "
           "WHERE d.word=r.target"), 0),
        ("kind 值域外",
         q("SELECT count(*) FROM sense_relation WHERE kind NOT IN "
           "('synonym','antonym','hypernym','hyponym','holonym','meronym',"
           " 'coordinate','derived','related','expression','proverb','troponym','alt_of')"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-44s %10s  期望 %s" % ("✓" if good else "🔴", name, f(got), f(want)))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = {w: i for w, i in con.execute("SELECT word, id FROM dict")}
    bridges = {"de": {}, "en": {}}
    for src, w, txt, sid in con.execute(
            "SELECT x.src, d.word, x.text, x.sense_id FROM sense_src x "
            "JOIN dict d ON d.id=x.word_id WHERE x.text IS NOT NULL AND x.sense_id IS NOT NULL"):
        # 🔴 2026-09-04 修：原来写死 `src == "de-edition"`，那是**只有一个德语来源**
        #    时写的判据。之后德语释义又多了两层 —— `de-edition-backfill`（1.5c
        #    唯一映射，36,134 条）和 `de-edition-adjudicated`（C29 裁决，47,604 条）——
        #    它们会被这一行判成"英文版"，于是：
        #      · 德语桥**一条都不长**（还是 135,179），重跑等于白跑；
        #      · 英文桥里混进 8.4 万条德语原文（配不上任何英文释义，无害但是错的）。
        #    ⇒ 判据要问「**这是不是德语版的释义**」，不是「它是不是那一个来源名」。
        #    这正是 `Haus` 反义词挂到「房子」上的原因：源头写着 `sense_index: 14`
        #    （第 14 义是**锤头的一部分**，Auge/Bahn/Finne/Pinne 都是锤子部件），
        #    桥接不上 ⇒ sense_id 留 NULL ⇒ 渲染成整个词的反义词。
        ed = "de" if src.startswith("de-edition") else "en"
        bridges[ed].setdefault((w, (txt or "").strip()), sid)
    n_before = con.execute("SELECT count(*) FROM sense_relation").fetchone()[0]
    print("■ 库内词形 %s ／ 桥：德语版 %s 条・英文版 %s 条 ／ 现有关系 %s（阶段 2a 的 alt_of）"
          % (f(len(words)), f(len(bridges["de"])), f(len(bridges["en"])), f(n_before)))

    print("\n■ 扫两版…")
    rows, stat = harvest(words, bridges)
    for k, v in stat.most_common():
        print("   %-40s %s" % (k, f(v)))

    byk = Counter(r[2] for r in rows)
    print("\n■ 按关系类型")
    for k, v in byk.most_common():
        print("   %-14s %s" % (k, f(v)))
    n_sid = sum(1 for r in rows if r[1])
    print("\n■ 收下 %s 条 ／ 挂上义项 %s（%.1f%%）／ 覆盖词形 %s"
          % (f(len(rows)), f(n_sid), 100.0 * n_sid / max(len(rows), 1),
             f(len({r[0] for r in rows}))))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    # 🔴 **重跑必须先删再写，`INSERT OR IGNORE` 单独用是错的。**
    #    UNIQUE 是 `(word_id, sense_id, kind, target)` —— `sense_id` 在键里。
    #    桥变好之后，同一条关系会带着**真的 sense_id** 再来一次，与库里那条
    #    `sense_id=NULL` 的**不冲突** ⇒ 两条并存，而旧的那条照样渲染成
    #    "整个词的反义词"。`OR IGNORE` 挡得住完全一样的行，挡不住"同一件事的两种说法"。
    #    ⇒ 本层是**纯派生**（扫 dump 重算），删掉本层再整层重写才是它该有的语义。
    #
    # 🔴🔴 **删的范围按 `kind` 圈，不按 `src` 圈。** 第一版我写的是
    #    `WHERE src IN ('de-edition','en-edition')` ——「阶段 2a 的 alt_of 是另一层」，
    #    这句话对，但 **2a 写进去的 8,917 条 alt_of 用的正是 `en-edition` 这个 src**，
    #    于是一条不剩地被删掉了（账的闸当场报「2a alt_of 归位成的关系是 0」，
    #    已回滚重来）。
    #    ⚠️ 这和我同一次改动里刚修掉的那个 bug（`src == "de-edition"` 圈不住
    #      三个德语来源）**是同一个形状**：拿**来源名**去圈「这个产出器拥有哪些行」。
    #      来源名是给「这条数据是谁给的」用的，回答不了「这一层是谁写的」。
    #    ⇒ 判据换成「本产出器生产的 kind」，也就是 `KIND` 的值域本身 ——
    #      它已经在文件顶上声明过一次，这里 import 那一份，不另抄。
    own = sorted(set(KIND.values()))
    n_old = con.execute(
        "SELECT count(*) FROM sense_relation WHERE kind IN (%s)"
        % ",".join("?" * len(own)), own).fetchone()[0]
    con.close()
    print("\n■ 删旧 %s 行 ／ 写入 %s 行 ／ 净 %+d"
          % (f(n_old), f(len(rows)), len(rows) - n_old))
    with dbtool.session("keep-v3-5c-relations",
                        expect={"#sense_relation": len(rows) - n_old}) as s:
        s.execute("DELETE FROM sense_relation WHERE kind IN (%s)"
                  % ",".join("?" * len(own)), own)
        s.executemany(
            "INSERT OR IGNORE INTO sense_relation "
            "(word_id,sense_id,kind,target,tags,hidden,src,src_ref) "
            "VALUES (?,?,?,?,?,?,?,?)", rows)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n = con.execute("SELECT count(*) FROM sense_relation").fetchone()[0]
    ok = gate2(con, {"rows": n})
    print("\n%s（新增 %s）" % ("✓ 闸②全过" if ok else "🔴 有闸未通过", f(n - n_before)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
