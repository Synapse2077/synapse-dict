#!/usr/bin/env python3
"""阶段 1.5b：把英文 gloss 译成中文。2026-09-15。

═══ 译什么、从哪译 ═══
源文本是**英文 gloss**（`sense_gloss(lang='en')`，141,773 条全覆盖），
不是日语定义 —— 后者只有 13.6% 的义项有。
⚠️ 有日语定义时**作为上下文给模型**（帮它消歧），但明说「只译英文那条」。
   `[[context-you-give-leaks-into-output]]`：给模型的"仅供参考"会直接漏进输出 ——
   这里有个便宜的抓手：日语漏出来必然带假名，**控制组的 E1 正好逮它**。

═══ 🔴 payload 带 `kana`（读音）—— 日语特有的一条 ═══
同形异读是日语的常态（`月` = つき 月亮／げつ 月份／がち）。
读音是消歧信息，前六门没有这个维度。

═══ 控制组 ═══
判据在 `ja/pipeline/ctrl.py`（变异验证 9/9），**跑批与闸 import 同一份**。
🔴 日语不能用前六门那套：`has_han` 在这门语言上恒真，`日本語` 原样抄回会被判合格。

跑（在仓库根）：
    python3 -u ja/pipeline/translate_defs.py --slice 1     # 1% 切片
    python3 -u ja/pipeline/translate_defs.py --read        # 逐条读切片结果
"""
import sys as _sys
import pathlib as _pl
# 🔴🔴 **只把 `ja/` 放进 sys.path，绝不放别的语种。**
# 2026-09-15 差点出事：第一版为了用 `it/pipeline/ds_batch`，把 `it/` 插在最前面，
# 于是 `import paths` / `import dbtool` 拿到的是**意大利语那份**，
# 脚本连上了 `synapse-dict-it.sqlite`（报错「no such column: e.kana」才暴露）。
# 这次只读没写，同一个形状发生在写库那一步就是**往错的库里写**。
# ⇒ `ds_batch` 已拷成 `ja/pipeline/ds_batch.py`（铁律①：宁可重复不要耦合）。
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import asyncio
import collections
import json
import sqlite3

import dbtool
import paths
from pipeline import ctrl
from pipeline.ds_batch import run as ds_run          # noqa: E402  ja 自己那份

SYS = """你在把日语词典的释义翻译成中文，用于一部给中文读者的日语词典。

输入是 JSON 数组，每项有：
  `id`    标识号，**不是序号**，原样回传
  `word`  被解释的日语词
  `kana`  该词条的假名读音（同形异读时用它区分：月 つき 月亮／げつ 月份）
  `pos`   词性（n 名词／v 动词／adj 形容词／adv 副词／name 专名／kanji 汉字／phr 短语…）
  `en`    该义项的英文释义 —— **要翻译的就是这一条**
  `ja`    该义项的日语原文释义，**可能没有**。只作消歧参考，**不要翻译它、不要抄它**
  `sib`   这个词已有的其他义项中文（可能没有），**避免和它们重复**

规则
1. 输出**中文释义**，不是逐字翻译。能用一个常用汉语词对应就给那个词，
   不能对应就给一句简短的解释。
2. 🔴 **不许出现任何假名**（ひらがな・カタカナ）。出现假名说明没翻完。
3. 🔴 **不要把词头本身抄回来当释义**。原文只是重复 `word` 时，`zh` 给空字符串。
4. 🔴 **不要输出元描述**。「…的连用形」「…的异体字」「…的旧字体」说的是语法关系
   不是词义，`zh` 给空字符串。
5. 🔴 **词性要对上 `pos`**：`v` 给动词说法（「吃」不是「食物」），`n` 给名词说法。
6. 专名（`pos=name`）：有通用中文译名的用通用译名（`東京` →「东京」）；
   没有通用译名的**保留原文汉字**，不要音译生造。
7. `pos=kanji` 是「这个汉字本身」的条目：给这个字的字义（`犬` →「狗」），
   不要写成「汉字『犬』」这种元描述。
8. 学名、化学式、度量单位原样保留。
9. **不加句末标点**，不写「指」「表示」这类引导语。
10. 原文残缺或看不出意思，`zh` 给空字符串，不要猜。

输出 JSON **对象**，键是 `id`（字符串），值是 `{"zh": "<中文释义>"}`：
{"12345": {"zh": "狗"}, "12346": {"zh": "吃"}}
每个输入 id 都要有一个键，一个都不能少。只输出 JSON，不要解释。"""

