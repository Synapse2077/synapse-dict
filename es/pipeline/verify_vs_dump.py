#!/usr/bin/env python3
"""外锚闸：重扫 dump，按**词形 + 原值**逐条核对出版层。2026-08-10。

═══ 为什么要一类新的闸（docs/PITFALLS.md E3）═══
现有的闸绝大多数拿 **v1 源列**当真值（`sense_gloss` 比 `dict.definition`、
`example_gloss` 比 `example.zh`）。它们回答的是「**这次搬运忠不忠实**」，
不是「**这份数据对不对**」，而且**必然过期**：

  · 源列退休 ⇒ 两边都空，闸报通过。2026-08-10 `example_gloss` 就这么被删光
    50,289 条中文，闸全程绿灯。
  · 新来源出现 ⇒ 闸的 if/elif 没有 else，静默跳过。同一天 `sense_add:`
    那 1,963 条一条没核，闸仍报「一条不多、一条不少」。
  · 结构改动 ⇒ 键（id / 下标 / 行号）失效。

本脚本是另一类：**锚在仓库外的不可变源上**。它不认识我们的表结构，
只认「dump 里词形 W 有哪些原值」和「库里词形 W 有哪些原值」，两个集合对不上就报。
我们怎么改结构它都不会失效 —— 同 `build_frequency_layer`（回 wordfreq 重算）
与 `gen_tts --verify`（重算 sha1）。

═══ 覆盖哪几层 ═══
    pronunciation   382,674   源：kaikki 英文版 `sounds[].ipa`
    sense_relation  121,585   源：kaikki 英文版 `senses[].{synonyms,antonyms,…}`
`example` 跨 7 个语言版（en/es/fr/de/it/pt/zh，含 708 MB 的 fr），单独一轮做。
`collocation` 源自 `dict.collocation`，本身就是 v1 列，先不动。

═══ 🔴 允许的归一，以及为什么只允许这些 ═══
外锚闸的价值在于**不重复被测代码的判断**。所以只做两种双方约定好的形变：
  ① **定界符**：dump 写 `/ˈɡɾatis/` 或 `[ˈɡɾa.t̪is]`，库里按项目约定**存裸串**
     （见 ipa-bare-storage-convention）。剥掉首尾 `/ /` `[ ]` 是格式约定不是判断。
  ② **空白归一**：`\\s+` → 单空格。
⚠️ **不做 ipa_norm 那一套字符替换**。那是我们自己的转换器，拿它来核对
   等于「量自己的工具不量数据」（PITFALLS C3）。归一后仍对不上的，如实报出来。

用法（在仓库根）：
    python3 -m es.pipeline.verify_vs_dump                 # 全部层
    python3 -m es.pipeline.verify_vs_dump --layer ipa
    python3 -m es.pipeline.verify_vs_dump --layer rel
    python3 -m es.pipeline.verify_vs_dump --mutate        # 变异验证：闸抓不抓得住
"""
import argparse
import collections
import json
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))

import paths    # noqa: E402

DELIM = re.compile(r"^[/\[\(]+|[/\]\)]+$")
WS = re.compile(r"\s+")
# kaikki 的关系字段名 → 我们的 kind。
# 🔴 这张表必须**按库里实际存在的 kind 反推**，不能凭印象列。
#    `SELECT kind, COUNT(*) FROM sense_relation GROUP BY 1` 给出九种，
#    一一对上才算覆盖。第一版漏了 `derived`（29,893 条，字段名不以 nyms 结尾，
#    我那句 `k.endswith(("nyms","_terms"))` 根本够不着），于是闸报出
#    「库里凭空多出 29,965 条」的假警报 —— 同一道闸上第三次「量的是我的工具」。
# ⚠️ `descendants` / `abbreviations` / `form_of` / `alt_of` 在 dump 里也是
#    {word: …} 形状，但**我们没收进 sense_relation**（前两者不是词内关系，
#    后两者走变形层）。它们会落进 `unknown` 里被如实报出来，不静默丢。
REL_KEYS = {"synonyms": "synonym", "antonyms": "antonym",
            "hypernyms": "hypernym", "hyponyms": "hyponym",
            "related": "related", "coordinate_terms": "coordinate",
            "derived": "derived", "meronyms": "meronym", "holonyms": "holonym"}
# 库里九种 kind 与上表一一对应；对不上就是闸漏了，启动时自证。
DB_KINDS = set(REL_KEYS.values())


def norm(s: str) -> str:
    """只做定界符 + 空白两种归一。见 docstring：不碰 ipa_norm 那一套。"""
    return WS.sub(" ", DELIM.sub("", (s or "").strip())).strip()


# dump 里少数条目把**两个音标塞进同一个 `ipa` 字段**：
#     "/ˈɡɾaθjas/ [ˈɡɾa.θjas]"    "/tɾabaxaˈdoɾa/ [t̪ɾa.β̞a.xaˈð̞o.ɾa]"
# 建表脚本会拆成两条（音位式 + 窄式），本闸只剥首尾定界符 ⇒ 剥出来是
# `ˈɡɾaθjas/ [ˈɡɾa.θjas` 这种半截，于是误报 10 条「缺失」。
# 这是**源头的书写形态**，不是我们的转换判断 ⇒ 按同一约定拆开，属于允许的归一。
SPLIT_IPA = re.compile(r"(?<=[/\]])\s+(?=[/\[])")


