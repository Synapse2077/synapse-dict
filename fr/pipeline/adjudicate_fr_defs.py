#!/usr/bin/env python3
"""阶段 1.5 收官 — **法语原文释义归位（裁决）**。2026-08-25。

法文版写的法语定义有 710,567 条进了证据层，其中 522,842 条已经确定性地挂上了
出版义项（第二段(a)：结构 1:1 对得上），1,154 条洗完是空的占位符不出版。
**剩下 186,571 条挂不上**，因为"法文版的第几条" ≠ "我们的第几条"。
这一步把它们归位。

═══ 这一步**不产生任何新文本** ═══
🔴 与第三段（翻译）根本不同：翻译的产物是模型写的中文，坏了是"错的内容"；
   裁决的产物只有**标识号**，坏了是**错配** —— 用户的红线原话：
   「不要把义项和释义错配了，那才是真灾难」。
⇒ 所以本脚本的每一条规则、每一道控制判据，都是朝**宁可不挂**的方向拧的。
   不挂的代价 = 那条义项少一行法语原文（中文照旧在，用户查词照旧看得懂）；
   挂错的代价 = 把别的意思的法语原话贴到这条义项底下。**两者不对称。**

═══ 先做免费的：按词性硬过滤 ═══
`sense_src.src_ref` 里带着法文版自己的原始词性（`kk-fr:<词>:<pos_raw>#<occ>.<i>`），
用**收词器那一份** `POS_MAP` 归一后与 `sense.pos` 比。实测：

    候选唯一（退化成"是/否"）          112,065  ⇒ 送（**这一桶不是免费的，见下**）
    候选多条（真裁决）                  63,849  ⇒ 送
    📋 无候选（该词性我们一条义项都没有）  10,607  ⇒ 不送模型，记账
    📋 候选超过 20 条                       50  ⇒ 不送模型，记账

⭐ `n` 与 `name` 合成一类：各版对"专名"的标注系统性不同（`Hittite` 法文版记 name、
   我们记 n，而两边说的是同一件事）。实测这一条并回 987 条。**其余词性一律不并** ——
   `templier` 形容词 vs 名词、`unicorne` 名词 vs 形容词 是**真的义项缺口**，
   不是标注差异，硬并进去就是制造错配。

🔴 **候选唯一 ≠ 可以直接挂**。抽读桶① 22 条逮到 `terrain glissant`：
   我们的中文是引申义「问题雷区」，法文版给的是字面义 `Sol instable`（不稳的地面）。
   同一个词、同一个词性、双方各一条 —— **结构上完美 1:1，语义上是两回事**。
   盲挂会错配几千条。所以候选唯一这一桶照样送模型，只是问题退化成是/否。

═══ 控制判据：产物只有一个字段 `m`，就把它拆成十条 ═══
`[[control-must-cover-every-output-field]]`（那次控制组只量 `i` 不量 `zh`，
烧掉 418 万 token 作废）。这里的 `m` 是一张挂载表，十条判据全是**确定性**的：

    ① 幻觉标识号        `d`/`s` 不在本组给出的清单里          必须 0
    ② 一条 d 挂多条 s    契约禁止                              必须 0
    ③ 词性不一致        对"按词性过滤"这一步本身的回归断言      必须 0
    ④ 挂载率            总体 + 按候选数分层
    ⑤ 懒惰              多候选组里全挂到 rank 最小那条的比例
    ⑥ 一条 s 挂多条 d    合法（法文版拆成两条），但要盯住比例
    ⑦ 覆盖已有法语      该义项本来就有法语原文，又挂一条上去
    ⑧ 越权键            应答对象出现 `id`/`m` 之外的键 = 模型开始自己写东西
    ⑨ 空 m 组比例       整组全不挂
    ⑩ 挂完自撞          同一条 s 上两条法语几乎一样 = 白挂

⚠️ ①②③⑧ 是**硬闸**（红了不写库）；④⑤⑥⑦⑨⑩ 是**要我自己读**的量。

═══ 可逆 ═══
`[[prefer-reversible-designs]]`：写两处，两处都可原样撤回 ——
  `sense_src.sense_id`  NULL → 义项号（撤回 = 置回 NULL）
  `sense_gloss`         新增行，`src='fr-edition:adj'`（撤回 = 删这个 src 的行）
**不动任何已有行**，中文一个字不碰。

用法（在 fr/ 目录下）：
    python3 pipeline/adjudicate_fr_defs.py --stats        # 只看分桶，不发请求
    python3 pipeline/adjudicate_fr_defs.py --slice 900    # 1% 切片
    python3 pipeline/adjudicate_fr_defs.py --read 40      # 打样给我逐条读
    python3 pipeline/adjudicate_fr_defs.py --audit        # 只算控制表
    python3 pipeline/adjudicate_fr_defs.py                # 全量续跑
    python3 pipeline/adjudicate_fr_defs.py --apply        # 落库
    python3 pipeline/adjudicate_fr_defs.py --verify       # 落库后的闸（100% 非抽样）
    python3 pipeline/adjudicate_fr_defs.py --mutate       # 变异验证：故意弄坏看闸红不红
    python3 pipeline/adjudicate_fr_defs.py --undo         # 整体撤回
"""
import argparse
import hashlib
import json
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dbtool                                  # noqa: E402
import paths                                   # noqa: E402
from intake_fr_words import POS_MAP            # noqa: E402
from pipeline import gloss_clean               # noqa: E402
from pipeline import slot_translate            # noqa: E402

