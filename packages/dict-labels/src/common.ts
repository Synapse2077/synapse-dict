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
};

// 词汇关系的中文名。`derived` 是「派生词/习语」（`pie` → `a contrapié`），
// 与「相关词」分开：前者是从这个词长出来的，后者只是语义相邻。
export const REL_LABELS: Record<string, string> = {
  synonym: '近义', antonym: '反义', hypernym: '上位', hyponym: '下位',
  holonym: '整体', meronym: '部分', coordinate: '同类', related: '相关',
  derived: '派生',
};

export const TRANS_LABELS: Record<string, string> = { t: '及物', i: '不及物', ti: '及物/不及物' };
