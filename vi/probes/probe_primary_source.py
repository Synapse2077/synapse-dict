#!/usr/bin/env python3
"""阶段 1 动手前的待决项 §4.1：**主源选谁**。2026-09-28。**只读，不写库，可重跑。**

八门的两种分工（前七门「英文版主源 + 本语言版补」、ko「整个反过来」）在 vi 上都不适用：
en 45,281 词形 ／ vi 41,507 ／ **交集只有 19,681**，两边各自独有两万多。

⚠️ **这个脚本回答的不是「谁给的总量大」** —— 总量已经量过了（`probe_sources.py` §1），
   而且按总量拍板正是 §4.1 明写着不许做的事。
   主源决定的是**骨架**：`entry`（同形异义的边界）与 `dict.pos` 跟谁走、
   另一版的内容往这具骨架上挂。所以这里量三件事：

     §A 顶层字段名普查   —— 先把三版的字段名全打出来（今天已栽两次：
                            `etymology_text`/`etymology_texts`、`tags`/`note`）
     §B 交集 19,681 上逐字段对打 —— 同一个词，谁给得多
     §C 骨架能不能承载   —— pos 值域是否一致、一个词形拆几条 entry
     §D 各自独有的两万多是什么 —— 决定「另一版当补」够不够

🔴 判据全部收窄并写明：`real_gloss` **排除** form_of/alt_of 指针义项，
   因为那不是释义（ko 的 K24：指针被当释义收，越南语这边同理会虚胖）。

用法：
    python3 vi/probes/probe_primary_source.py
    python3 vi/probes/probe_primary_source.py --archive
"""
import argparse
import collections
import re
import gzip
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import paths                                                    # noqa: E402

SRC = [("en", paths.KK), ("vi", paths.EDITION), ("zh", paths.ZH_TRAD)]
ETYM_KEYS = ("etymology_text", "etymology_texts")

# 🔴 指针义项不是释义。en 版用 `form_of`/`alt_of`，越南文版同名字段也在用。
POINTER_KEYS = ("form_of", "alt_of")


