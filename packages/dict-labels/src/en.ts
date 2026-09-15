// ============================================================================
// 英语标签映射 —— **映射表唯一的家**（`[[dict-labels-package]]`：`App.tsx` 里不许新增）。
// 2026-09-08 阶段 8 新建。取值全部**从库里量出来**（按出现量排），不是凭空想的。
//
// 🔴 **查不到就原样透出**，绝不回退成泛泛的词。
//    `[[it-display-layer-stage8]]`：`|| g.kind` 那种兜底把「缺失的中文名」
//    伪装成了英文内容 —— **兜底越体面，缺陷越难发现**。
//    ⇒ 本文件的 `enLabel()` 查不到时返回原值，调用方能一眼看出哪些没映射。
//
// ═══ 2026-09-15：覆盖口径改成**按建库脚本的桶集合**，不按「库里现在有什么」═══
// 之前三张表是照库里出现量前 N 名写的，于是 register/region/grammar 各留了
// 20/74/42 种裸英文（3.1 万条会直接印到读者眼前）。根子和 `sym`、`lowercase`
// 两次一样：**只补闸报出来的那一个，不去看它的兄弟项**。
// ⇒ 现在三张表逐条对着 `en/pipeline/build_sense_tags.py` 的 GRAMMAR / REGION /
//   REGISTER / USAGE 四个集合写全 —— 集合是**入库的上界**，照它写完，
//   将来重跑建库也不会再冒出没映射的值。
//
// ═══ 两套来源、一套中文 ═══
// 同一个概念在库里有两种写法，因为有两个源（`field_src` 量过，泾渭分明）：
//     kaikki(`en-edition`)  US 14,667 ｜ slang 27,189 ｜ Internet 4,644
//     ECDICT(`ecdict`)      美国 3,039 ｜ 俚 3,784   ｜ 网络 35,546
// 数据层照实各记各的（源头说什么就是什么），**统一在展示层做**：
// 两边都映到同一个中文，读者看到的是一个概念一个徽标。
// ⚠️ 这要求调用方**按映射后的文字去重**（见 `App.tsx` 的 chips）——
//    不然 `US` + `美国` 会印成「美 美」。
// ============================================================================

import { TOPIC_LABELS } from './common.js';
import { mostSpecificTopics } from './topic-tree.js';

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

/**
 * 语法标签（`sense_tag.kind='grammar'`）。
 * 逐条对着 `build_sense_tags.py` 的 `GRAMMAR` 集合写全（69 个值）。
 * 🔴 `particle` 留在这里，但库里只剩 **2 条**（`venitive`、`-ahh`）——
 *    另 225 条带 `topic=physics`（`blue`「夸克的蓝色荷」、`positron`），
 *    说的是**粒子**不是**小品词**，已在数据层改判到 `topic`
 *    （`scripts/fix_en_particle_bucket.py`）。不在展示层糊一层中文盖过去。
 */
export const EN_GRAMMAR_LABELS: Record<string, string> = {
  // ── 可数性 / 数 / 比较级 ──
  countable: '可数', uncountable: '不可数', 'usually-uncountable': '多作不可数',
  comparable: '有比较级', 'not-comparable': '无比较级', uncomparable: '无比较级',
  'comparative-only': '仅比较级',
  'plural-only': '仅复数', 'singular-only': '仅单数', 'no-plural': '无复数形式',
  'in-plural': '用于复数', 'plural-normally': '通常用复数',
  plural: '复数', singular: '单数', invariable: '单复同形',
  // ── 及物性与配价 ──
  transitive: '及物', intransitive: '不及物', ambitransitive: '及物/不及物两可',
  ditransitive: '双宾', ergative: '作格', reflexive: '反身',
  impersonal: '无人称', copulative: '系动词', stative: '静态',
  auxiliary: '助动词', modal: '情态',
  // ── 分布与句法位置 ──
  attributive: '定语用法', predicative: '表语用法', postpositional: '后置',
  'in-compounds': '用于复合词', relational: '关系形容词',
  'with-definite-article': '带定冠词',
  collective: '集合用法', imperative: '祈使',
  personal: '人称', 'third-person': '第三人称',
  'second-person': '第二人称', 'first-person': '第一人称',
  // ── 词类 ──
  particle: '小品词', pronoun: '代词', letter: '字母', morpheme: '词素',
  onomatopoeic: '拟声', diminutive: '指小', agent: '施事',
  // 🔴 三个缩略是**三回事**，不许合并成一个「缩写」：
  //    contraction  don't / can't —— 音节缩合，仍是一个词
  //    initialism   FBI —— 逐字母念
  //    acronym      NASA —— 当成一个词拼读
  contraction: '缩合', initialism: '首字母缩写', acronym: '首字母拼读词',
  // 2026-09-09 补：老词典层的 `abbr.` 判不准词性，照 v3 自己的做法当语法标签。
  //   没有这一条，`mri` 的页面会给中文读者原样印出英文 `abbreviation`。
  abbreviation: '缩写',
  // ── 格 / 语态 / 缺陷范式 ──
  interrogative: '疑问', nominative: '主格', objective: '宾格',
  conjunctive: '连接用法', passive: '被动', defective: '缺陷动词',
  'no-past-participle': '无过去分词', 'no-present-participle': '无现在分词',
  // ── 介词搭配（源头是 `with-<prep>` 一族，照族写全，别只补见过的那个）──
  'with-on': '接 on', 'with-of': '接 of', 'with-in': '接 in',
  'with-to': '接 to', 'with-for': '接 for',
  // ── 出现在真义项上的这三个不是指针标记（指针义项整条已在建库时跳过）──
  participle: '分词', past: '过去式', gerund: '动名词',
};

