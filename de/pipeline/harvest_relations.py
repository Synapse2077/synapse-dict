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
   **只认单个纯数字**，其余一律 `sense_id=NULL`（关系仍然收，只是挂在词上）。
   🔴 **判不出就说判不出，不猜** —— 猜错了是把关系接到错误的义项上，
     比不挂更伤（`[[verification-gates-not-sampling]]`：错配才是真灾难）。

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
    rows, stat, seen = [], Counter(), set()

    def take(w, sid, kind, tgt, tags, ref, ed):
        if not tgt:
            stat["丢：目标为空"] += 1
            return
        if tgt == w:
            stat["丢：自指（目标就是词头）"] += 1
            return
        key = (w, sid, kind, tgt)
        if key in seen:
            stat["重复（同词同义项同类型同目标）"] += 1
            return
        seen.add(key)
        rows.append((words[w], sid, kind, tgt,
                     json.dumps(tags, ensure_ascii=False) if tags else None,
                     0, "%s-edition" % ed, ref))
        stat["收下（%s 版）" % ed] += 1

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
                        sid, si = None, it.get("sense_index")
                        if ed == "de":
                            m = PURE_INT.match(str(si)) if si else None
                            if m:
                                k = int(m.group(1)) - 1      # 源里从 1 数起
                                if 0 <= k < len(senses):
                                    gl = ((senses[k].get("glosses") or [""])[0] or "").strip()
                                    sid = bridge.get((w, gl))
                                    stat["  de 下标解析成功" if sid
                                         else "  de 下标解析了但义项挂不回库"] += 1
                                else:
                                    stat["  de 下标越界"] += 1
                            elif si:
                                stat["  de 下标不是单个数字（1-3 / 1,2 之类），不猜"] += 1
                            else:
                                stat["  de 源头没给下标"] += 1
                        take(w, sid, kind, (it.get("word") or "").strip(),
                             it.get("tags"), "kk-%s:%s:%s:%d" % (ed, w, field, j), ed)

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
        ed = "de" if src == "de-edition" else "en"
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

    con.close()
    print("\n■ 将写入 sense_relation %s 行" % f(len(rows)))
    with dbtool.session("keep-v3-5c-relations", expect={"#sense_relation": len(rows)}) as s:
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
