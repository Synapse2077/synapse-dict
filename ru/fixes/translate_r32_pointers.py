#!/usr/bin/env python3
"""R32 收尾：词形页指针说明里**照印非三语原文**的那批，译成中文。ru，2026-11-03。

═══ 盘子 ═══
fr 那 30 万条已解析成标签（`criteria.fr_pointer_tags` → `sense_src.ptr_tags`，页面用变格表同一张映射印中文）。剩下照印原文的：
    vi 901 条（164 种说法：`Dạng cách công cụ số ít` 工具格单数形式）
    pl  67 条（65 种：`lm od: пара`）
    fr 234 条（88 种：解析不全的 `(inusité)`／`et`·`ou` 并列／散文 `Blanchir.`）
⇒ **按说法去重后只译一次**（约 317 种），译文回填到每一行。用户 2026-11-03 拍板花这笔钱（预估远低于 1 元）。

═══ 落在哪 ═══
`sense_src.ptr_zh`：**派生列**，与 `ptr_tags`／`inferred_target` 同类（证据层原文 `text` 一字不动；外锚闸的列级调度把它列进
`ignore`）。页面取法：`ptr_tags` 有值印标签 → 否则 `ptr_zh` 有值印它（标「机翻」）→ 否则印原文。

═══ 控制组 ═══
每批注入 2 道定题（越南语／波兰语各一，答案只从说法本身推）：错位、静默丢批、答非所问各有一条判据（`audit()`）。
答案文件按**说法**存（`{"id": "p<n>", "zh": …}`），`p<n>` 由说法的排序位置给出、与库的行号无关 —— 回填时按说法原文对回去。

跑（在仓库根）：
    python3 -u ru/fixes/translate_r32_pointers.py              # 干跑：数盘子
    python3 -u ru/fixes/translate_r32_pointers.py --run        # 花钱（先播报时段）
    python3 -u ru/fixes/translate_r32_pointers.py --load       # 回收：干跑
    python3 -u ru/fixes/translate_r32_pointers.py --load --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "pipeline"))

import argparse
import asyncio
import collections
import json
import re
import sqlite3

import dbtool
import ds_batch
import paths
from pipeline import criteria

OUT = paths.WORK / "r32_pointer_zh_v2.jsonl"     # v1（无术语表）答错波兰语定题 49/60，留着对照
PER_BATCH = 20
F = lambda n: format(n, ",")                                      # noqa: E731

# 读者口径的那批行 —— 与回归闸 P28 同一个 WHERE（页面上照印非三语原文的指针说明）
SCOPE = ("sense_id IS NULL AND lang NOT IN ('zh','en','ru') "
         "AND (pointer_target IS NOT NULL OR inferred_target IS NOT NULL) AND ptr_tags IS NULL")

SYS = """你在给一部俄汉词典翻译「词形页的指针说明」。每条说明出自越南语／波兰语／法语维基词典，说的是这个俄语词形
是另一个词的什么形式（如「工具格单数形式」），少数是一句简短释义。

输入是 JSON 对象：键是编号，值含 l（说明的语言：vi／pl／fr）、t（说明原文）。
输出**同样的键**，值是 {"zh": "中文"}。键一个不许少、不许多、不许改。

规矩：
1. 译成简洁的中文词典用语，不要成句、不要加解释。俄语（西里尔字母）原样保留，不要音译或意译。
2. 语法术语一律用标准译法：主格 属格 与格 宾格 工具格 前置格 方位格 呼格 单数 复数 阳性 阴性 中性
   第一人称 第二人称 第三人称 现在时 过去时 将来时 陈述式 命令式 完成体 未完成体 主动 被动
   形动词 副动词 短尾形式 比较级 最高级 缩写 指小形式 —— 「X/Y」并列的保留斜杠：「主格/宾格复数形式」。
