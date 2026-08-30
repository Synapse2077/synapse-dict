#!/usr/bin/env python3
"""外审第二轮·族E：变位时态标签重算 + 外来语变位表清理。2026-08-30。

═══ 族E 是怎么被逮到的 ═══
外审两家四版都点了同一批词：`depenicará`「陈述式现在时/将来时」、
`desenluvássemos`「虚拟式简单过去时/未完成过去时」、
`sanguificarias`/`vociferaríeis` 标成「陈述式将来时」而它们是**条件式**。
我原以为是几条零散的标签啰嗦，回源用规则动词 falar/comer/partir 把
**全部 29 个时态签名**逐个对上之后才看清是一个系统性缺陷：

🔴 **葡语时态名本身是复合的，源头用多个 tag 编码同一个时态，我当成了「几选一」。**

      comerei   future+present            = futuro do presente   → 将来时
      comeria   future+past               = futuro do pretérito  → **条件式**
      comi      past（裸）                 = pretérito perfeito    → 简单过去时
      comia     past+continuative         = pretérito imperfeito  → 未完成过去时
      partira   pluperfect(+perfect)      = mais-que-perfeito     → 过去完成时

   `"/".join(tense)` 的后果分三档，从轻到重：
     ② 多出一个不存在的时态  「现在时/将来时」          46,779 条
     ③ 时态整个丢掉         `continuative` 不在 COMPOSE_TAGS ⇒ 被静默丢弃，
                          `past` 不在 TENSE ⇒ comia/comi/comesse 只剩「陈述式第一人称单数」
     ① **说成另一个时态**    comeria 标「陈述式将来时」，和 comerei **撞成同一个标签**  38,989 条

   ①才是真伤：读者查 `comeria` 得到的语法说明是**错的**，不是**糊的**。

⚠️ **「/」不是一律错的** —— `comemos` 确实同时是现在时和简单过去时（-er/-ir 第一人称复数
   真同形，785 条）。所以判据不能写成「多个时态 tag 就合并」这种形式代理
   （`[[criteria-from-meaning-not-form]]`），只能**逐签名裁**，表写在 infl_compose 一处。

═══ 族F：小语种版塞进变位层的垃圾 ═══
查族E 时顺手发现的，外审两家四版都没看见：

    criar → criaba / crío / ha criado      ← **西班牙语**（葡语该是 criava/crio/tem criado）
    dentista → von einem Zahnarzt zu träumen  ← **德语散文句**
    nada → inv                             ← 意语模板的「不变化」标记，不是词
    batalhão → batalhãoes                  ← 编造（正确是 batalhões）

回源确认 `criar` 是**源头错**：eswiktionary 在 `lang_code=pt` 段下挂了西语变位模板。
我的 `lang_code=='pt'` 过滤是对的，挡不住这个。

🔴 **第一版判据被数据打回**：我写的是「两个权威版都给了 ≥6 个形式、第三方版还多出来的」，
   一跑 3,213 行。逐条看就露馅 —— `aprazer→aprazera/aprazeram/aprazesse` 是**正确的葡语形式**，
   只是 `aprazer` 是缺陷动词、权威版收得不全。**「权威版给了 6 个形式」不等于「给了全套」**
   （一套变位 60+ 格）⇒ 又一个形式代理（`[[criteria-from-meaning-not-form]]`）。

🔴 **第二版判据也被打回**：改成「同一格（同一 tag 组合）填了不同词形」，678 对全部 100% 冲突。
   逐条看，这条判据逮到的是**冲突不是错误**，四种情况混在一起：

     apanhar → aparelha    fr 版把**另一个动词**的表挂上来了      → 真错
     convencer → convencce fr 模板造的假词形（重复 c）           → 真错
     boiar → bóia / boia   **两个都对** —— 1990 正字法协议前后     → 不是错
     togar → togue / toge  **权威版错**，fr 版对（-gar → -gue）   → 反着错

   ⇒ 这一族归 `[[conflict-deferred-final-pass]]`，**记账不动**（C25，674 对 / 2,278 行）。

⇒ 本步只删**能逐条证明**的。四个小版本（es/de/it/zh）对变位层的总贡献只有 789 行
   （占 0.09%），**量小到可以整个读完** —— 读完了就不该再用代理判据，直接点名。
   99 行，名单写在 FOREIGN 里，每条带理由。

═══ 记账（不在本步动）═══
  C25  678 对(词元,版本)同格冲突 2,278 行 —— 混着"真错/正字法差异/权威版才错"，要逐条裁
  C26  de/zh 版把**指小指大词**当屈折收（`mão→mãozinha`/`manopla`），16 行 ——
       `diminutive`/`augmentative` 该不该算屈折是判据问题，不是数据问题

用法（在 pt/ 目录下）：
    python3 fixes/fix_inflection_tense.py
    python3 fixes/fix_inflection_tense.py --apply
"""
import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import dbtool   # noqa: E402
import paths    # noqa: E402
from infl_compose import compose, resolve_tense, TENSE_TAGS   # noqa: E402