SRC = "fr-edition:adj"
OUT = paths.WORK / "adjudicate" / "fr_defs.jsonl"
# 🔴 **「已裁决」台账**：问过的证据行标识号，一行一个。
#    没有它，「待裁决」会把两件事混成一件 ——
#      ① 还没问过
#      ② 问过了，**模型按规则判定不该挂**（本轮 60,927 条，占 34.6%）
#    落库之后 ② 又变回"待裁决"，而组指纹是按**块内 d 标识号**算的、
#    块的组成在落库后变了 ⇒ 答案文件认不出来，于是**全部重问**。
#    实测：不加这个台账，一次无谓重跑就是 437 批（我跑了 85 批才发现，烧掉 135 万 token）。
#    ⚠️ 「模型说不挂」是**一个结论**，和「挂上了」一样要落账，不能只记成功的那一半。
DECIDED = paths.WORK / "adjudicate" / "decided.txt"


def load_decided():
    return {int(x) for x in DECIDED.read_text().split()} if DECIDED.exists() else set()


def save_decided(ids):
    DECIDED.parent.mkdir(parents=True, exist_ok=True)
    with DECIDED.open("a", encoding="utf-8") as f:
        f.write("".join("%d\n" % i for i in sorted(ids)))

# 🔴 共用件默认 CHUNK=160 是给**短槽值**定的（一条几个字）。裁决的一个单元是
#    「一个词的全部候选义项 + 全部待裁法语」，实测 ≈190 token/单元 ——
#    160 个塞进一个请求就是 3 万 token 的上下文，flash 静默丢条的概率随长度涨。
#    ⇒ 这一族压到 60。
slot_translate.CHUNK = 60

# 一次最多问几条待裁法语。超了就切块，**候选每块都完整重发**（少发候选 = 让模型瞎猜）。
D_CHUNK = 12
# 组内候选上限。超了不送模型（几十条义项的词，模型读不完，错配风险陡增）。
S_CAP = 20

# ⭐ 唯一的词性等价类。理由写在模块 docstring 里，**不要在这里再加成员** ——
#    每加一对就是允许一族错配，加之前必须像 n/name 那样先量出"这是标注差异不是义项差异"。
POS_EQ = {"name": "n"}

# 中文是**指针**（「X 的首字母缩写／复数／变体」）而不是释义的义项。
# 它们照样是合法候选 —— `TVA` 的「Téléviseurs 的首字母缩写」挂上法文版的
# 「Principale chaîne de télévision privée au Québec」是**对的**（指针指的就是那个东西）。
# ⚠️ 但这一族最容易似是而非，所以单列一条控制判据，切片里必须我自己读。
PTR_SRC = {"template:alt_of", "template:fr-alt_of", "template:pointer"}


def pos_key(p):
    p = (p or "").strip()
    return POS_EQ.get(p, p)


def ref_pos(src_ref):
    """从 `kk-fr:<词>:<pos_raw>#<occ>.<i>` 里取法文版的原始词性并归一。

    🔴 词形里可以有 `:`（`Wikipédia:…` 这类），所以必须从**右**切；
       `#` 也一样，先切 `#` 再切 `:`。
    """
    body = src_ref[len("kk-fr:"):] if src_ref.startswith("kk-fr:") else src_ref
    raw = body.rsplit("#", 1)[0].rsplit(":", 1)[-1]
    return POS_MAP.get(raw, raw)


SYS = """你在给一部法语词典做**释义归位**：把法文版维基词典写的法语定义，挂到我们已有的义项上。

输入是 JSON 数组，每项是一个法语词形一组：
- `id`：组标识号，**不是序号**，原样回传。
- `w`：法语词形。
- `s`：我们已有的义项。`i`=标识号（不是序号），`zh`=中文释义，`en`=英文释义（可能没有），`fr`=这条义项已有的法语原文（可能没有）。
- `d`：待归位的法语定义。`i`=标识号，`t`=正文。

对 `d` 里的**每一条**，判断它说的是不是 `s` 里某一条义项的**同一个意思**。

规则
1. 只有**同一个意思**才挂。近义、上下位、同一领域但不同所指，一律不挂。
2. **字面义和引申义不是同一个意思。** 中文写的是比喻用法而法语定义说的是字面情形（或反过来），不挂。这是最常见的坑。
3. `s` 里已经带 `fr` 的：如果这条 `d` 和那句 `fr` 说的是同一件事（法文版的第二种说法），可以挂；只是相似，不挂。
4. `s` 的 `zh` 有时候写的是**指针**（「X 的首字母缩写」「X 的复数」「X 的变体」），不是释义。这种义项指的就是 X 所指的那个东西：只有当 `d` 描述的正是那个东西时才挂。
5. 拿不准就不挂。**挂错比不挂坏得多** —— 不挂只是少一行法语原文，挂错是把别的意思贴到这条义项底下。
6. 一条 `d` 最多挂到一条 `s`。多条 `d` 可以挂到同一条 `s`。
7. **不要翻译、不要改写、不要生成任何新文本。你的答案里只有标识号。**

输出 JSON 数组，一组一个对象，只有两个键：
[{"id": <组标识号>, "m": [{"d": <d 的标识号>, "s": <挂到的义项标识号>}]}]
不挂的 `d` 不要出现在 `m` 里；整组都不挂就给空数组 `"m": []`。
只输出 JSON，不要解释。"""


