// ============================================================================
// 韩语专属映射表。2026-09-25（阶段 9）。
//
// ═══ 🔴🔴 这个文件的词性表我**写错过一次，而且自己的注释里就写着这个坑** ═══
// 第一版把 26 个**长码**（`noun` / `verb` / `character` / `particle` …）全写了一遍，
// 理由写在原注释里：「全局表用短码，ko 库里存的是长码，直接接全局表徽标全空」。
// 🔴 那句话是对的 —— **但它说的是 `entry.pos_raw` 那一列，而展示层读的是 `entry.pos`。**
//    实测三列三套值域：
//      `entry.pos`      短码（`n` `v` `hanja` `suf` `syl` `prov` `part`）← **展示层读这个**
//      `entry.pos_raw`  长码（`noun` `verb` `character` `suffix` …）    ← 源头原词
//      `dict.pos`       长码 ＋ 斜杠合并（`noun/unknown`）
//    ⇒ 一张按长码写的表接在读短码的地方上，**每一个徽标照样是空的**，
//      而我写的那道覆盖闸查的也是 `pos_raw` —— **闸对准了展示层不读的那一列，报全绿**。
//    `[[correct-steps-can-compose-a-hole]]`：每步都对、跨步假设失效；
//    ⇒ `ko/tests/test_display_labels.py` 已改成查 `entry.pos`（**读者口径**）。
//
// ═══ ⚠️ 覆盖层只放**确实不一样的** ═══
// 照 `[[dict-labels-package]]` 与 ja 的做法：一样的一律走全局 `POS_LABELS`，
// 这个包不是"把所有标签抄一遍"的地方。实测 ko 的 26 个短码里，
// **全局表已经给对了 20 个**，真正要覆盖的只有下面 6 个。
// ⚠️ 而更危险的是**错误的修法**：发现徽标空了顺手加个 `|| raw` 兜底 ——
//    页面上就会印出 `hanja` `syl` 这种英文原码，看着像内容。
//    `[[it-display-layer-stage8]]`：**兜底越体面，缺陷越难发现。**
// ============================================================================

/**
 * 词性覆盖层：韩语与全局 `POS_LABELS` **不同的那些**。查不到就落回全局表。
 * 🔴 **键是 `entry.pos` 的短码**（展示层读的那一列），不是 `pos_raw` 的长码。
 *
 * ⚠️ 返回 `''` 与返回 `undefined` 是两件事：
 *   `''`        ＝ **有意不印**（`unknown`）—— 调用方要把它与 undefined 分开处理
 *   `undefined` ＝ 本层没有意见 ⇒ 落回 `POS_LABELS`
 */
export const KO_POS_LABELS: Record<string, string> = {
  // ── ① 全局表**根本没有**这三个码（实测 `POS_LABELS[code] === undefined`）──
  hanja: '汉字',        // 10,172 条。单个汉字的条目（`犬` → `견` 的汉字形）。
  //                       ⚠️ 与 ja 的 `kanji` 同形而**术语不同**，不共用一行
  syl: '谚文音节',      //    377 条。`주` 这种音节条目，内容是它对应的汉字音
  counter: '量词',      //     95 条。단위 명사（`명`/`마리`/`송이`）

  // ── ② 全局表有、但**韩语里指的不是同一个东西**，必须覆盖 ──
  // 🔴 全局表写「小品词」—— 那是意语的 `sì`/`no`。韩语的 조사 是**助词**
  //    （`은/는/이/가/을/를`），是韩语形态的核心成分。与 ja 覆盖 `part` 同一个理由：
  //    改全局表会让意语跟着变。
  part: '助词',
  // 🔴 全局表写「限定词」。韩语的 관형사（`이`/`그`/`저`/`새`）是**冠形词** ——
  //    它不活用、只作定语，与印欧语的限定词不是一个词类。
  det: '冠形词',

  // ── ③ 全局表写「未标注」，ko 有意印成**什么都不印** ──
  // 🔴 实测 `entry.pos` 里 `unknown` 占 **191,180 / 335,398（57%）**。
  //    那是跨版收词（阶段 4a / K13）带来的：中文版与韩文版很多条目不标词性。
  //    在 57% 的词条页上挂一个「未标注」徽标，读者一条信息都拿不到，只剩噪声；
  //    **没有徽标本身就读作「源头没给词性」**。
  // ⚠️ 但绝不能印成「未知」/「词性不明」—— 那是把「我们没拿到」说成
  //    「这个词词性不明」，`[[dont-say-source-lacks-what-we-skipped]]`：
  //    两件事要在结构上分开。⇒ 只在这里留白，**不在别处替源头补**。
  unknown: '',
};

/**
 * 韩语的词性名。**本层没有意见就返回 `undefined`**，由调用方落回 `POS_LABELS`
 * （与 `jaPosLabel` 同一个契约）。`unknown` 返回 `''` —— 有意不印。
 */
export function koPosLabel(code: string | null | undefined): string | undefined {
  if (!code) return undefined;
  return KO_POS_LABELS[code];
}

