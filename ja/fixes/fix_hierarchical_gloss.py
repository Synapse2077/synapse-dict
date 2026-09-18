#!/usr/bin/env python3
"""修：多层 gloss 只收了第 0 层，具体释义整条丢了。2026-09-17。

═══ 怎么发现的 ═══
用户 2026-09-17：「义项跨版重复那个，猫的三个 a cat 处理一下」。
`猫` 那三块回源一查**不是重复**（汉字／ねこ／ねこま 三个词条，见欠账 14）；
但顺着「同 entry 内中英文双同」那一桶往下挖，挖到了这个：

    kaikki 的 `glosses` 是**层级数组**，第 0 层是伞形标题、最后一层才是这条义项说的话。
    `build_entry_layer.py` 写的是 `gs[0]` ⇒ **伞形留下、具体释义整条丢掉。**

    ある   19 条义项里 12 条共用伞形「to exist, to be, to have」⇒ 落库后同一句印 7 遍
    長谷川  40 条不同河流共用伞形「Nagatani River (…)」⇒ 40 条河全丢，40 行都写「长谷川」
    西     伞形是「in kabuki:」—— 单独看是个**冒号结尾的半句话**

⭐ 这一条解释了「同 entry 内重复」那 2,819 条里的 **1,247 条（44.2%）**；
   剩下 1,572 条是源头自己就有两条同文义项（`卓` 的两个「a male given name」），不是我的 bug。

⚠️ **而且花过钱**：受影响的 1,866 条里 **1,746 条已经翻成中文**，
   翻的是伞形，产出是「你」×2、「有」×7。这一轮要重译。

═══ 判据与结构 ═══
判据 import `pipeline/gloss_levels.split_levels`（**与生成侧同一份**）。
落库形状：
    sense_src.text                      ← 具体释义（证据层跟着源头最细那一层走）
    sense_gloss(en, 'definition')       ← 具体释义
    sense_gloss(en, 'umbrella')         ← 伞形（**只有多层时才有这一行**）
    sense_gloss(zh, 'umbrella')         ← 伞形的中文（本脚本 --load 时写入）

🔴 **`src_ref` 不许反解析。** 它里面的 `seq` 是运行计数器，依赖遍历顺序；
   而词形本身可能带冒号。我先写过一版 `ref.split(':')`，1,866 条只对上 1,091 条，
   **对不上的 775 条不报错、只静默漏修**。现在走 `build_entry_layer.iter_kk()`
   —— 生成侧那一个循环。

跑：
    python3 -u ja/fixes/fix_hierarchical_gloss.py                 # dry-run
    python3 -u ja/fixes/fix_hierarchical_gloss.py --apply         # 改英文侧 + 导出待翻池
    python3 -u ja/fixes/fix_hierarchical_gloss.py --load          # 把中文写回
"""
import sys as _sys
import pathlib as _pl
_ROOT = _pl.Path(__file__).resolve().parent.parent
_sys.path.insert(0, str(_ROOT))
_sys.path.insert(0, str(_ROOT / "pipeline"))

import argparse
import collections
import json
import sqlite3

import dbtool
import paths
from build_entry_layer import iter_kk
from gloss_levels import split_levels

f = lambda n: format(n, ",")
POOL = paths.WORK / "hier_gloss_pool.jsonl"
ANS = paths.WORK / "hier_gloss_zh.jsonl"


def source_map():
    """→ {src_ref#i: (伞形, 具体)}，只含多层的那些。"""
    out = {}
    for o, _w, _p, _e, _s, ref in iter_kk():
        for i, se in enumerate(o.get("senses") or []):
            umb, spec = split_levels(se.get("glosses"))
            if umb and spec:
                out["%s#%d" % (ref, i)] = (umb, spec)
    return out


def plan(con):
    deep = source_map()
    jobs = []                       # (sense_id, src_id, 伞形, 具体, 现在的 en)
    for src_id, sid, ref, txt in con.execute(
            "SELECT id, sense_id, src_ref, text FROM sense_src"
            " WHERE src='en-edition' AND lang='en'"):
        hit = deep.get(ref)
        if not hit or sid is None:
            continue
        umb, spec = hit
        jobs.append((sid, src_id, umb, spec, txt))
    return deep, jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--load", action="store_true")
    ap.add_argument("--pool", action="store_true", help="只重导待翻池，不写库")
    a = ap.parse_args()

    if a.load:
        return load()
    if a.pool:
        return write_pool()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    deep, jobs = plan(con)
    umbrellas = sorted({u for _s, _i, u, _sp, _t in jobs})
    zh_now = {sid: r for sid, r in con.execute(
        "SELECT sense_id, text FROM sense_gloss WHERE lang='zh'")}
    hit_zh = sum(1 for s, _i, _u, _sp, _t in jobs if s in zh_now)

    print("■ 源头多层义项 %s 条｜落到库里 %s 条｜不同的伞形 %s 个"
          % (f(len(deep)), f(len(jobs)), f(len(umbrellas))))
    print("   其中已有中文 %s 条（翻的是伞形，要重译）" % f(hit_zh))
    print("\n   改写样例：")
    for sid, _i, u, sp, t in jobs[:6]:
        print("      现在 en = %r" % t[:52])
        print("      改成 en = %r" % sp[:52])
        print("      伞形    = %r   现在的中文=%r" % (u[:44], zh_now.get(sid)))
    con.close()

    if not a.apply:
        print("\n（dry-run，加 --apply 改英文侧并导出待翻池）")
        return

    # ── ① 英文侧：证据层与出版层一起改，并补伞形行 ──
    upd_src = [(sp, i) for _s, i, _u, sp, _t in jobs]
    upd_en = [(sp, s) for s, _i, _u, sp, _t in jobs]
    ins_umb = [(s, "en", "umbrella", 0, u, "en-edition")
               for s, _i, u, _sp, _t in jobs]
    with dbtool.session("ja-hier-gloss-en", expect={
            "__rows__": 0,
            "#sense_gloss": len(ins_umb),
            "#sense_src": 0, "#sense": 0, "#dict": 0, "#entry": 0,
            "#sense_relation": 0, "#example": 0, "#example_gloss": 0,
            "#inflection": 0, "#pronunciation": 0, "#audio": 0}) as con:
        con.executemany("UPDATE sense_src SET text=? WHERE id=?", upd_src)
        con.executemany(
            "UPDATE sense_gloss SET text=? WHERE sense_id=? AND lang='en'"
            " AND kind='definition'", upd_en)
        con.executemany(
            "INSERT OR REPLACE INTO sense_gloss(sense_id,lang,kind,seq,text,src)"
            " VALUES(?,?,?,?,?,?)", ins_umb)

    write_pool()


