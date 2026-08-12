// 意大利语专属展示映射。

export const IT_AUX_LABELS: Record<string, string> = {
  avere: '助动词 avere', essere: '助动词 essere', both: '助动词 avere/essere',
};

export const IT_CONJ_LABELS: Record<string, string> = {
  '1': '第一变位 -are', '2': '第二变位 -ere', '3': '第三变位 -ire', '3isc': '第三变位 -ire (-isc-)',
};

export const IT_NUMBER_NOTE_LABELS: Record<string, string> = {
  invariable: '单复同形', 'plural-only': '仅复数', 'singular-only': '仅单数',
  uncountable: '不可数', collective: '集合名词',
};

// 意语地区标签（意语专属，不复用西语 REGION_LABELS）。映射不到回退原文。
export const IT_REGION_LABELS: Record<string, string> = {
  Italy: '意大利', Tuscany: '托斯卡纳', Switzerland: '瑞士意语区', Sardinia: '撒丁岛',
  Sicily: '西西里', Naples: '那不勒斯', Rome: '罗马', Florence: '佛罗伦萨', Milan: '米兰',
  Venice: '威尼斯', Turin: '都灵', Genoa: '热那亚', Bologna: '博洛尼亚', Lombardy: '伦巴第',
  Piedmont: '皮埃蒙特', Veneto: '威尼托', Campania: '坎帕尼亚', Calabria: '卡拉布里亚',
  Apulia: '普利亚', Abruzzo: '阿布鲁佐', Lazio: '拉齐奥', Liguria: '利古里亚',
  Umbria: '翁布里亚', Marche: '马尔凯', Molise: '莫利塞', Basilicata: '巴西利卡塔',
  Friuli: '弗留利', Trentino: '特伦蒂诺', 'Northern-Italy': '意大利北部',
  'Southern-Italy': '意大利南部', 'Central-Italy': '意大利中部', Northern: '北部',
  Southern: '南部', Eastern: '东部', Western: '西部', Central: '中部',
  regional: '地区性', dialectal: '方言', 'Ancient-Rome': '古罗马', Roman: '罗马',
};

export const IT_ARTICLE: Record<string, string> = { m: 'il', f: 'la', mf: 'il/la' };
