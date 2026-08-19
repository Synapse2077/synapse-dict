#!/usr/bin/env python3
"""489 条可见义项**一个中文都没有**：模板能填的先填，剩下的才送模型。2026-08-16。

═══ 用户看到的是什么 ═══
这些义项在页面上只有意语原文，中文那一行是空的：

    -cidi   （空）   it: plurale di -cida
    Aja     （空）   it: L'Aia
    Concord （空）   it: nome di varie località nei paesi anglofoni, tra cui:

全库 410,584 条可见义项里 489 条这样（0.12%），**全部来自意语版**。

═══ 怎么发现的 ═══
本来在追另一族缺陷（变形描述被当成义项），判据写了三版都不对
（第二版把 `o`「或者」`uno`「一」全命中了 —— **按字符集判定**的老毛病）。
按 `PITFALLS` A4 停手换方向，改查「中文是空的」——这个不用猜判据，是可判定的。
⭐ 判据难写的时候，先找一个**不需要判据**的相邻问题。

═══ 四族，两种做法（`PLAYBOOK` 5.3：模板在模型前面）═══
    ① 指针            180  `plurale di -cida` / `variante di Astro`
                           ⇒ 模板。沿用库里已有 7,899 条指针文案的写法（意语词 + 中文标签）
    ② 单个异名、目标有中文  ~50  `Aja` → `L'Aia`（海牙）
                           ⇒ 模板 + 查库拿目标的中文
    ③ 单个异名、目标没中文  ~100 `Casuaro` → `Casuario`
    ④ 真释义           153  `nome di varie località nei paesi anglofoni…`
                           ③④ ⇒ 送模型

用法（在 it/ 目录下）：
    python3 fixes/fill_empty_zh.py                # 分族看
    python3 fixes/fill_empty_zh.py --apply        # 只落模板那两族（不花钱）
    python3 fixes/fill_empty_zh.py --run          # 剩下的送模型
    python3 fixes/fill_empty_zh.py --apply-model
    python3 fixes/fill_empty_zh.py --verify
    python3 fixes/fill_empty_zh.py --mutate
"""
import argparse
import asyncio
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
import translate_it_defs as T   # noqa: E402

OUT = paths.WORK / "empty_zh.jsonl"
SRC_TPL = "template:it-ptr"
SRC_MODEL = "deepseek-v4-flash:empty-zh"

# 意语版的指针文案是封闭的一套说法。值里的 %s 放**意语目标词**，
# 与库里已有的 7,899 条指针文案写法一致（`fremere 的异体形式`）。
PTR_IT = [
    (re.compile(r"^plurale\s+femminile\s+di\s+(.+)$", re.I), "%s 的阴性复数形式"),
    (re.compile(r"^plurale\s+maschile\s+di\s+(.+)$", re.I), "%s 的阳性复数形式"),
    (re.compile(r"^plurale\s+di\s+(.+)$", re.I), "%s 的复数形式"),
    (re.compile(r"^singolare\s+di\s+(.+)$", re.I), "%s 的单数形式"),
    (re.compile(r"^femminile\s+di\s+(.+)$", re.I), "%s 的阴性形式"),
    (re.compile(r"^maschile\s+di\s+(.+)$", re.I), "%s 的阳性形式"),
    (re.compile(r"^grafia\s+alternativa\s+di\s+(.+)$", re.I), "%s 的异体拼写"),
    (re.compile(r"^forma\s+alternativa\s+di\s+(.+)$", re.I), "%s 的异体形式"),
    (re.compile(r"^variante\s+(?:antica\s+-?\s*e\s+in\s+disuso\s+-?\s*)?"
                r"(?:da\s+evitare\s+)?d[ia]\s+(.+)$", re.I), "%s 的变体形式"),
]

SYS = """你是意大利语—中文词典编纂员。输入是一个意大利语词条和它的意语释义，
这条义项目前**没有中文**。给出中文。

规则：
1. 写这个词**指的那个东西**在中文里的说法，读者拿它替换句子里的这个词，意思应当成立
2. 释义只是另一个意语词（`Casuaro` → `Casuario`）时，给那个词的中文说法，
   并在括号里注明「（异体）」
3. 专名（地名、人名、族名）给通行中译名；没有通行名的按当地读音音译，
   并在括号里写出它是什么（`（尼日尔城市）`）
4. 不要写"关于这个词"的话（"指…""表示…""该词…"）
5. 句末不加任何标点
6. 释义本身没有信息量、或你无法确定时，`zh` 给空字符串 ""，**不要猜**

输入是 JSON 数组，每项有 `id`、`word`、`it`。
输出**只有** JSON 数组，每项 {"id": 原样, "zh": "中文"}。不要围栏、不要解释。"""


