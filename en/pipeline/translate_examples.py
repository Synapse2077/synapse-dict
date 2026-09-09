#!/usr/bin/env python3
"""阶段 5e：例句译成中文 → `example_gloss(lang='zh')`。2026-09-08。

用户 2026-09-08 定：「example_gloss，保持一致吧，要书证」——
⇒ 池子是**全部**例句（含 51.3 万条书证），与 de/pt/fr/it 四门一致。

═══ 🔴🔴 payload 必须带义项上下文 —— fr 最大的一族就栽在这里 ═══
`FR_PLAN` 族 A「例句译文与它所挂的义项不符」，风险面 **22.1 万条**，重跑 41 元：

    taper「发臭」下   `Ça tape ici !`      → 「这儿真热」   ← 取的是另一个义项
    librairie「书店」下 `La librairie du roi.` → 「国王的书店」

根因是 payload **只给了句子、没给义项**。一词多义时模型只能猜，而它猜最常见的那个义。
⇒ **不是可选项。**en 的条件比 pt 还好：例句**挂上义项 99.98%**（de 那轮 51.3%），
   所以上下文直接取 `sense_gloss(lang='en')`，不用 `src_gloss` 近似。

═══ 🔴 批与并发必须在这里覆盖（2026-09-08 的教训）═══
`slot_translate` 的 `CHUNK=160 / CONC=8` 是**给小批量用的默认值**。
1.5c 那轮我漏了这两行覆盖，跑出 3,652 条/分钟＝4.5 小时，窗口内跑不完、
60% 要进高峰全价（多 133 元）。改成 CONC=60 后 20,323 条/分钟，**提速 5.6 倍**。
fr 早在 8 月就把这件事写进了代码：「flash 并发限额 2,500，共用件默认的 8 是给小批量定的；
**并发只影响墙钟，一分钱不影响 token 成本**」——我拷了共用件没拷调用方。

例句比释义长（均 166 vs 88 字符）⇒ 批取 40（照 de/fr 的例句配置），并发 60。

═══ ⭐ 免费路径先走 ═══
**2,206 条古英语/方言引文，源头自带现代英语转写**
（`Let that choilt a-be, wilt ta.` → `Let that child alone, will you.`）。
那批把现代英语一并给模型，比让它啃 17 世纪拼写准。
⚠️ 有污染：`raven` 那条的 `english` 是书名 `Comus` 不是译文 ⇒ 只在明显是整句时用。

═══ 按**内容键**翻，不按行 ═══
例句 758,288 ／ 不同句子 702,147 —— 同一句给多个词当例句只翻一次，省 7.4%。
🔴 落盘键仍是**数据库主键**（`[[model-answer-files-key-by-id]]`），
   用 `example.id` 的最小值代表这一句，回填时按文本展开到所有同文本行。

    cd en && python3 -u pipeline/translate_examples.py --plan
    cd en && python3 -u pipeline/translate_examples.py --slice 7000   # 1% 切片实测单价
    cd en && python3 -u pipeline/translate_examples.py --run
    cd en && python3 -u pipeline/translate_examples.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import json
import random
import sqlite3

import dbtool
import paths
import slot_translate as st

# 见文件头「批与并发」那一段 —— **不覆盖就是 4.5 小时**
# 🔴🔴 **批越大，模型把 id 与内容配错行的概率越高。**
#    2026-09-09 外审照出：CHUNK=40 跑出来 134 片整批错开一位
#    （`fixes/fix_shifted_examples.py`）。重翻一律用小批。
st.CHUNK = int(__import__("os").environ.get("EX_CHUNK", "40"))
st.CONC = 60

OUT = paths.WORK / "examples"
ANS = OUT / "zh.jsonl"
SRC = "model:example"

RULES = """你在把英语词典的例句翻译成中文，给中文读者用。

输入是 JSON 数组，每项有：
  `id`   标识号，**不是序号**，原样回传
  `en`   英语例句原文
  `w`    这条例句是给哪个词做例句的
  `s`    🔴 **这条例句挂在该词的哪条义项下**（英文释义）——译文必须符合这条义项
  `sz`   同一条义项的中文释义（可能为空）
  `m`    可选。源头给的现代英语转写（原句是古英语或方言时才有）