NONFIN = {"participle", "infinitive", "gerund"}

# ══════ 族F：逐条点名。(词元, 形式) → 为什么删 ══════
# 🔴 **不用判据用清单**，因为总量 789 行、我全读过了。
#    判据是给读不完的量准备的；读得完还写判据 = 给自己造一个会误伤的代理。
FOREIGN = {
    # ── 德语版：把散文句 / 带冠词的词条头 / 语言标签当成了词形 ──
    ("dentista", "::Was bedeutet es"): "德语散文句",
    ("dentista", "Was bedeutet es"): "德语散文句",
    ("dentista", "der mir einen Zahn zieht?"): "德语散文句",
    ("dentista", "von einem Zahnarzt zu träumen"): "德语散文句",
    ("dentista", "von einer Zahnärztin zu träumen"): "德语散文句",
    ("biquíni", "Brasilien: biquinizão"): "带语言标签",
    ("amigo", "a amiga"): "带冠词", ("amigo", "as amigas"): "带冠词",
    ("amigo", "o amigo"): "带冠词", ("amigo", "os amigos"): "带冠词",
    ("cinza", "a cinza"): "带冠词", ("cinza", "as cinzas"): "带冠词",
    ("cinza", "o cinza"): "带冠词", ("cinza", "os cinzas"): "带冠词",
    ("mãe", "pai"): "另一个词，不是 mãe 的阳性",
    ("me", "nós"): "me 是宾格、nós 是主格，不是它的复数",
    ("química", "químicos"): "químicos 是 químico 的复数，不是 química 的",
    # ── 意语版：模板标记 / 编造的复数 / 补充式异词 ──
    ("nada", "inv"): "意语模板的「不变化」标记，不是词",
    ("norreno", "inv"): "意语模板的「不变化」标记，不是词",
    ("batalhão", "batalhãoes"): "编造，正确是 batalhões",
    ("lontra", "lontres"): "编造，正确是 lontras",
    ("médico", "médics"): "编造（英语式复数）",
    ("supervisor", "supervisors"): "编造（英语式复数）",
    ("nenhum", "nenhuna"): "编造，正确是 nenhuma",
    ("nenhum", "nenhunas"): "编造，正确是 nenhumas",
    ("mulher", "homens"): "补充式异词，不是屈折",
    ("homem", "mulheres"): "补充式异词，不是屈折",
    # ── 中文版 ──
    ("dormir", "dormo"): "编造，正确是 durmo",
    ("arruinar", "arruino"): "漏重音符，正确是 arruíno",
    # ── 法语版：缺格占位符 ──
    ("aprazer", "---"): "变位表缺格的占位符",
    ("chover", "---"): "变位表缺格的占位符",
    ("prazer", "---"): "变位表缺格的占位符",
}
# es 版 `criar` 的整张动词变位表都是西语（源头把西语模板挂在了葡语段下）。
# 这一条按**表**点名而不是按行，因为整张表 68 格无一例外。
FOREIGN_TABLE = {("criar", "es-edition-forms")}



