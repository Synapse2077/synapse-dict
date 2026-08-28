// 法语专属展示映射。

export const FR_AUX_LABELS: Record<string, string> = {
  avoir: '助动词 avoir', être: '助动词 être', both: '助动词 avoir/être',
};

export const FR_VGROUP_LABELS: Record<string, string> = {
  '1': '第一组 -er', '2': '第二组 -ir (-iss-)', '3': '第三组（不规则）',
};

// 形容词位置：前置/后置/两可（BAGS 类前置，颜色国籍等后置，ancien/grand 两可且变义）
export const FR_ADJPOS_LABELS: Record<string, string> = {
  pre: '名词前', post: '名词后', both: '前/后（位置变义）',
};

// 法语地区标签（法语专属，不复用 es/it 的地区表）。映射不到回退原文。
export const FR_REGION_LABELS: Record<string, string> = {
  France: '法国', Belgium: '比利时', Switzerland: '瑞士法语区', Quebec: '魁北克',
  Canada: '加拿大', 'Canadian-French': '加拿大法语', Louisiana: '路易斯安那',
  Acadia: '阿卡迪亚', Africa: '非洲', Wallonia: '瓦隆', Haiti: '海地',
  Luxembourg: '卢森堡', Normandy: '诺曼底', Brittany: '布列塔尼', Provence: '普罗旺斯',
  Occitania: '奥克西塔尼', Savoie: '萨瓦', Languedoc: '朗格多克', Picardy: '皮卡第',
  Ontario: '安大略', Newfoundland: '纽芬兰', Antilles: '安的列斯', Guyana: '圭亚那',
  Northern: '北部', Southern: '南部', Eastern: '东部', Western: '西部', Central: '中部',
  regional: '地区性', dialectal: '方言', 'Old-French': '古法语', 'Middle-French': '中古法语',
};

// 🔴 2026-08-26（阶段 8）补齐 `sense_tag(kind='region')` 里**实际出现过但上表没有**的值。
//    全量取值 54 种，逐个对过 —— 上表是七月按印象写的，缺了一半。
//    ⚠️ 映射不到会把生标签（`North-America`）直接显示给用户，
//       这类「表不全」的缺陷闸查不出来，只能靠**把取值全查一遍**发现。
Object.assign(FR_REGION_LABELS, {
  'North-America': '北美', 'Ancient-Rome': '古罗马', Roman: '罗马', Canadian: '加拿大',
  Rwanda: '卢旺达', Morocco: '摩洛哥', Congo: '刚果', Lyon: '里昂', West: '西部',
  Vietnam: '越南', Alsace: '阿尔萨斯', Egyptian: '埃及', Lorraine: '洛林',
  Montreal: '蒙特利尔', North: '北部', 'New-England': '新英格兰', Paris: '巴黎',
  East: '东部', Europe: '欧洲', European: '欧洲', Bugey: '比热', Fribourg: '弗里堡',
  Ireland: '爱尔兰', 'New-Zealand': '新西兰', Northeastern: '东北部', South: '南部',
  Southeastern: '东南部', 'Southern-Africa': '南部非洲', Toulouse: '图卢兹', Valais: '瓦莱',
});

// 🔴 **同一个概念在库里有两套词汇表**，这里必须分开两张：
//      `pronunciation.region` → BCP-47 式代码（fr-FR / fr-CA / fr-CH / fr-BE / fr-AF）
//      `sense_tag(region)`    → 英文地名（Quebec / Belgium / …）
//    音标层建表时把 `raw_tags` 归一成了代码，义项标签层保留了英文名。
//    ⚠️ 把上面那张表拿来查 `fr-FR` 会落空、直接把 `fr-FR` 显示给用户。
//    📋 记账：真正的修法是让 `sense_tag` 也归一成代码（数据层的事，不在阶段 8 做）。
export const FR_REGION_CODE_LABELS: Record<string, string> = {
  'fr-FR': '法国', 'fr-CA': '加拿大', 'fr-CH': '瑞士', 'fr-BE': '比利时', 'fr-AF': '非洲',
};

