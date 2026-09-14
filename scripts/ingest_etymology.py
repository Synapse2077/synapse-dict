#!/usr/bin/env python3
"""词源正文层 `etymology`：**六门共用一个脚本**。2026-09-14。

═══ 为什么是一份而不是六份 ═══
2026-09-14 先给 en 写了 `en/pipeline/ingest_etymology.py`，接着要套另外五门。
判据与语种无关：**「从 dump 里把 `etymology_text` 搬进库，按词源号对齐」**。
抄六份的下场这个仓库有现成的账（de 那 16 个孤儿类名、五门各抄一份的搭配 JSX）。
⇒ 合并成这一份，`--lang` 选门；**语种差异全部从库里问出来，不写死**（见 `Plan`）。
（`scripts/fix_pointer_gloss.py --lang pt` 是同一种形状的先例。）

═══ 🔴 存全文，一个字节不改 ═══
用户 2026-09-14：「线上不会放 dump，只会放 sqlite……我想看全部信息的时候能否查看」
⇒ **凡是没进 sqlite 的就是永久丢了**。入库只做搬运：`text` ＝ 源头原文，
连那棵 "Etymology tree" 一起。「只印第一句」写在展示层
（`packages/dict-labels/src/etym.ts` 的 `etymologyBrief`），改判据不用回源重抽。

═══ 🔴 `edition` 列：分清「源头没写」与「我们没抽」═══
it/fr/pt 的义项来自多个维基版（en/it/fr/pt/el/tr/zh-edition），每版**各有一套词源编号**，
而 `paths.KK` 只是英文版切片。没有这一列，服务层就分不清：
  · 抽过这一版、源头确实没写  ⇒ 页面照实说「源头未给出」
  · **这一版我们还没抽**      ⇒ 页面必须闭嘴
把后者说成前者就是把「我们没做」说成「源头没有」—— 造假，比缺更伤权威。

═══ 🔴 词源号是**位置型**键 ═══
它是「这个词的第几支词源」，只在同一份 dump 内有效。库若建自 dump A、正文抽自 B，
编号一移位就把「词源 ② 的正文」贴到「词源 ③ 的义项」上 —— **数量对得上、配对全错**，
而且看着完全合理（`[[primary-key-is-not-enough]]`）。⇒ 写库前全量比对，见 `align_gate`。

用法（仓库根）：
    python3 scripts/ingest_etymology.py --lang es
    python3 scripts/ingest_etymology.py --lang es --run
"""
import argparse
import gzip
import importlib
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANGS = ["en", "es", "it", "fr", "pt", "de"]

# 🔴 `paths.KK`（英文版 per-language 切片）在**这门库里**对应哪个来源前缀。
#    en/es/it/fr/pt 记成 `en-edition`，de 记成 `kk-en` —— 建库那几轮各自定的，
#    不是同一个字符串。**写死会过期，所以启动时必须回库核一次**（见 `Plan.check`）。
EN_PREFIX = {"en": "en-edition", "es": "en-edition", "it": "en-edition",
             "fr": "en-edition", "pt": "en-edition", "de": "kk-en"}

# ── 非英文版（2026-09-14 补）─────────────────────────────────────────────────
# it/fr/pt 的义项还来自各语言自己的维基版。它们的 dump **字段名不一样**：
#   英文版切片：`etymology_text`（单数，字符串）+ `etymology_number`
#   各语言版本：`etymology_texts`（**复数，数组**），**没有 etymology_number**
# 🔴 第一版按 `etymology_text` 去找，四份 dump 抽样全是 0%，差点判成「数据没有」——
#    **字段名对不上和数据不存在长得一模一样**。查了一条记录的全部键才看见复数那个。
#
# 🔴 **我们的 `entry.etym_no` 对这些版一律是 `"0"`**（建库时源头没给编号）。
#    也就是说：源头 `etymology_texts` 有两条以上时，**我们无从知道哪条对应哪个义项组** ——
#    那种词整词跳过。实测「恰好一条」的比例：it 94% / fr 68% / pt 20% / zh 22%，
#    够用；剩下的宁可缺，不许猜（`[[dict-framework-doc]]`：错比缺更伤权威）。
EDITION_DUMP = {
    "it-edition": "itwiktionary.jsonl.gz",
    "fr-edition": "frwiktionary.jsonl.gz",
    "pt-edition": "ptwiktionary.jsonl.gz",
    "zh-edition": "zhwiktionary.jsonl.gz",
}
# dump 是**多语种整包**，要按 lang_code 筛出目标语言那一部分。
LANG_CODE = {"it": "it", "fr": "fr", "pt": "pt", "es": "es", "de": "de", "en": "en"}

