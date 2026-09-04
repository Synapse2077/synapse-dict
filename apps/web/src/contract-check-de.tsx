/**
 * 德语展示层契约闸：把真实数据喂进 React 组件、渲染成 HTML，再断言。2026-09-04（阶段 8）。
 *
 * ═══ 为什么数据层的回归闸不够 ═══
 * `de/tests/test_no_regression.py` 的 L 组守的是「`german.ts` 里有没有 `FROM sense`」——
 * 那只能证明**代码里写了**，证明不了**渲染出来有**。这两件事差着一个组件。
 *
 * 已知四个真实案例，全是「库里全对、接口全对、页面上没有」：
 *   · it `TVTB` 有两条义项却整块不渲染 —— 组件里一个 `entry.isLemma &&` 挡住 8,552 个词形；
 *   · it 意语原文导了 89,531 条、接口一直在返回，**组件那一行漏了写**，用户问了才发现；
 *   · fr 库里 39 万条录音 URL，而 `french.ts` 里 `FROM audio` 出现 **0 次**；
 *   · pt 契约闸建出来第一次跑就逮到 `entry.isLemma &&` 挡住 6,520 个词形。
 *
 * 🔴🔴 **de 是这四个里最严重的**：同一个 `entry.isLemma &&` 挡住 **124,291 个词形**
 *      （pt 的 19 倍）——`'Ndrangheta` 恩德朗盖塔、`'n Abend` 晚上好都有中文，
 *      页面上一个字不显示。2026-09-04 接线时读代码发现并修掉；
 *      **本闸存在的意义是「下次没人会再读一遍」**。
 *
 * ⇒ 本闸的每一条都断言 **HTML 里有没有**，不是数据库里有没有。
 *
 * ═══ de 独有、别的语种的闸够不到的三条 ═══
 *   ① **释义不许被 `is_lemma` 挡住** —— 124,291 个有义项的词形 `is_lemma=0`。
 *      `is_lemma` 是我们自己打的标，拿它决定"要不要显示释义"就是
 *      `[[llm-as-evaluator-discipline]]` ⑫「用自己的分类限制自己的输出」。
 *   ② **构词必须与变形分区** —— `kind='derivation'` 7,156 行（收尾单 C13，外审两家一致）：
 *      `Häuslein ← Haus 指小词` 混进变形区，读者会以为它是格形式。
 *   ③ **`alt_of` 只许出现在义项里** —— de 的 8,917 条全部挂在义项上（词条级 0 条）。
 *      pt 那轮把义项级的话按词条级渲染，在 `banco`（银行）页顶印出「异体 → banco de dados」，
 *      **那句话本身是错的**。
 *
 * ═══ 用法（仓库根目录）═══
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-de.tsx
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-de.tsx --limit 400
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-de.tsx --mutate
 *
 * ⚠️ `--tsconfig` 不能省：仓库根目录没有 tsconfig.json，tsx 找不到 jsx: "react-jsx"。
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { getService } from '@synapse-dict/dict-core';
import { GermanEntryView } from './App';

const svc = getService('de') as unknown as {
  getEntry(w: string): unknown;
  db: { prepare(s: string): { all(...a: unknown[]): unknown[] } };
};
const db = svc.db;
type Entry = Record<string, any>;
type Check = { name: string; hit: (e: Entry, html: string) => string | null };

function render(entry: Entry): string {
  return renderToStaticMarkup(createElement(GermanEntryView, {
    entry: entry as never, speakLocale: 'de-DE', onWord: () => {}, speak: () => {},
  } as never));
}

// 🔴 比对两边必须**同样归一**，否则断言在报自己的 bug（pt 那轮踩过：
//    例句中文里的 `&` 在 HTML 里是 `&amp;`、换行被压成空格 ⇒ `includes(原文)` 必然找不到）。
const norm = (x: string) => x
  .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
  .replace(/&quot;/g, '"').replace(/&#x27;|&#39;/g, "'")
  .replace(/\s+/g, ' ').trim();
const text = (h: string) => norm(h.replace(/<[^>]*>/g, ' '));
const count = (h: string, re: RegExp) => (h.match(re) ?? []).length;

const CHECKS: Check[] = [
  {
    name: '🔴 ① 有义项却整块释义不渲染（`is_lemma` 挡住 124,291 个词形那个形状）',
    hit: (e, h) => (e.senses.length > 0 && !/class="sense-zh"/.test(h))
      ? `${e.senses.length} 条义项，HTML 里一条 .sense-zh 都没有` : null,
  },
  {
    // ⭐ 上一条只问「有没有」，这一条问「**几条就该有几条**」——
    //    少一条（被某个 filter 悄悄吃掉）也红。
    name: '🔴 中文释义条数与渲染出来的对不上',
    hit: (e, h) => {
      const want = e.senses.filter((s: Entry) => s.zh).length;
      const got = count(h, /class="sense-zh"/g);
      return want > 0 && got < want ? `有中文的义项 ${want}，渲染 ${got}` : null;
    },
  },
  {
    name: '🔴 德语原文释义没渲染（it 漏了 89,531 条那个形状）',
    hit: (e, h) => {
      const want = e.senses.filter((s: Entry) => s.de).length;
      const got = count(h, /class="sense-src-de"/g);
      return want > 0 && got < want ? `有德语原文的义项 ${want}，渲染 ${got}` : null;
    },
  },
  {
    name: '🔴 音标没渲染',
    hit: (e, h) => (e.readings.length > 0 && !text(h).includes(e.readings[0].ipa))
      ? `主读音 /${e.readings[0].ipa}/ 不在页面上` : null,
  },
  {
    name: '🔴 多读音只渲染了一个（读者看不到另一读）',
    hit: (e, h) => {
      const uniq = [...new Set(e.readings.map((r: Entry) => r.ipa))] as string[];
      if (uniq.length < 2) return null;
      const t = text(h);
      const miss = uniq.slice(0, 4).filter((x) => !t.includes(x));
      return miss.length ? `${uniq.length} 个不同读音，页面上缺 ${miss.join(' / ')}` : null;
    },
  },
  {
    // ⚠️ 期望值走**服务层已经限过量的那份**（`entry.audio` 已 LIMIT 8），
    //    不在这里重算一套限量规则 —— pt 那轮就是因为闸自己算了一份，
    //    展示层加「每地区最多 2 条」后当场报 4 条假红。
    name: '🔴 录音没渲染 / 数量对不上（fr 那次 39 万条一个用户看不见）',
    hit: (e, h) => {
      const want = e.audio.length;
      const got = count(h, /class="audio-btn"/g);
      return want > 0 && got !== want ? `${want} 条录音，页面上 ${got} 个播放按钮` : null;
    },
  },
  {
    name: '🔴 例句没渲染',
    hit: (e, h) => (e.examples.length > 0 && !/class="example-item"/.test(h))
      ? `${e.examples.length} 条例句，HTML 里一条都没有` : null,
  },
  {
    // 布局规矩：最多渲染 12 条。断言只问**这些该显示的**里有中文的那几条。
    name: '🔴 例句有中文却没渲染出来',
    hit: (e, h) => {
      const t = text(h);
      const shown = e.examples.slice(0, 12) as Entry[];
      const miss = shown.filter((x) => x.zh && !t.includes(norm(x.zh).slice(0, 20)));
      return miss.length
        ? `该显示的 ${shown.length} 条里，有中文却没出现在页面上的 ${miss.length}（如「${miss[0].zh.slice(0, 18)}」）`
        : null;
    },
  },
  {
    name: '🔴 ② 构词混进了变形区（收尾单 C13，读者会当成格形式）',
    hit: (e, h) => {
      if (e.derivations.length === 0) return null;
      // 变形区是 `.infl-notes`，构词区是 `.de-infl-list`。构词的词头**不许**出现在变形区里。
      const m = h.match(/<ul class="infl-notes">[\s\S]*?<\/ul>/);
      if (!m) return null;
      const inInfl = text(m[0]);
      const leak = (e.derivations as Entry[]).filter((d) => inInfl.includes(d.base));
      return leak.length ? `${leak.length} 条构词漏进了变形区（如 ${leak[0].base}）` : null;
    },
  },
  {
    name: '🔴 ② 有构词却没有构词区',
    hit: (e, h) => (e.derivations.length > 0 && !/class="de-infl-list"/.test(h))
      ? `${e.derivations.length} 条构词，HTML 里没有 .de-infl-list` : null,
  },
  {
    name: '🔴 ③ 义项级异体没渲染',
    hit: (e, h) => {
      const want = (e.senses as Entry[]).filter((s) => (s.altOf ?? []).length > 0).length;
      const got = count(h, /class="sense-altof"/g);
      return want > 0 && got < want ? `有异体的义项 ${want}，渲染 ${got}` : null;
    },
  },
  {
    // 🔴 de 的 alt_of **全部挂在义项上**（词条级 0 条）。词条级关系区里若冒出 alt_of，
    //    就是把义项级的话升级成了词条级断言 —— pt 那轮在 `banco` 页顶印出错话的形状。
    name: '🔴 ③ `alt_of` 冒到了词条级关系区（pt banco 那个形状）',
    hit: (e, h) => {
      const m = h.match(/<div class="rel-row">[\s\S]*?<\/div>/g) ?? [];
      const bad = m.filter((x) => /异体|alt_of/.test(x));
      return bad.length ? `词条级关系区里出现了异体（${bad.length} 处）` : null;
    },
  },
  {
    name: '🔴 语义关系没渲染',
    hit: (e, h) => (e.relations.length > 0 && !/class="rel-row"/.test(h))
      ? `${e.relations.length} 组词条级关系，HTML 里没有 .rel-row` : null,
  },
  {
    name: '🔴 词形变化没渲染',
    hit: (e, h) => (e.forms.length > 0 && !/class="de-form-grid"/.test(h))
      ? `${e.forms.length} 个形式，HTML 里没有 .de-form-grid` : null,
  },
  {
    name: '🔴 隐藏的例句漏到了页面上',
    hit: (e, h) => {
      const t = text(h);
      const rows = db.prepare(
        `SELECT text FROM example WHERE word = ? AND hidden = 1 LIMIT 20`).all(e.word) as
        Array<{ text: string }>;
      const leak = rows.filter((r) => t.includes(norm(r.text).slice(0, 30)));
      return leak.length ? `${leak.length} 条 hidden=1 的例句出现在页面上` : null;
    },
  },
];

// ── 取样：**按形状取，不是随机抽** ──
// 随机抽 300 个词，抽到的绝大多数是没有义项的变形 —— 那样闸里大半条断言从不触发，
// 「全部通过」就成了假绿。⇒ 每一类形状各取一批，保证每条断言都有活可干。
// ⚠️ SQLite 的 `UNION ALL` 分支里不许带 LIMIT，每支要包一层子查询 —— 这里索性各查各的。
const LIMIT = Number(process.argv[process.argv.indexOf('--limit') + 1]) || 320;
const PER = Math.ceil(LIMIT / 8);
const arms: Array<[string, string]> = [
  // 🔴 第一支就是 124,291 那批：**有义项但 `is_lemma=0`**。
  //    没有这一支，「释义被 is_lemma 挡住」那条断言一次都不会触发。
  ['有义项但 is_lemma=0（124,291 那批）',
    `SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id
      WHERE d.is_lemma=0 GROUP BY d.id LIMIT ${PER}`],
  ['多义项词', `SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id
      GROUP BY d.id ORDER BY COUNT(*) DESC LIMIT ${PER}`],
  ['有德语原文释义', `SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id
      JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='de' GROUP BY d.id LIMIT ${PER}`],
  ['多读音', `SELECT d.word FROM dict d JOIN pronunciation p ON p.word_id=d.id
      GROUP BY d.id HAVING COUNT(DISTINCT p.ipa)>1 LIMIT ${PER}`],
  ['有录音', `SELECT word FROM audio GROUP BY word LIMIT ${PER}`],
  ['例句有中文', `SELECT e.word FROM example e
      JOIN example_gloss g ON g.example_id=e.id AND g.lang='zh'
      WHERE COALESCE(e.hidden,0)=0 GROUP BY e.word LIMIT ${PER}`],
  // C13：没有这一支，「构词混进变形区」那两条断言就是恒真的。
  ['有构词 derivation', `SELECT d.word FROM dict d JOIN inflection i ON i.word_id=d.id
      WHERE i.kind='derivation' GROUP BY d.id LIMIT ${PER}`],
  ['义项级异体 alt_of', `SELECT d.word FROM dict d JOIN sense_relation r ON r.word_id=d.id
      WHERE r.kind='alt_of' AND r.sense_id IS NOT NULL GROUP BY d.id LIMIT ${PER}`],
];
const words: string[] = [];
const bucket = new Map<string, number>();
for (const [name, sql] of arms) {
  const got = (db.prepare(sql).all() as Array<{ word: string }>).map((r) => r.word);
  bucket.set(name, got.length);
  for (const w of got) if (!words.includes(w)) words.push(w);
}

// 已接受基线：`断言名 → [上限, 理由]`。**超了红。**
// 🔴 与回归闸同一条规矩：锁的是**数字**不是名字（`[[fix-regression-and-gate]]` 第四种机制：
//    pt 那轮 ACCEPT 按名字豁免，基线从 539 涨到 643 一声没吭）。
// ⚠️ 一条永远红的闸 = 没人看的闸 = 没有闸。所以已知未修的缺陷必须带数字进来。
const ACCEPT: Record<string, [number, string]> = {
  '🔴 ② 构词混进了变形区（收尾单 C13，读者会当成格形式）': [40,
    '收尾单 C32：全库 434 条构词关系被存了两遍且说法不一致 —— 同一个 (词形,原形) ' +
    '既有 kind=derivation 且标签正确（`Reifen ← reifen` 名词化不定式），' +
    '又有一条 kind=inflection 而标签是泛泛的「变形」。**数据缺陷，不在展示层遮**，' +
    '与 C15/C16 同批在生成侧修（都要重跑 2b）。' +
    '上限 40 是按本闸取样规模定的（“有构词 derivation”那一支取 40 个词，全中也就 40）。'],
};

const mutate = process.argv.includes('--mutate');
const fails = new Map<string, string[]>();
const counts = new Map<string, number>();
let n = 0;
for (const w of words) {
  const e = svc.getEntry(w) as Entry | null;
  if (!e) continue;
  n++;
  let html = render(e);
  // ⭐ 变异要**每条断言都打得到**：只抹一两个类名，新加的断言就是恒真的
  //    （`[[fix-regression-and-gate]]`：一条永远通过的检查等于没检查）。
  if (mutate) {
    html = html
      .replace(/class="sense-zh"/g, 'class="x"')
      .replace(/class="sense-src-de"/g, 'class="x"')
      .replace(/class="audio-btn"/g, 'class="x"')
      .replace(/class="example-item"/g, 'class="x"')
      .replace(/class="de-infl-list"/g, 'class="x"')
      .replace(/class="sense-altof"/g, 'class="x"')
      .replace(/class="rel-row"/g, 'class="x"')
      .replace(/class="de-form-grid"/g, 'class="x"');
  }
  for (const c of CHECKS) {
    const why = c.hit(e, html);
    if (why) {
      const arr = fails.get(c.name) ?? [];
      if (arr.length < 4) arr.push(`${w}：${why}`);
      fails.set(c.name, arr);
      counts.set(c.name, (counts.get(c.name) ?? 0) + 1);
    }
  }
}

console.log(`═══ 契约闸（de）：渲染出来的 HTML 对不对 ═══\n`);
console.log(`  取样 ${n} 个词（按形状取，不是随机）：\n` +
  [...bucket].map(([k, v]) => `    ${k} ${v}`).join('\n') + '\n');
let red = 0;
for (const c of CHECKS) {
  const arr = fails.get(c.name);
  const n = counts.get(c.name) ?? 0;
  const acc = ACCEPT[c.name];
  if (!arr) { console.log(`   ✅ ${c.name}`); continue; }
  if (acc && n <= acc[0]) {
    console.log(`   🟡 ${c.name}  ${n} 条  ← 已接受（上限 ${acc[0]}）`);
    console.log(`        理由：${acc[1]}`);
    for (const x of arr.slice(0, 2)) console.log(`        ${x}`);
    continue;
  }
  red++;
  console.log(`   🔴 ${c.name}  ${n} 条${acc ? `  ← 超出已接受上限 ${acc[0]}` : ''}`);
  for (const x of arr) console.log(`        ${x}`);
}
console.log(red ? `\n🔴 ${red} 条红` : `\n✅ 全部通过（${CHECKS.length} 条断言）`);
if (mutate) console.log('\n（--mutate：抹掉八个类名，上面应有 ≥8 条红）');
process.exit(mutate ? 0 : (red ? 1 : 0));
