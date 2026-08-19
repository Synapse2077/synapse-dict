/**
 * 展示层契约闸：把真实数据喂进 React 组件、渲染成 HTML，再断言。2026-08-16。
 *
 * ═══ 为什么需要它 ═══
 * 2026-08-16 之前，所有的闸都在数据库里自查（出版层↔证据层双向回核、词性必须与证据一致、
 * 中文不许逐字重复……），而用户从**界面上**挑出了三个我完全看不见的缺陷：
 *
 *   ① `tempo` 的义项被拆成两组，第二组标题显示成英文原始串 `noun`
 *      —— 库里混着两套词性词表，展示层的 `POS_LABELS` 查不到 `noun` 就把原始串吐出来
 *   ② `Dodoma`（坦桑尼亚首都）被归到【短语】
 *      —— 意语版拿 `phrase` 当多词表达的筐
 *   ③ `TVTB` 有两条义项却整块释义不渲染
 *      —— 组件里有个 `entry.isLemma &&` 前置条件，挡住 **8,552 个词形**
 *
 * 三个的共同点：**只在渲染之后才存在**。查库查不到，查接口也查不到 ——
 * ③ 的接口返回是完全正确的，缺陷在 React 组件那一行。
 * ⇒ 要抓这一类，就必须真的渲染。
 *
 * ═══ 不装新依赖 ═══
 * 仓库里没有任何测试框架。用 `react-dom/server` 把组件渲染成静态 HTML（react-dom 本来就在），
 * 用 `tsx` 直接跑 TS（本来就在），数据走 `ItalianDictService` —— 与 API **同一条代码路径**。
 *
 * ═══ 用法（仓库根目录）═══
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check.tsx
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check.tsx --mutate
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check.tsx --limit 200
 *
 * ⚠️ `--tsconfig` 不能省：仓库根目录没有 tsconfig.json，tsx 找不到
 *    `jsx: "react-jsx"`（在 tsconfig.base.json 里），会退回经典运行时并报
 *    `ReferenceError: React is not defined` —— 而 App.tsx 靠 vite 的自动运行时，不 import React。
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { getService, type ItalianEntry } from '@synapse-dict/dict-core';
import { POS_LABELS, REL_LABELS, itAudioRegion } from '@synapse-dict/dict-labels';
import { ItalianEntryView } from './App';

// 🔴 走 `getService('it')` —— 与 API **同一条代码路径、同一个数据目录推算逻辑**。
//    第一版直接 `new ItalianDictService()` 少传路径，报 ERR_INVALID_ARG_TYPE。
const svc = getService('it') as unknown as {
  getEntry(w: string): unknown;
  db: { prepare(s: string): { all(...a: unknown[]): unknown[] } };
};
const db = svc.db;

type Check = { name: string; hit: (e: ItalianEntry, html: string) => string | null };

/** 渲染一条词条为静态 HTML。组件要的回调在这里给空实现。 */
function render(entry: ItalianEntry): string {
  return renderToStaticMarkup(
    createElement(ItalianEntryView, {
      entry, speakLocale: 'it-IT', onWord: () => {}, speak: () => {},
    } as never),
  );
}

