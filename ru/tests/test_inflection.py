#!/usr/bin/env python3
"""**屈折闸** —— 阶段 3 的不变量。ru，2026-10-09。

    python3 ru/tests/test_inflection.py
    python3 ru/tests/test_inflection.py --mutate     # 变异验证：闸的闸
    python3 ru/tests/test_inflection.py --accept     # 把覆盖率现状锁成基线

═══ 这一层 638 万行，而它最容易出的错**不是脏数据，是「这一行属于谁」** ═══
① **拉丁转写混进 `form`**（I5/I11）。`forms` 字段装着四类东西，而只有一类是屈折形：
   照「有语法标签就收」做会灌进 **45.8 万行** `romanization`；而**光按 tag 挡还不够** ——
   en/fr 版会发出「只带语法标签的转写行」（`я → ja`，120,671 行，fr 占 103,246）。
   ⇒ 判据是**两个独立信号一致**，而 I11 查的是**第二个信号的落点**：
   出版层一个拉丁字母都不许有。
② **张冠李戴**（I12）。en 版代词表模板 `g` 把整张人称代词范式印在**每个**代词页上
   （`я → ты / он / она`），落过库的 2,871 行里 85.3% 首字母与词头不同（基线 3.35%）；
   ru 版同一个病的小规模复发是「兄弟代词」（`она → он`，81 行）。
   ⚠️ 删它之前**证明过零信息损失**：ru 版给每个代词自己的正确范式。
③ **两列必须互相对得上**（I4）。`form` 是不带重音的、`stressed` 是带重音的，
   而后者剥掉重音符**必须等于**前者 —— 两列各写一次就会漂。
④ **闸自己用收它的那个函数复核**（I2）。判据一律 `import criteria`：
   ko 的 K24／vi 的 R19 都是闸手写一版近似判据，**同时更宽又更窄**。

⚠️ I2 要把 638 万行逐行过一遍判据（约 2 分钟）。**不抽样** ——
   `[[verification-gates-not-sampling]]`：可逆性回核 100% 非抽样。
"""
import argparse
import collections
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402
from pipeline.build import SRC                                  # noqa: E402

# 🔴 **花名册独立声明**，不从代码里数（ko 的 K31：改测试时删掉一条而闸报全绿）
ROSTER = ("I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8", "I9", "I10",
          "I11", "I12", "I13")

ACCEPT = HERE / ".inflection_accept.json"

# `src` 的登记表。**问名单不写形状。**
# ⚠️ pl 版**有意不在里面** —— 它那 21,093 行 `forms` **整个是拉丁转写**
#    （`transliteration`），一条屈折形都没有。这句话本身是判据的一部分：
#    哪天 pl 出现在这一列，说明转写被当成屈折形收了进来。
SRC_DOMAIN = frozenset({"en-edition", "ru-edition", "zh-edition-simp",
                        "zh-edition-trad", "fr-edition", "vi-edition"})

# `table_tag` 的登记表（实测 8 种，全是 ru 版的模板名）。
# 🔴 `g` **不在里面而且必须不在** —— 它是张冠李戴那张表（见文件头 ②）。
TABLE_TAG_DOMAIN = frozenset({
    "ru-conj", "ru-conj-old", "ru-decl-adj", "ru-decl-adj-irreg",
    "ru-decl-noun-irreg", "ru-decl-noun-irreg-unc", "ru-ndecl", "ru-noun-table"})


def _open():
    return sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)


def _accept():
    try:
        return json.loads(ACCEPT.read_text("utf-8"))
    except Exception:                            # noqa: BLE001
        return {}


def coverage(con):
    tot = con.execute("SELECT COUNT(*) FROM dict WHERE is_lemma=1").fetchone()[0]
    got = con.execute(
        "SELECT COUNT(DISTINCT d.id) FROM dict d JOIN entry e ON e.word_id=d.id "
        "JOIN inflection i ON i.entry_id=e.id WHERE d.is_lemma=1").fetchone()[0]
    rows = con.execute("SELECT COUNT(*) FROM inflection").fetchone()[0]
    return dict(lemmas=tot, with_table=got, pct=100.0 * got / max(tot, 1),
                rows=rows, per_lemma=rows / max(got, 1))


