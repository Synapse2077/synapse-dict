#!/usr/bin/env python3
"""阶段 5：把缺中文的 72,064 条义项译成中文。2026-09-21。

═══ 盘子（免费路径全走过之后剩下的）═══
    缺中文的义项        72,064
      ├ 有英文释义      48,836   en → zh
      └ 有韩文释义      23,228   ko → zh
      两样都没有的           0   ⇒ **不需要盲推**
    （盲推那条路在 ja/es 上量过：无源可查的词让模型按构词猜，
      错误率卡在 24–25% 纹丝不动 —— `[[blind-gloss-inference-ceiling]]`。
      ko 这一轮完全不碰它，是因为**真的没有这一类**，不是因为我们跳过了。）

═══ 走过的免费路径，逐条写明为什么不够（`[[prove-free-path-before-quoting]]`）═══
 ① 中文维基的第三个韩语切片 —— **不存在**。kaikki 索引页只有「朝鲜语」「朝鮮語」
    两个（韩语/韓語/韩国语/韓國語 全部 0 命中），两片都已全取。
 ② 英文版 `translations` —— **0 条**。
 ③ 韩文版 `translations` 里的中文 —— 5,833 条，但**能安全挂上义项的只有 1,767**：
    `개` → 狗/犬/獒 三个译词、`sense` 字段为空 ⇒ 挂到哪一条义项上是**猜**。
    判据：该词只有一条义项、且正缺中文，才挂。
 ④ 同词形的别的义项已有中文 —— 7,510 条。**不能用**：那是拿 A 义项的释义去填 B
    义项（es 实测这种判重/挪用里 12.4% 是义项错配，`PLAYBOOK` 5.6）。
 ⑤ ECDICT 单词直查 —— 11,314 条候选（单个英文词 10,455 ＋ `to`+词 859）。
    **没做**：库里「缺中文的义项」与「有中文的义项」是两批**不相交**的行
    （zh 版的义项自带中文，en 版的义项没有），⇒ **天然没有 sense 级真值可以验它**。
    没有标尺就不敢往出版层写（`[[verify-before-claiming-confirmed]]`）。
    🔴 什么会让它回来：若造出一份 sense 级的英中对照集（哪怕几百条人工），
      能把 ECDICT 直查的准确率量出来，那 11,314 条就值得省。

═══ 🔴 控制组：不是走过场，它验的是**每一个输出字段** ═══
`[[control-must-cover-every-output-field]]`：控制组漏验一个字段就烧掉 418 万 token 作废重跑。
本任务输出只有一个字段 `zh`，但它有**三种坏法**，控制组各对一条：
  · **错位** —— 答案挂到别的义项上。⇒ 每批注入 `PROBE` 里的定题（`water`→水），
    答案对不上就是 id 对齐坏了。这是最危险的一种：内容都像样，只是配错了对象
    （`[[primary-key-is-not-enough]]`：主键保证认领得上，不保证配对对）。
  · **静默丢批** —— flash 会丢掉批里的一部分（it 实测过）。⇒ 回收时逐 id 点名。
  · **答非所问** —— 输出里混进词头/注音/解释。⇒ 形状检查 ＋ 人眼抽样。

═══ 🔴 答案文件按**义项主键**存，不按"第几条" ═══
`[[model-answer-files-key-by-id]]`：按序号存会把中文贴到别的义项上。
`[[answer-file-is-the-ledger]]`：清库 ≠ 清答案文件；同一个数连着两轮不动，先怀疑这轮没生效。

跑（在仓库根）：
    python3 -u ko/pipeline/translate_glosses.py --slice 0.01      # 实测单价
    python3 -u ko/pipeline/translate_glosses.py --lang en         # 正式跑
    python3 -u ko/pipeline/translate_glosses.py --load            # 回收进库
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import asyncio
import collections
import hashlib
import re
import json
import sqlite3

import ds_batch
import paths

OUT = paths.WORK / "gloss_zh"
PER_BATCH = 20

SYS = """你是韩汉词典的释义编辑。把给定的词典释义译成中文。

输入是一个 JSON 对象：键是义项编号，值含 w（韩语词头）、p（词性）、g（原释义）。
输出**同样的键**，值是 {"zh": "中文释义"}。键一个不许少、不许多、不许改。

规矩：
1. 译成**词典释义**的体例：名词用名词、动词用动词短语，不要译成句子，不要加句号。
2. 原释义用分号或逗号并列了几个义项的，中文也并列，用「，」分隔，顺序不变。
3. **只译释义本身**。不要输出韩语词头、不要加罗马字或音标、不要加「意思是」这类引导语、
   不要加解释或例句。
