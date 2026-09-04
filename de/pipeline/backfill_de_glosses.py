#!/usr/bin/env python3
"""阶段 1.5c：把德语版释义补到**已有英文义项**的词上（唯一映射那一档）。2026-09-04。

═══ 这一步是外锚闸逼出来的 ═══
阶段 7 建 `verify_vs_dump.py`（锚外部 dump、永不过期的那类闸）第一次跑就报：
**德语版源头 238,364 条真释义，1.5a 只收了 135,179，缺 103,171 条**（62,577 个词形）。
所有内部闸都看不见它 —— 词形在库、义项也在库，缺的是**这条义项的德语原文**
（`[[external-anchor-gates]]`：es 那轮同一道闸逮到 `derived` 义项级漏收 20,193 条）。

═══ 🔴 缺口不是 bug，是 1.5a 的收录范围换掉的一笔钱 ═══
`ingest_de_senses.main()` 的 `targets` 是 `zero = 一条义项都没有的词形` ——
**只补英文版没覆盖的词**。这个范围有它的道理：

    es / fr  本语言版对**所有词**都收 ⇒ 与英文版词形重叠 15–28%
             ⇒ 同一个词两套义项，必须逐条裁决（fr 花掉一整笔钱）
    pt / de  只补零义项的词          ⇒ 重叠 0.0%（de 实测 **3 个词**）
             ⇒ 裁决这一笔从没发生

⚠️ **所以「重叠 0.0%」不是德语的性质，是这个范围决定的结果。**
   而 `[[gloss-three-languages]]` 定的方针是「释义保留三语：中文＋英文＋本语言」，
   于是 `Dezember` 有英文义项、有中文，**独独缺德语原文** —— 这是对着已定方针的真缺口。

═══ 免费路径分三档，本步只做第一档 ═══
（`[[prove-free-path-before-quoting]]`：报价必须带「试过哪些免费路径、各自为什么不行」）

    ① 库 1 条义项 · 源 1 条真释义 · 词性相容  → **唯一映射，本步做**   36,134 词形
    ② 库 n 条 · 源 n 条，按序位对              → 🔴 **不做**            5,082 词形
    ③ 条数不同                                → 需要判官，另行报价     19,628 词形

🔴 **② 为什么不做**：它靠「两个版本的义项顺序一一对应」，而那是两个社区各自编的。
   ③ 的样本直接反证：`Neustadt` 库 27 条 / 源 2 条、`kommen` 库 19 条 / 源 8 条 ——
   两版切分义项的粒度根本不同，②那 5,082 个只是**碰巧条数相同**。
   把下标当稳定契约正是 `[[one-problem-at-a-time]]` 那条教训的形状。

═══ 判据：什么叫「唯一映射」═══
① 这个词形在库里**恰好 1 条**出版义项，且它没有德语释义
② 德语版给这个词形**恰好 1 条**真释义（判据 import `ingest_de_senses.is_real_sense`）
③ **词性相容**

🔴 词性那一关被样本打回两次，记下来免得下一轮重走：
   · v1 不查词性 —— 会把「德语版讲的是另一个同形词」的情况混进来
   · v2 词性**完全相等** —— 挡掉 2,233 条，读样本发现**大多不是错配**：
     `Niederländisch`/`Wonnemond`/`Afrikaans` 库=name 源=n，
     两版对「专名 vs 普通名词」的归类习惯不同，意思完全对得上
     ⇒ v3 把 `name` 与 `n` 视为同一类（德语所有名词首字母大写，
       专名/普通名词的界线本来就是编辑约定）
   · v3 仍挡掉 1,733 条，样本显示**还是大多对的**：`PKW`/`z. B.`/`CD` 库=n·adv、
     源=abbrev —— 德语版把缩写按**形式**归类，我们的 `pos` 记的是展开后的**功能**。
   ⇒ **停在 v3**（`[[criteria-narrower-than-you-think]]`：修判据三轮就停手，
     残差当上界报）。停在这一边是安全的：那 1,733 条是**被漏掉**不是**被搞错**，
     属于「缺」不属于「错」（`FRAMEWORK §一`）。

═══ 闸 ═══
① `dbtool` 的 expect 闸（`#sense_gloss` / `#sense_src` 增量显式声明）。
② 不变量：只补到「原本没有德语释义」的义项上 ／ 一条义项不许有两条德语释义 ／
   证据行必须挂上义项 ／ 补完之后「缺德语释义的词形」必须真的降下来。
③ 抽样反验：打印德语原文与库里已有的中文并排 —— 这一步**没有自动判据**，
   两者对不对得上只能人眼看。

用法（在 de/ 目录下）：
    python3 -u pipeline/backfill_de_glosses.py            # 干跑
    python3 -u pipeline/backfill_de_glosses.py --apply
"""
import argparse
import gzip
import json
import random
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbtool                                                  # noqa: E402
import paths                                                   # noqa: E402
from build import POS_MAP                                      # noqa: E402
from ingest_de_senses import is_real_sense                     # noqa: E402
from intake_edition_words import EDITIONS, norm_word           # noqa: E402

