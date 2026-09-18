#!/usr/bin/env python3
"""阶段 4c：汉字的**音訓読み**层。零模型调用、零下载、零成本。2026-09-18。

═══ 为什么这一层到今天才建 —— 一条判据写滑了 ═══
`JA_PLAN` §二判据 4 写着：

    「**不存在 15% 读音缺口**」——缺的 14,161 条全部是 `pos=character`
    （汉字作为「字」，本来就没有单一读音）。按 85% 立项去补，补的是一个不存在的洞。

前半句是对的：汉字确实**没有单一读音**，`青` 不能说"读作 X"。
后半句滑了：它从「没有**单一**读音」推到了「不用补」，而汉字有的是一组**分类**读音 ——

    青  音読み：ショウ(呉音) セイ(漢音) チン・シイ(唐音)
        訓読み：あお、あお-い          古訓：あをし

**日语版 dump 把这组读音写了，我们没抽。** 这正是
`[[dont-say-source-lacks-what-we-skipped]]`：「源头没写」和「我们没抽」要在结构上分开。
在此之前 `青` 的 character 条目在库里 `kana` 和 `romaji` **两列全空**。

═══ 🔴 日语版是唯一来源：英文版一条都没有 ═══
英文版 14,970 个 `character` 条目的 `forms` 里只有 `romanization` 1,732 /
`kyūjitai` 720 / `shinjitai` 633，**没有任何音训读**；`青` 的 `head_templates`
和 `sounds` 都是 `null`。⇒ 不做跨版合并，`src` 恒为 `ja-edition`。
（`[[multi-edition-methodology]]`：英文版是**结构**基准，不是**内容**上限。）

═══ 🔴 判据打在 tag 上，假名字形只用来**交叉验证** ═══
日语惯例是「音読み写片假名、訓読み写平假名」。那是**形式代理**，不能当判据
（`[[criteria-from-meaning-not-form]]`）：源头已经把音/训写在 `tags` 里了，
拿字形去猜等于把一个已知量重新推导一遍，还会在源头与惯例不符时静默出错。

⇒ 判据：`tags` 映射（14 种组合，全覆盖、无残差）；
   字形一致率作为**验证指标**打印出来，不一致的逐条列出来给人看。

    音読み  go-on 呉音 / kan-on 漢音 / to-on 唐音 / kan-yo-on 慣用音 / on（未细分）
    訓読み  kun 訓読み / ko-kun 古訓
    名乗り  nanori —— 🔴 **不并进訓読み**：它是人名专用读音，
            并进去等于断言「なのり可以当普通训读用」，那是错的

`joyo` 是**正交**标记（该读音在常用汉字表内），不是第七个类别 ⇒ 单独一列 `is_joyo`。

═══ 🔴 送假名的连字符是信息，不是噪声 ═══
`い-きる` 表示 `生きる` 里 `生` 只读 `い`，`きる` 是送假名。剥掉连字符会把
「这个字读什么」和「整个词读什么」混成一件事。⇒ 原样存 `kana`，
另拆 `kana_stem`（字本身的读音）+ `okurigana`（送假名）两列，展示层要哪个取哪个。
全量 7,273 条里 2,076 条带连字符。

═══ 源头有 24.7% 的重复行 ═══
`行` 在日语版有多个条目，每个都带一份完整读音表 ⇒ 同一读音出现多次。
去重后 9,661 → **7,272** 条。

🔴 **去重键里不许有 `joyo` —— 第一版有，当场被 `UNIQUE(src_ref)` 拦下。**
我在上面写着「`joyo` 是正交标记、不是第七个类别」，然后把它放进了去重键 ——
**说的和做的不一致**（`[[criteria-from-meaning-not-form]]` 的自伤形态）。
后果是同一个读音带/不带 `joyo` 各留一行，而 `src_ref` 不含 `joyo` ⇒ 主键冲突。

⚠️ 全量只有 **1 组**撞上：`弁 / ベン / 呉音`。`弁` 是新字体合并字（辨・瓣・辯 三字并一），
日语版里有多个条目，其中一个标了 `joyo` 另一个没标。
⇒ 身份键 `(词, 读音, kind, subkind)`，`is_joyo` 取 **OR** ——
   只要源头有一处说它在常用汉字表内，它就在（少标是漏，多标才是错）。
⭐ **0.01% 的冲突率，靠抽样是看不见的**；逮到它的是主键，不是我读数据。

跑（在仓库根）：
    python3 -u ja/pipeline/build_kanji_reading.py
    python3 -u ja/pipeline/build_kanji_reading.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import json
import re
import sqlite3

import dbtool
import paths

f = lambda n: format(n, ",")

DDL = """CREATE TABLE IF NOT EXISTS kanji_reading (
           id        INTEGER PRIMARY KEY AUTOINCREMENT,
           word_id   INTEGER NOT NULL,      -- → dict.id（汉字本身）
           entry_id  INTEGER,               -- → entry.id（pos_raw='character' 那条）
           kana      TEXT NOT NULL,         -- 原样，含送假名连字符（あお-い）
           kana_stem TEXT NOT NULL,         -- 连字符前＝这个**字**的读音（あお）
           okurigana TEXT,                  -- 连字符后的送假名（い）；无连字符为 NULL
           kind      TEXT NOT NULL,         -- on 音読み / kun 訓読み / nanori 名乗り
           subkind   TEXT,                  -- go-on/kan-on/to-on/kan-yo-on/ko-kun
           is_joyo   INTEGER NOT NULL DEFAULT 0,   -- 该读音在常用汉字表内
           seq       INTEGER NOT NULL,      -- 源头顺序（音读在前、训读在后，别重排）
           src       TEXT NOT NULL,         -- 🔴 恒为 ja-edition：英文版一条都没有
           src_ref   TEXT NOT NULL,
           UNIQUE(src_ref)
         )"""
IDX = ["CREATE INDEX IF NOT EXISTS idx_kr_word ON kanji_reading(word_id)",
       "CREATE INDEX IF NOT EXISTS idx_kr_entry ON kanji_reading(entry_id)",
       "CREATE INDEX IF NOT EXISTS idx_kr_kind ON kanji_reading(kind, subkind)"]

# 🔴 判据表：tag → (kind, subkind)。源头 14 种组合全覆盖，落不进来的**大声报**。
#    `joyo` 在进这张表之前就被剥掉（它是正交标记，见文件头）。
KIND = {
    "go-on":     ("on", "go-on"),       # 呉音
    "kan-on":    ("on", "kan-on"),      # 漢音
    "to-on":     ("on", "to-on"),       # 唐音
    "kan-yo-on": ("on", "kan-yo-on"),   # 慣用音
    "on":        ("on", None),          # 音読み（源头未细分）
    "kun":       ("kun", None),         # 訓読み
    "ko-kun":    ("kun", "ko-kun"),     # 古訓
    "nanori":    ("nanori", None),      # 名乗り —— 不并进 kun，见文件头
}
KATAKANA = re.compile(r"^[ァ-ヴー]+$")
HIRAGANA = re.compile(r"^[ぁ-ゖー]+$")


def split_okuri(kana):
    """`い-きる` → (`い`, `きる`)；`あお` → (`あお`, None)。

    🔴 只认**第一个**连字符：`う-まれる` 这类只有一个，而万一源头出现两个，
       后面的属于送假名的一部分，不该再切一刀。
    """
    if "-" not in kana:
        return kana, None
    stem, _, okuri = kana.partition("-")
    return stem, (okuri or None)


def scan():
    """扫日语版，返回 (rows, stat, unknown, shape_mismatch)。"""
    stat = collections.Counter()
    unknown = collections.Counter()      # 落不进 KIND 的 tag
    # 🔴 身份键 **不含 `joyo`**（它是正交标记，见文件头）。值里存 is_joyo，重复时取 OR。
    seen = {}
    per = collections.defaultdict(list)

    with open(paths.EDITION, encoding="utf-8") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            w = o.get("word")
            if not w:
                continue
            for fm in o.get("forms") or []:
                tags = fm.get("tags") or []
                if "transliteration" not in tags:
                    continue
                stat["源头 transliteration 形"] += 1
                cls = [t for t in tags if t not in ("transliteration", "joyo")]
                if not cls:
                    # 无分类标记 —— 那是**普通词的假名读音**（`保護`→`ほご`），
                    # 不是汉字音训读；`entry.kana` 已经有了，这层不收。
                    stat["无分类标记（普通词读音，不收）"] += 1
                    continue
                kana = (fm.get("form") or "").strip()
                if not kana:
                    stat["读音为空（丢）"] += 1
                    continue
                hit = [c for c in cls if c in KIND]
                if len(hit) != 1:
                    for c in cls:
                        if c not in KIND:
                            unknown[c] += 1
                    stat["🔴 分类标记认不出（丢）"] += 1
                    continue
                kind, sub = KIND[hit[0]]
                joyo = 1 if "joyo" in tags else 0

                key = (w, kana, kind, sub)
                if key in seen:
                    stat["源头重复行（去重）"] += 1
                    i = seen[key]
                    if joyo and not per[w][i][5]:
                        # `弁/ベン/呉音`：一处标了常用一处没标 ⇒ OR。少标是漏，多标才是错。
                        per[w][i] = per[w][i][:5] + (1,)
                        stat["⚠️ joyo 标记两可（取 OR）"] += 1
                    continue
                seen[key] = len(per[w])

                stem, okuri = split_okuri(kana)
                per[w].append((kana, stem, okuri, kind, sub, joyo))

    # 交叉验证：tag 推出的 kind vs 假名字形（片假名≈音読み）。**验证不是判据。**
    shape = collections.Counter()
    mismatch = []
    for w, rows in per.items():
        for kana, stem, okuri, kind, sub, joyo in rows:
            if KATAKANA.match(stem):
                form = "片假名"
            elif HIRAGANA.match(stem):
                form = "平假名"
            else:
                form = "混/其他"
            expect = "片假名" if kind == "on" else "平假名"
            shape["%s/%s" % (kind, form)] += 1
            if form != expect and form != "混/其他":
                mismatch.append((w, kana, kind, sub, form))
    return per, stat, unknown, shape, mismatch


def build(per):
    """挂 word_id / entry_id，产出可插的行。"""
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid = {w: i for w, i in con.execute("SELECT word, id FROM dict")}
    eid = {}
    for w, i in con.execute("SELECT d.word, e.id FROM dict d JOIN entry e"
                            " ON e.word_id=d.id WHERE e.pos_raw='character'"
                            " ORDER BY e.id"):
        eid.setdefault(w, i)      # 同字多条 character 条目时取第一条
    con.close()

    rows, miss = [], []
    for w in sorted(per):
        if w not in wid:
            miss.append(w)
            continue
        for seq, (kana, stem, okuri, kind, sub, joyo) in enumerate(per[w]):
            ref = "ja-ed:%s:kr:%s:%s:%s" % (w, kind, sub or "-", kana)
            rows.append((wid[w], eid.get(w), kana, stem, okuri, kind, sub,
                         joyo, seq, "ja-edition", ref))
    return rows, miss


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    per, stat, unknown, shape, mismatch = scan()
    print("■ 扫源头（%s）" % paths.EDITION.name)
    for k, v in stat.most_common():
        print("   %-34s %9s" % (k, f(v)))
    if unknown:
        print("   🔴 KIND 表里没有的分类标记（判据有洞，不要静默跳过）：")
        for k, v in unknown.most_common(20):
            print("      %-20s %s" % (k, f(v)))

    rows, miss = build(per)
    print("\n■ 落点")
    print("   %-34s %9s" % ("汉字数", f(len(per))))
    print("   %-34s %9s" % ("读音行", f(len(rows))))
    print("   %-34s %9s" % ("🔴 词形不在 dict（丢）", f(len(miss))))
    if miss:
        print("      样本：%s" % " ".join(miss[:12]))
    nul = sum(1 for r in rows if r[1] is None)
    print("   %-34s %9s" % ("⚠️ 挂不上 character 条目", f(nul)))

    byk = collections.Counter("%s/%s" % (r[5], r[6] or "-") for r in rows)
    print("\n■ 分类分布")
    LAB = {"on/go-on": "音読み·呉音", "on/kan-on": "音読み·漢音",
           "on/to-on": "音読み·唐音", "on/kan-yo-on": "音読み·慣用音",
           "on/-": "音読み（未细分）", "kun/-": "訓読み",
           "kun/ko-kun": "訓読み·古訓", "nanori/-": "名乗り"}
    for k, v in byk.most_common():
        print("   %-18s %-14s %8s" % (k, LAB.get(k, "?"), f(v)))
    print("   %-33s %9s" % ("其中常用汉字表内（is_joyo=1）", f(sum(r[7] for r in rows))))
    print("   %-33s %9s" % ("带送假名连字符", f(sum(1 for r in rows if r[4]))))

    print("\n■ 交叉验证：tag 推出的类别 vs 假名字形（**验证指标，不是判据**）")
    for k, v in sorted(shape.items()):
        print("   %-22s %8s" % (k, f(v)))
    tot = sum(shape.values())
    print("   ⇒ 与「音読み写片假名／訓読み写平假名」惯例不符 %s 条 = %.2f%%"
          % (f(len(mismatch)), 100.0 * len(mismatch) / max(tot, 1)))
    for w, kana, kind, sub, form in mismatch[:20]:
        print("      %-3s %-10s tag判=%s/%s 但字形是%s" % (w, kana, kind, sub or "-", form))

    dbtool.sample_check([(r[2], r[3], r[4] or "", r[5], r[6] or "-", "✓" if r[7] else "")
                         for r in rows[::max(1, len(rows) // 16)]],
                        12, ("读音", "字音", "送假名", "类", "细分", "常用"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    with dbtool.session("ja-kanji-reading", expect={"#kanji_reading": len(rows)},
                        invalidates=[]) as s:
        s.execute(DDL)
        for q in IDX:
            s.execute(q)
        s.execute("DELETE FROM kanji_reading")
        s.executemany(
            "INSERT INTO kanji_reading (word_id, entry_id, kana, kana_stem, okurigana,"
            " kind, subkind, is_joyo, seq, src, src_ref)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    joyo_tot = q("SELECT COUNT(*) FROM entry WHERE pos_raw='character'"
                 " AND kanji_grade='常用'")
    joyo_hit = q("SELECT COUNT(DISTINCT e.id) FROM entry e JOIN kanji_reading k"
                 " ON k.entry_id=e.id WHERE e.pos_raw='character'"
                 " AND e.kanji_grade='常用'")
    print("\n■ 写后回核（全量，非抽样）")
    for name, got, want in [
        ("kanji_reading 行数", q("SELECT COUNT(*) FROM kanji_reading"), len(rows)),
        ("孤儿（word_id 不在 dict）",
         q("SELECT COUNT(*) FROM kanji_reading k LEFT JOIN dict d"
           " ON d.id=k.word_id WHERE d.id IS NULL"), 0),
        ("entry_id 指向的不是 character 条目",
         q("SELECT COUNT(*) FROM kanji_reading k JOIN entry e ON e.id=k.entry_id"
           " WHERE e.pos_raw<>'character'"), 0),
        ("kind 取值越界",
         q("SELECT COUNT(*) FROM kanji_reading WHERE kind NOT IN"
           " ('on','kun','nanori')"), 0),
        ("subkind 取值越界",
         q("SELECT COUNT(*) FROM kanji_reading WHERE subkind IS NOT NULL AND"
           " subkind NOT IN ('go-on','kan-on','to-on','kan-yo-on','ko-kun')"), 0),
        ("kana_stem 还带着连字符",
         q("SELECT COUNT(*) FROM kanji_reading WHERE kana_stem LIKE '%-%'"), 0),
        ("名乗り被并进訓読み",
         q("SELECT COUNT(*) FROM kanji_reading WHERE kind='kun'"
           " AND src_ref LIKE '%:nanori:%'"), 0),
    ]:
        print("   %s %-32s %9s（期望 %s）" % ("✅" if got == want else "🔴", name,
                                            f(got), f(want)))
    print("   ⭐ **常用汉字**有音训读的 %s / %s = %.1f%%"
          % (f(joyo_hit), f(joyo_tot), 100.0 * joyo_hit / max(joyo_tot, 1)))
    con.close()


if __name__ == "__main__":
    main()
