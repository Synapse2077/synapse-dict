#!/usr/bin/env python3
"""俄语写库闸门 —— 备份 / 保留策略 / 不变量核对 / 抽样反验。ru 专用，不 import 其他语种。

本文件是 `vi/dbtool.py` 的**拷贝 + 改语种特有部分**，不是 import ——
铁律①「按本质设计，按语种解耦，互不引用；每个语种一套脚本，宁可重复不要耦合」。

🔴 **为什么拷 vi 那份，理由与语言无关**（用户 2026-09-28 对上一门说过：
   「你不要习惯性拿上一门当模板」—— 所以这里写清楚**这一层**选 vi 的工程理由）。
   俄语和越南语在语言学上几乎没有共同点（俄语重屈折、西里尔字母；越南语无屈折、拉丁字母），
   `docs/RU_PLAN.md` §0.5 是一张**按层选模板**的表。这一层选 vi 的理由只有一条：
   **九门里只有 vi 这份同时带着下面四样东西**，拷别门＝开局继承已知 bug。

     · **B6** `__main__` 在「库还不存在」时 `KeyError` —— 这正是开新语种第一天的状态，
       七门原样欠着，ko 修了、vi 继承（见文件末 `__main__`）。
     · **B7** `_track_audit()` 只审计列、不审计表 —— ja/en/de/pt 四门的 `TRACK_TABLES`
       里都躺着库里没有的 `pronunciation_entry`。
     · **K31 的欠账机制**（`_gate_debt`）—— 写库之后自动把过期的闸记成欠账，
       判据是「写了哪张表」而不是「哪些计数变了」（纯内容 UPDATE 穿过计数型判据）。
     · **收词闸**（`invalidates=`）—— `__rows__>0` 必须显式声明让哪些层过期了。
       俄语要收的词形是九门里最多的一门，这道闸比在 vi 上更要紧。

🔴🔴 **拷过来当天就修掉了 vi/ko 两门里的两处同源 bug（B22）**：
   `backup()` 在库不存在时返回 `None`（新语种第一次建库的正常状态），
   而 `session()` 的两条**错误路径**都直接拿它当 Path 用 ⇒ `AttributeError`：
     ① 异常回滚那一路 `bak.unlink()`      ⇒ **把真正的建库报错挤到第二条**
     ② 闸红那一路     `bak.exists()`      ⇒ **闸的结论整个印不出来**
   两处都只在**「新语种的第一次建库」＋「出错」**同时成立时才发作 —— 也就是
   **只有今天这一天会撞上**，而撞上时它遮住的正是我最需要看到的那条消息。
   ⚠️ ②里面还留着 `if bak:` 的死分支（作者想处理 None，但判空写在了 `.exists()` 之后），
      是「想到了、位置放错了」的化石。⇒ 已记进 `docs/BACKLOG.md` **B22**，vi/ko 待修。

⚠️ `PLAYBOOK` 1.4：「不能推后。es 是先修了一周数据才有闸门的，那一周的写库全部无法追溯。」
   所以这是俄语的第二个代码文件（第一个是 `paths.py`），排在任何数据动作前面
   —— 现在库还不存在。

═══ 🔴 最关键的一条：未声明的列必须零变化 ═══
`expect` 里没写的列，写库前后非空计数**必须完全相同**，否则报错退出。
`expect` 是**增量**不是总数。

═══ 🔴🔴🔴 ru 的头号陷阱：**归一不许用 NFD**，与 vi 方向相反 ═══
vi 那份的 `norm_vi()` 是「NFD 之后去掉所有组合符」，**在越南语上是正解**
（带调元音要拆开才看得见基字母）。把同一个工具搬到俄语上是**灾难**：

    'й' = U+0439  单码位 ──NFD──▶ и + U+0306        去组合符 ⇒ 'и'   ✘ 毁掉一个字母
    'ё' = U+0451  单码位 ──NFD──▶ е + U+0308        去组合符 ⇒ 'е'   ✘ 毁掉辨义

`й` 是俄语字母表里独立的第 11 个字母（不是 и 的变体）；`ё` **辨义**：
`всё`（一切）/`все`（所有人）、`совершённый`（完成体）/`совершенный`（完美的）。
阶段 -1 实测 ru 版释义里 ё 出现率 **4.66%** —— 它真的在数据里。

⇒ 本文件的 `norm_ru()` **只去 U+0301 重音符**（源头给词头标的重读位置，`ко́шка`），
  **一个组合符一个组合符地列**，不走「去掉所有组合符」那条路。
⚠️ vi 那门归一出事的代价是现成的：`word_norm` 冲突 1,263 组 ⇒
   **1,291 个页面打不开、而且显示的是别的词的内容**。俄语词形更多，同类事故更大。
🔴 **这条已经做成断言**（见 `_norm_selfcheck()`，**import 时就跑**）：
   谁把 `norm_ru` 改回 NFD 版，`import dbtool` 当场炸。
   `[[lesson-must-become-mechanism]]`：教训的交付物是会自己响的东西，不是一段注释。

═══ 🔴🔴 `has_han` / `norm_vi` 这两个名字在本文件里**故意不存在** ═══
从别门拷来的脚本必然写着 `dbtool.norm_vi(...)` 或 `dbtool.has_han(...)`。
留着同名函数会**静默给出错误答案**；不提供它，`AttributeError` 当场炸。
（ja/ko/vi 三门删 `has_han` 的同一个理由，这里多删一个 `norm_vi`。）

═══ ⭐ 「这段文本是不是中文」在 ru 上**反而简单**，别照搬 ko/vi 的机制 ═══
ko/vi 上这个判据很难，因为韩语汉字/汉越字/喃字**就是表意文字**，字形上分不出中越，
所以那两门的 `is_chinese_text(s, src)` 强制调用方给 `src`、给不出就抛异常。

俄语**不存在这个问题**：西里尔和表意文字是两套不相交的字符系统。
⇒ 本文件的 `is_chinese_text(s)` **不要 `src`**。照搬那条「必须给 src」会逼每个调用方
  编一个 `src` 出来，而编出来的 src 比字形判据更不可靠。
⚠️ 但**「是中文」≠「是可用的中文释义」**是另一件事，ko 的 K24 栽在那儿
  （「白送中文释义 206,091 条」**97.2% 是元描述**，中文覆盖率 74% → 2.11%）。
  那个判据归阶段 5，不在本文件里，也不许拿 `is_chinese_text` 当它用。
"""
import os
import re
import shutil
import sqlite3
import sys
import time
import unicodedata as ud
from contextlib import contextmanager
from pathlib import Path

import paths

HERE = Path(__file__).resolve().parent
DB = paths.DB
TABLE = "dict"

# 追踪的列：写库前后都会计数。**不在这张表里的列，出了问题不会被发现**。
#
# 🔴🔴 **条目可以写 `列` 或 `表.列`**（ja 2026-09-16 大改留下的形状）。
#    ja 改之前列了 23 个列名而 `snapshot()` 只在 `dict` 上找 ⇒ **实际守住 4 个**。
#    `_track_audit()` 现在会把死条目大声报出来。
#
# 🔴🔴 **本清单现在只有「阶段 0 之前能确定的那几列」，不是从 vi 抄来的全集。**
#    ru 的 schema 要到阶段 0 才定死。此刻把一堆猜的列名写进来，`snapshot()` 会
#    静默跳过它们，于是清单**看起来**覆盖着十几个字段而一个都没守 —— 那正是 ja 栽的跤。
#    ⇒ 规矩：**一层建出来，当天把它的列加进这张表**；建库之后跑一次本文件的 `__main__`，
#      `_track_audit()` 会告诉你实际守住了几列。别等项目做完才数。
#
# 🔴 **别照搬任何一门的形态/读音列**（`[[es-v3-structure-backfill]]`：
#    照搬别的语言结构前，先量这门语言有没有那个病）。
#    ⚠️ 下面这几行是**待量的提问，不是已知的答案** —— 阶段 -1 的探针回答它们：
#      · **屈折层**：俄语 6 格 × 2 数 × 3 性、动词体/分词 ——
#        de 收屈折形进 `dict` ⇒ 120 万词形 / `inflection` 536 万行，俄语预计更大。
#        🔴 这是 `RU_PLAN` §0.4 **要用户先拍板**的第一件事：它改变覆盖率的分母，
#        也就定死了「要给多少条义项买中文」。**没拍板之前不许建这一层的列。**
#      · **重音位置**：俄语重音辨义（`замо́к` 锁 / `за́мок` 城堡）且屈折时会移动。
#        它是不是一等字段、存在哪张表 —— 阶段 -1 量「词头带不带 U+0301」之后再定。
#      · **体（aspect）**：видовые пары 是关系层的新 `kind` 还是单独一张表（§0.4 第三件）。
#      · **ё**：`word` 里带 ё 的词形要不要同时存一个 е 写法的检索别名 ——
#        见 `norm_ru()` 的注释，**那是检索层的决定，不是归一层的**。
TRACK = [
    # ── 骨架层（阶段 0/1 建 `dict` 时就该有）。先只列这三个**现在就确定**的 ──
    # 检索归一键。🔴 它的生成函数 `norm_ru()` 带 import 时自检（NFD 禁区），
    #    而这一列盯的是「有没有人把它写空」。两件事都要有人管。
    'word_norm',
    'is_lemma',          # 词元 / 屈折形。俄语上这一列**决定一切覆盖率的分母**
    'pos',
    # ── 下面的列**等阶段 0 的 schema 定了当天往这儿加**，现在故意留空 ──
]
TRACK_TABLES = [
                # 🔴 这里列的是**出版层的表**，每张的行数都被逐张盯着。
                #    ru 此刻一张都还没建 —— `snapshot()` 会跳过不存在的表，这是安全的；
                #    但**建出一张就要当天列进来一张**，否则它被清空也不会有人说话。
                #    ja 的 `etymology` 整层缺席三个月而阶段表全 ✅，就是这个形状：
                #    **阶段表对没列进去的层结构性失明。**
                #
                # 🔴🔴 **这张名单也是空的，而且这是有意的。**
                #    从 vi 拷过来会带着 `han_spelling`/`nom_spelling`/`noun_classifier`
                #    三张**俄语根本不会有的表**，以及一条「`inflection` 有意不建」的否定结论
                #    —— 那条结论在俄语上**正好相反**（`RU_PLAN` §0.5「别照搬的」）。
                #    死条目的代价见 B7：ja/en/de/pt 四门的名单里躺着库里没有的
                #    `pronunciation_entry`，行数闸对它完全失明。
                #    ⇒ 阶段 0 建出 schema 的那一天，逐张往这儿加。
                ]

