#!/usr/bin/env python3
"""阶段 6 探针：**例句 / 关系 / 录音三层的落点**，以及例句翻译那个要花钱的分母。ru，2026-10-23。只读。

    python3 -u ru/probes/probe_stage6.py > data/work/ru/probe/probe_stage6.txt

每一节回答一件会决定收割器怎么写、或者钱花在哪儿的事：
  §A 例句：每源规模／字段完整值域（`type`/`tags`/`raw_tags`）／**挂得上哪种义项**（四级落点）
  §B 🔴 **花钱之前先量这一列本身**（vi 的 B21：256 条根本不是例句是在付费前逮到的、ko 的 K15 是付费后）：
       形状分堆，每堆给样本，**按源拆开**（一堆判据太宽一堆真渣，总数看不见）
  §C 例句译文：每源 `translation`/`english` 到底是什么语言、是不是译文（vi 版的「译文」是作者名）
  §D 🔴 要花钱的分母：可出版、挂在可出版义项上、**没有中文译文**的例句，几种范围
  §E 关系：每源每字段（词级/义项级）条数、条目字段值域、目标是否在 dict、目标文字
  §F ru 版 `related`（R1/R10）：`raw_tags` 分组标签值域 → 白名单的依据；体对候选（en/zh-t 的 `forms`）
  §G 录音：每源条数／url 字段／commons_key 去重率（B12）／Lingua Libre 文件名与词形对照
判据一律 `import criteria`；值域全打不截断（ru 外审那一轮的教训：猜的候选表一天漏三个值名）。
"""
import collections
import json
import random
import re
import sqlite3
import sys
import unicodedata as ud
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import paths                                                    # noqa: E402
from pipeline import criteria                                   # noqa: E402
from pipeline.build import SRC, rd                              # noqa: E402

RND = random.Random(20261023)
F = lambda n: format(n, ",")                                    # noqa: E731
EG_CAP = 300


def script_of(s):
    """一串里出现的文字系统（按 Unicode 字符名第一个词）。"""
    out = collections.Counter()
    for ch in s or "":
        if ch.isalpha():
            out[ud.name(ch, "?").split()[0]] += 1
    return out


def has_cyr(s):
    return any("CYRILLIC" in ud.name(ch, "") for ch in s or "")


def has_cjk(s):
    return any("CJK" in ud.name(ch, "") for ch in s or "")


def commons_key(url):
    """MediaWiki 标题归一：取文件名、URL 解码、`_`→空格、首字母大写。"""
    if not url:
        return None
    name = unquote(url.rsplit("/", 1)[-1])
    # transcoded 形如 .../File.ogg/File.ogg.mp3 —— 取原文件名
    m = re.search(r"/([^/]+\.(?:ogg|oga|wav|flac|opus|mp3))/[^/]+$", unquote(url), re.I)
    if m:
        name = m.group(1)
    name = name.replace("_", " ").strip()
    return name[:1].upper() + name[1:]


_LL = re.compile(r"^LL-Q\d+ \([a-z]{3}\)-.*?-(.+)\.(wav|ogg|oga|mp3|flac|opus)$", re.I)


class Eg:
    def __init__(self):
        self.c = collections.Counter()
        self.eg = collections.defaultdict(list)

    def add(self, k, s, n=1):
        self.c[k] += n
        if len(self.eg[k]) < EG_CAP:
            self.eg[k].append(s)

    def dump(self, indent="   ", k_eg=4):
        for k, v in sorted(self.c.items(), key=lambda kv: (kv[0][0], -kv[1])):
            print("%s%-58s %10s" % (indent, " / ".join(map(str, k)), F(v)))
            for x in RND.sample(self.eg[k], min(k_eg, len(self.eg[k]))):
                print("%s      · %s" % (indent, x))


