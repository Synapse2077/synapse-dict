// 跨语种共用的展示映射：性别、词性、语域、数、学科领域、关系、变形、及物性。
// 纯数据，零依赖 —— 浏览器（划词弹窗）与 Node 都能直接 import。

export const EXCHANGE_LABELS: Record<string, string> = {
  p: '过去式', d: '过去分词', i: '现在分词', '3': '第三人称单数',
  r: '比较级', t: '最高级', s: '复数', '0': '原形',
};

// `mf` 写作「阴阳」而非「阴/阳」：斜杠容易被读成"二选一"，而 mf 的语义是"两者都是"。
// 词头徽标处它还要同时承担两种现象 —— 义项间分属（`radio`：la radio 收音机 / el radio 半径）
// 与义项内两性通用（`fiscal`：el/la fiscal，跟着人的性别走）—— 用词得中性一些。
export const GENDER_LABELS: Record<string, string> = { f: '阴', m: '阳', mf: '阴阳', n: '中' };

// 逐义项词性 → 中文标签（对应 build.py POS_MAP 的短码）。
export const POS_LABELS: Record<string, string> = {
  n: '名词', name: '专名', adj: '形容词', adv: '副词', v: '动词', pron: '代词',
  prep: '介词', conj: '连词', det: '限定词', num: '数词', intj: '感叹词',
  pref: '前缀', suf: '后缀', phr: '短语', contr: '缩合', art: '冠词', prov: '谚语',
  // 2026-08-15 补：对应 build.py POS_MAP 新增的四个 kaikki 取值
  abbr: '缩写', affix: '词缀', onom: '拟声词',
  // 2026-08-16 补 sym：`POS_MAP` 里 symbol→sym 一直都在，这张表却没有对应项，
  //   于是 `bo` / `ar` / `AQ` 的分组标题直接显示英文 `sym`。**展示层契约闸第一次跑就逮到的。**
  sym: '符号',
  // 2026-08-17 补齐剩下四个：`POS_MAP` 有、这张表没有的取值一次找全（照 sym 那次的教训，
  //   别只补闸报出来的那一个）。逐条回库看过实际内容再定词：
  //   char 全是字母表条目（`f` 意大利语字母表第六个字母）⇒「字母」不是泛指的「字符」
  //   punct 是引号族（`« »` 标示引语）／part 是 `sì` `no` `a'`／interfix 只有 `-isc-`
  char: '字母', punct: '标点', part: '小品词', interfix: '连接成分',
  // 2026-08-26 补 **法语的两个取值**（法语展示层契约闸全量跑逮到 15 处）。
  //   照 `sym` 那次的教训**一次找全**：把 fr 的 `sense.pos` 全部 27 种与本表对了一遍，
  //   缺的就这两个（`adj/n` 由 `posLabel` 按 `/` 拆开后自然命中，不算缺）。
  //   逐条回库看过实际内容再定词：
  //     var 是**排印变体**（1,383 条）—— `coeur` / `oeil` / `noeud` 这些无连字拼写，
  //         法文版释义写的是 `Variante typographique de cœur.`。
  //         🔴 译成「变体」太泛：它专指**因排印限制而写成的形式**，不是一般的异体。
  //     postp 是后置词（4 条，`durant` 一类跟在名词后的用法）
  var: '排印变体', postp: '后置词',
  // 2026-08-20 补 **西语的原始取值**（西语展示层契约闸第一次跑就逮到 97 处）：
  //   🔴 上面那批（`sym`/`char`/`abbr`）是**意语**的短码 —— `it/build.py` 的 `POS_MAP`
  //      把 kaikki 的 `symbol`/`character`/`abbreviation` 映射成了短码；
  //      而 **es 的 `POS_MAP` 没有这几项**，原始串直接透传进 `sense.pos`。
  //      ⇒ 同一张表要同时认两套取值。这不是重复，是两个语种的真实数据。
  //   逐条回库看过实际内容再定词（照 `sym` 那次的教训，一次找全，别只补闸报出来的那个）：
  //     abbrev 是词典学缩写（`Mús.` 音乐 / `UM` 货币符号 / `CORDE` 语料库名）
  //     character 全是字母表条目（`A` 西班牙语字母表第一个字母）⇒「字母」不是「字符」
  //     prep_phrase 是介词短语（`sin duda` 毫无疑问 / `de cabeza` 不假思索）
  //     symbol 是计量与排版符号（`GB` 吉字节 / `@` 阿罗巴）
  //     particle 是 `sí` 那族肯定词 ／ infix 只有 `-x-` `-it-`
  //     syllable 只有 `pa`（仅用于 `de pe a pa`）／unknown 只有 `erre` 一条，源头没给词性
  abbrev: '缩写', character: '字母', prep_phrase: '介词短语', symbol: '符号',
  particle: '小品词', infix: '中缀', syllable: '音节', unknown: '未标注',
  // 🔴 2026-08-29 pt 阶段 3b 预检加：葡语版有 1 条 `root`（`abelh-` = abelha 的词根）。
  //    映射成 `pref`（前缀）是错的 —— 词根不是前缀。按「一个都不用默认值填平」
  //    （`[[prompt-self-harm-two-patterns]]`：`pos or "v"` 把分类名说成动词，落库 404 行）
  //    显式给它一行。⚠️ `abbrev` 上面已经有了，pt 那 1,344 条不用新增。
  root: '词根',
  // 🔴 2026-09-01 de 阶段 3 预检加：德语版有 3 条 `circumfix`（`Ge-…-e`、`be-…-t`）。
  //    环缀是德语构词的真实类型（`Ge-` + 词干 + `-e` 一次成词），
  //    拆成 prefix + suffix 会丢掉「必须同时出现」这一条。同 `root` 的处理：显式给一行。
  circumfix: '环缀',
  // 🔴🔴 2026-09-10 补 **de `pronunciation.pos` 的长写法**（用户看 `schön` 页看出来的：
  //    读音区印着「/ʃøːn/ **verb**」）。根子是 **de 一个库里两套词性取值**：
  //      `sense.pos`         n / v / phr / pref / suf      ← 短码，上面早就有
  //      `pronunciation.pos` noun / verb / phrase / prefix / suffix  ← 长写法
  //    实测 de 的 `pronunciation.pos` 15 种取值里，这 5 种查不到 ⇒ 原样印英文，
  //    而它们覆盖 **699,802 / 1,034,438 = 67.7%** 的读音行（`noun` 一种就 39 万）。
  //    ⚠️ 我先想去生成侧把两套统一 —— **不改**：那要重跑阶段 4 且 de 已封版，
  //       而这里加五行是纯展示层的、可逆的。两套取值是**数据的真实形状**，
  //       同 `sym`/`abbrev` 那两次：「同一张表要同时认两套取值，这不是重复」。
  //    🔴 照 `sym` 那次的教训**一次找全**：de 的 15 种取值全部与本表对过，缺的就这 5 种。
  noun: '名词', verb: '动词', phrase: '短语', prefix: '前缀', suffix: '后缀',
};

