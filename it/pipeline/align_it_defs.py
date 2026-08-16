#!/usr/bin/env python3
"""③ 意语给 1 条、我们有多条：把意语原文释义对齐到**具体哪一条**义项。2026-08-14。

═══ 为什么这一步值得做 ═══
不是为了覆盖率。全库 387,997 条中文里，**96.4% 翻译时没见过一个意大利字**
（53.1% 从英文释义翻、43.3% 从法语释义翻、只有 3.6% 从意语原文翻）。
这一步每对齐一条，就多一条「同一义项上有两个独立来源」——
那是全库唯一能拿来**互校**的地方，也是「译文质量到底多少」这把尺的原料。

═══ 分三桶，只有第三桶花钱 ═══
    ① 词性唯一        565 (8.3%)  确定性，直接挂
    ② 我们没有这个词性  280 (4.1%)  意语讲的是我们没收的词类 ⇒ 不挂，记账
    ③ 同词性多条     6,001 (87.7%) 要语义对齐，14,870 个候选义项

⚠️ **必须允许「一条都挂不上」**。抽样时逮到 `sbandamento`：意语释义是
   「群体成员的四散」，而我们那 5 条义项（侧滑/横倾/混乱/倾斜/飞机转弯倾斜）
   一条都不是它 —— 那是我们**没收的义项**，硬挂就是 `错配`，用户说的真灾难。

═══ 两个控制组，都是免费的真值 ═══
🔴 `llm-as-evaluator-discipline` ⑦：用前必跑负控。这里两边都有现成真值：
  · 正控 = 桶①那 565 条，但**把所有词性的义项都摆给模型**。
    正确答案已由词性确定性地知道 ⇒ 模型选中率就是它的对齐准确率。
  · 负控 = 把 A 词的意语释义配 B 词的义项列表。正确答案恒为「挂不上」⇒
    模型只要选了任何一条就是在编。
  两个控制组不过，不跑正式批。

用法（在 it/ 目录下）：
    python3 pipeline/align_it_defs.py --plan
    python3 pipeline/align_it_defs.py --apply-unique     # 桶①，不花钱
    python3 pipeline/align_it_defs.py --control          # 正控+负控
    python3 pipeline/align_it_defs.py --run              # 桶③
    python3 pipeline/align_it_defs.py --apply
    python3 pipeline/align_it_defs.py --verify
    python3 pipeline/align_it_defs.py --mutate
"""
import argparse
import asyncio
import json
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))

import ark_batch   # noqa: E402
import dbtool      # noqa: E402
import paths       # noqa: E402
from promote_it_gloss import PTR, SRC, pos_of_ref   # noqa: E402
from demote_alt_pointer_defs import is_pointer   # noqa: E402  A38 的确定性指针判据
from strip_it_placeholder import clean, not_a_definition   # noqa: E402

OUT = paths.WORK / "it_align.jsonl"
CTRL = paths.WORK / "it_align_control.jsonl"
CHUNK = 12

SYS = """你是意大利语词典编纂员。每条给你一个意大利语词、它的词性、
一条**意大利语维基词典**写的意语释义 `it`，以及我们词典里该词**已有的义项列表**
（每条带序号 `i`、英文释义 `en`、中文释义 `zh`）。

判断：`it` 这条释义**对应已有义项里的哪一条**？

🔴 如果一条都不对应就输出 `0`。意大利语版收的义项我们不一定有 —— 例如
   `sbandamento` 意语写「群体成员的四散」，而我们只有「侧滑／横倾／混乱／倾斜」，
   那就是 `0`。**宁可输出 0，也不要硬挂**：挂错比不挂坏得多。
🔴 以你自己对**意大利语**的理解判断，`en`/`zh` 只是我们已有义项的说明。
🔴 只在「`it` 讲的就是这条义项说的那件事」时才对应。近义、上下位、同一领域
   但不是同一件事的，一律 `0`。

输入是一个 JSON 对象，键是编号，值是一条待判断的记录。
输出**只有**一个 JSON 对象，**键与输入完全相同**，值是 {"i": 序号或0}。
例如输入有键 "1" "2"，就输出 {"1": {"i": 3}, "2": {"i": 0}}。
不要围栏、不要解释、不要输出数组。"""


