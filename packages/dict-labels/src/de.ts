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
};
