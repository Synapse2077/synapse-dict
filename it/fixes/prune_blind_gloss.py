#!/usr/bin/env python3
"""盲推释义分族处置：藏掉尺子量过的那一族，留下尺子没量过、我逐条读过的两族。2026-08-20。

═══ 背景 ═══
`pipeline/fill_blind_gloss.py` 给「各版都没有释义」的 3,391 个词头按构词推了中文。
盲测（`probes/blind_gloss_pilot.py`）给出真错率 **24–25%**，换模型/开思考都不动；
我的建议是不填，**用户 2026-08-17 两次明确要求全部填上**。2026-08-20 用户说「动，看一下」。

═══ 🔴 关键发现：那 24–25% 只量了三族里的一族 ═══
盲测的正控写得很清楚 —— **「C2 生僻动词，库里有中文释义（与目标词同类：低频、构词复杂）」**。
而这 3,391 条按频次一分，是**三个性质完全不同的族**：

    A  有频次（zipf>0）      164 条  英语外来词 + 介词短语
                                    green / tag / editor / training / vip
                                    all'interno（在内部）/ all'alba（在黎明）
    C  freq_zipf 为 NULL     162 条  多词固定搭配 + 构词成分（A63：NULL＝量不了，不是生僻）
                                    a pancia in su（仰面朝天）/ sabato inglese（半天工作制）
                                    reggere il sacco（帮凶）/ -terapeuta / -coltura
    B  freq_zipf = 0.0     3,065 条  生僻单词（多为古体/方言动词）← **正控就是这一族**
                                    corvettare / scorredare / coinglutire

A 和 C **不是"按构词猜"** —— 意思就摆在词形里（英语原词、或短语各部分的组合）。
拿一把只在 B 上校准过的尺子去判 A 和 C 的死刑，就是 [[measure-landing-not-source]] 的变体：
**把某一族上量到的数字当成了全体的属性**。

⇒ 处置分族：
    · B（3,065）**藏掉** —— 尺子实测 24–25%，而全库其余部分是 1.2%；
      且这一族 `freq_zipf=0.0` 意为「量过了，跑动文本里一次都没出现」，几乎不会被查到。
      「错比缺更伤权威」。
    · A + C（326）**留下** —— 我逐条读完 326 条，下面记的是读出来的问题。

═══ 我读出来的问题，分两类记 ═══
① **源头证实的错**（4 条）—— 有外部背书，直接改：
     sbronzare   「使成青铜色，晒黑」  en 版 `sbronzarsi` = to get very drunk；`sbronza` = drunkenness
                                      ⇒ 模型把它当成了 `bronzare`（镀青铜）
     rivalere    「重新有价值」        en 版 `rivalersi` = to make up for / to take it out on
     citara      「西塔拉琴」          fr 版 `Cithare` = 古希腊基萨拉琴，不是印度西塔琴
     sull'avviso 「持此意见」          en 版 `avviso` 有 warning / opinion 两支，
                                      固定搭配 `stare sull'avviso` 取的是 warning 那支
                                      ⇒ 这正是 [[it-translation-quality-measured]] 记的
                                        「取了歧义源的错义支」那个形状

② **我判为错、但没有任何源可对**（3 条）—— 不改（改了就是拿我的猜替它的猜），**藏掉**：
     labe      「唇；边缘」   我读作"污点/瑕疵"（拉丁 labes），无背书
     -stato    「状态，国家」 我读作"使停止/调节者"（termostato 的那个 -stato），无背书
     -occhio   「眼，孔」     我读作指小/贬义后缀（ranocchio），无背书

⚠️ 说清楚这份读的边界：**它不是一把带真值的尺子**，是我逐条读的判断。
   A 族 164 条里我另标了约 8 条"不精确"（`cuocersi`「煮自己」、`sprecarsi`「浪费自己」
   这类直译、`all'aria`「在户外」其实是 `all'aria aperta` 的意思），
   C 族约 3 条（`gastro-filologo` 两个猜法并列、`neo-crepuscolarismo` 应作"新暮色派"）——
   **没改也没藏**，因为改它们同样是拿我的猜换它的猜。真错率的上界因此高于我改的这 7 条。

═══ 可逆 ═══
藏＝`sense.hidden=1`，`sense_gloss.src` 的 `deepseek-v4-flash:blind-morph:c<n>` 一个字节不动。
要全部放回来：`UPDATE sense SET hidden=0 WHERE id IN (SELECT sense_id FROM sense_gloss
WHERE src LIKE 'deepseek-v4-flash:blind-morph%')`。

用法（在 it/ 目录下）：
    python3 fixes/prune_blind_gloss.py            # 干跑
    python3 fixes/prune_blind_gloss.py --apply
    python3 fixes/prune_blind_gloss.py --verify
    python3 fixes/prune_blind_gloss.py --mutate
"""
import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402

