#!/usr/bin/env python3
"""**账的闸** —— `docs/EN_PLAN.md` 说的话，与盘上和库里的事实对不对得上。
2026-09-06 随 en 阶段 -2 建。

═══ 为什么有这个文件 ═══
用户 2026-08-27：「你自己定的规矩，自己的经验教训，你自己为什么不执行呢」。
查会话自己的记录，形状很干净：**做成机制的全守住了，写成文字的一条没守住。**
⇒ 不再往记忆里写"要记得 X"，写**会自己响的东西**（`[[lesson-must-become-mechanism]]`）。

它逮的是**账**不是数据：阶段表标着 ✅ 而交付物根本不存在
（de 阶段 5 的关系层/频次层就是这么漏了七天的；de 阶段 -1 也被这道闸当场退回过 🔄）。

═══ en 这一版比 de 少什么、多什么 ═══
**少**：de 那份 1111 行，绝大部分是德语专属的收尾单条目核对（C1–C50）。
   en 现在阶段表整列 ⬜，没有收尾单，照抄 1100 行只会得到一堆恒真断言 ——
   **一条永远通过的检查等于没检查**（de 阶段 7 实测过两条）。⇒ 只写现在真能红的。
**多**：**P3 建库主源存证闸**。`EN_PLAN` §1.3 承诺「`KK_2025` 一个字节都不删」，
   而那是**写在注释里的**承诺。de 七月那份包正是这么没的
   （代价：16,483 个词形的读音说不清来源、也补不回来）。⇒ 做成机制。

🔴 **每条检查都必须有一个「它确实会红」的反例** —— 见 `mutate()`。

用法（在 en/ 目录下）：
    python3 tests/test_plan_ledger.py
    python3 tests/test_plan_ledger.py --mutate
"""
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths                                                        # noqa: E402

HERE = Path(__file__).resolve().parent
PLAN = paths.ROOT / "docs" / "EN_PLAN.md"
ANCHOR = HERE / "dump_anchor.txt"

# 阶段 0 的交付物 —— **只有这 13 张**。
# 🔴 2026-09-07 这张表一度把 `entry` / `inflection` 也算进来，阶段 0 跑完当场报红。
#    数据没错，错的是判据：照 de 的划分，`entry` 归**阶段 1**、`inflection` 归**阶段 2**、
#    `search_prefix`/`search_prefix_meta` 归**阶段 9** —— 建表与填内容分属不同阶段
#    （`SCHEMA` 那张「建于 / 内容定于」表就是为分清这两件事画的）。
#    ⇒ 每张表只能算**一个**阶段的交付物，否则前一个阶段永远交不齐。
V3_TABLES = ["dict", "sense", "sense_src", "sense_gloss", "sense_tag",
             "sense_relation", "pronunciation",
             "example", "example_gloss", "collocation", "collocation_gloss",
             "audio", "field_src"]
LATER_TABLES = {"entry": "1", "inflection": "2",
                "search_prefix": "9", "search_prefix_meta": "9"}


# ══════════════════ 读事实 ══════════════════

def _tables():
    try:
        c = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    except sqlite3.Error:
        return {}
    try:
        out = {}
        for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            try:
                out[t] = c.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
            except sqlite3.Error:
                out[t] = -1
        return out
    finally:
        c.close()


# 阶段号的形状：`-2` / `3a` / `1.5` / `1a′`（撇号是"补挂"那类返工步）
STAGE_ID = re.compile(r"-?[0-9][0-9.a-z]*[\u2032\u0027]?")


def stage_region(text):
    """阶段表那一节的正文。找不到就退回全文（`fake_plan` 走这条）。"""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("## ") and "阶段表" in ln:
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("## "):
                    return "\n".join(lines[i:j])
            return "\n".join(lines[i:])
    return text


