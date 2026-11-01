#!/usr/bin/env python3
"""出版层中文的**安全**繁→简 —— 跨门共用一份（B29，2026-10-30）。

═══ 为什么不能整段 OpenCC ═══
B25（2026-10-29）：整段 `t2s` 在**本来就是简体**的文本上会改错 —— 转成扩展平面字形
（`宽翅鵟→宽翅𫛭`，多数字体是豆腐块）、改坏 GB2312 里的歧义字（卦名 `乾下艮上`、`覆上了雪`）。
⇒ 逐个位置决定收不收 OpenCC 的改动：
   ① 目标字不在 BMP ⇒ 不收；
   ② 原字不在 GB2312（方向无歧义，`國→国`）⇒ 收；
   ③ 原字在 GB2312 而 OpenCC 要改它（歧义区）⇒ 只有「这行是繁体文本」（含②那种字）才收，
      另有逐条裁决过的短语表：`OPENCC_RIGHT` 在简体文本里也收，`OPENCC_WRONG` 永远不收；
   ④ 繁简对举（`習 /习`、`首頁、首页`）⇒ 不收。

═══ B29 加的三条（fr/pt 干跑逐条读出来的）═══
   ⑤ 与假名相连的汉字串是**日文**（`飲む`）⇒ 不收；
   ⑥ 引号里只有一个汉字 ＝ 在**讲这个字本身**（`“雞”字在粤语中读作…`、量词`“頭”（tou）`）⇒ 不收；
   ⑦ `KEEP` 逐条裁决：讲繁体字本身的（`發 “发射”`／`髮 “头发”`）、五声音阶的 `徵`（读 zhǐ，不是「征」）、
      日文专名（`饂飩` `摺物` `篠笛` `小澤` `伊東`）；`FIX`：OpenCC 给错字的（`竹筴魚` 规范是 `竹荚鱼`，
      OpenCC 给扩展 A 区的 `䇲`）。

de 在 B25 写了第一份，ja／ru 各有自己一份（时间更早，判据同源）；本文件从 de 那份搬来，de 改为 import 这里。

自测：python3 scripts/zh_t2s.py
"""
import os
import re

import opencc

_T2S = opencc.OpenCC("t2s")

OPENCC_RIGHT = ("反覆", "重覆", "覆信", "乾性", "乾燥", "乾田", "乾苔", "鼠麴")   # `反复`/`干燥`…是规范写法
# 规范简体里**没有独立用法**的字：简体文本里出现就是漏转，照收（ru 同一张，从 OpenCC 字表枚举）。
ALWAYS = frozenset("後於夥摺醣菸麽捱徵藉彷俱")
OPENCC_WRONG = ("覆上", "覆住", "覆育", "慰藉", "狼藉", "枕藉",                  # 「盖」「养育」；`慰藉`仍写藉
                "覆盖", "覆蓋")                                                 # en `多重覆盖`：「重覆」子串命中了 OPENCC_RIGHT
NEVER = frozenset("薹樫筴篠噁")  # 薹：OpenCC 字表错（`薹草`是规范简体）；樫：日文「かし」→ 扩展 A `㭴`；筴：除 `竹筴`（FIX）外不明；
                              # 噁：**规范字**（通用规范汉字表收，化学专用：噁唑、二噁烷、噁英、噁草酮）—— OpenCC 按台湾用字
                              #   `噁心＝恶心` 一律转。2026-10-30 发现时 B29 已在 en/fr/es/it 转坏 550 处，`fix_chem_e.py` 改回；
                              #   只有「噁心」照转（FIX）
                              # 篠：OpenCC 给异体 `筿`，en 4 条全是日本姓氏地名（`篠田` `篠原踊`）
