#!/usr/bin/env python3
"""阶段 2：变形层（活用）。2026-09-15。零模型调用。

═══ 🔴 三处和前六门不一样，每处都有实测 ═══
① **源是日语版，不是英文版。**英文版只给 975/13,921 个动词（7.0%）活用表、中位 2 个形；
   日语版 19,564 词 / 中位 19 个形。照「英文版是结构基准」的惯性走，
   会得出「日语动词几乎不活用」这个荒谬结论（`[[multi-edition-methodology]]`：
   英文版是**结构**基准不是**内容**上限）。
② **入口判据不是「forms 有 tags 就收」。**59 万行 forms 里只有 45.3% 是真形态：
       真形态      267,312  45.3%
       罗马字重复   126,849  21.5%   ← 同一个格位的第三份拷贝
       canonical    91,353  15.5%   ← 就是词头本身
       异表记        62,913  10.7%   ← 旧字体/假名写法，**归关系层不归这里**
   照搬会把 20.3 万真活用虚报成 35.7 万。
③ **名词零贡献。**日语名词没有格、没有数、没有性 —— `noun` 的 16.7 万行 forms
   里真形态只有 201 行（0.1%），全是异表记。
   对照 de：名词的属格与复数是变形层的大头。**照搬 de 的判据会收进 16.7 万行异表记。**

═══ 中文语法说明 ═══
`infl_compose.compose()` 确定性组合，**全量 280,340 行只有 1 行拼不出**（已补 `-tari`）。
顺序就是判据，那个模块自带变异验证。

跑（在仓库根）：
    python3 -u ja/pipeline/build_inflection_layer.py
    python3 -u ja/pipeline/build_inflection_layer.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import collections
import json
import re
import sqlite3

import dbtool
import paths
from pipeline.build import NOT_A_WORD, norm_ja
from pipeline.infl_compose import compose, has_error

MORPH = {"stem", "past", "negative", "formal", "informal", "conditional", "continuative",
         "imperative", "adverbial", "attributive", "terminative", "hypothetical",
         "volitional", "causative", "passive", "potential", "irrealis", "perfective",
         "imperfective", "polite", "realis", "perfect", "desiderative",
         "conjunctive", "contrastive", "-tari"}
JUNK_FORM = {"-", "—", "*", "", "…"}
# 🔴 **罗马字按内容挡，不按标签挡。**英文版有 86,237 行罗马字形**没打 `romanization` 标签**
#    （`尾籠` 的「敬体否定」给成 `birō de wa arimasen`），占收进来的 20.3%。
#    判据不是形式代理：**日语的活用形按定义写成假名或汉字**，纯拉丁串不是日语词形。
JA_SCRIPT = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")


def _assert_ja():
    assert paths.DB.name == "synapse-dict-ja.sqlite", "🔴 paths 不是 ja 的：%s" % paths.DB
    assert not hasattr(dbtool, "has_han"), "🔴 dbtool 不是 ja 的"


def scan():
    rows = []
    stat = collections.Counter()
    for path, src in ((paths.KK, "en-edition"), (paths.EDITION, "ja-edition")):
        for line in open(path, encoding="utf-8"):
            o = json.loads(line)
            pos = o.get("pos")
            if pos in NOT_A_WORD:
                continue
            base = (o.get("word") or "").strip()
            if not base:
                continue
            for i, f in enumerate(o.get("forms") or []):
                tg = set(f.get("tags") or [])
                stat["forms 总行"] += 1
                if "romanization" in tg:
                    stat["跳过·罗马字重复"] += 1
                    continue
                if "canonical" in tg:
                    stat["跳过·canonical（词头本身）"] += 1
                    continue
                if has_error(tg):
                    stat["跳过·源头抽取报错"] += 1
                    continue
                if not (tg & MORPH):
                    stat["跳过·异表记等（归关系层）"] += 1
                    continue
                fm = (f.get("form") or "").strip()
                if fm in JUNK_FORM or fm == base:
                    stat["跳过·空/占位/与词头同形"] += 1
                    continue
                if not JA_SCRIPT.search(fm):
                    stat["跳过·罗马字（按内容判，源头没打标签）"] += 1
                    continue
                zh = compose(tg)
                if not zh:
                    stat["跳过·拼不出中文说明"] += 1
                    continue
                rows.append((fm, base, pos, zh,
                             json.dumps(sorted(tg), ensure_ascii=False), src,
                             "%s:%s:%s#%d" % (src, base, pos, i)))
                stat["收·%s" % src] += 1
    return rows, stat


def main():
    _assert_ja()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    rows, stat = scan()
    for k, v in stat.most_common():
        print("   %-28s %9s" % (k, format(v, ",")))

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    con.close()
    forms = {r[0] for r in rows}
    new = sorted(forms - set(have))
    print("\n   不同变形词形 %s ｜已在 dict %s ｜**要新插** %s"
          % (format(len(forms), ","), format(len(forms) - len(new), ","), format(len(new), ",")))
    print("   ⇒ dict %s → %s" % (format(len(have), ","), format(len(have) + len(new), ",")))

    # 🔴 抽样反验：pt 那轮靠这一步挡下 283,136 条假词形（法语版把主语代词写进了变位表单元格）
    dbtool.sample_check([(r[0], r[1], r[3], r[5]) for r in rows[::max(1, len(rows) // 18)]],
                        14, ("变形", "原形", "中文说明", "来源"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    with dbtool.session("ja-inflection-layer", expect={
            "__rows__": len(new), "pos": 0, "#inflection": len(rows)}) as s:
        s.executemany("INSERT INTO dict (word, word_norm, is_lemma) VALUES (?,?,0)",
                      [(w, norm_ja(w)) for w in new])
        con2 = s.conn if hasattr(s, "conn") else None
        wid = {w: i for i, w in s.execute("SELECT id, word FROM dict")}
        s.executemany(
            "INSERT INTO inflection (word_id, kind, base, base_id, label_zh, tags, src, src_ref)"
            " VALUES (?,'inflection',?,?,?,?,?,?)",
            [(wid[fm], base, wid.get(base), zh, tags, src, ref)
             for fm, base, pos, zh, tags, src, ref in rows])


if __name__ == "__main__":
    main()
