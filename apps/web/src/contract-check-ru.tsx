/**
 * **ru 展示层契约闸** —— 用真服务数据渲染 `RussianEntryView`，断言**读者看见什么**。2026-10-25（ru 阶段 9b）。
 *
 *     npm run gate:ru-display
 *     npm run gate:ru-display -- --mutate
 *
 * ═══ 为什么必须有它 ═══
 * vi 阶段 9：数据层十一道闸全绿，渲染出来当场逮到 8 个缺陷；ru 9a 第一次渲染就逮到三个
 * （同形异重音并组、指针目标带重音解析不到、高频词的俄/英义项没有中文）。
 * ⭐ 逮到它们的方式只有一个：**把数据渲染出来读**。这道闸把「读」变成断言。
 *
 * ⚠️ 它直接渲染视图、不走 `App.tsx` 的分发 —— 分发由 `dispatch-audit.ts` 守（vi 那一跤）。
 * ⚠️ 前端类型是手抄镜像；这里喂的是**服务真实返回的对象**，形状对不上会直接渲染错 ⇒ 这里就是对账。
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { getService } from '@synapse-dict/dict-core';
import { RussianEntryView } from './App';
import { POS_LABELS, REL_LABELS, RU_POS_LABELS, RU_RELATION_LABELS, RU_INFL_TAG_LABELS, RU_GRAMMAR_LABELS,
  RU_USAGE_LABELS, RU_USAGE_UNPRINTED, RU_FAMILY_POS_LABELS, RU_FAMILY_FORM_LABELS, RU_ASPECT_SUBKIND_LABELS,
  RU_ETYM_TYPE_LABELS, RU_EDITION_LABELS } from '@synapse-dict/dict-labels';

const svc = getService('ru') as unknown as { getEntry(w: string): any;
  db: { prepare(s: string): { all(...a: unknown[]): unknown[] } } };

/** C11：**全值域**标签覆盖。抽样页（L1–L10）只逮得到样本词碰巧用到的键 ——
 *  第一版跑出来只红了 `emphatic` 一个，而全值域一查是 59＋27＋51 个漏映射。
 *  ⚠️ 键是展示层**真的 SELECT 的那一列**（entry.pos／inflection.tags 拆开／sense_tag.value／关系的 kind/rel_group/form_group）。 */
function domainGaps(): string[] {
  const q = (sql: string) => (svc.db.prepare(sql).all() as Array<{ v: string }>).map((r) => r.v);
  const gaps: string[] = [];
  const need = (what: string, vals: string[], ok: (v: string) => boolean) => {
    const bad = vals.filter((v) => v != null && v !== '' && !ok(v));
    if (bad.length) gaps.push(`${what} ${bad.length} 个：${bad.slice(0, 8).join('、')}`);
  };
  need('词性', q('SELECT DISTINCT pos AS v FROM entry'), (v) => !!(RU_POS_LABELS[v] ?? POS_LABELS[v]));
  need('关系种类', q('SELECT DISTINCT kind AS v FROM sense_relation WHERE hidden = 0'), (v) => !!(RU_RELATION_LABELS[v] ?? REL_LABELS[v]));
  need('词族词性组', q('SELECT DISTINCT rel_group AS v FROM sense_relation WHERE rel_group IS NOT NULL'), (v) => !!RU_FAMILY_POS_LABELS[v]);
  need('词族构词组', [...new Set(q('SELECT DISTINCT form_group AS v FROM sense_relation WHERE form_group IS NOT NULL')
    .flatMap((v) => v.split('+')))], (v) => !!RU_FAMILY_FORM_LABELS[v]);
  need('体对 subkind', [...new Set(q('SELECT DISTINCT subkind AS v FROM sense_relation WHERE subkind IS NOT NULL')
    .flatMap((v) => v.split('+')))], (v) => !!RU_ASPECT_SUBKIND_LABELS[v]);
  const infl = new Set<string>();
  for (const v of q('SELECT DISTINCT tags AS v FROM inflection')) for (const t of (v ?? '').split('|')) infl.add(t);
  need('变位表标签', [...infl].filter((t) => !t.startsWith('src-')), (v) => !!RU_INFL_TAG_LABELS[v]);
  need('语法标签', q("SELECT DISTINCT value AS v FROM sense_tag WHERE bucket = 'grammar'"), (v) => !!RU_GRAMMAR_LABELS[v]);
  // 语体标签：要么映射、要么在冻结的「有意不印」名单里 —— 新值进来就红，不静默丢
  need('语体标签', q("SELECT DISTINCT value AS v FROM sense_tag WHERE bucket = 'label'"),
    (v) => !!RU_USAGE_LABELS[v] || RU_USAGE_UNPRINTED.has(v));
  need('词源类型', q('SELECT DISTINCT etym_type AS v FROM etymology WHERE etym_type IS NOT NULL'), (v) => !!RU_ETYM_TYPE_LABELS[v]);
  need('版名', q('SELECT DISTINCT src AS v FROM entry'), (v) => !!RU_EDITION_LABELS[v]);
  return gaps;
}
const MUTATE = process.argv.includes('--mutate');