def ex_shape(text, word, ref):
    """例句文本的形状分堆。**这是探针，不是判据** —— 判据由读完样本后写进 criteria。"""
    t = (text or "").strip()
    if not t:
        return "空正文" + ("（只有 ref）" if ref else "")
    if not any(ch.isalnum() for ch in t):
        return "没有字母/数字"
    if not has_cyr(t):
        return "一个西里尔字母都没有"
    if criteria.strip_stress(t).strip(" .!?…").lower() == criteria.strip_stress(word).lower():
        return "整条就是词头本身"
    if re.search(r"\{\{|\}\}|\[\[|\]\]|<[a-z/]|&[a-z]+;|''", t):
        return "含 wiki/HTML 标记残渣"
    if re.search(r"(?i)отсутствует пример|пример употребления|нет примера", t):
        return "占位串（«нет примера»类）"
    if "◆" in t:
        return "含 ◆"
    if "\n" in t:
        return "多行"
    if len(t) > 600:
        return "超长 >600 字符"
    lat = sum(1 for ch in t if "LATIN" in ud.name(ch, ""))
    cyr = sum(1 for ch in t if "CYRILLIC" in ud.name(ch, ""))
    if lat > cyr:
        return "拉丁字母多于西里尔"
    if has_cjk(t):
        return "混有汉字"
    if len(t) <= 3:
        return "≤3 字符"
    return "看起来正常"


