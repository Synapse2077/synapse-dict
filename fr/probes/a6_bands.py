#!/usr/bin/env python3
"""收尾单 A6 —— 按**批内长度相关性**分档，逐档判、修、验、换。2026-08-28。

═══ 这个文件补的是一个洞，不是一个新想法 ═══
A6（跑批答案贴错条目）我 8-28 上午做过一轮，结论写的是「**信号在 3% 档耗尽 ⇒ 收口**」：

    0–1% 档 29.2% ／ 1–2% 4.7% ／ 2–3% 1.5% ／ 3–4% 0.5% ／ 4–5% 0.3%   （背景 0.75%）

🔴 那条曲线是错的 —— 不是数算错，是**池子少了 20% 的人**。
`judge_example_offpool.py` 的取数是 `JOIN sense s ON s.id=e.sense_id`（内连接），
`sense_id IS NULL` 的 **147,405 条**例句（有中文、页面"例句"块里就摆着）
从来没进过判官的池子，族 A 和 A6 两轮都没有。

怎么发现的：第二轮外审，两家**各自独立**指出 `clair` 的例句块「原文与译文完全错位」。
回源：8 条错译同属一批（Spearman r=0.450，**百分位 0.36%**，本来就在我送过判官的
最低 1% 档里），而它们 `sense_id` 全是 NULL ⇒ 被内连接吃掉。

    Mais, ô planète belle et claire […]        → 后来，主塔不再有人居住…（那是下面第 5 句的译文）
    Adieu donc, clairs soleils si divins…      → 17 间客房舒适明亮…（第 6 句的）
    Des armes claires.                          → 天气晴朗，天空清澈（第 20 句的）

⭐ **闸问「有没有」，判官问「对不对」，而「判官的池子有没有洞」这个问题，
   只有把成品摆到另一双眼睛面前才会被问出来。** 这一轮外审花了几元钱。

═══ 方法（不变，见 `probes/batch_misassignment.py`）═══
`pool()` 是 `ORDER BY id` 确定性的、`CHUNK=40` ⇒ 批次可离线完整重建。
批内配对被打乱 ⇒ 长句配到短译文 ⇒ 该批 `len(fr)~len(zh)` 的 Spearman 相关塌掉。
⚠️ 信号在**批**这一层，不在条目这一层；它只负责缩小范围，判还是判官判、人还是要抽读。

═══ 四段，每段可续跑（与 `fix_example_sense_mismatch.py` 同一套纪律）═══
    ① --judge        判该档里**还没判过**的
    ② --retranslate  只重翻被判 `other` 的
    ③ --verify       判新译文
    ④ --apply        **只在「旧的判坏、新的判好」时才替换**
④ 那条判据是安全性所在：判官过宽只会让某些条目白重翻一次，漏判只是维持现状。

用法（在 fr/ 目录下，**排低谷跑**）：
    python3 -u probes/a6_bands.py --band 0 1            # 只看这一档有多少没判过
    python3 -u probes/a6_bands.py --band 0 1 --judge
    python3 -u probes/a6_bands.py --band 0 1 --retranslate --verify
    python3 -u probes/a6_bands.py --band 0 1 --apply
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import dbtool                                    # noqa: E402
import paths                                     # noqa: E402
from pipeline import slot_translate              # noqa: E402
from pipeline import translate_examples as _tx   # noqa: E402
import batch_misassignment as _bm                # noqa: E402
import judge_example_offpool as _j               # noqa: E402

f = lambda n: format(n, ",")
EX = paths.WORK / "examples"
JUDGE = EX / "a6_band.jsonl"        # ① 旧译文的判官结论（跨档累积，就是台账）
RT = EX / "a6_bands_rt.jsonl"       # ② 重翻
VERIFY = EX / "a6_bands_v2.jsonl"   # ③ 新译文的判官结论

# 全库随机抽样测出来的背景率 —— 一个档的富集要跟它比，不是跟 0 比
BACKGROUND = 0.0075


def band_ids(con, lo, hi):
    """→ 该百分位档里的 example_id 集合。批次离线重建，不请模型。"""
    ans = slot_translate.done_keys(EX / "example_zh.jsonl")
    cs = _bm.chunks(con, ans)
    cs.sort(key=lambda x: x[0])
    a, b = int(len(cs) * lo / 100), int(len(cs) * hi / 100)
    return {str(e) for _r, i in cs[a:b] for e in i}, len(cs), cs[max(a, 0)][0], cs[b - 1][0]


def judged_before():
    """已经判过的 id —— **跨文件累积**。

    🔴 这一步就是 `[[record-the-negative-decision]]`：「判过且判为 ok」和
       「还没判过」必须分得开，否则下一轮又要重判一遍（那次我烧了 135 万 token）。
    """
    out = {}
    for name in ("a6_lowcorr", "a6_cand", "a6_judge2", "a6_band", "offpool_judge"):
        p = EX / (name + ".jsonl")
        if not p.exists():
            continue
        for ln in p.open(encoding="utf-8"):
            try:
                o = json.loads(ln)
            except ValueError:
                continue
            out[str(o.get("id", "")).lstrip("N")] = str(o.get("v", "")).strip().lower()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--band", nargs=2, type=float, default=(0, 1), metavar=("LO", "HI"))
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--retranslate", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--read", type=int, default=0)
    a = ap.parse_args()
    lo, hi = a.band

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ids, nb, r_lo, r_hi = band_ids(con, lo, hi)
    items = {i["id"]: i for i in _j.pool(con)}
    # 🔴 **已经修过的不许再修一遍**：判官的结论是对**当时那条旧译文**下的，
    #    行修过之后 `other` 这个结论就过期了，拿它再触发一次重翻 = 用新一轮的
    #    抖动去覆盖已经修对的译文（探针实测这个任务重跑 85% 会变文本）。
    #    ⇒ 判据用落库时打的来源标记，而不是"我记得修过"。
    fixed = {str(i) for (i,) in con.execute(
        "SELECT example_id FROM example_gloss WHERE lang='zh' AND src LIKE 'model:example:a6%'")}
    con.close()

    done = judged_before()
    inband = [items[i] for i in ids if i in items]
    todo = [i for i in inband if i["id"] not in done]
    noattach = sum(1 for i in inband if not i["sense"])
    print("■ %g–%g%% 档（r∈[%.3f, %.3f]，全库 %s 批）" % (lo, hi, r_lo, r_hi, f(nb)))
    print("   档内在池子里的例句 %s 条（其中**没挂义项** %s 条 —— 就是内连接吃掉的那批）"
          % (f(len(inband)), f(noattach)))
    print("   还没判过 %s 条" % f(len(todo)))

    if a.judge and todo:
        slot_translate.translate(todo, _j.SYS, JUDGE,
                                 fields=("id", "fr", "w", "sense", "zh"),
                                 keep=("id", "w"), key_field="id", answer_field="v",
                                 land="id")
        done = judged_before()

    # ── 报这一档的富集 ────────────────────────────────────────────────
    c = Counter(done.get(i["id"], "未判") for i in inband)
    n = sum(v for k, v in c.items() if k in ("ok", "sense", "other"))
    bad = [i for i in inband if done.get(i["id"]) == "other" and i["id"] not in fixed]
    already = sum(1 for i in inband if done.get(i["id"]) == "other" and i["id"] in fixed)
    if n:
        print("\n══ 判官结果 ══  %s" % dict(c))
        nb_other = len(bad) + already
        print("   🔴 other（答案贴错条目）%s / %s = **%.2f%%**   背景 %.2f%% ⇒ 富集 %.1f 倍"
              % (f(nb_other), f(n), 100.0 * nb_other / n, 100 * BACKGROUND,
                 (nb_other / n) / BACKGROUND if n else 0))
        print("      其中上一轮已经修过 %s 条 ⇒ 本轮待修 %s 条" % (f(already), f(len(bad))))
        # 没挂义项那批单独报一次 —— 这一轮要回答的就是「它们是不是更脏」
        na = [i for i in inband if not i["sense"] and done.get(i["id"]) in ("ok", "sense", "other")]
        nab = [i for i in na if done.get(i["id"]) == "other"]
        if na:
            print("   其中**没挂义项**的：%s / %s = %.2f%%" % (f(len(nab)), f(len(na)),
                                                        100.0 * len(nab) / len(na)))

    if a.read:
        print("\n══ 抽读（判官不是真值，我要自己看）══")
        for i in bad[:a.read]:
            print("\n[%s] 义项：%s" % (i["w"], (i["sense"] or "（没挂义项）")[:24]))
            print("   FR %s" % i["fr"][:130])
            print("   ZH %s" % i["zh"][:110])

    if a.retranslate and bad:
        slot_translate.translate([{"id": i["id"], "fr": i["fr"]} for i in bad],
                                 _tx.SYS, RT, fields=("id", "fr"),
                                 keep=("id",), key_field="id", answer_field="zh", land="id")
    if a.verify:
        new = slot_translate.done_keys(RT, "id")
        cand = [dict(i, zh=new[i["id"]]["zh"]) for i in bad
                if i["id"] in new and (new[i["id"]].get("zh") or "").strip()]
        if cand:
            slot_translate.translate(cand, _j.SYS, VERIFY,
                                     fields=("id", "fr", "w", "sense", "zh"),
                                     keep=("id", "w"), key_field="id", answer_field="v",
                                     land="id")

    if a.apply:
        new = slot_translate.done_keys(RT, "id")
        v2 = slot_translate.done_keys(VERIFY, "id")
        # 🔴 唯一的替换判据：**旧的判坏、新的判好**。缺任何一半都不动。
        rep = [(new[i["id"]]["zh"], int(i["id"])) for i in bad
               if i["id"] in new and (new[i["id"]].get("zh") or "").strip()
               and str(v2.get(i["id"], {}).get("v", "")).strip().lower() == "ok"]
        print("\n■ 旧坏+新好 ⇒ 可替换 %s 条（新译文仍判坏的 %s 条不动）"
              % (f(len(rep)), f(len(bad) - len(rep))))
        for zh, eid in rep[:6]:
            print("   %s → %s" % (eid, zh[:70]))
        if rep:
            with dbtool.session("keep-v3-a6-band-%g-%g" % (lo, hi), expect={}) as s:
                s.executemany(
                    "UPDATE example_gloss SET text=?, src='model:example:a6fix' "
                    "WHERE example_id=? AND lang='zh'", rep)
            print("✓ 替换 %s 条" % f(len(rep)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
