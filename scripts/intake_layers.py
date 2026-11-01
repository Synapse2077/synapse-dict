#!/usr/bin/env python3
"""收词之后哪些层要重跑 —— 十门一张表，并且**被写库闸门执行**。2026-11-01（B3）。

═══ 为什么 ═══
同一个形状发生过至少六次，每次都是事后补的：
  pt  收词在变形层之后 ⇒ 30 万变形没人连线，46.2% 的词形成了空白页
  ja  收词之后没重跑读音层 ⇒ 词元读音覆盖 99.90% → 39.8%；中文覆盖 98.66% → 70.77%；声调漏 9 个词三个月
  ko  K13 补收 13,062 个词头之后，罗马字／关系层／例句层三层各要单独补，三次都是事后想起一个补一个
ja/ko/vi/ru 后来有了「收词闸」（插新词形必须写 `invalidates`），但那是**当场一句自由文本**：
声明写在 A 处、活儿干在 B 处，**没有任何东西验证活儿干完了**；另六门连这一句都没有。

═══ 机制（十门 `dbtool.session` 都接）═══
① **插新词形（`__rows__ > 0`）必须传 `rerun=[层名…]`**，层名只能是下表里这一门登记过的；
   `rerun=[]` 是显式声明「一层都不受影响」。建库步骤（tag 以 `build` 开头）豁免。
② 写成功之后，`rerun` 里每一层记进 `data/db/.intake-pending.json`（欠账，落盘）。
③ **之后任何一次写库，tag 以某层登记的前缀开头 ⇒ 那一层销账**（＝那个重跑脚本真的写过库了）；
   不走 `session` 的脚本（`scripts/analyze_db.py`）跑完调 `done()`。
④ 欠账在十门每次写库后打屏，并进汇总闸 `gate:intake-pending`（欠着就红）。
⑤ **怎么验它重跑得对**：`verify` 指向这一门账的闸 `COVERAGE` 里的那一行（覆盖率下限，账的闸每次写库后自动跑）；
   没有 `COVERAGE` 的门写明靠什么。表本身由 `--selftest` 核：脚本在、前缀真出现在脚本里、`verify` 名字真在 `COVERAGE` 里。

⚠️ `invalidates=` 仍在，但只是**备注**（52 个调用点拿它写「这次写库要注意什么」），不再是门禁。

用法：
    python3 scripts/intake_layers.py              # 打欠账；欠着退出码 1（gate:intake-pending）
    python3 scripts/intake_layers.py --table      # 打整张表
    python3 scripts/intake_layers.py --selftest   # 核表＋机制自检（gate:intake-layers）
"""
import datetime
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PENDING = ROOT / "data" / "db" / ".intake-pending.json"
LANGS = ("en", "es", "it", "fr", "pt", "de", "ja", "ko", "vi", "ru")

# 层名 → 它与什么数挂钩（跨门同义）
TIED = {
    "变形连线": "词元集合：新收的原形要被已有变形指回来，新收的变形要指到原形（`inflection.base_id`）",
    "读音": "词元集合：每个新词元的音标／读音行",
    "重音": "词元集合：每个新词元的重音位置",
    "假名读音": "词元集合：`entry.kana` 按词元回填",
    "人工读音": "词元集合：源头给的人工读音",
    "规则读音": "词元集合：G2P 规则生成的读音（与人工的分开报）",
    "罗马字": "词元集合：四套罗马字按词元生成",
    "汉字层": "词元集合中的汉字词：汉字读音／音训／汉字表记",
    "活用类": "用言词元：活用类与活用表",
    "义项标签": "义项集合：新收义项的语域／地区等标签",
    "量词": "名词词元：量词搭配",
    "义项中文": "义项集合：新收义项的中文（付费跑批）",
    "例句": "词元集合：新词元在源头的例句（收割按词形对）",
    "例句中文": "例句集合：新收例句的中文（付费跑批）",
    "关系": "词元集合：新词元自己的关系 ＋ 旧关系里指向新词元的目标（死链变活链）",
    "词源": "词元集合：新词元的词源正文（按词源号对齐）",
    "词源中文": "词源集合：新收词源的中文",
    "频次": "词元集合：`freq_zipf` 等频次列按词形回填",
    "录音": "词元集合：Commons 录音按词形挂",
    "出版正文": "出版层中文的简体出版列（`text_pub`）—— 新行要同步",
    "搜索前缀": "词元集合：搜索下拉的预计算前缀表（新词搜不到＝白收）",
    "统计信息": "全库：`sqlite_stat1`（行数变了一个量级时计划器会选错）",
}


