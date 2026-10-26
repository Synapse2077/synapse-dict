#!/usr/bin/env python3
"""阶段 3：**屈折层**。ru，2026-10-09。九门里规模最大的一层。

═══ 收什么 ═══
`inflection` 一行 ＝ **某个词元的某一个屈折形**。
🔴 `entry_id` 的语义是**「原形的那个 entry」**（照 it 阶段 8 定死的），
   不是「这个屈折形自己的 entry」—— 后者在阶段 1 已经作为独立的 `dict`/`entry` 行收过了。

═══ 🔴🔴🔴 这一层最贵的一课：`forms` 这一个字段装着四类东西 ═══
「完整 tag 值域、无条件不过滤」那一节打出 **138 种 tag**，照出四类：

    ① 词头自己的带重音拼写   `canonical`/`stressed`         → 阶段 2 已收
    ② **拉丁转写**           `romanization` 437,016 ／ `transliteration` 21,093
    ③ **变位表模板元数据**   `table-tags`/`inflection-template`/`class` 257,286
    ④ 真正的屈折形           6,561,212

⇒ **照「有语法标签就收」做，会往 `form` 里灌 45.8 万行拉丁转写。**
   而 pl 版那「20,776 个有 forms 行的词」**整个是转写，一条屈折形都没有** ——
   拿它当「有变位表的词」算分母，覆盖率会虚报 4.5 个百分点。

🔴🔴 **而光按 tag 挡还不够**：en/fr 版会发出「只带语法标签的拉丁转写行」
   （`я → ja ['first-person','nominative','personal']`，**120,671 行**，fr 占 103,246）。
   ⇒ 判据必须**两个独立信号一致**：tag 不在非词形登记表里 **且** 这串字真的是西里尔。
   判据的家是 `criteria.inflection_rows`，本文件一条都不自己写。

═══ ⚠️ 指针路**有意不做**，而这个结论是被一次错的度量差点骗过去的 ═══
en 版 38.3 万个条目带 `form_of` 指针（屈折形页 → 词元），是 `PLAYBOOK` 四说的
「2b/2c 两条反向的路」的另一条。实测：

    只拿 **ru 版** 的变位表比：重叠 91.98%，只有指针路给的 **31,656** 对
    拿**全部版**的变位表并集比：重叠 **99.03%**，只有指针路给的 **3,848** 对（+262 个词元）

🔴 第一个数是**我的度量比问题窄** —— 落库的变位表来自六个版，只拿 ru 版比
   把指针路的增量**高估了 8.2 倍**（`[[measure-landing-not-source]]`：
   新数字先假设我的度量错了。同一天这是第二次，上一次是「指针目标只有 24.27%
   在 dict 里」，真因是 91.81% 的目标带重音符）。
⇒ **量的是什么**：指针路能给出而全部变位表都没给的 (屈折形, 词元) 对。
   **量出多少**：3,848 对 / +262 个词元 / +0.04 个百分点。
   **什么会推翻它**：① 这个数涨过 5 万对或覆盖率增量过 1 个百分点；
   ② 阶段 9 的读者路径要印「这个词形指向哪个词元」——
     那件事的家是 `sense_src.pointer_target`（阶段 5），**不是这张表**，
     指针本身一条都没丢。

═══ ⚠️ `class` 那一族没有家 —— 记欠账，不临时发明一列 ═══
`inflection-template` 给的是模板名（`ru-noun-table`）⇒ 落 `table_tag`。
而 `class` 给的是**词干型/重音型**（`velar-stem`／`accent-a`／`5b/c imperfective`），
**一个 entry 有多个**，且它与 `entry.declension` 现在装的 ru 版值域
（`declension-1/2/3/indeclinable`）**是两套不同的分类系统** ——
塞进同一列就是 ko 的 **K8/K10 同签名**那笔账（五种不规则共用一个值、
「数的是有值的行不是有信息的行」）。⇒ 存档 ＋ 欠账 **R16**，带锁。
"""
import argparse
import collections
import gzip
import json
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import dbtool                                                   # noqa: E402
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402
from pipeline.build import SRC, rd                              # noqa: E402

# 🔴 6,56 万行**不许攒在内存里**（实测一行 tuple 约 540 字节 ⇒ 3.5 GB）。
#    先落一个临时 TSV，数清之后再流式写库 —— `expect` 要的是精确增量，
#    而精确增量只能在数清之后才知道。
SPOOL = paths.WORK / "stage3_inflection_spool.tsv.gz"