规则：
1. 译**整句**，不是词典释义。句子该有的标点保留。
2. 🔴 **必须按 `s` 那条义项来译。**一词多义时不要挑最常见的那个意思。
   `sz` 是同一条义项的中文说法，用它确认自己没有取错义项；**但 `sz` 是释义不是译文**，
   不要把它抄进句子里。
3. 有 `m` 时以 `m` 为准理解原句（`en` 是古拼写），译文仍对应原句。
4. 专名（人名/地名/书名）用通行译名；没有通行译名的**保留原文**，不要生造音译。
5. 文献出处、页码、年份**不出现在译文里** —— 它们不是句子的一部分。
6. 公式、代号、外语引文原样保留。
7. **绝不编造**。看不懂或信息不足时，输出空字符串。
8. 只输出 JSON 数组，每项 {"id": <原样回传>, "h": "<`en` 的前 4 个词，原样抄>",
   "zh": "<中文>"}。不要解释。
   🔴 `h` 是用来核对你有没有把行配错的：它必须是**同一项** `en` 的开头四个词。"""


import re as _re
_LAT = _re.compile(r"[A-Za-z]")


def is_rendering(en, m):
    """源头的 `english` 字段是不是**这句话的现代英语转写**。

    🔴 **`len(m) > 20` 是形式代理，不是判据** —— 我第一版就写的它，实测放行了一堆：
        Hengist, King of Kent ／ W. Cunningham Mallory ／ Japan Meru Shinbunsha
        中国科学院兰州冰川冻土沙漠研究所沙漠研究室 ／ 一整段德语
    把书名当"这句话的意思"喂给模型，比不给更糟。

    ⭐ 按含义写：**转写是同一句话的现代说法 ⇒ 长度与原句相当**；
       书名/作者名/出版社比原句短得多。再加两条挡非英语的。
       实测 1,128 → 792 条，排掉的全是书名（`A Concise Geography of China`、
       `The Religion of a Doctor`、`Anarchy, a Journal of Order`）。
    ⚠️ 会误伤个别真转写（`ten of two → 1:50` 数字占比高）——
       但 `m` 只是提示，**误收一个书名比误漏一个提示贵**，判据往严里写。
    """
    if not m or " " not in m:
        return False
    if len(m) / max(len(en), 1) < 0.5:
        return False
    return sum(1 for x in m if _LAT.match(x)) / len(m) >= 0.5


def pool(con, skip_done=True):
    """→ [{id, en, w, s, sz, m?}]，**按文本去重**，id 取该文本下最小的 example.id。

    `skip_done=False` = 不减掉已落库的。A/B 要的是「同一批条目两种 payload」，
    而切片那 7,000 条已经 `--apply` 进库了 ⇒ 默认口径会把 A/B 取成空集。
    """
    q = con.execute
    have = ({i for (i,) in q("SELECT example_id FROM example_gloss WHERE lang='zh'")}
            if skip_done else set())
    best, meta = {}, {}
    # 🔴 `hidden=1` 的不翻 —— 那 6,402 条是维护提示与错放的关系数据
    #    （`fixes/hide_non_examples.py`），读者看不见，翻了纯属烧钱。
    # 🔴 构词式 `magnesium + -a → magnesia` **有意留在例句区**（前缀词条下有信息），
    #    但它没有可翻的东西：切片里 11 条"译文无汉字"全是它，模型原样回传是对的。
    #    ⇒ **"该展示"和"该翻译"是两个问题，分开判。**
    for eid, w, txt, sid, tr in q(
            "SELECT e.id, e.word, e.text, e.sense_id, e.src_translation FROM example e "
            "WHERE e.hidden = 0 AND NOT (e.text LIKE '%+%' AND e.text LIKE '%→%')"):
        if eid in have:
            continue
        cur = best.get(txt)
        if cur is None or eid < cur:
            best[txt] = eid
            meta[txt] = (w, sid, tr)
    gl = dict(q("SELECT sense_id, text FROM sense_gloss WHERE lang='en'"))
    # ⭐ **en 独有的一条便宜**：1.5c 已经把 99.76% 的义项翻成中文了。
    #    `bull` 第19义英文写 `Of large mammals, adult male`，模型仍把 `bull ape`
    #    译成「公牛」；中文义项「（大型哺乳动物的）雄性」几乎不可能被这么读。
    #    ⚠️ 值不值得加**不猜，跑 A/B**（`--ab N`）——多花的是入 token，约 +7%。
    zh = dict(q("SELECT sense_id, text FROM sense_gloss WHERE lang='zh'"))
    out = []
    for txt, eid in best.items():
        w, sid, tr = meta[txt]
        it = {"id": eid, "en": txt, "w": w, "s": (gl.get(sid) or "")[:160],
              "sz": (zh.get(sid) or "")[:60]}
        if is_rendering(txt, tr):
            it["m"] = tr
        out.append(it)
    out.sort(key=lambda x: x["id"])
    return out


def head4(s):
    """英文原文的前 4 个词，小写去标点 —— 与模型回传的 `h` 比对用。"""
    import re as _re
    w = _re.findall(r"[A-Za-z0-9\u00c0-\u024f']+", s or "")[:4]
    return " ".join(x.lower() for x in w)


def load_answers(con=None):
    """答案文件 → {example_id: 中文}。空串跳过（规则 7 让模型看不懂时输出空）。

    🔴🔴 **带 `h` 的答案要核对配对**（2026-09-09 加）。
       外审照出 134 片「整批错开一位」：`id` 发出去也回来了，
       但模型把 id 与内容配错了行 —— 六条落库闸**全绿**，
       因为错位不改变任何计数，只把内容挪了一格。
       ⇒ 让模型把 `en` 的前四个词抄回来，**对不上就当没答**，
         下一轮 `--run` 会重新问它。
       ⚠️ 老答案没有 `h`，只能靠 `fixes/fix_shifted_examples.py` 的长度比判据兜底；
         新答案一律核对。**主键保证认领得上，不保证配对是对的。**
    """
    ans, blank, bad = {}, 0, 0
    mis = 0
    head = {}
    if con is not None:
        head = {i: head4(t) for i, t in con.execute(
            "SELECT id, text FROM example WHERE hidden=0")}
    if not ANS.exists():
        return ans, blank, bad
    for ln in ANS.open(encoding="utf-8"):
        try:
            o = json.loads(ln)
        except Exception:
            bad += 1          # 末行截断等，`done_keys` 也是这么跳的
            continue
        if "id" not in o:
            bad += 1
            continue
        zh = (o.get("zh") or "").strip()
        h = o.get("h")
        if h is not None and head:
            want = head.get(o["id"])
            # 🔴 **按前缀比，不按等值比。**实测模型稳定抄回 **3 个词**而我要的是 4 个
            #    ⇒ 等值比会把 `god save the queen` vs `god save the` 判成错配，
            #    2,946 条**正确的译文**会被当垃圾扔掉重买。
            #    ⚠️ 判据要对「模型没完全照做格式」免疫 —— 它照做的是意图（抄开头），
            #      我不能因为它少抄一个词就否定整条。
            got = head4(h)
            if want and got and not (want.startswith(got) or got.startswith(want)):
                mis += 1
                continue                 # 真·配错行 ⇒ 当没答，下一轮重新问
        if zh:
            ans[o["id"]] = zh
        else:
            blank += 1
    return ans, blank, bad, mis


def expand(con, ans):
    """答案按 `example.id` 领取 → 展开到**所有同文本**的例句行。

    🔴 池子是按文本去重的（`pool()` 用该文本下最小的 id 代表它），
       所以落库时必须展开回去，否则 5.6 万条同文本的例句会一条中文都没有。
    🔴🔴 **模型编出来的 id 一条都不许落库** —— 1.5c 那次烧掉 175 万 token 的
       正是「编中了主键就把中文贴到别的义项上」。这里拿池子当白名单，
       不在池子里的 id 直接丢并计数（计数 > 0 就说明应答认领出了问题，闸会红）。
    """
    # 🔴🔴 **落库也要过 `hidden`** —— 只在 `pool()` 里挡住是不够的：
    #    答案文件里还留着切片时翻过的隐藏行，下一次 `--apply` 会把中文原样写回去，
    #    把 `fixes/hide_non_examples.py` 那条"藏起来的例句不许有中文"的不变量撞红。
    #    ⇒ **同一条规则要在写入侧和读取侧各拦一次**（[[it-regression-gate]]）。
    txt_of, ids_of, hid = {}, {}, set()
    for eid, txt, h in con.execute("SELECT id, text, hidden FROM example"):
        if h:
            hid.add(eid)
            continue
        txt_of[eid] = txt
        ids_of.setdefault(txt, []).append(eid)
    # 🔴🔴 **同一句英文只许有一个答案。**
    #    `fixes/split_quote_ref.py` 把出处从正文里削掉之后，原本不同的两条例句
    #    正文变成了同一句 ⇒ 答案文件里就有了两条指向同一文本的答案，
    #    各自展开到同一批行 ⇒ `UNIQUE(example_id, lang)` 当场炸。
    #    ⚠️ 这是**改了上游文本、下游按文本分组**的必然后果，不是答案文件坏了。
    #    ⇒ 按文本收敛，取 id 最小的那条（确定性，重跑结果一样）。
    best = {}
    for eid in sorted(ans):
        txt = txt_of.get(eid)
        if txt is not None:
            best.setdefault(txt, eid)
    rows, alien, hidden_n, covered = [], 0, 0, set()
    for eid, zh in ans.items():
        # 🔴 **「被藏了」与「编造的主键」是两件事，不许混成一个数。**
        #    混起来这个闸就报不出真正危险的那件（模型瞎编 id 把中文贴到别的条目上），
        #    因为它会被一堆良性的隐藏行淹掉 —— 判据比它要描述的东西宽了。
        if eid in hid:
            hidden_n += 1
            continue
        txt = txt_of.get(eid)
        if txt is None:
            alien += 1
            continue
        if best[txt] != eid:
            continue                 # 同一句英文的重复答案，见上面那段
        covered.add(txt)
        for e in ids_of[txt]:
            rows.append((e, zh))
    return rows, alien, hidden_n, len(covered)


def gates(con, rows, before, n_txt):
    q = lambda s, *a: con.execute(s, a).fetchone()[0]
    checks = [
        ("落库行数与算出来的一致",
         q("SELECT COUNT(*) FROM example_gloss WHERE src=?", SRC), len(rows)),
        ("🔴 没有空串中文",
         q("SELECT COUNT(*) FROM example_gloss WHERE src=? AND TRIM(text)=''", SRC), 0),
        # 🔴🔴 同一句英文在全库只能有一个中文 —— 展开写错就会在这里炸
        ("🔴 同一句英文只有一个中文",
         q("""SELECT COUNT(*) FROM (SELECT e.text FROM example_gloss g
              JOIN example e ON e.id=g.example_id WHERE g.src=?
              GROUP BY e.text HAVING COUNT(DISTINCT g.text)>1)""", SRC), 0),
        # 🔴🔴 期望值原来写的是 `len({中文串})` —— **拿中文串去重代理"覆盖了几句英文"**，
        #    落库当场报红 1,051 条。回源一读，数据是对的：
        #      `Shut your face!` / `Shut your beak!` / `Shut your mug!` → 都该是「闭上你的嘴！」
        #    **不同英文译成同一句中文是正常的**，一一对应是我凭空加的假设。
        #    ⇒ 期望值改成 `expand()` 真正覆盖到的**不同英文句数**。
        ("🔴 中文条数与不同英文句数对得上",
         q("""SELECT COUNT(DISTINCT e.text) FROM example_gloss g
              JOIN example e ON e.id=g.example_id WHERE g.src=?""", SRC), n_txt),
        # 🔴 别的来源一行都不许被动到（`example_gloss` 目前只有这一个来源，
        #    但闸要问"有没有被动"，不是"现在有几行"）
        ("🔴 别的来源没被动过",
         q("SELECT COUNT(*) FROM example_gloss WHERE src IS NOT ? OR src IS NULL", SRC),
         before["other"]),
        # 🔴🔴 应答里的 id 必须真是 `example.id` —— 1.5c 那次烧掉 175 万 token 的
        #    正是模型瞎编主键、编中了就把中文贴到别的条目上
        ("🔴 应答 id 全是真主键", before["alien"], 0),
    ]
    bad = 0
    for name, got, want in checks:
        ok = got == want
        bad += not ok
        print("   %s %-34s %s / %s" % ("✅" if ok else "🔴", name,
                                       format(got, ","), format(want, ",")))
    return bad


def do_apply(run):
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    ans, blank, bad_ln, mis = load_answers(con)
    # 🔴 白名单是**全部 `example.id`**，不是 `pool()`。
    #    `pool()` 会把「已经有中文的」减掉 ⇒ 拿它当白名单，第二次 --apply 时
    #    每一条答案都会被判成"池子外"，闸红、数据被清空重写成 0 行。
    #    **幂等性要在写之前想清楚**（`[[prefer-reversible-designs]]`）。
    rows, alien, hidden_n, n_txt = expand(con, ans)
    tot, = con.execute("SELECT COUNT(*) FROM example").fetchone()
    now, = con.execute("SELECT COUNT(*) FROM example_gloss WHERE src=?", (SRC,)).fetchone()
    other, = con.execute(
        "SELECT COUNT(*) FROM example_gloss WHERE src IS NOT ? OR src IS NULL",
        (SRC,)).fetchone()
    con.close()
    print("═══ 阶段 5e 落库 ═══")
    print("   答案 %s 条（空串跳过 %s ／ 坏行 %s ／ 例句已藏 %s ／ 🔴 不是真主键 %s "
          "／ 🔴🔴 配对核不上 %s）"
          % (format(len(ans), ","), format(blank, ","), format(bad_ln, ","),
             format(hidden_n, ","), format(alien, ","), format(mis, ",")))
    print("   展开到例句行 **%s** ／ 全库例句 %s ＝ **%.2f%%**"
          % (format(len(rows), ","), format(tot, ","), 100 * len(rows) / max(tot, 1)))
    if not run:
        print("\n(干跑。加 --run 才写库)")
        return 0
    with dbtool.session("keep-v3-example-gloss",
                        expect={"#example_gloss": len(rows) - now}) as s:
        s.execute("DELETE FROM example_gloss WHERE src=?", (SRC,))
        s.executemany("INSERT INTO example_gloss (example_id,lang,text,src) "
                      "VALUES (?,'zh',?,?)", [(e, z, SRC) for e, z in rows])
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    print("\n═══ 闸② ═══")
    bad = gates(con, rows, {"other": other, "alien": alien}, n_txt)
    con.close()
    return 1 if bad else 0


def do_ab(n):
    """A/B：在**最难的一格**上加 `sz` 重跑，与已有答案并排。

    🔴 判据要挑**能把两组分开**的那一格 —— 单义词怎么译都不会取错义项，
       拿全池子做 A/B 会被 78% 的简单条目稀释成"看不出差别"。
       ⇒ 只取多义词（≥6 义）的**非首义**，那正是 `bull` 栽的地方。
    ⚠️ 这一轮**只买对照组**：B 组（无 sz）就是切片已经买过的答案，一分钱不再花。
    """
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = con.execute
    old = {o["id"]: o["zh"] for o in
           (json.loads(l) for l in (OUT / "slice.jsonl").open(encoding="utf-8"))
           if o.get("zh", "").strip()}
    hard = []
    for eid, sid in q("SELECT id, sense_id FROM example WHERE sense_id IS NOT NULL"):
        if eid in old:
            hard.append((eid, sid))
    rk = dict(q("SELECT id, rank FROM sense"))
    wd = dict(q("SELECT id, word_id FROM sense"))
    cnt = {}
    for wid_, c in q("SELECT word_id, COUNT(*) FROM sense GROUP BY word_id"):
        cnt[wid_] = c
    hard = [e for e, s in hard if rk.get(s, 0) > 0 and cnt.get(wd.get(s), 0) >= 6]
    con.close()
    random.Random(20260908).shuffle(hard)
    pick = set(hard[:n])
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    items = [i for i in pool(con, skip_done=False) if i["id"] in pick]
    con.close()
    print("═══ A/B：最难的一格（多义词≥6义 的非首义）%d 条 ═══" % len(items))
    print("   A 组＝带中文义项 `sz`（本轮买）／ B 组＝切片已有答案（不再花钱）")
    st.announce_window()
    st.translate(items, RULES, OUT / "ab.jsonl",
                 fields=("id", "en", "w", "s", "sz", "m"), keep=("id",))
    new = {o["id"]: o["zh"] for o in
           (json.loads(l) for l in (OUT / "ab.jsonl").open(encoding="utf-8"))
           if o.get("zh", "").strip()}
    diff = [i for i in new if i in old and new[i].strip() != old[i].strip()]
    print("\n   两组不同的 %d / %d ＝ %.1f%%"
          % (len(diff), len(new), 100 * len(diff) / max(len(new), 1)))
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    meta = {}
    for k in range(0, len(diff), 900):
        ck = diff[k:k + 900]
        for eid, w, txt, sid in con.execute(
                "SELECT id, word, text, sense_id FROM example WHERE id IN (%s)"
                % ",".join("?" * len(ck)), ck):
            meta[eid] = (w, txt, sid)
    gl = dict(con.execute("SELECT sense_id, text FROM sense_gloss WHERE lang='zh'"))
    con.close()
    print("\n   🔬 并排读（人判，机械判不了）：")
    for i in diff[:25]:
        w, txt, sid = meta[i]
        print("\n   ── %s ｜ 义项(中): %s" % (w, (gl.get(sid) or "")[:60]))
        print("      英: %s" % txt[:120])
        print("      B : %s" % old[i][:100])
        print("      A : %s" % new[i][:100])
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--slice", type=int, default=0)
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--ab", type=int, default=0,
                    help="在**最难的一格**（多义词非首义）上跑 N 条带 sz 的，与已有答案并排比")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--run-apply", action="store_true",
                    help="与 --apply 连用才真写库")
    a = ap.parse_args()
    if a.apply:
        return do_apply(a.run_apply)
    if a.ab:
        return do_ab(a.ab)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    items = pool(con)
    tot, = con.execute("SELECT COUNT(*) FROM example").fetchone()
    con.close()
    ch = sum(len(i["en"]) for i in items)
    with_m = sum(1 for i in items if "m" in i)
    print("═══ 阶段 5e 池子 ═══")
    print("   例句 %s ／ **不同句子 %s**（去重省 %.1f%%）"
          % (format(tot, ","), format(len(items), ","), 100 * (1 - len(items) / tot)))
    print("   总字符 %.1fM ／ 平均 %.0f" % (ch / 1e6, ch / max(len(items), 1)))
    print("   ⭐ 带现代英语转写 %s 条" % format(with_m, ","))
    print("   带义项上下文 %s = %.2f%%"
          % (format(sum(1 for i in items if i["s"]), ","),
             100 * sum(1 for i in items if i["s"]) / max(len(items), 1)))
    if a.slice:
        random.Random(20260908).shuffle(items)
        items = items[:a.slice]
        print("\n   🔬 切片 %s 条（1%% 实测单价）" % format(len(items), ","))
    if not (a.run or a.slice):
        print("\n(干跑。--slice N 先实测单价／--run 全量／--apply 落库)")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    st.announce_window()
    out = OUT / ("slice.jsonl" if a.slice else "zh.jsonl")
    # ⚠️ **不发 `sz`** —— A/B 跑过（§12.2），带中文义项净值 ≈ 0 而多花 +7%。
    #    只有 `do_ab` 那条路径发它。2026-09-09 加配对核对时我一度顺手加了进来，
    #    那等于**悄悄推翻一个用数据做过的决定**，已撤回。
    s = st.translate(items, RULES, out, fields=("id", "en", "w", "s", "m"),
                     keep=("id",), echo_field="h")
    n = len(items)
    if s.get("tok"):
        print("\n═══ 单价实测 ═══")
        print("   %s 条 ｜ token %s（入 %s ／ 出 %s）｜ **%.1f token/条**"
              % (format(n, ","), format(s["tok"], ","), format(s.get("tok_in", 0), ","),
                 format(s.get("tok_out", 0), ","), s["tok"] / n))
        usd = (s.get("tok_in", 0) * 0.44 + s.get("tok_out", 0) * 1.32) / 1e6
        print("   本轮 ≈%.2f 元（半价）⇒ 全量 %s 条外推 **≈%.0f 元**"
              % (usd * 7.2 / 2, format(len(pool(sqlite3.connect(
                  "file:%s?mode=ro" % paths.DB, uri=True))), ","),
                 usd * 7.2 / 2 * 702147 / n))
    return 0


if __name__ == "__main__":
    _sys.exit(main())