// 法语冠词（逐义项性别用）：le 阳 / la 阴。
export const FR_ARTICLE: Record<string, string> = { m: 'le', f: 'la', mf: 'le/la' };

// ══════════════════════════════════════════════════════════════════════════
//  法文版 `tags` 的分桶映射（2026-08-27，族 C 第二段）
//
//  法文版给可见义项写了 3,415 种 tag / 180,410 行，现有各表只覆盖 41.8%。
//  长尾全是**法语写的**领域名与地名（`Cynologie` 犬学 / `Armement` 军械 /
//  `Québec` / `Normandie`），以及一批**根本不是标签**的结构标记。
//
//  🔴 分四桶，**结构标记明确不出版**：把 `alt-of`（12,753 行，最大的一个）
//     或 `transitive` 印成义项旁边的胶囊，读者会以为那是词义的一部分。
//     那些是语法/元信息，属于词条头或根本不该展示。
//
//  ⭐ 值一律映射到**已有的规范键**（英文），中文只从 `TOPIC_LABELS` /
//     `FR_REGION_LABELS` / `REGISTER_LABELS` 取 —— 在这里再写一份中文
//     就是让同一个概念有两个译名慢慢漂开（`[[refactor-mindset-code-quality]]`）。
// ══════════════════════════════════════════════════════════════════════════