# 鍊：OpenCC 一律给「炼」，而台湾用字里它多半是「链」（`马可夫鍊` `拉鍊` `鍊接` `锚鍊` `鍊介壳虫`＝链蚧）。
#     只有这些才是「炼」：
LIAN_REFINE = ("锻鍊", "鍛鍊", "修鍊", "鍊金", "鍊丹", "精鍊", "提鍊", "鍊鋼", "鍊钢", "磨鍊", "熬鍊",
               "淬鍊", "冶鍊", "鍊油", "鍊铁", "鍊鐵", "鍊乳")
# ⑦ 逐条裁决（B29，fr/pt）。短语覆盖到的位置一律不动。
KEEP = ("）發 ", "）髮 ",                       # fr 例句在讲 發/髮 两字简化成同一个「发」
        "角 — 徵", "徵 — 羽", "角徵", "徵羽",    # 宫商角徵羽：徵 读 zhǐ
        "饂飩", "摺物", "篠笛", "小澤", "伊東", "kanji 漢字",
        "（蕎麦）", "一貫（",                      # es：日语词／日本旧重量单位「贯」
        "喫茶", "若者頭")                          # en：日本「喫茶店」（`满载喫水`→吃水 照收）／相扑「若者頭」
FIX = {"竹筴": "竹荚", "尾鞦": "尾鞧",          # OpenCC 给 `竹䇲`（扩展 A）／`马尾秋`（鞦韆的秋；这里是马具「后鞧」）
       # 模型拿繁简两种字形区分 salamandra／tritón 两种动物 ⇒ 一转就成了「蝾螈和蝾螈」；tritón 是水螈
       "蝾螈和蠑螈": "蝾螈和水螈",
       "侏儸": "侏罗",            # OpenCC 给扩展 A `侏㑩纪`
       "俥": "车",
       "噁心": "恶心"}                # en 全是轮机术语（`倒俥` `试俥` `俥钟`）；OpenCC 给扩展 A `伡`。⚠️ 象棋的「俥」出现了要回来改

_KANA = re.compile(r"[぀-ヿ]")
_HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_QUOTED_ONE = re.compile(r"[“‘「『\"]([㐀-鿿])[”’」』\"]")


def _gb(ch):
    try:
        ch.encode("gb2312")
        return True
    except UnicodeEncodeError:
        return False


def _hit(text, i, phrases):
    return any(text[j:j + len(p)] == p for p in phrases for j in range(max(0, i - len(p) + 1), i + 1))


# ⑧ 外语原词形写在括号里：前面紧挨着拉丁字母／谚文（`karoshi（過労死）` `Tōkyō（東京）` `역ᄉᆞ（歷史）`），
#    或前面正是它的简体（`李登辉（李登輝）`）
#    ko 的汉字表记用尖括号／方括号（`현시〈顯示〉` `운동<運動>` `袁世凯[袁世凱]`），一并算
#    括号里可以夹空格／谚文／破折号（ko `개체 수 피라미드（個體 數 피라미드）` `설사하다(泄瀉－)`），
#    前面可以隔一个收引号（`“자외선”(紫外線)`）
_PAREN_ORIG = re.compile(r"([A-Za-zÀ-ɏḀ-ỿᄀ-ᇿ가-힯][”’\"」』)]?|[㐀-鿿]+)\s*[（(〈<\[]"
                         r"([^（）()〈〉<>［］\[\]\n]*?[㐀-鿿][^（）()〈〉<>［］\[\]\n]*?)[）)〉>\]]")