def _cols(conn, table=None):
    return {r[1] for r in conn.execute("PRAGMA table_info(%s)" % (table or TABLE))}


def _track_audit(conn, verbose=True):
    """🔴🔴 **TRACK 里哪条在哪张表都找不到 —— 大声说出来。**

    `snapshot()` 有一条「找不到的列就跳过」，那是给「先写进清单、再建出来」留的口子。
    合理，但它让**「名字写错了」和「还没建出来」长得一模一样** ——
    2026-09-16 发现 ja 的 TRACK 列了 23 个字段而**实际只守住 4 个**：
    另外 19 个（日语全部的一等字段 kana/romaji/ipa/pitch_*）住在 `entry`/`pronunciation` 上，
    而 `snapshot` 只在 `dict` 上找。它们静静躺了整个项目，一次都没守过。

    ⇒ 这个函数把死条目报出来。**库已经建完之后还找不到的，就是死条目。**

    ═══ 🔴🔴 2026-09-20：ja 那次只修了**列**那一半，`TRACK_TABLES` 没人审计 ═══
    开 ko 建完库当天就撞见：`TRACK_TABLES` 里列着 `pronunciation_entry`，
    而我的 schema 没建它 —— `snapshot()` 照样静默跳过，快照里连个空位都没有。
    回头查另七门：**这张表只有 `it` 真实存在（282,060 行），
    而 ja / en / de / pt 四门的 `TRACK_TABLES` 里都列着它、库里都没有** ——
    四个死条目躺着，和当初那 19 个列一模一样的形状。
    ⇒ 本函数同时审计 `TRACK` 和 `TRACK_TABLES`。
      **同一个洞有两半时，修一半比不修更危险** —— 它会让人以为这类问题已经解决了。
    """
    tabs = _tables(conn)
    dead = []
    for c in TRACK:
        tbl, col = c.split(".", 1) if "." in c else (TABLE, c)
        if tbl not in tabs or col not in _cols(conn, tbl):
            dead.append(c)
    dead_tabs = [t for t in TRACK_TABLES if t not in tabs]
    if dead and verbose:
        print("\n⚠️ TRACK 里有 %d 条**列**在库里找不到（写错名字？还是从别的语种抄来的残留？）："
              % len(dead))
        print("     %s" % "、".join(dead))
        print("   🔴 找不到的列**闸门守不住** —— 它会被静默跳过，"
              "而清单看起来仍然覆盖着它。")
    if dead_tabs and verbose:
        print("\n⚠️ TRACK_TABLES 里有 %d 张**表**在库里找不到：" % len(dead_tabs))
        print("     %s" % "、".join(dead_tabs))
        print("   🔴 同上 —— 行数闸对它完全失明。要么建出来，要么从清单里删掉，"
              "**不许让它躺着**。")
    return dead + ["#" + t for t in dead_tabs]


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


# ══════ 俄语的归一：**逐个列出要去掉的组合符，不走「去掉所有组合符」** ══════
#
# 🔴🔴🔴 见文件头。这是 ru 与 vi **方向相反**的那一条，也是本门最贵的一个坑：
#    `й`(U+0439) 和 `ё`(U+0451) 都是 NFC 单码位，NFD 会把它们各拆成两个码位，
#    于是「NFD 之后去掉组合符」会把 **й → и、ё → е** ——
#    前者毁掉俄语字母表里独立的一个字母，后者毁掉**辨义**（`всё`/`все`）。
#
# ⇒ 白名单，只列**源头当装饰加上去的那些**：
_STRIP_MARKS = (
    "́",   # COMBINING ACUTE ACCENT  —— 重读符。ru 版给词头标重音位置（`ко́шка`）
    "̀",   # COMBINING GRAVE ACCENT  —— 少见，同类装饰（`о̀`）
)
# 🔴 **不是黑名单。** 写成「去掉除 U+0306/U+0308 以外的组合符」是同一个错的变装版：
#    下一个没想到的组合符出现时，黑名单会默认删掉它，白名单会默认留着它。
#    `[[dont-gate-facts-on-my-uncertainty]]`：不确定的时候别默认"可以扔"。


def strip_stress(s):
    """只去重读符/抑音符，**其余一个字符都不动**。原语。"""
    t = s or ""
    for m in _STRIP_MARKS:
        t = t.replace(m, "")
    return t


def norm_ru(s):
    """检索归一键。**只做两件事**：去重读符 ＋ 小写。

    🔴 **这里没有 NFD，也没有 `ё→е` 折叠**，两条都是有意的：
      · NFD 见文件头 —— 它会毁掉 й 和 ё；
      · `ё→е` 折叠会把 `всё`(一切) 和 `все`(所有人) 撞成一个键。
        ⚠️ 这条**有代价、而且我选了这一边**：源头和用户都常把 ё 写成 е
           （俄语日常书写里 ё 普遍省写）⇒ 用户搜 `все` 搜不到 `всё`。
           那是**检索召回**问题，归展示层去解（搜索时可以双写查询），
           **不许靠毁掉数据层的键来解** —— vi 那门 `word_norm` 冲突 1,263 组、
           1,291 个页面显示别的词的内容，就是在数据层折叠出来的。
      · 大小写折叠**要求原串另存**：`PLAYBOOK` 四「大小写折叠去重会吃掉专名词头」
        （es 丢了 573 个 `Cefalópodos`）。本函数只产出**检索键**，
        `dict.word` 必须存原样，「精确大小写」是检索的第一排序键。
    """
    return strip_stress(s or "").lower()


# ══════ 字符系统：俄语＝西里尔，中文＝表意文字，**两套不相交** ══════
def is_cyrillic(c):
    """单个字符是不是西里尔字母。**原语，不是判据。**

    判据交给 `unicodedata` 答，不手抄码位范围 —— ko 那份手抄 CJK 区间为此栽过两次，
    vi 上手抄会漏 41.3%（喃字住在扩展区）。西里尔的扩展区同理会继续加
    （Extended-A/B/C/D），一份写死的区间表必然追不上。
    ⚠️ 已知上限：`unicodedata` 的版本就是这个判据的上限（vi 那门撞到过 ——
       Python 的 unicodedata 14.0 不认识 CJK 扩展 H）。对西里尔基本区无影响。
    """
    try:
        return "CYRILLIC" in ud.name(c)
    except ValueError:            # 未命名码位（未分配 / 代理对半边 / 控制字符）
        return False


def has_cyrillic(s):
    """这串里有没有西里尔字母。原语。"""
    return any(is_cyrillic(c) for c in s or "")


def is_ideograph(c):
    """单个字符是不是 CJK 表意文字。**原语，不是判据。**"""
    try:
        return ud.name(c).startswith(("CJK UNIFIED IDEOGRAPH", "CJK COMPATIBILITY IDEOGRAPH"))
    except ValueError:
        return False


