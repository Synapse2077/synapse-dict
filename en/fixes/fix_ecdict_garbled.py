#!/usr/bin/env python3
"""ECDICT 的中文里有一批**乱码字**：码位落在扩展 C 区（U+2A9xx 一带），字形与上下文毫无关系。en，2026-10-30。

═══ 缺陷 ═══
    仅能𪤛口的生活          → 糊口          异𪤆唑𪧀            → 异噁唑鎓（isoxazolium）
    螲𪤅科（Ctenizidae）    → 螲蟷科        毛脚𪤢（Buteo）      → 毛脚鵟
多数字体没有这些字 ⇒ 页面上是豆腐块；有字形的字体里它们也是别的字。B29 量字体覆盖时撞见的
（扩展平面 215 种字里 98 种本机没有任何字体，其中这一簇是 ECDICT 自己的编码错位，不是罕用字）。

═══ 判据：逐字裁决的映射表，只收「上下文能定」的 ═══
每个字都在它出现的每一行上下文里对过（拉丁学名／英文词头／同一行别处的写法），见 `MAP` 的注释。
⚠️ 有意**不**收的（12 来个）：单字科名（`𪧁科` `𪩅科` `地𪪅科` `讯𪪔科`）、`𪥠(105号元素𪨬的别称)` 等 ——
   上下文定不了，猜一个鱼科名印上去是「看起来很权威的错」（`[[dict-framework-doc]]`：错比缺更伤权威）。
⚠️ 换成**现在显示得出来**的字形（`鮄` `鰶` `鵟`），不换成规范简体（`𫚒` `𫚶` `𫛭`）——
   后者在扩展平面，本机字体没有，换过去还是豆腐块。B29 的安全繁简判据也不会把它们转过去（目标不在 BMP 不收）。

只改出版层 `sense_gloss`，证据层 `sense_src` 一个字不动。

跑（在仓库根）：
    python3 -u en/fixes/fix_ecdict_garbled.py            # 干跑
    python3 -u en/fixes/fix_ecdict_garbled.py --apply
"""
import sys as _sys
import pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))

import argparse
import sqlite3

import dbtool
import paths

MAP = {
    "𪤅": "蟷",   # 螲蟷科 Ctenizidae（trap-door spider ×2）
    "𪤆": "噁",   # 异噁唑 isoxazole
    "𪧀": "鎓",   # 异噁唑鎓 isoxazolium／硝鎓离子 nitronium
    "𪤗": "鮄",   # 豹鲂鮄目 Dactylopteriformes／黄鲂鮄科 Peristediidae（模型对同一词写的就是鲂鮄）
    "𪤚": "魟",   # 鳐(魟)目 Batoidea／魟科 Dasyatidae／燕魟科 Gymnuridae
    "𪤛": "糊",   # 糊口（bare livelihood／supperless ×2／hungry-poor）
    "𪤝": "鰶",   # gizzard shad 无齿鰶／真鰶 Dorosoma
    "𪤢": "鵟",   # 毛脚鵟 Buteo lagopus
    "𪤮": "梭",   # 梭鲈属 Stizostedion／大眼梭鲈 walleye
    "𪤷": "鱚",   # 鼠鱚目 Gonorynchiformes
    "𪧫": "鰕",   # 鰕虎鱼亚目 Gobioidei
    "𪨂": "蟌",   # 色蟌科 Agrionidae
    "𪩘": "姆",   # 达勒姆 Durham
    "𪩜": "鳽",   # 日鳽科 Eurypygidae（sunbittern）
    "𪩿": "鳽",   # 大麻鳽 bittern（bull of the bog）—— 两个乱码码位都是「鳽」，各自的上下文都能定
    "𪩧": "牻",   # 牻牛儿苗科 Geraniaceae
    "𪪆": "铈",   # 钙钇铈矿 kainosite-(Y)
    "𪪉": "酐",   # 钼酐 molybdic anhydride
    "𪪘": "伞",   # 伞形绒毛蓼 Eriogonum umbellatum
    "𪪚": "鯻",   # 鯻科 Theraponidae
    "𪪝": "楤",   # 裸茎楤木 Aralia nudicaulis
    "𪤔": "鮰",   # 鮰 Ictalurus（黑鮰 black bullhead／青鮰 blue catfish）／黄石鮰 stonecat
    "𪤇": "鮨",   # 美洲石鮨 Morone americana（white perch，鮨科）
    "𤟥": "缇",   # 灵缇 greyhound／狐缇
    "𧍃": "蜚",   # 马得拉蜚蠊 Leucophaea maderae
}


def plan(con):
    out = []
    for rid, t in con.execute("SELECT rowid, text FROM sense_gloss WHERE lang='zh'"):
        if t and any(c in MAP for c in t):
            out.append((rid, t, "".join(MAP.get(c, c) for c in t)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    todo = plan(con)
    con.close()
    for rid, old, new in todo:
        print("   %8d  %s\n             → %s" % (rid, old[:60], new[:60]))
    print("■ 要改 %d 行（映射 %d 个乱码字）" % (len(todo), len(MAP)))
    if not a.apply or not todo:
        return
    with dbtool.session("en-fix-ecdict-garbled") as s:
        s.executemany("UPDATE sense_gloss SET text=? WHERE rowid=?", [(new, rid) for rid, _o, new in todo])
    con = sqlite3.connect("file:%s?mode=ro" % paths.DB, uri=True)
    left = len(plan(con))
    print("■ 写后回核：出版层仍含映射表里的乱码字 %d 行（期望 0）" % left)
    if left:
        raise SystemExit("🔴 回核红")


if __name__ == "__main__":
    main()
