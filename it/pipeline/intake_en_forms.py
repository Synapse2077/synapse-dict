#!/usr/bin/env python3
"""跨版收词（一）：把英文版 dump 变位表里**从没收过**的词形收进来。2026-08-16。

═══ 缺口从哪来 ═══
词形数 it 767,289 / es 1,139,997，少 33%；每个动词均摊变形 it 11.0 / es 55.6。
根因不是数据不行，是 **es 做过一轮跨版大收词（+369,001 行），it 没做过**。

七月的 `build.py` 只给"在 dump 里独立成条目"的词形建了 `dict` 行；
`forms[]`（变位表）里的词形只被压进 `dict.infl` 字符串，**没有独立词形行**。
`build_inflection_layer.py` 是从那个字符串**搬**过来的，所以也补不上。

═══ 🔴 量这个缺口，我的尺子错了四轮，每轮都是读样本读出来的 ═══
    第一版 裸比对              585,790   ← 全是**教学重音**（`déttero` vs `dettero`）
    第二版 归一重音            247,877   ← 混着变位表格子（`(loro) baratterebbero`）
    第三版 只算单词            130,807   ← 还混着 `-` 占位符和 kaikki 自标的
                                          `error-unrecognized-form`
    第四版 收紧 + **存归一形**  124,401   ← 逐个查库核过，真的没有

⚠️ 意语的正字重音**只出现在词末**（`città`/`caffè`/`perché`）；词中的重音符
   （`insonnoliàmo`）是词典的重音标注，**不是拼写**。⇒ 存 `insonnoliamo`。
   第一版把这条搞反，误差 4.7 倍。

═══ 收什么、挂到哪 ═══
只收**原形已在库里**的（124,401 全部满足），所以每一条都能挂上：
    `dict`        新词形行，`is_lemma=0`
    `inflection`  word_id → 新词形；base/base_id → 原形；label_zh 用现成的
                  `infl_compose.compose(tags)`；`entry_id` → 原形该词性的词条

`src_ref = kkform-en:<原形>:<词性>:<归一词形>` —— 与义项级那套（`kk-en:…#0.0`）
**分开命名**，因为来路不同：那套锚的是"第几条义项"，这套锚的是"变位表里的一格"。

═══ 闸 ═══
① 可复算：重扫 dump，本步建的每一行都必须能逐字节重算出来（100%，非抽样）
② 反错配：`inflection.word_id` 指的词形 == 归一后的 form；`base_id` 指的词形 == base
③ 不重复：新词形归一后不许与库里已有词形撞
④ `label_zh` 不许为空（组合不出来的用「变位形式」兜底，但要数出来）

用法（在 it/ 目录下）：
    python3 pipeline/intake_en_forms.py            # 扫描 + 分布，不写库
    python3 pipeline/intake_en_forms.py --apply
    python3 pipeline/intake_en_forms.py --verify
    python3 pipeline/intake_en_forms.py --mutate
"""
import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))

import dbtool        # noqa: E402
import infl_compose  # noqa: E402
import paths         # noqa: E402
from split_case_forms import norm as word_norm   # noqa: E402  word_norm 同一套规则

DUMP = paths.DATA / "dumps" / "kaikki.org-dictionary-Italian.jsonl"
SRC = "en-edition"

# 「是一个意语词形」：至少两个字母，只含字母/撇号/连字符，首尾不是连字符
OK = re.compile(r"^(?=.*[A-Za-zÀ-ÿ]{2})[A-Za-zÀ-ÿ'’][A-Za-zÀ-ÿ'’\-]{0,38}[A-Za-zÀ-ÿ'’]$")
# 这些 tag 标的不是"这个词的形式"：辅助动词本身、词头复读、表格元数据、kaikki 自标的解析失败
SKIP_TAG = {"auxiliary", "canonical", "table-tags", "inflection-template", "class",
            "error-unrecognized-form", "romanization", "transliteration"}

# 🔴 **不是变形**的那一族，本轮不收（记账）。它们是词形没错，但挂进 `inflection`
#    会告诉用户「camera 的变位形式」—— 那是错的：
#      alternative   `bce←BCE` `Niccosia←Nicosia`   异体拼写，归宿是 `sense_relation`
#      diminutive    `camerina←camera`（小房间）    ┐
#      augmentative  `camerona←camera`（大房间）    ├ 意语的 alterati，是**派生词**，
#      pejorative    `carnaccia←carne`（劣质肉）    │ 各自是独立词位，不是 camera 的形式
#      derogatory    `abatuccio←abate`             ┘
#    实测 2,193 条。收它们要先决定归宿（`sense_relation` 的 kind），是另一件事。
NOT_INFL = {"alternative", "diminutive", "augmentative", "pejorative", "derogatory"}