def main():
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    wid = dict(con.execute("SELECT word, id FROM dict"))
    is_lemma = dict(con.execute("SELECT id, is_lemma FROM dict"))
    # sense_src src_ref → (sense_id, 该义项 hidden)
    s_hidden = dict(con.execute("SELECT id, hidden FROM sense"))
    ssrc = {}
    for ref_, sid in con.execute("SELECT src_ref, sense_id FROM sense_src"):
        ssrc[ref_] = sid
    con.close()
    print("■ 俄语阶段 6 探针  2026-10-23  判据 %s" % criteria.RULE_VER, flush=True)

    ref = criteria.SrcRef()
    A = {k: collections.Counter() for k in ("n", "land", "type", "tags", "raw_tags", "keys")}
    shape = Eg()
    trl = Eg()
    dup = collections.Counter()
    seen_ex = collections.defaultdict(set)     # word → 归一正文集合（跨版重复）
    pay = collections.Counter()
    pay_chars = collections.Counter()
    REL = Eg()
    relkeys = collections.defaultdict(collections.Counter)
    rel_tgt = collections.Counter()
    rel_tgt_eg = collections.defaultdict(list)
    rel_pairs = collections.defaultdict(set)
    ru_rel_raw = collections.Counter()
    ru_rel_raw_eg = collections.defaultdict(list)
    aspect = Eg()
    snd = collections.Counter()
    snd_keys = collections.defaultdict(collections.Counter)
    ckeys = collections.defaultdict(set)       # word → commons_key 集合（全源）
    urls = collections.defaultdict(set)
    ll = Eg()
    for src, p in SRC:
        lang = criteria.SENSE_LANG[src]
        for e in rd(p):
            ok, _skip, pos = criteria.entry_accept(e)
            if not ok:
                continue
            w = e["word"]
            no, sub = criteria.etym_no_pair(e)
            sref, _seq = ref.take(src, w, pos, no, sub)
            word_id = wid.get(w) or wid.get(criteria.strip_stress(w))
            # ── 例句 ──
            for si, s in enumerate(e.get("senses") or []):
                exs = s.get("examples") or []
                if not exs:
                    continue
                key = "%s#s%d" % (sref, si)
                if key not in ssrc:
                    land = "④ 义项不在 sense_src（无释义）"
                else:
                    sid = ssrc[key]
                    if sid is None:
                        land = "③ 义项只在证据层（指针/非三语）"
                    elif s_hidden.get(sid):
                        land = "② 挂在被藏的义项上"
                    else:
                        land = "① 挂在可出版义项上"
                for x in exs:
                    A["n"][src] += 1
                    A["land"][(src, land)] += 1
                    A["keys"][src] += 0
                    for k in x:
                        A["keys"][(src, k)] += 1
                    if x.get("type"):
                        A["type"][(src, x["type"])] += 1
                    for t in x.get("tags") or []:
                        A["tags"][(src, t)] += 1
                    for t in x.get("raw_tags") or []:
                        A["raw_tags"][(src, t)] += 1
                    text = x.get("text") or ""
                    sh = ex_shape(text, w, x.get("ref"))
                    shape.add((src, sh), "%s ⟫ %s%s" % (
                        w, text.replace("\n", "⏎")[:110],
                        ("  ‖ref: " + x["ref"][:50]) if x.get("ref") else ""))
                    tr = x.get("translation") or x.get("english") or ""
                    if tr:
                        sc = script_of(tr).most_common(1)
                        trl.add((src, "译文主文字=" + (sc[0][0] if sc else "无字母")),
                                "%s ⟫ %s  ⇒  %s" % (w, text[:60], tr[:60]))
                    else:
                        trl.add((src, "无译文"), "%s ⟫ %s" % (w, text[:60]))
                    nt = re.sub(r"\W+", "", criteria.strip_stress(text).lower())
                    if nt in seen_ex[w]:
                        dup[src] += 1
                    seen_ex[w].add(nt)
                    # 付费分母：俄语正文、形状正常、挂在可出版义项、没有中文译文
                    zh_tr = lang == "zh" and has_cjk(tr)
                    if sh == "看起来正常" and land.startswith("①") and not zh_tr:
                        lem = is_lemma.get(word_id) == 1
                        for scope, cond in (("P1 全部", True), ("P2 只词元", lem),
                                            ("P3 只 ru 版", src == "ru-edition"),
                                            ("P4 非 ru 版", src != "ru-edition")):
                            if cond:
                                pay[scope] += 1
                                pay_chars[scope] += len(text)
            # ── 关系 ──
            levels = [("词级", e)] + [("义项级", s) for s in e.get("senses") or []]
            for lvl, obj in levels:
                for k, v in obj.items():
                    if k in ("forms", "senses", "examples", "sounds", "head_templates",
                             "inflection_templates", "categories", "etymology_templates",
                             "descendants_templates", "translations", "form_of", "alt_of",
                             "info_templates", "attestations", "links", "wikipedia"):
                        continue
                    if not (isinstance(v, list) and v and isinstance(v[0], dict) and "word" in v[0]):
                        continue
                    for it in v:
                        REL.add((src, lvl, k), "%s → %s" % (w, (it.get("word") or "")[:40]), 1)
                        for kk in it:
                            relkeys[(src, k)][kk] += 1
                        t = (it.get("word") or "").strip()
                        if not t:
                            rel_tgt[(src, k, "目标空")] += 1
                            continue
                        if not has_cyr(t):
                            cls = "目标无西里尔"
                        elif t in wid or criteria.strip_stress(t) in wid:
                            cls = "目标在 dict"
                        else:
                            cls = "目标不在 dict"
                        rel_tgt[(src, k, cls)] += 1
                        if cls != "目标在 dict" and len(rel_tgt_eg[(src, k, cls)]) < 6:
                            rel_tgt_eg[(src, k, cls)].append("%s → %s" % (w, t[:50]))
                        rel_pairs[(src, k)].add(hash((w, criteria.strip_stress(t))))
                        if src == "ru-edition" and k == "related":
                            for rt in it.get("raw_tags") or ["（无 raw_tags）"]:
                                ru_rel_raw[rt] += 1
                                if len(ru_rel_raw_eg[rt]) < 3:
                                    ru_rel_raw_eg[rt].append("%s → %s" % (w, t[:30]))
            # 体对候选：forms 里带 perfective/imperfective 的（en/zh 版）
            if pos == "verb":
                for f in e.get("forms") or []:
                    tg = set(f.get("tags") or [])
                    asp = tg & {"perfective", "imperfective", "biaspectual", "perfect"}
                    if asp:
                        extra = sorted(tg - asp)
                        aspect.add((src, "forms·" + "+".join(sorted(asp)),
                                    "其他标签=" + ("+".join(extra) or "无")),
                                   "%s → %s" % (w, f.get("form", "")[:40]))
                for s in e.get("senses") or []:
                    for t in s.get("tags") or []:
                        if t in ("semelefactive", "iterative", "perfective", "imperfective"):
                            aspect.add((src, "sense.tags", t), w)
            # ── 录音 ──
            for so in e.get("sounds") or []:
                u = None
                for uk in ("ogg_url", "mp3_url", "wav_url", "oga_url", "flac_url", "opus_url"):
                    if so.get(uk):
                        snd_keys[src][uk] += 1
                        u = u or so[uk]
                if not (so.get("audio") or u):
                    continue
                snd[(src, "带录音的 sound")] += 1
                ck = commons_key(so.get("audio") or u)
                urls[w].add(u)
                ckeys[w].add(ck)
                for t in so.get("tags") or []:
                    snd_keys[src]["tag:" + t] += 1
                for t in so.get("raw_tags") or []:
                    snd_keys[src]["raw:" + t] += 1
                m = _LL.match(ck or "")
                if m:
                    fw = m.group(1)
                    same = criteria.strip_stress(fw).lower().replace("ё", "е") == \
                        criteria.strip_stress(w).lower().replace("ё", "е")
                    ll.add((src, "LinguaLibre 文件名" + ("＝词形" if same else "≠词形")),
                           "%s ⇐ %s" % (w, ck[:70]))
                else:
                    ll.add((src, "非 LinguaLibre 命名"), "%s ⇐ %s" % (w, (ck or "")[:70]))
        print("   …%s 扫完" % src, flush=True)

    print("\n§A 例句规模与四级落点")
    for src, _p in SRC:
        print("   ── %s：%s 条" % (src, F(A["n"][src])))
        for (s2, land), v in sorted(A["land"].items()):
            if s2 == src:
                print("      %-40s %10s  %5.1f%%" % (land, F(v), 100 * v / max(1, A["n"][src])))
        print("      字段：%s" % {k[1]: v for k, v in A["keys"].items() if isinstance(k, tuple) and k[0] == src})
        for lab in ("type", "tags", "raw_tags"):
            d = {k[1]: v for k, v in A[lab].items() if k[0] == src}
            if d:
                print("      %s 完整值域（%d 种）：%s" % (lab, len(d), dict(sorted(d.items(), key=lambda kv: -kv[1]))))
        print("      同词跨/同版正文重复：%s" % F(dup[src]))

    print("\n§B 🔴 例句正文形状分堆（按源；每堆随机 4 条）")
    shape.dump()

    print("\n§C 例句译文：主文字（按源）")
    trl.dump()

    print("\n§D 🔴 付费分母：形状正常 ＋ 挂在可出版义项 ＋ 无中文译文")
    for k in sorted(pay):
        print("   %-20s %10s 条 ／ %12s 字符" % (k, F(pay[k]), F(pay_chars[k])))

    print("\n§E 关系：每源每字段条数（词级/义项级）")
    for k, v in sorted(REL.c.items()):
        print("   %-50s %10s   去重(源词,目标)=%s" % (" / ".join(k), F(v), F(len(rel_pairs[(k[0], k[2])]))))
    print("   条目字段值域：")
    for k, d in sorted(relkeys.items()):
        print("      %s/%s：%s" % (k[0], k[1], dict(d.most_common())))
    print("   目标落点：")
    for k, v in sorted(rel_tgt.items()):
        print("      %-56s %10s   %s" % (" / ".join(k), F(v), " ｜ ".join(rel_tgt_eg.get(k, [])[:4])))

    print("\n§F ru 版 `related` 的 raw_tags 完整值域（%d 种；R10 白名单的依据）" % len(ru_rel_raw))
    for k, v in ru_rel_raw.most_common():
        print("   %10s  %-60s %s" % (F(v), k[:60], " ｜ ".join(ru_rel_raw_eg[k])))
    print("\n§F2 体对候选（verb 的 forms 带体标签 ／ sense.tags 的方式体）")
    aspect.dump(k_eg=6)

    print("\n§G 录音")
    for k, v in sorted(snd.items()):
        print("   %-40s %10s" % (" / ".join(k), F(v)))
    for src, d in snd_keys.items():
        print("   %s 字段/标签：%s" % (src, dict(d.most_common())))
    nu = sum(len(v) for v in urls.values())
    nk = sum(len(v) for v in ckeys.values())
    print("   全源合并：(词,url) %s ／ (词,commons_key) %s ⇒ B12 重复 %s（%.1f%%）"
          % (F(nu), F(nk), F(nu - nk), 100 * (nu - nk) / max(1, nu)))
    print("   有录音的词形 %s；其中词元 %s" % (
        F(len(ckeys)), F(sum(1 for w in ckeys if is_lemma.get(wid.get(w)) == 1))))
    ll.dump(k_eg=5)
    print("\n■ 完。")


if __name__ == "__main__":
    main()