4. 原释义是**元描述**的（如 "abbreviation of X"、"'X'의 준말"、"alternative form of X"），
   译成对应的中文元描述（「X 的缩写」「X 的略语」「X 的异体」），X 原样保留不翻译。
5. 原释义里括号中的补充说明（语域、领域、用法）保留，用中文括号。
6. 吃不准的直译，**不要编造**，不要为了通顺增添原文没有的信息。
7. w 和 p 只是**帮你消歧**的，不许出现在输出里。

元描述用语**固定这么译**（韩文版释义里约四分之一带这些词，译法必须前后一致）：
   북한말 / 북한어 → 北韩说法      연변말 → 延边说法       방언 → 方言
   준말 → 略语                  본말 → 本词             옛말 → 古语
   어근 → 词根                  비표준어 → 非标准语      높임말 → 敬语形式
   낮춤말 → 谦称形式             …의 잘못 → …的误写      속되게 이르는 말 → 的俗称
   …을/를 이르는 말 → 对…的称呼
🔴 `북한말` **不是**「朝鲜语」（那是语言的名字），它指的是**北韩的说法**。"""

# 🔴 控制组的定题。答案是**确定**的，用来验 id 对齐没坏。
#    ⚠️ 它们不是"考模型翻得好不好"——那要靠抽样人读。这几条只回答一个问题：
#      **这个键上的答案，是不是这个键的题目给出来的。**
PROBE = {
    "__c1": {"w": "물", "p": "n", "g": "water", "want": ("水",)},
    "__c2": {"w": "하나", "p": "num", "g": "one", "want": ("一", "1")},
    "__c3": {"w": "어머니", "p": "n", "g": "mother", "want": ("母", "妈")},
}


def gap_rows(con, lang):
    """缺中文、且有 `lang` 释义的义项。**口径只写一份，且一个义项只出一次。**

    🔴 2026-09-22 花钱前逮到：一个义项可以有**多条**同语言释义
       （en 49,313 行 / 48,836 个义项 ⇒ 477 个义项带两条）。
       而 payload 是按 `sense_id` 做键的 dict ⇒ 第二条会**静默覆盖**第一条，
       「送出去的是哪一条」变成了字典遍历顺序决定的，我不知道、也验不出来。
       ⇒ 在 SQL 里就按 `(kind, seq)` 取**第一条**，把选择写死在判据里。
    ⚠️ 丢掉的那一条不是丢内容：`sense_gloss` 原样在库里，
       只是中文释义按第一条译（词典一条义项配一条中文释义）。
    """
    return con.execute("""
        SELECT s.id, d.word, e.pos, g.text
          FROM sense s
          JOIN dict d  ON d.id = s.word_id
          JOIN entry e ON e.id = s.entry_id
          JOIN sense_gloss g ON g.sense_id = s.id AND g.lang = ?
         WHERE NOT EXISTS (SELECT 1 FROM sense_gloss x
                            WHERE x.sense_id = s.id AND x.lang = 'zh')
           AND g.rowid = (SELECT y.rowid FROM sense_gloss y
                           WHERE y.sense_id = s.id AND y.lang = g.lang
                           ORDER BY y.kind, y.seq LIMIT 1)
         ORDER BY s.id""", (lang,)).fetchall()


def pick_slice(rows, frac):
    """按义项 id 的稳定哈希抽 —— **不是 `rows[::n]`**。

    🔴 切片之后再抽样是本项目一天内犯过三次的错：`rows[:4000:311]` 抽出来
       全是生僻汉字，因为 Unicode 把 CJK 排在谚文前面。按哈希抽与顺序无关。
    """
    k = int(frac * 0xFFFF)
    return [r for r in rows
            if int(hashlib.md5(str(r[0]).encode()).hexdigest()[:4], 16) < k]


def build(rows):
    batches, meta = [], []
    for i in range(0, len(rows), PER_BATCH):
        chunk = rows[i:i + PER_BATCH]
        pay = {str(sid): {"w": w, "p": pos, "g": g} for sid, w, pos, g in chunk}
        m = [(str(sid), sid) for sid, *_ in chunk]
        # 每批注入一条定题（轮着来），键混在中间不放开头
        ck = list(PROBE)[i // PER_BATCH % len(PROBE)]
        pay[ck] = {x: PROBE[ck][x] for x in ("w", "p", "g")}
        m.append((ck, ck))
        batches.append(pay)
        meta.append(m)
    return batches, meta


# ══════════════════════════════════════════════════════════════════
# 回收：把答案文件写进 `sense_gloss`
# ══════════════════════════════════════════════════════════════════
SRC_MODEL = "model:deepseek-v4-flash"

# 🔴 引号风格**在代码里确定性归一**，不靠 prompt 保证。
#    实测切片里同一批混用四种（全角单 169／不加 127／全角双 68／直角 33）——
#    词典页面上这是看得见的不一致。
#    ⚠️ 只在**引号里裹的是谚文/汉字词**时才换，别去动引号里的中文行文
#      （那可能是真的强调），判据按内容写不按符号写。
_Q = re.compile(r"[‘'“\"]([^’'”\"]{1,24})[’'”\"]")


def normalize_zh(t):
    """统一引号；去掉首尾空白。**一个内容字符都不改。**"""
    t = (t or "").strip()

    def rep(m):
        inner = m.group(1)
        # 🔴 只在**引号里含谚文**时归一 —— 那才是"在指称一个韩语词头"。
        #    第一版把汉字也算进来，于是 `他说"这样不行"` 也被改成了「这样不行」：
        #    汉字与中文行文在 Unicode 上分不开，按字符集判就是形式代理。
        #    ⚠️ 代价说明白：**汉字词头**（`株式会社`）被引用时不会归一 ——
        #      宁可少改，不可改错（`[[criteria-from-meaning-not-form]]`）。
        if (re.search(r"[가-힣]", inner)
                and re.fullmatch(r"[가-힣ᄀ-ᇿㄱ-ㆎ·\-\s]+", inner)):
            return "「%s」" % inner
        return m.group(0)
    return _Q.sub(rep, t)


def load(con_rw_path, langs, dry=True):
    """把 `OUT/<lang>.jsonl` 写进 `sense_gloss`。**幂等**：已有中文的义项跳过。"""
    import dbtool
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    have = {r[0] for r in con.execute(
        "SELECT sense_id FROM sense_gloss WHERE lang='zh'")}
    valid = {r[0] for r in con.execute("SELECT id FROM sense")}
    con.close()

    rows, stat = [], collections.Counter()
    seen = set()
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
                stat["🔴 义项 id 在库里不存在"] += 1
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
            rows.append((sid, "zh", "definition", 0, zh, SRC_MODEL))
            stat["要写"] += 1
    for k, v in stat.most_common():
        print("   %-28s %9s" % (k, format(v, ",")))
    if dry or not rows:
        print("\n(干跑。确认后 --load --apply)")
        return

    with dbtool.session("load-ko-zh-glosses",
                        expect={"#sense_gloss": len(rows)},
                        invalidates=[
                            "🔴 义项的中文覆盖率会从 74.09% 跳到接近 100% —— "
                            "账本闸 P6 的下限要在**确认落点之后**上调，不是提前调",
                            "展示层（阶段 9）：`sense_gloss.src` 现在有 "
                            "`model:deepseek-v4-flash` 这一档，与白送的 zh 版释义不是一回事",
                        ]) as s:
        s.executemany("INSERT INTO sense_gloss (sense_id, lang, kind, seq, text, src) "
                      "VALUES (?,?,?,?,?,?)", rows)

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    # 🔴 期望值**按口径重算**，不用 `len(rows)`（同一天栽过：两个坏数同源 ⇒ 恒绿）
    left = q("SELECT COUNT(*) FROM sense s WHERE NOT EXISTS("
             "SELECT 1 FROM sense_gloss g WHERE g.sense_id=s.id AND g.lang='zh')")
    print("\n═══ 写后回核 ═══")
    print("   模型译文行            %s" % format(
        q("SELECT COUNT(*) FROM sense_gloss WHERE src='%s'" % SRC_MODEL), ","))
    print("   仍缺中文的义项        %s" % format(left, ","))
    print("   义项中文覆盖率        %.2f%%" % q(
        "SELECT 100.0*COUNT(DISTINCT sense_id)/(SELECT COUNT(*) FROM sense) "
        "FROM sense_gloss WHERE lang='zh'"))
    con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", action="store_true", help="把答案文件写进库")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--lang", choices=["en", "ko"], default="")
    ap.add_argument("--slice", type=float, default=0.0,
                    help="只跑这个比例（实测单价用）")
    ap.add_argument("--conc", type=int, default=8)
    ap.add_argument("--filter", default="",
                    help="只跑原释义匹配这个正则的 —— 用来**专门验某一类**，"
                         "而不是重跑整片（验证要对着缺陷，不是对着平均值）")
    ap.add_argument("--tag", default="", help="答案文件另起名，别覆盖已买到的")
    a = ap.parse_args()

    if a.load:
        load(paths.DB, [a.lang] if a.lang else ["en", "ko"], dry=not a.apply)
        return

    # 🔴 **无条件播报现在是什么价**。它装在这儿的理由就是我记不住
    #    （记了三次仍然说错两次，`[[deepseek-pricing-window]]`）。
    peak = ds_batch.announce_window()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    langs = [a.lang] if a.lang else ["en", "ko"]
    OUT.mkdir(parents=True, exist_ok=True)
    for lang in langs:
        rows = gap_rows(con, lang)
        if a.filter:
            import re as _re
            rx = _re.compile(a.filter)
            rows = [r for r in rows if rx.search(r[3])]
        if a.slice:
            rows = pick_slice(rows, a.slice)
        tag = a.tag or "%s%s" % (lang, "-slice" if a.slice else "")
        path = OUT / ("%s.jsonl" % tag)
        batches, meta = build(rows)
        print("\n■ %s → zh：%s 条义项，%s 批（每批 %d ＋ 1 条定题）"
              % (lang, format(len(rows), ","), format(len(batches), ","), PER_BATCH))
        if not rows:
            continue
        ntok = asyncio.run(ds_batch.run(SYS, batches, meta, path,
                                        mode="flash", conc=a.conc, every=5))
        # 🔴 token 数**落盘**。第一版只打在屏幕上，被 `tail` 截掉就永远拿不回来了，
        #    而它正是这一轮要买的那个数（`[[answer-file-is-the-ledger]]` 同一条：
        #    过程产物不落盘 ＝ 没做过）。续跑时累加。
        tp = path.with_suffix(".tokens.json")
        prev = json.loads(tp.read_text()) if tp.exists() else {"tok": 0, "runs": []}
        prev["tok"] += ntok
        prev["runs"].append({"tok": ntok, "n": len(rows), "peak": peak})
        tp.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
        audit(path, rows, prev["tok"], peak)
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
          % ("✅" if not miss else "🔴", format(len(want & set(got)), ","),
             format(len(want), ","), format(len(miss), ",")))

    # ③ 答非所问：形状
    import re
    bad_shape = collections.Counter()
    for sid, w, pos, g in rows:
        t = got.get(sid)
        if t is None:
            continue
        if not t.strip():
            bad_shape["空"] += 1
        elif re.search(r"[가-힣]", t) and not re.search(r"[가-힣]", g):
            bad_shape["混进谚文（原文没有）"] += 1
        elif re.search(r"[A-Za-z]{4,}", t) and not re.search(r"[A-Za-z]{4,}", g):
            bad_shape["混进拉丁词（原文没有）"] += 1
        # ⚠️ 两条判据 2026-09-21 收窄过 —— 第一版**两条都只看译文、不看源文**，
        #    于是把合法输出报成了缺陷（又一次「判据比它要描述的东西宽」）：
        #    · 句号：61 条里 **61 条源文自己就带句点**（韩文版释义是完整句），
        #      译文单方面加句号的是 **0**。
        #    · 词头：5 条全是**汉字词头**（`剩`→剩余、`核`→核、`株式会社`→株式会社），
        #      汉字词头的中文译文本来就含同一个字。只有**谚文**词头出现在译文里才是病。
        elif t.rstrip().endswith("。") and not g.rstrip().endswith((".", "。")):
            bad_shape["译文单方面加了句号"] += 1
        elif (w and w in t and w not in g
              and any("가" <= c <= "힣" for c in w)):
            bad_shape["把谚文词头写进了释义"] += 1
    n = len(want & set(got))
    print("   %s 形状             坏 %d / %s"
          % ("✅" if not bad_shape else "⚠️", sum(bad_shape.values()), format(n, ",")))
    for k, v in bad_shape.most_common():
        print("      ⚠️ %-22s %d" % (k, v))

    # ④ 单价：**这是本次切片要买的数**
    if ntok:
        per = ntok / max(n, 1)
        print("\n═══ 单价（%s）═══" % ("🔴 高峰全价" if peak else "✅ 空闲半价"))
        print("   总 token %s ／ 成功 %s 条 ⇒ **每条 %.1f token**"
              % (format(ntok, ","), format(n, ","), per))
        print("   ⚠️ 折算到全量要乘的是**条数**，不是切片比例 —— "
              "切片是按哈希抽的，长度分布与全量一致，但**这一点要实测不要假设**")

    print("\n■ 抽样（人眼看 —— 形状检查看不出「译错了」）")
    for sid, w, pos, g in rows[:6] + rows[len(rows) // 2:len(rows) // 2 + 6]:
        if sid in got:
            print("   %-10s %-6s %-42s → %s" % (w, pos, g[:42], got[sid]))


if __name__ == "__main__":
    main()