# ── I2 在变异副本上只复核「副本里有、真库里没有」的行 ──────────────────
# 🔴 为什么成立：`mutate()` 开跑前强制真库基线全绿 ⇒ 真库 638 万行**已经逐行**过了
#    `criteria.inflection_rows`；没变的行不可能变成不合格。变异只改几行（或删一批），
#    要复核的只有差集。普通档与最后的反控制**照样逐行全查**。
# ⭐ 代价从「12 条 × 638 万次 Python 调用」（一轮 ≈1.5 小时）降到秒级。
# 🔴🔴 这条捷径自己的闸是 **I2 那条变异**：它往副本里改一行坏值 ——
#    差集写坏（比如恒为空）的话 I2 逮不到，变异当场报「没逮到」。
#    ⚠️ 差集的列必须**正好是判据读的那几列**（form/stressed/tags/table_tag/e.pos）：
#       少一列 ⇒ 改了那一列的变异会被差集漏掉（B20：变异要动判据真正读的量）。
_I2_COLS = ("SELECT i.id, i.form, i.stressed, i.tags, i.table_tag, e.pos "
            "FROM %(p)sinflection i JOIN %(p)sentry e ON e.id=i.entry_id")


def _i2_rows(con, base):
    if base is None:
        return con.execute(_I2_COLS % {"p": ""})
    con.execute("ATTACH DATABASE ? AS base", ("file:%s?mode=ro" % base,))
    return con.execute((_I2_COLS % {"p": ""}) + " EXCEPT " + (_I2_COLS % {"p": "base."}))