// 语域标签 → 中文（对应 build.py REGISTERS）。
export const REGISTER_LABELS: Record<string, string> = {
  colloquial: '口语', vulgar: '粗俗', slang: '俚语', derogatory: '贬义',
  offensive: '冒犯', humorous: '诙谐', literary: '文学', dated: '旧式',
  euphemistic: '委婉', informal: '非正式', formal: '正式', pejorative: '贬义',
  childish: '童语', poetic: '诗歌', familiar: '亲昵', proscribed: '非规范',
  nonstandard: '非标准', obsolete: '废弃', historical: '历史', archaic: '古语',
  rare: '罕见', uncommon: '少见', neologism: '新词', Internet: '网络',
  misspelling: '误拼', 'pronunciation-spelling': '音写', dialectal: '方言',
  regional: '地区性', jargon: '行话', slur: '蔑称', ironic: '反讽',
  sarcastic: '讽刺', endearing: '亲昵', emphatic: '强调', rhetoric: '修辞',
  bureaucratese: '官腔', Leet: 'Leet黑话', figuratively: '比喻',
  // 🔴 2026-08-26（fr 阶段 8）补：fr 的 register 全量 40 种里**这 7 种查不到中文**，
  //    会把生标签（`World-War-I`）直接印在义项旁边。
  //    是渲染后契约闸逮到的 —— 数据层闸看不见「标签映射不全」这类缺陷。
  //    ⚠️ 这是共享表，补条目只会让别的语种也不再漏生标签，不改变已有行为。
  // 🔴 2026-09-18（ja 阶段 1d）补：`ethnic` en 那门 790 条也在用、`Anglicism`
  //    与已有的 `Leet`/`verlan` 同族（借用来源），都是**跨语种通用**的概念 ⇒ 进共享表。
  //    ⚠️ 同一轮里 ja 的 `Classical`/`honorific`/`humble`/`polite` **没有**进这张表：
  //       它们在日语上指的是敬语三分体系与文語，与这里的通用义不是一回事 ⇒
  //       走 `ja.ts` 的 `JA_REGISTER_LABELS` 覆盖层（`part`「小品词 vs 助词」同款）。
  ethnic: '族群', Anglicism: '英语借词',
  Ancient: '古代', Middle: '中古', 'Middle-Ages': '中世纪', 'World-War-I': '一战',
  excessive: '过度', mildly: '轻度', vernacular: '本土说法',
  // 🔴 2026-08-27（fr 族 C 第二段）：法文版 `tags` 分桶后映射到的规范键。
  //    法语维基词典的语域体系比英语版细 —— 「极罕见 / 很罕见 / 较罕见 / 少用」
  //    是四个不同的标注，合并成一个「罕见」就把源头的信息抹平了。
  anglicism: '英语借词', 'false-anglicism': '假英语词',
  'extremely-rare': '极罕见', 'very-rare': '很罕见', rarer: '较罕见',
  'seldom-used': '少用', 'more-common': '较常用', 'less-common': '较少用', common: '常用',
  proverbial: '谚语', hapax: '孤例', meliorative: '褒义', 'very-familiar': '很随便',
  broadly: '广义', especially: '尤指', specifically: '特指', literally: '字面义',
  metonymically: '转喻', 'by-analogy': '类比', hyperbole: '夸张', idiomatic: '习语',
  collectively: '集合用法', generically: '泛指', physical: '具体义',
  'spelling-1990': '1990新正字法', 'spelling-pre1835': '1835前旧拼写',
  // 2026-08-27 第二轮（fr 族 C）
  derisive: '嘲讽', 'criticized-usage': '受非议用法', blasphemous: '亵渎',
  insult: '侮辱', nickname: '绰号', 'sometimes-pejorative': '有时贬义',
  sometimes: '有时', nowadays: '今义', honorific: '敬称', verlan: '倒音俚语',
  latinism: '拉丁借词', germanism: '德语借词', hispanism: '西语借词',
  italianism: '意语借词', litotes: '曲言', 'traditional-spelling': '传统拼写',
  acronym: '首字母缩略', rural: '乡村用语',
  // 🔴 2026-09-15：六门标签覆盖率一次量全（`scripts/contract/tag_coverage_all.ts`），
  //    这张共享表还漏着 de 21 种 / pt 5 种 / it 2 种 / es 1 种。补的逻辑同上一轮：
  //    **对着各语种建库脚本的 REGISTERS 集合写**，不是只补量到的那几个。
  // ⚠️ de 的 `build.py` 把「语用/年代/文化传统」全归进 REGISTERS（它没有 usage 桶），
  //    所以 `often`/`Roman`/`Medieval` 这类会以语域标签的身份出现 —— 照它的桶给名字，
  //    不在展示层替 de 重新分桶（`[[multilang-decoupling-essence]]`：按语种解耦）。
  often: '常', now: '今', originally: '原义', chiefly: '主要',
  standard: '标准语', colloquially: '口语', technical: '专业',
  modern: '现代', Medieval: '中世纪', Roman: '古罗马',
  'Ancient-Rome': '古罗马', 'Greco-Roman': '希腊罗马',
  Early: '早期', Late: '晚期',
  'nonce-word': '临时造词', retronym: '回溯新词', 'strict-sense': '严格义',
  'non-scientific': '非学术义', metaphoric: '比喻', exaggerated: '夸张',
  polite: '礼貌', impolite: '不礼貌', 'term-of-address': '称呼语',
  taboo: '禁忌语', hypercorrect: '矫枉过正', academic: '学术',
  affective: '情感用语', solemn: '庄重', affected: '做作', elevated: '高雅',
  'eye-dialect': '方言拼写', 'World-War-II': '二战',
  // ⚠️ 这三个是 de 的 dump 里各 **1 条**的标签，看样本仍判不准它在修饰什么
  //    （`Hartlot`「硬钎料」的 `hard`、`anthropisch` 的 `natural`、
  //     `Sonderangebot`「特价」的 `special`）——像是源头把多词标注拆碎的残片。
  //    给一个不加戏的直译先把裸英文挡住，**并记在这儿等回源**：
  //    `[[dont-say-source-lacks-what-we-skipped]]`，判不准就说判不准，别装成已知。
  hard: '硬', natural: '自然', special: '特别',
};