/** 法文版 tag → 领域（`sense_tag.kind='topic'`，中文查 `TOPIC_LABELS`） */
export const FR_TAG_TOPIC: Record<string, string> = {
  // —— 法文版把「这个词是国名/岛名/河名」也写成 tag，对查词的人很有用
  Pays: 'countries', Îles: 'islands', 'Cours d’eau': 'rivers',
  Toponymie: 'toponymy', toponymic: 'toponymy', Ethnonymie: 'ethnonymy',
  Anthroponyme: 'anthroponymy',
  // —— 学科与行业
  Didactique: 'didactics', Économie: 'economics', 'Économie du travail': 'economics',
  Viticulture: 'viticulture', Nosologie: 'nosology', Métier: 'occupations',
  Génétique: 'genetics', Industrie: 'industry', Armement: 'weaponry',
  Élevage: 'animal-husbandry', Zootechnie: 'animal-husbandry', Pharmacie: 'pharmacy',
  Imprimerie: 'printing', Audiovisuel: 'broadcasting', Administration: 'administration',
  'Médecine vétérinaire': 'veterinary-medicine', Travail: 'labor', Justice: 'law',
  'Droit féodal': 'law', 'Droit du travail': 'law', 'Droit de propriété': 'law',
  Navigation: 'nautical', Jardinage: 'gardening', 'Jeux vidéo': 'video-games',
  'Jeux de rôle': 'role-playing-games', 'Cartes à jouer': 'card-games',
  LGBTQ: 'LGBT', Cynologie: 'cynology', Félinologie: 'felinology',
  Hippologie: 'hippology', 'Sports hippiques': 'equestrianism', Manège: 'equestrianism',
  Communisme: 'communism', Syndicalisme: 'unionism', 'Luttes sociales': 'activism',
  Transféminisme: 'feminism',
  'Industrie pétrolière': 'petroleum', Raffinage: 'petroleum',
  'Réseaux informatiques': 'computer-networking', 'Sécurité informatique': 'computer-security',
  'Programmation orientée objet': 'programming', 'Langage Java': 'programming',
  'Intelligence artificielle': 'artificial-intelligence', Infographie: 'computer-graphics',
  Wikis: 'wikis',
  'Science-fiction': 'science-fiction', Fantastique: 'fantasy',
  Nucléaire: 'nuclear-physics', 'Sécurité nucléaire': 'nuclear-physics',
  'Physique des réacteurs nucléaires': 'nuclear-physics',
  'Technologie des réacteurs nucléaires': 'nuclear-physics',
  'Cycle du combustible nucléaire': 'nuclear-physics',
  Divinité: 'mythology', 'Mythologie grecque': 'mythology', Liturgie: 'liturgy',
  Sunnisme: 'Islam', Judaism: 'Judaism', Biblical: 'biblical', Hinduism: 'Hinduism',
  'Ancient-Greek': 'ancient-greece', 'Ancient-Roman': 'ancient-rome',
  Urbanisme: 'urbanism', 'Travaux publics': 'public-works', Logistique: 'logistics',
  Peinture: 'painting', Sculpture: 'sculpture', Céramique: 'ceramics',
  'Télédétection spatiale': 'remote-sensing', 'Propulsion spatiale': 'astronautics',
  Optique: 'optics', Acoustique: 'acoustics', 'Chimie physique': 'physical-chemistry',
  'Chimie organique': 'organic-chemistry', Stéréochimie: 'stereochemistry',
  Pâtisserie: 'baking', Confiserie: 'confectionery', Boucherie: 'butchery',
  Charcuterie: 'butchery', Fromage: 'cheeses', Sauces: 'cooking',
  Metal: 'music', Rock: 'music', Jazz: 'music', Versification: 'poetry',
  Soierie: 'weaving', 'Travail du cuir': 'leather',
  'Histoire naturelle': 'natural-sciences', 'Histoire de France': 'history',
  'Histoire des techniques': 'history', 'Histoire des sciences': 'history',
  Préhistoire: 'prehistory', 'Calendrier chinois': 'calendar',
  'Relations internationales': 'international-relations',
  Lépidoptérologie: 'lepidopterology', Ophiologie: 'herpetology',
  Glirologie: 'mammalogy', Primatologie: 'primatology', Cétologie: 'cetology',
  Chiroptérologie: 'mammalogy', 'Biologie cellulaire': 'cytology',
  Ethnobiologie: 'ethnobiology', Phytosociologie: 'phytosociology',
  Arboriculture: 'arboriculture', Agronomie: 'agronomy',
  'Exploitation forestière': 'forestry', Environnement: 'environment',
  'Industrie minière': 'mining', 'Industrie de l’énergie': 'energy',
  Bibliothéconomie: 'library-science', Papeterie: 'papermaking', Reliure: 'bookbinding',
  Verrerie: 'glassmaking', Serrurerie: 'locksmithing', Horlogerie: 'horology',
  Tonnellerie: 'cooperage', Hydraulique: 'hydraulics', Électrotechnique: 'electrical-engineering',
  Gynécologie: 'gynecology', Puériculture: 'childcare', Nutrition: 'nutrition',
  'Santé publique': 'public-health', 'Médecine non conventionnelle': 'alternative-medicine',
  Cosmétologie: 'cosmetology', Handicap: 'disability', Reproduction: 'reproduction',
  Phonétique: 'phonetics', 'Théorie des graphes': 'graph-theory',
  'Sciences sociales': 'social-science', Société: 'society', Famille: 'family',
  Funéraire: 'funerals', Prison: 'prison', Publicité: 'advertising',
  'Marque commerciale': 'trademarks', Poste: 'postal', Sécurité: 'safety',
  'Lutte contre l’incendie': 'firefighting', Gymnastique: 'gymnastics',
  'Sports de glisse': 'board-sports', 'Pseudo-sciences': 'pseudoscience',
};

