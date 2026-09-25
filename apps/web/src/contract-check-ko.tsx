/** 展示层契约闸（ko）。2026-09-25（阶段 9c）。
 *
 * ═══ 为什么数据层全绿之后还要这一道 ═══
 * `[[it-display-layer-stage8]]`：**接上展示层是独立一道闸。**
 * ko 这一轮它已经兑现了三次，全是数据闸报绿时逮到的：
 *   · `를` 的读音印出来是 `4mL\``（X-SAMPA 冒充 IPA，98 行）
 *   · `하다` 的罗马字印出来是 `Ko-hada.oga`（**录音文件名**）
 *   · 关系词 34.6% 点下去是空白页（`^팔도` / `경마(競馬)` 直接当词头去比对）
 * 三件事的共同点：**所有形式判据都满足**，只有内容是错的。
 *
 * ⇒ 本闸把 `KoreanEntryView` 用 `react-dom/server` 渲染成静态 HTML，
 *   断言全部盯**去标签之后的可见文字**，不盯 DOM 结构。
 *
 * 跑：npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-ko.tsx
 *     加 `--dump 한국 꽃` 把渲染结果打出来读（找缺陷用的，不是闸）
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { getService } from '@synapse-dict/dict-core';
import { KoreanEntryView } from './App';
import { EXAMPLES } from './App';
import { KO_RELATION_LABELS, KO_ANNOTATION_KINDS, POS_LABELS,
         KO_POS_LABELS, KO_CONJ_CLASS_LABELS } from '@synapse-dict/dict-labels';

const svc = getService('ko') as unknown as {
  getEntry(w: string): any;
  db: { prepare(s: string): { all(...a: unknown[]): unknown[] } };
};
const db = svc.db;

function render(entry: unknown): string {
  return renderToStaticMarkup(createElement(KoreanEntryView, {
    entry, speakLocale: 'ko-KR', onWord: () => {}, speak: () => {},
  } as never));
}

function visibleText(html: string): string {
  return html.replace(/<[^>]*>/g, ' ').replace(/&quot;/g, '"').replace(/&#x27;/g, "'")
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/\s+/g, ' ');
}

/** 只看**可见文字**，不看 `title=` 这种提示属性 —— 提示不是内容。 */
function bodyText(html: string): string {
  return visibleText(html.replace(/\stitle="[^"]*"/g, ''));
}

type Check = { word: string; name: string; hit: (t: string, e: any, html: string) => string | null };

const CHECKS: Check[] = [
  // ══ 韩语特有的字段，必须真的印到页面上 ══
  // 🔴 每一条都写成「这个词必须看得到 X」，不是「渲染没报错」——
  //    `[[it-display-layer-stage8]]`：兜底越体面，缺陷越难发现。
  { word: '한국', name: '修正罗马字（RR）印出来了',
    hit: (t) => (t.includes("han'guk") ? null : '看不到 RR 罗马字') },
  { word: '한국', name: '汉字表记印出来了',
    hit: (t) => (t.includes('韓國') ? null : '看不到汉字表记 韓國') },
  // ⭐ ko 独有的一层：发音形谚文。`읽다` 实际读作 `익따`。
  //    拉丁七门全无这一层，它比 IPA 对中文读者直观得多。
  { word: '읽다', name: '发音形谚文印出来了',
    hit: (t) => (t.includes('익따') ? null : '看不到发音形谚文 익따') },
  // 🔴 音标按 `notation` 加定界符：韩语 98.6% 是**窄式**，印 `/…/` 是错的。
  { word: '읽다', name: '窄式音标印成方括号',
    hit: (t) => (/\[\s*ik̚t͈a̠\s*\]/.test(t) ? null : '窄式音标没印成 [ ]') },
  { word: '아름답다', name: '活用类徽标印出来了',
    hit: (t) => (t.includes('ㅂ 不规则') ? null : '看不到活用类') },
  { word: '아름답다', name: '活用表印出来了并写明共多少个形式',
    hit: (t) => (/活用.*共 \d+ 个形式/.test(t) ? null : '活用区没写共多少个形式') },
  { word: '꽃', name: '关系类别用中文名（不是英文原码）',
    hit: (t) => (t.includes('配用量词') ? null : '看不到「配用量词」——counter 没映射') },
  { word: '사랑', name: '例句与译文印出来了',
    hit: (t) => (t.includes('사랑해') && t.includes('爱') ? null : '看不到例句或译文') },

  // ══ 🔴 这三条钉的是本轮真实逮到的缺陷，别让它们回来 ══
  { word: '하다', name: '罗马字不是音频文件名',
    hit: (t) => (/\.(oga|ogg|mp3)/.test(t) ? '罗马字位置印出了音频文件名' : null) },
  { word: '를', name: '读音里没有 X-SAMPA',
    hit: (t) => (/[0-9`\\]/.test(t.replace(/共 \d+ 个形式/g, '')) ? 'IPA 里出现了 ASCII 数字/反引号/反斜杠' : null) },
  { word: '한국', name: '关系目标不带 wiktextract 的 `^` 专名标记',
    hit: (t) => (t.includes('^') ? '页面上出现了 `^`' : null) },
];

/** 全量扫描：对每个抽样词渲染一遍，盯**跨词的结构性契约**。 */
function sweep(words: string[]) {
  let bad = 0;
  const seenKinds = new Set<string>();
  let deadLinks = 0; let links = 0; let annotationLinks = 0;
  let rawCode = 0;
  for (const w of words) {
    const e = svc.getEntry(w);
    if (!e) continue;
    const html = render(e);
    const t = bodyText(html);
    // ① 关系类别名一律是中文 —— 英文原码漏到页面上就是 `|| g.kind` 那个坑。
    // 🔴🔴 **判据只看 `rel-kind` 那一格，不看整页文字。** 第一版扫的是整页，
    //    当场报「原码漏出 14 处」—— 而那 14 处全在**英文释义里**
    //    （`a region ... related to ...`）。判据比它要描述的东西宽了一整个数量级，
    //    `[[criteria-narrower-than-you-think]]`：它说的是"类别徽标印了原码"，
    //    不是"页面上出现过这个英文单词"。
    const kindCells = [...html.matchAll(/<span class="rel-kind">([^<]*)<\/span>/g)]
      .map((m) => m[1]);
    for (const cell of kindCells) {
      if (/^[a-z_]+$/.test(cell)) {
        console.log(`   🔴 ${w} 的关系徽标印的是英文原码 \`${cell}\``);
        rawCode += 1;
      }
    }
    for (const g of [...e.relations, ...e.senses.flatMap((s: any) => s.relations)]) {
      seenKinds.add(g.kind);
      // ② 汉字注那一族不许是链接；其余的链接必须有 targetNorm
      for (const it of g.items) {
        if (KO_ANNOTATION_KINDS.has(g.kind)) {
          if (html.includes(`href="#${encodeURIComponent(it.target)}"`)) annotationLinks += 1;
        } else if (it.targetNorm) { links += 1; } else { deadLinks += 1; }
      }
    }
    // ③ 词性徽标不许印英文原码
    for (const en of e.entries) {
      if (!en.pos) continue;
      const label = KO_POS_LABELS[en.pos] ?? POS_LABELS[en.pos];
      if (label === undefined) {
        console.log(`   🔴 ${w} 的词性 \`${en.pos}\` 两张表都没有 —— 徽标会印原码`);
        bad += 1;
      }
    }
    // ④ 活用类徽标不许印韩语原词（表里没有就会落回原词）
    for (const en of e.entries) {
      if (en.conjClass && !KO_CONJ_CLASS_LABELS[en.conjClass]) {
        console.log(`   🔴 ${w} 的活用类 \`${en.conjClass}\` 不在表里`);
        bad += 1;
      }
    }
  }
  console.log(`   ${rawCode === 0 ? '✅' : '🔴'} 关系类别印的是中文名        原码漏出 ${rawCode} 处`);
  console.log(`   ${annotationLinks === 0 ? '✅' : '🔴'} 汉字表记印文本不印链接      被印成链接 ${annotationLinks} 条`);
  console.log(`   ℹ️  关系链接 ${links} 条可点、${deadLinks} 条源头引用了我们没收的词（K21，如实印成纯文本）`);
  console.log(`   ℹ️  本轮扫到 ${seenKinds.size} 种关系类别`);
  bad += rawCode + annotationLinks;
  return bad;
}

