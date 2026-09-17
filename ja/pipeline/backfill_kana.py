#!/usr/bin/env python3
"""阶段 4b：假名读音回补。零模型调用。2026-09-15。

═══ 这一步为什么存在 ═══
阶段 1 报的读音覆盖率是 **99.90%**，那个数对当时的库成立。
阶段 3a 收词之后，库里多了 13.4 万个**一个读音都没有**的词元 ——
覆盖率静默掉到按词元算 39.8%，而**没有任何一道闸会响**：
阶段 1 的写库闸门锁的是「当时写进去多少行」，锁不住「后面又插进来多少行没有」。

🔴 `[[measure-landing-not-source]]` 的另一面：**先量的数，后面的步骤会让它过期。**
   pt 那轮是「收词之后必须重跑变形层」，这轮是「收词之后必须重跑读音层」，
   同一个形状第二次。⇒ 本文件末尾的闸按**词元覆盖率**问，不按「本步写了多少行」问。

═══ 三个源，按「确定性」排优先级，不按「信息量」 ═══
    S3 identity      词头本身就是假名 ⇒ 读音就是它自己。**这是同义反复，不可能错。**
    S1 ja-edition    日语版 `forms[tags=transliteration]` 里**唯一的裸条目**
    S2 zh-gloss-head 中文版 gloss 抬头 `大臣【だいじん】` 的括号内容

🔴 我第一版把优先级写成 S1 > S2 > S3（按「源头多有料」排）。**反了。**
   实测 S1∩S3 的 16 个交集里错 2 个、S2∩S3 的 2 个交集里错 2 个，而且错的方式很难看：
       しお        S1 给 しほ            ← 历史假名遣，不是现代读音
       ブラスバンド  S1 给 すいそうがくだん  ← 那是**近义词**（吹奏楽団）的读音
       ワンゲル     S2 给 ワンダーフォーゲル ← 那是全称，不是读音
   交集小、错得整齐 ⇒ 不是噪声，是**这两个源在假名词头上系统性地装别的东西**。
   而 S3 在这些词上给的是确定正确的答案，却被我排到最后覆盖掉。
   ⇒ 排序判据改成「哪个源在这类词上不可能错」。

═══ 拿独立锚量过才敢写（`[[external-anchor-gates]]`）═══
用英文版 head_templates 给的读音当锚（与本轮三源完全独立）：
    S1 可比 20,584  命中 97.24%
    S2 可比  7,438  命中 98.29%
不命中的绝大多数是**真实的异读**（今日 きょう／こんにち、九月 ながつき／くがつ 都对），
真错的是源头笔误那一小撮（位置付ける いちっける ← づ 写成 っ）。

═══ 有意不做的两件事 ═══
① **多读音词不猜。** 日语版给 ≥2 个裸 transliteration 的 1,744 个词形（今日→
   こんにち／こんち／こんじつ）整批跳过。`entry.kana` 只有一格，随便挑一个
   ＝把硬币翻面当数据写进去。宁可留空。
② **不补 `romaji`。** 罗马字的规矩是**存源头的不自己算**（自己算与源头一致率仅
   64.27%，见 `build_entry_layer` 文件头）。三个源都只给假名 ⇒ romaji 保持 NULL。

跑（在仓库根）：
    python3 -u ja/pipeline/backfill_kana.py
    python3 -u ja/pipeline/backfill_kana.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import gzip
import json
import re
import sqlite3

import dbtool
import paths

# 纯假名：真假名 + 长音符 + 叠字符。🔴 **不要整块 U+30A0–30FF**：
# 那里面有 `・`（U+30FB），`dbtool.has_kana` 第一版就是这么栽的（变异测试全绿，
# 因为我的用例里一个标点都没有）。
PURE_KANA = re.compile(r"^[ぁ-ゖァ-ヺーゝゞヽヾ]+$")
# 中文版 gloss 抬头。🔴 三个条件缺一不可：整行匹配、括号前**恰好是词头**、
#    括号内**纯假名**。少任何一条都会咬到学科标签（`【數學】`）和
#    混排词头（`基本システム【きほん system】`）——`intake_edition_words` 的文件头记着这两例。
HEAD_READING = re.compile(r"^(\S+)【([^】]+)】$")


def ja_edition_readings(want):
    """日语版：`forms` 里 tags 恰好只有 `transliteration` 的条目。

    ⚠️ 带 `go-on`/`kan-on`/`kun`/`joyo` 等标签的那些是**汉字的音训表**
       （青 → ショウ/セイ/チン/シイ/あお/あお-い/あをし），不是这个词的读音。
       所以判据是「标签集合减去 transliteration 之后为空」，不是「含 transliteration」。
    """
    out, multi = {}, 0
    for ln in open(paths.EDITION, encoding="utf-8"):
        o = json.loads(ln)
        w = o["word"]
        if w not in want or w in out:
            continue
        bare = [f["form"] for f in (o.get("forms") or [])
                if (f.get("tags") or []) == ["transliteration"]
                or set(f.get("tags") or []) == {"transliteration"}]
        bare = [b for b in dict.fromkeys(bare) if PURE_KANA.match(b)]
        if len(bare) == 1:
            out[w] = bare[0]
        elif len(bare) > 1:
            multi += 1
    return out, multi


def zh_edition_readings(want):
    """中文版：gloss 抬头的【】内容。

    🔴 阶段 3a 把这一行当「结构残渣」洗掉了 —— **洗对了**（它不是释义），
       但洗之前没有把里面的读音收走。删一个东西之前先问它里面有没有别的层要的料。
    """
    out = {}
    with gzip.open(paths.ZH_EDITION, "rt", encoding="utf-8") as fh:
        for ln in fh:
            o = json.loads(ln)
            if o.get("lang_code") != "ja":
                continue
            w = o["word"]
            if w not in want or w in out:
                continue
            for s in o.get("senses") or []:
                for g in s.get("glosses") or []:
                    for line in g.split("\n"):
                        m = HEAD_READING.match(line.strip())
                        if m and m.group(1) == w and PURE_KANA.match(m.group(2)):
                            out[w] = m.group(2)
                            break
                    if w in out:
                        break
                if w in out:
                    break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    ro = lambda: sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    con = ro()
    want = collections.Counter()
    for w, n in con.execute("SELECT d.word, COUNT(*) FROM entry e JOIN dict d ON d.id=e.word_id"
                            " WHERE e.kana IS NULL GROUP BY 1"):
        want[w] = n
    print("■ 缺 kana：entry %s 行 / 词形 %s 个"
          % (f"{sum(want.values()):,}", f"{len(want):,}"), flush=True)

    s3 = {w: w for w in want if PURE_KANA.match(w)}
    s1, multi = ja_edition_readings(want)
    s2 = zh_edition_readings(want)
    print("■ S1 日语版 %s（多读音放弃 %s）  S2 中文版 %s  S3 词头即假名 %s"
          % (f"{len(s1):,}", f"{multi:,}", f"{len(s2):,}", f"{len(s3):,}"), flush=True)

    # 🔴 确定性优先：identity 最后 update ⇒ 它覆盖前两个（见文件头那三个反例）
    pick = {}
    for src, d in (("zh-gloss-head", s2), ("ja-edition", s1), ("identity", s3)):
        for w, v in d.items():
            pick[w] = (v, src)
    by_src = collections.Counter(s for _, s in pick.values())
    rows = sum(want[w] for w in pick)
    print("■ 可补 词形 %s / %s = %.1f%%   entry %s / %s = %.1f%%"
          % (f"{len(pick):,}", f"{len(want):,}", 100 * len(pick) / len(want),
             f"{rows:,}", f"{sum(want.values()):,}",
             100 * rows / sum(want.values())), flush=True)
    for s, n in by_src.most_common():
        print("     %-14s %s" % (s, f"{n:,}"), flush=True)

    # 两源都给了的地方对不对得上 —— 不一致不阻断，但必须报出来
    both = set(s1) & set(s2)
    if both:
        ag = sum(1 for w in both if s1[w] == s2[w])
        print("■ S1∩S2 %s 个，一致 %.2f%%" % (f"{len(both):,}", 100 * ag / len(both)),
              flush=True)

    romaji_before = con.execute(
        "SELECT COUNT(*) FROM entry WHERE romaji IS NOT NULL").fetchone()[0]

    if not a.apply:
        print("\n（dry-run，加 --apply 写库）")
        for w, (v, s) in list(pick.items())[:10]:
            print("   %-12s → %-16s %s" % (w, v, s))
        return

    with dbtool.session("ja-backfill-kana", expect={
            "#entry": 0, "#dict": 0, "#sense": 0, "#pronunciation": 0}) as con:
        con.executemany(
            "UPDATE entry SET kana=?, kana_src=? WHERE kana IS NULL AND word_id="
            "(SELECT id FROM dict WHERE word=?)",
            [(v, s, w) for w, (v, s) in pick.items()])

    con = ro()
    q = lambda s: con.execute(s).fetchone()[0]
    # ══════ 写库闸门：**按词元覆盖率问**，不按「本步写了多少行」问 ══════
    # 本步写了多少行是自比，下次收词之后它照样全绿而覆盖率照样掉。
    checks = [
        ("词元读音覆盖率 ≥ 68%", q(
            "SELECT 100*COUNT(DISTINCT CASE WHEN kana IS NOT NULL THEN word_id END)"
            "/COUNT(DISTINCT word_id) FROM entry") >= 68),
        ("kana 里没有汉字", q("SELECT COUNT(*) FROM entry WHERE kana GLOB '*[一-鿿]*'") == 0),
        ("kana 里没有拉丁字母", q(
            "SELECT COUNT(*) FROM entry WHERE kana GLOB '*[A-Za-z]*'") == 0),
        ("kana 非空即有 kana_src", q(
            "SELECT COUNT(*) FROM entry WHERE kana IS NOT NULL AND"
            " (kana_src IS NULL OR kana_src='')") == 0),
        # 🔴 这一条第一版我写成了「kana_src 不是 identity 的行里 romaji 为空」——
        #    那是**形式代理**，而且代理还不成立：`identity` 在阶段 1 就用过（25,605 行），
        #    本步写的 identity 行和阶段 1 的在列里长得一模一样，按 kana_src 根本分不开。
        #    ⇒ 改成直接量**写库前后 romaji 非空数有没有变**。
        ("romaji 非空数没变（%s）" % f"{romaji_before:,}",
         q("SELECT COUNT(*) FROM entry WHERE romaji IS NOT NULL") == romaji_before),
    ]
    print()
    for name, ok in checks:
        print("   %s %s" % ("✅" if ok else "🔴", name))
    print("\n■ 词元读音覆盖率 %.1f%%（本步前 39.8%%）" % q(
        "SELECT 100.0*COUNT(DISTINCT CASE WHEN kana IS NOT NULL THEN word_id END)"
        "/COUNT(DISTINCT word_id) FROM entry"))
    if not all(ok for _, ok in checks):
        _sys.exit(1)


if __name__ == "__main__":
    main()