/** 法文版 tag → 地区（`sense_tag.kind='region'`，中文查 `FR_REGION_LABELS`） */
export const FR_TAG_REGION: Record<string, string> = {
  // —— 2026-08-27 第二轮补（长尾里 ≥15 行、确认是地名的）——
  Touraine: 'Touraine', Aunis: 'Aunis', Jura: 'Jura', Bourbonnais: 'Bourbonnais',
  Limousin: 'Limousin', Sologne: 'Sologne', Charentes: 'Charentes',
  'Charente-Maritime': 'Charente-Maritime', Drôme: 'Drome', Morvan: 'Morvan',
  Forez: 'Forez', Saintonge: 'Saintonge', Maine: 'Maine', Aquitaine: 'Aquitaine',
  Bordelais: 'Bordelais', Alpes: 'Alps', 'Languedoc-Roussillon': 'Languedoc-Roussillon',
  'Nord-Pas-de-Calais': 'Nord-Pas-de-Calais', 'Rhône-Alpes': 'Rhone-Alpes',
  Centre: 'Central-France', 'Centre de la France': 'Central-France',
  'Midi de la France': 'Southern-France', 'Sud de la France': 'Southern-France',
  'Ouest de la France': 'Western-France', Nord: 'Northern-France',
  Wallonie: 'Wallonia', 'Suisse romande': 'French-Switzerland', Genève: 'Geneva',
  Guyane: 'Guyane', Martinique: 'Martinique', Mayotte: 'Mayotte',
  'Polynésie française': 'French-Polynesia', 'Terre-Neuve': 'Newfoundland-fr',
  Joual: 'Joual',
  Maghreb: 'Maghreb', Tunisie: 'Tunisia', Madagascar: 'Madagascar',
  'Burkina Faso': 'Burkina-Faso', Mali: 'Mali', Bénin: 'Benin', Togo: 'Togo',
  Burundi: 'Burundi', Centrafrique: 'Central-African-Republic',
  'Congo-Brazzaville': 'Congo-Brazzaville', 'Afrique de l’Ouest': 'West-Africa',
  Liban: 'Lebanon', 'Île Maurice': 'Mauritius',
  'Amérique du Nord': 'North-America-fr', 'États-Unis': 'United-States',
  Missouri: 'Missouri', 'European-Union': 'European-Union',
  Québec: 'Quebec', Suisse: 'Switzerland', Belgique: 'Belgium', Louisiane: 'Louisiana',
  Acadie: 'Acadia', Afrique: 'Africa', Maroc: 'Morocco', Algérie: 'Algeria',
  'Côte d’Ivoire': 'Ivory-Coast', 'Congo-Kinshasa': 'Congo', Haïti: 'Haiti',
  Cameroun: 'Cameroon', Sénégal: 'Senegal', 'La Réunion': 'Reunion',
  Guadeloupe: 'Guadeloupe', 'Nouvelle-Calédonie': 'New-Caledonia', Japon: 'Japan',
  URSS: 'USSR', 'Vallée d’Aoste': 'Aosta-Valley',
  Normandie: 'Normandy', Bretagne: 'Brittany', Occitanie: 'Occitania',
  Bourgogne: 'Burgundy', 'Franche-Comté': 'Franche-Comte', Auvergne: 'Auvergne',
  Poitou: 'Poitou', Picardie: 'Picardy', Ardennes: 'Ardennes', Champagne: 'Champagne',
  Anjou: 'Anjou', Vendée: 'Vendee', Vosges: 'Vosges', Berry: 'Berry',
  Dauphiné: 'Dauphine', Lyonnais: 'Lyon', Marseille: 'Marseille',
  'Nord de la France': 'Northern', 'Parler gaga': 'Saint-Etienne',
};