def empty_senses(con):
    """→ [(sense_id, word, 意语原文)]，可见但没有中文的。"""
    return con.execute(
        "SELECT s.id, d.word, (SELECT text FROM sense_gloss WHERE sense_id=s.id "
        "AND lang='it' AND kind='definition' AND seq=0) "
        "FROM sense s JOIN dict d ON d.id=s.word_id WHERE COALESCE(s.hidden,0)=0 "
        "AND NOT EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id "
        "AND g.lang='zh' AND g.seq=0 AND trim(g.text)<>'') ORDER BY s.id").fetchall()


def zh_of_word(con):
    cache = {}

    def f(w):
        if w not in cache:
            r = con.execute(
                "SELECT g.text FROM dict d JOIN sense s ON s.word_id=d.id "
                "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' AND g.seq=0 "
                "WHERE d.word=? AND COALESCE(s.hidden,0)=0 AND trim(g.text)<>'' "
                "ORDER BY s.rank LIMIT 1", (w,)).fetchone()
            cache[w] = r[0] if r else None
        return cache[w]
    return f


def split(con):
    """→ (模板可填 [(sid, word, zh)], 要送模型 [(sid, word, it)], 统计)"""
    zh_of = zh_of_word(con)
    tpl, model, st = [], [], Counter()
    for sid, w, it in empty_senses(con):
        t = (it or "").strip().rstrip(".;")
        if not t:
            st["🔴 连意语原文都没有（无从下手）"] += 1
            continue
        hit = None
        for rx, fmt in PTR_IT:
            m = rx.match(t)
            if m:
                hit = fmt % m.group(1).strip().rstrip(".;")
                break
        if hit:
            tpl.append((sid, w, hit))
            st["① 指针 ⇒ 模板"] += 1
            continue
        # ② 释义就是另一个词，且那个词在库里有中文
        if len(t.split()) <= 3 and zh_of(t):
            # ⚠️ 目标的中文自己可能已经带括号（`阿加德斯（非洲城市）`），
            #    直接再加一对会出「…（非洲城市）（Agades 的异体）」。并进已有那对里。
            z = zh_of(t)
            note = "%s 的异体" % t
            tpl.append((sid, w, re.sub(r"）\s*$", "，%s）" % note, z)
                        if z.endswith("）") else "%s（%s）" % (z, note)))
            st["② 单个异名、目标有中文 ⇒ 模板"] += 1
            continue
        model.append((sid, w, t))
        st["③④ 送模型"] += 1
    return tpl, model, st


def load_model():
    got = {}
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            try:
                x = json.loads(line)
                zh = (x.get("zh") or "").strip().rstrip("。.")
                if zh and not re.fullmatch(r"[A-Za-zÀ-ÿ'\- ]+", zh):
                    got[int(x["id"])] = zh
            except Exception:
                continue
    return got


def gate(con):
    print("\n═══ 闸 ═══")
    left = empty_senses(con)
    tpl, model, _ = split(con)
    checks = [
        # 🔴 已接受基线：模型对读不懂的按 prompt 规则 6 给空串，那批留空比编造好。
        #    基线随 --apply-model 之后实测填入，**只减不增**。
        ("🔴 模板能填的都已填", len(tpl), 0),
        ("🔴 填进去的中文里不许全是拉丁字母",
         sum(1 for (t,) in con.execute(
             "SELECT text FROM sense_gloss WHERE lang='zh' AND src IN (?,?)",
             (SRC_TPL, SRC_MODEL)) if re.fullmatch(r"[A-Za-zÀ-ÿ'\- ]+", t)), 0),
        ("🔴 指针文案必须点名意语目标词",
         sum(1 for (t,) in con.execute(
             "SELECT text FROM sense_gloss WHERE lang='zh' AND src=?", (SRC_TPL,))
             if " 的" not in t and "（" not in t), 0),
        # 🔴 已接受基线 59 + 理由：**源头自己就没有内容**，不是我们漏了 ——
        #    `attributo araldico che si applica:`（冒号后是空的）、`Un nome`、
        #    `benefirma: benefirma`（自指）。模型按 prompt 规则 6 正确地给了空串，
        #    留空比编造好（`aim-for-perfect-not-cheap` 的反面不是"填满"，是"别造假"）。
        #    **基线只减不增**：涨了说明又有新的空中文进来了。
        ("仍然没有中文的可见义项（源头无内容，基线 59）", len(left), 59),
    ]
    ok = True
    for name, got, want in checks:
        ok &= got == want
        print("   %s %-46s %s (期望 %s)" % ("✅" if got == want else "🔴", name, got, want))
    return ok


