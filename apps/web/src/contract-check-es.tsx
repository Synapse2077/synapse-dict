/**
 * 展示层契约闸（**西语**）：把真实数据喂进 React 组件、渲染成 HTML，再断言。2026-08-20。
 *
 * ═══ 为什么现在才有 ═══
 * 意语的这道闸（`contract-check.tsx`，17 条）2026-08-16 就建了，起因是用户从**界面上**
 * 挑出三个查库查不到、查接口也查不到的缺陷。西语一直没有 ——
 * 而 2026-08-20 这一天西语改了**三处渲染**：
 *
 *   ① `inflNotes` 从劈 `dict.infl` 字符串改成读 `inflection` 表
 *   ② 「变位形式 / 参见」两个标题按 `inflNotes` 是否为空分（3,881 个拼写变体词形受影响）
 *   ③ 新增「变形形」区块（8,075 个补收词头的反查）
 *
 * 三处都只有**数据侧**的闸盯着（回归闸 C1–C12）。数据对不等于页面对 ——
 * 这正是 [[fix-regression-and-gate]] 记的第二种机制（被绕过）。
 *
 * ═══ 与意语那份的关系：**独立文件，不复用**（按语种解耦）═══
 * 组件不同（`SpanishEntryView` vs `ItalianEntryView`）、字段不同
 * （`unifiedSenses`/`baseForms`/`forms` vs `senses`/`readings`/`plurals`）、
 * 类名不同。共用只会让两边都被迫迁就对方。
 *
 * ═══ 不装新依赖 ═══
 * `react-dom/server` 渲染成静态 HTML，`tsx` 直接跑 TS，数据走 `getService('es')` ——
 * 与 API **同一条代码路径**。
 *
 * ═══ 用法（仓库根目录）═══
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-es.tsx
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-es.tsx --mutate
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-es.tsx --limit 300
 *
 * ⚠️ `--tsconfig` 不能省（理由同意语那份：根目录没有 tsconfig.json，
 *    tsx 找不到 `jsx: "react-jsx"` 会报 `React is not defined`）。
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { getService } from '@synapse-dict/dict-core';
import { SpanishEntryView, capAudios } from './App';
import { ES_REGION_LABELS } from '@synapse-dict/dict-labels';

const svc = getService('es') as unknown as {
  getEntry(w: string): unknown;
  db: { prepare(s: string): { all(...a: unknown[]): unknown[] } };
};
const db = svc.db;

type EsEntry = {
  word: string; pos: string | null; phonetic: string | null; isLemma: boolean;
  unifiedSenses: Array<{ id: number; pos: string | null; title: string; detail: string | null }>;
  baseForms: string[]; inflNotes: string[];
  forms: Array<{ word: string; label: string }>;
  examples: Array<{ text: string; senseId: number | null }>;
  homographs: Array<{ word: string }>;
  audios: Array<{ file: string; url: string | null; region: string | null;
    speaker: string | null }>;
};

type Check = { name: string; hit: (e: EsEntry, html: string) => string | null };

function render(entry: EsEntry): string {
  return renderToStaticMarkup(
    createElement(SpanishEntryView, {
      entry, speakLocale: 'es-ES', onWord: () => {}, speak: () => {},
    } as never),
  );
}

/** 去标签，只留可见文字 —— 断言要盯**用户看到的东西**，不是 DOM 结构。 */
function visibleText(html: string): string {
  return html.replace(/<[^>]*>/g, ' ').replace(/&quot;/g, '"').replace(/&#x27;/g, "'")
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
}

const CHECKS: Check[] = [
  {
    name: '🔴 有可见义项就必须渲染出「释义」区块',
    hit: (e, html) => (e.unifiedSenses.length > 0 && !html.includes('>释义<')
      ? `${e.unifiedSenses.length} 条义项一条都没渲染` : null),
  },
  {
    name: '🔴 未折叠的义项中文都必须出现在页面文字里',
    // ⚠️ **2026-09-12 起断言全部义项**：折叠已按用户要求去掉（观察态）。
    //    原来这里只断言首屏那 8 条 —— 折叠规则改回来时，这一处要跟着改回去。
    //    ——「`mano` 的 26 条义项一屏铺不下」是有意的产品设计，折叠的仍可展开。
    //    第一版断言「每条义项」⇒ 报 535 处假红。**又一次拿自己的期望当判据**（A33）。
    hit: (e, html) => {
      const t = visibleText(html);
      const miss = e.unifiedSenses
        .filter((s) => s.title && !t.includes(s.title));
      return miss.length ? `${miss.length} 条中文没渲染，如「${miss[0].title.slice(0, 20)}」` : null;
    },
  },
  {
    name: '🔴 词性分组标题不许出现未映射的原始串',
    // 意语那边真出过：`POS_LABELS` 查不到就把 `noun` 原样吐出来。
    hit: (_e, html) => {
      const raw = [...html.matchAll(/<div class="pos-group-label">([^<]*)<\/div>/g)]
        .map((m) => m[1])
        .filter((x) => /^[a-z_]+$/.test(x));
      return raw.length ? `未映射的词性标题：${[...new Set(raw)].join(', ')}` : null;
    },
  },
  {
    name: '🔴 变位说明必须逐条渲染出来（今天改成读 inflection 表）',
    hit: (e, html) => {
      const t = visibleText(html);
      const miss = e.inflNotes.filter((n) => !t.includes(n));
      return miss.length ? `${miss.length} 条变位说明没渲染，如「${miss[0]}」` : null;
    },
  },
  {
    name: '🔴 拼写变体不许顶「变位形式」的标题',
    // `aqui`→`aquí` 是常见误拼，不是变位形式。判据 = 有原形链接但**没有任何语法说明**。
    // `sólo`(zipf 5.79) / `asi`(5.21) / `tambien`(4.98) 全是高频词。
    hit: (e, html) => (e.baseForms.length > 0 && e.inflNotes.length === 0
      && html.includes('>变位形式<')
      ? '没有语法说明却写着「变位形式」' : null),
  },
  {
    name: '🔴 有语法说明就必须写「变位形式」，不能写「参见」',
    hit: (e, html) => (e.inflNotes.length > 0 && html.includes('>参见<')
      ? '有语法说明却写着「参见」' : null),
  },
  {
    name: '🔴 补收的无释义词头必须渲染出「变形形」区块',
    // 8,075 个补收词头（源头只有变形页、没有词头页）。不显示这块的话页面是全空的。
    hit: (e, html) => (e.forms.length > 0 && e.unifiedSenses.length === 0
      && !html.includes('>变形形<')
      ? `${e.forms.length} 个变形形一个都没渲染，页面是空的` : null),
  },
  {
    name: '🔴 有义项的词条不许挂「变形形」区块（会挤掉释义）',
    // `acoparse` 有 58 个变位形，挂在正常词条页上会撑爆版面 —— 组件里有这个前置条件。
    hit: (e, html) => (e.unifiedSenses.length > 0 && html.includes('>变形形<')
      ? '有释义却还铺了变形形' : null),
  },
  {
    name: '🔴 被修掉的伪原形不许出现在页面上',
    // wiktextract 把 `desemejado`+`se` 粘成 `desemejadose`；`tú and vos` 是英文泄漏。
    // 判据问**库里真藏/真重指了什么**，不复制一份名单。
    hit: (_e, html) => {
      const t = visibleText(html);
      const leak = BAD_BASES.filter((b) => t.includes(`${b} 的 `));
      return leak.length ? `页面上出现了伪原形「${leak[0]}」` : null;
    },
  },
  {
    name: '🔴 音标有值就必须渲染出来',
    hit: (e, html) => (e.phonetic && !html.includes('phonetic-value')
      ? '有音标却没渲染音标行' : null),
  },
  {
    name: '🔴 组件自己挑中的例句必须渲染出来',
    // ⚠️ 判据必须**照组件自己的挑选规则**：每条义项 `slice(0,3)`、未挂靠的 `slice(0,6)`。
    //    第一版写成「每条例句都要出现」⇒ `lo` 报红，而它的义项 3813 有 5 条例句、
    //    组件有意只铺 3 条。**那是我的尺子没算进有意截断，不是缺陷**（A33 先查尺子）。
    hit: (e, html) => {
      const t = visibleText(html);
      const want: string[] = [];
      for (const s of e.unifiedSenses) {   // 折叠已去掉，全部义项都铺例句
        for (const x of e.examples.filter((y) => y.senseId === s.id).slice(0, 3)) want.push(x.text);
      }
      for (const x of e.examples.filter((y) => !y.senseId).slice(0, 6)) want.push(x.text);
      const miss = want.filter((x) => x && !t.includes(x.slice(0, 24)));
      return miss.length ? `${miss.length} 条组件挑中的例句没渲染` : null;
    },
  },
  {
    // 🔴🔴 **2026-09-13 新增，因为这一排今天才第一次对用户可见。**
    //    在此之前 es 的真人录音被 `SHOW_HUMAN_AUDIO` 挡着，库里 11,203 条
    //    一条都渲染不出来 —— 而这道闸从 2026-08-20 建起就没有一条检查盯着它，
    //    等于 `french.ts` 那次「39 万条录音 `FROM audio` 出现 0 次」的翻版：
    //    **没人看见的东西，也没有闸在看**。开关一删，闸必须同时补上。
    // ⚠️ 期望条数走展示层自己那份 `capAudios`（每地区 ≤2、总数 ≤6），
    //    **不在这里另写一份限量规则** —— pt/de 两轮都栽在闸自算一份、限量一改就报假红。
    // ⚠️ 判据查 `.audio-chip` 不查 `<audio>`：`HumanAudioRow` 的播放走 JS `new Audio()`，
    //    HTML 里根本没有 `<audio>` 标签。
    name: '🔴 有真人录音却没渲染 / 数量对不上',
    hit: (e, html) => {
      const want = capAudios(e.audios ?? []).length;
      const got = (html.match(/class="audio-chip/g) || []).length;
      return want > 0 && got !== want ? `可渲染录音 ${want} 条，页面上 ${got} 个播放按钮` : null;
    },
  },
  {
    // 🔴 2026-09-13：录音地区在库里是**英文/西文原名**（`Spain` / `Venezuela` / `Chiloé`），
    //    映射不到 `ES_REGION_LABELS` 就原样印在中文词典页上。
    //    （it 那边有同形状的一条：「录音地区不许把法语原文印出来」。）
    // ⚠️ 判据不能写成「标签里不许出现拉丁字母」—— 无地区的录音**有意**退到录音人名
    //    （`Marreromarco` 这种），那是源头给的事实，不是漏译。
    //    ⇒ 白名单是：映射表的**译名** ∪ 本词条录音的**录音人名** ∪「未标注」。
    // ⚠️ 同名按钮会带上 ` · 录音人` 后缀，比之前先劈掉。
    name: '🔴 录音地区必须有中文标签（不许把原名印出来）',
    hit: (e, html) => {
      const zh = new Set(Object.values(ES_REGION_LABELS));
      const speakers = new Set((e.audios ?? []).map((a) => (a.speaker || '').replace(/_/g, ' ')));
      const shown = [...html.matchAll(/class="audio-region">([^<]*)</g)].map((m) => m[1]);
      const bad = shown.map((x) => x.split(' · ')[0])
        .filter((x) => x && x !== '未标注' && !zh.has(x) && !speakers.has(x));
      return bad.length ? `录音地区没有中文标签：${[...new Set(bad)].join(', ')}` : null;
    },
  },
  {
    name: '页面上不许出现 undefined / [object Object]（不含源语言原文）',
    // ⚠️ **先剥掉源语言原文块再查**。`espacio` 的英文 gloss 里就写着
    //    "space; course; period (an **undefined** period of time)" —— 那是真内容，不是缺陷。
    //    第一版直接在全文里搜 `undefined` ⇒ 假红。**判据要排除我们没写的那部分文本**。
    hit: (_e, html) => {
      const stripped = html
        .replace(/<div class="sense-src"[\s\S]*?<\/div>/g, '')   // EN/ES 原文锚点
        .replace(/<div class="ex-es"[\s\S]*?<\/div>/g, '')       // 例句原文
        .replace(/<div class="colloc-text"[\s\S]*?<\/div>/g, '');
      const t = visibleText(stripped);
      // 🔴 2026-09-13：`NaN` 不能用 `includes` 查。取样面扩到「有录音的 9,709 个词形」后
      //    `salitre` 当场报红 —— 它的中文详解里写着 **NaNO₂**（亚硝酸钠的化学式），
      //    那是真内容。判据要的是 React 把一个 `NaN` 数值印出来，那种情况 `NaN` 是
      //    **独立词**；夹在字母数字中间的一律不是。（`[[criteria-narrower-than-you-think]]`：
      //    判据比它要描述的东西宽 —— 这一条今天已经是第二次了。）
      const bad = ['undefined', '[object Object]'].filter((x) => t.includes(x));
      if (/(?<![A-Za-z0-9])NaN(?![A-Za-z0-9])/.test(t)) bad.push('NaN');
      return bad.length ? `页面文字里出现 ${bad.join(', ')}` : null;
    },
  },
];

/** 库里真正被藏掉或重指掉的伪原形 —— 判据取自数据，不写死名单。 */
const BAD_BASES: string[] = (db.prepare(
  `SELECT DISTINCT base FROM inflection
   WHERE (base_fixed IS NOT NULL OR COALESCE(hidden,0)=1) AND base <> ''`)
  .all() as Array<{ base: string }>).map((r) => r.base);

/** 高风险面：今天动过的三处各自的全集 + 一批常用词。 */
function targets(limit: number): string[] {
  const q = (sql: string) => (db.prepare(sql).all() as Array<{ word: string }>).map((r) => r.word);
  // 🔴 `--limit` 从头切 ⇒ **必覆盖面排最前**，否则小族被整段切掉、
  //    对应的检查永远命中 0，等于一条永远通过的检查。
  // ① 被修掉伪原形的那些词形（518 行）
  const famA = q(`SELECT DISTINCT d.word FROM inflection i JOIN dict d ON d.id=i.word_id
     WHERE i.base_fixed IS NOT NULL OR COALESCE(i.hidden,0)=1`);
  // ② 拼写变体：有 exchange、无 infl（3,881 行）
  const famB = q(`SELECT word FROM dict
     WHERE COALESCE(exchange,'')<>'' AND COALESCE(infl,'')=''`);
  // ③ 补收的无释义词头（8,075 个）
  const famC = q(`SELECT d.word FROM dict d WHERE d.phonetic_src='rule'
     AND d.definition IS NULL AND d.translation IS NULL AND d.is_lemma=1
     AND EXISTS(SELECT 1 FROM inflection i WHERE i.base_id=d.id) LIMIT 1200`);
  // ④ 有真人录音的全部词形（9,709 个）—— 2026-09-13 解开展示后新增的必覆盖面。
  //    ⚠️ 放进 `must` 而不是下面的 `set`：`set` 排在 `must` 之后，而变异验证只取
  //    `words.slice(0, 4000)`，①②③ 就已经 5,599 个 ⇒ 录音那条变异会报「可试对象 0」，
  //    也就是一条**永远通过**的假闸（上面 ①②③ 交错就是为了治这个，这里同理）。
  const famD = q(`SELECT DISTINCT word FROM audio`);
  // 🔴 **三族轮转交错，不是首尾相接。** 第一版按 ①②③ 顺序拼，而 ①② 就有 4,399 个 ——
  //    `--limit 3000` 和变异验证的 `slice(0,4000)` 都取不到 ③，
  //    「补收词头的变形形区块」那条变异报「可试对象 0」。
  //    交错之后任何一个 `--limit` 都会同时覆盖三族。
  const must: string[] = [];
  for (let i = 0; i < Math.max(famA.length, famB.length, famC.length, famD.length); i += 1) {
    if (i < famA.length) must.push(famA[i]);
    if (i < famB.length) must.push(famB[i]);
    if (i < famC.length) must.push(famC[i]);
    if (i < famD.length) must.push(famD[i]);
  }

  const set = new Set<string>();
  for (const w of q(`SELECT d.word FROM dict d
     ORDER BY COALESCE(d.freq_zipf,0) DESC LIMIT 3000`)) set.add(w);      // 常用词
  for (const w of q(`SELECT DISTINCT d.word FROM dict d JOIN sense s ON s.word_id=d.id
     WHERE s.pos IS NOT NULL LIMIT 3000`)) set.add(w);
  // ⚠️ es 的 `example` 用 `dict_id` 不是 `word_id`（意语那边是 `word_id`）——
  //    抄意语那份的列名会直接 SQL 报错。两个语种的表列**不是一套**。
  for (const w of q('SELECT DISTINCT word FROM example LIMIT 2000')) set.add(w);
  for (const w of q(`SELECT d.word FROM dict d JOIN inflection i ON i.word_id=d.id
     GROUP BY d.id HAVING count(*) > 3 LIMIT 2000`)) set.add(w);          // 多条变位说明
  for (const w of must) set.delete(w);
  const all = [...must, ...set];
  return limit > 0 ? all.slice(0, limit) : all;
}

function run(words: string[], quiet = false): number {
  const fails = new Map<string, string[]>();
  let n = 0;
  if (!quiet) console.log(`■ 待渲染 ${words.length.toLocaleString()} 个词条`);
  for (const w of words) {
    if (!quiet && n > 0 && n % 2000 === 0) {
      console.log(`   [${n.toLocaleString()}/${words.length.toLocaleString()}] 已发现不符 ` +
        `${[...fails.values()].reduce((a, b) => a + b.length, 0)}`);
    }
    const entry = svc.getEntry(w) as EsEntry | null;
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
    console.log(`\n═══ 西语展示层契约闸（渲染 ${n.toLocaleString()} 个词条）═══`);
    // ⚠️ 统计口径与展示口径必须一致 —— 「渲染直接抛错」不在 CHECKS 里，
    //    只打印 CHECKS 的键会出现「全绿但总数非零」（意语那份栽过）。
    const names = [...new Set([...CHECKS.map((c) => c.name), ...fails.keys()])];
    for (const name of names) {
      const f = fails.get(name) ?? [];
      console.log(`   ${f.length ? '🔴' : '✅'} ${name.padEnd(44)} ${f.length}`);
      for (const line of f.slice(0, 3)) console.log(`        ${line}`);
    }
  }
  return [...fails.values()].reduce((a, b) => a + b.length, 0);
}

/**
 * 变异验证：一条永远通过的检查等于没检查。
 *
 * 🔴 **两种变异别混**（意语那份 2026-08-18 重写时的教训）：
 *   ① data —— 改数据，只验**只看数据**的检查
 *   ② html —— 先正常渲染，再**把渲染结果打坏**。这才是「组件漏写了一行」的真实形状，
 *      而本文件里大多数检查问的正是「组件有没有把这个字段渲染出来」。
 *      只做 ① 的话，改完数据组件照样忠实渲染 ⇒ 那些变异**在构造上就不可能红**。
 */
function mutate(words: string[]): void {
  type DataCase = [string, (e: EsEntry) => void, ((e: EsEntry) => boolean)?];
  type HtmlCase = [string, (html: string) => string, (e: EsEntry) => boolean];

  const dataCases: DataCase[] = [
    ['给一条义项塞映射不出来的词性',
     (e) => { if (e.unifiedSenses[0]) e.unifiedSenses[0].pos = 'zzz_unknown'; },
     (e) => e.unifiedSenses.length > 0],
    ['把中文换成 undefined 字样',
     (e) => { if (e.unifiedSenses[0]) e.unifiedSenses[0].title = 'undefined'; },
     (e) => e.unifiedSenses.length > 0],
    ['🔴 把伪原形塞回变位说明',
     (e) => { e.inflNotes = [`${BAD_BASES[0]} 的 过去分词`]; },
     (e) => e.baseForms.length > 0],
    // ⚠️ 这条只能做成**数据**变异：库里的地区取值现在全都映射得到（2026-09-13 补完
    //    `Chiloé` 之后），真实数据里已经没有能触发它的词 ⇒ 改 HTML 的话「可试对象 0」。
    ['🔴 录音地区给一个映射表里没有的原名',
     (e) => { if (e.audios[0]) { e.audios[0].region = 'Neverland'; e.audios[0].speaker = null; } },
     (e) => capAudios(e.audios ?? []).length > 0],
  ];

  const htmlCases: HtmlCase[] = [
    ['组件漏渲染义项中文', (h) => h.replace(/<div class="sense-zh">[\s\S]*?<\/div>/g, ''),
     (e) => e.unifiedSenses.some((s) => !!s.title)],
    ['组件漏渲染整个释义区块', (h) => h.replace(/>释义</g, '>x<'),
     (e) => e.unifiedSenses.length > 0],
    ['组件漏渲染变位说明', (h) => h.replace(/<ul class="infl-notes">[\s\S]*?<\/ul>/g, ''),
     (e) => e.inflNotes.length > 0],
    ['🔴 拼写变体被写成「变位形式」', (h) => h.replace(/>参见</g, '>变位形式<'),
     (e) => e.baseForms.length > 0 && e.inflNotes.length === 0],
    ['🔴 变位形式被写成「参见」', (h) => h.replace(/>变位形式</g, '>参见<'),
     (e) => e.inflNotes.length > 0],
    ['🔴 补收词头的「变形形」区块没渲染', (h) => h.replace(/>变形形</g, '>x<'),
     (e) => e.forms.length > 0 && e.unifiedSenses.length === 0],
    ['组件漏渲染音标', (h) => h.replace(/phonetic-value/g, 'x-value'),
     (e) => !!e.phonetic],
    ['组件漏渲染例句', (h) => h.replace(/<div class="ex-es"[^>]*>[\s\S]*?<\/div>/g, ''),
     (e) => e.examples.length > 0],
    ['🔴 组件漏渲染真人录音行', (h) => h.replace(/class="audio-chip/g, 'class="x-chip'),
     (e) => capAudios(e.audios ?? []).length > 0],
  ];

  console.log('\n═══ 变异验证 ═══');
  let caught = 0;
  const total = dataCases.length + htmlCases.length;

  for (const [name, mut, need] of dataCases) {
    let red = false; let tried = 0;
    for (const w of words) {
      const e = svc.getEntry(w) as EsEntry | null;
      if (!e || (need && !need(e))) continue;
      tried += 1;
      mut(e);
      if (CHECKS.some((c) => c.hit(e, render(e)))) { red = true; break; }
    }
    caught += red ? 1 : 0;
    console.log(`   ${red ? '✅' : '🔴'} ${('[数据] ' + name).padEnd(40)} ` +
      `${red ? '闸红了（对）' : `闸没红 —— 这条闸是假的（可试对象 ${tried}）`}`);
  }

  for (const [name, damage, need] of htmlCases) {
    let red = false; let tried = 0;
    for (const w of words) {
      const e = svc.getEntry(w) as EsEntry | null;
      if (!e || !need(e)) continue;
      tried += 1;
      const broken = damage(render(e));
      if (CHECKS.some((c) => c.hit(e, broken))) { red = true; break; }
    }
    caught += red ? 1 : 0;
    // ⚠️ 变异没触发时**先查变异对不对**。`tried=0` 说明这批词里根本没有能触发的对象，
    //    那是取样面的问题，不是闸的问题（今天已经在这上面栽了四次）。
    console.log(`   ${red ? '✅' : '🔴'} ${('[渲染] ' + name).padEnd(40)} ` +
      `${red ? '闸红了（对）' : `闸没红 —— 这条闸是假的（可试对象 ${tried}）`}`);
  }

  console.log(`\n   变异验证 ${caught}/${total}`);
  if (caught !== total) process.exit(1);
}

const argv = process.argv.slice(2);
const li = argv.indexOf('--limit');
const limit = li >= 0 ? Number(argv[li + 1]) : 0;
const words = targets(limit);

if (argv.includes('--mutate')) {
  mutate(words.slice(0, 4000));
} else {
  const bad = run(words);
  console.log(`\n   ${bad === 0 ? '✅ 全部通过' : `🔴 ${bad} 处不符`}`);
  process.exit(bad === 0 ? 0 : 1);
}