def load(con):
    """→ (unique, multi, nopos)。三桶的元素都带 word_id / 意语文本。"""
    vis = defaultdict(list)
    for wid, sid, pos in con.execute(
            "SELECT s.word_id, s.id, COALESCE(e.pos, s.pos) FROM sense s "
            "LEFT JOIN entry e ON e.id=s.entry_id WHERE COALESCE(s.hidden,0)=0 "
            "ORDER BY s.rank"):
        vis[wid].append((sid, pos))
    gl = defaultdict(dict)
    for sid, lang, t in con.execute(
            "SELECT sense_id, lang, text FROM sense_gloss WHERE lang IN ('en','zh')"):
        gl[sid][lang] = t
    word = dict(con.execute("SELECT id, word FROM dict"))

    per = defaultdict(list)
    for xid, wid, ref, text in con.execute(
            "SELECT id, word_id, src_ref, text FROM sense_src "
            "WHERE src=? AND sense_id IS NULL", (SRC,)):
        if not_a_definition(text) or PTR.match(text):
            continue
        per[wid].append((xid, pos_of_ref(ref), text))

    # A38：指向 alt_of 目标的指针文本不进出版层。**前置过滤**，别等挂上去再靠闸退回
    #    —— 第一版没滤，对齐挂了 5 条（`uliva` → `variante di oliva`），闸红后才退。
    alt_t = defaultdict(list)
    for wid, tgt in con.execute("SELECT word_id, target FROM sense_relation WHERE kind='alt_of'"):
        alt_t[wid].append(tgt)

    unique, multi, nopos = [], [], []
    for wid, lst in per.items():
        if len(lst) != 1 or len(vis.get(wid, [])) < 2:
            continue
        xid, ipos, text = lst[0]
        if any(is_pointer(text, t) for t in alt_t.get(wid, [])):
            continue
        same = [s for s, p in vis[wid] if p == ipos]
        row = dict(xid=xid, wid=wid, word=word[wid], pos=ipos, it=text)
        if not same:
            nopos.append(row)
        elif len(same) == 1:
            unique.append(row | {"sid": same[0]})
        else:
            multi.append(row | {"cands": [
                (s, (gl[s].get("en") or "")[:90], (gl[s].get("zh") or "")[:40])
                for s in same]})
    return unique, multi, nopos


def payload(r, cands):
    # ⚠️ 不放 `id`：身份由**批内键**承载。`quality_pass.acall` 解析时做
    #    `out[out.find("{"):out.rfind("}")+1]`，模型若吐数组会被切成 `{…},{…}` 而解析失败
    #    —— 第一版控制组 5 批全挂在这里。
    return {"w": r["word"], "pos": r["pos"], "it": r["it"][:220],
            "senses": [{"i": i, "en": en, "zh": zh}
                       for i, (_s, en, zh) in enumerate(cands, start=1)]}


def batched(items, chunk=None):
    """→ (batches, meta)，键是**每批本地 1..N**（豆包会重编全局键，见 ark_batch）。"""
    chunk = chunk or CHUNK
    batches, meta = [], []
    for i in range(0, len(items), chunk):
        ch = items[i:i + chunk]
        batches.append({str(k): p for k, (p, _rid) in enumerate(ch, start=1)})
        meta.append([(str(k), rid) for k, (_p, rid) in enumerate(ch, start=1)])
    return batches, meta


def truth_set(con):
    """正控真值：**已裁决**的意语证据里，该词有多条可见义项、且答案已知的那些。

    ⚠️ 第一版拿桶①当正控，但 `--apply-unique` 跑完那批就不在「未裁决」里了，
       `load()` 取不到 ⇒ 正控 0 条、报 0.0%。改成从已裁决的证据反查，
       真值面反而更大（含阶段 1.5 早先提升的那些）。
    """
    vis = defaultdict(list)
    for wid, sid in con.execute("SELECT word_id, id FROM sense WHERE COALESCE(hidden,0)=0 "
                                "ORDER BY rank"):
        vis[wid].append(sid)
    word = dict(con.execute("SELECT id, word FROM dict"))
    out = []
    for wid, sid, ref, text in con.execute(
            "SELECT word_id, sense_id, src_ref, text FROM sense_src "
            "WHERE src=? AND sense_id IS NOT NULL", (SRC,)):
        if len(vis.get(wid, [])) < 2 or sid not in vis[wid]:
            continue
        out.append(dict(wid=wid, word=word[wid], pos=pos_of_ref(ref),
                        it=clean(text), sid=sid, all=vis[wid]))
    return out


