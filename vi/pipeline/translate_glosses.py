#!/usr/bin/env python3
"""阶段 5b：把缺中文的义项译成中文。2026-10-02。

═══ 盘子 ═══
    缺中文的**可出版**义项  92,842
      ├ 有越南语释义        52,686   vi → zh   （整句式词典释义）
      └ 有英文释义          40,156   en → zh   （多为同义词串）
      两样都没有的               0   ⇒ **不需要盲推**
    （盲推那条路在 ja/es/ko 上量过三次：无源可查的词让模型按构词猜，
      错误率卡在 24–25% 纹丝不动 —— `[[blind-gloss-inference-ceiling]]`。
      vi 这一轮完全不碰它，是因为**真的没有这一类**，不是因为我们跳过了。）

🔴🔴 **旧报价的 55,168 条复现不出来。** 2026-10-01 报的是「55,168 条 / 2,573,473 字符
   / 半价约 7.0 元」，而今天按同一个口径量是 **92,842 条 / 3.86M 字符**。
   阶段 6/7 只增不减义项，所以差的不是库变了，是**那个口径我今天复现不出来**。
   `[[reversal-needs-new-measurement]]`：手上的数变了就得重新报，不许拿旧报价开跑。
   ⇒ `--slice` 先跑 1% **实测单价**，再据实测报全量。**估算一律不作数。**

═══ 走过的免费路径，逐条写明为什么不够（`[[prove-free-path-before-quoting]]`）═══
 ① 中文版两片 —— **已榨干**。31,965 条候选里真释义 9,854 条全部入库（W2 的结论）。
 ② 中文版的**词源栏** —— 已收（阶段 7a，3,719 段），其中 2,032 段是
    `漢越詞，來自學習。` 这种中文。但**词源 ≠ 释义**，补不了释义栏。
 ③ ja 版 14,756 条带汉字的 gloss ＋ ko 版 106 条 —— **是日语/韩语不是中文**，
    三语方针有意不收（`[[gloss-three-languages]]`）。
 ④ 被隐藏的 33,361 条证据 —— 按定义不是释义（指针/表记/元描述/纯标点）。
 ⑤ 同词形的别的义项已有中文 —— **不能用**：那是拿 A 义项的释义去填 B 义项
    （es 实测这种挪用里 12.4% 是义项错配，`PLAYBOOK` 5.6）。
 ⑥ 汉字表记当释义 —— ko 的 **K25** 量完否决（生成物 58.3% 就是汉字本身，
    与真释义不一致 34.0%）。vi 同形：W2 已证 69.2% 的 zh gloss 只是表记。

═══ 🔴 控制组：验的是**每一个输出字段** ═══
`[[control-must-cover-every-output-field]]`：控制组漏验一个字段就烧掉 418 万 token 作废重跑。
输出只有 `zh` 一个字段，但它有三种坏法，控制组各对一条：
  · **错位** —— 答案挂到别的义项上。⇒ 每批注入 `PROBE` 定题，对不上就是 id 对齐坏了。
    这是最危险的一种：内容都像样，只是配错了对象（`[[primary-key-is-not-enough]]`）。
  · **静默丢批** —— flash 会丢掉批里的一部分（it 实测过）。⇒ 回收时逐 id 点名。
  · **答非所问** —— 输出里混进词头/音标/解释。⇒ 形状检查 ＋ 人眼抽样。
🔴 形状判据**必须同时看原文**：ko 那边第一版两条判据只看译文，把合法输出报成缺陷
   （61 条「译文加了句号」里 61 条源文自己带句点）。本文件的判据一律对比 `g`。

═══ 🔴 答案文件按**义项主键**存 ═══
`[[model-answer-files-key-by-id]]`：按「第几条」存会把中文贴到别的义项上。
`[[answer-file-is-the-ledger]]`：清库 ≠ 清答案文件 ——
同一个数连着两轮不动，先怀疑这轮没生效。

跑（在仓库根）：
    python3 -u vi/pipeline/translate_glosses.py --slice 0.01    # 实测单价，**先跑这个**
    python3 -u vi/pipeline/translate_glosses.py --lang vi
    python3 -u vi/pipeline/translate_glosses.py --lang en
    python3 -u vi/pipeline/translate_glosses.py --load --apply  # 回收进库
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse                                                   # noqa: E402
import asyncio                                                    # noqa: E402
import collections                                                # noqa: E402
import hashlib                                                    # noqa: E402
import json                                                       # noqa: E402
import re                                                         # noqa: E402
import sqlite3                                                    # noqa: E402

import ds_batch                                                   # noqa: E402
import paths                                                      # noqa: E402

OUT = paths.WORK / "gloss_zh"
PER_BATCH = 20
F = lambda n: format(n, ",")                                      # noqa: E731

SYS = """你是越汉词典的释义编辑。把给定的词典释义译成中文。

