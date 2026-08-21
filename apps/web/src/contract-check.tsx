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
import { ItalianEntryView, groupItSenses, getInitialLang, readingBelongsTo } from './App';

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
    // 2026-08-19：`dict.plural` 单列装不下双复数（`braccio` 的 braccia/bracci），
    // 接口改成给 `plurals[]` 之后，组件必须**全部铺出来**——少铺一个就等于告诉用户它不存在
    name: '🔴 该显示的复数形都必须全部渲染出来',
    hit: (e, html) => {
      const t = visibleText(html);
      const isNoun = !!e.pos && e.pos.split('/').some((p) => p === 'n' || p === 'name');
      if (!isNoun) return null;
      // 🔴 2026-08-21：必须带上 A97 的归属守卫，否则这条闸**比实现更严 = 假红**。
      //    全量取样时报了 119 处，`ZTL`(缩写)、`buon senso`(词组) 这些词的
      //    `scope` 里混着非 NOMINAL 词类，组件**有意**不渲染性/复数徽标
      //    （`buon senso` 库里那个复数 `buon sensi` 本身就是错的，正确是 `buoni sensi`）。
      //    ⚠️ 这不是放宽闸：它防的仍然是「组件只铺了第一个复数形」，
      //       变异照样能逮到 —— 那些词的 scope 全是 NOMINAL。
      const NOMINAL = new Set(['noun', 'name', 'adj']);
      const scope = e.posWithSenses ?? [];
      if (scope.length > 0 && !scope.every((p) => NOMINAL.has(p))) return null;
      const miss = e.plurals.filter((p) => !t.includes(p.form));
      return miss.length ? `${miss.length} 个复数形没渲染：${miss.map((p) => p.form).join('、')}` : null;
    },
  },
  {
    // 🔴 `plural_gender` 的语义是**异性复数**；与词头性别相同却渲染出性别徽标 = 假信息
    name: '🔴 不许渲染出与词头同性别的「异性复数」',
    hit: (e) => {
      const bad = e.plurals.filter((p) => p.gender && p.gender === e.gender);
      return bad.length ? `${bad.map((p) => p.form).join('、')} 标了与词头相同的性别` : null;
    },
  },
  {
    // 2026-08-19：同形异读词（`subito` 副词 ˈsubito / 动词 suˈbito）把读音标在**对应那组义项**
    // 的组头上。接口给了 `readings[].entryId`，组件漏渲染就等于用户仍然分不清哪个读音配哪组。
    // ⚠️ 只断言「**专属**于某个词条、且那个词条确实有义项组」的读音 ——
    //    共用读音（entryId=null）本来就只在词头显示，不该出现在组头。
    name: '🔴 专属于某组义项的读音必须标在那一组上',
    // 🔴 判据必须与组件**用同一个 `groupItSenses`**（所以它是 export 的）。
    //    第一版我按「义项的 entryId 集合」自己算了一遍，报了 67 条假红 ——
    //    那些义项 `pos` 是空的（全库 1.9%），组头根本不渲染、没地方挂读音，
    //    而读音在词头那行已经显示过了。**尺子错，不是组件错**（A33）。
    hit: (e, html) => {
      const grps = groupItSenses(e.senses as never);
      if (grps.length < 2) return null;              // 单组：词头那行已经显示过
      const all = grps.map((g) => g.entryId);
      const want = grps.filter((g) => g.pos).flatMap((g) =>
        e.readings.filter((r) => readingBelongsTo(r as never, g.entryId, all)).slice(0, 1));
      if (want.length === 0) return null;
      const shown = [...html.matchAll(/class="pos-group-ipa">([^<]*)</g)].map((m) => m[1]);
      const miss = want.filter((r) => !shown.some((x) => x.includes(r.ipa)));
      return miss.length ? `${miss.length} 条专属读音没标到组头：${miss[0].ipa}` : null;
    },
  },
  {
    name: '页面上不许出现 undefined / [object Object]',
    // ⚠️ 判据里**不能有 `null`**：意语 `null'` 是 `nulla` 的省音形式，**词形本身**就长这样。
    //    第一版拿裸串判报了它；第二版试图"先剔除词头和释义再判"，页面上仍有别处出现，还是误报。
    //    ⇒ 把 `null` 从判据里去掉。
    // ⚠️ 2026-08-19 又中一次，同一个形状：`indefinito` / `imprecisato` 的**英文释义原文**
    //    就是 "undefined, unresolved" —— 取样面从 2 万涨到 3.9 万才撞上。
    //    ⇒ 扫描前先剔掉 `.sense-src`（EN/IT 原文）那几块：**那是源头的字，不是我们渲染的值**，
    //       我们只该为自己生成的东西负责。剔完 `undefined` 仍然是硬判据。
    hit: (_e, html) => {
      const ours = html.replace(/<div class="sense-src"[\s\S]*?<\/div>/g, '');
      const t = visibleText(ours);
      const bad = ['undefined', '[object Object]', 'NaN'].filter((x) => t.includes(x));
      return bad.length ? `渲染出 ${bad.join('、')}` : null;
    },

  },
  {
    // 2026-08-19：`example.hidden` 是新加的列（87 条古法语/拉丁/法语释义被当成了意语例句）。
    // 🔴 加了列还得**读取路径也认它**，否则就是「数据改了、页面照旧」——
    //    `fix-regression-and-gate` 记的第二种机制：查写入列永远绿，用户看到的是错的。
    //    ⇒ 这一条直接问页面：藏起来的例句原文**不许出现在渲染结果里**。
    name: '🔴 藏起来的例句不许渲染出来',
    hit: (e, html) => {
      const hid = hiddenExamples(e.word);
      if (hid.length === 0) return null;
      const t = visibleText(html);
      const leak = hid.filter((x) => t.includes(x.slice(0, 40)));
      return leak.length ? `${leak.length} 条已藏例句漏进页面：${leak[0].slice(0, 40)}` : null;
    },
  },

  // ══ 2026-08-21 点测评审：修在**展示层**的四条 ═══════════════════════════
  // 🔴 这四条**只能在这里守**。回归闸查的是数据库，而修复做在 `italian.ts`/`App.tsx`
  //    里 —— 谁把守卫删掉，回归闸照样全绿（那正是「被绕过」）。
  //    ⇒ 数据层的数字进了回归闸的 ACCEPT 基线，用户看得见的部分由这四条负责。
  {
    name: '🔴 变形提示不许重复成多行',
    hit: (e, html) => {
      const items = [...html.matchAll(/<li[^>]*>([^<]*)<\/li>/g)].map((m) => m[1]);
      const dup = items.filter((x, i) => items.indexOf(x) !== i);
      return dup.length ? `重复 ${dup.length} 行，例：${dup[0]}` : null;
    },
  },
  {
    name: '🔴 同一个搭配不许出现两次',
    hit: (e) => {
      const t = e.collocations.map((c) => c.text);
      const dup = t.filter((x, i) => t.indexOf(x) !== i);
      return dup.length ? `重复 ${dup.length} 条，例：${dup[0]}` : null;
    },
  },
  {
    // `la` 的「阳性」是名词「音名拉」的性，冠词/代词是阴性 —— 顶在词头就是错的。
    // ⚠️ 判据要和 `App.tsx` 的守卫**同一个定义**：`posWithSenses.length >= 2`。
    name: '🔴 词头徽标归属不明时不许显示性/复数/助动词',
    hit: (e, html) => {
      // 判据与 App.tsx 的守卫**同一个定义**：名词/专名/形容词共享性数系统，
      // 混进没有性数的词类（冠词/代词/介词/动词）才叫归属不明。
      const NOMINAL = new Set(['noun', 'name', 'adj']);
      const scope = e.posWithSenses ?? [];
      if (scope.length === 0) return null;
      const badges = html.match(/<div class="entry-meta-row entry-badges">[\s\S]*?<\/div>\s*(?=<)/);
      if (!badges) return null;
      const shown = [...badges[0].matchAll(/class="badge (g|plural|num|aux|conj) /g)].map((m) => m[1]);
      const bad: string[] = [];
      if (!scope.every((p) => NOMINAL.has(p))) {
        bad.push(...shown.filter((x) => x === 'g' || x === 'plural' || x === 'num'));
      }
      if (!scope.includes('verb')) {
        bad.push(...shown.filter((x) => x === 'aux' || x === 'conj'));
      }
      return bad.length ? `归属不明却渲染了徽标：${[...new Set(bad)].join('、')}` : null;
    },
  },
  {
    // `sentirsi` **就是** `sentire` 的自反形式，说它「与上面的释义不是同一个词」是错的。
    name: '🔴 自反形式不许被说成「不是同一个词」',
    hit: (e, html) => {
      const refl = e.reflexiveOf ?? [];
      if (refl.length === 0 || e.baseForms.length === 0) return null;
      if (!e.baseForms.every((b) => refl.includes(b))) return null;
      return visibleText(html).includes('不是同一个词')
        ? `${e.word} 是 ${refl.join('、')} 的自反形式，却被说成不是同一个词` : null;
    },
  },
  {
    // `fix_unclosed_paren` 藏起来的 602 条说明片段，不许从关系区漏出来。
    name: '🔴 关系区不许出现括号残渣',
    hit: (e, html) => {
      const items = [...html.matchAll(/class="rel-(?:link|plain)"[^>]*>([^<]*)</g)].map((m) => m[1]);
      const bad = items.filter((x) => (x.includes('(') !== x.includes(')')));
      return bad.length ? `${bad.length} 条括号残渣，例：${bad[0]}` : null;
    },
  },
];

/** 某个词形被藏起来的例句原文。判据要问**库里真藏了什么**，不复制一份名单。 */
const hiddenExQuery = db.prepare(
  'SELECT text FROM example WHERE word = ? AND COALESCE(hidden,0) = 1');
function hiddenExamples(word: string): string[] {
  return (hiddenExQuery.all(word) as Array<{ text: string }>).map((r) => r.text);
}

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
  // 🔴 藏起来的例句那 87 条 —— **全量**进取样面。
  //    不进来的话「藏起来的例句不许渲染」那条检查在多数取样下命中 0 条，
  //    等于一条永远通过的检查（`verification-gates-not-sampling`）。
  for (const w of q(`SELECT DISTINCT word FROM example WHERE COALESCE(hidden,0)=1`)) set.add(w);
  for (const w of q(`SELECT DISTINCT word FROM audio LIMIT 2000`)) set.add(w);
  for (const w of q(`SELECT d.word FROM dict d JOIN sense_relation r ON r.word_id=d.id
     GROUP BY d.id HAVING count(*) > 12 LIMIT 1500`)) set.add(w);   // 一定会触发截断
  for (const w of q(`SELECT d.word FROM dict d JOIN pronunciation p ON p.word_id=d.id
     GROUP BY d.id HAVING count(*) > 1 LIMIT 2000`)) set.add(w);    // 多读音
  // 双复数（braccia/bracci 那族，1,833 个）—— 全部铺进取样面
  for (const w of q(`SELECT b.word FROM inflection i JOIN dict b ON b.id=i.base_id
     WHERE i.label_zh='复数' GROUP BY b.id HAVING count(DISTINCT i.word_id) > 1`)) set.add(w);
  // 🔴 `--limit` 是从头切的 —— 排在后面的取样面会被整段切掉。
  //    「藏起来的例句」那族只有 87 条，切没了检查就永远命中 0 ⇒ **必覆盖面排最前**。
  const must = q(`SELECT DISTINCT word FROM example WHERE COALESCE(hidden,0)=1`);
  for (const w of must) set.delete(w);
  const all = [...must, ...set];
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
    // 2026-08-21：搭配去重做在 `italian.ts` 的 colsQuery 侧，这条检查读的是
    // `e.collocations` 这个**数据结果**，所以变异也打在数据上（不是 html）。
    ['把一条搭配复制成两条',
     (e) => { if (e.collocations[0]) e.collocations.push({ ...e.collocations[0] }); },
     (e) => e.collocations.length > 0],
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
    ['组件漏把专属读音标到组头', (h) => h.replace(/<span class="pos-group-ipa">[\s\S]*?<\/span>/g, ''),
     (e) => {
       const grps = groupItSenses(e.senses as never);
       return grps.length > 1 && grps.filter((g) => g.pos).some((g) =>
         e.readings.some((r) => readingBelongsTo(r as never, g.entryId,
           groupItSenses(e.senses as never).map((x) => x.entryId))));
     }],
    ['组件只铺了第一个复数形', (h) => {
      const parts = [...h.matchAll(/<span class="badge plural"[\s\S]*?<\/span>/g)];
      return parts.length > 1 ? h.replace(parts[parts.length - 1][0], '') : h;
    }, (e) => e.plurals.length > 1],
    ['组件漏说关系被截断了', (h) => h.replace(/<span class="rel-more">[^<]*<\/span>/g, ''),
     (e) => e.relations.some((g) => g.total > g.targets.length)],
    ['组件把录音地区的法语原文直接印出来',
     (h) => h.replace(/<span class="audio-region">[^<]*<\/span>/,
                      '<span class="audio-region">Monopoli (Italie)</span>'),
     (e) => e.audios.some((a) => a.region === 'Monopoli (Italie)')],
    // ── 2026-08-21 点测评审那四条展示层修复的变异 ──────────────────────
    ['组件把变形提示重复渲染了',
     (h) => h.replace(/(<ul class="infl-notes">)(<li[^>]*>[^<]*<\/li>)/, '$1$2$2'),
     (e) => e.inflNotes.length > 0],
    ['组件在归属不明时仍渲染性别徽标',
     (h) => h.replace(/(<div class="entry-meta-row entry-badges">)/,
                      '$1<span class="badge g g-m">阳性</span>'),
     // 只在**确实归属不明**的词上打，否则造出来的不是缺陷
     (e) => {
       const N = new Set(['noun', 'name', 'adj']);
       const s = e.posWithSenses ?? [];
       return s.length > 0 && !s.every((p) => N.has(p));
     }],
    ['组件把自反形式说成不是同一个词',
     (h) => h.replace(/下面是 /, '下面这些与上面的释义不是同一个词 —— '),
     (e) => {
       const r = e.reflexiveOf ?? [];
       return r.length > 0 && e.baseForms.length > 0 && e.baseForms.every((b) => r.includes(b));
     }],
    ['组件把括号残渣渲染进关系区',
     (h) => h.replace(/(class="rel-plain">)([^<]*)(<)/, '$1kiwi australe ($3'),
     (e) => e.relations.some((g) => g.targets.some((t) => !t.linkable))],
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

/**
 * 语种码守卫：存在 localStorage 里的 `dict-lang` 必须先跟缓存的语言表核一次。
 *
 * 这一条不按词条循环 —— 它问的不是"某个词渲染对不对"，而是**首帧用哪个语种去查**。
 * `/api/langs` 回来之后确实会核对，但那是一个网络往返之后的事；在那之前发出去的
 * 请求会落到后端的"未知语种回退默认语种"分支 —— 后端行为是对的，
 * 可用户看到的是另一门语言的结果，而语言栏高亮的是他选的那个。
 *
 * 三种输入各断言一次：**合法码放行 / 非法码回退 / 表为空时不拦**。
 * 🔴 第三条最容易被"顺手写严"破坏：首次访问时缓存表是空的，
 *    那时没有可信判据，拦了等于永远回退到 en。
 */
function langGuard(): number {
  const cases: [string, string | null, string | null, string][] = [
    ['合法码原样放行', 'it', '[{"code":"it"},{"code":"en"}]', 'it'],
    ['已下线/拼错的码回退', 'zz', '[{"code":"it"},{"code":"en"}]', 'en'],
    ['缓存表为空时不拦（首次访问）', 'it', null, 'it'],
    ['没存过时用默认', null, '[{"code":"it"}]', 'en'],
  ];
  let bad = 0;
  for (const [name, saved, langs, want] of cases) {
    const store: Record<string, string> = {};
    if (saved !== null) store['dict-lang'] = saved;
    if (langs !== null) store['dict-langs'] = langs;
    (globalThis as { localStorage?: unknown }).localStorage = {
      getItem: (k: string) => (k in store ? store[k] : null),
      setItem: () => {},
    };
    const got = getInitialLang();
    const ok = got === want;
    if (!ok) bad++;
    console.log(`   ${ok ? '✅' : '🔴'} ${name.padEnd(28)} → ${got}（应 ${want}）`);
  }
  delete (globalThis as { localStorage?: unknown }).localStorage;
  return bad;
}

const argv = process.argv.slice(2);
const limit = argv.includes('--limit') ? Number(argv[argv.indexOf('--limit') + 1]) : 0;
const words = targets(limit);
if (argv.includes('--lang')) {
  console.log('\n═══ 语种码守卫 ═══');
  process.exit(langGuard() === 0 ? 0 : 1);
} else if (argv.includes('--mutate')) {
  mutate(words);
} else {
  console.log('\n═══ 语种码守卫 ═══');
  const langBad = langGuard();
  const bad = run(words) + langBad;
  console.log(`\n   ${bad === 0 ? '✅ 全部通过' : `🔴 共 ${bad} 处不符`}`);
  process.exit(bad === 0 ? 0 : 1);
}
