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
  // ── 🔴 `pronunciation.region` / `audio.region` 的取值（收尾单 C31）──────────
  //    上面那批是 `sense_tag` 的取值（源头 tag 原样），下面这 6 个来自读音与录音两张表。
  //    ⚠️ **两张表用了两套代码**：录音是 `de-AT`/`de-CH`（BCP-47 风格），
  //    读音是 `at`/`ch`/`de-north`/`de`（kaikki 原样）。
  //    这里把它们**都译成中文**是标签表的本职（不译＝给读者看原始代码）；
  //    但**「两套代码并存」这个缺陷不靠这张表遮盖** —— 回归闸有一条断言专门盯它
  //    （`[[aim-for-perfect-not-cheap]]`：别用展示层补丁代替把事情做进数据里）。
  at: '奥地利', ch: '瑞士', de: '德国',
  'de-AT': '奥地利', 'de-CH': '瑞士', 'de-north': '北德',
  // ── 🔴 2026-09-15：对着 `de/pipeline/build.py` 的 `REGIONS` 集合补全 ──────────
  //    六门标签覆盖率量下来，de 的 region 是最差的一门（79.6%，50 种裸英文 1,134 条）：
  //    `Southern-Germany`(360)、`Northern-Germany`(219) 这种高频值就这么印在页面上。
  //    上面那批是当初照「库里出现量前 N 名」写的 —— 又是
  //    `[[criteria-narrower-than-you-think]]`：**照集合写才有上界，照出现量写永远有尾巴**。
  // ⚠️ 源头对同一个地方有多种写法（`Southern-Germany`/`southern-Germany`/`southern`），
  //    全部收敛到同一个中文，靠调用方按**映射后的文字**去重。
  // 德国境内
  'Southern-Germany': '德国南部', 'southern-Germany': '德国南部',
  'Northern-Germany': '德国北部', 'West-Germany': '西德', 'East-Germany': '东德',
  Rhineland: '莱茵兰', Westphalia: '威斯特法伦', Ruhrgebiet: '鲁尔区',
  Ruhr: '鲁尔区', Ruhrdeutsch: '鲁尔方言', 'Münsterland': '明斯特兰',
  Hesse: '黑森', Palatinate: '普法尔茨', Palatine: '普法尔茨',
  Franconia: '弗兰肯', Cologne: '科隆', Hamburg: '汉堡',
  'Schleswig-Holstein': '石勒苏益格-荷尔斯泰因', 'Berlin-Brandenburg': '柏林-勃兰登堡',
  Berlinisch: '柏林方言', Swabian: '施瓦本', Saxon: '萨克森', Silesia: '西里西亚',
  Bavarian: '巴伐利亚',
  // 奥地利 / 瑞士 / 其余德语区
  Vienna: '维也纳', Tyrol: '蒂罗尔', Carinthia: '克恩顿', Styria: '施蒂利亚',
  Vorarlberg: '福拉尔贝格', Basel: '巴塞尔',
  Liechtenstein: '列支敦士登', Luxembourg: '卢森堡', Belgium: '比利时',
  Alsace: '阿尔萨斯', Alsatian: '阿尔萨斯', Bohemia: '波希米亚', Moravia: '摩拉维亚',
  // 方言分区（语言学意义上的，不是行政区）
  Alemannic: '阿勒曼尼', 'Upper-German': '上德语', 'Central-German': '中德语',
  'Northwest-German': '西北德语', 'Middle-West-German': '中西部德语',
  'Eastern-German': '东德语区', 'Western-German': '西德语区',
  // 德语之外的世界
  Namibia: '纳米比亚', 'South-Africa': '南非', Africa: '非洲', Egyptian: '埃及',
  Europe: '欧洲', European: '欧洲', Russia: '俄罗斯', Iran: '伊朗',
  Ireland: '爱尔兰', UK: '英国', US: '美国', Texas: '得克萨斯',
  Pennsylvania: '宾夕法尼亚', Australia: '澳大利亚', 'New-Zealand': '新西兰',
  Grenadian: '格林纳达',
  // 泛指方位（源头就这么泛，照实印；大小写两版同义）
  North: '北部', South: '南部', East: '东部', West: '西部',
  Northern: '北部', Southern: '南部', Eastern: '东部', Western: '西部',
  Central: '中部', northern: '北部', southern: '南部', eastern: '东部',
  western: '西部', central: '中部',
  Northeastern: '东北部', Northwestern: '西北部',
  Southeastern: '东南部', Southwestern: '西南部',
};