# ⑩ 全角方括号 ＝ 词头的汉字/喃字写法（vi `［保領］` `［長］ → trưởng`；en 的 `［机］` 领域标签跟着不转，代价只是原状）
_FW_BRACKET = re.compile(r"［([^［］\n]+)］")
# ⑪ 整行只是一串汉字写法、且含扩展平面字（喃字）⇒ 是异体/喃字列表（vi `隱隱 𨏈𨏈 殷殷` `生𦠄 生機`）
_NOM_LIST = re.compile(r"^[\s,，、;；㐀-鿿\U00020000-\U0003ffff]+$")
_SUPP = re.compile(r"[\U00020000-\U0003ffff]")
# ⑪b 同音字表：≥3 项、每项一个字（可带括号里的简体）—— vi `儸 囉(啰) 攎 攞 欏(椤)…`。
#     同义词串（`厭倦，厭煩，發膩`）每项不止一个字，照转
_C1 = r"[㐀-鿿\U00020000-\U0003ffff](?:[(（][㐀-鿿][)）])?"
_CHAR_LIST = re.compile(r"^\s*%s(?:\s+%s){2,}\s*$" % (_C1, _C1))   # 只认空格分隔：`扒，剷，刮` 是同义词释义
# ⑨ 「X语／X文」后面引号里的词形（`日语“新聞”的罗马字`）
_QUOTED_ORIG = re.compile(r"[语語文][：:]?\s*[“「『\"]([㐀-鿿]+)[”」』\"]")


def _protected(text):
    """⑤⑥⑧⑨⑩⑪ 不许动的位置。"""
    if _CHAR_LIST.match(text):
        return set(range(len(text)))
    if _NOM_LIST.match(text) and _SUPP.search(text):
        items = [x for x in re.split(r"[\s,，、;；]+", text) if x]
        if len(items) >= 2 and all(len(x) <= 4 for x in items):   # `𢬗的漢字讀音` 是一句话不是列表
            return set(range(len(text)))
    keep = set()
    for m in _FW_BRACKET.finditer(text):
        keep.update(range(m.start(1), m.end(1)))
    for m in _QUOTED_ONE.finditer(text):
        keep.add(m.start(1))
    for m in _PAREN_ORIG.finditer(text):
        before, inner = m.group(1), m.group(2)
        if not _HAN.match(before[-1]) or _T2S.convert(inner) == before[-len(inner):] != inner:
            keep.update(range(m.start(2), m.end(2)))
    for m in _QUOTED_ORIG.finditer(text):
        keep.update(range(m.start(1), m.end(1)))
    for m in _KANA.finditer(text):                # 假名两侧连着的汉字串整串都算日文
        for step in (-1, 1):
            j = m.start() + step
            while 0 <= j < len(text) and _HAN.match(text[j]):
                keep.add(j)
                j += step
    return keep


def _t2s_once(text):
    out = _T2S.convert(text)
    if out == text or len(out) != len(text):      # OpenCC t2s 逐字等长；不等长就别信它
        return text
    trad_row = any(a != b and not _gb(a) for a, b in zip(text, out))
    keep = _protected(text)
    res = []
    for i, (a, b) in enumerate(zip(text, out)):
        if a == "鍊" and i not in keep and not _hit(text, i, KEEP):
            res.append("炼" if _hit(text, i, LIAN_REFINE) else "链")
        elif a == b or ord(b) > 0xFFFF or a in NEVER or i in keep or _hit(text, i, OPENCC_WRONG + KEEP):
            res.append(a)
        elif _gb(a) and not (trad_row or a in ALWAYS or _hit(text, i, OPENCC_RIGHT)):
            res.append(a)
        elif re.match(r"\s*[/／（(、]\s*" + re.escape(b), text[i + 1:i + 5]) or \
                re.search(re.escape(b) + r"\s*[/／（(、]\s*$", text[max(0, i - 4):i]):
            res.append(a)
        else:
            res.append(b)
    s = "".join(res)
    # ④ 词级的繁简对举（`首頁、首页`／`征用，徵用`，两种顺序）：逐字那一支只看紧邻的一个字
    for m in re.finditer(r"(?=([㐀-鿿]{2,4})(\s*[/／、，,]\s*)([㐀-鿿]{2,4}))", text):
        a, b = m.group(1), m.group(3)
        if a == b:
            continue
        ia, ib = m.start(), m.start() + len(a) + len(m.group(2))
        if _T2S.convert(a) == b:                  # 繁在前
            s = s[:ia] + a + s[ia + len(a):]
        elif _T2S.convert(b) == a:                # 简在前
            s = s[:ib] + b + s[ib + len(b):]
    return s


