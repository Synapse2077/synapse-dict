#!/usr/bin/env python3
"""「中文」整条是拉丁字母的 67 条：补真中文。2026-08-15。

═══ 怎么发现的 ═══
用户从 `tempo` 的界面挑出「（所有义项）」这类元话语后，我扫全库找同类老账。
扫出 34,547 条候选，细化两轮后**真缺陷只剩 68 条**（假阳性率 99.8%）：

    ① 括号里写「（所有义项）」  7 条  ← 已由 strip-meta-allsenses 修掉
    ⑤ 整条是拉丁字母          67 条  ← 本脚本

⚠️ 被我先后排除的两大族，**都不是缺陷**，记在这里免得下次再扫一遍：
    · 35,279 条 变位合体词的语法构成说明（`spiegandoti`「正给你解释（spiegare动名词+代词ti）」）
    · 7,761 条 `src='template'` 的指针文案（`fremere 的异体形式`）—— 必须含意语原词

═══ 67 条分四类，只有第一类是错的 ═══
    🔴 译成了别的语言 ~11：`pezza onorevole`→`honorable pieces`（英）、
       `rotico`→`rhotique`（法）、`shazammare`→`Shazamer`（法）
    · 技术缩写/品牌 ~23：`USB` `MP3` `ChatGPT` —— 中文里本来就这么用，
      但该补括号说明（`USB（通用串行总线）`）
    · 摩洛哥地名 15：法语版收的，缺音译
    · 音乐流派 12：`sophisti-pop` `G-funk` —— 多数没有通行中译

═══ prompt 按含义写，不用形式代理（A45）═══
`criteria-from-meaning-not-form`：不写「简短」「不要长句」，写**要传达什么**。

用法（在 it/ 目录下）：
    python3 fixes/fix_untranslated_zh.py --plan
    python3 fixes/fix_untranslated_zh.py --run
    python3 fixes/fix_untranslated_zh.py --apply
    python3 fixes/fix_untranslated_zh.py --verify
"""
import argparse
import asyncio
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool     # noqa: E402
import ds_batch   # noqa: E402
import paths      # noqa: E402
from align_it_defs import batched   # noqa: E402

OUT = paths.WORK / "it_untranslated.jsonl"
NEW_SRC = "deepseek-v4-flash:fix-untranslated"
LATIN_ONLY = re.compile(r"^[A-Za-z0-9 .\-’']+$")

SYS = """你是意大利语—中文词典编纂员。每条给你一个意大利语词条 `w`、它的词性 `pos`、
现有的英文释义 `en`（可能为空）和现在库里那条**没译成中文**的内容 `cur`。

给出这条词条的**中文释义** `zh` —— 读者拿它去理解这个词时，应当知道它指什么。

分情况：
🔴 `cur` 是英文或法语（不是中文）⇒ 它是**错的**，请给出真正的中文。
   例：`pezza onorevole` 现在是 `honorable pieces`（英文），中文该是「荣誉纹饰（纹章学）」。
· 国际通用的缩写或品牌（`USB` `MP3` `ChatGPT`）⇒ 保留原写法，**并在括号里给中文说明**，
  例：`USB（通用串行总线）`、`MP3（音频压缩格式）`。
· 地名 ⇒ 中文音译，并在括号里写清它在哪个国家/地区，例：`姆祖拉（摩洛哥城镇）`。
· 音乐流派、亚文化名词等确实没有通行中译的 ⇒ 保留原名，括号里说明它是什么，
  例：`G-funk（美国西海岸嘻哈曲风）`。
· 你确实不知道这个词指什么 ⇒ `zh` 给空字符串 ""，**不要猜**。

括号外放这个词本身的中文说法或原名；括号里放让读者认出它所需的限定信息，不限长度。
句末不加任何标点。

输入是一个 JSON 对象，键是编号。输出**只有**一个 JSON 对象，键与输入相同，
值形如 {"zh": "姆祖拉（摩洛哥城镇）"}。不要围栏、不要解释、不要输出数组。"""


