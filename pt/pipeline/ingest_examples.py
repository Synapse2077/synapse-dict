#!/usr/bin/env python3
"""阶段 5c — 收例句（七版 kaikki）→ `example` / `example_gloss`。2026-08-30。

⚠️ **本步不花一分钱。** 收例句、挂义项、把源头自带的中/英译文放进出版层，全是确定性的。
   中文翻译是**另一步**（`slot_translate`），单独报价、单独跑。两件事不许捆在一起 ——
   捆在一起就没法先看"免费能拿到多少"再决定买多少。

═══ 判据与边界 ═══
· **只认 kaikki**（用户 2026-08-03 方针 A3）：Tatoeba / OPUS 一律不碰。
· **文本一个字节都不许动。** `bold_text_offsets` 是弹窗高亮词形用的坐标，
  改一个字符就全错位。⇒ 释义那套清洗**不适用于例句**；有残渣只能记账，不能剥。
· 例句挂到**义项**上，依据是**源头坐标**，确定性对上，不猜。

═══ 规模（实测 2026-08-30，`probes/examples.py`，七版全量）═══

    各版例句合计      52,052
    **全局不同句子**   40,783   ← 翻译成本的真分母（同一句可给几个词当例句）
    句长 中位 55 ／ 均 80 ／ P90 178

    pt 24,491 ／ fr 13,744 ／ en 11,663 ／ zh 885 ／ de 739 ／ es 452 ／ it 78

⭐ **比 fr 小一个数量级**（fr 615,033 不同句子），而且质量更好 ——
   fr 那批几乎全是文学引文，pt 这批有大量教学例句（`Dá-me uma apitadela quando chegares a Beja!`）。

═══ 译文分两层（照 it/fr）═══
· `example_gloss` = **出版层**，只放中英（A3：释义只留三语，例句原文本身就是葡语）。
     中文版自带 **807 条中文** ／ 英文版自带 **8,852 条英文** —— **免费的，先拿**。
· `example.src_translation` + `src_lang` = **证据层**，放源头给的、我们不出版的语言
     （法/德/西/意版给的本国语译文 13,723 条）。留着能回源核对，不展示。

🔴 **不许把法语版的 `translation` 当中文用**，也不许把它当英文用 —— 它是法语。
   `[[context-you-give-leaks-into-output]]`：给模型的"仅供参考"上下文会直接漏进输出。

═══ 义项坐标：反解库里现成的 `src_ref`（同 5b，判据只许一份）═══
只有英文版的义项能挂上（其余版的释义层要等阶段 1.5）。挂不上照收、`sense_id` 留 NULL。

用法（在 pt/ 目录下）：
    python3 -u pipeline/ingest_examples.py            # 干跑
    python3 -u pipeline/ingest_examples.py --apply
    python3 -u pipeline/ingest_examples.py --verify
"""
import argparse
import gzip
import json
import random
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from ingest_relations import sense_index   # noqa: E402  判据只许一份
from intake_edition_words import EDITIONS, norm_apos   # noqa: E402

# 各版 `examples[].translation` 是**哪门语言**。这张表是本文件唯一的真相来源 ——
# 🔴 写错一个就会把法语译文当中文发布出去。
TR_LANG = {"pt": "pt", "en": "en", "fr": "fr", "zh": "zh",
           "es": "es", "it": "it", "de": "de",
           # 2026-08-30 补下的八个切片
           "ja": "ja", "ru": "ru", "pl": "pl", "el": "el",
           "ko": "ko", "tr": "tr", "nl": "nl", "cs": "cs"}
# 🔴 **漏配一个必须当场崩，不许用默认值兜底。**
#    实测：加了八个源却忘了这张表 ⇒ `TR_LANG[ed]` 直接 `KeyError: 'ja'` —— **这是对的**。
#    如果当初写成 `TR_LANG.get(ed, "??")`，日语版的译文会被贴上错的语言标签**发布出去**。
#    （`[[prompt-self-harm-two-patterns]]` 的反面：那次是 `pos or "v"` 把缺失值
#      用默认值填平，把分类名和缩写全说成了动词。）
#    下面这条断言让「加了源忘了配语言」在**导入时**就炸，而不是扫到一半才炸。
assert set(TR_LANG) >= set(EDITIONS), (
    "🔴 这些源没配译文语言：%s —— 见 TR_LANG 上面那段"
    % sorted(set(EDITIONS) - set(TR_LANG)))
PUBLISH = {"zh", "en"}          # 出版层只收这两门（方针 A3）
f = lambda n: format(n, ",")


def clean_bold(text, offsets):
    """→ 能用的 bold 坐标 JSON，或 None。**判据只在这里一份。**

    🔴 源头有 29 条 `bold_text_offsets` **指向的是别的字符串**（多半是英文译文）：

        'Ela cantou a sua melhor música.'   len=31   坐标 [[38,42]]
        'Emparedei meu jardim.'             len=21   坐标 [[22,30],[41,43]]

    ⚠️ 处置是**整组置空，不是剔掉越界的那几对** ——
       一半越界说明这组坐标根本不属于这段文本，信另一半没有依据。
    ⚠️ **文本一个字节都不动**：`bold` 是坐标，坏的是坐标不是文本。
    """
    if not offsets:
        return None
    if any(not (0 <= a <= z <= len(text)) for a, z in offsets):
        return None
    return json.dumps(offsets)