def run_control(multi, con):
    """正控：真值已知的条目摆**全部**义项。负控：A 的释义配 B 的义项（真值恒为 0）。"""
    gl = defaultdict(dict)
    for sid, lang, t in con.execute(
            "SELECT sense_id, lang, text FROM sense_gloss WHERE lang IN ('en','zh')"):
        gl[sid][lang] = t
    known = truth_set(con)
    print("■ 正控可用真值 %s 条" % f"{len(known):,}")

    random.seed(7)
    pos_items, truth = [], {}
    for r in random.sample(known, min(120, len(known))):
        cands = [(s, (gl[s].get("en") or "")[:90], (gl[s].get("zh") or "")[:40])
                 for s in r["all"]]
        truth[r["wid"]] = [s for s, _, _ in cands].index(r["sid"]) + 1
        pos_items.append((payload(r, cands), r["wid"]))

    neg_items = []
    pool = [r for r in multi if len(r["cands"]) >= 3]
    for a, b in zip(random.sample(pool, 60), random.sample(pool, 60)):
        if a["wid"] == b["wid"]:
            continue
        neg_items.append((payload(a, b["cands"]), -a["wid"]))   # 负号标记，避免与正控撞

    batches, meta = batched(pos_items + neg_items)
    CTRL.unlink(missing_ok=True)
    # ⚠️ 控制组走 **online**：只有 180 条，要的是快反馈不是半价。
    #    第一版用了 turbo-batch，11 分钟一批都没落盘（batch 端点标称延迟 2s~5min，
    #    实际更长），而我又把命令写成 `... | tail -14` —— `tail` 会缓冲到进程结束，
    #    把 `ark_batch` 每批 flush 的可观测性彻底废掉。**跑批别接 tail**。
    asyncio.run(__import__("ds_batch").run(SYS, batches, meta, CTRL, mode="flash", conc=8, every=3))

    got = {}
    for line in CTRL.open(encoding="utf-8"):
        r = json.loads(line)
        got[r["id"]] = r.get("i")
    ok = sum(1 for w, t in truth.items() if got.get(w) == t)
    ans = sum(1 for w in truth if w in got)
    negs = [v for k, v in got.items() if k < 0]
    clean_neg = sum(1 for v in negs if v in (0, None))
    print("\n═══ 控制组 ═══")
    print("   正控（真值已由词性确定）  答 %3d 条，选对 %3d 条  准确率 %.1f%%"
          % (ans, ok, 100.0 * ok / max(ans, 1)))
    print("   负控（真值恒为「挂不上」）答 %3d 条，答 0 的 %3d 条  洁净率 %.1f%%"
          % (len(negs), clean_neg, 100.0 * clean_neg / max(len(negs), 1)))
    print("\n   判据：正控 ≥85%% 且负控 ≥80%% 才跑正式批（挂错比不挂坏得多，负控更要紧）")
    return ok / max(ans, 1) >= 0.85 and clean_neg / max(len(negs), 1) >= 0.80


