#!/usr/bin/env python3
"""阶段 1.5 第二段：把**能确定性对上**的意语释义从证据层提升到出版层。2026-08-13。

═══ 只提升一档：1:1 ═══
「意语版给 1 条 / 我们也只有 1 条」的词形。其余（③意语1我们多 / ④意语多我们1 /
⑤多对多，共约 6 万条）**一律留在证据层**，`sense_id` 保持 NULL。
两位顾问在这一档上意见一致：机械提升会把近义变体当成独立义项，出版层义项数虚高。

═══ 1:1 安全吗 —— 用第三方版本回答，不用模型 ═══
风险是「英文版只收了 A 义、意语版只收了 B 义，各一条正好凑成 1:1」，这是统计假象。
两位顾问都建议「词性一致」当门槛。实测词性一致率 93.1%，但**不一致的那批主要是
两版词类划分口径不同**（`noun→phrase` 712 / `name→noun` 123 / `num→adj` 71），
挡掉的是分类噪声，不是同形异义 ⇒ **词性门槛是必要条件，但远不是充分条件**。

真正的判据用**法语版**（第三方，意语义项 130 万条，我们已有切片）：
它对同一个词形给了几条义项 —— 给 1 条就是三方共同认为单义。实测 1:1 的 25,393 个词形：

    法语版也只 1 条 13,474 (53.1%) │ 法语版没收 10,997 (43.3%)
    法语版 2 条        802 ( 3.2%) │ 🔴 法语版 ≥3 条 120 (0.5%)  ← 唯一的真风险面

⇒ 提升判据 = **1:1 且词性一致 且 法语版义项数 < 3**。挡下的 120 个词形留在证据层记账。

═══ 落法 ═══
    sense_gloss(sense_id, lang='it', kind='definition', seq=0, text, src='it-edition')
    sense_src.sense_id ← 裁决完成（NULL → 具体 sense）
`kind='definition'` 是这一层的意义：它是**单语定义**，不是 `equivalent` 那种对应词。

用法（在 it/ 目录下）：
    python3 pipeline/promote_it_gloss.py            # 干跑，报分档
    python3 pipeline/promote_it_gloss.py --apply
    python3 pipeline/promote_it_gloss.py --verify
    python3 pipeline/promote_it_gloss.py --mutate
"""
import argparse
import gzip
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))
from strip_it_placeholder import clean, not_a_definition   # noqa: E402  共用同一把尺

SRC = "it-edition"
AFFIX_POS = {"prefix", "suffix", "infix", "interfix", "circumfix", "combining_form"}
FR_MAX = 3      # 法语版义项数 ≥ 这个值就判「多义、有风险」，不自动提升

# 变形指针的文本判据。🔴 只在**提升**时用，证据层收全（见 ingest_it_edition.py 的说明）。
# ⚠️ 第一版漏了三类，反向核对逮到的：目标是多词（`plurale di ospedale psichiatrico`）、
#    `vedi` 模板（`plurale, vedi acqua`）、`per` 模板（`forma arcaica o poetica per fiero`）。
#    残差按上界报：改到第二版就停手，剩下的当已知上界记账。
PTR = re.compile(
    r"^(prima |seconda |terza )?(persona )?"
    r"(singolare|plurale|maschile|femminile|participio|gerundio|infinito|imperativo|"
    r"indicativo|congiuntivo|condizionale|superlativo|diminutivo|accrescitivo|"
    r"vezzeggiativo|peggiorativo|dispregiativo|forma|voce)\b.{0,120}?\b(di|per|vedi)\s+.{1,40}$",
    re.IGNORECASE)


def pos_of_ref(ref):
    """kk-it:<词形>:<词性>#<occ>.<idx> → 词性。词形可能含 ':'，从右边切。"""
    return ref[len("kk-it:"):].rsplit("#", 1)[0].rsplit(":", 1)[1]