// 🔴 2026-08-27 补：`FR_TAG_REGION` 映射到、而上面两张表里没有的 14 个键。
//    映射不到会把 `Ivory-Coast` 这种生标签直接印给用户 —— 契约闸会红。
Object.assign(FR_REGION_LABELS, {
  Algeria: '阿尔及利亚', Morocco: '摩洛哥', Cameroon: '喀麦隆', Senegal: '塞内加尔',
  'Ivory-Coast': '科特迪瓦', Japan: '日本', USSR: '苏联', Reunion: '留尼汪',
  Guadeloupe: '瓜德罗普', 'New-Caledonia': '新喀里多尼亚', 'Aosta-Valley': '瓦莱达奥斯塔',
  Burgundy: '勃艮第', 'Franche-Comte': '弗朗什-孔泰', Dauphine: '多菲内',
  Vendee: '旺代', 'Saint-Etienne': '圣艾蒂安',
  // 法国本土历史大区/城市（法文版直接用法语名，映射到自身）
  Auvergne: '奥弗涅', Poitou: '普瓦图', Ardennes: '阿登', Champagne: '香槟',
  Anjou: '安茹', Vosges: '孚日', Berry: '贝里', Marseille: '马赛',
  // 🔴 2026-08-27 第二轮：法文版长尾里剩下的地名，**从数据全量取**不再手写白名单
  //    （手写那版被 `abacost`/`smala` 打回过：它们都给了地区，只是不在我表里）。
  //    法国本土历史地区
  Touraine: '图赖讷', Aunis: '奥尼斯', Jura: '汝拉', Bourbonnais: '波旁内',
  Limousin: '利穆赞', Sologne: '索洛涅', Charentes: '夏朗特', 'Charente-Maritime': '滨海夏朗特',
  Drome: '德龙', Morvan: '莫尔旺', Forez: '福雷', Saintonge: '桑通日', Maine: '曼恩',
  Aquitaine: '阿基坦', Bordelais: '波尔多地区', Alps: '阿尔卑斯',
  'Languedoc-Roussillon': '朗格多克-鲁西永', 'Nord-Pas-de-Calais': '北部-加来海峡',
  'Rhone-Alpes': '罗讷-阿尔卑斯',
  //    方位（法文版用得很多，不映射就会印出法语原文）
  'Central-France': '法国中部', 'Southern-France': '法国南部', 'Western-France': '法国西部',
  'Northern-France': '法国北部',
  //    法语区与海外
  Wallonia: '瓦隆', 'French-Switzerland': '瑞士法语区', Geneva: '日内瓦',
  Guyane: '法属圭亚那', Martinique: '马提尼克', Mayotte: '马约特',
  'French-Polynesia': '法属波利尼西亚', 'Newfoundland-fr': '纽芬兰', Joual: '茹阿尔语',
  //    非洲与其他法语国家
  Maghreb: '马格里布', Tunisia: '突尼斯', Madagascar: '马达加斯加',
  'Burkina-Faso': '布基纳法索', Mali: '马里', Benin: '贝宁', Togo: '多哥',
  Burundi: '布隆迪', 'Central-African-Republic': '中非', 'Congo-Brazzaville': '刚果（布）',
  'West-Africa': '西非', Lebanon: '黎巴嫩', Mauritius: '毛里求斯',
  //    更大的范围
  'North-America-fr': '北美', 'United-States': '美国', Missouri: '密苏里',
  'European-Union': '欧盟',
});

/** 法文版 tag → 语域/用法（`sense_tag.kind='register'`，中文查 `REGISTER_LABELS`） */
export const FR_TAG_REGISTER: Record<string, string> = {
  // 🔴 2026-08-28（收尾单 A4）：`Régional`/`Régionalisme` 原来在 REGION 桶里，
  //    渲染成「地区：地区性」—— 那不是一个地区，是**用法说明**。
  //    `REGISTER_LABELS` 里本来就有 regional→地区性 / dialectal→方言。
  Régional: 'regional', Régionalisme: 'regional',
  Anglicism: 'anglicism', 'Faux anglicisme': 'false-anglicism',
  'Extrêmement rare': 'extremely-rare', 'Très rare': 'very-rare',
  'Plus rare': 'rarer', 'Peu usité': 'seldom-used',
  'Plus courant': 'more-common', 'Moins courant': 'less-common', common: 'common',
  'Par plaisanterie': 'humorous', Proverbial: 'proverbial', Hapax: 'hapax',
  Affectueux: 'endearing', Mélioratif: 'meliorative', Archaïque: 'archaic',
  'very-familiar': 'very-familiar',
  broadly: 'broadly', especially: 'especially', specifically: 'specifically',
  literally: 'literally', metonymically: 'metonymically', analogy: 'by-analogy',
  hyperbole: 'hyperbole', euphemism: 'euphemistic', idiomatic: 'idiomatic',
  collectively: 'collectively', generically: 'generically', physical: 'physical',
  'orthographe rectifiée de 1990': 'spelling-1990',
  'orthographe d’avant 1835': 'spelling-pre1835',
  // —— 2026-08-27 第二轮补 ——
  'Par dérision': 'derisive', 'Usage critiqué': 'criticized-usage',
  Blasphématoire: 'blasphemous', Insulte: 'insult', Surnom: 'nickname',
  'Parfois péjoratif': 'sometimes-pejorative', Parfois: 'sometimes',
  Quelquefois: 'sometimes', 'Aujourd’hui': 'nowadays', Distinction: 'honorific',
  verlan: 'verlan', Latinisme: 'latinism', Germanisme: 'germanism',
  Hispanisme: 'hispanism', Italianisme: 'italianism', litotes: 'litotes',
  proverb: 'proverbial', generally: 'broadly',
  'orthographe traditionnelle': 'traditional-spelling', Acronyme: 'acronym',
  Rural: 'rural',   // 「乡村用语」是语域不是地区
};