// 关系条目上的标签 → 中文。2026-08-21。
// 🔴 外审逮到的：es 的「派生」区把原始英文标签直接印了出来
//    （`casilla diminutive`、`casucha pejorative`、`a casa adverb`、`近义 diñar slang`）——
//    `RelationRow` 里写的是 `r.tags.join('·')`，**没查任何映射表**。
// ⚠️ 值域与 REGISTER_LABELS 有重叠但不相同：这里还会出现构词标签（指小/指大）、
//    性数标签、以及**关系类型自身**（`synonym`/`synonym-of`）——后者作为标签是冗余的
//    （它就挂在「近义」那一组下面），映射成空串表示不显示。
export const REL_TAG_LABELS: Record<string, string> = {
  ...REGISTER_LABELS,
  diminutive: '指小', augmentative: '指大', pejorative: '贬义',
  masculine: '阳性', feminine: '阴性', 'masculine-feminine': '阴阳',
  singular: '单数', plural: '复数', alternative: '异体', obsolete: '废弃',
  verb: '动词', noun: '名词', adjective: '形容词', adverb: '副词',
  // 关系类型自身作为标签是冗余的 ⇒ 空串＝不渲染
  synonym: '', 'synonym-of': '', antonym: '', also: '', related: '',
};

/** 关系标签渲染成中文；查不到就原样显示（别把没见过的标签吞掉）。 */
export function relTagLabel(tag: string): string {
  const v = REL_TAG_LABELS[tag];
  return v === undefined ? tag : v;
}

// 数属性 → 中文（对应 build.py NUMBER）。
export const NUMBER_LABELS: Record<string, string> = {
  uncountable: '不可数', 'plural-only': '仅复数', invariable: '单复同形', collective: '集合',
  // 2026-09-15 对着 de `build.py` 的 `NUMBER_NOTE` 集合补全（es 的 `in-plural` 304 条
  //   本来会把英文原样印出来）。同一集合五门共用，补完谁都不再漏。
  countable: '可数', 'singular-only': '仅单数', 'in-plural': '用于复数',
  'plural-normally': '通常用复数', 'no-plural': '无复数形式',
  'singulare-tantum': '仅单数', 'plurale-tantum': '仅复数',
  'usually-uncountable': '多作不可数',
};

