#!/usr/bin/env python3
"""建 `pronunciation` 表：把读音的多变体从「一列一个」变成「一变体一行」。2026-08-07。

见 `docs/SCHEMA.md` §2.2。`dict.phonetic` 一个词只存一条，而源头给的远不止一条。

═══ 先把「变体」这个词说清楚（三种，性质完全不同）═══
实测 kaikki 西语切片 165,193 个有音标的词头、446,130 条变体，分三类：

  ① **记法差**（音位式 / 严式）：`/ˈɡɾatis/` 与 `[ˈɡɾa.t̪is]` 是**同一个读音**的两种写法。
     判据在源头里明摆着 —— **定界符**（`kaikki_util.notation_of`），不必从附标猜。
     🔴 先前把它们当成两个读音，「多变体」的规模被虚报成 98.8%。
  ② **地区差**（半岛 θ / 拉美 s）：`abˈduθe` 与 `abˈduse`。这是真差异，但成规律。
  ③ **真·多读音**：`pie` 的 /ˈpje/(脚) 与 /piˈe/(字母读法)、`y` 的 5 种。
     把 ①② 都归一之后只剩 **9,813 词（5.9%）**。
     ⚠️ `docs/SCHEMA.md` 原记 33,527 / 23.7%，那个数把 ①② 也算进去了，虚高。

═══ 🔴 顺带证伪的一条：`phoneticLatam` 的规则派生是错的 ═══
展示层至今用 `θ→s` 从半岛音派生拉美音。实测含 θ 的 29,134 个词头里：

    源头给了 seseo 形且与规则派生一致   28,488
    🔴 源头给了，但与规则派生**不一致**    630
    源头只给半岛形，只能派生               16

那 630 条错得有规律 —— `sc` 在拉美是单个 /s/、词尾 `-d` 在半岛读 /θ/ 而拉美读 /d/：

    irascible   半岛 iɾasˈθible   规则 iɾasˈsible ❌   源头 iɾaˈsible ✅
    visceral    半岛 bisθeˈɾal    规则 bisseˈɾal  ❌   源头 biseˈɾal  ✅
    quetzal     半岛 ketˈθal      规则 ketˈsal    ❌   源头 keˈtsal   ✅
    Madrid      半岛 maˈdɾiθ      规则 maˈdɾis    ❌   源头 maˈdɾid   ✅

⇒ 有权威源就用权威源，没有才派生并标 `src='rule'`。

═══ 结构 ═══
    pronunciation(id, word_id, ipa, notation, region, tags, is_primary, src, src_ref)

  · `ipa` 裸存，不带 `/../` 或 `[..]`（沿用既有约定，展示层加）
  · `notation` phonemic | narrow —— **存不存与展不展示是两个独立开关**
  · `region` es-ES（含 θ）/ es-419（seseo）/ null（两地相同或判不出）
  · `is_primary` 每个词每个 region 各选一条作默认展示 = 音位式里的第一条
  · `src_ref` 回源坐标 `kk:<word>:<pos>#<sounds 下标>`。
    ⚠️ **必须带 pos**：同一个词形在 dump 里有多个词性条目（`gratis` 既是 adj 又是 adv），
    各自的 sounds 下标都从 0 起 —— 不带 pos 就有 5.3 万条坐标撞车。

═══ 三道闸 ═══
① 可逆性回核：与 dump **双向**集合比对（全量，非抽样）——
   「dump 有的库里都有」＋「库里有的 dump 里都有」，后者防止凭空多出音标
② 不变量断言：主键无重、无孤儿、每个词至少一条 primary
③ 抽样：本步骤是确定性转换

用法（在仓库根）：
    python3 -m es.pipeline.build_pronunciation_layer
    python3 -m es.pipeline.build_pronunciation_layer --apply
"""
import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import dbtool           # noqa: E402
import kaikki_util as K  # noqa: E402
import paths            # noqa: E402