/**
 * 🔴 **明确不出版**的法文版 tag。它们不是「标签」——
 *    印成义项旁边的胶囊，读者会以为那是词义的一部分。
 *
 *    · 结构标记：`alt-of`（12,753 行，全库最大的一个 tag）＝这条是指针义项，
 *      展示层已经有专门的「异体 →」那一行在做这件事。
 *    · 语法/配价：及物性、代动词、前置/后置、无冠词 —— 属于**词条头的徽标**，
 *      那边已经有 `transitivity`/`pronominal`/`adjPos` 三个字段在渲染。
 *      在义项旁边再印一遍是同一个信息印两次。
 *    · 编者元信息：`information à préciser ou à vérifier` 是维基的待办标记。
 *    · `Transitude` / `Variations diaéthiques` 是法文版自己的分类学术语，
 *      对查词的人没有意义。
 */
export const FR_TAG_SKIP: ReadonlySet<string> = new Set([
  'alt-of', 'toponymic-alt', 'ellipsis',
  'transitive', 'intransitive', 'pronominal', 'Transitude', 'Absolument',
  'Antéposé', 'Postposé', 'Au masculin', 'Sans article',
  'Abréviation', 'abbreviation', 'analytic',
  'information à préciser ou à vérifier', 'Variations diaéthiques',
  // 🔴 数与可数性也是**语法**不是标签 —— 词条头的 `plural` / `number_note`
  //    字段已经在渲染，义项旁边再印一个「复数」胶囊是同一个信息印两次。
  'uncountable', 'countable', 'plural', 'singular', 'plural-only', 'singular-only',
  'impersonal', 'collective', 'defective', 'invariable', 'masculine', 'feminine',
  // 🔴 2026-08-27 第二轮：长尾里剩下的语法/句法标记。
  //    `Transitif avec le complément d’objet introduit par de` 这种是**配价说明**，
  //    属于词条头的 `government` 字段（「动词固定介词支配」），不是义项标签。
  'conjugation', 'auxiliary', 'reflexive', 'Au féminin', 'Avec le', 'Avec de',
  'Transitif avec le complément d’objet introduit par de',
  'Transitif avec le complément d’objet introduit par à',
  'définition à préciser ou à vérifier', 'Par substantivation', 'Substantivement',
  'Souvent au pluriel', 'Surtout au pluriel',
]);

// 读音的**语境变体**标签（`pronunciation.context`，收尾单 A1，2026-08-27）。
// 🔴 不是转写风格（那是 `notation`：音位式/音值式），是这条读音在什么语境下成立。
//    目前只有连诵：`les` 单说是 /le/，在元音前才是 /le.z‿/。
export const FR_PRON_CONTEXT_LABELS: Record<string, string> = {
  liaison: '连诵',
};
