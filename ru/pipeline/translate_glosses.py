#!/usr/bin/env python3
"""阶段 5b：把缺中文的可出版义项译成中文。ru，2026-10-23（拷 vi 的骨架，判据与提示按俄语重写）。

═══ 🔴 这一步花钱，**报价与开跑分两次** ═══
    python3 -u ru/pipeline/translate_glosses.py --slice 0.01      # ① 实测单价（先跑这个）
    （拿着实测单价报价 ⇒ 用户拍板范围与预算）
    python3 -u ru/pipeline/translate_glosses.py --scope S2 --lang ru   # ② 全量（拍板之后）
    python3 -u ru/pipeline/translate_glosses.py --load --apply          # ③ 回收进库

═══ 盘子（阶段 5a 落库后，`probe_sense_layer.py` §E）═══
    S1 两组都翻              396,308 条 ／ 16,829,068 字符
    S2 每词一组（ru 优先）    374,186 条 ／ 16,081,879 字符
    S3 每词一组（en 优先）    369,430 条 ／ 15,188,844 字符
⇒ 钱几乎全落在 ru 版那 49 万条俄语单语释义上（en 版 82% 是指针，真释义只有 8.8 万）。
🔴 **估算一律不作数**（vi 5b 旧报价复现不出来、实测是 3.2 倍）⇒ 切片实测单价再报。

═══ 走过的免费路径（`[[prove-free-path-before-quoting]]`）═══
 ① zh 两片 —— **已榨干**：可出版 122,491 条，real 桶抽读 60/60 含真释义，全部出版；
    mixed 5,970 条（R3 待切）／meta 6,441 条按定义不是释义。
 ② 同词形别的义项的中文 —— **不能挪用**（es 实测 12.4% 义项错配，`PLAYBOOK` 5.6）。
 ③ fr/vi/pl 版的释义 —— 三语方针有意不收（它们给俄语词的是**翻译**不是定义）。
    ⚠️ 26,046 个空白页词元里有 10,333 个只有这三版的证据 —— 要不要破例**是用户的决定**。

═══ 🔴 控制组：每一个输出字段、每一种坏法各一条 ═══
  · **错位**（答案挂到别的义项上）⇒ 每批注入定题，对不上就是 id 对齐坏了
  · **静默丢批** ⇒ 逐 id 点名
  · **答非所问** ⇒ 形状检查，**每条判据对比原文**（ko 那次只看译文、把合法输出报成缺陷）
答案文件**按义项主键**存（`[[model-answer-files-key-by-id]]`）。
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

SYS = """你是俄汉词典的释义编辑。把给定的俄语词的词典释义译成中文。

输入是一个 JSON 对象：键是义项编号，值含 w（俄语词头）、p（词性）、g（原释义，俄语或英语）。
输出**同样的键**，值是 {"zh": "中文释义"}。键一个不许少、不许多、不许改。

规矩：
1. 译成**词典释义**的体例：名词用名词、动词用动词短语、形容词用「…的」，不要译成句子。
   俄语版的释义多是整句式定义，译成简洁的中文释义，不要照搬句式。
