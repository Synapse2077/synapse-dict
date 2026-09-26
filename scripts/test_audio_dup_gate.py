#!/usr/bin/env python3
"""跨语种闸：**同一条录音不许存成两行**。2026-09-26。

═══ 为什么必须是跨语种的闸 ═══
2026-09-25 在 ko 上修掉 456 组「转码名 vs 原始名」，当时以为是 ko 一门的事。
2026-09-26 按 Commons 自己的标题规则（`scripts/commons_filename.py`）一量，
**八门全有**：

    en 8 ／ es 33 ／ it 205 ／ fr 3,780 ／ pt 359 ／ de 598 ／ ja 2 ／ ko 39

`[[decision-not-propagated-across-editions]]`：一门做对了其余照旧错着，
而每门自己的闸全绿 —— 这类缺陷只能由跨语种的闸逮。

🔴🔴 **它和「按钮标签重复」是两个不同的缺陷，互相看不见**：
   ko 那 39 组重复行**在页面上看不出来**（一行解析出了录音人、一行没有，
   两个按钮的标签正好不一样）；而 K23 标签重复的是**另外 39 个词**，
   两批完全不相交。⇒ 两道闸都要有，少一道就有一类缺陷没人看：
       这一道（数据）：同一个文件不许两行
       `apps/web/src/contract-check-audio.tsx`（展示）：按钮标签两两不同

═══ 欠账锚在常量上，只许降不许升 ═══
另七门的数据现在**不动**（只动当前语种，`[[es-only-scope]]`），记在 `docs/BACKLOG.md` B12。
所以这道闸不是「必须为 0」，而是：
    · 当前语种（ko）必须为 0
    · 其余每门不许**超过**下面登记的数
    · 谁降下去了也会报 —— 提醒把常量改小，别让欠账数字虚高（假装还欠着）
`[[expectation-must-be-declared]]`：期望值要独立声明；锚在常量上，别从现状推。

用法：
    python3 scripts/test_audio_dup_gate.py          # 红了退出码非 0
    python3 scripts/test_audio_dup_gate.py --list fr  # 打这门的重复清单
"""
import argparse
import collections
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from commons_filename import TRANSCODE, commons_key  # noqa: E402

DB = ROOT / "data" / "db"

# 🔴 已登记的欠账（2026-09-26 实测）。**当前语种必须是 0。**
#    值是「同一个文件多存的行数」，不是组数。
DEBT = {
    "en": 8,      # `LL-…-&#39;ll.wav` vs `…-'ll.wav` —— HTML 实体没解码
    "es": 33,     # `Es-us-Alejandro.ogg` vs `es-us-Alejandro.ogg` —— 首字母大小写
    "it": 205,    # `It-Lombardia.ogg` vs `it-Lombardia.ogg`
    "fr": 3780,   # 八门里最多，fr 录音层本身也是最大的（39.2 万行）
    "pt": 359,    # `Pt-pt Abrantes FF` vs `Pt-pt_Abrantes_FF` —— 下划线 ≡ 空格
    "de": 598,
    "ja": 2,      # `Ja-nihon(日本).ogg` vs `ja-nihon(日本).ogg`
    "ko": 0,      # ✅ 2026-09-26 结清（456 组 + 39 组两轮）
}
CURRENT = "ko"   # 当前语种：它必须是 0

# 🟡 这笔欠账里「不能无脑并」的部分（2026-09-26 实测）：文件是同一个，
#    而不同维基版给的 ipa/region 不一样 ⇒ 并之前要先裁决留哪个值。
#    登记它是为了**不许再涨**；涨了说明又有新的写入方在制造分歧。
SOFT = {"en": 0, "es": 9, "it": 46, "fr": 16, "pt": 3, "de": 0, "ja": 0, "ko": 0}


