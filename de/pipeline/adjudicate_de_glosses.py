#!/usr/bin/env python3
"""C29 ③：德语释义与已有义项的**对齐裁决**。de 版，2026-09-04。

═══════════════════════════════════════════════════════════════════
 v2（2026-09-04 下午重写）—— **v1 的产物已被外审证伪，整层重判**
═══════════════════════════════════════════════════════════════════
v1 落库 50,719 条 / 37,980 条义项，渲染出来后两家外审同时指到同一处，
回源逐条核实**属实**：

    stehen #7761「写着，标示」  ← sich in einer vertikalen Position befinden  🔴
    stehen #7764「合适，好看」  ← nicht funktionieren, nicht arbeiten          🔴
    kommen #2949「归入，被放置」← beginnen, sich ereignen, sich ergeben        🔴
    kommen #2951「发生，出现」  ← einen Orgasmus erleben                       🔴

🔴 **根因不是"配不上硬配"，是它在按位置往下数**。原始应答：

    stehen  m = [0→7759, 1→7760, 2→7761, 3→7764, 4→7764, 5→7765, 6→null]

正是规则 5 明令禁止的那件事。全量复盘（拿「de[i] → 第 i 条待补义项」当基线）：

    每词落库 1 条  8,145 词    80.9% 与位置基线一致
    每词落库 2 条 11,099 词    60.3%
    每词落库 3-4 条 4,362 词   41.1%
    每词落库 ≥5 条    971 词   24.3%

⇒ 难词上它确实在读意思（≥5 那档只有 24.3%），**中等难度的滑到位置上去了**。
  这是 `[[criteria-from-meaning-not-form]]` 的模型侧版本：
  我把「不许按位置」写进了 prompt，然后**把两个列表按位置排好递给它**。
  一条只写在提示里、结构上却处处在鼓励的规则，等于没写。

🔴 **第二个缺陷：源侧没去重**。`src[w].append(g)` 跨 dump 条目累加，
   同一个词在德语版有多个词条（词源／词性各一条）时整套释义被重复收进来 ——
   `kommen` de[0..2] 是同一句话三份，`wegen` 一条义项挂了同一句话 20 遍。
   已修：按原文去重、保序。

🔴 **第三件：全量跑的是关思考那份**。文件头当初自己写着「对齐是推导型 ⇒
   两遍并排比用数据定」，而 `_think.jsonl` 只有 22KB＝只跑了切片就上了全量。
   `[[lesson-must-become-mechanism]]`：写下来的纪律没有闸就守不住。

   ⇒ **v2 的裁决（2026-09-04，300 词切片实测）：关思考。**
     速度      关 300 词/4 分钟   ｜ 开 **31 词/26 分钟**（全量要三周）
     两份重叠  56 词 / 170 对，一致 **89.4%**
     分歧谁对  关：`Windpocke`→水痘 ✅、`wegnehmen` 三条→拿走 ✅
               开：`schneiden`「unfair überholen」→「打断，插话」❌（那是超车加塞）
     ⇒ 开思考不是更差，是**又慢 40 倍又没赢**。
     ⚠️ 这**不推翻**纪律 ⑦「推导型判官必须开思考」，是这一族不适用：
        v2 已经用 `g` 字段把推导**外化成一个必须交付的产物**，
        思考链在做同一件事 ⇒ 重复投入。判据是「推导有没有别的落点」，
        不是「任务是不是推导型」。

═══ v2 改了什么（每一条都对着上面一个根因）═══
① **打乱两侧的呈现顺序**（`shuffle_view`）。位置线索从结构上拿掉，
   而不是在 prompt 里请它别用。id 仍是真主键（`[[model-answer-files-key-by-id]]`），
   打乱的只是数组顺序 ⇒ 答案照样可续跑、可与 v1 逐条并排。
② **每条德语释义必须先自己写一个 ≤10 字的中文 `g`，再挑 `s`**。
   这是把「读意思」变成一个它必须交付的产物：
   - 逼它对每一条做语义处理，而不是扫一眼列表；
   - 给我一条**可读的轨迹** —— `g` 和它挑中那条义项的 `zh` 对不上，我一眼看得见。
   ⚠️ `g` 只当**抽样透镜**用，不当过滤器（`[[criteria-from-meaning-not-form]]`：
     字面重合是形式代理，「栗子」与「壳斗科落叶乔木」重合 0 个字却完全正确）。
③ **一致性控制**：同一批词换一个打乱种子再跑一遍，两份应答应当一致。
   这是唯一能问出「它到底在读意思还是在猜」的控制 ——
   位置基线只能证伪，一致性能证实。
④ 源侧去重、④ 落库前把 v1 整层删掉再写（同一个 dbtool 会话，可回滚）。

═══ 判官纪律，逐条落到设计上（v1 就有，保留）═══
⑧ **payload 必须带权威源值** → 每条义项同时给英文原文和中文。
② **编号一律用数据库主键** → `s` 是 `sense.id`，prompt 写明「不是序号」。
⑦ **用前必跑负控** → 掺入别的词的德语释义，正确答案全是 `null`。
④ **控制组必须覆盖每一个输出字段** → 本族输出是 `g` 和 `s`，两个都有判据。

用法（在 de/ 目录下）：
    python3 -u pipeline/adjudicate_de_glosses.py --slice 300              # 关思考
    python3 -u pipeline/adjudicate_de_glosses.py --slice 300 --think      # 开思考
    python3 -u pipeline/adjudicate_de_glosses.py --slice 300 --shuf 2     # 一致性对照
    python3 -u pipeline/adjudicate_de_glosses.py --slice 300 --vs-v1      # 与 v1 并排
    python3 -u pipeline/adjudicate_de_glosses.py --apply                  # 全量落库
"""
import argparse
import gzip
import json
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import paths                                                   # noqa: E402
import slot_translate                                          # noqa: E402
from ingest_de_senses import is_real_sense                     # noqa: E402
from intake_edition_words import EDITIONS, norm_word           # noqa: E402