def t2s(s, cap=6):
    """**安全的**繁→简，转到收敛（`opencc` 短语切分依赖上下文，转一遍邻字变了下一遍会再变）。"""
    for k, v in FIX.items():
        s = s.replace(k, v)
    for _ in range(cap):
        out = _t2s_once(s)
        if out == s:
            return s
        s = out
    raise RuntimeError("t2s %d 轮仍不收敛：%r" % (cap, s[:60]))


_EXT = None


def ext_targets():
    """OpenCC 字表里「常用平面字 → **扩展平面**字」的目标字集合（815 个，从 OpenCC 自己的字表读，不手抄）。
    页面上出现它们，多半是整段 t2s 转出来的豆腐块（`鮟鱇→𩽾𩾌`）；回归闸拿它锁住 B25 不回来。"""
    global _EXT
    if _EXT is None:
        _EXT = set()
        for root, _d, fs in os.walk(os.path.dirname(opencc.__file__)):
            for f in fs:
                if f.startswith("TSCharacters") and f.endswith(".txt"):
                    for line in open(os.path.join(root, f), encoding="utf-8"):
                        a, b = line.rstrip("\n").split("\t")
                        _EXT.update(x for x in b.split() if len(x) == 1 and ord(x) > 0xFFFF
                                    and len(a) == 1 and ord(a) <= 0xFFFF)
        assert len(_EXT) > 500, "🔴 OpenCC 字表没读到（%d）—— 闸会空过" % len(_EXT)
    return _EXT