# ══════════════════════════════════════════════════════════════════ 取数
def collect(con):
    """→ (groups, ledger)。groups 里的每一项就是一次请求单元。"""
    st = Counter()
    decided = load_decided()
    pub = set(con.execute(
        "SELECT s.word_id, g.text FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
        "WHERE g.lang='fr'"))
    todo = defaultdict(list)
    for sid, wid, t, ref in con.execute(
            "SELECT id, word_id, text, src_ref FROM sense_src WHERE src='fr-edition'"):
        # 🔴 证据层是**原文**，出版层是**洗过的文本**（`pipeline/gloss_clean.py`）。
        #    拿原文去比出版层，5,668 条洗过的行会被当成"还没出版"再挂一遍 ——
        #    同一句法语在同一条义项上出现两次。⇒ 两边都过 `clean` 再比。
        t = gloss_clean.clean(t)
        if not t:
            st["📋 占位符/编者残渣，洗完为空 ⇒ 不出版（记账）"] += 1
            continue
        if (wid, t) in pub:
            st["已出版（确定性挂上的 + 本段裁决挂上的）"] += 1
            continue
        if sid in decided:
            st["📋 已问过，模型按规则判定不挂（不再重问）"] += 1
            continue
        todo[wid].append((sid, t, ref_pos(ref)))
    st["待裁决"] = sum(len(v) for v in todo.values())

    sen = defaultdict(list)
    for wid, sid, rank, pos in con.execute(
            "SELECT word_id, id, rank, pos FROM sense WHERE hidden=0 ORDER BY rank"):
        sen[wid].append((sid, rank, pos or ""))
    zh, en, fr, zh_src = {}, {}, {}, {}
    for sid, lang, txt, src in con.execute(
            "SELECT sense_id, lang, text, src FROM sense_gloss "
            "WHERE lang IN ('zh','en','fr')"):
        {"zh": zh, "en": en, "fr": fr}[lang].setdefault(sid, txt)
        if lang == "zh":
            zh_src.setdefault(sid, src)
    words = dict(con.execute("SELECT id, word FROM dict"))

    groups, ledger = [], []
    for wid, ds in todo.items():
        cands = sen.get(wid, [])
        for p, grp in _by_pos(ds, cands):
            if not grp["s"]:
                st["🔴 该词性我们一条义项都没有 ⇒ 无法裁决（记账）"] += len(grp["d"])
                ledger += [(words[wid], p, t) for _i, t, _p in grp["d"]]
                continue
            if len(grp["s"]) > S_CAP:
                st["🔴 候选超过 %d 条 ⇒ 不送模型（记账）" % S_CAP] += len(grp["d"])
                ledger += [(words[wid], p, t) for _i, t, _p in grp["d"]]
                continue
            st["候选唯一（是/否）" if len(grp["s"]) == 1 else "候选多条（真裁决）"] \
                += len(grp["d"])
            ss = [{"i": sid, "zh": zh.get(sid, ""), "en": en.get(sid, ""),
                   "fr": fr.get(sid, "")} for sid, _r, _p in grp["s"]]
            ptr = {sid for sid, _r, _p in grp["s"] if zh_src.get(sid) in PTR_SRC}
            for s in ss:                       # 空字段不发，别占 token
                for k in ("en", "fr"):
                    if not s[k]:
                        del s[k]
            dd = [{"i": sid, "t": t} for sid, t, _p in grp["d"]]
            for k in range(0, len(dd), D_CHUNK):
                part = dd[k:k + D_CHUNK]
                # 🔴 落盘键里必须带**这一块到底问了哪几条**的指纹，不能只带块序号。
                #    待裁集合一变（洗掉一条占位符、或补挂了一条），块边界就整体平移，
                #    旧答案里的 `d` 标识号会落到别的块上 —— 那正是
                #    `[[model-answer-files-key-by-id]]` 那次「答案贴到别的义项上」的机制。
                #    带指纹之后，集合一变旧答案自动失效、只失效受影响的那些块。
                fp = hashlib.md5(
                    ",".join(str(x["i"]) for x in part).encode()).hexdigest()[:10]
                groups.append({
                    "fr": "%s\x1f%s\x1f%s" % (words[wid], p, fp),  # 落盘键
                    "id": "%d:%s:%s" % (wid, p, fp),               # 模型认领键
                    "w": words[wid], "s": ss, "d": part,
                    "_rank": {sid: r for sid, r, _p in grp["s"]},
                    "_hasfr": {s["i"] for s in ss if "fr" in s},
                    "_ptr": sorted(ptr),
                    # ③ 的凭据：这一块里所有 d 和所有 s 归一后的词性。
                    # 按构造它们必然相等 —— 所以这条断言盯的是**过滤那一步有没有坏掉**，
                    # 不是盯模型（`[[it-regression-gate]]`：闸要在写入侧和读取侧各查一次）。
                    "_pos": (p, sorted({pos_key(c[2]) for c in grp["s"]})),
                })
    return groups, ledger, st


def _by_pos(ds, cands):
    """按归一后的词性把「待裁法语」和「候选义项」配成组。"""
    out = []
    for p in sorted({pos_key(x[2]) for x in ds}):
        out.append((p, {"d": [x for x in ds if pos_key(x[2]) == p],
                        "s": [c for c in cands if pos_key(c[2]) == p]}))
    return out


