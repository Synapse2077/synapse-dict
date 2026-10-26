#!/usr/bin/env python3
"""阶段 4 探针：**音标层的落点**。ru，2026-10-23。只读，不写库。

    python3 -u ru/probes/probe_pronunciation_layer.py > data/work/ru/probe/probe_pronunciation_layer.txt

建表时有两条判断是「待量」或「量反了」，这一份要把它们量清：
  ⑦ 「源头没有成套的地域读音（现为 0）」——抽 4 万行就看见 Moscow/СПб/Ukraine 标签
  ⑧ `pronunciation_entry` 不建，门槛 5% ——「同一词形的不同词条给了不同读音」**尚未量**
另外四件抽样看见的事，每一件都决定「这条音标属于谁 / 能不能印」：
  ① ru 版 `tags: singular/plural` —— 复数那条是**另一个词形**的读音
  ② `неправильно`/`нерекомендуемое`/`proscribed` —— 源头说这是**错的读音**
  ③ vi 版 `phonetic respelling` —— 不是 IPA
  ④ pl 版 `sense_index`、en 版 `form` —— 挂在义项/别的词形上

判据一律 `from pipeline import criteria`。值域**全打不截断**（10-07 那一跤）。
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

RND = random.Random(20261023)


def eg_add(d, k, x, cap=8):
    if len(d[k]) < cap:
        d[k].append(x)


def main():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    is_lemma = dict(con.execute("SELECT word, is_lemma FROM dict"))
    con.close()

    rows = collections.Counter()                 # src → 带 ipa 的 sounds 行
    delim = collections.defaultdict(collections.Counter)
    delim_eg = collections.defaultdict(list)
    tagdom = collections.defaultdict(collections.Counter)    # src → tag（全值域）
    rawdom = collections.defaultdict(collections.Counter)    # src → raw_tag（全值域）
    keydom = collections.defaultdict(collections.Counter)    # src → sounds 键
    flag_eg = collections.defaultdict(list)
    # 词形 → 源 → [(entry 序号, frozenset(无标签的 ipa))]
    per_entry = collections.defaultdict(lambda: collections.defaultdict(list))
    # 词形 → 源 → set(无标签的 ipa)，给跨源一致率用
    per_word = collections.defaultdict(lambda: collections.defaultdict(set))
    num_eg = collections.defaultdict(list)
    for src, p in SRC:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                e = json.loads(line)
                ok, _skip, _pos = criteria.entry_accept(e)
                if not ok:
                    continue
                w = e["word"]
                plain = set()
                for s in e.get("sounds") or []:
                    if "ipa" not in s:
                        continue
                    rows[src] += 1
                    ip = s.get("ipa") or ""
                    k = criteria.ipa_delimiter(ip)
                    delim[src][k] += 1
                    eg_add(delim_eg, (src, k), "%s → %s" % (w, ip[:50]), 5)
                    tg = s.get("tags") or []
                    rt = s.get("raw_tags") or []
                    for t in tg:
                        tagdom[src][t] += 1
                    for t in rt:
                        rawdom[src][t] += 1
                    for kk in s:
                        keydom[src][kk] += 1
                    # 「这条不是这个词形本身的标准读音」的结构信号（只量，不下结论）
                    marks = []
                    if set(tg) & {"singular", "plural"}:
                        marks.append("number:" + "/".join(sorted(set(tg) & {"singular", "plural"})))
                    if s.get("form"):
                        marks.append("form")
                    if "sense_index" in s:
                        marks.append("sense_index")
                    for m in marks:
                        eg_add(flag_eg, (src, m), "%s → %s %s %s" % (
                            w, ip[:40], tg[:3], rt[:2] or s.get("form") or s.get("sense_index") or ""), 6)
                    if not marks and not tg and not rt:
                        plain.add(criteria.normalize_ipa(ip))
                    elif "number:singular" in marks and not (set(tg) - {"singular"}) and not rt:
                        # 单数那条就是词形自己（主格单数＝词元），算进 plain
                        plain.add(criteria.normalize_ipa(ip))
                    if "number:plural" in marks:
                        eg_add(num_eg, src, (w, ip, e.get("forms") or []), 400)
                if plain:
                    per_entry[w][src].append(frozenset(plain))
                    per_word[w][src] |= plain

    print("■ 俄语阶段 4 探针：音标层的落点  2026-10-23  判据 %s" % criteria.RULE_VER)

    print("\n§A 每源带 ipa 的 sounds 行，按定界符分（`criteria.ipa_delimiter`）")
    for src, _p in SRC:
        print("   %-16s %9s   %s" % (src, format(rows[src], ","),
                                    dict(delim[src].most_common())))
    print("   非方括号/斜杠/反斜杠/裸 的样本：")
    for (src, k), xs in sorted(delim_eg.items()):
        if k in ("[]", "//", "\\\\", "裸"):
            continue
        print("     %s %s：%s" % (src, k, " ｜ ".join(xs)))

    print("\n§B sounds 的键、tags、raw_tags —— **完整值域，不截断**")
    for src, _p in SRC:
        if not rows[src]:
            continue
        print("   ── %s" % src)
        print("      键   %s" % dict(keydom[src].most_common()))
        print("      tags %s" % dict(tagdom[src].most_common()))
        print("      raw  %s" % dict(rawdom[src].most_common()))

    print("\n§C 「这条读音不属于词形本身」的结构信号（样本）")
    for (src, m), xs in sorted(flag_eg.items()):
        print("   %s ／ %s" % (src, m))
        for x in xs:
            print("      %s" % x)

    print("\n§C2 ru 版复数读音：同一 entry 的 forms 里有没有主格复数可挂")
    hit = miss = 0
    egs = []
    for w, ip, forms in num_eg.get("ru-edition", []):
        pl = [f.get("form") for f in forms
              if {"nominative", "plural"} <= set(f.get("tags") or [])]
        if pl:
            hit += 1
        else:
            miss += 1
        if len(egs) < 12:
            egs.append("%s → %s ⇒ 主格复数 %s" % (w, ip, pl[:2]))
    print("   样本 %d 条里：forms 里有主格复数 %d ／ 没有 %d" % (hit + miss, hit, miss))
    for x in egs:
        print("      %s" % x)

    print("\n§D ⑧ `pronunciation_entry` 的门槛：同一源里、同一词形的**不同 entry** 给了**不相交**的读音")
    tot_rows = sum(len(s) for w in per_word for s in per_word[w].values())
    div_w = collections.Counter()
    div_rows = 0
    div_eg = []
    for w, by in per_entry.items():
        for src, lst in by.items():
            if len(lst) < 2:
                continue
            sets = [x for x in lst if x]
            disjoint = any(not (a & b) for i, a in enumerate(sets) for b in sets[i + 1:])
            if disjoint:
                div_w[src] += 1
                div_rows += len(per_word[w][src])
                if len(div_eg) < 4000:
                    div_eg.append("%s〔%s〕 %s" % (w, src, " ／ ".join(
                        ",".join(sorted(x)) for x in sets)))
    print("   读音行（去重后、只算无标签的）%s" % format(tot_rows, ","))
    print("   有分歧的词形（按源）%s" % dict(div_w))
    print("   涉及读音行 %s ＝ **%.2f%%**（门槛 5%%）"
          % (format(div_rows, ","), 100.0 * div_rows / max(tot_rows, 1)))
    for x in RND.sample(div_eg, min(25, len(div_eg))):
        print("      %s" % x)

    print("\n§E 跨源一致率（同一词形、两源各自的无标签读音，归一后**逐字**比）")
    pairs = [("en-edition", "ru-edition"), ("en-edition", "zh-edition-trad"),
             ("ru-edition", "fr-edition"), ("en-edition", "pl-edition")]
    for a, b in pairs:
        both = same = overlap = 0
        dif = []
        for w, by in per_word.items():
            if by.get(a) and by.get(b):
                both += 1
                if by[a] == by[b]:
                    same += 1
                elif by[a] & by[b]:
                    overlap += 1
                elif len(dif) < 3000:
                    dif.append("%s：%s ／ %s" % (w, ",".join(sorted(by[a]))[:40],
                                                ",".join(sorted(by[b]))[:40]))
        print("   %s × %s：共有 %s 个词形 ／ 完全相同 %.2f%% ／ 有交集 %.2f%% ／ 不相交 %.2f%%"
              % (a, b, format(both, ","), 100.0 * same / max(both, 1),
                 100.0 * overlap / max(both, 1),
                 100.0 * (both - same - overlap) / max(both, 1)))
        for x in RND.sample(dif, min(8, len(dif))):
            print("      %s" % x)

    print("\n§F 覆盖：词形有没有任何一条无标签读音（按 dict.is_lemma 分）")
    for lab, want in (("词元", 1), ("屈折形", 0)):
        tot = sum(1 for w, l in is_lemma.items() if l == want)
        got = sum(1 for w, l in is_lemma.items() if l == want and per_word.get(w))
        print("   %-6s %s / %s ＝ %.2f%%" % (lab, format(got, ","), format(tot, ","),
                                          100.0 * got / max(tot, 1)))
        by = collections.Counter()
        for w, l in is_lemma.items():
            if l == want and per_word.get(w):
                for s in per_word[w]:
                    by[s] += 1
        print("          按源：%s" % dict(by.most_common()))
    extra(is_lemma, per_word)
    print("\n■ 完。")


# ── 第二轮（同日）：§A–F 读完之后冒出来的五个问题 ─────────────────────────
import re                                                       # noqa: E402
# 🔴 **只用来量，不进库、不进 criteria**：把两套记音体系的已知约定差异剥掉，
#    看剩下的「真分歧」有多少。PLAYBOOK 3.2：约定差异不是缺陷，不许拿它去「修」。
_CONV = [("ɪ̯", "j"), ("(j)", "j"), ("⁽ʲ⁾", "ʲ"), ("(ʲ)", "ʲ"), (".", ""), ("‿", ""),
         ("ʌ", "ɐ"), ("g", "ɡ")]
_V = set("aeiouyɐɪʊəɨɵʉɛɔæø")


def _conv(ip):
    for a, b in _CONV:
        ip = ip.replace(a, b)
    return re.sub(r"\(([^)]*)\)", r"\1", ip)


def _stress_pos(ip):
    """主重音前有几个元音核。拿不到 ˈ 就 None。"""
    if "ˈ" not in ip:
        return None
    pre = ip.split("ˈ", 1)[0]
    return sum(1 for i, ch in enumerate(pre) if ch in _V
               and not pre[i + 1:i + 2] == "\u032f")


def extra(is_lemma, per_word):
    by_src_word = collections.defaultdict(lambda: collections.defaultdict(list))
    fr_tag_audio = collections.Counter()
    en_form = collections.Counter()
    en_form_eg = []
    for src, p in SRC:
        if src not in ("ru-edition", "fr-edition", "en-edition"):
            continue
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                e = json.loads(line)
                ok, _s, _pos = criteria.entry_accept(e)
                if not ok:
                    continue
                for s in e.get("sounds") or []:
                    if "ipa" not in s:
                        continue
                    if src == "ru-edition" and criteria.ipa_delimiter(s["ipa"]) == "裸":
                        by_src_word["ru裸"][e["word"]].append(s["ipa"])
                    if src == "fr-edition" and s.get("raw_tags"):
                        fr_tag_audio["有 raw_tags 且有录音" if s.get("audio")
                                     else "有 raw_tags 而无录音"] += 1
                    if src == "en-edition" and s.get("form"):
                        same = s["form"] == e["word"]
                        en_form["form＝词头" if same else "form≠词头"] += 1
                        if not same and len(en_form_eg) < 12:
                            en_form_eg.append("%s → form=%s %s" % (e["word"], s["form"], s["ipa"]))

    print("\n§G ru 版「裸」5,862 条是什么（随机 25）")
    ws = list(by_src_word["ru裸"].items())
    for w, ips in RND.sample(ws, min(25, len(ws))):
        print("      %s → %s" % (w, " ｜ ".join(ips[:3])))

    print("\n§H fr 版 raw_tags 与录音同在一个对象里吗（是 ⇒ 地名是录音者所在地，不是读音方言）")
    print("   %s" % dict(fr_tag_audio))

    print("\n§I en 版 sounds.form：%s" % dict(en_form))
    for x in en_form_eg:
        print("      %s" % x)

    print("\n§J en × ru：剥掉已知记音约定之后的「真分歧」，以及**主重音位置**是否一致")
    both = same_raw = same_conv = st_both = st_same = 0
    st_dif = []
    for w, by in per_word.items():
        a, b = by.get("en-edition"), by.get("ru-edition")
        if not (a and b):
            continue
        both += 1
        same_raw += bool(a & b)
        ca, cb = {_conv(x) for x in a}, {_conv(x) for x in b}
        same_conv += bool(ca & cb)
        pa = {_stress_pos(x) for x in a} - {None}
        pb = {_stress_pos(x) for x in b} - {None}
        if pa and pb:
            st_both += 1
            if pa & pb:
                st_same += 1
            elif len(st_dif) < 4000:
                st_dif.append("%s：en %s ／ ru %s" % (w, ",".join(sorted(a))[:40],
                                                     ",".join(sorted(b))[:40]))
    print("   共有 %s 个词形：原样有交集 %.2f%% ／ 剥约定后有交集 %.2f%%"
          % (format(both, ","), 100.0 * same_raw / max(both, 1), 100.0 * same_conv / max(both, 1)))
    print("   两边都有主重音的 %s 个：重音位置有交集 %.2f%% ／ **不相交 %s 个（%.2f%%）**"
          % (format(st_both, ","), 100.0 * st_same / max(st_both, 1),
             format(st_both - st_same, ","), 100.0 * (st_both - st_same) / max(st_both, 1)))
    for x in RND.sample(st_dif, min(30, len(st_dif))):
        print("      %s" % x)

    print("\n§K 词元缺读音的那批：是源头一条都没给，还是只给了带标签的")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    pos_of = collections.defaultdict(set)
    for w, p in con.execute("SELECT d.word, e.pos FROM dict d JOIN entry e ON e.word_id=d.id "
                            "WHERE d.is_lemma=1"):
        pos_of[w].add(p)
    con.close()
    gap = [w for w, l in is_lemma.items() if l == 1 and not per_word.get(w)]
    pc = collections.Counter()
    for w in gap:
        for p in pos_of.get(w, ()):
            pc[p] += 1
    print("   缺读音的词元 %s 个；按词性（一个词可多个）：%s"
          % (format(len(gap), ","), pc.most_common(12)))
    print("   随机 25：%s" % " ".join(RND.sample(gap, min(25, len(gap)))))


if __name__ == "__main__":
    main()
