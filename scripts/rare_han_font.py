#!/usr/bin/env python3
"""罕用汉字兜底字体：从十门库里收出扩展 B 以后的字，切成按需下载的小字体；同一份文件也是闸。B29，2026-10-31。

═══ 缺陷 ═══
库里有 7,426 种**扩展 B 及以后**的汉字（越南语喃字、日语引的古字、元素名、鸟名鱼名……），
本机 428 个字体文件里有 3,385 种**一个字形都没有** ⇒ 页面上是豆腐块。
数据是对的（这些是引文、是源头原字），**不能拿别的字替换** —— 只能给页面配字形。

═══ 做法（Google Fonts 那套切片）═══
· 源字体：Plangothic（遍黑体）V2.9.5795，SIL OFL 1.1，两个文件覆盖扩展 B–I（实测 7,426/7,426）。
  ⚠️ 它**有意不含扩展 A 与基本区新增**（设计成给思源黑体一类字体补缺）——那两段系统中文字体都有，
  本机 3,385 个缺字形全在 U+20000 以上 ⇒ 本脚本的边界就是 `FLOOR = U+20000`。
· 只取**库里真出现的字**，按源文件分组、每 `SLICE` 字切一片 woff2，`@font-face` 的 `unicode-range`
  逐字列出 ⇒ 浏览器**只在页面上真出现某片里的字时才下载那一片**，普通页面一个字节不多下。
· 字族名 `SD Rare Han`，插在 `styles.css` 每个字体栈的通用族名前面：前面列的字体有字形就用前面的，
  都没有才轮到它（OFL 允许改名发布子集；它没有声明保留字体名）。
· OFL 要求随字体附许可证全文 ⇒ `LICENSE-OFL.txt` 与切片放在一起，闸查它在。

═══ 闸（`npm run gate:rare-han`）═══
  R1  库里每个 ≥ U+20000 的汉字都在切片里（数据侧：新收了一个生僻字就红 ⇒ 重跑 `--build`）
  R2  每片 woff2 的字表 ＝ manifest 记的那片 ＝ CSS 里那片的 `unicode-range`（三份对得上）
  R3  `styles.css` 里每个以通用族名结尾的字体栈都带着 `SD Rare Han`，且在通用族名之前
  R4  `main.tsx` 引入了 `rare-han.css`
  R5  许可证全文在；目录里没有 manifest 之外的残留切片
扫库按**库文件的大小＋修改时间**缓存（`data/work/fonts/rare_scan_cache.json`）：库没写过就复用，
写过库自动重扫（全扫十门约 30 分钟，主要是 en/ru/fr/de 的大表）。

用法（在仓库根）：
    python3 -u scripts/rare_han_font.py --build     # 扫库（走缓存）→ 生成切片、CSS、manifest
    python3 -u scripts/rare_han_font.py             # 闸
    python3 -u scripts/rare_han_font.py --mutate    # 闸 ＋ 变异验证
"""
import hashlib
import io
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANGS = ("en", "es", "it", "fr", "pt", "de", "ja", "ko", "vi", "ru")
FAMILY = "SD Rare Han"
FLOOR = 0x20000                       # 扩展 B 起；以下交给系统字体（见文件头）
SLICE = 100
SRC_DIR = ROOT / "data/work/fonts/plangothic"
SRC = {  # 文件名 → sha256（换版本必须改这里，闸才认）
    "PlangothicP1-Regular.ttf": "550b5d0775b15405946b18f4843df439a51e69508d7e6778d94c1f7a53dc5ad6",
    "PlangothicP2-Regular.ttf": "681933370adfe0fc7253f77735275a82fea09fe4f8adba907bdeb46c110daf8f",
}
SRC_URL = "https://github.com/Fitzgerald-Porthmouth-Koenigsegg/Plangothic_Project/releases/tag/V2.9.5795"
OUT_DIR = ROOT / "apps/web/public/fonts/rare-han"
URL_BASE = "/fonts/rare-han/"
CSS = ROOT / "apps/web/src/rare-han.css"
STYLES = ROOT / "apps/web/src/styles.css"
MAIN = ROOT / "apps/web/src/main.tsx"
MANIFEST = OUT_DIR / "manifest.json"
LICENSE = "LICENSE-OFL.txt"
CACHE = ROOT / "data/work/fonts/rare_scan_cache.json"
GENERIC = ("sans-serif", "serif", "monospace")