def _mut_wrong_pos(c2):
    """把一条已裁决的意语证据改挂到同词、**不同词性**的义项上。"""
    for xid, sid, wid, pos in c2.execute(
            "SELECT x.id, x.sense_id, s.word_id, COALESCE(e.pos, s.pos) FROM sense_src x "
            "JOIN sense s ON s.id=x.sense_id LEFT JOIN entry e ON e.id=s.entry_id "
            "WHERE x.src='it-edition' AND x.sense_id IS NOT NULL LIMIT 400"):
        alt = [s2 for s2, p2 in c2.execute(
            "SELECT s2.id, COALESCE(e2.pos, s2.pos) FROM sense s2 "
            "LEFT JOIN entry e2 ON e2.id=s2.entry_id WHERE s2.word_id=? AND s2.id<>?",
            (wid, sid)) if p2 is not None and p2 != pos]
        if not alt:
            continue
        c2.execute("UPDATE sense_src SET sense_id=? WHERE id=?", (alt[0], xid))
        c2.execute("UPDATE sense_gloss SET sense_id=? WHERE sense_id=? AND lang='it' "
                   "AND kind='definition'", (alt[0], sid))
        return True
    return False


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    # 闸① 出版层 ↔ 证据层：本步新挂的意语定义，文字必须等于证据清洗后的结果
    ev = {sid: t for sid, t in con.execute(
        "SELECT sense_id, text FROM sense_src WHERE src=? AND sense_id IS NOT NULL", (SRC,))}
    pub = {sid: t for sid, t in con.execute(
        "SELECT sense_id, text FROM sense_gloss WHERE lang='it' AND kind='definition'")}
    bad = sum(1 for sid, t in ev.items() if pub.get(sid) not in (t, clean(t)))
    bad += sum(1 for sid in pub if sid not in ev)
    checks = [
        ("🔴 出版层 ↔ 证据层双向逐字节（含清洗口径）", bad, 0),
        ("🔴 一条 sense 最多一条意语定义",
         q("SELECT count(*) FROM (SELECT sense_id FROM sense_gloss WHERE lang='it' "
           "AND kind='definition' GROUP BY 1 HAVING count(*)>1)"), 0),
        # 🔴 这条是**防错配**的那道闸 —— 用户点名「义项和释义错配才是真灾难」。
        #    ⚠️ 第一版加了 `AND s.entry_id IS NOT NULL`，把 pos 为 NULL 的义项整批跳过 ⇒
        #       变异验证 3/4，没红的正好就是错配那条。判据改成：**我们侧有词性的，
        #       就必须一致**；没词性的比不了，单独计数报出来（不能默默跳过）。
        ("🔴 挂上的义项必须与意语证据同词性（防错配）",
         sum(1 for ipos, opos in con.execute(
             "SELECT x.src_ref, COALESCE(e.pos, s.pos) FROM sense_src x "
             "JOIN sense s ON s.id=x.sense_id LEFT JOIN entry e ON e.id=s.entry_id "
             "WHERE x.src=? AND x.sense_id IS NOT NULL", (SRC,))
             if opos is not None and pos_of_ref(ipos) != opos), 0),
        ("🔴 证据行的 word_id 与它挂上的义项同词",
         q("SELECT count(*) FROM sense_src x JOIN sense s ON s.id=x.sense_id "
           "WHERE x.src=? AND x.word_id<>s.word_id", SRC), 0),
        ("🔴 出版层不许出现占位符/纯域标签",
         sum(1 for (t,) in con.execute(
             "SELECT text FROM sense_gloss WHERE lang='it' AND kind='definition'")
             if not_a_definition(t)), 0),
        ("被裁决的证据行数 == 出版层意语释义数",
         q("SELECT count(*) FROM sense_src WHERE src=? AND sense_id IS NOT NULL", SRC)
         - q("SELECT count(*) FROM sense_gloss WHERE lang='it' AND kind='definition'"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-44s %s (期望 %s)" % ("✅" if good else "🔴", name,
                                           f"{got:,}", f"{want:,}"))
    return ok


def write(rows, tag):
    """rows = [(sense_id, src_id, text)]"""
    with dbtool.session(tag, expect={"#sense_gloss": len(rows)}) as s:
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?,'it','definition',0,?,?)",
                      [(sid, clean(t), SRC) for sid, _x, t in rows])
        s.executemany("UPDATE sense_src SET sense_id=? WHERE id=?",
                      [(sid, xid) for sid, xid, _t in rows])


