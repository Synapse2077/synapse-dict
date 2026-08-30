// 葡萄牙语专属展示映射。

export const PT_VCONJ_LABELS: Record<string, string> = {
  '1': '第一变位 -ar', '2': '第二变位 -er', '3': '第三变位 -ir', por: 'pôr 类',
};

// 葡语地区标签（葡语专属，不复用其它语种地区表）。映射不到回退原文。
export const PT_REGION_LABELS: Record<string, string> = {
  Brazil: '巴西', Portugal: '葡萄牙', Brazilian: '巴西', European: '欧洲葡语',
  'Southern-Brazil': '巴西南部', 'South-Brazil': '巴西南部', 'North-Brazil': '巴西北部',
  'Rio-de-Janeiro': '里约', 'São-Paulo': '圣保罗', Caipira: '内陆方言',
  Bahia: '巴伊亚', 'Minas-Gerais': '米纳斯', Paraná: '巴拉那',
  'Northeastern-Brazil': '巴西东北', Lisbon: '里斯本', Porto: '波尔图',
  Angola: '安哥拉', Mozambique: '莫桑比克', Macau: '澳门', 'Cape-Verde': '佛得角',
  'East-Timor': '东帝汶', Galicia: '加利西亚', Azores: '亚速尔', Madeira: '马德拉',
  Northern: '北部', Southern: '南部', Central: '中部', regional: '地区性',
  dialectal: '方言', 'Old-Portuguese': '古葡语',
};

// 葡语冠词（逐义项性别用）：o 阳 / a 阴。
export const PT_ARTICLE: Record<string, string> = { m: 'o', f: 'a', mf: 'o/a' };

// ══════ 变形标签的语法成分表 —— **葡语的语法词汇只许有一份** ══════
// 住在 dict-labels 而不是 dict-core：`App.tsx` 也要用它挑标题，而 dict-core 依赖
// `node:sqlite`、浏览器端引不了（`[[dict-labels-package]]`：展示层映射表唯一的家）。
// 两处用它：① 服务层给变形标签去重（A 的成分是 B 的子集 ⇒ A 更泛，丢）
//          ② 展示层挑区块标题（有没有动词专属成分）
// 🔴 **选择支按长度降序生成** —— `[[regex-alternation-order]]` 记过三次：
//    正则选择支是**从左到右 first-match，不是最长匹配**，短的排前面就挡住长的
//    （`分词` 排在 `过去分词` 前会把 `过去分词阴性单数` 切成 `分词`+…）⇒ 不手写顺序，由代码排。
export const PT_VERB_PARTS = ['陈述式', '虚拟式', '命令式', '条件式', '现在时', '简单过去时',
  '未完成过去时', '过去完成时', '将来时', '人称不定式', '不定式', '过去分词', '分词',
  '副动词', '第一', '第二', '第三', '人称', '否定'];
// 名词/形容词也有的成分：数与性。只剩这些 ⇒ 这不是「变位」。
export const PT_NOMINAL_PARTS = ['单数', '复数', '阴性', '阳性'];
const PT_PART_WORDS = [...PT_VERB_PARTS, ...PT_NOMINAL_PARTS].sort((a, b) => b.length - a.length);
const PT_PARTS = new RegExp(`(${PT_PART_WORDS.join('|')})`, 'g');
// ⚠️ 葡语的 `particípio` **就是**过去分词 —— 两个标签指同一个范畴，归一后才比得了。
const PT_PART_NORM: Record<string, string> = { '过去分词': '分词' };
export const ptPartsOf = (l: string | null): Set<string> =>
  new Set((l ? l.match(PT_PARTS) ?? [] : []).map((x) => PT_PART_NORM[x] ?? x));

// 🔴 判据按**含义**：「变位」只用来说动词。名词复数（`gamão → gamões`）和
//    形容词阴性（`acérrimo → acérrima`）顶着「变位形式」的标题是错的（外审两家四版都点了）。
const PT_VERB_SET = new Set(PT_VERB_PARTS.map((x) => PT_PART_NORM[x] ?? x));
export function ptInflHeading(labels: (string | null)[]): string {
  return labels.some((l) => [...ptPartsOf(l)].some((p) => PT_VERB_SET.has(p)))
    ? '变位形式' : '词形变化';
}
