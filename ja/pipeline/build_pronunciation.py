#!/usr/bin/env python3
"""阶段 4：读音层（IPA + 声调）。零模型调用。2026-09-15。

⚠️ 假名读音与罗马字**不在这张表**：它们是 `entry` 的一等属性列，阶段 1 就填了
   （`kana` 覆盖 99.90%）。这里只放 IPA 和声调。

═══ 🔴 三版分工是量出来的，不是猜的 ═══
                 IPA 词形（库内）   声调      录音
    英文版          59,353      0        4     ← IPA 的主力
    日语版             133      7,199    84
    中文版          21,601      18,460   144   ← 声调的**唯一**可用源

🔴 **日语版的声调 100% 是坏的**：10,215 条记录里 **10,212 条的 `other` 字面是 `"("`**，
   重音位置全丢，只剩类型标签；而且它的 `raw_tags` 散在神奈川/京都/岐阜/愛媛…，
   不是一套标准。中文版 27,487 条**全带 `roman` 标记**、`raw_tags` 99.75% 是東京
   ⇒ **声调只从中文版取**。

═══ 🔴 IPA 裸存 + `notation` 必须真的用起来 ═══
六语种的约定是裸存（不带定界符），展示层加。但日语 **99.98% 是 `[...]`**（77,373 vs 12）
—— 那是**窄式/实际音值**，不是音位。给窄式套 `/.../` 是**记法错误**不是风格问题。
⇒ 存的时候把定界符剥掉、把它是哪一种记进 `notation`，展示层读这一列决定加 `[ ]` 还是 `/ /`。
这列 v3 早就有，六门一直没用起来，ja 是第一个必须用它的。

═══ 声调核位置：推导出来，但**只在与源头标签一致时才写** ═══
`[nìhóꜜǹ]` 的 `ꜜ` 标出降位，之前有几拍就是核位置（平板＝0）。
拿源头的类型标签（Heiban/Atamadaka/Nakadaka/Odaka）反验：**27,475 / 27,487 ＝ 99.96%**。
🔴 不一致的 12 条**只存原始标记、`pitch_pos` 留空** —— 推不准就不写，
   别让一个算出来的数去顶替源头说的话（`[[dict-framework-doc]]`：错比缺更伤权威）。

跑（在仓库根）：
    python3 -u ja/pipeline/build_pronunciation.py
    python3 -u ja/pipeline/build_pronunciation.py --apply
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

PITCH_TAGS = ("Heiban", "Nakadaka", "Atamadaka", "Odaka")
VOWEL = "aeiouāīūēōàèìòùáéíóúâêîôûǎěǐǒǔ"
SMALL = re.compile(r"[ゃゅょャュョぁぃぅぇぉァィゥェォ]")


def nucleus(rom):
    """`ꜜ` 之前有几拍 ⇒ 声调核位置。平板（无 `ꜜ`）返回 0。

    🔴 日语「一拍」不等于「一个元音」，三类要单独数（每一类都是反验逼出来的）：
       ん   `n`/`ń`/`ǹ` **后面不跟元音也不跟 y** —— 拗音 `nya` 的 n 不是独立一拍
       促音 罗马字里是双写辅音（`tt`/`pp`），**也写成 `tch`（あっち）或撇号 `'`（ちょっかい）**
    """
    t = re.sub(r"^\[|\]$", "", rom or "")
    if "ꜜ" not in t:
        return 0
    head = t.split("ꜜ")[0]
    n = len(re.findall("[" + VOWEL + "]", head, re.I))
    n += len(re.findall("[ńǹn](?![" + VOWEL + "y])", head, re.I))
    n += len(re.findall(r"([bcdfghjklmnpqrstvwz])\1", head, re.I))
    n += len(re.findall(r"tch", head, re.I))
    n += head.count("'")
    return n


def pitch_type(pos, moras):
    if pos == 0:
        return "Heiban"
    if pos == 1:
        return "Atamadaka"
    return "Odaka" if pos == moras else "Nakadaka"


def bare_ipa(t):
    """→ (裸串, notation)。六语种统一裸存，是哪一种记进 `notation`。"""
    t = (t or "").strip()
    if t.startswith("[") and t.endswith("]"):
        return t[1:-1].strip(), "narrow"
    if t.startswith("/") and t.endswith("/"):
        return t[1:-1].strip(), "phonemic"
    return t, "narrow"          # 日语 99.98% 是窄式，无定界符时按窄式记


def _assert_ja():
    assert paths.DB.name == "synapse-dict-ja.sqlite", "🔴 paths 不是 ja 的：%s" % paths.DB
    assert not hasattr(dbtool, "has_han"), "🔴 dbtool 不是 ja 的"


def scan(wid, eref):
    rows = []
    stat = collections.Counter()
    seen = set()

    def add(w, ipa, notation, mark, pos_, region, src, ref, eid=None):
        k = (wid[w], eid, ipa, notation)
        if k in seen:
            stat["跳过·同词同音重复"] += 1
            return
        seen.add(k)
        rows.append((wid[w], eid, ipa, notation, mark, pos_, region, src, ref))

    # ① 英文版：IPA 主力，能挂到具体词条上
    for line in open(paths.KK, encoding="utf-8"):
        o = json.loads(line)
        w = (o.get("word") or "").strip()
        if w not in wid:
            continue
        praw = o.get("pos") or "unknown"
        etym = str(o.get("etymology_number") or "0")
        for i, s in enumerate(o.get("sounds") or []):
            if not s.get("ipa"):
                continue
            ipa, nt = bare_ipa(s["ipa"])
            if not ipa:
                continue
            eid = eref.get("kk-ja:%s:%s:%s:0" % (w, praw, etym))
            add(w, ipa, nt, None, None, None, "en-edition",
                "kk-ja:%s:%s#%d" % (w, praw, i), eid)
            stat["IPA·en-edition"] += 1

    # ② 中文版：IPA 补充 + **声调的唯一来源**
    for line in gzip.open(paths.ZH_EDITION, "rt", encoding="utf-8"):
        if '"lang_code": "ja"' not in line:
            continue
        o = json.loads(line)
        if o.get("lang_code") != "ja":
            continue
        w = (o.get("word") or "").strip()
        if w not in wid:
            continue
        for i, s in enumerate(o.get("sounds") or []):
            tg = [t for t in (s.get("tags") or []) if t in PITCH_TAGS]
            region = (s.get("raw_tags") or [None])[0]
            if s.get("ipa"):
                ipa, nt = bare_ipa(s["ipa"])
                if ipa:
                    add(w, ipa, nt, None, None, region, "zh-edition",
                        "zh:%s#%d" % (w, i))
                    stat["IPA·zh-edition"] += 1
            if tg and s.get("roman"):
                mark = s["roman"]
                p = nucleus(mark)
                kana = s.get("other") or ""
                m = len(SMALL.sub("", kana))
                # 🔴 推导与源头标签**不一致就不写 `pitch_pos`**，只留原始标记
                if m and pitch_type(p, m) == tg[0]:
                    stat["声调·核位置推得准"] += 1
                else:
                    p = None
                    stat["声调·推不准（只存标记，pos 留空）"] += 1
                add(w, "", "pitch", mark, p, region, "zh-edition",
                    "zh-pitch:%s#%d" % (w, i))
    return rows, stat


def main():
    _assert_ja()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    eref = {r: i for i, r in con.execute("SELECT id, src_ref FROM entry")}
    con.close()

    rows, stat = scan(wid, eref)
    for k, v in stat.most_common():
        print("   %-30s %9s" % (k, format(v, ",")))
    ipa_w = len({r[0] for r in rows if r[3] != "pitch"})
    pit_w = len({r[0] for r in rows if r[3] == "pitch"})
    print("   ⇒ pronunciation %s 行 ｜有 IPA 的词形 %s ｜有声调的词形 %s"
          % (format(len(rows), ","), format(ipa_w, ","), format(pit_w, ",")))

    dbtool.sample_check([(r[2] or "(声调)", r[3], r[4] or "", r[5] if r[5] is not None else "",
                          r[7]) for r in rows[::max(1, len(rows) // 16)]],
                        12, ("IPA", "记法", "声调标记", "核位", "来源"))
    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    with dbtool.session("ja-pronunciation", expect={"#pronunciation": len(rows)}) as s:
        s.executemany(
            "INSERT INTO pronunciation (word_id, entry_id, ipa, notation, pitch_mark,"
            " pitch_pos, region, src, src_ref) VALUES (?,?,?,?,?,?,?,?,?)", rows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    tot = q("SELECT COUNT(*) FROM dict")
    for name, got, want in [
        ("pronunciation 行数", q("SELECT COUNT(*) FROM pronunciation"), len(rows)),
        ("孤儿（word_id 不在 dict）", q("SELECT COUNT(*) FROM pronunciation p LEFT JOIN dict d"
                                  " ON d.id=p.word_id WHERE d.id IS NULL"), 0),
        ("IPA 还带着定界符", q("SELECT COUNT(*) FROM pronunciation WHERE ipa LIKE '[%'"
                          " OR ipa LIKE '/%'"), 0),
        ("notation 取值越界", q("SELECT COUNT(*) FROM pronunciation WHERE notation NOT IN"
                           " ('narrow','phonemic','pitch')"), 0),
        ("声调行没有标记", q("SELECT COUNT(*) FROM pronunciation WHERE notation='pitch'"
                       " AND (pitch_mark IS NULL OR pitch_mark='')"), 0)]:
        print("   %s %-30s %10s（期望 %s）" % ("✅" if got == want else "🔴", name,
                                             format(got, ","), format(want, ",")))
    print("   ⭐ 有 IPA 的词形 %s / %s = %.1f%% ｜有声调的 %s = %.1f%%"
          % (format(ipa_w, ","), format(tot, ","), 100 * ipa_w / tot,
             format(pit_w, ","), 100 * pit_w / tot))
    con.close()


if __name__ == "__main__":
    main()