def rd(p):
    op = gzip.open if str(p).endswith(".gz") else open
    with op(p, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def real_glosses(e):
    """真释义条数：排除指针义项。⚠️ 不判「是不是元描述」—— 那是 W2 的活儿，判据未收敛。"""
    n = 0
    for s in e.get("senses", []) or []:
        if any(s.get(k) for k in POINTER_KEYS):
            continue
        n += len([g for g in (s.get("glosses") or []) if g.strip()])
    return n


def n_examples(e):
    return sum(len(s.get("examples") or []) for s in e.get("senses", []) or [])


def n_ipa(e):
    return len([s for s in e.get("sounds", []) or [] if s.get("ipa")])


def n_audio(e):
    return len([s for s in e.get("sounds", []) or [] if s.get("audio") or s.get("ogg_url")])


def n_forms(e):
    return len(e.get("forms") or [])


def has_etym(e):
    return int(any(e.get(k) for k in ETYM_KEYS))


# 每个词形上聚合出的一行「谁给了什么」
FIELDS = [
    ("释义(非指针)", real_glosses),
    ("例句", n_examples),
    ("音标", n_ipa),
    ("录音", n_audio),
    ("forms(汉字/量词/异体)", n_forms),
    ("词源", has_etym),
]


def load(p):
    """{词形: {字段: 数量}} ＋ {词形: [pos…]} ＋ {词形: 条目数}"""
    agg = collections.defaultdict(lambda: collections.Counter())
    pos = collections.defaultdict(set)
    cnt = collections.Counter()
    for e in rd(p):
        w = e["word"]
        cnt[w] += 1
        if e.get("pos"):
            pos[w].add(e["pos"])
        for name, fn in FIELDS:
            agg[w][name] += fn(e)
    return agg, pos, cnt


def sA_keys():
    print("§A 顶层字段名普查 —— **抽任何字段之前先做这一步**（今天已栽两次）")
    for tag, p in SRC:
        c = collections.Counter()
        for e in rd(p):
            c.update(e.keys())
        n = sum(1 for _ in rd(p))
        ks = ["%s %.0f%%" % (k, 100 * v / n) for k, v in c.most_common()]
        print("  %s 版（%s 条）：%s" % (tag, format(n, ","), "、".join(ks)))
    print("  ⇒ 三版字段名不是同一套。`etymology_text`(en) vs `etymology_texts`(vi/zh) 在这儿就能看见。")


def sB_head_to_head(EN, VI):
    print("\n§B 交集词形上逐字段对打 —— §4.1 明写的判据「同一个词谁给得更全」")
    both = sorted(set(EN) & set(VI))
    print("  交集词形 **%s** 个。每格＝在这批词上，该字段只有哪一版给了。\n" % format(len(both), ","))
    print("  %-24s %9s %9s %9s %9s   %s" % ("字段", "只 en 有", "只 vi 有", "两版都有", "两版都无", "总量 en : vi"))
    verdict = {}
    for name, _ in FIELDS:
        eo = vo = bo = no = 0
        se = sv = 0
        for w in both:
            a, b = EN[w][name], VI[w][name]
            se += a
            sv += b
            if a and b:
                bo += 1
            elif a:
                eo += 1
            elif b:
                vo += 1
            else:
                no += 1
        verdict[name] = (eo, vo, bo, no, se, sv)
        print("  %-24s %9s %9s %9s %9s   %s : %s"
              % (name, format(eo, ","), format(vo, ","), format(bo, ","), format(no, ","),
                 format(se, ","), format(sv, ",")))
    print("""
  读法：「只 en 有」高 ⇒ 拿 vi 当骨架会丢这一列；反之亦然。
       两列都高 ⇒ **这一层必须并**，谁当主源都不能只取一边。""")
    return verdict


def sC_skeleton(EN_pos, VI_pos, EN_cnt, VI_cnt, both):
    print("\n§C 骨架能不能承载 —— 主源真正决定的东西")
    # C1 pos 值域
    pe = collections.Counter()
    pv = collections.Counter()
    for w in both:
        pe.update(EN_pos.get(w, ()))
        pv.update(VI_pos.get(w, ()))
    print("  C1 `pos` 值域（交集词形上）：")
    print("     en 版 %2d 种：%s" % (len(pe), "、".join("%s %s" % (k, format(v, ",")) for k, v in pe.most_common(8))))
    print("     vi 版 %2d 种：%s" % (len(pv), "、".join("%s %s" % (k, format(v, ",")) for k, v in pv.most_common(8))))
    print("     只 en 有的 pos：%s" % ("、".join(sorted(set(pe) - set(pv))) or "无"))
    print("     只 vi 有的 pos：%s" % ("、".join(sorted(set(pv) - set(pe))) or "无"))
    same = sum(1 for w in both if EN_pos.get(w) == VI_pos.get(w))
    print("     两版给出**完全相同** pos 集合的词形：%s / %s（%.1f%%）"
          % (format(same, ","), format(len(both), ","), 100 * same / len(both)))

    # C2 一个词形拆几条 entry（同形异义边界）
    print("  C2 一个词形拆成几条 entry（＝`entry` 层的边界由谁定）：")
    for tag, cnt in (("en", EN_cnt), ("vi", VI_cnt)):
        d = collections.Counter(cnt[w] for w in both)
        tot = sum(cnt[w] for w in both)
        print("     %s 版：交集上共 %s 条 entry，分布 %s"
              % (tag, format(tot, ","),
                 "、".join("%d条×%s" % (k, format(v, ",")) for k, v in sorted(d.items())[:6])))
    diff = sum(1 for w in both if EN_cnt[w] != VI_cnt[w])
    print("     两版 entry 条数**不一致**的词形：%s（%.1f%%）⇒ 合并时必须有一版说了算"
          % (format(diff, ","), 100 * diff / len(both)))


def sD_exclusive(EN, VI, EN_pos, VI_pos):
    print("\n§D 各自独有的两万多是什么 —— 决定「另一版当补」够不够")
    eo = set(EN) - set(VI)
    vo = set(VI) - set(EN)
    for tag, keys, agg, pos in (("en 独有", eo, EN, EN_pos), ("vi 独有", vo, VI, VI_pos)):
        sp = sum(1 for w in keys if " " in w)
        g = sum(1 for w in keys if agg[w]["释义(非指针)"])
        ipa = sum(1 for w in keys if agg[w]["音标"])
        p = collections.Counter()
        for w in keys:
            p.update(pos.get(w, ()))
        print("  %s %s 个：含空格 %.1f%% ／ 有真释义 %.1f%% ／ 有音标 %.1f%% ／ 前 5 pos %s"
              % (tag, format(len(keys), ","), 100 * sp / len(keys), 100 * g / len(keys),
                 100 * ipa / len(keys),
                 "、".join("%s %s" % (k, format(v, ",")) for k, v in p.most_common(5))))
    print("""  ⇒ 若两边独有的都「有真释义」占高位，说明**两边都不是对方的子集**，
     「主源 + 补」这个说法在 vi 上本身就要改写成「**并**，其中一版定骨架」。""")


def sE_cost(EN_cnt, VI_cnt, both):
    """§C2 报了「16.1% 不一致」，但**不一致的方向**才是代价所在。

    选 en 定骨架 ⇒ vi 比 en 多切的那批，vi 的义项挂不满，必须有挂靠规则；
    选 vi 定骨架 ⇒ en 比 vi 多切的那批同理。**两个方向的行数不一样，必须分开数。**
    （`[[primary-key-is-not-enough]]`：计数型判据对「配错」结构性失明 ——
      16.1% 这一个数把两种完全不同的代价混在一起了。）
    """
    print("\n§E 不一致的**方向** —— 16.1% 那个数把两种代价混在一起了")
    en_more = [w for w in both if EN_cnt[w] > VI_cnt[w]]
    vi_more = [w for w in both if VI_cnt[w] > EN_cnt[w]]
    print("  en 切得更细：%s 个词形（多出 %s 条 entry）"
          % (format(len(en_more), ","), format(sum(EN_cnt[w] - VI_cnt[w] for w in en_more), ",")))
    print("  vi 切得更细：%s 个词形（多出 %s 条 entry）"
          % (format(len(vi_more), ","), format(sum(VI_cnt[w] - EN_cnt[w] for w in vi_more), ",")))
    print("  ⇒ 谁定骨架，**对方多切的那批就需要一条挂靠规则**，这是阶段 1 的真实工作量。")


def sF_zh_and_holes():
    """三件会翻盘的事：zh 版词源的增量、vi 版 `unknown` 词性是什么、en 版 `character` 是什么。"""
    print("\n§F 三个会影响裁决的细节")

    # F1 zh 版词源：zh 的 etymology_texts 覆盖 65% > en 的 56%，增量在哪
    ew = {"en": set(), "vi": set(), "zh": set()}
    for tag, p in SRC:
        for e in rd(p):
            if any(e.get(k) for k in ETYM_KEYS):
                ew[tag].add(e["word"])
    u = ew["en"] | ew["vi"] | ew["zh"]
    print("  F1 词源覆盖（词形数）：en %s ／ vi %s ／ zh %s ／ 并集 %s"
          % tuple(format(len(x), ",") for x in (ew["en"], ew["vi"], ew["zh"], u)))
    print("     zh 相对 en 的**净增量**：%s 个词形（en 没有而 zh 有）"
          % format(len(ew["zh"] - ew["en"]), ","))
    print("     ⇒ 词源层的源不是一版，这条与「主源」是两件事（`[[multi-edition-methodology]]`）")

    # F2 vi 版 unknown 词性
    unk, ex = 0, []
    for e in rd(paths.EDITION):
        if e.get("pos") == "unknown":
            unk += 1
            if len(ex) < 6:
                g = (e.get("senses") or [{}])[0].get("glosses") or [""]
                ex.append("%s〔%s〕%s" % (e["word"], e.get("pos_title", ""), g[0][:20]))
    print("  F2 vi 版 `pos=unknown` **%s 条** —— en 版没有这个值。例：%s"
          % (format(unk, ","), "；".join(ex)))

    # F3 en 版 character 词性：是不是单个表意文字
    ch = single = 0
    exc = []
    for e in rd(paths.KK):
        if e.get("pos") == "character":
            ch += 1
            w = e["word"]
            if len(w) == 1:
                single += 1
            if len(exc) < 6:
                exc.append(w)
    print("  F3 en 版 `pos=character` **%s 条**，其中单字符 %s（%.1f%%）。例：%s"
          % (format(ch, ","), format(single, ","), 100 * single / ch, " ".join(exc)))
    print("     ⇒ 这批是**汉字/喃字本身**，不是国语字词形。它们该进 `dict` 还是只喂汉字层，")
    print("       是阶段 1 收词判据必须先答的（`[[dict-scope-four-rules]]`「词全」指的是越南语词）。")


def sG_pointers():
    """🔴 §B/§D 的「有真释义」被我自己的判据**高估了** —— 指针不一定写在 form_of 里。

    ko 的 K-形陷阱原样复现：韩文版指针的 `form_of` 是 None、目标藏在别处。
    vi 版把指针写成 gloss 正文（`Xem X` 看 X ／ `Như X` 如同 X），
    en 版写成 `Alternative form of X`。两版都得用**正文判据**兜一层。
    """
    print("\n§G 🔴 指针义项不全在 `form_of` 里 —— 修正 §B/§D 的「有真释义」")
    VIP = re.compile(r"^(Xem|Như|Xt\.?|Cv\.?|Nh\.?)\s+\S", re.I)
    ENP = re.compile(r"^(Alternative |Obsolete form|Sino-Vietnamese reading of|"
                     r"Nonstandard form|Misspelling of|Romanization of|Archaic form)", re.I)

    def wm(p, pat):
        real, ptr = collections.Counter(), collections.Counter()
        for e in rd(p):
            w = e["word"]
            real[w] += 0
            for s in e.get("senses", []) or []:
                for g in s.get("glosses") or []:
                    t = g.strip()
                    if not t:
                        continue
                    if s.get("form_of") or s.get("alt_of") or pat.match(t):
                        ptr[w] += 1
                    else:
                        real[w] += 1
        return real, ptr

    ER, EP = wm(paths.KK, ENP)
    VR, VP = wm(paths.EDITION, VIP)
    for tag, keys, R, P in (("en 独有", set(ER) - set(VR), ER, EP),
                            ("vi 独有", set(VR) - set(ER), VR, VP)):
        r = sum(1 for w in keys if R[w])
        op = sum(1 for w in keys if not R[w] and P[w])
        ng = sum(1 for w in keys if not R[w] and not P[w])
        print("  %s %s：有真释义 %s（%.1f%%）／ **只有指针** %s（%.1f%%）／ 一条 gloss 都没有 %s"
              % (tag, format(len(keys), ","), format(r, ","), 100 * r / len(keys),
                 format(op, ","), 100 * op / len(keys), format(ng, ",")))
    print("  ⚠️ 光用 `form_of` 判，vi 独有会报 99.2%；加上正文判据是 92.1% —— 差 7 个点全是指针。")


# 判据：整段形如 `<词形>［漢字］`，且**头部与词形一致**、**括号内全是表意文字**。
# 两个条件都是**收窄**用的：`[[criteria-narrower-than-you-think]]`。
BRACKET = re.compile(r"^\s*(.+?)\s*[［\[]([^］\]]+)[］\]]\s*[。.]?\s*$")


def sH_zh_hanzi():
    """⭐ zh 版 `etymology_texts` 的大头**不是散文词源，是一张汉字表记表**。

    我第一版判据（找「漢越／汉字／喃／借自」）只命中 2,875 / 26,230，
    把 23,355 段丢进「其他」桶 —— 而抽 20 条一看，几乎全是 `thư viện［書院］` 这个形状。
    🔴 `[[residual-bucket-is-not-evidence]]`：「其他」桶是残差不是度量。
    """
    print("\n§H ⭐ zh 版词源栏里藏着一张汉字表记表（改写了阶段 2 的源分工）")
    import unicodedata as ud

    def ideo(c):
        try:
            return ud.name(c).startswith(("CJK UNIFIED IDEOGRAPH", "CJK COMPATIBILITY IDEOGRAPH"))
        except ValueError:
            return False

    zh = collections.defaultdict(set)
    mism = nonideo = 0
    for e in rd(paths.ZH_TRAD):
        w = e["word"]
        for t in e.get("etymology_texts") or []:
            m = BRACKET.match(t.strip())
            if not m:
                continue
            head, han = m.group(1), m.group(2).strip()
            if head != w:
                mism += 1
                continue
            if not all(ideo(c) or c.isspace() for c in han):
                nonideo += 1
                continue
            zh[w].add(han.replace(" ", ""))
    print("  zh 版命中词形 **%s** ／ 对 %s ／ 一形多字 %s（＝**单候选**）"
          % (format(len(zh), ","), format(sum(len(v) for v in zh.values()), ","),
             format(sum(1 for v in zh.values() if len(v) > 1), ",")))
    print("  判据挡掉：头部≠词形 %s ／ 括号内非纯表意 %s（有意不收）" % (mism, nonideo))

    HAN_TAGS = {"CJK", "Hán-Nôm"}
    en = collections.defaultdict(set)
    for e in rd(paths.KK):
        for f in e.get("forms", []) or []:
            if HAN_TAGS & set(f.get("tags") or []):
                g = "".join(c for c in f.get("form", "") if ideo(c))
                if g:
                    en[e["word"]].add(g)
    print("  en 版 forms 命中词形 %s ／ 对 %s（＝**多候选**，ko 的 `hanja_spelling` 形状）"
          % (format(len(en), ","), format(sum(len(v) for v in en.values()), ",")))

    both = set(en) & set(zh)
    agree = sum(1 for w in both if en[w] & zh[w])
    print("  🔴 **两源交叉验证**：两边都给的只有 **%s** 个词形 ⇒ 对得上 %s（%.1f%%）"
          % (format(len(both), ","), format(agree, ","), 100 * agree / max(len(both), 1)))
    print("     ⚠️ 样本只有 %s，**这不足以当验收**；且分歧里有真同形异义"
          % format(len(both), ","))
    print("       （`đồng thanh` en=銅青「铜绿」／ zh=同聲「异口同声」—— 两个都对，是两个词）")
    print("     ⇒ 支持 v4pro 的那条：汉字表记要挂 **sense/entry**，不能挂 word。")
    print("  ⇒ 并集词形 **%s**（en 单独 %s，**zh 净增 %s**）"
          % (format(len(set(en) | set(zh)), ","), format(len(en), ","),
             format(len(set(zh) - set(en)), ",")))


def sI_etym_prose():
    """🔴🔴 **同一天内「词源」这一个字段咬了三口**，这是第三口：判据**太宽**。

    ①  字段名     只认 `etymology_text` 单数 ⇒ 并集 43,785 掉到 25,321（漏 42%）
    ②  残差桶     把 23,355 段 `词形［漢字］` 扔进「其他」⇒ 差点丢掉 2.1 万条汉字表记
    ③  **本函数** 反过来：把那 2.1 万条表记**当成词源计数** ⇒ zh 的净增量虚报 15 倍

    ⇒ 「有 etymology 字段」≠「有词源」。表记归阶段 2，散文才归阶段 7。
    """
    print("\n§I 🔴 词源要分「真散文」与「裸表记」—— 否则 zh 的贡献虚报 15 倍")
    import unicodedata as ud

    def ideo(c):
        try:
            return ud.name(c).startswith(("CJK UNIFIED IDEOGRAPH", "CJK COMPATIBILITY IDEOGRAPH"))
        except ValueError:
            return False

    def bare_table(w, t):
        m = BRACKET.match(t.strip())
        return bool(m) and m.group(1) == w and \
            all(ideo(c) or c.isspace() for c in m.group(2).strip())

    field, prose = {}, {}
    for tag, p in SRC:
        f, pr = set(), set()
        for e in rd(p):
            w = e["word"]
            for k in ETYM_KEYS:
                v = e.get(k)
                for t in ([v] if isinstance(v, str) else (v or [])):
                    if not (t or "").strip():
                        continue
                    f.add(w)
                    if not bare_table(w, t):
                        pr.add(w)
        field[tag], prose[tag] = f, pr
    uf = set().union(*field.values())
    up = set().union(*prose.values())
    print("  %-14s %8s %8s %8s   %s" % ("", "en", "vi", "zh", "并集"))
    print("  %-14s %8s %8s %8s   **%s**"
          % ("有词源字段", *(format(len(field[t]), ",") for t in ("en", "vi", "zh")), format(len(uf), ",")))
    print("  %-14s %8s %8s %8s   **%s**"
          % ("**真散文词源**", *(format(len(prose[t]), ",") for t in ("en", "vi", "zh")), format(len(up), ",")))
    print("  ⇒ zh 版 %s 条里 **%s（%.1f%%）整段只是 `词形［漢字］`** —— 那是表记不是词源。"
          % (format(len(field["zh"]), ","), format(len(field["zh"]) - len(prose["zh"]), ","),
             100 * (len(field["zh"]) - len(prose["zh"])) / len(field["zh"])))
    print("  ⇒ zh 相对 en 的净增：按字段算 %s，**按散文算只有 %s**（虚报 %.0f 倍）"
          % (format(len(field["zh"] - field["en"]), ","), format(len(prose["zh"] - field["en"]), ","),
             len(field["zh"] - field["en"]) / max(len(prose["zh"] - field["en"]), 1)))
    print("  ⇒ 阶段 -1 那行「有词源 51.9%%」的**读者口径真值是 %.1f%%**（%s / 84,328）"
          % (100 * len(up) / 84328, format(len(up), ",")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", action="store_true")
    a = ap.parse_args()
    buf = io.StringIO()
    with redirect_stdout(buf):
        print("■ vi §4.1 主源裁决（只读）")
        sA_keys()
        EN, EN_pos, EN_cnt = load(paths.KK)
        VI, VI_pos, VI_cnt = load(paths.EDITION)
        sB_head_to_head(EN, VI)
        both = sorted(set(EN) & set(VI))
        sC_skeleton(EN_pos, VI_pos, EN_cnt, VI_cnt, both)
        sD_exclusive(EN, VI, EN_pos, VI_pos)
        sE_cost(EN_cnt, VI_cnt, both)
        sF_zh_and_holes()
        sG_pointers()
        sH_zh_hanzi()
        sI_etym_prose()
    out = buf.getvalue()
    print(out, end="")
    if a.archive:
        paths.PROBE.mkdir(parents=True, exist_ok=True)
        f = paths.PROBE / "probe_primary_source.txt"
        f.write_text(out, encoding="utf-8")
        print("■ 已存档 → %s" % f.relative_to(paths.ROOT))


if __name__ == "__main__":
    main()