f = lambda n: format(n, ",")
SRC = "de-edition-adjudicated"

# 🔴 **本族要把批调小**。共用件默认 160，那是给翻译族调的（一条进一条出）。
#    v2 每条要多吐一个 `g`，输出长了一倍 ⇒ 切片实测 300 词里 **195 条第一遍没答上**，
#    靠对半切补回来 —— 补回来的那几批，**入 token 是白付的第二遍**（入 83,037，
#    没有重试大约只要 50,000）。⇒ 从一开始就发小批，别指望重试兜底。
#    （`[[retry-must-converge-or-drop-loud]]` 保证的是「会收敛」，不是「不浪费」。）
slot_translate.CHUNK = 60
V1_OUT = paths.WORK / "adjudicate" / "de_gloss_map.jsonl"       # v1 留底，只读


def out_path(a):
    """v2 的落盘文件。**打乱种子进文件名** —— 不同种子的应答不能混进同一份，
    否则一致性控制就是拿自己比自己。"""
    n = "de_gloss_map2%s%s.jsonl" % ("_think" if a.think else "",
                                     "" if a.shuf == 1 else "_shuf%d" % a.shuf)
    return paths.WORK / "adjudicate" / n


SYS = """你在为一部德语词典做**义项对齐**。

给你一个德语词，以及：
· `senses`：这个词在词典里**已有**的义项，每条带 `s`（标识号）、`en`（英文原文）、`zh`（中文）
· `de`：德语维基词典给这个词写的德语释义，每条带 `i`（标识号）

任务：对**每一条德语释义**，判断它描述的是哪一条已有义项。

分两步做，两步都要输出：
  第一步 `g`：用**不超过 10 个汉字**写出这条德语释义的意思。先自己读懂它。
  第二步 `s`：在 `senses` 里找哪一条说的是同一件事，回传那条的 `s`；没有就 `null`。

规则：
1. `s` 和 `i` 都是**标识号，不是序号**，原样回传，不要改写、不要重新编号。
2. 🔴 **两个列表都是乱序的**，第几条对第几条毫无意义。
   德语版和英文版是两个社区各自切的义项，粒度和顺序都不同。
   只按 `g` 和 `zh`/`en` 说的是不是同一件事来判断。
3. **配不上就给 `null`** —— 德语版常写词典里没有的义项，留空是正常结果。
   **错配比留空糟得多**：错配会让读者读到一条与中文矛盾的德语原文。
4. 一条义项可以挂多条德语释义（德语版有时把一条义项拆得更细，
   `Enkel` 的「踝骨」和「踝关节」在我们这里都是一条「脚踝」）。
   ⚠️ 但如果你把**所有**德语释义都堆到同一条义项上，说明你没有在区分，请重想。
5. 一条德语释义只能挂到**一条**义项上。

输出 JSON 数组：
[{"id": <词的标识号>, "m": [{"i": <德语释义标识号>, "g": "<≤10字中文>", "s": <义项标识号或 null>}]}]
只输出 JSON，不要解释。"""


