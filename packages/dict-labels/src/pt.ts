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
