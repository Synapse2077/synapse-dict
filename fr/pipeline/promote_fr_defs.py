#!/usr/bin/env python3
"""阶段 1.5 第二段(a)：把**能确定性裁决**的法语释义提升到出版层。2026-08-22。

═══ 分桶（写库前实测，不是早上那份）═══
1.5 第一段灌进 `sense_src` 的 **697,814** 条法语释义，逐条问「能不能确定性挂」：

| 桶 | 条数 | 占比 | 处置 |
|---|---:|---:|---|
| **桶0：该词形一条出版义项都没有** | **510,970** | 73.2% | **法语释义直接建义项**（免费）|
| **桶①：真 1:1**（我们 1 条 · 法文版也只 1 条，同词性）| **47,072** | 6.7% | **确定性挂**（免费）|
| 桶①'：我们 1 条 · **法文版多条** | 64,508 | 9.2% | 🔴 要裁决，本步不动 |
| 桶③：同词性多条 | 63,590 | 9.1% | 🔴 要裁决，本步不动 |
| 桶② 我们没有这个词性 | 11,594 | 1.7% | 不挂，记账 |
| 查不到 `entry.pos` | 80 | 0.0% | 记账 |

⇒ **本步处理 558,042 条（80.0%），零模型调用。**

🔴🔴 **桶① 整个被撤掉了 —— 它根本不是"确定性"的。**

第一版判据是「我们这个词性下只有 1 条义项」；收紧成「两边都只有 1 条」之后我以为稳了。
**写完库一看样本，错得很明显**：

    ore     zh=矿石，矿砂       ← fr: Contrevent au côté opposé à la tuyère…（锻炉部件）
    telon   zh=（古代）关税，税关  ← fr: Ancienne sorte d'étoffe.（一种旧布料）
    traper  zh=设陷阱捕捉，诱捕    ← fr: Grossir (se dit des melons).（瓜类膨大）

**词性对得上、两边各一条，但根本不是同一个义项** —— 我们那一条义项本来就不全，
法文版讲的是这个词的**另一个**意思。
⇒ 「结构上 1:1」推不出「语义上同一条」。**这是判据比它要描述的东西宽的又一例，
   而且这次错的是"确定性、免费"这个定性本身。**
⇒ 桶① 的 47,072 条**改归裁决桶**（与桶③ 同批处理，必须允许「一条都挂不上」）。
   `[[verification-gates-not-sampling]]` 用户原话：「不要把义项和释义错配了，那才是真灾难」。
   it 那轮的 `sbandamento` 是同一个教训：**必须允许一条都挂不上**。

⇒ **本步只做桶0**：该词形一条出版义项都没有 ⇒ 法语释义直接建义项。
   那里不存在"挂到哪一条"的问题，**才是真正确定性的**。

═══ 🔴 记账：2,004 条（0.29%）其实是变形说明，源头漏标 `form_of` ═══
拿 `fr_infl_parse.parse()` 当探测器扫了一遍待裁决的 697,814 条，
**2,004 条能被变形解析器识别** —— 也就是说源头把变形说明写成了释义、又没打 `form_of` 标记：

    les        Pluriel de le ou la.
    aucune     Féminin singulier de aucun.
    contenu    Participe passé du verbe contenir.

⚠️ **但本步不排除它们**，理由是探测器自己有假阳性：
    première   "masculin et féminin identiques Élève de cette classe."
               ← 这是**真释义**，只因为以 `masculin` 开头被宽松分支匹配了。
排除会误伤真释义，而收进来的是**源头逐字原文**、不是我编的。
⇒ 记账，交给后面用更严的判据处理（要求模板把整句吃掉，而不是只匹配开头）。
**判据改到第三轮就停手**（`[[measure-landing-not-source]]`）。

═══ 桶0 建出来的义项**没有中文** ═══
本步只搬法语原文（`sense_gloss(lang='fr', kind='definition')`）。
中文要靠翻译，那是第二段(b) 的事、也是唯一花钱的地方。
⇒ 做完这一步，那 42 万个空词条会**显示法语释义但没有中文** ——
   比空着强，但**对中文用户仍不是成品**。这一点不含糊。

用法（在 fr/ 目录下）：
    python3 pipeline/promote_fr_defs.py            # 干跑
    python3 pipeline/promote_fr_defs.py --apply
    python3 pipeline/promote_fr_defs.py --verify
"""
import argparse
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

