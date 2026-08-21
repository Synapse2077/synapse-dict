#!/usr/bin/env python3
"""关系区里混进的英语说明文字。es，2026-08-21（点测评审）。

═══ 怎么发现的 ═══
外审（豆包）读 `la` 的渲染成品时指出：「相关词模块末尾混入无关的泛语法说明文本」。
回源确认属实 —— `sense_relation.target` 里躺着整句英语：

    Like other masculine words
    masculine pronouns can be used when the gender of the subject is unknown
    when the subject is plural and of mixed gender
    Treated as if it were third person for purposes of conjugation and reflexivity
    Only used in certain circumstances and rarely as a subject pronoun

它们是英文版维基词典**代词表格里的脚注**，收关系时被当成了关系目标。
页面上跟在 `yo mí me conmigo …` 后面，看起来像是一串"相关词"。

═══ 判据修了两轮 ═══
🔴 第一版：「含空格 + 全 ASCII + 长度>40」→ 337 条，**误伤严重**。
   西语基本字母不带变音符时**本来就是 ASCII**，于是 109 条 `derived` 谚语全被圈进来：
   `no hay peor ciego que el que no quiere ver`、`salir de Guatemala y meterse en Guatepeor`、
   `contra el vicio de pedir, la virtud de no dar` —— 那些是真数据。
   ⚠️「全 ASCII」根本区分不了语言，只区分得了"有没有变音符"。
⇒ 第二版：**双向**判据 —— 含英语功能词 **且不含**西语功能词。251 条，16 种文本，
   逐条读过（5 种 ×48 是代词表脚注，11 种 ×1 是零散英文说明）。

═══ 为什么是藏不是删 ═══
与同批的 `hide_relation_colloc_residue` 一致：`sense_relation.hidden`，可逆，
且收关系脚本重放时 `INSERT OR IGNORE` 不会覆盖 `hidden`。

用法（在 es/ 目录下）：
    python3 fixes/hide_english_relation_notes.py            # 干跑
    python3 fixes/hide_english_relation_notes.py --apply
    python3 fixes/hide_english_relation_notes.py --verify
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

f = lambda n: format(n, ",")

# 判据：**双向**。回归闸 import 这两条，不另写。
EN_WORD = re.compile(
    r"\b(the|of|when|used|can|be|as|if|for|with|are|is|it|its|their|other|only|rarely|purposes)\b",
    re.I)
ES_WORD = re.compile(
    r"\b(el|la|los|las|de|del|que|para|con|por|una|un|en|se|no|es|al|lo|si|te|me)\b", re.I)


# ── 逐条读过、写死的碎片名单 ────────────────────────────────────────────────
# 判据修到第三轮就停手（`measure-landing-not-source`），这 8 种是**逐条确认**的：
#   · `If le` / `les precedes lo` / `or las in a clause` / `it is replaced with se`
#     / `Used primarily in Spain` —— 英文版代词表的一句脚注
#     「If le/les precedes lo/las in a clause, it is replaced with se. Used primarily in Spain」
#     被切成了 5 段，每段单独成了一条 related。长度判据够不到 `If le`（5 个字符）。
#   · `se3` / `ello5` —— 源头是 `se³` / `ello⁵`，**脚注上标被压成了普通数字**，
#     于是变成了库里不存在的词形。
#   · `—` —— 代词表里的空格占位符。
# 每一种都出现在 48 个代词词条上（×48），合计 384 条。
EXACT_JUNK = {
    "If le", "les precedes lo", "or las in a clause", "it is replaced with se",
    "Used primarily in Spain", "se3", "ello5", "—",
}


def is_english_note(target):
    """这条关系目标是不是英语说明文字（而不是西语词/词组）。"""
    t = (target or "").strip()
    if t in EXACT_JUNK:
        return True
    if " " not in t or len(t) <= 25:
        return False                     # 单词与短词组一律不判（西语词组多得是）
    return bool(EN_WORD.search(t)) and not ES_WORD.search(t)


def scan(con):
    return [(rid, w, k, t) for rid, w, k, t in con.execute(
        "SELECT r.id, d.word, r.kind, r.target FROM sense_relation r "
        "JOIN dict d ON d.id=r.word_id WHERE COALESCE(r.hidden,0)=0")
        if is_english_note(t)]


def gate(con):
    n = sum(1 for (t,) in con.execute(
        "SELECT target FROM sense_relation WHERE COALESCE(hidden,0)=0") if is_english_note(t))
    print("■ 读取路径上仍有英语说明冒充关系目标：%s 条" % f(n))
    return n == 0


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        ok = gate(ro)
        ro.close()
        return 0 if ok else 1
    rows = scan(ro)
    ro.close()
    texts = {}
    for _rid, _w, _k, t in rows:
        texts[t] = texts.get(t, 0) + 1
    print("■ 要藏 %s 条，共 %s 种不同文本：" % (f(len(rows)), f(len(texts))))
    for t, n in sorted(texts.items(), key=lambda x: -x[1]):
        print("     ×%-4d %s" % (n, t[:76]))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("hide-english-relation-notes", expect={"__rows__": 0}) as s:
        s.execute("UPDATE sense_relation SET hidden=1 WHERE id IN (%s)"
                  % ",".join(str(r[0]) for r in rows))
        s.written = len(rows)
    print("\n■ 已藏 %s 条" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