f = lambda n: format(n, ",")

SRC = "deepseek-v4-flash:blind-morph%"

# ① 源头证实的错 —— 词形 → (新中文, 背书)
FIX = {
    "sbronzare":   ("灌醉；（sbronzarsi）喝醉", "en 版 sbronzarsi = to get very drunk / sbronza = drunkenness"),
    "rivalere":    ("（rivalersi）求偿，讨回；报复", "en 版 rivalersi = to make up for / to take it out on"),
    "citara":      ("基萨拉琴（古希腊弦乐器）", "fr 版 Cithare"),
    # 🔴 键必须用**库里的写法**：这一条是印刷撇号 `sull’avviso`（U+2019），
    #    第一版我按 ASCII 撇号写，干跑时静静地少改一条 —— 差额对不上才发现。
    #    与 `merge_apostrophe_variants` / `extend_entry_layer` 撞的是同一个坑。
    "sull’avviso": ("警惕，提防", "en 版 avviso 的 warning 支；固定搭配 stare sull’avviso"),
}

# ② 我判为错、无源可对 —— 不改，藏
HIDE_SUSPECT = {
    "labe":     "我读作「污点，瑕疵」（拉丁 labes），但无任何源可对 ⇒ 不拿我的猜换它的猜",
    "-stato":   "我读作「使停止/调节者」（termostato 那个 -stato），现中文「状态，国家」像是把它当成了意语单词 stato",
    "-occhio":  "我读作指小/贬义后缀（ranocchio），现中文「眼，孔」像是望文生义",
}


def families(con):
    """→ {族: [(sense_id, 词形, 中文)]}。判据是 `freq_zipf`，A63 的三分法。"""
    fam = {"A 有频次": [], "C 量不了（多词/词缀）": [], "B 生僻单词（zipf=0）": []}
    for sid, w, zh, z in con.execute(
            "SELECT s.id, d.word, g.text, d.freq_zipf FROM sense_gloss g "
            "JOIN sense s ON s.id = g.sense_id JOIN dict d ON d.id = s.word_id "
            "WHERE g.src LIKE ? ORDER BY d.word", (SRC,)):
        key = "C 量不了（多词/词缀）" if z is None else (
            "B 生僻单词（zipf=0）" if z == 0 else "A 有频次")
        fam[key].append((sid, w, zh))
    return fam


def plan(con):
    """→ (要改的 [(sid, 词形, 旧, 新)], 要藏的 [(sid, 词形, 理由)])"""
    fam = families(con)
    keep = {w: sid for _k in ("A 有频次", "C 量不了（多词/词缀）")
            for sid, w, _zh in fam[_k]}
    upd, hide = [], []
    for w, (new, _why) in FIX.items():
        sid = keep.get(w)
        if sid is None:
            continue
        old = con.execute("SELECT text FROM sense_gloss WHERE sense_id=? AND lang='zh' "
                          "AND kind='equivalent' AND seq=0", (sid,)).fetchone()
        if old and old[0] != new:
            upd.append((sid, w, old[0], new))
    for w, why in HIDE_SUSPECT.items():
        sid = keep.get(w)
        if sid is not None:
            hide.append((sid, w, why))
    for sid, w, _zh in fam["B 生僻单词（zipf=0）"]:
        hide.append((sid, w, "B 族：盲测正控就是这一族，实测真错率 24–25%"))
    return upd, hide, fam


def gate(con):
    ok = True

    def chk(name, got, want):
        nonlocal ok
        good = got == want
        ok &= good
        print("   %s %-44s %s（应 %s）" % ("✅" if good else "🔴", name, f(got), f(want)))

    fam = families(con)
    vis = lambda ids: con.execute(
        "SELECT count(*) FROM sense WHERE COALESCE(hidden,0)=0 AND id IN (%s)"
        % ",".join(str(i) for i, _w, _z in ids)).fetchone()[0] if ids else 0
    chk("A 族仍可见（尺子没量过这一族）", vis(fam["A 有频次"]), 164 - 1)          # labe 已藏
    chk("C 族仍可见（尺子没量过这一族）", vis(fam["C 量不了（多词/词缀）"]), 162 - 2)  # -stato/-occhio 已藏
    chk("🔴 B 族一条都不许可见（实测 24–25% 错）", vis(fam["B 生僻单词（zipf=0）"]), 0)
    # 四条源头证实的改写必须逐字还在
    bad = 0
    for w, (new, _why) in FIX.items():
        r = con.execute(
            "SELECT g.text FROM sense_gloss g JOIN sense s ON s.id=g.sense_id "
            "JOIN dict d ON d.id=s.word_id WHERE d.word=? AND g.src LIKE ? AND g.lang='zh'",
            (w, SRC)).fetchone()
        if not r or r[0] != new:
            bad += 1
    chk("🔴 源头证实的 4 条改写逐字还在", bad, 0)
    # 可逆：`src` 标记一个字节都不许动，否则整批撤不回来
    chk("🔴 盲推标记完好（撤回的唯一抓手）",
        con.execute("SELECT count(*) FROM sense_gloss WHERE src LIKE ?", (SRC,)).fetchone()[0],
        3391)
    return ok


