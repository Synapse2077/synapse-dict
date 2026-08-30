/**
 * 葡语展示层契约闸：把真实数据喂进 React 组件、渲染成 HTML，再断言。2026-08-30（阶段 8）。
 *
 * ═══ 为什么数据层的回归闸不够 ═══
 * `pt/tests/test_no_regression.py` 的 L 组守的是「`portuguese.ts` 里有没有 `FROM sense`」——
 * 那只能证明**代码里写了**，证明不了**渲染出来有**。这两件事差着一个组件。
 *
 * 已知三个真实案例，全是「库里全对、接口全对、页面上没有」：
 *   · it `TVTB` 有两条义项却整块不渲染 —— 组件里一个 `entry.isLemma &&` 挡住 8,552 个词形；
 *   · it 意语原文导了 89,531 条、接口一直在返回，**组件那一行漏了写**，用户问了才发现；
 *   · fr 库里 39 万条录音 URL，而 `french.ts` 里 `FROM audio` 出现 **0 次**。
 *
 * ⇒ 本闸的每一条都断言 **HTML 里有没有**，不是数据库里有没有。
 *
 * ═══ pt 独有、别的语种的闸够不到的三条 ═══
 *   ① **双读音必须分得出巴/葡** —— 元音变换让两支不是口音差别而是音位对立
 *      （`novos` 巴 /ˈnɔvus/ vs 葡 /ˈnɔvuʃ/）。只渲染一个音标等于把信息抹平。
 *   ② **变形必须查得出** —— 132,660 条 `inflection.entry_id` 为空（收尾单 C11），
 *      展示层若走 `entry` 会把它们全丢掉，而**页面照样"正常"显示**，只是空一块。
 *   ③ **源语言行要带语种标签** —— fr 收尾单 C29 记的就是「pt/de 的源语言行没有标记」。
 *
 * ═══ 用法（仓库根目录）═══
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-pt.tsx
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-pt.tsx --limit 400
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-pt.tsx --mutate
 *
 * ⚠️ `--tsconfig` 不能省：仓库根目录没有 tsconfig.json，tsx 找不到 jsx: "react-jsx"。
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { getService } from '@synapse-dict/dict-core';
import { PortugueseEntryView } from './App';

const svc = getService('pt') as unknown as {
  getEntry(w: string): unknown;
  db: { prepare(s: string): { all(...a: unknown[]): unknown[] } };
};
const db = svc.db;
type Entry = Record<string, any>;
type Check = { name: string; hit: (e: Entry, html: string) => string | null };

function render(entry: Entry): string {
  return renderToStaticMarkup(createElement(PortugueseEntryView, {
    entry: entry as never, onWord: () => {}, speak: () => {},
  } as never));
}

const text = (h: string) => h.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ');
const count = (h: string, re: RegExp) => (h.match(re) ?? []).length;

const CHECKS: Check[] = [
  {
    name: '🔴 有义项却整块释义不渲染（it `TVTB` 那个形状）',
    hit: (e, h) => (e.senses.length > 0 && !/class="sense-zh"/.test(h))
      ? `${e.senses.length} 条义项，HTML 里一条 .sense-zh 都没有` : null,
  },
  {
    name: '🔴 中文释义条数与渲染出来的对不上',
    hit: (e, h) => {
      const want = e.senses.filter((s: Entry) => s.zh).length;
      const got = count(h, /class="sense-zh"/g);
      return want > 0 && got < want ? `有中文的义项 ${want}，渲染 ${got}` : null;
    },
  },
  {
    name: '🔴 葡语原文定义没渲染（it 漏了 89,531 条那个形状）',
    hit: (e, h) => {
      const want = e.senses.filter((s: Entry) => s.pt).length;
      return want > 0 && count(h, /class="sense-src" lang="pt"/g) < want
        ? `有葡语原文的义项 ${want}，渲染 ${count(h, /class="sense-src" lang="pt"/g)}` : null;
    },
  },
  {
    name: '🔴 源语言行没有语种标签（fr 收尾单 C29 那个形状）',
    hit: (e, h) => {
      const rows = count(h, /class="sense-src"/g);
      const tags = count(h, /class="sense-src-lang"/g);
      return rows !== tags ? `源语言行 ${rows} 条，语种标签 ${tags} 个` : null;
    },
  },
  {
    name: '🔴 ① 双读音：库里巴葡欧葡不同，页面上却只有一个',
    hit: (e, h) => {
      if (!e.ipaBr || !e.ipaPt || e.ipaBr === e.ipaPt) return null;
      const t = text(h);
      const miss = [e.ipaBr, e.ipaPt].filter((x) => !t.includes(x));
      return miss.length ? `两支读音不同，页面上缺 ${miss.join(' / ')}` : null;
    },
  },
  {
    name: '🔴 ① 双读音不同却没有巴/葡标签（读者分不清哪个是哪个）',
    hit: (e, h) => (e.ipaBr && e.ipaPt && e.ipaBr !== e.ipaPt
      && !/class="phonetic-label"/.test(h))
      ? '两支读音不同，却没渲染地区标签' : null,
  },
  {
    name: '🔴 ② 变形没渲染（走 entry 会丢 132,660 条，页面只是空一块）',
    hit: (e, h) => (e.inflections.length > 0 && !/class="infl-notes"/.test(h))
      ? `${e.inflections.length} 条变形，HTML 里没有 .infl-notes` : null,
  },
  {
    name: '🔴 例句没渲染',
    hit: (e, h) => (e.examples.length > 0 && !/class="example-item"/.test(h))
      ? `${e.examples.length} 条例句，HTML 里一条都没有` : null,
  },
  {
    name: '🔴 例句有中文却没渲染出来',
    hit: (e, h) => {
      const want = e.examples.slice(0, 12).filter((x: Entry) => x.zh).length;
      const got = count(h, /class="example-zh"/g);
      return want > 0 && got < want ? `前 12 条里有中文的 ${want}，渲染 ${got}` : null;
    },
  },
  {
    name: '🔴 录音没渲染（fr 那次 39 万条一个用户看不见）',
    hit: (e, h) => (e.audio.length > 0 && !/class="audio-clip"/.test(h))
      ? `${e.audio.length} 条录音，HTML 里没有 <audio>` : null,
  },
  {
    name: '🔴 语义关系没渲染',
    hit: (e, h) => (e.relations.length > 0 && !/class="rel-group"/.test(h))
      ? `${e.relations.length} 组关系，HTML 里没有 .rel-group` : null,
  },
  {
    name: '🔴 关系被截断却没说总数（读者以为就这么多）',
    hit: (e, h) => {
      const cut = e.relations.some((g: Entry) => g.total > g.targets.length);
      return cut && !/class="rel-more"/.test(h) ? '有分类被截断，页面没写「共 N」' : null;
    },
  },
  {
    name: '🔴 例句出处渲染成了孤立标点（`.` 那族）',
    hit: (_e, h) => {
      const m = h.match(/class="example-ref">([^<]*)</g) ?? [];
      const bad = m.filter((x) => x.replace(/.*>/, '').trim().length < 2);
      return bad.length ? `${bad.length} 条出处只剩标点` : null;
    },
  },
  {
    name: '🔴 隐藏的义项/例句漏到了页面上',
    hit: (e, h) => {
      const t = text(h);
      const rows = db.prepare(
        `SELECT text FROM example WHERE word = ? AND hidden = 1 LIMIT 20`).all(e.word) as
        Array<{ text: string }>;
      const leak = rows.filter((r) => t.includes(r.text.slice(0, 30)));
      return leak.length ? `${leak.length} 条 hidden=1 的例句出现在页面上` : null;
    },
  },
];

// ── 取样：**按形状取，不是随机抽** ──
// 随机抽 300 个词，抽到的绝大多数是没有义项的变形 —— 那样闸里大半条断言从不触发，
// 「全部通过」就成了假绿。⇒ 每一类形状各取一批，保证每条断言都有活可干。
// ⚠️ SQLite 的 `UNION ALL` 分支里**不许带 LIMIT**，每支要包一层子查询。
const LIMIT = Number(process.argv[process.argv.indexOf('--limit') + 1]) || 300;
const PER = Math.ceil(LIMIT / 5);
const arms: Array<[string, string]> = [
  ['多义项词', `SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id
                 WHERE COALESCE(s.hidden,0)=0 GROUP BY d.id
                 ORDER BY COUNT(*) DESC LIMIT ${PER}`],
  ['entry_id 为空的变形（C11）', `SELECT d.word FROM dict d JOIN inflection i ON i.word_id=d.id
                 WHERE i.entry_id IS NULL GROUP BY d.id LIMIT ${PER}`],
  ['巴葡欧葡读音不同', `SELECT d.word FROM dict d JOIN pronunciation p ON p.word_id=d.id
                 WHERE p.region='pt-BR' AND EXISTS(SELECT 1 FROM pronunciation q
                   WHERE q.word_id=d.id AND q.region='pt-PT' AND q.ipa<>p.ipa)
                 GROUP BY d.id LIMIT ${PER}`],
  ['有录音', `SELECT word FROM audio GROUP BY word LIMIT ${PER}`],
  ['例句有中文', `SELECT e.word FROM example e
                 JOIN example_gloss g ON g.example_id=e.id AND g.lang='zh'
                 WHERE COALESCE(e.hidden,0)=0 GROUP BY e.word LIMIT ${PER}`],
];
const words: string[] = [];
const bucket = new Map<string, number>();
for (const [name, sql] of arms) {
  const got = (db.prepare(sql).all() as Array<{ word: string }>).map((r) => r.word);
  bucket.set(name, got.length);
  for (const w of got) if (!words.includes(w)) words.push(w);
}

const mutate = process.argv.includes('--mutate');
const fails = new Map<string, string[]>();
let n = 0;
for (const w of words) {
  const e = svc.getEntry(w) as Entry | null;
  if (!e) continue;
  n++;
  let html = render(e);
  if (mutate) html = html.replace(/class="audio-clip"/g, 'class="x"')
    .replace(/class="sense-src-lang"/g, 'class="x"');
  for (const c of CHECKS) {
    const why = c.hit(e, html);
    if (why) {
      const arr = fails.get(c.name) ?? [];
      if (arr.length < 4) arr.push(`${w}：${why}`);
      fails.set(c.name, arr);
    }
  }
}

console.log(`═══ 契约闸（pt）：渲染出来的 HTML 对不对 ═══\n`);
console.log(`  取样 ${n} 个词（按形状取，不是随机）：` +
  [...bucket].map(([k, v]) => `${k} ${v}`).join(' ／ ') + '\n');
let red = 0;
for (const c of CHECKS) {
  const arr = fails.get(c.name);
  if (!arr) { console.log(`   ✅ ${c.name}`); continue; }
  red++;
  console.log(`   🔴 ${c.name}`);
  for (const x of arr) console.log(`        ${x}`);
}
console.log(red ? `\n🔴 ${red} 条红` : `\n✅ 全部通过（${CHECKS.length} 条断言）`);
if (mutate) console.log(`\n（--mutate：抹掉 audio-clip 与 sense-src-lang 两个类名，上面应有 ≥2 条红）`);
process.exit(mutate ? 0 : (red ? 1 : 0));