# 自测：每条都是 fr/pt/de 库里的真句子（或其片段）。左＝原文，右＝期望。
CASES = [
    ("國際音標", "国际音标"),
    ("宽翅鵟", "宽翅鵟"),                                   # ① 不转成扩展平面 𫛭
    ("乾下艮上", "乾下艮上"), ("反覆无常", "反复无常"),      # ③
    ("征收", "征收"), ("後裔", "后裔"),                       # ALWAYS
    ("習 /习", "習 /习"), ("首頁、首页", "首頁、首页"),        # ④
    ("飲む (nomu) 是五段动词。", "飲む (nomu) 是五段动词。"),  # ⑤
    ("“雞”字在粤语中读作", "“雞”字在粤语中读作"),            # ⑥
    ("则用量词“頭”（tou）。", "则用量词“頭”（tou）。"),
    ("fā（第一声）發 “发射” 和 fà（第四声）髮 “头发”", "fā（第一声）發 “发射” 和 fà（第四声）髮 “头发”"),  # ⑦
    ("宫 — 商 — 角 — 徵 — 羽。", "宫 — 商 — 角 — 徵 — 羽。"),
    ("狐饂飩，日式荞麦面", "狐饂飩，日式荞麦面"), ("日本姓氏，小沢或小澤", "日本姓氏，小沢或小澤"),
    ("大竹筴鱼", "大竹荚鱼"), ("马尾鞦", "马尾鞧"), ("马鞍尾鞦，尾带", "马鞍尾鞧，尾带"),
    ("征用，徵用", "征用，徵用"),                             # ④ 简在前
    ("包括蝾螈和蠑螈", "包括蝾螈和水螈"),
    # en（B29）
    ("多重覆盖问题", "多重覆盖问题"), ("重覆循环", "重复循环"), ("反覆无常的", "反复无常的"),
    ("马可夫鍊", "马可夫链"), ("档案鍊接", "档案链接"), ("锻鍊,训练", "锻炼,训练"), ("隐形拉鍊", "隐形拉链"),
    ("紧急倒俥试验", "紧急倒车试验"), ("黑侏儸纪", "黑侏罗纪"), ("炭中的黑樫", "炭中的黑樫"),
    ("爵士喫茶店", "爵士喫茶店"), ("满载喫水", "满载吃水"), ("若者頭，相扑界", "若者頭，相扑界"),
    ("二噁烷", "二噁烷"), ("磺胺异噁唑", "磺胺异噁唑"), ("令人噁心", "令人恶心"),
    ("轧麻筴机", "轧麻筴机"), ("頭城鎮（台湾地名）", "头城镇（台湾地名）"),
    ("日本的karoshi（過労死）概念", "日本的karoshi（過労死）概念"), ("地名Tōkyō（東京），在", "地名Tōkyō（東京），在"),
    ("韩语：역사（歷史）（yeoksa）", "韩语：역사（歷史）（yeoksa）"), ("李登辉（李登輝）于1923年", "李登辉（李登輝）于1923年"),
    ("新闻（日语“新聞”的罗马字）", "新闻（日语“新聞”的罗马字）"), ("日语姓氏篠田的转写", "日语姓氏篠田的转写"),
    ("DNA（脫氧核糖核酸）", "DNA（脫氧核糖核酸）"),     # ⑧ 偏宽的代价：缩写后的括号也不转 —— 留繁体只是原状，转错才是损坏
    ("脱氧核糖核酸（簡稱DNA）", "脱氧核糖核酸（简称DNA）"),
    ("현시〈顯示〉的漢字表記。", "현시〈顯示〉的汉字表记。"), ("袁世凯[袁世凱]的韩国汉字音读名", "袁世凯[袁世凱]的韩国汉字音读名"),
    ("汉字或谚汉混合表记：개체 수 피라미드（個體 數 피라미드）", "汉字或谚汉混合表记：개체 수 피라미드（個體 數 피라미드）"),
    ("汉字或谚汉混合表记：범상（犯上 凡常 犯狀） / 實力不凡", "汉字或谚汉混合表记：범상（犯上 凡常 犯狀） / 实力不凡"),
    ("取代漢字詞“자외선”(紫外線)", "取代汉字词“자외선”(紫外線)"), ("（= 설사하다(泄瀉－)）", "（= 설사하다(泄瀉－)）"),
    ("直系（종손 (宗孫, jongson)）和旁系孫輩", "直系（종손 (宗孫, jongson)）和旁系孙辈"),
    ("（= bảo lãnh）［保領］ 担保，保释", "（= bảo lãnh）［保領］ 担保，保释"), ("［長］ → trưởng, tràng", "［長］ → trưởng, tràng"),
    ("隱隱 𨏈𨏈 殷殷", "隱隱 𨏈𨏈 殷殷"), ("𢬗的漢字讀音", "𢬗的汉字读音"), ("veo (沋, 為, 漂, 𤅜)", "veo (沋, 為, 漂, 𤅜)"),
    ("(Quần đảo) 南沙群島（南中國海的群島）", "(Quần đảo) 南沙群岛（南中国海的群岛）"),
    ("儸 囉(啰) 攎 攞 欏(椤) 玀(猡)", "儸 囉(啰) 攎 攞 欏(椤) 玀(猡)"), ("厭倦，厭煩，發膩", "厌倦，厌烦，发腻"), ("扒，剷，刮", "扒，铲，刮"),
    ("日语词（蕎麦），指", "日语词（蕎麦），指"), ("重达到一貫（3.75千克）", "重达到一貫（3.75千克）"),
    ("（汉字 kanji 漢字）用于", "（汉字 kanji 漢字）用于"),
    ("的組織所裹挟", "的组织所裹挟"), ("下濛濛细雨", "下蒙蒙细雨"),   # 普通漏转照收
    ("agachar 的第一人稱複數（nós）將來時直陳式", "agachar 的第一人称复数（nós）将来时直陈式"),
]


def _selftest():
    bad = [(a, t2s(a), b) for a, b in CASES if t2s(a) != b]
    for a, got, want in bad:
        print("  🔴 %s → %s（期望 %s）" % (a, got, want))
    print("  zh_t2s 自测 %d/%d" % (len(CASES) - len(bad), len(CASES)))
    return not bad


if __name__ == "__main__":
    raise SystemExit(0 if _selftest() else 1)