2. 原释义并列了几个对译的，中文也并列，用「，」分隔，顺序不变；译完若有完全相同的只留一个。
3. **只译释义本身**。不要输出俄语词头、不要加音标、不要加「意思是」这类引导语、不要加例句。
4. 原释义开头的**语体/领域缩写**译成中文标签，放在最前面，用〈〉括起来，**必须用下表的译法**
   （下表覆盖待译释义里 93% 的缩写；表外认不出的缩写**原样保留**，不要猜）：
     разг.〈口〉 устар.〈旧〉 прост.〈俗〉 сниж.〈俗〉 перен.〈转〉 истор.〈史〉 жарг.〈行话〉
     мед.〈医〉 минер.〈矿〉 рег.〈方〉 диал.〈方〉 лингв.〈语〉 филол.〈语文〉 спец.〈专〉 книжн.〈书〉
     обсц.〈粗〉 вульг.〈粗〉 груб.〈粗〉 неол.〈新〉 геогр.〈地理〉 геол.〈地质〉 ботан.〈植〉 зоол.〈动〉
     биол.〈生〉 биохим.〈生化〉 анат.〈解剖〉 физиол.〈生理〉 хим.〈化〉 физ.〈物〉 матем.〈数〉
     астрон.〈天文〉 воен.〈军〉 морск.〈海〉 полит.〈政〉 публиц.〈政论〉 экон.〈经〉 фин.〈金融〉
     юр.〈法〉 крим.〈犯罪〉 религ.〈宗〉 церк.〈宗〉 мифол.〈神话〉 филос.〈哲〉 психол.〈心理〉
     психиатр.〈精神病〉 муз.〈乐〉 спорт.〈体〉 кулин.〈烹〉 карт.〈牌戏〉 техн.〈技〉 комп.〈计〉
     информ.〈计〉 интернет.〈网〉 проф.〈行业〉 мол.〈青年〉 советск.〈苏〉 поэт.〈诗〉
     неодобр.〈贬〉 уничиж.〈贬〉 пренебр.〈蔑〉 презр.〈蔑〉 шутл.〈谑〉 ирон.〈讽〉 ласк.〈爱〉
     экспр.〈表情〉 эвф.〈婉〉 бран.〈骂〉 редк.〈罕〉 собир.〈集合〉 мн.〈复〉 однокр.〈一次体〉
     субстантивир.〈名词化〉
   几个缩写开头的是**句式不是标签**，按第 5 条译：страд. к X／женск. к X／сокр. от X／
   сравн. к X／уменьш. к X／дееприч.／прич.。
5. 俄语版的**固定句式**，译法必须前后一致：
     связанный, соотносящийся по значению с существительным X → 与名词 X 相关的
     свойственный, характерный для X                          → X 所特有的
     действие по значению гл. X                               → X 这一动作
     состояние по значению гл. X                              → X 的状态
     свойство по значению прил. X                             → X 的性质
     уменьш.-ласк. к X ／ уменьш. к X                          → X 的指小（表爱）形式
     то же, что X                                             → 同 X
     женск. к X                                               → X 的阴性形式
     страд. к X                                               → X 的被动态
     сокр. от X                                               → X 的缩写
     сравн. ст. к X ／ сравн. к X                             → X 的比较级
   被指称的词形 X **原样保留俄文，不翻译**。
6. 英语释义里的元描述同样处理：synonym of X → X 的同义词；abbreviation of X → X 的缩写；
   a surname → 姓氏；a male given name → 男性名。X 原样保留。