/** 去掉标签，只留可见文字 —— 断言要盯**用户看到的东西**，不是 DOM 结构。 */
function visibleText(html: string): string {
  return html.replace(/<[^>]*>/g, '').replace(/&quot;/g, '"').replace(/&#x27;/g, "'")
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
}

const CHECKS: Check[] = [
  {
    // ③ 的回归测试
    name: '🔴 有可见义项就必须渲染出「释义」区块',
    hit: (e, html) => (e.senses.length > 0 && !html.includes('释义'))
      ? `有 ${e.senses.length} 条义项却没有释义区块` : null,
  },
  {
    // ③ 更强的一条：每条义项的中文都要出现在页面上
    name: '🔴 每条义项的中文都必须出现在页面文字里',
    hit: (e, html) => {
      const t = visibleText(html);
      const miss = e.senses.filter((s) => s.zh && !t.includes(s.zh));
      return miss.length ? `${miss.length} 条中文没渲染出来，例：${miss[0].zh}` : null;
    },
  },
  {
    // ① 的回归测试：词性分组标题不许出现原始英文串
    name: '🔴 词性分组标题不许出现未映射的原始串',
    hit: (e, html) => {
      const labels = new Set(Object.values(POS_LABELS));
      const raw = [...html.matchAll(/class="pos-group-label">([^<]*)</g)].map((m) => m[1]);
      const bad = raw.filter((x) => x && !labels.has(x));
      return bad.length ? `分组标题出现原始串：${bad.join('、')}` : null;
    },
  },
  {
    // ① 的另一面：库里的词性值必须在 POS_LABELS 里查得到
    name: '🔴 每条义项的词性都要能映射成中文标签',
    hit: (e) => {
      const bad = e.senses.map((s) => s.pos).filter((p): p is string => !!p && !POS_LABELS[p]);
      return bad.length ? `词性查不到中文标签：${[...new Set(bad)].join('、')}` : null;
    },
  },
  {
    // 意语原文这两天导了 89,531 条，接口一直在返回，而组件那一行我漏了写 —— 用户问了才发现
    name: '🔴 有意语原文的义项必须把原文渲染出来',
    hit: (e, html) => {
      const t = visibleText(html);
      const miss = e.senses.filter((s) => s.it && !t.includes(s.it.slice(0, 20)));
      return miss.length ? `${miss.length} 条意语原文没渲染，例：${miss[0].it?.slice(0, 30)}` : null;
    },
  },
  // ── 阶段 8 接上展示层的四样，各配一条「接口给了、页面必须显示出来」──────────
  // 这四条防的是同一个形状：**数据早就落库、接口也在返回，而组件里少写了一行**
  // （`s.it` 那次就是这么漏掉 89,531 条意语原文的，用户问了才发现）。
  {
    name: '🔴 默认读音必须渲染出来',
    hit: (e, html) => (e.ipa && !visibleText(html).includes(e.ipa))
      ? `ipa=${e.ipa} 没出现在页面上` : null,
  },
  {
    name: '🔴 每条例句的原文都必须出现在页面文字里',
    hit: (e, html) => {
      const t = visibleText(html);
      // 与组件的截断口径一致：义项下最多 3 条，词级最多 8 条（服务端已截）
      const want = [
        ...e.senses.flatMap((s) => s.examples.slice(0, 3).map((x) => x.text)),
        ...e.examples.map((x) => x.text),
      ];
      const miss = want.filter((x) => !t.includes(x));
      return miss.length ? `${miss.length} 条例句没渲染，例：${miss[0].slice(0, 30)}` : null;
    },
  },
  {
    name: '🔴 有真人录音就必须渲染出录音行',
    hit: (e, html) => (e.audios.length > 0 && !html.includes('audio-chip'))
      ? `有 ${e.audios.length} 条录音却没有录音行` : null,
  },
  {
    // 与 POS_LABELS 那条同一个形状：录音地区是**法语原值**，映射不到就会把法语印在中文词典上。
    // ⚠️ 判据只看**地区那个 span**，不看整页文字。第一版拿整页判，`primavera` 报红 ——
    //    它的一条例句出处是法语新闻标题「Italie : une foule en liesse…」，
    //    页面上确实有 `Italie` 三个字母，但那不是地区标签。**尺子错，不是数据错**（A33）。
    name: '🔴 录音地区不许把法语原文印出来',
    hit: (e, html) => {
      const shown = [...html.matchAll(/class="audio-region">([^<]*)</g)].map((m) => m[1]);
      const leaked = shown.filter((x) => x && itAudioRegion(x) !== x);
      return leaked.length ? `地区原文漏进页面：${[...new Set(leaked)].join('、')}` : null;
    },
  },
  {
    name: '🔴 关系截断了必须把总数说出来',
    hit: (e, html) => {
      const cut = e.relations.filter((g) => g.total > g.targets.length);
      const t = visibleText(html);
      const miss = cut.filter((g) => !t.includes(`共 ${g.total} 个`));
      return miss.length ? `${miss.length} 组截断了没说总数（${miss[0].kind} ${miss[0].total}）` : null;
    },
  },
  {
    name: '🔴 关系分类都要能映射成中文标签',
    hit: (e) => {
      const bad = e.relations.map((g) => g.kind).filter((k) => !REL_LABELS[k]);
      return bad.length ? `关系分类查不到中文：${bad.join('、')}` : null;
    },
  },
  {
    name: '页面上不许出现 undefined / [object Object]',
    // ⚠️ 判据里**不能有 `null`**：意语 `null'` 是 `nulla` 的省音形式，**词形本身**就长这样。
    //    第一版拿裸串判报了它；第二版试图"先剔除词头和释义再判"，页面上仍有别处出现，还是误报。
    //    ⇒ 直接把 `null` 从判据里去掉 —— `undefined`/`[object Object]`/`NaN` 不可能是合法意语内容，
    //       而 `null` 会。为一条假阳性继续加复杂度不划算（`PITFALLS` A4：判据改三轮就停手）。
    hit: (_e, html) => {
      const t = visibleText(html);
      const bad = ['undefined', '[object Object]', 'NaN'].filter((x) => t.includes(x));
      return bad.length ? `渲染出 ${bad.join('、')}` : null;
    },

  },
];

/** 高风险面：三个已知缺陷各自的全集 + 一批常用词。 */
function targets(limit: number): string[] {
  const q = (sql: string) => (db.prepare(sql).all() as Array<{ word: string }>).map((r) => r.word);
  const set = new Set<string>();
  // ③ 被 isLemma 挡过的 8,552 个词形 —— 全量
  for (const w of q(`SELECT DISTINCT d.word FROM dict d JOIN sense s ON s.word_id=d.id
     WHERE COALESCE(s.hidden,0)=0 AND COALESCE(d.is_lemma,0)=0`)) set.add(w);
  // ① 词性可能映射不出来的
  for (const w of q(`SELECT DISTINCT d.word FROM dict d JOIN sense s ON s.word_id=d.id
     WHERE COALESCE(s.hidden,0)=0 AND s.pos IS NOT NULL`).slice(0, 4000)) set.add(w);
  // 带意语原文的
  for (const w of q(`SELECT DISTINCT d.word FROM dict d JOIN sense s ON s.word_id=d.id
     JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='it'
     WHERE COALESCE(s.hidden,0)=0 LIMIT 4000`)) set.add(w);
  // 阶段 8 新接的四样，各取一批（**有数据的那批**才验得出"接口给了页面没显示"）
  for (const w of q(`SELECT DISTINCT word FROM example LIMIT 3000`)) set.add(w);
  for (const w of q(`SELECT DISTINCT word FROM audio LIMIT 2000`)) set.add(w);
  for (const w of q(`SELECT d.word FROM dict d JOIN sense_relation r ON r.word_id=d.id
     GROUP BY d.id HAVING count(*) > 12 LIMIT 1500`)) set.add(w);   // 一定会触发截断
  for (const w of q(`SELECT d.word FROM dict d JOIN pronunciation p ON p.word_id=d.id
     GROUP BY d.id HAVING count(*) > 1 LIMIT 2000`)) set.add(w);    // 多读音
  const all = [...set];
  return limit > 0 ? all.slice(0, limit) : all;
}

function run(words: string[], quiet = false): number {
  const fails = new Map<string, string[]>();
  let n = 0;
  // ⚠️ 每条都要跑一次完整 React 渲染，上万条要十几分钟。**必须有进度**，
  //    否则跑起来跟卡死分不出来（今天已经在跑批上栽过一次：命令接了 `| tail` 把输出憋住了）。
  if (!quiet) console.log(`■ 待渲染 ${words.length.toLocaleString()} 个词条`);
  for (const w of words) {
    if (!quiet && n > 0 && n % 2000 === 0) {
      console.log(`   [${n.toLocaleString()}/${words.length.toLocaleString()}] 已发现不符 ` +
        `${[...fails.values()].reduce((a, b) => a + b.length, 0)}`);
    }
    const entry = svc.getEntry(w) as ItalianEntry | null;
    if (!entry) continue;
    n += 1;
    let html: string;
    try {
      html = render(entry);
    } catch (err) {
      fails.set('🔴 渲染直接抛错', [...(fails.get('🔴 渲染直接抛错') ?? []), `${w}: ${err}`]);
      continue;
    }
    for (const c of CHECKS) {
      const msg = c.hit(entry, html);
      if (msg) fails.set(c.name, [...(fails.get(c.name) ?? []), `${w} —— ${msg}`]);
    }
  }
  if (!quiet) {
    console.log(`\n═══ 展示层契约闸（渲染 ${n.toLocaleString()} 个词条）═══`);
    // ⚠️ 第一版只打印 CHECKS 里的键，而"渲染直接抛错"不在其中 ——
    //    结果是六条全绿、总数却是 300。**统计口径和展示口径必须一致**，否则闸自己在骗自己。
    const names = [...new Set([...CHECKS.map((c) => c.name), ...fails.keys()])];
    for (const name of names) {
      const f = fails.get(name) ?? [];
      console.log(`   ${f.length ? '🔴' : '✅'} ${name.padEnd(40)} ${f.length}`);
      for (const line of f.slice(0, 3)) console.log(`        ${line}`);
    }
  }
  return [...fails.values()].reduce((a, b) => a + b.length, 0);
}

/** 变异验证：人为破坏，闸必须报红。一条永远通过的检查等于没检查。 */
function mutate(words: string[]): void {
  // ══════════════════════════════════════════════════════════════════════
  //  两种变异，**别混**（2026-08-18 阶段 8 重写，原因写在下面）
  //
  //  🔴 原来这里只有「改数据」一种，而本文件里大多数检查问的是
  //     「**组件有没有把这个字段渲染出来**」—— 改完数据、组件照样忠实渲染，
  //     检查当然不红。也就是说那几条变异**在构造上就不可能成立**，
  //     它们给出的绿灯是假的（`verification-gates-not-sampling`：
  //     一条永远通过的检查等于没检查，而一条永远失败的变异同样等于没验）。
  //
  //  ⇒ ① data：改数据 —— 只验**只看数据**的检查（词性/关系分类能不能映射成中文）
  //     ② html：先正常渲染，再**把渲染结果打坏** —— 这才是"组件漏写了一行"的真实形状，
  //        也正是这些检查要防的那个缺陷（`s.it` 漏渲染 89,531 条那次）
  // ══════════════════════════════════════════════════════════════════════
  type DataCase = [string, (e: ItalianEntry) => void, ((e: ItalianEntry) => boolean)?];
  type HtmlCase = [string, (html: string) => string, (e: ItalianEntry) => boolean];

  const dataCases: DataCase[] = [
    ['给一条义项塞一个映射不出来的词性',
     (e) => { if (e.senses[0]) e.senses[0].pos = 'zzz_unknown'; }],
    ['塞一个映射不出来的关系分类',
     (e) => { if (e.relations[0]) e.relations[0].kind = 'zzz_rel'; },
     (e) => e.relations.length > 0],
    ['把中文换成 undefined 字样',
     (e) => { if (e.senses[0]) e.senses[0].zh = 'undefined'; }],
  ];

  // 「组件少渲染了一块」——用正则把渲染结果里的那一块抠掉，检查必须报出来。
  const htmlCases: HtmlCase[] = [
    ['组件漏渲染义项中文', (h) => h.replace(/<div class="sense-zh">[\s\S]*?<\/div>/g, ''),
     (e) => e.senses.some((x) => !!x.zh)],
    ['组件漏渲染意语原文', (h) => h.replace(/<div class="sense-src" lang="it">[\s\S]*?<\/div>/g, ''),
     (e) => e.senses.some((x) => !!x.it)],
    ['组件漏渲染例句', (h) => h.replace(/<div class="sense-example">[\s\S]*?<\/div><\/div>/g, ''),
     (e) => e.examples.length > 0 || e.senses.some((x) => x.examples.length > 0)],
    ['组件漏渲染音标', (h) => h.replace(/<span class="phonetic-value">[^<]*<\/span>/g, ''),
     (e) => !!e.ipa],
    ['组件漏渲染录音行', (h) => h.replace(/audio-chip/g, 'x-chip'),
     (e) => e.audios.length > 0],
    ['组件漏说关系被截断了', (h) => h.replace(/<span class="rel-more">[^<]*<\/span>/g, ''),
     (e) => e.relations.some((g) => g.total > g.targets.length)],
    ['组件把录音地区的法语原文直接印出来',
     (h) => h.replace(/<span class="audio-region">[^<]*<\/span>/,
                      '<span class="audio-region">Monopoli (Italie)</span>'),
     (e) => e.audios.some((a) => a.region === 'Monopoli (Italie)')],
  ];

  console.log('\n═══ 变异验证 ═══');
  let caught = 0;
  const total = dataCases.length + htmlCases.length;

  for (const [name, mut, need] of dataCases) {
    let red = false;
    for (const w of words) {
      const e = svc.getEntry(w) as ItalianEntry | null;
      if (!e || e.senses.length === 0 || (need && !need(e))) continue;
      mut(e);
      if (CHECKS.some((c) => c.hit(e, render(e)))) { red = true; break; }
    }
    caught += red ? 1 : 0;
    console.log(`   ${red ? '✅' : '🔴'} ${('[数据] ' + name).padEnd(38)} ` +
      `${red ? '闸红了（对）' : '闸没红 —— 这条闸是假的'}`);
  }

  for (const [name, damage, need] of htmlCases) {
    let red = false;
    let tried = 0;
    for (const w of words) {
      const e = svc.getEntry(w) as ItalianEntry | null;
      if (!e || !need(e)) continue;
      tried += 1;
      const broken = damage(render(e));
      if (CHECKS.some((c) => c.hit(e, broken))) { red = true; break; }
    }
    caught += red ? 1 : 0;
    // ⚠️ 变异没触发时**先查变异对不对**（阶段 7 的教训：B2 那条是我造的用例造不出缺陷）。
    //    `tried=0` 说明这批词里根本没有能触发的对象，那是取样面的问题，不是闸的问题。
    console.log(`   ${red ? '✅' : '🔴'} ${('[渲染] ' + name).padEnd(38)} ` +
      `${red ? '闸红了（对）' : `闸没红 —— 这条闸是假的（可试对象 ${tried}）`}`);
  }

  console.log(`\n   变异验证 ${caught}/${total}`);
  if (caught !== total) process.exit(1);
}

const argv = process.argv.slice(2);
const limit = argv.includes('--limit') ? Number(argv[argv.indexOf('--limit') + 1]) : 0;
const words = targets(limit);
if (argv.includes('--mutate')) {
  mutate(words);
} else {
  const bad = run(words);
  console.log(`\n   ${bad === 0 ? '✅ 全部通过' : `🔴 共 ${bad} 处不符`}`);
  process.exit(bad === 0 ? 0 : 1);
}
