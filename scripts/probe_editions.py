#!/usr/bin/env python3
"""维基词典**版本探测器** —— 某个目标语言在各版本里各有多少料，该下哪几个。2026-08-01。

═══ 为什么需要它 ═══
维基词典按**版本**组织，每个版本是「某社区用该语言写的、讲多种语言的词典」。
所以「做西语就下西语版」是错的直觉，我们为此白下过东西：
  · 意语版 38 MB 只有 40,090 条意语音标，而**法语版里的意语有 684,198 条（17 倍）**；
  · 中文版整包下了 215 MB，其实西语切片 10.3 MB 就够。
每个语言在各版本里的排名都不一样（社区活跃度不同），**必须实测，不能猜**。

═══ 两个便宜的事实（本脚本就建立在它们上面）═══
① `https://kaikki.org/<xx>wiktionary/` 索引页**直接列出该版本覆盖的每个语种及义项数**，
   免费、不下载。
② **非英文版也有 per-language 切片**（rawdata 页说只有整包，那是不全的）：
       https://kaikki.org/<xx>wiktionary/<本地语种名>/kaikki.org-dictionary-<本地语种名>.jsonl.gz
   实测法语版五个目标语言的切片合计 229 MB，整包 676 MB —— **省 66%**。

⚠️ 语种名是**用该版本自己的语言写的**（Spanish / Español / Espagnol / Spaans / 西班牙語…），
   所以要靠名称模式识别。模式表见 NAMES，识别不到时脚本会把该版本的**全部语种**列出来供人工确认
   —— 不假装万无一失。
⚠️ 同一语言在同一版本里可能有**多个本地名**（中文版的「西班牙語」和「西班牙语」是两个独立切片，
   都得取）。

用法（在仓库根目录）：
  python3 scripts/probe_editions.py --lang es
  python3 scripts/probe_editions.py --lang de --editions fr,zh,nl,ru,pl
  python3 scripts/probe_editions.py --edition nl            # 看某版本收了哪些语种
"""
import argparse
import gzip
import re
import sys
import urllib.parse
import urllib.request
from html import unescape

UA = {"User-Agent": "synapse-dict/1.0 (dictionary research; contact via repo)"}

# 值得探的版本（按已知体量，非穷举）。en 单列：它是我们六个库的建库基准。
EDITIONS = ["en", "fr", "zh", "nl", "de", "es", "ru", "pl", "it", "pt", "el", "ja", "ko", "tr", "cs"]

# 目标语言在各版本里的本地名模式。匹配用小写子串/正则，宁可多报也别漏。
NAMES = {
    "es": r"spanish|español|espanol|espagnol|spaans|spanisch|spagnolo|espanhol|špan|szpan|spanyol|"
          r"hiszpa|испан|ισπαν|西班牙|스페인|スペイン|espanyol|castellano",
    "en": r"^english$|anglais|engels|englisch|inglese|inglés|ingles|angiel|англ|αγγλ|英語|英语|영어|英文",
    "fr": r"^french$|français|francais|frans|französisch|francese|francês|francuski|франц|γαλλ|法語|法语|프랑스|フランス",
    "de": r"^german$|allemand|duits|deutsch|tedesco|alemán|aleman|alemão|niemiecki|немец|γερμαν|德語|德语|독일|ドイツ",
    "it": r"^italian$|italien|italiaans|italienisch|italiano|włoski|wloski|итальян|ιταλ|意大利|義大利|이탈리아|イタリア",
    "pt": r"^portuguese$|portugais|portugees|portugiesisch|portoghese|portugués|português|portugalski|"
          r"португал|πορτογαλ|葡萄牙|포르투갈|ポルトガル",
}

ROW = re.compile(r'<a\s+href="([^"]+?)/index\.html"[^>]*>([^<]+?)\s*\((\d+)\s+senses\)', re.I)


