#!/usr/bin/env python3
"""补收两份 dump 里有、库里没落地的义项。2026-08-10。

═══ 怎么发现的 ═══
2026-08-06 记的「西语版 100% 收完、英文版 0 条丢失」是**错的**。那个数量的是
`dict.definition → sense_src` 的**库内搬运**，只能证明搬运没丢，证明不了
2026-07 建库时从 dump 漏没漏。2026-08-10 直接扫两份 dump 逐条 diff，真缺 2,066 条。

⭐ 两次差点报出假缺口，都是**尺子**的问题，本脚本把两条尺子都钉死在项目自己的判据上：
  ① **落点是 `sense_gloss` 不是 `sense_src`**。`Argentina` 的英文释义在 `sense_gloss`
     里躺着，只是没建 `sense_src` 证据行 —— 查错表报出 4,062 条假缺口。
     `sense_src` 是证据层，不是落点。
  ② **"什么算真义项"必须用项目自己的判据**。我自编的过滤给西语版报 14.36%，
     因为拦不住 `Participio de capturar.` 这类**用散文写的**变形指针（kaikki 没打
     `form_of` 标）。换成 `ingest_edition.is_form_sense` 之后是 0.32%。
     英文版同理：2,843 条里 1,330 条是 `build.py` 的 `PROSE_INFL` 有意路由进变形层的。

🔴 用项目自己的判据量项目自己的产物有**循环论证**风险（判据误判成变形，两边都少，
   我就看不见）。所以补了一道确定性反查，见 `--audit`：28,409 条被西语版判据判成变形的，
   开头不符合任何变形套话的只有 77 条，逐条看全是 `hacerlo`/`dame` 这类带附着代词的
   动词形，本就该在变形层 ⇒ 判据没误伤真义项。

═══ 🔴 为什么不直接往 `sense` 表插 ═══
`build_sense_layer.py` 是 **DROP 重建**四张表的。直接插进去，下次谁跑一遍建表脚本
就全没了 —— 正是 [[replay-scripts-undo-fixes]] 那个坑（`UNIQUE` 保证不重复，
**不保证不倒退**）。补的东西必须落在**建表脚本的输入端**。

═══ 🔴 也不往 `dict.definition` 追加行 ═══
那是 v2 好不容易摆脱的「按行号对齐的字符串数组」契约。追加一行看着安全（不动已有下标），
但 `definition` 比 `definition_es` 短的词，新行会和**别人的**西语释义配成一对 ——
那正是用户说的「义项和释义错配，那才是真灾难」。

⇒ 建一张行式表 `sense_add`，`build_sense_layer.py` 读它当**第三个证据源**（C 组）。
   重建幂等、可逆（`DELETE FROM sense_add` + 重建 = 撤销）、不碰任何行号。
   以后再做 dump 差分补收，还是往这张表加行。

═══ 收什么（2,066 条 / 1,403 个词）═══
    英文版 kaikki      1,513 条    西语版 eswiktionary   553 条
      872 个词形**根本不在 `dict` 里** → 本脚本建词头行（`is_lemma=1`，音标取 dump）
        636 专名 Esmeraldas/Carintia/Bosnia   41 缩写 CIA/AM/SMS
         40 多词 estación de policía          155 小写普通词 babel/inti
      531 个词是**已有词条缺其中几条** → 只加 `sense_add` 行
        teléfono 缺「手机」 corazón 缺「洋蓟心」 derecho 缺「布料正面」 padre 缺「神父」

`zh` 本脚本不填，留给 `translate_sense_gap.py`（同 `sense_es` 的分工）。

═══ 三道闸（docs/SCHEMA.md §5.0）═══
① 可逆性回核：重新扫两份 dump 重算一遍缺口，与 `sense_add` 里的**逐条比对**（全量）
② 不变量断言：见 `gate2`
③ 抽样：确定性搬运，不适用
⭐ `--mutate` 造 6 种错，闸全抓住才算数

用法（在仓库根）：
    python3 -m es.pipeline.ingest_sense_gap             # 算缺口 + 计划，不写库
    python3 -m es.pipeline.ingest_sense_gap --audit     # 只跑「判据有没有误伤真义项」的反查
    python3 -m es.pipeline.ingest_sense_gap --apply
    python3 -m es.pipeline.ingest_sense_gap --verify    # 闸①②
    python3 -m es.pipeline.ingest_sense_gap --mutate    # 变异验证
"""
import argparse
import collections
import gzip
import json
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))

