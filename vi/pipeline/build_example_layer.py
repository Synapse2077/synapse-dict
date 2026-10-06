#!/usr/bin/env python3
"""vi 阶段 6a：**例句层**（`example` / `example_gloss`）。2026-10-01。

判据全部 `import stage6_sources`，本文件一行判据都不写。
裁决过程见 `vi/probes/probe_stage6.py` §B（可重跑）。

═══ 挂靠：例句挂在**义项**上，而义项的键是 `sense_src.src_ref` ═══
例句在源头躺在 `senses[si].examples[]` 里 ⇒ 键是 `(版, 词, 词性, 词源号, si)`，
比义项层的键少最后一节（`gi`，gloss 序号）。一个 si 有多个 gloss 时取**第一条已出版的**。
⚠️ 实测一个 si 带 >1 个 gloss 的只有 587 组（0.4%）⇒ 影响面很小，**但仍然声明**。

三级落点，每一级都写清为什么（`[[dont-gate-facts-on-my-uncertainty]]`）：

    ① 键对得上且该义项已出版  ⇒ `sense_id` ＝ 那条义项     56,419 条（72.0%）
    ② 键对得上而该义项被隐藏  ⇒ `sense_id` NULL，词条级      1,838 条（ 2.3%）
    ③ **本版的义项压根没进 `sense_src`** ⇒ NULL，词条级     20,097 条（25.6%）

🔴 ③ 不是 bug，也不是「键算错了」—— 是**我们有意只收了三版的义项**
   （en/vi/zh，`[[gloss-three-languages]]`）。跨版收割的 fr/ko/de/nl… 九版
   没有义项行，它们的例句自然挂不到义项上。
   `[[dont-say-source-lacks-what-we-skipped]]`：这两件事必须在结构上分得开 ——
   所以 ② 和 ③ 是两个计数，不是一个「挂不上」。

═══ 🔴🔴 译文的语种**按版定，不按字段名定** ═══
vi 版 709 条 `translation` 里**一条真译文都没有**（214 条整串是 `.`，290 条是
`(tục ngữ)` 这种出处标注）。照字段名收 ⇒ 读者看见「译文：.」。
那批进 `example.ref`（它确实是出处），不进 `example_gloss`。

用法：
    python3 vi/pipeline/build_example_layer.py            # 干跑
    python3 vi/pipeline/build_example_layer.py --apply
"""
import argparse
import collections
import gzip
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import build_v3_schema as SCHEMA                                  # noqa: E402
import dbtool                                                     # noqa: E402
import paths                                                      # noqa: E402
import stage6_sources as S6                                       # noqa: E402
# 🔴 W25：折叠解析。判据只有一个家（`criteria.py` §⑩），两个收割器都 import 它。
from criteria import merged_sense_map                              # noqa: E402

PATH_OF = {
    "en-edition": paths.KK, "vi-edition": paths.EDITION,
    "zh-edition-trad": paths.ZH_TRAD, "zh-edition-simp": paths.ZH_SIMP,
    "fr-edition": paths.FR_EDITION, "ja-edition": paths.JA_EDITION,
    "ko-edition": paths.KO_EDITION, "pl-edition": paths.PL_EDITION,
    "ru-edition": paths.RU_EDITION, "nl-edition": paths.NL_EDITION,
    "pt-edition": paths.PT_EDITION, "de-edition": paths.DE_EDITION,
}
F = lambda n: format(n, ",")                                      # noqa: E731


