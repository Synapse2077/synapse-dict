#!/usr/bin/env python3
"""Commons 文件名的等价判据 —— **八门共用的唯一一份**。2026-09-26。

═══ 为什么必须只有一份 ═══
「同一条录音被存成两行」这笔账在八门上都存在，而判它的规则不是我们定的，
是 **MediaWiki 自己的标题归一规则**（外部事实，永不过期）：

    · 下划线 `_` ≡ 空格            `LL-Q9176_(kor)-…` 与 `LL-Q9176 (kor)-…` 是同一个文件
    · 首字母大小写不敏感            `Es-us-Alejandro.ogg` 与 `es-us-Alejandro.ogg` 同一个
    · 连续空白折叠

再叠上**我们自己入库时带进来**的一层（不是 MediaWiki 的规则，是我们两个写入方的差别）：

    · `X.<oga|ogg|wav|flac|opus>.mp3` 是 X 的**转码派生**，不是另一个文件
      （各维基版内嵌的是转码后的 mp3 名，Commons 收割拿到的是原始名）

🔴🔴 **判据写在两个地方就一定会漂** —— 这条账已经付过两次学费：
   ① 2026-09-25 ko 第一版只认转码后缀、名字要逐字符相同 ⇒ 漏掉 39 组下划线变体；
   ② 同一个脚本里**回核用的判据和分组用的判据不一样**（回核没过 `commons_title`），
      那意味着「修的是下划线这一类，回核却按逐字符比」，刚修掉的那一类永远报 0。
   ⇒ 判据搬到这里，`ko/pipeline/dedupe_audio_transcodes.py`（修）与
     `scripts/test_audio_dup_gate.py`（查）都 import 它，不许再各写一份。
     `[[criteria-from-meaning-not-form]]`、`[[decision-not-propagated-across-editions]]`

⚠️ **不认的两种**（有意留着，它们是不同的文件）：
   · `.ogg` vs `.oga`     —— Commons 上是两个独立文件（`Ko-한국.oga` / `Ko-한국.ogg`）
   · `X` vs `Ko-X`        —— 不同的标题（`결혼식.ogg` / `Ko-결혼식.oga`）
   这两种在页面上排出两个按钮是**对的**，它们真是两条录音；
   按钮标签分不开则是展示层的事（`packages/dict-labels/src/audio.ts`）。
"""
import re

# 转码派生后缀：`X.ogg.mp3` → `X.ogg`
TRANSCODE = re.compile(r"\.(oga|ogg|wav|flac|opus)\.mp3$", re.I)


def original_name(fn):
    """转码名 → 原始 Commons 文件名；本来就是原始名的原样返回。"""
    m = TRANSCODE.search(fn or "")
    return fn[:m.end() - 4] if m else (fn or "")


def commons_title(fn):
    """MediaWiki 标题归一：下划线 ≡ 空格，连续空白折叠。"""
    return re.sub(r"\s+", " ", (fn or "").replace("_", " ")).strip()


def commons_key(fn):
    """**同一个 Commons 文件**的判据键。两行的 key 相同 ⇒ 是同一条录音存了两次。

    🔴🔴 **第一版我在这里写了 `.lower()`（整串小写），当场被闸逮住。**
       MediaWiki 的规则是**只有首字母大小写不敏感**，其余字符敏感 ——
       `File:AB.ogg` 与 `File:Ab.ogg` 在 Commons 上是**两个不同的文件**。
       整串小写把 de 的重复数从 598 虚涨到 1,503，并让 es/it/fr 报出
       9/47/26 组**字段冲突** —— 字段冲突正是「判据把不同的东西并到一起」的信号。
       ⚠️ 更该记的是：我当时在注释里写了「整串小写会多并的那种一例都没有 ——
          实测」，**那句话是编的，我没量过**。判据宽了还给它背书，
          是 `[[criteria-narrower-than-you-think]]` 与
          `[[verify-before-claiming-confirmed]]` 叠在一起犯。
       ⇒ 只归一首字母，其余原样。
    """
    t = commons_title(original_name(fn))
    return (t[:1].lower() + t[1:]) if t else t
