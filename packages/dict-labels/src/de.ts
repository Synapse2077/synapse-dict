// 德语专属展示映射。

export const DE_ARTICLE: Record<string, string> = { m: 'der', f: 'die', n: 'das', mf: 'der/die' };

export const DE_AUX_LABELS: Record<string, string> = {
  haben: '完成时·haben', sein: '完成时·sein', both: '完成时·haben/sein',
};

export const DE_VCLASS_BASE: Record<string, string> = {
  weak: '弱变化', strong: '强变化', mixed: '混合变化', irregular: '不规则',
};

// 德语地区标签（德语专属）。映射不到回退原文。
export const DE_REGION_LABELS: Record<string, string> = {
  Germany: '德国', Austria: '奥地利', Switzerland: '瑞士', 'South-Tyrol': '南蒂罗尔',
  Bavaria: '巴伐利亚', Berlin: '柏林', Saxony: '萨克森', Swabia: '施瓦本',
  'Low-German': '低地德语', 'High-German': '高地德语', 'Middle-High-German': '中古高地德语',
  'Old-High-German': '古高地德语', Austrian: '奥地利', Swiss: '瑞士', German: '德国',
  Viennese: '维也纳', 'Northern-German': '北德', 'Southern-German': '南德',
  regional: '地区性', dialectal: '方言', Yiddish: '意第绪语', GDR: '东德', DDR: '东德',
};