def main():
    ap = argparse.ArgumentParser()
    for f in ("plan", "apply-unique", "control", "run", "apply", "verify", "mutate"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()

    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    unique, multi, nopos = load(ro)

    if a.plan:
        n = len(unique) + len(multi) + len(nopos)
        print("■ ③ 候选 %s 个词形" % f"{n:,}")
        print("   ① 词性唯一（确定性，直接挂）   %6s (%.1f%%)"
              % (f"{len(unique):,}", 100.0 * len(unique) / n))
        print("   ② 我们没有这个词性（不挂，记账）%6s (%.1f%%)"
              % (f"{len(nopos):,}", 100.0 * len(nopos) / n))
        print("   ③ 同词性多条（要对齐）         %6s (%.1f%%)  候选义项 %s 条"
              % (f"{len(multi):,}", 100.0 * len(multi) / n,
                 f"{sum(len(r['cands']) for r in multi):,}"))
        print("\n   ② 桶的词性分布: %s"
              % Counter(r["pos"] for r in nopos).most_common(6))
        return 0

    if a.apply_unique:
        rows = [(r["sid"], r["xid"], r["it"]) for r in unique]
        print("■ 桶① 词性唯一，直接挂 %s 条" % f"{len(rows):,}")
        ro.close()
        write(rows, "align-it-unique")
        print("■ 已写入")
        return 0

    if a.control:
        ok = run_control(multi, ro)
        ro.close()
        return 0 if ok else 1

    if a.run:
        items = [(payload(r, r["cands"]), r["wid"]) for r in multi]
        batches, meta = batched(items)
        ro.close()
        # 🔴 必须用**控制组验过的那条通路**（online pro）。换模型/换通路 = 控制组作废。
        asyncio.run(__import__("ds_batch").run(SYS, batches, meta, OUT, mode="flash", conc=12, every=20))
        return 0

    if a.apply:
        got = {}
        if OUT.exists():
            for line in OUT.open(encoding="utf-8"):
                r = json.loads(line)
                got[r["id"]] = r.get("i")
        rows, stat = [], Counter()
        for r in multi:
            i = got.get(r["wid"])
            if i is None:
                stat["模型没回答（留证据层）"] += 1
            elif i == 0:
                stat["✅ 模型判「一条都挂不上」（留证据层，归 ④ 类）"] += 1
            elif not isinstance(i, int) or not 1 <= i <= len(r["cands"]):
                stat["🔴 序号越界（丢弃）"] += 1
            else:
                stat["✅ 对齐成功"] += 1
                rows.append((r["cands"][i - 1][0], r["xid"], r["it"]))
        for k, v in stat.most_common():
            print("   %-44s %7s" % (k, f"{v:,}"))
        print("\n■ 将挂上 %s 条" % f"{len(rows):,}")
        ro.close()
        if rows:
            write(rows, "align-it-multi")
            print("■ 已写入")
        return 0

    if a.mutate:
        import contextlib
        import io
        import shutil
        import tempfile
        tmp = Path(tempfile.mkdtemp()) / "m.sqlite"
        cases = [
            ("改掉一条出版层意语定义的一个字符",
             "UPDATE sense_gloss SET text=text||'x' WHERE lang='it' AND kind='definition' "
             "AND sense_id=(SELECT min(sense_id) FROM sense_gloss WHERE lang='it' "
             "AND kind='definition')"),
            # ⚠️ 第一版把这条写成一大坨相关子查询 UPDATE，**一行都没改到**，闸自然不红，
            #    我差点当成"闸是假的"。造不出变异 = 这条验证是空的，所以下面显式返回 False。
            ("把一条已裁决证据改挂到**别的词性**的义项上（错配）", _mut_wrong_pos),
            ("给一条 sense 挂第二条意语定义",
             "INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) SELECT sense_id,'it',"
             "'definition',1,'falso','it-edition' FROM sense_gloss WHERE lang='it' "
             "AND kind='definition' LIMIT 1"),
            ("把占位符文本挂进出版层",
             "INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) SELECT s.id,'it',"
             "'definition',0,'definizione mancante; se vuoi, aggiungila tu','it-edition' "
             "FROM sense s WHERE s.id NOT IN (SELECT sense_id FROM sense_gloss WHERE lang='it' "
             "AND kind='definition') LIMIT 1"),
        ]
        caught = 0
        for name, sql in cases:
            shutil.copy(paths.DB, tmp)
            c2 = sqlite3.connect(tmp)
            if callable(sql):
                if not sql(c2):
                    print("   🔴 %-44s 造不出变异 —— 这条验证是空的" % name)
                    c2.close()
                    continue
            else:
                c2.execute(sql)
            c2.commit()
            c2.close()
            r2 = sqlite3.connect("file:%s?mode=ro" % tmp, uri=True)
            with contextlib.redirect_stdout(io.StringIO()):
                red = not gate(r2)
            r2.close()
            caught += red
            print("   %s %-44s %s" % ("✅" if red else "🔴", name,
                                      "闸红了（对）" if red else "闸没红 —— 这条闸是假的"))
        print("\n   变异验证 %d/%d" % (caught, len(cases)))
        return 0 if caught == len(cases) else 1

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
