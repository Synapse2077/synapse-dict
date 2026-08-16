#!/usr/bin/env python3
"""④⑤ 意语给多条：对齐 + **新建义项**（中文直接从意语原文翻，第一手）。2026-08-15。

═══ 这一步在回答什么 ═══
同样 16,035 个词形，**意语版给 46,955 条义项，我们只有 34,795 条** —— 这就是
`SCHEMA` §9 说的「我们的义项收粗了」的量化。差额不是噪声，是意大利人自己
认为该分开而我们没分的义项。

═══ 单位是 (词形, 词性)，不是词形 ═══
词性是**确定性**的前置约束（③ 上验过）。同一个词形可能有多个词性的意语释义，
按 (wid, pos) 切开之后，每个单元内部才是纯粹的语义对齐问题。
    · 我们侧该词性 0 条义项 → 全部新建，**不用问模型**（3,200 条）
    · 我们侧有 → 模型做指派

═══ 指派规则：一条我方义项最多接一条意语定义 ═══
闸里的不变量（`一条 sense 最多一条意语定义`）本身就蕴含这条。它的**词典学含义**是：
若两条意语定义都指向我们同一条义项，说明我们那条是个粗口袋 ⇒ 第一条挂上去，
其余**新建**。谁先挂由**源头顺序**决定（意语版自己的 rank 1 通常是主义项），
确定性、可复现，不靠模型排序。

═══ 新建义项的中文从哪来 ═══
🔴 全库 96.4% 的中文翻译时没见过一个意大利字（53.1% 从英文、43.3% 从法语）。
这一步新建的义项**直接从意语原文翻**，`src` 记 `deepseek:from-it`，是全库
第一批第一手中文。对齐与翻译**一次调用产出**（es 实测多吐字段近乎零成本）。

═══ prompt 的判据全部按含义写，不用形式代理（A45）═══
🔴 第一版写的是「中文对应词式释义，**不是长句翻译**」「多个…**最多 3 个**」——
   全是形式代理。用户 2026-08-15 点破：**要按义项本身的含义出发**。
   这个缺陷**恰好打在本步的核心上**：新建义项正是因为它跟已有义项不同才新建的，
   而那版 prompt 只让模型「写短」，**没要求把不同点写出来** ——
   等于一边造新义项一边抹掉它跟旧义项的区别。
   ⇒ 已跑的 1,875 批（3.3M token）作废重跑，控制组一并重验（A41）。

═══ 已知的风险与它的确定性兜底 ═══
③ 的控制组显示模型**偏保守**：负控 100% 洁净（不编），但正控里有真匹配却答 0 的
（`disc jockey` / `weberiano`）。在这一步，答 0 = 新建义项 ⇒ 保守偏向会造出
**与已有义项重复的新义项**。
⇒ 不靠模型自律，靠**确定性事后闸**：新建完立刻查「同词形下中文逐字相同」，
   撞上的不落库。这正是 ③ 那轮量出 622 组重复时写好的判据。

用法（在 it/ 目录下）：
    python3 pipeline/align_it_multi.py --plan
    python3 pipeline/align_it_multi.py --control
    python3 pipeline/align_it_multi.py --run
    python3 pipeline/align_it_multi.py --apply
    python3 pipeline/align_it_multi.py --verify
    python3 pipeline/align_it_multi.py --mutate
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
import ds_batch    # noqa: E402  DeepSeek 同接口通路，用于三家横评
import dbtool      # noqa: E402
import paths       # noqa: E402
from align_it_defs import batched   # noqa: E402  共用批次切分（本地键 1..N）
from demote_alt_pointer_defs import is_pointer   # noqa: E402
from build import POS_MAP   # noqa: E402  词性映射唯一的家
from promote_it_gloss import PTR, SRC, pos_of_ref   # noqa: E402
from strip_it_placeholder import clean, not_a_definition   # noqa: E402

OUT = paths.WORK / "it_multi.jsonl"
CTRL = paths.WORK / "it_multi_control.jsonl"
# 🔴 实际跑的是 flash（豆包已禁用）。这个常量是换模型前定的，落库后才发现记成了 pro ——
#    来源写错等于骗自己，已回改并同步修正库里那 16,302 行。
ZH_SRC = "deepseek-v4-flash:from-it"
CHUNK = 6      # 每条 payload 比 ③ 大得多（多条意语 × 多条义项），批要小

SYS = """你是意大利语—中文词典编纂员。每条给你一个意大利语词、词性、
`its`＝**意大利语维基词典**写的若干条意语释义（带编号 n），
`senses`＝我们词典里该词该词性**已有的义项**（带编号 i、英文 en、中文 zh）。