def checks(con, base=None):
    """`base` ＝ 真库路径：只在变异副本上传（见 `_i2_rows`）。普通档必须是 None。"""
    out = []
    acc = _accept()

    def q(sql, *a):
        return con.execute(sql, a).fetchone()[0]

    # ── I1 这一层非空 ──────────────────────────────────────────────
    n = q("SELECT COUNT(*) FROM inflection")
    out.append(("I1", n > 0, "" if n else "`inflection` 是空的 —— 阶段 3 声明 ✅ 而一行都没有"))

    # ── I2 出版值必须满足收它的那条判据（判据 import，闸不重写）────────
    bad2, eg2 = 0, []
    for iid, form, stressed, tags, tt, pos in _i2_rows(con, base):
        src_form = stressed or form
        tg = [x for x in (tags or "").split("|") if x]
        # 🔴 回核用的「词头」就是 `form` 自己 —— 判据问的是「这个串是不是一个
        #    合法的俄语词形」，而它不需要知道词元是谁（词元关系由 `entry_id` 承载）。
        ok, kind, rows = True, "", None
        kind, rows = criteria.inflection_rows(form, src_form, tg, pos=pos,
                                              table_tag=tt)
        if kind != "ok" or not rows or rows[0][0] != form:
            bad2 += 1
            if len(eg2) < 5:
                eg2.append("#%d %s|%s〔%s〕" % (iid, form, stressed or "", kind))
    out.append(("I2", bad2 == 0,
                "" if not bad2 else
                "%s 行出版值过不了 `criteria.inflection_rows` —— "
                "**收它的判据和查它的判据必须是同一个函数**：%s"
                % (format(bad2, ","), " ｜ ".join(eg2))))

    # ── I3 外键 ＋ 不许有空 `form` ──────────────────────────────────
    fk = q("SELECT COUNT(*) FROM inflection i LEFT JOIN entry e ON e.id=i.entry_id "
           "WHERE e.id IS NULL")
    empty = q("SELECT COUNT(*) FROM inflection WHERE TRIM(form)=''")
    out.append(("I3", fk == 0 and empty == 0,
                "" if not (fk or empty) else
                "entry_id 悬空 %s 行 ／ `form` 为空 %s 行"
                % (format(fk, ","), format(empty, ","))))

    # ── I4 两列互相对得上：`stressed` 剥掉重音符 ＝ `form` ────────────
    # 🔴 **两个方向**：值不一致 ＋ 带重音的那批比例跌破基线
    #    （只查前者的话「把 `stressed` 全清空」会静默通过）。
    mism = q("SELECT COUNT(*) FROM inflection WHERE stressed IS NOT NULL "
             "AND REPLACE(REPLACE(stressed,CHAR(769),''),CHAR(768),'')<>form")
    nst = q("SELECT COUNT(*) FROM inflection WHERE stressed IS NOT NULL "
            "AND TRIM(stressed)<>''")
    pct = 100.0 * nst / max(n, 1)
    base_pct = acc.get("stressed_pct")
    drop = base_pct is not None and pct < base_pct - 0.01
    out.append(("I4", mism == 0 and not drop,
                "" if not (mism or drop) else
                "`stressed` 与 `form` 对不上 %s 行；带重音符占比 %.2f%%"
                "（基线 %s）—— 两列各写一次就会漂"
                % (format(mism, ","), pct,
                   "%.2f%%" % base_pct if base_pct is not None else "未锁")))

    # ── I5 `form` 不许带重音符（它的定义就是「不带」）──────────────────
    mk = q("SELECT COUNT(*) FROM inflection WHERE form LIKE '%'||CHAR(769)||'%' "
           "OR form LIKE '%'||CHAR(768)||'%'")
    out.append(("I5", mk == 0,
                "" if not mk else
                "%s 行 `form` 带着重音符 —— 带重音的那一份在 `stressed` 列，"
                "两列混了之后检索键就不干净了" % format(mk, ",")))

    # ── I6 `tags` 值域 ⊆ 实测域 ∪ 两个命名空间 ──────────────────────
    dom = set(acc.get("tags", []))
    unseen = collections.Counter()
    for (t,) in con.execute("SELECT tags FROM inflection WHERE tags IS NOT NULL"):
        for x in t.split("|"):
            if not x:
                continue
            if x.startswith("src-mark:") or x.startswith("src-label:"):
                continue
            if dom and x not in dom:
                unseen[x] += 1
    out.append(("I6", not dom or not unseen,
                "" if (not dom or not unseen) else
                "`tags` 出现 %d 个没登记的值：%s —— 源头加了新 tag，"
                "**要么登记要么是抽错了**（2026-10-07 那一跤：我拿猜的值域写判据，"
                "两家外审对一个不存在的现象各给了一套归因）"
                % (len(unseen), unseen.most_common(6))))

    # ── I7 `src` ⊆ 登记表，**且每一个登记的源都有行**（vi 的 X12）─────
    got = {r[0] for r in con.execute("SELECT DISTINCT src FROM inflection")}
    uns, misses = sorted(got - SRC_DOMAIN), sorted(SRC_DOMAIN - got)
    out.append(("I7", not uns and not misses,
                "" if not (uns or misses) else
                "`src` 没登记的值 %s ／ 登记了而一行都没有的源 %s —— "
                "后者只查「表非空」是查不出来的（少收一整版也全绿）"
                % (uns, misses)))

    # ── I8 `table_tag` 值域 ⊆ 登记表（`g` 必须不在）──────────────────
    tt = {r[0] for r in con.execute(
        "SELECT DISTINCT table_tag FROM inflection WHERE table_tag IS NOT NULL")}
    bad8 = sorted(tt - TABLE_TAG_DOMAIN)
    out.append(("I8", not bad8,
                "" if not bad8 else
                "`table_tag` 出现没登记的值 %s —— 其中 `g` 是**张冠李戴那张表**"
                "（en 版把整张代词范式印在每个代词页上）" % bad8))

    # ── I9 (entry_id, form, tags) 不许重复 ─────────────────────────
    dup = q("SELECT COUNT(*) FROM (SELECT entry_id, form, COALESCE(tags,'') "
            "FROM inflection GROUP BY 1,2,3 HAVING COUNT(*)>1)")
    out.append(("I9", dup == 0,
                "" if not dup else
                "%s 组 (entry_id, form, tags) 重复 —— 源头自己就有重复行"
                "（en 7.6 万 / fr 9.1 万），收割器要去重" % format(dup, ",")))

    # ── I10 覆盖率基线：**只许涨不许跌** ───────────────────────────
    cov = coverage(con)
    base = acc.get("coverage")
    if base is None:
        ok10, why10 = False, ("词元变位表覆盖 %.2f%%，而**还没有已接受基线** —— "
                              "跑一次 `--accept`" % cov["pct"])
    else:
        ok10 = cov["pct"] >= base["pct"] - 0.01
        why10 = ("" if ok10 else
                 "覆盖率跌到 %.2f%%（基线 %.2f%%）—— 「已接受」≠「不再看」"
                 % (cov["pct"], base["pct"]))
        if ok10 and abs(cov["pct"] - 100.0) < 1e-9:
            ok10, why10 = False, "覆盖率恒等 100.00% —— **假闸的签名**（分母套了分子）"
    out.append(("I10", ok10, why10))

    # ── I11 🔴 出版层一个拉丁字母都不许有（第二个信号的落点）───────────
    lat = q("SELECT COUNT(*) FROM inflection WHERE form GLOB '*[a-zA-Z]*' "
            "OR stressed GLOB '*[a-zA-Z]*'")
    out.append(("I11", lat == 0,
                "" if not lat else
                "%s 行出版值含拉丁字母 —— `forms` 字段里有 45.8 万行拉丁转写，"
                "而 en/fr 版会发出「只带语法标签的转写行」(120,671 行)，"
                "**光按 tag 挡挡不住**" % format(lat, ",")))

    # ── I12 张冠李戴的两类必须是 0 ─────────────────────────────────
    g = q("SELECT COUNT(*) FROM inflection WHERE table_tag IN (%s)"
          % ",".join("'%s'" % x for x in criteria.BAD_TABLE_TAGS))
    sib = q("SELECT COUNT(*) FROM inflection i JOIN entry e ON e.id=i.entry_id "
            "WHERE e.pos='pron' AND (i.tags IS NULL OR i.tags='')")
    out.append(("I12", g == 0 and sib == 0,
                "" if not (g or sib) else
                "张冠李戴复发：`g` 表 %s 行 ／ 代词表的兄弟代词 %s 行 —— "
                "读者会在 `я` 的页上看见 `ты` 被印成它的屈折形"
                % (format(g, ","), format(sib, ","))))

    # ── I13 R16 的锁：`class` 那一族还没有家 ───────────────────────
    # 🔴 **带锁的豁免**：`class`（词干型/重音型，512 种值、56,985 个 entry）
    #    与 `entry.declension` 现在装的 ru 版值域是**两套分类系统**，
    #    塞一列就是 ko 的 K8/K10 同签名 ⇒ 现在只存档。
    #    锁：存档文件必须在，且**一旦库里出现装它的列/表，这条当场红**，
    #    逼人回来写明「它的家在哪、值域怎么分」。
    arch = paths.WORK / "stage3_inflection_stats.json"
    live = {r[1] for r in con.execute("PRAGMA table_info(inflection)")}
    cols = {r[1] for r in con.execute("PRAGMA table_info(entry)")}
    appeared = sorted({"infl_class", "stem_class", "accent_class"}
                      & (live | cols))
    ok13 = arch.exists() and not appeared
    out.append(("I13", ok13,
                "" if ok13 else
                ("存档 %s 不在 —— `class` 那 512 种值就真的丢了" % arch.name
                 if not arch.exists() else
                 "库里出现了 %s —— R16 的锁到期了：`class` 有家了，"
                 "那就要写明值域怎么与 `entry.declension` 分开" % appeared)))
    return out