def load(con):
    rows = []
    for sid, w, pos, t, src in con.execute(
            "SELECT g.sense_id, d.word, COALESCE(s.pos,e.pos), g.text, g.src FROM sense_gloss g "
            "JOIN sense s ON s.id=g.sense_id JOIN dict d ON d.id=s.word_id "
            "LEFT JOIN entry e ON e.id=s.entry_id "
            "WHERE g.lang='zh' AND g.seq=0 AND COALESCE(s.hidden,0)=0"):
        if not LATIN_ONLY.fullmatch(t):
            continue
        en = con.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang='en' "
                         "AND seq=0", (sid,)).fetchone()
        rows.append(dict(sid=sid, w=w, pos=pos or "?", cur=t,
                         en=(en[0] if en else ""), src=src))
    return rows


def gate(con):
    print("\n═══ 闸 ═══")
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    # 🔴 已接受基线 + 理由（否则闸永远红、没人看）：
    #    `pbsl` —— 源头没给英文释义、也查不到是什么缩写，模型按规则七拒绝猜。
    #    宁可留原样也不编，`FRAMEWORK`「错比缺更伤权威」。
    ACCEPTED = {"pbsl"}
    left = [r for r in load(con)
            if not (r["src"] or "").startswith(NEW_SRC) and r["w"] not in ACCEPTED]
    checks = [
        ("🔴 不再有「整条是拉丁字母」的中文（本脚本改过的除外）", len(left), 0),
        ("🔴 改过的行必须含中文字符",
         sum(1 for (t,) in con.execute("SELECT text FROM sense_gloss WHERE src=?", (NEW_SRC,))
             if not re.search(r"[一-鿿]", t)), 0),
        ("只改中文行", q("SELECT count(*) FROM sense_gloss WHERE src=? AND lang<>'zh'",
                       NEW_SRC), 0),
        ("句末无标点", q("SELECT count(*) FROM sense_gloss WHERE src=? AND "
                     "(text LIKE '%。' OR text LIKE '%.')", NEW_SRC), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-48s %s (期望 %s)" % ("✅" if good else "🔴", name, got, want))
    return ok


def main():
    ap = argparse.ArgumentParser()
    for f in ("plan", "run", "apply", "verify"):
        ap.add_argument("--" + f, action="store_true")
    a = ap.parse_args()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    rows = [r for r in load(ro) if r["src"] != NEW_SRC]

    if a.plan:
        print("■ 待修 %d 条" % len(rows))
        for r in rows[:12]:
            print("   %-24s cur=%-22s en=%s" % (r["w"][:24], r["cur"][:22], r["en"][:26]))
        return 0

    if a.run:
        items = [({k: r[k] for k in ("w", "pos", "en", "cur")}, r["sid"]) for r in rows]
        ro.close()
        OUT.unlink(missing_ok=True)
        asyncio.run(ds_batch.run(SYS, *batched(items, 10), OUT, mode="flash", conc=4, every=2))
        return 0

    got = {}
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            r = json.loads(line)
            if (r.get("zh") or "").strip():
                got[r["id"]] = r["zh"].strip()
    if a.apply:
        upd = [(got[r["sid"]], NEW_SRC, r["sid"]) for r in rows if r["sid"] in got]
        print("■ 将改 %d 条（模型未给中文的 %d 条留原样）" % (len(upd), len(rows) - len(upd)))
        for zh, _s, sid in upd[:10]:
            w = next(r["w"] for r in rows if r["sid"] == sid)
            cur = next(r["cur"] for r in rows if r["sid"] == sid)
            print("   %-22s %-20s → %s" % (w[:22], cur[:20], zh[:32]))
        ro.close()
        if not upd:
            return 0
        with dbtool.session("fix-untranslated-zh", expect={"#sense_gloss": 0}) as s:
            s.executemany("UPDATE sense_gloss SET text=?, src=? WHERE sense_id=? "
                          "AND lang='zh' AND seq=0", upd)
        print("■ 已写入")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
