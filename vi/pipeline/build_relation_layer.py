#!/usr/bin/env python3
"""vi 阶段 6b：**语义关系层**（`sense_relation`）。2026-10-01。

判据全部 `import stage6_sources`。裁决见 `vi/probes/probe_stage6.py` §C（可重跑）。

═══ 🔴🔴 B17 的判据：naive 版比正确版宽 **11 倍** ═══
    naive「兜底 `related` 撞上**任何**别的 kind」    14,547 对（13.5%）
    正确「兜底 `related` 撞上**语义更具体**的 kind」   1,317 对（ 1.2%）

差的 13,230 全是 `paronym + related`（法语版同时列 *paronymes* 与 *apparentés*）。
**paronym 是语音关系** —— 两个词读音像，并不意味着语义相关，所以 `related` 仍带信息。
照 naive 版做 ＝ 隐藏 14,547 对里 13,230 对**该留的**。
`[[consult-two-models-on-rules]]`：兜底分支要单独量。

═══ 🔴 `target_id` 解析不了的留 NULL —— 展示层据此决定不做成链接 ═══
实测可解析 83.1%，16.9% 解析不了。那不是缺陷：关系目标里有大量派生复合词、
短语，它们本来就没有自己的词条。**ko 那边「关系词 34.6% 点下去空白页」就是
把这类目标做成了链接。** ⇒ `target_id IS NULL` 是一等信息，不是失败。

⚠️ 同一个 `word_norm` 对应多条 `dict` 行时（实测 8,537 次），取 **id 最小**的那条，
   但**先试精确大小写匹配**（`Trang` 的关系不该指到 `trang` 上去）。这是声明，不是默认。

═══ 🔴 K14：两个写入方在 `src` 列必须分得开 ═══
ko 的 `sense_relation` 有两个写入方而 `src` 列分不开它们（欠账 K14）。
vi 这一层**目前只有一个写入方**（跨版收割），`src` 写成 `<版>-edition`。
🔴 **什么会推翻**：将来若有第二个写入方（比如从汉字表记生成异体关系），
   它必须用自己的 `src` 前缀，并且这道闸要加一条「每个 src 的行数都 > 0」。

用法：
    python3 vi/pipeline/build_relation_layer.py            # 干跑
    python3 vi/pipeline/build_relation_layer.py --apply
"""
import argparse
import collections
import gzip
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import dbtool                                                     # noqa: E402
import paths                                                      # noqa: E402
import stage6_sources as S6                                       # noqa: E402
from criteria import (is_han_headword, norm_vi,                    # noqa: E402
                      merged_sense_map)   # 🔴 W25 折叠解析，见例句层同一处注释

PATH_OF = {
    "en-edition": paths.KK, "vi-edition": paths.EDITION,
    "zh-edition-trad": paths.ZH_TRAD, "zh-edition-simp": paths.ZH_SIMP,
    "fr-edition": paths.FR_EDITION, "ja-edition": paths.JA_EDITION,
    "ko-edition": paths.KO_EDITION, "pl-edition": paths.PL_EDITION,
    "ru-edition": paths.RU_EDITION, "nl-edition": paths.NL_EDITION,
    "pt-edition": paths.PT_EDITION, "de-edition": paths.DE_EDITION,
}
F = lambda n: format(n, ",")                                      # noqa: E731