def scan(ids, sidx, editions):
    """→ (rows, glosses, stat)

    rows[(word, text)] = dict(...)   —— `UNIQUE(word, text)` 就是这个键
    glosses[(word, text)][lang] = 译文
    """
    rows, glosses, stat = {}, {}, Counter()
    for ed in editions:
        path, filt = EDITIONS[ed]
        if not path.exists():
            stat["🔴 dump 不存在：" + ed] += 1
            continue
        occ_of = Counter()
        op = gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" \
            else open(path, encoding="utf-8")
        with op as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if filt and e.get("lang_code") != "pt":
                    continue
                w0 = (e.get("word") or "").strip()
                if not w0:
                    continue
                w = norm_apos(w0)
                if w not in ids:
                    stat["词不在库里（跳过）"] += 1
                    continue
                pos_raw = e.get("pos") or ""
                etym = str(e.get("etymology_number") or 0)
                occ = occ_of[(w0, pos_raw, etym)]
                occ_of[(w0, pos_raw, etym)] += 1
                for i, sn in enumerate(e.get("senses") or []):
                    sid = sidx.get((w0, pos_raw, etym, i)) if ed == "en" else None
                    gloss0 = (sn.get("glosses") or [""])[0]
                    for ex in (sn.get("examples") or []):
                        t = (ex.get("text") or "").strip()
                        if not t:
                            stat["无 text（跳过）"] += 1
                            continue
                        stat["例句·" + ed] += 1
                        key = (w, t)
                        tr = (ex.get("english") or ex.get("translation") or "").strip()
                        lang = "en" if ex.get("english") else TR_LANG[ed]
                        if key not in rows:
                            rows[key] = {
                                "word": w, "sense_id": sid, "text": t,
                                "bold": clean_bold(t, ex.get("bold_text_offsets")),
                                "ref": (ex.get("ref") or "").strip() or None,
                                "src_gloss": gloss0[:300] or None,
                                "src_translation": None, "src_lang": None,
                                "src": "%s-edition" % ed}
                        else:
                            stat["同句被多版/多义项给出（合并）"] += 1
                            if rows[key]["sense_id"] is None and sid is not None:
                                rows[key]["sense_id"] = sid
                                stat["合并时补上了义项挂载"] += 1
                        if tr:
                            if lang in PUBLISH:
                                g = glosses.setdefault(key, {})
                                if lang not in g:
                                    g[lang] = (tr, "%s-edition" % ed)
                                    stat["✅ 免费译文·" + lang] += 1
                            elif rows[key]["src_translation"] is None:
                                rows[key]["src_translation"] = tr
                                rows[key]["src_lang"] = lang
                                stat["证据层译文·" + lang] += 1
        stat["扫完 " + ed] += 1
    return rows, glosses, stat


