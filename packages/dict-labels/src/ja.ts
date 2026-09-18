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

/** 汉字的音訓読み（`kanji_reading`，阶段 4c）。
 *
 * 🔴 **`kind` 三分、`subkind` 是细分，两者不能压平成一层。**
 *    压平会把「音読み·呉音」和「訓読み·古訓」摆成并列的七八个筐，
 *    而读者第一眼要的是**音读还是训读**这个二分 —— 细分是第二眼的事。
 * 🔴 **`nanori`(名乗り) 单独一档，不归訓読み**：它是**人名专用**读音，
 *    拿它去读普通词是错的；并进訓読み等于在页面上说它可以。
 * ⚠️ `is_joyo` 是**正交**标记（该读音在常用汉字表内），不是第九个类别 ——
 *    印成小徽标，不进这张表。
 */
export const JA_KANJI_READING_KIND: Record<string, string> = {
  on: '音读', kun: '训读', nanori: '名乗',
};
export const JA_KANJI_READING_SUBKIND: Record<string, string> = {
  'go-on': '吴音', 'kan-on': '汉音', 'to-on': '唐音', 'kan-yo-on': '惯用音',
  'ko-kun': '古训',
};
/** 分区顺序：音读在前、训读在后、名乗最后 —— 与日语辞书惯例和源头顺序一致。 */
export const JA_KANJI_READING_ORDER = ['on', 'kun', 'nanori'];

/** 语域覆盖层（`sense_tag.kind='register'`）。**只放与全局表不同义的**，其余走
 * `REGISTER_LABELS`。
 *
 * 🔴🔴 **日语敬语是三分体系，全局表那三个译名对日语一个都不准。**
 *    全局表：`honorific`「敬称」（那是称呼语）、`polite`「礼貌」（泛泛的语气）
 *    日语里它们是**语法范畴**，与 `humble` 构成闭合的三分：
 *      尊敬語 `honorific` —— 抬高对方（いらっしゃる）
 *      謙譲語 `humble`    —— 压低自己（伺う）
 *      丁寧語 `polite`    —— 对听话人客气（です・ます）
 *    印成「敬称／礼貌」会把一个语法体系讲成语气强弱，学习者据此是学不对的。
 * 🔴 `Classical` 全局表是「古典」（古希腊罗马、古典拉丁语），日语的
 *    `Classical`＋`Japanese` 是**文語**（见 `build_sense_tags.py` 判据③）。
 */
export const JA_REGISTER_LABELS: Record<string, string> = {
  honorific: '尊敬语', humble: '谦让语', polite: '丁宁语',
  Classical: '文语', modern: '现代语',
};

/** 地区（`sense_tag.kind='region'`）。日语的方言区，另六门没有。
 *
 * ⚠️ **长音符两种写法都要有**：源头 `Kanto`/`Kantō` 混用，建库侧两种都收
 *    （`build_sense_tags.REGION`），映射表跟着收，否则收进来了却印不出中文。
 */
export const JA_REGION_LABELS: Record<string, string> = {
  dialectal: '方言',
  Kansai: '关西', Kagoshima: '鹿儿岛',
  Kyūshū: '九州', Kyushu: '九州',
  Shikoku: '四国',
  Chūgoku: '中国地方', Chugoku: '中国地方',   // ⚠️ 日本的中国地方，不是中国
  Kantō: '关东', Kanto: '关东',
  Tōhoku: '东北', Tohoku: '东北',
  Hokkaidō: '北海道', Hokkaido: '北海道',
  Tōkyō: '东京', Tokyo: '东京',
  Kyōto: '京都', Kyoto: '京都',
  Ōsaka: '大阪', Osaka: '大阪',
  Ryūkyū: '琉球', Ryukyu: '琉球',
  Okinawa: '冲绳', Nagoya: '名古屋',
};

