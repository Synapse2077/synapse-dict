#!/usr/bin/env python3
"""阶段 1.5b/1.5c：把中文装进 `sense_gloss(lang='zh')`。2026-09-07。

用户 2026-09-07 定案：「该花花吧，我认了，保证质量就行」。

═══ 🔴🔴 本步最重要的一条：**放弃老库豆包写的那批**（用户 2026-09-07 决定）═══
老 en（2026-07-26～07-31）在 ECDICT 上降过一轮 bad 率，用的是**豆包 lite/turbo**。
留痕日志逐桶核出来：

    qual      条数        被模型改写   文本来源
    core      59,137       0.2%       ECDICT 原文（人工整理的开源数据集）
    judged    79,537     100.0%       🔴 豆包
    fixed    580,376      97.5%       🔴 豆包 lite/turbo
    good     812,045       4.3%       ECDICT 原文
    fair   2,151,929       0.0%       ECDICT 原文
    low      210,599       0.0%       ECDICT 原文

⇒ 两条判据，缺一不可：
  ① **`fixed`/`judged` 不当答案** —— 我曾报「core+fixed 单义词 161,474 条可直接贴」，
     其中 149,995 条是豆包写的。**只有 core 桶的 11,479 条站得住。**
  ② **`fixed`/`judged` 不当锚** —— 把豆包的输出当"参考"喂给 flash，
     是在传播另一个模型的错误（`[[context-you-give-leaks-into-output]]`）。
     160 万条锚里 503,544 条（31.4%）属于这两桶，全部拿掉。

代价 **25 元**（200 → 225）。用户：「保证质量就行」。
⚠️ 七月那轮**不是全废**：IPA 完整保留（阶段 4）；`qual` 那一列是当时最有价值的产物
   —— 正是靠它才分得出「ECDICT 原文」和「豆包写的」，没有它这个错查不出来。

═══ 🔴 `core` 的 `bad≈0.02%` 这个数不能信 ═══
它是**豆包 turbo 自己判出来的**，不是人判的。文本可用（99.8% 是 ECDICT 原文），
数字不可用。切片里当场读到 ECDICT 自己错的：
    amontillado  en「A pale, **dry** sherry」 ECDICT「西班牙产**半干**型」  ← 与原文矛盾
    footpad      en「animal's paw」          ECDICT「拦路强盗」            ← 另一个义项

═══ 锚怎么用（切片实测的结论，见 `EN_PLAN` §七）═══
带锚 vs 不带锚：token +34%，**钱只 +13%**（锚让模型少啰嗦，省下贵 3 倍的出方向）。
最高风险格 27 条全读完：6 好 / 20 平 / **1 条被拖错**（`season` 第 17 义）。
⇒ 带 —— **但多义词的深层义项不给锚**（方案 (c)，见 `deep()`）。
🔴 我先试过「跑完之后加一道拖拽闸」，拿切片真数据验出来**不成立**，已删除，见 `EN_PLAN` §9。

═══ 用法（都不自动跑，`--run` 才发请求）═══
    python3 -u pipeline/translate_defs.py --plan     # 干跑：池子 + 报价 + 闸
    python3 -u pipeline/translate_defs.py --free     # 1.5b 免费段（零 API）
    python3 -u pipeline/translate_defs.py --run      # 1.5c 付费段
    python3 -u pipeline/translate_defs.py --apply    # 落库
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import json
import re
import sqlite3

import dbtool
import paths
import slot_translate as st
from translate_slice import ANCHOR_RULE, RULES

OUT = paths.WORK / "defs"
ANS = OUT / "zh.jsonl"

# 🔴🔴 **批与并发必须在这里覆盖，`slot_translate` 的默认值只是给小批量用的。**
#    2026-09-08 我漏了这两行，全量跑出 3,652 条/分钟 ＝ **4.5 小时**，
#    窗口内跑不完、60% 要进高峰全价（多 133 元）。用户一句「你的并发是多少」问出来的。
#
#    根因是 `[[replay-scripts-undo-fixes]]` 的形状：**修复写在调用方，我搬的是共用件**。
#    fr 早在 8 月就把这件事查清并写进了 `fr/pipeline/translate_examples.py`：
#      「DeepSeek flash 的并发限额是 2,500（官网），共用件默认的 8 是给小批量定的。
#        并发 16 要 6.4 小时，150 只要 40 分钟，而 150 只用掉限额的 6%。
#        **并发只影响墙钟，一分钱不影响 token 成本。**」
#    我拷了 `slot_translate.py`，没拷调用方这两行 ⇒ 拿 8 跑了 18 分钟。
#
#    取值照 de 的 `translate_defs.py`（**同一件事**：释义翻译、同模型、同 API）：
#      CHUNK=80  —— de 注释「释义长 ⇒ 批小一点，免得单批出方向 token 过大」。
#                  en 释义均 88 字符，比德语的 61 还长 ⇒ 80 比我原来那个 160 更合适。
#      CONC=60   —— 只占 2,500 限额的 2.4%。
#    ⚠️ 这活是**网络等待**为主，CPU 只花在 JSON 解析（用户 2026-08-25「别把 cpu 干爆了」）。
st.CHUNK = 80
st.CONC = 60

# 🔴 锚只认 ECDICT 原文这四桶。`fixed`/`judged` 是豆包写的，一个字都不进 payload。
ANCHOR_QUAL = ("core", "good", "fair", "low")
DOUBAO_QUAL = ("fixed", "judged")
# 免费直接贴：只有 core 桶（99.8% ECDICT 原文），且必须单义词·单词性·单行
FREE_QUAL = ("core",)
POS_RE = re.compile(r"\b(n|v|vt|vi|a|adj|ad|adv|prep|conj|pron|int|num|art|aux)\.\s")
NET = re.compile(r"https?://|www\.")

SRC_FREE = "ecdict-core"
SRC_PAID = "model:def"


def _ptr(q):
    return {s for (s,) in q("SELECT sense_id FROM sense_src WHERE "
                            "raw_tags LIKE '%\"form-of\"%' OR raw_tags LIKE '%\"alt-of\"%'")}


# 🔴🔴 方案 (c)：**多义词的深层义项不给锚**（用户 2026-09-08 采纳）
DEEP_SENSES, DEEP_RANK = 4, 1


def deep(wid, rank, real):
    """这条义项是不是「多义词的非首义」—— 锚在这里收益最小、风险最大。

    ═══ 为什么是结构性地不给，而不是事后加一道闸 ═══
    切片实测（`EN_PLAN` §7.1①），锚的**收益**和**风险**在同一格反向分布：

        1 义·首义      锚的收益 29%（B 命中锚而 A 没命中）  风险 ≈0（锚就是这条义项的）
        4-9 义·非首义  收益  6%                          风险高
        10+ 义·非首义  收益  5%                          **风险最高**

    锚是**词条级**的：多义词第 12 义配的锚大概率说的是别的义项。
    `season` 第 17/18 义 `To impregnate.` 就是这么被拽成「使成熟，使老练；使木材干燥」的。

    🔴 **我先试过事后加闸，验出来不成立**（`EN_PLAN` §9）：
       任何"输出与锚重合多少"的判据都分不出 `season`（抄错了）和 `slump`（对的，
       只是正确译文本来就与锚共用词汇）—— 两者形式完全一样，只有语义不同。
       ⇒ 数片段判不了这件事。**换成结构性地不给锚**：不需要判官、不需要第二轮、
         不需要人读，而且**更便宜**（无锚的入方向少 27.6 token/条）。

    代价：那一格约 8,914 条会变啰嗦但不会错；收益：约 385 条**意思错**的风险消失。
    `FRAMEWORK §一`「错比缺更伤权威」——这个方向是对的。
    """
    return real.get(wid, 0) >= DEEP_SENSES and rank > DEEP_RANK


def pool(con):
    """→ (free, paid)。free = [(sense_id, 中文)]；paid = [{id,word,pos,en,ref?}]"""
    q = con.execute
    ptr = _ptr(q)
    lg = {}
    for wid, txt, qual in q("SELECT word_id, text, qual FROM legacy_gloss"):
        lg[wid] = (txt, qual)
    have = {s for (s,) in q("SELECT sense_id FROM sense_gloss WHERE lang='zh'")}

    # 非指针义项数（免费段判"单义词"要用这个，不是全部义项数）
    real = {}
    for sid, wid in q("SELECT id, word_id FROM sense"):
        if sid not in ptr:
            real[wid] = real.get(wid, 0) + 1

    free, paid = [], []
    for sid, wid, rk, pos, w, en in q(
            "SELECT s.id, s.word_id, s.rank, s.pos, d.word, g.text FROM sense s "
            "JOIN dict d ON d.id=s.word_id "
            "JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='en'"):
        if sid in ptr or sid in have:
            continue
        txt, qual = lg.get(wid, (None, None))
        # ── 1.5b 免费：core 桶 · 该词只有一条实义项 · ECDICT 那条单词性单行
        if (txt and qual in FREE_QUAL and real.get(wid, 0) == 1
                and len(set(POS_RE.findall(txt))) <= 1 and "\n" not in txt):
            free.append((sid, txt.strip()))
            continue
        # ── 1.5c 付费：锚只给 ECDICT 原文四桶，**且不给多义词的深层义项**
        ref = None
        if txt and qual in ANCHOR_QUAL and not NET.search(txt) and not deep(wid, rk, real):
            ref = " / ".join(x.strip() for x in txt.split("\n") if x.strip())[:180]
        it = {"id": sid, "word": w, "pos": pos or "", "en": en}
        if ref:
            it["ref"] = ref
        paid.append(it)
    return free, paid


def gates(con, free, paid):
    """🔴 花钱之前先证明「豆包写的一个字都没进 payload」。

    🔴 **「payload 带不带 id」必须排第一条** —— 2026-09-07 变异当场咬到：
       它原本排最后，前面几条先拿 `i["id"]` 去查，**撞上缺失的 key 直接抛异常**。
       抛异常也拦住了花钱（fail-safe），但闸报的是 traceback 不是「🔴 少了 id」——
       读的人得去看栈才知道发生了什么。⇒ **闸自己不许崩**：先验形状，再验内容。
    """
    q = con.execute
    bad_wids = {w for (w,) in q("SELECT word_id FROM legacy_gloss WHERE qual IN %s"
                                % str(DOUBAO_QUAL))}
    # 🔴 一次取全，不逐行查 —— `[[query-perf-collation-traps]]`：
    #    免费段 1.1 万条各发一次 `WHERE word_id=?`，闸自己要跑几十秒。
    qual_of = dict(q("SELECT word_id, qual FROM legacy_gloss"))
    sid2wid, rank_of = {}, {}
    for sid, wid, rk in q("SELECT id, word_id, rank FROM sense"):
        sid2wid[sid] = wid
        rank_of[sid] = rk
    ptr = _ptr(q)
    real = {}
    for sid, wid in sid2wid.items():
        if sid not in ptr:
            real[wid] = real.get(wid, 0) + 1
    noid = sum(1 for i in paid if "id" not in i)
    ok_paid = [i for i in paid if "id" in i]
    leak = [i["id"] for i in ok_paid if i.get("ref") and sid2wid.get(i["id"]) in bad_wids]
    free_leak = [s for s, _ in free if sid2wid.get(s) in bad_wids]
    checks = [
        # ① 形状：先验 payload 长得对不对，后面几条才敢碰它的字段
        ("payload 一律带 id（那个 175 万 token 的 bug）", noid, 0),
        # ② 内容
        ("🔴 豆包桶的文本混进锚", len(leak), 0),
        ("🔴 豆包桶的文本混进免费段", len(free_leak), 0),
        # 🔴 这里**故意写死 "core"，不读 `FREE_QUAL`** —— 判据不许引用它要检查的那个变量。
        #    读 FREE_QUAL 的话，谁把 `fixed` 加进 FREE_QUAL，这条就跟着放行 ＝ 恒真。
        ("免费段全部来自 core 桶",
         sum(1 for s, _ in free if qual_of.get(sid2wid.get(s)) != "core"), 0),
        ("付费池与免费段不重叠",
         len({s for s, _ in free} & {i["id"] for i in ok_paid}), 0),
        # ③ 方案 (c)：多义词的深层义项一条锚都不许带
        # 🔴🔴 **这里故意不调 `deep()`，阈值写死** —— 判据不许引用它要检查的那个变量。
        #    2026-09-08 变异当场咬到：调 `deep()` 的话，谁把 `DEEP_SENSES` 调大，
        #    取锚和查锚**同时失效**，闸跟着放行 ＝ 恒真（M4 一开始就是这么漏的）。
        #    ⚠️ 这是**有意的重复**，不是忘了抽公共函数：闸必须独立于被它检查的策略。
        #    同一份文件里 `FREE_QUAL` 那条已经因为同一个理由写死过 "core"，
        #    我半小时后在 `deep()` 上又犯了一遍 —— 所以两处都留着这段说明。
        ("🔴 多义词深层义项带了锚（方案 c）",
         sum(1 for i in ok_paid if i.get("ref")
             and real.get(sid2wid.get(i["id"]), 0) >= 4
             and rank_of.get(i["id"], 1) > 1), 0),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-40s %s / %s" % ("✅" if ok else "🔴", name,
                                       format(got, ","), format(want, ",")))
    return bad


def quote(paid):
    A_in, A_out, B_in, B_out = 43.4, 26.5, 71.0, 22.5
    nb = sum(1 for i in paid if i.get("ref"))
    na = len(paid) - nb
    i = nb * B_in + na * A_in
    o = nb * B_out + na * A_out
    usd = (i * 0.44 + o * 1.32) / 1e6
    print("   带锚 %s ／ 无锚 %s" % (format(nb, ","), format(na, ",")))
    print("   预计 入 %.1fM ／ 出 %.1fM ⇒ **半价 %.0f 元**（全价 %.0f）"
          % (i / 1e6, o / 1e6, usd * 7.2 / 2, usd * 7.2))


def mutate(con):
    """⭐ 每条闸造一个反例。**期望值全是 0 的闸最容易变成恒真** ——
    这五条守的都是"一个字都不许漏进来"，不造反例就分不清「真的没漏」和「闸瞎了」。"""
    global ANCHOR_QUAL, FREE_QUAL
    print("\n═══ 变异验证 ═══")
    keep_a, keep_f = ANCHOR_QUAL, FREE_QUAL
    cases = []

    # M1 把豆包桶放进锚 —— 闸必须报"混进锚"
    ANCHOR_QUAL = keep_a + ("fixed",)
    f, pd = pool(con)
    cases.append(("豆包 fixed 桶进锚", _red(con, f, pd)))
    ANCHOR_QUAL = keep_a

    # M2 把豆包桶放进免费段 —— 闸必须报"混进免费段"+"不是 core"
    FREE_QUAL = keep_f + ("fixed",)
    f, pd = pool(con)
    cases.append(("豆包 fixed 桶进免费段", _red(con, f, pd)))
    FREE_QUAL = keep_f

    # M4 关掉方案 (c)（把 DEEP_SENSES 调到永不触发）—— 闸必须报"深层义项带了锚"
    global DEEP_SENSES
    keep_d = DEEP_SENSES
    DEEP_SENSES = 10 ** 9
    f, pd = pool(con)
    cases.append(("方案 (c) 被关掉（深层义项又带锚了）", _red(con, f, pd)))
    DEEP_SENSES = keep_d

    # M3 payload 掉了 id（那个 175 万 token 的 bug 的形状）
    f, pd = pool(con)
    pd2 = [{k: v for k, v in i.items() if k != "id"} for i in pd[:50]] + pd[50:]
    cases.append(("payload 缺 id", _red(con, f, pd2)))

    ok = sum(1 for _, r in cases if r)
    for why, r in cases:
        print("   %s  %s" % ("✓" if r else "🔴 没逮住", why))
    print("   变异 %d/%d" % (ok, len(cases)))
    return 0 if ok == len(cases) else 1


def _red(con, free, paid):
    """跑一遍闸，只回"红了没"，不打印。

    🔴 **崩溃不算"逮住"**。闸抛异常虽然也拦住了花钱，但它报的是 traceback 不是
       一行「🔴 少了 id」—— 变异必须把这两种区分开，否则一个会崩的闸看起来像合格。
    """
    import contextlib
    import io
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            n = gates(con, free, paid)
    except Exception as e:
        print("      ⚠️ 闸**抛异常**而不是报红：%s: %s" % (type(e).__name__, str(e)[:60]))
        return False
    return n > 0


HAN = re.compile(r"[㐀-䶿一-鿿]")


def _frags(ref):
    """把词条级锚拆成中文片段。学科方括号不算内容。"""
    s = re.sub(r"^[a-z]{1,5}\.\s*|\s*/\s*[a-z]{1,5}\.\s*", " ", ref or "")
    s = re.sub(r"\[[^\]]{1,6}\]", " ", s)
    return {x.strip() for x in re.split(r"[；;，,、/\s]+", s)
            if len(x.strip()) >= 2 and HAN.search(x)}


def read_answers():
    """→ {sense_id: 中文}。坏行跳过；**空答案保留**（规则 6 让它留空，那是信号不是缺失）。"""
    out = {}
    if not ANS.exists():
        return out
    for ln in ANS.open(encoding="utf-8"):
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if isinstance(o, dict) and "id" in o:
            out[int(o["id"])] = (o.get("zh") or "").strip()
    return out


def normalize(z):
    """落库前的确定性规整。**只去句末「。」，绝不碰 ！？**

    🔴 词典释义按惯例不带句号，实测 97,808 条（9.2%）带了。
    🔴🔴 **但不能一刀切句末标点** —— de 那轮实测过「叹词的感叹号是中文的一部分」，
       en 这轮 479 条句末 ！？ 逐条看下来**全是词义本身**：
           胡说！废话！          （对雪橇犬的吆喝声）出发！走！
           （表示疑问或困惑）嗯？什么？   （变戏法用语）嘿，变！瞧！
       删掉它们就是把词义删了。⇒ 判据按含义写：**句号是格式，叹号问号是内容。**
    ⭐ 在**数据里**规整，不在展示层打补丁（`[[aim-for-perfect-not-cheap]]`）。
    """
    z = z.strip()
    while z.endswith("。"):
        z = z[:-1].rstrip()
    return z


def apply_(con, paid, free):
    """把答案落进 `sense_gloss(lang='zh')`。

    🔴 **落库前必须证明「每一条答案都来自我们发出去的那个池子」** ——
       这正是 2026-09-07 那个 175 万 token 事故的形状：模型没收到 id 就瞎编，
       编中了真主键就把中文贴到别的义项上（`[[model-answer-files-key-by-id]]`）。
       结构上查不了语义，但查得了**来源**：答案 id ⊄ 付费池 ⇒ 一定是编的。
    """
    ans = read_answers()
    if not ans:
        print("\n🔴 %s 没有答案" % ANS)
        return 1
    sent = {i["id"] for i in paid}
    have = {s for (s,) in con.execute("SELECT sense_id FROM sense_gloss WHERE lang='zh'")}
    alien = sorted(set(ans) - sent)
    empty = [s for s, z in ans.items() if not z]
    rows = [(s, normalize(z), SRC_PAID) for s, z in ans.items()
            if normalize(z) and s in sent and s not in have]
    kept_bang = sum(1 for _, z, _ in rows if z and z[-1] in "！？!?")
    _sent_ids = {i["id"] for i in paid}
    bang_before = sum(1 for s_, z in ans.items()
                      if z.rstrip() and z.rstrip()[-1] in "！？!?"
                      and s_ in _sent_ids and s_ not in have)
    stripped = sum(1 for s, z, _ in rows if ans[s].rstrip() != z)
    checks = [
        ("🔴 答案 id 不在付费池里（＝模型编的）", len(alien), 0),
        ("🔴 要写的 sense_id 已经有中文了", len({s for s, _, _ in rows} & have), 0),
        ("答案数 ≤ 发出去的条数", int(len(ans) > len(sent)), 0),
        # 🔴 规整的负控：句末 ！？ 是词义本身，一条都不许被削掉。
        #    ⚠️ 判据是**规整前后数量相等**，不是"等于某个数"——
        #       我第一版写死 479，字面量闸当场报警（写死行数必然过期），
        #       而且那样问的是"快照对不对"，不是"规整有没有碰它"。
        ("句末 ！？ 被规整削掉了（负控）", bang_before - kept_bang, 0),
        ("🔴 规整后不许出现空串", sum(1 for _, z, _ in rows if not z), 0),
    ]
    print("\n═══ 闸②：落库之前 ═══")
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-40s %s / %s" % ("✅" if ok else "🔴", name, format(got, ","),
                                       format(want, ",")))
    print("   ⭐ 去掉句末「。」%s 条 ｜ 保住句末 ！？ %s 条" % (format(stripped, ","), format(kept_bang, ",")))
    print("   答案 %s ｜ 模型留空 %s（规则 6，**不写库**）｜ 本次要写 %s"
          % (format(len(ans), ","), format(len(empty), ","), format(len(rows), ",")))
    if bad:
        print("\n🔴 闸红，不落库。")
        if alien:
            print("   外来 id 样本：%s" % alien[:8])
        return 1
    with dbtool.session("keep-v3-15c-defs", expect={"#sense_gloss": len(rows)}) as s:
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?,'zh','definition',0,?,?)", rows)
    print("\n✅ 1.5c 落库 %s 条" % format(len(rows), ","))
    return 0


def main():
    ap = argparse.ArgumentParser()
    for f in ("plan", "free", "run", "apply", "mutate"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    free, paid = pool(con)
    print("═══ 阶段 1.5 池子 ═══")
    print("   1.5b 免费直接贴（core 桶单义词）%s 条" % format(len(free), ","))
    print("   1.5c 付费翻                    %s 条" % format(len(paid), ","))
    print("\n═══ 闸①：花钱之前 ═══")
    if gates(con, free, paid):
        print("\n🔴 闸红，不跑。")
        return 1
    print("\n═══ 报价 ═══")
    quote(paid)
    con.close()

    if a.free:
        OUT.mkdir(parents=True, exist_ok=True)
        with dbtool.session("keep-v3-15b-free", expect={"#sense_gloss": len(free)}) as s:
            s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                          "VALUES (?,'zh','definition',0,?,?)",
                          [(sid, txt, SRC_FREE) for sid, txt in free])
        print("\n✅ 1.5b 落库 %s 条" % format(len(free), ","))
        return 0

    if a.run:
        OUT.mkdir(parents=True, exist_ok=True)
        st.announce_window()
        b = [i for i in paid if i.get("ref")]
        n = [i for i in paid if not i.get("ref")]
        print("\n══ 带锚 %s 条 ══" % format(len(b), ","))
        st.translate(b, RULES + ANCHOR_RULE, ANS,
                     fields=("id", "en", "word", "pos", "ref"), keep=("id", "word"))
        print("\n══ 无锚 %s 条 ══" % format(len(n), ","))
        st.translate(n, RULES, ANS,
                     fields=("id", "en", "word", "pos"), keep=("id", "word"))
        return 0

    if a.mutate:
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        rc = mutate(con)
        con.close()
        return rc

    if a.apply:
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        rc = apply_(con, paid, free)
        con.close()
        return rc

    if not a.plan:
        print("\n(干跑。--free / --run / --apply / --mutate)")
    return 0


if __name__ == "__main__":
    _sys.exit(main())