def has_latin(s):
    """有没有拉丁字母。

    🔴 **在 ru 上它不是「不是俄语」的判据**（在 vi 上它是「不是中文」的单向判据）。
       俄语词典里合法地带拉丁字母的东西不少：缩写对照（`ДНК` ↔ `DNA`）、学名、
       化学式、外来词原形。⇒ 这里只是个原语，别拿它当语言判据。
    ⚠️ 这里**不能**照 vi 那份写 `ud.normalize("NFD", …)` —— 见文件头，
       NFD 在俄语上是禁区。带附加符的拉丁字母（`é`）直接按单码位判。
    """
    return any("a" <= c.lower() <= "z" for c in s or "")


def is_chinese_text(s):
    """「这段文本是中文吗」—— **唯一该被当判据用的那个**。**不要 `src` 参数。**

    两步：
      ① 有西里尔字母 ⇒ 不是中文（那是俄语原文漏进来了）
      ② 有表意文字   ⇒ 是中文

    🔴 **为什么不照搬 ko/vi 的「必须给 src」**：那两门是因为韩语汉字/汉越字/喃字
       本身就是表意文字，`學生` 在字形上分不出中越，只能看来源。
       俄语没有这个问题 —— 西里尔和表意文字不相交，**字形就够**。
       照搬会逼每个调用方编一个 `src` 出来，而编出来的 src 比字形判据更不可靠。

    ⚠️ **「是中文」≠「是可用的中文释义」。** ko 的 K24：zh 版「白送中文释义 206,091 条」
       里 **97.2% 是元描述**（中文覆盖率 74% → 2.11%）。那个判据归阶段 5，
       写在 `ru/pipeline/criteria.py` 里、可 import、**只有一个家** ——
       不许在这儿重写一版，也不许拿本函数代替它。
    """
    t = s or ""
    if has_cyrillic(t):
        return False
    return any(is_ideograph(c) for c in t)


# ══════ 🔴🔴 归一的自检：**import 时就跑** ══════
# 文件头那一课（「NFD 在越南语是正解、在俄语是灾难」）如果只是注释，
# 下一个从 vi/ko 拷脚本过来的人会把 `norm_vi` 的实现粘进 `norm_ru`，
# 而症状是**静默的**：库照样建得出来，只是 й/ё 从检索键里消失了，
# 等到展示层发现「搜 ёж 搜不到」已经是几万行数据之后。
# ⇒ `[[lesson-must-become-mechanism]]`：做成会自己响的东西，别再写一句话。
#
# ⚠️ 用例是**两个方向都写**（`[[expectation-must-be-declared]]`）：
#    只断言「该相等的相等」，一个 `return s` 的空实现也能全过。
_NORM_MUST_DIFFER = [
    ("ёж", "еж", "ё 辨义：刺猬 ／（吃的现在时）—— 折叠掉就撞键"),
    ("всё", "все", "ё 辨义：一切 ／ 所有人"),
    ("мой", "мои", "й 是字母表里独立的一个字母，不是 и 的变体"),
    ("тайна", "таина", "й 在词中：秘密 ／（不存在的形）"),
]
_NORM_MUST_EQUAL = [
    ("ко́шка", "кошка", "重读符是源头加的装饰，必须去掉"),
    ("Москва", "москва", "大小写折叠进检索键"),
]


def _norm_selfcheck():
    for a, b, why in _NORM_MUST_DIFFER:
        if norm_ru(a) == norm_ru(b):
            raise AssertionError(
                "🔴🔴🔴 `norm_ru` 把 %r 和 %r 归成了同一个键（%r）—— %s\n"
                "   这是「NFD 之后去掉组合符」那条路的症状（它把 й→и、ё→е）。\n"
                "   **俄语的归一只许去 U+0301/U+0300**，见本文件头。\n"
                "   vi 那门归一出事的代价：word_norm 冲突 1,263 组 ⇒ "
                "1,291 个页面显示别的词的内容。" % (a, b, norm_ru(a), why))
    for a, b, why in _NORM_MUST_EQUAL:
        if norm_ru(a) != norm_ru(b):
            raise AssertionError(
                "🔴 `norm_ru` 没把 %r 和 %r 归成同一个键（%r ≠ %r）—— %s"
                % (a, b, norm_ru(a), norm_ru(b), why))


_norm_selfcheck()


def db_exists():
    """库文件在不在。**新语种第一次写库之前它不在**，这不是异常。"""
    return DB.exists()


def snapshot(conn=None):
    """当前不变量：`dict` 总行数 + 各追踪列的非空行数 + 各出版层表的行数（键前缀 `#`）。

    TRACK / TRACK_TABLES 里还不存在的列或表跳过 —— 这样"先写进清单、再由脚本建出来"
    的顺序是安全的（前后各取一次快照，它在中途出现，前快照没有、后快照有）。
    """
    # 🔴 **新语种的第一次写库**：库文件还不存在，不变量是空的 —— 这不是异常。
    #    另外六门的库都已存在，所以这个洞只有开新语种时才撞得上，而那恰恰是
    #    `PLAYBOOK` 1.4 说「闸门不能推后」要覆盖的那一刻：
    #    es 先修了一周数据才有闸门，那一周的写库全部无法追溯。
    #    ⚠️ 返回空字典而不是抛错，代价是「库被误删」也会静默通过。
    #       所以 `session()` 里另有一条：**只有建库 tag 才允许从空库开始**，
    #       见那边的 `_ALLOW_EMPTY_PREFIX`。这里只负责如实回答「现在有什么」。
    if conn is None and not DB.exists():
        return {}

    own = conn is None
    if own:
        conn = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    try:
        out = {"__rows__": conn.execute("SELECT COUNT(*) FROM %s" % TABLE).fetchone()[0]}
        for c in TRACK:
            tbl, col = c.split(".", 1) if "." in c else (TABLE, c)
            if col not in _cols(conn, tbl):
                continue
            out[c] = conn.execute(
                "SELECT COUNT(*) FROM %s WHERE TRIM(COALESCE(%s,''))<>''" % (tbl, col)
            ).fetchone()[0]
        tabs = _tables(conn)
        for t in TRACK_TABLES:
            if t in tabs:
                out["#" + t] = conn.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        return out
    finally:
        if own:
            conn.close()


def diff(before, after):
    """两次快照之差。**必须取两边键的并集** —— 会话中途 ALTER 出来的新列只在
    after 里有，只遍历 before 的话它从 0 涨到 15 万也看不见；
    反过来阶段 0 要**删列**，被删的列只在 before 里有，同理。"""
    keys = set(before) | set(after)
    return {k: after.get(k, 0) - before.get(k, 0) for k in keys
            if after.get(k, 0) != before.get(k, 0)}


#  ── 保留策略（2026-08-11 在 es 上立，fr 开工即带）─────────────────────────
#  es 上每次写库前全量复制 697 MB，十天攒了 118 个备份、**56 GB**，
#  其中大量是同一天同一个 tag 隔一两分钟的重复。当天清掉 120 个、释放 50.9 GB。
#  不加策略的话两周后原样复发 —— 清理是一次性的，产生速度不是。
#  🔴 de 现在的库只有 111 MB，看着无所谓；fr 开工时是 96 MB，做完是 **2.9 GB**。
#     **策略要在库还小的时候就装上**，等它长大再装就已经堆了几十 GB。
#
#  🔴 里程碑用文件名豁免，不靠"记得手动留"：
#     tag 里带 `keep` 的（`dbtool.session("keep-v2-schema")`）不被"最旧"淘汰。
#     结构大改之前请用这个前缀 —— 那种备份删了就真回不去了。
_ALLOW_EMPTY_PREFIX = "build"   # 只有建库步骤允许从「库还不存在」开始

KEEP_TAG = "keep"
#  🔴 2026-08-21：`keep` **只豁免 ①③，计入 ②**。
#     当天清盘发现自动淘汰一个都没删而 backups 已 9.8 GB：es 9 个备份里 6 个带 keep
#     全豁免，剩 3 个非豁免的字节数又刚好没到上限 ⇒ **堆积的不是普通备份，是豁免名单本身**。
#     （当时的修法是"把 keep 计入条数"—— 治标，2026-08-25 已被下面那条取代。）
#  🔴 2026-08-25 第四次咬人之后**换方向，不再调参数**：条数上限整个删掉。
#     它刚刚挤掉了 `keep-v3-infl@20260822`（不可再生的迁移锚点），而当天我打了
#     7 个彼此只差一次小改动的 1.8 GB 里程碑 —— **该删的是那 7 个里的中间几个，
#     不是最老的那个**。条数上限没有"哪个更值钱"的概念，只会按时间从老到新砍，
#     于是永远砍在最不该砍的地方。
#     ⇒ 新规则见 `prune_backups`：**按字节封顶（含 keep）+ 按稀疏度淘汰**。
KEEP_PLAIN = 2              # 普通（非 keep）备份只留最近这么多个 —— 例行 pre-state，
#                             下一个备份一出现，上一个的价值立刻衰减
# 同一语种**全部**备份的总量上限，**keep 也计入**。
# 🔴 keep 从前不计入字节 ⇒ 唯一约束它的是条数，而 fr 一个备份 1.8 GB、上限 24 个
#    ＝ 43 GB 的隐性预算，实测已经涨到 37 GB。豁免名单本身就是问题
#    （2026-08-21 在 es 上已经诊断过一次，当时的修法是"把 keep 计入条数"——治标）。
# ⇒ keep 计入字节，超了按**稀疏度**淘汰（见 `_thin`），首尾永不删。
MAX_BACKUP_BYTES = 8 * 1024 ** 3

