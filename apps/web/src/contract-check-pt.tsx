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
import { PortugueseEntryView, capAudios } from './App';

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

// 🔴 2026-08-31：比对两边必须**同样归一**，否则断言在报自己的 bug。
//    这里踩到两条：例句中文里的 `&` 在 HTML 里是 `&amp;`、中文里的换行被这一行压成空格
//    ⇒ 直接 `includes(原文)` 必然找不到，报出 4 条「例句没渲染」的假红（例句其实都在）。
const norm = (x: string) => x
  .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
  .replace(/&quot;/g, '"').replace(/&#x27;|&#39;/g, "'")
  .replace(/\s+/g, ' ').trim();
const text = (h: string) => norm(h.replace(/<[^>]*>/g, ' '));
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
    // 🔴 **2026-08-31 改成按内容判**。旧版数的是 `.example-item` / `.example-zh` 两个**类名**，
    //    今天把例句挂进义项（`.sense-example` / `.ex-zh`）之后当场报 4+4 条假红 ——
    //    例句一条没丢，`agro` 的那条就画在它的义项下面。
    //    ⇒ 数类名的断言**跟着布局漂**；改成问「**该出现的那句话，页面上有没有**」。
    name: '🔴 例句没渲染',
    hit: (e, h) => (e.examples.length > 0
      && !/class="sense-example"/.test(h))
      ? `${e.examples.length} 条例句，HTML 里一条都没有` : null,
  },
  {
    // 布局的规矩：每条义项下最多 3 条、页尾的无归属例句最多 12 条。
    // 断言只问**这些该显示的**里有中文的那几条，其中文有没有真的出现在页面文本里。
    name: '🔴 例句有中文却没渲染出来',
    hit: (e, h) => {
      const t = text(h);
      const shown: Entry[] = [];
      for (const s of e.senses) {
        shown.push(...e.examples.filter((x: Entry) => x.senseId === s.id).slice(0, 3));
      }
      shown.push(...e.examples.filter((x: Entry) => x.senseId === null).slice(0, 12));
      const miss = shown.filter((x) => x.zh && !t.includes(norm(x.zh).slice(0, 24)));
      return miss.length
        ? `该显示的 ${shown.length} 条里，有中文却没出现在页面上的 ${miss.length}（如「${miss[0].zh.slice(0, 20)}」）`
        : null;
    },
  },
  {
    // 🔴 2026-08-31 改：发音从页尾挪到音标下、换成 `HumanAudioRow` 之后，
    //    渲染出来的是 `<button class="audio-chip">`，`<audio>` 是点击时才 `new Audio()` 造的
    //    ⇒ 旧断言查 `.audio-clip` 当场报 4 条假红（录音一条没丢）。
    // ⭐ 顺手**加强**：不是问「有没有」，是问「**几条录音就该有几个按钮**」——
    //    少一个（比如被某个 filter 悄悄吃掉）也red。
    name: '🔴 录音没渲染 / 数量对不上（fr 那次 39 万条一个用户看不见）',
    hit: (e, h) => {
      // ⚠️ 期望值走 `capAudios`（展示层那份唯一的限量规则），**不在这里重算** ——
      //    2026-08-31 给共用组件加「每地区最多 2 条」后，旧的「几条录音就该有几个按钮」
      //    当场报 4 条假红。放宽断言是错的：它的职责是「少一个也红」。
      const want = capAudios(e.audio as Array<{ url: string | null; region?: string | null }>).length;
      const got = count(h, /class="audio-chip[^"]*"/g);
      return want > 0 && got !== want ? `${want} 条录音，页面上 ${got} 个播放按钮` : null;
    },
  },
  {
    // 🔴 2026-08-31：这条闸建成时就该有，没有 ⇒ **7,947 条 alt_of 从阶段 8 那天起一个用户没看见**
    //    （`dict-core` 一直在返回，`PortugueseEntryView` 那一行漏了写）。
    //    it 那次同一形状是用户问出来的，这次是接义项级关系时顺手翻出来的。
    name: '🔴 词条级异体指针没渲染（接口一直在返回，组件漏了那一行）',
    hit: (e, h) => (e.altOf.length > 0 && !/class="alt-of-row"/.test(h))
      ? `${e.altOf.length} 条词条级异体，HTML 里没有 .alt-of-row` : null,
  },
  {
    // 🔴 反向的那一半：**义项级的异体不许升级成词条级横幅**。
    //    这正是 2026-08-31 我自己造出来的缺陷 —— 库里 7,947 条 alt_of 全挂在义项上，
    //    而渲染是按词条级查的 ⇒ `banco`（银行）页顶印出「异体 → banco de dados」，
    //    **这句话本身是错的**。用户看 `banco` 时逮到的。
    name: '🔴 义项级异体没画在义项里（或被升级成了词条级横幅）',
    hit: (e, h) => {
      const n = e.senses.reduce((a: number, x: Entry) => a + (x.altOf?.length ?? 0), 0);
      if (!n) return null;
      if (!/class="sense-altof"/.test(h)) return `${n} 条义项级异体，HTML 里没有 .sense-altof`;
      const inSense = new Set<string>(
        e.senses.flatMap((x: Entry) => (x.altOf ?? []).map((a: Entry) => a.target)));
      const up = e.altOf.filter((a: Entry) => inSense.has(a.target));
      return up.length ? `${up.length} 条义项级异体被升级到了词条级（如 ${up[0].target}）` : null;
    },
  },
  {
    name: '🔴 语义关系没渲染',
    hit: (e, h) => (e.relations.length > 0 && !/class="rel-group"/.test(h))
      ? `${e.relations.length} 组关系，HTML 里没有 .rel-group` : null,
  },
  {
    // 🔴 2026-08-31 接义项级关系时加的。库里 153,452 条关系有 71,017 条带 `sense_id`，
    //    而旧版展示层查的是 `WHERE word_id = ?` —— **义项归属整个丢掉**：
    //    `pinta` 8 个义项，查「痣」的读者会看到另外两个粗俗义项的 110 个近义词混在一起。
    //    ⇒ 断言「义项自己有关系，就必须画在义项里面（`.sense-rels`）」。
    name: '🔴 义项级关系没画在义项下面（又拍回词条级那个形状）',
    hit: (e, h) => {
      const n = e.senses.reduce(
        (a: number, x: Entry) => a + (x.relations?.length ?? 0), 0);
      return n > 0 && !/class="sense-rels"/.test(h)
        ? `${n} 组关系挂在义项上，HTML 里没有 .sense-rels` : null;
    },
  },
  {
    // ⚠️ 反向的那一半：词条级区块只许画**没有义项归属**的那 82,435 条。
    //    少了这条，「两边各印一遍」这种回归照样全绿。
    name: '🔴 同一条关系在词条级和义项级各印了一遍',
    hit: (e, h) => {
      const inSense = new Set<string>();
      for (const x of e.senses) {
        for (const g of (x.relations ?? [])) {
          for (const t of g.targets) inSense.add(`${g.kind}\u0000${t.word}`);
        }
      }
      const dup = e.relations.flatMap((g: Entry) =>
        g.targets.filter((t: Entry) => inSense.has(`${g.kind}\u0000${t.word}`))
                 .map((t: Entry) => `${g.kind}:${t.word}`));
      return dup.length && /class="rel-group"/.test(h)
        ? `词条级重复了义项级的 ${dup.length} 条（如 ${dup[0]}）` : null;
    },
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
      // 🔴 2026-08-31：出处行的类名从 `.example-ref` 换成了共用的 `.ex-ref`
      //    （pt 的例句块统一到五门通用标记）。查旧类名 ⇒ **这条断言从此永远绿**。
      //    今天第四次撞「换了标记、断言还查旧类名」——所以两个都认。
      const m = h.match(/class="(?:example-ref|ex-ref)">([^<]*)</g) ?? [];
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
const PER = Math.ceil(LIMIT / 7);
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
  // 🔴 2026-08-31 补的第六支。加「异体指针没渲染」那条断言时，五支取样里
  //    **没有一支是奔 alt_of 去的** ⇒ 断言一次都不触发、绿得毫无意义。
  //    这正是本文件开头写的假绿：「每一类形状各取一批，保证每条断言都有活可干」。
  // ⚠️ 分两支取。alt_of 拆级之后（词条级只留 sense_id IS NULL），
  //    只按「有 alt_of」取样会几乎全取到**义项级**的 ⇒ 词条级那条断言又变空。
  //    同一个坑今天踩第二次：**断言分了级，取样就必须跟着分级**。
  ['词条级异体（sense_id 空）', `SELECT d.word FROM dict d JOIN sense_relation r ON r.word_id=d.id
                 WHERE r.kind='alt_of' AND r.sense_id IS NULL GROUP BY d.id LIMIT ${PER}`],
  ['义项级异体', `SELECT d.word FROM dict d JOIN sense_relation r ON r.word_id=d.id
                 WHERE r.kind='alt_of' AND r.sense_id IS NOT NULL GROUP BY d.id LIMIT ${PER}`],
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
  // ⭐ 变异要**每条断言都打得到**：只抹两个类名，新加的断言就是恒真的
  //    （`[[fix-regression-and-gate]]`：一条永远通过的检查等于没检查）。
  //    ③ 抹掉 `sense-rels` ＝ 义项级关系被拍回词条级；
  //    ④ 把义项级关系原样复制到词条级 ＝ 同一条印两遍那个回归。
  if (mutate) {
    html = html.replace(/class="audio-chip[^"]*"/g, 'class="x"')
      .replace(/class="sense-src-lang"/g, 'class="x"')
      .replace(/class="sense-rels"/g, 'class="x"')
      .replace(/class="alt-of-row"/g, 'class="x"')
      .replace(/class="sense-altof"/g, 'class="x"');
    const first = e.senses.find((x: Entry) => (x.relations ?? []).length > 0);
    if (first) e.relations = [...e.relations, ...first.relations];
  }
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
if (mutate) console.log(`\n（--mutate：抹掉 audio-chip / sense-src-lang / sense-rels / alt-of-row / sense-altof 五个类名，并把义项级关系复制到词条级，上面应有 ≥6 条红）`);
process.exit(mutate ? 0 : (red ? 1 : 0));