function render(entry: unknown): string {
  return renderToStaticMarkup(createElement(RussianEntryView, {
    entry, speakLocale: 'ru-RU', onWord: () => {}, speak: () => {},
  } as never));
}
const vis = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/&quot;/g, '"').replace(/&#x27;/g, "'")
  .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/\s+/g, ' ');

/** 标签区（词性/标签/关系种类/词族分组/变位表头）里的文字 —— 这些地方**只许是中文**。 */
function labelSpans(html: string): string[] {
  const out: string[] = [];
  const re = /class="(ru-pos|ru-chip|ru-rel-kind|ru-family-pos|ru-infl-tag)"[^>]*>([^<]*)</g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(html))) out.push(m[2]);
  // 变位表的表头单元格
  const th = /<th>([^<]*)<\/th>/g;
  while ((m = th.exec(html))) out.push(m[1]);
  return out;
}

type Check = { id: string; word: string; name: string; hit: (t: string, e: any, html: string) => string | null };

const CHECKS: Check[] = [
  // ① 同形异重音：за́мок（城堡）／замо́к（锁）各成一组，各带各的读音
  { id: 'C1', word: 'замок', name: '同形异重音分组：城堡跟 за́мок、锁跟 замо́к',
    hit: (t) => {
      const a = t.indexOf('за́мок /ˈzamək/'); const b = t.indexOf('замо́к /zɐˈmok/');
      if (a < 0 || b < 0) return '两个重音组的「拼写＋读音」不是各自并排出现';
      const castle = t.indexOf('城堡', a);
      return castle > a && (b < a || castle < b) ? null : '「城堡」不在 за́мок 那一组里';
    } },
  // ② 词形页：指针印出来、目标可点
  { id: 'C2', word: 'воды', name: '词形页印出「是 вода 的属格单数」且目标可点',
    hit: (t, _e, h) => (t.includes('这个词形是') && /ru-pointer-go[^>]*>→ вода/.test(h) ? null : '没有可点的 → вода 指针') },
  // ③ 名词变格表：6×2，表头中文、格子里是带重音的形式
  { id: 'C3', word: 'вода', name: '名词变格表 6 格 × 单复数，带重音',
    // 🔴 只看**表里**：第一版查整页，`воды́` 在例句/指针里也有 ⇒ 清掉表里的重音变异照样绿（变异逮到的）
    hit: (_t, _e, h) => {
      const m = h.match(/<table class="ru-infl-table">([\s\S]*?)<\/table>/);
      if (!m) return '没有变格表';
      const tt = vis(m[1]);
      return ['主格', '属格', '与格', '宾格', '工具格', '前置格', '单数', '复数'].every((x) => tt.includes(x))
        && tt.includes('воды́') ? null : '变格表缺格名或表里没有带重音的形式';
    } },
  // ④ 体对印出来
  { id: 'C4', word: 'показать', name: '体的对应词 показывать 印出来',
    hit: (t) => (t.includes('体的对应词') && t.includes('пока́зывать') ? null : '看不到体的对应词') },
  // ⑤ 构词词族：标题＋词性分组
  { id: 'C5', word: 'полвека', name: '同根词按词性分组、带计数',
    // 🔴 只看词族的分组标题：第一版查整页的「形容词」，别处的标签也有 ⇒ 分组整个丢了照样绿（变异逮到的）
    hit: (t, _e, h) => (t.includes('同根词') && /class="ru-family-pos">形容词</.test(h) && t.includes('полувековой')
      ? null : '同根词区没按词性分组') },
  // ⑥ 模型中文必须标「机翻」（读者要分得出源头中文与买来的中文）
  { id: 'C6', word: 'вода', name: '模型译文标「机翻」',
    hit: (t) => (t.includes('机翻') ? null : '模型中文例句没有「机翻」标注') },
  // ⑦ 藏起来的东西一个都不许印
  { id: 'C7', word: 'тараса', name: '词源占位 `От ??` 不印',
    hit: (t) => (t.includes('??') ? '页面上出现了 ??' : null) },
  { id: 'C8', word: 'на-', name: '构词示意式（藏）不当例句印',
    hit: (t) => (t.includes('на- (na-) + идти́') ? '藏起来的构词示意式印出来了' : null) },
  { id: 'C9', word: 'день', name: '指针段「See the etymology of the corresponding lemma form」不印',
    hit: (t) => (t.includes('See the etymology of the corresponding lemma form') ? '指针段印出来了' : null) },
  // ⑧ 张冠李戴的录音不播（`нога ⇐ Ru-ноги.ogg` 是 hidden）
  { id: 'C10', word: 'нога', name: '张冠李戴的录音不出现',
    hit: (_t, _e, h) => (h.includes('Ru-%D0%BD%D0%BE%D0%B3%D0%B8') || h.includes('Ru-ноги') ? '录的是复数的那条录音出现在词元页上' : null) },
  // ⑨' R29：繁体版的源头中文印成简体（`text_pub`）；繁体原文一个字都不许出现在页面上
  { id: 'C12', word: 'товарищ', name: '繁体版释义印成简体（同學→同学）',
    hit: (t) => (t.includes('同學') ? '页面上印的是繁体原文「同學」' : t.includes('同学') ? null : '看不到「同学」') },
  { id: 'C13', word: 'книгу', name: '繁体版指针说明印成简体（賓格單數→宾格单数）',
    hit: (t) => (/賓格|單數/.test(t) ? '指针说明是繁体原文' : t.includes('宾格单数') ? null : '看不到「宾格单数」') },
  // ⑨'' R30：省写 ё 也找得到；只差 ё/е 的另一个词印出来、不合并
  // ⚠️ 样本不能用 `елка`：常用词的省写形源头多半收成了独立的异写条目（`елка`/`теплый` 都在库里），
  //    召回键只救「省写形不是任何词」的那 36,842 个 ⇒ 样本取其中一个（`чес` → `чёс`）
  { id: 'C14', word: 'чес', name: '省写 ё 找到 чёс 并说明',
    hit: (t, e) => (e.word === 'чёс' && t.includes('按 ё 的写法找到') ? null : `打开的是「${e.word}」或没有说明`) },
  { id: 'C15', word: 'все', name: '「все」页印出只差 ё 的 всё（另一个词，不合并）',
    hit: (t, e) => (e.word === 'все' && t.includes('ё/е 写法不同的词') && t.includes('всё') ? null : '看不到 всё') },
  // ⑨ 读者口径的标签覆盖：标签区一个英文键都不许漏出来（ko：映射表与展示层读不同列 ⇒ 徽标全空/漏键）
  ...['вода', 'замок', 'показать', 'полвека', 'все', 'Москва', 'идти', 'красный', 'быть', 'дом'].map((w, i) => ({
    id: `L${i + 1}`, word: w, name: `「${w}」标签区没有漏出英文键`,
    hit: (_t: string, _e: any, h: string) => {
      const bad = labelSpans(h).filter((x) => /[A-Za-z]{3,}/.test(x));
      return bad.length ? `漏键：${[...new Set(bad)].slice(0, 6).join('、')}` : null;
    },
  })),
];

