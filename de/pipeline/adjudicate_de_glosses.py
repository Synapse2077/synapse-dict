#!/usr/bin/env python3
"""C29 ③：德语释义与已有义项的**对齐裁决**。de 版，2026-09-04。

═══ 这是本项目 de 上唯一还要花钱的一笔 ═══
外锚闸量出德语版源头 238,364 条真释义、1.5a 只收 135,179。
1.5c 用**唯一映射**确定性补掉 36,134（免费），剩下的分三档：

    ① 库 1 条 · 源 1 条 · 词性相容   → 1.5c 已做，**免费**
    ② 库 n 条 · 源 n 条，按序位对    → 🔴 **不做**
    ③ 条数不同                       → **本步**，19,628 词形 / 36,641 条

🔴 **② 为什么不做**：它靠「两个版本的义项顺序一一对应」，而那是两个社区各自编的。
   ③ 的样本直接反证：`Neustadt` 库 27 条 / 源 2 条、`kommen` 库 19 条 / 源 8 条 ——
   两版切分义项的粒度根本不同。把下标当稳定契约正是 `[[one-problem-at-a-time]]` 的形状。

═══ 🔴 切片要回答的头号问题**不是「准确率多少」** ═══
fr 那轮的教训（`[[llm-as-evaluator-discipline]]`）：正控我量了三版
**60.7% → 77.3% → 100%，前两版全是我的分母错** —— 54.5% 的题根本**没有唯一正确答案**
（同词有「异体拼写」和「废弃异体形式」两条中文，挂哪条都对）。

⇒ 本切片的头号产出是：**这 19,628 个词里，有多少题是"有唯一正确答案"的**。
  这个比例决定全量该不该做、做完能信多少。准确率是第二位的。

═══ 判官纪律，逐条落到设计上 ═══
⑧ **payload 必须带权威源值**（fr 那轮给了 `src` 后误报从 45% 降到 78% 消解）
   → 每条义项**同时给英文原文和中文**。只给中文＝让它猜我们的译文对不对，那是另一个问题。
② **编号一律用数据库主键**（`[[model-answer-files-key-by-id]]`）
   → `s` 是 `sense.id`，prompt 写明「标识号不是序号，原样回传」。
     用下标的代价付过：`registrare` 那次中文贴到了别的义项上。
⑦ **用前必跑负控**
   → 切片里掺入**别的词的德语释义**，正确答案是全部 `null`。
     它要是硬往上配，这个判官就不能用。
④ **控制组必须覆盖每一个输出字段**（`[[control-must-cover-every-output-field]]`：
   那次烧掉 418 万 token 是因为只验了下标、没验中文）
   → 本族输出只有 `s`，所以控制判据全部围着它：值域外／挂到别的词上／
     同一条义项被两条德语释义同时认领／全 null 摆烂。

═══ ⚠️ think 开关：**两条记忆在这里冲突，不靠记忆裁决** ═══
`[[batch-never-enables-thinking]]`：跑批一律关思考，判据是「任务是不是推导型」；
`[[llm-as-evaluator-discipline]]` ⑦：**推导型判官必须开思考**
（v4-pro 关思考在 es 上 0/2 摆烂）。
翻译不是推导型，**对齐是**。⇒ 同一批切片跑两遍（关/开）并排比，用数据定。
多花的钱是几分钱级别。

用法（在 de/ 目录下）：
    python3 -u pipeline/adjudicate_de_glosses.py --slice 300           # 关思考
    python3 -u pipeline/adjudicate_de_glosses.py --slice 300 --think   # 开思考
    python3 -u pipeline/adjudicate_de_glosses.py --audit               # 只看控制判据
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
from build import POS_MAP                                      # noqa: E402
from ingest_de_senses import is_real_sense                     # noqa: E402
from intake_edition_words import EDITIONS, norm_word           # noqa: E402

f = lambda n: format(n, ",")
OUT_OFF = paths.WORK / "adjudicate" / "de_gloss_map.jsonl"
OUT_ON = paths.WORK / "adjudicate" / "de_gloss_map_think.jsonl"

SYS = """你在为一部德语词典做**义项对齐**。

给你一个德语词，以及：
· `senses`：这个词在词典里**已有**的义项，每条带 `s`（标识号）、`en`（英文原文）、`zh`（中文）
· `de`：德语维基词典给这个词写的德语释义，每条带 `i`（序号）

任务：判断**每一条德语释义描述的是哪一条已有义项**。

