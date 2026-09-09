#!/usr/bin/env python3
"""阶段 4：音标层 → `pronunciation`。2026-09-08。**零 API、零下载、零成本。**

计划见 `EN_PLAN` §3.1 —— 那一节的框架在阶段 -1 被数据推翻过一次：
原写「352.9 万行缺口、必须单独立项、可能要上 CMUdict」，实测**核心根本没有缺口**
（核心 59,137 里两侧全空只有 3 条），六个外版对核心的净增益 ≈0（只补得上 12.6%，
de 那轮是 82.0%）⇒ **六个外版一版不收，CMUdict 不要。**

═══ 两个源，缺一不可 ═══
① **kaikki en 版**（读中间件 `entries.jsonl`，**不扫 3.2 GB**）
   283,962 条 sounds，**占位符 0 条**（de 那轮有 21,149 条 `[…]` 占位）。
② ⭐ **项目自产 115,955 条**（老库 `phonetic_uk`/`phonetic_us`，07-31「en音标改造」的产物）
   🔴 **这是 kaikki 换不掉的资产**：kaikki 新包全部才 100,104 个词头有 IPA，
      且只覆盖核心的 63%。自产那批覆盖核心缺口 **100%**。
      ⇒ 必须原样搬进来，`src='en-selfgen'`，**不许被 kaikki 覆盖**（闸里有一条守它）。
   ⚠️ 七月那轮的中文因为结构是词条级的已全部作废，**音标是它唯一留下来的东西**。

═══ 四条判据，都是量出来的不是拍的 ═══
① **残片不入库**（本步自己逮到的）：335 条「裸音标」其实是**变体残片** ——
       fluorine  `-ɪn/`   源头是 /ˈflʊəriːn, -ɪn/，kaikki 把第二个变体切成了后缀
       finale    `fə-/`   前缀片段        ask  `ˈɛs/`  定界符不成对
   存 `-ɪn` 当 fluorine 的美音就是错的。判据按含义写：**一条音标必须是完整的**
   ⇒ 定界符成对 且 不以连字符起止。落 ledger 不静默丢。
② **notation 按定界符判**：`/…/` 音位式 93% ／ `[…]` 严式 7%。
   🔴 de 不能这么判（德语版 100% 是 `[…]` 定界，照搬会把全库标成 narrow），
      **en 能判是因为 en 版两种都用** —— 判据按这门语言的数据定，不照搬。
③ **地区：源头给的就记，推不出的留 null**。
   🔴 我第一版只映射 uk/us，把 Australia 13,461 / Canada 12,354 / NZ 9,505 /
      Scotland 7,185 全算进"推不出" ⇒ 地区覆盖被自己压低 14 个百分点。
      那些是**源头明说的事实**，不是我推的（`[[dont-gate-facts-on-my-uncertainty]]`）。
      扩表后 48% → **63%**。
④ **ipa 裸存**，不带 `/` `[` —— 六语种统一约定（`[[ipa-bare-storage-convention]]`），
   展示层加定界符。

    cd en && python3 -u pipeline/build_pronunciation.py
    cd en && python3 -u pipeline/build_pronunciation.py --run
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import collections
import json
import re
import sqlite3

import dbtool
import paths

ING = paths.WORK / "ingest" / "entries.jsonl"
LEDGER = paths.WORK / "ingest" / "pron_dropped.tsv"
SRC_KK, SRC_SELF = "en-edition", "en-selfgen"

REGION = {"UK": "uk", "RP": "uk", "British": "uk", "Received-Pronunciation": "uk",
          "England": "uk", "Northern-England": "uk", "Southern-England": "uk",
          "US": "us", "GA": "us", "GenAm": "us", "General-American": "us", "American": "us",
          "General-American-with-cot-caught-merger": "us",
          "Australia": "au", "General-Australian": "au",
          "Canada": "ca", "New-Zealand": "nz", "Ireland": "ie", "Scotland": "gb-sct",
          "Wales": "gb-wls", "India": "in", "South-Africa": "za"}
REGIONS = set(REGION.values())
PLACEHOLDER = re.compile(r"^[\[\(]?\s*[…\.\s\-–—]*\s*[\]\)]?$")


def parse_ipa(raw, word=""):
    """→ ([(裸 ipa, notation), …], 拒收原因 Counter)。三条判据都被数据打回过一次：

    🔴① **一个字段里可能塞着多个变体，用 `~` 隔开** —— 落库之后闸才报出来：
         `eagle` 的 `[ˈɪi̯ɡəl] ~ [ˈɪi̯ɡl̩]` 剥掉外层定界符后剩 `ˈɪi̯ɡəl] ~ [ˈɪi̯ɡl̩`。
         我第一版只查了 `,` 和 `…`。这两个都是**正经读音**⇒ **拆成两行，不是拒收**。
    🔴② **后缀词头的音标本来就以连字符开头** —— `-ability → -əˈbɪlɪti` 是对的，
         我的残片判据把 400 条合法后缀读音当成了残片
         （`[[criteria-narrower-than-you-think]]`：判据比它要描述的东西更宽）。
         ⇒ 连字符只在**词头自己没有连字符**时才算残片。
    ③ 真残片仍要拒：`fluorine /-ɪn/`（词头无连字符却给了后缀）、`finale /fə-/`。
    """
    out, why = [], collections.Counter()
    s = (raw or "").strip()
    if not s or PLACEHOLDER.match(s):
        return [], collections.Counter({"占位符": 1})
    w_hyphen = word.startswith("-") or word.endswith("-")
    for part in re.split(r"\s*~\s*", s):
        t = part.strip()
        if not t:
            continue
        if t[0] == "/" and t[-1] == "/" and len(t) > 2:
            body, nota = t[1:-1].strip(), "phonemic"
        elif t[0] == "[" and t[-1] == "]" and len(t) > 2:
            body, nota = t[1:-1].strip(), "narrow"
        else:
            why["定界符不成对（变体残片）"] += 1
            continue
        if not body:
            why["空"] += 1
            continue
        if (body[0] in "-–—" or body[-1] in "-–—") and not w_hyphen:
            why["连字符残片"] += 1
            continue
        if "," in body or "…" in body:
            why["一条里塞了多个变体"] += 1
            continue
        if "/" in body or "[" in body or "]" in body:
            why["剥不干净（内含定界符）"] += 1
            continue
        out.append((body, nota))
    return out, why


def collect(con):
    q = con.execute
    wid = dict(q("SELECT word, id FROM dict"))
    eid = dict(q("SELECT src_ref, id FROM entry"))
    rows, drop = [], collections.Counter()
    seen_key = collections.Counter()
    stat = collections.Counter()

    # ── ① kaikki（中间件，键的造法与 build_entry_layer 逐字一致）
    for line in ING.open(encoding="utf-8"):
        d = json.loads(line)
        w = d["word"]
        i = wid.get(w)
        praw = d.get("pos") or "unknown"
        etym = str(d.get("etym") or "0")
        k = (w, praw, etym)
        seq = seen_key[k]
        seen_key[k] += 1
        if i is None:
            continue
        e = eid.get("kk-en:%s:%s:%s:%d" % (w, praw, etym, seq))
        for s in d.get("sounds") or []:
            raw = s.get("ipa")
            if not raw:
                continue
            stat["sounds"] += 1
            got, why = parse_ipa(raw, w)
            drop.update(why)
            stat["dropped"] += sum(why.values())
            tags = s.get("tags") or []
            reg = next((REGION[t] for t in tags if t in REGION), None)
            for ipa, nota in got:
                rows.append((i, e, ipa, nota, reg,
                             json.dumps(tags, ensure_ascii=False) or None,
                             praw, 0, SRC_KK,
                             "kk-en:%s:%s:%s:%d" % (w, praw, etym, seq)))
                stat["kk"] += 1
            stat["split"] += max(0, len(got) - 1)

    # ── ② 项目自产（老库 uk/us）—— 词级，无 entry/pos
    for w, uk, us in q("SELECT word, phonetic_uk, phonetic_us FROM legacy_dict "
                       "WHERE COALESCE(phonetic_uk,'')<>'' OR COALESCE(phonetic_us,'')<>''"):
        i = wid.get(w)
        if i is None:
            stat["self_orphan"] += 1
            continue
        for v, reg in ((uk, "uk"), (us, "us")):
            v = (v or "").strip()
            if not v or PLACEHOLDER.match(v):
                continue
            # 🔴 **自产那批原来根本没过判据** —— 直接塞进去，闸当场报出 7 条含定界符、
            #    400 条连字符。老库的值是裸的（无 / 或 []），所以补上定界符再走同一把尺子，
            #    **一个源一把尺子会让两边的问题分头漏掉**。
            got, why = parse_ipa("/%s/" % v, w)
            drop.update(why)
            stat["dropped"] += sum(why.values())
            for ipa, nota in got:
                rows.append((i, None, ipa, "phonemic", reg, None, None, 0, SRC_SELF,
                             "en-selfgen:%s:%s" % (w, reg)))
                stat["self"] += 1
    return rows, stat, drop


def gates(con, stat, planned):
    q = lambda s: con.execute(s).fetchone()[0]
    n_self = q("SELECT COUNT(*) FROM pronunciation WHERE src='%s'" % SRC_SELF)
    checks = [
        ("pronunciation 行数", q("SELECT COUNT(*) FROM pronunciation"), planned),
        ("🔴 ipa 裸存（不含 / 或 [）",
         q("SELECT COUNT(*) FROM pronunciation WHERE ipa LIKE '%/%' OR ipa LIKE '%[%'"), 0),
        # 🔴 判据要和 `parse_ipa` 说的是同一件事：**连字符只在词头自己没有连字符时才算残片**。
        #    我第一版闸写成"任何连字符起止都算残片"，把 1,131 条合法的后缀读音报成红
        #    （`-ability → -əˈbɪlɪti` 是对的）。⇒ 闸比它要守的规则更宽，等于误报。
        ("🔴 ipa 是残片（词头无连字符却给了连字符音标）",
         q("SELECT COUNT(*) FROM pronunciation p JOIN dict d ON d.id=p.word_id "
           "WHERE (p.ipa LIKE '-%' OR p.ipa LIKE '%-') "
           "AND d.word NOT LIKE '-%' AND d.word NOT LIKE '%-'"), 0),
        # 负控：后缀词头的连字符音标必须**还在**（防止我又把判据写成一刀切）
        ("负控 后缀词头的连字符音标没被误删",
         q("SELECT COUNT(*) FROM pronunciation p JOIN dict d ON d.id=p.word_id "
           "WHERE (p.ipa LIKE '-%' OR p.ipa LIKE '%-') "
           "AND (d.word LIKE '-%' OR d.word LIKE '%-')") > 0, True),
        ("word_id 全在 dict 里",
         q("SELECT COUNT(*) FROM pronunciation p LEFT JOIN dict d ON d.id=p.word_id "
           "WHERE d.id IS NULL"), 0),
        ("entry_id 要么空要么在 entry 里",
         q("SELECT COUNT(*) FROM pronunciation p LEFT JOIN entry e ON e.id=p.entry_id "
           "WHERE p.entry_id IS NOT NULL AND e.id IS NULL"), 0),
        ("notation 只有两种",
         q("SELECT COUNT(*) FROM pronunciation WHERE notation NOT IN ('phonemic','narrow')"), 0),
        ("region 只在白名单内",
         q("SELECT COUNT(*) FROM pronunciation WHERE region IS NOT NULL AND region NOT IN (%s)"
           % ",".join("'%s'" % r for r in sorted(REGIONS))), 0),
        ("src 只有两种",
         q("SELECT COUNT(*) FROM pronunciation WHERE src NOT IN ('%s','%s')" % (SRC_KK, SRC_SELF)), 0),
        # 🔴 自产那批是 kaikki 换不掉的资产，一条都不许少
        ("⭐ 自产音标全在（不许被 kaikki 覆盖）", n_self, stat["self"]),
        # 🔴 负控**按含义写，不写"必须为 0"**：
        #    第一版写死 0，被 `airstream`（freq_rank 31007）报红 —— 而它两个源都真的没有音标。
        #    「给不出」不是缺陷，**「给得出却没收进来」才是**。⇒ 判据改成后者。
        ("🔴 核心词无音标、但老库其实有",
         q("SELECT COUNT(*) FROM dict d JOIN legacy_dict l ON l.word=d.word "
           "WHERE (d.freq_rank IS NOT NULL OR d.exam_tag IS NOT NULL) "
           "AND (COALESCE(l.phonetic_uk,'')<>'' OR COALESCE(l.phonetic_us,'')<>'') "
           "AND NOT EXISTS(SELECT 1 FROM pronunciation p WHERE p.word_id=d.id)"), 0),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-40s %s / %s" % ("✅" if ok else "🔴", name,
                                       format(got, ","), format(want, ",")))
    return bad


# 🔴🔴 **表结构要改：`UNIQUE` 里必须有 `region`**（2026-09-08 本步逮到）
#    阶段 0 建表时写的是 `UNIQUE(word_id, entry_id, ipa, notation)`。
#    实测：**61,212 条同 ipa 但地区不同** —— `cat` 的 `ˈkæt` 同时标着 uk 和 us。
#    这个约束等于**禁止「同一个音标适用于多个地区」**，而那是常态不是异常。
#    照它去重就会「只留第一条、把后来者的地区整个丢掉」——
#    `[[de-dict-pipeline]]` 记着 de 那轮**一模一样的 bug**：
#      「逮到一个任何闸都逮不到的 bug：去重时只留第一条、把后来者的地区信息整个丢了
#        ——合并后每条记录都合法，是独立探针与收割器给出不一致的数才照出来的。」
#    ⇒ 这次是**在写库之前**照出来的，因为我按 de 的教训专门去查了「丢的是不是地区」。
#    表还是空的，改约束最便宜。
DDL = """
DROP INDEX IF EXISTS idx_dict_pron_word;
ALTER TABLE pronunciation RENAME TO pronunciation_old;
CREATE TABLE pronunciation (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id    INTEGER NOT NULL,
    entry_id   INTEGER,
    ipa        TEXT NOT NULL,
    notation   TEXT NOT NULL,
    region     TEXT,
    tags       TEXT,
    pos        TEXT,
    is_primary INTEGER NOT NULL DEFAULT 0,
    src        TEXT NOT NULL,
    src_ref    TEXT NOT NULL,
    UNIQUE(word_id, entry_id, ipa, notation, region)
);
DROP TABLE pronunciation_old;
CREATE INDEX idx_dict_pron_word ON pronunciation(word_id);
CREATE INDEX idx_dict_pron_entry ON pronunciation(entry_id);
"""


def main(run=False):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows, stat, drop = collect(con)
    # 按新约束去重；同键的 tags **合并**不丢（318 条只差 tags）
    seen, uniq = {}, []
    for r in rows:
        k = (r[0], r[1], r[2], r[3], r[4])
        if k in seen:
            stat["dup"] += 1
            j = seen[k]
            a = json.loads(uniq[j][5] or "[]")
            b = json.loads(r[5] or "[]")
            if b and set(b) - set(a):
                m = a + [x for x in b if x not in a]
                uniq[j] = uniq[j][:5] + (json.dumps(m, ensure_ascii=False),) + uniq[j][6:]
                stat["tag_merged"] += 1
            continue
        seen[k] = len(uniq)
        uniq.append(tuple(r))
    print("═══ 阶段 4 计划 ═══")
    print("   kaikki sounds        %9s" % format(stat["sounds"], ","))
    print("   🔴 拒收（残片/占位符） %9s" % format(stat["dropped"], ","))
    for k, v in drop.most_common():
        print("        %-24s %s" % (k, format(v, ",")))
    print("   kaikki 入库           %9s" % format(stat["kk"], ","))
    print("   ⭐ 自产入库            %9s（落不上 %s）"
          % (format(stat["self"], ","), format(stat["self_orphan"], ",")))
    print("   同键去重（新约束含 region）%9s（其中 tags 合并 %s）" % (format(stat["dup"], ","), format(stat["tag_merged"], ",")))
    print("   ── 合计               %9s 行" % format(len(uniq), ","))
    con.close()
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text("reason\tcount\n" + "".join("%s\t%d\n" % (k, v) for k, v in drop.most_common()),
                      encoding="utf-8")
    if not run:
        print("\n(干跑。加 --run 才写库)  拒收明细 → %s" % LEDGER)
        return 0

    # 🔴 **重建时 `expect` 是「增量」不是「总数」**（2026-09-08 当场咬到）：
    #    本步会 DELETE 再重灌，闸比的是前后行数之差。写成总数 ⇒ 库里已有 495,766 行时
    #    实际增量只有 +2,711，闸报红（它的提示语说得很准：「期望值恰好等于写库后的总行数」）。
    #    ⚠️ 这个 expect **必须现算**，不能写死 —— 它随库当前状态变，
    #       写死就是 `EN_PLAN` 记的那条「非单调判据」（阶段 0「dict 必须为空」同形）。
    con0 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    now, = con0.execute("SELECT COUNT(*) FROM pronunciation").fetchone()
    con0.close()
    delta = len(uniq) - now
    print("\n   库内现有 %s 行 ⇒ 本次净增量 %+d" % (format(now, ","), delta))
    with dbtool.session("keep-v3-4-pronunciation", expect={"#pronunciation": delta}) as s:
        s.execute("DELETE FROM pronunciation")
        for stmt in DDL.strip().split(";"):
            if stmt.strip():
                s.execute(stmt)
        s.executemany(
            "INSERT INTO pronunciation (word_id,entry_id,ipa,notation,region,tags,pos,"
            "is_primary,src,src_ref) VALUES (?,?,?,?,?,?,?,?,?,?)", uniq)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸② ═══")
    bad = gates(con, stat, len(uniq))
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    _sys.exit(main(run="--run" in _sys.argv))