# `infl_compose.compose()` 组合不出、但**确实是变形**的：逐个读过写在这里。
# 实测只有一族：裸 `('feminine',)` 3,105 条（`fera←fero` `tala←talo`）。
EXTRA_LABEL = {
    ("feminine",): "阴性形式",      # fera←fero，3,105 条
    ("masculine",): "阳性形式",
    ("superlative",): "绝对最高级",   # bellissimo←bello，意语确是屈折形式
}

# 🔴 标不出中文语法说明的**一律不收**（实测 47 条）。里面混着 kaikki 的解析残渣
#    （`subjunctive`/`archaic` 被当成了 `essere` 的"词形"），也有 `endearing`
#    `demonym` 这类其实属于派生的。宁可少收，不给用户一条说不清是什么的词形。


def deaccent_inner(w):
    """剥掉**词中**的重音标注，保留词末的正字重音。

    🔴 意语正字重音只在最后一个字母上（`città` `caffè` `perché` `più`）。
       词中的 `à/è/é/ì/ò/ó/ù`（`insonnoliàmo`）是词典给读者标重音用的，不是拼写。
    """
    out = []
    for i, ch in enumerate(w or ""):
        if i < len(w) - 1 and unicodedata.combining(ch) == 0:
            d = unicodedata.normalize("NFD", ch)
            if len(d) > 1:
                ch = d[0]
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


def label_of(tg):
    """kaikki tags → 中文语法说明。compose() 组合不出的，只认我逐个读过的那几族。"""
    return infl_compose.compose(list(tg)) or EXTRA_LABEL.get(tuple(tg), "")


def src_ref_of(base, pos, form):
    return "kkform-en:%s:%s:%s" % (base, pos, form)