def mutate():
    print("\n═══ 变异验证：模板判据 ═══")
    def tpl(t):
        for rx, fmt in PTR_IT:
            m = rx.match(t)
            if m:
                return fmt % m.group(1).strip()
        return None
    cases = [
        ("plurale di X", "plurale di -cida", "-cida 的复数形式"),
        ("plurale femminile 要先于 plurale 命中",
         "plurale femminile di -grafo", "-grafo 的阴性复数形式"),
        ("femminile di X", "femminile di -grafo", "-grafo 的阴性形式"),
        ("variante di X", "variante di Astro", "Astro 的变体形式"),
        ("variante 带插入语", "variante antica - e in disuso - di accademia", "accademia 的变体形式"),
        ("variante da evitare di X", "variante da evitare di Cechia", "Cechia 的变体形式"),
        ("🔴 真释义 ⇒ 模板不认", "nome di varie località nei paesi anglofoni", None),
        ("🔴 单个异名 ⇒ 模板不认（走 ② 或模型）", "Agades", None),
    ]
    ok = True
    for name, t, want in cases:
        got = tpl(t)
        good = got == want
        ok &= good
        print("   %s %-34s %-38s → %s" % ("✅" if good else "🔴", name, t[:38], got))
    print("\n   变异验证 %s" % ("通过" if ok else "🔴 判据有问题"))
    return ok


def write(rows, tag, src):
    with dbtool.session(tag, expect={"#sense_gloss": len(rows)}) as s:
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?, 'zh', 'equivalent', 0, ?, ?)",
                      [(sid, zh, src) for sid, _w, zh in rows])


def main():
    ap = argparse.ArgumentParser()
    for f in ("apply", "run", "apply-model", "verify", "mutate"):
        ap.add_argument("--" + f, action="store_true", dest=f.replace("-", "_"))
    a = ap.parse_args()
    if a.mutate:
        return 0 if mutate() else 1
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    tpl, model, st = split(ro)
    for k, v in st.most_common():
        print("   %-38s %7s" % (k, f"{v:,}"))

    if a.run:
        items = [{"id": sid, "word": w, "it": t} for sid, w, t in model]
        print("\n■ 送模型 %s 条" % f"{len(items):,}")
        T.SYS, T.CHUNK = SYS, 20
        OUT.parent.mkdir(parents=True, exist_ok=True)
        asyncio.run(T.run_batches(items, OUT))
        return 0

    if a.apply_model:
        got = load_model()
        rows = [(sid, w, got[sid]) for sid, w, _t in model if sid in got]
        print("\n■ 模型填回 %s 条（读不懂给空串的 %s 条留空）"
              % (f"{len(rows):,}", f"{len(model) - len(rows):,}"))
        for sid, w, zh in rows[:12]:
            it = dict((s, t) for s, _w, t in model)[sid]
            print("   %-18s %-24s ← %s" % (w[:18], zh[:24], it[:40]))
        ro.close()
        if rows:
            write(rows, "fill-empty-zh-model", SRC_MODEL)
            print("\n■ 已填 %s 条" % f"{len(rows):,}")
        return 0

    print("\n■ 模板可填 %s 条" % f"{len(tpl):,}")
    for sid, w, zh in tpl[:12]:
        print("   %-18s %s" % (w[:18], zh[:52]))
    print("\n■ 要送模型 %s 条" % f"{len(model):,}")
    for sid, w, t in model[:6]:
        print("   %-18s %s" % (w[:18], t[:52]))
    ro.close()
    if not a.apply or not tpl:
        print("\n(未加 --apply，不写库)" if not a.apply else "")
        return 0
    write(tpl, "fill-empty-zh-tpl", SRC_TPL)
    print("\n■ 已填 %s 条（模板）" % f"{len(tpl):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