// 学科领域 → 中文。库里 402 种取值 / 20,647 条标签 / 18,763 条义项，这里**全部覆盖**。
//
// 🔴 2026-08-12：地区、语域、数三张表早就有，唯独 topic 漏了 —— 英文原值
//    （`anatomy`/`medicine`）就这么印在中文词典里，用户看 `radio` 时直接问「这是什么」。
//    只翻一部分会让同一行胶囊中英混排（「解剖学 · nautical」），比全英文更难看，
//    所以一次翻完，长尾也不留。
//
// ⚠️ kaikki 的取值有同义变体，一律映到同一个中文：连字符与空格两版
//    （`martial-arts`/`martial arts`、`organic-chemistry`/`organic chemistry`）、
//    英美拼写（`archaeology`/`archeology`、`color`/`colour`、`gemmology`/`gemology`）、
//    单复数（`meat`/`meats`、`social-science`/`social-sciences`）、
//    大小写（`Freemasonry`/`freemasonry`）。
export const TOPIC_LABELS: Record<string, string> = {
  // 🔴 2026-09-18（ja 阶段 1d）补：ja 的 topic 448 种里这 11 种查不到中文。
  //    全是**跨语种通用**的领域名 ⇒ 进共享表，别的语种也跟着不再静默少印。
  //    ⚠️ `buddhism` 小写那条是源头大小写不一致（`Buddhism` 已有），一并收 ——
  //       归一化交给映射表比在建库侧改源头值安全（改了就对不回源头）。
  // 🔴 2026-09-18（ja 阶段 1f，ja/zh 两版接进来）补：宗教/思想领域 + 修辞学。
  //    `Christian` 106 条是 ja 版的大户（`天`「神がいる場所」/`祝福`/`クリスマス`）。
  //    ⚠️ `rhetoric` 共享 REGISTER 里已有「修辞」（当**语域**用），这里是**领域**
  //       （`メタファー`「隠喩」/`オノマトペ`）—— 同一个码两种用法，两张表各有一条，
  //       靠 `kind` 分开，不会打架。
  // ja/zh 两版还带来两个领域：`capital-city` 30 条（首都）、`lexicology` 1 条。
  'capital-city': '首都', lexicology: '词汇学',
  //    ⚠️ `Jainism`/`Sikhism` **本表下方早就有**（那段用双引号格式，我第一版没查到就
  //       又写了一遍）—— **tsc 的 TS1117 当场逮到重复键**。JS 对象字面量后者胜出，
  //       两条值恰好一样所以行为没变，但它是一条随时会分叉的隐患。
  Christian: '基督教', Protestant: '新教', Biblical: '圣经',
  Tao: '道教', Nazism: '纳粹主义', Confucianism: '儒学',
  'physical-sciences': '自然科学', 'board-games': '棋盘游戏', ideology: '意识形态',
  'mechanical-engineering': '机械工程', 'Shingon-Buddhism': '真言宗',
  'medical-terminology': '医学术语', 'Tendai-or-Kegon-Buddhism': '天台宗·华严宗',
  buddhism: '佛教', 'electrical-device': '电器', 'performing-arts': '表演艺术',
  prefectures: '行政区划',
  medicine: '医学', anatomy: '解剖学', nautical: '航海', botany: '植物学',
  'organic-chemistry': '有机化学', 'organic chemistry': '有机化学', music: '音乐',
  biochemistry: '生物化学', architecture: '建筑', chemistry: '化学', cities: '城市',
  pathology: '病理学', computing: '计算机', law: '法律', sports: '体育',
  zoology: '动物学', biology: '生物学', soccer: '足球', history: '历史',
  linguistics: '语言学', geology: '地质学', politics: '政治', religion: '宗教',
  mythology: '神话', mineralogy: '矿物学', metrology: '计量学', food: '食品',
  astronomy: '天文学', military: '军事', games: '游戏', geography: '地理',
  physics: '物理', grammar: '语法', philosophy: '哲学', pharmacology: '药理学',
  bullfighting: '斗牛', agriculture: '农业', geometry: '几何', economics: '经济学',
  heraldry: '纹章学', mathematics: '数学', psychology: '心理学', war: '战争',
  mammals: '哺乳动物', electronics: '电子', finance: '金融', Christianity: '基督教',
  tools: '工具', baseball: '棒球', biblical: '圣经', art: '艺术', cytology: '细胞学',
  chess: '国际象棋', 'inorganic-chemistry': '无机化学', electricity: '电学',
  surgery: '外科', construction: '施工', mechanics: '力学', meteorology: '气象学',
  fish: '鱼类', cooking: '烹饪', theater: '戏剧', genetics: '遗传学', insects: '昆虫',
  textiles: '纺织', 'video-games': '电子游戏', LGBT: '性少数', education: '教育',
  photography: '摄影', dance: '舞蹈', dancing: '舞蹈', literature: '文学',
  mycology: '真菌学', printing: '印刷', folklore: '民俗', poetry: '诗歌',
  countries: '国家', country: '国家', 'card-games': '纸牌', cycling: '自行车',
  paleontology: '古生物学', phonetics: '语音学', sociology: '社会学', weaponry: '武器',
  physiology: '生理学', aeronautics: '航空', neurology: '神经病学', psychiatry: '精神病学',
  ecology: '生态学', Islam: '伊斯兰教', engineering: '工程', vehicles: '车辆',
  automotive: '汽车', typography: '排版', climbing: '攀登', film: '电影',
  Internet: '互联网', business: '商业', cinematography: '电影摄影', logic: '逻辑学',
  mining: '采矿', transport: '运输', 'linear-algebra': '线性代数', television: '电视',
  basketball: '篮球', boxing: '拳击', immunology: '免疫学', metallurgy: '冶金',
  optics: '光学', tennis: '网球', aviation: '航空', fencing: '击剑', journalism: '新闻',
  statistics: '统计学', astrology: '占星', carpentry: '木工', oncology: '肿瘤学',
  taxonomy: '分类学', feminism: '女权主义', archaeology: '考古学', archeology: '考古学',
  clothing: '服装', exercise: '健身', fantasy: '奇幻', lifestyle: '生活方式',
  sewing: '缝纫', fishing: '渔业', 'motor-racing': '赛车', racing: '竞速',
  science: '科学', sciences: '科学', 'science-fiction': '科幻', 'science fiction': '科幻',
  'martial-arts': '武术', 'martial arts': '武术', ophthalmology: '眼科',
  'rail-transport': '铁路', railways: '铁路', sex: '性', sexuality: '性', sexology: '性学',
  'Roman-Catholicism': '天主教', Catholicism: '天主教', cosmetics: '化妆品',
  dentistry: '牙科', odontology: '牙科', theology: '神学', ornithology: '鸟类学',
  telecommunications: '电信', accounting: '会计', anthropology: '人类学',
  athletics: '田径', equestrianism: '马术', technology: '技术', algebra: '代数',
  bacteriology: '细菌学', cardiology: '心脏病学', entomology: '昆虫学',
  horticulture: '园艺', microbiology: '微生物学', telephony: '电话', virology: '病毒学',
  hunting: '狩猎', weightlifting: '举重', arithmetic: '算术', dermatology: '皮肤科',
  neuroanatomy: '神经解剖学', numismatics: '钱币学', oenology: '酿酒学', poker: '扑克',
  rugby: '橄榄球', semantics: '语义学', 'American-football': '美式橄榄球',
  broadcasting: '广播', football: '足球', furniture: '家具', gaming: '游戏',
  'graphical-user-interface': '图形界面', zootomy: '动物解剖学', banking: '银行',
  narratology: '叙事学', swimming: '游泳', weather: '天气', alchemy: '炼金术',
  comics: '漫画', manga: '漫画', electrical: '电气', fiction: '小说', firearms: '枪械',
  ichthyology: '鱼类学', 'law-enforcement': '执法', phonology: '音系学',
  programming: '编程', prosody: '韵律学', tourism: '旅游', trigonometry: '三角学',
  veterinary: '兽医', ethics: '伦理学', fashion: '时尚', government: '政府',
  hematology: '血液学', marketing: '市场营销', orthography: '正字法',
  topography: '地形学', beekeeping: '养蜂', 'clinical-psychology': '临床心理学',
  communication: '传播', electromagnetism: '电磁学', embryology: '胚胎学',
  gymnastics: '体操', hydrology: '水文学', lichenology: '地衣学',
  parapsychology: '超心理学', radio: '无线电', road: '道路', Buddhism: '佛教',
  billiards: '台球', cryptozoology: '神秘动物学', geopolitics: '地缘政治',
  golf: '高尔夫', handball: '手球', historiography: '史学',
  'social-science': '社会科学', 'social-sciences': '社会科学', taxation: '税务',
  technical: '技术', teratology: '畸形学', thermodynamics: '热力学', time: '时间',
  Zoroastrianism: '琐罗亚斯德教', astrophysics: '天体物理学', bodybuilding: '健美',
  chronology: '年代学', 'computer-graphics': '计算机图形学', copyright: '版权',
  dogs: '犬', drama: '戏剧', dramaturgy: '戏剧学', insurance: '保险',
  'intellectual-property': '知识产权', mechanical: '机械', networking: '网络',
  philately: '集邮', pragmatics: '语用学', 'professional-wrestling': '职业摔角',
  volleyball: '排球', wine: '葡萄酒', 'algebraic-geometry': '代数几何',
  calculus: '微积分', communism: '共产主义', 'computer-hardware': '计算机硬件',
  continents: '大洲', design: '设计', diving: '潜水', ecclesiastical: '教会',
  farriery: '蹄铁术', financial: '金融', forestry: '林业', gambling: '赌博',
  health: '健康', investment: '投资', jewelry: '珠宝', judo: '柔道',
  lexicography: '词典学', management: '管理', media: '媒体', occultism: '神秘学',
  planetology: '行星学', pool: '桌球', pornography: '色情', psychoanalysis: '精神分析',
  snooker: '斯诺克', software: '软件', syntax: '句法', vegetable: '蔬菜',
  wrestling: '摔跤', Gnosticism: '诺斯替教', 'alternative-medicine': '替代医学',
  arachnology: '蛛形学', archery: '射箭', astronautics: '航天', blogging: '博客',
  bridge: '桥牌', cartography: '制图学', climatology: '气候学', color: '颜色',
  colour: '颜色', comedy: '喜剧', commerce: '商贸', commercial: '商业',
  'computer-games': '电脑游戏', 'computer-languages': '计算机语言', cosmology: '宇宙学',
  cryptography: '密码学', diplomacy: '外交', epidemiology: '流行病学',
  espionage: '间谍', fabrics: '织物', firefighting: '消防', geomorphology: '地貌学',
  'graph-theory': '图论', healthcare: '医疗保健', informatics: '信息学',
  knitting: '编织', 'mobile-telephony': '移动通信', obstetrics: '产科',
  pseudoscience: '伪科学', rowing: '赛艇', skiing: '滑雪', surfing: '冲浪',
  toxicology: '毒理学', traffic: '交通', urology: '泌尿科', writing: '书写',
  ACG: '二次元', 'Abrahamic-religions': '亚伯拉罕诸教', Ayurveda: '阿育吠陀',
  Egyptology: '埃及学', Freemasonry: '共济会', freemasonry: '共济会',
  'SI-units': '国际单位制', anarchism: '无政府主义', anime: '动画', baking: '烘焙',
  biotechnology: '生物技术', bowling: '保龄球', brewing: '酿造',
  'category-theory': '范畴论', ceramics: '陶瓷', checkers: '西洋跳棋',
  'complex-analysis': '复分析', computer: '计算机', 'computing-theory': '计算理论',
  criminology: '犯罪学', crystallography: '晶体学', databases: '数据库', drugs: '药物',
  'emergency-medicine': '急救医学', endocrinology: '内分泌学', energy: '能源',
  entertainment: '娱乐', epigraphy: '铭文学', falconry: '鹰猎', fascism: '法西斯主义',
  fluids: '流体', gemmology: '宝石学', gemology: '宝石学', glaciology: '冰川学',
  glassmaking: '玻璃制造', 'graphic-design': '平面设计', 'group-theory': '群论',
  hairdressing: '美发', hairstyle: '发型', 'higher-education': '高等教育',
  horology: '钟表学', horses: '马', hydraulics: '水力学', hydrography: '水文测绘',
  illness: '疾病', 'information-science': '信息科学', legal: '法律',
  limnology: '湖沼学', 'linguistic-morphology': '词法', location: '地点',
  lutherie: '提琴制作', maritime: '海事', masonry: '砌筑',
  'mathematical-analysis': '数学分析', meat: '肉类', meats: '肉类', monarchy: '君主制',
  morphology: '形态学', motorcycling: '摩托车', mountaineering: '登山',
  neuroscience: '神经科学', newspapers: '报刊', nobility: '贵族',
  'number-theory': '数论', oceanography: '海洋学', officialese: '公文体',
  palynology: '孢粉学', petrochemistry: '石油化学', petrology: '岩石学', pets: '宠物',
  'political-science': '政治学', 'probability-theory': '概率论', 'real-estate': '房地产',
  retail: '零售', sailing: '帆船', seismology: '地震学', semiotics: '符号学',
  'speech-pathology': '言语病理学', state: '州省', stone: '石材', temperature: '温度',
  'translation-studies': '翻译学', travel: '旅行', 'units-of-measure': '计量单位',
  volcanology: '火山学', weaving: '织造', weekdays: '星期', woodworking: '木工',
  // 🔴 2026-08-27 fr 收领域标签时补的 12 个（族 C）。法文版给 260,660 条可见义项
  //    标了 topics，现有表已覆盖 95.3%，这 12 个把覆盖率抬到 **99%**。
  //    ⚠️ `linguistic` 与已有的 `linguistics` 是**两个键**（法文版用无 s 的写法），
  //       两个都要留 —— 少一个就有 3,897 条义项的标签渲染成英文原始串。
  linguistic: '语言学', cuisine: '烹饪', automobile: '汽车', mammalogy: '哺乳动物学',
  biogeography: '生物地理学', beverages: '饮料', police: '警务', malacology: '软体动物学',
  pedology: '土壤学', petrography: '岩相学', ethnology: '民族学', colorimetry: '色度学',
  // 🔴 2026-08-27（fr 族 C 第二段）：法文版 `tags` 里的领域名映射到的规范键。
  //    法语维基词典的领域体系有一批英语版没有的细分（犬学/猫科学/鲸类学/翼手目学），
  //    合并成「动物学」会把它给的信息抹掉。
  didactics: '教学法', viticulture: '葡萄种植', nosology: '疾病分类学', occupations: '职业', industry: '工业',
  'animal-husbandry': '畜牧', pharmacy: '药学', administration: '行政',
  'veterinary-medicine': '兽医', labor: '劳动', gardening: '园艺', 'role-playing-games': '角色扮演游戏',
  cynology: '犬学', felinology: '猫科学', hippology: '马学', unionism: '工会', activism: '社会运动',
  petroleum: '石油', 'computer-networking': '计算机网络', 'computer-security': '信息安全',
  'artificial-intelligence': '人工智能', wikis: '维基', 'nuclear-physics': '核', liturgy: '礼拜仪式',
  Judaism: '犹太教', Hinduism: '印度教', 'ancient-greece': '古希腊', 'ancient-rome': '古罗马',
  urbanism: '城市规划', 'public-works': '公共工程', logistics: '物流', painting: '绘画', sculpture: '雕塑',
  'remote-sensing': '遥感', acoustics: '声学', 'physical-chemistry': '物理化学',
  stereochemistry: '立体化学', confectionery: '糖果', butchery: '肉铺', cheeses: '奶酪', leather: '皮革',
  'natural-sciences': '博物学', prehistory: '史前', calendar: '历法',
  'international-relations': '国际关系', lepidopterology: '鳞翅目学', herpetology: '爬虫学',
  primatology: '灵长类学', cetology: '鲸类学', ethnobiology: '民族生物学', phytosociology: '植物社会学',
  arboriculture: '树艺', agronomy: '农学', environment: '环境', 'library-science': '图书馆学',
  papermaking: '造纸', bookbinding: '装订', locksmithing: '锁具', cooperage: '制桶',
  'electrical-engineering': '电工', gynecology: '妇科', childcare: '育儿', nutrition: '营养学',
  'public-health': '公共卫生', cosmetology: '美容', disability: '残障', reproduction: '生殖',
  society: '社会', family: '家庭', funerals: '丧葬', prison: '监狱',
  advertising: '广告', trademarks: '商标', postal: '邮政', safety: '安全', 'board-sports': '板类运动',
  islands: '岛屿', rivers: '河流', toponymy: '地名学', ethnonymy: '族名学', anthroponymy: '人名学',

  // ══ 🔴 2026-09-15：en 的 kaikki topic 解开展示，一次把落点上的洞补完 ══
  //    在此之前 en 的英文 topic **有意不显示**（77 万条），因为「上千种取值没有映射表」。
  //    真按落点量过之后是另一回事（`[[measure-landing-not-source]]`）：
  //      · 这张共享表**已经覆盖 en 的 40.7 万条**（es/fr 那两轮翻的，值域是共用的）；
  //      · kaikki 的 topic 是**一条链**，折掉祖先之后（见 `topic-tree.ts`）
  //        真正到达读者的只剩 1.4 万条没中文 —— 不是「上千种」。
  //    ⇒ 补的就是这 315 种。判不准的逐条回库看过样本再定词。
  //    ⚠️ 同一个概念的多种写法（`naval`/`navy`/`Navy`、`paleography`/`palaeography`、
  //       `fortification`/`fortifications`、源头的错拼 `palentology`/`mineralology`）
  //       一律映到同一个中文，靠调用方按**映射后的文字**去重。
  hobbies: '业余爱好', cricket: '板球', Greek: '希腊', rhetoric: '修辞', communications: '通信', topology: '拓扑学',
  BDSM: 'BDSM', sumo: '相扑', "ice-hockey": '冰球', particle: '粒子', arts: '艺术', Roman: '罗马',
  Japanese: '日本', manufacturing: '制造业', "set-theory": '集合论', "horse-racing": '赛马',
  "Ancient-Rome": '古罗马', crafts: '手工艺', "human-sciences": '人文社科', naval: '海军', property: '物权法',
  Norse: '北欧', publishing: '出版', "signal-processing": '信号处理', Jewish: '犹太', manner: '方式副词',
  paganism: '异教', metalworking: '金属加工', curling: '冰壶', snowboarding: '单板滑雪',
  cryptocurrencies: '加密货币', Mormonism: '摩门教', "cellular-automata": '元胞自动机', skateboarding: '滑板',
  roofing: '屋面工程', Marxism: '马克思主义', surveying: '测绘', birdwatching: '观鸟', Chinese: '中国',
  Germanic: '日耳曼', shipbuilding: '造船', "Indo-European-studies": '印欧语研究', "game-theory": '博弈论',
  aerospace: '航空航天', phytopathology: '植物病理学', Egyptian: '埃及', trading: '交易',
  "underwater-diving": '潜水', glassblowing: '玻璃吹制', sociolinguistics: '社会语言学', acting: '表演',
  demoscene: 'demoscene', computational: '计算语言学', bingo: '宾果', authorship: '著作', dice: '骰子',
  "fluid-dynamics": '流体力学', Jainism: '耆那教', juggling: '杂耍', "stock-market": '股市',
  "order-theory": '序理论', "civil-engineering": '土木工程', Wicca: '威卡教', "World-War-I": '一战',
  "seduction-community": '搭讪圈', Scientology: '山达基', ufology: '飞碟学', Shinto: '神道教', Navy: '海军',
  epistemology: '认识论', machining: '机械加工', softball: '垒球', shipping: '航运', backgammon: '双陆棋',
  "hip-hop": '嘻哈', combinatorics: '组合数学', robotics: '机器人学', cartomancy: '纸牌占卜', Quakerism: '贵格会',
  "space-science": '空间科学', demography: '人口学', "patent-law": '专利法', occult: '神秘学',
  Rastafari: '拉斯塔法里', audio: '音响', demographics: '人口统计', Sikhism: '锡克教', homeopathy: '顺势疗法',
  skating: '滑冰', Protestantism: '新教', histology: '组织学', Unix: 'Unix', lacrosse: '长曲棍球',
  "web-design": '网页设计', plumbing: '管道工程', "textual-criticism": '校勘学', gynaecology: '妇科',
  "information-theory": '信息论', gastroenterology: '消化内科', mysticism: '神秘主义', palaeography: '古文字学',
  paleography: '古文字学', etymology: '词源学', radiology: '放射医学', creationism: '神创论',
  probability: '概率论', mahjong: '麻将', telegraphy: '电报', "software-compilation": '编译',
  "algebraic-topology": '代数拓扑', blackjack: '二十一点', smoking: '烟草', roguelikes: 'Roguelike',
  darts: '飞镖', Latin: '拉丁', academia: '学术界', fortification: '筑城', shogi: '将棋', phrenology: '颅相学',
  calligraphy: '书法', IRC: 'IRC', aerodynamics: '空气动力学', "ball-games": '球类',
  "systems-theory": '系统论', money: '货币', graffiti: '涂鸦', squash: '壁球',
  "stock-ticker-symbol": '股票代码', socialism: '社会主义', fortifications: '筑城', navy: '海军',
  pulmonology: '呼吸内科', electrochemistry: '电化学', "classical-studies": '古典学',
  "measure-theory": '测度论', phenomenology: '现象学', "Rubik's-Cube": '魔方', circus: '马戏',
  netball: '无挡板篮球', nanotechnology: '纳米技术', "entertainment-industry": '娱乐业',
  "letterpress-typography": '活版印刷', Scrabble: '拼字游戏', dyeing: '染色', caving: '洞穴探险',
  prostitution: '性交易', "Chinese-cuisine": '中餐', ethnography: '民族志', ballistics: '弹道学',
  dominoes: '多米诺骨牌', musicology: '音乐学', Hebrew: '希伯来', "travel-industry": '旅游业',
  ropemaking: '制绳', bryology: '苔藓学', campanology: '钟铃学', duration: '时段', vexillology: '旗帜学',
  "Eastern-Christianity": '东方基督教', language: '语言', acrobatics: '杂技', cheerleading: '啦啦操',
  beer: '啤酒', conchology: '贝壳学', drafting: '制图', hydrodynamics: '流体动力学', videography: '摄像',
  engraving: '雕版', "racquet-sports": '拍类运动', bioinformatics: '生物信息学', phycology: '藻类学',
  nematology: '线虫学', xiangqi: '象棋', "radio-communications": '无线电通信',
  "information-technology": '信息技术', skydiving: '跳伞', tarot: '塔罗', nephrology: '肾内科',
  "quantum-field-theory": '量子场论', "temporal-location": '时点', "Western-Christianity": '西方基督教',
  Sufism: '苏非派', capitalism: '资本主义', neurobiology: '神经生物学', planets: '行星', editing: '编辑',
  conservation: '自然保护', spinning: '纺纱', sociopolitics: '社会政治', Linux: 'Linux',
  Ornithology: '鸟类学', "aerial-freestyle": '自由式滑雪空中技巧', "speech-therapy": '言语治疗',
  bibliography: '目录学', dressage: '盛装舞步', ontology: '本体论', paintball: '彩弹射击',
  "rock-paper-scissors": '石头剪刀布', parachuting: '跳伞', horseracing: '赛马', radiography: '放射成像',
  Kantianism: '康德主义', acarology: '蜱螨学', "visual-art": '视觉艺术', ironworking: '铁工', fisheries: '渔业',
  planktology: '浮游生物学', parasitology: '寄生虫学', dialectology: '方言学', guitar: '吉他',
  naturism: '裸体主义', neurotoxicology: '神经毒理学', CAD: 'CAD', DVD: 'DVD', andrology: '男科',
  bowmaking: '制弓', uranography: '星图学', paleogeography: '古地理学', quarrying: '采石',
  "stock-exchange": '证券交易所', dressmaking: '女装裁制', chromatography: '色谱法',
  "parliamentary-procedure": '议事规则', scholarly: '学术出版', NASA: 'NASA', Windows: 'Windows',
  neurophysiology: '神经生理学', "visual-arts": '视觉艺术', astrocartography: '星位占星', pesäpallo: '芬兰棒球',
  paleobiology: '古生物学', quilting: '绗缝', scientific: '科技用语', existentialism: '存在主义',
  gerontology: '老年学', psycholinguistics: '心理语言学', information: '信息', pharmaceuticals: '药品',
  demonology: '恶魔学', "analytic-number-theory": '解析数论', paleoanthropology: '古人类学',
  palentology: '古生物学', papercraft: '纸艺', "space-sciences": '空间科学', ballooning: '热气球',
  behavior: '行为', immunochemistry: '免疫化学', lithography: '平版印刷', sociobiology: '社会生物学',
  histopathology: '组织病理学', piledriving: '打桩', finances: '财务', retailing: '零售',
  mineralology: '矿物学', city: '城市', telephone: '电话', stenography: '速记',
  "wireless-telegraphy": '无线电报', "country-dancing": '乡村舞', court: '法庭', microeconomics: '微观经济学',
  weapon: '武器', hawking: '放鹰狩猎', feudalism: '封建制', "pocket-billiards": '落袋台球',
  stratigraphy: '地层学', manosphere: '男性圈', psychopathology: '精神病理学', spiritualism: '唯灵论',
  states: '状态', modelling: '模型制作', trains: '铁道', Buddhist: '佛教', CSS: 'CSS',
  "Indian-Chinese-cuisine": '印式中餐', "Indian-cookery": '印度菜', Lisp: 'Lisp',
  "alpine-skiing": '高山滑雪', bone: '骨骼', angelology: '天使学', "historical-ethnography": '历史民族志',
  "art-history": '艺术史', iconography: '图像学', smithwork: '锻工', sailmaking: '制帆',
  astrogeology: '天体地质学', "brick-making": '制砖', "radio-technology": '无线电技术', "sugar-making": '制糖',
  "tin-plate-manufacture": '马口铁制造', jewellery: '珠宝', cryptocurrency: '加密货币', cards: '纸牌',
  "in-technical-contexts": '术语用法', cigars: '雪茄', climate: '气候', seasons: '季节',
  codicology: '古籍版本学', colleges: '高校', scriptwriting: '编剧', talking: '言谈',
  "computer-sciences": '计算机科学', "historical-demography": '历史人口学', "sheepdog-trials": '牧羊犬赛',
  "economic-liberalism": '经济自由主义', lubricants: '润滑剂', "sewage-treatment": '污水处理',
  equitation: '马术', "gem-cutting": '宝石切割', veganism: '纯素主义', region: '地域', mammology: '哺乳动物学',
  "printing-technology": '印刷技术', traumatology: '创伤学', pneumology: '呼吸病学',
};