import dbtool            # noqa: E402
import paths             # noqa: E402
from pipeline.build import PROSE_INFL, POS_MAP, meta_of, unaccent      # noqa: E402
from pipeline.ingest_edition import (is_form_entry, is_form_sense,     # noqa: E402
                                     pick_ipa)
# 残渣清洗复用 8-05 那一份 —— 库里的西语释义就是被它洗过的，另写一份必然对不上
from fixes.clean_sense_es_residue import clean as clean_residue        # noqa: E402

DDL = """
CREATE TABLE IF NOT EXISTS sense_add (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  word      TEXT NOT NULL,      -- **精确拼写**，不折叠大小写（折叠正是当初漏收的原因）
  dict_id   INTEGER,            -- → dict.id，落库时回填
  lang      TEXT NOT NULL,      -- 这句原文是什么语言：en / es
  gloss     TEXT NOT NULL,      -- 原文
  pos       TEXT,               -- 归一后的词性
  pos_title TEXT,               -- 西语版 pos_title 原文；英文版为空
  tags      TEXT,               -- JSON array
  meta      TEXT,               -- JSON object，英文版走 build.meta_of
  zh        TEXT,               -- 中文；本脚本不填，留给 translate_sense_gap
  zh_src    TEXT,
  src       TEXT NOT NULL,      -- en-edition / es-edition
  src_ref   TEXT NOT NULL,      -- 回源坐标
  UNIQUE(src_ref)
);
CREATE INDEX IF NOT EXISTS idx_sense_add_word ON sense_add(word);
CREATE INDEX IF NOT EXISTS idx_sense_add_dict ON sense_add(dict_id);
"""

# 变形套话开头。只用于 `--audit` 的反查，不参与收录判断。
FORMULA = re.compile(
    r"^\s*(gerundio|participio|infinitivo|imperativo|forma|primera|segunda|tercera|"
    r"plural|singular|femenino|masculino|superlativo|diminutivo|aumentativo|grafía)", re.I)
NEW_DICT_COLS = ("word", "word_norm", "phonetic", "phonetic_raw", "phonetic_src",
                 "pos", "is_lemma", "meta")


# ═══════════════════════ 扫 dump：源头有哪些真义项 ═══════════════════════