def rd(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def sense_index(con):
    """→ ({(版,词,词性,词源号,si): sense_id}, {同键: 这个键在 sense_src 里有几行})

    🔴 `src_ref` 是 `sense:<ed>:<w>:<pos>:<etym>:<si>:<gi>`，而**词形本身可能含 `:`**
       ⇒ 从右往左切。`split(":")` 会把带冒号的词形切烂而不报错。
    """
    # 🔴🔴 **W25：`sense_id` 要过一道折叠解析。** 1,631 条义项被判成「同一个义项被
    #    两版各描述了一遍」而 `hidden=1`，它们身上挂着 **756 条可出版例句** ——
    #    展示层只渲染 `hidden=0` 的义项、例句跟着义项走 ⇒ 不解析就**整批从页面消失**。
    # ⚠️ 为什么在**收割器**里解析，而不是让填充器去 UPDATE `example.sense_id`：
    #    外锚闸的例句恒等式**含 `sense_id`**，直接改库会判红而它会是对的
    #    （W16 刚栽过一次同形的）。收割器自己产出解析后的值 ⇒ 闸仍是恒等式。
    merged = merged_sense_map(con)
    sid, groups = {}, collections.Counter()
    for ref, s in con.execute("SELECT src_ref, sense_id FROM sense_src ORDER BY id"):
        if not ref.startswith("sense:"):
            continue
        s = merged.get(s, s)
        body = ref[len("sense:"):]
        ed, rest = body.split(":", 1)
        rest, _gi = rest.rsplit(":", 1)
        rest, si = rest.rsplit(":", 1)
        rest, etym = rest.rsplit(":", 1)
        w, pos = rest.rsplit(":", 1)
        k = (ed, w, pos, etym, int(si))
        groups[k] += 1
        if s is not None and k not in sid:
            sid[k] = s
    return sid, groups


def collect(wid, s2id, groups):
    """收割十二版的例句。→ (rows, stat)

    ═══ 🔴🔴 2026-10-03：清洗判据搬进来了，**不是搬进外锚闸** ═══
    阶段 6e 开跑前逮到四类「这行根本不是例句」（见 `stage6_sources.py` §⑤）。
    第一版我是在 `vi/fixes/fix_example_defects.py` 里**改库**，于是外锚闸当场判红
    448＋262＋18 条 —— 它是对的：库里的 `text` 与 dump 不再逐字相等。
    ⚠️ 当时有两条路：
        ① 让外锚闸也套一遍清洗判据   ② 让**收割器**在入库前就清洗
    选 ② 的理由是**可重建性**：按 ① 做，重跑一次 `build_example_layer.py --rebuild`
    会把 448 条脏正文写回去，而闸照样绿（因为闸两边都套了同一层清洗）。
    ⇒ 判据住在 `stage6_sources.py`，**施用点只有收割器这一个**，
      库是它的产物，闸是对这个产物的恒等式。`[[replay-scripts-undo-fixes]]`：
      「修复会被后一步静默撤销」—— 把修复做进收割器就没有「后一步」。

    ⚠️ 越南语音节表从 `wid` 推（它就是 `dict` 的全部词形），**不新引依赖**。
    """
    rows, stat = [], collections.Counter()
    syl = S6.vi_syllables(wid)      # 🔴 同一个实现，闸那边传连接、这边传词形
    for src, _lang in S6.EDITIONS:
        ed = src.split("-")[0]
        tr_lang = S6.TR_LANG[src]
        ref_from_tr = src in S6.REF_FROM_TRANSLATION
        for e in rd(PATH_OF[src]):
            w = (e.get("word") or "").strip()
            if w not in wid:
                stat["源词不在 dict（汉字词头等，有意不收）"] += 1
                continue
            pos = e.get("pos")
            etym = str(e.get("etymology_number", "0") or "0")
            for si, s in enumerate(e.get("senses") or []):
                for xi, x in enumerate(s.get("examples") or []):
                    t = (x.get("text") or "").strip()
                    if not t:
                        stat["文本空 ⇒ 不入库"] += 1
                        continue
                    # 🔴🔴 **按版切掉挤在同一格里的外语译文**（ko 版 1,655 条内嵌韩语）。
                    #    阶段 9 把例句渲染出来才看见的 —— 数据层五道闸全绿，
                    #    而页面上印着 `Em nuôi 2 con chó . 나는 개를 두마리 기르고 있다.`
                    #    ⚠️ 顺序要紧：**切完再判 hidden_why**，否则那 45 条韩语标签行
                    #      会以「有国语字母」的身份穿过去（`같은 말 : yêu thương`）。
                    # 🔴 **标记残渣先清**（55 条）：`#*: ` 行首标记会干扰后面所有
                    #    按行走的判据（出处首行、内嵌英译），所以它必须排在最前。
                    ct = S6.clean_markup(t)
                    if ct != t:
                        stat["清掉标记残渣（%s）" % ed] += 1
                        t = ct or t
                    if src in S6.TRANSLATION_INSIDE_TEXT:
                        cut = S6.strip_foreign_translation(t)
                        if cut != t:
                            stat["切掉内嵌的外语译文（%s）" % ed] += 1
                        t = cut or t      # 全切空时留原文，交给 hidden_why 判掉
                    k = (ed, w, pos, etym, si)
                    sense_id = s2id.get(k)
                    if sense_id is not None:
                        stat["落点① 挂上已出版义项"] += 1
                    elif k in groups:
                        stat["落点② 该义项被隐藏 ⇒ 词条级"] += 1
                    else:
                        stat["落点③ 本版义项没收（三语方针）⇒ 词条级"] += 1
                    # 出处：`ref` 字段，以及**那些版里其实装着出处的 `translation`**
                    ref = (x.get("ref") or "").strip() or None
                    tr = (x.get("translation") or x.get("english") or "").strip()
                    if ref_from_tr and tr and not ref:
                        ref = tr
                    # ── 🔴🔴 2026-10-03 清洗（阶段 6e 开跑前）：顺序是判据的一部分
                    # ⑤b 出处串进了 `text` 首行而 `ref` 是空的 ⇒ 搬过去（202 条）
                    cite, body = S6.split_citation_prefix(t, syl)
                    if cite:
                        if ref:
                            # ⚠️ 实测 202/202 条 `ref` 都是空的，**但不许假设** ——
                            #    覆盖一条正当出处比留着串位更坏。
                            stat["首行像出处但 `ref` 已有内容 ⇒ 不动"] += 1
                        else:
                            ref, t = cite, body
                            stat["出处从 text 首行搬进 ref（%s）" % ed] += 1
                    # ⑤d 内嵌英译行 ⇒ 搬进译文侧（282 行）。**不是删**：
                    #    实测 262 条库里没有英译，剥掉就丢了英译。
                    inline_en = []
                    if src in S6.INLINE_EN_IN_TEXT:
                        nb, en_lines = S6.split_inline_english(t)
                        if en_lines and nb.strip():
                            t, inline_en = nb, en_lines
                            stat["内嵌英译行搬进译文（%s）" % ed] += len(en_lines)
                    # ── ⑥ W16：本版自己的释义语言挤在同一格里（52 条）
                    # 🔴 这一族**不改 `text`**，只算出一条**出版正文** `pub`：
                    #    fr 版 44 条的尾巴是**法语**，三语方针不许它进 `example_gloss`，
                    #    除了留在 `text` 里它没有别的家 ⇒ 改 `text` 就是永久丢掉源头译文。
                    #    用户 2026-10-05 定的就是「页面不印、证据层原样留」。
                    # ⚠️ 与上面四种清洗**结构不同**（它们直接改 `text`）—— 记 W22。
                    pub, ed_gloss, ed_lang = S6.split_edition_gloss(t, w, src, syl)
                    if ed_gloss:
                        stat["出版正文摘掉本版释义尾巴（%s→%s）" % (ed, ed_lang)] += 1
                    # 🔴 `why` 判在 `t`（整格）上，**不是判在 `pub` 上**：
                    #    6e 那 7.6 万条付费译文是按 `t` 的 hidden 口径挑行买的，
                    #    换成 `pub` 会让一批行的隐藏状态漂移 ⇒ 付费列的落点跟着变。
                    #    ⚠️ 实测这一族 52 条全部 `hidden=0`，两种口径结果相同，
                    #      所以这不是「迁就现状」，是**不为零收益承担漂移风险**。
                    why = S6.example_hidden_why(t, w, x.get("tags") or [], syl)
                    stat[("隐藏：" + why) if why else "✅ 可出版"] += 1
                    # 🔴 出处对中文读者完全不可读 ⇒ 不发布（679 条韩语圣经章节号）。
                    #    ⚠️ 判据是「一个拉丁字母都没有」，**不是「含韩文就切」** ——
                    #      后者会截断 56 条以拉丁为主、夹着原文人名的正当引文。
                    if ref and S6.ref_is_unreadable(ref):
                        stat["出处不可读（无拉丁字母）⇒ 不发布（%s）" % ed] += 1
                        ref = None
                    gloss = None
                    if tr_lang and tr:
                        gloss = (tr_lang, tr)
                        stat["译文 %s" % tr_lang] += 1
                    elif tr:
                        stat["译文是第四语言（%s）⇒ 有意不收" % ed] += 1
                    # 🔴🔴 内嵌英译**接在已有译文前面**，不是丢掉也不是接在后面。
                    #    回 dump 核出来的是**源头的错位**：
                    #        text    : 出处 ⏎ 越南语1 ⏎ 越南语2 ⏎ 英译1
                    #        english : 英译2     ← 英译的**末行**单独进了字段
                    #    拼回去验得上：`Everyone has just one homeland,` ＋
                    #    `like their one and only mother.` 正对
                    #    `Quê hương mỗi người chỉ một, / Như là chỉ một mẹ thôi.`
                    #  ⚠️ 第一版我判成「这条已有英译 ⇒ 内嵌那行是重复 ⇒ 丢掉」，
                    #    而逐条比对 18 条**没有一条相同** ——
                    #    `[[criterion-true-half-vouches-for-false-half]]`：
                    #    「已有英译」那半句是真的，于是给「所以内嵌是重复」背了书，
                    #    而后半句一次都没验。按它做会删掉 18 行真英译。
                    #  ⚠️ 内嵌英译是**英语**，与本版 `translation` 字段装什么无关
                    #    ⇒ 不走 `tr_lang`（那张表管的是 `translation` 字段的语种）。
                    if inline_en:
                        joined = "\n".join(inline_en)
                        if gloss and gloss[0] == "en":
                            gloss = ("en", joined + "\n" + gloss[1])
                            stat["内嵌英译接在源头英译**前面**"] += 1
                        elif gloss:
                            stat["内嵌英译撞上非英语译文（%s）⇒ 保留原译文" % ed] += 1
                        else:
                            gloss = ("en", joined)
                            stat["内嵌英译新建译文（白捡，%s）" % ed] += 1
                    # 🔴 本版释义**在三语之内就搬进 `example_gloss`，不是丢掉**
                    #    （与 `split_inline_english` 同一条规矩：搬不是删）。
                    #    实测 en 版 6 条 `đốt mía ― internode of a sugarcane`
                    #    **库里一条英译都没有** ⇒ 搬过去白捡 6 条。
                    # ⚠️ 不许覆盖已有译文：源头 `translation` 字段比这个尾巴可靠。
                    if ed_gloss and ed_lang in S6.GLOSS_LANG_PUBLISHABLE:
                        if gloss and gloss[0] == ed_lang:
                            stat["本版释义尾巴撞上已有 %s 译文 ⇒ 保留原译文" % ed_lang] += 1
                        elif gloss:
                            stat["本版释义尾巴（%s）撞上别的语种译文 ⇒ 保留原译文" % ed_lang] += 1
                        else:
                            gloss = (ed_lang, ed_gloss)
                            stat["本版释义尾巴搬进译文（白捡，%s→%s）" % (ed, ed_lang)] += 1
                    # 🔴 主键必须唯一标定源记录：版+词+词性+词源号+义序+例序。
                    #    漏掉词性/词源号 ⇒ 同一个词的名词条与动词条的例句键撞在一起
                    #    （义项层上这个 bug 差点悄悄丢掉一万条真义项）。
                    # ⚠️ `pub` 挂在**末位**（r[8]）：`gloss_rows`/`_sync` 都按下标读这个元组，
                    #    插在中间会静默错位（义项层上这个 bug 真的发生过）。
                    rows.append((wid[w], sense_id, t, ref, why, src,
                                 "ex:%s:%s:%s:%s:%d:%d" % (ed, w, pos, etym, si, xi),
                                 gloss, pub))
    # 同一条证据在同一版里出现两次就是重复（`src_ref` 唯一）
    seen, out = set(), []
    for r in rows:
        if r[6] in seen:
            stat["同源重复（去重）"] += 1
            continue
        seen.add(r[6])
        out.append(r)
    out = _dedup_same_cell(out, stat)
    return out, stat


def _dedup_same_cell(out, stat):
    """W24：**同一格里**（同一词形的同一个义项／同一个「例句」区）跨版重复的例句。

    🔴🔴 **分组键必须带 `sense_id`，这是读者口径。** 展示层把带义项的例句印在各自的
       义项下、`sense_id IS NULL` 的印在末尾的「例句」区 —— 所以「同一个词形下文本相同」
       **不等于读者看见重复**。按词形分组得 1,569 组，按读者口径只有 **417 组**。
       我第一次报的就是那个大 3.8 倍的数（`[[measure-landing-not-source]]`）。
    ⚠️ 上游的 `src_ref` 去重管的是「**同一版**里同一条证据出现两次」，
       跨版同句它结构性失明 —— 而那恰好是读者唯一看得见的那一类。
    ⚠️ **不删行**：证据层留着（两版各自确实收了这一句），只标 `hidden`，
       与 B17 的 `redundant-related`、W9 的死链目标同一个处置
       （`[[prefer-reversible-designs]]`）。
    🔴 判据和「留哪一行」的次序都在 `stage6_sources` §⑦，这里只施用。
    """
    byk = collections.defaultdict(list)
    for i, r in enumerate(out):
        if r[4] is not None:
            continue                      # 已经被隐藏的不参与（它本来就不印）
        byk[(r[0], r[1], S6.example_dup_key(r[8]))].append(i)
    for idxs in byk.values():
        if len(idxs) < 2:
            continue
        idxs.sort(key=lambda i: S6.dup_survivor_rank(
            out[i][7][0] if out[i][7] else None, bool(out[i][3]),
            out[i][5], out[i][6]))
        keep, drop = idxs[0], idxs[1:]
        # 🔴 **并，不是丢**：留下来那行缺出处就从被隐藏的行搬过来（实测 5 组需要）
        if not out[keep][3]:
            for i in drop:
                if out[i][3]:
                    out[keep] = out[keep][:3] + (out[i][3],) + out[keep][4:]
                    stat["重复组：出处并到留下来那行"] += 1
                    break
        for i in drop:
            out[i] = out[i][:4] + (S6.HIDDEN_DUP_IN_CELL,) + out[i][5:]
            # ⚠️ 上面已经把它们计进「✅ 可出版」了 ⇒ 必须减回来，
            #    否则统计与库对不上（而统计是我唯一的独立产物）
            stat["✅ 可出版"] -= 1
            stat["隐藏：" + S6.HIDDEN_DUP_IN_CELL] += 1
    return out


def gloss_rows(rows):
    """`collect()` 的行里，**哪些真的会在 `example_gloss` 里落一行**。

    🔴🔴 **2026-10-02 抽出来的，而且是外锚闸第一次跑就逼出来的。**
       原先这个条件以字面量写在 `main()` 里（`[r for r in rows if r[7] and r[4] is None]`），
       外锚闸照着"有译文"自己写了一遍 ⇒ 漏掉 `r[4] is None`，报 **458 条假缺**。
    ⚠️ 教训比「少写一个条件」大：**import 收割器的判据还不够** ——
       「哪些行才真的落库」这一步也是判据，它也必须只有一个家。
       ko 那道外锚闸记的是「闸自己重写收割器的判据」，这里是**同一个病的更细一层**：
       判据共用了，**落库口径没共用**。
    ⭐ 条件本身的理由：隐藏的例句不存译文（闸 **X8**）—— 否则 6e 按「有没有译文」
       挑行时，钱会花在不出版的行上（ko 的 6d 正是这个口径）。
    """
    return [r for r in rows if r[7] and r[4] is None]


def _sync(rows, gl):
    """原地把 `example` 同步到 `collect()` 的产出。→ 打印失效译文的 id 清单。

    🔴 **只改不一样的那几行**，`example` 的行数一行不许变（`src_ref` 是主键口径）。
    ⚠️ undo 需要的东西（旧 `text`）**在 do 之前就取齐**并落盘 ——
       这套流程里真丢过一行数据，就是因为 undo 去读已经改掉的行。

    🔴🔴 **2026-10-05 补「补插缺失的源头译文」。** 在此之前 `_sync` 只会 UPDATE
       `example` 的列、DELETE 变成隐藏的行的译文，**一条译文都不会插** ——
       于是 W16 白捡的那 6 条英译（`đốt mía ― internode of a sugarcane`）
       会**静默掉在地上**：`collect()` 的统计里印着「白捡 6 条」而库里一条没有。
    ⭐ 逮到它的方式：`collect()` 的统计项与库的实际增量是**两个独立产物**，
       `--sync` 走完对一遍就露馅（ko 的 X8 那次也是「两个产物差 69 行」逼出来的）。
    ⚠️ **只插不覆盖**：`(example_id, lang)` 已有行就跳过 —— 6e 的付费中文和源头
       英译都在这张表里，覆盖等于拿免费的盖掉花钱的。
    """
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    cols = {r[1] for r in con.execute("PRAGMA table_info(example)")}
    has_pub = "text_pub" in cols
    have = {ref: (eid, sid, t, rf, h, why, pub)
            for ref, eid, sid, t, rf, h, why, pub in con.execute(
                "SELECT src_ref, id, sense_id, text, ref, hidden, hidden_why, %s FROM example"
                % ("text_pub" if has_pub else "NULL"))}
    con.close()
    upd, now_hidden, text_changed, pub_changed = [], [], [], []
    for r in rows:
        ref = r[6]
        if ref not in have:
            raise SystemExit("🔴 `src_ref=%r` 在库里不存在 —— 收词变了？`--sync` 只同步"
                             "**已有行的列**，行数变了要走 `--rebuild`（而它现在被"
                             "付费数据保险拦着）。" % ref)
        eid, sid, t, rf, h, why, pub = have[ref]
        want = (r[1], r[2], r[3], 1 if r[4] else 0, r[4], r[8])
        if (sid, t, rf, h, why, pub) == want:
            continue
        upd.append(want + (eid,))
        if h == 0 and want[3] == 1:
            now_hidden.append(eid)
        elif want[3] == 0 and t != want[1]:
            text_changed.append(eid)
        # 🔴 `text_pub` 变了要**单独数**，不许并进 `text_changed` ——
        #    后者的含义是「译文失效、要重新买」，而出版正文摘掉外语尾巴之后
        #    中文译文**不用重买**（它只要跟着切掉对应那半，确定性、0 元）。
        #    两个数混在一起会把 52 条免费活算成付费活。
        if want[3] == 0 and pub != want[5]:
            pub_changed.append(eid)
    if not has_pub:
        print("\n■ `text_pub` 列还不存在 ⇒ 本次是**首次填充**，"
              "所以每一行都算「改了」（%s 行），这不是漂移。" % F(len(upd)))
    print("\n■ `--sync`：要改 %s 行（变成隐藏 %s ／ 正文改了 %s ／ 出版正文改了 %s）"
          % (F(len(upd)), F(len(now_hidden)), F(len(text_changed)),
             "首次填充" if not has_pub else F(len(pub_changed))))
    # ── 缺失的源头译文（W16 白捡的那 6 条英译走这条路）
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    gid = {ref: i for i, ref in con.execute("SELECT id, src_ref FROM example")}
    hasg = {(e, l) for e, l in con.execute("SELECT example_id, lang FROM example_gloss")}
    con.close()
    ins = [(gid[r[6]], r[7][0], r[7][1], r[5]) for r in gl
           if r[6] in gid and (gid[r[6]], r[7][0]) not in hasg]
    print("   要补插的源头译文 %s 条%s" % (
        F(len(ins)), ("（%s）" % collections.Counter(x[1] for x in ins).most_common())
        if ins else ""))
    if not upd and not ins:
        print("   库已经与 `collect()` 一致，什么都不做。")
        return
    # 🔴 失效译文的 id 清单**先落盘**，再写库 —— 写库之后就查不出哪些是失效的了
    redo = sorted(text_changed)
    out = paths.WORK / "example_zh" / "redo_ids.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(redo))
    print("   失效译文 id 清单 → %s（%s 条）" % (out.name, F(len(redo))))
    print("   ⇒ 写库之后跑：python3 -u vi/pipeline/translate_examples.py --redo redo_ids")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    drop_g = con.execute(
        "SELECT COUNT(*) FROM example_gloss WHERE example_id IN (%s)"
        % ",".join("?" * len(now_hidden)), now_hidden).fetchone()[0] if now_hidden else 0
    con.close()
    print("   变成隐藏的行上要删掉的译文 %s 条（X8：隐藏的不许带译文）" % F(drop_g))
    with dbtool.session(
            "sync-vi-example-layer",
            expect={"__rows__": 0,
                    "example.hidden_why": None,     # 隐藏原因会增减，不校验具体数
                    "example.ref": None,            # 出处会增减
                    # 🔴 **逐列声明**：没写出的列必须变化 0，这是闸门拦住
                    #    「多写了一列」的唯一机制。首次填充 = 全部可出版行
                    #    （隐藏行的 `text_pub` 也填，它是纯派生值）。
                    "example.text_pub": None,
                    "example_gloss.text": len(ins) - drop_g,
                    "example_gloss.lang": len(ins) - drop_g,
                    "example_gloss.src": len(ins) - drop_g,
                    "example_gloss.example_id": len(ins) - drop_g,
                    "#example_gloss": len(ins) - drop_g},
            invalidates=[]) as s:
        # 🔴 列先补上再写：`ADD_COLUMNS` 是建表那一侧的登记表，这里调它而不是
        #    自己写 `ALTER TABLE` —— 两份 DDL 迟早漂开（W15 那个填充器同一条规矩）。
        have_c = {r[1] for r in s.execute("PRAGMA table_info(example)")}
        for tbl, col, typ in SCHEMA.ADD_COLUMNS:
            if tbl == "example" and col not in have_c:
                s.execute("ALTER TABLE example ADD COLUMN %s %s" % (col, typ))
        s.executemany("UPDATE example SET sense_id=?, text=?, ref=?, hidden=?, hidden_why=?, "
                      "text_pub=? WHERE id=?", upd)
        if now_hidden:
            s.executemany("DELETE FROM example_gloss WHERE example_id=?",
                          [(e,) for e in now_hidden])
        if ins:
            s.executemany("INSERT INTO example_gloss (example_id, lang, text, src) "
                          "VALUES (?,?,?,?)", ins)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    # 🔴 本层是**纯派生层**（全部从 dump 重算，无付费数据）⇒ 重跑＝清空再建。
    #    没有这个开关就只能手动清表，而**手动清表不留痕、不走闸门**
    #    （关系层/词源层/汉字层 2026-10-01 已各补一个，这里 2026-10-03 补上）。
    #    ⚠️ `example_gloss` 有外键指向 `example` ⇒ **先删 gloss 再删 example**。
    #    ⚠️ 等 6e 跑完之后这个开关就**不许再用**：那时 `example_gloss` 里有
    #      7.6 万条花钱买来的模型译文，重建会把它们一起删掉
    #      （`[[enrich-not-rebuild]]`：给已含付费数据的库加字段别重建）。
    ap.add_argument("--rebuild", action="store_true",
                    help="清空 example/example_gloss 再建（纯派生层；6e 之后禁用）")
    # 🔴🔴 **6e 之后唯一能用的那条路。**
    #    `--rebuild` 会删掉 75,970 条花钱买来的译文，所以上面那道保险把它拦住了
    #    （`[[enrich-not-rebuild]]`：给已含付费数据的库加字段，原地补列别重建）。
    #    而判据还会继续收窄（2026-10-03 一天之内收了三次）⇒ 必须有一条**原地**的路。
    # ⇒ `--sync` 拿 `collect()` 当真值，只改**不一样的那几行**：
    #      · `text`/`ref`/`hidden`/`hidden_why` 逐列对齐
    #      · 变成隐藏的行，它的译文**一起删掉**（例句层闸 X8：隐藏的不许带译文）
    #      · `text` 变了的行，**把 id 打出来** —— 它们的付费译文是旧正文的译文，失效了，
    #        必须重跑（`translate_examples.py --redo`）。不打出来就是静默留着错译文。
    ap.add_argument("--sync", action="store_true",
                    help="原地把库同步到 `collect()`（6e 之后代替 --rebuild）")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    s2id, groups = sense_index(con)
    tot = len(wid)
    con.close()
    print("■ dict %s 词形；义项键 %s 组（有已出版义项的 %s）"
          % (F(tot), F(len(groups)), F(len(s2id))))

    rows, stat = collect(wid, s2id, groups)
    pub = [r for r in rows if r[4] is None]
    gl = gloss_rows(rows)
    print("\n■ 例句 %s 条（可出版 %s ／ 隐藏 %s），译文 %s 条"
          % (F(len(rows)), F(len(pub)), F(len(rows) - len(pub)), F(len(gl))))
    for k, v in sorted(stat.items(), key=lambda x: -x[1]):
        print("   %-44s %8s" % (k, F(v)))

    cov = len({r[0] for r in pub})
    covzh = len({r[0] for r in gl if r[7][0] == "zh"})
    print("\n■ 读者口径：有可出版例句的词形 **%s（%.1f%%）**；其中有中文译文的 %s（%.2f%%）"
          % (F(cov), 100.0 * cov / tot, F(covzh), 100.0 * covzh / tot))
    print("   ⚠️ 中文译文覆盖这么低不是漏抽 —— 源头只有 zh 版给（698 条），"
          "其余九版的译文是第四语言。把越南语例句本身译成中文是**要花钱的那条路**。")

    dbtool.sample_check([(r[2][:46], (r[5] or "")[:14],
                          "挂义项" if r[1] else "词条级", r[4] or "出版") for r in rows],
                        10, ("例句", "源", "落点", "出版/隐藏"))

    if not a.apply:
        print("\n(干跑。确认后 --apply)")
        return

    if a.sync:
        _sync(rows, gl)
        return

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    old_x = con.execute("SELECT COUNT(*) FROM example").fetchone()[0]
    old_g = con.execute("SELECT COUNT(*) FROM example_gloss").fetchone()[0]
    con.close()
    if old_x and not a.rebuild:
        raise SystemExit("🔴 example 已有 %s 行 —— 纯派生层，重跑要加 `--rebuild`。" % F(old_x))
    # 🔴 6e 的保险：模型译文一旦落库，`--rebuild` 会把它们删掉 ⇒ 当场拦住。
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    paid = con.execute("SELECT COUNT(*) FROM example_gloss WHERE src LIKE 'model%'").fetchone()[0]
    con.close()
    if paid:
        raise SystemExit("🔴🔴 `example_gloss` 里有 %s 条**花钱买来的**模型译文（6e）——"
                         "`--rebuild` 会删掉它们。改成原地补列，别重建"
                         "（`[[enrich-not-rebuild]]`）。" % F(paid))
    with dbtool.session(
            "build-vi-example-layer",
            expect={"__rows__": 0, "#example": len(rows) - old_x,
                    "#example_gloss": len(gl) - old_g},
            invalidates=["例句层落第一行 ⇒ `example`/`example_gloss` 从 UNCLAIMED 里拿出来，"
                         "例句层闸必须登记并跑绿（`vi/tests/test_example_layer.py`）"]) as s:
        if a.rebuild:
            s.execute("DELETE FROM example_gloss")   # 先删子表（外键）
            s.execute("DELETE FROM example")
        s.executemany(
            "INSERT INTO example (word_id, sense_id, text, ref, hidden, hidden_why, "
            "src, src_ref, text_pub) VALUES (?,?,?,?,?,?,?,?,?)",
            [(r[0], r[1], r[2], r[3], 0 if r[4] is None else 1, r[4], r[5], r[6], r[8])
             for r in rows])
        eid = {ref: i for i, ref in s.execute("SELECT id, src_ref FROM example")}
        s.executemany(
            "INSERT INTO example_gloss (example_id, lang, text, src) VALUES (?,?,?,?)",
            [(eid[r[6]], r[7][0], r[7][1], r[5]) for r in gl])

    print("\n═══ 写后回核 ═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]                     # noqa: E731
    checks = [
        ("example 行数", q("SELECT COUNT(*) FROM example"), len(rows)),
        ("example_gloss 行数", q("SELECT COUNT(*) FROM example_gloss"), len(gl)),
        ("src_ref 唯一", q("SELECT COUNT(*) FROM (SELECT src_ref FROM example "
                          "GROUP BY src_ref HAVING COUNT(*)>1)"), 0),
        ("每条都挂得上 dict",
         q("SELECT COUNT(*) FROM example e LEFT JOIN dict d ON d.id=e.word_id "
           "WHERE d.id IS NULL"), 0),
        ("sense_id 要么空要么真指向一条 sense",
         q("SELECT COUNT(*) FROM example e LEFT JOIN sense s ON s.id=e.sense_id "
           "WHERE e.sense_id IS NOT NULL AND s.id IS NULL"), 0),
        # 🔴 译文只挂在可出版的例句上 —— 隐藏的例句带译文＝白译
        ("隐藏的例句不带译文",
         q("SELECT COUNT(*) FROM example_gloss g JOIN example e ON e.id=g.example_id "
           "WHERE e.hidden=1"), 0),
        ("译文只有三语",
         q("SELECT COUNT(*) FROM example_gloss WHERE lang NOT IN ('zh','en','vi')"), 0),
    ]
    for name, got, want in checks:
        print("   %s %-38s %s（期望 %s）"
              % ("✅" if got == want else "🔴", name, F(got), F(want)))
    con.close()
    if any(g != w for _n, g, w in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