def is_rare(ch):
    """判据只此一份：码位 ≥ U+20000 且是汉字（扩展 B 及以后的表意文字平面，SIP/TIP）。"""
    o = ord(ch)
    return FLOOR <= o < 0x40000


# ══════ 数据侧 ══════

def db_of(lang):
    r = subprocess.run([sys.executable, "-B", "-c", "import paths; print(paths.DB)"],
                       cwd=ROOT / lang, capture_output=True, text=True, check=True)
    return Path(r.stdout.strip().splitlines()[-1])


def scan_db(db):
    """一个库里出现的全部罕用字。所有表的所有文本列都扫（超集：多切几个字不花读者一个字节）。"""
    out = set()
    c = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    try:
        tabs = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for t in tabs:
            for r in c.execute('PRAGMA table_info("%s")' % t).fetchall():
                if r[2] and "TEXT" not in r[2].upper():
                    continue
                for (v,) in c.execute('SELECT "%s" FROM "%s"' % (r[1], t)):
                    if isinstance(v, str) and v and max(v) >= "\U00020000":
                        out.update(ch for ch in v if is_rare(ch))
    finally:
        c.close()
    return out


def data_chars(verbose=True):
    """→ {字: [语种…]}。按库文件大小＋mtime 缓存。"""
    try:
        cache = json.loads(CACHE.read_text())
    except (OSError, ValueError):
        cache = {}
    res = {}
    for lang in LANGS:
        db = db_of(lang)
        if not db.exists():
            continue
        st = db.stat()
        key = "%d:%d" % (st.st_size, st.st_mtime_ns)
        hit = cache.get(lang)
        if hit and hit["key"] == key:
            chars = hit["chars"]
        else:
            if verbose:
                print("   扫 %s（库变过，重扫）…" % lang, flush=True)
            chars = "".join(sorted(scan_db(db)))
            cache[lang] = {"key": key, "chars": chars}
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(cache, ensure_ascii=False))
        for ch in chars:
            res.setdefault(ch, []).append(lang)
    return res


# ══════ 生成 ══════

def _src_fonts():
    from fontTools.ttLib import TTFont
    fonts = {}
    for name, sha in SRC.items():
        p = SRC_DIR / name
        if not p.exists():
            raise SystemExit("🔴 源字体不在：%s（从 %s 下载）" % (p, SRC_URL))
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        if got != sha:
            raise SystemExit("🔴 源字体 sha256 对不上：%s（换版本要改 SRC）" % name)
        fonts[name] = TTFont(p)
    return fonts


def _ranges(cps):
    """码位列表 → `U+XXXX` / `U+XXXX-YYYY` 串。"""
    cps = sorted(cps)
    out, i = [], 0
    while i < len(cps):
        j = i
        while j + 1 < len(cps) and cps[j + 1] == cps[j] + 1:
            j += 1
        out.append("U+%X" % cps[i] if i == j else "U+%X-%X" % (cps[i], cps[j]))
        i = j + 1
    return ",".join(out)