def L(layer, rerun, tags, verify=None, note=""):
    """一条登记。tags：能证明「这一层重跑过了」的会话标签前缀；verify：COVERAGE 名或 None（note 写明靠什么）。"""
    return {"layer": layer, "rerun": rerun, "tags": tuple(tags), "verify": verify, "note": note}


ETYM = "scripts/ingest_etymology.py --lang %s --run --replace"
ANALYZE = "scripts/analyze_db.py --lang %s --apply"
NOCOV = "这一门没有 `COVERAGE` 覆盖率表 ⇒ 靠「重跑脚本写过库」销账 ＋ 写库后自动跑的回归闸"

LAYERS = {
    "en": [
        L("变形连线", "en/pipeline/build_inflection_layer.py", ["keep-v3-2-inflection"], note=NOCOV),
        L("读音", "en/pipeline/build_pronunciation.py", ["keep-v3-4-pronunciation"], note=NOCOV),
        L("例句", "en/pipeline/build_ex_rel.py", ["keep-v3-5ab-ex-rel"], note="与关系同一个脚本。" + NOCOV),
        L("关系", "en/pipeline/build_ex_rel.py", ["keep-v3-5ab-ex-rel"], note="与例句同一个脚本。" + NOCOV),
        L("义项标签", "en/pipeline/build_sense_tags.py", ["keep-v3-1d-tags"],
          note="⚠️ 它是清空重建，会撤销建库后的定点修复（见它的文件头与 `en/fixes/fill_late_middle_register.py`）—— 新词只补不重建。" + NOCOV),
        L("频次", "en/pipeline/fill_freq.py", ["keep-v3-5d-freq"], note=NOCOV),
        L("录音", "en/pipeline/harvest_audio.py", ["keep-v3-6-audio"], note=NOCOV),
        L("词源", ETYM % "en", ["ingest-etymology-en"], note=NOCOV),
        L("义项中文", "en/pipeline/translate_defs.py", ["keep-v3-15c-defs"], note="付费。" + NOCOV),
        L("例句中文", "en/pipeline/translate_examples.py", ["keep-v3-example-gloss"], note="付费。" + NOCOV),
        L("搜索前缀", "en/pipeline/build_search_prefix.py", ["keep-v3-9-search-prefix"], note=NOCOV),
        L("统计信息", ANALYZE % "en", [], note="不走 session，跑完调 `done()`"),
    ],
    "es": [
        L("变形连线", "es/pipeline/build_inflection_layer.py", ["inflection-layer"], note=NOCOV),
        L("读音", "es/pipeline/build_pronunciation_layer.py", ["build-pronunciation-layer"], note=NOCOV),
        L("例句", "es/pipeline/build_example_layer.py", ["build-example-layer"], note=NOCOV),
        L("关系", "es/pipeline/build_relation_layer.py", ["build-relation-layer"], note=NOCOV),
        L("频次", "es/pipeline/build_frequency_layer.py", ["build-frequency-layer"], note=NOCOV),
        L("录音", "es/pipeline/ingest_audio.py", ["ingest-audio"], note=NOCOV),
        L("词源", ETYM % "es", ["ingest-etymology-es"], note=NOCOV),
        L("义项中文", "es/pipeline/translate_sense_gap.py", ["translate-sense-gap-"], note="付费。" + NOCOV),
        L("例句中文", "es/pipeline/translate_examples.py", ["translate-examples"], note="付费。" + NOCOV),
        L("搜索前缀", "es/pipeline/build_search_prefix.py", ["search-prefix"], note=NOCOV),
        L("统计信息", ANALYZE % "es", [], note="不走 session，跑完调 `done()`"),
    ],
    "it": [
        L("变形连线", "it/pipeline/build_inflection_layer.py", ["keep-v3-inflection"], note=NOCOV),
        L("读音", "it/pipeline/build_pronunciation_layer.py", ["build-pronunciation-layer"], note=NOCOV),
        L("例句", "it/pipeline/ingest_examples.py", ["ingest-examples"], note=NOCOV),
        L("关系", "it/pipeline/ingest_relations.py", ["ingest-relations"], note=NOCOV),
        L("频次", "it/pipeline/build_freq_layer.py", ["build-freq-layer"], note=NOCOV),
        L("录音", "it/pipeline/ingest_audio_urls.py", ["ingest-audio-urls"], note=NOCOV),
        L("词源", ETYM % "it" + "（意语版另加 --edition it-edition）", ["ingest-etymology-it"], note=NOCOV),
        L("义项中文", "it/pipeline/translate_it_defs.py", ["translate-it-defs"], note="付费。" + NOCOV),
        L("例句中文", "it/pipeline/translate_examples.py", ["translate-examples"], note="付费。" + NOCOV),
        L("搜索前缀", "it/pipeline/build_search_prefix.py", ["search-prefix"], note=NOCOV),
        L("统计信息", ANALYZE % "it", [], note="不走 session，跑完调 `done()`"),
    ],
    "fr": [
        L("变形连线", "fr/pipeline/build_inflection_layer.py", ["keep-v3-infl"], note=NOCOV),
        L("读音", "fr/pipeline/build_pronunciation_layer.py", ["keep-v3-pron"], note=NOCOV),
        L("例句", "fr/pipeline/ingest_examples.py", ["keep-v3-examples"], note=NOCOV),
        L("关系", "fr/pipeline/ingest_fr_relations.py", ["keep-v3-fr-relations"], note=NOCOV),
        L("频次", "fr/pipeline/build_freq_layer.py", ["build-fr-freq-layer"], note=NOCOV),
        L("录音", "fr/pipeline/ingest_audio_urls.py", ["keep-v3-fr-audio-urls"], note=NOCOV),
        L("词源", ETYM % "fr" + "（法语版另加 --edition fr-edition）", ["ingest-etymology-fr"], note=NOCOV),
        L("义项中文", "fr/pipeline/gloss_translate.py", ["keep-v3-gloss-zh"], note="付费。" + NOCOV),
        L("例句中文", "fr/pipeline/translate_examples.py", ["keep-v3-example-zh"], note="付费。" + NOCOV),
        L("搜索前缀", "fr/pipeline/build_search_prefix.py", ["search-prefix"], note=NOCOV),
        L("统计信息", ANALYZE % "fr", [], note="不走 session，跑完调 `done()`"),
    ],
    "pt": [
        L("变形连线", "pt/pipeline/build_inflection_layer.py", ["keep-v3-infl"],
          note="⭐ pt 栽过：收词在变形层之后 ⇒ 46.2% 空白页。另有 `link_table_forms.py`（keep-v3-2c-link-forms）补链。" + NOCOV),
        L("读音", "pt/pipeline/harvest_pronunciation.py", ["keep-v3-ipa-harvest"], note=NOCOV),
        L("例句", "pt/pipeline/ingest_examples.py", ["keep-v3-5c-examples"], note=NOCOV),
        L("关系", "pt/pipeline/ingest_relations.py", ["keep-v3-5b-relations"], note=NOCOV),
        L("频次", "pt/pipeline/build_freq_layer.py", ["build-pt-freq-layer"], note=NOCOV),
        L("录音", "pt/pipeline/ingest_audio.py", ["keep-v3-6-audio"], note=NOCOV),
        L("词源", ETYM % "pt", ["ingest-etymology-pt"], note=NOCOV),
        L("义项中文", "pt/pipeline/translate_defs.py", ["keep-v3-15b-def-zh"], note="付费。" + NOCOV),
        L("例句中文", "pt/pipeline/translate_examples.py", ["keep-v3-example-zh"], note="付费。" + NOCOV),
        L("搜索前缀", "pt/pipeline/build_search_prefix.py", ["search-prefix"], note=NOCOV),
        L("统计信息", ANALYZE % "pt", [], note="不走 session，跑完调 `done()`"),
    ],
    "de": [
        L("变形连线", "de/pipeline/build_inflection_layer.py", ["keep-v3-infl"],
          note="各版补链另有 `link_edition_forms.py`（keep-v3-2c-…）。" + NOCOV),
        L("读音", "de/pipeline/harvest_pronunciation.py", ["keep-v3-4-pron-de"], note=NOCOV),
        L("例句", "de/pipeline/harvest_examples.py", ["keep-v3-5a-examples"], note=NOCOV),
        L("关系", "de/pipeline/harvest_relations.py", ["keep-v3-5c-relations"], note=NOCOV),
        L("频次", "de/pipeline/fill_freq.py", ["keep-v3-5d-freq"], note=NOCOV),
        L("录音", "de/pipeline/harvest_audio.py", ["keep-v3-6-audio"], note=NOCOV),
        L("词源", ETYM % "de" + "（德语版另加 --edition kk-de）", ["ingest-etymology-de", "ingest-etymology-kk-de"], note=NOCOV),
        L("义项中文", "de/pipeline/translate_defs.py", ["keep-v3-15b-def-zh"], note="付费。" + NOCOV),
        L("例句中文", "de/pipeline/translate_examples.py", ["keep-v3-5b-example-zh"], note="付费。" + NOCOV),
        L("搜索前缀", "de/pipeline/build_search_prefix.py", ["keep-v3-9-search-prefix"], note=NOCOV),
        L("统计信息", ANALYZE % "de", [], note="不走 session，跑完调 `done()`"),
    ],
    "ja": [
        L("变形连线", "ja/pipeline/build_inflection_layer.py", ["ja-inflection-layer"], "**不是**空白页的词形占比"),
        L("读音", "ja/pipeline/build_pronunciation.py", ["ja-pronunciation"], "核心词的声调覆盖率",
          note="⭐ ja 阶段 5d 收词后漏了 9 个词的声调三个月"),
        L("假名读音", "ja/pipeline/backfill_kana.py", ["ja-backfill-kana"], "词元的假名读音覆盖率",
          note="⭐ 3a 收词那次 99.90% → 39.8% 而没有闸会响"),
        L("汉字层", "ja/pipeline/build_kanji_reading.py", ["ja-kanji-reading"], "常用汉字的音訓読み覆盖率"),
        L("义项标签", "ja/pipeline/build_sense_tags.py", ["ja-sense-tags"], "义项标签覆盖率"),
        L("例句", "ja/pipeline/harvest_examples.py", ["ja-harvest-examples"], note="ja 的 `COVERAGE` 没有例句一行 ⇒ 靠销账 ＋ 回归闸"),
        L("关系", "ja/pipeline/harvest_relations.py", ["ja-harvest-relations"], note="ja 的 `COVERAGE` 没有关系一行 ⇒ 靠销账 ＋ 回归闸"),
        L("频次", "ja/pipeline/fill_freq.py", ["ja-fill-freq"], note="靠销账 ＋ 回归闸"),
        L("录音", "ja/pipeline/harvest_audio.py", ["ja-harvest-audio"], note="靠销账 ＋ 回归闸"),
        L("词源", ETYM % "ja", ["ingest-etymology-ja"], "有英文版词条的词里带词源正文的占比"),
        L("义项中文", "ja/pipeline/translate_defs.py", ["ja-translate-defs"], "义项的中文覆盖率",
          note="付费。⭐ 3a 收词那次 98.66% → 70.77%"),
        L("例句中文", "ja/pipeline/translate_examples.py", ["ja-translate-examples"], note="付费。靠销账 ＋ 回归闸"),
        L("搜索前缀", "ja/pipeline/build_search_prefix.py", ["ja-build-search-prefix"], note="靠销账 ＋ 回归闸"),
        L("统计信息", "ja/pipeline/run_analyze.py --run", ["ja-analyze"], note="回归闸 X5 查统计信息是否过期"),
    ],
    "ko": [
        L("变形连线", "ko/pipeline/build_inflection_layer.py（规则生成另跑 conj_generate.py）",
          ["build-ko-inflection", "ko-generate-conjugation"], "变形形能指回原形的占比"),
        L("人工读音", "ko/pipeline/build_pronunciation.py", ["build-ko-pronunciation"], "词元的**人工**读音覆盖率（g2p 不算）",
          note="⭐ K13 那批 99.7% 带人工 IPA 而一行都没进 `pronunciation`"),
        L("规则读音", "ko/pipeline/fill_g2p_pronunciation.py", ["fill-ko-g2p-pronunciation"], "词元的读音覆盖率（含规则生成）"),
        L("罗马字", "ko/pipeline/fill_romanization.py --topup", ["fill-ko-romanization"],
          note="⭐ K13 补收后 22,868 → 77,741 是事后想起来补的。`COVERAGE` 没有罗马字一行 ⇒ 靠销账 ＋ 外锚闸 `verify_layers_vs_dump.py`"),
        L("汉字层", "ko/pipeline/build_hanja_reading.py（音训另跑 fill_eumhun.py）",
          ["build-ko-hanja-reading", "fill-ko-eumhun"], "汉字音节里有音训的占比"),
        L("活用类", "ko/pipeline/fill_conj_class.py（规则推导另跑 derive_conj_class.py）",
          ["fill-ko-conj-class", "ko-derive-conj-class"], "用言词条里能说出活用类的占比（全部来源）"),
        L("例句", "ko/pipeline/topup_examples_new_words.py", ["ko-topup-examples"],
          note="⭐ K13 那 1 条是外锚闸逮到的。靠销账 ＋ 外锚闸"),
        L("关系", "ko/pipeline/topup_relations_new_words.py", ["ko-topup-relations-new-words"],
          note="⭐ K13 补收后 +3,838 是事后定向补写的。靠销账 ＋ 外锚闸"),
        L("录音", "ko/pipeline/harvest_audio.py", ["ko-harvest-audio"], note="靠销账 ＋ 外锚闸"),
        L("词源", "ko/pipeline/build_etymology.py", ["ko-build-etymology"], note="靠销账 ＋ 外锚闸"),
        L("义项中文", "ko/pipeline/translate_glosses.py", ["load-ko-zh-glosses"], "读者能看到的义项里有中文的占比（非 hidden）", note="付费"),
        L("例句中文", "ko/pipeline/translate_examples.py", ["ko-load-example-zh"], "读者能看到的例句里有中文的占比", note="付费"),
        L("词源中文", "ko/pipeline/translate_etymology.py", ["ko-load-etymology-zh"], note="付费。靠销账"),
        L("统计信息", "ko/pipeline/analyze_db.py", ["ko-analyze"], note="靠销账"),
    ],
    "vi": [
        L("读音", "vi/pipeline/build_pronunciation.py（方言合成另跑 compose_pronunciation.py）",
          ["build-vi-pronunciation", "compose-vi-pronunciation"], "音标（读者口径）"),
        L("汉字层", "vi/pipeline/build_han_layer.py", ["build-vi-han-layer"], "汉字表记"),
        L("例句", "vi/pipeline/build_example_layer.py --sync", ["build-vi-example-layer", "sync-vi-example-layer"], "例句（读者口径）"),
        L("关系", "vi/pipeline/build_relation_layer.py", ["build-vi-relation-layer", "sync-vi-relation-sense-id"], "语义关系（读者口径）"),
        L("量词", "vi/pipeline/build_classifier_layer.py", ["build-vi-classifier-layer"], "量词"),
        L("录音", "vi/pipeline/build_audio_layer.py", ["build-vi-audio-layer"], "录音"),
        L("词源", "vi/pipeline/build_etymology_layer.py", ["build-vi-etymology-layer"], "词源（读者口径）"),
        L("义项中文", "vi/pipeline/translate_glosses.py", ["load-vi-zh-glosses"], "中文释义（读者口径）", note="付费"),
        L("例句中文", "vi/pipeline/translate_examples.py", ["vi-6e-example-zh"], "例句中文（读者口径）", note="付费"),
        L("出版正文", "vi/pipeline/zh_pub.py", ["b29-vi-zh-pub"], note="回归闸 P37 锁出版正文与判据一致"),
        L("统计信息", ANALYZE % "vi", [], note="不走 session，跑完调 `done()`"),
    ],
    "ru": [
        L("变形连线", "ru/pipeline/inflection_layer.py", ["inflection-layer"], note="靠销账 ＋ ru 的变形层闸"),
        L("重音", "ru/pipeline/stress_layer.py", ["stress-layer"], "词元·带重音拼写"),
        L("读音", "ru/pipeline/pronunciation_layer.py", ["pronunciation-layer"], note="靠销账 ＋ ru 的读音层闸"),
        L("例句", "ru/pipeline/example_layer.py", ["example-layer", "example-sync-"], note="靠销账 ＋ ru 的例句层闸"),
        L("关系", "ru/pipeline/relation_layer.py", ["relation-layer"], note="靠销账 ＋ ru 的关系层闸"),
        L("录音", "ru/pipeline/audio_layer.py", ["audio-layer"], note="靠销账 ＋ ru 的录音层闸"),
        L("词源", "ru/pipeline/etymology_layer.py", ["etymology-layer"], "词元·有可出版词源"),
        L("义项中文", "ru/pipeline/translate_glosses.py", ["load-ru-zh-glosses"], "词元·有可印中文", note="付费"),
        L("例句中文", "ru/pipeline/translate_examples.py", ["example-zh-load"], "可出版例句·有中文", note="付费"),
        L("词源中文", "ru/pipeline/translate_etymology.py", ["etymology-zh-load"], "词元·有中文词源",
          note="付费；7b 用户确认暂不翻译 —— 只在有人重开 7b 时才真的要跑"),
        L("出版正文", "ru/pipeline/zh_pub.py", ["zh-pub-r29"], note="靠销账"),
        L("统计信息", ANALYZE % "ru", [], note="不走 session，跑完调 `done()`"),
    ],
}


