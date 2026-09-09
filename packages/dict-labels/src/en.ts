// ============================================================================
// 英语标签映射 —— **映射表唯一的家**（`[[dict-labels-package]]`：`App.tsx` 里不许新增）。
// 2026-09-08 阶段 8 新建。取值全部**从库里量出来**（按出现量排），不是凭空想的。
//
// 🔴 **查不到就原样透出**，绝不回退成泛泛的词。
//    `[[it-display-layer-stage8]]`：`|| g.kind` 那种兜底把「缺失的中文名」
//    伪装成了英文内容 —— **兜底越体面，缺陷越难发现**。
//    ⇒ 本文件的 `enLabel()` 查不到时返回原值，调用方能一眼看出哪些没映射。
// ============================================================================

/** 考纲标签 —— **五门里只有 en 有**（ECDICT 资产，`EN_PLAN` §2.3）。按覆盖量排 */
export const EN_EXAM_LABELS: Record<string, string> = {
  zk: '中考', gk: '高考', cet4: '四级', cet6: '六级',
  ky: '考研', toefl: '托福', ielts: '雅思', gre: 'GRE',
};

/** 读音/录音地区。`pronunciation.region` 是 `uk`/`us`，`audio.region` 是 `en-GB`/`en-US` */
export const EN_REGION_LABELS: Record<string, string> = {
  uk: '英', us: '美', au: '澳', ca: '加', nz: '新西兰',
  ie: '爱尔兰', in: '印度', za: '南非', 'gb-sct': '苏格兰', 'gb-wls': '威尔士',
  'en-GB': '英', 'en-US': '美', 'en-AU': '澳', 'en-CA': '加', 'en-NZ': '新西兰',
  'en-IE': '爱尔兰', 'en-IN': '印度', 'en-ZA': '南非',
};

/** 语义关系。`derived`/`related`/`abbreviation` 在库里是 hidden=1，此处仍给名字备用 */
export const EN_RELATION_LABELS: Record<string, string> = {
  synonym: '近义词', antonym: '反义词',
  hypernym: '上位词', hyponym: '下位词',
  holonym: '整体词', meronym: '部分词',
  coordinate: '同位词', troponym: '方式词',
  alt_of: '异体', derived: '派生与词组', related: '相关词', abbreviation: '缩写',
};

/** 语法标签（`sense_tag.kind='grammar'`）。取值按库内出现量排 */
export const EN_GRAMMAR_LABELS: Record<string, string> = {
  countable: '可数', uncountable: '不可数', 'plural-only': '仅复数', plural: '复数',
  transitive: '及物', intransitive: '不及物', ambitransitive: '及物/不及物两可',
  'not-comparable': '无比较级', comparable: '有比较级',
  morpheme: '词素', 'in-compounds': '用于复合词', letter: '字母',
  attributive: '定语用法', predicative: '表语用法', reflexive: '反身',
  auxiliary: '助动词', modal: '情态', copulative: '系动词',
  // 🔴 2026-09-09 补：老词典层的 `abbr.` 判不准词性，照 v3 自己的做法当语法标签。
  //    没有这一条，`mri` 的页面会给中文读者原样印出英文 `abbreviation` ——
  //    正是 `[[it-display-layer-stage8]]` 那条「兜底越体面缺陷越难发现」。
  abbreviation: '缩写',
};

/** 语域（`register`）—— 读者最需要的一档：告诉他这个词能不能用 */
export const EN_REGISTER_LABELS: Record<string, string> = {
  obsolete: '废弃', archaic: '古体', dated: '旧式', historical: '历史',
  slang: '俚语', informal: '非正式', colloquial: '口语', formal: '正式',
  vulgar: '粗俗', derogatory: '贬义', offensive: '冒犯', humorous: '诙谐',
  euphemistic: '委婉', poetic: '诗歌', literary: '文学', rare: '罕用',
  dialectal: '方言', nonstandard: '非标准', proscribed: '不规范',
};

/** 用法（`usage`）—— 修饰这条义项**怎么用**，不是它是什么 */
export const EN_USAGE_LABELS: Record<string, string> = {
  figuratively: '比喻', literally: '字面', idiomatic: '习语',
  usually: '通常', often: '常', sometimes: '有时', especially: '尤指',
  broadly: '广义', narrowly: '狭义', also: '亦作', chiefly: '主要',
  physical: '具体', capitalized: '首字母大写',
};

/** 地区标签（`sense_tag.kind='region'`）与读音地区**不是一套取值**，分开映射 */
export const EN_SENSE_REGION_LABELS: Record<string, string> = {
  US: '美', UK: '英', Australia: '澳', Canada: '加', Scotland: '苏格兰',
  Ireland: '爱尔兰', India: '印度', 'New-Zealand': '新西兰', Philippines: '菲律宾',
  'South-Africa': '南非', dialectal: '方言', Britain: '英',
};

const BY_KIND: Record<string, Record<string, string>> = {
  grammar: EN_GRAMMAR_LABELS,
  register: EN_REGISTER_LABELS,
  usage: EN_USAGE_LABELS,
  region: EN_SENSE_REGION_LABELS,
};

/**
 * 义项标签取中文。
 * 🔴 **查不到原样返回**，不回退成 kind 也不返回空 —— 见文件头。
 * ⚠️ `topic`（77 万条、学科主题）**有意不映射**：它有上千种取值（`natural-sciences`
 *    `physical-sciences` `lifestyle` …），逐个翻是另一件事；在读者面前
 *    展示层默认不显示这一桶，需要时再补，不在这里造半张表。
 */
export function enLabel(kind: string, value: string): string {
  return BY_KIND[kind]?.[value] ?? value;
}

/** 考纲标签串（`dict.exam_tag` 是空格分隔的多个）→ 中文数组 */
export function enExamLabels(tag: string | null): string[] {
  if (!tag) return [];
  return tag.split(/\s+/).filter(Boolean).map((t) => EN_EXAM_LABELS[t] ?? t);
}