def ipa_values(raw: str):
    """一个 `sounds[].ipa` 字段 → 它实际承载的若干个裸音标。"""
    for part in SPLIT_IPA.split((raw or "").strip()):
        v = norm(part)
        if v:
            yield v


def scan_dump():
    """一次扫过 kaikki 西语切片，同时取音标与关系。→ (ipa, rel, unknown_rel_keys)"""
    ipa = collections.defaultdict(set)          # word → {裸音标}
    rel = collections.defaultdict(set)          # word → {(kind, target)}
    unknown = collections.Counter()
    n = 0
    with open(paths.KK, encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            if e.get("lang_code") != "es":
                continue
            n += 1
            w = e.get("word")
            for s in e.get("sounds") or []:
                if s.get("ipa"):
                    ipa[w].update(ipa_values(s["ipa"]))
            # 🔴 关系有**两级**：条目级 15,156 条 + 义项级 78,355 条。
            #    第一版只扫了义项级，于是报出「库里凭空多出 44,461 条」的假警报 ——
            #    又一次「量的是我的工具，不是数据」（PITFALLS C3）。
            for holder in [e] + list(e.get("senses") or []):
                for k, v in holder.items():
                    # 判据不是「字段名长什么样」（`derived` 就不带 nyms），
                    # 是「值是不是一串 {word: …}」—— 那才是关系的形状。
                    if not (isinstance(v, list) and v
                            and isinstance(v[0], dict) and "word" in v[0]):
                        continue
                    if k in ("forms", "form_of", "alt_of", "sounds", "examples",
                             "descendants", "abbreviations"):
                        continue                      # 不是词内关系，走别的层
                    if k not in REL_KEYS:
                        unknown[k] += len(v)
                        continue
                    for it in v:
                        t = (it or {}).get("word") if isinstance(it, dict) else None
                        t = (t or "").strip()
                        # 自指（`mordaga --synonym--> mordaga`）建表脚本明确丢弃
                        # （`build_relation_layer.py` 的 `if not t or t == w`），
                        # 丢得对 —— 一个词是自己的同义词没有信息。闸也照这条约定，
                        # 否则每次都稳定误报 290 条，久了这道闸就没人看了。
                        if t and t != w:
                            rel[w].add((REL_KEYS[k], t))
    print(f"  扫 {paths.KK.name}：西语条目 {n:,}")
    return ipa, rel, unknown


def compare(name, dump, db, indict, show=6):
    """→ (真缺, 多)。两边都按 (词形, 值) 的集合比。

    ⚠️ 「词形根本不在 `dict` 里」要**单独报，不计入本层的缺**：
    那是**收词**缺口（`Pinyin` / `CECOT` / `Citano` 这类词我们压根没收），
    音标层和关系层再怎么跑也变不出没有的词头来。混在一起报，
    这道闸就永远非零，久了就没人看了 —— 而它恰恰是那种「必须一直保持 0」的闸。
    """
    d = {(w, v) for w, vs in dump.items() for v in vs}
    b = {(w, v) for w, vs in db.items() for v in vs}
    miss, extra = d - b, b - d
    nodict = {(w, v) for w, v in miss if w not in indict}
    real = miss - nodict
    print(f"\n  ── {name}")
    print(f"     dump {len(d):,} 条 / 库 {len(b):,} 条")
    print(f"     {'🔴' if real else '  '} dump 有、库里没有（真缺）：{len(real):,}")
    for w, v in sorted(real)[:show]:
        print(f"        {w:<22}{str(v)[:52]}")
    print(f"     {'ℹ️' if nodict else '  '} 词形不在 dict 里（收词缺口，不算本层的）：{len(nodict):,}"
          + (f"   例：{sorted({w for w, _ in nodict})[:5]}" if nodict else ""))
    print(f"     {'⚠️' if extra else '  '} 库里有、dump 没有（凭空多出）：{len(extra):,}")
    for w, v in sorted(extra)[:show]:
        print(f"        {w:<22}{str(v)[:52]}")
    return len(real), len(extra)


def scan_examples():
    """扫**全部 7 个语言版**取例句。→ {word: {text}}，以及每个版的条数。

    🔴 例句是唯一一个跨 7 个 dump 的层（en/es/fr/de/it/pt/zh，含 708 MB 的 fr）。
       `ingest_examples.py` 按 `(word, text)` 去重、按源优先级先到先得，
       所以**不能按 src 分别比**，只能比并集。
    ⚠️ 文件清单直接引用 `ingest_examples.SOURCES` —— 少扫一个版就会把那一版
       全部误报成「凭空多出」。清单要跟着它走，抽取逻辑才是本闸自己的。
    """
    from pipeline.ingest_examples import SOURCES
    import gzip
    out = collections.defaultdict(set)
    per = collections.Counter()
    for src, path, kind in SOURCES:
        if not Path(path).exists():
            print(f"  ⚠️ 缺文件，跳过（会导致该版全部误报）：{path}")
            continue
        op = gzip.open if kind == "gz" else open
        n = 0
        with op(path, "rt", encoding="utf-8") as f:
            for line in f:
                e = json.loads(line)
                if e.get("lang_code") != "es":
                    continue
                w = e.get("word")
                for s in e.get("senses") or []:
                    for x in s.get("examples") or []:
                        t = (x.get("text") or "").strip()
                        if t:
                            out[w].add(t)
                            n += 1
        per[src] = n
        print(f"    {src:<12}{n:>9,}   {Path(path).name}")
    return out, per


def db_examples(con):
    out = collections.defaultdict(set)
    for w, t in con.execute("SELECT word, text FROM example"):
        out[w].add((t or "").strip())
    return out


def db_ipa(con):
    out = collections.defaultdict(set)
    for w, v in con.execute(
            "SELECT d.word, p.ipa FROM pronunciation p JOIN dict d ON d.id = p.word_id"):
        v = norm(v)
        if v:
            out[w].add(v)
    return out


def db_rel(con):
    out = collections.defaultdict(set)
    for w, k, t in con.execute(
            "SELECT d.word, r.kind, r.target FROM sense_relation r "
            "JOIN dict d ON d.id = r.word_id"):
        if t:
            out[w].add((k, t.strip()))
    return out


def run(layers, con, quiet=False):
    indict = {w for (w,) in con.execute("SELECT word FROM dict")}
    bad = 0
    if "ex" in layers:
        print("\n  扫 7 个语言版取例句：")
        ex, _per = scan_examples()
        m, e = compare("example ← 7 版 senses[].examples[].text", ex,
                       db_examples(con), indict)
        bad += m
        if not (layers - {"ex"}):
            return bad
    ipa, rel, unknown = scan_dump()
    if unknown:
        print(f"\n  ⚠️ 本闸不认识的关系字段（如实报，不静默丢）：{dict(unknown)}")
    # 🔴 闸自证：库里出现的每一种 kind 都必须在 REL_KEYS 的值域里，
    #    否则说明 dump 侧根本没扫那一类，缺多少都看不见（`derived` 就这么漏了 20,460 条）。
    if "rel" in layers:
        got = {k for (k,) in con.execute("SELECT DISTINCT kind FROM sense_relation")}
        if got - DB_KINDS:
            print(f"\n  🔴 闸失效：库里有本闸不扫的 kind {sorted(got - DB_KINDS)}")
            bad += 1
    if "ipa" in layers:
        m, e = compare("pronunciation ← kaikki sounds[].ipa", ipa, db_ipa(con), indict)
        bad += m
    if "rel" in layers:
        m, e = compare("sense_relation ← kaikki 各级关系字段", rel, db_rel(con), indict)
        bad += m
    return bad


def mutate(layers):
    """⭐ 变异验证：在副本上删/改几条，看闸抓不抓得住。"""
    import shutil
    import tempfile
    import io
    import contextlib
    print("\n" + "=" * 62)
    print("⭐ 变异验证：副本上造 4 种错")
    print("=" * 62)
    muts = [
        ("① 删掉一条音标", "DELETE FROM pronunciation WHERE id=(SELECT MIN(id) FROM pronunciation)"),
        ("② 改掉一条音标（与 dump 对不上）",
         "UPDATE pronunciation SET ipa='xxx' WHERE id=(SELECT MIN(id) FROM pronunciation)"),
        ("③ 删掉一条关系", "DELETE FROM sense_relation WHERE id=(SELECT MIN(id) FROM sense_relation)"),
        ("④ 改掉一条关系的 target",
         "UPDATE sense_relation SET target='xxx' WHERE id=(SELECT MIN(id) FROM sense_relation)"),
    ]
    caught = 0
    for name, sql in muts:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "m.sqlite"
            shutil.copy2(paths.DB, p)
            c = sqlite3.connect(p)
            c.execute(sql)
            c.commit()
            c.close()
            c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                bad = run(layers, c)
            c.close()
            caught += bad > 0
            print(f"  {'✅ 抓住' if bad else '🔴 漏过'}  {name}")
    print(f"\n  {caught}/4 被抓住" + ("" if caught == 4 else "  🔴 有闸是摆设"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer", choices=["ipa", "rel", "ex", "all"], default="all")
    ap.add_argument("--mutate", action="store_true")
    args = ap.parse_args()
    layers = {"ipa", "rel", "ex"} if args.layer == "all" else {args.layer}

    print("═══ 外锚闸：重扫 dump 逐条核对（全量，非抽样）═══")
    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    bad = run(layers, con)
    con.close()
    print(f"\n{'✅ 全部对得上' if bad == 0 else f'🔴 dump 有而库里没有 {bad:,} 条'}")
    if args.mutate:
        mutate(layers)


if __name__ == "__main__":
    main()
