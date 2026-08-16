#!/usr/bin/env python3
"""收尾：把意语版**剩下的 10,263 条真定义**全部上架。2026-08-15。

═══ 剩的是谁 ═══
③（意语 1 条）与 ④⑤（意语多条）跑完后，`sense_src(sense_id IS NULL)` 里
过完 `not_a_definition` / `PTR` / A38 指针三道筛，还剩 10,313 条，实测：

    ① 纯链接残渣（`casa ( approfondimento) f sing`）         5   ← 不上架
    ② 只剩性数标签或空（`scarlatto` / `tesauro m`）          16   ← 不上架
    ③ 只有拉丁学名（`la sua classificazione scientifica è…`） 29   ← 照送，模型认得
    ✅ 真定义                                          10,263

两个来源，但**操作是同一个**：新建义项 + 中文从意语原文直译。
  · B 我们缺整个词性 5,300（51.4%）——`inventore` 的形容词义、`parlare` 的名词化
    不定式、`arancione` 的名词义。这是**结构性缺口**，不是零碎补漏。
  · C 有该词性但没挂上 5,000（48.5%）——④⑤ 里模型判 0 却没吐中文的，
    以及"撞车降级"的（两条意语释义指向我们同一条 ⇒ 我们那条是粗口袋）。

═══ 与 ④⑤ 的唯一差别 ═══
`senses` 常为空 ⇒ 模型不用选、只用翻，任务更简单。
其余全部复用：同 prompt、同 payload 形状、同 `resolve` 的确定性指派、
同「新建中文与已有逐字相同就不落库」的兜底、同一套闸。

🔴 模型只用 DeepSeek flash（豆包已在 `ark_batch` 硬拦截，2026-08-15 用户明令）。
🔴 先跑 1% 切片、我自己读完再放全量（`control-must-cover-every-output-field` 的教训：
   上一次是跑完 418 万 tokens 才第一次读产出）。

用法（在 it/ 目录下）：
    python3 pipeline/finish_it_defs.py --plan
    python3 pipeline/finish_it_defs.py --run --slice 100    # 切片
    python3 pipeline/finish_it_defs.py --read               # 自己读切片产出
    python3 pipeline/finish_it_defs.py --run                # 全量
    python3 pipeline/finish_it_defs.py --apply
    python3 pipeline/finish_it_defs.py --verify
"""
import argparse
import asyncio
import json
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fixes"))

import dbtool      # noqa: E402
import ds_batch    # noqa: E402
import paths       # noqa: E402
from align_it_defs import batched   # noqa: E402
from align_it_multi import SYS, ZH_SRC, gate, payload, resolve   # noqa: E402  一把尺
from demote_alt_pointer_defs import is_pointer   # noqa: E402
from promote_it_gloss import PTR, SRC, pos_of_ref   # noqa: E402
from strip_it_placeholder import clean, not_a_definition   # noqa: E402

OUT = paths.WORK / "it_finish.jsonl"
CHUNK = 8

# 上架前的最后三道确定性筛（实测各 5 / 16 / 0 条；学名那族照送模型）
LINK = re.compile(r"\(\s*(approfondimento|citazioni|vedi\s+approfondimento)\s*\)", re.I)
TAGS = re.compile(r"^\s*[mfnc]?\s*(sing|plur|inv)?\s*[mfnc]?\s*(sing|plur|inv)?\s*$", re.I)


def is_residue(text, head):
    """wiktextract 把「延伸阅读」链接和性数标签当成了 gloss。剥掉后什么都不剩＝残渣。"""
    core = LINK.sub("", clean(text)).strip()
    core = re.sub(r"^%s\b" % re.escape(head), "", core, flags=re.I).strip()
    core = re.sub(r"\b([mfnc])\s+(sing|plur|inv)\b", "", core, flags=re.I).strip(" ,;")
    return not core or bool(TAGS.match(core))


def load(con):
    """→ units[(wid,pos)] = dict(word,pos,its=[(xid,text)],ours=[(sid,en,zh)])，含残渣统计"""
    vis = defaultdict(list)
    for wid, sid, pos in con.execute(
            "SELECT s.word_id, s.id, COALESCE(e.pos, s.pos) FROM sense s "
            "LEFT JOIN entry e ON e.id=s.entry_id WHERE COALESCE(s.hidden,0)=0 ORDER BY s.rank"):
        vis[(wid, pos)].append(sid)
    gl = defaultdict(dict)
    for sid, lang, t in con.execute(
            "SELECT sense_id, lang, text FROM sense_gloss WHERE lang IN ('en','zh') AND seq=0"):
        gl[sid][lang] = t
    word = dict(con.execute("SELECT id, word FROM dict"))
    alt_t = defaultdict(list)
    for wid, tgt in con.execute("SELECT word_id, target FROM sense_relation WHERE kind='alt_of'"):
        alt_t[wid].append(tgt)

    per, stat = defaultdict(list), Counter()
    for xid, wid, ref, text in con.execute(
            "SELECT id, word_id, src_ref, text FROM sense_src "
            "WHERE src=? AND sense_id IS NULL ORDER BY id", (SRC,)):
        if not_a_definition(text) or PTR.match(text):
            continue
        if any(is_pointer(text, t) for t in alt_t.get(wid, [])):
            continue
        if is_residue(text, word[wid]):
            stat["🔴 残渣，不上架（链接/性数标签）"] += 1
            continue
        stat["✅ 待上架"] += 1
        per[(wid, pos_of_ref(ref))].append((xid, text))

    units = {}
    for (wid, pos), its in per.items():
        units[(wid, pos)] = dict(
            word=word[wid], pos=pos, its=its,
            ours=[(s, gl[s].get("en") or "", gl[s].get("zh") or "")
                  for s in vis.get((wid, pos), [])])
    return units, stat