对 `its` 里的**每一条**，判断它对应已有义项的哪一条：
  · 对应上 → 给出那条的 `i`
  · 🔴 一条都不对应 → `i` 填 0，并**额外给出中文释义** `zh`

🔴 `senses` 里每条最多被用一次。若两条意语释义你都想指向同一条，说明我们那条
   义项太粗：把**更贴近**的那条指过去，另一条填 0（它是我们缺的义项）。
🔴 宁可填 0 也不要硬指。近义、上下位、同一领域但不是同一件事的，一律 0。
🔴 以你自己对**意大利语**的理解判断，`en`/`zh` 只是我们已有义项的说明。

`zh` 怎么写（只在 i=0 时给）：
 1. 写这条义项**指的那个东西**在中文里的说法 —— 读者拿它去替换句子里的这个词，
    意思应当成立。不要写"关于这个词"的话（"用于构成…""参见…""该词表示…"）。
 2. 🔴 你写的这条会**和 `senses` 里的义项并排显示给用户**。所以它必须让读者
    一眼看出跟那些不是同一个意思。**区分点是什么就写什么**，写在括号里，
    括号内**不限长度**：
        Polistena 已有「波利斯泰纳（姓氏）」
                  → 新增写「波利斯泰纳（意大利雷焦卡拉布里亚省市镇）」
        Aisne     已有「埃纳河（法国河流）」 → 新增写「埃纳河（比利时河流）」
    若不写括号，你的中文就会跟已有的某条**字面相同** —— 那样这条等于没写。
 3. 括号外只放对应词本身。意思确实有几个不同说法时用中文逗号并列，
    **只列真正不同的**；同义重复的不要。
 4. 句末不加任何标点。
 5. 学名、`:*` 之类的抓取残渣不要带进中文。
 6. 带语体色彩的（粗俗、俚语、文语、古语）要在中文里体现出来。
 7. 你确实读不懂这条意语释义时，`zh` 给空字符串 ""，**不要猜**。