/** C16（R30）：搜索下拉 —— 省写 ё 的前缀也要找得到带 ё 的词，逐字对上的排第一。 */
type SearchFn = (p: string, l: number) => Array<{ word: string }>;
function searchGaps(search: SearchFn): string[] {
  const out: string[] = [];
  if (!search('елк', 30).some((r) => r.word === 'ёлка')) out.push('搜「елк」没有 ёлка');
  if (search('всё', 5)[0]?.word !== 'всё') out.push(`搜「всё」第一条是 ${search('всё', 5)[0]?.word}`);
  if (search('все', 5)[0]?.word !== 'все') out.push(`搜「все」第一条是 ${search('все', 5)[0]?.word}`);
  return out;
}

function run(mutateEntry?: (w: string, e: any) => any): string[] {
  const red: string[] = [];
  const cache = new Map<string, any>();
  for (const c of CHECKS) {
    let e = cache.get(c.word);
    if (e === undefined) { e = svc.getEntry(c.word); cache.set(c.word, e); }
    if (!e) { red.push(`${c.id} 找不到词「${c.word}」`); continue; }
    const ee = mutateEntry ? mutateEntry(c.word, structuredClone(e)) : e;
    const html = render(ee);
    const why = c.hit(vis(html), ee, html);
    if (why) red.push(`${c.id} ${c.name}：${why}`);
  }
  return red;
}

