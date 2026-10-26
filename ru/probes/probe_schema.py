#!/usr/bin/env python3
"""阶段 0 的建表依据：**哪个字段该落在哪一层**。2026-10-07。只读可重跑。

═══ 为什么必须先量 ═══
项目既有判据（`SCHEMA` §10.4.1，意语上立的）：
**「互斥单值的落列（`gender`），多值的落行」** ——
而「它是单值还是多值」**是个实测问题，不是语感问题**。
意语那轮我第一版把及物性当单值落列，实测有 `ditransitive+transitive`、
`intransitive+pronominal+transitive` 这种组合 ⇒ 推翻重做。

本脚本逐个字段回答三个问题：
  ① 它在**一个词条内**是不是单值？（决定落 `entry` 列还是落行）
  ② 它在**一个词形内**是不是单值？（决定能不能落 `dict` 列）
  ③ 它住在源头的哪一层（词级 `tags` ／ 义项级 `senses[].tags` ／ `forms[]`）？

🔴 **R7 就是这里最要紧的一条**：外审两家都倾向「体是 sense 级属性」，
   理由是 `идти` 的「走」义对 `пойти`、「走一段路程」义对 `пройти`。
   **那是个可量的事实，不许靠两家的倾向拍** —— 本脚本 §R7 量它。

═══ 「一个词条」在 dump 里怎么认 ═══
kaikki 的一行 JSON ＝ 一个 (word, pos, etymology_number) 组合，
也就是我们 `entry` 表的一行（`SCHEMA` 的 v3 约定）。
⚠️ **同一个 word 的每个 pos 是独立的一行**（`PLAYBOOK` 二的判据坑），
   所以「一个词条内」＝「一行内」，不是「同一个 word 的所有行」。

用法：
    python3 ru/probes/probe_schema.py [--limit N] [--archive]
"""
import argparse
import collections
import gzip
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                                    # noqa: E402

SRC = [("en", paths.KK), ("ru", paths.EDITION), ("zh-t", paths.ZH_TRAD)]

# 候选的「一等本质字段」。每一个都要回答「单值还是多值」。
# 🔴 值域**从源头实测的完整值域里抄**，不是我猜的（见 `probe_aspect_relations.py` §D
#    的教训：同一张猜的候选表一天内漏了三个值名）。
GROUPS = {
    "aspect":       {"imperfective", "perfective", "perfect", "biaspectual"},
    # 🆕 动作方式（способы действия）—— §D 逮到的两个，源头给了标签
    "actionality":  {"semelefactive", "iterative"},
    "gender":       {"masculine", "feminine", "neuter", "common"},
    "animacy":      {"animate", "inanimate"},
    "declension":   {"declension-1", "declension-2", "declension-3", "indeclinable"},
    "transitivity": {"transitive", "intransitive", "reflexive", "pronominal",
                     "impersonal", "ditransitive"},
    "number":       {"singular", "plural", "plural-only", "uncountable", "countable"},
}


def rd(p, limit=None):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                return
            yield json.loads(line)