# ══════════════════════════════════════════════════════════════════ 控制判据
NEAR = re.compile(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ]")


def controls(groups, got, title):
    """十条判据。→ (硬闸是否全过, 统计 dict)"""
    c = Counter()
    n_pair = n_map = 0
    per_sense = defaultdict(list)
    answered = 0
    for g in groups:
        rec = got.get(g["fr"])
        if rec is None:
            c["缺条（没被答）"] += len(g["d"])
            continue
        answered += 1
        m = rec.get("m")
        if not isinstance(m, list):
            c["🔴 ⑧ 越权键：m 不是数组"] += 1
            m = []
        extra = set(rec) - {"fr", "m", "id", "w"}
        if extra:
            c["🔴 ⑧ 越权键：%s" % ",".join(sorted(extra))[:40]] += 1
        p, sp = g["_pos"]
        if sp != [p]:
            c["🔴 ③ 词性过滤坏了：组内候选词性 %s ≠ %s" % (sp, p)] += 1
        ok_d = {x["i"] for x in g["d"]}
        ok_s = {x["i"] for x in g["s"]}
        n_pair += len(g["d"])
        seen_d = set()
        hit = []
        for x in m:
            if not isinstance(x, dict) or "d" not in x or "s" not in x:
                c["🔴 ⑧ 挂载项缺 d/s"] += 1
                continue
            d_i, s_i = x["d"], x["s"]
            if d_i not in ok_d or s_i not in ok_s:
                c["🔴 ① 幻觉标识号"] += 1
                continue
            if d_i in seen_d:
                c["🔴 ② 一条 d 挂了多条 s"] += 1
                continue
            seen_d.add(d_i)
            hit.append((d_i, s_i))
        n_map += len(hit)
        if not hit:
            c["⑨ 整组不挂"] += 1
        if len(g["s"]) == 1:
            c["④ 候选唯一 · 待裁"] += len(g["d"])
            c["④ 候选唯一 · 挂上"] += len(hit)
        else:
            c["④ 候选多条 · 待裁"] += len(g["d"])
            c["④ 候选多条 · 挂上"] += len(hit)
            if hit and len({s for _d, s in hit}) == 1 and \
                    g["_rank"][hit[0][1]] == min(g["_rank"].values()):
                c["⑤ 多候选组全挂到 rank 最小那条"] += 1
        by_s = Counter(s for _d, s in hit)
        c["⑥ 一条 s 挂了多条 d"] += sum(v - 1 for v in by_s.values() if v > 1)
        c["⑦ 挂到已有法语原文的义项上"] += sum(1 for _d, s in hit if s in g["_hasfr"])
        c["⑦' 挂到指针式中文的义项上（要单独读）"] += sum(
            1 for _d, s in hit if s in set(g["_ptr"]))
        txt = {x["i"]: x["t"] for x in g["d"]}
        for d_i, s_i in hit:
            per_sense[s_i].append(txt[d_i])

    for s_i, ts in per_sense.items():
        keys = [NEAR.sub("", t).lower()[:60] for t in ts]
        if len(keys) != len(set(keys)):
            c["⑩ 同一条义项挂上了几乎相同的两句法语"] += 1

    # 🔴 硬闸的语义：**不是"答案文件里一条违约都不许有"**，而是
    #    "违约必须少到能确认是模型抖动、而且**全部会在写库前被丢掉**"。
    #    实测（85,504 组 / 175,914 条）：
    #        第一轮  幻觉 73 · 一对多 106 · m 非数组 414   ⇒ 重问
    #        第二轮  幻觉  0 · 一对多  24 · m 非数组  59   ⇒ 重问
    #        第三轮  幻觉  0 · 一对多   6 · m 非数组   0   ⇒ 停手
    #    两轮重问把它压掉 99%，剩下的是随机抖动，再问收益已经没有了
    #    （`[[criteria-narrower-than-you-think]]`：修三轮就停手，残差当上界报）。
    # ⚠️ 兜底不是"容忍"，是**三层**：
    #    ① `apply_rows` 按契约丢弃（一对多 ⇒ **整条丢**，不取第一条）
    #    ② `verify()` 在**库那一侧**断言写进去的违约为 0
    #    ③ 这里的比率闸：超过 0.1% 就说明不是抖动，是判据/契约出事了，必须停。
    HARD_RATE = 0.001
    hard = [k for k in c if k.startswith("🔴") and c[k] > HARD_RATE * max(n_pair, 1)]
    drop = sum(v for k, v in c.items() if k.startswith("🔴"))
    print("\n══ %s ══" % title)
    print("   组 %s（已答 %s）｜ 待裁 %s 条 ｜ 挂上 %s 条（%.1f%%）"
          % (format(len(groups), ","), format(answered, ","), format(n_pair, ","),
             format(n_map, ","), 100.0 * n_map / max(n_pair, 1)))
    for k in ("④ 候选唯一", "④ 候选多条"):
        a, b = c[k + " · 挂上"], c[k + " · 待裁"]
        if b:
            print("   %-30s %7s / %-7s  %.1f%%"
                  % (k, format(a, ","), format(b, ","), 100.0 * a / b))
    for k, v in sorted(c.items()):
        if k.startswith("④"):
            continue
        print("   %-42s %8s" % (k, format(v, ",")))
    if hard:
        print("   🔴 硬闸红了（超过 %.1f%%，不是抖动）：%s"
              % (HARD_RATE * 100, "；".join(hard)))
    else:
        print("   ✅ 硬闸过（违约 %s 条 = %.3f%%，**全部会在写库前丢掉**；"
              "库那侧由 --verify 断言为 0）" % (format(drop, ","),
                                              100.0 * drop / max(n_pair, 1)))
    return not hard, c