def main():
    ap = argparse.ArgumentParser()
    for f in ("plan", "run", "read", "apply", "verify"):
        ap.add_argument("--" + f, action="store_true")
    ap.add_argument("--slice", type=int, default=0, help="只跑前 N 个单位（切片自检）")
    ap.add_argument("--conc", type=int, default=20)
    a = ap.parse_args()

    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    units, stat = load(ro)

    if a.plan:
        for k, v in stat.most_common():
            print("   %-32s %7s" % (k, f"{v:,}"))
        b = sum(1 for u in units.values() if not u["ours"])
        nb = sum(len(u["its"]) for u in units.values() if not u["ours"])
        print("\n■ 单位 (词形,词性) %s 个 / 意语释义 %s 条"
              % (f"{len(units):,}", f"{sum(len(u['its']) for u in units.values()):,}"))
        print("   B 我们缺整个词性  %s 个单位 / %s 条" % (f"{b:,}", f"{nb:,}"))
        print("   C 有该词性没挂上  %s 个单位 / %s 条"
              % (f"{len(units) - b:,}",
                 f"{sum(len(u['its']) for u in units.values() if u['ours']):,}"))
        print("\n   词性分布 %s" % Counter(u["pos"] for u in units.values()).most_common(8))
        return 0

    keys = sorted(units, key=lambda k: (k[0], k[1]))
    if a.slice:
        random.seed(5)
        keys = random.sample(keys, min(a.slice, len(keys)))

    if a.run:
        items = [(payload(units[k]), "%d|%s" % k) for k in keys]
        print("■ 本轮 %s 个单位 / %s 条意语释义"
              % (f"{len(items):,}", f"{sum(len(units[k]['its']) for k in keys):,}"), flush=True)
        ro.close()
        asyncio.run(ds_batch.run(SYS, *batched(items, CHUNK), OUT,
                                 mode="flash", conc=a.conc, every=20))
        return 0

    got = {}
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            r = json.loads(line)
            got[r["id"]] = r

    if a.read:
        rows = []
        for k in keys:
            u = units[k]
            r = got.get("%d|%s" % k)
            if not r:
                continue
            _h, fresh, _s = resolve(u, r)
            for _xid, it, zh in fresh:
                rows.append((u["word"], u["pos"], clean(it), zh,
                             [x[2] for x in u["ours"]]))
        print("■ 切片产出新建义项 %s 条，抽 18 条：" % f"{len(rows):,}")
        random.seed(3)
        for w, pos, it, zh, sib in random.sample(rows, min(18, len(rows))):
            print("\n  %-18s [%s]" % (w, pos))
            print("     it  %s" % it[:76])
            print("     新  %s" % zh[:46])
            print("     已有 %s" % ("／".join(x[:16] for x in sib[:3]) or "（无，我们缺这个词性）"))
        return 0

    if a.apply:
        # 🔴 已经挂着意语定义的义项不能再挂第二条（`UNIQUE(sense_id,lang,kind,seq)`）。
        #    `resolve()` 只防**本轮内部**撞车，防不住跟 ③/④⑤ 那两轮撞 ——
        #    第一版没挡，写库直接 IntegrityError（dbtool 已回滚，库未受损）。
        taken = {sid for (sid,) in ro.execute(
            "SELECT sense_id FROM sense_gloss WHERE lang='it' AND kind='definition'")}
        hooks, fresh, st = [], [], Counter()
        for k in keys:
            u = units[k]
            r = got.get("%d|%s" % k)
            if r is None:
                st["模型没回答（留证据层）"] += len(u["its"])
                continue
            h, f, s2 = resolve(u, r)
            for x in h:
                if x[0] in taken:
                    st["🔴 目标义项已有意语定义（留证据层）"] += 1
                    continue
                taken.add(x[0])
                hooks.append(x)
            fresh += [(k[0], k[1]) + x for x in f]
            st += s2
        for kk, v in st.most_common():
            print("   %-42s %7s" % (kk, f"{v:,}"))
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
        with dbtool.session("finish-it-defs",
                            expect={"#sense": len(s_rows), "#sense_gloss": len(g_rows)}) as wdb:
            wdb.executemany("INSERT INTO sense (id,word_id,rank,pos) VALUES (?,?,?,?)", s_rows)
            wdb.executemany("INSERT INTO sense_gloss (sense_id,lang,kind,seq,text,src) "
                            "VALUES (?,?,?,?,?,?)", g_rows)
            wdb.executemany("UPDATE sense_src SET sense_id=? WHERE id=?", link)
        print("■ 已写入")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