def write_pool():
    """导出待翻池：具体释义（按 sense_id）＋ 伞形（按文本去重）。

    🔴 键一律用**数据库主键**，不用「第几条」（`[[model-answer-files-key-by-id]]`）。
    🔴 **伞形必须随具体释义一起给模型当上下文** —— `the left side of the stage
       in the Edo-style` 单看不知道在讲什么，加上 `in kabuki:` 才译得对。
       ⚠️ 但要明说「只译 `en`，`umbrella` 只作参考」：
       `[[context-you-give-leaks-into-output]]`，给的参考会直接漏进输出。
    """
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    _deep, jobs = plan(con)
    umbrellas = sorted({u for _s, _i, u, _sp, _t in jobs})
    ukey = {u: "u%d" % k for k, u in enumerate(umbrellas)}
    meta = {sid: (w, kana, pos) for sid, w, kana, pos in con.execute(
        "SELECT s.id, d.word, e.kana, s.pos FROM sense s"
        " JOIN dict d ON d.id = s.word_id LEFT JOIN entry e ON e.id = s.entry_id")}
    con.close()
    paths.WORK.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(POOL, "w", encoding="utf-8") as fh:
        for sid, _i, u, sp, _t in jobs:
            w, kana, pos = meta.get(sid, ("?", None, None))
            p = {"key": "s%d" % sid, "word": w, "pos": pos or "?",
                 "umbrella": u, "en": sp}
            if kana:
                p["kana"] = kana
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")
            n += 1
        for u, k in sorted(ukey.items(), key=lambda kv: kv[1]):
            fh.write(json.dumps({"key": k, "word": "", "pos": "?", "en": u},
                                ensure_ascii=False) + "\n")
    print("\n   待翻池 → %s（%s 条具体 ＋ %s 条伞形）"
          % (POOL, f(n), f(len(umbrellas))))
    print("   下一步：python3 -u ja/pipeline/translate_hier_gloss.py --slice 5")


def load():
    """把翻译结果写回 —— 具体释义覆盖原中文，伞形新建 `kind='umbrella'` 行。"""
    if not ANS.exists():
        _sys.exit("🔴 没有 %s，先跑翻译" % ANS)
    zh = {}
    for line in open(ANS, encoding="utf-8"):
        o = json.loads(line)
        # ⚠️ `ds_batch` 落盘的键叫 `id`（我们在 meta 里传的就是池子的 `key`）。
        if o.get("zh"):
            zh[o["id"]] = o["zh"]
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    _deep, jobs = plan(con)
    umbrellas = sorted({u for _s, _i, u, _sp, _t in jobs})
    ukey = {u: "u%d" % k for k, u in enumerate(umbrellas)}
    have = {sid for (sid,) in con.execute(
        "SELECT sense_id FROM sense_gloss WHERE lang='zh' AND kind<>'umbrella'")}
    con.close()

    upd, ins, ins_u = [], [], []
    miss = collections.Counter()
    for sid, _i, u, _sp, _t in jobs:
        s = zh.get("s%d" % sid)
        if not s:
            miss["具体释义没有译文"] += 1
        elif sid in have:
            upd.append((s, sid))
        else:
            ins.append((sid, "zh", "equivalent", 0, s, "model:deepseek-v4-flash"))
        t = zh.get(ukey[u])
        if not t:
            miss["伞形没有译文"] += 1
        else:
            ins_u.append((sid, "zh", "umbrella", 0, t, "model:deepseek-v4-flash"))
    print("■ 回填：更新中文 %s 条｜新建中文 %s 条｜伞形中文 %s 条"
          % (f(len(upd)), f(len(ins)), f(len(ins_u))))
    for k, v in miss.items():
        print("   ⚠️ %s：%s" % (k, f(v)))
    with dbtool.session("ja-hier-gloss-zh", expect={
            "__rows__": 0,
            "#sense_gloss": len(ins) + len(ins_u),
            "#sense_src": 0, "#sense": 0, "#dict": 0, "#entry": 0,
            "#sense_relation": 0, "#example": 0, "#example_gloss": 0,
            "#inflection": 0, "#pronunciation": 0, "#audio": 0}) as con:
        con.executemany(
            "UPDATE sense_gloss SET text=?, src='model:deepseek-v4-flash'"
            " WHERE sense_id=? AND lang='zh' AND kind<>'umbrella'", upd)
        con.executemany(
            "INSERT OR REPLACE INTO sense_gloss(sense_id,lang,kind,seq,text,src)"
            " VALUES(?,?,?,?,?,?)", ins + ins_u)
    print("   ✅ 完成")


if __name__ == "__main__":
    main()
