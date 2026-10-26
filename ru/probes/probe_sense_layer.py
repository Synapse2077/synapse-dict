#!/usr/bin/env python3
"""阶段 5 探针：**义项层的落点与要花钱的那个分母**。ru，2026-10-23。只读。

    python3 -u ru/probes/probe_sense_layer.py > data/work/ru/probe/probe_sense_layer.txt

要回答的五件事（每一件都决定收割器怎么写、或者钱花在哪）：
  §A 每源的义项/释义规模，以及 **`glosses` 是不是带着父义项**（en 版子义项的列表会重复父释义）
  §B 指针义项走哪几条路（`form_of`／`alt_of`／`form-of` 标签／实体级 ru-crit-9/10）
  §C 义项级标签的**完整值域**（`sense_tag` 的 bucket 要按它分；R11 的落点）
  §D zh 版白送的中文：`zh_gloss_kind` 三桶 ＋ R3 那批「纸质词典抄进来」的形状
  §E 🔴 **要花钱的分母**：几种翻译范围各自要翻多少条、多少字符 —— 报价前用户要比的就是这张表
  §F 三语都没有可出版释义的词元（＝空白页风险），按来源分
判据一律 `import criteria`；值域全打不截断。
"""
import collections
import gzip
import json
import random
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402
from pipeline.build import SRC                                  # noqa: E402

LANG = {"en-edition": "en", "ru-edition": "ru", "zh-edition-simp": "zh", "zh-edition-trad": "zh",
        "fr-edition": "fr", "vi-edition": "vi", "pl-edition": "pl"}
THREE = {"en", "ru", "zh"}
RND = random.Random(20261023)