def lang_of(dbtool_file):
    return Path(dbtool_file).resolve().parent.name


def names(lang):
    return [x["layer"] for x in LAYERS.get(lang, [])]


# ── 写库闸门调这三个 ─────────────────────────────────────────────────────
def check_rerun(dbtool_file, tag, expect, rerun):
    """session 开头调。插新词形而没声明 `rerun` ⇒ 拒绝；声明了表里没有的层名 ⇒ 拒绝。"""
    lang = lang_of(dbtool_file)
    rows = (expect or {}).get("__rows__", 0) or 0
    if rerun is not None:
        bad = [x for x in rerun if x not in names(lang)]
        if bad:
            raise SystemExit("🔴 `rerun=` 里有 %s 这一门没登记的层：%s\n   %s 登记过的：%s\n   （表在 scripts/intake_layers.py；新层先登记再用）"
                             % (lang, "、".join(map(repr, bad)), lang, "、".join(names(lang))))
        return
    if rows > 0 and not tag.startswith("build"):
        raise SystemExit(
            "🔴 tag=%r 要插 %s 行新词形，但没有声明 `rerun=[...]`（B3 收词闸）。\n"
            "   收词会让按词元算的层静默过期 —— pt 46.2%% 空白页、ja 读音 99.90%%→39.8%%、ko 三层事后补。\n"
            "   %s 登记过的层：%s\n"
            "   ⇒ 传 `rerun=[...]` 列出要重跑的（写完记欠账，那几个脚本写过库才销账），或 `rerun=[]` **显式**声明一层都不受影响。"
            % (tag, format(rows, ","), lang, "、".join(names(lang))))