def fr_sense_counts(wanted):
    """法语版对这些词形各给了几条非指针义项。外部锚，确定性，免费。"""
    n = Counter()
    with gzip.open(paths.KK_FR, "rt", encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            w = (e.get("word") or "").strip().lower()
            if w not in wanted:
                continue
            pos = e.get("pos") or ""
            for s in (e.get("senses") or []):
                if (s.get("form_of") or s.get("alt_of")) and pos not in AFFIX_POS:
                    continue
                if not (s.get("glosses") or [""])[0].strip():
                    continue
                n[w] += 1
    return n


def classify(con):
    """→ (可提升 [(sense_id, src_id, text)], 分档统计, 被挡下的词形样例)"""
    ours = defaultdict(list)
    for wid, sid, pos in con.execute(
            "SELECT s.word_id, s.id, COALESCE(e.pos, s.pos) FROM sense s "
            "LEFT JOIN entry e ON e.id = s.entry_id WHERE COALESCE(s.hidden,0)=0"):
        ours[wid].append((sid, pos))
    its = defaultdict(list)
    stat = Counter()
    for sid_src, wid, ref, text, done in con.execute(
            "SELECT id, word_id, src_ref, text, sense_id FROM sense_src WHERE src=?", (SRC,)):
        if PTR.match(text):
            stat["变形指针·文本判定（提升时才滤，证据层保留）"] += 1
            continue
        # 🔴 占位符不是释义（`definizione mancante; se vuoi, aggiungila tu`）。
        #    `fixes/strip_it_placeholder.py` 已把它们从出版层删掉并撤回裁决；这里不滤，
        #    重跑就会把它们**原样灌回去** —— `replay-scripts-undo-fixes` 那个坑。
        #    但它们仍占「意语给了几条」的位置吗？不占：源头等于没写定义。
        if not_a_definition(text):
            stat["占位符·非释义（证据层保留，永不提升）"] += 1
            continue
        its[wid].append((sid_src, pos_of_ref(ref), text, done))

    word = {i: w for i, w in con.execute("SELECT id, word FROM dict")}
    one = {}
    for wid, lst in its.items():
        n_our = len(ours.get(wid, []))
        if n_our == 0:
            stat["① 我们没有可见义项"] += len(lst)
        elif len(lst) == 1 and n_our == 1:
            one[wid] = (lst[0], ours[wid][0])
        elif len(lst) == 1:
            stat["③ 意语1条 / 我们多条（留证据层）"] += len(lst)
        elif n_our == 1:
            stat["④ 意语多条 / 我们1条（留证据层）"] += len(lst)
        else:
            stat["⑤ 多对多（留证据层）"] += len(lst)

    fr = fr_sense_counts({word[w].lower() for w in one})
    out, held = [], []
    for wid, ((src_id, it_pos, text, done), (sid, our_pos)) in one.items():
        # 🔴 已裁决的不再处理。本脚本是**重放式**的：它按当前库重新分档，而分档结果
        #    会随后续阶段变化（2a 加 alt 义项、3b 给零义项词形建义项、占位符清理藏义项）。
        #    不挡这一条，重跑就会给已提升的 33,049 条再插一遍出版行。
        #    ⚠️ 但它们仍要参与上面的 1:1 计数 —— 一个词形已提升 1 条、还剩 1 条未提升，
        #       那是「意语 2 条」，不是 1:1。所以过滤只能放在这里，不能放在收集处。
        if done is not None:
            stat["已提升过（跳过，不重放）"] += 1
            continue
        if it_pos != our_pos:
            stat["🔴 1:1 但词性不一致（挡下）"] += 1
            continue
        if fr.get(word[wid].lower(), 0) >= FR_MAX:
            stat["🔴 1:1 但法语版判为多义（挡下）"] += 1
            if len(held) < 8:
                held.append((word[wid], fr[word[wid].lower()], text[:52]))
            continue
        stat["✅ 可提升"] += 1
        out.append((sid, src_id, clean(text)))   # 落库写清洗后的，闸① 认这个口径
    return out, stat, held


def nonunique(con):
    """已提升、但该词形其实有**多条**非指针非占位意语证据的 —— 不再满足 1:1，退回。

    🔴 为什么会有：`not_a_definition` 的判据改过三轮（`PITFALLS` A4 说三轮就停手），
       而它决定了「意语给了几条」。判据一收紧/一放宽，1:1 的人群就变。
       `dirimpettaio` 意语版实际给了两条**不同**定义（`chi si trova di fronte` /
       `chi si trova nell'edificio…`），当初另一条被占位符挡住才看着像 1:1。
    ⇒ 不再改判据，改成**让闸自愈**：违反不变量的退回证据层，归到 ④ 档统一处理。
    """
    n = Counter()
    for wid, text in con.execute("SELECT word_id, text FROM sense_src WHERE src=?", (SRC,)):
        if PTR.match(text) or not_a_definition(text):
            continue
        n[wid] += 1
    return [(sid, w) for sid, wid, w in con.execute(
        "SELECT g.sense_id, s.word_id, d.word FROM sense_gloss g "
        "JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id "
        "WHERE g.lang='it' AND g.kind='definition' AND s.entry_id IS NOT NULL")
        if n[wid] != 1]


def gate1(con, verbose=True):
    """闸① 出版层的每一条意语释义，必须与它的证据行**逐字节**相同、且指向同一条 sense。
    双向：证据行被裁决了就必须有出版行，有出版行就必须有被裁决的证据行。"""
    print("\n═══ 闸① 出版层 ↔ 证据层 回核（全量双向，非抽样）═══")
    ev = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT sense_id, text, src_ref FROM sense_src WHERE src=? AND sense_id IS NOT NULL",
        (SRC,))}
    pub = {r[0]: r[1] for r in con.execute(
        "SELECT sense_id, text FROM sense_gloss WHERE lang='it' AND kind='definition'")}
    # ⚠️ 出版层**可编辑**：占位符清理改写了文字（`fixes/strip_it_placeholder.py`）。
    #    所以判据不是"逐字节相同"，而是"等于证据文字**按同一规则清洗后**的结果" ——
    #    直接引用那边的 `clean`，不另写一套（两把尺是本项目最常见的假红/假绿来源）。
    bad = []
    for sid, (text, ref) in ev.items():
        if pub.get(sid) not in (text, clean(text)):
            bad.append(("已裁决的证据没有对应的出版行/文字不同", sid, text[:44], (pub.get(sid) or "")[:44]))
    for sid, text in pub.items():
        if sid not in ev:
            bad.append(("出版层有意语释义，证据层却没裁决过（凭空）", sid, "", text[:44]))
    print("   已裁决证据 %s 条 / 出版层意语释义 %s 条 / 不符 %d"
          % (f"{len(ev):,}", f"{len(pub):,}", len(bad)))
    for b in bad[:6]:
        print("     ✗ %s sense#%s\n        证据=%s\n        出版=%s" % b)
    print("   %s" % ("✅ 零不符" if not bad else "🔴 有不符"))
    return not bad


