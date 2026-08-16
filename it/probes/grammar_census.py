#!/usr/bin/env python3
"""语法层取数：源头到底给了什么。2026-08-13，Q1。

═══ 为什么要先量 ═══
库里现在的 `dict.aux` / `dict.transitivity` 是七月流水线写的，**词形级**一份值：
    aux:          avere 40,614 / essere 6,228 / both 2,160
    transitivity: t 5,555 / i 1,726 / ti 1,690      ← 只有 8,971 个词形有值
而源头 kaikki 的两个信号根本不在同一层：
    · 及物性是 **义项级** 的（`senses[].tags` 里的 transitive/intransitive/…）
    · 助动词是 **词条级** 的（`forms[]` 里 tags 含 "auxiliary" 的那一行）
七月把两者都压平到词形上了，所以 `both` 这 2,160 个词只能显示"两者皆可"，
用户看不出哪个义项配哪个助动词 —— 这正是 v3 分层要解决的。

⚠️ 我第一次量 aux 时搜的是 `head_templates` 里的 `"aux"` 参数、正则写的 `avere`，
   而 dump 里写的是重音形式 `avére`，量出来偏小。真值在 `forms[]`。
   ⇒ 这个脚本一律**先打印原始样本**再统计，不许凭印象写判据。

用法（在 it/ 目录下）：
    python3 probes/grammar_census.py            # 全量统计
    python3 probes/grammar_census.py --sample   # 只打印原始样本，看清结构
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths   # noqa: E402

# 及物性相关的义项标签（源头原词，不改写）
TRANS_TAGS = {"transitive", "intransitive", "reflexive", "pronominal",
              "impersonal", "ditransitive", "ambitransitive", "copulative"}


def iter_dump():
    with open(paths.KK, encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def sample(n=6):
    """先看清结构，再谈统计。"""
    shown_aux = shown_trans = 0
    for e in iter_dump():
        if e.get("pos") != "verb":
            continue
        auxf = [f for f in (e.get("forms") or []) if "auxiliary" in (f.get("tags") or [])]
        if auxf and shown_aux < n:
            shown_aux += 1
            print("── 助动词样本 %d: %s (etym %s)" % (shown_aux, e.get("word"), e.get("etymology_number")))
            for f in auxf:
                print("     forms[]: %s" % json.dumps(f, ensure_ascii=False))
        for s in (e.get("senses") or []):
            t = set(s.get("tags") or []) & TRANS_TAGS
            if t and shown_trans < n:
                shown_trans += 1
                print("── 及物性样本 %d: %s → tags=%s" % (shown_trans, e.get("word"), sorted(s.get("tags") or [])))
                print("     gloss: %s" % ((s.get("glosses") or [""])[0])[:70])
        if shown_aux >= n and shown_trans >= n:
            return


def census():
    verb_entries = 0
    aux_entries = 0
    aux_values = Counter()          # 每个词条的助动词取值组合
    aux_form_tags = Counter()       # auxiliary 那一行还带了什么别的 tag（条件标签）
    multi_aux = 0                   # 一个词条给了不止一个助动词
    trans_senses = 0
    trans_combo = Counter()         # 义项上的及物性标签组合
    verbs_with_trans = set()
    dual = []                       # 双助动词词条：留着看条件标签

    for e in iter_dump():
        pos = e.get("pos")
        senses = e.get("senses") or []
        for s in senses:
            t = tuple(sorted(set(s.get("tags") or []) & TRANS_TAGS))
            if t:
                trans_senses += 1
                trans_combo[t] += 1
                verbs_with_trans.add((e.get("word"), pos))
        if pos != "verb":
            continue
        verb_entries += 1
        auxf = [f for f in (e.get("forms") or []) if "auxiliary" in (f.get("tags") or [])]
        if not auxf:
            continue
        aux_entries += 1
        vals = sorted({(f.get("form") or "").strip() for f in auxf})
        aux_values[tuple(vals)] += 1
        for f in auxf:
            extra = tuple(sorted(set(f.get("tags") or []) - {"auxiliary"}))
            aux_form_tags[extra] += 1
        if len(vals) > 1:
            multi_aux += 1
            if len(dual) < 400:
                dual.append({
                    "word": e.get("word"), "etym": e.get("etymology_number"),
                    "forms": [{"form": f.get("form"), "tags": f.get("tags")} for f in auxf],
                    "sense_tags": [sorted(set(s.get("tags") or []) & TRANS_TAGS)
                                   for s in senses],
                })

    print("\n══ 助动词（词条级，来自 forms[] 里 tags 含 auxiliary 的行）")
    print("  动词词条总数            %8d" % verb_entries)
    print("  带助动词的词条          %8d  (%.1f%%)" % (aux_entries, 100.0 * aux_entries / max(verb_entries, 1)))
    print("  其中给了 >1 个助动词    %8d" % multi_aux)
    print("  取值组合 top10:")
    for k, v in aux_values.most_common(10):
        print("     %-28s %6d" % ("+".join(k), v))
    print("  auxiliary 行上的**其它标签**（这就是「什么条件下用哪个」的凭据）top12:")
    for k, v in aux_form_tags.most_common(12):
        print("     %-38s %6d" % ("+".join(k) if k else "(无)", v))

    print("\n══ 及物性（义项级，来自 senses[].tags）")
    print("  带及物性标签的义项      %8d" % trans_senses)
    print("  涉及词条（词形+词性）   %8d" % len(verbs_with_trans))
    print("  标签组合 top12:")
    for k, v in trans_combo.most_common(12):
        print("     %-38s %6d" % ("+".join(k), v))

    out = paths.WORK / "probe" / "dual_aux.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dual, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n  双助动词词条样本已存 %s（%d 条）" % (out, len(dual)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    a = ap.parse_args()
    if a.sample:
        sample()
    else:
        census()
    return 0


if __name__ == "__main__":
    sys.exit(main())