# 🔴 2026-09-01 第五次：**规则里没有「这门语言做完了」这个概念。**
#    用户问「pt 的结果还没做整理和备份清理对吧」时的现场：pt 十一个备份 7.9 GB，
#    `prune_backups` 试算 **删 0 个** —— 不是规则坏了，是它刚好卡在 8 GB 下面 1%。
#    而那十一个全是 v3 重构途中的阶段里程碑（schema→intake→ipa→2c→5b→audio→…），
#    每一个的意义都是「万一这一步做错了退回来」。**阶段全做完、三道闸全绿之后，
#    这个意义就没了** —— 留着的是一条已经走完的楼梯。
#    ⚠️ 前四次咬人我改的都是**同一层**（补内容→提上限→改豁免方向→换成字节+稀疏度），
#      这次加的是**一个新维度：时间上的阶段**。预算不该是常数，它该随语种的状态变。
#    ⇒ 完结之后预算收到 `DONE_BACKUP_BYTES`，`_thin` 的「首尾永不删」照旧生效，
#      于是活下来的正好是**最老那个（整轮重构之前，不可再生）**
#      和**最新那个（回滚上一步）**，中间的楼梯全部让干净。
DONE_BACKUP_BYTES = 1.5 * 1024 ** 3

# 判据是**计划表里那一行**，不是手工开关：
#   `docs/RU_PLAN.md` 里出现 `# ✅ ru 完结` 才算完结。
# 🔴 为什么不设一个 `DONE = True` 常量：那是「写着已修」和「真的修了」的老毛病
#    （收尾单 C49/C50 那一族）。而这一行同时被**账的闸**盯着 ——
#    阶段表说完成、交付物就必须存在。⇒ 标完结这个动作本身是有代价的，
#    它不会被顺手打上去，也就不会顺手把备份预算砍掉。
PLAN_DOC = paths.ROOT / "docs" / "RU_PLAN.md"


def _language_is_done():
    """本语种是否已在计划表里标注完结。读不到文件一律按**未完结**（预算宽松）——
    删数据的默认值必须偏保守。

    🔴🔴 **2026-10-02：这个正则里原本写的是 `ko`**（本文件从 ko 拷来，`PLAN_DOC` 改了、
       注释改了、**正则没改**）⇒ 读 `VI_PLAN.md` 却找「ko 完结」，**永远匹配不上**。
       哪天 vi 标完结，预算不会收紧 —— 那正是 `[[backup-retention]]` 里 fr 那行 ✅
       白写半个月的原形，而跨语种闸 `scripts/test_backup_policy_gate.py` 就是为它建的。
    ⚠️ 它藏了四天，因为那道闸的 `LANGS` 名单里没有 vi（闸对没登记的语种结构性失明），
       而**即使登记了也逮不到**：计划表没标完结 ⇒ declared=False、effective=False ⇒
       「两边一致」判绿。⇒ 已在那道闸里补**正反控制**（拿临时计划表正着问一遍），
       `[[expectation-must-be-declared]]`：0 == 0 不是一致，是两边都没信息。
    """
    try:
        # 🔴 **这一行和 `PLAN_DOC` 必须一起改。** vi 那份改了文件名、改了注释、
        #    **正则里留着 `ko`**，于是读 VI_PLAN 却找「ko 完结」，永远匹配不上，藏了四天。
        #    ⇒ 认这一行的是跨语种闸 `scripts/test_backup_policy_gate.py` 的
        #      `mechanism_probe()`（**正反控制**：拿一份临时计划表正着问一遍）。
        #      🔴 它只对 `LANGS` 里登记过的语种生效 —— ru 已于 2026-10-07 登记，
        #      而登记本身是那道闸的 `_discover()` 当场判红逼出来的。
        return bool(re.search(r"^#+\s*✅\s*ru\s*完结", PLAN_DOC.read_text("utf-8"), re.M))
    except OSError:
        return False




def _thin(items, when, budget, floor=2):
    """总字节超预算时，反复删掉**时间上最"挤"**的那个。→ (留下的, 删掉的)

    "挤" = 它与前后邻居的时间跨度最小 ⇒ 删了它，时间轴上留下的空洞最小。
    效果是**密集簇被抽稀、稀疏的老锚点自然存活** —— 正好是按时间从老到新砍的反面。

    🔴 `floor` = 最少留几个，首尾优先保住：最新的是「回滚上一步」，
       最老的是「回到起点」，这两个的价值不随邻居多少衰减 ⇒ 里程碑用 floor=2。
    ⚠️ **普通备份不能用这个下限**：它们不是锚点，只是例行 pre-state，
       预算被里程碑占满时该让干净（floor=0）。第一版把 floor 写死成 2，
       测试当场逮到「普通的该砍光却留了 2 个」。
    """
    live = sorted(items, key=lambda p: when[p])
    total = sum(p.stat().st_size for p in live)
    out = []
    while total > budget and len(live) > max(floor, 0):
        if len(live) <= 2:                       # 只剩首尾，按从老到新让
            i = 0
        else:
            i = min(range(1, len(live) - 1),
                    key=lambda j: when[live[j + 1]] - when[live[j - 1]])
        p = live.pop(i)
        total -= p.stat().st_size
        out.append(p)
    return live, out


def _backup_time(p, day, hms):
    """备份时间取**文件名里的时间戳**，不取 mtime。

    🔴 2026-08-21：`backup()` 用 `shutil.copy2` 复制，**它连源库的 mtime 一起搬过来**
       ⇒ `.bak` 的 mtime 是「这个库最后一次被写」的时刻，**不是「备份是什么时候打的」**。
       两者能差很远：es 上实测最狠的 `pre-keep-v3-entry-20260820-140712.bak`
       mtime 是 **8-11、差 9 天**（库封版后一直没动，9 天后才打的这个备份）。
       规则①②都按时间排队，用错时钟会把**刚打的里程碑排成最老的**先删掉。
    ⚠️ 文件名时分秒有 4 位（`-1421`）和 6 位（`-140712`）两种写法，补零到 6 位再解析。
       解析不了就退回 mtime —— 宁可排序差一点，也不能因为一个怪名字就抛异常。
    """
    try:
        return time.mktime(time.strptime(day + hms.ljust(6, "0"), "%Y%m%d%H%M%S"))
    except ValueError:
        return p.stat().st_mtime