def parse_rows(text):
    """→ (pairs, unparsed)。pairs = [(阶段号, 状态)]，**按出现顺序、保留重复**。

    🔴🔴 **闸不许把「读不出来的行」当成「不存在的行」**（2026-09-07 用户问
       「阶段2、3暂时都不做是吧」问出来的）。当时表里有两处静默丢弃：

         ① **阶段 2 有两行** —— 做完时新加了一行 ✅、没删旧的 ⬜。
            `parse_stages` 返回 dict ⇒ 后一行**静默覆盖**前一行，闸只看见一个。
            用户读表读到的是那个僵尸 ⬜ 行，以为阶段 2 还没做。
         ② **阶段 `1a′` 闸从来没查过** —— 旧正则 `-?[0-9][0-9.a-z]*` 不认 `′`。
            `deliverables()` 里**登记了** `"1a′"`，解析器却看不见它 ⇒
            一个标着 ✅ 的阶段，交付物一次都没被核过，而且没有任何提示。

    ⇒ 修法**不是把正则加宽**（正则永远追不上下一个没见过的形状），
      是**把丢弃变成响声**：阶段表区域里每一行都必须被认出来，认不出就红。
      加宽只是顺带把 `′` 收进来，真正的闸是 `unparsed`。
    """
    pairs, unparsed = [], []
    for line in stage_region(text).splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        raw = cells[0].strip()
        sid = raw.strip("*").strip()
        if not sid or sid == "#" or set(sid) <= set("-: "):
            continue                      # 表头与分隔行
        if STAGE_ID.fullmatch(sid):
            pairs.append((sid, cells[2]))
        elif raw.startswith("**"):
            # 首格加粗＝作者当它是一行阶段，而闸认不出 ⇒ 必须出声，不许静默跳过
            unparsed.append(sid)
    return pairs, unparsed


def parse_stages(text):
    """从阶段表里读出 {阶段号: 状态文本}。重号会被覆盖 —— 重号本身由 P1 报。"""
    return dict(parse_rows(text)[0])


# 🔴🔴 **只认状态格里第一个状态符，不做子串命中。**
#    de 在 2026-09-03 已经栽过一次并记进了 [[fix-regression-and-gate]]：
#    状态栏写「🔄 **1.5a ✅ 已落库**／1.5b 未跑」，`"✅" in state` 子串命中
#    ⇒ 半成品被判成已完成，**而闸是绿的**。当时的结论是「改判据别改文案，
#    靠记性下次照犯」—— 然后 en 这份拷贝里还是子串写法，2026-09-08 我照犯了。
#    ⇒ 两条一起上：这里认第一个标记（文案怎么写都拦得住），P6 再把混写的格子报红。
MARKS = ("✅", "🟡", "⬜", "🔄")


def _done(status):
    hit = [(status.index(m), m) for m in MARKS if m in status]
    return bool(hit) and min(hit)[1] == "✅"


# ══════════════════ 各阶段的交付物 ══════════════════
# 判据：**声明 ✅ 就必须交得出东西。** 每个 lambda 返回 (ok, 说明)。

def _f(rel):
    """仓库根下的相对路径存在吗"""
    p = paths.ROOT / rel
    return p.exists(), rel


def _rows(t, tabs):
    n = tabs.get(t, None)
    return (n is not None and n > 0), "%s %s" % (t, "不存在" if n is None else f"{n:,} 行")