输入是一个 JSON 对象，键是编号，值是一条记录。
输出**只有**一个 JSON 对象，**键与输入完全相同**，值形如
{"r": [{"n": 1, "i": 2}, {"n": 2, "i": 0, "zh": "对门楼里的住户"}]}。
不要围栏、不要解释、不要输出数组。"""


def load(con):
    """→ units[(wid, pos)] = dict(word, pos, its=[(xid,text)], ours=[(sid,en,zh)])"""
    vis = defaultdict(list)
    for wid, sid, pos in con.execute(
            "SELECT s.word_id, s.id, COALESCE(e.pos, s.pos) FROM sense s "
            "LEFT JOIN entry e ON e.id=s.entry_id WHERE COALESCE(s.hidden,0)=0 "
            "ORDER BY s.rank"):
        vis[(wid, pos)].append(sid)
    gl = defaultdict(dict)
    for sid, lang, t in con.execute(
            "SELECT sense_id, lang, text FROM sense_gloss WHERE lang IN ('en','zh') AND seq=0"):
        gl[sid][lang] = t
    word = dict(con.execute("SELECT id, word FROM dict"))
    alt_t = defaultdict(list)
    for wid, tgt in con.execute("SELECT word_id, target FROM sense_relation WHERE kind='alt_of'"):
        alt_t[wid].append(tgt)

    per = defaultdict(list)
    for xid, wid, ref, text in con.execute(
            "SELECT id, word_id, src_ref, text FROM sense_src "
            "WHERE src=? AND sense_id IS NULL ORDER BY id", (SRC,)):
        if not_a_definition(text) or PTR.match(text):
            continue
        if any(is_pointer(text, t) for t in alt_t.get(wid, [])):   # A38
            continue
        per[wid].append((xid, pos_of_ref(ref), text))

    units = {}
    for wid, lst in per.items():
        if len(lst) < 2:                      # ③ 已处理过 1 条的情形
            continue
        by = defaultdict(list)
        for xid, pos, text in lst:
            by[pos].append((xid, text))
        for pos, its in by.items():
            # 🔴 不按字数截断。截断是**形式判据**，而这些文字正是要被判断含义的对象 ——
            #    实测截掉 1,322 条意语释义（2.82%），`azzurro` 被切在 `rep|ubblicani` 中间，
            #    而完整送入只多花 **3.6%** 字符。用户 2026-08-15：
            #    「不要随意用这种模棱两可的词，要按照义项本身的含义出发」。
            ours = [(s, gl[s].get("en") or "", gl[s].get("zh") or "")
                    for s in vis.get((wid, pos), [])]
            units[(wid, pos)] = dict(word=word[wid], pos=pos, its=its, ours=ours)
    return units


def payload(u):
    return {"w": u["word"], "pos": u["pos"],
            "its": [{"n": n, "t": clean(t)} for n, (_x, t) in enumerate(u["its"], 1)],
            "senses": [{"i": i, "en": en, "zh": zh}
                       for i, (_s, en, zh) in enumerate(u["ours"], 1)]}


def resolve(u, r):
    """模型答案 → (挂上的 [(sid,xid,text)], 新建的 [(xid,text,zh)], 统计)。

    🔴 「一条义项最多接一条意语定义」在这里**确定性地**执行：按源头顺序先到先得，
       撞车的降级为新建。模型即使违反 prompt 也不会写坏库。
    """
    used, hook, fresh, st = set(), [], [], Counter()
    ans = {}
    for e in (r.get("r") or []):
        if isinstance(e, dict) and isinstance(e.get("n"), int):
            ans[e["n"]] = e
    for n, (xid, text) in enumerate(u["its"], 1):
        e = ans.get(n)
        if e is None:
            st["模型没给这一条（留证据层）"] += 1
            continue
        i = e.get("i")
        if isinstance(i, int) and 1 <= i <= len(u["ours"]):
            if i in used:
                st["🔴 撞车：同一条义项被指两次 ⇒ 降级为新建"] += 1
                i = 0
            else:
                used.add(i)
                hook.append((u["ours"][i - 1][0], xid, text))
                st["✅ 挂到已有义项"] += 1
                continue
        elif i != 0:
            st["🔴 序号越界（留证据层）"] += 1
            continue
        zh = (e.get("zh") or "").strip()
        if not zh:
            st["判 0 但没给中文（留证据层）"] += 1
            continue
        fresh.append((xid, text, zh))
        st["✅ 新建义项（中文第一手）"] += 1
    return hook, fresh, st


def run_control(units, con, mode="online", conc=8):
    """正控＝**混合题**：真答案已知的一条 + 另一个词的干扰项放同一道题。
    真值：真的那条 → 已知下标；干扰的那条 → 0。一道题同时考「会不会挂」和「会不会编」。
    """
    gl = defaultdict(dict)
    for sid, lang, t in con.execute(
            "SELECT sense_id, lang, text FROM sense_gloss WHERE lang IN ('en','zh') AND seq=0"):
        gl[sid][lang] = t
    vis = defaultdict(list)
    for wid, sid, pos in con.execute(
            "SELECT s.word_id, s.id, COALESCE(e.pos, s.pos) FROM sense s "
            "LEFT JOIN entry e ON e.id=s.entry_id WHERE COALESCE(s.hidden,0)=0 ORDER BY s.rank"):
        vis[(wid, pos)].append(sid)
    word = dict(con.execute("SELECT id, word FROM dict"))
    known = []
    for wid, sid, ref, text in con.execute(
            "SELECT word_id, sense_id, src_ref, text FROM sense_src "
            "WHERE src=? AND sense_id IS NOT NULL", (SRC,)):
        pos = pos_of_ref(ref)
        ss = vis.get((wid, pos), [])
        if len(ss) >= 2 and sid in ss:
            known.append((wid, pos, sid, ss, clean(text)))
    print("■ 正控可用真值 %s 条" % f"{len(known):,}")

    random.seed(13)
    picks = random.sample(known, min(100, len(known)))
    decoys = random.sample(known, min(100, len(known)))
    items, truth = [], {}
    for (wid, pos, sid, ss, text), d in zip(picks, decoys):
        if d[0] == wid:
            continue
        u = dict(word=word[wid], pos=pos, its=[(0, text), (0, d[4])],
                 ours=[(s, (gl[s].get("en") or "")[:90], (gl[s].get("zh") or "")[:40])
                       for s in ss])
        key = "%d|%s" % (wid, pos)
        truth[key] = ss.index(sid) + 1
        items.append((payload(u), key))
    batches, meta = batched(items, CHUNK)
    global CTRL
    CTRL = CTRL.with_name("it_multi_ctrl_%s.jsonl" % mode)
    CTRL.unlink(missing_ok=True)
    eng = ds_batch if mode in ("flash", "ds-pro") else ark_batch
    asyncio.run(eng.run(SYS, batches, meta, CTRL, mode=mode, conc=conc, every=5))

    got = {}
    for line in CTRL.open(encoding="utf-8"):
        r = json.loads(line)
        got[r["id"]] = r
    hit = miss = ans = fab = clean_d = 0
    for key, t in truth.items():
        r = got.get(key)
        if not r:
            continue
        d = {e.get("n"): e for e in (r.get("r") or []) if isinstance(e, dict)}
        ans += 1
        if (d.get(1) or {}).get("i") == t:
            hit += 1
        else:
            miss += 1
        if (d.get(2) or {}).get("i") in (0, None):
            clean_d += 1
        else:
            fab += 1
    print("\n═══ 控制组（混合题 %d 道）═══" % ans)
    print("   真条目选对   %3d / %3d  = %.1f%%" % (hit, ans, 100.0 * hit / max(ans, 1)))
    print("   干扰项答 0   %3d / %3d  = %.1f%%  （答错=在编）" % (clean_d, ans, 100.0 * clean_d / max(ans, 1)))
    print("\n   判据：干扰项 ≥90%% 必须过（编造直接污染库）；真条目 ≥80%%")
    return clean_d / max(ans, 1) >= 0.90 and hit / max(ans, 1) >= 0.80


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    ev = {sid: t for sid, t in con.execute(
        "SELECT sense_id, text FROM sense_src WHERE src=? AND sense_id IS NOT NULL", (SRC,))}
    pub = {sid: t for sid, t in con.execute(
        "SELECT sense_id, text FROM sense_gloss WHERE lang='it' AND kind='definition'")}
    bad = sum(1 for sid, t in ev.items() if pub.get(sid) not in (t, clean(t)))
    bad += sum(1 for sid in pub if sid not in ev)

    # 🔴 新建义项**不许**与同词形已有中文逐字相同 —— 模型偏保守（该挂却答 0）的
    #    唯一后果就是造重复，这条闸是它的确定性兜底。
    # ⚠️ 第一版写成「全库重复数 == 788（历史遗留）」，又是**写死基线**（A28，今天第四次）。
    #    改成结构性口径：只约束**本步新建的**（`src=ZH_SRC`），与历史遗留无关，
    #    以后把那 788 修掉了这条闸也不会莫名变红。
    zh_all = defaultdict(list)
    mine = set()
    for wid, sid, t, src in con.execute(
            "SELECT s.word_id, s.id, g.text, g.src FROM sense_gloss g "
            "JOIN sense s ON s.id=g.sense_id "
            "WHERE g.lang='zh' AND g.seq=0 AND COALESCE(s.hidden,0)=0"):
        zh_all[wid].append((sid, t))
        if src == ZH_SRC:
            mine.add(sid)
    dup = 0
    for wid, lst in zh_all.items():
        cnt = Counter(t for _s, t in lst)
        dup += sum(1 for s, t in lst if s in mine and cnt[t] > 1)

    checks = [
        ("🔴 出版层 ↔ 证据层双向逐字节（含清洗口径）", bad, 0),
        ("🔴 一条 sense 最多一条意语定义",
         q("SELECT count(*) FROM (SELECT sense_id FROM sense_gloss WHERE lang='it' "
           "AND kind='definition' GROUP BY 1 HAVING count(*)>1)"), 0),
        # ⚠️ 2026-08-15：`sense.pos` 已归一成短码（`fixes/normalize_sense_pos.py`），
        #    而 `src_ref` 和 `entry.pos` 是 kaikki 长写法 ⇒ **两侧都过 `POS_MAP`** 再比，
        #    否则这条闸从此永远假红（长短写法对不上，不是数据错）。
        ("🔴 挂上的义项必须与意语证据同词性（防错配）",
         sum(1 for ipos, opos in con.execute(
             "SELECT x.src_ref, COALESCE(e.pos, s.pos) FROM sense_src x "
             "JOIN sense s ON s.id=x.sense_id LEFT JOIN entry e ON e.id=s.entry_id "
             "WHERE x.src=? AND x.sense_id IS NOT NULL", (SRC,))
             if opos is not None
             and POS_MAP.get(pos_of_ref(ipos), pos_of_ref(ipos)) != POS_MAP.get(opos, opos)), 0),
        ("🔴 本步新建义项的中文与同词形其它义项逐字相同", dup, 0),
        ("🔴 第一手中文的 src 必须记在明处",
         q("SELECT count(*) FROM sense_gloss WHERE src=? AND lang<>'zh'", ZH_SRC), 0),
        ("🔴 新建义项必须同时有中文和意语原文",
         q("SELECT count(*) FROM sense_gloss g WHERE g.src=? AND NOT EXISTS("
           "SELECT 1 FROM sense_gloss h WHERE h.sense_id=g.sense_id AND h.lang='it' "
           "AND h.kind='definition')", ZH_SRC), 0),
        ("每个词形的 rank 连续无空洞",
         q("SELECT count(*) FROM (SELECT word_id FROM sense GROUP BY word_id "
           "HAVING max(rank)<>count(*) OR min(rank)<>1)"), 0),
        ("被裁决的证据行数 == 出版层意语释义数",
         q("SELECT count(*) FROM sense_src WHERE src=? AND sense_id IS NOT NULL", SRC)
         - q("SELECT count(*) FROM sense_gloss WHERE lang='it' AND kind='definition'"), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-46s %s (期望 %s)" % ("✅" if good else "🔴", name,
                                           f"{got:,}", f"{want:,}"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("plan", "control", "run", "apply", "verify", "mutate", "drop-truncated"):
        ap.add_argument("--" + f, action="store_true")
    # 🔴 `PLAYBOOK` 十：大批量生成填充走 turbo batch（半价），别用 pro online 默认。
    #    我这两轮违反了 —— 选 pro 的理由根本不是质量，是「online 看得见进度」，
    #    而 quality_pass 的 online 默认就是 pro。模型成了延迟决策的副产品。
    # 🔴 默认 flash。豆包两个 mode 已在 ark_batch 里硬拦截（2026-08-15，费用）
    ap.add_argument("--mode", default="flash",
                    help="flash(DeepSeek，默认) | ds-pro | 🔴online/turbo-batch=豆包，已禁用")
    ap.add_argument("--conc", type=int, default=12)
    # 🔴 按难度分工，不按习惯选模型（用户 2026-08-15：「这么大批量为什么要用 pro，它真的很贵」）
    #    控制组考的全是 hard（构造时要求我们有 ≥2 条义项），只占真实活儿的 41.9%。
    #    easy＝我们只有 1 条，模型只需判「挂 or 新建」；hard＝要在多条里选。
    ap.add_argument("--bucket", default="all", choices=["all", "easy", "hard"])
    # 顽固的 JSON 解析失败：把块拆小到 1，逐个单位跑，隔离出真正坏的那条
    ap.add_argument("--chunk", type=int, default=CHUNK)
    a = ap.parse_args()

    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    units = load(ro)

    if a.plan:
        n_it = sum(len(u["its"]) for u in units.values())
        n_our = sum(len(u["ours"]) for u in units.values())
        no_our = {k: u for k, u in units.items() if not u["ours"]}
        print("■ ④⑤ 单位 (词形,词性) %s 个" % f"{len(units):,}")
        print("   意语释义 %s 条 / 我们侧同词性义项 %s 条" % (f"{n_it:,}", f"{n_our:,}"))
        print("   其中「我们侧该词性 0 条义项」%s 个单位 / %s 条意语释义 —— 全部新建，不问模型"
              % (f"{len(no_our):,}", f"{sum(len(u['its']) for u in no_our.values()):,}"))
        print("   要问模型的 %s 个单位 / %s 条意语释义"
              % (f"{len(units) - len(no_our):,}",
                 f"{n_it - sum(len(u['its']) for u in no_our.values()):,}"))
        print("\n   🔴 下界：一条义项最多接一条意语定义 ⇒ 至少 %s 条要新建"
              % f"{max(0, n_it - n_our):,}")
        return 0

    if a.drop_truncated:
        # 把「输入曾被截断」的单位从结果里删掉，好让 --run 的续传重做它们。
        # 判据用**旧的**上限值，不是猜的：`its` 里任一条清洗后 >200 字，或
        # `ours` 里任一条英文 ≥90 字 —— 那正是旧代码切过的地方。
        bad = {"%d|%s" % k for k, u in units.items()
               if any(len(clean(t)) > 200 for _x, t in u["its"])
               or any(len(en) >= 90 for _s, en, _z in u["ours"])}
        ro.close()
        if not OUT.exists():
            print("■ 还没有结果文件")
            return 0
        lines = OUT.read_text(encoding="utf-8").splitlines()
        keep = [l for l in lines if json.loads(l)["id"] not in bad]
        print("■ 受截断影响的单位 %s 个；结果行 %s → %s"
              % (f"{len(bad):,}", f"{len(lines):,}", f"{len(keep):,}"))
        OUT.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
        print("■ 已删除，再跑一次 --run 即可重做这些单位")
        return 0

    if a.control:
        ok = run_control(units, ro, mode=a.mode, conc=a.conc)
        ro.close()
        return 0 if ok else 1

    if a.run:
        def want(u):
            n = len(u["ours"])
            return n >= 1 and (a.bucket == "all"
                               or (a.bucket == "easy" and n == 1)
                               or (a.bucket == "hard" and n >= 2))
        items = [(payload(u), "%d|%s" % k) for k, u in units.items() if want(u)]
        print("■ 桶 %s：%s 个单位" % (a.bucket, f"{len(items):,}"), flush=True)
        batches, meta = batched(items, a.chunk)
        ro.close()
        # 🔴 与 ③ 同一条通路（online pro）。换模型 = 控制组作废（A41）
        eng = ds_batch if a.mode in ("flash", "ds-pro") else ark_batch
        asyncio.run(eng.run(SYS, batches, meta, OUT, mode=a.mode, conc=a.conc, every=25))
        return 0

    if a.apply:
        got = {}
        if OUT.exists():
            for line in OUT.open(encoding="utf-8"):
                r = json.loads(line)
                got[r["id"]] = r
        hooks, fresh, st = [], [], Counter()
        for k, u in units.items():
            key = "%d|%s" % k
            if not u["ours"]:
                # 确定性：我们侧该词性一条义项都没有 ⇒ 全部新建，但没有中文，留证据层
                st["我们侧无该词性义项（本轮不动，留证据层）"] += len(u["its"])
                continue
            r = got.get(key)
            if r is None:
                st["模型没回答这个单位（留证据层）"] += len(u["its"])
                continue
            h, f, s2 = resolve(u, r)
            hooks += h
            fresh += [(k[0], k[1]) + x for x in f]
            st += s2
        for kk, v in st.most_common():
            print("   %-42s %7s" % (kk, f"{v:,}"))

        # 🔴 确定性去重兜底：新建的中文若与该词形已有中文逐字相同，不落库
        zh_of = defaultdict(set)
        for wid, t in ro.execute(
                "SELECT s.word_id, g.text FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
                "WHERE g.lang='zh' AND g.seq=0 AND COALESCE(s.hidden,0)=0"):
            zh_of[wid].add(t)
        keep, dropped = [], 0
        for wid, pos, xid, text, zh in fresh:
            if zh in zh_of[wid]:
                dropped += 1
                continue
            zh_of[wid].add(zh)
            keep.append((wid, pos, xid, text, zh))
        print("\n   🔴 新建中文与已有逐字相同、拦下  %s" % f"{dropped:,}")
        print("■ 挂到已有义项 %s 条 / 新建义项 %s 条" % (f"{len(hooks):,}", f"{len(keep):,}"))
        if not (hooks or keep):
            return 0
        mx = dict(ro.execute("SELECT word_id, max(rank) FROM sense GROUP BY word_id"))
        sid = ro.execute("SELECT max(id) FROM sense").fetchone()[0]
        ro.close()
        s_rows, g_rows, link = [], [], []
        for sid2, xid, text in hooks:
            g_rows.append((sid2, "it", "definition", 0, clean(text), SRC))
            link.append((sid2, xid))
        for wid, pos, xid, text, zh in keep:
            sid += 1
            mx[wid] = mx.get(wid, 0) + 1
            s_rows.append((sid, wid, mx[wid], pos))
            g_rows.append((sid, "zh", "equivalent", 0, zh, ZH_SRC))
            g_rows.append((sid, "it", "definition", 0, clean(text), SRC))
            link.append((sid, xid))
        with dbtool.session("align-it-multi",
                            expect={"#sense": len(s_rows), "#sense_gloss": len(g_rows)}) as w:
            w.executemany("INSERT INTO sense (id,word_id,rank,pos) VALUES (?,?,?,?)", s_rows)
            w.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                          "VALUES (?,?,?,?,?,?)", g_rows)
            w.executemany("UPDATE sense_src SET sense_id=? WHERE id=?", link)
        print("■ 已写入")
        return 0

    if a.mutate:
        import contextlib
        import io
        import shutil
        import tempfile
        tmp = Path(tempfile.mkdtemp()) / "m.sqlite"

        def _dup(c2):
            """造一条与同词形已有中文逐字相同的「本步新建」义项。"""
            row = c2.execute(
                "SELECT s.word_id, g.text FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
                "WHERE g.lang='zh' AND g.seq=0 AND COALESCE(s.hidden,0)=0 LIMIT 1").fetchone()
            if not row:
                return False
            wid, t = row
            sid = c2.execute("SELECT max(id)+1 FROM sense").fetchone()[0]
            rk = c2.execute("SELECT max(rank)+1 FROM sense WHERE word_id=?", (wid,)).fetchone()[0]
            c2.execute("INSERT INTO sense (id,word_id,rank,pos) VALUES (?,?,?,'noun')", (sid, wid, rk))
            c2.execute("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                       "VALUES (?,'zh','equivalent',0,?,?)", (sid, t, ZH_SRC))
            c2.execute("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                       "VALUES (?,'it','definition',0,'falso',?)", (sid, SRC))
            return True

        def _no_it(c2):
            """造一条只有中文、没有意语原文的「本步新建」义项。"""
            row = c2.execute("SELECT id, word_id FROM sense WHERE COALESCE(hidden,0)=0 "
                             "LIMIT 1").fetchone()
            wid = row[1]
            sid = c2.execute("SELECT max(id)+1 FROM sense").fetchone()[0]
            rk = c2.execute("SELECT max(rank)+1 FROM sense WHERE word_id=?", (wid,)).fetchone()[0]
            c2.execute("INSERT INTO sense (id,word_id,rank,pos) VALUES (?,?,?,'noun')", (sid, wid, rk))
            c2.execute("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                       "VALUES (?,'zh','equivalent',0,'某个独一无二的中文串xyzzy',?)", (sid, ZH_SRC))
            return True

        def _wrong_pos(c2):
            for xid, sid, wid, pos in c2.execute(
                    "SELECT x.id, x.sense_id, s.word_id, COALESCE(e.pos,s.pos) FROM sense_src x "
                    "JOIN sense s ON s.id=x.sense_id LEFT JOIN entry e ON e.id=s.entry_id "
                    "WHERE x.src=? AND x.sense_id IS NOT NULL LIMIT 400", (SRC,)):
                # ⚠️ 靶子必须是**还没有意语定义**的义项 —— ④⑤ 之后大量义项已有，
                #    直接改挂会撞 UNIQUE(sense_id,lang,kind,seq)，变异造不出来。
                alt = [s2 for s2, p2 in c2.execute(
                    "SELECT s2.id, COALESCE(e2.pos,s2.pos) FROM sense s2 "
                    "LEFT JOIN entry e2 ON e2.id=s2.entry_id WHERE s2.word_id=? AND s2.id<>? "
                    "AND s2.id NOT IN (SELECT sense_id FROM sense_gloss WHERE lang='it' "
                    "AND kind='definition')", (wid, sid)) if p2 is not None and p2 != pos]
                if not alt:
                    continue
                c2.execute("UPDATE sense_src SET sense_id=? WHERE id=?", (alt[0], xid))
                c2.execute("UPDATE sense_gloss SET sense_id=? WHERE sense_id=? AND lang='it' "
                           "AND kind='definition'", (alt[0], sid))
                return True
            return False

        cases = [
            ("改掉一条出版层意语定义的一个字符",
             "UPDATE sense_gloss SET text=text||'x' WHERE lang='it' AND kind='definition' "
             "AND sense_id=(SELECT min(sense_id) FROM sense_gloss WHERE lang='it' "
             "AND kind='definition')"),
            ("把已裁决证据改挂到别的词性的义项上（错配）", _wrong_pos),
            ("🔴 新建一条与已有中文逐字相同的义项（模型保守的后果）", _dup),
            ("新建义项只有中文、没有意语原文", _no_it),
            ("把第一手中文的 src 记到英文行上",
             "UPDATE sense_gloss SET src='%s' WHERE lang='en' AND sense_id="
             "(SELECT min(sense_id) FROM sense_gloss WHERE lang='en')" % ZH_SRC),
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