def collect(limit=None, verbose=True):
    """扫七源 → 把屈折行写进临时 TSV。→ 统计。**只读库，不写库。**"""
    ref = criteria.SrcRef()
    st = {
        "kind": collections.Counter(),
        "kind_eg": collections.defaultdict(list),
        "rows": collections.Counter(),           # src → 落库行数
        "lemmas": collections.defaultdict(set),  # src → 覆盖的词
        "dup": collections.Counter(),            # 同一 entry 内 (form,tags) 重复
        "table_tag": collections.Counter(),      # 模板名的值域
        "classes": collections.Counter(),        # `class` 的值域（欠账 R16）
        "class_entries": 0,
        "marked": collections.Counter(),
        "ptr": collections.Counter(),
    }
    SPOOL.parent.mkdir(parents=True, exist_ok=True)
    n_out = 0
    with gzip.open(SPOOL, "wt", encoding="utf-8") as spool:
        for src, p in SRC:
            t0 = time.time()
            n = 0
            for e in rd(p, limit):
                n += 1
                ok, _skip, pos = criteria.entry_accept(e)
                if not ok:
                    continue
                w = e["word"]
                no, sub = criteria.etym_no_pair(e)
                sref, _seq = ref.take(src, w, pos, no, sub)
                forms = e.get("forms") or []
                if not forms:
                    continue
                # ── 先把这个 entry 的模板名/类取出来（它们不是词形）──
                tt, cls = None, []
                for f in forms:
                    tags = set(f.get("tags") or [])
                    v = (f.get("form") or "").strip()
                    if not v:
                        continue
                    if "inflection-template" in tags:
                        tt = tt or v
                        st["table_tag"][v] += 1
                    elif "class" in tags:
                        cls.append(v)
                        st["classes"][v] += 1
                if cls:
                    st["class_entries"] += 1
                # ── 再收屈折形 ──
                seen = set()
                for f in forms:
                    tags = f.get("tags") or []
                    # 🔴 判据要知道这一行的**上下文**（词性 ＋ 它来自哪张表）——
                    #    张冠李戴的那两类（en 的 `g` 代词表 / ru 的兄弟代词）
                    #    靠单行的形状看不出来，错的是「它属于谁」。
                    kind, rows = criteria.inflection_rows(
                        w, f.get("form") or "", tags, pos=pos, table_tag=tt)
                    st["kind"][kind] += 1
                    if len(st["kind_eg"][kind]) < 6:
                        st["kind_eg"][kind].append(
                            "%-16s → %-26s %s" % (w, (f.get("form") or "")[:26],
                                                  tags[:3]))
                    for bare, stressed, extra in rows:
                        tg = "|".join(sorted(set(tags) | set(extra)))
                        key = (bare, tg)
                        if key in seen:
                            st["dup"][src] += 1
                            continue
                        seen.add(key)
                        for x in extra:
                            st["marked"][x] += 1
                        n_out += 1
                        st["rows"][src] += 1
                        st["lemmas"][src].add(w)
                        spool.write("\t".join((
                            sref, bare, stressed or "", tg, tt or "", src,
                            "%s#infl.%d" % (sref, len(seen) - 1))) + "\n")
            if verbose:
                print("  · %-16s %9s 行  %5.1fs" % (src, format(n, ","),
                                                    time.time() - t0),
                      file=sys.stderr)
    st["n_out"] = n_out
    return st


def report(st):
    print("\n■ 阶段 3 屈折层")
    print("   会落库 %s 行" % format(st["n_out"], ","))
    print("\n   判据分桶（`criteria.inflection_rows`，**收的只有 ok 那一桶**）：")
    tk = sum(st["kind"].values())
    for k, v in st["kind"].most_common(14):
        print("      %-44s %10s  %6.2f%%" % (k, format(v, ","),
                                             100.0 * v / max(tk, 1)))
    rest = len(st["kind"]) - 14
    if rest > 0:
        tail = sum(v for _k, v in st["kind"].most_common()[14:])
        print("      （另有 %d 个小桶合计 %s 行，明细见探针存档 —— "
              "**每个都有名字，没有「其他」兜底桶**）" % (rest, format(tail, ",")))
    print("\n   按源：")
    for src, _p in SRC:
        if st["rows"][src]:
            print("      %-16s %12s 行   %8s 个词   源头重复 %s"
                  % (src, format(st["rows"][src], ","),
                     format(len(st["lemmas"][src]), ","),
                     format(st["dup"][src], ",")))
    print("\n   `table_tag` 的值域（%d 种，全打）：" % len(st["table_tag"]))
    for k, v in st["table_tag"].most_common():
        print("      %-28s %10s" % (k, format(v, ",")))
    print("\n   🔴 `class` 这一族**没有家**（欠账 R16）：涉及 %s 个 entry、%d 种值"
          % (format(st["class_entries"], ","), len(st["classes"])))
    for k, v in st["classes"].most_common(8):
        print("      %-28s %10s" % (k, format(v, ",")))
    print("\n   源头标过记号的行（进 `tags`，命名空间 `src-mark:`）：")
    for k, v in st["marked"].most_common():
        print("      %-18s %10s" % (k, format(v, ",")))


