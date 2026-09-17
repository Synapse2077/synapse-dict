#!/usr/bin/env python3
"""阶段 0（上半）：建库 —— `dict` 骨架。2026-09-15。（下半是 `build_v3_schema.py` 建十四张表）

═══ 🔴 ja 没有「迁移」这个动作 ═══
de/pt 的阶段 0 叫「表结构迁移」：它们先建了扁平的 `dict`（带 `definition`/`translation`/
`collocation`/`example`/`flag` 等 v2 遗留列），v2/v3 设计出来之后才把这些列搬进新表，
de 那轮还为此做了「可逆性回核」—— 后来发现**那个能力几周前就没了**
（比的是「从新表重建 vs dict 原列」，而中间补过义项、重排过 rank，两边必然不等）。

ja 直接建成最终结构 ⇒ **`dict` 里一个 v2 遗留列都不建**。不搬、不需要回核、
也不会有 de「降列导致回归闸 A2 失效」那种连带。
这是新语种唯一一处比前六门占便宜的地方（`PLAYBOOK` 第零节点名的最贵返工来源）。

═══ 判据：什么进 `dict` ═══
只收**真词条目**的词形。原始 199,484 行里先剔两类（占 39%）：

    soft-redirect  44,899   异表记 / 同音索引页，**一条 gloss 都没有**
    romanization   32,062   罗马字条目（`nihongo`）

🔴 `soft-redirect` 的词形**要能被搜到**（查 `あかるい` 不该返回 0 条），但**不在这一步收**：
   现在插进来只有词形、没有指向、没有义项，等于造 4.5 万个「搜得到、点进去空白页」。
   pt 正是这么栽的：阶段顺序错导致 **355,605 个词形（46.2%）既无义项也无变形链**。
   ⇒ 它们连同指向一起进**阶段 3**，见 `JA_PLAN` §三⑤ 与 §五。
   ⚠️ 而且它不是一对一：7,079 条（15.8%）有 ≥2 个目标，`いぬ → 犬 狗 戌 率寝 寝ぬ 去ぬ`
      是**同音索引页**不是异体 —— 当异体写进关系层是 6,681 条规模的错。

═══ `word_norm`：折叠只用于**匹配**，绝不用于**身份** ═══
片假名 → 平假名 + NFKC。⚠️ 折叠后**实测 576 组碰撞、卷进 1,159 个词头**（`あい`/`アイ`、`あ`/`ア` ——
它们是**不同的词条**）。
⚠️ 这个数比只折假名的口径（541 组 / 1,084 个）大，差额来自 `NFKC`：
它还会把全角/半角、`（´・ω・｀）` 的四种写法、`〒`/`〶` 折到一起。
**有意保留 NFKC** —— 那几类折叠对检索是对的；代价是碰撞面更大，
而碰撞本来就只影响匹配、不影响身份。
这与西语 `Cefalópodos`/`cefalópodos` 吃掉 573 个专名词头是同一个形状，照它的修法：
**`word` 原样存不折叠，`word_norm` 是折叠副本，精确拼写是检索第一排序键。**
⚠️ SQLite 的 `COLLATE NOCASE`/`lower()` 只折 ASCII，对假名无效 ⇒ 折叠必须在 Python 侧做。

跑（在 ja/ 目录下）：
    python3 -u pipeline/build.py            # 干跑，只报数
    python3 -u pipeline/build.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import json
import unicodedata

import dbtool
import paths

# 这两类不是词，剔掉。判据是源头自己给的 `pos`，不是形式代理。
NOT_A_WORD = {"soft-redirect", "romanization"}

# 片假名 → 平假名：整段区间平移 0x60（ァ U+30A1 → ぁ U+3041）。
# ⚠️ 只平移 U+30A1–U+30F6；`ー`(U+30FC) 长音符**不动**，它在平假名里也写作 `ー`。
_KATA_LO, _KATA_HI, _SHIFT = 0x30A1, 0x30F6, 0x60


def norm_ja(s: str) -> str:
    """检索归一：NFKC（半角片假名/全角字母归位）+ 片假名折成平假名。

    🔴 **只用于匹配，不用于身份**。见文件头。
    """
    t = unicodedata.normalize("NFKC", s or "")
    return "".join(chr(ord(c) - _SHIFT) if _KATA_LO <= ord(c) <= _KATA_HI else c for c in t)


def is_pointer_sense(se) -> bool:
    tg = se.get("tags") or []
    return bool(se.get("form_of") or se.get("alt_of")
                or "form-of" in tg or "alt-of" in tg or "romanization" in tg)


def scan():
    """扫英文版切片 → 每个词形一条记录。返回 (rows, stat)。"""
    words = {}                       # word → {pos:Counter, lemma:bool}
    stat = collections.Counter()
    for line in open(paths.KK, encoding="utf-8"):
        o = json.loads(line)
        stat["原始行"] += 1
        pos = o.get("pos")
        if pos in NOT_A_WORD:
            stat["剔除·%s" % pos] += 1
            continue
        w = o.get("word")
        if not w:
            stat["无词头"] += 1
            continue
        # 🔴 源头确实收了「空格」这个字符（`pos=punct`，1 条）。但**词典里一行空白
        #    比少收一个空格更伤**（`[[dict-framework-doc]]`：错比缺更伤权威），
        #    而且它会让后续任何「词形非空」的不变量失效。
        #    ⚠️ 明说是**我们跳过的**，不是源头没有（`[[dont-say-source-lacks-what-we-skipped]]`）。
        if not w.strip():
            stat["剔除·词形是空白（源头有，我们不收）"] += 1
            continue
        stat["真词条目"] += 1
        e = words.setdefault(w, {"pos": collections.Counter(), "lemma": False})
        e["pos"][pos] += 1
        # 词元判据：**这个词形有没有至少一条不是指针的义项**。
        # 🔴 不用「词性是不是 X」这种形式代理 —— 指针与否是源头逐义项说清楚的。
        for se in (o.get("senses") or []):
            if (se.get("glosses") or []) and not is_pointer_sense(se):
                e["lemma"] = True
                break
    rows = []
    for w, e in words.items():
        # 聚合词性：多个词条目时按出现量排，`/` 连接（逐义项词性在 sense.pos）
        pos = "/".join(p for p, _ in e["pos"].most_common() if p)
        rows.append((w, norm_ja(w), pos or None, 1 if e["lemma"] else 0))
    rows.sort(key=lambda r: r[0])
    stat["不同词形"] = len(rows)
    stat["词元"] = sum(r[3] for r in rows)
    return rows, stat


DDL_DICT = """CREATE TABLE dict (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  word        TEXT NOT NULL,        -- 书写形，**原样不折叠**（汉字/假名/混排）
  word_norm   TEXT NOT NULL,        -- 检索归一：NFKC + 片假名→平假名。只用于匹配不用于身份
  is_lemma    INTEGER NOT NULL,     -- 有没有至少一条非指针义项
  pos         TEXT,                 -- 聚合词性（逐义项词性在 sense.pos）
  -- ── 日语一等字段 ──
  -- 🔴 **读音不在这儿，在 `entry`**：一个词形可以有多个词条、各读各的音
  --    （`猫` = ねこ / ねこま），3,951 条 entry 一条里就有 ≥2 个读音。
  --    放 `dict` 上等于断言「一个词形一个读音」，那是错的。见 JA_PLAN §二.1–2。
  kanji_grade TEXT,                 -- 字种等级（常用/教育/人名用/表外）——**字形**的属性
  level       TEXT,                 -- CEFR / JLPT，后续阶段填
  freq_zipf   REAL                  -- 阶段 5 填；量不出来的留 NULL 不填 0
  -- ⚠️ 这里**有意不建** definition/translation/meta/infl/exchange/collocation/
  --    example/flag 八个 v2 遗留列 —— 那是 de/pt 要迁移才有的包袱，de 后来专门
  --    跑 `--drop-cols` 把它们删掉。ja 直接建成最终结构，不制造这笔债。
);"""

DDL_INDEX = [
    # 🔴 **不建 `COLLATE NOCASE` 索引**：SQLite 的 NOCASE 只折 ASCII，对假名完全无效，
    #    而症状不是慢、是**查不到词**。前六门都有 `idx_word ON dict(word COLLATE NOCASE)`，
    #    日语照抄就是留一个假索引。折叠走 `word_norm`（Python 侧算好的）。
    "CREATE INDEX idx_word ON dict(word)",
    "CREATE INDEX idx_word_norm ON dict(word_norm)",
    "CREATE INDEX idx_lemma ON dict(is_lemma)",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    rows, stat = scan()
    print("■ 扫 %s" % paths.KK.name)
    for k in ("原始行", "剔除·soft-redirect", "剔除·romanization",
              "剔除·词形是空白（源头有，我们不收）", "无词头",
              "真词条目", "不同词形", "词元"):
        if stat[k]:
            print("   %-22s %9s" % (k, format(stat[k], ",")))
    print("   %-22s %9s" % ("非词元（只有指针义项）", format(stat["不同词形"] - stat["词元"], ",")))

    dbtool.sample_check([(w, n, p, l) for w, n, p, l in rows[:2000:137]],
                        10, ("词形", "归一", "词性", "词元"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    # 建库这一步允许从空库开始 —— tag 必须以 `build` 开头，见 dbtool._ALLOW_EMPTY_PREFIX
    with dbtool.session("build-ja-skeleton",
                        expect={"__rows__": len(rows), "pos": len(rows)}) as s:
        s.execute(DDL_DICT)
        for q in DDL_INDEX:
            s.execute(q)
        s.executemany(
            "INSERT INTO dict (word, word_norm, is_lemma, pos) VALUES (?,?,?,?)",
            [(w, n, l, p) for w, n, p, l in rows])

    print("\n═══ 写后回核 ═══")
    con = dbtool.ro() if hasattr(dbtool, "ro") else None
    import sqlite3
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("dict 行数", q("SELECT COUNT(*) FROM dict"), len(rows)),
        ("word 唯一", q("SELECT COUNT(*) FROM (SELECT word FROM dict GROUP BY word HAVING COUNT(*)>1)"), 0),
        ("word_norm 空", q("SELECT COUNT(*) FROM dict WHERE word_norm=''"), 0),
        ("词元数", q("SELECT COUNT(*) FROM dict WHERE is_lemma=1"), stat["词元"]),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-16s %10s（期望 %s）" % ("✅" if good else "🔴", name,
                                              format(got, ","), format(want, ",")))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