def build():
    from fontTools import subset
    want = data_chars()
    fonts = _src_fonts()
    cmaps = {n: f.getBestCmap() for n, f in fonts.items()}
    by_src = {n: [] for n in SRC}
    lost = []
    for ch in sorted(want):
        src = next((n for n in SRC if ord(ch) in cmaps[n]), None)
        (by_src[src] if src else lost).append(ord(ch))
    if lost:
        raise SystemExit("🔴 源字体没有这些字（%d）：%s" % (len(lost), "".join(map(chr, lost[:50]))))
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)
    slices, css = [], []
    for n, cps in by_src.items():
        tag = "p1" if "P1" in n else "p2"
        for k in range(0, len(cps), SLICE):
            part = cps[k:k + SLICE]
            fname = "rh-%s-%02d.woff2" % (tag, k // SLICE)
            from fontTools.ttLib import TTFont
            ft = TTFont(SRC_DIR / n)
            o = subset.Options()
            o.flavor = "woff2"
            o.layout_features = []
            o.notdef_outline = True
            o.drop_tables += ["FFTM"]
            o.name_IDs = [0, 13, 14]          # 版权＋许可证说明（OFL 要求随附）；字族名下面改
            sub = subset.Subsetter(o)
            sub.populate(unicodes=part)
            sub.subset(ft)
            ft["name"].setName(FAMILY, 1, 3, 1, 0x409)
            ft["name"].setName("Regular", 2, 3, 1, 0x409)
            ft["name"].setName(FAMILY.replace(" ", "") + "-" + fname[:-6], 6, 3, 1, 0x409)
            ft.flavor = "woff2"
            ft.save(OUT_DIR / fname)
            slices.append({"file": fname, "src": n, "chars": "".join(map(chr, part))})
            css.append("@font-face {\n  font-family: '%s';\n  src: url('%s%s') format('woff2');\n"
                       "  font-display: swap;\n  unicode-range: %s;\n}" % (FAMILY, URL_BASE, fname, _ranges(part)))
    shutil.copy(SRC_DIR / LICENSE, OUT_DIR / LICENSE)
    MANIFEST.write_text(json.dumps({
        "family": FAMILY, "source": SRC_URL, "license": "SIL OFL 1.1",
        "src_sha256": SRC, "floor": "U+%X" % FLOOR, "slices": slices}, ensure_ascii=False, indent=1))
    CSS.write_text(
        "/* 由 scripts/rare_han_font.py --build 生成，勿手改。罕用汉字（扩展 B 及以后）兜底字体：\n"
        "   Plangothic（SIL OFL 1.1，许可证见 public/fonts/rare-han/LICENSE-OFL.txt）的按需切片。\n"
        "   每片只在页面上真出现它的字时才下载。 */\n" + "\n".join(css) + "\n")
    tot = sum((OUT_DIR / s["file"]).stat().st_size for s in slices)
    print("■ 生成 %d 片、%d 字、合计 %.0f KB（单片最大 %.0f KB）" % (
        len(slices), sum(len(s["chars"]) for s in slices), tot / 1024,
        max((OUT_DIR / s["file"]).stat().st_size for s in slices) / 1024))


# ══════ 闸 ══════

def _css_slices(text):
    """CSS → {文件名: set(码位)}。"""
    out = {}
    for m in re.finditer(r"url\('%s([^']+)'\)[^}]*?unicode-range:\s*([^;]+);" % re.escape(URL_BASE), text, re.S):
        cps = set()
        for part in m.group(2).split(","):
            a, _, b = part.strip()[2:].partition("-")
            cps.update(range(int(a, 16), int(b or a, 16) + 1))
        out[m.group(1)] = cps
    return out


def _font_cps(path):
    from fontTools.ttLib import TTFont
    return {cp for cp in TTFont(path).getBestCmap() if cp >= FLOOR}


def stacks(text):
    """styles.css 里每个字体栈 → [(行号, 栈文本)]。"""
    return [(text[:m.start()].count("\n") + 1, " ".join(m.group(2).split()))
            for m in re.finditer(r"(font-family|--[\w-]*font)\s*:\s*([^;]+);", text)]


def stack_bad(stack):
    """含通用族名的栈：必须带 FAMILY，且紧贴在**第一个**通用族名前面。→ 问题描述或 None。
    🔴 第一版只查「以通用族名结尾」的栈 ⇒ `'A', serif, 'SD Rare Han'` 结尾不是通用族名，被放过（M5 逮到）；
       浏览器走到 `serif` 就交给系统兜底，排在它后面的兜底字体永远轮不到。"""
    parts = [p.strip().strip("'\"") for p in stack.split(",")]
    gen = [i for i, p in enumerate(parts) if p in GENERIC]
    if not gen:
        return None                  # `var(--x)` 引用：判它指向的变量定义
    if FAMILY not in parts:
        return "没带 %s" % FAMILY
    if parts.index(FAMILY) != gen[0] - 1:
        return "%s 不在第一个通用族名正前面" % FAMILY
    return None


def check(state):
    """state：{data, manifest, css, fonts{文件: 码位}, files, styles, main, license}。→ {判据: [问题]}"""
    bad = {k: [] for k in ("R1", "R2", "R3", "R4", "R5")}
    man = {s["file"]: {ord(c) for c in s["chars"]} for s in state["manifest"]["slices"]}
    have = set().union(*man.values()) if man else set()
    miss = sorted(c for c in state["data"] if ord(c) not in have)
    if miss:
        bad["R1"].append("库里有 %d 个罕用字不在切片里：%s ⇒ 重跑 --build" % (len(miss), "".join(miss[:30])))
    css = state["css"]
    for f, cps in man.items():
        if state["fonts"].get(f) != cps:
            bad["R2"].append("%s：字体文件的字表与 manifest 不一致" % f)
        if css.get(f) != cps:
            bad["R2"].append("%s：CSS 的 unicode-range 与 manifest 不一致" % f)
    for f in set(css) - set(man):
        bad["R2"].append("CSS 引用了 manifest 里没有的片 %s" % f)
    for line, st in stacks(state["styles"]):
        why = stack_bad(st)
        if why:
            bad["R3"].append("styles.css:%d %s：%s" % (line, why, st))
    if not re.search(r"""^import\s+['"]\./rare-han\.css['"];?\s*$""", state["main"], re.M):
        bad["R4"].append("main.tsx 没有 import './rare-han.css'")
    if not state["license"]:
        bad["R5"].append("切片目录里没有 %s（OFL 要求随附）" % LICENSE)
    extra = set(state["files"]) - set(man) - {LICENSE, MANIFEST.name}
    if extra:
        bad["R5"].append("切片目录里有 manifest 之外的残留：%s" % sorted(extra))
    return bad


def load_state(verbose=True):
    if not MANIFEST.exists():
        raise SystemExit("🔴 还没生成：先跑 --build")
    manifest = json.loads(MANIFEST.read_text())
    return {
        "data": data_chars(verbose),
        "manifest": manifest,
        "css": _css_slices(CSS.read_text()) if CSS.exists() else {},
        "fonts": {s["file"]: _font_cps(OUT_DIR / s["file"]) for s in manifest["slices"]
                  if (OUT_DIR / s["file"]).exists()},
        "files": [p.name for p in OUT_DIR.iterdir()],
        "styles": STYLES.read_text(),
        "main": MAIN.read_text(),
        "license": (OUT_DIR / LICENSE).exists(),
    }


def report(bad):
    n = 0
    for k, v in bad.items():
        for x in v:
            print("   🔴 %s %s" % (k, x))
            n += 1
    return n


def mutate(state):
    import copy
    cases = []
    first = state["manifest"]["slices"][0]
    victim = first["chars"][0]

    def m1(s):   # 库里出现一个切片里没有的字
        s["data"]["\U0002FFFD"] = ["xx"]
    cases.append(("M1 库里新出现一个切片里没有的罕用字 → R1", "R1", m1))

    def m2(s):   # 字体文件丢了一个字
        s["fonts"][first["file"]] = s["fonts"][first["file"]] - {ord(victim)}
    cases.append(("M2 字体文件少了一个字 → R2", "R2", m2))

    def m3(s):   # CSS 的 unicode-range 漏了一个字
        s["css"][first["file"]] = s["css"][first["file"]] - {ord(victim)}
    cases.append(("M3 CSS 的 unicode-range 漏了一个字 → R2", "R2", m3))

    def m4(s):   # 某个字体栈把兜底字体删了
        s["styles"] = s["styles"].replace("'%s', " % FAMILY, "", 1)
        assert s["styles"] != state["styles"], "M4 空操作：styles.css 里找不到 '%s', " % FAMILY
    cases.append(("M4 一个字体栈丢了兜底字体 → R3", "R3", m4))

    def m5(s):   # 兜底字体放到了通用族名后面
        s["styles"] += "\n.x { font-family: 'A', serif, '%s'; }\n" % FAMILY
    cases.append(("M5 兜底字体排在通用族名后面 → R3", "R3", m5))

    def m6(s):
        s["main"] = re.sub(r"""^import\s+['"]\./rare-han\.css['"];?\s*$""", "", s["main"], flags=re.M)
    cases.append(("M6 main.tsx 不再引入 rare-han.css → R4", "R4", m6))

    def m7(s):
        s["license"] = False
    cases.append(("M7 许可证文件不在 → R5", "R5", m7))

    def m8(s):
        s["files"] = s["files"] + ["rh-p9-99.woff2"]
    cases.append(("M8 目录里多一个残留切片 → R5", "R5", m8))

    fails = 0
    for label, rule, fn in cases:
        s = copy.deepcopy(state)
        fn(s)
        hit = bool(check(s)[rule])
        fails += not hit
        print("   %s %s" % ("✅" if hit else "🔴 没逮到：", label))
    print("\n变异 %d/%d 逮到" % (len(cases) - fails, len(cases)))
    return fails


def main():
    if "--build" in sys.argv:
        build()
        return
    state = load_state()
    n = report(check(state))
    man = state["manifest"]["slices"]
    print("%s 罕用字兜底字体：库里 %d 字、切片 %d 片 %d 字%s" % (
        "🔴" if n else "✅", len(state["data"]), len(man), sum(len(s["chars"]) for s in man),
        "，%d 处不对" % n if n else ""))
    if n:
        raise SystemExit(1)
    if "--mutate" in sys.argv:
        print("\n■ 变异验证")
        if mutate(state):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