7. 学名（拉丁双名法）、化学式、单位符号**原样保留**。括号里的补充说明保留，用中文括号。
8. 吃不准的直译，**不要编造**，不要为了通顺增添原文没有的信息。
9. w 和 p 只是**帮你消歧**的，不许出现在输出里。"""

# 🔴 定题：答案是**确定**的，只用来验 id 对齐没坏（不是考翻得好不好）。
PROBE = {
    # 🔴 第一版 `want` 写的是「水」—— 而规则 3/9 明令「只译释义、不许输出词头」，模型答
    #    「透明的无色液体」**恰恰是对的**。题照抄了 vi 的形状（vi 给的是英文 `water`）而答案没换
    #    ⇒ **出题错了，不是模型错了**。定题的答案只能从**释义**里推，不能从词头里推。
    "__c1": {"w": "вода", "p": "noun", "g": "прозрачная бесцветная жидкость", "want": ("液体",)},
    "__c2": {"w": "мать", "p": "noun", "g": "женщина по отношению к своим детям", "want": ("母", "妈")},
    "__c3": {"w": "один", "p": "num", "g": "число 1", "want": ("一", "1")},
    "__c4": {"w": "собака", "p": "noun", "g": "dog", "want": ("狗", "犬")},
}

SCOPES = ("S1", "S2", "S3")


def gap_rows(con, lang, scope="S1"):
    """缺中文、且有 `lang` 释义的**可出版**义项。口径只写一份。

    S1 两组都翻；S2 每词一组 ru 优先（en 只翻「这个词没有 ru 义项」的）；
    S3 每词一组 en 优先（ru 只翻「这个词没有 en 义项」的）。
    🔴 「缺中文」按**词形**判：这个词形已有**可印的** zh 义项就不翻（5a 的 zh 不跨版合并，
       但读者已经能在这一页上看见中文 ⇒ 再买一份就是重复花钱）。与探针 §E 同口径。
    🔴 `s.hidden=0`：隐藏的不花钱译（ko 的 6d 把钱花在了不出版的行上）。
    """
    other = {"ru": "en", "en": "ru"}[lang]
    skip_other = (scope == "S2" and lang == "en") or (scope == "S3" and lang == "ru")
    sql = """
        SELECT s.id, d.word, COALESCE(e.pos, '?'), g.text
          FROM sense s
          JOIN dict d  ON d.id = s.word_id
     LEFT JOIN entry e ON e.id = s.entry_id
          JOIN sense_gloss g ON g.sense_id = s.id AND g.lang = ?
         WHERE s.hidden = 0
           AND NOT EXISTS (SELECT 1 FROM sense s2 JOIN sense_gloss g2 ON g2.sense_id = s2.id
                            WHERE s2.word_id = s.word_id AND s2.hidden = 0 AND g2.lang = 'zh')"""
    if skip_other:
        sql += """
           AND NOT EXISTS (SELECT 1 FROM sense s3 JOIN sense_gloss g3 ON g3.sense_id = s3.id
                            WHERE s3.word_id = s.word_id AND s3.hidden = 0 AND g3.lang = '%s')""" % other
    sql += " ORDER BY s.id"
    return con.execute(sql, (lang,)).fetchall()


def pick_slice(rows, frac):
    """按义项 id 的稳定哈希抽（不是 `rows[::n]` —— 按顺序抽会抽出一整片同类）。"""
    k = int(frac * 0xFFFF)
    return [r for r in rows if int(hashlib.md5(str(r[0]).encode()).hexdigest()[:4], 16) < k]


def already(path):
    out = set()
    if path.exists():
        for line in path.open(encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:                        # noqa: BLE001
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
        ck = list(PROBE)[i // per % len(PROBE)]
        pay[ck] = {x: PROBE[ck][x] for x in ("w", "p", "g")}
        m.append((ck, ck))
        batches.append(pay)
        meta.append(m)
    return batches, meta


_CYR_WORD = re.compile(r"[А-Яа-яЁё][А-Яа-яЁё\-́]+")


def audit(path, rows, ntok, peak):
    """控制组：错位／静默丢批／答非所问 ＋ 单价。"""
    got = {}
    for line in path.open(encoding="utf-8"):
        try:
            d = json.loads(line)
        except Exception:                            # noqa: BLE001
            continue
        got[d["id"]] = d.get("zh")
    want = {sid for sid, *_ in rows}
    print("\n═══ 控制组 ═══")
    ctl_bad = []
    for k, v in PROBE.items():
        ans = got.get(k)
        if ans is None:
            ctl_bad.append((k, "没回来"))
        elif not any(x in ans for x in v["want"]):
            ctl_bad.append((k, "答成了 %r（该含 %s）" % (ans, "/".join(v["want"]))))
    print("   %s 定题对齐   %d/%d" % ("✅" if not ctl_bad else "🔴", len(PROBE) - len(ctl_bad), len(PROBE)))
    for k, why in ctl_bad:
        print("      🔴 %s %s" % (k, why))
    miss = want - set(got)
    print("   %s 逐 id 点名  回来 %s / 要 %s（丢 %s）"
          % ("✅" if not miss else "🔴", F(len(want & set(got))), F(len(want)), F(len(miss))))
    bad, samples = collections.Counter(), collections.defaultdict(list)
    for sid, w, pos, g in rows:
        t = got.get(sid)
        if t is None:
            continue
        why = None
        if not (t or "").strip():
            why = "空"
        elif not re.search(r"[㐀-鿿]", t):
            why = "没有一个汉字（多半没翻译）"
        elif w and w.lower() in t.lower() and w.lower() not in g.lower():
            why = "把俄语词头写进了释义（原文没有）"
        else:
            # 词干一级：译文里的俄语词，原文（或词头）里也得有**同词干**的 —— 没有就是编的。
            # 🔴 第一版按整词比，1% 切片报 10 条、大多是**对的**：句式「свойственный бекеше →
            #    бекеша 所特有的」要求把 X 还原成原形（与格→主格）⇒ 改按前 5 个字母比
            #    （vi 那条「判据收窄成词一级」的同形）。
            src = (g + " " + (w or "")).lower().replace("\u0301", "")
            ext = sorted(x for x in {y.lower().replace("\u0301", "") for y in _CYR_WORD.findall(t)}
                         if x[:5] not in src)
            if ext:
                why = "🔴 译文里的俄语词原文没有（疑似幻觉）"
        if why:
            bad[why] += 1
            if len(samples[why]) < 4:
                samples[why].append((w, g[:40], t[:40]))
    n = len(want & set(got))
    print("   %s 形状        坏 %d / %s" % ("✅" if not bad else "⚠️", sum(bad.values()), F(n)))
    for k, v in bad.most_common():
        print("      ⚠️ %-28s %d" % (k, v))
        for w, g, t in samples[k]:
            print("           %-14s %-40s → %s" % (w, g, t))
    per = ntok / max(n, 1) if ntok else 0
    if ntok:
        print("\n═══ 单价（%s）═══" % ("🔴 高峰全价" if peak else "✅ 空闲半价"))
        print("   总 token %s ／ 成功 %s 条 ⇒ **每条 %.1f token**" % (F(ntok), F(n), per))
    print("\n■ 抽样（人眼看 —— 形状检查看不出「译错了」）")
    for sid, w, pos, g in rows[:8] + rows[len(rows) // 2:len(rows) // 2 + 8]:
        if sid in got:
            print("   %-16s %-6s %-46s → %s" % (w, pos, g[:46], got[sid]))
    return per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=["ru", "en"], default="")
    ap.add_argument("--scope", choices=SCOPES, default="S1")
    ap.add_argument("--slice", type=float, default=0.0)
    ap.add_argument("--conc", type=int, default=60,
                    help="从 60 起（`[[batch-concurrency-dont-be-timid]]`：跑慢了会跨出半价窗口）")
    ap.add_argument("--tag", default="")
    ap.add_argument("--count", action="store_true", help="只数各范围的盘子，不花钱")
    ap.add_argument("--allow-peak", action="store_true", help="允许在高峰全价时段跑（默认拒跑）")
    ap.add_argument("--exception", action="store_true",
                    help="破例：空白页词元的 fr/vi/pl 证据 → 中文（用户 2026-10-23 拍板）")
    # 🔴🔴 `[[retry-must-converge-or-drop-loud]]`：temperature=0 下模型**确定性地**漏同一批里的同一个键，
    #    原样重发永远收敛不了（vi 5b 实测）。⇒ 只取还缺的 id，批长**对半切**（20→10→5→…→1），
    #    到 1 还缺就**大声放弃并把 id 打出来**。拷 vi 模板时**漏了这一段**，全量跑完丢 79 条才补。
    ap.add_argument("--retry-missing", action="store_true")
    ap.add_argument("--load", action="store_true", help="把答案文件写进库（默认干跑）")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--prune-xl", action="store_true", help="撤掉过不了 sense_hidden_why 的破例义项")
    a = ap.parse_args()

    if a.prune_xl:
        prune_xl(dry=not a.apply)
        return 0
    if a.load:
        load(dry=not a.apply)
        return 0
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    if a.exception:
        rows = [r[:4] for r in xl_rows(con)]
        con.close()
        peak = ds_batch.announce_window()
        if peak and not a.allow_peak:
            raise SystemExit("🔴 高峰全价时段不开跑")
        path = OUT / "xl.jsonl"
        done = already(path)
        todo = [r for r in rows if r[0] not in done]
        batches, meta = build(todo)
        print("\n■ 破例 fr/vi/pl → zh：%s 条（已有 %s）%s 批" % (F(len(rows)), F(len(rows) - len(todo)), F(len(batches))))
        if todo:
            ntok = asyncio.run(ds_batch.run(SYS_XL, batches, meta, path, mode="flash", conc=a.conc, every=5))
            tp = path.with_suffix(".tokens.json")
            prev = json.loads(tp.read_text()) if tp.exists() else {"tok": 0, "runs": []}
            prev["tok"] += ntok
            prev["runs"].append({"tok": ntok, "n": len(todo), "peak": peak})
            tp.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
            audit(path, rows, prev["tok"], peak)
        return 0
    if a.count:
        for sc in SCOPES:
            tot = {lg: gap_rows(con, lg, sc) for lg in ("ru", "en")}
            print("   %s  ru %s 条/%s 字 ／ en %s 条/%s 字" % (
                sc, F(len(tot["ru"])), F(sum(len(r[3]) for r in tot["ru"])),
                F(len(tot["en"])), F(sum(len(r[3]) for r in tot["en"]))))
        return 0

    peak = ds_batch.announce_window()          # 🔴 无条件播报价格档位
    if peak and not a.allow_peak:
        raise SystemExit("🔴 高峰全价时段不开跑（切片也一样，`[[deepseek-pricing-window]]`）；"
                         "确需全价跑加 --allow-peak")
    OUT.mkdir(parents=True, exist_ok=True)
    report = {}
    for lang in ([a.lang] if a.lang else ["ru", "en"]):
        rows = gap_rows(con, lang, a.scope)
        full = len(rows)
        if a.slice:
            rows = pick_slice(rows, a.slice)
        tag = a.tag or "%s-%s%s" % (lang, a.scope, "-slice" if a.slice else "")
        path = OUT / ("%s.jsonl" % tag)
        # 🔴 **分批之前先剔掉已有答案的 id。** `ds_batch.run` 的续传是按**整批**判的（一批里的 id
        #    全有答案才算完成），全量重新分批后，切片那 3,316 条零散落在各批里 ⇒ 没有一批是完整的
        #    ⇒ 会被**重译一遍**（2026-10-23 第一次开全量时看见「已完成 0 批」才发现）。
        if a.retry_missing:
            per = PER_BATCH // 2
            while per >= 1:
                # 🔴 `already()` 读整份答案文件 —— 第一版写在推导式里，**每一行读一遍 30 万行**
                #    （79 条重试 10 分钟没跑完；今天第二次同一个错，第一次是 `set(flip)` 在循环里）
                got = already(path)
                left = [r for r in rows if r[0] not in got]
                if not left:
                    print("■ %s：一条都不缺 ✓" % lang)
                    break
                b2, m2 = build(left, per)
                print("■ %s：还缺 %s 条 ⇒ 批长 %d，%s 批" % (lang, F(len(left)), per, F(len(b2))))
                ntok = asyncio.run(ds_batch.run(SYS, b2, m2, path, mode="flash",
                                                conc=min(a.conc, len(b2)), every=5))
                tp = path.with_suffix(".tokens.json")
                prev = json.loads(tp.read_text()) if tp.exists() else {"tok": 0, "runs": []}
                prev["tok"] += ntok
                prev["runs"].append({"tok": ntok, "retry_missing": per, "peak": peak})
                tp.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
                if per == 1:
                    got = already(path)
                    still = [r for r in rows if r[0] not in got]
                    if still:
                        print("🔴🔴 批长已切到 1 仍拿不到 %d 条 —— **放弃，不静默丢**：" % len(still))
                        for sid, w, pos, g in still:
                            print("     id=%-8d %-20s %s" % (sid, w, g[:60]))
                    break
                per //= 2
            continue
        done = already(path)
        todo_rows = [r for r in rows if r[0] not in done]
        if done:
            print("■ 答案文件里已有 %s 条（同一版 prompt）⇒ 不重译" % F(len(rows) - len(todo_rows)))
        batches, meta = build(todo_rows)
        print("\n■ %s → zh（%s）：%s 条（全量 %s）%s 批" % (lang, a.scope, F(len(rows)), F(full), F(len(batches))))
        if not rows:
            continue
        ntok = asyncio.run(ds_batch.run(SYS, batches, meta, path, mode="flash", conc=a.conc, every=5))
        tp = path.with_suffix(".tokens.json")
        prev = json.loads(tp.read_text()) if tp.exists() else {"tok": 0, "runs": []}
        prev["tok"] += ntok
        prev["runs"].append({"tok": ntok, "n": len(rows), "full": full, "peak": peak})
        tp.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
        report[lang] = audit(path, rows, prev["tok"], peak)
    con.close()
    if a.slice and report:
        print("\n═══ 折算到三种范围（**按实测单价 × 条数**，token 数；元价见报价）═══")
        con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
        for sc in SCOPES:
            tok = sum(report.get(lg, 0) * len(gap_rows(con, lg, sc)) for lg in ("ru", "en"))
            print("   %s  ≈ %s token" % (sc, F(int(tok))))
        con.close()
    return 0



# ══════════════════════════════════════════════════════════════════
# 破例：空白页词元的 fr/vi/pl 证据 → 中文（用户 2026-10-23 拍板）
# ══════════════════════════════════════════════════════════════════
# 🔴 三语方针**在原文这一层不破**：fr/vi/pl 原文仍然只在证据层、不出版；出版的只有模型中文。
#    破例的范围由 `xl_rows` 的 WHERE 定死：**词元**、**一条可印义项都没有**、证据**不是指针**。
#    答案文件按 **`sense_src.id`** 存（这些证据还没有 `sense` 行），文件名带 `xl-` 前缀与主体分开。
SYS_XL = SYS.replace("g（原释义，俄语或英语）", "g（原释义，法语、越南语或波兰语 —— 多为对译词）")


def xl_rows(con):
    """🔴 必须过 `criteria.sense_hidden_why`（与收割器同一道判据）。第一版没过 ⇒ 55 条证据原文
    **只是一个冒号 `:`** 也被送去翻译，模型要么答「（无释义）」、要么**照词头猜**
    （`змейковый → 蛇的`）—— 后者正是禁止的盲推（`[[blind-gloss-inference-ceiling]]`：24–25% 错）。
    是义项闸 E4 当场拦下的（它用同一个判据从证据原文重算）。"""
    import sys as __s
    __s.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
    from pipeline import criteria as _C
    return [r for r in _xl_rows_raw(con) if not _C.sense_hidden_why(r[4], r[3])]


def _xl_rows_raw(con):
    return con.execute("""
        SELECT x.id, d.word, COALESCE(e.pos, '?'), x.text, x.lang
          FROM sense_src x
          JOIN dict d ON d.id = x.word_id
     LEFT JOIN entry e ON e.id = x.entry_id
         WHERE d.is_lemma = 1 AND x.lang IN ('fr', 'vi', 'pl')
           AND x.pointer_target IS NULL AND x.sense_id IS NULL
           AND NOT EXISTS (SELECT 1 FROM sense s WHERE s.word_id = d.id AND s.hidden = 0)
         ORDER BY x.id""").fetchall()


# ══════════════════════════════════════════════════════════════════
# 回收：答案文件 → 库
# ══════════════════════════════════════════════════════════════════
SRC_MODEL = "model:deepseek-v4-flash"
# 标签译法的确定性归一 —— prompt 管不住风格一致性（vi 的引号那一课）。只收切片里实测见过的变体。
_LABEL_NORM = {"〈语言〉": "〈语〉", "〈语言学〉": "〈语〉"}


def normalize_zh(t):
    t = (t or "").strip()
    for a, b in _LABEL_NORM.items():
        t = t.replace(a, b)
    return t


def _answers(path):
    out = {}
    if path.exists():
        for line in path.open(encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:                        # noqa: BLE001
                continue
            if isinstance(d.get("id"), int):
                out.setdefault(d["id"], d.get("zh"))
    return out


def prune_xl(dry=True):
    """撤掉**不该建**的破例义项：证据原文过不了 `sense_hidden_why`（2026-10-23 的 55 条 `:`）。
    三步一起做：删 gloss → 证据 `sense_id` 置回 NULL → 删 sense。**undo 需要的 id 在 do 之前取齐**（vi 那一课）。"""
    import dbtool
    import sys as __s
    __s.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
    from pipeline import criteria as _C
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    bad = [(sid, xid) for sid, xid, lang, text in con.execute(
        "SELECT s.id, x.id, x.lang, x.text FROM sense s JOIN sense_src x ON x.sense_id=s.id "
        "WHERE x.lang IN ('fr','vi','pl')") if _C.sense_hidden_why(lang, text)]
    ng = con.execute("SELECT COUNT(*) FROM sense_gloss WHERE sense_id IN (%s)"
                     % (",".join(str(b[0]) for b in bad) or "0")).fetchone()[0]
    con.close()
    print("■ 要撤掉的破例义项 %d 个（gloss %d 条）" % (len(bad), ng))
    if dry or not bad:
        print("(干跑)")
        return
    with dbtool.session("prune-xl-blind", expect={"#sense": -len(bad), "#sense_gloss": -ng},
                        invalidates=["sense", "sense_gloss"]) as s:
        s.executemany("DELETE FROM sense_gloss WHERE sense_id=?", [(b[0],) for b in bad])
        s.executemany("UPDATE sense_src SET sense_id=NULL WHERE id=?", [(b[1],) for b in bad])
        s.executemany("DELETE FROM sense WHERE id=?", [(b[0],) for b in bad])


def load(dry=True, main_tags=("ru-S1-slice2", "en-S1-slice2"), xl_tag="xl"):
    """两类，**分开回收、分开计数**：
      ① 主体：`sense_gloss(zh, src=model:…)` 挂到已有的出版义项上
      ② 破例：新建 `sense`（hidden=0）＋ `sense_src.sense_id` 指过去 ＋ 一条模型中文 gloss
    🔴 幂等：已有模型中文的义项跳过；破例那批已有 sense_id 的证据跳过。
    """
    import dbtool
    import re as _re
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    pub = {r[0] for r in con.execute("SELECT id FROM sense WHERE hidden=0")}
    have = {r[0] for r in con.execute(
        "SELECT sense_id FROM sense_gloss WHERE src=?", (SRC_MODEL,))}
    xl_ok = {r[0]: r for r in xl_rows(con)}
    src_meta = {r[0]: r[1:] for r in con.execute(
        "SELECT id, word_id, entry_id FROM sense_src WHERE id IN (%s)"
        % ",".join(str(i) for i in xl_ok) or "0")} if xl_ok else {}
    next_sid = con.execute("SELECT COALESCE(MAX(id),0) FROM sense").fetchone()[0] + 1
    con.close()
    st = collections.Counter()
    main, new_sense, link, xl_gloss = [], [], [], []
    for tag in main_tags:
        for sid, zh in _answers(OUT / ("%s.jsonl" % tag)).items():
            zh = normalize_zh(zh)
            if sid not in pub:
                st["🔴 主体：义项 id 不在出版层"] += 1
            elif sid in have:
                st["主体：已有模型中文，跳过"] += 1
            elif not zh or not _re.search(r"[㐀-鿿]", zh):
                st["🔴 主体：空或没有汉字（不入库）"] += 1
            else:
                have.add(sid)
                main.append((sid, "zh", zh, SRC_MODEL))
                st["主体：要写"] += 1
    for xid, zh in _answers(OUT / ("%s.jsonl" % xl_tag)).items():
        zh = normalize_zh(zh)
        if xid not in xl_ok:
            st["破例：证据已不在破例范围（已出版/非词元/有义项），跳过"] += 1
            continue
        if not zh or not _re.search(r"[㐀-鿿]", zh):
            st["🔴 破例：空或没有汉字（不入库）"] += 1
            continue
        word_id, entry_id = src_meta[xid]
        new_sense.append((next_sid, word_id, entry_id, 0, 0, None))
        link.append((next_sid, xid))
        xl_gloss.append((next_sid, "zh", zh, SRC_MODEL))
        next_sid += 1
        st["破例：要写"] += 1
    for k, v in st.most_common():
        print("   %-46s %9s" % (k, F(v)))
    if dry or not (main or new_sense):
        print("\n(干跑。确认后 --load --apply)")
        return
    with dbtool.session(
            "load-ru-zh-glosses",
            expect={"#sense_gloss": len(main) + len(xl_gloss), "#sense": len(new_sense)},
            invalidates=["sense", "sense_gloss",
                         "🔴 中文覆盖率会从 23.89% 跳上去 ⇒ 义项闸 E12 的基线要在**确认落点之后**重锁"]) as s:
        s.executemany("INSERT INTO sense_gloss(sense_id,lang,text,src) VALUES (?,?,?,?)", main)
        s.executemany("INSERT INTO sense(id,word_id,entry_id,rank,hidden,hidden_why) "
                      "VALUES (?,?,?,?,?,?)", new_sense)
        s.executemany("UPDATE sense_src SET sense_id=? WHERE id=?", link)
        s.executemany("INSERT INTO sense_gloss(sense_id,lang,text,src) VALUES (?,?,?,?)", xl_gloss)
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]                      # noqa: E731
    # 🔴 期望值**按口径重算**，不用 len(rows)（两个坏数同源 ⇒ 恒绿）
    print("\n═══ 写后回核 ═══")
    print("   模型译文行                 %s" % F(q("SELECT COUNT(*) FROM sense_gloss WHERE src='%s'" % SRC_MODEL)))
    print("   仍缺中文的可出版词元        %s" % F(q(
        "SELECT COUNT(*) FROM dict d WHERE d.is_lemma=1 AND EXISTS(SELECT 1 FROM sense s WHERE "
        "s.word_id=d.id AND s.hidden=0) AND NOT EXISTS(SELECT 1 FROM sense s JOIN sense_gloss g "
        "ON g.sense_id=s.id WHERE s.word_id=d.id AND s.hidden=0 AND g.lang='zh')")))
    con.close()


if __name__ == "__main__":
    raise SystemExit(main())