def prune_backups(verbose=True, dry=False):
    """三条规则依次收紧：
    ① 同一 tag 同一天只留一个   —— 普通留**最新**，keep 留**最早**（真正的 pre-state）
    ② 普通备份只留最近 KEEP_PLAIN 个
    ③ 总字节封顶 MAX_BACKUP_BYTES（**keep 也计入**）：先砍普通的，
       还超就按**稀疏度**抽稀 keep（`_thin`）—— 密集簇的中间点先走，首尾永不删

    🔴 2026-08-25 用 ③ 的稀疏度淘汰**换掉了**原来的条数上限。
       条数上限只会按时间从老到新砍，而"该砍的"恰恰是同一天连打的那几个近乎重复的
       快照 —— 它砍在了最不该砍的地方，实测挤掉 `keep-v3-infl@20260822`。

    `dry=True` 只列不删 —— **改这个函数之后先 dry 跑一遍**。
    它是本仓库里唯一一个会自动删数据的地方，写错了没有第二次机会。
    """
    pat = re.compile(r"^%s\.pre-(.+)-(\d{8})-(\d{4,6})\.bak$" % re.escape(DB.stem))
    rows, when = [], {}
    for p in paths.BACKUPS.glob("%s.pre-*.bak" % DB.stem):
        m = pat.match(p.name)
        if m:
            rows.append((p, m.group(1), m.group(2)))
            when[p] = _backup_time(p, m.group(2), m.group(3))
    exempt, drop = set(), []
    # ① 同 (tag, 日期) 只留一个。
    #
    #    普通备份留**最新**：它是离现在最近的可恢复状态。
    #
    #    🔴 2026-08-23：keep 原来完全豁免这一条，**代价当天就付了** ——
    #    我把 `strip-footnote` 判据改窄了两次、重试三次，留下 3 个同标签同日的
    #    1.8 GB 快照（`apos` 更狠，4 个），条数配额被占满，规则② 挤掉了
    #    `pre-keep-v3-altof` 这个**阶段 2 的真里程碑**。
    #    ⇒ keep 也进这一条，但方向**相反：留最早的那个**。
    #      理由：里程碑的意义是「操作 X **之前**的状态」。同一天同一个 tag 跑了三次，
    #      第一个才是真正的 pre-state，后两个是我改到一半的中间态 ——
    #      作为回滚锚点严格地更差。
    #    ⚠️ 代价说明白：如果同一天把同一个 tag 复用给了两个**不同**的操作，
    #      留最早 = 回滚会多退一步。仍然可恢复，只是退得更远。
    #      （这比「里程碑被重试快照挤掉」——直接不可恢复——好。）
    newest, oldest = {}, {}
    for p, tag, day in rows:
        if KEEP_TAG in tag:
            k = (tag, day)
            if k not in oldest or when[p] < when[oldest[k]]:
                if k in oldest:
                    drop.append(oldest[k])
                oldest[k] = p
            else:
                drop.append(p)
            continue
        k = (tag, day)
        if k not in newest or when[p] > when[newest[k]]:
            if k in newest:
                drop.append(newest[k])
            newest[k] = p
        else:
            drop.append(p)
    exempt = set(oldest.values())              # 过了 ① 的 keep
    # ② 普通备份只留最近 KEEP_PLAIN 个。
    #    它们是例行的 pre-state，下一个备份一出现，上一个基本就没人会回去了；
    #    而里程碑不一样，它标的是「某次结构变更之前」，隔多久都可能要回去。
    plain = sorted(newest.values(), key=lambda p: -when[p])
    drop += plain[KEEP_PLAIN:]
    plain = plain[:KEEP_PLAIN]

    # ③ 总字节封顶（**keep 也计入**），超了按稀疏度抽稀。
    #    先砍普通的（更不值钱），还超再抽稀 keep。
    done = _language_is_done()
    budget = DONE_BACKUP_BYTES if done else MAX_BACKUP_BYTES
    used = sum(p.stat().st_size for p in exempt)
    plain, cut = _thin(plain, when, max(budget - used, 0), floor=0) if plain else ([], [])
    drop += cut
    used += sum(p.stat().st_size for p in plain)
    if used > budget:
        survive_keep, cut_keep = _thin(list(exempt), when, budget - sum(
            p.stat().st_size for p in plain))
        drop += cut_keep
        exempt = set(survive_keep)
    keep = set(plain) | exempt

    # 🔴 删 keep 有**两条**路径，仍然分开打（合并打印 = 信息淹没在噪声里）：
    #    ①' 同标签同日的重试快照 —— 该组仍留着最早那个，没丢回滚能力
    #    ③  预算超了被抽稀 —— 该标签整个消失
    # ⚠️ 2026-08-25：③ 从前是「条数上限从最老开始砍」＝**意外**，所以用 🔴 报警；
    #    换成稀疏度淘汰之后它是**预期行为**（密集簇本来就该抽稀），
    #    再打 🔴 就是狼来了。降级成陈述句，但仍逐条列出来，不许静默。
    by_group = {}
    for p, tag, day in rows:
        if KEEP_TAG in tag:
            by_group.setdefault((tag, day), []).append(p)
    survivors = {k for k, ps in by_group.items() if any(p in keep for p in ps)}
    for p in drop:
        if KEEP_TAG not in p.name:
            continue
        m = pat.match(p.name)
        grp = (m.group(1), m.group(2)) if m else None
        if grp in survivors:
            print("   · 清理同标签同日的重试快照：%s（该里程碑仍保留最早的一个）" % p.name)
        else:
            # ⚠️ 文案必须跟着规则改（2026-08-25 的教训：规则从「意外」变成
            #    「预期行为」而文案还在打 🔴 ＝ 狼来了）。这里再多一种情形：
            #    完结收紧是**一次性的、可预期的**，不该和日常超预算混着报。
            print("   %s：%s" % (
                "· 已完结，楼梯收干净（预算 %.1f GB）" % (budget / 1024 ** 3) if done
                else "⚠️ 淘汰里程碑（总量超 %.0f GB，抽稀掉这个时间点）" % (budget / 1024 ** 3),
                p.name))

    gone = sorted("%s@%s" % k for k in by_group if k not in survivors)
    if gone:
        print("   （被抽稀掉的里程碑标签：%s）" % ", ".join(gone))

    freed = sum(p.stat().st_size for p in drop)
    if dry:
        print("■ 试算：会保留 %d 个、删 %d 个（%.1f GB）" % (len(keep), len(drop), freed / 1024 ** 3))
        for p in sorted(keep):
            print("   保留  " + p.name)
        for p in sorted(drop):
            print("   删除  " + p.name)
        return len(drop), freed
    for p in drop:
        p.unlink()
    if verbose and drop:
        print("■ 备份保留策略：清掉 %d 个旧备份，释放 %.1f GB（保留 %d 个）"
              % (len(drop), freed / 1024 ** 3, len(keep)))
    return len(drop), freed


def backup(tag):
    """备份落在 `data/backups/`，并顺手执行保留策略。

    ⚠️ 2026-08-01 重构后一度仍用 `DB.with_name(...)`，于是备份被写进了 `data/db/`，
       和成品库混在一起 —— 目录分工形同虚设。改用 paths.BACKUPS。
    """
    paths.BACKUPS.mkdir(parents=True, exist_ok=True)
    dst = paths.BACKUPS / ("%s.pre-%s-%s.bak" % (DB.stem, tag, time.strftime("%Y%m%d-%H%M%S")))
    # 🔴 库还不存在（新语种第一次建库）⇒ 没有「写库前状态」可留档，不是异常。
    #    返回 None，调用方据此不打印备份行。**不许伪造一个空备份文件** ——
    #    那会让保留策略以为有一个可回滚的里程碑，而它什么都回滚不到。
    if not DB.exists():
        return None
    shutil.copy2(DB, dst)
    # 🔴 淘汰放在**复制之后**：万一复制失败就抛异常了，不会先把旧的删掉再发现新的没建成。
    prune_backups()
    return dst


def _line(snap, d=None):
    # 🔴 空快照＝库还不存在（新语种第一次写库）。另外六门的库都已存在，
    #    所以这条路径从没被走过 —— 与 `snapshot()` 那处是同一个洞的第二半。
    if not snap:
        return "（库还不存在，不变量为空）"
    parts = ["总行 {:,}".format(snap.get("__rows__", 0))]
    for c in TRACK + ["#" + t for t in TRACK_TABLES]:
        if c not in snap:
            continue
        s = "{} {:,}".format(c, snap[c])
        if d and c in d:
            s += " ({:+,})".format(d[c])
        parts.append(s)
    return " | ".join(parts)


# 🔴🔴 **这次写库动了哪些表** —— 从 SQL 里抠表名。**ko 的 K31** 的第二版，2026-09-26（机制照搬，编号是 ko 的）。
#
# 第一版把「哪几道闸过期了」建在 `diff()`（计数差）上。当天就撞到洞：
# ko 的 K16 重译 20 条例句译文是**纯内容 UPDATE**，所有计数一个没变 ⇒ `diff` 是空的
# ⇒ **一道闸都没被标脏**，而例句译文正是外锚闸和契约闸盯的东西。
# ⭐ 这正是 `[[primary-key-is-not-enough]]` 记过的形状：**计数型判据对内容改动
#   结构性失明**。⇒ 判据换成「写了哪张表」，它对 INSERT/UPDATE/DELETE 一视同仁。
_WRITE_SQL = re.compile(
    r"\b(?:INSERT(?:\s+OR\s+[A-Z]+)?\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)"
    r"\s+[\"'`\[]?([a-z_][a-z0-9_]*)", re.I)


class _S:
    """会话句柄。只暴露写库入口，强制所有写操作被计数。"""

    def __init__(self, conn):
        self.conn = conn
        self.written = 0
        self.touched = set()        # 这次写库动过的表名（给欠账机制用，见 `_gate_debt`）

    def _note(self, sql):
        for m in _WRITE_SQL.finditer(sql or ""):
            self.touched.add(m.group(1).lower())

    def executemany(self, sql, seq):
        seq = list(seq)
        self._note(sql)
        self.conn.executemany(sql, seq)
        self.written += len(seq)
        return len(seq)

    def addcolumn(self, name, decl="TEXT"):
        """幂等加列。加列本身不改任何行，不计入 written。"""
        if name in _cols(self.conn):
            return False
        self.conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (TABLE, name, decl))
        self.touched.add(TABLE)     # 改了结构，读者口径的闸一律重跑
        return True

    def execute(self, sql, args=()):
        # ⚠️ `execute` 既用来读也用来写（脚本常拿它跑 SELECT）。`_note` 只认
        #    写语句的关键字，所以 SELECT 不会被误记成「动过表」。
        self._note(sql)
        return self.conn.execute(sql, args)