# ══════════════════════════════════════════════════════════ 取数
def pool(con):
    """→ [{id, w, senses, de}]，③ 档（条数不同，或两边都 >1）。

    🔴 **待重判的义项也算"缺德语释义"**：v1 写的那层整层作废，
       判据是「除了 v1 那层之外，还有没有别的来源给过它德语释义」。
       写成 `NOT EXISTS(... AND src<>SRC)`，而不是「没有 de 释义」——
       后者会把 37,980 条已被 v1 占住的义项整批排除，
       正是 `[[llm-as-evaluator-discipline]]` ⑫「取数把一整类排除在外」那个洞。
    """
    by_word = defaultdict(list)
    wid_of = {}
    for w, wid, sid, zh, en in con.execute(
            "SELECT d.word, d.id, s.id,"
            "       (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='zh' LIMIT 1),"
            "       (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='en' LIMIT 1)"
            "  FROM sense s JOIN dict d ON d.id=s.word_id"
            " WHERE NOT EXISTS(SELECT 1 FROM sense_gloss g "
            "                   WHERE g.sense_id=s.id AND g.lang='de' AND g.src<>?)"
            " ORDER BY s.rank", (SRC,)):
        k = norm_word(w)
        by_word[k].append({"s": sid, "en": en, "zh": zh})
        wid_of.setdefault(k, wid)
    print("■ 待判（含 v1 已占住、本轮作废的）词形 %s" % f(len(by_word)))

    path, need_filter = EDITIONS["de"]
    src = defaultdict(list)
    seen = defaultdict(set)                 # 🔴 源侧去重：同一个词在德语版有多条词条
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if need_filter and '"lang_code"' in line and '"de"' not in line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("lang_code") != "de":
                continue
            w = norm_word(e.get("word"))
            if w not in by_word:
                continue
            for s in e.get("senses") or []:
                if not is_real_sense(s):
                    continue
                g = re.sub(r"\s+", " ", (s.get("glosses") or [""])[0]).strip()
                if g and g not in seen[w]:
                    seen[w].add(g)
                    src[w].append(g)

    items = []
    for w, defs in src.items():
        senses = by_word[w]
        if len(senses) == 1 and len(defs) == 1:
            continue                        # ① 档，1.5c 已确定性做掉
        items.append({"id": str(wid_of[w]), "w": w, "senses": senses,
                      "de": [{"i": i, "t": t} for i, t in enumerate(defs)]})
    return items


def shuffle_view(items, seed):
    """🔴 **v2 的头号改动**：把两侧的呈现顺序打乱。

    v1 把 `senses` 按 `rank`、`de` 按 dump 顺序**排好**递过去，然后在 prompt 里
    请它「不要按位置」—— 结构上处处在鼓励，规则上一句话禁止，结果是 60% 的
    中等难度词按位置往下数。⇒ 线索要**从结构上拿掉**。

    ⚠️ 打乱的只是数组顺序，`i`/`s` 仍是真标识号 ⇒ 答案可续跑、可与 v1 并排。
    """
    for it in items:
        r = random.Random("%s|%d" % (it["id"], seed))
        r.shuffle(it["senses"])
        r.shuffle(it["de"])
    return items