// 词汇关系的中文名。`derived` 是「派生词/习语」（`pie` → `a contrapié`），
// 与「相关词」分开：前者是从这个词长出来的，后者只是语义相邻。
// 🔴 2026-09-05：`expression`/`proverb` 补进来 —— 它们是 de 的 C37（关系层重收）
//    引进的两个 kind（12,803 ＋ 1,058 行），**而这张表没跟着加** ⇒ 德语页面上
//    直接印出英文原词：`Haus` 的关系行里混着 `expression auf jemanden Häuser bauen können`、
//    `proverb ein Haus ist leichter angezündet als gelöscht`。
//    ⚠️ 三层数据的闸全绿（kind 在值域内、关系挂对了义项），**是渲染出来才看见的**
//      —— `[[it-display-layer-stage8]]` 那条又中一次。
//    ⇒ 契约闸新加一条：`sense_relation.kind` 的每个值都必须在这张表里有名字。
export const REL_LABELS: Record<string, string> = {
  synonym: '近义', antonym: '反义', hypernym: '上位', hyponym: '下位',
  holonym: '整体', meronym: '部分', coordinate: '同类', related: '相关',
  derived: '派生', expression: '习语', proverb: '谚语',
};

export const TRANS_LABELS: Record<string, string> = { t: '及物', i: '不及物', ti: '及物/不及物' };

