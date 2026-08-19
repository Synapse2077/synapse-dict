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

// ============================================================================
// 真人录音的地区标注（`audio.region`）
//
// 🔴 这些值**是法语**：意语录音的绝大多数来自法语版 wiktionary（A13 那条同源），
//    它把录音人的所在地写成 `Monopoli (Italie)` / `(Italie) : Milan` / `Milan, Italie`。
//    25 种取值里有 12 种只是同一个地方的**不同标点写法** ——
//    枚举 25 条会把标点变体也固化成数据，源头再换一种写法就又漏一个。
//    ⇒ 只维护「地名 → 中文」，写法差异交给 `itAudioRegion()` 扫词。
//
// ⚠️ 放在 dict-labels 而不是 App.tsx：划词弹窗要显示录音来源时会用同一份
//    （`refactor-mindset-code-quality` 那次批评的正是「先塞进 App.tsx 再说」）。
// ============================================================================
export const IT_AUDIO_PLACE_LABELS: Record<string, string> = {
  Monopoli: '莫诺波利', Milan: '米兰', Naples: '那不勒斯', Rome: '罗马',
  Turin: '都灵', Venise: '威尼斯', Florence: '佛罗伦萨', Bologne: '博洛尼亚',
  Sicile: '西西里', Sardaigne: '撒丁岛', Toscane: '托斯卡纳', Ombrie: '翁布里亚',
  'Vénétie': '威尼托', Lombardie: '伦巴第', Piémont: '皮埃蒙特', Marches: '马尔凯',
  Calabre: '卡拉布里亚', Campanie: '坎帕尼亚', Pouilles: '普利亚', Latium: '拉齐奥',
  Ligurie: '利古里亚', Abruzzes: '阿布鲁佐', 'Busto Arsizio': '布斯托阿西齐奥',
};

/**
 * 录音地区原值 → 中文。**扫词而不是查表**，见 `IT_AUDIO_PLACE_LABELS` 上方的理由。
 *
 * 规则三条，按优先级：
 *   ① 认出具体地名 → 「意大利·米兰」
 *   ② 只认出国名（`Italie` / `italien` / `in italiano`）→ 「意大利」
 *   ③ 一个都认不出 → **原样回退**，绝不吞掉（吞掉就等于悄悄丢信息）
 *
 * `Italie (région ?)` 里的 `région ?` 是法语版自己的存疑标记，不是地名 ⇒ 落到 ②。
 */
export function itAudioRegion(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const s = raw.trim();
  if (!s) return null;
  for (const [fr, zh] of Object.entries(IT_AUDIO_PLACE_LABELS)) {
    if (s.includes(fr)) return `意大利·${zh}`;
  }
  if (/itali/i.test(s)) return '意大利';
  return s;
}