def plan(con):
    """→ (relabel, foreign, unresolved)"""
    relabel, unresolved = [], collections.Counter()
    auth = collections.defaultdict(set)
    other = collections.defaultdict(list)
    for iid, w, b, tg, old, src in con.execute(
            "SELECT i.id, d.word, i.base, i.tags, i.label_zh, i.src "
            "  FROM inflection i JOIN dict d ON d.id=i.word_id"):
        if src.startswith("en-") or src.startswith("pt-"):
            auth[b].add(w)
        else:
            other[b].append((iid, w, src, tg))
        if not tg:
            continue
        t = set(json.loads(tg))
        # 覆盖闸：有时态 tag 却解析不出时态 ⇒ 表有洞，必须报出来而不是静默回退
        if not (t & NONFIN) and (t & TENSE_TAGS) and resolve_tense(t) == ("", None):
            unresolved[tuple(sorted(t & TENSE_TAGS))] += 1
        new = compose(json.loads(tg))
        if new and new != old:
            relabel.append((iid, old, new, "%s→%s" % (b, w)))

    foreign = []
    for b, rows in other.items():
        for iid, w, src, tg in rows:
            why = FOREIGN.get((b, w))
            # 🔴 整张表点名时**删整张表**，不按行筛。
            #    `criado`/`criando` 恰好葡西同形，但这张表本身不是关于葡语的证据 ——
            #    "碰巧对"不是保留理由，何况权威版本来就给了这两个形式。
            if why is None and (b, src) in FOREIGN_TABLE:
                why = "整张表是西语（源头把西语模板挂在葡语段下）"
            if why:
                foreign.append((iid, b, w, src, why))
    # 名单里每一条都必须真的命中，否则说明库变了、名单过期 —— 大声报，不静默
    hit = {(b, w) for _i, b, w, _s, _y in foreign}
    miss = set(FOREIGN) - hit
    return relabel, foreign, unresolved, miss


def main(a):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    relabel, foreign, unresolved, miss = plan(con)
    f = lambda n: format(n, ",")

    if unresolved:
        print("🔴 时态表有洞，以下组合解析不出时态（先补表再跑）：")
        for k, v in unresolved.most_common():
            print("     %6d  %s" % (v, "+".join(k)))
        return 1
    print("✓ 覆盖闸：库里每个带时态 tag 的组合都被表解析到（0 落空）")

    agg = collections.Counter()
    ex = {}
    for _i, old, new, s in relabel:
        agg[(old, new)] += 1
        ex.setdefault((old, new), s)
    print("\n■ 族E 时态标签重算  %s 行" % f(len(relabel)))
    for (old, new), v in agg.most_common(12):
        print("   %7d  %-26s → %-24s %s" % (v, old[:26], new[:24], ex[(old, new)]))
    if len(agg) > 12:
        print("   …… 另 %d 种变化" % (len(agg) - 12))

    if miss:
        print("\n🔴 FOREIGN 名单里这些没在库里命中（名单过期或库已变）：")
        for b, w in sorted(miss):
            print("     %s → %s" % (b, w))
        return 1
    print("\n■ 族F 外来语/残渣变位（删）  %s 行 —— 逐条点名，每条带理由" % f(len(foreign)))
    byy = collections.Counter(y for _i, _b, _w, _s, y in foreign)
    for y, v in byy.most_common():
        smp = [("%s→%s" % (b, w)) for _i, b, w, _s, yy in foreign if yy == y][:3]
        print("   %5d  %-34s %s" % (v, y[:34], " ".join(smp)))

    if not a.apply:
        print("\n(未加 --apply，不写库)")
        return 0

    with dbtool.session("fix-pt-inflection-tense",
                        expect={"#inflection": -len(foreign)}) as s:
        s.executemany("UPDATE inflection SET label_zh=? WHERE id=?",
                      [(new, i) for i, _o, new, _s in relabel])
        s.executemany("DELETE FROM inflection WHERE id=?", [(i,) for i, _b, _w, _s, _y in foreign])
    print("\n✓ 族E 重算 %s 行 ／ 族F 删 %s 行" % (f(len(relabel)), f(len(foreign))))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    sys.exit(main(ap.parse_args()))