# ══════════════════════════════════════════════════════════════════ 两个真值控制组
def controls_truth(con, groups, n=300):
    """🔴 **正控 + 负控，两边都有现成真值，都不额外花钱。**

    照抄 `it/pipeline/align_it_defs.py`（2026-08-14）那一轮 —— fr 这次我漏了，
    是用户问「两种语言的经验应该还好吧」才回头查出来的。
    `[[llm-as-evaluator-discipline]]` ⑦：**用前必跑负控**，负控不过就别跑正式批。

    · 正控：拿**已经确定性挂上**的证据（第二段(a) 结构 1:1 对上的，真值已知），
            把该词**同词性的全部义项**摆给模型 ⇒ 选中率 = 对齐准确率。
    · 负控：把 A 词的法语释义配 **B 词**的候选义项 ⇒ 真值恒为「一条都不挂」，
            模型只要挂了任何一条就是在编。**这是唯一能量出「编造率」的实验。**
    """
    import asyncio
    import httpx

    # —— 正控真值：sense_gloss 里已挂的 (sense_id, fr 原文)，取该词同词性多义项的 ——
    rows = list(con.execute(
        "SELECT s.word_id, s.id, s.pos, g.text FROM sense_gloss g "
        "JOIN sense s ON s.id=g.sense_id AND s.hidden=0 "
        "WHERE g.lang='fr' AND g.src='fr-edition'"))
    by_word = defaultdict(list)
    for wid, sid, pos, txt in rows:
        by_word[(wid, pos_key(pos or ""))].append((sid, txt))
    sen, zh, en = defaultdict(list), {}, {}
    for wid, sid, pos in con.execute(
            "SELECT word_id, id, pos FROM sense WHERE hidden=0 ORDER BY rank"):
        sen[(wid, pos_key(pos or ""))].append(sid)
    for sid, lang, txt in con.execute(
            "SELECT sense_id, lang, text FROM sense_gloss WHERE lang IN ('zh','en')"):
        (zh if lang == "zh" else en).setdefault(sid, txt)
    words = dict(con.execute("SELECT id, word FROM dict"))

    pos_items = []
    for (wid, p), lst in by_word.items():
        cands = sen.get((wid, p), [])
        if len(cands) < 2 or len(lst) != 1:      # 要多义项才构成"选哪一条"
            continue
        sid, txt = lst[0]
        pos_items.append({"id": "P%d" % len(pos_items), "w": words[wid],
                          "s": [{"i": c, "zh": zh.get(c, ""), "en": en.get(c, "")}
                                for c in cands],
                          "d": [{"i": 1, "t": txt}], "_truth": sid})
    random.Random(11).shuffle(pos_items)
    pos_items = pos_items[:n]

    # —— 负控：A 的法语释义 + B 的候选义项，真值恒为「不挂」 ——
    neg_items = []
    for i in range(min(n, len(pos_items) - 1)):
        a, b = pos_items[i], pos_items[(i + 7) % len(pos_items)]
        if a["w"] == b["w"]:
            continue
        neg_items.append({"id": "N%d" % i, "w": b["w"], "s": b["s"], "d": a["d"]})

    print("■ 正控 %s 组（真值已知）｜ 负控 %s 组（真值恒为「一条都不挂」）"
          % (format(len(pos_items), ","), format(len(neg_items), ",")))

    async def run(items):
        key = slot_translate.env()["DEEPSEEK_API_KEY"].strip()
        out, tok = {}, 0
        async with httpx.AsyncClient() as cl:
            for k in range(0, len(items), 40):
                g, t = await slot_translate._ask(
                    cl, key, SYS, items[k:k + 40], ["id", "w", "s", "d"],
                    key_field="id", answer_field="m")
                out.update(g)
                tok += t
        return out, tok

    got_p, t1 = asyncio.run(run(pos_items))
    got_n, t2 = asyncio.run(run(neg_items))

    hit = miss = blank = 0
    for it in pos_items:
        m = got_p.get(it["id"])
        m = m if isinstance(m, list) else []
        pick = [x["s"] for x in m if isinstance(x, dict) and "s" in x]
        if not pick:
            blank += 1
        elif pick[0] == it["_truth"]:
            hit += 1
        else:
            miss += 1
    made = sum(1 for it in neg_items
               if isinstance(got_n.get(it["id"]), list) and got_n[it["id"]])

    print("\n══ 正控（对齐准确率）══")
    print("   选对 %s ｜ 选错 %s ｜ 留空 %s ｜ **准确率 %.1f%%（在它给出答案的那些里 %.1f%%）**"
          % (format(hit, ","), format(miss, ","), format(blank, ","),
             100.0 * hit / max(len(pos_items), 1),
             100.0 * hit / max(hit + miss, 1)))
    print("══ 负控（编造率）══")
    print("   %s / %s 组挂了不该挂的 ⇒ **编造率 %.1f%%**（期望接近 0）"
          % (format(made, ","), format(len(neg_items), ","),
             100.0 * made / max(len(neg_items), 1)))
    print("   token %s" % format(t1 + t2, ","))
    return 0