def write(st, rebuild=False):
    conn = sqlite3.connect(paths.DB)
    q = conn.execute
    ent = {r[1]: r[0] for r in q("SELECT id, src_ref FROM entry")}
    base = q("SELECT COUNT(*) FROM inflection").fetchone()[0] if rebuild else 0
    exp = {
        "#inflection": st["n_out"] - base,
        "inflection.form": st["n_out"] - base,
    }
    # 🔴 `stressed` 是**可空**的，而且确实有一批没有（缩写 `б/г`、`янв.`
    #    这类没有元音可标的）—— 所以它的期望值要**单独数**，不能照抄总行数。
    #    ⚠️ 这一条是写 `expect` 时自己拦住的：抄总行数的话闸会红在一个没错的数据上
    #      （阶段 1 的 `is_lemma` 同一个形状）。
    # 🔴 **两遍流式，不许把 650 万个 tuple 攥在手里**（实测约 3.5 GB）：
    #    第一遍只数（`expect` 要精确增量，而精确增量只能数清之后才知道），
    #    第二遍在 session 里分块灌。读两次 500 MB 的 gz 比吃 3.5 GB 内存便宜得多。
    def spool_rows():
        with gzip.open(SPOOL, "rt", encoding="utf-8") as f:
            for line in f:
                sref, bare, stressed, tg, tt, src, sr = line.rstrip("\n").split("\t")
                yield sref, bare, stressed, tg, tt, src, sr

    n_rows = n_stressed = miss = 0
    for sref, _b, stressed, _tg, _tt, _src, _sr in spool_rows():
        if sref not in ent:
            miss += 1
            continue
        n_rows += 1
        if stressed:
            n_stressed += 1
    if miss:
        raise SystemExit("🔴🔴 %s 行的 `src_ref` 在库里找不到 entry —— "
                         "探针 §0 证明过这不该发生，查完再跑" % format(miss, ","))
    if n_rows != st["n_out"]:
        # 🔴 两个独立算出来的数必须相等：扫描时数的 ＋ 从临时文件数回来的。
        #    不等 ⇒ 临时文件写坏了或被人动过，**不许静默往下走**。
        raise SystemExit("🔴🔴 扫描时数了 %s 行，从临时文件数回来 %s 行 —— "
                         "两个数不一致，临时文件不可信"
                         % (format(st["n_out"], ","), format(n_rows, ",")))
    exp["#inflection"] = n_rows - base
    exp["inflection.form"] = n_rows - base
    exp["inflection.stressed"] = n_stressed - (
        conn.execute("SELECT COUNT(*) FROM inflection WHERE stressed IS NOT NULL "
                     "AND TRIM(stressed)<>''").fetchone()[0] if rebuild else 0)
    print("\n   其中带重音符的 %s 行（%.2f%%）—— 缩写/无元音的那批没有，**如实留空**"
          % (format(n_stressed, ","), 100.0 * n_stressed / max(n_rows, 1)))
    with dbtool.session("inflection-layer" + ("-rebuild" if rebuild else ""),
                        expect=exp, invalidates=["inflection"]) as s:
        if rebuild:
            s.execute("DELETE FROM inflection")
        buf = []
        for sref, bare, stressed, tg, tt, src, sr in spool_rows():
            eid = ent.get(sref)
            if eid is None:
                continue
            buf.append((eid, bare, stressed or None, tg or None, tt or None,
                        src, sr))
            if len(buf) >= 200000:
                s.executemany(
                    "INSERT INTO inflection(entry_id,form,stressed,tags,"
                    "table_tag,src,src_ref) VALUES (?,?,?,?,?,?,?)", buf)
                buf = []
        if buf:
            s.executemany(
                "INSERT INTO inflection(entry_id,form,stressed,tags,"
                "table_tag,src,src_ref) VALUES (?,?,?,?,?,?,?)", buf)
    out = paths.WORK / "stage3_inflection_stats.json"
    out.write_text(json.dumps({
        "rows": st["n_out"], "stressed": n_stressed,
        "kinds": dict(st["kind"]),
        "by_src": {k: v for k, v in st["rows"].items()},
        # 🔴 `class` 这一族没有家 ⇒ **存档，不丢**（照 R11 的办法）
        "class_values": dict(st["classes"]),
        "class_entries": st["class_entries"],
        "table_tags": dict(st["table_tag"]),
        "rule_ver": criteria.RULE_VER,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n■ 统计已存档 → %s（含 `class` 值域，欠账 R16）" % out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--rebuild", action="store_true",
                    help="判据改了：清掉这一层原地重算（本层无付费数据）")
    a = ap.parse_args()
    print("■ 扫七源（屈折层）……", file=sys.stderr)
    st = collect(a.limit or None)
    report(st)
    if a.dry:
        print("\n(dry：没写库，临时 TSV 留在 %s)" % SPOOL)
        return 0
    if a.limit:
        raise SystemExit("🔴 `--limit` 只许和 `--dry` 一起用")
    write(st, rebuild=a.rebuild)
    SPOOL.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