@contextmanager
def session(tag, expect=None, dry=False, verbose=True, invalidates=None):
    """写库闸门。

    expect: {列名: 期望的非空计数变化}；表用 `"#表名"`。
        · 显式写出的列：变化必须**恰好等于**期望值；写 None 表示"允许变但不校验数值"。
        · **没写出的列 / 表：变化必须为 0。**
        · 总行数 `__rows__` 默认必须为 0；要插行就得**显式**写出期望的增量，
          写不对就报错退出。
          🔴 es 2026-08-03 才放开这一条：此前所有写库都是原地更新，闸门直接写死
          "行数不许变"。收词要插 36.9 万行 —— 但**不能因此把这道闸拆掉**，
          只能从"永远 0"改成"必须显式声明具体数字"。插行时所有列的非空计数都会
          跟着涨，所以那一批列也必须逐个写进 expect，闸门才拦得住"多写了一列"。
          ⚠️ de 的阶段 3 收词规模**未知**（德语版有 963,570 个词形、我们库内 349,775，
             但那是源头数、落点未量），但 fr 那轮是本项目
             至今最大的一次插行（38.5 万 → 208.6 万），同一个形状，这条尤其要认真写。
    """
    expect = dict(expect or {})
    # ══════════════════════════════════════════════════════════════
    # 🔴🔴 **收词闸**：插新词形的那一步，必须当场说清它让哪些层过期了。
    #
    # 起因是同一个形状发生了三次，每次都是**事后**补的：
    #   pt   收词在变形层之后 ⇒ 30 万变形没人连线，46.2% 的词形成了空白页
    #   ja   收词之后没重跑读音层 ⇒ 词元读音覆盖 99.90% 静默掉到 39.8%
    #   ja   收词之后中文覆盖 98.66% 掉到 70.77%
    # 三次我都写了教训，三次都没拦住下一次 —— 因为**教训只在我主动回忆时才响**，
    # 而「我刚发现一批新词可以收」恰恰是我最不会回忆它的时刻
    # （`[[lesson-must-become-mechanism]]`）。
    #
    # ⇒ 把它变成**这个路口上过不去的东西**：`__rows__ > 0` 就必须传 `invalidates`。
    #   传空列表也行 —— 但那是一次**显式声明**「我想过了，一层都不受影响」，
    #   而不是默认。默认值的方向决定了它拦不拦得住人。
    #
    # ⚠️ 名单从 `tests/test_plan_ledger.COVERAGE` 里读，**不在这儿手抄一份** ——
    #    两张名单迟早漂开（`[[refactor-mindset-code-quality]]`）。
    _INV["cur"] = invalidates
    _rows = expect.get("__rows__", 0) or 0
    if _rows > 0 and invalidates is None and not tag.startswith(_ALLOW_EMPTY_PREFIX):
        raise SystemExit(
            "🔴 tag=%r 要插 %s 行新词形，但没有声明 `invalidates=[...]`。\n"
            "   **收词会让按词元算的覆盖率静默掉下来** —— 同一个形状发生过三次：\n"
            "     pt 收词后变形层没重跑 ⇒ 46.2%% 空白页\n"
            "     ja 收词后读音层没重跑 ⇒ 词元读音覆盖 99.90%% → 39.8%%\n"
            "     ja 收词后中文覆盖     ⇒ 98.66%% → 70.77%%\n"
            "   已知与词元数挂钩的层：%s\n"
            "   ⇒ 传 `invalidates=[...]` 列出这次要重跑的，或 `invalidates=[]` "
            "**显式**声明一层都不受影响。"
            % (tag, format(_rows, ","), "、".join(_word_count_layers())))
    # 🔴 空库只允许**建库**那一步开。别的 tag 遇到空库，说明库被误删或路径写错了 ——
    #    那种时候静默从零开始写，比报错危险得多（`[[backup-retention]]` 咬过六次的
    #    都是「删数据的默认值不够保守」这个形状）。
    if not DB.exists() and not tag.startswith(_ALLOW_EMPTY_PREFIX):
        raise SystemExit(
            "🔴 %s 不存在，而 tag=%r 不是建库步骤。\n"
            "   库被误删／paths.DB 写错？要从零建库请用 tag 以 %r 开头。"
            % (DB, tag, _ALLOW_EMPTY_PREFIX))
    before = snapshot()
    if verbose:
        print("■ 写库前不变量：" + _line(before))
    if dry:
        if verbose:
            print("(dry：不备份、不写库)")
        # 库不存在时 ro 连接会炸 ⇒ 干跑落到内存库，让调用方的 DDL 能跑通而不落盘
        conn = (sqlite3.connect("file:%s?mode=ro" % DB, uri=True) if DB.exists()
                else sqlite3.connect(":memory:"))
        try:
            yield _S(conn)
        finally:
            conn.close()
        return

    bak = backup(tag)
    if verbose:
        print("■ 已备份 → " + bak.name if bak else "■ 库还不存在，无可备份（本步建库）")
    conn = sqlite3.connect(DB)
    s = _S(conn)
    try:
        yield s
        conn.commit()
    except BaseException:
        conn.rollback()
        conn.close()
        # 🔴 2026-08-22：**rollback 成功 ⇒ 这份备份是冗余的，当场删掉。**
        #    事务回滚后库就是备份拍下的那个状态，留着它只是噪声 —— 而噪声会挤掉里程碑：
        #    当天 `keep-v3-apos` 那个 7 行的小改动失败重试三次，留下 4 份内容几乎相同的备份，
        #    把 `keep-v3-schema` 和 `keep-v3-entry` 两个**不可再生的迁移锚点**挤出了条数上限。
        #    ⚠️ 只删「异常回滚」这一路。**闸核对未通过那一路不能删** ——
        #       那时数据已经在库里，备份是唯一的回滚点。
        # 🔴🔴 **B22 的第一处**：`backup()` 在库不存在时返回 `None`（新语种第一次建库
        #    的正常状态，`backup()` 自己的注释写着「不许伪造一个空备份文件」），
        #    而 vi/ko 两门这里直接 `bak.unlink()` ⇒ `AttributeError`。
        #    它**不是 OSError**，所以下面那个 except 接不住，于是
        #    **真正的建库报错被挤成"During handling of the above exception"的上一条** ——
        #    而这正是开新语种第一天唯一会走到的路径。
        if bak is None:
            print("\n🔴 写库异常，已 rollback。本步是建库，没有可回滚的前状态"
                  "（库原本就不存在）—— 删掉半成品库重跑即可。", file=sys.stderr)
            raise
        try:
            bak.unlink()
            print("\n🔴 写库异常，已 rollback；本次备份是冗余的，已删除（%s）"
                  % bak.name, file=sys.stderr)
        except OSError:
            print("\n🔴 写库异常，已 rollback。备份仍在：" + bak.name, file=sys.stderr)
        raise
    after = snapshot(conn)
    conn.close()

    d = diff(before, after)
    bad = []
    want_rows = expect.get("__rows__", 0)
    if d.get("__rows__", 0) != want_rows:
        bad.append("总行数变了 {:+,}，期望 {:+,}".format(d.get("__rows__", 0), want_rows))
    for c in TRACK:
        got = d.get(c, 0)
        if c in expect:
            want = expect[c]
            if want is not None and got != want:
                bad.append("{} 变化 {:+,}，期望 {:+,}".format(c, got, want))
        elif got:
            bad.append("🔴 未声明的列 {} 变了 {:+,} —— 改到了不该改的地方".format(c, got))
    for t in TRACK_TABLES:                       # 出版层表的行数，判据同上
        key = "#" + t
        got = d.get(key, 0)
        if key in expect:
            want = expect[key]
            if want is not None and got != want:
                msg = "{} 行数变化 {:+,}，期望 {:+,}".format(t, got, want)
                # ⭐ 认出「声明了总数而不是增量」这个形状，直接说人话。
                #    2026-08-30 我一天犯了三次（频次层／录音层／例句层）：
                #    `expect={"#tbl": len(rows)}` 里 `rows` 是**整轮扫描的产物**，
                #    而 `INSERT OR IGNORE` 只插新的 ⇒ 期望值等于**写库后的总数**。
                #    与其让人对着两个数发呆，不如闸自己指出来。
                if want == after.get(key, 0):
                    msg += ("\n      ⭐ 期望值恰好等于**写库后的总行数** ⇒ "
                            "多半是把 `expect` 写成了总数。它比的是**增量**：\n"
                            "         增量 = 这批 rows 里、键还不在库里的那些"
                            "（`INSERT OR IGNORE` 只插新的）")
                bad.append(msg)
        elif got:
            bad.append("🔴 未声明的表 {} 行数变了 {:+,} —— 动到了不该动的表".format(t, got))
    if verbose:
        print("■ 写入 {:,} 条".format(s.written))
        print("■ 写库后不变量：" + _line(after, d))
    if bad:
        # 🔴 2026-08-17：核对失败的红字原来只走 stderr，我两次用 grep 过滤输出
        #    就把它滤掉了，只看到「已收 N 条」就往下走 —— 数据已经 commit 了却不知道。
        #    ⇒ 同时打到 stdout，并在**最后一行**再重复一次结论，让它难被漏读。
        for out in (sys.stderr, sys.stdout):
            print("\n🔴 不变量核对未通过：", file=out)
            for b in bad:
                print("   " + b, file=out)
            # 🔴 2026-08-30：**回滚命令必须先确认那个文件还在。**
            #    实测踩到：同一个脚本改了两版连着跑，第一版抛 IntegrityError 走异常路径
            #    自删备份（那次是对的，事务已回滚），第二版闸红时打出的 `cp` 路径
            #    已经被保留策略清掉了 —— 照着敲会得到 "No such file"，
            #    而我以为自己手上有回滚点。**说得出的回滚点必须是存在的回滚点。**
            # 🔴🔴 **B22 的第二处，比第一处更坏**：vi/ko 那份写的是
            #    `if bak.exists(): if bak: … else: …` —— 判空写在了 `.exists()` **之后**，
            #    所以 `bak is None`（建库）时第一行就 `AttributeError`，
            #    **整个 `bad` 清单一条都印不出来**：闸红了，而闸的结论被自己的报错吃掉。
            #    里面那个 `if bak:` 是「想到了、位置放错了」的化石（永远为真的死分支）。
            #    ⇒ 判空提到最前面。
            if bak is None:
                print("   ⚠️ 本步是建库，没有可回滚的前状态 —— 删掉半成品库重跑即可", file=out)
            elif bak.exists():
                print("   回滚：cp '%s' '%s'" % (bak, DB), file=out)
            else:
                print("   🔴🔴 **没有回滚点** —— 本次备份 %s 已不在（被保留策略清掉，"
                      "或上一次异常回滚时自删）。只能向前修。" % bak.name, file=out)
            print("🔴🔴🔴 本次写库未通过，**数据已在库中**，要么按上面的命令回滚，"
                  "要么确认这些变化是预期的并补进 expect。", file=out)
        raise SystemExit(1)
    if verbose:
        print("■ 不变量核对通过 ✓")
    # 🔴 两道闸**各叫各的，谁也不挂在谁末尾**。
    #    fr 那份是 `_regression_check` 在末尾调 `_ledger_gate`，而它在回归闸文件
    #    不存在时会提前 return —— fr 上不发作（建账的闸时回归闸早就在了），
    #    但 pt 到阶段 7 之前回归闸都不存在 ⇒ **账的闸从阶段 -2 建好起就是死的**，
    #    而我建它的全部理由就是"不等到阶段 7"。
    #    ⇒ 一道闸的执行不许由另一道闸的存在与否决定。
    _regression_check(verbose)
    _ledger_gate(verbose)
    _literal_gate(verbose)
    # 🔴 TRACK 死条目审计：闸门自己守不住的列，必须说出来
    _con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    try:
        _track_audit(_con, verbose)
    finally:
        _con.close()
    # 🔴 **说在最后** —— 那是人还在看屏幕的时候。说在开头会被后面几十行不变量冲掉。
    _announce_invalidated(_INV.get("cur"), verbose)
    _gate_debt(d, tag, s.touched, s.written)


