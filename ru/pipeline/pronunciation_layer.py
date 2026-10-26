#!/usr/bin/env python3
"""阶段 4：**音标层**。ru，2026-10-23。

    python3 -u ru/pipeline/pronunciation_layer.py --dry      # 只统计
    python3 -u ru/pipeline/pronunciation_layer.py            # 写库
    python3 -u ru/pipeline/pronunciation_layer.py --rebuild  # 判据改了：清掉重算（本层无付费数据）

判据一条都不在本文件里写 —— `criteria` §⑨（拆格／归属／能不能印）。依据见 RU_PLAN §十一。

═══ 三件事，每一件都决定「这条读音属于谁」═══
① **`entry_id` 照抄来源**：源头每一行就是一个 entry，挂钩靠重算 `src_ref`（`criteria.SrcRef`，
   与重音层同一个函数、同一个扫源顺序 —— 阶段 2 §0 证明过双向差集为 0）。
   为什么要它：同形异重音词（`подать` ˈpodətʲ／pɐˈdatʲ）只挂 `word_id` 就分不清哪个读音对应哪个意思。
② **复数读音挂到主格复数那个词形上**（ru 版 `tags: plural` 3.7 万条），`entry_id` 留 NULL
   （它来自词元的 entry，不是复数词形自己的）。🔴 挂不上就**不收**，绝不挂在词元上。
③ **源头说是错的／不推荐的**：存，`hidden=1`，`hidden_why` 说清是哪一种。不印 ≠ 不存。

═══ ⚠️ 去重只去「同一个 entry、同一个源、同一个串」═══
不同 entry 给的同一个串**各留一行** —— 它们的 `entry_id` 不同，合并就把 ① 丢了。
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


def collect(conn, limit=None, verbose=True):
    wid = dict(conn.execute("SELECT word, id FROM dict"))
    eid = dict(conn.execute("SELECT src_ref, id FROM entry"))
    ref = criteria.SrcRef()
    rows, seen = [], set()
    st = {
        "kind": collections.Counter(), "kind_eg": collections.defaultdict(list),
        "by_src": collections.Counter(), "notation": collections.Counter(),
        "dialect": collections.Counter(), "hidden": collections.Counter(),
        "target": collections.Counter(), "tilde_dropped": 0, "dup": 0,
        "orphan_entry": 0, "orphan_word": 0,
    }

    def eg(k, x):
        if len(st["kind_eg"][k]) < 6:
            st["kind_eg"][k].append(x)

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
            sounds = [s for s in (e.get("sounds") or []) if "ipa" in s]
            if not sounds:
                continue
            entry_id = eid.get(sref)
            if entry_id is None:
                st["orphan_entry"] += 1
                continue
            # R13：7 个带重音符的词头已并进孪生行
            self_wid = wid.get(w) or wid.get(criteria.strip_stress(w))
            if self_wid is None:
                st["orphan_word"] += 1
                continue
            plural_wid = None
            for si, s in enumerate(sounds):
                tags = s.get("tags") or []
                raw_tags = s.get("raw_tags") or []
                kind, parts = criteria.pronunciation_parts(s.get("ipa"), tags, raw_tags, word=w)
                st["kind"][kind.split("·")[0] if kind.startswith("ok") else kind] += 1
                if not kind.startswith("ok"):
                    eg(kind, "%s → %s" % (w, (s.get("ipa") or "")[:50]))
                    continue
                if "~后丢弃" in kind:
                    st["tilde_dropped"] += int(kind.rsplit("丢弃", 1)[1].rstrip("条"))
                target = criteria.pronunciation_target(tags)
                if target is None:
                    st["kind"]["单复数同标·归属不明"] += 1
                    eg("单复数同标·归属不明", "%s → %s %s" % (w, s.get("ipa"), tags))
                    continue
                if target == "plural":
                    if plural_wid is None:
                        npl = criteria.nominative_plural(e)
                        plural_wid = (wid.get(npl) if npl else None) or False
                    if not plural_wid:
                        st["kind"]["复数读音·挂不上主格复数词形"] += 1
                        eg("复数读音·挂不上主格复数词形", "%s → %s" % (w, s.get("ipa")))
                        continue
                    w_id, e_id = plural_wid, None
                else:
                    w_id, e_id = self_wid, entry_id
                st["target"][target] += 1
                dialect, hidden, why = criteria.pronunciation_status(tags, raw_tags)
                # 🔴 `tags` 与 `raw_tags` **分开存**：闸要从这一列重算 dialect/hidden
                #    （`criteria.pronunciation_status` 对两边的判法不同），混成一个数组就重算不出来。
                tj = json.dumps({"tags": list(tags), "raw_tags": list(raw_tags)},
                                ensure_ascii=False) if (tags or raw_tags) else None
                for ip, notation, pno in parts:
                    key = (w_id, e_id, ip, src)
                    if key in seen:
                        st["dup"] += 1
                        continue
                    seen.add(key)
                    rows.append((w_id, e_id, ip, dialect, notation, tj, hidden, why,
                                 src, "%s#ipa.%d.%d" % (sref, si, pno)))
                    st["by_src"][src] += 1
                    st["notation"][notation] += 1
                    st["dialect"][dialect] += 1
                    st["hidden"][why or "印"] += 1
        if verbose:
            print("  · %-16s %9s 行  %5.1fs" % (src, format(n, ","), time.time() - t0),
                  file=sys.stderr)
    return rows, st


def report(rows, st):
    print("\n■ 阶段 4 音标层（判据 %s）—— 会落库 %s 行" % (criteria.RULE_VER, format(len(rows), ",")))
    print("   按源 %s" % dict(st["by_src"].most_common()))
    print("   记音类型 %s" % dict(st["notation"]))
    print("   方言 %s" % dict(st["dialect"].most_common()))
    print("   能不能印 %s" % dict(st["hidden"]))
    print("   归属 %s" % dict(st["target"]))
    print("   `~` 后丢弃 %s 条 ／ 同 entry 同源同串去重 %s 条"
          % (format(st["tilde_dropped"], ","), format(st["dup"], ",")))
    print("   挂不上 entry %d ／ 挂不上 dict %d（两个都必须是 0）"
          % (st["orphan_entry"], st["orphan_word"]))
    print("\n   每一格的去向（完整，不截断）：")
    for k, v in st["kind"].most_common():
        print("      %9s  %s" % (format(v, ","), k))
        for x in st["kind_eg"].get(k, [])[:3]:
            print("                 %s" % x)


def write(rows, conn, rebuild=False):
    base = conn.execute("SELECT COUNT(*) FROM pronunciation").fetchone()[0] if rebuild else 0
    if base and not rebuild:
        raise SystemExit("🔴 `pronunciation` 已有 %s 行 —— 要重算就加 `--rebuild`" % format(base, ","))
    n = len(rows) - base
    with_entry = sum(1 for r in rows if r[1] is not None)
    with_tags = sum(1 for r in rows if r[5])
    with_why = sum(1 for r in rows if r[7])
    q = lambda s: conn.execute(s).fetchone()[0] if rebuild else 0   # noqa: E731
    exp = {
        "#pronunciation": n,
        "pronunciation.ipa": n,
        "pronunciation.entry_id": with_entry - q(
            "SELECT COUNT(*) FROM pronunciation WHERE entry_id IS NOT NULL"),
        "pronunciation.tags": with_tags - q(
            "SELECT COUNT(*) FROM pronunciation WHERE tags IS NOT NULL AND TRIM(tags)<>''"),
        "pronunciation.hidden_why": with_why - q(
            "SELECT COUNT(*) FROM pronunciation WHERE hidden_why IS NOT NULL AND TRIM(hidden_why)<>''"),
    }
    conn.close()
    with dbtool.session("pronunciation-layer" + ("-rebuild" if rebuild else ""),
                        expect=exp, invalidates=["pronunciation"]) as s:
        if rebuild:
            s.execute("DELETE FROM pronunciation")
        s.executemany(
            "INSERT INTO pronunciation(word_id,entry_id,ipa,dialect,notation,tags,hidden,"
            "hidden_why,src,src_ref) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("■ 扫七源（音标层）……", file=sys.stderr)
    rows, st = collect(conn, a.limit or None)
    report(rows, st)
    if st["orphan_entry"] or st["orphan_word"]:
        raise SystemExit("🔴 有读音挂不上 entry/dict —— `SrcRef` 重放与库不一致，不写库")
    if a.dry:
        print("\n(dry：没写库)")
        return 0
    if a.limit:
        raise SystemExit("🔴 `--limit` 只许和 `--dry` 一起用")
    conn.close()
    write(rows, sqlite3.connect(paths.DB), rebuild=a.rebuild)
    out = paths.WORK / "stage4_pronunciation_stats.json"
    out.write_text(json.dumps({
        "rows": len(rows), "by_src": dict(st["by_src"]), "kind": dict(st["kind"]),
        "notation": dict(st["notation"]), "dialect": dict(st["dialect"]),
        "hidden": dict(st["hidden"]), "target": dict(st["target"]),
        "tilde_dropped": st["tilde_dropped"], "dup": st["dup"],
        "rule_ver": criteria.RULE_VER,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n■ 统计已存档 → %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