def scan(con):
    """→ {归一词形: (base, pos, tags)}，只收原形已在库里的。"""
    have = {w for (w,) in con.execute("SELECT word FROM dict")}
    have_n = {deaccent_inner(w) for w in have}
    out, st = {}, Counter()
    with DUMP.open(encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("lang_code") != "it":
                continue
            base, pos = d.get("word"), d.get("pos")
            if base not in have or not pos:
                continue
            for fm in (d.get("forms") or []):
                x, tg = fm.get("form"), set(fm.get("tags") or [])
                if not x or not OK.match(x):
                    st["形状不是词形（表格子/占位符/太长）"] += 1
                    continue
                if tg & SKIP_TAG:
                    st["tag 说它不是这个词的形式"] += 1
                    continue
                if tg & NOT_INFL:
                    st["🔴 是派生词/异体拼写，不是变形（本轮不收，见 NOT_INFL）"] += 1
                    continue
                k = deaccent_inner(x)
                if k in have_n:
                    st["库里已有"] += 1
                    continue
                if k in out:
                    st["本轮已收（同一词形多处出现）"] += 1
                    continue
                if not label_of(tuple(sorted(tg))):
                    st["🔴 标不出中文语法说明，不收"] += 1
                    continue
                out[k] = (base, pos, tuple(sorted(tg)))
                st["✅ 可收"] += 1
    return out, st


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    left, _ = scan(con)
    # ① 可复算：本步建的每一行，src_ref 必须能按同一规则重算
    bad_ref = 0
    for wid, base, pos_ref, sr in con.execute(
            "SELECT i.word_id, i.base, i.src_ref, i.src_ref FROM inflection i "
            "WHERE i.src_ref LIKE 'kkform-en:%'"):
        w = con.execute("SELECT word FROM dict WHERE id=?", (wid,)).fetchone()[0]
        parts = sr.split(":")
        if len(parts) != 4 or parts[1] != base or parts[3] != w:
            bad_ref += 1
    checks = [
        ("🔴 没有还能收却没收的", len(left), 0),
        ("🔴 本步建的行 src_ref 逐字节可复算", bad_ref, 0),
        ("🔴 base_id 指的词形必须等于 base 文本",
         q("SELECT count(*) FROM inflection i JOIN dict d ON d.id=i.base_id "
           "WHERE i.src_ref LIKE 'kkform-en:%' AND d.word <> i.base"), 0),
        ("🔴 本步收的词形一律 is_lemma=0",
         q("SELECT count(*) FROM dict d JOIN inflection i ON i.word_id=d.id "
           "WHERE i.src_ref LIKE 'kkform-en:%' AND COALESCE(d.is_lemma,0)<>0"), 0),
        ("🔴 label_zh 不许为空",
         q("SELECT count(*) FROM inflection WHERE src_ref LIKE 'kkform-en:%' "
           "AND (label_zh IS NULL OR trim(label_zh)='')"), 0),
        ("🔴 word_norm 必须按同一套规则算",
         sum(1 for w, n in con.execute(
             "SELECT d.word, d.word_norm FROM dict d JOIN inflection i ON i.word_id=d.id "
             "WHERE i.src_ref LIKE 'kkform-en:%'") if word_norm(w) != n), 0),
        ("词形表里没有重复词形",
         q("SELECT count(*) FROM (SELECT word FROM dict GROUP BY word HAVING count(*)>1)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-42s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    return ok


def mutate():
    print("\n═══ 变异验证：判据 ═══")
    cases = [
        ("词中重音剥掉", deaccent_inner("insonnoliàmo"), "insonnoliamo"),
        ("词末重音保留（正字法）", deaccent_inner("città"), "città"),
        ("词末重音保留（perché）", deaccent_inner("perché"), "perché"),
        ("多个词中重音全剥", deaccent_inner("ritranquillàsse"), "ritranquillasse"),
        ("没有重音的不动", deaccent_inner("destanti"), "destanti"),
        ("🔴 表格子不是词形", bool(OK.match("(loro) baratterebbero")), False),
        ("🔴 占位符不是词形", bool(OK.match("-")), False),
        ("🔴 单字母不是词形", bool(OK.match("a")), False),
        ("正常词形认得", bool(OK.match("codificatami")), True),
        ("带撇号的认得", bool(OK.match("dell'")), True),
    ]
    ok = True
    for name, got, want in cases:
        good = got == want
        ok &= good
        print("   %s %-26s → %-20s (期望 %s)" % ("✅" if good else "🔴", name, got, want))
    print("\n   变异验证 %s" % ("通过" if ok else "🔴 判据有问题"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("apply", "verify", "mutate"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    got, st = scan(ro)
    for k, v in st.most_common():
        print("   %-38s %11s" % (k, f"{v:,}"))
    lab = Counter()
    for k, (b, p, tg) in got.items():
        lab[label_of(tg)] += 1
    print("\n■ 可收 %s 个新词形；中文语法说明分布（前 10）" % f"{len(got):,}")
    for t, n in lab.most_common(10):
        print("   %-30s %s" % (t, f"{n:,}"))
    for k in list(got)[:6]:
        b, p, tg = got[k]
        print("   %-24s ← %-16s %s" % (k[:24], b[:16], label_of(tg)))
    ro.close()
    if not a.apply or not got:
        print("\n(未加 --apply，不写库)" if not a.apply else "")
        return 0

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid_of = dict(con.execute("SELECT word, id FROM dict"))
    ent_of = {}
    for eid, wid, pos in con.execute("SELECT id, word_id, pos FROM entry"):
        ent_of.setdefault((wid, pos), eid)
    nxt = con.execute("SELECT max(id) FROM dict").fetchone()[0] + 1
    con.close()
    d_rows, i_rows = [], []
    for k in sorted(got):
        b, p, tg = got[k]
        bid = wid_of[b]
        d_rows.append((nxt, k, word_norm(k), 0))
        i_rows.append((nxt, ent_of.get((bid, p)), b, bid,
                       label_of(tg), None,
                       json.dumps(list(tg), ensure_ascii=False), SRC, src_ref_of(b, p, k)))
        nxt += 1
    # ⚠️ 总行数的键是 `__rows__`（`dbtool` 内部名），不是打印时看到的「总行」。
    #    第一版写成「总行」，dbtool 认不出 ⇒ 判定"总行数凭空多了 122,234"，**当场回滚**。
    #    闸干得对：不认识的键宁可拦下，也不放行一次没声明的写入。
    with dbtool.session("intake-en-forms",
                        expect={"__rows__": len(d_rows), "#inflection": len(i_rows)}) as s:
        s.executemany("INSERT INTO dict (id,word,word_norm,is_lemma) VALUES (?,?,?,?)", d_rows)
        s.executemany("INSERT INTO inflection "
                      "(word_id,entry_id,base,base_id,label_zh,desc_en,tags,src,src_ref) "
                      "VALUES (?,?,?,?,?,?,?,?,?)", i_rows)
    print("\n■ 已收 %s 个词形" % f"{len(d_rows):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