# ══════════════════════════════════════════════════════════════════ 打样
def read_sample(groups, got, n, only=None):
    """挑**挂上了的**打样 —— 要我读的是错配风险，不是留空。

    `only`：`multi` 只看多候选组，`ptr` 只看指针式中文，`None` 全部。
    """
    rows = []
    for g in groups:
        rec = got.get(g["fr"])
        if not rec:
            continue
        zh = {x["i"]: x.get("zh", "") for x in g["s"]}
        txt = {x["i"]: x["t"] for x in g["d"]}
        ptr = set(g["_ptr"])
        for x in rec.get("m") or []:
            if not (isinstance(x, dict) and x.get("d") in txt and x.get("s") in zh):
                continue
            if only == "multi" and len(g["s"]) < 2:
                continue
            if only == "ptr" and x["s"] not in ptr:
                continue
            flag = ("指" if x["s"] in ptr else " ") + \
                   ("覆" if x["s"] in g["_hasfr"] else " ")
            rows.append((g["w"], len(g["s"]), flag, zh[x["s"]], txt[x["d"]]))
    random.Random(3).shuffle(rows)
    print("\n══ 打样 %d/%d 条%s（只看挂上了的；候选数 1 = 是/否，>1 = 真裁决；"
          "指=中文是指针 覆=该义项本已有法语）══"
          % (min(n, len(rows)), len(rows), "" if not only else " · " + only))
    for w, k, fl, z, t in rows[:n]:
        print("   %-20s [候选%d]%s 我们: %-30s\n        法文版: %s"
              % (w[:20], k, fl, z[:30], t[:110]))
    return rows


# ══════════════════════════════════════════════════════════════════ 落库
def apply_rows(con, groups, got):
    # 本轮**问过的每一条**证据都要入账，不管挂没挂上（见 DECIDED 的注释）
    asked = {x["i"] for g in groups if got.get(g["fr"]) is not None for x in g["d"]}
    seq0 = Counter()
    for sid, in con.execute(
            "SELECT sense_id FROM sense_gloss WHERE lang='fr' AND kind='definition'"):
        seq0[sid] += 1

    pairs = []          # (src_id, sense_id, text)
    for g in groups:
        rec = got.get(g["fr"])
        if not rec:
            continue
        ok_d = {x["i"]: x["t"] for x in g["d"]}
        ok_s = {x["i"] for x in g["s"]}
        m = rec.get("m")
        if not isinstance(m, list):
            continue
        # 🔴 **一条 d 被挂到多条 s ⇒ 整条丢掉，不许"取第一条"。**
        #    契约第 6 条禁止一对多；模型违约时它给的四个答案里
        #    没有任何理由认为第一个是对的（`manchot` 一条定义同时挂到 4 条义项）。
        #    取第一条 = 拿一个我知道不可信的答案去写库，正是「错配」那个红线。
        by_d = defaultdict(list)
        for x in m:
            if isinstance(x, dict) and x.get("d") in ok_d and x.get("s") in ok_s:
                by_d[x["d"]].append(x["s"])
        for d_i, ss in by_d.items():
            if len(set(ss)) != 1:
                continue
            pairs.append((d_i, ss[0], ok_d[d_i]))

    # 🔴 幂等：证据行已经裁决过的（`sense_id` 非空）不再动。重放不该改已有归属。
    done = {i for (i,) in con.execute(
        "SELECT id FROM sense_src WHERE src='fr-edition' AND sense_id IS NOT NULL")}
    pairs = [p for p in pairs if p[0] not in done]
    if len({p[0] for p in pairs}) != len(pairs):
        print("🔴 同一条证据出现多次归属，**不写**")
        return 1

    rows = []
    have = {(sid, t) for sid, t in con.execute(
        "SELECT sense_id, text FROM sense_gloss WHERE lang='fr'")}
    skip = 0
    for _d, s_i, t in pairs:
        if (s_i, t) in have:            # 同一条义项上已有同一句法语 ⇒ 不重复写
            skip += 1
            continue
        rows.append((s_i, seq0[s_i], t))
        seq0[s_i] += 1
        have.add((s_i, t))

    print("\n■ 可落库：证据归属 %s 条 ｜ 新增法语释义行 %s 条（同句已在 %s 条，跳过）"
          % (format(len(pairs), ","), format(len(rows), ","), format(skip, ",")))
    if not rows and not pairs:
        return 0
    with dbtool.session("keep-v3-adjudicate", expect={"#sense_gloss": len(rows)}) as s:
        s.executemany("UPDATE sense_src SET sense_id=? WHERE id=? AND sense_id IS NULL",
                      [(s_i, d_i) for d_i, s_i, _t in pairs])
        s.executemany("INSERT OR IGNORE INTO sense_gloss "
                      "(sense_id,lang,kind,seq,text,src) VALUES (?,'fr','definition',?,?,?)",
                      [(s_i, q, t, SRC) for s_i, q, t in rows])
    save_decided(asked)
    print("✓ 写入完成；已裁决台账 +%s 条（含模型判定不挂的）。撤回：--undo"
          % format(len(asked), ","))
    return 0