def gate2(con, n_expect=None):
    print("\n═══ 闸② 不变量断言 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    n = q("SELECT count(*) FROM sense_gloss WHERE lang='it' AND kind='definition'")

    # 函数内 import：`demote_alt_pointer_defs` 反过来要用本模块的 SRC，模块级会成环。
    from demote_alt_pointer_defs import is_pointer   # noqa: E402
    _ev_n = Counter()
    for wid, text in con.execute("SELECT word_id, text FROM sense_src WHERE src=?", (SRC,)):
        if PTR.match(text) or not_a_definition(text):
            continue
        _ev_n[wid] += 1
    _n_selfptr = sum(1 for text, target in con.execute(
        "SELECT g.text, r.target FROM sense_gloss g JOIN sense_relation r "
        "ON r.sense_id=g.sense_id AND r.kind='alt_of' "
        "WHERE g.lang='it' AND g.kind='definition'") if is_pointer(text, target))

    checks = [
        # ⚠️ 口径第三次修（2026-08-14）。前两版都是**锚自己上一版**型断言，必然过期：
        #    它们数「当前有几条义项」，而义项数被后续阶段一直改（2a 加 alt、3b 加零义项
        #    词形、占位符清理藏义项）。第三次红时终于看清 —— 断言「意语定义不许挂在 alt
        #    义项上」本身就是错的：意语版给 `anitra`（雁形目鸟类）、`granturco`（玉米）、
        #    `acquasanta`（圣水）写了**真定义**，而我们只有「anatra 的异体形式」这种废话，
        #    挂上去正是收意语版的目的。真该挡的是**指针文本**，不是"落在 alt 义项上"。
        #    ⇒ 改锚**证据层**（外部 dump 的投影，不随我们的阶段变化）：
        ("🔴 本脚本提升的意语定义，其证据是该词形唯一的非指针非占位意语证据",
         len(nonunique(con)), 0),
        # 判据与 `fixes/demote_alt_pointer_defs.py` **共用同一个函数**，不另写近似 SQL
        ("🔴 出版层不许有「指向自己 alt 目标」的意语定义", _n_selfptr, 0),
        ("🔴 一条 sense 最多一条意语定义",
         q("SELECT count(*) FROM (SELECT sense_id FROM sense_gloss WHERE lang='it' "
           "AND kind='definition' GROUP BY 1 HAVING count(*)>1)"), 0),
        ("意语释义的 src 都记为 it-edition",
         q("SELECT count(*) FROM sense_gloss WHERE lang='it' AND kind='definition' "
           "AND COALESCE(src,'')<>'it-edition'"), 0),
        ("被裁决的证据行数 == 出版层意语释义数",
         q("SELECT count(*) FROM sense_src WHERE src=? AND sense_id IS NOT NULL", SRC), n),
        ("🔴 已裁决的证据都必须有对应的出版释义（占位符清理要撤回裁决）",
         q("SELECT count(*) FROM sense_src x WHERE x.src=? AND x.sense_id IS NOT NULL "
           "AND NOT EXISTS(SELECT 1 FROM sense_gloss g WHERE g.sense_id=x.sense_id "
           "AND g.lang='it' AND g.kind='definition')", SRC), 0),
        # 🔴 这里原来写死了三个行数（396073/198049/290411）——「锚自己上一版」型断言，
        #    下一阶段一动数据就必然红。已换成**结构性**口径：本步只把 `sense_id` 从 NULL
        #    改成具体值、并加 lang='it' 的行，所以 en/zh 的行数与 sense 的行数由**别的**
        #    脚本的闸负责，这里只守自己该守的。
        ("🔴 意语定义不会多于意语证据（本步不凭空造释义）",
         q("SELECT count(*) FROM sense_gloss WHERE lang='it' AND kind='definition'")
         - q("SELECT count(*) FROM sense_src WHERE src=? AND sense_id IS NOT NULL", SRC), 0),
        ("裁决后的证据行，word_id 与它挂上的 sense 属于同一个词",
         q("SELECT count(*) FROM sense_src x JOIN sense s ON s.id=x.sense_id "
           "WHERE x.src=? AND x.word_id<>s.word_id", SRC), 0),
    ]
    if n_expect is not None:
        checks.insert(0, ("出版层意语释义条数 == 期望", n, n_expect))
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-50s %s (期望 %s)" % ("✅" if good else "🔴", name,
                                           f"{got:,}", f"{want:,}"))
    return ok


