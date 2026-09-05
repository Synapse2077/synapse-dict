#!/usr/bin/env python3
"""收尾单 C41 —— 把英文版的德语音标收进 `pronunciation`。de，2026-09-05。

═══ 🔴🔴 这一条推翻了收尾单上自己写的结论 ═══
账上原话：「`dict.ipa` 与 `pronunciation` **39% 实质分歧、且一面倒是 `dict.ipa` 错**
⇒ **有意不搬**」。今天用 `probes/c41_en_ipa.py` 把那句话拆开量，三个数都不支持它：

  ① **忠实度 99.7%**：七月的 `dict.ipa` 与**今天重收的英文版**逐字一致。
     ⇒ 那 39% 不是「七月收得糙」，两侧的差异确实是**英文版 vs 德语版**。
  ② **那个 39% 是我度量出来的假数**。它来自 `probes/ipa_conventions.py` 的
     「⑨ 其他」桶，而**那一桶是残差** —— 定义就是「上面几条消去器都解释不了的」。
     消去器少一条，这一桶就虚胖一块。补上四条**实测存在**的德语转写约定后：

         ˈaːbn̩t / ˈaːbənt     音节化辅音 vs 央元音+辅音
         ˈapˌmaxʊŋ / ˈapˌmaχʊŋ  ach-Laut 的两个字母
         ɔɪ̯ / ɔʏ̯、aɪ̯ / aɛ̯    同一个双元音的两种记法
         ˈapˌz̥aːɡə / ˈapˌsaːɡə  清化附加符；英文版还标送气 tʰ

     ⑨ 桶 **16.8% → 3.3%**（英文版 vs 德语版，55,382 个可比词形）。
  ③ 剩下的 3.3% 里**确实有真错**，抽 30 条真词看，约一半是：
         Agnes    德语版 ˈaɡnɛs      英文版 ˈax.nəs        ← 真错
         Aikido   德语版 aɪ̯ˈkiːdo   英文版 aɪˈkiːdəʊ      ← 那是英语读法
         Abwehr…  德语版 ˈapveːɐ̯…   英文版 ˈap.vɛɐ̯…      ← vor/wehr 元音错
     ⇒ **英文版音标的错误率约 1.5–3%**。

═══ 于是取舍变了 ═══
原来的取舍是「拿 39% 可疑值换空白」⇒ 不换（`FRAMEWORK §一`：错比缺更伤权威）。
真实的取舍是「拿 **1.5–3% 可疑值** 换 **12,846 个读者点进去一片空白的页面**」⇒ 换。
⚠️ 两个取舍的**输入数字差一个数量级，而结论相反** —— 这就是为什么
  `[[verify-before-claiming-confirmed]]` 说「改口径前回权威源」：
  我当时是拿自己的残差桶当权威源的。

═══ 为什么是「重收」不是「搬列」═══
🔴 **不从 `dict.ipa` 搬**，尽管两边 99.7% 一样。搬列会把
   `ipa_src='unknown'` 的 29,329 条原样搬进来 —— 那是**七月那条没有 provenance 的路**。
   重收拿到的是：`src='en-edition'`、`src_ref` 指到具体条目、`pos`、`region`、`tags`，
   而且**过了阶段 4 的四道过滤**（X-SAMPA／省略号占位符／音节切分冒充音标／空串），
   七月那次一道都没过。
   ⇒ 代价是覆盖率低：29,329 里今天的英文版只认得 12,846（43.8%）。
     其余 16,483 —— 12,328 个词形**根本不在今天的英文版德语条目里**
     （dump 是 8-31 重下的，七月那份已被保留策略清掉），
     4,155 个条目还在但没有可用音标。**这些不补**：
     拿一个来源已不可复验的旧值顶上，正是 `[[external-anchor-gates]]` 反对的事。

═══ 分层：空白页有意不补（判据同阶段 4）═══
    有真义项   47,453 缺 → 补 12,846
    只是变形  178,446 缺 → 顺带收（读者从变形页也点得到音标）
    空白页     49,297 缺 → **不补**，页面上除音标什么都没有，补了更像缺陷

用法（在 de/ 目录下）：
    python3 -u fixes/fill_ipa_from_en.py            # 干跑，只量不写
    python3 -u fixes/fill_ipa_from_en.py --apply
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import paths                                                    # noqa: E402
# 🔴 **四道过滤 import 阶段 4 那一份，一个字都不抄。** 手抄的代价见 `--drop-cols`
#    那轮：我自己写的切分器报了 43 条假红，而真的就在隔壁文件里。
from harvest_pronunciation import (bare, truncated,             # noqa: E402
                                   looks_like_spelling, REGION, gate2)

f = lambda n: format(n, ",")
SRC = "en-edition"


def targets(con):
    """→ ({词形: word_id}, 有真义项的词形, 只是变形的词形)。**空白页不进目标集。**"""
    rows = con.execute(
        "SELECT d.id, d.word, "
        "       EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id), "
        "       EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id) "
        "  FROM dict d "
        " WHERE NOT EXISTS(SELECT 1 FROM pronunciation p WHERE p.word_id=d.id)").fetchall()
    ids, sense, infl = {}, set(), set()
    for wid, w, has_s, has_i in rows:
        if has_s:
            sense.add(w)
        elif has_i:
            infl.add(w)
        else:
            continue                       # 空白页
        ids[w] = wid
    return ids, sense, infl


def harvest(keep):
    """扫英文版德语切片 → (rows, stat)。rows = [(词形, ipa, region, tags, pos, 下标)]"""
    rows, stat, tagc = [], Counter(), Counter()
    with open(paths.KK, encoding="utf-8") as fh:
        for line in fh:
            if '"sounds"' not in line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                stat["坏行"] += 1
                continue
            if e.get("lang_code") != "de":
                continue
            w = e.get("word") or ""
            if w not in keep:
                continue
            pos = e.get("pos") or None
            for i, s in enumerate(e.get("sounds") or []):
                raw = s.get("ipa")
                if not raw:
                    continue
                stat["源头 ipa 条数"] += 1
                tags = list(s.get("tags") or []) + list(s.get("raw_tags") or [])
                for t in tags:
                    tagc[t] += 1
                if any("SAMPA" in t.upper() for t in tags):
                    stat["🔴 丢弃：X-SAMPA 冒充 IPA"] += 1
                    continue
                v = bare(raw)
                if not v or truncated(v, w):
                    stat["🔴 丢弃：含省略号（占位符或半截）"] += 1
                    continue
                if looks_like_spelling(v, w):
                    stat["🔴 丢弃：音节切分/拼写冒充音标"] += 1
                    continue
                rows.append((w, v, next((REGION[t] for t in tags if t in REGION), None),
                             json.dumps(tags, ensure_ascii=False) if tags else None, pos, i))
                stat["收下"] += 1
    return rows, stat, tagc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n_before = con.execute("SELECT COUNT(*) FROM pronunciation").fetchone()[0]
    n_de = con.execute("SELECT COUNT(*) FROM pronunciation WHERE src='de-edition'").fetchone()[0]
    ids, sense, infl = targets(con)
    con.close()
    print("■ 零覆盖且值得补的词形 %s（有真义项 %s ＋ 只是变形 %s；空白页不进目标集）"
          % (f(len(ids)), f(len(sense)), f(len(infl))))

    print("\n■ 扫英文版德语切片…")
    rows, stat, tagc = harvest(set(ids))
    for k, v in stat.most_common():
        print("   %-40s %s" % (k, f(v)))

    print("\n■ 地区标记全量分布（判据同阶段 4，不新写一份）")
    for k, v in tagc.most_common(12):
        print("   %-30s %8s %s" % (k[:30], f(v), "← region=" + REGION[k] if k in REGION else ""))

    covered = {r[0] for r in rows}
    print("\n■ 落点")
    print("   ⭐ 有真义项的缺口  %s / %s = %.1f%%  ← 收尾单 C21/C41 盯的就是这个数"
          % (f(len(covered & sense)), f(len(sense)), 100.0 * len(covered & sense) / max(len(sense), 1)))
    print("      只是变形的缺口  %s / %s = %.1f%%"
          % (f(len(covered & infl)), f(len(infl)), 100.0 * len(covered & infl) / max(len(infl), 1)))

    # 去重 + is_primary：**判据与阶段 4 同形**（按落库行算，不按源头下标算）
    seen, primary, out = set(), set(), []
    for w, v, reg, tg, pos, i in rows:
        k = (ids[w], v, pos)
        if k in seen:
            continue
        seen.add(k)
        pk = (ids[w], pos)
        is_pri = 0 if pk in primary else 1
        primary.add(pk)
        out.append((ids[w], None, v, "phonemic", reg, tg, pos, is_pri, SRC,
                    "kk-en:%s:%s#%d" % (w, pos or "", i)))
    print("\n■ 源头 %s 条 → 去重后 %s 条（同词形同词性同音标重复 %s 次）"
          % (f(len(rows)), f(len(out)), f(len(rows) - len(out))))

    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0

    import dbtool
    with dbtool.session("keep-v3-c41-ipa-en", expect={"#pronunciation": len(out)}) as s:
        s.executemany(
            "INSERT INTO pronunciation "
            "(word_id,entry_id,ipa,notation,region,tags,pos,is_primary,src,src_ref) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)", out)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    ok = gate2(con, {"rows": n_before + len(out)})

    print("\n═══ 闸③ 本步专有 ═══")
    checks = [
        # 🔴 **反向闸**：这一步只许**加**，德语版那一层一行都不许动。
        #    `[[fix-regression-and-gate]]`：只查"新的对不对"查不出"旧的被动了"。
        ("🔴 德语版那一层被动了（应恒为 %s）" % f(n_de),
         q("SELECT COUNT(*) FROM pronunciation WHERE src='de-edition'"), n_de),
        # 🔴 只补**零覆盖**的词形。判据写在这里，与 `targets()` 说的是同一件事。
        ("🔴 补到了本来就有德语版音标的词形上",
         q("SELECT COUNT(DISTINCT p.word_id) FROM pronunciation p WHERE p.src='%s' "
           "  AND EXISTS(SELECT 1 FROM pronunciation q WHERE q.word_id=p.word_id "
           "             AND q.src='de-edition')" % SRC), 0),
        ("🔴 补到了空白页上（页面上除音标什么都没有）",
         q("SELECT COUNT(DISTINCT p.word_id) FROM pronunciation p WHERE p.src='%s' "
           "  AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=p.word_id) "
           "  AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=p.word_id)" % SRC), 0),
        ("🔴 说不出是从哪条英文版条目来的（src_ref 空）",
         q("SELECT COUNT(*) FROM pronunciation WHERE src='%s' "
           "  AND COALESCE(src_ref,'')=''" % SRC), 0),
    ]
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %10s  期望 %s" % ("✓" if good else "🔴", name, f(got), f(want)))

    d6 = q("SELECT COUNT(*) FROM (SELECT DISTINCT s.word_id FROM sense s "
           "WHERE NOT EXISTS(SELECT 1 FROM pronunciation p WHERE p.word_id=s.word_id))")
    print("\n■ 回归闸 D6（有义项的词形没有读音，读者口径）：47,453 → %s" % f(d6))
    con.close()
    print("\n%s" % ("✓ 闸全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