def mutate():
    """变异验证：**故意弄坏，看闸红不红**。`[[dbtool-and-golden-tests]]`——
    写完闸不做变异，等于不知道它是不是永远绿的（那一轮逮出过 1 条假绿）。

    只改**内存里的判据**，一个字节都不写库。
    """
    import contextlib
    import io as _io
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if not con.execute("SELECT count(*) FROM sense_gloss WHERE src=?", (SRC,)).fetchone()[0]:
        # 🔴 库里一行都没写的时候，任何闸都是绿的 —— 那不是"闸好"，是"没数据"。
        #    `[[wait-loops-lie-about-progress]]` 同一个形状：绿灯本身不携带信息。
        print("🔴 本段还没写过库，变异验证**此刻没有意义**（0 行数据，闸必然全绿）。"
              "\n   落库之后再跑一次。")
        return 1
    real_clean, real_pos_key = gloss_clean.clean, globals()["pos_key"]
    cases = [
        ("① 把 clean 弄歪（重建必然对不上）",
         lambda: setattr(gloss_clean, "clean", lambda t: real_clean(t) + "·")),
        ("③ 把词性归一弄歪（n/name 不再同类）",
         lambda: globals().__setitem__("pos_key", lambda p: (p or "").strip())),
    ]
    bad = 0
    for name, break_it in cases:
        break_it()
        with contextlib.redirect_stdout(_io.StringIO()):
            rc = verify()
        gloss_clean.clean = real_clean
        globals()["pos_key"] = real_pos_key
        print("── 变异：%-36s 闸 %s"
              % (name, "🔴 红了（对）" if rc else "✅ 仍然绿 —— **这条闸是假的**"))
        bad += 0 if rc else 1
    print("■ 变异 %d 例，假绿 %d" % (len(cases), bad))
    return 1 if bad else 0


def verify():
    """写完之后的闸。`[[verification-gates-not-sampling]]`：**100% 非抽样**。

    核心是一条**可逆性**断言：新写进出版层的每一行，都必须能从
    「它对应的那条证据 + `gloss_clean.clean`」原样重建出来。
    这把「有没有搬错文本 / 有没有漏洗」变成可判定的，而不是靠抽样看运气。
    """
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ok = True

    def chk(name, got, want):
        nonlocal ok
        good = got == want
        ok &= good
        print("   %s %-52s %10s  期望 %s"
              % ("✓" if good else "🔴", name, format(got, ","), format(want, ",")))

    n_new = con.execute("SELECT count(*) FROM sense_gloss WHERE src=?", (SRC,)).fetchone()[0]
    n_adj = con.execute("SELECT count(*) FROM sense_src WHERE src='fr-edition' "
                        "AND sense_id IS NOT NULL").fetchone()[0]
    print("■ 本段写入：出版层 %s 行 ｜ 证据层已裁决 %s 条"
          % (format(n_new, ","), format(n_adj, ",")))

    # ① 可逆性：**每一行**都必须能从「挂在同一条义项上的某条证据 + clean」重建。
    #    🔴 一条义项可以挂多行法语，所以必须**按行聚合**再判 ——
    #       按 (行, 证据) 配对去数，配不上的那些配对根本不是错。
    rebuilt = defaultdict(bool)
    rows = set()
    for gid, txt, src_txt in con.execute(
            "SELECT g.sense_id, g.text, x.text FROM sense_gloss g "
            "JOIN sense_src x ON x.sense_id=g.sense_id AND x.src='fr-edition' "
            "WHERE g.src=? AND g.lang='fr'", (SRC,)):
        rows.add((gid, txt))
        if gloss_clean.clean(src_txt) == txt:
            rebuilt[(gid, txt)] = True
    chk("① 出版层有行无法由「证据 + clean」重建",
        sum(1 for r in rows if not rebuilt[r]), 0)

    # ②③ 分两口径报。**本段**必须全绿；第二段(a) 的遗留单独列，不许拿它把闸染红
    #    （`[[fix-regression-and-gate]]`：闸永远红 ⇒ 没人看 ⇒ 等于没有闸）。
    def scoped(sql):
        mine = con.execute(sql % ("AND g.src='%s'" % SRC)).fetchone()[0]
        allx = con.execute(sql % "").fetchone()[0]
        return mine, allx - mine

    n_orph, n_orph_old = scoped(
        "SELECT count(*) FROM sense_src x "
        "LEFT JOIN sense_gloss g ON g.sense_id=x.sense_id AND g.lang='fr' "
        "LEFT JOIN sense s ON s.id=x.sense_id AND s.hidden=0 "
        "WHERE x.src='fr-edition' AND x.sense_id IS NOT NULL AND s.id IS NULL %s")
    chk("② 本段：证据指向了不存在/已隐藏的义项", n_orph, 0)
    print("      📋 第二段(a) 遗留 %s 条 —— 是 `strip_editorial_residue` 隐掉的"
          " 870 条占位符义项，归阶段 8「零可见义项的词条怎么渲染」" % format(n_orph_old, ","))

    n_pos = n_pos_old = 0
    for ref, pos, src in con.execute(
            "SELECT x.src_ref, s.pos, (SELECT g.src FROM sense_gloss g "
            "  WHERE g.sense_id=x.sense_id AND g.lang='fr' LIMIT 1) "
            "FROM sense_src x JOIN sense s ON s.id=x.sense_id "
            "WHERE x.src='fr-edition' AND x.sense_id IS NOT NULL"):
        if pos_key(ref_pos(ref)) != pos_key(pos or ""):
            if src == SRC:
                n_pos += 1
            else:
                n_pos_old += 1
    chk("③ 本段：裁决落在了不同词性的义项上", n_pos, 0)
    print("      📋 第二段(a) 遗留 %s 条 —— 逐条看过，**全是 `我们的 pos 是空串`**，"
          "不是词性不同；已单列成账" % format(n_pos_old, ","))
    # ④ 同一条义项上出现两行一模一样的法语
    chk("④ 同一条义项上重复的法语原文",
        con.execute("SELECT count(*) FROM (SELECT sense_id, text FROM sense_gloss "
                    "WHERE lang='fr' GROUP BY sense_id, text HAVING count(*)>1)"
                    ).fetchone()[0], 0)
    # ⑤ 洗过的文本不该再带残渣
    chk("⑤ 新行里还带引用脚注 `^([`",
        con.execute("SELECT count(*) FROM sense_gloss WHERE src=? AND text LIKE '%^([%'",
                    (SRC,)).fetchone()[0], 0)
    # ⑥ 中文一个字没动
    print("\n■ 中文行数（本段不该动它）：%s"
          % format(con.execute("SELECT count(*) FROM sense_gloss WHERE lang='zh'"
                               ).fetchone()[0], ","))
    n_vis = con.execute("SELECT count(*) FROM sense WHERE hidden=0").fetchone()[0]
    n_fr = con.execute("SELECT count(DISTINCT sense_id) FROM sense_gloss g "
                       "JOIN sense s ON s.id=g.sense_id AND s.hidden=0 "
                       "WHERE g.lang='fr'").fetchone()[0]
    print("■ 可见义项 %s，其中有法语原文 %s（%.1f%%）"
          % (format(n_vis, ","), format(n_fr, ","), 100.0 * n_fr / n_vis))
    print("%s" % ("✓ 闸全过" if ok else "🔴 有闸未通过"))
    return 0 if ok else 1