规则：
1. `s` 是**数据库标识号，不是序号**，原样回传，不要改写、不要重新编号。
2. 一条德语释义只能挂到**一条**义项上。
3. **配不上就给 `null`** —— 德语版可能写了词典里没有的义项。宁可留空，不要硬配。
4. **一条义项可以挂多条德语释义** —— 德语版常常把我们的一条义项拆得更细
   （`Enkel` 的「踝骨」和「踝关节」在我们这里都是一条「脚踝」，两条都该挂上）。
   ⚠️ 但如果你把**所有**德语释义都堆到了同一条义项上，说明你没有在区分，请重想。
5. 判断依据是**意思**，不是位置、不是长短、不是顺序。
   德语版和英文版切分义项的粒度不同，第 1 条对第 1 条经常是错的。
6. 拿不准就给 `null`。**错配比留空糟得多。**

输出 JSON 数组：[{"id": <词的标识号>, "m": [{"i": <德语释义序号>, "s": <义项标识号或 null>}]}]
只输出 JSON，不要解释。"""


def pool(con):
    """→ [{id, w, pos, senses, de}]，只取 ③ 档（库 n 条 · 源 m 条，n≠m 或都>1）。"""
    # 库侧：缺德语释义的义项，按词形聚
    by_word = defaultdict(list)
    pos_of, wid_of = {}, {}
    for w, wid, sid, pos, zh, en in con.execute(
            "SELECT d.word, d.id, s.id, s.pos,"
            "       (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='zh' LIMIT 1),"
            "       (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='en' LIMIT 1)"
            "  FROM sense s JOIN dict d ON d.id=s.word_id"
            " WHERE NOT EXISTS(SELECT 1 FROM sense_gloss g "
            "                   WHERE g.sense_id=s.id AND g.lang='de')"
            " ORDER BY s.rank"):
        k = norm_word(w)
        by_word[k].append({"s": sid, "en": en, "zh": zh})
        pos_of.setdefault(k, pos)
        wid_of.setdefault(k, wid)
    print("■ 缺德语释义的词形 %s" % f(len(by_word)))

    # 源侧：德语版的真释义
    path, need_filter = EDITIONS["de"]
    src = defaultdict(list)
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
                if g:
                    src[w].append(g)

    items = []
    for w, defs in src.items():
        senses = by_word[w]
        # ① 档（1对1）1.5c 已做；这里只要 ③：条数不同，或两边都 >1
        if len(senses) == 1 and len(defs) == 1:
            continue
        items.append({"id": str(wid_of[w]), "w": w, "pos": pos_of[w],
                      "senses": senses, "de": [{"i": i, "t": t}
                                               for i, t in enumerate(defs)]})
    return items


def inject_negative(items, rng, rate=0.12):
    """🔴 负控：给一部分词**掺进别的词的德语释义**，正确答案必须是 `null`。

    ⑦「用前必跑负控」—— 判官会不会硬往上配，只有这样才问得出来。
    → {词id: {掺进去的 i}}，供控制判据核对。
    """
    planted = {}
    pool_defs = [d["t"] for it in items for d in it["de"]]
    for it in items:
        if rng.random() > rate:
            continue
        alien = rng.choice(pool_defs)
        if any(alien == d["t"] for d in it["de"]):
            continue
        i = len(it["de"])
        it["de"].append({"i": i, "t": alien})
        planted[it["id"]] = {i}
    return planted


def controls(items, got, planted, title):
    """控制判据。**输出只有 `s` 这一个字段，所以判据全部围着它。**"""
    c, ex = Counter(), {}
    by_id = {it["id"]: it for it in items}

    def hit(k, a, b=""):
        c[k] += 1
        ex.setdefault(k, (a, b))

    n = answered = 0
    unique_ok = 0
    for it in items:
        rec = got.get(it["id"])
        if not rec:
            continue
        n += 1
        m = rec.get("m") or []
        valid = {s["s"] for s in it["senses"]}
        seen = Counter()
        idxs = {d["i"] for d in it["de"]}
        for x in m:
            if not isinstance(x, dict):
                hit("🔴 应答不是对象", str(x)[:40])
                continue
            i, sid = x.get("i"), x.get("s")
            if i not in idxs:
                hit("🔴 德语释义序号越界", it["w"], str(i))
            if sid is None:
                continue
            answered += 1
            if sid not in valid:
                # ⑧ 最要命的一类：挂到了**别的词**的义项上
                hit("🔴 义项标识号不属于这个词（错配的最坏形态）", it["w"], str(sid))
                continue
            seen[sid] += 1
        # 🔴🔴 **v1 判据写错了**：原来是「同一条义项被多条认领 ⇒ 红」，实测 27.67%，
        #    读样本发现**大多是对的** —— `Enkel` 的 de[2]「踝骨」与 de[3]「踝关节」
        #    都该挂到我们那唯一一条「脚踝」上，而 `sense_gloss` 的主键
        #    `(sense_id, lang, kind, seq)` 里的 `seq` **本来就是为这件事留的**。
        #    ⇒ 我的规则在跟表结构打架（今天第 N 次「判据比它要描述的东西窄」）。
        #    真正的风险不是「多对一」，是**根本没在区分** ⇒ 判据换成下面这条。
        if len(it["senses"]) >= 3 and len(seen) == 1 and sum(seen.values()) >= 3:
            hit("🔴 所有德语释义都堆到同一条义项（没在区分）", it["w"],
                "%d 条义项 / %d 条释义" % (len(it["senses"]), sum(seen.values())))
        multi = sum(1 for k in seen.values() if k > 1)
        if multi:
            hit("一条义项挂了多条德语释义（德语版切得更细，记账不判红）", it["w"], str(multi))
        if not any(x.get("s") is not None for x in m if isinstance(x, dict)):
            hit("全部留空（模型判定一条都配不上）", it["w"])
        # 🔴 负控：掺进去的那条**必须**是 null
        for i in planted.get(it["id"], ()):
            x = next((y for y in m if isinstance(y, dict) and y.get("i") == i), None)
            if x and x.get("s") is not None:
                hit("🔴🔴 负控失败：掺进去的别的词的释义被硬配上了", it["w"], str(x.get("s")))
            else:
                unique_ok += 1

    n = max(n, 1)
    print("\n══ %s（%s 个词）══" % (title, f(n)))
    for k, v in c.most_common():
        print("  %-46s %7s  %5.2f%%" % (k, f(v), 100.0 * v / n))
        a, b = ex[k]
        print("        %s %s" % (str(a)[:40], str(b)[:30]))
    npl = sum(len(v) for v in planted.values())
    print("  %-46s %7s / %s" % ("✅ 负控答对（掺进去的被判 null）", f(unique_ok), f(npl)))
    print("  %-46s %7s" % ("挂上的德语释义条数", f(answered)))
    hard = [k for k in c if k.startswith("🔴") and c[k] > 0.02 * n]
    print("  %s" % ("🔴 硬闸红了（>2%）：" + "；".join(hard) if hard
                    else "✅ 硬闸过（每条 🔴 都 ≤2%）"))
    return not hard


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", type=int, default=0)
    ap.add_argument("--think", action="store_true",
                    help="开思考（跑批默认关，见文件头「两条记忆冲突」那段）")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--read", type=int, default=0)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    out = OUT_ON if a.think else OUT_OFF
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    items = pool(con)
    con.close()
    nde = sum(len(i["de"]) for i in items)
    print("■ ③ 档：%s 个词形 ／ %s 条德语释义待裁决" % (f(len(items)), f(nde)))

    rng = random.Random(11)
    want = rng.sample(items, min(a.slice, len(items))) if a.slice else items
    # 🔴 负控掺入的下标**必须落盘**：它决定了落库时哪一条 `i` 是假的。
    #    不落盘的话，下一次跑（种子/顺序但凡有一点不同）就分不清真假 ——
    #    与 `[[model-answer-files-key-by-id]]` 同一个道理：**别让"第几条"成为隐含契约**。
    pfile = Path(str(out) + ".planted.json")
    if pfile.exists() and not a.slice:
        planted = {k: set(v) for k, v in json.loads(pfile.read_text()).items()}
        for it in want:                      # 按落盘的记录重放掺入，保证下标对得上
            for i in sorted(planted.get(it["id"], ())):
                if i >= len(it["de"]):
                    it["de"].append({"i": i, "t": "（负控占位，见 .planted.json）"})
    else:
        planted = inject_negative(want, rng)
        if not a.slice:
            pfile.parent.mkdir(parents=True, exist_ok=True)
            pfile.write_text(json.dumps({k: sorted(v) for k, v in planted.items()},
                                        ensure_ascii=False))
    print("■ 本轮 %s 个词；负控掺入 %s 条别的词的释义（正确答案必须是 null）"
          % (f(len(want)), f(sum(len(v) for v in planted.values()))))

    got = slot_translate.done_keys(out, land="id")
    if not a.audit:
        todo = [i for i in want if i["id"] not in got]
        if todo:
            slot_translate.translate(
                todo, SYS, out,
                fields=("id", "w", "pos", "senses", "de"),
                keep=("id", "w"), key_field="id", answer_field="m", land="id",
                think=a.think)
            got = slot_translate.done_keys(out, land="id")

    ok = controls(want, got, planted, "控制判据（对齐裁决，%s思考）" % ("开" if a.think else "关"))
    if a.read:
        for it in rng.sample([x for x in want if x["id"] in got], min(a.read, len(want))):
            print("\n── %s ──" % it["w"])
            for s in it["senses"]:
                print("   义项#%s zh=%s ｜ en=%s" % (s["s"], (s["zh"] or "-")[:22], (s["en"] or "-")[:34]))
            m = {x.get("i"): x.get("s") for x in (got[it["id"]].get("m") or []) if isinstance(x, dict)}
            for d in it["de"]:
                print("   de[%d] → %s   %s" % (d["i"], m.get(d["i"]), d["t"][:56]))
    print("\n%s" % ("✅ 控制判据全过" if ok else "🔴 有硬闸未过"))
    if not a.apply:
        print("\n(未加 --apply，未写库)")
        return 0
    if not ok:
        print("\n🔴 硬闸未过，**不写库**")
        return 1
    return apply(want, got, planted)


SRC = "de-edition-adjudicated"


def apply(items, got, planted):
    """把裁决结果写成 `sense_gloss(de)` + `sense_src` 留底。

    🔴 落库前四道筛，每一条都对应控制判据里的一类：
      ① 掺进去的负控条 —— 按 `.planted.json` 的下标剔掉，**不靠"它答了 null"来剔**
         （它有 32 条硬配上了，正是要靠下标挡住）
      ② `i` 越界（219 条）
      ③ `s` 不属于这个词（6 条，错配的最坏形态）
      ④ 这条义项已经有德语释义了（防重入）
    ⚠️ **一条义项可以挂多条**（德语版切得更细，`aussterben` 的两条都是「灭绝」），
       靠 `sense_gloss` 主键里的 `seq` 区分 —— 那一列本来就是为这件事留的。
    """
    import dbtool
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    has_de = {sid for (sid,) in con.execute(
        "SELECT sense_id FROM sense_gloss WHERE lang='de'")}
    wid_of = {}
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
                stat["🔴 ① 负控条被硬配上，按下标剔掉"] += 1
                continue
            if i not in real:
                stat["🔴 ② 序号越界，剔掉"] += 1
                continue
            if sid not in valid:
                stat["🔴 ③ 义项不属于这个词，剔掉"] += 1
                continue
            if sid in has_de:
                stat["④ 这条义项已有德语释义（防重入）"] += 1
                continue
            seq = seq_of[sid]
            seq_of[sid] += 1
            gl.append((sid, "de", "definition", seq, real[i], SRC))
            sr.append((int(it["id"]), sid, SRC,
                       "kk-de-adj:%s#%d" % (it["w"], i), "de", real[i], None))
            stat["✅ 落库"] += 1

    for k, v in stat.most_common():
        print("   %-40s %10s" % (k, f(v)))
    n_multi = sum(1 for v in seq_of.values() if v > 1)
    print("\n■ 将写入 %s 条德语释义，覆盖 %s 条义项（其中 %s 条挂了多条）"
          % (f(len(gl)), f(len(seq_of)), f(n_multi)))

    with dbtool.session("keep-v3-c29-adjudicated",
                        expect={"#sense_gloss": len(gl), "#sense_src": len(sr)}) as s:
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
    ]
    ok2 = True
    for name, gotv, want in checks:
        good = gotv == want
        ok2 &= good
        print("   %s %-38s %10s  期望 %s" % ("✓" if good else "🔴", name, f(gotv), f(want)))
    miss = q("SELECT COUNT(*) FROM (SELECT DISTINCT s.word_id FROM sense s WHERE NOT EXISTS"
             "(SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='de'))")
    print("\n■ 缺德语释义的词形 → %s" % f(miss))
    con.close()
    print("\n%s" % ("✓ 闸②全过" if ok2 else "🔴 有闸未通过"))
    return 0 if ok2 else 1


if __name__ == "__main__":
    sys.exit(main())