def inject_negative(items, rng, rate=0.12):
    """🔴 负控：掺进别的词的德语释义，正确答案必须是 `null`（纪律 ⑦）。"""
    planted = {}
    pool_defs = [d["t"] for it in items for d in it["de"]]
    for it in items:
        if rng.random() > rate:
            continue
        alien = rng.choice(pool_defs)
        if any(alien == d["t"] for d in it["de"]):
            continue
        i = max(d["i"] for d in it["de"]) + 1
        it["de"].append({"i": i, "t": alien})
        planted[it["id"]] = {i}
    return planted


# ══════════════════════════════════════════════════════════ 控制判据
def positional(items, got):
    """→ (对数, 与位置基线一致的对数)。**基线按原始顺序算，不按打乱后的顺序。**

    这是唯一能证伪「它在按位置数」的判据。v1 全量 53.9%，
    其中每词只落 1 条的那档 80.9%（那档位置对也可能是真对，所以要分档看）。
    """
    tot = same = 0
    for it in items:
        rec = got.get(it["id"])
        if not rec:
            continue
        base = [s["s"] for s in sorted(it["senses"], key=lambda x: x["s"])]
        for x in (rec.get("m") or []):
            if not isinstance(x, dict) or x.get("s") is None:
                continue
            i = x.get("i")
            tot += 1
            if isinstance(i, int) and i < len(base) and base[i] == x["s"]:
                same += 1
    return tot, same


def controls(items, got, planted, title):
    """控制判据。**输出有 `g` 和 `s` 两个字段，两个都要有判据**（纪律 ④）。"""
    c, ex = Counter(), {}

    def hit(k, a, b=""):
        c[k] += 1
        ex.setdefault(k, (a, b))

    n = answered = 0
    neg_ok = 0
    for it in items:
        rec = got.get(it["id"])
        if not rec:
            continue
        n += 1
        m = rec.get("m") or []
        valid = {s["s"]: (s["zh"] or "") for s in it["senses"]}
        seen = Counter()
        idxs = {d["i"] for d in it["de"]}
        for x in m:
            if not isinstance(x, dict):
                hit("🔴 应答不是对象", str(x)[:40])
                continue
            i, sid, g = x.get("i"), x.get("s"), x.get("g")
            if i not in idxs:
                hit("🔴 德语释义标识号越界", it["w"], str(i))
            # ── `g` 的判据（v2 新增的输出字段）
            if not isinstance(g, str) or not g.strip():
                hit("🔴 没写中文改写 g（第一步没做）", it["w"], str(i))
            elif len(g) > 16:
                hit("中文改写 g 超长（要求 ≤10 字）", it["w"], g[:20])
            if sid is None:
                continue
            answered += 1
            if sid not in valid:
                hit("🔴 义项标识号不属于这个词（错配的最坏形态）", it["w"], str(sid))
                continue
            seen[sid] += 1
            # 抽样透镜，不是过滤器：g 与所选义项中文一个字都不重合 ⇒ 值得读
            if isinstance(g, str) and valid[sid] and not (set(g) & set(valid[sid])):
                hit("· g 与所选义项中文零重合（抽样透镜，不判红）",
                    it["w"], "%s ↮ %s" % (g[:10], valid[sid][:10]))
        if len(it["senses"]) >= 3 and len(seen) == 1 and sum(seen.values()) >= 3:
            hit("🔴 所有德语释义都堆到同一条义项（没在区分）", it["w"],
                "%d 条义项 / %d 条释义" % (len(it["senses"]), sum(seen.values())))
        if sum(1 for k in seen.values() if k > 1):
            hit("一条义项挂了多条德语释义（记账不判红）", it["w"], "")
        if not any(x.get("s") is not None for x in m if isinstance(x, dict)):
            hit("全部留空（模型判定一条都配不上）", it["w"])
        for i in planted.get(it["id"], ()):
            x = next((y for y in m if isinstance(y, dict) and y.get("i") == i), None)
            if x and x.get("s") is not None:
                hit("🔴🔴 负控失败：掺进去的别的词的释义被硬配上了", it["w"], str(x.get("s")))
            else:
                neg_ok += 1

    n = max(n, 1)
    print("\n══ %s（%s 个词）══" % (title, f(n)))
    for k, v in c.most_common():
        print("  %-48s %7s  %5.2f%%" % (k, f(v), 100.0 * v / n))
        a, b = ex[k]
        print("        %s %s" % (str(a)[:40], str(b)[:34]))
    npl = sum(len(v) for v in planted.values())
    print("  %-48s %7s / %s" % ("✅ 负控答对（掺进去的被判 null）", f(neg_ok), f(npl)))
    tot, pos = positional(items, got)
    print("  %-48s %7s / %s  %5.1f%%   （v1 全量 53.9%%）"
          % ("与位置基线一致的对数（越低越说明在读意思）", f(pos), f(tot),
             100.0 * pos / max(tot, 1)))
    print("  %-48s %7s  留空率 %.1f%%"
          % ("挂上的德语释义条数", f(answered),
             100.0 * (tot_de(items) - answered) / max(tot_de(items), 1)))
    hard = [k for k in c if k.startswith("🔴") and c[k] > 0.02 * n]
    print("  %s" % ("🔴 硬闸红了（>2%）：" + "；".join(hard) if hard
                    else "✅ 硬闸过（每条 🔴 都 ≤2%）"))
    return not hard


