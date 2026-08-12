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

// 法语冠词（逐义项性别用）：le 阳 / la 阴。
export const FR_ARTICLE: Record<string, string> = { m: 'le', f: 'la', mf: 'le/la' };