_INV = {"cur": None}


def _gate_debt(d, tag, touched=(), written=0):
    """这次写库让哪几道闸**过期**了（机制来自 ko 的 K31）：记进欠账文件，并在最末尾大声说。

    ═══ 为什么不是「记得跑一下」 ═══
    2026-09-26 发现两道外锚闸从 **09-25 起红了整整一天**，两条都不是新缺陷，
    是「修了数据没跟着重跑闸」。这里之前什么都不说 ⇒ 没有任何东西会提醒人。
    `[[lesson-must-become-mechanism]]`：**做成机制的全守住了，写成文字的一条没守住。**

    ⚠️ 与上面几道一样**只报不拦**（数据已经 commit 了）。真正拦人的是
       账的闸 P10：欠账非空就红，而账的闸每次写库都自动跑。

    🔴 算不出依赖时（`gates.service_tables()` 抛）**把所有闸都记成脏的** ——
       宽的代价是多跑几分钟，窄的代价就是 09-25 那两条。
       `[[dont-gate-facts-on-my-uncertainty]]`：不确定的时候别默认「没事」。
    """
    # 🔴 **「还没建」和「建了但坏了」必须分开说。**
    #    vi 那份只有一条「读不到 ⇒ 🔴🔴 这本身要查」，于是在**阶段 1 之前**
    #    每次写库都会打一条看起来很严重的红字 —— 而那时它只是还没建。
    #    狼来了的代价在 ko 身上量过：11 道闸里 3 道从没人跑过、1 道红着一整天。
    #    ⚠️ 同一个分辨 `_regression_check` 里已经有了（「文件不存在＝跳过，
    #       文件在但跑不起来＝必须喊」）—— 这里是把它补齐，不是新发明。
    if not (HERE / "gates.py").exists():
        print("\n⚠️ 闸台账 `ru/gates.py` **尚未建** —— 这次写库让哪些闸过期了，"
              "现在没有任何东西在记。", file=sys.stderr)
        print("   这不是「没有欠账」，是「没有台账」。`RU_PLAN` §0.6：闸从阶段 1 就建。",
              file=sys.stderr)
        return
    try:
        sys.path.insert(0, str(HERE))
        import gates
    except Exception as e:                       # noqa: BLE001 —— 文件在却读不进来，要喊
        print("\n🔴🔴 闸台账 `ru/gates.py` **在、但读不进来**（%s）—— **这本身要查**："
              "这套机制整个靠它。" % e, file=sys.stderr)
        return
    # 🔴🔴 **判据是「写了哪张表」∪「哪些计数变了」，不是只看计数。**
    #    只看计数的第一版当天就被 ko 那次纯内容 UPDATE 穿过去了（计数全没变、
    #    欠账是空的、而 20 条例句译文已经改了）——
    #    `[[primary-key-is-not-enough]]`：计数型判据对内容改动结构性失明。
    try:
        names, from_diff = gates.dirty(d, extra_tables=touched)
    except BaseException as e:                   # noqa: BLE001
        print("\n🔴🔴 算不出哪些闸过期了（%s）⇒ **按最坏情况把每道闸都记成脏的**。"
              % e, file=sys.stderr)
        names = [g["name"] for g in gates.GATES]
        from_diff = {"（算不出）"}
    touched = set(touched) | set(from_diff)
    # 🔴 写了行、却一张表也没认出来 ⇒ **抠表名的正则漏了这种写法**。
    #    那种时候按最坏情况全标脏，并大声说 —— 静默漏掉正是这套机制要治的病。
    if written and not touched:
        print("\n🔴🔴 写了 %s 条，而一张表也没从 SQL 里认出来 —— **`_WRITE_SQL` 漏了"
              "这种写法**。按最坏情况把每道闸都标脏。" % format(written, ","),
              file=sys.stderr)
        names = [g["name"] for g in gates.GATES]
        touched = {"（认不出表名）"}
    if names:
        gates.mark(names, tag, touched)
    gates.announce()


def _word_count_layers():
    """→ 与词元数挂钩的层名。**从账的闸的 COVERAGE 表读，不手抄。**"""
    try:
        sys.path.insert(0, str(HERE))
        from tests.test_plan_ledger import COVERAGE
        return [name for name, _floor, _sql, _why in COVERAGE]
    except Exception:
        return ["（读不到 test_plan_ledger.COVERAGE —— 那本身要查）"]


def _announce_invalidated(inv, verbose=True):
    """写完之后大声说一遍要重跑什么。**说在最后**，因为那是人还在看屏幕的时候。"""
    if inv is None:
        return
    if not inv:
        print("■ 收词闸：已声明 `invalidates=[]` —— 一层都不受影响")
        return
    print("\n🔴 **收词闸：以下层已过期，必须重跑**")
    for x in inv:
        print("     · %s" % x)
    print("   ⚠️ 重跑之前先跑一遍账的闸（P6 按覆盖率盯着它们）：python3 tests/test_plan_ledger.py")