def pct(a, b):
    return "%6.2f%%" % (100.0 * a / b) if b else "     —"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--archive", action="store_true")
    a = ap.parse_args()
    limit = a.limit or None

    acc = {}
    for name, p in SRC:
        d = {
            "lines": 0,
            # 每个字段：在词级/义项级各出现多少行、行内多值多少
            "at_word": collections.Counter(),
            "at_sense": collections.Counter(),
            "word_multi": collections.Counter(),     # 词级 tags 里同组出现 ≥2 个值
            "entry_multi": collections.Counter(),    # 一行内各义项之间同组取值不一致
            "entry_multi_sample": collections.defaultdict(list),
            # 词形 ↔ 词条 ↔ 词元
            "word_rows": collections.Counter(),      # 一个 word 有几行
            "etym_no": collections.Counter(),
            # 🔴 源头的 `etymology_number` **混了 int 与 str 两种类型**（第一版在这里崩了）。
            #    vi 的 B18 就是它的下游：`etym_no` 存成 TEXT ⇒ 字典序 ⇒ 「10」排在「2」前面。
            #    ⇒ 本列**必须按 INTEGER 存**，入库时强转并断言转得动。
            "etym_no_types": collections.Counter(),
            "pos_per_word": collections.defaultdict(set),
            "is_form": 0, "is_lemma": 0,
            "form_of_src": collections.Counter(),
        }
        for e in rd(p, limit):
            d["lines"] += 1
            w = e.get("word") or ""
            d["word_rows"][w] += 1
            d["pos_per_word"][w].add(e.get("pos"))
            _en = e.get("etymology_number")
            d["etym_no_types"][type(_en).__name__] += 1
            d["etym_no"][str(_en) if _en is not None else "0"] += 1

            wt = set(e.get("tags") or [])
            for g, vals in GROUPS.items():
                hit = wt & vals
                if hit:
                    d["at_word"][g] += 1
                if len(hit) >= 2:
                    d["word_multi"][g] += 1

            # 🔴 R7：一行（＝一个 entry）内，各义项之间同一组取值是否一致
            per_group = collections.defaultdict(set)
            for s in e.get("senses") or []:
                st = set(s.get("tags") or [])
                for g, vals in GROUPS.items():
                    hit = st & vals
                    if hit:
                        d["at_sense"][g] += 1
                        per_group[g] |= hit
            for g, seen in per_group.items():
                if len(seen) >= 2:
                    d["entry_multi"][g] += 1
                    if len(d["entry_multi_sample"][g]) < 6:
                        d["entry_multi_sample"][g].append(
                            "%s(%s) %s" % (w, e.get("pos"), sorted(seen)))

            # 词元 / 屈折形：指针从哪儿来
            fo = e.get("form_of") or []
            sense_fo = [s for s in e.get("senses") or [] if s.get("form_of")]
            has_formof_tag = any("form-of" in (s.get("tags") or [])
                                 for s in e.get("senses") or [])
            if fo or sense_fo or has_formof_tag:
                d["is_form"] += 1
                d["form_of_src"]["word.form_of" if fo else
                                 "sense.form_of" if sense_fo else
                                 "仅 sense.tags 含 form-of"] += 1
            else:
                d["is_lemma"] += 1
        acc[name] = d
        print("  · %-5s %9s 行" % (name, "{:,}".format(d["lines"])), file=sys.stderr)

    buf = io.StringIO()
    with redirect_stdout(buf):
        print("■ 俄语阶段 0 建表依据  2026-10-07"
              + ("（--limit %d）" % a.limit if a.limit else "（全量）"))

        print("\n" + "═" * 78)
        print("§ R7 🔴 **体是 entry 级还是 sense 级** —— 外审两家都倾向 sense 级，这里量它")
        print("═" * 78)
        print("  判据：一行 JSON ＝ 一个 (word, pos, etym_no) ＝ 我们 `entry` 表的一行。")
        print("  「entry 内不一致」＝ 同一行的各义项之间，同一组 tag 取到了 ≥2 个不同值。\n")
        print("  %-14s%12s%14s%16s%14s" % (
            "字段组", "词级有值", "义项级有值", "**entry 内不一致**", "词级自身多值"))
        print("  " + "-" * 72)
        for name, _ in SRC:
            print("  ── %s（%s 行）" % (name, "{:,}".format(acc[name]["lines"])))
            d = acc[name]
            for g in GROUPS:
                print("  %-14s%12s%14s%10s %s%14s" % (
                    g,
                    "{:,}".format(d["at_word"][g]),
                    "{:,}".format(d["at_sense"][g]),
                    "{:,}".format(d["entry_multi"][g]),
                    pct(d["entry_multi"][g], max(d["lines"], 1)),
                    "{:,}".format(d["word_multi"][g])))
        print("\n  ⇒ 判据（`SCHEMA` §10.4.1）：**entry 内不一致 ⇒ 必须落行；一致 ⇒ 可以落列。**")
        print("  🔴 「不一致」的样例必须人读 —— 它可能是源头脏数据而不是真的多值：")
        for name, _ in SRC:
            for g, smp in acc[name]["entry_multi_sample"].items():
                if smp:
                    print("     %s / %-14s %s" % (name, g, " ｜ ".join(smp[:4])))

        print("\n" + "═" * 78)
        print("§ S1 词形 ↔ 词条 ↔ 词元：`dict` / `entry` 怎么切")
        print("═" * 78)
        print("  %-6s%14s%14s%14s%16s" % ("源", "行数", "唯一 word", "一词多行占比", "词元 / 屈折形"))
        print("  " + "-" * 66)
        for name, _ in SRC:
            d = acc[name]
            multi = sum(1 for w, n in d["word_rows"].items() if n >= 2)
            print("  %-6s%14s%14s%8s %s%7s / %s" % (
                name, "{:,}".format(d["lines"]), "{:,}".format(len(d["word_rows"])),
                "{:,}".format(multi), pct(multi, max(len(d["word_rows"]), 1)),
                "{:,}".format(d["is_lemma"]), "{:,}".format(d["is_form"])))
        print("\n  `etymology_number` 分布（0 ＝ 源头没给，也就是单词源）：")
        for name, _ in SRC:
            d = acc[name]
            print("     %-6s %s" % (name, "  ".join(
                "%s→%s" % (k, "{:,}".format(v))
                # 🔴 **不许截断。** 第一版写了 `[:8]`，而 `1.1`/`1.2` 排在后面
                #    ⇒ 我据此写下「值域是 0–7」，建库时判据当场炸在 `'1.1'` 上。
                #    「把值域全打出来」要**真的全打**。
                for k, v in sorted(d["etym_no"].items(),
                                   key=lambda kv: (len(kv[0]), kv[0])))))
            print("            源头类型分布：%s  ← 🔴 混类型，入库必须强转 INTEGER"
                  % "  ".join("%s=%s" % (k, "{:,}".format(v))
                              for k, v in d["etym_no_types"].most_common()))
        print("\n  「这是个屈折形」的指针**源头是用哪几种方式说出来的**")
        print("  （`PLAYBOOK` 四：pt 补链补了四步，每一步都是发现上一步的判据够不着）：")
        for name, _ in SRC:
            d = acc[name]
            print("     %-6s %s" % (name, "  ".join(
                "%s=%s" % (k, "{:,}".format(v)) for k, v in d["form_of_src"].most_common())))
    txt = buf.getvalue()
    print(txt)
    if a.archive:
        paths.PROBE.mkdir(parents=True, exist_ok=True)
        out = paths.PROBE / "probe_schema.txt"
        out.write_text(txt, "utf-8")
        print("■ 已存档 → %s" % out, file=sys.stderr)


if __name__ == "__main__":
    main()
