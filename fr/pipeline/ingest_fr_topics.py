#!/usr/bin/env python3
"""族 C 第一段 — 收法文版的**领域标签**进 `sense_tag`。2026-08-27。

═══ 起因 ═══
外审指出 `cervelle`「大脑，脑」这个核心义被标成「路易斯安那 古语 贬义」。
回源查标签是怎么挂上去的，发现的问题比那一条大得多：

    两版都有标签的可见义项        25,861
      出版的标签 ⊆ 英语版           5,753
      两版都覆盖                   2,586
      ⊆ 法文版**独有**                 0     ← 一条都没有
      什么标签都没出版              17,522

**法文版的标签整批没有进出版层**，而里面正是法语特有的信息。
其中 `topics`（领域）一条都没收 —— 现有 `sense_tag` 只有 `region` 2,759 + `register` 15,101。

    法文版 topics：269 种 / 260,660 行，涉及 **243,052 条可见义项**

═══ 这一步只做 topics，**不动 region/register** ═══
🔴 我写过一版规则「法文版有标注却没标地区 ⇒ 撤掉英语版的 region」，量出 664 条该撤。
   逐条读立刻打回：`abacost` 法文版说 `['Centrafrique','Congo-Kinshasa']`、
   `smala` 说 `['Au Maghreb']` —— **它们都给了地区**，只是不在我手写的那张地区表里。
   `[[criteria-narrower-than-you-think]]`：判据比它要描述的东西更窄。
⇒ region/register 的优先级问题**留作记账**，等有了法语地区词表再做。
  本步是**纯增量**：只往 `sense_tag` 加 `kind='topic'` 的行，一条已有的都不碰。

═══ 只出版**映射得出中文**的值 ═══
契约闸有一条「义项的地区/语域标签都要能映射成中文」。收进来却映射不出，
用户看到的就是 `ornithology` 这种英文原始串 —— 那比不收更坏。
⇒ 判据 = 值在 `packages/dict-labels` 的 `TOPIC_LABELS` 里。
  实测该表已覆盖 95.3% 的行，2026-08-27 补了 12 个键后到 **99%**。
  映射不出的记账，不出版。

用法（在 fr/ 目录下）：
    python3 -u pipeline/ingest_fr_topics.py            # 只报数
    python3 -u pipeline/ingest_fr_topics.py --apply    # 落库
    python3 -u pipeline/ingest_fr_topics.py --undo     # 撤回（删 kind='topic' 的行）
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import dbtool                                    # noqa: E402
import paths                                     # noqa: E402

f = lambda n: format(n, ",")
LABELS = HERE.parent.parent / "packages" / "dict-labels" / "src" / "common.ts"
# 🔴 一行里有多个 `key: '值'`，**必须全局扫不能只匹配行首** ——
#    第一版只匹配行首，把 `geography`/`botany`/`chemistry` 全算成"缺映射"，
#    于是"要补 135 个键"，真值是 12 个。量错了整整一个数量级。
# 🔴 **第二次**：改成全局扫之后 `^` 没开 `re.M`，于是**行首**的键又漏了 ——
#    `linguistic` 明明刚加进表里，闸却报它"映射不出"（3,897 行）。
#    ⇒ `re.M` 不能省。写在这儿是因为我在这个文件的注释里刚记过一遍还是犯了。
KV = re.compile(r"(?:^|[{,])\s*'?([A-Za-z0-9À-ÿ' \-’.]+?)'?\s*:\s*'", re.M)


def topic_keys():
    """`TOPIC_LABELS` 里的键。**判据只许一份** —— 读那张表本身，不在这里抄一份。"""
    s = LABELS.read_text(encoding="utf-8")
    i = s.index("export const TOPIC_LABELS")
    return {m.group(1).strip() for m in KV.finditer(s[i:s.index("\n};", i)])}


def plan(con):
    """→ (rows, ledger, st)；rows = [(sense_id, 'topic', value)]"""
    keys = topic_keys()
    vis = {s for (s,) in con.execute("SELECT id FROM sense WHERE hidden=0")}
    have = {(s, k, v) for s, k, v in con.execute(
        "SELECT sense_id, kind, value FROM sense_tag")}
    st, ledger = Counter(), Counter()
    seen = set()
    for sid, raw in con.execute(
            "SELECT sense_id, raw_tags FROM sense_src "
            "WHERE src='fr-edition' AND sense_id IS NOT NULL"):
        if sid not in vis:
            st["📋 义项已隐藏 ⇒ 跳过"] += 1
            continue
        try:
            d = json.loads(raw or "{}")
        except ValueError:
            st["🔴 raw_tags 解析失败"] += 1
            continue
        for t in (d.get("topics") or []):
            if t not in keys:
                ledger[t] += 1
                continue
            if (sid, "topic", t) in have:
                st["已有同样的行 ⇒ 跳过"] += 1
                continue
            if (sid, t) in seen:
                continue
            seen.add((sid, t))
            st["可新增"] += 1
    rows = [(s, "topic", t) for s, t in sorted(seen)]
    return rows, ledger, st


def gates(con, rows, ledger):
    ok = True

    def g(name, bad, n):
        nonlocal ok
        print("  %s %s：%s / %s" % ("✅" if not bad else "🔴", name, f(bad), f(n)))
        if bad:
            ok = False

    keys = topic_keys()
    g("① 每条新行的值都映射得出中文", sum(1 for _s, _k, v in rows if v not in keys), len(rows))
    vis = {s for (s,) in con.execute("SELECT id FROM sense WHERE hidden=0")}
    g("② 只挂在可见义项上", sum(1 for s, _k, _v in rows if s not in vis), len(rows))
    g("③ kind 全是 topic（本步不碰 region/register）",
      sum(1 for _s, k, _v in rows if k != "topic"), len(rows))
    have = {(s, k, v) for s, k, v in con.execute(
        "SELECT sense_id, kind, value FROM sense_tag")}
    g("④ 不与已有行重复（PRIMARY KEY 会拦，但先自己拦）",
      sum(1 for r in rows if r in have), len(rows))
    tot = sum(ledger.values())
    print("  ℹ️ 映射不出中文、**不出版**的：%s 行 / %s 种" % (f(tot), f(len(ledger))))
    for k, v in ledger.most_common(8):
        print("       %-24s %s" % (k, f(v)))
    return ok


def undo():
    with dbtool.session("keep-v3-fr-topics-undo", expect={}) as s:
        n = s.execute("SELECT COUNT(*) FROM sense_tag WHERE kind='topic'").fetchone()[0]
        s.execute("DELETE FROM sense_tag WHERE kind='topic'")
    print("✓ 已撤回 %s 行" % f(n))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo", action="store_true")
    a = ap.parse_args()
    if a.undo:
        return undo()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    rows, ledger, st = plan(con)
    print("■ 可新增 topic 标签 %s 行，涉及 %s 条可见义项"
          % (f(len(rows)), f(len({s for s, _k, _v in rows}))))
    for k, v in st.most_common(6):
        print("   %-30s %s" % (k, f(v)))
    print("   现有 sense_tag %s 行" %
          f(con.execute("SELECT COUNT(*) FROM sense_tag").fetchone()[0]))
    print("\n── 新增值分布（前 14）──")
    c = Counter(v for _s, _k, v in rows)
    for k, v in c.most_common(14):
        print("   %-20s %s" % (k, f(v)))
    print("\n══ 闸 ══")
    ok = gates(con, rows, ledger)
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 闸未过，**不写库**")
        return 1
    with dbtool.session("keep-v3-fr-topics", expect={"#sense_tag": len(rows)}) as s:
        s.executemany("INSERT INTO sense_tag(sense_id,kind,value) VALUES(?,?,?)", rows)
    print("✓ 写入 %s 行" % f(len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