def tot_de(items):
    return sum(len(i["de"]) for i in items)


def consistency(a_items, a_got, b_got, planted):
    """🔴 **一致性控制**：同一批词、两个打乱种子，答案该一致。

    位置基线只能**证伪**（"它在按位置数"）；一致性能**证实** ——
    如果换个顺序它给出另一套答案，那它给的就不是对意思的判断，是对排列的反应。
    """
    tot = agree = both_null = 0
    diff = []
    for it in a_items:
        ra, rb = a_got.get(it["id"]), b_got.get(it["id"])
        if not ra or not rb:
            continue
        pl = planted.get(it["id"], set())
        ma = {x["i"]: x.get("s") for x in (ra.get("m") or [])
              if isinstance(x, dict) and x.get("i") not in pl}
        mb = {x["i"]: x.get("s") for x in (rb.get("m") or [])
              if isinstance(x, dict) and x.get("i") not in pl}
        for i in set(ma) & set(mb):
            tot += 1
            if ma[i] == mb[i]:
                agree += 1
                if ma[i] is None:
                    both_null += 1
            elif len(diff) < 12:
                t = next((d["t"] for d in it["de"] if d["i"] == i), "")
                diff.append((it["w"], t[:44], ma[i], mb[i]))
    print("\n══ 一致性（换一个打乱种子重跑同一批）══")
    print("  可比对数 %s   一致 %s  %.1f%%（其中两边都判 null %s）"
          % (f(tot), f(agree), 100.0 * agree / max(tot, 1), f(both_null)))
    nn = tot - both_null
    print("  去掉「两边都 null」后 %s 对，一致 %s  %.1f%%"
          % (f(nn), f(agree - both_null), 100.0 * (agree - both_null) / max(nn, 1)))
    for w, t, x, y in diff:
        print("   %-14s %-46s %s ↔ %s" % (w[:14], t, x, y))
    return 100.0 * agree / max(tot, 1)