SYS_JA = """你在把日语词典的释义翻译成中文，用于一部给中文读者的日语词典。

输入是 JSON 数组，每项有：
  `id`    标识号，**不是序号**，原样回传
  `word`  被解释的日语词
  `kana`  该词条的假名读音（同形异读时用它区分）
  `pos`   词性（n 名词／v 动词／adj 形容词／adv 副词／name 专名／kanji 汉字／phr 短语…）
  `ja`    该义项的**日语原文释义** —— 要翻译的就是这一条
  `sib`   这个词已有的其他义项中文（可能没有），**避免和它们重复**

规则
1. 输出**中文释义**，不是逐字翻译。能用一个常用汉语词对应就给那个词，
   不能对应就给一句简短的解释。
2. 🔴🔴 **不许出现任何假名**（ひらがな・カタカナ）。原文是日语，抄回原文最省事也最没用 ——
   出现假名一律视为没翻。
3. 🔴 **日语汉字词与汉语同形不等于同义**：`勉強` 是「学习」不是「勉强」，
   `手紙` 是「信」不是「手纸」，`大丈夫` 是「没问题」不是「大丈夫」。
   **按日语的意思译，不要看见汉字就照搬。**
4. 🔴 **不要输出元描述**。「…的连用形」「…的异体字」说的是语法关系不是词义，`zh` 给空字符串。
5. 🔴 **词性要对上 `pos`**：`v` 给动词说法，`n` 给名词说法。
6. 专名（`pos=name`）：有通用中文译名的用通用译名；没有的**保留原文汉字**，不要音译生造。
7. 学名、化学式、度量单位原样保留。
8. **不加句末标点**，不写「指」「表示」这类引导语。
9. 原文残缺或看不出意思，`zh` 给空字符串，不要猜。

输出 JSON **对象**，键是 `id`（字符串），值是 `{"zh": "<中文释义>"}`：
{"12345": {"zh": "学习"}, "12346": {"zh": "信"}}
每个输入 id 都要有一个键，一个都不能少。只输出 JSON，不要解释。"""


OUT = paths.WORK / "translate" / "defs.jsonl"
OUT_JA = paths.WORK / "translate" / "defs_ja.jsonl"
CHUNK = 60


def pool(slice_pct=None, frm="en"):
    """要翻的义项：有 `frm` 语言 gloss、**还没有中文**的那些。

    🔴 `frm='ja'` 是阶段 3b：**日译中**，和 1.5b 的英译中不是同一道题。
       日语汉字词与汉语同形不等于同义（`勉強`＝学习不是勉强），抄回原文的诱惑大得多
       ⇒ SYS 另写一份、控制组的 E1「残留假名」在这一轮是主力判据。
       ⚠️ **不许拿 1.5b 的实测单价直接套**（`[[prove-free-path-before-quoting]]`），
          这一轮要自己跑切片量。
    """
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = con.execute("""
        SELECT s.id, d.word, e.kana, s.pos,
               (SELECT g.text FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='en' LIMIT 1),
               (SELECT g.text FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='ja' LIMIT 1),
               s.word_id
        FROM sense s JOIN dict d ON d.id=s.word_id
        LEFT JOIN entry e ON e.id=s.entry_id
        WHERE NOT EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='zh')
        ORDER BY s.id""").fetchall()
    # 兄弟义项已有的中文（payload 纪律①：不带会让模型把同一个意思译两遍）
    sib = collections.defaultdict(list)
    for wid, t in con.execute(
            "SELECT s.word_id, g.text FROM sense_gloss g JOIN sense s ON s.id=g.sense_id"
            " WHERE g.lang='zh'"):
        sib[wid].append(t)
    con.close()
    out = []
    for sid, w, kana, pos, en, ja, wid in rows:
        main = ja if frm == "ja" else en
        if not main:
            continue
        # 🔴 切片判据用 `id % 100`，**确定性可复现** —— 随机抽样没法「再跑一次对比」
        if slice_pct and sid % 100 >= slice_pct:
            continue
        p = {"id": sid, "word": w, "pos": pos or "?", frm: main}
        if kana:
            p["kana"] = kana
        if frm == "en" and ja:
            p["ja"] = ja
        if sib.get(wid):
            p["sib"] = sib[wid][:4]
        out.append(p)
    return out


