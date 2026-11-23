#!/usr/bin/env python3
"""空壳词条闸 —— 「有词条，页面上什么可读内容都没有」。2026-11-17。

═══ 为什么有这道闸 ═══
用户问「各个语言都存在有词条但没内容的单词」。实测十门：

    en 208,117（5.19%）／pt 6,391／de 7,920／it 261／es 7／其余五门 0

两类成因**完全不同**（处理方式也不同，见 BACKLOG）：
  · en：ECDICT 的 `low` 质量释义被 `intake_legacy.plan_gloss` 判为 `published=0`
    —— 208,117 条**全部**有释义，是「有意不发布」，不是源头没写；
  · pt/de：kaikki 的屈折形/变体（`10seitige`、`Cleusa`），源头没有定义、
    而且没连上原形（`inflection` 无行）⇒ 页面只剩词头。

⇒ 本闸锁住这个基线：**谁重跑某一层把内容弄丢了，空壳数会涨，当场红。**
   用户 2026-11-17 定：搜索保留这些词（收词方针是「词全」），页面要明说
   「暂无可发布的释义」；pt/de 那批补变形关系。基线只许降、不许悄悄涨。

═══ 口径 ═══
「页面上没有任何可读内容」= 下面所有层都空：
  义项 `sense`／词源 `etymology`／读音 `pronunciation`／词条结构 `entry`／
  变形关系 `inflection`（两端都算）／关系 `sense_relation`／
  已发布的 ECDICT 兜底 `legacy_gloss.published=1`（仅 en）／
  汉字读音 `kanji_reading`（ja）／`hanja_reading`（ko）／`han_spelling`+`nom_spelling`（vi）。

🔴 **基线是 2026-11-17 独立实测的常量，不从库里现推** —— 从现状推的期望永远等于现状，
   删掉一个词条的内容它也不会红（`[[expectation-must-be-declared]]`）。
   数字变少是好事：闸打 ✅ 并提示可以下调基线。
   数字变多是**回归**：红，并指出涨了多少。

⚠️ 不计 `example`/`audio`：有例句/录音一般也有义项；单独算会让真正空的词漏过去。
⚠️ 这是**数据层近似**，不是渲染验证。展示层的空状态由各门契约闸管。

用法：
    python3 -u scripts/test_empty_entry_gate.py        # 跑闸（含变异自检）
"""
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = str(ROOT / "data" / "db" / "synapse-dict-%s.sqlite")

LANGS = ["en", "es", "it", "fr", "pt", "de", "ja", "ko", "vi", "ru"]

# 2026-11-17 实测基线。加语言或修数据后，**只有变少才动它**。
BASE = {
    "en": 208117, "es": 7, "it": 261, "fr": 0, "pt": 6391,
    "de": 7920, "ja": 0, "ko": 0, "vi": 0, "ru": 0,
}

# 每门「变形关系」怎么算。ru 的 inflection 只有 entry_id，没有 word_id/base_id。
INFLECTION = {
    l: "EXISTS (SELECT 1 FROM inflection i WHERE i.word_id=d.id OR i.base_id=d.id)"
    for l in ("en", "es", "it", "fr", "pt", "de", "ja", "ko")
}
INFLECTION["vi"] = "0"   # vi 没有 inflection 表
INFLECTION["ru"] = ("EXISTS (SELECT 1 FROM inflection i "
                    "JOIN entry e3 ON e3.id=i.entry_id WHERE e3.word_id=d.id)")

# 各门特有的「也算内容」的表。
EXTRA = {
    "en": ["EXISTS (SELECT 1 FROM legacy_gloss g WHERE g.word_id=d.id AND g.published=1)"],
    "ja": ["EXISTS (SELECT 1 FROM kanji_reading k WHERE k.word_id=d.id)"],
    "ko": ["EXISTS (SELECT 1 FROM hanja_reading k WHERE k.word_id=d.id)"],
    "vi": ["EXISTS (SELECT 1 FROM han_spelling k WHERE k.word_id=d.id)",
           "EXISTS (SELECT 1 FROM nom_spelling k WHERE k.word_id=d.id)"],
}
# 十门都有 sense_relation。
for _l in LANGS:
    EXTRA.setdefault(_l, []).append(
        "EXISTS (SELECT 1 FROM sense_relation r WHERE r.word_id=d.id)")