def scan_en():
    """英文版 kaikki 的真义项。判据 = kaikki 结构化标记 + `build.py` 的 `PROSE_INFL`
    （后者是我们自己有意把散文变形指针路由进变形层的那条，必须一起用，
    否则会把 1,330 条「有意不收」的报成「漏收」）。"""
    out = collections.defaultdict(dict)      # word → {gloss: (pos, sense)}
    with open(paths.KK, encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            if e.get("lang_code") != "es":
                continue
            pos = e.get("pos") or "unknown"
            for s in e.get("senses") or []:
                gl = [g for g in (s.get("glosses") or []) if g and g.strip()]
                tags = set(s.get("tags") or [])
                if not gl or s.get("form_of") or s.get("alt_of") \
                        or "form-of" in tags or "alt-of" in tags:
                    continue
                g = re.sub(r"\s+", " ", gl[-1]).strip()
                if PROSE_INFL.search(g):
                    continue
                # 🔴 `glosses` 是**层级路径**不是单串：`teléfono` 的两条义项都长
                #    `["telephone (a telecommunication device…)", "mobile phone"]` 这样，
                #    `build.py` 存 `[0]`（上位义）⇒ 两条压成同一串，「手机」「转盘电话」
                #    的区别整个丢掉。622 条真义项是这个形态。
                #    ⇒ 收**最具体的那一段**（父串库里本来就有，是它自己的一条义项），
                #      父串存进 meta，让出版层能把它挂在父义项下面而不是平铺
                #      （`Como` 的 8 个美国小镇平铺出来就是噪音）。
                parent = re.sub(r"\s+", " ", gl[0]).strip() if len(gl) > 1 else None
                if parent == g:
                    parent = None
                out[e["word"]].setdefault(g, (pos, s, parent))
    return out


def scan_es():
    """西语版 eswiktionary 的真义项。判据 = `ingest_edition.is_form_sense`（项目自己的）。

    🔴 **必须先过 `clean_sense_es_residue.clean`，而且要在压空白之前。**
    西语版的 gloss 是「正文 \\n :*Sinónimos: …」这种形态，残渣挂在换行之后。
    我第一版先做了 `\\s+→空格`，把清洗函数赖以工作的换行毁掉，于是
    `atender` 的「Hacer caso… favorable.」在库里明明有，却因为 dump 原文尾巴上
    多了 `:*Sinónimo: acoger` 而被判成「缺失」—— **79 条假缺口**。
    判断「库里有没有」时原文与清洗后两种形态都认（见 `landed` 的用法）。

    正文清洗后为空 = 整条就是 `:*Ámbito: …` 这类元数据行，本来就不是释义 ⇒ 不收。
    """
    out = collections.defaultdict(dict)
    with gzip.open(paths.EDITION, "rt", encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            if e.get("lang_code") != "es":
                continue
            fe = is_form_entry(e)
            for s in e.get("senses") or []:
                for raw in (s.get("glosses") or []):
                    if not raw or not raw.strip() or is_form_sense(s, fe):
                        continue
                    body, _cut = clean_residue(raw)
                    if not body:
                        continue                       # 整条都是残渣，不是释义
                    out[e["word"]].setdefault(body, (e, s))
    return out


def landed(con):
    """落点：`sense_gloss` 里每个词形已有的 en / es 原文。

    🔴 是 `sense_gloss` 不是 `sense_src` —— 见 docstring 陷阱①。
    还要并上 `sense_add` 自己（续跑时别把上一轮补的又算成缺）。"""
    out = {"en": collections.defaultdict(set), "es": collections.defaultdict(set)}
    for w, lang, t in con.execute(
            "SELECT d.word, g.lang, g.text FROM sense_gloss g "
            "JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id "
            "WHERE g.lang IN ('en','es')"):
        t = (t or "").strip()
        out[lang][w].add(t)
        # 库里存的既有洗过的也有没洗的（`clean_sense_es_residue` 只跑过 `sense_es`），
        # 两种形态都登记，否则同一条义项会因为尾巴上一段 `:*Sinónimos:` 被判成缺失
        if lang == "es" and ("\n" in t or ":*" in t or "*" in t):
            body, _ = clean_residue(t)
            if body:
                out[lang][w].add(body)
    if con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                   "AND name='sense_add'").fetchone()[0]:
        for w, lang, g in con.execute("SELECT word, lang, gloss FROM sense_add"):
            out[lang][w].add((g or "").strip())
    return out


def compute(con, verbose=True):
    """→ (gap, en_src, es_src)。gap = [(word, lang, gloss, payload), …]，顺序确定。"""
    if verbose:
        print(f"扫英文版 {Path(paths.KK).name} …")
    en = scan_en()
    if verbose:
        print(f"  {len(en):,} 个词形 / {sum(len(v) for v in en.values()):,} 条真义项")
        print(f"扫西语版 {Path(paths.EDITION).name} …")
    es = scan_es()
    if verbose:
        print(f"  {len(es):,} 个词形 / {sum(len(v) for v in es.values()):,} 条真义项")

    have = landed(con)
    gap = []
    for lang, src in (("en", en), ("es", es)):
        for w in sorted(src):
            for g in sorted(src[w]):
                if g not in have[lang].get(w, ()):
                    gap.append((w, lang, g, src[w][g]))
    return gap, en, es


# ═══════════════════════ 反查：判据有没有误伤真义项 ═══════════════════════

def audit():
    """🔴 用项目自己的判据量项目自己的产物是循环论证。这里做确定性反查：
    被判成变形、却**不以任何变形套话开头**的有多少条，逐条看。"""
    print("═══ 反查：西语版判据有没有把真义项误判成变形 ═══")
    risky = []
    with gzip.open(paths.EDITION, "rt", encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            if e.get("lang_code") != "es":
                continue
            fe = is_form_entry(e)
            for s in e.get("senses") or []:
                gl = [g for g in (s.get("glosses") or []) if g and g.strip()]
                if not gl:
                    continue
                struct = bool(s.get("form_of") or s.get("alt_of")
                              or "form-of" in set(s.get("tags") or []))
                if is_form_sense(s, fe) and not struct:
                    risky.append((e["word"], e.get("pos_title"), gl[-1].strip()))
    odd = [r for r in risky if not FORMULA.match(r[2])]
    print(f"  只因『pos_title 是 Forma… + 散文像变形』被判成变形的：{len(risky):,} 条")
    print(f"  其中**开头不是任何变形套话**的：{len(odd):,} 条（{len(odd)/max(len(risky),1)*100:.2f}%）")
    # 🔴 项目教训：这一栏必须逐条看得见，不能只报个数（novia 就躺在没打印的 6 行里）
    for w, pt, g in odd:
        print(f"     {w:<24}[{pt}] {g[:70]}")
    print("\n  ⇒ 若上面全是 hacerlo/dame 这类带附着代词的动词形，判据没误伤真义项。")


# ═══════════════════════════════ 计划 ═══════════════════════════════

def plan(con, gap, en, es):
    """→ (new_rows, add_rows, stat)。new_rows 建词头，add_rows 进 sense_add。"""
    in_dict = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    stat = collections.Counter()
    by_word = collections.defaultdict(list)
    for w, lang, g, payload in gap:
        by_word[w].append((lang, g, payload))

    new_rows, add_rows = [], []
    for w in sorted(by_word):
        if w not in in_dict:
            # 建词头。音标/词性只从**西语版**取（英文版这批多是专名，pick_ipa 是
            # ingest_edition 那一份，与库内值 95.6% 逐字一致，别另写）。
            ipa = ipa_raw = None
            poss, metas = [], []
            for lang, g, payload in by_word[w]:
                if lang == "es":
                    e, s = payload
                    if ipa is None:
                        ipa, ipa_raw = pick_ipa(e)
                    p = POS_MAP.get(e.get("pos") or "unknown", e.get("pos"))
                else:
                    pos_raw, s, _parent = payload
                    p = POS_MAP.get(pos_raw, pos_raw)
                if p and p not in poss:
                    poss.append(p)
            new_rows.append((w, unaccent(w), ipa, ipa_raw,
                             "es-edition" if ipa else None,
                             "/".join(poss) if poss else None, 1, None))
            stat["建新词头"] += 1
            stat["  有音标" if ipa else "  无音标"] += 1
        else:
            stat["挂到已有词条"] += 1

        for i, (lang, g, payload) in enumerate(by_word[w]):
            if lang == "es":
                e, s = payload
                pt = e.get("pos_title")
                pos = POS_MAP.get(e.get("pos") or "unknown", e.get("pos"))
                tags = json.dumps(s.get("tags") or [], ensure_ascii=False)
                m = None
            else:
                pos_raw, s, parent = payload
                pt = None
                pos = POS_MAP.get(pos_raw, pos_raw)
                tags = json.dumps(s.get("tags") or [], ensure_ascii=False)
                mo = meta_of(s, pos_raw) or {}
                if parent:
                    mo["parent"] = parent      # 上位义原文，出版层据此挂在父义项下
                m = json.dumps(mo, ensure_ascii=False)
            add_rows.append((w, None, lang, g, pos, pt, tags, m,
                             f"{'kk' if lang == 'en' else 'eswikt'}:{w}#{i}:{lang}",
                             "en-edition" if lang == "en" else "es-edition"))
            stat[f"义项·{lang}"] += 1
    return new_rows, add_rows, stat


# ═══════════════════════════════ 闸 ═══════════════════════════════

def gate1(con, quiet=False) -> bool:
    """闸① 可逆性回核：重新扫两份 dump 重算缺口，与 `sense_add` 逐条比对（全量）。

    ⚠️ 回核时 `landed()` 会把 `sense_add` 自己算进"已有"，所以重算出来的缺口
    应当是**空的**；同时 `sense_add` 里的每一条都必须能在 dump 里找到原文。"""
    def say(*a):
        if not quiet:
            print(*a)
    say("\n═══ 闸① 可逆性回核（全量，非抽样）═══")
    gap, en, es = compute(con, verbose=not quiet)
    say(f"  落库后重算，仍缺：{len(gap)}")
    for w, lang, g, _ in gap[:5]:
        say(f"     🔴 {w} [{lang}] {g[:60]}")
    ok = not gap

    rows = con.execute("SELECT word, lang, gloss FROM sense_add").fetchall()
    src = {"en": en, "es": es}
    orphan = [(w, lang, g) for w, lang, g in rows if g not in src[lang].get(w, ())]
    say(f"  `sense_add` 里 dump 中找不到原文的：{len(orphan)}")
    for w, lang, g in orphan[:5]:
        say(f"     🔴 {w} [{lang}] {g[:60]}")
    ok &= not orphan
    say(f"  `sense_add` 共 {len(rows):,} 条")
    say("  ✅ 闸① 通过" if ok else "  🔴 闸① 没过")
    return ok


def gate2(con, quiet=False) -> bool:
    """闸② 不变量断言。"""
    def say(*a):
        if not quiet:
            print(*a)
    say("\n═══ 闸② 不变量断言 ═══")
    checks = [
        ("dict_id 没回填", "SELECT COUNT(*) FROM sense_add WHERE dict_id IS NULL"),
        ("dict_id 指向不存在的行",
         "SELECT COUNT(*) FROM sense_add a LEFT JOIN dict d ON d.id=a.dict_id "
         "WHERE d.id IS NULL"),
        ("🔴 dict_id 指向的词形与 word 不同（错配）",
         "SELECT COUNT(*) FROM sense_add a JOIN dict d ON d.id=a.dict_id "
         "WHERE d.word <> a.word"),
        ("gloss 为空", "SELECT COUNT(*) FROM sense_add WHERE TRIM(COALESCE(gloss,''))=''"),
        ("lang 不是 en/es", "SELECT COUNT(*) FROM sense_add WHERE lang NOT IN ('en','es')"),
        ("🔴 与 sense_gloss 里已有的原文重复（会显示两遍）",
         "SELECT COUNT(*) FROM sense_add a JOIN sense s ON s.word_id=a.dict_id "
         "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang=a.lang AND g.text=a.gloss"),
        ("同一词形同一 lang 下 gloss 重复",
         "SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) n FROM sense_add "
         "GROUP BY word, lang, gloss HAVING n>1)"),
        ("🔴 dict 里出现了同词形两行（word 本应全库唯一）",
         "SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) n FROM dict "
         "GROUP BY word HAVING n>1)"),
    ]
    ok = True
    for name, sql in checks:
        n = con.execute(sql).fetchone()[0]
        say(f"  {'🔴' if n else '  '} {name:<46}{n:>7,}")
        ok &= n == 0
    return ok


def mutate():
    """⭐ 变异验证：一条永远通过的检查等于没检查。在**副本**上造 6 种错。"""
    import shutil
    import tempfile
    import io
    import contextlib
    print("\n" + "=" * 64)
    print("⭐ 变异验证：副本上造 6 种错，逐个看闸的反应")
    print("=" * 64)
    muts = [
        ("① 删掉一条已补的义项（漏收又回来了）",
         "DELETE FROM sense_add WHERE id=(SELECT MIN(id) FROM sense_add)"),
        ("② 改掉一条的原文（与 dump 对不上）",
         "UPDATE sense_add SET gloss='xxx 篡改 xxx' WHERE id=(SELECT MIN(id) FROM sense_add)"),
        ("🔴③ dict_id 指到别的词上（义项与词错配）",
         "UPDATE sense_add SET dict_id=(SELECT id FROM dict WHERE word='casa') "
         "WHERE id=(SELECT MIN(id) FROM sense_add WHERE word<>'casa')"),
        ("④ dict_id 清空（没回填）",
         "UPDATE sense_add SET dict_id=NULL WHERE id=(SELECT MIN(id) FROM sense_add)"),
        ("⑤ 同一词形同一 lang 下塞进重复 gloss",
         "INSERT INTO sense_add (word,dict_id,lang,gloss,src,src_ref) "
         "SELECT word,dict_id,lang,gloss,src,src_ref||'#dup' FROM sense_add "
         "WHERE id=(SELECT MIN(id) FROM sense_add)"),
        ("🔴⑥ 补的原文其实 sense_gloss 里已经有了（会显示两遍）",
         "INSERT INTO sense_add (word,dict_id,lang,gloss,src,src_ref) "
         "SELECT d.word, d.id, g.lang, g.text, 'x', 'x:dup' FROM sense_gloss g "
         "JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id "
         "WHERE g.lang='en' LIMIT 1"),
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
                good = gate1(c, quiet=True) and gate2(c, quiet=True)
            c.close()
            caught += not good
            print(f"  {'✅ 抓住' if not good else '🔴 漏过'}  {name}")
    print(f"\n  {caught}/6 被抓住" + ("" if caught == 6 else "  🔴 有闸是摆设，必须修"))


# ═══════════════════════════════ main ═══════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--audit", action="store_true", help="只跑「判据有没有误伤真义项」反查")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    args = ap.parse_args()

    if args.audit:
        audit()
        return

    if args.verify or args.mutate:
        con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
        ok = gate1(con) and gate2(con)
        con.close()
        print(f"\n{'✅ 两道闸都通过' if ok else '🔴 有闸没过'}")
        if args.mutate:
            mutate()
        return

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    gap, en, es = compute(con)
    new_rows, add_rows, stat = plan(con, gap, en, es)
    con.close()

    print(f"\n缺口 {len(gap):,} 条 / {len({w for w, *_ in gap}):,} 个词形")
    for k, v in stat.most_common():
        print(f"  {k:<20}{v:>8,}")
    kind = collections.Counter(
        "多词" if " " in w else "全大写(缩写)" if w.isupper() and len(w) > 1
        else "首字母大写(专名)" if w[:1].isupper() else "小写普通词"
        for w, *_ in new_rows)
    print("\n  新建词头的构成：")
    for k, v in kind.most_common():
        print(f"    {k:<16}{v:>7,}")
    dbtool.sample_check(
        [(w, lang, (g or "")[:52]) for w, _, lang, g, *_ in add_rows[:12]],
        12, ("词", "源", "补收的原文"))

    if not args.apply:
        print("\n未加 --apply，不写库。")
        return

    ph = ",".join("?" * len(NEW_DICT_COLS))
    with dbtool.session("ingest-sense-gap", expect={
            "__rows__": +len(new_rows),
            "pos": +sum(1 for r in new_rows if r[5]),
            "phonetic": +sum(1 for r in new_rows if r[2]),
            "phonetic_raw": +sum(1 for r in new_rows if r[3]),
            "phonetic_src": +sum(1 for r in new_rows if r[4]),
    }) as s:
        for ddl in DDL.strip().split(";"):
            if ddl.strip():
                s.execute(ddl)
        s.executemany(f"INSERT INTO dict ({','.join(NEW_DICT_COLS)}) VALUES ({ph})",
                      new_rows)
        s.executemany(
            "INSERT INTO sense_add (word, dict_id, lang, gloss, pos, pos_title, "
            "tags, meta, src_ref, src) VALUES (?,?,?,?,?,?,?,?,?,?)", add_rows)
        # dict_id 回填：**按精确拼写**关联，绝不折叠大小写
        s.execute("UPDATE sense_add SET dict_id="
                  "(SELECT id FROM dict WHERE dict.word = sense_add.word) "
                  "WHERE dict_id IS NULL")

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    ok = gate1(con) and gate2(con)
    con.close()
    if ok:
        print("\n✅ 两道闸都通过")
        print("\n下一步：")
        print("  ① python3 -m es.pipeline.translate_sense_gap --apply   # 补中文")
        print("  ② python3 -m es.pipeline.build_sense_layer --apply     # 重建出版层")
    else:
        last = sorted(paths.BACKUPS.glob("*.pre-ingest-sense-gap-*.bak"))[-1]
        print(f"\n🔴 有闸没过。数据**已经写进库了**（闸跑在 commit 之后），要撤：\n"
              f"   cp {last} {paths.DB}")


if __name__ == "__main__":
    main()
