// ============================================================================
// 日语专属映射表。2026-09-16（阶段 8）。
//
// 🔴 **日语是第一门需要「按语种覆盖词性名」的语言。**
//    前六门共用一张 `POS_LABELS` 一直够用，因为拉丁语言的词性体系彼此接近。
//    日语有三个**别的语言根本没有**的词类，还有一个**同码不同义**的：
//
//      kanji / kana / romaji   ← 汉字条目 / 假名条目 / 罗马字条目，六门全无
//      adnom（連体詞）          ← `この`『その』，不是形容词也不是限定词
//      counter（助数詞）        ← 数词后缀，`本`『枚』『匹』
//      🔴 part：全局表写「小品词」，而日语的 `particle` 是**助词**（は/が/を/に）
//         —— 同一个码，两门语言指的不是一个东西。**这正是要 per-lang 覆盖层的理由**：
//         改全局表会让意语的 `sì`/`no`（那才是小品词）跟着变。
//
// ⚠️ 覆盖层只放**确实不一样的**，一样的一律走全局表（`[[dict-labels-package]]`：
//    这个包是展示层映射表唯一的家，但不是"把所有标签抄一遍"的地方）。
// ============================================================================

/** 词性覆盖层：日语与全局表不同的那些。查不到就落回 `POS_LABELS`。 */
export const JA_POS_LABELS: Record<string, string> = {
  // ── 六门全无的三个 ──
  kanji: '汉字',
  kana: '假名',
  romaji: '罗马字',
  // ── 日语词类 ──
  adnom: '连体词',
  // ⚠️ `counter` 译「量词」还是「助数词」是 `JA_PLAN` §四.3 记着的**待用户拍板**项：
  //    可读性 vs 忠于源头术语。**先用「量词」**（中文读者认得），
  //    改的话只改这一行 —— 这就是覆盖层的价值。
  counter: '量词',
  // ── 🔴 同码不同义：必须覆盖 ──
  part: '助词',          // 全局表是「小品词」（意语的 sì/no），日语的是 は/が/を/に
  comb: '接续成分',      // 全局表无；日语这 31 条全是 っ/ッ/ー/ん
  // ── 语气更贴日语 ──
  intj: '感叹词',
  prov: '谚语',
};

/** 日语的词性名。`raw` 支持 `n/v` 这种聚合值，由调用方拆开后逐段查。 */
export function jaPosLabel(code: string): string | undefined {
  return JA_POS_LABELS[code];
}

/** 活用类（`entry.vclass`）。**词元的属性，不是某个形的属性。**
 *
 * 🔴 代码形如 `godan-ka`（五段・カ行）／`sa-irregular`（サ行変格）。
 *    `irregular` **不会单独出现** —— サ変和カ変是两个不同的活用类，
 *    只存 `irregular` 等于把两种东西合成一个（`fill_vclass.vclass_of` 保证）。
 */
const ROW_ZH: Record<string, string> = {
  a: 'ア', ka: 'カ', sa: 'サ', ta: 'タ', na: 'ナ', ha: 'ハ',
  ma: 'マ', ya: 'ヤ', ra: 'ラ', wa: 'ワ', ba: 'バ', ga: 'ガ',
};
const STEM_ZH: Record<string, string> = {
  godan: '五段', ichidan: '一段', nidan: '二段', yodan: '四段',
  'shimo-ichidan': '下一段', 'kami-ichidan': '上一段',
  'shimo-nidan': '下二段', 'kami-nidan': '上二段',
};
export function jaVclassLabel(code: string | null): string {
  if (!code) return '';
  if (code.endsWith('-irregular')) {
    const r = ROW_ZH[code.slice(0, -'-irregular'.length)];
    return r ? `${r}行变格活用` : '变格活用';
  }
  const i = code.lastIndexOf('-');
  if (i < 0) return STEM_ZH[code] ?? code;
  const stem = STEM_ZH[code.slice(0, i)];
  const row = ROW_ZH[code.slice(i + 1)];
  if (!stem) return code;
  return row ? `${stem}活用・${row}行` : `${stem}活用`;
}

/** 字种等级（`entry.kanji_grade`）。源头来自 `senses[].categories`。 */
export const JA_KANJI_GRADE_LABELS: Record<string, string> = {
  jōyō: '常用汉字',
  kyōiku: '教育汉字',
  jinmeiyō: '人名用汉字',
  hyōgai: '表外汉字',
};

/** 东京式声调型。由「重音核位置 + 拍数」唯一决定，**库里不存这一列**，展示层算。
 *
 * 🔴 判据写在这里而不是存进库，是因为它**可以被推导**：存一个可推导的列，
 *    就是留一个会和 `pitch_pos` 打架的冗余列（见 `ja/pipeline/build_pronunciation.py`）。
 */
export function jaPitchType(pos: number | null, mora: number): string {
  if (pos === null || pos === undefined) return '';
  if (pos === 0) return '平板型';
  if (pos === 1) return '头高型';
  if (pos === mora) return '尾高型';
  return '中高型';
}

/** 关系类型里日语特有的那两个。其余走 `RELATION_LABELS`。 */
export const JA_RELATION_LABELS: Record<string, string> = {
  // 🔴 **日语这一门把 13 个 kind 全列出来，不靠全局表兜底。** 理由是实测：
  //    `relTagLabel()` 对 `related`/`synonym`/`antonym` 返回的是**空字符串** ——
  //    渲染出来是个**空标签**，比印英文码更难发现（印 `derived` 至少扎眼）。
  //    另外 8 个（derived/proverb/coordinate/hyponym/hypernym/abbreviation/
  //    meronym/holonym）直接原样返回英文码。
  //    ⇒ 展示层契约闸原来只查「有没有印出英文码」，**对空标签结构性失明**，
  //      13 个里只逮到 1 个。判据已同时加上「标签不许为空」。
  synonym: '近义词', antonym: '反义词',
  hypernym: '上位词', hyponym: '下位词',
  coordinate: '同位词', holonym: '整体词', meronym: '部分词',
  derived: '派生词', related: '相关词',
  proverb: '谚语', abbreviation: '缩写',
  alt_of: '异体写法',
  // 🔴 2026-09-16 加：从英文版指针正文里抽出的字体关系（`佛` → `仏`）。
  //    日语词典里这是**一等信息**，不是杂项 —— 读者查到旧字体时要知道现代写法。
  kyujitai: '旧字体对应',
  // 🔴 `see_also` 是日语才有的一档：**同音索引页**（`いぬ → 犬 狗 戌 率寝 寝ぬ 去ぬ`）。
  //    它**不断言这些词是异体**，只说"都念这个音" —— 措辞必须跟着判据走，
  //    印成「异体写法」就是在页面上做一个数据层拒绝做的断言（`JA_PLAN` §二.5）。
  see_also: '同音词',
};