输入是一个 JSON 对象：键是义项编号，值含 w（越南语词头）、p（词性）、g（原释义）。
输出**同样的键**，值是 {"zh": "中文释义"}。键一个不许少、不许多、不许改。

规矩：
1. 译成**词典释义**的体例：名词用名词、动词用动词短语，不要译成句子。
   原释义是完整句子的（越南语版多为句式定义），译成简洁的中文释义，不要照搬句式。
2. 原释义用分号/逗号并列了几个义项的，中文也并列，用「，」分隔，顺序不变。
   ⚠️ 但若译完之后并列项**中文完全相同**，只保留一个。
3. **只译释义本身**。不要输出越南语词头、不要加音标或汉越字、不要加「意思是」这类引导语、
   不要加解释或例句。
4. 原释义是**元描述**的，译成对应的中文元描述，被指称的词形 X **原样保留不翻译**：
     synonym of X          → X 的同义词
     initialism of X       → X 的首字母缩写
     abbreviation of X     → X 的缩写
     Dạng ... của X        → X 的…形式
     a surname from Chinese        → 源自汉语的姓氏
     a male/female/unisex given name from Chinese → 源自汉语的男性/女性/通用名
5. 原释义里括号中的补充说明（语域、领域、用法、学名）保留，用中文括号。
   学名（拉丁双名法，如 Ziziphus nummularia）**原样保留不翻译**。
6. 吃不准的直译，**不要编造**，不要为了通顺增添原文没有的信息。
7. w 和 p 只是**帮你消歧**的，不许出现在输出里。

越南语版释义里的固定用语，**译法前后必须一致**：
   Một xã Việt Nam thuộc:   → 越南的一个乡，属于：
   Tên gọi các xã Việt Nam thuộc: → 越南若干乡的名称，属于：
   (Xem từ nguyên 1)        → （见词源 1）
   từ Hán-Việt              → 汉越词          từ cổ → 古语
   khẩu ngữ                 → 口语            thông tục → 俗语
   phương ngữ               → 方言            tiếng địa phương → 地方话
   nghĩa bóng               → 引申义          nghĩa rộng → 广义
   ít dùng                  → 罕用            cũ → 旧称