/**
 * 语域（`register`）—— 读者最需要的一档：告诉他这个词能不能用。
 * 上半段对着 `build_sense_tags.py` 的 `REGISTER` 集合（kaikki 侧），
 * 下半段是 ECDICT 的方括号短码（`build_legacy_sense.py` 的 `MARK_REGISTER`），
 * **两边映到同一个中文**。
 */
export const EN_REGISTER_LABELS: Record<string, string> = {
  // ── 时代层 ──
  obsolete: '废弃', archaic: '古体', dated: '旧式', historical: '历史',
  // 🔴 `Early` / `Modern` 是源头把「Early Modern English」拆成的**两个 tag**
  //    （`aback` 的 tags 是 `['Early','Modern','obsolete']`），不是两个独立语域。
  //    ⇒ 拆开的两个徽标连读仍是「早期 现代英语」，照源头的拆法印，不硬拼。
  //    ⚠️ 同族的 `Late`（源头有，`ablatitious` 是 Late Modern）**建库时没收**，
  //       落在 `tag_dropped.tsv` 里（10 条）。这里先给名字，
  //       下次重跑 `build_sense_tags.py` 时把 `Late`/`Middle` 补进 REGISTER。
  Early: '早期', Late: '晚期', Modern: '现代英语',
  // ── 常用度 ──
  rare: '罕用', uncommon: '少见', neologism: '新词', 'nonce-word': '临时造词',
  // ── 正式度 ──
  slang: '俚语', informal: '非正式', colloquial: '口语', formal: '正式',
  literary: '文学', poetic: '诗歌', jargon: '行话', technical: '专业',
  standard: '标准语', nonstandard: '非标准', proscribed: '不规范',
  dialectal: '方言',
  // ── 冒犯度 ──
  // `ethnic` 790 条**全部**同时带 `slur` —— 源头把「ethnic slur」拆成了两个 tag，
  // 连读即「族群 蔑称」。`mildly` 327 条里 219 条带 `vulgar`（mildly vulgar）。
  vulgar: '粗俗', derogatory: '贬义', offensive: '冒犯',
  slur: '蔑称', ethnic: '族群', mildly: '轻度',
  // ── 语气 / 人群 ──
  humorous: '诙谐', euphemistic: '委婉', sarcastic: '讥讽', ironic: '反讽',
  emphatic: '强调', excessive: '夸张', endearing: '昵爱', familiar: '亲昵',
  childish: '童语',
  // ── 社群变体 ──
  Internet: '网络', Leet: '黑客体', Polari: '波拉里黑话',
  // ── ECDICT 方括号短码 → 与上面同一套中文 ──
  俚: '俚语', 口语: '口语', 网络: '网络', 古: '古体', 废: '废弃',
  方: '方言', 谑: '诙谐', 贬: '贬义', 褒: '褒义', 讳: '委婉',
  书: '书面语', 俗: '俗语', 粗: '粗俗', 婉: '委婉',
};

/**
 * 用法（`usage`）—— 修饰这条义项**怎么用**，不是它是什么。
 * 对着 `build_sense_tags.py` 的 `USAGE` 集合（18 个值）写全。
 */
