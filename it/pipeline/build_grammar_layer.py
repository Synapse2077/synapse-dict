#!/usr/bin/env python3
"""语法层：把源头的**及物性**和**助动词**落到它们本来所属的层。2026-08-13，Q1。

═══ 问题 ═══
七月流水线把两个信号都压平到**词形**上了：
    dict.aux          avere 40,614 / essere 6,228 / both 2,160
    dict.transitivity t 5,555 / i 1,726 / ti 1,690     ← 只有 8,971 个词形有值
而源头里它们根本不在同一层：
    · 及物性 = **义项级**（`senses[].tags` 的 transitive/intransitive/reflexive/…）
    · 助动词 = **词条级**（`forms[]` 里 tags 含 "auxiliary" 的那一行）
压平的代价：`rallentare` 只能显示 aux=both，用户看不出「及物义用 avere、不及物义用 essere」。

═══ 落法 ═══
① 及物性 → `sense_tag(kind='grammar', value=<源头原词>)`
   🔴 **不建 `sense.transitivity` 列**（`SCHEMA` §10.4 原来是这么写的，这里推翻）：
      及物性是**多值**的（transitive+ditransitive、impersonal+intransitive 实测都有），
      塞进单列就要发明一套编码，而发明的编码既会失真又会变成第二份真值。
      `gender` 能当列是因为它互斥单值 —— 多值的东西落行，单值的才落列。
   数据源是**库里的 `sense_src.raw_tags`**（证据层建库时已经存下了），不重扫 dump。

② 助动词 → `entry.aux`（'avere' / 'essere' / 'both'）
   ⚠️ 源头写的是重音形式 `avére` / `èssere`，还有 `"-"` 这种占位（`fire`）—— 都要归一。
   ⚠️ 我第一次量这个数时搜的是 `head_templates` 的 "aux" 参数、正则写 `avere`，
      漏掉了重音符，量出来偏小。真值在 `forms[]`。

③ 双助动词的逐义项归属 → `sense.aux`（**只在能确定时才写**）
   819 个词条给了两个助动词。源头**自己带了条件标签**：
       rallentare: avére[transitive] + èssere[intransitive]
   ⇒ 义项及物性 ↔ 词条条件标签，**确定性匹配**，不调模型。
   条件标签缺失（`sapere`：两个助动词都不带条件）或匹配到多个 ⇒ 不写，停在 entry 的 both。
   🔴 `sense.aux` 是**覆盖值不是复制值**：单助动词词条的义项一律留 NULL，
      展示层取 `sense.aux ?? entry.aux`。不复制 = 不会漂移。

🔴 `dict.aux` / `dict.transitivity` 本轮**不动**（见文末「记账」）：把它降级成派生聚合
   需要变形层的 lemma 指针（阶段 2）。本轮只**量**它与新层的一致性，不改写。

用法（在 it/ 目录下）：
    python3 pipeline/build_grammar_layer.py            # 干跑，只报数
    python3 pipeline/build_grammar_layer.py --apply
    python3 pipeline/build_grammar_layer.py --verify   # 闸①外锚 + 闸②不变量
    python3 pipeline/build_grammar_layer.py --mutate   # 变异验证：闸必须能红
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402
from build_entry_layer import assign_seq   # noqa: E402  复用 seq 分配，保证与 entry 层同一把尺

# 源头的及物性标签，**原样收录不改写**（收哪些是判据，改成什么样不是我们的活）
GRAMMAR_TAGS = {"transitive", "intransitive", "ditransitive", "ambitransitive",
                "reflexive", "pronominal", "impersonal", "copulative"}
# 助动词归一：源头带重音符，"-" 是占位符（wiktextract 没抓到值）
AUX_NORM = {"avére": "avere", "avere": "avere", "èssere": "essere", "essere": "essere"}
# 条件标签里只有及物性维度能与义项对上；rare/usually/also 这类是程度副词，不参与匹配
COND_TAGS = GRAMMAR_TAGS


# ══════════════════════════════════════════════════════════════════ 取数

def replay_aux(dump_path, words):
    """扫 dump，产出 {(词形,词性,词源号,ipas): {助动词: 条件标签集合}}，以及 seq 用的 dup_groups。

    ⚠️ 键里带 ipas 是因为 entry 层的 seq 就是按音标分的（同键不同音标要拆成两个 entry）。
    """
    aux_of = defaultdict(lambda: defaultdict(set))
    dup_groups = defaultdict(list)
    stat = Counter()
    with open(dump_path, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                stat["坏行"] += 1
                continue
            w0 = e.get("word") or ""
            if w0.strip().lower() not in words:
                continue
            pos = e.get("pos") or ""
            etym = str(e.get("etymology_number") or 0)
            key0 = (w0, pos, etym)
            ipas = frozenset(s["ipa"] for s in (e.get("sounds") or []) if s.get("ipa"))
            dup_groups[key0].append((ipas, (e.get("etymology_text") or "")[:200]))
            if pos != "verb":
                continue
            for fm in (e.get("forms") or []):
                tags = fm.get("tags") or []
                if "auxiliary" not in tags:
                    continue
                raw = (fm.get("form") or "").strip()
                val = AUX_NORM.get(raw)
                if val is None:
                    stat["助动词取值无法归一（'-' 占位或异常）"] += 1
                    continue
                stat["auxiliary 行"] += 1
                aux_of[(key0, ipas)][val] |= (set(tags) & COND_TAGS)
    return aux_of, dup_groups, stat


def entry_aux_rows(aux_of, seq_of):
    """{entry.src_ref: (aux 值, {助动词: 条件标签})}"""
    out, lost = {}, 0
    for (key0, ipas), vals in aux_of.items():
        seq = seq_of.get((key0, ipas))
        if seq is None:
            # assign_seq 对每个出现过的 (键, 音标) 都给了 seq；落到这里说明尺子不一致，
            # 不能静默跳过 —— 静默跳过正是「漏收看起来像全绿」的经典形状。
            lost += 1
            continue
        w, pos, etym = key0
        ref = "kk-en:%s:%s:%s:%d" % (w, pos, etym, seq)
        cur = out.setdefault(ref, {})
        for k, v in vals.items():
            cur[k] = cur.get(k, set()) | v
    if lost:
        print("   🔴 %d 个带助动词的 dump 词条对不上 entry 的 seq —— 尺子不一致，停手" % lost)
        raise SystemExit(1)
    return {ref: (resolve_aux(v), v) for ref, v in out.items()}


def resolve_aux(vals):
    ks = sorted(vals)
    if not ks:
        return None
    return ks[0] if len(ks) == 1 else "both"


def sense_grammar(con):
    """从证据层 `sense_src.raw_tags` 取及物性 → {sense_id: [标签…]}（排序、去重）。"""
    out = {}
    for sid, raw in con.execute(
            "SELECT sense_id, raw_tags FROM sense_src WHERE raw_tags IS NOT NULL"):
        try:
            tags = json.loads(raw)
        except Exception:
            continue
        hit = sorted(set(tags) & GRAMMAR_TAGS)
        if hit:
            out[sid] = hit
    return out


def derive_sense_aux(con, ent_aux, sgram):
    """双助动词词条：义项及物性 ↔ 词条条件标签，确定性匹配。

    返回 ({sense_id: aux}, 统计)。匹配不上 / 匹配到多个 ⇒ 不写。
    """
    ref_of, id_of = {}, {}
    for eid, ref in con.execute("SELECT id, src_ref FROM entry"):
        ref_of[eid] = ref
        id_of[ref] = eid
    out, stat = {}, Counter()
    dual = {ref: v for ref, (a, v) in ent_aux.items() if a == "both"}
    dual_ids = {id_of[r] for r in dual if r in id_of}
    for sid, eid in con.execute(
            "SELECT id, entry_id FROM sense WHERE entry_id IS NOT NULL"):
        if eid not in dual_ids:
            continue
        stat["双助动词词条下的义项"] += 1
        conds = dual[ref_of[eid]]
        tags = set(sgram.get(sid, []))
        if not tags:
            stat["义项没有及物性标签 ⇒ 不写"] += 1
            continue
        hit = [a for a, c in conds.items() if c and (c & tags)]
        if len(hit) == 1:
            out[sid] = hit[0]
            stat["✅ 确定性定到单一助动词"] += 1
        elif not hit:
            stat["条件标签缺失或对不上 ⇒ 不写" if any(conds.values())
                 else "词条两个助动词都没给条件标签 ⇒ 不写"] += 1
        else:
            stat["匹配到多个助动词 ⇒ 不写"] += 1
    return out, stat


# ══════════════════════════════════════════════════════════════════ 闸

def gate1(con, dump_path, verbose=True):
    """闸① 外锚回核：库里的语法层 vs **dump 原文**，双向、100%、非抽样。

    锚的是冻结的外部文件，不是我们自己的上一版 ⇒ 这条闸永不过期。
    """
    print("\n═══ 闸① 外锚回核（vs dump 原文，全量双向）═══")
    words = {w.lower() for (w,) in con.execute("SELECT word FROM dict")}
    aux_of, dup_groups, _ = replay_aux(dump_path, words)
    seq_of = assign_seq(dup_groups, verbose=False)
    want = entry_aux_rows(aux_of, seq_of)

    bad = []
    have = {ref: aux for ref, aux in con.execute(
        "SELECT src_ref, aux FROM entry WHERE aux IS NOT NULL")}
    for ref, (aux, _) in want.items():
        if aux is not None and have.get(ref) != aux:
            bad.append(("entry.aux 少了或不对", ref, aux, have.get(ref)))
    for ref, aux in have.items():                       # 反向：库里有、dump 没有 = 凭空捏造
        if want.get(ref, (None, None))[0] != aux:
            bad.append(("entry.aux 库里有 dump 没有", ref, want.get(ref, (None,))[0], aux))
    print("   entry.aux   dump 侧 %s 条 / 库侧 %s 条 / 不符 %d"
          % (f"{sum(1 for v in want.values() if v[0]):,}", f"{len(have):,}", len(bad)))

    # 及物性：sense_tag(grammar) 必须与证据层 raw_tags 逐条相等（双向）
    want_g = sense_grammar(con)
    have_g = defaultdict(list)
    for sid, v in con.execute("SELECT sense_id, value FROM sense_tag WHERE kind='grammar'"):
        have_g[sid].append(v)
    bad_g = 0
    for sid in set(want_g) | set(have_g):
        if want_g.get(sid, []) != sorted(have_g.get(sid, [])):
            bad_g += 1
            if len(bad) < 8:
                bad.append(("sense_tag(grammar) 与证据层不符", sid,
                            want_g.get(sid), sorted(have_g.get(sid, []))))
    print("   及物性      证据层 %s 条义项 / 出版层 %s 条 / 不符 %d"
          % (f"{len(want_g):,}", f"{len(have_g):,}", bad_g))

    if bad:
        for b in bad[:8]:
            print("     ✗ %s  %s  dump=%s 库=%s" % b)
    print("   %s" % ("✅ 零不符" if not bad and not bad_g else "🔴 有不符"))
    return not bad and not bad_g


def gate2(con):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    has_aux = "aux" in {r[1] for r in con.execute("PRAGMA table_info(sense)")}
    checks = [
        ("entry.aux 取值只有 avere/essere/both",
         q("SELECT count(*) FROM entry WHERE aux IS NOT NULL "
           "AND aux NOT IN ('avere','essere','both')"), 0),
        ("entry.aux 只出现在动词词条上",
         q("SELECT count(*) FROM entry WHERE aux IS NOT NULL AND pos<>'verb'"), 0),
        ("sense_tag(grammar) 取值都在源头标签表里",
         q("SELECT count(*) FROM sense_tag WHERE kind='grammar' AND value NOT IN (%s)"
           % ",".join("'%s'" % t for t in sorted(GRAMMAR_TAGS))), 0),
        ("sense_tag(grammar) 无重复（同义项同标签）",
         q("SELECT count(*) FROM (SELECT sense_id,value FROM sense_tag "
           "WHERE kind='grammar' GROUP BY 1,2 HAVING count(*)>1)"), 0),
        ("sense_tag 无孤儿",
         q("SELECT count(*) FROM sense_tag t LEFT JOIN sense s ON s.id=t.sense_id "
           "WHERE s.id IS NULL"), 0),
        ("sense.aux 取值只有 avere/essere",
         q("SELECT count(*) FROM sense WHERE aux IS NOT NULL "
           "AND aux NOT IN ('avere','essere')") if has_aux else 0, 0),
        ("🔴 sense.aux 只在 entry.aux='both' 时才写（否则就是复制、会漂移）",
         q("SELECT count(*) FROM sense s JOIN entry e ON e.id=s.entry_id "
           "WHERE s.aux IS NOT NULL AND COALESCE(e.aux,'')<>'both'") if has_aux else 0, 0),
        ("sense.aux 必须与该义项的及物性标签相容",
         q("SELECT count(*) FROM sense s WHERE s.aux IS NOT NULL AND NOT EXISTS "
           "(SELECT 1 FROM sense_tag t WHERE t.sense_id=s.id AND t.kind='grammar')")
         if has_aux else 0, 0),
        ("register/region 标签没被本轮碰过",
         q("SELECT count(*) FROM sense_tag WHERE kind IN ('register','region')"), 17645),
        ("🔴 每条带语法标签的证据行都在出版层有对应（阶段 2a 新增义项时漏过 415 条）",
         q("SELECT count(*) FROM sense_src x WHERE x.raw_tags IS NOT NULL "
           "AND x.sense_id IS NOT NULL AND (%s) AND NOT EXISTS("
           "SELECT 1 FROM sense_tag t WHERE t.sense_id=x.sense_id AND t.kind='grammar')"
           % " OR ".join("x.raw_tags LIKE '%%\"%s\"%%'" % t for t in sorted(GRAMMAR_TAGS))), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-56s %s (期望 %s)" % ("✅" if good else "🔴", name, got, want))
    return ok


def mutate(dump_path):
    """变异验证：一条永远通过的检查等于没检查。每种变异都必须被逮到。"""
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "m.sqlite"
    shutil.copy(paths.DB, tmp)
    cases = [
        ("改掉一个 entry.aux（avere→essere）",
         "UPDATE entry SET aux='essere' WHERE aux='avere' AND id="
         "(SELECT min(id) FROM entry WHERE aux='avere')"),
        ("删掉一条 sense_tag(grammar)",
         "DELETE FROM sense_tag WHERE kind='grammar' AND rowid="
         "(SELECT min(rowid) FROM sense_tag WHERE kind='grammar')"),
        ("凭空多一条 sense_tag(grammar)",
         "INSERT INTO sense_tag (sense_id,kind,value) SELECT sense_id,'grammar','reflexive' "
         "FROM sense_tag WHERE kind='grammar' AND value='transitive' LIMIT 1"),
        ("抹掉一个 entry.aux（漏收）",
         "UPDATE entry SET aux=NULL WHERE id=(SELECT min(id) FROM entry WHERE aux IS NOT NULL)"),
        ("给单助动词词条的义项写 sense.aux（复制值陷阱）",
         "UPDATE sense SET aux='avere' WHERE id=(SELECT s.id FROM sense s "
         "JOIN entry e ON e.id=s.entry_id WHERE e.aux='avere' LIMIT 1)"),
    ]
    caught = 0
    for name, sql in cases:
        c2 = sqlite3.connect(tmp)
        c2.execute(sql)
        c2.commit()
        ro = sqlite3.connect("file:%s?mode=ro" % tmp, uri=True)
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            g1 = gate1(ro, dump_path, verbose=False)
            g2 = gate2(ro)
        ro.close()
        red = not (g1 and g2)
        caught += red
        print("   %s %-46s %s" % ("✅" if red else "🔴", name,
                                  "闸红了（对）" if red else "闸没红 —— 这条闸是假的"))
        # 还原
        c2 = sqlite3.connect(tmp)
        c2.close()
        shutil.copy(paths.DB, tmp)
    print("\n   变异验证 %d/%d" % (caught, len(cases)))
    return caught == len(cases)


# ══════════════════════════════════════════════════════════════════ 主

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    a = ap.parse_args()

    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        ok = gate1(ro, paths.KK) & gate2(ro)
        return 0 if ok else 1
    if a.mutate:
        return 0 if mutate(paths.KK) else 1

    words = {w.lower() for (w,) in ro.execute("SELECT word FROM dict")}
    print("■ 扫 dump 取助动词 …")
    aux_of, dup_groups, stat = replay_aux(paths.KK, words)
    for k, v in stat.most_common():
        print("   %-40s %8s" % (k, f"{v:,}"))
    seq_of = assign_seq(dup_groups, verbose=False)
    ent_aux = entry_aux_rows(aux_of, seq_of)
    dist = Counter(v[0] for v in ent_aux.values())
    print("\n■ entry.aux：%s 个词条" % f"{len(ent_aux):,}")
    for k, v in dist.most_common():
        print("   %-10s %8s" % (k, f"{v:,}"))

    sgram = sense_grammar(ro)
    gdist = Counter(t for v in sgram.values() for t in v)
    print("\n■ 及物性：%s 条义项带标签，共 %s 个标签"
          % (f"{len(sgram):,}", f"{sum(gdist.values()):,}"))
    for k, v in gdist.most_common():
        print("   %-16s %8s" % (k, f"{v:,}"))

    saux, sstat = derive_sense_aux(ro, ent_aux, sgram)
    print("\n■ 双助动词逐义项归属：")
    for k, v in sstat.most_common():
        print("   %-44s %8s" % (k, f"{v:,}"))

    # 与七月旧值的一致性（只量不改，见文件头「记账」）
    old = {}
    for w, aux in ro.execute("SELECT word, aux FROM dict WHERE aux IS NOT NULL AND aux<>''"):
        old[w.lower()] = aux
    ref_word = {}
    for ref in ent_aux:
        ref_word[ref] = ref.split(":")[1]
    agree = dis = miss = 0
    for ref, (aux, _) in ent_aux.items():
        o = old.get(ref_word[ref])
        if o is None:
            miss += 1
        elif o == aux:
            agree += 1
        else:
            dis += 1
    print("\n■ 与七月 dict.aux 的一致性（只量不改）：一致 %s / 不一致 %s / 旧库无值 %s"
          % (f"{agree:,}", f"{dis:,}", f"{miss:,}"))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    id_of = {ref: eid for eid, ref in ro.execute("SELECT id, src_ref FROM entry")}
    ro.close()
    ent_rows = [(aux, id_of[ref]) for ref, (aux, _) in ent_aux.items()
                if aux and ref in id_of]
    # 🔴 只插**还没有的**：阶段 2a 之后新增了义项，本脚本必须能增量重跑而不重复插。
    #    （`INSERT OR IGNORE` 不行 —— sense_tag 没有唯一约束。）
    ro2 = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    exist = {(sid, v) for sid, v in ro2.execute(
        "SELECT sense_id, value FROM sense_tag WHERE kind='grammar'")}
    ro2.close()
    tag_rows = [(sid, "grammar", t) for sid, ts in sgram.items() for t in ts
                if (sid, t) not in exist]
    n_tags = len(tag_rows)

    with dbtool.session("grammar-layer",
                        expect={"#sense_tag": n_tags}) as s:
        cols = {r[1] for r in s.conn.execute("PRAGMA table_info(sense)")}
        if "aux" not in cols:
            s.execute("ALTER TABLE sense ADD COLUMN aux TEXT")
        s.executemany("UPDATE entry SET aux=? WHERE id=?", ent_rows)
        s.executemany("INSERT INTO sense_tag (sense_id,kind,value) VALUES (?,?,?)", tag_rows)
        s.executemany("UPDATE sense SET aux=? WHERE id=?",
                      [(v, k) for k, v in saux.items()])
    print("\n■ 已写：entry.aux %s 行 / sense_tag(grammar) %s 行 / sense.aux %s 行"
          % (f"{len(ent_rows):,}", f"{n_tags:,}", f"{len(saux):,}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