3. 原文自相矛盾或残缺的（源头写坏的）**照原文意思直译，不要自行修正或补全**。
4. 原文是释义而不是形式说明的，译成释义（「Blanchir.」→「漂白」）。
5. 只说了「od: X」「của X」而没说是什么形式的，译成「X 的变化形式」，**不要猜是哪一种形式**。
6. 俄语词（含重音符）**逐字照抄**，不许改重音位置、不许增删字母。
7. 下表是三种语言的语法缩写与术语，**必须按表译**，表里有的一个都不许漏、原文没有的格／数／性／人称一个都不许加：
"""

# ═══ 术语表：模型用它译、`check()` 用它核 —— 两个用途、同一份 ═══
# 🔴 v1 没给术语表，抽查与定题逮到：波兰语 `lp`（单数）译成复数、`krótka forma n lp`（中性单数短尾）译成**阳性**（28 种）、
#    只写 `od: быть` 的被编成「副动词」；越南语 `giới cách`（前置格）有时译成工具格；法语 `оди́н` 被抄成 `о́дин`。
#    ⇒ 中文名**只有一个家**：变格表表头那张 `RU_INFL_TAG_LABELS`（TS），这里读它，不在 Python 里另抄一份。
def _labels():
    src = (paths.ROOT / "packages" / "dict-labels" / "src" / "ru.ts").read_text(encoding="utf-8")
    body = src.split("export const RU_INFL_TAG_LABELS")[1].split("};")[0]
    return {k.strip("'"): v for k, v in re.findall(r"('?[\w-]+'?):\s*'([^']+)'", body)}


L = _labels()
EXTRA = {"indicative": "陈述式", "inflected": "变化形式"}      # 变格表不用、说明里会出现的两个
T = lambda k: L.get(k) or EXTRA[k]                                # noqa: E731
VI = [("cách công cụ", "instrumental"), ("sinh cách", "genitive"), ("dữ cách", "dative"), ("giới cách", "prepositional"),
      ("danh cách", "nominative"), ("đối cách", "accusative"), ("hô cách", "vocative"), ("số ít", "singular"), ("số nhiều", "plural"),
      ("giống đực", "masculine"), ("giống cái", "feminine"), ("giống trung", "neuter"),
      ("ngôi thứ nhất", "first-person"), ("ngôi thứ hai", "second-person"), ("ngôi thứ ba", "third-person"),
      ("hiện tại", "present"), ("quá khứ", "past"), ("tương lai", "future"), ("mệnh lệnh", "imperative"),
      ("trần thuật", "indicative"), ("chưa hoàn thành", "imperfective"), ("hoàn thành", "perfective"),
      ("bị động", "passive"), ("chủ động", "active"), ("phân từ", "participle"), ("viết tắt", "abbreviation"),
      ("so sánh hơn", "comparative"), ("biến tố", "inflected"),
      # 2026-11-03 核对器逮到的漏项（模型译对了、是表漏了）：
      ("vô sinh", "inanimate"), ("hữu sinh", "animate"), ("định vị cách", "locative"), ("short", "short-form"),
      ("adverbial phân từ", "adverbial")]
PL = [("krótka forma", "short-form"), ("stopień wyższy", "comparative"), ("imiesłów przysłówkowy", "adverbial"),
      ("imiesłów przymiotnikowy", "participle"), ("przymiotnikowy", "participle"), ("bierny", "passive"), ("czynny", "active"),
      ("czasu teraźniejszego", "present"), ("czasu przeszłego", "past"), ("niedokonany", "imperfective"), ("dokonany", "perfective"),
      ("lm", "plural"), ("lp", "singular"), ("n", "neuter"), ("m", "masculine"), ("ż", "feminine"),
      ("M.", "nominative"), ("D.", "genitive"), ("C.", "dative"), ("B.", "accusative"), ("N.", "instrumental"),
      ("Ms.", "prepositional"), ("W.", "vocative"), ("3.", "third-person"), ("2.", "second-person"), ("1.", "first-person")]
FR = list(criteria._FR_PTR_TAG.items()) + [(k + " personne", v) for k, v in criteria._FR_PTR_PERSON.items()]
GLOSS = {"vi": VI, "pl": PL, "fr": FR}
# 「多出来就是错」的那几类：格、数、性、人称（模型自己补一个原文没有的，就是 v1 的病）
#   🔴 第一版只列了格/数/性/人称，`od: быть` 被编成「副动词」照样过 ⇒ 扩到术语表的全部语法术语，
#      只留修饰语（罕用/古/异体：法语 `(inusité)` 本该译成「罕用」，而它不在术语表里）。
STRICT = {T(k) for g in GLOSS.values() for _t, k in g} - {T(k) for k in ("rare", "archaic", "alternative", "inflected")}
_HEAD_CUT = re.compile(r"\s+(?:của|od:?|de|d[’'])\s.*$|\s+d[’']\S.*$|\s*od:.*$", re.S | re.I)
_LAT = re.compile(r"[A-Za-zÀ-ÿʹ’'][A-Za-zÀ-ÿʹ’'\u0300-\u036f]{2,}")
_CYR = re.compile(r"[А-Яа-яЁё][А-Яа-яЁё\u0300\u0301\-]*")


def expected(lang, text):
    """→ 原文说明部分（目标词之前）里出现的术语的中文名集合。长的先匹配（`chưa hoàn thành` 不许被 `hoàn thành` 先吃）。"""
    # 🔴 **逐行切**目标词那一截：vi 的 `Dạng biến tố của X:\n## sinh cách số ít\n## …` 是多行，第一版从 `của` 起
    #    把后面整段切掉 ⇒ 下面几行的术语没算进「应有」⇒ 172 条对的译文被判成「多出来」（核对器自己的错）
    head = " %s " % " ".join(_HEAD_CUT.sub("", ln) for ln in text.split("\n")).lower()
    out = set()
    for term, key in sorted(GLOSS[lang], key=lambda x: -len(x[0])):
        pat = r"(?<![\w.])%s(?![\w])" % re.escape(term.lower())
        if re.search(pat, head):
            out.add(T(key))
            head = re.sub(pat, " ", head)
    return out


def terms_in(zh):
    """译文里出现的术语。🔴 **长的先认、认过的位置抹掉**：第一版按子串查，「非动物」里有「动物」、「未完成体」里有「完成体」
    ⇒ 把对的译文判成「多了动物／完成体」（核对器自己的错，不是模型的）。"""
    found = set()
    for w in sorted(set(L.values()) | set(EXTRA.values()), key=len, reverse=True):
        if w in zh:
            found.add(w)
            zh = zh.replace(w, "\u0000" * len(w))
    return found


def check(lang, text, zh):
    """→ None（过）或不过的理由。两个独立信号：术语表推出的应有术语 vs 模型译文。"""
    want = expected(lang, text)
    got = terms_in(zh)
    miss = [w for w in want if w not in got]
    if miss:
        return "缺 " + "、".join(sorted(miss))
    extra = [w for w in STRICT if w in got and w not in want]
    if extra:
        return "多 " + "、".join(sorted(extra))
    lost = [w for w in _CYR.findall(text) if w not in zh]
    if lost:
        return "俄语词没照抄：" + "、".join(lost[:3])
    # 外语原文没译完就漏进译文（抽查逮到：`il n’y a pas`、`：se battre`）—— 三语方针。
    #   只放行源文**括号里**的拉丁字母（vi 的转写 `(kašalót)`、`(type 1c(1))`）。
    ok_lat = {w.lower() for inner in re.findall(r"\(([^()]*)\)", text) for w in _LAT.findall(inner)}
    leak = [w for w in _LAT.findall(zh) if w.lower() not in ok_lat]
    if leak:
        return "外语原文漏进译文：" + " ".join(leak[:4])
    return None


def glossary_text():
    return "\n".join("   %s：%s" % (lang, "；".join("%s＝%s" % (t, T(k)) for t, k in g)) for lang, g in GLOSS.items())


# 定题：答案只从说法本身推（`[[prompt-self-harm-two-patterns]]`：别让题目自己出错）
PROBE = {
    "__c1": {"l": "vi", "t": "Dạng sinh cách số ít", "want": ("单数", "属格")},   # 最后一个＝对题的标志
    "__c2": {"l": "pl", "t": "lm od: стол", "want": ("复数", "стол")},
}


def phrases(con):
    """→ (按说法排序的 [(lang, 原文)]，{(lang, 原文): [行 id]})"""
    rows = collections.defaultdict(list)
    for i, lang, t in con.execute("SELECT id, lang, text FROM sense_src WHERE " + SCOPE):
        rows[(lang, t.strip())].append(i)
    return sorted(rows), rows


def build(keys):
    batches, meta = [], []
    for i in range(0, len(keys), PER_BATCH):
        pay, m = {}, []
        for j, (lang, t) in enumerate(keys[i:i + PER_BATCH], start=i):
            pay["p%d" % j] = {"l": lang, "t": t}
            m.append(("p%d" % j, "p%d" % j))
        for ck, v in PROBE.items():
            pay[ck] = {"l": v["l"], "t": v["t"]}
            m.append((ck, "%s#%d" % (ck, i // PER_BATCH)))
        batches.append(pay)
        meta.append(m)
    return batches, meta


def answers():
    out = {}
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:                                     # noqa: BLE001
                continue
            out.setdefault(d.get("id"), (d.get("zh") or "").strip())
    return out


def audit(keys):
    """控制组：定题答对、一个不丢、答案是中文且没把俄语词丢掉。→ 红的条数"""
    ans = answers()
    red = 0
    probes = {k: v for k, v in ans.items() if isinstance(k, str) and k.startswith("__c")}
    # 定题分两个用途：**对没对上题**（答案里有这道题自己的词 ⇒ 没错位）拦着；**准不准**只报数 ——
    #   每一行本来就过 `check()`，丢了「复数」的那一行自己会被拦下（v2 定题 60 次里 3 次答「стол 的变化形式」）。
    bad_probe = [k for k, v in probes.items() if PROBE[k.split("#")[0]]["want"][-1] not in v]
    inacc = [k for k, v in probes.items() if not all(w in v for w in PROBE[k.split("#")[0]]["want"])]
    print("■ 定题准确率：%d/%d 全对（不全对的 %d 道是丢了术语，不是错位）" % (len(probes) - len(inacc), len(probes), len(inacc)))
    miss = [j for j in range(len(keys)) if not ans.get("p%d" % j)]
    nozh = [(keys[j], ans["p%d" % j]) for j in range(len(keys))
            if ans.get("p%d" % j) and not re.search(r"[一-鿿]", ans["p%d" % j])]
    lost = [(keys[j], ans["p%d" % j], check(keys[j][0], keys[j][1], ans["p%d" % j])) for j in range(len(keys))
            if ans.get("p%d" % j) and check(keys[j][0], keys[j][1], ans["p%d" % j])]
    by = collections.Counter(k[0][0] for k in lost)
    print("■ 控制组：定题 %d 道、答错 %d ／ 缺答 %d ／ 译文没有汉字 %d ／ 术语核对不过 %d（%s）—— 不过的照印原文"
          % (len(probes), len(bad_probe), len(miss), len(nozh), len(lost),
             "／".join("%s %d" % kv for kv in sorted(by.items()))))
    for x in [(k, probes[k]) for k in bad_probe[:5]] + nozh[:5] + lost[:25]:
        print("   ", x)
    red += len(bad_probe) + len(miss)
    return red, nozh, lost


def nozh_or_bad(k, zh):
    return not re.search(r"[\u4e00-\u9fff]", zh) or check(k[0], k[1], zh) is not None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--load", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    has_col = "ptr_zh" in {c[1] for c in con.execute("PRAGMA table_info(sense_src)")}
    keys, rows = phrases(con)
    con.close()
    by = collections.Counter(l for l, _t in keys)
    print("■ 照印非三语原文的指针说明 %s 行 ／ %s 种说法（%s）"
          % (F(sum(len(v) for v in rows.values())), F(len(keys)),
             "／".join("%s %d" % kv for kv in sorted(by.items()))))
    if a.run:
        batches, meta = build(keys)
        asyncio.run(ds_batch.run(SYS + glossary_text(), batches, meta, OUT, mode="flash", conc=20))
    if not (a.run or a.load):
        print("（干跑。--run 花钱）")
        return
    red, _nozh, _lost = audit(keys)
    if not a.load:
        return
    if red:
        raise SystemExit("🔴 控制组红，不回收")
    ans = answers()
    upd = [(ans["p%d" % j], i) for j, k in enumerate(keys) for i in rows[k]
           if not nozh_or_bad(k, ans["p%d" % j])]
    print("■ 回填 %s 行" % F(len(upd)))
    if not a.apply:
        print("（干跑。--apply 写库）")
        return
    with dbtool.session("ru-r32-pointer-zh",
                        expect={"sense_src.ptr_zh": len(upd), "__rows__": 0},
                        invalidates=[]) as s:
        if not has_col:
            s.execute("ALTER TABLE sense_src ADD COLUMN ptr_zh TEXT")
        s.executemany("UPDATE sense_src SET ptr_zh=? WHERE id=?", upd)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    got = con.execute("SELECT COUNT(*) FROM sense_src WHERE " + SCOPE + " AND ptr_zh IS NOT NULL").fetchone()[0]
    left = con.execute("SELECT COUNT(*) FROM sense_src WHERE " + SCOPE + " AND ptr_zh IS NULL").fetchone()[0]
    print("■ 写后回核：有中文 %d 行（期望 %d）；核对不过、照印原文 %d 行" % (got, len(upd), left))
    if got != len(upd):
        raise SystemExit("🔴 回核红")


if __name__ == "__main__":
    main()