def main():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    is_lemma = dict(con.execute("SELECT word, is_lemma FROM dict"))
    con.close()

    st = collections.defaultdict(collections.Counter)
    tagdom = collections.defaultdict(collections.Counter)
    rawdom = collections.defaultdict(collections.Counter)
    topdom = collections.defaultdict(collections.Counter)
    zh_kind = collections.Counter()
    zh_eg = collections.defaultdict(list)
    r3 = collections.Counter()
    r3_eg = collections.defaultdict(list)
    parent_eg = []
    # word → src → [published gloss text]（三语）
    pub = collections.defaultdict(lambda: collections.defaultdict(list))
    zh_real_w = set()
    for src, p in SRC:
        lang = LANG[src]
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                e = json.loads(line)
                ok, _s, _pos = criteria.entry_accept(e)
                if not ok:
                    continue
                w = e["word"]
                ent_form, ent_via = criteria.is_inflected_form(e)
                entity_ptr = ent_via in ("word.tags:form-of", "word.tags:participle+全部义项",
                                         "word.form_of")
                senses = e.get("senses") or []
                st[src]["entries"] += 1
                prev_g0 = None
                for s in senses:
                    gl = [g.strip() for g in (s.get("glosses") or []) if g and g.strip()]
                    st[src]["senses"] += 1
                    if not gl:
                        st[src]["senses·无释义"] += 1
                        continue
                    st[src]["senses·有释义"] += 1
                    if len(gl) > 1:
                        st[src]["glosses 列表长度>1"] += 1
                        if prev_g0 is not None and gl[0] == prev_g0:
                            st[src]["…且首元素＝上一义项的首元素（父释义重复）"] += 1
                            if src == "en-edition" and len(parent_eg) < 6:
                                parent_eg.append("%s：%s" % (w, " ⟫ ".join(gl)[:120]))
                    prev_g0 = gl[0]
                    for t in s.get("tags") or []:
                        tagdom[src][t] += 1
                    for t in s.get("raw_tags") or []:
                        rawdom[src][t] += 1
                    for t in s.get("topics") or []:
                        topdom[src][t] += 1
                    # 指针：走哪条路
                    if s.get("form_of"):
                        via = "sense.form_of"
                    elif s.get("alt_of"):
                        via = "sense.alt_of"
                    elif "form-of" in (s.get("tags") or []):
                        via = "sense.tags:form-of"
                    elif entity_ptr:
                        via = "实体级（%s）" % ent_via
                    else:
                        via = None
                    if via:
                        st[src]["指针·" + via] += 1
                        continue
                    text = gl[-1]           # 子义项的最后一个元素才是它自己的释义
                    st[src]["可出版义项"] += 1
                    st[src]["可出版字符"] += len(text)
                    if lang == "zh":
                        k = criteria.zh_gloss_kind(text)
                        zh_kind[(src, k)] += 1
                        if len(zh_eg[(src, k)]) < 400:
                            zh_eg[(src, k)].append("%s → %s" % (w, text.replace("\n", "⏎")[:90]))
                        if k == "real":
                            zh_real_w.add(w)
                        for lab, cond in (
                                ("多行", "\n" in text),
                                ("含西里尔（变位词尾/俄语夹注）", any("CYRILLIC" in criteria.ud.name(ch, "") for ch in text)),
                                ("〔〕〈〉标记", any(ch in text for ch in "〔〕〈〉")),
                                ("「见X」交叉引用", "见" in text or "見" in text),
                                ("圈码①", any("①" <= ch <= "⑳" for ch in text)),
                                ("问号残渣", "?" in text)):
                            if cond:
                                r3[(src, lab)] += 1
                                if len(r3_eg[(src, lab)]) < 5:
                                    r3_eg[(src, lab)].append("%s → %s" % (w, text.replace("\n", "⏎")[:90]))
                    if lang in THREE:
                        pub[w][src].append(text)

    print("■ 俄语阶段 5 探针：义项层  2026-10-23  判据 %s" % criteria.RULE_VER)
    print("\n§A 每源规模")
    for src, _p in SRC:
        print("   ── %s（%s）" % (src, LANG[src]))
        for k, v in st[src].items():
            print("      %-44s %10s" % (k, format(v, ",")))
    print("   en 版父释义重复样本：")
    for x in parent_eg:
        print("      %s" % x)

    print("\n§C 义项级标签 —— 完整值域（按源）")
    for src, _p in SRC:
        for lab, dom in (("tags", tagdom), ("raw_tags", rawdom), ("topics", topdom)):
            if dom[src]:
                d = dom[src]
                print("   %s %s（%d 种）：%s" % (src, lab, len(d), dict(d.most_common())))

    print("\n§D zh 版：`zh_gloss_kind` 三桶（可出版义项）")
    for k, v in sorted(zh_kind.items()):
        print("   %-26s %9s" % ("%s/%s" % k, format(v, ",")))
        for x in RND.sample(zh_eg[k], min(6, len(zh_eg[k]))):
            print("        %s" % x)
    print("   R3 形状（zh 可出版义项里）：")
    for k, v in sorted(r3.items()):
        print("   %-40s %9s   %s" % ("%s/%s" % k, format(v, ","), " ｜ ".join(r3_eg[k][:2])))

    print("\n§E 🔴 要花钱的分母：几种翻译范围（en/ru 可出版义项，**该词形已有 zh real 的不算**）")
    scopes = collections.Counter()
    chars = collections.Counter()
    for w, by in pub.items():
        if w in zh_real_w:
            continue
        lem = is_lemma.get(w, 1) == 1
        en, ru = by.get("en-edition", []), by.get("ru-edition", [])
        for name, rows in (
                ("S1 全部（en＋ru 两组都翻）", en + ru),
                ("S2 每词一组（有 ru 用 ru，否则 en）", ru or en),
                ("S3 每词一组（有 en 用 en，否则 ru）", en or ru),
                ("S4 只翻词元·两组都翻", (en + ru) if lem else []),
                ("S5 只翻词元·每词一组（ru 优先）", (ru or en) if lem else []),
                ("S6 只翻词元·每词一组（en 优先）", (en or ru) if lem else [])):
            scopes[name] += len(rows)
            chars[name] += sum(len(x) for x in rows)
    for k in sorted(scopes):
        print("   %-40s %9s 条 ／ %11s 字符" % (k, format(scopes[k], ","), format(chars[k], ",")))

    print("\n§F 三语都没有可出版释义的词元（＝空白页风险）")
    blank = [w for w, l in is_lemma.items() if l == 1 and not pub.get(w)]
    print("   %s / %s 个词元" % (format(len(blank), ","), format(sum(1 for l in is_lemma.values() if l == 1), ",")))
    print("   随机 30：%s" % " ".join(RND.sample(blank, min(30, len(blank)))))
    print("\n■ 完。")


if __name__ == "__main__":
    main()