def undo():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    n = con.execute("SELECT count(*) FROM sense_gloss WHERE src=?", (SRC,)).fetchone()[0]
    print("■ 要撤回 sense_gloss %s 行，并把对应证据的 sense_id 置回 NULL" % format(n, ","))
    if not n:
        return 0
    with dbtool.session("keep-v3-adjudicate-undo", expect={"#sense_gloss": -n}) as s:
        s.execute("DELETE FROM sense_gloss WHERE src=?", (SRC,))
        s.execute("UPDATE sense_src SET sense_id=NULL WHERE src='fr-edition' "
                  "AND sense_id IS NOT NULL")
    print("✓ 已撤回")
    return 0


# ══════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--slice", type=int, default=0)
    ap.add_argument("--read", type=int, default=0)
    ap.add_argument("--only", choices=("multi", "ptr"), help="打样只看某一族")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--mutate", action="store_true", help="变异验证：闸红不红")
    ap.add_argument("--truth", type=int, metavar="N", default=0,
                    help="正控+负控各 N 组（真值实验，用前必跑）")
    ap.add_argument("--ledger", metavar="PATH", help="无法裁决的清单写成 JSON")
    # 冒烟/改契约时用另一个答案文件。🔴 prompt 一改，旧答案就作废
    # （`[[model-answer-files-key-by-id]]`），别让试跑的答案混进正式那份。
    ap.add_argument("--out", metavar="PATH")
    a = ap.parse_args()
    global OUT
    if a.out:
        OUT = Path(a.out)
    if a.undo:
        return undo()
    if a.verify:
        return verify()
    if a.mutate:
        return mutate()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    groups, ledger, st = collect(con)
    if a.truth:
        return controls_truth(con, groups, a.truth)
    print("■ 分桶")
    for k, v in st.most_common():
        print("   %-46s %10s" % (k, format(v, ",")))
    print("   %-46s %10s" % ("⇒ 请求单元（一个 词形×词性 一块）", format(len(groups), ",")))
    if a.ledger:
        Path(a.ledger).write_text(json.dumps(
            [{"word": w, "pos": p, "fr": t} for w, p, t in ledger],
            ensure_ascii=False, indent=1), encoding="utf-8")
        print("   无法裁决清单 %s 条 → %s" % (format(len(ledger), ","), a.ledger))
    if a.stats:
        return 0

    got = slot_translate.done_keys(OUT)
    want = (random.Random(1).sample(groups, min(a.slice, len(groups)))
            if a.slice else groups)
    if not a.audit:
        todo = [g for g in want if g["fr"] not in got]
        if todo:
            slot_translate.translate(todo, SYS, OUT, fields=("id", "w", "s", "d"),
                                     keep=("fr",), key_field="id", answer_field="m")
            got = slot_translate.done_keys(OUT)

    scope = [g for g in want if g["fr"] in got]
    ok, _c = controls(scope, got, "控制判据（本次范围）")
    controls([g for g in scope if len(g["s"]) > 1], got, "控制判据（只看多候选组）")
    if a.read:
        read_sample(scope, got, a.read, a.only)

    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 硬闸未过，**不写库**")
        return 1
    return apply_rows(con, scope, got)


if __name__ == "__main__":
    sys.exit(main())