if (!MUTATE) {
  const red = run();
  const gaps = domainGaps();
  console.log(`   ${gaps.length ? '🔴' : '✅'} C11  全值域标签覆盖（词性／关系／词族分组／变位表／语法／语体／词源类型／版名）`);
  for (const g of gaps) console.log(`      C11 ${g}`);
  if (gaps.length) red.push('C11');
  const sg = searchGaps((p, l) => svc.search(p, l));
  console.log(`   ${sg.length ? '🔴' : '✅'} C16  搜索：省写 ё 也找得到、逐字对上的排第一`);
  for (const g of sg) console.log(`      C16 ${g}`);
  if (sg.length) red.push('C16');
  console.log(`■ ru 展示层契约闸 —— ${CHECKS.length} 条`);
  for (const c of CHECKS) console.log(`   ${red.some((r) => r.startsWith(`${c.id} `)) ? '🔴' : '✅'} ${c.id.padEnd(4)} ${c.name}`);
  for (const r of red) console.log(`      ${r}`);
  console.log(red.length ? `■ ${red.length} 条红` : '■ 全绿 ✓');
  process.exit(red.length ? 1 : 0);
} else {
  // 变异：在**服务返回的对象**上注入缺陷（数据层的变异各层闸自己有），看对应那条红
  const MUTS: Array<[string, string, (w: string, e: any) => any]> = [
    ['C1', '并组回归：所有 entry 的重音清空', (_w, e) => { e.entries.forEach((x: any) => { x.stressed = null; x.stressVariants = []; }); return e; }],
    ['C2', '指针目标解析不到', (_w, e) => { e.pointers.forEach((p: any) => { p.targetId = null; }); return e; }],
    ['C3', '变格表丢了带重音的形式', (_w, e) => { e.inflections.forEach((r: any) => { r.stressed = null; }); return e; }],
    ['C4', '体对丢了', (_w, e) => { e.relations = e.relations.filter((r: any) => r.kind !== 'aspect_pair'); return e; }],
    ['C5', '词族分组丢了', (_w, e) => { e.relations.forEach((r: any) => { r.relGroup = null; }); return e; }],
    ['C6', '模型标记丢了', (_w, e) => { e.examples.forEach((x: any) => { if (x.zhSrc) x.zhSrc = 'zh-edition-trad'; });
      e.senses.forEach((s: any) => s.glosses.forEach((g: any) => { g.model = false; })); return e; }],
    ['C7', '占位回到词源', (w, e) => { if (w === 'тараса') e.etymologies.push({ entryId: e.entries[0].id, etymNo: 0, text: 'От ??', etymType: null, src: 'ru-edition' }); return e; }],
    ['C8', '构词示意式被放出来', (w, e) => { if (w === 'на-') e.examples.push({ senseId: null, entryId: e.entries[0].id, text: 'на- (na-) + идти́ (idtí, “to go”) → найти́', ref: null, zh: null, zhSrc: null, en: null, src: 'en-edition' }); return e; }],
    ['C9', '指针词源被放出来', (w, e) => { if (w === 'день') e.etymologies.push({ entryId: e.entries[0].id, etymNo: 0, text: 'See the etymology of the corresponding lemma form.', etymType: null, src: 'en-edition' }); return e; }],
    ['C10', '张冠李戴录音被放出来', (w, e) => { if (w === 'нога') e.audios.push({ entryId: null, url: 'https://upload.wikimedia.org/x/Ru-ноги.ogg', commonsKey: 'Ru-ноги.ogg', src: 'pl-edition' }); return e; }],
    ['C12', '释义回到繁体原文', (w, e) => { if (w === 'товарищ') e.senses.forEach((s: any) => s.glosses.forEach((g: any) => { g.text = g.text.replace('同学', '同學'); })); return e; }],
    ['C13', '指针说明回到繁体原文', (w, e) => { if (w === 'книгу') e.pointers.forEach((p: any) => { p.text = p.text.replace('宾格单数', '賓格單數'); }); return e; }],
    ['C14', 'ё 兜底丢了（说明不印）', (w, e) => { if (w === 'чес') e.foldedFrom = null; return e; }],
    ['C15', 'ё/е 异写丢了', (w, e) => { if (w === 'все') e.yoVariants = []; return e; }],
    ['L1', '一个词性键没有映射（漏到徽标上）', (w, e) => { if (w === 'вода') e.entries[0].pos = 'nonexistent_pos'; return e; }],
  ];
  let fails = 0;
  console.log(`■ ru 展示层契约闸 —— 变异 ${MUTS.length} 条（在服务返回的对象上注入）`);
  for (const [id, why, f] of MUTS) {
    const red = run(f).map((r) => r.split(' ')[0]);
    const ok = red.includes(id);
    if (!ok) fails += 1;
    console.log(`   ${ok ? '✅' : '🔴🔴 没逮到'} ${id.padEnd(4)} ${why}${ok && red.length > 1 ? `（连带 ${red.filter((x) => x !== id).join(',')}）` : ''}`);
  }
  // C16 的变异：搜索退回「只按 word_norm 前缀」（R30 之前的样子）—— 省写 ё 的那条必须红
  {
    const old: SearchFn = (p, l) => svc.search(p, 100).filter((r: any) => r.word.toLowerCase().replace(/[́̀]/g, '').startsWith(p)).slice(0, l);
    const ok = searchGaps(old).length > 0;
    if (!ok) fails += 1;
    console.log(`   ${ok ? '✅' : '🔴🔴 没逮到'} C16  搜索退回只按 word_norm 前缀`);
  }
  if (searchGaps((p, l) => svc.search(p, l)).length) { console.log('🔴🔴 反控制失败：C16 基线不绿'); process.exit(1); }
  const base = run();
  if (base.length) { console.log('🔴🔴 反控制失败：基线不绿'); process.exit(1); }
  console.log(fails ? `🔴 ${fails} 条没逮到` : '■ 变异全过 ✓，反控制：基线仍全绿');
  process.exit(fails ? 1 : 0);
}