def read_back():
    """逐条读切片结果 + 过控制组。🔴 **判据 import `ctrl`，不手抄。**"""
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    src = {r[0]: (r[1], r[2], r[3]) for r in con.execute(
        "SELECT s.id, d.word, (SELECT g.text FROM sense_gloss g"
        " WHERE g.sense_id=s.id AND g.lang='en' LIMIT 1), s.pos"
        " FROM sense s JOIN dict d ON d.id=s.word_id")}
    con.close()
    hits = collections.Counter()
    rows = []
    n = 0
    for line in OUT.open(encoding="utf-8"):
        r = json.loads(line)
        sid = r.get("id")
        zh = (r.get("zh") or "").strip()
        w, en, pos = src.get(sid, ("?", "", None))
        n += 1
        bad = ctrl.check(zh, en, w, pos)
        for c, _ in bad:
            hits[c] += 1
        rows.append((sid, w, en, zh, bad))
    print("■ 切片 %s 条" % f"{n:,}")
    print("■ 控制组命中：")
    for c, v in sorted(hits.items()):
        print("   %-4s %5d  %5.2f%%   %s" % (c, v, 100 * v / n,
              next(d for cc, d in ctrl.check("", "", "") + [(c, "")] if cc == c) if c == "E0" else ""))
    # 🔴 `W` 开头是警告不是失败 —— 分开算，否则一个「无法用形式判定」的量会假装成错误率
    err = sum(1 for *_, b in rows if any(c[0] == "E" for c, _ in b))
    warn = sum(1 for *_, b in rows if b and not any(c[0] == "E" for c, _ in b))
    print("   🔴 真失败 %s 条 = %.2f%%   ⚠️ 只带警告 %s 条 = %.2f%%   ✅ 干净 %s 条 = %.1f%%"
          % (f"{err:,}", 100 * err / n, f"{warn:,}", 100 * warn / n,
             f"{n - err - warn:,}", 100 * (n - err - warn) / n))
    print("\n■ 随机 12 条逐条读（🔴 控制判据全过也要人眼读 —— de 那轮读完发现 88/129 是判据宽）")
    for sid, w, en, zh, bad in rows[::max(1, n // 12)][:12]:
        flag = ((("🔴 " if any(c[0] == "E" for c, _ in bad) else "⚠️ ")
                 + ",".join(c for c, _ in bad)) if bad else "  ")
        print("   %s %-10s %-40s → %s" % (flag, w, (en or "")[:40], zh))


def _assert_ja():
    """🔴 开跑前确认 `paths`/`dbtool` 真是 ja 那份 —— 这是上面那个 near-miss 的闸。
    一条永远通过的检查等于没有检查，所以它查的是**具体的库文件名**。"""
    assert paths.DB.name == "synapse-dict-ja.sqlite", "🔴 paths 不是 ja 的：%s" % paths.DB
    assert not hasattr(dbtool, "has_han"), "🔴 dbtool 不是 ja 的（ja 那份没有 has_han）"


def load():
    """把 `defs.jsonl` 落进 `sense_gloss(lang='zh')`。

    🔴 **留空的不落**（E0，1,909 条）：那是模型按 SYS 规则 10「看不出意思就空着」
       主动弃权，写一行空释义比没有更伤。
    ⚠️ **控制组的红不作为过滤条件**：判据有假阳（残余 151 条里读 10 条，多数仍是判据宽），
       拿它过滤会把正确译文一起丢掉。残差当**上界**记进计划表，不静默处理。
    ⚠️ 答案按 `sense.id` 认领，**不按行号**（`[[model-answer-files-key-by-id]]`）。
    """
    import sqlite3 as _sq
    con = _sq.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {r[0] for r in con.execute("SELECT sense_id FROM sense_gloss WHERE lang='zh'")}
    alive = {r[0] for r in con.execute("SELECT id FROM sense")}
    con.close()
    rows, empty, dup, orphan = [], 0, 0, 0
    seen = set()
    for line in OUT.open(encoding="utf-8"):
        r = json.loads(line)
        sid, zh = r.get("id"), (r.get("zh") or "").strip()
        if sid not in alive:
            orphan += 1
            continue
        if sid in have or sid in seen:
            dup += 1
            continue
        if not zh:
            empty += 1
            continue
        seen.add(sid)
        rows.append((sid, "zh", "equivalent", 0, zh,
                     "model:deepseek-v4-flash" + (":from-ja" if OUT is OUT_JA else "")))
    print("■ 可落 %s 条 ｜ 留空不落 %s ｜ 已有中文跳过 %s ｜ 孤儿 %s"
          % (f"{len(rows):,}", f"{empty:,}", f"{dup:,}", f"{orphan:,}"))
    with dbtool.session("ja-translate-defs", expect={"#sense_gloss": len(rows)}) as s:
        s.executemany("INSERT INTO sense_gloss (sense_id, lang, kind, seq, text, src)"
                      " VALUES (?,?,?,?,?,?)", rows)
    con = _sq.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    n = q("SELECT COUNT(*) FROM sense")
    zh = q("SELECT COUNT(DISTINCT sense_id) FROM sense_gloss WHERE lang='zh'")
    checks = [
        ("中文 gloss 里混进假名（判据用错就会这样）", q(
            "SELECT COUNT(*) FROM sense_gloss WHERE lang='zh' AND src LIKE 'model%'"
            " AND (text GLOB '*[ぁ-ゖ]*' OR text GLOB '*[ァ-ヺ]*')"), None),
        ("空中文", q("SELECT COUNT(*) FROM sense_gloss WHERE lang='zh' AND TRIM(text)=''"), 0),
        ("孤儿 gloss", q("SELECT COUNT(*) FROM sense_gloss g LEFT JOIN sense s"
                       " ON s.id=g.sense_id WHERE s.id IS NULL"), 0),
    ]
    ok = True
    for name, got, want in checks:
        if want is None:
            print("   ⚠️ %-38s %10s（已知上界，不当红）" % (name, format(got, ",")))
            continue
        good = got == want
        ok &= good
        print("   %s %-38s %10s（期望 %s）" % ("✅" if good else "🔴", name,
                                              format(got, ","), format(want, ",")))
    print("   ⭐ 中文覆盖 %s / %s = %.2f%%" % (format(zh, ","), format(n, ","), 100 * zh / n))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


def main():
    _assert_ja()
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=int, help="只跑 N%% 的切片（按 id %% 100）")
    ap.add_argument("--read", action="store_true", help="逐条读已跑的结果")
    ap.add_argument("--mode", default="flash")
    ap.add_argument("--load", action="store_true", help="把答案落库")
    ap.add_argument("--from", dest="frm", default="en", choices=["en", "ja"],
                    help="从哪个语言译（en＝阶段 1.5b，ja＝阶段 3b）")
    a = ap.parse_args()
    global OUT
    if a.frm == "ja":
        OUT = OUT_JA
    if a.read:
        return read_back()
    if a.load:
        return load()

    p = pool(a.slice, a.frm)
    batches, meta = [], []
    for i in range(0, len(p), CHUNK):
        batches.append(p[i:i + CHUNK])
        meta.append([(str(x["id"]), x["id"]) for x in p[i:i + CHUNK]])
    print("■ 池子 %s 条 / %s 批（CHUNK=%d）" % (f"{len(p):,}", f"{len(batches):,}", CHUNK))
    est = sum(len(json.dumps(b, ensure_ascii=False)) for b in batches) / 2.5
    print("■ 粗估入 token ≈ %s" % f"{int(est):,}")
    tok = asyncio.run(ds_run(SYS_JA if a.frm == "ja" else SYS, batches, meta, OUT,
                             mode=a.mode, conc=10,
                             every=5, thinking="disabled"))
    print("■ 实跑 token %s" % f"{tok:,}")


if __name__ == "__main__":
    main()