TABLE = "pronunciation"
DDL = """CREATE TABLE pronunciation (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  word_id    INTEGER NOT NULL,      -- → dict.id
  ipa        TEXT NOT NULL,         -- 裸存，不带定界符
  notation   TEXT NOT NULL,         -- phonemic | narrow
  region     TEXT,                  -- es-ES / es-419；null = 两地相同或判不出
  tags       TEXT,                  -- 源头 tags/raw_tags 的 JSON 数组
  is_primary INTEGER NOT NULL DEFAULT 0,
  src        TEXT NOT NULL,         -- en-edition / rule
  src_ref    TEXT NOT NULL,         -- kk:<word>:<pos>#<sounds 下标>
  UNIQUE(word_id, ipa, notation)
)"""
IDX = ["CREATE INDEX idx_pron_word ON pronunciation(word_id)",
       "CREATE INDEX idx_pron_region ON pronunciation(region, notation)"]


def region_of(ipa: str) -> str | None:
    """θ 存在 ⇒ 半岛（distinción）；同一个词里另有无 θ 的对应形 ⇒ 那条是拉美。

    ⚠️ 只有**成对出现**时才标地区。单独一条无 θ 的音标不能推成拉美 ——
    绝大多数西语词根本不含 c/z，两地读法完全相同，标上 `es-419` 是无中生有。
    这个判断需要看整个词的变体集合，故由调用方 `classify()` 做，本函数只判有无 θ。
    """
    return "es-ES" if "θ" in ipa else None


def classify(variants):
    """→ [(ipa, notation, region, tags)]。region 只在 θ/无θ 成对时才填。"""
    has_th = any("θ" in v.ipa for v in variants)
    out = []
    for v in variants:
        if not has_th:
            reg = None                       # 全词无 θ ⇒ 两地同音，不标地区
        elif "θ" in v.ipa:
            reg = "es-ES"
        else:
            reg = "es-419"
        out.append((v.ipa, v.notation, reg, list(v.tags)))
    return out


def collect(con):
    dictid = {w: i for w, i in con.execute("SELECT word, id FROM dict")}
    rows, stat = [], collections.Counter()
    for line in open(paths.KK, encoding="utf-8"):
        e = json.loads(line)
        if e.get("lang_code") != "es":
            continue
        w = (e.get("word") or "").strip()
        did = dictid.get(w)
        if did is None:
            stat["dump 有、库里没这个词形（跳过）"] += 1
            continue
        v = K.sounds_variants(e)
        if not v:
            continue
        cls = classify(v)
        # is_primary：每个 region 取**音位式的第一条**；
        # ⚠️ 该词一条音位式都没有时（只给了严式），退而取严式的第一条 ——
        #    否则这个词在展示层没有默认音标可显示。实测这种词有 1 个。
        primary = {}
        for i, (ipa, nota, reg, _t) in enumerate(cls):
            if nota == "phonemic" and reg not in primary:
                primary[reg] = i
        for i, (ipa, nota, reg, _t) in enumerate(cls):
            primary.setdefault(reg, i)
        for i, (ipa, nota, reg, tg) in enumerate(cls):
            rows.append((did, ipa, nota, reg,
                         json.dumps(tg, ensure_ascii=False) if tg else None,
                         1 if primary.get(reg) == i else 0,
                         "en-edition", f"kk:{w}:{e.get('pos') or '?'}#{i}"))
            stat[f"{nota} / {reg or '通用'}"] += 1
    return rows, stat