def _regression_check(verbose=True):
    """写库之后跑一遍回归闸。

    ═══ 为什么这道闸必须在这里，而不是"记得跑一下" ═══
    用户 2026-08-11：「同一个问题你修了，隔天修其他问题，你又发现之前的问题又出现了。」
    根因是修复写在**输出层**，而输出层会被 DROP 重建 —— es 上已知三次，
    三次全是**事后偶然撞见**的，间隔一周到十天。上面两道不变量闸拦不住它们：
    行数没变、列的非空计数没变，**变的是内容对不对**。
    ⇒ 这里必须跑一遍「过去每个修复现在还在不在」，让回归在**产生它的那次写库**上报出来。

    ⚠️ 它**只报不拦**。理由：写库已经 commit 了（回归闸要读最终状态才准），
       而且不是每次红都该回滚 —— 有些是这次写库有意为之。报出来 + 备份路径就够决策了。
    不想跑：`SKIP_REGRESSION_CHECK=1`。

    📋 ru 的回归闸要到阶段 8 才建，现在还不存在（`docs/RU_PLAN.md`）。
    **文件不存在 = 静默跳过；文件在但跑不起来 = 必须喊** —— 后者是闸自己坏了。
    """
    if os.environ.get("SKIP_REGRESSION_CHECK") == "1":
        return
    if not (HERE / "tests" / "test_no_regression.py").exists():
        return                                   # 阶段 7 之前：这道闸还没建，不是坏了
    try:
        sys.path.insert(0, str(HERE))
        from tests.test_no_regression import check_brief
        red = check_brief()
    except Exception as e:                      # 闸自己坏了不能挡住写库，但必须喊出来
        print("\n⚠️ 回归闸没跑起来（%s）—— 这本身要查" % e, file=sys.stderr)
        return
    if not red:
        if verbose:
            print("■ 回归闸通过 ✓（过去的修复都还在）")
    else:
        print("\n🔴 回归闸报警：有 %d 条过去的修复现在失效了" % len(red), file=sys.stderr)
        for cid, name, why in red:
            print("   %-5s %-38s %s" % (cid, name, why), file=sys.stderr)
        print("   明细：python3 tests/test_no_regression.py", file=sys.stderr)


def _ledger_gate(verbose=True):
    """**账的闸** —— 计划表和收尾单说的话，与库里的事实对不对得上。

    🔴 起因：用户 2026-08-27「你自己定的规矩，自己的经验教训，你自己为什么不执行呢」。
       查会话自己的记录，形状很干净：**做成机制的全守住了，写成文字的一条没守住**
       （`think=False` 硬默认 / `DOUBAO_DISABLED` / 本文件的 `expect` 闸 都守住了；
       `[[ship-dont-measure-in-circles]]` 这类 prose 一条没守住）。
       ⇒ 不再往记忆里写"要记得 X"，写会自己响的东西。

    它逮的是**账**不是数据：阶段表标着 ✅ 而交付物是 0（阶段 5 的关系层/频次层
    就是这么漏了七天的）、收尾单不存在或记账又散开。
    与回归闸同样**只报不拦**。
    """
    p = HERE / "tests" / "test_plan_ledger.py"
    if not p.exists():
        # 🔴🔴 2026-09-21 改：原来这里是 `return` —— **静默**。
        #    ja 就是这么栽的：这个文件从阶段 -2 缺到阶段 4b，三道挂钩每次写库
        #    都什么都没做，而日志照样打「■ 不变量核对通过 ✓」，
        #    我盯着那行绿字做完了九个阶段，**没注意到「账的闸通过 ✓」从来没出现过**。
        #    ⇒ 缺席必须出声。一道不在场的闸和一道全绿的闸，日志上长得不能一样。
        print("\n⚠️ 账的闸**不存在**（%s）—— 计划表与库对不对得上，现在没有任何东西在查。"
              % p.relative_to(paths.ROOT), file=sys.stderr)
        print("   这不是「通过」，是「没查」。🔴 `RU_PLAN` §0.6 第 4 条：账的闸**从阶段 1 就建**，不等阶段 8。",
              file=sys.stderr)
        return
    try:
        from tests.test_plan_ledger import check_brief as _lb
        red = _lb()
    except Exception as e:
        print("\n⚠️ 账的闸没跑起来（%s）—— 这本身要查" % e, file=sys.stderr)
        return
    if not red:
        if verbose:
            print("■ 账的闸通过 ✓（计划表与收尾单和库对得上）")
        return
    print("\n🔴 账的闸报警：%d 条" % len(red), file=sys.stderr)
    for cid, why in red:
        print("   %-4s %s" % (cid, why), file=sys.stderr)
    print("   明细：python3 tests/test_plan_ledger.py", file=sys.stderr)


def _literal_gate(verbose=True):
    """**写死行数的断言**扫描 —— 2026-08-29 建。

    🔴 起因：pt 的脚本从 fr 拷来改，fr 的断言里写死了 fr 的行数。移植当天咬了**三次**
       （de 这一轮从 pt 拷，形状完全相同，这道闸从第一天就挂上）
       （`58` 出现在两个文件里；`split_case_folded` 的 dict 行数 / 义项 / 变形三条全是 fr 的数）。
       三次的数据都完全正确，红的全是断言。

    ⇒ 挂在这里而不是"记得跑"：会触发它的场合恰恰是**跑一份新移植的脚本**，
      而那必然是一次写库。`[[lesson-must-become-mechanism]]`：
      学到教训的交付物是一道会自己响的闸，不是一条记忆。

    与另两道闸同样**只报不拦**。
    """
    p = HERE / "tests" / "test_no_literal_counts.py"
    if not p.exists():
        return
    try:
        from tests.test_no_literal_counts import check_brief as _lc
        red = _lc()
    except Exception as e:
        print("\n⚠️ 字面量闸没跑起来（%s）—— 这本身要查" % e, file=sys.stderr)
        return
    if not red:
        if verbose:
            print("■ 字面量闸通过 ✓（断言里没有写死的行数）")
        return
    print("\n🔴 字面量闸报警：%d 条断言把期望值写死成了行数" % len(red), file=sys.stderr)
    for f, ln, name, val in red[:8]:
        print("   %s:%d  期望 %s  ← %s" % (f, ln, f"{val:,}", name[:44]), file=sys.stderr)
    print("   明细：python3 tests/test_no_literal_counts.py", file=sys.stderr)


def sample_check(rows, n=10, cols=("词", "改前", "改后")):
    """抽样反验：随机打印 n 条改前/改后，供人眼核。

    🔴 **别跳过这一步。**不变量只能证明"没改到不该改的范围"，
    证明不了"改对了内容" —— 后者只有人眼看得出来。
    """
    import random
    rows = list(rows)
    if not rows:
        print("(无可抽样的行)")
        return
    pick = random.sample(rows, min(n, len(rows)))
    w = [max(len(str(r[i])[:40]) for r in pick + [list(cols)]) for i in range(len(cols))]
    print("\n■ 抽样 {}/{:,} 条反验：".format(len(pick), len(rows)))
    print("   " + "  ".join(str(c).ljust(w[i]) for i, c in enumerate(cols)))
    for r in pick:
        print("   " + "  ".join(str(r[i])[:40].ljust(w[i]) for i in range(len(cols))))


if __name__ == "__main__":
    s = snapshot()
    print("%s  表 %s" % (DB.name, TABLE))
    # 🔴 **空快照＝库还不存在**（新语种第一次跑本文件时的正常状态）。
    #    拷过来的版本在这儿直接 `s["__rows__"]` ⇒ `KeyError`，而 `PLAYBOOK` 1.4
    #    要求的恰恰是「闸门排在任何数据动作前面」—— 也就是**必须在库不存在时跑得起来**。
    #    七门都没撞上，唯一的原因是它们都等库建完了才跑这个入口。
    #    ⚠️ 这个洞在 `ja`/`de`/`fr`/`pt` 的同名文件里原样存在 ⇒ 已记进 `docs/BACKLOG.md`。
    if not s:
        print("  （库还不存在 —— 本语种尚未建库，不变量为空。这不是异常。）")
        print("\n  TRACK 现在声明了 %d 个列 / %d 张表。建库之后再跑一次本入口，"
              "`_track_audit()` 会告诉你**实际守住了几个**。" % (len(TRACK), len(TRACK_TABLES)))
        raise SystemExit(0)
    print("  总行 {:,}".format(s["__rows__"]))
    for c in TRACK:
        if c not in s:
            print("  {:16}{:>12}".format(c, "(列不存在)"))
            continue
        print("  {:16}{:>12,}  {:>6.2f}%".format(c, s[c], 100 * s[c] / max(s["__rows__"], 1)))
    print("\n出版层各表行数")
    for t in TRACK_TABLES:
        k = "#" + t
        print("  {:20}{:>12}".format(t, "{:,}".format(s[k]) if k in s else "(表不存在)"))
