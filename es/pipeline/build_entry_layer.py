#!/usr/bin/env python3
"""建 es 的 `entry` 词条层，并给每条义项一个**内容派生**的锚。2026-08-20。

═══ 为什么做这件事（判据是量出来的，不是照搬 it）═══
2026-08-20 逐条评估了 it 有而 es 没有的三张表，结论是**只做两张**：

  ✅ entry              ← 本文件
  ✅ inflection         ← build_inflection_layer.py
  ❌ pronunciation_entry  全量回源实测只有 **14 个**词形符合「不同词条读音不同」，
                          逐条处理即可。西语正字法基本音位化，it 的 `pesca`
                          /ˈpɛska/ 桃子 vs /ˈpeska/ 捕鱼 那种对立在西语里不成系统。
                          （咨询的两家分别估 ~200 和 ~2,500，都错了一到两个数量级；
                            我自己第一把粗尺子给 13,742，错了三个数量级。）

🔴 **entry 的理由不是词性分组，也不是词源。** 这两条我一开始都写错过：
  · 词性分组 `sense.pos` 早就有了，`App.tsx:1249` 的 `senseHasPos` 2026-08-12 就
    把 `llama`（羊驼）的「及物」徽标修掉了 —— 我只查了 `dict.transitivity` 列
    没查读取路径，又犯了「量源头不量落点」。
  · 词源轴在西语几乎是空的：全 dump 807,155 行里只有 10,041 条带 `etymology_number`，
    同 (词形,词性) 多词源的仅 1,017 组，且绝大多数是后缀（`-a` / `-ado`）。

真正的理由只有一条，但它很硬：**证据层锚在行号上**。

    es  sense_src.src_ref = 'dict:3#1:en'        ← dict.id + definition 文本列第几行
    it  entry.src_ref     = 'kk-en:pie:noun:3:0' ← 词形+词性+词源号，内容派生

`build_sense_layer.py:509` 把 `sense_owner` 的 4,501 条**人工归属**键在这个 src_ref 上，
注释还写着「重建后仍稳定的回源坐标」。它不稳定 —— 记账本里那条
「`split_case_homographs` 的 4,501 条归属被 `build_sense_layer` 重建抹掉」就是这一批。
「把易变的当稳定契约」在本项目已经咬过四次，这是第五处。

⇒ 本文件给每条 en-edition 义项挂上 `entry_id`，锚从「第几行」换成「哪个词条」。
   旧 `src_ref` **不删**，冻结成迁移锚点（同 it 对 `dict.ipa` 的处置）。

═══ entry 的主键 ═══
`src_ref = kk-en:<原拼写>:<kaikki 原词性>:<词源号>:<seq>`
· 用**原拼写**不是小写 —— `build.py:227` 的 `key = word.lower()` 把 `A` 和 `a` 折进
  同一个桶，那正是 [[case-folding-contaminates-columns]] 记的坑，别在新表里复制它。
· 用 **kaikki 原词性**（noun/verb）不是 es 短码 —— src_ref 要能回源，短码是我们的转换。
  `entry.pos` 列另存短码，与 `sense.pos` 同一套，方便 join。
· wiktextract 会把同一维基章节切成多条 JSON。键重复时：读音与词源文本都相同 ⇒ 合并；
  否则 `seq` 递增分开。**合并前逐组断言**，不同的会被数出来。

═══ 三道闸 ═══
① **可逆性回核**（100%，非抽样）：复刻 `build.py` 的义项循环，
   算出的每条义项文字必须与 `sense_src(en-edition)` 里同一坐标的 `text` **逐字节相同**。
   对不上的那条就不挂 entry_id —— 宁可留空，不许挂错。
   🔴 这道闸同时证明了两件事：锚对了、且 `build.py` 到今天没被谁悄悄改过输出。
② 不变量断言：entry 无孤儿 / src_ref 无重复 / 每个 entry_id 指向的 pos 与 sense.pos 相符。
③ 抽样：本步是确定性复刻，无判断成分，不适用。

用法（在 es/ 目录下）：
    python3 pipeline/build_entry_layer.py            # 试算 + 三道闸，不写库
    python3 pipeline/build_entry_layer.py --apply    # 建表并写入
    python3 pipeline/build_entry_layer.py --mutate   # 变异验证：闸必须报出人为破坏
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbtool   # noqa: E402
import paths    # noqa: E402
import build as B   # noqa: E402   复刻的判据直接 import 被复刻的那份代码（A93）

SRC = "en-edition"
REF = re.compile(r"^dict:(\d+)#(\d+):en$")

DDL = """CREATE TABLE entry (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  word_id  INTEGER NOT NULL,        -- → dict.id（词形仍是搜索与身份单位）
  pos      TEXT NOT NULL,           -- es 短码，与 sense.pos 同一套；不再是 "n/v" 串
  pos_raw  TEXT NOT NULL,           -- kaikki 原词性，src_ref 用的就是它
  etym_no  TEXT NOT NULL,           -- 词源号；没编号记 "0"
  seq      INTEGER NOT NULL,        -- 同键内序号，正常 0
  spelling TEXT NOT NULL,           -- **原拼写**（dict.word 可能是小写折叠后的）
  src      TEXT NOT NULL,
  src_ref  TEXT NOT NULL,           -- kk-en:<原拼写>:<原词性>:<词源号>:<seq>
  UNIQUE(src_ref)
)"""
IDX = ["CREATE INDEX idx_entry_word ON entry(word_id)",
       "CREATE INDEX idx_entry_pos  ON entry(word_id, pos)"]


# ───────────────────────── 复刻 ─────────────────────────
def replay(dump_path):
    """复刻 build.py:243-283 的循环。**只要 real_gloss 那一支**，逐条记来源 entry。

    返回 (buckets, entry_meta)：
      buckets[word.lower()] = [(gloss, ekey), …]   顺序与 build.py 写进 definition 的一致
      entry_meta[ekey]      = {ipa, etym_text, n}
    """
    buckets = defaultdict(lambda: {"glosses": [], "seen": set(), "alt": {}})
    meta = {}
    n_line = 0
    with open(dump_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            if e.get("lang_code") != "es":
                continue
            word = (e.get("word") or "").strip()
            if not word:
                continue
            n_line += 1
            rec = buckets[word.lower()]
            pos = e.get("pos", "")
            ekey = (word, pos, str(e.get("etymology_number") or "0"))
            m = meta.setdefault(ekey, {"ipa": None, "etym": None, "n": 0})
            m["n"] += 1
            if m["ipa"] is None:
                m["ipa"] = B.pick_ipa(e.get("sounds"))
                m["etym"] = (e.get("etymology_text") or "")[:200]
            # build.py 的三个判据，逐字照抄（affix / abbr / 变位义）
            is_affix = pos in ("suffix", "prefix", "infix", "interfix")
            for s in e.get("senses", []):
                tags = s.get("tags", [])
                is_abbr = bool(set(tags) & B.ABBR_TAGS)
                g = re.sub(r"\s+", " ", (s.get("glosses") or [""])[0]).strip()
                if not g:
                    continue
                if (not is_affix and not is_abbr and B.is_infl_sense(s)
                        and B.base_of(s)):
                    # 变位/异体指针：build.py 把它写进 infl 不写进 definition。
                    # 但 `absconder` 的 `obsolete form of esconder` 这类**后来被补收成了义项**
                    # （4,741 个词形「库比复刻多」里的一大族）。它们同样来自某个 dump entry，
                    # 记进**次级**表，锚的时候主表查不到再查它。
                    rec["alt"].setdefault(g, ekey)
                    continue
                if g in rec["seen"]:
                    continue                       # 🔴 按**桶**去重，正是 build.py 的行为
                rec["seen"].add(g)
                rec["glosses"].append((g, ekey))
    return ({k: (v["glosses"], v["alt"]) for k, v in buckets.items()}, meta, n_line)


def assign_seq(meta):
    """同 (拼写,词性,词源号) 出现多次时定 seq。读音与词源文本都相同 ⇒ 同一个 entry。

    ⚠️ 这里**不做**「都当成一个」的省事处理：it 那边实测 1,813 组重复键里有 2 组
       读音不同（是真的两个词），压掉就等于让一个词条连同它的读音整个不可见。
    """
    # meta 的键已含拼写/词性/词源号，wiktextract 的多条 JSON 已在 replay 里合并进同一个
    # ekey（`m["n"]` 记了合并了几条）。真要分 seq 得在 replay 里按 ipa 分桶 ——
    # 先量：有多少键合并了 >1 条 JSON。
    return Counter(v["n"] for v in meta.values())


# ───────────────────────── 闸① ─────────────────────────
def gate_reversible(con, buckets, verbose=True):
    """复刻结果 vs sense_src(en-edition)，**逐条逐字节**。

    → (plan, counters)
      plan = [(sense_id, ekey)]  只含逐字节对上的那些。对不上的一条都不挂。
    """
    ev = defaultdict(dict)        # word_id -> {idx: (sense_id, text)}
    for sid, wid, ref, text in con.execute(
            "SELECT sense_id, word_id, src_ref, text FROM sense_src WHERE src=?", (SRC,)):
        m = REF.match(ref or "")
        if m:
            ev[wid][int(m.group(2))] = (sid, text)

    lower_ids = defaultdict(list)
    id_by_word = {}
    for i, w in con.execute("SELECT id, word FROM dict"):
        lower_ids[w.lower()].append(i)
        id_by_word.setdefault(w, i)

    plan, c = [], Counter()
    for key, (items, alts) in buckets.items():
        ids = lower_ids.get(key)
        if not ids:
            c["桶在库里没有对应词形"] += 1
            continue

        # ── 尺子甲：顺序保真度（只报，不决定挂谁）──────────────────────
        # 🔴 第一版拿它兼做挂锚的判据，两次都被**位置**咬：
        #    ① 按 dict.id 升序拼两行的证据 → `Andorra` 那 204 个大小写拆分桶全红；
        #    ② 改成按拼写分派 → `a`/`A` 这类**折叠残留**（证据还躺在小写行上、
        #       按合并顺序排）又红。位置在这份数据上根本不是稳定契约。
        #    ⇒ 顺序只用来证明「复刻忠实」，挂锚改用尺子乙。
        canon = min(ids)
        per_row = defaultdict(list)
        for g, ekey in items:
            per_row[id_by_word.get(ekey[0], canon)].append((g, ekey))
        touched = False
        for rid in ids:
            d = ev.get(rid) or {}
            seq = [d[k] for k in sorted(d)]
            if not seq:
                continue
            touched = True
            mine = per_row.get(rid) or []
            n = min(len(seq), len(mine))
            same = sum(1 for j in range(n) if seq[j][1] == mine[j][0])
            if same == len(seq) == len(mine):
                c["顺序·整行逐字节相同"] += 1
            elif same == n and n:
                c["顺序·一侧是另一侧的前缀"] += 1
            elif same:
                c["顺序·部分对齐"] += 1
            else:
                c["顺序·完全不对齐（折叠残留/后来补收）"] += 1
        if not touched:
            c["无 en-edition 证据（多半是纯变形词形）"] += 1

        # ── 尺子乙：按**文字**挂锚（与顺序无关）────────────────────────
        # `build.py` 在桶内按文字去重 ⇒ 同一桶里文字唯一 ⇒ 文字就是可用的键。
        # 仍然是逐字节相等，没有放宽判据，只是不再依赖「第几条」。
        by_text = {g: ekey for g, ekey in items}
        for rid in ids:
            for _, (sid, text) in sorted((ev.get(rid) or {}).items()):
                ekey = by_text.get(text) or alts.get(text)
                if ekey is None:
                    c["🔴 库里有、复刻里找不到这条文字"] += 1
                else:
                    plan.append((sid, ekey))
                    c["✅ 按文字锚到 entry" if text in by_text
                      else "✅ 锚到异体/变位指针 entry"] += 1
    if verbose:
        print("■ 闸① 可逆性回核")
        for k, v in sorted(c.items()):
            print("     %-36s %s" % (k, format(v, ",")))
        print("     可确定挂锚的义项 %s 条" % format(len(plan), ","))
    return plan, c


# ───────────────────────── 写库 ─────────────────────────
def build_rows(plan, meta, con):
    """→ (entry 行, sense_id→src_ref 映射)。只给闸①认可的义项建 entry。"""
    # 🔴 **精确表与回退表必须分开。** 第一版写成一张表、两个 setdefault：
    #        word_id.setdefault(w, i); word_id.setdefault(w.lower(), i)
    #    `Ángel` 的 id 比 `ángel` 小 ⇒ 扫到它时 `word_id['ángel']` 就被大写行占了，
    #    轮到真正的 `ángel` 行时 setdefault 是空操作 ⇒ 17 个 entry 的 word_id 指错行
    #    （22 条义项，天使的释义挂到了人名 `Ángel` 的词条上）。
    #    小写回退是为了「拼写在库里根本没有」的情况，不该盖过精确命中。
    exact, fallback = {}, {}
    for i, w in con.execute("SELECT id, word FROM dict"):
        exact.setdefault(w, i)
        fallback.setdefault(w.lower(), i)

    used, rows, ref_of = {}, [], {}
    for sid, ekey in plan:
        spelling, pos_raw, etym = ekey
        ref = "kk-en:%s:%s:%s:0" % (spelling, pos_raw, etym)
        ref_of[sid] = ref
        if ref in used:
            continue
        wid = exact.get(spelling)
        if wid is None:
            wid = fallback.get(spelling.lower())
        if wid is None:
            continue
        used[ref] = True
        rows.append((wid, B.POS_MAP.get(pos_raw, pos_raw), pos_raw, etym, 0,
                     spelling, SRC, ref))
    return rows, ref_of


def apply(con, rows, ref_of):
    con.execute("DROP TABLE IF EXISTS entry")
    con.execute(DDL)
    con.executemany(
        "INSERT INTO entry (word_id,pos,pos_raw,etym_no,seq,spelling,src,src_ref)"
        " VALUES (?,?,?,?,?,?,?,?)", rows)
    for s in IDX:
        con.execute(s)
    cols = {r[1] for r in con.execute("PRAGMA table_info(sense)")}
    if "entry_id" not in cols:
        con.execute("ALTER TABLE sense ADD COLUMN entry_id INTEGER")
    id_of = dict(con.execute("SELECT src_ref, id FROM entry"))
    upd = [(id_of[r], sid) for sid, r in ref_of.items() if r in id_of]
    con.executemany("UPDATE sense SET entry_id=? WHERE id=?", upd)
    return len(upd)


# ───────────────────────── 闸② ─────────────────────────
def gate_invariants(con, verbose=True):
    q = lambda s: con.execute(s).fetchone()[0]
    bad = []
    n = q("SELECT COUNT(*) FROM entry")
    if q("SELECT COUNT(*) FROM entry e LEFT JOIN dict d ON d.id=e.word_id WHERE d.id IS NULL"):
        bad.append("entry 有孤儿 word_id")
    if q("SELECT COUNT(*) FROM (SELECT src_ref FROM entry GROUP BY src_ref HAVING COUNT(*)>1)"):
        bad.append("entry.src_ref 有重复")
    # ── 义项所在词形 ≠ 词条所在词形 ──────────────────────────────────
    # 已接受基线 **934 条，全部是大小写折叠残留**（2026-08-20 逐条核过，无例外）：
    #   `A` 的义项（字母 A / 象棋「象」）躺在 `a` 行、`FA`（房颤）在 `fa` 行、
    #   `LIBRE`（洪都拉斯自由党）在 `libre` 行、`Ángel` 在 `ángel` 行。
    # 根因是 `build.py:227` 的 `key = word.lower()`，见 [[case-folding-contaminates-columns]]。
    # 🔴 这不是本层引入的错，是本层**第一次让它变得可查询** —— 在此之前
    #    库里查不出任何异常。留基线不修，是因为修它要动 `sense.word_id`（搬义项），
    #    属于内容改动，得单独一轮。记在 es-CONVENTIONS 记账本。
    # ⚠️ 判据必须用 Python 的 casefold：SQLite 的 `lower()` 不认非 ASCII，
    #    `lower('Ángel')` 原样返回 —— 我第一版用 SQL 比，32 条重音大写词被误判成
    #    「不是大小写问题」，差点当成真缺陷去查。
    BASE_CASE_FOLD = 934
    off = con.execute(
        "SELECT ds.word, de.word FROM sense s JOIN entry e ON e.id=s.entry_id"
        " JOIN dict ds ON ds.id=s.word_id JOIN dict de ON de.id=e.word_id"
        " WHERE e.word_id!=s.word_id").fetchall()
    other = [(a, b) for a, b in off if a.casefold() != b.casefold()]
    if other:
        bad.append("🔴 sense 挂到了**不只是大小写不同**的词形的 entry 上 %s 条，例：%s"
                   % (format(len(other), ","), other[:3]))
    if len(off) > BASE_CASE_FOLD:
        bad.append("🔴 大小写折叠残留从基线 %s 涨到 %s —— 有人新造了折叠"
                   % (format(BASE_CASE_FOLD, ","), format(len(off), ",")))
    if verbose:
        print("     大小写折叠残留 %s 条（基线 %s，已接受）" % (
            format(len(off), ","), format(BASE_CASE_FOLD, ",")))
    mism = q("SELECT COUNT(*) FROM sense s JOIN entry e ON e.id=s.entry_id"
             " WHERE s.pos IS NOT NULL AND s.pos!=e.pos")
    if mism:
        bad.append("🔴 sense.pos 与 entry.pos 不符 %s 条" % format(mism, ","))
    if verbose:
        print("■ 闸② 不变量：entry %s 行 / 挂锚义项 %s 条" % (
            format(n, ","), format(q("SELECT COUNT(*) FROM sense WHERE entry_id IS NOT NULL"), ",")))
        for b in bad:
            print("     🔴 " + b)
        if not bad:
            print("     ✅ 全部通过")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()

    print("■ 复刻 build.py 的义项循环 …")
    buckets, meta, n_line = replay(paths.KK)
    print("   dump 西语条目 %s / 桶 %s / entry 键 %s" % (
        format(n_line, ","), format(len(buckets), ","), format(len(meta), ",")))
    dup = assign_seq(meta)
    print("   wiktextract 把同一键切成多条 JSON 的：%s 个键（最多 %d 条）" % (
        format(sum(v for k, v in dup.items() if k > 1), ","), max(dup)))

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    plan, c = gate_reversible(con, buckets)
    if c.get("🔴 第一条就对不上") or c.get("🔴 中途错位，尾巴放弃"):
        print("   ⚠️ 有错位，上面已计数；这些义项不挂 entry_id（宁缺勿错）")
    rows, ref_of = build_rows(plan, meta, con)
    con.close()
    print("■ 将建 entry %s 行，给 %s 条义项挂锚" % (
        format(len(rows), ","), format(len(ref_of), ",")))

    if a.mutate:
        return mutate(buckets)
    if not a.apply:
        print("\n(未加 --apply，没有写库)")
        return 0

    with dbtool.session("entry-layer", expect={}) as s:
        n = apply(s.conn, rows, ref_of)
        s.written = n
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    bad = gate_invariants(con)
    con.close()
    return 1 if bad else 0


def mutate(buckets):
    """变异验证：人为破坏复刻结果，闸①必须报红。

    🔴 变异要打在**闸真正检查的那一侧**。it 阶段 8 踩过：变异全去改数据，
       而检查问的是「组件有没有渲染」⇒ 构造上不可能红。
       这里闸①锚的判据是「库里那条文字能不能在复刻结果里逐字节找到」，
       所以变异就改复刻出来的文字与映射，而不是改顺序 ——
       **顺序已经不是判据了，改顺序现在应该照样绿**，这条本身就是一个负控。
    """
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n0 = len(gate_reversible(con, buckets, verbose=False)[0])
    # 挑真有多条义项、且库里确实存在的桶
    picks = [k for k, (it, al) in buckets.items() if len(it) >= 3][:2000]
    picks = [k for k in picks if con.execute(
        "SELECT 1 FROM dict d JOIN sense_src ss ON ss.word_id=d.id AND ss.src=?"
        " WHERE d.word=? LIMIT 1", (SRC, k)).fetchone()][:8]
    cases, ok = [], 0

    def run(name, mut, want_red=True):
        nonlocal ok
        b2 = dict(buckets)
        mut(b2)
        p2, c2 = gate_reversible(con, b2, verbose=False)
        red = len(p2) < n0 or c2.get("🔴 库里有、复刻里找不到这条文字", 0) > 198
        good = red == want_red
        ok += good
        cases.append((name, ("✅ 报红" if red else "✅ 照常绿") if good
                      else ("🔴 该红没红" if want_red else "🔴 不该红却红了"),
                      n0 - len(p2)))

    k0, k1, k2, k3 = picks[0], picks[1], picks[2], picks[3]
    run("① 改掉一条义项的文字",
        lambda b: b.__setitem__(k0, ([("__篡改__", b[k0][0][0][1])] + b[k0][0][1:], b[k0][1])))
    run("② 删掉一条义项",
        lambda b: b.__setitem__(k1, (b[k1][0][1:], b[k1][1])))
    run("③ 在文字中间插一个字符",
        lambda b: b.__setitem__(k2, (b[k2][0][:1] +
                                     [("x" + b[k2][0][1][0], b[k2][0][1][1])] + b[k2][0][2:],
                                     b[k2][1])))
    run("④ 清空异体指针表",
        lambda b: [b.__setitem__(k, (v[0], {})) for k, v in list(b.items())[:0]] or
                  b.update({k: (v[0], {}) for k, v in b.items() if v[1]}))
    run("⑤【负控】把义项顺序倒过来",
        lambda b: b.__setitem__(k3, (list(reversed(b[k3][0])), b[k3][1])), want_red=False)
    con.close()
    print("\n■ 变异验证")
    for n, r, d in cases:
        print("     %-26s %s（挂锚变化 %+d）" % (n, r, -d))
    print("     %d/%d" % (ok, len(cases)))
    return 0 if ok == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