export const EN_USAGE_LABELS: Record<string, string> = {
  figuratively: '比喻', literally: '字面', idiomatic: '习语',
  usually: '通常', often: '常', sometimes: '有时', especially: '尤指',
  broadly: '广义', narrowly: '狭义', also: '亦作', chiefly: '主要',
  physical: '具体', 'by-extension': '引申', generally: '泛指',
  capitalized: '首字母大写',
  // 2026-09-15 补齐 usage 桶剩下的 6 种 —— 用户在 `h` 的页面上看见英文 `lowercase`。
  //   逐条回库看过实际内容再定词：
  //     lowercase/uppercase 全是字母条目（`f` 小写第六个字母 / `A` 大写第一个）
  //     metonymically 是转喻（`pound`→收容所的工作人员、`raven`→维京军事力量）
  //     specifically 是**特指**，与已有的 `especially`「尤指」不是一回事
  //     possibly 给义项加不确定（`man`→鼓起勇气），用「或指」不用「可能」——
  //       徽标位置上「可能」会被读成在修饰词义本身
  //     gender-neutral 写「不分性别」不写「中性」：后者会和语法性别的
  //       `GENDER_LABELS.n`（中）撞车，而这里说的是用法不是语法性
  lowercase: '小写', uppercase: '大写', metonymically: '转喻',
  specifically: '特指', possibly: '或指', 'gender-neutral': '不分性别',
};

/**
 * 地区标签（`sense_tag.kind='region'`）与读音地区**不是一套取值**，分开映射。
 * 对着 `build_sense_tags.py` 的 `REGION` 集合 + ECDICT 的 `MARK_REGION` 写全。
 * 🔴 同一地区的多种写法（`US`/`American`/`美国`/`美`）**全部收敛到一个中文**，
 *    读者看到的是一个徽标；靠调用方按映射后的文字去重。
 */
export const EN_SENSE_REGION_LABELS: Record<string, string> = {
  // ── 国家 / 大区 ──
  US: '美', American: '美', UK: '英', British: '英', Britain: '英',
  Australia: '澳', Australian: '澳', Canada: '加', Canadian: '加',
  Ireland: '爱尔兰', Irish: '爱尔兰', India: '印度', 'New-Zealand': '新西兰',
  'South-Africa': '南非', Singapore: '新加坡', Philippines: '菲律宾',
  Philippine: '菲律宾', Malaysia: '马来西亚', 'Hong-Kong': '香港',
  Jamaica: '牙买加', Nigeria: '尼日利亚', Pakistan: '巴基斯坦',
  Bangladesh: '孟加拉国', Indonesia: '印度尼西亚', Myanmar: '缅甸',
  Kenya: '肯尼亚', Zimbabwe: '津巴布韦', Guyana: '圭亚那', Botswana: '博茨瓦纳',
  'Trinidad-and-Tobago': '特立尼达和多巴哥', China: '中国', Japan: '日本',
  Russia: '俄罗斯', Europe: '欧洲', Africa: '非洲', Caribbean: '加勒比',
  'South-Asia': '南亚', Commonwealth: '英联邦',
  // ── 不列颠诸岛 ──
  England: '英格兰', Scotland: '苏格兰', Scottish: '苏格兰',
  Wales: '威尔士', Welsh: '威尔士',
  'Northern-Ireland': '北爱尔兰', Ulster: '阿尔斯特',
  'Northern-England': '英格兰北部', 'Southern-England': '英格兰南部',
  Midlands: '英格兰中部', 'West-Midlands': '西米德兰兹',
  'East-Anglia': '东盎格利亚', 'West-Country': '英格兰西南部',
  Yorkshire: '约克郡', Cornwall: '康沃尔', Devon: '德文郡',
  Cumbria: '坎布里亚', Northumbria: '诺森布里亚',
  Shetland: '设得兰', Orkney: '奥克尼', London: '伦敦',
  // ── 北美地方 ──
  'Southern-US': '美国南部', 'Northern-US': '美国北部',
  'Midwestern-US': '美国中西部', 'New-England': '新英格兰',
  Appalachia: '阿巴拉契亚', California: '加利福尼亚', Texas: '得克萨斯',
  Louisiana: '路易斯安那', Pennsylvania: '宾夕法尼亚', Maine: '缅因州',
  'New-York': '纽约州', 'New-York-City': '纽约市',
  Hawaii: '夏威夷', Quebec: '魁北克', Newfoundland: '纽芬兰',
  // ── 方言/口音的专名 ──
  Geordie: '泰恩赛德方言', Cockney: '伦敦东区腔',
  'Multicultural-London-English': '伦敦多元文化英语',
  Singlish: '新加坡式英语', Manglish: '马来西亚式英语',
  // ── 泛指方位（源头就这么泛，照实印）──
  North: '北部', South: '南部', East: '东部', West: '西部',
  Northeastern: '东北部', Southwestern: '西南部',
  Southern: '南部', Western: '西部',
  regional: '地方', dialectal: '方言',
  // ── ECDICT 方括号标记 → 与上面同一套中文 ──
  美国: '美', 美: '美', 英国: '英', 英: '英', 英格兰: '英格兰',
  加拿大: '加', 澳: '澳', 澳大利亚: '澳', 苏格兰: '苏格兰', 威尔士: '威尔士',
  爱尔兰: '爱尔兰', 新西兰: '新西兰', 印度: '印度', 南非: '南非',
  // 🔴「主英国英语」不能并进「英」：源头明说的是 chiefly，丢了就是改了源头的话。
  主美国英语: '主美', 主英国英语: '主英',
};