def roster_check(rows):
    bad = []
    got = [c for c, _ok, _w in rows]
    if len(got) != len(ROSTER):
        bad.append("输出 %d 条，花名册声明 %d 条" % (len(got), len(ROSTER)))
    if sorted(got) != sorted(ROSTER):
        bad.append("编号对不上：多 %s ／ 少 %s"
                   % (sorted(set(got) - set(ROSTER)), sorted(set(ROSTER) - set(got))))
    if len(set(got)) != len(got):
        bad.append("有重复编号 %s" % got)
    return bad


def report():
    if not paths.DB.exists():
        print("🔴 库不存在：%s" % paths.DB)
        return 1
    con = _open()
    try:
        rows = checks(con)
        cov = coverage(con)
    finally:
        con.close()
    print("■ 屈折闸（ru 阶段 3）—— 花名册 %d 条" % len(ROSTER))
    for cid, ok, why in rows:
        print("   %s %-5s %s" % ("✅" if ok else "🔴", cid, why))
    rb = roster_check(rows)
    for b in rb:
        print("   🔴🔴 花名册自检：" + b)
    print("   %s 行 ／ 词元 %s/%s 有变位表 ＝ **%.2f%%** ／ 每词元平均 %.1f 行"
          % (format(cov["rows"], ","), format(cov["with_table"], ","),
             format(cov["lemmas"], ","), cov["pct"], cov["per_lemma"]))
    red = [r for r in rows if not r[1]]
    print("■ %s（%d/%d）" % ("全绿 ✓" if not red and not rb else "有红",
                            len(rows) - len(red), len(rows)))
    return len(red) + len(rb)


