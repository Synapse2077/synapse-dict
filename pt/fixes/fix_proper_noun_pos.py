#!/usr/bin/env python3
"""族I：葡语版没有「专名」这个类别，地名/人名全被标成「名词」。2026-08-30。

═══ 外审两家四版都点了同一个词 ═══
`Itaúna do Sul` —— 巴西市镇，页面上印着「名词」。回源查清楚了：

    ptwiktionary  pos = noun   pos_title = Substantivo   ← **葡语版根本没有专名这一类**
    kaikki(英文版) pos = name                             ← 英文版分

⇒ 不是我们标错，是**只有葡语版收的词拿不到这个区分**。凡是葡语版独有的地名/人名
  （巴西市镇、葡萄牙教区、人名），一律落成 `n`。

═══ 判据 ═══
🔴 不用"词形长得像专名"这种形式代理，用**源头自己说的**：
   葡语版的释义开头就点明了这条义项指的是什么类别 ——
   `município brasileiro do estado do Paraná` / `prenome feminino` / `freguesia de Portugal`。
   判据 = 释义以这些类别词开头 **且** 词形首字母大写。

⭐ **反向查逮到 91 条假阳**（`[[criteria-narrower-than-you-think]]` 的老套路）：
     achatadura   `estado de coisa que se achatou`   ← `estado` 是"状态"不是"州"
     balsedo      `ilha flutuante formada por plantas` ← 不是某个具体岛
   两条都是**小写**词形 ⇒ 加上"首字母大写"这一条就干净了（葡语普通名词不大写）。
   随机抽 30 条人眼核：30/30 全对。

═══ 三层 pos 怎么改 ═══
先量了三层之间的关系，**没有假设**：
  · `entry.pos` == 其义项 pos 集合排序后 `/` 连接 —— 实测 134,414 / 0 完全一致 ⇒ 可重算
  · `dict.pos`  != 其词条 pos 并集 —— **29,054 条不一致**（`abada` dict 是 `n`，词条有 n/v），
    它有自己的历史 ⇒ **不许整体重算**。只在「这个词的全部义项都变成专名、且 dict.pos
    恰好是 `n`」时改成 `name`，其余一律不动。

用法（在 pt/ 目录下）：
    python3 fixes/fix_proper_noun_pos.py
    python3 fixes/fix_proper_noun_pos.py --apply
"""
import argparse
import collections
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dbtool   # noqa: E402
import paths    # noqa: E402

# 源头释义开头的类别词。**按含义列**：这些词说明"这条义项指的是一个具体的地方/人"。
KIND = re.compile(
    r"^(município|cidade|vila|freguesia|distrito|rio |estado |província|comuna|aldeia"
    r"|localidade|concelho|povoação|ilha |lago |montanha|serra |sobrenome|prenome|apelido)",
    re.I)


def plan(con):
    hit, rejected = [], []
    for w, sid, pos, txt in con.execute(
            "SELECT d.word, s.id, s.pos, ss.text FROM sense s "
            "  JOIN dict d ON d.id=s.word_id "
            "  JOIN sense_src ss ON ss.sense_id=s.id "
            " WHERE ss.lang='pt'"):
        if not KIND.match(txt) or pos == "name":
            continue
        # 🔴 `abbrev` 不动 —— 它比 `name` 信息**更多**，改过去是降级。
        #    干跑时读出来的：`EI` / `EIIL` / `EIIS` 释义是 `Estado Islâmico`，
        #    被 `estado ` 这个类别词命中，但它们是**缩写**，不是地名。
        if pos not in ("n", "phr"):
            continue
        if not w[:1].isupper():
            rejected.append((w, txt))       # 反向查：判据命中但不是专名
            continue
        hit.append((w, sid, pos))
    return hit, rejected


def main(a):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    hit, rejected = plan(con)
    f = lambda n: format(n, ",")
    print("■ 源头点明是地名/人名、现在却不是 `name` 的义项：%s" % f(len(hit)))
    print("   原 pos 分布：%s" % collections.Counter(p for _w, _s, p in hit).most_common())
    print("■ 反向查（判据命中但词形小写 ⇒ 不动）：%s" % f(len(rejected)))
    for w, t in rejected[:4]:
        print("     %-18s %s" % (w[:18], t[:56]))

    sids = {s for _w, s, _p in hit}
    # entry.pos 重算（规则已实测：== 义项 pos 集合）
    senses = collections.defaultdict(set)
    for eid, sid, p in con.execute("SELECT entry_id, id, pos FROM sense "
                                   "WHERE entry_id IS NOT NULL AND pos IS NOT NULL"):
        senses[eid].add("name" if sid in sids else p)
    ent_new = {}
    for eid, old in con.execute("SELECT id, pos FROM entry"):
        if eid in senses:
            new = "/".join(sorted(senses[eid]))
            if new != old:
                ent_new[eid] = new
    # dict.pos 只在「全部义项都成了专名且原值恰好是 n」时改
    byword = collections.defaultdict(list)
    for wid, sid in con.execute("SELECT word_id, id FROM sense"):
        byword[wid].append(sid)
    dict_new = []
    for wid, ss in byword.items():
        if not any(s in sids for s in ss):
            continue
        if all(s in sids for s in ss):
            old = con.execute("SELECT pos FROM dict WHERE id=?", (wid,)).fetchone()[0]
            if old == "n":
                dict_new.append(wid)
    print("■ 连带改：entry.pos %s 条 ／ dict.pos %s 条（只改原值恰好是 `n` 的）"
          % (f(len(ent_new)), f(len(dict_new))))
    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0
    with dbtool.session("fix-pt-proper-noun-pos", expect={}) as s:
        s.executemany("UPDATE sense SET pos='name' WHERE id=?", [(i,) for i in sids])
        s.executemany("UPDATE entry SET pos=? WHERE id=?",
                      [(v, k) for k, v in ent_new.items()])
        s.executemany("UPDATE dict SET pos='name' WHERE id=?", [(i,) for i in dict_new])
    print("\n✓ sense %s ／ entry %s ／ dict %s" % (f(len(sids)), f(len(ent_new)), f(len(dict_new))))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    sys.exit(main(ap.parse_args()))