DDL = """CREATE TABLE etymology (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  word_id  INTEGER NOT NULL,          -- → dict.id
  edition  TEXT NOT NULL,             -- 哪个维基版（en-edition / it-edition / kk-en …）
  etym_no  TEXT NOT NULL,             -- 该版内的词源号；源头没编号时记 "0"
  text     TEXT NOT NULL,             -- 🔴 源头原文，一个字节不改（含 Etymology tree）
  src      TEXT NOT NULL,             -- 哪份 dump 文件
  UNIQUE(word_id, edition, etym_no)
)"""
IDX = ["CREATE INDEX idx_etym_word ON etymology(word_id)"]


def load(lang):
    """按语种载入它自己的 `paths` 与 `dbtool`（六门各一份，互不引用）。"""
    for p in (str(ROOT / lang), str(ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)
    for m in ("paths", "dbtool"):
        sys.modules.pop(m, None)
    return importlib.import_module("paths"), importlib.import_module("dbtool")


def word_src_of(ref):
    """从 `src_ref` 里取**源头词形**。六门、各版的 `src_ref` 形状不止一种：

        kk-en:gratis:adv:0:0      英文版切片：前缀:词形:pos:词源号:seq
        kk-fr:accueil:noun#0      法语版：**只有三段**，没有词源号也没有 seq
        kk-de:'n Abend:intj#0     同上，且词形自己含空格/撇号
        kk-it:a:b:noun:1:0        词形自己含冒号

    🔴 所以不能写死「第几段是词形」。规则：去掉前缀 → 从右边剥掉所有纯数字段
    （词源号、seq）→ 再剥掉一段（pos）→ 剩下的**原样拼回去**就是词形。
    ⚠️ 第一版只认五段式（`rsplit(":", 3)`），于是 fr/pt 的本版 `src_ref` 全被丢掉，
       对齐闸报「库里没有来源前缀 fr-edition」——**看起来像映射过期，其实是解析太窄**。
    """
    if not ref:
        return None
    parts = ref.split("#", 1)[0].split(":")
    if len(parts) < 3:
        return None
    rest = parts[1:]
    while rest and rest[-1].isdigit():
        rest.pop()
    if rest:
        rest.pop()                     # pos_raw
    return ":".join(rest) or None


def num_of_ref(ref):
    """`src_ref` 里的词源号（只有五段式才有）。en/de 走这条；其余四门用 `entry.etym_no`。"""
    if not ref:
        return None
    parts = ref.split("#", 1)[0].split(":")
    return parts[-2] if len(parts) >= 5 and parts[-2].isdigit() else None


def db_keys(con):
    """库里每条「词源支」：(word_id, dict 词形, 来源前缀, 源头词形, 词源号)。

    ⚠️ 取法**按库里有什么走**：es/it/fr/pt 的义项挂 `entry`，en/de 只有 `sense_src`。
       判据是「这张表有没有这一列」，不是「这门语言叫什么」——
       写死语种名的桥迟早对不上（`[[criteria-narrower-than-you-think]]`）。
    """
    has_entry = con.execute(
        "SELECT COUNT(*) FROM pragma_table_info('sense') WHERE name='entry_id'"
    ).fetchone()[0] > 0
    # 🔴 **「版」和「`src_ref` 的前缀」不是一回事**，这一步踩过：
    #      es  `entry.src` = `en-edition`，而 `entry.src_ref` = `kk-en:ate:noun:1:0`
    #      en  `sense_src.src_ref` = `en-edition:serene:adj:1:0#0`（两者恰好同名）
    #      de  `sense_src.src_ref` = `kk-en:A:noun:1:0#0`
    #    而展示层拿来当键的是 **`etymKeyOfEntry(entry.src, …)`**（es/it/fr/pt）
    #    或 **`src_ref` 的前缀**（en/de）。`edition` 必须写**展示层会用的那个**，
    #    否则服务层按 etymKey 去查，一条都查不到，而且一声不吭。
    # 🔴 **号从哪来，分两种**：
    #    es/it/fr/pt 挂 `entry` ⇒ 版取 `e.src`、号取 **`e.etym_no` 那一列**；
    #    en/de 只有 `sense_src.src_ref` ⇒ 版与号都从 `src_ref` 里拆。
    #    第一版两边都去 `src_ref` 里拆号，而 fr/pt 的**本版** `src_ref` 是三段式
    #    （`kk-fr:accueil:noun#0`，压根没有号）⇒ 整批被丢掉。
    #    展示层用的是 `etymKeyOfEntry(e.src, e.etym_no)`，这里必须跟它一致。
    sql = ("""SELECT s.word_id, d.word, e.src, e.etym_no, e.src_ref FROM sense s
              JOIN dict d ON d.id = s.word_id
              JOIN entry e ON e.id = s.entry_id
              WHERE e.etym_no IS NOT NULL AND e.etym_no <> ''"""
           if has_entry else
           """SELECT s.word_id, d.word, NULL, NULL, ss.src_ref FROM sense s
              JOIN dict d ON d.id = s.word_id
              JOIN sense_src ss ON ss.sense_id = s.id""")
    out = set()
    for wid, word, edition, etym_no, ref in con.execute(sql):
        wsrc = word_src_of(ref) or word
        no = etym_no if etym_no is not None else num_of_ref(ref)
        ed = edition or (ref.split(":", 1)[0] if ref else None)
        if no is None or ed is None or not str(no).isdigit():
            continue
        out.add((wid, word, ed, wsrc, str(no)))
    return out


def scan(dump, watch):
    """单遍扫 dump。`got` 只收有正文的；`seen` 记 `watch` 里那些词的**全部**编号。

    🔴 两者必须分开，且 `seen` **不许做字符串预筛**。en 那次为省 20 秒跳过了
       「既没 etymology_text 也没 etymology_number」的行，而那正是源头**没有编号**、
       我们记成 `"0"` 的一类 ⇒ 对齐闸把 `doddered`/`j` 这种词全判成错位。
       **判据依赖哪些行，就必须看哪些行。**
    """
    got, seen, conflict = {}, {}, 0
    t0 = time.time()
    with dump.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i % 1000000 == 0 and i:
                print("   %s 行 / %ds / 已收 %s"
                      % (format(i, ","), time.time() - t0, format(len(got), ",")), flush=True)
            o = json.loads(line)
            w = o.get("word")
            if not w:
                continue
            n = str(o.get("etymology_number") or "0")
            if w in watch:
                seen.setdefault(w, set()).add(n)
            t = o.get("etymology_text")
            if not t:
                continue
            k = (w, n)
            if k in got:
                if got[k] != t:
                    conflict += 1
                    if len(t) > len(got[k]):     # 留长的：短的那份是截断，丢长的＝丢内容
                        got[k] = t
                continue
            got[k] = t
    return got, seen, conflict


def scan_edition(dump, lang_code):
    """扫**语言自己那一版**的 dump，只收「恰好一条词源正文」的记录。

    返回 `{源头词形: 正文}`，外加统计（多条的、没有的）。
    🔴 只收恰好一条：我们的 `etym_no` 对这些版一律是 `"0"`，多条时对不上号。
    ⚠️ **不按「会印词源标题的词」过滤**。第一版传了 `watch` 进来做筛选，于是
       只有多词源的词拿得到正文，单词源的一条都没有 —— 而口径是**收全**
       （任何一个词都查得到词源，不只是同形异源那批）。干跑时表现为
       「落库 2,934 行」而本版明明有 16,548 支，差额被我当成"源头没写"报了出去。
    """
    got, many, none = {}, 0, 0
    t0 = time.time()
    with gzip.open(dump, "rt", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i % 1000000 == 0 and i:
                print("   %s 行 / %ds / 已收 %s"
                      % (format(i, ","), time.time() - t0, format(len(got), ",")), flush=True)
            o = json.loads(line)
            if (o.get("lang_code") or "") != lang_code:
                continue
            w = o.get("word")
            if not w:
                continue
            et = o.get("etymology_texts") or []
            if len(et) == 0:
                none += 1
            elif len(et) > 1:
                many += 1
            else:
                t = (et[0] or "").strip()
                # 同一个词多条记录（名/动各一）会给同一段话；取最长的那份
                if t and len(t) > len(got.get(w, "")):
                    got[w] = t
    return got, many, none


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, choices=LANGS)
    ap.add_argument("--edition", help="非英文版，如 it-edition；不给就抽英文版那一支")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    paths, dbtool = load(a.lang)
    prefix = a.edition or EN_PREFIX[a.lang]
    if a.edition and a.edition not in EDITION_DUMP:
        print("🔴 不认识的版 `%s`；已知：%s" % (a.edition, "、".join(EDITION_DUMP)))
        return 1

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    keys = db_keys(con)
    if not any(p == prefix for _, _, p, _, _ in keys):
        print("🔴 库里没有来源前缀 `%s` —— EN_PREFIX 的映射过期了，先核对再跑。" % prefix)
        con.close()
        return 1

    # 每个 dict 词形底下有几支词源（决定页面印不印「词源 ①②」）
    per_word = {}
    for wid, word, p, wsrc, no in keys:
        per_word.setdefault(word, set()).add((p, no))
    multi = {w for w, v in per_word.items() if len(v) > 1}
    print("■ %s：带词源号的词 %s｜会印词源标题的 %s"
          % (a.lang, format(len(per_word), ","), format(len(multi), ",")), flush=True)

    # 本轮只抽**英文版**那一支；其余版各有自己的 dump（`edition` 列就是为此留的）。
    # 🔴 **收全，不只收「会印词源标题的」那批**（用户 2026-09-14 拍板的口径 B）：
    #    只收同形异源那 0.5%–1.7% 省不下多少（en 实测 4.4 MB vs 42 MB，库 4.7 GB），
    #    而收全意味着**任何一个词都查得到词源**。
    mine = [(wid, word, wsrc, no) for wid, word, p, wsrc, no in keys if p == prefix]
    # 🔴 `watch` 是**源头词形**，且只盯「会印词源标题」的那批 ——
    #    对齐闸要的就是它们（错位只在多词源的词上会被读者看见），
    #    全量记 `seen` 要吃掉一两 GB 内存。
    watch = {wsrc for _, word, wsrc, _ in mine if word in multi}

    if a.edition:
        # ── 非英文版：字段是 `etymology_texts`（数组），没有编号 ──
        dumpf = paths.DUMPS / EDITION_DUMP[a.edition]
        if not dumpf.exists():
            print("🔴 dump 不在盘上：%s" % dumpf)
            con.close()
            return 1
        print("═══ 扫 dump：%s（lang_code=%s）═══" % (dumpf.name, LANG_CODE[a.lang]), flush=True)
        byword, many, none = scan_edition(dumpf, LANG_CODE[a.lang])
        print("   恰好一条词源的 %s 条｜源头给了多条（对不上号，跳过）%s｜源头没有 %s"
              % (format(len(byword), ","), format(many, ","), format(none, ",")))
        # 🔴 这些版我们的 `etym_no` 一律是 `"0"` ⇒ 只认 0 号那一支，别的一律不碰。
        got = {(w, "0"): t for w, t in byword.items()}
        seen, conflict = None, 0
    else:
        print("═══ 扫 dump：%s ═══" % paths.KK.name, flush=True)
        got, seen, conflict = scan(paths.KK, watch)
        print("   (词, 词源号) 去重后 %s 条｜同键内容不一致 %s 处（留了长的那份）"
              % (format(len(got), ","), format(conflict, ",")))

    # ═══ 闸① 对齐：库里**英文版那一支**的编号，必须被 dump 原样覆盖（按源头词形比）═══
    want = {}
    for _, word, wsrc, no in mine:
        if word in multi:
            want.setdefault(wsrc, set()).add(no)
    print("\n═══ 闸① 对齐 ═══")
    if seen is None:
        # 🔴 非英文版**没有编号可对**，对齐闸换成另一条同等强度的：
        #    我们对这些版记的必须**只有 `0` 一支**。哪天建库改成给它们编号了，
        #    这里会当场红 —— 而那时 `(w, "0")` 那个写法就已经在错配了。
        odd = sorted({no for _, _, _, no in mine if no != "0"})
        print("   本版在库里的词源号取值：%s" % (sorted({no for _, _, _, no in mine})))
        if odd:
            print("   🔴 出现了 `0` 以外的编号 %s —— 建库口径变了，`(w,\"0\")` 的假设不再成立。"
                  % odd)
            con.close()
            return 1
        bad = []
    else:
        bad = sorted(w for w, v in want.items() if w in seen and not v <= seen[w])
        print("   英文版有份的源头词形 %s｜对不齐 %s（%.3f%%）"
              % (format(len(want), ","), format(len(bad), ","), 100 * len(bad) / max(len(want), 1)))
        for w in bad[:8]:
            print("      · %s  库 %s ｜ dump %s" % (w, sorted(want[w]), sorted(seen.get(w, []))))
        if len(bad) > max(50, len(want) * 0.01):
            print("   🔴 对不齐比例过高 —— dump 与建库源多半不是同一份，不许落库。")
            con.close()
            return 1

    # 🔴 折叠碰撞：同一个 `(word_id, 版, 词源号)` 底下挂着两个不同的源头词形
    #    （es 的 `CAN`/`can`、it/fr 的直撇号/弯撇号）。表的唯一键是这三样，
    #    两份正文塞不进同一行 ⇒ **整组跳过**。缺比错轻，且量在千分之一以下。
    #
    # ═══ 已量过、决定**不修**的一件事（2026-09-14，落账免得再翻）═══
    # 展示层的 `etymKey` 是 `(版, 词源号)`，**不含源头词形** ⇒ 理论上会把两个词并成一支。
    # 用户问要不要修。回库数了「真会印出词源标题、且确实撞键」的词：
    #     es 撞键 69 组 → **真受影响 0 个词**（都是单键词，压根不印标题）
    #     fr 撞键  1 组 → 0      pt 0 组 → 0
    #     it 撞键  4 组 → **2 个词**：`senz'altro` / `in un batter d'occhio`
    # 而那 2 个一查是**直撇号与弯撇号的同一个短语**（`senz'altro` ↔ `senz’altro`）——
    # 合并恰恰是对的，拆开反而错。
    # ⇒ **零个真缺陷**。要「修」得给 `etymology` 加 `word_src` 列 + 六门重抽 + 动服务层与闸，
    #   代价不小、收益为负。不做。哪天 `dict.word` 的折叠口径变了再回来看这段。
    slot = {}
    for wid, _, wsrc, no in mine:
        slot.setdefault((wid, no), set()).add(wsrc)
    clash = {k for k, v in slot.items() if len(v) > 1}
    print("   折叠碰撞（一个词形下两个源拼写共用同一词源号）%s 组，整组跳过"
          % format(len(clash), ","))

    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()

    skip, seen_slot, rows, missing = set(bad), set(), [], 0
    for wid, _, wsrc, no in mine:
        if wsrc in skip or (wid, no) in clash or (wid, no) in seen_slot:
            continue
        t = got.get((wsrc, no))
        if not t:
            missing += 1            # 源头这一支没写正文 —— 正常，不是错
            continue
        seen_slot.add((wid, no))
        rows.append((wid, prefix, no, t,
                     EDITION_DUMP[a.edition] if a.edition else str(paths.KK.name)))
    rows.sort(key=lambda r: (r[0], r[2]))

    nbytes = sum(len(r[3].encode("utf-8")) for r in rows)
    print("\n═══ 计划 ═══")
    print("   落库              %12s 行   %.1f MB" % (format(len(rows), ","), nbytes / 1024 ** 2))
    print("   覆盖词形          %12s" % format(len({r[0] for r in rows}), ","))
    print("   源头这一支没写正文 %12s（正常，页面照实说）" % format(missing, ","))
    print("   带 Etymology tree %12s"
          % format(sum(1 for r in rows if r[3].lstrip().lower().startswith("etymology tree")), ","))
    if not a.run:
        print("\n(干跑。加 --run 才写库)")
        return 0

    with dbtool.session("ingest-etymology-%s" % (a.edition or a.lang),
                        expect={"#etymology": len(rows)}) as s:
        if "etymology" not in have:
            s.execute(DDL)
            for i in IDX:
                s.execute(i)
        s.executemany(
            "INSERT INTO etymology (word_id, edition, etym_no, text, src) VALUES (?,?,?,?,?)",
            rows)

    # ═══ 闸② 写后回核：新开只读连接，不复用会话里那条 ═══
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda sql: con.execute(sql).fetchone()[0]      # noqa: E731
    checks = [("本版行数", q("SELECT COUNT(*) FROM etymology WHERE edition='%s'" % prefix),
               len(rows)),
              ("空正文", q("SELECT COUNT(*) FROM etymology WHERE TRIM(text)=''"), 0),
              ("孤儿 word_id", q("SELECT COUNT(*) FROM etymology e WHERE NOT EXISTS"
                                 "(SELECT 1 FROM dict d WHERE d.id=e.word_id)"), 0),
              ]
    con.close()
    print("\n═══ 闸② 写后回核 ═══")
    ok = True
    for name, v, want in checks:
        ok &= v == want
        print("   %s %-14s %s（期望 %s）"
              % ("✅" if v == want else "🔴", name, format(v, ","), format(want, ",")))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