/** 语法（`sense_tag.kind='grammar'`）。**封闭集合** —— 值域由
 * `ja/pipeline/build_sense_tags.GRAMMAR` 定死，漏一个页面上就露英文码。
 *
 * ⚠️ 不能用 `IT_GRAMMAR_LABELS`：那是意语的（`congiuntivo` 那套）。
 * 🔴 `suru` 是日语独有的一等信息：`勉強` 标了它才说明能说「勉強する」。
 * 🔴 `morpheme` 是这一桶最大的一项（1,187 条）—— 指**不单独成词的构词成分**
 *    （`塔`「塔」只在复合词里用），译「构词成分」不译「语素」：
 *    后者是语言学术语，读者要的是"这个字不能单说"。
 */
export const JA_GRAMMAR_LABELS: Record<string, string> = {
  morpheme: '构词成分', suru: 'する动词', 'in-compounds': '用于复合词',
  intransitive: '自动词', transitive: '他动词',
  attributive: '连体形', predicative: '述语', conjunctive: '连用形',
  adverbial: '作状语', 'sentence-final': '句末',
  auxiliary: '助动词', particle: '助词',
  pronoun: '代词', demonstrative: '指示词', numeral: '数词',
  noun: '名词', verb: '动词', adjective: '形容词',
  prefix: '前缀', suffix: '后缀', name: '专名', abbreviation: '缩略',
  'term-of-address': '称呼语',
  deictically: '指示用法', anaphorically: '回指用法',
  reflexive: '反身', collective: '集合', impersonal: '无人称',
  countable: '可数', uncountable: '不可数',
  present: '现在', past: '过去', perfect: '完成', imperfect: '未完成',
  negative: '否定', interrogative: '疑问', imperative: '命令', genitive: '属格',
  participle: '分词',
  'first-person': '第一人称', 'second-person': '第二人称', 'third-person': '第三人称',
};

/** 用法/修辞（`sense_tag.kind='usage'`）。**ja 是第一门用这个桶的。**
 *
 * 🔴 这一桶不是"剩下的都扔这儿"：它装的是**这条义项怎么被使用**，
 *    既不是语域（谁在什么场合说）也不是语法（怎么接）。
 * ⭐ `onomatopoeic`＋`ideophonic` 633 条 —— 拟声拟态词是日语的显著特征，
 *    单独立桶才印得出来；混进 register 会被「口语」「俚语」淹掉。
 */
export const JA_USAGE_LABELS: Record<string, string> = {
  idiomatic: '惯用', figuratively: '比喻', literally: '字面',
  broadly: '广义', narrowly: '狭义',
  onomatopoeic: '拟声词', ideophonic: '拟态词',
  metonymically: '转喻', emphatic: '强调',
};

/** 关系类型里日语特有的那两个。其余走 `RELATION_LABELS`。 */
/**
 * 关系分区：**构词** 还是 **语义**。2026-09-17。
 *
 * 🔴 分家的理由是 de 那轮外审两家一致的结论（`DE_PLAN` 收尾单 C13）：
 *    `Häuslein ← Haus 指小词` 和 `Häuser ← Haus 复数` 并排会被当成同一类东西。
 *    日语上这件事更严重，因为**量级差一个数量级**：`桜` 有 160 个派生词、
 *    8 个近义词、1 个上位词 —— 混在一区里，那 9 条语义关系直接被 160 条构词淹没，
 *    而语义关系恰恰是查词的人要的那一类。
 *
 * ⚠️ `related`（相关词）归**语义**：源头拿它当"意思上沾边"的筐，
 *    里面是 `猫に小判`／`猫の額` 这种惯用语，不是构词产物。
 * ⚠️ `proverb` 归**语义**：清洗之后它只剩 en 版那 384 条真谚语
 *    （ja 版的 32,932 条"熟語"已归位到 `derived`，见
 *     `ja/fixes/fix_relation_kind_and_targets.py`）。
 *
 * 指针类（`alt_of`／`see_also`／`kyujitai`／`abbreviation`）**两区都不进** ——
 * 它们在页面顶上有自己的位置（"异体写法"／"同音词"），那是读者进错写法时要的第一眼。
 */
export const JA_RELATION_SECTION: Record<string, 'word-formation' | 'semantic'> = {
  derived: 'word-formation',
  synonym: 'semantic', antonym: 'semantic',
  hypernym: 'semantic', hyponym: 'semantic', coordinate: 'semantic',
  holonym: 'semantic', meronym: 'semantic',
  related: 'semantic', proverb: 'semantic',
};

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