🔴 `xã` 是越南的行政区划单位（乡/社），**不要译成「社会」**。"""

# 🔴 控制组的定题。答案是**确定**的，用来验 id 对齐没坏。
#    ⚠️ 它们不是"考模型翻得好不好"——那要靠抽样人读。这几条只回答一个问题：
#      **这个键上的答案，是不是这个键的题目给出来的。**
PROBE = {
    "__c1": {"w": "nước", "p": "noun", "g": "water", "want": ("水",)},
    "__c2": {"w": "một", "p": "num", "g": "one", "want": ("一", "1")},
    "__c3": {"w": "mẹ", "p": "noun", "g": "mother", "want": ("母", "妈")},
}


def gap_rows(con, lang):
    """缺中文、且有 `lang` 释义的**可出版**义项。口径只写一份，一个义项只出一次。

    ⚠️ vi 的 `sense_gloss` 上有 `UNIQUE(sense_id, lang, text)`，实测
       「一个义项多条同语言释义」**是 0 条**（ko 那边有 477 个）⇒ 这里不需要
       ko 那样的 `rowid` 选第一条。但仍然 `GROUP BY s.id` 把这件事**写死在判据里** ——
       哪天源头变了，`MIN(g.text)` 至少是确定的选择，而不是字典遍历顺序决定的
       （ko 那次正是「静默覆盖，送出去的是哪一条我不知道也验不出来」）。
    🔴 `s.hidden=0`：隐藏的义项（指针/表记/纯标点）**不花钱译** ——
       ko 的 6d 栽在按「有没有译文」挑行，钱花在了不出版的行上。
    """
    return con.execute("""
        SELECT s.id, d.word, COALESCE(e.pos, '?'), MIN(g.text)
          FROM sense s
          JOIN dict d  ON d.id = s.word_id
     LEFT JOIN entry e ON e.id = s.entry_id
          JOIN sense_gloss g ON g.sense_id = s.id AND g.lang = ?
         WHERE s.hidden = 0
           AND NOT EXISTS (SELECT 1 FROM sense_gloss x
                            WHERE x.sense_id = s.id AND x.lang = 'zh')
         GROUP BY s.id
         ORDER BY s.id""", (lang,)).fetchall()


def pick_slice(rows, frac):
    """按义项 id 的稳定哈希抽 —— **不是 `rows[::n]`**。

    🔴 切片之后再抽样是本项目犯过三次的错：按顺序抽会抽出一整片同类
       （Unicode 把 CJK 排在前面、`ORDER BY s.id` 把同一版的义项排在一起）。
       按哈希抽与顺序无关，长度分布才与全量可比。
    """
    k = int(frac * 0xFFFF)
    return [r for r in rows
            if int(hashlib.md5(str(r[0]).encode()).hexdigest()[:4], 16) < k]


def already(path):
    """答案文件里已经有答案的义项 id。"""
    out = set()
    if path.exists():
        for line in path.open(encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if isinstance(d.get("id"), int):
                out.add(d["id"])
    return out


def build(rows, per=None):
    per = per or PER_BATCH
    batches, meta = [], []
    for i in range(0, len(rows), per):
        chunk = rows[i:i + per]
        pay = {str(sid): {"w": w, "p": pos, "g": g} for sid, w, pos, g in chunk}
        m = [(str(sid), sid) for sid, *_ in chunk]
        # 每批注入一条定题（轮着来），键**混在中间不放开头**
        ck = list(PROBE)[i // per % len(PROBE)]
        pay[ck] = {x: PROBE[ck][x] for x in ("w", "p", "g")}
        m.append((ck, ck))
        batches.append(pay)
        meta.append(m)
    return batches, meta


# ══════════════════════════════════════════════════════════════════
# 回收：把答案文件写进 `sense_gloss`
# ══════════════════════════════════════════════════════════════════
SRC_MODEL = "model:deepseek-v4-flash"

# 🔴 引号风格**在代码里确定性归一**，不靠 prompt 保证（prompt 管不住风格一致性）。
# ⚠️ 判据按**内容**写不按符号写：只在引号里裹的是**纯拉丁串**（＝在指称一个越南语词形）
#    时才换成「」。中文行文里的引号可能是真的强调，不许动。
#    ko 那边第一版把汉字也算进来，于是 `他说"这样不行"` 也被改了 ——
#    汉字与中文行文在 Unicode 上分不开，按字符集判就是形式代理。
_Q = re.compile(r"[‘'“\"]([^’'”\"]{1,24})[’'”\"]")
_LATIN_WORD = re.compile(
    r"^[A-Za-zÀ-ỹ][A-Za-zÀ-ỹ\s\-·]*$")
# 越南语特征串：含越南语专有字母或带调元音的拉丁词。**只用来做词一级的对比**，
# 不用来做「有没有」的判断（见 `audit` 里那条收窄过的判据）。
_VI_TOKEN = re.compile(
    "[A-Za-zÀ-ỹ]*["
    "ăâêôơưđĂÂÊÔƠƯĐ"
    "àáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩị"
    "òóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ"
    "][A-Za-zÀ-ỹ]*")


def normalize_zh(t):
    """统一引号；去掉首尾空白。**一个内容字符都不改。**"""
    t = (t or "").strip()

    def rep(m):
        inner = m.group(1).strip()
        if inner and _LATIN_WORD.match(inner):
            return "「%s」" % inner
        return m.group(0)
    return _Q.sub(rep, t)


def load(langs, dry=True):
    """把 `OUT/<lang>.jsonl` 写进 `sense_gloss`。**幂等**：已有中文的义项跳过。"""
    import dbtool
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {r[0] for r in con.execute(
        "SELECT sense_id FROM sense_gloss WHERE lang='zh'")}
    valid = {r[0] for r in con.execute("SELECT id FROM sense WHERE hidden=0")}
    con.close()

    rows, stat, seen = [], collections.Counter(), set()
    for lang in langs:
        p = OUT / ("%s.jsonl" % lang)
        if not p.exists():
            print("⚠️ %s 没有答案文件（还没跑批？）" % p.name)
            continue
        for line in p.open(encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:
                stat["答案行解析不了"] += 1
                continue
            sid, zh = d.get("id"), normalize_zh(d.get("zh"))
            if not isinstance(sid, int):
                stat["定题/非整数键（控制组，不入库）"] += 1
                continue
            if sid not in valid:
                stat["🔴 义项 id 不在出版层里"] += 1
                continue
            if sid in have:
                stat["已有中文，跳过"] += 1
                continue
            if sid in seen:
                stat["答案文件里重复"] += 1
                continue
            if not zh:
                stat["🔴 空译文（不入库）"] += 1
                continue
            seen.add(sid)
            rows.append((sid, "zh", zh, SRC_MODEL))
            stat["要写"] += 1
    for k, v in stat.most_common():
        print("   %-30s %9s" % (k, F(v)))
    if dry or not rows:
        print("\n(干跑。确认后 --load --apply)")
        return

    with dbtool.session(
            "load-vi-zh-glosses",
            expect={"__rows__": 0, "#sense_gloss": len(rows)},
            invalidates=[
                "🔴 义项的中文覆盖率会从 10.6% 跳到接近 100% ⇒ "
                "账的闸 V10 的「释义（读者口径）」下限要在**确认落点之后**上调，不是提前调",
                "展示层（阶段 9）：`sense_gloss.src` 现在多了 "
                "`model:deepseek-v4-flash` 这一档，与白送的 zh 版释义不是一回事 —— "
                "读者得分得出哪条是机器译的",
            ]) as s:
        s.executemany("INSERT INTO sense_gloss (sense_id, lang, text, src) "
                      "VALUES (?,?,?,?)", rows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]                      # noqa: E731
    # 🔴 期望值**按口径重算**，不用 `len(rows)`（两个坏数同源 ⇒ 恒绿）
    left = q("SELECT COUNT(*) FROM sense s WHERE s.hidden=0 AND NOT EXISTS("
             "SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='zh')")
    print("\n═══ 写后回核 ═══")
    print("   模型译文行           %s" % F(q(
        "SELECT COUNT(*) FROM sense_gloss WHERE src='%s'" % SRC_MODEL)))
    print("   仍缺中文的可出版义项  %s" % F(left))
    print("   中文覆盖**词形**      %.2f%%" % q(
        "SELECT 100.0*COUNT(DISTINCT s.word_id)/(SELECT COUNT(*) FROM dict) "
        "FROM sense s JOIN sense_gloss g ON g.sense_id=s.id "
        "WHERE s.hidden=0 AND g.lang='zh'"))
    con.close()


def audit(path, rows, ntok, peak):
    """回收侧的三条控制。**每一条对着一种坏法**，见文件头。"""
    got = {}
    for line in path.open(encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        got[d["id"]] = d.get("zh")
    want = {sid for sid, *_ in rows}

    print("\n═══ 控制组 ═══")
    # ① 错位：定题的答案必须含它该含的字
    ctl_bad = []
    for k, v in PROBE.items():
        ans = got.get(k)
        if ans is None:
            ctl_bad.append((k, "没回来"))
        elif not any(x in ans for x in v["want"]):
            ctl_bad.append((k, "答成了 %r（该含 %s）" % (ans, "/".join(v["want"]))))
    print("   %s 定题对齐        %d/%d"
          % ("✅" if not ctl_bad else "🔴", len(PROBE) - len(ctl_bad), len(PROBE)))
    for k, why in ctl_bad:
        print("      🔴 %s %s" % (k, why))

    # ② 静默丢批：逐 id 点名
    miss = want - set(got)
    print("   %s 逐 id 点名       回来 %s / 要 %s（丢 %s）"
          % ("✅" if not miss else "🔴", F(len(want & set(got))), F(len(want)), F(len(miss))))

    # ③ 答非所问：形状。**每条判据都对比原文 `g`**
    bad = collections.Counter()
    samples = collections.defaultdict(list)
    for sid, w, pos, g in rows:
        t = got.get(sid)
        if t is None:
            continue
        why = None
        if not t.strip():
            why = "空"
        elif not re.search(r"[㐀-鿿]", t):
            # 中文译文里**一个汉字都没有** ⇒ 多半没翻译（原样回显）或只回了拉丁串
            why = "没有一个汉字（多半没翻译）"
        elif w and w.lower() in t.lower() and w.lower() not in g.lower():
            # 词头被写进了释义，而原文里没有 —— 判据**对比原文**，不是只看译文
            why = "把越南语词头写进了释义"
        else:
            # 🔴 **这条判据第一版是「译文里有越南语特征拼写而原文没有」—— 太宽。**
            #    1% 切片实测命中 9 条，**9 条全是合法输出**：
            #      `cốp 的叠音形式，仅用于 côm cốp` ／ `hoá công 的传统声调标注拼写`
            #      `（常用于成语 ăn sống nuốt tươi）` ／ `称为 bê、bê bò 或 bờ`
            #    中文释义**本来就要引用那个越南语词形**（限定搭配、异写、字母名称）。
            #    按字符类判＝形式代理（`[[criteria-from-meaning-not-form]]`），
            #    与 ko 那次「5 条全是汉字词头，汉字词头的中文译文本来就含同一个字」同形。
            # ⇒ 收窄成**词一级**的对比：译文里出现的越南语串，原文里（或词头里）**也得有**。
            #   原文没有而译文编出来的，才是幻觉 —— 这才是这条判据本来想查的事。
            vi_t = {x.lower() for x in _VI_TOKEN.findall(t) if len(x) > 2}
            vi_g = {x.lower() for x in _VI_TOKEN.findall(g)} | {(w or "").lower()}
            extra = sorted(x for x in vi_t if not any(x in y for y in vi_g))
            if extra:
                why = "🔴 译文里的越南语串原文没有（疑似幻觉）：%s" % extra[:3]
        if why:
            bad[why] += 1
            if len(samples[why]) < 3:
                samples[why].append((w, g[:36], t[:36]))
    n = len(want & set(got))
    print("   %s 形状             坏 %d / %s"
          % ("✅" if not bad else "⚠️", sum(bad.values()), F(n)))
    for k, v in bad.most_common():
        print("      ⚠️ %-26s %d" % (k, v))
        for w, g, t in samples[k]:
            print("           %-12s %-36s → %s" % (w, g, t))

    # ④ 单价：**这是本次切片要买的数**
    if ntok:
        per = ntok / max(n, 1)
        print("\n═══ 单价（%s）═══" % ("🔴 高峰全价" if peak else "✅ 空闲半价"))
        print("   总 token %s ／ 成功 %s 条 ⇒ **每条 %.1f token**" % (F(ntok), F(n), per))
        print("   ⚠️ 折算到全量要乘的是**条数**，不是切片比例 —— "
              "切片按哈希抽，长度分布应与全量一致，但**这一点要实测不要假设**")

    print("\n■ 抽样（人眼看 —— 形状检查看不出「译错了」）")
    idx = list(range(0, min(6, len(rows)))) + list(
        range(len(rows) // 2, min(len(rows) // 2 + 6, len(rows))))
    for i in idx:
        sid, w, pos, g = rows[i]
        if sid in got:
            print("   %-14s %-8s %-40s → %s" % (w, pos, g[:40], got[sid]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", action="store_true", help="把答案文件写进库")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--lang", choices=["vi", "en"], default="")
    ap.add_argument("--slice", type=float, default=0.0, help="只跑这个比例（实测单价用）")
    ap.add_argument("--conc", type=int, default=60,
                    help="🔴 从 60 起不从 16 起 —— `[[batch-concurrency-dont-be-timid]]`："
                         "实测快一个数量级且失败都是 0，**并发选低了直接换算成钱**"
                         "（跑慢了会跨出半价窗口）")
    ap.add_argument("--tag", default="", help="答案文件另起名，别覆盖已买到的")
    # 🔴🔴 `[[retry-must-converge-or-drop-loud]]`：**重试必须对半切 + 封顶 + 到顶大声放弃。**
    #    原来只有「按批续传」：同一批原样重发。而 temperature=0 下模型**确定性地**
    #    漏同一个键 —— 实测 en 那一轮 id=27899 连漏两次，批里 19/20 都回来了，
    #    内容也毫无特殊（`tension; tone (especially of anatomy)`）。
    #    原样重发永远收敛不了，而「重试了两次还缺一条」在日志上只是一行 🔴。
    # ⇒ 本开关**只取还缺的那些 id**，并把批长**对半切**（20→10→5→…→1）逐轮缩，
    #   到 1 还缺就**大声放弃并把 id 打出来**，不静默丢。
    ap.add_argument("--retry-missing", action="store_true",
                    help="只重跑答案文件里还缺的 id，批长逐轮对半切到 1")
    a = ap.parse_args()

    if a.load:
        load([a.lang] if a.lang else ["vi", "en"], dry=not a.apply)
        return

    # 🔴 **无条件播报现在是什么价**。装在这儿的理由就是我记不住
    #    （记了三次仍然说错两次，`[[deepseek-pricing-window]]`）。
    peak = ds_batch.announce_window()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    langs = [a.lang] if a.lang else ["vi", "en"]
    OUT.mkdir(parents=True, exist_ok=True)
    for lang in langs:
        rows = gap_rows(con, lang)
        full = len(rows)
        if a.slice:
            rows = pick_slice(rows, a.slice)
        tag = a.tag or "%s%s" % (lang, "-slice" if a.slice else "")
        path = OUT / ("%s.jsonl" % tag)

        if a.retry_missing:
            # 对半切，逐轮缩；每轮只带还缺的 id
            ntok, per = 0, PER_BATCH
            while per >= 1:
                have = already(path)
                left = [r for r in rows if r[0] not in have]
                if not left:
                    print("\n■ %s：一条都不缺 ✓" % lang)
                    break
                b2, m2 = build(left, per)
                print("\n■ %s：还缺 %s 条 ⇒ 批长 %d，%s 批"
                      % (lang, F(len(left)), per, F(len(b2))))
                ntok += asyncio.run(ds_batch.run(SYS, b2, m2, path, mode="flash",
                                                 conc=min(a.conc, len(b2)), every=5))
                if per == 1:
                    still = [r for r in rows if r[0] not in already(path)]
                    if still:
                        # 🔴 到顶了还缺 ⇒ **大声放弃**，把 id 和原文都打出来
                        print("\n🔴🔴 批长已切到 1 仍然拿不到 %d 条 —— **放弃，不静默丢**：" % len(still))
                        for sid, w, pos, g in still:
                            print("     id=%-8d %-20s %s" % (sid, w, g[:60]))
                    break
                per //= 2
            tp = path.with_suffix(".tokens.json")
            prev = json.loads(tp.read_text()) if tp.exists() else {"tok": 0, "runs": []}
            prev["tok"] += ntok
            prev["runs"].append({"tok": ntok, "retry_missing": True, "peak": peak})
            tp.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
            audit(path, rows, prev["tok"], peak)
            continue

        batches, meta = build(rows)
        print("\n■ %s → zh：%s 条义项（全量 %s）%s 批（每批 %d ＋ 1 条定题）"
              % (lang, F(len(rows)), F(full), F(len(batches)), PER_BATCH))
        if not rows:
            continue
        ntok = asyncio.run(ds_batch.run(SYS, batches, meta, path,
                                        mode="flash", conc=a.conc, every=5))
        # 🔴 token 数**落盘**。只打在屏幕上会被 `tail` 截掉，而它正是这一轮要买的那个数。
        tp = path.with_suffix(".tokens.json")
        prev = json.loads(tp.read_text()) if tp.exists() else {"tok": 0, "runs": []}
        prev["tok"] += ntok
        prev["runs"].append({"tok": ntok, "n": len(rows), "full": full, "peak": peak})
        tp.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
        audit(path, rows, prev["tok"], peak)
    con.close()


if __name__ == "__main__":
    main()
