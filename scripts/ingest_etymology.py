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
import collections
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
    # 🔴 de 的本版前缀是 `kk-de`，**不是 `de-edition`** —— 与 `EN_PREFIX` 里
    #    de 记 `kk-en` 同源（建库那几轮各自定的字符串）。写成 `de-edition`
    #    会一条都对不上，而且一声不吭。2026-09-15 补，此前 de 本版整个没抽。
    "kk-de": "dewiktionary.jsonl.gz",
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
    """`src_ref` 里的词源号。en/de 走这条；其余四门用 `entry.etym_no`。

    🔴 **两种形状，靠「从右数连续的纯数字段」区分，不靠段数、更不靠前缀**
       （与 `packages/dict-core/src/etym.ts` 的 `etymKeyOfSrcRef` 是同一条规则，
        两边必须一致，否则灌进库的键和页面查的键对不上、且一声不吭）：

        前缀:词:pos:词源号:seq   尾随数字 2 段 ⇒ 号在 [-2]   en / de 的英文版切片
        前缀:词:pos:seq         尾随数字 1 段 ⇒ 号在 [-1]   de 的德语版

    ⚠️ 原来写死 `len(parts) >= 5`，于是 de 的德语版 171,313 条全部返回 None，
       `db_keys` 把它们整批跳过 —— 表现为「de 本版没有词源」，
       而真相是**我们没抽**（2026-09-15 修）。
    ⚠️ `pos` 段**永不是纯数字**（de 全量实测 0 例），所以游标不会越界。
    """
    if not ref:
        return None
    parts = ref.split("#", 1)[0].split(":")
    trail = 0
    for p in reversed(parts):
        if p.isdigit():
            trail += 1
        else:
            break
    if trail not in (1, 2) or len(parts) < trail + 2:
        return None
    return parts[-trail]


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

    返回 `{源头词形: 正文}`，外加统计（多条的、没有的、同词冲突丢弃的）。
    🔴 只收恰好一条：我们的 `etym_no` 对这些版一律是 `"0"`，多条时对不上号。

    🔴🔴 **「多条」有两种形状，第一版只守住了一种**（2026-09-14 验收查出来的）：
      ① 一个条目里 `etymology_texts` 有 2 条以上  → 整词跳过（原来就有）
      ② **同一个词有多个条目，各自 1 条，内容却不同** → 原来「取最长的那份」
    ②' 的注释写着「名/动各一**会给同一段话**」—— 这个假设不成立。
       法语版 dump 按词性拆条目，`sur` 的形容词条（古法兰克语 *sûr「酸」）
       和介词条（拉丁 super「在…上」）是**两支完全不同的词源**，
       按字符串长度挑 ＝ 抛硬币。实测 fr 1,526 个词中招，其中 148 个 zipf≥4.0，
       `sur`(6.8) / `tu`(6.5) 手工核对**挑错了那一支**，且会渲染上页面。
    ⇒ ② 与 ① 归一处理：**内容不同就整词丢弃**。同一个判据不许两条路径只守一条
       （`[[correct-steps-can-compose-a-hole]]`）。宁可缺，不许猜。
    ⚠️ it/pt/zh 版实测冲突数为 0（那几版 dump 不按词性拆条目），本改动只影响 fr。
    ⚠️ **不按「会印词源标题的词」过滤**。第一版传了 `watch` 进来做筛选，于是
       只有多词源的词拿得到正文，单词源的一条都没有 —— 而口径是**收全**
       （任何一个词都查得到词源，不只是同形异源那批）。干跑时表现为
       「落库 2,934 行」而本版明明有 16,548 支，差额被我当成"源头没写"报了出去。
    """
    got, many, none = {}, 0, 0
    conflict = set()          # 同词多条记录、内容互不相同 ⇒ 整词丢弃（见 docstring ②）
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
                if not t:
                    continue
                prev = got.get(w)
                if prev is None:
                    got[w] = t
                elif prev != t:
                    # 🔴 同一个词的另一个条目给了**不同**的词源 ⇒ 无从判断哪支对应哪个义项组
                    conflict.add(w)
    # 冲突的整词丢弃（不是留一个）。丢多少由调用方打印出来，**不许静默**。
    for w in conflict:
        got.pop(w, None)
    return got, many, none, len(conflict)


def scan_edition_seq(dump, lang_code):
    """扫本语种版 dump，按 **(词形, pos) 在 dump 里的出现顺序** 给条目编号，
    返回 `{(词形, seq): 正文}`。给 **de 的德语版**用。

    ═══ 为什么 de 和 it/fr/pt 不是一回事 ═══
    it/fr/pt 的本版 `src_ref` 是三段式、`etym_no` 一律 `"0"`（源头没编号）；
    **de 的是 `kk-de:词:pos:seq#义项下标`**，那个数字不是词源号，是
    `de/pipeline/ingest_de_senses.py` 里 `seq_of[(word, pos_raw)]` 这个计数器 ——
    「这是该 (词,pos) 在 dump 里的第几个条目」。而**每个条目自带
    `etymology_texts`** ⇒ 对齐反而是精确的，不像 it/fr 那样要靠「恰好一条」。

    🔴 **这是位置型键，必须验过才能用。** 建库当时的 `targets` 是「一条义项都没有的
       词」，那个状态已经不存在、无法重建。验法：`src_ref` 里带着 pos 和义项下标，
       而 `sense_src.text` 存着释义原文 ⇒ 拿 `senses[下标].glosses[0]` 逐条比。
       2026-09-15 实测：抽 3,000 条**释义逐字节一致 3,000 条（100%）**、
       seq 越界 0 条 ⇒ 按原始 (词,pos) 枚举与建库当时等价。
       （另有 96 行 0.06% 的 (词,pos) 在 dump 里找不到 —— `clean_head` 改写过，收不到。）

    ⚠️ 同一个词的不同 pos 各自从 0 起数 ⇒ **(词, seq) 会跨 pos 碰撞**（实测 509 个词、
       0.3%）。这里与 `scan_edition` 同一口径：**内容不同就整词丢弃**，不挑不猜。
       （不把 pos 塞进键：那要连带动 `etymKeyOfSrcRef`、`db_keys` 的数字断言和
        `etym_no` 在六门里的语义，为 0.3% 铺这么大的面不划算。）
    """
    got, none, many = {}, 0, 0
    conflict = set()
    seq_of = collections.Counter()
    seq_max = {}              # 词形 → 该词形见过的最大 seq（供闸①查越界，见 main）
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
            pos = o.get("pos") or "unknown"
            seq = seq_of[(w, pos)]
            seq_of[(w, pos)] += 1
            if seq > seq_max.get(w, -1):
                seq_max[w] = seq
            et = o.get("etymology_texts") or []
            if len(et) == 0:
                none += 1
                continue
            if len(et) > 1:
                many += 1
                continue
            t = (et[0] or "").strip()
            if not t:
                continue
            k = (w, str(seq))
            prev = got.get(k)
            if prev is None:
                got[k] = t
            elif prev != t:
                conflict.add(k)          # 跨 pos 撞了同一个 (词,seq) 且内容不同
    for k in conflict:
        got.pop(k, None)
    return got, many, none, len(conflict), seq_max


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, choices=LANGS)
    ap.add_argument("--edition", help="非英文版，如 it-edition；不给就抽英文版那一支")
    ap.add_argument("--run", action="store_true")
    # 🔴 重跑用：先把**这一版**已有的行删干净再插。判据变了就必须能重跑，
    #    否则「发现抽错了」等于「永远改不了」。只删本版，别版一行不碰。
    ap.add_argument("--replace", action="store_true",
                    help="先删掉本版已有的行再写（重跑用）")
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
        # 🔴 **两种口径，判据取自库里这一版的号，不写死语种**：
        #      号全是 "0"  ⇒ 源头本来就没编号（it/fr/pt/zh）→ 只收「恰好一条」的词
        #      号有 0 以外 ⇒ 那是 **seq**（de：该 (词,pos) 的第几个 dump 条目）
        #                    → 按 (词,pos) 出现顺序枚举，逐条目对齐
        #    写死 `if lang == "de"` 迟早过期（`[[criteria-narrower-than-you-think]]`）。
        nums = {no for _, _, _, no in mine}
        by_seq = nums - {"0"} != set()
        print("   本版在库里的号取值 %s ⇒ 走 **%s** 口径"
              % (sorted(nums)[:6], "逐条目(seq)" if by_seq else "恰好一条"))
        seq_max = None
        if by_seq:
            byword, many, none, dropped, seq_max = scan_edition_seq(dumpf, LANG_CODE[a.lang])
            got = dict(byword)                       # 键已经是 (词形, seq)
        else:
            byword, many, none, dropped = scan_edition(dumpf, LANG_CODE[a.lang])
            got = {(w, "0"): t for w, t in byword.items()}
        print("   恰好一条词源的 %s 条｜源头给了多条（对不上号，跳过）%s｜源头没有 %s"
              % (format(len(byword), ","), format(many, ","), format(none, ",")))
        # 🔴 同键多条记录、内容互不相同 ⇒ 整个丢弃。**必须打出来**：
        #    这一类原来是「按字符串长度静默二选一」，fr 有 1,526 个词中招
        #    （`sur`/`tu` 挑错了那一支）。静默丢弃和静默挑错一样不可接受。
        print("   同键多条记录**内容不同**、整键丢弃 %s（宁可缺，不许猜）"
              % format(dropped, ","))
        seen, conflict = None, 0
    else:
        seq_max = None
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
        print("   本版在库里的词源号取值：%s" % (sorted({no for _, _, _, no in mine})[:8]))
        if seq_max is not None:
            # ── seq 口径（de）：**号必须落在 dump 真实存在的条目上** ──
            # 这是位置型键，强度等价于英文版的「编号被 dump 原样覆盖」：
            # 建库当时按 (词,pos) 出现顺序编号，若我这遍枚举与当时不同步，
            # 必然出现「库里的 seq 比 dump 里该词的条目数还大」。
            # ⚠️ 离线另验过一条更强的（不放进热路径，太吃内存）：`src_ref` 里带义项下标，
            #    拿 `senses[下标].glosses[0]` 与 `sense_src.text` 逐条比 ——
            #    2026-09-15 抽 3,000 条**释义逐字节一致 3,000 条（100%）**。
            oob = [(w, n) for _, _, w, n in mine
                   if w in seq_max and int(n) > seq_max[w]]
            miss = sorted({w for _, _, w, _ in mine if w not in seq_max})
            print("   seq 越界（库里的号大于 dump 该词的条目数）%s"
                  % format(len(oob), ","))
            print("   dump 里找不到这个词形 %s（clean_head 改写过，收不到）"
                  % format(len(miss), ","))
            if oob:
                for w, n in oob[:8]:
                    print("      · %s  库 seq=%s ｜ dump 最大 %s" % (w, n, seq_max[w]))
                print("   🔴 出现越界 —— 我这遍枚举与建库当时不同步，配对不可信，不许落库。")
                con.close()
                return 1
            bad = []
        else:
            # ── 全 0 口径（it/fr/pt/zh）：我们对这些版记的必须**只有 `0` 一支** ──
            odd = sorted({no for _, _, _, no in mine if no != "0"})
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

    old_n = 0
    if a.replace and "etymology" in have:
        con2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        old_n = con2.execute("SELECT COUNT(*) FROM etymology WHERE edition=?",
                             (prefix,)).fetchone()[0]
        con2.close()
        print("   重跑模式：本版已有 %s 行，将先删后插（净变化 %+d）"
              % (format(old_n, ","), len(rows) - old_n))
    with dbtool.session("ingest-etymology-%s" % (a.edition or a.lang),
                        expect={"#etymology": len(rows) - old_n}) as s:
        if "etymology" not in have:
            s.execute(DDL)
            for i in IDX:
                s.execute(i)
        if old_n:
            s.execute("DELETE FROM etymology WHERE edition='%s'" % prefix)
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