def deliverables(tabs):
    return {
        "-2": lambda: _all([
            _f("en/dbtool.py"),
            _f("en/tests/test_plan_ledger.py"),
            _f("en/tests/test_no_literal_counts.py"),
            _f("en/tests/test_prune_backups.py"),
            _f("en/tests/test_tools.py"),
            _f("en/tests/dump_anchor.txt"),
        ]),
        "-1": lambda: _f("docs/lang/en-CONVENTIONS.md"),
        # 🔴 en 的阶段 0 **只建空表 + 改名**，不灌数据（数据归 3a）——
        #    与 de/pt 的"迁移式阶段 0"性质不同，判据不能照抄成「dict 有行」。
        #
        # 🔴🔴 **交付物判据必须是单调的**（2026-09-07 当场咬到）：
        #    我原来还加了一条「dict 必须为空」。它在阶段 0 结束那一刻是对的，
        #    但 3a 一灌数据就把**已经完成的阶段 0** 判成红了 ——
        #    那不是缺陷，是我拿"某一刻的状态"当"交付物"。
        #    ⇒ 交付物只能写「做完之后永远成立」的事：表建出来了、老表冻存了、改名做了。
        #      "那一刻还是空的"属于**闸②**（`pipeline/build_v3_schema.py` 里查过了），不属于账。
        "0": lambda: _all([(t in tabs, "表 %s" % t) for t in V3_TABLES] +
                          [_rows("legacy_dict", tabs),
                           ("stardict" not in tabs, "老表 stardict 仍在（改名没做）")]),
        # 阶段 1 已拆成 1a 挂尺子 / 1b 词条层 / 1c 义项层（`EN_PLAN` 阶段表）。
        # 🔴 拆阶段就必须同步登记交付物 —— 2026-09-07 忘了，账的闸当场报
        #    「标了 ✅ 但没登记交付物」。那条分支是为这种情况写的，它起作用了。
        "1a": lambda: _all([_rows("field_src", tabs),
                            (tabs.get("field_src", 0) > 0, "field_src 空 = 尺子没挂")]),
        "1b": lambda: _all([("entry" in tabs, "表 entry"), _rows("entry", tabs)]),
        "1c": lambda: _all([_rows("sense", tabs), _rows("sense_src", tabs)]),
        "1": lambda: _all([("entry" in tabs, "表 entry"), _rows("entry", tabs)]),
        "1d": lambda: _rows("sense_tag", tabs),
        "1.5": lambda: _rows("sense_gloss", tabs),
        "2": lambda: _rows("inflection", tabs),
        "2c": lambda: _rows("inflection", tabs),
        "3a": lambda: _rows("dict", tabs),
        "3b": lambda: _all([_rows("dict", tabs), _rows("legacy_gloss", tabs)]),
        "1a′": lambda: _rows("field_src", tabs),
        "4": lambda: _rows("pronunciation", tabs),
        "5": lambda: _rows("example", tabs),
        "6": lambda: _rows("audio", tabs),
        "7": lambda: _f("en/tests/test_no_regression.py"),
        "8": lambda: _f("packages/dict-core/src/english.ts"),
        "9": lambda: _rows("search_prefix", tabs),
    }


def _all(pairs):
    bad = [why for ok, why in pairs if not ok]
    return (not bad), ("缺：" + "、".join(bad[:4]) if bad else "齐")


# ══════════════════ 检查 ══════════════════