const argv = process.argv.slice(2);
if (argv[0] === '--dump') {
  for (const w of argv.slice(1)) {
    const e = svc.getEntry(w);
    if (!e) { console.log(`\n🔴 ${w} 查不到`); continue; }
    const html = render(e);
    console.log(`\n${'='.repeat(70)}\n${w}   (${html.length} 字节 HTML)\n${'='.repeat(70)}`);
    console.log(html
      .replace(/<\/(div|li|section|details|summary|h3|h2|p|ul|ol|article)>/g, '\n')
      .replace(/<[^>]*>/g, ' ')
      .replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&amp;/g, '&')
      .split('\n').map((l) => l.replace(/\s+/g, ' ').trim()).filter(Boolean).join('\n'));
  }
  process.exit(0);
}

console.log('\n═══ ko 展示层契约闸 ═══');
let red = 0;
for (const c of CHECKS) {
  const e = svc.getEntry(c.word);
  if (!e) { console.log(`   🔴 ${c.word.padEnd(6)} ${c.name} —— 这个词查不到`); red += 1; continue; }
  const html = render(e);
  const why = c.hit(bodyText(html), e, html);
  if (why) { console.log(`   🔴 ${c.word.padEnd(6)} ${c.name.padEnd(28)} ${why}`); red += 1; }
  else console.log(`   ✅ ${c.word.padEnd(6)} ${c.name}`);
}

console.log('\n═══ 结构性契约（扫欢迎页推荐词 ＋ 一批高频词）═══');
// 🔴 抽样不能只用推荐词 —— 那是我挑出来"好看"的，天然偏向没问题的页面
//    （`[[verification-gates-not-sampling]]`）。补一批**按关系数排前列**的词，
//    它们是版面压力最大的那一端。
const heavy = (db.prepare(
  'SELECT d.word FROM sense_relation r JOIN dict d ON d.id = r.word_id'
  + ' GROUP BY r.word_id ORDER BY COUNT(*) DESC LIMIT 40').all() as { word: string }[])
  .map((r) => r.word);
red += sweep([...(EXAMPLES.ko ?? []), ...heavy]);

if (red) { console.log(`\n🔴 ko 展示层契约闸：${red} 条红`); process.exit(1); }
console.log('\n■ ko 展示层契约闸全绿 ✓');