def vs_v1(items, got):
    """与 v1 的应答并排 —— 差在哪、差多少。v1 是只读留底，不参与落库。"""
    v1 = slot_translate.done_keys(V1_OUT, land="id")
    tot = same = 0
    changed = []
    for it in items:
        ra, rb = got.get(it["id"]), v1.get(it["id"])
        if not ra or not rb:
            continue
        ma = {x["i"]: x.get("s") for x in (ra.get("m") or []) if isinstance(x, dict)}
        mb = {x["i"]: x.get("s") for x in (rb.get("m") or []) if isinstance(x, dict)}
        for i in set(ma) & set(mb):
            tot += 1
            if ma[i] == mb[i]:
                same += 1
            elif len(changed) < 25:
                t = next((d["t"] for d in it["de"] if d["i"] == i), "")
                zh = {s["s"]: s["zh"] for s in it["senses"]}
                g = next((x.get("g") for x in ra["m"]
                          if isinstance(x, dict) and x.get("i") == i), "")
                changed.append((it["w"], t[:40], g, zh.get(mb[i]), zh.get(ma[i])))
    print("\n══ 与 v1 并排（%s 对可比）══  相同 %s  %.1f%%"
          % (f(tot), f(same), 100.0 * same / max(tot, 1)))
    print("   %-12s %-42s %-11s %-15s → %s" % ("词", "德语释义", "v2的g", "v1 挂到", "v2 挂到"))
    for w, t, g, o, nw in changed:
        print("   %-12s %-42s %-11s %-15s → %s"
              % (w[:12], t, (g or "")[:11], (o or "∅")[:15], (nw or "∅")[:15]))