def run(verbose=True, plan_text=None, tabs=None):
    """→ [(编号, 说明)]，空表示全绿"""
    red = []
    text = plan_text if plan_text is not None else (
        PLAN.read_text("utf-8") if PLAN.exists() else None)
    tabs = _tables() if tabs is None else tabs
    lines = []

    # ── P1 计划表在，且阶段表读得出来
    if text is None:
        red.append(("P1", "计划表 %s 不存在 —— 账的闸没有账可对" % PLAN.name))
        stages = {}
    else:
        pairs, unparsed = parse_rows(text)
        stages = dict(pairs)
        if not stages:
            red.append(("P1", "阶段表解析出 0 行 —— 表格格式变了，闸已经瞎了"))
        # 🔴 重号：dict 会静默覆盖，读表的人却会看见两行、各说各话
        dups = sorted({k for k in stages if [x for x, _ in pairs].count(k) > 1})
        if dups:
            red.append(("P1", "阶段号重复 %s —— 做完时新加了一行却没删旧的，"
                              "表里两行各说各话，闸只看得见后一行" % "、".join(dups)))
        # 🔴 闸认不出的行：宁可报红，也不许当它不存在
        if unparsed:
            red.append(("P1", "阶段表里有 %d 行闸认不出：%s —— "
                              "认不出就查不到，等于这些阶段没有闸"
                              % (len(unparsed), "、".join(unparsed[:4]))))
        lines.append("P1 阶段表 %d 行（去重 %d），✅ %d 个"
                     % (len(pairs), len(stages), sum(_done(v) for v in stages.values())))

    # ── P2 声明 ✅ 就必须交得出东西
    dl = deliverables(tabs)
    for sid, status in sorted(stages.items()):
        if not _done(status):
            continue
        if sid not in dl:
            red.append(("P2", "阶段 %s 标了 ✅ 但没登记交付物 —— 补进 deliverables()" % sid))
            continue
        ok, why = dl[sid]()
        if not ok:
            red.append(("P2", "阶段 %s 标着 ✅，交付物却%s" % (sid, why)))
        else:
            lines.append("P2 阶段 %-4s ✅  %s" % (sid, why))

    # ── P3 建库主源存证锚（en 独有）
    #    🔴 `EN_PLAN` §1.3 承诺「KK_2025 一个字节都不删」。写在注释里的承诺守不住。
    if not ANCHOR.exists():
        red.append(("P3", "存证锚 %s 不存在" % ANCHOR.name))
    else:
        n = 0
        for ln in ANCHOR.read_text("utf-8").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            name, _, want = ln.rpartition(" ")
            p = paths.DUMPS / name
            if not p.exists():
                red.append(("P3", "🔴🔴 建库主源不见了：%s —— 外锚闸的前提没了" % name))
            elif str(p.stat().st_size) != want:
                red.append(("P3", "🔴 %s 字节数变了：%s ≠ 锚记的 %s"
                            % (name, f"{p.stat().st_size:,}", f"{int(want):,}")))
            else:
                n += 1
        if n:
            lines.append("P3 建库主源 %d 份，字节数与锚一致" % n)

    # ── P4 冻结表还在（老库那 390 万行是一年付费成果的载体）
    frozen = {t: tabs[t] for t in ("stardict", "legacy_dict") if t in tabs}
    if not frozen:
        red.append(("P4", "🔴🔴 `stardict` 与 `legacy_dict` 一张都不在 —— 老库没了"))
    else:
        lines.append("P4 冻结表 " + "、".join("%s %s 行" % (k, f"{v:,}")
                                             for k, v in frozen.items()))

    # ── P5 阶段 0 之后：老表必须已改名，不许两张并存
    if _done(stages.get("0", "")) and len(frozen) == 2:
        red.append(("P5", "阶段 0 已 ✅ 而 `stardict` 与 `legacy_dict` 并存 —— "
                          "改名没做完，两张表会各说各话"))

    # ── P6 状态格里只许有一个状态符
    #    🔴🔴 **2026-09-08 我自己当场犯的**：阶段 5 的状态我写成
    #      「🟡 5a/5b/5d ✅ 已完成；5c 判定不做；5e 例句中文等命令」——
    #      `_done()` 只查 "✅" 在不在，于是这个**半成品被读成了完成**，
    #      P2 还兴高采烈地对上了交付物（`example` 有行）。
    #    ⇒ 状态是**一个格子一个状态**。要写细节写进备注列，别写进状态列。
    #      与 P1「认不出的行必须出声」同一条原则：**闸读不准就报红，不许自己挑一个。**
    for sid, status in sorted(stages.items()):
        marks = [m for m in MARKS if m in status]
        if len(marks) > 1:
            red.append(("P6", "阶段 %s 的状态格里同时有 %s —— "
                              "闸只查 ✅ 在不在，混着写会把半成品读成完成；"
                              "细节写进备注列" % (sid, "、".join(marks))))

    # ── P7 反向：标 ⬜ 却已经交得出东西 ＝ 僵尸行
    #    🔴 **2026-09-08 用户问「其他步骤都完了吗」才发现**：阶段 4（音标 498,477 行）
    #      与阶段 6（发音 102,751 行）早就做完了，表里还躺着 ⬜。
    #      P2 只查「✅ 的交不交得出东西」，**另一个方向整个没有闸** ——
    #      用户读表会以为还有两步没做，我读表会以为还要再做一遍。
    #    ⚠️ **只查 ⬜，不查 🟡**：🟡 是「有意的部分完成」（阶段 5 的 5e 还没跑），
    #      拿它报红就是把闸写得比它要描述的东西更宽（`[[criteria-narrower-than-you-think]]`）。
    for sid, status in sorted(stages.items()):
        if "⬜" not in status or "✅" in status or "🟡" in status:
            continue
        if sid not in dl:
            continue
        ok, why = dl[sid]()
        if ok:
            red.append(("P7", "阶段 %s 标着 ⬜，交付物却已经%s —— "
                              "做完了没回填，读表的人会以为还没做" % (sid, why)))

    if verbose:
        print("═══ 账的闸（%s）═══" % PLAN.name)
        for s in lines:
            print("   ✓ " + s)
        for cid, why in red:
            print("   🔴 %-4s %s" % (cid, why))
        print("\n   %s" % ("✅ 计划表与盘上/库里对得上" if not red else "🔴 %d 条对不上" % len(red)))
    return red