def empty_sql(lang: str) -> str:
    cond = [
        "NOT EXISTS (SELECT 1 FROM sense s WHERE s.word_id=d.id)",
        "NOT EXISTS (SELECT 1 FROM etymology x WHERE x.word_id=d.id)",
        "NOT EXISTS (SELECT 1 FROM pronunciation p WHERE p.word_id=d.id)",
        "NOT EXISTS (SELECT 1 FROM entry en WHERE en.word_id=d.id)",
        "NOT (%s)" % INFLECTION[lang],
    ] + ["NOT (%s)" % e for e in EXTRA[lang]]
    return "SELECT count(*) FROM dict d WHERE " + " AND ".join(cond)


def count_empty(con: sqlite3.Connection, lang: str) -> int:
    return con.execute(empty_sql(lang)).fetchone()[0]


def total(con: sqlite3.Connection) -> int:
    return con.execute("SELECT count(*) FROM dict").fetchone()[0]


# ── 变异自检：在内存库里证明判据真的认得出「空壳」和「不空」 ──
def make_fixture() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE dict (id INTEGER PRIMARY KEY, word TEXT, pos TEXT, is_lemma INT);
        CREATE TABLE sense (id INTEGER PRIMARY KEY, word_id INT);
        CREATE TABLE etymology (id INTEGER PRIMARY KEY, word_id INT);
        CREATE TABLE pronunciation (id INTEGER PRIMARY KEY, word_id INT);
        CREATE TABLE entry (id INTEGER PRIMARY KEY, word_id INT);
        CREATE TABLE inflection (id INTEGER PRIMARY KEY, word_id INT, base_id INT);
        CREATE TABLE sense_relation (id INTEGER PRIMARY KEY, word_id INT);
        INSERT INTO dict(id, word) VALUES (1, 'shell'), (2, 'full');
        INSERT INTO sense(word_id) VALUES (2);
    """)
    return con


def selftest() -> int:
    bad = 0

    def check(name: str, got, want) -> None:
        nonlocal bad
        ok = got == want
        print("   %s %-46s %s / %s" % ("✅" if ok else "🔴", name, got, want))
        bad += not ok

    con = make_fixture()
    check("M1 一个只有 dict 行的词条 ⇒ 空壳", count_empty(con, "it"), 1)
    con.execute("INSERT INTO etymology(word_id) VALUES (1)")     # 救 shell
    check("M2 任何一层（词源）都能把它从空壳里救出来", count_empty(con, "it"), 0)
    con.execute("DELETE FROM etymology")
    con.execute("INSERT INTO sense(word_id) VALUES (2)")         # 改的是 full
    check("M3 改另一个词的内容，不影响 shell", count_empty(con, "it"), 1)
    con.execute("INSERT INTO inflection(word_id, base_id) VALUES (2, 1)")  # base_id 指向 shell
    check("M4 变形关系的**两端**都算内容（base_id 命中）", count_empty(con, "it"), 0)
    con.execute("DELETE FROM inflection")
    con.execute("INSERT INTO pronunciation(word_id) VALUES (1)")
    check("M5 读音也算内容", count_empty(con, "it"), 0)
    con.execute("DELETE FROM pronunciation")
    check("M6 反控制：删掉 ⇒ 回到 1（判据不是恒 0）", count_empty(con, "it"), 1)
    con.close()
    return bad


def main() -> int:
    print("═══ 空壳词条闸：有词条但页面上没有任何可读内容 ═══\n")
    print("   %-4s %10s %10s %8s  %s" % ("门", "空壳", "基线", "占比", "状态"))
    red = 0
    for l in LANGS:
        db = DB % l
        if not Path(db).exists():
            print("   %-4s %10s %10s %8s  ⚠️ 库不存在，跳过" % (l, "-", BASE[l], "-"))
            continue
        t0 = time.time()
        try:
            con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
            n = count_empty(con, l)
            tot = total(con)
            con.close()
        except sqlite3.Error as e:
            print("   🔴 %-4s 查不动：%s" % (l, e))
            red += 1
            continue
        base = BASE[l]
        pct = 100.0 * n / tot if tot else 0.0
        if n > base:
            state = "🔴 比基线多 %d" % (n - base)
            red += 1
        elif n < base:
            state = "✅ 比基线少 %d（可下调基线）" % (base - n)
        else:
            state = "✅"
        print("   %-4s %10s %10s %7.2f%%  %s  (%.1fs)"
              % (l, format(n, ","), format(base, ","), pct, state, time.time() - t0))

    print("\n═══ 变异自检（内存库）═══")
    mut = selftest()

    print()
    if red or mut:
        print("🔴 空壳 %d 门超基线 ／ 变异 %d 条没逮到" % (red, mut))
        return 1
    print("✅ 十门空壳数都在基线以内")
    return 0


if __name__ == "__main__":
    sys.exit(main())
