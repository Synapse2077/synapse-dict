// 西班牙语专属展示映射。

// 地区标签 → 中文（对应 build.py REGIONS）。映射不到回退原文。
//
// 🔴 2026-08-12 合并：`App.tsx` 里原本有**两张**西语地区表 —— 义项胶囊用
//    `REGION_LABELS`(71 项)、录音地区用 `REGION_ZH`(10 项)。后者 9 项与前者完全重复，
//    第 10 项 `'Costa Rica'`（空格）只是 `'Costa-Rica'`（连字符）的另一种拼写。
//    译文当时尚未分叉纯属运气 —— 这正是把映射表抽成独立包的直接起因。
//    ⇒ 合并为一张，两种拼写都保留成键。
export const ES_REGION_LABELS: Record<string, string> = {
  'Costa Rica': '哥斯达黎加',   // ← 原 REGION_ZH 的空格拼写，录音表用的是这一版
  Spain: '西班牙', 'Canary-Islands': '加那利群岛', Andalusia: '安达卢西亚',
  'Latin-America': '拉美', Mexico: '墨西哥', Chile: '智利', Colombia: '哥伦比亚',
  Peru: '秘鲁', Venezuela: '委内瑞拉', Cuba: '古巴', Bolivia: '玻利维亚',
  Ecuador: '厄瓜多尔', Guatemala: '危地马拉', Honduras: '洪都拉斯', Nicaragua: '尼加拉瓜',
  'Costa-Rica': '哥斯达黎加', Paraguay: '巴拉圭', Uruguay: '乌拉圭',
  'Dominican-Republic': '多米尼加', 'Puerto-Rico': '波多黎各', Caribbean: '加勒比',
  Rioplatense: '拉普拉塔河地区', Argentina: '阿根廷', Panama: '巴拿马',
  'El-Salvador': '萨尔瓦多', 'Central-America': '中美洲', 'South-America': '南美洲',
  'North-America': '北美洲', Philippines: '菲律宾', US: '美国', UK: '英国',
  Canada: '加拿大', Australia: '澳大利亚', Louisiana: '路易斯安那', Texas: '得州',
  California: '加州', 'New-York-City': '纽约市', Aragon: '阿拉贡', Asturias: '阿斯图里亚斯',
  Galicia: '加利西亚', Navarre: '纳瓦拉', Tenerife: '特内里费', Seville: '塞维利亚',
  Valencia: '巴伦西亚', Catalonia: '加泰罗尼亚', Mallorca: '马略卡', Belize: '伯利兹',
  Antilles: '安的列斯', Guerrero: '格雷罗', Puebla: '普埃布拉', Bogota: '波哥大',
  Manila: '马尼拉', Llanos: '亚诺斯平原', Morocco: '摩洛哥', Angola: '安哥拉',
  'Equatorial-Guinea': '赤道几内亚', Iberian: '伊比利亚', European: '欧洲',
  'European-Union': '欧盟', EU: '欧盟', Lunfardo: '隆法多黑话', 'Southern-Spain': '西班牙南部',
  Northern: '北部', Southern: '南部', Eastern: '东部', Western: '西部',
  Northeastern: '东北部', Northwestern: '西北部', Southeastern: '东南部',
  Southwestern: '西南部', Central: '中部',
};

// 西语定冠词（按性别；共性 mf 两冠词）
export const ES_ARTICLE: Record<string, string> = { m: 'el', f: 'la', mf: 'el/la', n: 'lo' };

// 西语三变位类
export const ES_CONJ_LABELS: Record<string, string> = {
  '1': '第一变位 -ar', '2': '第二变位 -er', '3': '第三变位 -ir',
};