def check_brief():
    return run(verbose=False)


# ══════════════════ 变异 ══════════════════

def mutate():
    """⭐ 每条规则造一个反例，闸必须报。**一条永远通过的检查等于没检查。**"""
    print("═══ 变异验证 ═══")
    real = PLAN.read_text("utf-8") if PLAN.exists() else ""
    tabs_now = _tables()

    def ids(red):
        return {c for c, _ in red}

    cases = []

    # M1 计划表没了
    cases.append(("P1", "计划表读不到", lambda: run(False, plan_text=None, tabs=tabs_now)
                  if not PLAN.exists() else run(False, plan_text="没有表格", tabs=tabs_now)))
    # M2 阶段表格式变了（解析出 0 行）＝闸瞎了
    cases.append(("P1", "阶段表解析出 0 行", lambda: run(False, plan_text="# 标题\n正文",
                                                     tabs=tabs_now)))
    # 🔴 变异**不许靠替换计划表的原文** —— 2026-09-07 踩到：我改了阶段 0 那行的措辞，
    #    `str.replace` 静默变成 no-op ⇒ 变异不再制造缺陷，M5 悄悄变成恒真（7/7 → 6/7 才发现）。
    #    ⇒ 合成一张最小阶段表，与正文措辞完全解耦。
    def fake_plan(*rows):
        head = "| # | 阶段 | 状态 | 依赖 | 备注 |\n|---|---|---|---|---|\n"
        return head + "".join("| **%s** | x | %s | — | — |\n" % r for r in rows)

    # M3 把一个交不出东西的阶段标成 ✅
    # 🔴🔴 **这条变异 2026-09-08 被发现已经空转**：它原来写 `tabs=tabs_now`，
    #    靠的是「search_prefix 这张表当时还不存在」。阶段 9 一做完，表有了 52 万行，
    #    变异就**再也造不出缺陷**，静默变成恒真 —— 与 §M5 那次 `str.replace` 变 no-op 同病。
    # ⇒ **变异不许依赖「现在恰好没有」**，缺陷要自己造出来：把交付物从 tabs 里拿掉。
    cases.append(("P2", "阶段 9 假称 ✅（把 search_prefix 拿掉）",
                  lambda: run(False, plan_text=fake_plan(("9", "✅")),
                              tabs={k: v for k, v in tabs_now.items()
                                    if k != "search_prefix"})))
    # M4 冻结表消失
    cases.append(("P4", "老库两张冻结表都不在",
                  lambda: run(False, plan_text=real,
                              tabs={k: v for k, v in tabs_now.items()
                                    if k not in ("stardict", "legacy_dict")})))
    # M5 阶段 0 已完成却两张表并存（改名没做完，两张表会各说各话）
    t2 = dict(tabs_now)
    t2["stardict"] = t2["legacy_dict"] = t2.get("legacy_dict", 1)
    cases.append(("P5", "阶段 0 ✅ 而 stardict/legacy_dict 并存",
                  lambda: run(False, plan_text=fake_plan(("0", "✅")), tabs=t2)))

    # M9 状态格混着写（✅ 与 🟡 同格）—— 闸会把半成品读成完成
    cases.append(("P6", "状态格里 🟡 和 ✅ 同时出现",
                  lambda: run(False, plan_text=fake_plan(("5", "🟡 a 已 ✅ 完成；b 待跑")),
                              tabs=tabs_now)))
    # M10 标 ⬜ 却已经交得出东西（僵尸 ⬜ 行）—— 2026-09-08 真实发生过（阶段 4/6）
    cases.append(("P7", "阶段 4 标 ⬜ 而 pronunciation 有行",
                  lambda: run(False, plan_text=fake_plan(("4", "⬜")), tabs=tabs_now)))

    # M7 阶段号重复（僵尸行没删）—— 2026-09-07 真实发生过
    cases.append(("P1", "阶段 2 出现两行（一 ⬜ 一 ✅）",
                  lambda: run(False, plan_text=fake_plan(("2", "⬜"), ("2", "✅")),
                              tabs=tabs_now)))
    # M8 阶段表里混进闸认不出的行 —— 必须出声，不许静默跳过
    cases.append(("P1", "阶段表里有闸认不出的加粗行",
                  lambda: run(False, plan_text=fake_plan(("2", "✅"), ("四之一", "✅")),
                              tabs=tabs_now)))

    # M11 **负控**：状态格 "🟡 … ✅ …" 不许被读成完成
    #    这是 de 那次的原样重现 —— 旧的子串写法会让 P2 去查交付物（这里已把
    #    search_prefix 拿掉 ⇒ 旧写法必报 P2 红）。新写法只认第一个标记 ⇒ P2 必须**不响**，
    #    只由 P6 报「混写」。**闸不许对一个明明写着 🟡 的阶段做完成性判断。**
    neg = run(False, plan_text=fake_plan(("9", "🟡 a 已 ✅ 完成；b 待跑")),
              tabs={k: v for k, v in tabs_now.items() if k != "search_prefix"})
    neg_ids = ids(neg)
    neg_ok = ("P2" not in neg_ids) and ("P6" in neg_ids)

    ok = 0
    for want_id, why, fn in cases:
        got = ids(fn())
        good = want_id in got
        ok += good
        print("   %s  %-40s → %s" % ("✓" if good else "🔴 没逮住", why,
                                     ",".join(sorted(got)) or "全绿"))

    print("   %s  %-40s → %s" % ("✓" if neg_ok else "🔴 负控失败",
                                 "负控：🟡 里夹 ✅ 不许被读成完成",
                                 ",".join(sorted(neg_ids)) or "全绿"))
    ok += neg_ok
    extra_n = 1        # 不走 cases 循环的检查，单独计进分母

    # M6 存证锚：改一个字节数，P3 必须红。**改真文件不安全 ⇒ 用临时锚**
    import tempfile
    global ANCHOR
    keep = ANCHOR
    try:
        d = Path(tempfile.mkdtemp())
        bad = d / "a.txt"
        bad.write_text("kaikki.org-dictionary-English-20250424.jsonl 1\n", "utf-8")
        ANCHOR = bad
        good = "P3" in ids(run(False, plan_text=real, tabs=tabs_now))
        ok += good
        print("   %s  %-40s → %s" % ("✓" if good else "🔴 没逮住",
                                     "存证锚字节数对不上", "P3" if good else "全绿"))
        missing = d / "b.txt"
        missing.write_text("不存在的包.jsonl 123\n", "utf-8")
        ANCHOR = missing
        good2 = "P3" in ids(run(False, plan_text=real, tabs=tabs_now))
        ok += good2
        print("   %s  %-40s → %s" % ("✓" if good2 else "🔴 没逮住",
                                     "存证锚指向的包不在盘上", "P3" if good2 else "全绿"))
    finally:
        ANCHOR = keep

    total = len(cases) + extra_n + 2    # +2 = 下面两条存证锚
    print("\n   变异 %d/%d" % (ok, total))
    return ok == total


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(0 if mutate() else 1)
    sys.exit(1 if run() else 0)
