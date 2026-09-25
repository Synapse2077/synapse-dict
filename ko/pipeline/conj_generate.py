#!/usr/bin/env python3
"""按规则生成活用表。ko，2026-09-24（结清 K8 的另一半）。

═══ 为什么可以生成，以及**凭什么相信它** ═══
7,862 个用言词元源头一张活用表都没有，读者点进去是空的（K8 的读者口径那一半）。
任何 dump 都补不上 —— 只能按规则生成。**而"按规则"必须先证明规则是对的。**

🔴 **规则不是我写的，是从数据里学的**：库里有 4,418 个词元带真实活用表
（403,687 行，来自英文版）。本文件把它们学成
    键 = (活用类, 词性, tags, 词干末元音, 有无收音, 谐音阴阳, 词干末音节)
    值 = {(从词干砍掉几个字母, 接上哪些字母)}     ← 一个键对应**一组**形式
然后对没有表的词套同一张表。

🔴🔴 **凭据是留出法，不是"看着像对"**：
    一半词元学规则 → 另一半生成 → 逐个形式比源头
    准确率 **99.84%** ／ 召回率 90.99%（召回低是留出把键弄稀了，正式跑用全量）
⚠️ 第一版准确率只有 99.19%，多生成里有**真错**：
    `모르다 → 몰러`   르불규칙的谐音要看**前一音节**（모＝ㅗ 阳性）⇒ 应是 `몰라`
    `꼬다  → 꼬너라`  `-너라` 只有 오다 一族有
  ⇒ 键里加了「谐音阴阳」和「词干末音节」。**是数据告诉我键缺什么的。**

═══ 🔴 只生成"安全类"，不安全的宁可留空 ═══
按活用类分档量准确率（留出法），差别极大：

    여불규칙 99.95%   규칙 99.96%   ㅂ불규칙 99.95%   르불규칙 99.97%   ㄹ탈락 99.85%
    러불규칙 98.82%   ㅅ불규칙 97.83%   ㅎ불규칙 96.42%   으탈락 95.85%
    🔴 ㄷ불규칙 **82.99%**

`SAFE` 只收 ≥99.8% 的五类。**恰好覆盖要生成的 96.6%** ——
错误集中在小类上，而要补的那批 93% 是 `-하다`/`-거리다`/`-대다` 这种最规则的派生词。
⚠️ 不安全的那几类**留空**，落账。`[[dict-framework-doc]]`：**错比缺更伤权威**。

═══ 预期残差，先说在前面 ═══
按实际类别构成算 **≈290 个错误词形 / 668,000 行（0.04%）**。
🔴 这个数**不是估计出来就完了**：全部生成行标 `src='rule'`，
   ⇒ 判错了可以整批撤，⇒ 展示层能把它和源头给的表分开，
   ⇒ 外锚闸排除它（与读音层排除 `src='g2p'` 同一条规矩）。

用法（在仓库根）：
    python3 -u ko/pipeline/conj_generate.py            # 干跑＋留出法自测
    python3 -u ko/pipeline/conj_generate.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))

import argparse
import collections
import json
import random
import sqlite3
import unicodedata

import dbtool
import paths
from infl_tags import label_zh

f = lambda n: format(n, ",")
SRC = "rule"
BATCH = 50000

CHO = [chr(0x1100 + i) for i in range(19)]
JUNG = [chr(0x1161 + i) for i in range(21)]
JONG = [""] + [chr(0x11A8 + i) for i in range(27)]
BRIGHT = {"ᅡ", "ᅩ", "ᅣ", "ᅭ"}

# 留出法上「同 tags 下形式错」率 ≤0.1% 的类。**锁的是类名，数字写在文件头**。
SAFE = {"여불규칙", "규칙", "ㅂ불규칙", "르불규칙"}
# 🔴 `ㄹ탈락` 2026-09-24 被闸挡在外面（形式错率 0.147% > 0.1%）。
#    **不放宽阈值去迁就它** —— 实测要生成的那批里 `ㄹ탈락` 是 **0 个词**，
#    移出去一分钱不花。`[[proxy-metric-gets-optimized]]`：
#    闸红了先看代价，代价是 0 就别动闸。

# 只生成「同类同词性的词里 ≥80% 都有」的 tags 组合。
# 🔴 实测 0.8 是**白拿的**：命中一条不少（180,055）、召回不变（91.7%）、
#    「同 tags 下形式错」不变（87），而「源头没给这个 tags」砍掉一半（14,341→7,642）。
#    ⚠️ 0.95 会把召回打到 48.5% —— **阈值调紧不是越紧越好**，要量。
MIN_SHARE = 0.8

# 🔴 形容词没有命令形/共动形。**这是语言事实，不是阈值** ——
#    能用事实写的判据就别用统计阈值（`[[criteria-from-meaning-not-form]]`）。
#    实测残余里 925/7,642 是命令/共动类，其中落在形容词上的正是这条要挡的。
ADJ_FORBIDDEN = ("imperative", "hortative")


def jamo(s):
    out = []
    for ch in s:
        if "가" <= ch <= "힣":
            n = ord(ch) - 0xAC00
            out += [CHO[n // 588], JUNG[(n % 588) // 28]]
            if n % 28:
                out.append(JONG[n % 28])
        else:
            out.append(ch)
    return out


def unjamo(js):
    out, i = [], 0
    while i < len(js):
        ch = js[i]
        if ch in CHO and i + 1 < len(js) and js[i + 1] in JUNG:
            a, b, j = CHO.index(ch), JUNG.index(js[i + 1]), 0
            i += 2
            if i < len(js) and js[i] in JONG[1:]:
                j = JONG.index(js[i])
                i += 1
            out.append(chr(0xAC00 + a * 588 + b * 28 + j))
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _lcp(a, b):
    i = 0
    while i < len(a) and i < len(b) and a[i] == b[i]:
        i += 1
    return i


def harmony(stem):
    """谐音阴阳。🔴 取**最后一个非 ㅡ 的元音** —— 르불규칙 看的是前一音节
    （`모르` 的 ㅡ 不算数，要看 `모` 的 ㅗ ⇒ 阳性 ⇒ `몰라` 不是 `몰러`）。
    第一版漏了这一条，当场生成出 `몰러`。"""
    for v in reversed([j for j in jamo(stem) if j in JUNG]):
        if v != "ᅳ":
            return "B" if v in BRIGHT else "D"
    return "D"


def load_info(con):
    """{原形: (活用类, {词性})}"""
    info = {}
    for w, cl, pos in con.execute(
            "SELECT d.word, e.conj_class, e.pos_raw FROM entry e "
            "JOIN dict d ON d.id=e.word_id WHERE e.conj_class IS NOT NULL"):
        info.setdefault(w, [cl, set()])[1].add(
            "adj" if pos in ("adj", "adjective") else "verb")
    return info


def keyof(info, base, tags):
    v = info.get(base)
    stem = base[:-1]
    if not v or not stem or not ("가" <= stem[-1] <= "힣"):
        return None
    cl, poss = v
    pk = "both" if len(poss) > 1 else next(iter(poss))
    n = ord(stem[-1]) - 0xAC00
    return (cl, pk, tags, JUNG[(n % 588) // 28], (n % 28) > 0,
            harmony(stem), stem[-1])


def learn(con, info, only=None):
    """从有真实活用表的词元学规则表。`only` 限定训练集（留出法用）。

    🔴 一个键**对应一组形式**，不是一个。`하다` 的 `["causative","informal"]`
       下面同时有 `하여서`/`해서`/`하셔서` —— 都对。第一版假设"一个键一个形式"，
       一致率只有 48%，**是这个假设错，不是规则学不出来**。
    ⚠️ 只收**出现在 ≥50% 训练词元上**的变体：罕见变体（`-거라`）只有部分词有，
       照收会给所有词都安一个。
    """
    rule = collections.defaultdict(collections.Counter)
    seen = collections.Counter()
    real = collections.defaultdict(set)
    for base, w, tags in con.execute(
            "SELECT i.base, d.word, i.tags FROM inflection i "
            "JOIN dict d ON d.id=i.word_id WHERE i.src <> ?", (SRC,)):
        if only is not None and base not in only:
            continue
        if keyof(info, base, tags) is None:
            continue
        real[base].add((tags, w))
    for base, items in real.items():
        ks = set()
        for tags, w in items:
            k = keyof(info, base, tags)
            ks.add(k)
            js, jw = jamo(base[:-1]), jamo(w)
            i = _lcp(js, jw)
            rule[k][(len(js) - i, tuple(jw[i:]))] += 1
        for k in ks:
            seen[k] += 1
    return ({k: {v for v, n in d.items() if n >= 0.5 * seen[k]}
             for k, d in rule.items()}, real)


def index_rules(R):
    """规则表按**键去掉 tags 的那部分**分桶 → {桶: {tags: 变体}}。

    ⚠️ 纯性能改写，行为一字不变。原来 `generate()` 对每个词元扫全部 14,525 个键
       （7,592 × 14,525 ≈ 1.1 亿次），干跑要跑好几分钟。分桶之后每个词只看自己那一桶。
    """
    idx = collections.defaultdict(dict)
    for k, v in R.items():
        idx[(k[0], k[1], k[3], k[4], k[5], k[6])][k[2]] = v
    return idx


def generate(info, IDX, base, keep=None):
    """→ [(tags, 生成的词形)]。键对不上就不生成（不猜）。

    `keep` = 允许的 tags 组合集合（`MIN_SHARE` 筛出来的）。None 表示不筛。
    """
    k0 = keyof(info, base, None)
    if k0 is None:
        return []
    bucket = IDX.get((k0[0], k0[1], k0[3], k0[4], k0[5], k0[6]))
    if not bucket:
        return []
    out = []
    stem_j = jamo(base[:-1])
    isadj = info[base][1] == {"adj"}
    for tags, variants in bucket.items():
        if keep is not None and tags not in keep:
            continue
        # 🔴 形容词没有命令形/共动形 —— 语言事实
        if isadj and any(x in tags for x in ADJ_FORBIDDEN):
            continue
        for drop, suf in variants:
            if drop > len(stem_j):
                continue
            out.append((tags, unjamo(stem_j[:len(stem_j) - drop] + list(suf))))
    return out


def tag_share(real, info, only):
    """{(活用类, 词性): {tags: 用了它的词元数}} 与总数 —— `MIN_SHARE` 的分母。"""
    use = collections.defaultdict(collections.Counter)
    tot = collections.Counter()
    for b in only:
        ps = info[b][1]
        k = (info[b][0], "both" if len(ps) > 1 else next(iter(ps)))
        tot[k] += 1
        for t in {t for t, _ in real[b]}:
            use[k][t] += 1
    return use, tot


def keepset(use, tot, info, base):
    ps = info[base][1]
    k = (info[base][0], "both" if len(ps) > 1 else next(iter(ps)))
    return {t for t, n in use[k].items() if n >= MIN_SHARE * tot[k]}


def holdout(con, info):
    """🔴 **交付物之一**：不跑这一步不许写库。留出法逐个形式比源头。

    🔴🔴 **把「多生成」拆成两类，因为它们性质完全不同**（这一版才拆对）：
      ① `tagmiss` 源头根本没给这个 tags 组合 —— 形式**合法**，源头只是没列全
         （`-아요`/`-면`/`-어서` 这类普通格子占大头）。补它是**填缺**。
      ② `formwrong` **同一个 tags 下形式与源头不同** —— 这才是真错：
         `적시다 → 적세요`（该是 `적시세요`，规则把词干里的 `시` 当成了敬语中缀）
    ⚠️ 第一版把两者混在一起当"准确率"，得出 91.37%，差点据此否掉整件事；
      而混在一起之前我还量过一个 **99.95%** —— 那次只问「这个词**已有的** tags
      生成得对不对」，**是一道更容易的题**。三个数量的是三件事。
      ⇒ 闸盯的是 ②，因为 ① 不是错。
    """
    _, real = learn(con, info)
    lemmas = sorted(real)
    random.Random(20260924).shuffle(lemmas)
    h = len(lemmas) // 2
    R, _ = learn(con, info, only=set(lemmas[:h]))
    IDX = index_rules(R)
    use, tot = tag_share(real, info, lemmas[:h])
    per = collections.defaultdict(lambda: [0, 0, 0])
    for b in lemmas[h:]:
        got = real[b]
        gottags = {t for t, _ in got}
        gen = set(generate(info, IDX, b, keepset(use, tot, info, b)))
        cl = info[b][0]
        per[cl][0] += len(gen & got)
        for t, w in gen - got:
            per[cl][1 if t not in gottags else 2] += 1
    return per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    info = load_info(con)

    print("■ 留出法自测（一半学、一半生成，逐个形式比源头）")
    per = holdout(con, info)
    bad = []
    print("   %-9s %9s %10s %8s %8s"
          % ("活用类", "命中", "源头没列", "🔴形式错", "错率"))
    for cl, (tp, tm, fw) in sorted(per.items(), key=lambda x: -x[1][0]):
        r = 100.0 * fw / max(tp, 1)
        mark = "✅" if cl in SAFE else "⬜"
        if cl in SAFE and r > 0.1:
            mark = "🔴"
            bad.append((cl, r))
        print("   %s %-8s %9s %10s %8s %7.3f%%%s"
              % (mark, cl, f(tp), f(tm), f(fw), r,
                 "  ← 生成" if cl in SAFE else "  ← 跳过"))
    if bad:
        raise SystemExit("🔴 安全类里有「形式错」率超过 0.1%% 的：%s\n"
                         "   ⇒ 要么把它移出 SAFE，要么先把键补细。**不许直接写库**" % bad)

    R, full = learn(con, info)
    IDX = index_rules(R)
    use, tot = tag_share(full, info, list(full))
    # 要生成的：用言词元、没有任何活用表、活用类在 SAFE 里
    # 🔴 词干必须**全是谚文**。韩语用言的词干是用谚文写的；
    #    汉字写法的词头（`期하다`）套上词尾会生成 `期했다` 这种**不存在的东西**。
    #    ⚠️ 这与变形层里 `熱工 → 熱아` 是同一个洞 —— 源头也犯过，
    #      `is_korean_form` 有意允许汉字（"汉字词的变形"），在**生成**这一侧就太宽了。
    #    自检当场报 98 条，**判据是自检逼出来的，不是我想周全的**。
    ishangul = lambda w: all("가" <= c <= "힣" or c in " -" for c in w)
    todo = [w for (w,) in con.execute(
        "SELECT DISTINCT d.word FROM entry e JOIN dict d ON d.id=e.word_id "
        "WHERE e.pos_raw IN ('verb','adj','adjective') AND d.word LIKE '%다' "
        "AND d.is_lemma=1 AND NOT EXISTS("
        "  SELECT 1 FROM inflection i WHERE i.base=d.word)")
        if info.get(w) and info[w][0] in SAFE and ishangul(w)]
    indict = {w: i for i, w in con.execute("SELECT id, word FROM dict")}
    n_dict_before = con.execute("SELECT COUNT(*) FROM dict").fetchone()[0]
    n_infl_before = con.execute("SELECT COUNT(*) FROM inflection").fetchone()[0]
    con.close()

    rows, newforms = [], set()
    for b in todo:
        for tags, w in generate(info, IDX, b, keepset(use, tot, info, b)):
            rows.append((b, w, tags))
            if w not in indict:
                newforms.add(w)
    print("\n■ 要生成 %s 个词元 ／ %s 行 ／ 新词形 %s"
          % (f(len(todo)), f(len(rows)), f(len(newforms))))
    print("   inflection %s → %s" % (f(n_infl_before), f(n_infl_before + len(rows))))
    print("   dict       %s → %s" % (f(n_dict_before),
                                     f(n_dict_before + len(newforms))))
    # 🔴 预期残差**按各类实测错率加权**，不拍一个统一的数 ——
    #    各类差着一个数量级（르불규칙 0.032% vs 으탈락 7.48%），拍平均数会骗自己。
    rate = {cl: (fw / max(tp, 1)) for cl, (tp, _tm, fw) in per.items()}
    bycls = collections.Counter(info[b][0] for b, _w, _t in rows)
    est = sum(n * rate.get(cl, 0.0) for cl, n in bycls.items())
    print("   ⚠️ 预期残差 ≈ **%d 个错误词形**（%.3f%%）—— 按各类实测错率加权："
          % (est, 100.0 * est / max(len(rows), 1)))
    for cl, n in bycls.most_common():
        print("        %-8s %9s 行 × %.3f%% = %5.0f"
              % (cl, f(n), 100 * rate.get(cl, 0), n * rate.get(cl, 0)))
    print("   ⇒ 全部标 `src='%s'`，判错了可整批撤" % SRC)
    print("\n■ 抽样")
    for b in todo[:3]:
        g = sorted({w for _t, w in generate(info, IDX, b, keepset(use, tot, info, b))})
        print("   %-12s → %s …（共 %d）" % (b, "  ".join(g[:8]), len(g)))
    # 🔴 生成物自检：不许出现非谚文、不许与原形同形
    weird = [(b, w) for b, w, _t in rows
             if not all("가" <= ch <= "힣" or ch in " -" for ch in w) or w == b]
    print("\n   %s 生成物里有非谚文或与原形同形的：%s"
          % ("✅" if not weird else "🔴", f(len(weird))))
    if weird:
        for x in weird[:10]:
            print("      %s" % (x,))
        raise SystemExit("🔴 生成物不干净")

    if not a.apply:
        print("\n（干跑。确认后 --apply）")
        return

    newlist = sorted(newforms)
    with dbtool.session(
            "ko-generate-conjugation",
            expect={"__rows__": len(newlist), "pos": 0,
                    "#inflection": len(rows),
                    "inflection.base_id": len(rows),
                    "inflection.label_zh": len(rows)},
            invalidates=[
                "🔴 外锚闸 `verify_layers_vs_dump.py` 变形层：必须排除 `src='rule'`，"
                "否则 66 万行生成数据会被当成「库里有·追不回源头」—— "
                "与读音层排除 `src='g2p'` 同一条规矩",
                "账的闸 P6「用言词元里有活用表可看的占比（读者口径）」：会从 35.98% 跳到 ~97%",
                "搜索层（阶段 9）：`search_prefix` 要在这批之后重建（新增约 50 万词形）",
                "空白页判据：新词形 `is_lemma=0` 且有变形链 ⇒ 不算空白页，但覆盖率分母变了",
            ]) as s:
        s.executemany(
            "INSERT INTO dict (word, word_norm, is_lemma, pos) VALUES (?,?,0,NULL)",
            [(w, unicodedata.normalize("NFC", w)) for w in newlist])
        for i, w in s.execute("SELECT id, word FROM dict WHERE id > ?",
                              (max(indict.values()),)):
            indict[w] = i
        buf = []
        for n, (b, w, tags) in enumerate(rows, 1):
            tg = json.loads(tags)
            buf.append((indict[w], None, "inflection", b, indict.get(b),
                        label_zh(tg), " ".join(sorted(tg)), tags, SRC,
                        "rule:%s:%s" % (b, w)))
            if len(buf) >= BATCH:
                s.executemany(
                    "INSERT INTO inflection (word_id, entry_id, kind, base, base_id,"
                    " label_zh, desc_en, tags, src, src_ref) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    buf)
                buf = []
                print("   …已写 %s 行" % f(n))
        if buf:
            s.executemany(
                "INSERT INTO inflection (word_id, entry_id, kind, base, base_id,"
                " label_zh, desc_en, tags, src, src_ref) VALUES (?,?,?,?,?,?,?,?,?,?)",
                buf)

    print("\n═══ 写后回核（从库里重算）═══")
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    q = lambda x: con.execute(x).fetchone()[0]
    checks = [
        ("inflection 行数", q("SELECT COUNT(*) FROM inflection"),
         n_infl_before + len(rows)),
        ("dict 行数", q("SELECT COUNT(*) FROM dict"), n_dict_before + len(newlist)),
        ("生成行都标着 src='rule'",
         q("SELECT COUNT(*) FROM inflection WHERE src='%s'" % SRC), len(rows)),
        # 🔴 **源头给的那批一行都不许被动过** —— 这是反向闸
        ("源头给的变形行原样没动",
         q("SELECT COUNT(*) FROM inflection WHERE src<>'%s'" % SRC), n_infl_before),
        ("word_id 都指得到",
         q("SELECT COUNT(*) FROM inflection i LEFT JOIN dict d ON d.id=i.word_id "
           "WHERE d.id IS NULL"), 0),
        ("base_id 都指得到",
         q("SELECT COUNT(*) FROM inflection i LEFT JOIN dict d ON d.id=i.base_id "
           "WHERE d.id IS NULL"), 0),
        # 🔴 生成的变形形不许自己变成词元
        ("生成的新词形 is_lemma=0",
         q("SELECT COUNT(*) FROM dict d WHERE d.is_lemma=1 AND EXISTS("
           "SELECT 1 FROM inflection i WHERE i.word_id=d.id AND i.src='%s') "
           "AND NOT EXISTS(SELECT 1 FROM entry e WHERE e.word_id=d.id)" % SRC), 0),
    ]
    ok = True
    for name, got, want in checks:
        good = got == want
        ok &= good
        print("   %s %-30s %10s（期望 %s）" % ("✅" if good else "🔴", name,
                                              f(got), f(want)))
    print("\n■ 读者口径：用言词元里有活用表可看的占比")
    print("   %.2f%%" % q(
        "SELECT 100.0*COUNT(DISTINCT CASE WHEN EXISTS("
        "  SELECT 1 FROM inflection i WHERE i.base=d.word) THEN d.word END)"
        "/COUNT(DISTINCT d.word) FROM entry e JOIN dict d ON d.id=e.word_id "
        "WHERE e.pos_raw IN ('verb','adj','adjective') AND d.word LIKE '%다' "
        "AND d.is_lemma=1"))
    con.close()
    if not ok:
        raise SystemExit("🔴 回核对不上")


if __name__ == "__main__":
    main()