def verify(con) -> None:
    """闸① 与 dump 双向集合比对（全量，非抽样）。"""
    print("\n═══ 闸① 可逆性回核（全量，非抽样）═══")
    # ⚠️ 用**集合比对**而非按 src_ref 一一对应：同一词形的多个词性条目常给出
    #    完全相同的音标，落库时按 UNIQUE(word_id, ipa, notation) 有意去重了。
    #    要核的是「dump 里有的库里都有」「库里有的 dump 里都有」，不是逐坐标相等。
    have = collections.defaultdict(set)
    for w, ipa, nota in con.execute(
            "SELECT d.word, p.ipa, p.notation "
            "FROM pronunciation p JOIN dict d ON d.id = p.word_id"):
        have[w].add((ipa, nota))
    want = collections.defaultdict(set)
    for line in open(paths.KK, encoding="utf-8"):
        e = json.loads(line)
        if e.get("lang_code") != "es":
            continue
        w = (e.get("word") or "").strip()
        if w not in have:
            continue
        for v in K.sounds_variants(e):
            want[w].add((v.ipa, v.notation))
    miss = sum(len(want[w] - have[w]) for w in want)      # dump 有、库里没
    extra = sum(len(have[w] - want.get(w, set())) for w in have)   # 库里有、dump 没
    n = sum(len(v) for v in want.values())
    print(f"  回 dump 核对 {n:,} 条去重后的变体")
    print(f"    dump 有、库里没：{miss}")
    print(f"    库里有、dump 没：{extra}   ← 凭空多出来的音标")
    for w in list(want)[:3000]:
        if want[w] - have[w]:
            print(f"    例：{w}  缺 {sorted(want[w]-have[w])[:2]}")
            break
    assert miss == 0 and extra == 0
    print("  ✅ 闸① 通过：与 dump 双向一致，一条不多、一条不少")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    rows, stat = collect(con)
    n_word = len({r[0] for r in rows})
    con.close()
    print(f"待写 {len(rows):,} 条 / {n_word:,} 个词")
    for k, v in stat.most_common():
        print(f"  {k:<34}{v:>9,}")

    print("\n═══ 闸② 不变量断言 ═══")
    dup = collections.Counter((r[0], r[1], r[2]) for r in rows)
    bad = [k for k, v in dup.items() if v > 1]
    print(f"  (word_id, ipa, notation) 重复：{len(bad)}")
    # 同一词形在 dump 里有多个词性条目，常给出完全相同的音标 ⇒ 有意去重。
    # 在内存里去重并报数，别指望 UNIQUE 静默吞掉（那样报的行数就是假的）。
    seen, uniq = set(), []
    for r in rows:
        k = (r[0], r[1], r[2])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    print(f"  去重后 {len(uniq):,}（丢 {len(rows)-len(uniq):,} 条同词同音标同记法）")
    noprim = n_word - len({r[0] for r in uniq if r[5]})
    print(f"  没有任何 primary 的词：{noprim}")

    dbtool.sample_check(
        [(r[1][:22], r[2], r[3] or "通用", "★" if r[5] else "") for r in uniq[:12]],
        12, ("音标", "记法", "地区", "默认"))

    if not args.apply:
        print("\n未加 --apply，不写库。")
        return

    with dbtool.session("build-pronunciation-layer", expect={}) as s:
        s.execute(f"DROP TABLE IF EXISTS {TABLE}")
        s.execute(DDL)
        for i in IDX:
            s.execute(i)
        s.executemany(
            "INSERT INTO pronunciation (word_id,ipa,notation,region,tags,is_primary,src,src_ref)"
            " VALUES (?,?,?,?,?,?,?,?)", uniq)

    con = sqlite3.connect(f"file:{paths.DB}?mode=ro", uri=True)
    q = lambda x: con.execute(x).fetchone()[0]          # noqa: E731
    print(f"\n落库核对：pronunciation {q('SELECT COUNT(*) FROM pronunciation'):,} 条 / "
          f"{q('SELECT COUNT(DISTINCT word_id) FROM pronunciation'):,} 个词")
    print(f"  悬空 word_id {q('SELECT COUNT(*) FROM pronunciation WHERE word_id NOT IN (SELECT id FROM dict)')}")
    for r in con.execute("SELECT notation, COALESCE(region,'通用'), COUNT(*) "
                         "FROM pronunciation GROUP BY 1,2 ORDER BY 3 DESC"):
        print(f"    {r[0]:<10}{r[1]:<10}{r[2]:>9,}")
    verify(con)
    con.close()


if __name__ == "__main__":
    main()