def _mut_overpromote(c2):
    """把一条「该词形有多条非指针意语证据」的证据提升上去 —— 违反 1:1，但证据链自洽，
    闸① 逮不到，只有新断言能逮。"""
    from collections import Counter as _C
    n = _C()
    for wid, text in c2.execute("SELECT word_id, text FROM sense_src WHERE src=?", (SRC,)):
        if not (PTR.match(text) or not_a_definition(text)):
            n[wid] += 1
    for xid, wid, text in c2.execute(
            "SELECT id, word_id, text FROM sense_src WHERE src=? AND sense_id IS NULL", (SRC,)):
        if n[wid] < 2 or PTR.match(text) or not_a_definition(text):
            continue
        row = c2.execute("SELECT id FROM sense WHERE word_id=? AND entry_id IS NOT NULL "
                         "AND id NOT IN (SELECT sense_id FROM sense_gloss WHERE lang='it' "
                         "AND kind='definition') LIMIT 1", (wid,)).fetchone()
        if not row:
            continue
        c2.execute("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                   "VALUES (?,'it','definition',0,?,?)", (row[0], text, SRC))
        c2.execute("UPDATE sense_src SET sense_id=? WHERE id=?", (row[0], xid))
        return True
    return False


def _mut_selfptr(c2):
    """把一条被 `demote_alt_pointer_defs` 退回的指针重新挂上去。"""
    from demote_alt_pointer_defs import is_pointer
    for xid, wid, text in c2.execute(
            "SELECT id, word_id, text FROM sense_src WHERE src=? AND sense_id IS NULL", (SRC,)):
        for sid, target in c2.execute(
                "SELECT s.id, r.target FROM sense s JOIN sense_relation r "
                "ON r.sense_id=s.id AND r.kind='alt_of' WHERE s.word_id=?", (wid,)):
            if is_pointer(text, target):
                c2.execute("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                           "VALUES (?,'it','definition',0,?,?)", (sid, text, SRC))
                c2.execute("UPDATE sense_src SET sense_id=? WHERE id=?", (sid, xid))
                return True
    return False


def mutate():
    import contextlib
    import io
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "m.sqlite"
    cases = [
        ("改掉一条出版层意语释义的一个字符",
         "UPDATE sense_gloss SET text=text||'x' WHERE lang='it' AND kind='definition' "
         "AND sense_id=(SELECT min(sense_id) FROM sense_gloss WHERE lang='it' AND kind='definition')"),
        ("删掉一条出版层意语释义（证据仍是已裁决）",
         "DELETE FROM sense_gloss WHERE lang='it' AND kind='definition' "
         "AND sense_id=(SELECT min(sense_id) FROM sense_gloss WHERE lang='it' AND kind='definition')"),
        ("凭空加一条出版层意语释义（证据层没裁决过）",
         "INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) SELECT s.id,'it','definition',0,"
         "'falso','it-edition' FROM sense s WHERE s.id NOT IN "
         "(SELECT sense_id FROM sense_gloss WHERE lang='it' AND kind='definition') LIMIT 1"),
        ("把一条证据挂到别的词的 sense 上",
         "UPDATE sense_src SET sense_id=(SELECT max(id) FROM sense) WHERE src='it-edition' "
         "AND sense_id IS NOT NULL AND id=(SELECT min(id) FROM sense_src WHERE src='it-edition' "
         "AND sense_id IS NOT NULL)"),
        ("给一个有多条义项的词挂上意语定义（越档提升）",
         "INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) SELECT s.id,'it','definition',0,"
         "'falso','it-edition' FROM sense s WHERE (SELECT count(*) FROM sense x "
         "WHERE x.word_id=s.word_id AND COALESCE(x.hidden,0)=0)>1 LIMIT 1"),
        # 🔴 下面两条专打**新加的**两条断言。不补它们，新断言就是没被验证过的绿灯 ——
        #    上面五条全是被闸① 逮的，跟新断言无关。
        ("越档提升：给「意语给了多条」的词提升其中一条（证据也一并裁决，绕开闸①）",
         _mut_overpromote),
        ("把一条指针定义重新挂回 alt 义项（证据也一并裁决）", _mut_selfptr),
    ]
    caught = 0
    for name, sql in cases:
        shutil.copy(paths.DB, tmp)
        c2 = sqlite3.connect(tmp)
        if callable(sql):
            if not sql(c2):     # 造不出这个变异 ⇒ 这条验证等于没跑，必须报出来
                print("   🔴 %-42s 造不出变异 —— 这条验证是空的" % name)
                c2.close()
                continue
        else:
            c2.execute(sql)
        c2.commit()
        c2.close()
        ro = sqlite3.connect("file:%s?mode=ro" % tmp, uri=True)
        with contextlib.redirect_stdout(io.StringIO()):
            red = not (gate1(ro) and gate2(ro))
        ro.close()
        caught += red
        print("   %s %-42s %s" % ("✅" if red else "🔴", name,
                                  "闸红了（对）" if red else "闸没红 —— 这条闸是假的"))
    print("\n   变异验证 %d/%d" % (caught, len(cases)))
    return caught == len(cases)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--demote-nonunique", action="store_true",
                    help="把不再满足 1:1 的已提升行退回证据层（闸自愈）")
    a = ap.parse_args()

    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if (gate1(ro) & gate2(ro)) else 1
    if a.mutate:
        return 0 if mutate() else 1
    if a.demote_nonunique:
        bad = nonunique(ro)
        print("■ 不再满足 1:1、退回证据层 %d 条" % len(bad))
        for sid, w in bad[:10]:
            print("   %s" % w)
        ro.close()
        if not bad:
            return 0
        with dbtool.session("demote-nonunique-it",
                            expect={"#sense_gloss": -len(bad)}) as s2:
            ids = [(sid,) for sid, _ in bad]
            s2.executemany("DELETE FROM sense_gloss WHERE sense_id=? AND lang='it' "
                           "AND kind='definition'", ids)
            s2.executemany("UPDATE sense_src SET sense_id=NULL WHERE sense_id=? AND src=?",
                           [(sid, SRC) for sid, _ in bad])
        return 0

    rows, stat, held = classify(ro)
    for k, v in stat.most_common():
        print("   %-42s %9s" % (k, f"{v:,}"))
    if held:
        print("\n   被法语版判为多义、挡下来的样例（留证据层）：")
        for w, n, t in held:
            print("      %-16s 法语版 %d 条  意语原文: %s" % (w, n, t))
    print("\n■ 将提升 %s 条意语定义到出版层" % f"{len(rows):,}")
    ro.close()
    if not a.apply:
        print("(未加 --apply，不写库)")
        return 0

    with dbtool.session("promote-it-gloss",
                        expect={"#sense_gloss": len(rows)}) as s:
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?,'it','definition',0,?,'it-edition')",
                      [(sid, text) for sid, _, text in rows])
        s.executemany("UPDATE sense_src SET sense_id=? WHERE id=?",
                      [(sid, src_id) for sid, src_id, _ in rows])
    print("\n■ 已提升 %s 条" % f"{len(rows):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