/**
 * `topic` 桶里**不是学科**的那些 —— 不出版。
 *
 * 🔴 `heading` 301 条：kaikki 拿它标「这条 gloss 是个**总述义项**（下面还有子义项）」，
 *    `fall`「To be moved downwards」、`and`「Expressing a condition」都带着它。
 *    那是结构元信息，不是领域。印成学科徽标，读者会以为词义与之有关。
 * ⚠️ 与 fr 的 `FR_TAG_SKIP` 同一条纪律：**结构标记明确不出版**。
 *    数据层照实留着（源头确实这么说的，`[[dont-say-source-lacks-what-we-skipped]]`），
 *    只是不往页面上放。
 */
export const EN_TOPIC_SKIP: ReadonlySet<string> = new Set(['heading']);

const BY_KIND: Record<string, Record<string, string>> = {
  grammar: EN_GRAMMAR_LABELS,
  register: EN_REGISTER_LABELS,
  usage: EN_USAGE_LABELS,
  region: EN_SENSE_REGION_LABELS,
};

/**
 * 义项标签取中文。
 * 🔴 **查不到原样返回**，不回退成 kind 也不返回空 —— 见文件头。
 * ⚠️ `topic` 走共享的 `TOPIC_LABELS`（值域是六门共用的 kaikki slug，
 *    没必要在 en 再立一张）；折层级与过滤结构标记由 `enSenseTopics()` 负责。
 */
export function enLabel(kind: string, value: string): string {
  if (kind === 'topic') return TOPIC_LABELS[value] ?? value;
  return BY_KIND[kind]?.[value] ?? value;
}

/**
 * 一条义项的 topic → 该印出来的中文（按顺序，已去重）。
 *
 * 三步，缺一不可：
 *   ① 丢掉结构标记（`EN_TOPIC_SKIP`）；
 *   ② **只留最具体的**（`mostSpecificTopics`）—— kaikki 的 topic 是一条链，
 *      `google` 的板球义项挂着 ball-games/cricket/games/hobbies/lifestyle/sports 六个，
 *      原样印读者要从六个里自己挑一个。折完之后 76% 的义项只剩 1 个、21% 剩 2 个；
 *   ③ 查不到中文的**不印**。
 *      🔴 这一条与本文件开头「查不到就原样透出」是**两回事**：
 *         语域/地区/语法是封闭集合，漏一个就是我的活儿没干完，必须让它露出来刺眼；
 *         而 topic 是**开放集**（源头随时会加新领域），印一个 `phytopathology`
 *         给中文读者，比不印更坏。⇒ 缺的靠 `npm run gate:tags` 盯，不靠读者发现。
 */
export function enSenseTopics(values: string[]): string[] {
  const kept = mostSpecificTopics(values.filter((v) => !EN_TOPIC_SKIP.has(v)));
  const out: string[] = [];
  for (const v of kept) {
    const zh = TOPIC_LABELS[v];
    if (zh && !out.includes(zh)) out.push(zh);
  }
  return out;
}

/** 考纲标签串（`dict.exam_tag` 是空格分隔的多个）→ 中文数组 */
export function enExamLabels(tag: string | null): string[] {
  if (!tag) return [];
  return tag.split(/\s+/).filter(Boolean).map((t) => EN_EXAM_LABELS[t] ?? t);
}