def accept():
    con = _open()
    try:
        cov = coverage(con)
        tags = set()
        for (t,) in con.execute("SELECT tags FROM inflection WHERE tags IS NOT NULL"):
            for x in t.split("|"):
                if x and not x.startswith("src-mark:") and not x.startswith("src-label:"):
                    tags.add(x)
        nst = con.execute("SELECT COUNT(*) FROM inflection WHERE stressed IS NOT NULL "
                          "AND TRIM(stressed)<>''").fetchone()[0]
        pct = 100.0 * nst / max(cov["rows"], 1)
    finally:
        con.close()
    ACCEPT.write_text(json.dumps({
        "coverage": {"pct": round(cov["pct"], 2), "lemmas": cov["lemmas"],
                     "with_table": cov["with_table"], "rows": cov["rows"]},
        "stressed_pct": round(pct, 2),
        "tags": sorted(tags),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("■ 已接受基线写入 %s：覆盖 %.2f%% ／ 带重音 %.2f%% ／ tags 值域 %d 种"
          % (ACCEPT.name, cov["pct"], pct, len(tags)))
    return 0


def _mutations():
    """(编号, 说明, 允许的连带红, SQL)。**合成行一律负 id ＋ `«变异»` 词头**（B20）。

    🔴 「允许的连带红」逐条列，**没列的当红处理** —— 2026-10-08 写重音闸时
       发现它的报告无条件印「已声明」而我根本没声明过，
       **撒谎的报告比没有报告更坏**。
    """
    return [
        ("I2", "把一行出版值改成过不了判据的串", {"I5", "I11"},
         ["UPDATE inflection SET form='abc', stressed=NULL "
          "WHERE id=(SELECT MIN(id) FROM inflection)"]),
        ("I3", "让一行的 entry_id 悬空", {"I2"},
         ["UPDATE inflection SET entry_id=-7 "
          "WHERE id=(SELECT MIN(id) FROM inflection)"]),
        ("I4", "把 `stressed` 全清空（真值还在 `form` 里）", set(),
         ["UPDATE inflection SET stressed=NULL"]),
        # 🔴 连带 I4 是**该红的**：I4 断言「`stressed` 剥重音 ＝ `form`」，`form` 脏了等式就破。
        #    第一次跑变异（2026-10-23）漏声明、被「没声明的当红」拦下 —— 补声明不是放水，
        #    是把「审过了」写成真的。
        ("I5", "往 `form` 里塞一个重音符", {"I2", "I4", "I9"},
         ["UPDATE inflection SET form=stressed WHERE stressed IS NOT NULL "
          "AND id=(SELECT MIN(id) FROM inflection WHERE stressed IS NOT NULL)"]),
        ("I6", "往 `tags` 塞一个没登记的值", set(),
         ["UPDATE inflection SET tags='«变异»genitive' "
          "WHERE id=(SELECT MIN(id) FROM inflection)"]),
        ("I7", "删掉某一个源的全部行（模拟少收一版）", {"I10"},
         ["DELETE FROM inflection WHERE src='vi-edition'"]),
        ("I8", "往 `table_tag` 塞一个没登记的值", set(),
         ["UPDATE inflection SET table_tag='«变异»tbl' "
          "WHERE id=(SELECT MIN(id) FROM inflection)"]),
        ("I9", "造一组 (entry_id, form, tags) 重复", set(),
         ["INSERT INTO inflection(id,entry_id,form,stressed,tags,src,src_ref) "
          "SELECT -1, entry_id, form, stressed, tags, src, src_ref||'#mut' "
          "FROM inflection LIMIT 1"]),
        # 🔴 变异要动**判据真正读的那个量**。I10 读的是「有变位表的词元数」，
        #    所以要删掉一批词元的全部行 —— 按 entry_id 取模删一半。
        ("I10", "删掉一半词元的变位表（覆盖率跌破基线）", {"I7"},
         ["DELETE FROM inflection WHERE entry_id IN (SELECT e.id FROM entry e "
          "JOIN dict d ON d.id=e.word_id WHERE d.is_lemma=1 AND e.id%2=0)"]),
        ("I11", "塞一行拉丁转写（tag 只带语法标签，模拟 en/fr 版那 12 万行）",
         {"I2"},
         ["INSERT INTO inflection(id,entry_id,form,stressed,tags,src,src_ref) "
          "SELECT -2, id, 'sobaka', NULL, 'genitive|singular', 'en-edition', "
          "'mut-lat' FROM entry LIMIT 1"]),
        # 🔴 连带 I2 是**该红的**：`criteria.inflection_rows` 自己就拒 `g` 表（BAD_TABLE_TAGS）
        #    ⇒ 张冠李戴有**两道独立的防线**（值域 I8 ＋ 收割判据 I2），I12 是第三道（读者口径）。
        #    同上，2026-10-23 第一次跑变异时漏声明。
        ("I12", "让张冠李戴那张表复发（`table_tag='g'`）", {"I2", "I8"},
         ["INSERT INTO inflection(id,entry_id,form,stressed,tags,table_tag,"
          "src,src_ref) SELECT -3, id, '«变异»ты', NULL, 'nominative', 'g', "
          "'en-edition', 'mut-g' FROM entry LIMIT 1"]),
        # 🔴 I13 是**带锁的豁免**，验它的变异要打的是**锁本身**：
        #    往库里加一列装 `class` ⇒ 锁到期判红。
        #    ⚠️ 这一条照 vi 的 V10 教训写：带锁的豁免每多一个状态，
        #      验它的变异就要多一支 —— 现在是「还没有家」那一支。
        ("I13", "给 `entry` 加一列 `stem_class`（R16 的锁到期）", set(),
         ["ALTER TABLE entry ADD COLUMN stem_class TEXT"]),
    ]


def mutate():
    if not paths.DB.exists():
        print("🔴 库不存在，变异没法做")
        return 1
    if report():
        print("\n🔴 基线就不绿，先修基线（否则分不清是变异还是旧红）")
        return 1
    muts = _mutations()
    print("\n■ 变异验证（%d 条，跑在库的副本上，真库一个字节不动）" % len(muts))
    print("   ⚠️ I1    无变异档：清空 `inflection` 会让 I4/I9/I10/I12 连带红，分不开")
    real = paths.DB
    fails = []
    for cid, why, also, sqls in muts:
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / real.name
            shutil.copy2(real, cp)
            paths.DB = cp
            try:
                con = sqlite3.connect(cp)
                for s in sqls:
                    con.execute(s)
                con.commit()
                con.close()
                con = _open()
                try:
                    got = {c for c, ok, _ in checks(con, base=real) if not ok}
                finally:
                    con.close()
                if cid in got:
                    undecl = sorted(got - {cid} - set(also))
                    if undecl:
                        print("   🔴 %-5s 逮到了，**但有没声明的连带红 %s** —— %s"
                              % (cid, undecl, why))
                        fails.append(cid)
                    else:
                        extra = sorted(got - {cid})
                        print("   ✅ %-5s %s%s" % (cid, why, "" if not extra else
                                                   "（连带红 %s，已逐条声明）" % extra))
                elif got:
                    print("   🔴 %-5s 红了，但红的是 %s，不是它自己 —— %s"
                          % (cid, sorted(got), why))
                    fails.append(cid)
                else:
                    print("   🔴🔴 %-5s **一条都没红** —— 判据是假的或变异是空操作：%s"
                          % (cid, why))
                    fails.append(cid)
            finally:
                paths.DB = real
    if report():
        print("\n🔴🔴 反控制失败：真库基线不绿了 —— 副本隔离破了")
        return 1
    print("\n%s" % ("■ 变异验证全过 ✓，反控制：真库基线仍全绿" if not fails
                    else "🔴 %d 条没逮到：%s" % (len(fails), fails)))
    return 1 if fails else 0


def check_brief():
    if not paths.DB.exists():
        return [("I?", "库不存在")]
    con = _open()
    try:
        return [(c, w) for c, ok, w in checks(con) if not ok]
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--accept", action="store_true")
    a = ap.parse_args()
    if a.accept:
        raise SystemExit(accept())
    raise SystemExit(mutate() if a.mutate else (1 if report() else 0))


if __name__ == "__main__":
    main()