def scan(lang):
    """→ (多存的行数, 组数, 样本, 组内自检失败的组数)"""
    db = DB / ("synapse-dict-%s.sqlite" % lang)
    if not db.exists():
        return None
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    try:
        rows = con.execute("SELECT word, file, speaker, region, kind, ipa"
                           " FROM audio").fetchall()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    g = collections.defaultdict(list)
    for r in rows:
        g[(r[0], commons_key(r[1]))].append(r)
    dup = {k: v for k, v in g.items() if len(v) > 1}
    extra = sum(len(v) - 1 for v in dup.values())

    # ═══ 组内自检要分成两类 —— 第一版把它们混成一类，结果对 es/it/fr/pt 喊了狼 ═══
    # 🔴 `kind` 冲突 ＝ **判据错了**：判据说这是同一个文件，而一行标 human 一行标别的，
    #    那它们不可能是同一条录音 ⇒ 判据宽了，必须停下来。
    # 🟡 `ipa`/`region`/`speaker` 冲突 ＝ **文件是同一个，标注不一致**：
    #    实测全是不同维基版对同一条录音的转写差异 ——
    #        It-padre.ogg  (fr 版) ipa=ˈpa.dre   ／ it-padre.ogg (it 版) ipa=ˈpadre
    #        Pt doente     (fr 版) region=pt-BR  ／ Pt_doente    (en 版) region=pt-PT
    #    判据没错，但**并之前要先裁决留哪个值**（ko 那个脚本遇到冲突会拒绝合并）。
    #    ⇒ 这不是红，是这笔欠账里「不能无脑并」的那一部分，要如实报出规模。
    hard = soft = 0
    for v in dup.values():
        if len({x[4] for x in v if x[4] is not None}) > 1:
            hard += 1
        elif any(len({x[i] for x in v if x[i] is not None}) > 1 for i in (2, 3, 5)):
            soft += 1
    return extra, len(dup), list(dup.items())[:4], hard, soft


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", metavar="LANG", help="打这门的重复清单")
    a = ap.parse_args()

    print("■ 跨语种闸：同一条录音不许存成两行（判据＝ Commons 标题等价规则）\n")
    print("  语种   多存行数   登记欠账   组数   🔴kind冲突  🟡标注不一致   判决")
    print("  " + "─" * 74)
    red = []
    for lang in DEBT:
        got = scan(lang)
        if got is None:
            print("  %-5s （无库或无 audio 表）" % lang)
            continue
        extra, ngrp, sample, hard, soft = got
        want = DEBT[lang]
        if lang == CURRENT and extra != 0:
            v, note = "🔴", "当前语种必须为 0"
        elif extra > want:
            v, note = "🔴", "超过登记欠账 +%d" % (extra - want)
        elif extra < want:
            # 🔴🔴 **降下来也是红。** 第一版这里是 🟡 且不进 `red` ⇒ 退出码 0，
            #    而「数字变小」有两个完全不同的原因：
            #      ① 真有人修了这门  ② **判据自己坏了/变窄了**（改个正则就会）
            #    ②才是要命的那个，它会让这道闸从此永远绿。两种都必须有人来看。
            #    `[[fix-regression-and-gate]]`：修复消失的四种机制之一就是「闸悄悄失效」。
            v, note = "🔴", "降到 %d（登记 %d）—— 是真修了就把常量改小，不是就查判据" % (extra, want)
        else:
            v, note = "✅", "与登记一致"
        if hard:
            v, note = "🔴", note + "；%d 组 kind 冲突（判据宽了）" % hard
        if soft > SOFT.get(lang, 0):
            v, note = "🔴", note + "；标注不一致涨到 %d（登记 %d）" % (soft, SOFT.get(lang, 0))
        if v == "🔴":
            red.append(lang)
        print("  %-5s %9d %10d %6d %11d %13d   %s %s"
              % (lang, extra, want, ngrp, hard, soft, v, note))
        if a.list == lang:
            print("       清单（前 40 组）：")
            con = sqlite3.connect(
                "file:%s?mode=ro" % (DB / ("synapse-dict-%s.sqlite" % lang)), uri=True)
            rows = con.execute("SELECT word, file FROM audio").fetchall()
            con.close()
            g = collections.defaultdict(list)
            for w, fn in rows:
                g[(w, commons_key(fn))].append(fn)
            for k, v2 in [x for x in g.items() if len(x[1]) > 1][:40]:
                print("         %-20s %s" % (k[0], " ｜ ".join(v2)))

    print("\n■ 这道闸逮不到什么（写在脸上）")
    print("   · 它只问「是不是同一个文件存了两次」，**问不了「这条录音对不对」**")
    print("     —— 张冠李戴的录音（ko 那 58 行 `Y.mp3`）它全绿，那是 R14 的活儿")
    print("   · 它也问不了「按钮标签分不分得开」——"
          " 见 `apps/web/src/contract-check-audio.tsx`")
    if red:
        raise SystemExit("\n🔴 %s：录音重复超出登记 —— 先弄清楚再动数据"
                         % "、".join(red))
    print("\n■ 跨语种录音重复闸全绿 ✓（ko 为 0，其余与 `BACKLOG` B12 登记一致）")


if __name__ == "__main__":
    main()