# ══════════════════════════════════════════════════════════ 落库
def apply(items, got, planted):
    """整层重写：**先删 v1 那 50,719 条，再写 v2**，同一个 dbtool 会话可回滚。

    落库前四道筛（与 v1 同，每一条对应一类控制判据）：
      ① 负控条按 `.planted.json` 的标识号剔（不靠"它答了 null"来剔）
      ② `i` 越界  ③ `s` 不属于这个词  ④ 这条义项已有**别的来源**的德语释义
    """
    import dbtool
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    other = {sid for (sid,) in con.execute(
        "SELECT sense_id FROM sense_gloss WHERE lang='de' AND src<>?", (SRC,))}
    n_old_g = con.execute("SELECT COUNT(*) FROM sense_gloss WHERE src=?", (SRC,)).fetchone()[0]
    n_old_s = con.execute("SELECT COUNT(*) FROM sense_src WHERE src=?", (SRC,)).fetchone()[0]
    con.close()

    gl, sr, stat = [], [], Counter()
    seq_of = Counter()
    for it in items:
        rec = got.get(it["id"])
        if not rec:
            stat["没有答案"] += 1
            continue
        pl = planted.get(it["id"], set())
        real = {d["i"]: d["t"] for d in it["de"] if d["i"] not in pl}
        valid = {x["s"] for x in it["senses"]}
        for x in (rec.get("m") or []):
            if not isinstance(x, dict):
                continue
            i, sid = x.get("i"), x.get("s")
            if sid is None:
                stat["模型判定配不上（留空）"] += 1
                continue
            if i in pl:
                stat["🔴 ① 负控条被硬配上，按标识号剔掉"] += 1
                continue
            if i not in real:
                stat["🔴 ② 标识号越界，剔掉"] += 1
                continue
            if sid not in valid:
                stat["🔴 ③ 义项不属于这个词，剔掉"] += 1
                continue
            if sid in other:
                stat["④ 这条义项已有别的来源的德语释义"] += 1
                continue
            seq = seq_of[sid]
            seq_of[sid] += 1
            gl.append((sid, "de", "definition", seq, real[i], SRC))
            sr.append((int(it["id"]), sid, SRC,
                       "kk-de-adj2:%s#%d" % (it["w"], i), "de", real[i], None))
            stat["✅ 落库"] += 1

    for k, v in stat.most_common():
        print("   %-42s %10s" % (k, f(v)))
    n_multi = sum(1 for v in seq_of.values() if v > 1)
    print("\n■ 删 v1 %s 条释义 / %s 条证据" % (f(n_old_g), f(n_old_s)))
    print("■ 写 v2 %s 条释义，覆盖 %s 条义项（其中 %s 条挂了多条）"
          % (f(len(gl)), f(len(seq_of)), f(n_multi)))
    print("■ 净变化 释义 %+d ／ 证据 %+d" % (len(gl) - n_old_g, len(sr) - n_old_s))

    with dbtool.session("keep-v3-c29-readjudicated",
                        expect={"#sense_gloss": len(gl) - n_old_g,
                                "#sense_src": len(sr) - n_old_s}) as s:
        s.execute("DELETE FROM sense_gloss WHERE src=?", (SRC,))
        s.execute("DELETE FROM sense_src WHERE src=?", (SRC,))
        s.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                      "VALUES (?,?,?,?,?,?)", gl)
        s.executemany("INSERT INTO sense_src (word_id,sense_id,src,src_ref,lang,text,raw_tags) "
                      "VALUES (?,?,?,?,?,?,?)", sr)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    print("\n═══ 闸② 不变量断言 ═══")
    checks = [
        ("🔴 本步的释义为空", q("SELECT COUNT(*) FROM sense_gloss WHERE src=%r "
                          "AND TRIM(COALESCE(text,''))=''" % SRC), 0),
        ("🔴 本步的证据行没挂上义项",
         q("SELECT COUNT(*) FROM sense_src WHERE src=%r AND sense_id IS NULL" % SRC), 0),
        ("🔴 本步的证据行挂到别的词上",
         q("SELECT COUNT(*) FROM sense_src x JOIN sense s ON s.id=x.sense_id "
           "WHERE x.src=%r AND s.word_id<>x.word_id" % SRC), 0),
        ("🔴 同一(义项,seq)重复",
         q("SELECT COUNT(*) FROM (SELECT sense_id,seq FROM sense_gloss WHERE lang='de' "
           "GROUP BY 1,2 HAVING COUNT(*)>1)"), 0),
        # 🔴 v1 的第二个缺陷专用闸：同一条义项挂了两条**逐字相同**的德语释义
        ("🔴 同一义项挂了逐字相同的德语释义（v1 有 561 条）",
         q("SELECT COALESCE(SUM(c-1),0) FROM (SELECT sense_id,text,COUNT(*) c "
           "FROM sense_gloss WHERE lang='de' GROUP BY 1,2 HAVING COUNT(*)>1)"), 0),
    ]
    ok2 = True
    for name, gotv, want in checks:
        good = gotv == want
        ok2 &= good
        print("   %s %-46s %10s  期望 %s" % ("✓" if good else "🔴", name, f(gotv), f(want)))
    miss = q("SELECT COUNT(*) FROM (SELECT DISTINCT s.word_id FROM sense s WHERE NOT EXISTS"
             "(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='de'))")
    print("\n■ 缺德语释义的词形 → %s" % f(miss))
    con.close()
    print("\n%s" % ("✓ 闸②全过" if ok2 else "🔴 有闸未通过"))
    return 0 if ok2 else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=int, default=0)
    ap.add_argument("--think", action="store_true",
                    help="开思考。判据：对齐是推导型任务（纪律 ⑦），由切片数据定")
    ap.add_argument("--shuf", type=int, default=1, help="打乱种子；换一个＝一致性对照")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--read", type=int, default=0)
    ap.add_argument("--vs-v1", action="store_true")
    ap.add_argument("--consistency", type=int, default=0, help="与该种子的那份比一致性")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    out = out_path(a)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    items = pool(con)
    con.close()
    print("■ ③ 档：%s 个词形 ／ %s 条德语释义待裁决" % (f(len(items)), f(tot_de(items))))

    rng = random.Random(11)
    want = rng.sample(items, min(a.slice, len(items))) if a.slice else items
    # 🔴 负控掺入的标识号必须落盘（`[[model-answer-files-key-by-id]]` 同一个道理）。
    #    ⚠️ 打乱种子不同 ⇒ 应答不同 ⇒ 负控也各存一份，不许共用。
    # 🔴 **已答过的重放掺入、没答过的当场补掺**，两件事必须都做。
    #    只做前半会留一个洞：先跑切片再跑全量时，`pfile` 已存在 ⇒ 走重放分支 ⇒
    #    剩下 24,360 个词**一条负控都没有**，而负控是纪律 ⑦ 的全部内容。
    #    ⇒ 判据是「**这个词**掺过没有」，不是「这个文件存在没有」
    #      （又一次「判据比它要描述的东西宽」：文件在 ≠ 每个词都掺过）。
    pfile = Path(str(out) + ".planted.json")
    planted = ({k: set(v) for k, v in json.loads(pfile.read_text()).items()}
               if pfile.exists() else {})
    old = set(planted)
    by_id = {it["id"]: it for it in want}
    for wid, iis in planted.items():                  # 已答过的：按落盘记录重放
        it = by_id.get(wid)
        if not it:
            continue
        have = {d["i"] for d in it["de"]}
        for i in sorted(iis):
            if i not in have:
                it["de"].append({"i": i, "t": "（负控占位，见 .planted.json）"})
    # 🔴 判据是「**还没被问过**」，不是「还没掺过」。
    #    用后者会给切片里那 267 个「答过但没被抽中掺入」的词补掺 —— 模型从没见过
    #    这条假释义，应答里自然没有它，而 `controls` 的 `else` 分支会把「没答」
    #    记成「答对了」⇒ **负控通过率被凭空抬高**。
    #    一条永远通过的检查等于没检查，比误报更危险。
    answered = set(slot_translate.done_keys(out, land="id"))
    fresh = [it for it in want if it["id"] not in answered and it["id"] not in old]
    if fresh:
        planted.update(inject_negative(fresh, rng))
        pfile.parent.mkdir(parents=True, exist_ok=True)
        pfile.write_text(json.dumps({k: sorted(v) for k, v in planted.items()},
                                    ensure_ascii=False))
        print("■ 新掺入 %s 个词（此前已掺 %s 个）" % (f(len(planted) - len(old)), f(len(old))))
    print("■ 本轮 %s 个词；负控掺入 %s 条别的词的释义（正确答案必须是 null）"
          % (f(len(want)), f(sum(len(v) for v in planted.values()))))

    shuffle_view(want, a.shuf)              # 🔴 v2 头号改动，在负控掺入之后
    print("■ 打乱种子 %d ／ 思考 %s" % (a.shuf, "开" if a.think else "关"))

    got = slot_translate.done_keys(out, land="id")
    if not a.audit:
        todo = [i for i in want if i["id"] not in got]
        if todo:
            slot_translate.translate(
                todo, SYS, out,
                fields=("id", "w", "senses", "de"),
                keep=("id", "w"), key_field="id", answer_field="m", land="id",
                think=a.think)
            got = slot_translate.done_keys(out, land="id")

    ok = controls(want, got, planted,
                  "控制判据（v2 对齐裁决，%s思考，种子 %d）"
                  % ("开" if a.think else "关", a.shuf))
    if a.consistency:
        b = argparse.Namespace(think=a.think, shuf=a.consistency)
        consistency(want, got, slot_translate.done_keys(out_path(b), land="id"), planted)
    if a.vs_v1:
        vs_v1(want, got)
    if a.read:
        pick = [x for x in want if x["id"] in got]
        for it in rng.sample(pick, min(a.read, len(pick))):
            print("\n── %s ──" % it["w"])
            for s in sorted(it["senses"], key=lambda x: x["s"]):
                print("   义项#%s zh=%s ｜ en=%s"
                      % (s["s"], (s["zh"] or "-")[:22], (s["en"] or "-")[:34]))
            m = {x.get("i"): x for x in (got[it["id"]].get("m") or []) if isinstance(x, dict)}
            for d in sorted(it["de"], key=lambda x: x["i"]):
                x = m.get(d["i"]) or {}
                print("   de[%d] → %-6s %-11s %s"
                      % (d["i"], x.get("s"), (x.get("g") or "")[:11], d["t"][:52]))
    print("\n%s" % ("✅ 控制判据全过" if ok else "🔴 有硬闸未过"))
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 硬闸未过，**不写库**")
        return 1
    return apply(want, got, planted)


if __name__ == "__main__":
    sys.exit(main())