def mutate():
    cases = [
        ("放出一条 B 族（生僻单词）",
         "UPDATE sense SET hidden=0 WHERE id=(SELECT s.id FROM sense s "
         "JOIN sense_gloss g ON g.sense_id=s.id JOIN dict d ON d.id=s.word_id "
         "WHERE g.src LIKE '%blind-morph%' AND d.freq_zipf=0 AND s.hidden=1 LIMIT 1)"),
        ("顺手把一条 A 族也藏了",
         "UPDATE sense SET hidden=1 WHERE id=(SELECT s.id FROM sense s "
         "JOIN sense_gloss g ON g.sense_id=s.id JOIN dict d ON d.id=s.word_id "
         "WHERE g.src LIKE '%blind-morph%' AND d.freq_zipf>0 "
         "AND COALESCE(s.hidden,0)=0 LIMIT 1)"),
        # ⚠️ 必须**点名盲推那一条义项**：`citara` 有两条义项（另一条早已藏起来、
        #    一条 gloss 行都没有）。第一版子查询没带 `src` 条件，取到的是那条空的，
        #    UPDATE 一行都没改到 ⇒ 闸当然不红。**是变异挑错了行，不是闸假**（A33）。
        ("把一条源头证实的改写改回原样",
         "UPDATE sense_gloss SET text='西塔拉琴' WHERE lang='zh' AND src LIKE '%blind-morph%' "
         "AND sense_id IN (SELECT s.id FROM sense s JOIN dict d ON d.id=s.word_id "
         "WHERE d.word='citara')"),
        ("抹掉盲推标记（撤回的抓手没了）",
         "UPDATE sense_gloss SET src='x' WHERE src LIKE '%blind-morph%' "
         "AND sense_id=(SELECT min(sense_id) FROM sense_gloss WHERE src LIKE '%blind-morph%')"),
    ]
    passed = 0
    for name, sql in cases:
        d = Path(tempfile.mkdtemp())
        shutil.copy(paths.DB, d / "m.sqlite")
        con = sqlite3.connect(d / "m.sqlite")
        con.execute(sql)
        con.commit()
        print("\n── 变异：%s" % name)
        red = not gate(con)
        con.close()
        shutil.rmtree(d)
        print("   %s" % ("✅ 闸报红" if red else "🔴 闸没报 —— 这道检查是假的"))
        passed += red
    print("\n■ 变异 %s/%s" % (passed, len(cases)))
    return 0 if passed == len(cases) else 1


def main():
    ap = argparse.ArgumentParser()
    for x in ("apply", "verify", "mutate"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args()
    if a.mutate:
        return mutate()
    ro = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.verify:
        return 0 if gate(ro) else 1
    upd, hide, fam = plan(ro)
    print("■ 盲推释义 %s 条，按 A63 的频次三分法分族：" % f(sum(len(v) for v in fam.values())))
    for k in ("A 有频次", "C 量不了（多词/词缀）", "B 生僻单词（zipf=0）"):
        print("   %-22s %s" % (k, f(len(fam[k]))))
    print("\n■ 改 %s 条（源头证实）" % f(len(upd)))
    for _sid, w, old, new in upd:
        print("   %-14s「%s」→「%s」" % (w, old, new))
        print("        背书 %s" % FIX[w][1])
    print("\n■ 藏 %s 条 = B 族 %s + 我判为错但无源可对 %s"
          % (f(len(hide)), f(len(fam["B 生僻单词（zipf=0）"])), f(len(HIDE_SUSPECT))))
    for _sid, w, why in hide[:3]:
        print("   %-14s %s" % (w, why[:66]))
    if not a.apply:
        ro.close()
        print("\n(未加 --apply，不写库)")
        return 0
    ro.close()
    with dbtool.session("prune-blind-gloss", expect={"__rows__": 0}) as s:
        for sid, _w, _old, new in upd:
            s.execute("UPDATE sense_gloss SET text=? WHERE sense_id=? AND lang='zh' "
                      "AND kind='equivalent' AND seq=0", (new, sid))
        s.executemany("UPDATE sense SET hidden=1 WHERE id=?", [(sid,) for sid, _w, _r in hide])
    print("■ 已改 %s 条、藏 %s 条" % (f(len(upd)), f(len(hide))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
