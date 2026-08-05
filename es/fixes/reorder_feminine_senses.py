#!/usr/bin/env python3
"""把补入的阴性义项挪到**正确位置**。2026-08-04。

═══ 昨天只做完了一半 ═══
`pipeline/fill_feminine_senses.py`（2026-08-03）补回了被 `build.py` 整族丢掉的
`female equivalent of X` 义项，内容补对了 4,479 行 —— 但 `append_plan()` 一律
**追加到末尾**，位置一个没动。而那批缺陷的定义恰恰是「**错答案排在第一位**」：

    novia   用户先看到「甜面包卷」，我们补的「女朋友」排第 2
    gata    用户先看到「劫车」，    我们补的「雌猫」  排第 2
    rubia   用户先看到「旅行轿车」， 我们补的「金发女子」排第 2

划词弹窗只露头一两行 ⇒ 补了等于没补。本脚本只动顺序，不动内容。

═══ 🔴 「一律提前」是错的 ═══
第一直觉是把补入的义项挪到第一位。回 kaikki 核对后否掉了：

    muñeca  kaikki: [0] wrist（留） [1] female equivalent of muñeco（丢）
            → 「手腕」本来就该排第一，「小妞」挪到前面是**制造新缺陷**
    pata    七个义项全在第一个 noun 块且都保留，female equivalent 在**第二个
            noun 块**  → 「雌鸭」排末尾本来就是对的，这行根本不用动

⇒ 判据取 **kaikki 的原始位置**，不是我的直觉：
   **插入位置 k = kaikki 里排在「被丢义项」之前、且我们保留下来了的义项数。**
   （跨 pos 块按文件出现顺序拼接计数。novia 的 fem 义项在 noun[0..2]，其前无保留
     义项 → k=0 → 提到最前；muñeca 的在 noun[1]，其前 wrist 保留 → k=1。）

═══ 两类行，判据不同 ═══
① **指针行 4,285 行**（`amiga`／`objetora de conciencia` 这类 is_lemma=0）：
   原有内容全是 `amigo 的 阴性` 这种**元描述指针**，不是释义。真释义一律排指针前面
   （k=0），不必回 kaikki —— 指针没有"位置"可言。
   ⚠️ 判别用的 LABEL 正则要放宽成 `^.+ 的 \\S+$`：原脚本的 `^\\S+ 的` 在多词词组上
      漏判 59 条（`objetor de conciencia 的 阴性` 里基词带空格）。
② **真义项行 194 行**（`novia`／`muñeca` 这类 is_lemma=1、带英文 `definition`）：
   按上面的 k 回源定位。

═══ 闸门 ═══
纯重排 ⇒ 所有列的非空计数都不变 ⇒ `expect={}`（未声明的列变了就报错），
这道闸正好用来证明「我只换了顺序、没吃掉也没造出内容」。
另加两条本脚本自己的校验：重排前后**多重集必须完全相等**（逐行 assert），
以及 `align_check()` 三列行数对齐。
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
import dbtool                                                    # noqa: E402
import paths                                                     # noqa: E402

DROP_TAGS = {"form-of", "alt-of", "combined-form"}                # 同 build.py
BATCH_RE = re.compile(r"^fem-")
# 放宽：基词可以带空格（多词词组）
LABEL = re.compile(r"^.+ 的 \S+$")
CACHE = paths.WORK / "runs" / "fem_kaikki_order.json"

# ═══ 逐条人工复核（94 行非指针改动全看过）后的排除项 ═══
# 判据只改到第三轮就停手（纪律：残差当上界报，别为一条再发明通用规则）。
EXCLUDE = {
    # kaikki 的 chica 有两个块：noun[0] `female equivalent of chico: girl`（丢）
    # 和 adj[0] `feminine singular of chico`（丢）。补入的中文「小的」显然是**后者**，
    # 而前者我们本来就有（noun[1] gal/chick = 「姑娘，小妞」）。拿 noun 那条的位置
    # 去摆 adj 的内容 → 「小的」会顶掉「姑娘，小妞」成为首义，是**制造新缺陷**。
    "chica": "补入的是 adj 义项，位置基准却取自 noun 的 fem 义项",
}


# ═══ 取数 ═══

def affected():
    """→ [(id, word, definition, translation, meta_list, added_idx, is_lemma)]"""
    conn = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows = conn.execute(
        "SELECT id, word, definition, translation, meta, is_lemma FROM dict "
        "WHERE meta LIKE '%fem-%'").fetchall()
    conn.close()
    out, skipped = [], collections.Counter()
    for rid, w, dfn, tr, mj, il in rows:
        try:
            meta = json.loads(mj)
        except Exception:
            skipped["meta 不是合法 JSON"] += 1
            continue
        idx = [i for i, x in enumerate(meta)
               if isinstance(x, dict) and BATCH_RE.match(str(x.get("batch", "")))]
        if not idx:
            continue
        tr_lines = (tr or "").split("\n")
        if len(meta) != len(tr_lines):
            skipped["改前 meta/tr 就没对齐"] += 1
            continue
        # 补入的必须是**连续的末尾段**，否则说明有别的批次插过队，本脚本的假设不成立
        if idx != list(range(len(meta) - len(idx), len(meta))):
            skipped["补入项不在末尾"] += 1
            continue
        out.append({"id": rid, "word": w, "dfn": dfn or "", "tr": tr or "",
                    "meta": meta, "added": idx, "is_lemma": il})
    return out, skipped


WORD_RE = re.compile(r'"word":\s*"([^"]+)"')


def kaikki_order(words):
    """→ {词: {"k": k, "kept": 保留义项总数}}。

    k = 被丢的 female-equivalent 义项之前、保留下来的义项数；跨 pos 块按文件出现
    顺序拼接计数。

    🔴 **不能用 `"equivalent of" in ln` 预筛**。同一个词的每个 pos 块是**独立的一行
    JSON**，`pata` 的七个真义项在第一个 noun 块（那行不含 "equivalent of"，会被整行
    跳过），fem 义项在第二个 noun 块 —— 预筛过一次的结果是保留数少算成 0，于是
    「雌鸭」被挪到首位、把「（动物的）爪，足，腿」顶掉。这个错被 sample_check 的
    改前/改后对照当场逮住。改成先用正则抠 word 再决定要不要 json.loads。
    """
    if CACHE.exists():
        return json.load(open(CACHE, encoding="utf-8"))
    want = set(words)
    kept = collections.Counter()      # 词 → 目前累计的保留义项数
    first = {}                        # 词 → 第一个 fem 义项处的 k
    for ln in open(paths.KK, encoding="utf-8"):
        # 🔴 必须 findall 取**全部** "word"，不能 search 取第一个。kaikki 每行里
        #    `forms[]` 会先出现别的 "word"（novia 的 noun 块开头是音标形
        #    `"word": "nobya"`），只看第一个会把整块判成"不是我们要的词"跳过 ——
        #    novia 的 fem 义项全在那个 noun 块里，于是头号案例被静默漏掉。
        if not (set(WORD_RE.findall(ln)) & want):
            continue
        try:
            e = json.loads(ln)
        except Exception:
            continue
        if e.get("lang_code") != "es" or e.get("word") not in want:
            continue
        w = e["word"]
        for s in e.get("senses", []):
            g = " ".join(s.get("glosses") or [])
            dropped = bool(DROP_TAGS & set(s.get("tags") or []))
            if dropped and "equivalent of" in g:
                first.setdefault(w, kept[w])
            elif not dropped:
                kept[w] += 1
    out = {w: {"k": k, "kept": kept[w]} for w, k in first.items()}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    return out


# ═══ 定位 ═══

def target_pos(r, kk):
    """→ (插入位置, 判据名)。位置是**在原有义项列表中的下标**。

    🔴 我们的义项集合不总是等于 kaikki 的保留集合 —— 西语版收词时并进来的义项也在
    里面（`muñeca` 多一条「洋娃娃」，`pata` 多一条「系绳，牵绳」）。数不齐时按下标
    映射就不可靠，此时只认一种情形：
      · **k==0**（fem 义项在 kaikki 里就是第一条）→ 提到首位是稳的，不依赖后面怎么错位；
      · k>0 且数不齐 → **定不了位，不动**，计入残差如实报，不猜。
    """
    n_old = len(r["meta"]) - len(r["added"])
    old_tr = r["tr"].split("\n")[:n_old]
    if all(LABEL.match(x.strip()) for x in old_tr if x.strip()):
        return 0, "指针行"
    if r["word"] in EXCLUDE:
        return None, "人工复核排除 · " + EXCLUDE[r["word"]]
    e = kk.get(r["word"])
    if e is None:
        return None, "kaikki 查不到 fem 义项"
    k = e["k"]
    if e["kept"] == n_old:
        return k, "kaikki 位置·义项数对齐"
    # 🔴 兜底还要求 kaikki **至少保留过一条**。`palestina` 两条义项被全丢、kept=0，
    #    我们那四条（巴勒斯坦／帕莱斯蒂纳…）全部来自西语版 —— kaikki 压根没表态过
    #    fem 义项与它们孰先孰后，此时提到首位是拿"查不到"当"排第一"，纯属我猜。
    if k == 0 and e["kept"] > 0:
        return 0, "kaikki 位置·fem 居首"
    if e["kept"] == 0:
        return None, "kaikki 一条义项都没保留，定不了相对位置"
    return None, "义项数与 kaikki 不齐（我们 %d/kaikki %d）且 fem 不居首" % (
        n_old, e["kept"])


def permute(r, pos):
    """把末尾的补入段整体挪到 pos。→ (new_dfn, new_tr, new_meta_json) 或 None。"""
    n_add = len(r["added"])
    n_old = len(r["meta"]) - n_add

    def move(seq):
        old, add = seq[:n_old], seq[n_old:]
        return old[:pos] + add + old[pos:]

    tr_lines = r["tr"].split("\n")
    new_tr = move(tr_lines)
    new_meta = move(r["meta"])
    dfn_lines = r["dfn"].split("\n") if r["dfn"] else []
    new_dfn = move(dfn_lines) if dfn_lines else []

    # 多重集不变 —— 只换位置，不吃内容、不造内容
    assert sorted(new_tr) == sorted(tr_lines), r["word"]
    assert len(new_meta) == len(r["meta"]), r["word"]
    if dfn_lines:
        assert sorted(new_dfn) == sorted(dfn_lines), r["word"]
        assert len(new_dfn) == len(new_tr), r["word"]
    return ("\n".join(new_dfn) if dfn_lines else r["dfn"],
            "\n".join(new_tr),
            json.dumps(new_meta, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    rows, skipped = affected()
    print("■ 带 fem 批次标记的行：%d" % len(rows))
    if skipped:
        print("   跳过：%s" % dict(skipped))

    kk = kaikki_order([r["word"] for r in rows])
    print("■ kaikki 里定到位置的词：%d" % len(kk))

    plan, samples, stat = [], [], collections.Counter()
    for r in rows:
        pos, why = target_pos(r, kk)
        if pos is None:
            stat["定不了位，不动 · " + why] += 1
            continue
        n_old = len(r["meta"]) - len(r["added"])
        if pos == n_old:
            stat["本来就在对的位置（末尾）· " + why] += 1
            continue
        out = permute(r, pos)
        if out is None:
            stat["重排失败"] += 1
            continue
        stat["挪 · %s → 第 %d 位" % (why, pos + 1)] += 1
        plan.append(out + (r["id"],))
        if len(samples) < 18 and r["is_lemma"]:
            samples.append((r["word"],
                            r["tr"].split("\n")[0][:20],
                            out[1].split("\n")[0][:20]))
    print("■ %s" % json.dumps(dict(stat), ensure_ascii=False, indent=2))
    print("■ 待改 %d 行" % len(plan))
    dbtool.sample_check(samples, 18, ("词", "改前首义", "改后首义"))

    if not a.apply:
        print("\n(预览。确认后 --apply)")
        return
    # 纯重排：任何列的非空计数都不该变
    with dbtool.session("fem-reorder", expect={}) as s:
        s.executemany("UPDATE dict SET definition=?, translation=?, meta=? "
                      "WHERE id=?", plan)
    dbtool.align_check()


if __name__ == "__main__":
    main()