SRC = "fr-edition"


def plan(con):
    """→ (桶0 行, 桶① 行, 统计)。两桶都只含**确定性**的。"""
    ours = defaultdict(lambda: defaultdict(list))
    for sid, wid, pos in con.execute("SELECT id, word_id, pos FROM sense"):
        ours[wid][pos or ""].append(sid)
    maxrank = defaultdict(int)
    for wid, r in con.execute("SELECT word_id, max(rank) FROM sense GROUP BY word_id"):
        maxrank[wid] = r

    rows = list(con.execute(
        "SELECT x.id, x.word_id, x.text, e.pos, e.id FROM sense_src x "
        "LEFT JOIN entry e ON e.src_ref = substr(x.src_ref, 1, instr(x.src_ref, '.') - 1) "
        "WHERE x.src=? AND x.sense_id IS NULL ORDER BY x.id", (SRC,)))
    # 法文证据在 (word_id, pos) 上的条数 —— 桶① 的 1:1 判据要用
    frn = Counter((wid, pos) for _, wid, _, pos, _ in rows)

    # 🔴 已经带了法语 definition 的义项**不能再挂第二条** ——
    #    阶段 1.5 补丁刚回收的 12,753 条 alt_of 义项就自带法语原文。
    #    第一版没排除，`UNIQUE(sense_id,lang,kind,seq)` 在插入时当场拦住并 rollback。
    #    这正是那道唯一约束该做的事：它拦下的就是"同一条义项两份法语释义"。
    has_fr = {r[0] for r in con.execute(
        "SELECT sense_id FROM sense_gloss WHERE lang='fr' AND kind='definition'")}

    b0, b1, stat = [], [], Counter()
    for xid, wid, text, pos, eid in rows:
        by = ours.get(wid)
        if not by:
            b0.append((xid, wid, text, pos or "", eid))
            stat["桶0：本无义项 ⇒ 建义项"] += 1
            continue
        if pos is None:
            stat["🔴 查不到 entry.pos（记账）"] += 1
            continue
        n_our = len(by.get(pos, []))
        if n_our == 0:
            stat["桶②：我们没有这个词性（不挂，记账）"] += 1
        elif n_our == 1 and frn[(wid, pos)] == 1:
            tgt = by[pos][0]
            if tgt in has_fr:
                stat["🔴 目标义项已带法语释义（多为 alt_of 回收的）⇒ 不挂"] += 1
            else:
                # 🔴 不再挂：结构 1:1 ≠ 语义同一条（见文件头）。归裁决桶。
                stat["🔴 桶①：结构 1:1 但语义未验 ⇒ 归裁决桶，本步不挂"] += 1
        elif n_our == 1:
            stat["🔴 桶①'：我们1条·法文版多条 ⇒ 要裁决"] += 1
        else:
            stat["🔴 桶③：同词性多条 ⇒ 要裁决"] += 1
    return b0, b1, stat, maxrank


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return verify(con)

    b0, b1, stat, maxrank = plan(con)
    tot = sum(stat.values())
    for k, v in sorted(stat.items(), key=lambda x: -x[1]):
        print("   %-42s %9s  %5.1f%%" % (k, f"{v:,}", 100.0 * v / tot))
    print("\n■ 本步处理 %s 条（%.1f%%），零模型调用"
          % (f"{len(b0) + len(b1):,}", 100.0 * (len(b0) + len(b1)) / tot))

    print("\n── 桶0 样本（法语释义将成为该词的第一条义项）──")
    w_of = dict(con.execute("SELECT id, word FROM dict"))
    for xid, wid, text, pos, eid in b0[:6]:
        print("   %-22s [%s] %s" % (w_of.get(wid, "?")[:22], pos, text[:56]))
    print("── 桶① 样本（法语释义将挂到已有义项上）──")
    for xid, sid, text in b1[:6]:
        en = con.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang='en'",
                         (sid,)).fetchone()
        zh = con.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang='zh'",
                         (sid,)).fetchone()
        print("   已有 en=%-28s zh=%-14s ← fr: %s"
              % ((en[0] if en else "—")[:28], (zh[0] if zh else "—")[:14], text[:44]))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    nid = con.execute("SELECT max(id) FROM sense").fetchone()[0]
    senses, glosses, link = [], [], []
    for xid, wid, text, pos, eid in b0:
        nid += 1
        maxrank[wid] += 1
        senses.append((nid, wid, maxrank[wid], pos, eid))
        glosses.append((nid, "fr", "definition", 0, text, SRC))
        link.append((nid, xid))
    for xid, sid, text in b1:
        glosses.append((sid, "fr", "definition", 0, text, SRC))
        link.append((sid, xid))
    print("\n■ 将写入：新义项 %s / 法语 gloss %s / 证据挂载 %s"
          % (f"{len(senses):,}", f"{len(glosses):,}", f"{len(link):,}"))
    con.close()

    with dbtool.session("keep-v3-promote-fr",
                        expect={"#sense": len(senses), "#sense_gloss": len(glosses)}) as s:
        s.executemany("INSERT INTO sense (id,word_id,rank,pos,entry_id) VALUES (?,?,?,?,?)",
                      senses)
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?,?,?,?,?,?)", glosses)
        s.executemany("UPDATE sense_src SET sense_id=? WHERE id=?", link)

    return verify(sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True))