def _load():
    if not PENDING.exists():
        return {}
    try:
        return json.loads(PENDING.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise SystemExit("🔴 收词欠账读不动：%s（%s）—— 别当成「没欠」" % (PENDING, e))


def _save(d):
    PENDING.parent.mkdir(parents=True, exist_ok=True)
    PENDING.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def settle(pend, lang, tag, rerun, when):
    """纯函数。→ 新的欠账表。先按 tag 销账（这次写库就是某层的重跑），再记这次声明的新欠账。"""
    pend = {k: dict(v) for k, v in pend.items()}
    mine = pend.get(lang, {})
    for x in LAYERS.get(lang, []):
        if x["layer"] in mine and any(tag.startswith(p) for p in x["tags"]):
            del mine[x["layer"]]
    for layer in rerun or []:
        mine[layer] = {"by": tag, "when": when}
    if mine:
        pend[lang] = mine
    else:
        pend.pop(lang, None)
    return pend


def after_commit(dbtool_file, tag, rerun):
    """session 写成功（不变量核对通过）之后调。销账／记账，并打这一门还欠什么。只报不拦。"""
    lang = lang_of(dbtool_file)
    try:
        pend = _load()
        new = settle(pend, lang, tag, rerun, datetime.datetime.now().isoformat(timespec="seconds"))
        if new != pend:
            _save(new)
        gone = sorted(set(pend.get(lang, {})) - set(new.get(lang, {})))
        for g in gone:
            print("■ ✅ 收词欠账销掉：%s（%s 这次写库就是它的重跑）" % (g, tag))
        owe = new.get(lang, {})
        if owe:
            print("■ 🔴 %s 收词后还欠重跑 %d 层：" % (lang, len(owe)))
            by = {x["layer"]: x for x in LAYERS.get(lang, [])}
            for layer, rec in owe.items():
                print("     · %-6s ← %s（%s）⇒ %s" % (layer, rec.get("by"), rec.get("when"), by.get(layer, {}).get("rerun", "?")))
    except SystemExit as e:
        print("⚠️ %s" % e)


def done(lang, layer):
    """不走 session 的重跑脚本（`analyze_db.py`）跑完调。"""
    pend = _load()
    if layer in pend.get(lang, {}):
        del pend[lang][layer]
        if not pend[lang]:
            del pend[lang]
        _save(pend)
        print("■ ✅ 收词欠账销掉：%s / %s" % (lang, layer))


# ── 核表 ─────────────────────────────────────────────────────────────────
def coverage_names(lang):
    """→ 这一门账的闸 COVERAGE 的行名集合；没有 COVERAGE 返回 None。元组表（ja/ko/ru）与字典表（vi）都认。"""
    f = ROOT / lang / "tests" / "test_plan_ledger.py"
    if not f.exists():
        return None
    old = list(sys.path)
    sys.path[:0] = [str(ROOT / lang), str(ROOT / lang / "tests")]
    try:
        spec = importlib.util.spec_from_file_location("_ledger_" + lang, f)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        cov = getattr(m, "COVERAGE", None)
    finally:
        sys.path[:] = old
    if cov is None:
        return None
    return set(cov) if isinstance(cov, dict) else {c[0] for c in cov}


def audit_table(layers=None, cov_of=coverage_names):
    """→ 问题列表。纯（除了读文件）。"""
    layers = LAYERS if layers is None else layers
    bad = []
    if set(layers) != set(LANGS):
        bad.append("门不全：缺 %s／多 %s" % (sorted(set(LANGS) - set(layers)), sorted(set(layers) - set(LANGS))))
    for lang, xs in layers.items():
        seen = set()
        cov = cov_of(lang)
        for x in xs:
            if x["layer"] not in TIED:
                bad.append("%s：层名 %r 不在 TIED 里（先写清它与什么数挂钩）" % (lang, x["layer"]))
            if x["layer"] in seen:
                bad.append("%s：层 %r 登记了两次" % (lang, x["layer"]))
            seen.add(x["layer"])
            script = ROOT / x["rerun"].split()[0].split("（")[0]
            if not script.exists():
                bad.append("%s/%s：重跑脚本不在 %s" % (lang, x["layer"], script.relative_to(ROOT)))
                continue
            src = script.read_text(encoding="utf-8")
            if x["tags"]:
                # 前缀必须真出现在脚本里（或同目录的另一个登记脚本里）——否则这一层永远销不了账
                others = [ROOT / t.split()[0] for t in re.findall(r"[\w/]+\.py", x["rerun"])]
                body = src + "".join((script.parent / o.name).read_text(encoding="utf-8")
                                     for o in others if (script.parent / o.name).exists())
                # 模板拼出来的标签（`"ingest-etymology-%s" % lang`）：取占位符之前那一截当前缀
                stems = [s.split("%")[0].split("{")[0] for s in re.findall(r'"([^"\n]*(?:%s|\{)[^"\n]*)"', body)]
                for p in x["tags"]:
                    if p not in body and not any(st and p.startswith(st) for st in stems):
                        bad.append("%s/%s：销账前缀 %r 不在重跑脚本里（这一层会永远欠着）" % (lang, x["layer"], p))
            elif "done(" not in src:
                bad.append("%s/%s：没有销账前缀，而 %s 里也没调 `done()`" % (lang, x["layer"], script.name))
            if x["verify"] is not None:
                if cov is None:
                    bad.append("%s/%s：verify=%r 但这一门没有 COVERAGE" % (lang, x["layer"], x["verify"]))
                elif x["verify"] not in cov:
                    bad.append("%s/%s：verify=%r 不在 COVERAGE 里（改名了？）" % (lang, x["layer"], x["verify"]))
            elif not x["note"]:
                bad.append("%s/%s：没有 verify 也没写靠什么验" % (lang, x["layer"]))
    return bad


def selftest():
    bad = audit_table()
    for b in bad:
        print("🔴 " + b)
    n_tab = sum(len(v) for v in LAYERS.values())
    # 机制：settle 的分支
    W = "t"
    cases = [
        ("记账", settle({}, "ja", "ja-intake-x", ["读音", "义项中文"], W), {"ja": {"读音": {"by": "ja-intake-x", "when": W}, "义项中文": {"by": "ja-intake-x", "when": W}}}),
        ("重跑销账", settle({"ja": {"读音": {"by": "a", "when": W}}}, "ja", "ja-pronunciation", None, W), {}),
        ("别的门不销", settle({"ko": {"录音": {"by": "a", "when": W}}}, "ja", "ja-harvest-audio", None, W), {"ko": {"录音": {"by": "a", "when": W}}}),
        ("不相干的写库不销", settle({"ja": {"读音": {"by": "a", "when": W}}}, "ja", "ja-fill-freq", None, W), {"ja": {"读音": {"by": "a", "when": W}}}),
        ("前缀只认开头", settle({"ja": {"读音": {"by": "a", "when": W}}}, "ja", "x-ja-pronunciation", None, W), {"ja": {"读音": {"by": "a", "when": W}}}),
    ]
    for name, got, want in cases:
        if got != want:
            bad.append("settle「%s」→ %s，应为 %s" % (name, got, want))
            print("🔴 settle「%s」" % name)
    # check_rerun 的分支
    f = str(ROOT / "ja" / "dbtool.py")
    for name, args, should_raise in [
        ("插行没声明", ("ja-x", {"__rows__": 5}, None), True),
        ("插行声明空表", ("ja-x", {"__rows__": 5}, []), False),
        ("插行声明登记过的层", ("ja-x", {"__rows__": 5}, ["读音"]), False),
        ("声明了没登记的层", ("ja-x", {}, ["罗马字"]), True),
        ("建库豁免", ("build-ja", {"__rows__": 5}, None), False),
        ("不插行不用声明", ("ja-x", {"#sense": 3}, None), False),
    ]:
        try:
            check_rerun(f, *args)
            raised = False
        except SystemExit:
            raised = True
        if raised != should_raise:
            bad.append("check_rerun「%s」%s" % (name, "该拒没拒" if should_raise else "不该拒却拒了"))
            print("🔴 check_rerun「%s」" % name)
    # 核表自己的变异：把一条登记弄坏，audit_table 必须红
    import copy
    for name, mut in [
        ("脚本路径写错", lambda t: t["ja"][0].update(rerun="ja/pipeline/no_such.py")),
        ("销账前缀写错", lambda t: t["ko"][0].update(tags=("no-such-tag",))),
        ("verify 名字改了", lambda t: t["ru"][1].update(verify="不存在的覆盖率")),
        ("层名没登记进 TIED", lambda t: t["en"][0].update(layer="神秘层")),
        ("少一门", lambda t: t.pop("vi")),
        ("没有 verify 也没写靠什么", lambda t: t["es"][0].update(note="")),
        ("不走 session 却没调 done()", lambda t: t["ko"][-1].update(tags=(), rerun="ko/pipeline/build_etymology.py")),
    ]:
        t = copy.deepcopy(LAYERS)
        mut(t)
        if not audit_table(t):
            bad.append("核表变异「%s」没被逮到" % name)
            print("🔴 核表变异「%s」没被逮到" % name)
    print("%s 收词层表：十门 %d 层；核表＋机制自检%s" % ("🔴" if bad else "✅", n_tab, "：%d 处失败" % len(bad) if bad else "通过（settle 5／check_rerun 6／核表变异 7）"))
    return 1 if bad else 0


def show_pending():
    pend = _load()
    n = sum(len(v) for v in pend.values())
    print("■ 收词欠账：%d 层" % n)
    by = {(l, x["layer"]): x for l, xs in LAYERS.items() for x in xs}
    for lang, owe in sorted(pend.items()):
        for layer, rec in owe.items():
            print("  🔴 %s / %-6s ← %s（%s）⇒ %s" % (lang, layer, rec.get("by"), rec.get("when"), by.get((lang, layer), {}).get("rerun", "?")))
    if not n:
        print("  ✅ 没有欠着的重跑")
    return 1 if n else 0


def show_table():
    for lang in LANGS:
        print("════ %s" % lang)
        for x in LAYERS[lang]:
            print("  %-6s %s\n         挂钩：%s\n         验：%s" % (
                x["layer"], x["rerun"], TIED[x["layer"]],
                ("账的闸 COVERAGE「%s」" % x["verify"]) if x["verify"] else x["note"]))


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--selftest" in a:
        sys.exit(selftest())
    if "--table" in a:
        show_table()
        sys.exit(0)
    sys.exit(show_pending())