f = lambda n: format(n, ",")
SRC = "de-edition-backfill"
# 名词类：德语所有名词首字母大写，「专名 vs 普通名词」两版归类不同 —— 见文件头 v2。
NOUNISH = {"n", "name"}


def pos_ok(db_pos, src_pos):
    """词性相容判据。**只有这一份**，闸也调它。"""
    return db_pos == src_pos or {db_pos, src_pos} <= NOUNISH


def norm_gloss(s):
    return re.sub(r"\s+", " ", s or "").strip()


def collect(con):
    """→ {词形: (sense_id, pos)}，只含「恰好 1 条义项、且缺德语释义」的词形。"""
    out = {}
    for w, sid, pos in con.execute(
            "SELECT d.word, s.id, s.pos FROM sense s JOIN dict d ON d.id=s.word_id "
            " WHERE NOT EXISTS(SELECT 1 FROM sense_gloss g "
            "                   WHERE g.sense_id=s.id AND g.lang='de')"
            "   AND (SELECT COUNT(*) FROM sense x WHERE x.word_id=s.word_id)=1"):
        out[norm_word(w)] = (sid, pos)
    return out


def scan(one, words):
    """扫德语版 → (rows_gloss, rows_src, stat, 抽样用的三元组)。"""
    path, need_filter = EDITIONS["de"]
    cand, seq_of = {}, Counter()
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if need_filter and '"lang_code"' in line and '"de"' not in line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("lang_code") != "de":
                continue
            w = norm_word(e.get("word"))
            if w not in one:
                continue
            pos_raw = e.get("pos") or "unknown"
            k = (w, pos_raw)
            seq = seq_of[k]
            seq_of[k] += 1
            for i, s in enumerate(e.get("senses") or []):
                if not is_real_sense(s):
                    continue
                cand.setdefault(w, []).append(
                    (POS_MAP.get(pos_raw, pos_raw), norm_gloss((s.get("glosses") or [""])[0]),
                     s.get("tags") or [], "kk-de:%s:%s:%d#%d" % (w, pos_raw, seq, i)))
    gl, sr, stat, show = [], [], Counter(), []
    for w, items in cand.items():
        if len(items) != 1:
            stat["源头不是恰好 1 条真释义（本档不收，归 ③）"] += 1
            continue
        pos, g, tags, ref = items[0]
        sid, dbpos = one[w]
        if not g:
            continue
        if not pos_ok(dbpos, pos):
            stat["🔴 词性不相容（收紧掉，残差见文件头）"] += 1
            continue
        # 🔴 `kind` 是 NOT NULL，取值 `equivalent`（对应词）/ `definition`（定义式）。
        #    德语版给的是**定义式**（„der zwölfte und somit letzte Monat eines Jahres"），
        #    与 1.5a 落的那 135,179 条同类 —— **照现有约定填，不新造第三种值**。
        #    第一版传 None 被 `NOT NULL` 当场拦下、事务整个回滚，数据一个字节没动。
        gl.append((sid, "de", "definition", 0, g, SRC))
        sr.append((words[w], sid, SRC, ref, "de", g,
                   json.dumps(tags, ensure_ascii=False) if tags else None))
        stat["✅ 唯一映射 ⇒ 可确定性补"] += 1
        show.append((w, dbpos, g, sid))
    return gl, sr, stat, show