/**
 * 语义关系名。🔴 **值域照 `sense_relation.kind` 实测的 21 个写**。
 *
 * 🔴🔴 这张表我**写错过一次，而且是照着我以为有的写**：第一版只有 14 个，
 *   因为我抄的是前面一次 `LIMIT 12` 的查询输出，没回头重新量值域。
 *   当场是**覆盖闸**（表 vs 库里 `SELECT DISTINCT kind`）逮到的，缺 7 个：
 *   counter / descendant / dialectal / holonym / hypernym / hyponym / meronym。
 *   ⇒ `[[expectation-must-be-declared]]`：期望值要**独立声明**，不能从手边
 *     恰好有的那份输出推 —— 而那份输出恰恰是被 `LIMIT` 截断过的。
 *
 * ⚠️ 其中四个是 ko 特有、别门没有的，而且**它们的语义是数据层定死的**，
 *   展示层不许改口径（`[[dict-framework-doc]]`：错比缺更伤权威）：
 *     hanja_spelling  这个谚文词的**汉字表记**（`환면상송` → `換面相訟`）
 *     hanja_form_of   这个汉字条目是哪个谚文词的汉字形
 *     hangeul         这个汉字条目对应的**谚文**读法
 *     alt_hanja       同一个词的**另一种**汉字写法
 * 🔴 `alternative` 不能印成「方言」：南北差异走的是 `alternative` ＋ 变体标签，
 *   数据层**有意不把它断言成 dialectal**（阶段 6b 的决定）。
 */
export const KO_RELATION_LABELS: Record<string, string> = {
  synonym: '近义词',
  antonym: '反义词',
  derived: '派生词',
  related: '相关词',
  coordinate_term: '同类词',
  alt_of: '异体',
  alternative: '异形',        // ⚠️ 不是「方言」—— 见上
  proverb: '谚语',
  abbreviation: '缩略形',
  sound_variant: '语音变体',

  // ── 上下位/整体部分（覆盖闸补的 7 个里的 4 个）──
  hypernym: '上位词',
  hyponym: '下位词',
  holonym: '整体词',
  meronym: '部分词',
  // 🔴 `counter` 在**两张表里各有一个**，意思不同，别合并：
  //    `KO_POS_LABELS.counter` ＝ 这个词**是**量词（단위 명사）
  //    这里的 `counter`        ＝ 这个词**配用**哪个量词（사람 → 명）
  //    `[[criteria-from-meaning-not-form]]`：同一个码在两个位置是两件事。
  counter: '配用量词',
  descendant: '后代词',       // 别的语言从这个词借过去的形
  // 🔴 `dialectal` 实测 75 条，其中 kind 判错的占多数（K19）——
  //    标签照它**声称**的意思写，纠错在数据层做，不在展示层改口径。
  dialectal: '方言形',

  // ── 汉字那一族（ko 特有）──
  // 🔴🔴 这两个的 `target` 是**注不是词**（`換面相訟` 这种多字汉字串我们没有词头，
  //    51,254 条里 43,547 条在 `dict` 里查不到）⇒ 展示层**印文本、不做链接**。
  //    把它们当链接渲染就会造出 4 万个"点了是空白页"，而那不是缺陷，
  //    是**汉字表记本来就不是一个可查的词条**。
  hanja_spelling: '汉字表记',
  alt_hanja: '另一种汉字写法',
  // 下面两个反过来：目标是真词，可以链接
  hanja_form_of: '汉字形',
  hangeul: '谚文读法',
};

export function koRelationLabel(kind: string): string | undefined {
  return KO_RELATION_LABELS[kind];
}

/**
 * 这一类关系的 target 是**注**还是**词**。🔴 决定展示层印不印成链接。
 * 见 `KO_RELATION_LABELS` 里汉字族那两条的理由。
 */
export const KO_ANNOTATION_KINDS = new Set(['hanja_spelling', 'alt_hanja']);

/**
 * 活用类。🔴 **保留韩语术语原词并加中文解释** ——
 * `ㅂ불규칙` 这种名字本身就是韩语学习者要认的东西，译没了反而帮倒忙；
 * 只给中文又对不上任何教材。⇒ 两个都给，展示层决定怎么排。
 */
export const KO_CONJ_CLASS_LABELS: Record<string, string> = {
  규칙: '规则活用',
  여불규칙: '여 不规则（하다 类）',
  ㅂ불규칙: 'ㅂ 不规则',
  ㄷ불규칙: 'ㄷ 不规则',
  ㅅ불규칙: 'ㅅ 不规则',
  ㅎ불규칙: 'ㅎ 不规则',
  르불규칙: '르 不规则',
  러불규칙: '러 不规则',
  ㄹ탈락: 'ㄹ 脱落',
  으탈락: '으 脱落',
};

/**
 * 活用类是怎么来的。🔴 **读者有权知道哪一格是源头给的、哪一格是我们算的。**
 * 把两者印成一样就是拿生成物冒充源头。
 */
export const KO_CONJ_SRC_LABELS: Record<string, string> = {
  forms: '据源头活用表推定',
  suffix: '据构词后缀推定',
};

/**
 * 音标记法 → 定界符。🔴 韩语 98.6% 是**窄式**（带音变的实际音值），
 * 印成 `/…/` 是错的；`bare` ＝源头没说记法，**不许替源头猜**，裸印。
 */
export function koIpaWrap(ipa: string, notation: string): string {
  if (notation === 'narrow') return `[${ipa}]`;
  if (notation === 'phonemic') return `/${ipa}/`;
  return ipa;
}

/** 读音来源。`g2p` 要如实说明是**我们按标准发音法算的**，不是源头给的。 */
export const KO_PRON_SRC_NOTE: Record<string, string> = {
  g2p: '依《표준발음법》规则生成',
};