def verify(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        # 🔴 **不能写成 `NOT EXISTS(... WHERE d.word=e.word)`。**
        #    `dict` 上唯一的词形索引是 `idx_word ON dict(word COLLATE NOCASE)`，
        #    而这个比较用的是默认 BINARY ⇒ **索引用不上，退化成 `SCAN d`**，
        #    50,745 行各扫一遍 76.9 万行，实测跑了 10 分钟还没完。
        #    （`[[query-perf-collation-traps]]` 的镜像版：那条记的是"查询写了 NOCASE
        #      而索引没有"，这里是"索引是 NOCASE 而查询没写"，**同一个静默全表扫**。）
        #    ⚠️ 不能靠加 `COLLATE NOCASE` 绕过 —— 阶段 3a 特意把大小写折叠的词形拆成了
        #      两行（`Cefalópodos` 头足纲 vs `cefalópodos` 复数），NOCASE 会把它们混为一谈。
        #    ⇒ 改成 `EXCEPT`：两趟排序扫描，语义还是 BINARY。
        ("example.word 不在 dict",
         q("SELECT COUNT(*) FROM (SELECT DISTINCT word FROM example"
           " EXCEPT SELECT word FROM dict)"), 0),
        ("sense_id 非空但不在 sense",
         q("SELECT COUNT(*) FROM example e WHERE e.sense_id IS NOT NULL AND NOT EXISTS"
           "(SELECT 1 FROM sense s WHERE s.id=e.sense_id)"), 0),
        ("text 为空", q("SELECT COUNT(*) FROM example WHERE TRIM(text)=''"), 0),
        ("(word,text) 重复",
         q("SELECT COUNT(*) FROM (SELECT word,text FROM example GROUP BY 1,2 HAVING COUNT(*)>1)"), 0),
        ("example_gloss 指向不存在的 example",
         q("SELECT COUNT(*) FROM example_gloss g WHERE NOT EXISTS"
           "(SELECT 1 FROM example e WHERE e.id=g.example_id)"), 0),
        ("🔴 出版层混进了中英之外的语言",
         q("SELECT COUNT(*) FROM example_gloss WHERE lang NOT IN ('zh','en')"), 0),
        ("🔴 证据层的译文语言写成了中/英（该进出版层）",
         q("SELECT COUNT(*) FROM example WHERE src_lang IN ('zh','en')"), 0),
        ("🔴 bold 坐标越界（改过文本就会越界）",
         sum(1 for t, b in con.execute(
             "SELECT text, bold FROM example WHERE bold IS NOT NULL")
             if any(not (0 <= a <= z <= len(t)) for a, z in json.loads(b))), 0),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-46s %10s  (期望 %s)" % ("✅" if ok else "🔴", name, f(got), f(want)))
    print("\n   example %s ／ 挂到义项 %s ／ 出版层译文 %s"
          % (f(q("SELECT COUNT(*) FROM example")),
             f(q("SELECT COUNT(*) FROM example WHERE sense_id IS NOT NULL")),
             f(q("SELECT COUNT(*) FROM example_gloss"))))
    print("\n%s" % ("✅ 全部通过" if not bad else "🔴 %d 条红" % bad))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    # 🔴 **源清单只许一份** —— 从 `EDITIONS` 派生，不手抄。
    #    2026-08-30 实测：补下八个切片后只改了 `EDITIONS`，而这四个文件
    #    （relations/audio/examples/link_table_forms）各自手抄了一份默认值 ⇒
    #    **新源一个都没被扫**，`audio` 跑完行数一条没涨。
    #    `[[refactor-mindset-code-quality]]`：同一张表在两处各存一份，
    #    没分叉纯属运气。
    ap.add_argument("--editions", default=",".join(EDITIONS))
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return verify(ro)

    ids = {}
    for i, w in ro.execute("SELECT id, word FROM dict"):
        ids.setdefault(w, i)
    sidx = sense_index(ro)
    ro.close()
    print("■ 义项坐标索引：唯一命中 %s 个键" % f(len(sidx)))

    rows, glosses, stat = scan(ids, sidx, [x for x in a.editions.split(",") if x])
    for k, v in sorted(stat.items()):
        print("   %-38s %10s" % (k, f(v)))
    n_sid = sum(1 for r in rows.values() if r["sense_id"] is not None)
    print("   %-38s %10s" % ("→ example 行（(词,句) 去重）", f(len(rows))))
    print("   %-38s %10s" % ("   其中挂到义项", f(n_sid)))
    print("   %-38s %10s" % ("→ example_gloss 行（免费译文）",
                             f(sum(len(v) for v in glosses.values()))))
    print("   %-38s %10s" % ("🔴 还要翻的不同句子（成本分母）",
                             f(len({r["text"] for k, r in rows.items()
                                    if "zh" not in glosses.get(k, {})}))))

    print("\n── 抽样反验 15 条 ──")
    random.seed(0)
    for k in random.sample(sorted(rows), min(15, len(rows))):
        r = rows[k]
        print("   [%s] %-18s %s" % (r["src"][:2], r["word"][:18], r["text"][:96]))
        for lang, (t, _s) in sorted(glosses.get(k, {}).items()):
            print("        %s: %s" % (lang, t[:80]))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    ex_rows = [(r["word"], r["sense_id"], r["text"], r["bold"], r["ref"],
                r["src_gloss"], r["src_translation"], r["src_lang"], 0, r["src"])
               for r in rows.values()]
    # 🔴 `expect` 比的是**增量**不是总数。同一个错今天第三次（频次层/录音层/这里）——
    #    不是手滑，是我写收割器的固定套路有问题：`rows` 是**整轮扫描的产物**，
    #    而 `INSERT OR IGNORE` 只插新的。⇒ 增量 = rows 里键还不在库里的那些。
    ro4 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    had_ex = {(w, t) for w, t in ro4.execute("SELECT word, text FROM example")}
    had_gl = {(e, l) for e, l in ro4.execute(
        "SELECT example_id, lang FROM example_gloss")}
    eid_now = {(w, t): i for i, w, t in ro4.execute("SELECT id, word, text FROM example")}
    ro4.close()
    d_ex = sum(1 for r in ex_rows if (r[0], r[2]) not in had_ex)
    d_gl = sum(1 for k, v in glosses.items() for lang in v
               if (eid_now.get(k), lang) not in had_gl)
    with dbtool.session("keep-v3-5c-examples",
                        expect={"#example": d_ex, "#example_gloss": d_gl}) as s:
        s.executemany(
            "INSERT OR IGNORE INTO example "
            "(word,sense_id,text,bold,ref,src_gloss,src_translation,src_lang,hidden,src) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)", ex_rows)
        eid = {(w, t): i for i, w, t in s.execute("SELECT id, word, text FROM example")}
        s.executemany(
            "INSERT OR IGNORE INTO example_gloss (example_id,lang,text,src) VALUES (?,?,?,?)",
            [(eid[k], lang, t, src) for k, v in glosses.items()
             for lang, (t, src) in v.items() if k in eid])
    return verify(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True))


if __name__ == "__main__":
    sys.exit(main())