def missing_de(con):
    """还有多少个词形一条德语释义都没有 —— 本步的**目的**就是这个数降下来。"""
    return con.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT s.word_id FROM sense s "
        " WHERE NOT EXISTS(SELECT 1 FROM sense_gloss g "
        "                   WHERE g.sense_id=s.id AND g.lang='de'))").fetchone()[0]


def gate2(con, expect):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("sense_gloss(de) 行数 == 期望",
         q("SELECT COUNT(*) FROM sense_gloss WHERE lang='de'"), expect["gloss"]),
        ("🔴 一条义项有两条德语释义",
         q("SELECT COUNT(*) FROM (SELECT sense_id FROM sense_gloss WHERE lang='de' "
           "GROUP BY 1 HAVING COUNT(*)>1)"), 0),
        ("🔴 本步的证据行没挂上义项",
         q("SELECT COUNT(*) FROM sense_src WHERE src=%r AND sense_id IS NULL" % SRC), 0),
        ("🔴 本步的证据行挂到别的词上",
         q("SELECT COUNT(*) FROM sense_src x JOIN sense s ON s.id=x.sense_id "
           "WHERE x.src=%r AND s.word_id<>x.word_id" % SRC), 0),
        ("🔴 本步写的德语释义为空",
         q("SELECT COUNT(*) FROM sense_gloss WHERE lang='de' AND src=%r "
           "AND TRIM(COALESCE(text,''))=''" % SRC), 0),
        # 🔴 本步的**目的**。它不降 = 白做。
        ("🔴 缺德语释义的词形没有降下来",
         1 if missing_de(con) >= expect["missing_before"] else 0, 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-42s %12s  期望 %s" % ("✓" if good else "🔴", name, f(got), f(want)))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    words = {norm_word(w): i for w, i in con.execute("SELECT word, id FROM dict")}
    one = collect(con)
    before = missing_de(con)
    n_gl = con.execute("SELECT COUNT(*) FROM sense_gloss WHERE lang='de'").fetchone()[0]
    con.close()
    print("■ 缺德语释义的词形 %s ／ 其中只有 1 条义项的 %s ／ 现有德语释义 %s"
          % (f(before), f(len(one)), f(n_gl)))

    gl, sr, stat, show = scan(one, words)
    print()
    for k, v in stat.most_common():
        print("   %-46s %10s" % (k, f(v)))
    print("\n■ 可补 %s 条德语释义（缺德语释义的词形 %s → %s）"
          % (f(len(gl)), f(before), f(before - len(gl))))

    random.seed(7)
    print("\n── 抽样反验：德语原文 vs 库里已有的中文（人眼核，无自动判据）──")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    zh = dict(con.execute("SELECT sense_id, text FROM sense_gloss WHERE lang='zh'"))
    con.close()
    for w, p, g, sid in random.sample(show, min(14, len(show))):
        print("   %-22s [%-4s] %-56s ｜ %s" % (w[:22], p, g[:56], (zh.get(sid) or "（无中文）")[:24]))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    with dbtool.session("keep-v3-15c-de-gloss",
                        expect={"#sense_gloss": len(gl), "#sense_src": len(sr)}) as s:
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?,?,?,?,?,?)", gl)
        s.executemany("INSERT INTO sense_src (word_id,sense_id,src,src_ref,lang,text,raw_tags) "
                      "VALUES (?,?,?,?,?,?,?)", sr)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    after = missing_de(con)
    print("\n■ 缺德语释义的词形 %s → %s（降 %s，-%.1f%%）"
          % (f(before), f(after), f(before - after), 100 * (before - after) / max(before, 1)))
    ok = gate2(con, {"gloss": n_gl + len(gl), "missing_before": before})
    con.close()
    print("\n%s" % ("✓ 闸②全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