def verify(con):
    print("\n═══ 闸 ═══")
    q = lambda s: con.execute(s).fetchone()[0]
    checks = [
        ("rank 不从 1 连续的词形",
         q("SELECT count(*) FROM (SELECT word_id FROM sense GROUP BY word_id "
           "HAVING max(rank)<>count(*) OR min(rank)<>1)"), 0),
        ("没有任何 gloss 的 sense",
         q("SELECT count(*) FROM sense s LEFT JOIN sense_gloss g ON g.sense_id=s.id "
           "WHERE g.sense_id IS NULL"), 0),
        ("孤儿 sense", q("SELECT count(*) FROM sense s LEFT JOIN dict d ON d.id=s.word_id "
                         "WHERE d.id IS NULL"), 0),
        ("挂到不存在 sense 上的证据",
         q("SELECT count(*) FROM sense_src x LEFT JOIN sense s ON s.id=x.sense_id "
           "WHERE x.sense_id IS NOT NULL AND s.id IS NULL"), 0),
        # 🔴 撤掉桶① 之后这个数不该再变。上一版它从 58 掉到 31 ——
        #    正是桶① 把法语证据挂到了 27 条阶段 0 的中文孤儿上，而抽样一看**挂错了**。
        #    数字往"好"的方向动也要查：**58→31 看着像进步，其实是 27 条错配。**
        ("🔴 无 sense_src 的 sense == 58（阶段 0 的中文孤儿，本步不该动它）",
         q("SELECT count(*) FROM sense s LEFT JOIN sense_src x ON x.sense_id=s.id "
           "WHERE x.sense_id IS NULL"), 58),
        # 🔴 本步的核心断言：**一条已有义项上不许挂多于一条法语释义**。
        #    挂多条就意味着我把"法文版给的几条"当成了同一个义项 —— 那正是收紧判据要防的。
        ("🔴 同一义项挂了多条法语 definition",
         q("SELECT count(*) FROM (SELECT sense_id FROM sense_gloss "
           "WHERE lang='fr' AND kind='definition' GROUP BY sense_id HAVING count(*)>1)"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %10s  期望 %s" % ("✓" if good else "🔴", name, f"{got:,}", f"{want:,}"))
    dead = q("SELECT count(*) FROM dict d LEFT JOIN sense s ON s.word_id=d.id "
             "LEFT JOIN inflection i ON i.word_id=d.id WHERE s.id IS NULL AND i.id IS NULL")
    nozh = q("SELECT count(*) FROM sense s "
             "LEFT JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh' "
             "WHERE g.sense_id IS NULL")
    print("\n■ 既无义项也无变形的 dict 行：{:,}".format(dead))
    print("■ 🔴 **没有中文**的出版义项：{:,}（要靠第二段(b) 翻译）".format(nozh))
    print("%s" % ("✓ 闸全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