def get(url, binary=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
    return b if binary else b.decode("utf-8", "replace")


def head_size(url):
    """只取 Content-Length，不下载正文。取不到返回 None。"""
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            n = r.headers.get("Content-Length")
            return int(n) if n else None
    except Exception:
        return None


def base_of(edition):
    """🔴 英文版是特例：它的索引在 /dictionary/，不是 /enwiktionary/（后者 404）。
    这也是为什么只有英文版有现成的 per-language 子集 —— 那一整个目录就是它。"""
    return "https://kaikki.org/dictionary" if edition == "en" else f"https://kaikki.org/{edition}wiktionary"


def index_of(edition):
    """→ [(本地语种名, 义项数, href), ...]，已按义项数降序。"""
    html = get(base_of(edition) + "/")
    out = []
    for href, name, n in ROW.findall(html):
        name = unescape(name).strip()
        if name.lower().startswith("all languages"):
            continue
        out.append((name, int(n), unescape(href)))
    out.sort(key=lambda x: -x[1])
    return out


def slice_url(edition, href):
    """href 取自 HTML 的 href 属性，**已经是百分号编码的** —— 千万别再 quote 一次
    （第一版就是这么错的：`Español` 变成 `Espa%25C3%25B1ol`，HEAD 全部 404）。

    🔴 另一个坑：语种名含空格时，**目录名保留 `%20`，但文件名把空格删掉**：
        .../j%C4%99zyk%20hiszpa%C5%84ski/kaikki.org-dictionary-j%C4%99zykhiszpa%C5%84ski.jsonl.gz
    不处理的话，波兰语版这类名字全部 404（表现为"切片大小 —"）。"""
    fn = href.replace("%20", "").replace("+", "")
    return f"{base_of(edition)}/{href}/kaikki.org-dictionary-{fn}.jsonl.gz"


def probe_lang(lang, editions):
    pat = re.compile(NAMES[lang], re.I)
    rows = []
    for ed in editions:
        try:
            idx = index_of(ed)
        except Exception as e:
            print(f"  ⚠️ {ed} 版索引取不到：{e}", file=sys.stderr)
            continue
        hits = [(n, c, h) for n, c, h in idx if pat.search(n)]
        if not hits:
            print(f"  ⚠️ {ed} 版没匹配到 {lang} 的本地名 —— "
                  f"该版前 5 个语种是 {[n for n,_,_ in idx[:5]]}（人工确认后可补进 NAMES）",
                  file=sys.stderr)
            continue
        for n, c, h in hits:
            u = slice_url(ed, h)
            rows.append((ed, n, c, head_size(u), u))
    rows.sort(key=lambda x: -x[2])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=sorted(NAMES), help="目标语言")
    ap.add_argument("--edition", help="只看某个版本收了哪些语种")
    ap.add_argument("--editions", help="逗号分隔，覆盖默认探测列表")
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()

    if a.edition:
        idx = index_of(a.edition)
        tot = sum(c for _, c, _ in idx)
        print(f"■ {a.edition} 版收录 {len(idx):,} 种语言，义项合计 {tot:,}")
        print(f"  {'本地语种名':28}{'义项数':>12}")
        for n, c, _ in idx[:a.top]:
            print(f"  {n[:26]:28}{c:>12,}")
        return

    if not a.lang:
        ap.error("要么 --lang，要么 --edition")
    eds = a.editions.split(",") if a.editions else EDITIONS
    rows = probe_lang(a.lang, eds)
    print(f"\n■ 目标语言 {a.lang} 在各版本的存量（按义项数排序）")
    print(f"  {'版本':6}{'本地语种名':22}{'义项数':>12}{'切片大小':>12}")
    print("  " + "-" * 54)
    for ed, n, c, sz, _ in rows:
        s = f"{sz/1048576:.1f} MB" if sz else "—"
        print(f"  {ed:6}{n[:20]:22}{c:>12,}{s:>12}")
    print("\n  下载命令（按需取，**别下整包** —— 整包通常大 2–20 倍）：")
    for ed, n, c, sz, u in rows[:6]:
        print(f"    curl -# -o dumps/{ed}wiktionary-{a.lang}.jsonl.gz '{u}'")
    print("\n  ⚠️ 同一语言在同一版本可能有多个本地名（如中文版的 西班牙語/西班牙语），列出的都要取。")


if __name__ == "__main__":
    main()