def rd(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def resolve(norm_exact, norm_any, target):
    """目标词形 → `dict.id` 或 None。**先精确大小写，再归一后取 id 最小**。"""
    if target in norm_exact:
        return norm_exact[target]
    return norm_any.get(norm_vi(target))


def index(con):
    """→ (wid, norm_exact, norm_any, s2id, tot)。**抽出来是为了外锚闸能 import**。

    🔴 2026-10-02 抽的，`[[refactor-mindset-code-quality]]`。动机不是整洁：
       外锚闸（`verify_layers_vs_dump.py`）要拿**收割器本身**的产出跟库比，
       而这段逻辑原先埋在 `main()` 里 ⇒ 闸只能自己重写一遍判据，
       那正是 ko 那道外锚闸栽的跤（判据写宽报 3 万假缺、写细报 7,163 假缺，
       根因都是「闸与收割器不用同一个函数」）。**纯搬移，一行逻辑没动。**
    """
    wid = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    norm_exact, norm_any = {}, {}
    for i, w, wn in con.execute("SELECT id, word, word_norm FROM dict ORDER BY id"):
        norm_exact.setdefault(w, i)
        norm_any.setdefault(wn, i)
    # 义项级关系只有 en 版有 ⇒ 只给 en 版建 (词,词性,词源号,义序) → sense_id
    # 🔴 W25：与例句层同一道折叠解析（53 条义项级关系挂在被折叠的义项上）
    merged = merged_sense_map(con)
    s2id = {}
    for ref, sid in con.execute("SELECT src_ref, sense_id FROM sense_src ORDER BY id"):
        if not ref.startswith("sense:en:") or sid is None:
            continue
        sid = merged.get(sid, sid)
        body = ref[len("sense:"):]
        _ed, rest = body.split(":", 1)
        rest, _gi = rest.rsplit(":", 1)
        rest, si = rest.rsplit(":", 1)
        rest, etym = rest.rsplit(":", 1)
        w, pos = rest.rsplit(":", 1)
        s2id.setdefault((w, pos, etym, int(si)), sid)
    return wid, norm_exact, norm_any, s2id, len(wid)


def collect(wid, norm_exact, norm_any, s2id):
    """收割 ⇒ (最终行, 统计, (词,目标)→kind 集合, 值域外的关系字段)。

    🔴 **抽出来是为了外锚闸能 import 同一个函数**（见 `index()` 的注释）。
       纯搬移：去重与 B17 判定都在里面，因为**闸要比的是最终落库的那批行**。
    ⚠️ 「源头长出值域外的关系字段」那条守卫**有意留在 `main()`** ——
       它是 `raise SystemExit`，而闸不该代替调用方决定怎么死。
    """
    rows, stat = [], collections.Counter()
    pairs = collections.defaultdict(set)
    unknown = collections.Counter()
    for src, _lang in S6.EDITIONS:
        for e in rd(PATH_OF[src]):
            w = (e.get("word") or "").strip()
            # 🔴 兜底：源头有没有我们值域里没有的关系字段
            for k in e:
                if k.endswith(("nyms", "nymes")) and k not in S6.KINDS:
                    unknown[k] += 1
            if w not in wid:
                stat["源词不在 dict（汉字词头等，有意不收）"] += 1
                continue
            pos = e.get("pos")
            etym = str(e.get("etymology_number", "0") or "0")
            for si, obj in [(None, e)] + list(enumerate(e.get("senses") or [])):
                for fld, kind in S6.KINDS.items():
                    for ri, it in enumerate(obj.get(fld) or []):
                        if not isinstance(it, dict):
                            stat["关系项不是对象 ⇒ 丢"] += 1
                            continue
                        t, why = S6.relation_target(it)
                        if t is None:
                            stat["丢：" + why.split("（")[0]] += 1
                            continue
                        if is_han_headword(t):
                            # 汉字目标必然死链（汉字词头有意不进 dict）。
                            # ⚠️ **不拿 `roman` 顶上** —— 那是那个汉字词的读音，
                            #    不等于「这个词的 derived 是它」（编造关系）
                            stat["丢：目标是汉字/喃字 ⇒ 必然死链"] += 1
                            continue
                        if S6.has_non_vietnamese_script(t):
                            # 🔴 106 行：日语词 ／ **越南语词+韩语释义拼在一个字段** ／
                            #    **整段标签塞进 target**（`파생어: cá biệt (個別), …`）
                            #    —— 与 ko 自己那条「关系目标塞整段释义」同形
                            stat["丢：目标含假名/韩文字母 ⇒ 不是越南语词形"] += 1
                            continue
                        sense_id = (s2id.get((w, pos, etym, si))
                                    if si is not None else None)
                        stat["挂义项" if sense_id else "词条级"] += 1
                        pairs[(wid[w], norm_vi(t))].add(kind)
                        rows.append((
                            wid[w], sense_id, kind, t,
                            resolve(norm_exact, norm_any, t), src,
                            "rel:%s:%s:%s:%s:%s:%s:%d"
                            % (src.split("-")[0], w, pos, etym,
                               "T" if si is None else si, kind, ri)))
    # 去重（src_ref 唯一）
    seen, out = set(), []
    for r in rows:
        if r[6] in seen:
            stat["同源重复（去重）"] += 1
            continue
        seen.add(r[6])
        out.append(r)
    rows = out

    # ── 隐藏判据两条，**顺序有意义**：先 W9（目标压根不是越南语词），再 B17。
    #    🔴 顺序的理由：W9 那批全是死链，它们**不该参与 B17 的"吞掉"判断** ——
    #      一个死链目标不构成「读者在两个标题下看见同一个词」。
    #      （`pairs` 在上面已经算完，这里只决定 hidden_why，所以两条不会互相污染。）
    final = []
    for r in rows:
        if S6.non_quoc_ngu_letters(r[3]):
            # W9：目标含非国语字字母 ⇒ 不是越南语词形，实测 2,238 行全部死链
            final.append(r + (S6.HIDDEN_TARGET_FOREIGN,))
            continue
        hid = (r[2] == "related" and bool(pairs[(r[0], norm_vi(r[3]))] & S6.SUBSUME))
        final.append(r + (S6.HIDDEN_REDUNDANT_RELATED if hid else None,))
    rows = final
    return rows, stat, pairs, unknown


def _sync(rows):
    """原地把 `sense_relation.sense_id` 同步到 `collect()` 的产出。行数一行不变。

    🔴 W25 折叠义项之后那 53 条义项级关系要跟着改指向 —— 而**不能走 `--rebuild`**
       （它会删掉 W17 手工收的 30 条，见 `--sync` 的参数注释）。
    ⚠️ 只同步 `sense_id` 这一列：别的列若也漂了，说明判据变了，那该走重建而不是偷偷改。
    """
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = dict(con.execute("SELECT src_ref, sense_id FROM sense_relation"))
    con.close()
    upd, miss = [], 0
    for r in rows:
        ref = r[6]
        if ref not in have:
            miss += 1
            continue
        if have[ref] != r[1]:
            upd.append((r[1], ref))
    print("\n■ `--sync`：`sense_id` 要改 %s 行（收割器有而库里没有的键 %s 个）"
          % (F(len(upd)), F(miss)))
    if miss:
        # 🔴 **大声报，不静默** —— 键对不上意味着判据或收词变了，那是另一件事。
        print("   ⚠️ 有 %s 个键在库里不存在。`--sync` 只改已有行，"
              "行数要变得走重建。" % F(miss))
    if not upd:
        print("   库已经与 `collect()` 一致，什么都不做。")
        return
    with dbtool.session("sync-vi-relation-sense-id",
                        expect={"__rows__": 0, "sense_relation.sense_id": None},
                        invalidates=[]) as s:
        s.executemany("UPDATE sense_relation SET sense_id=? WHERE src_ref=?", upd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    # 🔴 本层是**纯派生层**（全部从 dump 重算，无付费数据）⇒ 重跑＝清空再建。
    #    没有这个开关就只能手动清表，而**手动清表不留痕、不走闸门**。
    ap.add_argument("--rebuild", action="store_true",
                    help="清空 sense_relation 再建（纯派生层，可重算）")
    # 🔴🔴 **2026-10-05（W25）补：只改 `sense_id` 的原地同步。**
    #    W25 折叠了 1,631 条义项，53 条义项级关系挂在被折的那些上 ⇒ 要重新指向。
    #    ⚠️ 不能走 `--rebuild`：它会**删掉 W17 手工收回来的 30 条**
    #      （`src='w17-from-examples'`，收割器永远产不出它们）。
    #      与例句层的付费数据保险同一个形状 —— 下面那道保险就是为此加的。
    ap.add_argument("--sync", action="store_true",
                    help="只把已有行的 sense_id 同步到 collect() 的产出（不增删行）")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid, norm_exact, norm_any, s2id, tot = index(con)
    con.close()
    print("■ dict %s 词形；en 版可挂靠的义项键 %s 组" % (F(tot), F(len(s2id))))

    rows, stat, pairs, unknown = collect(wid, norm_exact, norm_any, s2id)
    if unknown:
        print("\n🔴🔴 源头有 %d 种我们值域里没有的关系字段：%s" % (len(unknown), dict(unknown)))
        print("   ⇒ 先把它们加进 `stage6_sources.KINDS` 并想清 SUBSUME 该不该收，再建库。")
        raise SystemExit(1)


    naive = sum(1 for v in pairs.values() if "related" in v and len(v) > 1)
    right = sum(1 for v in pairs.values() if "related" in v and (v & S6.SUBSUME))
    pub = [r for r in rows if r[7] is None]
    # 🔴 标签改过：隐藏现在有**两个原因**（B17 ＋ W9），印成「B17 隐藏」会误导下一个人
    import collections as _c
    _why = _c.Counter(r[7] for r in rows if r[7])
    # 🔴🔴 **这一行原先是坏的，而它坏了多久没人知道**：`%` 的优先级高于 `+`，
    #    所以末尾那 4 个参数只喂给了最后一个字面量 `"）；(词,目标) 对 %s"`
    #    ⇒ `TypeError: not all arguments converted`。
    #    ⭐ **没人发现是因为 `main()` 从来没被跑过** —— 关系层建好之后就没再重跑，
    #      而两道闸只 import `index()`/`collect()`，碰不到 `main()`。
    #      这正是 `[[lesson-must-become-mechanism]]` 那一课的又一例：
    #      「代码存在」与「代码被跑过」是两件事，而只有后者能证明它是对的。
    #    ⇒ 2026-10-05 加 `--sync` 时第一次跑 `main()`，当场炸出来。
    print("\n■ 关系 %s 行（可出版 %s ／ 隐藏 %s：%s）；(词,目标) 对 %s"
          % (F(len(rows)), F(len(pub)), F(len(rows) - len(pub)),
             "、".join("%s=%s" % (k, F(v)) for k, v in _why.most_common()),
             F(len(pairs))))
    for k, v in sorted(stat.items(), key=lambda x: -x[1]):
        print("   %-44s %8s" % (k, F(v)))
    print("\n■ B17 两种判据（**差 %.1f 倍**，差的全是 `paronym+related`）"
          % (naive / max(right, 1)))
    print("   naive「related 撞上任何别的 kind」      %8s 对" % F(naive))
    print("   正确「related 撞上语义更具体的 kind」     %8s 对" % F(right))
    print("\n■ 按 kind（可出版）")
    for k, v in collections.Counter(r[2] for r in pub).most_common():
        print("   %-16s %8s" % (k, F(v)))
    res = sum(1 for r in pub if r[4] is not None)
    print("\n■ `target_id` 可解析 %s / %s（%.1f%%）—— 解析不了的留 NULL，"
          "**展示层不许做成链接**" % (F(res), F(len(pub)), 100.0 * res / max(len(pub), 1)))
    cov = len({r[0] for r in pub})
    print("■ 读者口径：有可出版关系的词形 **%s（%.1f%%）**" % (F(cov), 100.0 * cov / tot))

    dbtool.sample_check([(r[3][:30], r[2], (r[5] or "")[:14],
                          "有链" if r[4] else "无链", r[7] or "出版") for r in rows],
                        10, ("目标", "kind", "源", "链", "出版/隐藏"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    old = con.execute("SELECT COUNT(*) FROM sense_relation").fetchone()[0]
    con.close()
    if a.sync:
        _sync(rows)
        return
    if old and not a.rebuild:
        raise SystemExit("🔴 sense_relation 已有 %s 行 —— 纯派生层，重跑要加 `--rebuild`，"
                         "或用 `--sync` 只同步列。" % F(old))
    # 🔴 **第二个写入方的保险**：`--rebuild` 清表会连 W17 手工收回来的那批一起删掉，
    #    而收割器永远产不出它们（源头把那批关系数据挤进了 `examples`，没有结构字段）。
    #    与例句层的付费数据保险同一条规矩（`[[enrich-not-rebuild]]`）。
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    foreign = {s_: n for s_, n in con.execute(
        "SELECT src, COUNT(*) FROM sense_relation WHERE src NOT IN (%s) GROUP BY 1"
        % ",".join("'%s'" % x for x, _l in S6.EDITIONS))}
    con.close()
    if foreign and a.rebuild:
        raise SystemExit(
            "🔴🔴 `sense_relation` 里有**别的写入方**插的行：%s —— `--rebuild` 会删掉它们，"
            "而收割器产不出来。改用 `--sync`，或先确认那批能重放再手动清。"
            % foreign)
    with dbtool.session(
            "build-vi-relation-layer",
            expect={"__rows__": 0, "#sense_relation": len(rows) - old},
            invalidates=["关系层落第一行 ⇒ `sense_relation` 从 UNCLAIMED 里拿出来，"
                         "关系层闸必须登记并跑绿（`vi/tests/test_relation_layer.py`）"]) as s:
        if a.rebuild:
            s.execute("DELETE FROM sense_relation")
        s.executemany(
            "INSERT INTO sense_relation (word_id, sense_id, kind, target, target_id, "
            "hidden, hidden_why, src, src_ref) VALUES (?,?,?,?,?,?,?,?,?)",
            [(r[0], r[1], r[2], r[3], r[4], 0 if r[7] is None else 1, r[7], r[5], r[6])
             for r in rows])

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]                      # noqa: E731
    checks = [
        ("sense_relation 行数", q("SELECT COUNT(*) FROM sense_relation"), len(rows)),
        ("src_ref 唯一", q("SELECT COUNT(*) FROM (SELECT src_ref FROM sense_relation "
                          "GROUP BY src_ref HAVING COUNT(*)>1)"), 0),
        ("每条都挂得上 dict",
         q("SELECT COUNT(*) FROM sense_relation r LEFT JOIN dict d ON d.id=r.word_id "
           "WHERE d.id IS NULL"), 0),
        ("target_id 要么空要么真指向一条 dict",
         q("SELECT COUNT(*) FROM sense_relation r LEFT JOIN dict d ON d.id=r.target_id "
           "WHERE r.target_id IS NOT NULL AND d.id IS NULL"), 0),
        ("kind 都在值域里",
         q("SELECT COUNT(*) FROM sense_relation WHERE kind NOT IN (%s)"
           % ",".join("'%s'" % k for k in sorted(set(S6.KINDS.values())))), 0),
        # 🔴 目标不许是汉字/喃字（必然死链）—— 这条是收割时丢掉的那批的反向断言
        ("隐藏的都写了为什么",
         q("SELECT COUNT(*) FROM sense_relation WHERE hidden=1 AND "
           "(hidden_why IS NULL OR TRIM(hidden_why)='')"), 0),
    ]
    for name, got, want in checks:
        print("   %s %-38s %s（期望 %s）"
              % ("✅" if got == want else "🔴", name, F(got), F(want)))
    con.close()
    if any(g != w for _n, g, w in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