// ============================================================================
// 数据出处的中文名。2026-09-12。
//
// ⭐ 起因：用户问「搭配 / 固定短语 habitante quiteño 基多居民，这种为什么直接查
//    却没有结果呢？」—— 往回查才发现 es/it/fr/pt/de 五门的搭配层**整层是豆包
//    凭记忆写的**（各门 `pipeline/b_translate.py` 里同一行 prompt 的 `col` 字段），
//    没有任何外部出处。已确凿的错误：pt 的 `color primária 原色`
//    （`color` 在库里两条义项都标着 archaic，现代葡语是 `cor primária`）、
//    `Google Search`、以及 es 664 / it 492 / fr 190 / pt 364 条混进来的专名。
//
// 🔴 **不能只在展示层写死一句「仅供参考」** —— 那是拿展示层补丁盖数据问题
//    （`[[aim-for-perfect-not-cheap]]`）。出处已经作为 `collocation.src`
//    写进五门的库里（`scripts/mark_collocation_src.py`，98,973 行），
//    这张表只负责把那个值翻成人话。
//
// ⚠️ **数值别写进这里**。「74.2% 在我们自己的语料里查不到佐证」是**佐证率**，
//    不是**错误率** —— 我们的例句语料本来就小，`uñas postizas 假指甲` 查不到
//    但它是完全正常的西语。真实错误率至今没有量过，所以文案只说「机器生成」
//    这个**事实**，不说「多少是错的」这个**我不知道的数**
//    （`[[verify-before-claiming-confirmed]]`）。
// ============================================================================
// 🔴 **2026-09-12 下午起，这张表不再被页面渲染。** 用户看了效果后推翻：
//     「机器生成，这些标识还是不要了，用户看了只会产生不信任。
//       要么整个搭配不展示，要么就糊弄一下用户，而且也没说一定就是错的」
//    ⇒ 表留着，理由有两条，都不是"舍不得删"：
//      ① `contract-check-colloc.tsx` 拿它当**数据闸**：库里每个 `collocation.src`
//         取值都必须在这张表里有名字 —— 冒出没见过的来源要当场知道；
//      ② 它同时是那道**反向断言**的词表：「页面上不许出现这些词」。
//    删掉它，上面两条就都没有依据了。
export const SRC_LABELS: Record<string, { short: string; long: string; trusted: boolean }> = {
  'llm:doubao': {
    short: '机器生成',
    long: '由模型凭语言知识生成，未经词典收录，可能有误',
    trusted: false,
  },
  'kaikki:pseudo-sense': {
    short: '词典收录',
    long: '来自维基词典该词条下的短语条目',
    trusted: true,
  },
  'kaikki:subentry': {
    short: '词典收录',
    long: '来自维基词典该词条下的子条目',
    trusted: true,
  },
};

/** 出处 → 展示用信息。**未知出处不编造名字**，原样回显那个值并当作"不可信"。 */
export function srcLabel(src: string | null | undefined) {
  if (!src) return { short: '出处不明', long: '这条数据没有记录出处', trusted: false };
  return SRC_LABELS[src] ?? { short: src, long: '未知出处：' + src, trusted: false };
}
