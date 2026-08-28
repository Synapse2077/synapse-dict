/**
 * 法语展示层契约闸：把真实数据喂进 React 组件、渲染成 HTML，再断言。2026-08-26（阶段 8）。
 *
 * ═══ 为什么数据层的回归闸不够 ═══
 * `fr/tests/test_no_regression.py` 的 L 组本想守「App 有没有接上 v3」，
 * 但它查的是**数据库** —— 而它要守的东西在 TypeScript 里。
 * `french.ts` 改没改、组件里那一行写没写，SQL 一个字都看不见。
 *
 * it 已经用三个真实案例证明了这一类缺陷**只在渲染之后才存在**：
 *   `TVTB` 有两条义项却整块释义不渲染 —— 组件里一个 `entry.isLemma &&` 挡住 8,552 个词形，
 *   而接口返回完全正确。查库查接口都看不见。
 * 更近的一次：意语原文导了 89,531 条、接口一直在返回，**组件那一行我漏了写** ——
 *   用户问了才发现。fr 的 `s.fr`（法语原文定义，96.0% 覆盖）是**同一个形状**，
 *   本文件为它专设一条。
 *
 * ═══ 用法（仓库根目录）═══
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-fr.tsx
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-fr.tsx --limit 500
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-fr.tsx --mutate
 *
 * ⚠️ `--tsconfig` 不能省：仓库根目录没有 tsconfig.json，tsx 找不到 jsx: "react-jsx"，
 *    会退回经典运行时并报 `React is not defined`。
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { getService, type FrenchEntry } from '@synapse-dict/dict-core';
import {
  POS_LABELS, FR_REGION_LABELS, FR_REGION_CODE_LABELS, REGISTER_LABELS, TOPIC_LABELS,
} from '@synapse-dict/dict-labels';
import { FrenchEntryView, groupFrSenses, frReadingSlot, frHeadGender} from './App';

// 🔴 走 `getService('fr')` —— 与 API **同一条代码路径、同一个数据目录推算逻辑**。
const svc = getService('fr') as unknown as {
  getEntry(w: string): unknown;
  db: { prepare(s: string): { all(...a: unknown[]): unknown[] } };
};
const db = svc.db;

type Check = { name: string; hit: (e: FrenchEntry, html: string) => string | null };

function render(entry: FrenchEntry): string {
  return renderToStaticMarkup(createElement(FrenchEntryView, {
    entry: entry as never,
    speakLocale: 'fr-FR',
    onWord: () => {},
    speak: () => {},
  }));
}

// 🔴 比对**两侧都要归一空白**。第一版只归一了页面那侧，
//    而例句原文/中文里带换行（`livre` 那条是一整段对话），
//    折成空格之后就对不上了 —— 报了 13 条**假红，组件是对的**。
//    与 `[[criteria-narrower-than-you-think]]` 同一天第五次。
function norm(s: string): string {
  return s.replace(/\s+/g, ' ').trim();
}

// 🔴 组件把 kaikki 的上标记法 `^([X])` 渲染成 `[X]`，所以比对前要做同样的变换 ——
//    否则带编者注的例句永远「对不上」。
// 🔴 而且必须**整串比对，不能取前缀**：第一版取前 24 字符，
//    `-ane` 的 5 条例句前缀完全相同（`Dans la série des …`），
//    组件只渲染前 3 条，第 4 条却被判成「渲染了但没中文」—— 2 条假红。
//    ⇒ 「这条渲染了吗」的判据必须能**区分开同族的兄弟**。
function renderedIn(t: string, raw: string): boolean {
  // 🔴 **去掉全部空白再比**。组件把 `^([sic])` 拆成 span+sup 两个元素，
  //    `visibleText` 在标签之间插空格 ⇒ 页面上是 `rabattent [sic]`，
  //    而我算出来的是 `rabattent[sic]` —— 差一个空格，报了 1 条假红（`immutable`）。
  const strip = (x: string) => x.replace(/\^\((\[[^\])]*\]|[^\])]*)\)/g, '$1')
    .replace(/\[\[w:[^|\]]*\|([^\]]*)\]\]/g, '$1')
    .replace(/\s+/g, '');
  return strip(t).includes(strip(raw));
}

function visibleText(html: string): string {
  return html.replace(/<[^>]*>/g, ' ').replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"').replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/\s+/g, ' ');
}

const CHECKS: Check[] = [
  // ── 一、阶段 8 接上来的四样，各一条「接口给了、页面必须显示出来」──────────
  {
    name: '🔴 有可见义项就必须渲染出「释义」区块',
    hit: (e, html) => (e.senses.length > 0 && !html.includes('释义'))
      ? `有 ${e.senses.length} 条义项却没有释义区块` : null,
  },
  {
    name: '🔴 每条义项的中文都必须出现在页面文字里',
    hit: (e, html) => {
      const t = visibleText(html);
      const miss = e.senses.filter((s) => s.zh && !t.includes(norm(s.zh)));
      return miss.length ? `${miss.length} 条中文没渲染，例：${miss[0].zh}` : null;
    },
  },
  {
    // 🔴 这一条对着 it 那次「89,531 条意语原文接口在返回、组件漏写一行」的形状设的。
    //    fr 的法语原文定义有 631,471 条（96.0%），漏渲染的话规模是它的 7 倍。
    name: '🔴 有法语原文定义的义项必须把原文渲染出来',
    hit: (e, html) => {
      const t = visibleText(html);
      // 🔴 与例句同一个坑：法语定义里也有上标记法（`Mettre en fiches. ^(Pas clair)`），
      //    组件拆成 span+sup 后 `visibleText` 在中间插空格 ⇒ 前缀比对差一个空格。
      //    ⇒ 统一走 `renderedIn`（去全部空白 + 同样的上标变换）。
      const miss = e.senses.filter((s) => s.fr && !renderedIn(t, s.fr));
      return miss.length ? `${miss.length} 条法语原文没渲染，例：${miss[0].fr?.slice(0, 30)}` : null;
    },
  },
  {
    // 🔴 阶段 5 补做的关系层（+300,611 行，2026-08-27）。
    //    `french.ts` 里原来有一句「fr 的 sense_relation 只有 alt_of 一种，所以不做
    //    相关词分组」—— 数据补完之后那句话就成了错的。这条闸盯住的正是
    //    `[[it-display-layer-stage8]]` 那个形状：**数据层全绿，而没人读它**。
    name: '🔴 接口给了语义关系，页面就必须渲染出「相关词」',
    hit: (e, html) => {
      if (e.relations.length === 0) return null;
      const t = visibleText(html);
      if (!html.includes('相关词')) return `有 ${e.relations.length} 组关系却没有相关词区块`;
      const first = e.relations[0].targets[0];
      return first && !t.includes(first.word)
        ? `第一组第一个目标词 ${first.word} 没渲染出来` : null;
    },
  },
  {
    // ⚠️ alt_of 走的是**另一条线**（词头「异体 →」那一行）。混进「相关词」就是
    //    把"这是同一个词的另一种拼法"说成"这是个近义词"。
    name: '🔴 alt_of 不许混进相关词分组',
    hit: (e) => e.relations.some((g) => g.kind === 'alt_of')
      ? 'alt_of 出现在 relations 里（它属于词头的异体指针那条线）' : null,
  },
  {
    // 🔴 2026-08-28 第二轮外审：`fillâtre` 的 `beau-fils` 同时挂在「近义」和「下位」。
    //    全库 616 对（含 synonym 的那些）。`relationsOf` 现在让**具体关系**胜出。
    //    ⚠️ 这条只断言 synonym 与其他组不重叠 —— 不含 synonym 的 419 对
    //       （antonym+coordinate 等）是**有意保留**的，写死成"任意两组都不许重叠"
    //       就会天天报 419 条假红，那种闸最后一定被无视（PITFALLS E 组）。
    // 🔴 2026-08-28：`quelles` 的「阴性复数」印了四次（同一语法事实的四份跨版证言）。
    //    展示层去重，`inflection` 表一行不删。
    name: '🔴 变位形式不许出现重复的（原形+标签）',
    hit: (e) => {
      const seen = new Set<string>();
      for (const i of e.inflections) {
        const k = `${i.base}|${i.label ?? ''}`;
        if (seen.has(k)) return `变位形式重复：${k}`;
        seen.add(k);
      }
      return null;
    },
  },
  {
    name: '🔴 同一个目标词不许既在「近义」又在别的关系组里',
    hit: (e) => {
      const syn = e.relations.find((g) => g.kind === 'synonym');
      if (!syn) return null;
      const other = new Set(e.relations.filter((g) => g.kind !== 'synonym')
        .flatMap((g) => g.targets.map((t) => t.word)));
      const dup = syn.targets.find((t) => other.has(t.word));
      return dup ? `${dup.word} 同时出现在近义和另一个关系组里` : null;
    },
  },
  {
    name: '🔴 默认读音必须渲染出来',
    hit: (e, html) => (e.ipa && !visibleText(html).includes(e.ipa))
      ? `ipa=${e.ipa} 没出现在页面上` : null,
  },
  {
    // 🔴 收尾单 A1：连诵形是**真读音**（`les` 在元音前确实是 /le.z‿/），所以不删；
    //    但不标注就等于把语境变体当成另一个读音并排摆着，读者分不出来。
    //    这条闸盯的是「标签有没有被渲染出来」——数据标了、组件不读，就是白标。
    name: '🔴 连诵形读音必须带「连诵」标签',
    hit: (e, html) => {
      const li = e.readings.filter((r) => r.context === 'liaison');
      if (li.length === 0) return null;
      const t = visibleText(html);
      const shown = li.filter((r) => t.includes(r.ipa));
      return shown.length > 0 && !t.includes('连诵')
        ? `渲染了 ${shown.length} 条连诵形却没有「连诵」标签，例：${shown[0].ipa}` : null;
    },
  },
  {
    // 🔴 收尾单 A2：词头性别徽标必须跟义项走，不能跟词形级压平值走。
    //    `mari` 的 `dict.gender='mf'` 是 r1 丈夫(m) + r2 大麻(f) 合并出来的，
    //    印成「阴阳性」两边都不准。判据 `frHeadGender` 与组件共用同一份。
    name: '\u{1F534} 义项分别是阳/阴时，词头不许印「阴阳性」',
    // 🔴 判据必须锚在**词头徽标那个 class** 上，不能拿整页文本比。
    //    第一版拿 `visibleText(html).includes('阴阳性')` ⇒ `marine` 报红，
    //    而那个「阴阳性」根本不在词头，是**变位形式区块里内联原形 `marin` 的标签**
    //    （另一条渲染路径）。断言比它要断言的东西宽 ⇒ 报的是别处的事。
    hit: (e, html) => {
      const gs = [...new Set(e.senses.map((s) => s.gender).filter(Boolean))];
      if (!(gs.includes('m') && gs.includes('f'))) return null;
      return /class="badge g g-mf"/.test(html)
        ? `义项分别是 ${gs.join('/')}，词头徽标却印了「阴阳性」` : null;
    },
  },
  {
    // 🔴 这条第一版是「判据说该印 mf，页面上就必须有」—— **断言比组件宽**，
    //    当场报了 1 条假红（`a`）：它的 `frSensePos` 含 `pron`，而族 B 那条护栏
    //    规定「有别的带性词类在场就不印性别徽标」（法语冠词/限定词/代词也带性，
    //    且可能与名词的性相反）。判据只管**印哪个**，印不印还有 `isNoun` 把关。
    //    ⇒ 改成只查方向：**页面印出来的性别，必须就是判据算出来的那个**。
    name: '\u{1F534} 页面印出的性别徽标必须等于 frHeadGender 算出来的',
    hit: (e, html) => {
      const want = frHeadGender(e.gender, e.senses.map((s) => s.gender));
      const m = /class="badge g g-(mf|m|f)"/.exec(html);
      if (!m) return null;               // 没印 ⇒ 本条不管（印不印是 isNoun 的事）
      return m[1] === want ? null
        : `词头徽标印的是 ${m[1]}，判据算出来是 ${want ?? 'null（不该印）'}`;
    },
  },
  {
    // 阶段 5 的 740,366 条例句、99.9% 有中文 —— 全靠组件里那几行
    name: '🔴 挂到义项上的例句必须渲染出来',
    hit: (e, html) => {
      const t = visibleText(html);
      const attached = e.examples.filter((x) => x.senseId !== null);
      if (attached.length === 0) return null;
      // 组件对每条义项限 3 条，所以只要求「有一条出现」，不要求全部
      const anySense = new Set(e.senses.map((s) => s.id));
      const shown = attached.filter((x) => anySense.has(x.senseId as number))
        .some((x) => renderedIn(t, x.text));
      const should = attached.some((x) => anySense.has(x.senseId as number));
      return (should && !shown) ? `有 ${attached.length} 条挂上义项的例句，一条都没渲染` : null;
    },
  },
  {
    // 🔴 判据从「文本包含」换成**结构**：数渲染出来的 ex-fr 块与 ex-zh 块。
    //    文本包含在**近重复例句**上不可靠 —— `accuser` 有两条只差句末逗号的例句，
    //    组件渲染了长的那条，`includes` 就把短的也算成「渲染了」，
    //    再去找它那份略有不同的中文自然找不到 ⇒ 报了 50 条假红。
    //    同一天第三次栽在「用文本相似当身份判据」上（前两次：前 24 字符、带换行没归一）。
    //    ⇒ 「这一条渲染了吗」只能由**渲染结果的结构**回答，不能由文本猜。
    name: '🔴 渲染出来的例句必须带中文',
    hit: (e, html) => {
      // 组件里 ex-fr 与它的 ex-zh 是紧挨着的兄弟；没有中文的例句后面直接是块尾。
      const blocks = [...html.matchAll(/<div class="sense-example">([\s\S]*?)<\/div><\/div>|<div class="sense-example">([\s\S]*?)<\/div>/g)];
      const withFr = blocks.filter((b) => (b[0] ?? '').includes('ex-fr'));
      const noZh = withFr.filter((b) => !(b[0] ?? '').includes('ex-zh'));
      if (noZh.length === 0) return null;
      // 🔴 判据：**没中文的块数不许超过数据里本来就没中文的条数**。
      //    第一版写的是「这个词有任何一条例句带中文就算缺陷」—— 太宽，报 20 条假红：
      //    `-ail` 的 `éventer (“to ventilate”) → éventail (“fan”)` 是**构词式**，
      //    `-muche` 的 `trucmuche` 是单个词，本来就没有可翻的东西
      //    （= 记账里那 787 条「模型判定翻不了」，见 docs/FR_PLAN.md 阶段 5）。
      //    数上限而不是数「有没有」，才既能逮住「组件漏渲染中文」又不误伤已知空白。
      const noZhInData = e.examples.filter((x) => !x.zh).length;
      return noZh.length > noZhInData
        ? `${noZh.length} 个例句块没有中文块，而数据里只有 ${noZhInData} 条没中文` : null;
    },
  },
  {
    name: '🔴 异体指针（alt_of）必须渲染出来',
    hit: (e, html) => {
      const t = visibleText(html);
      const miss = e.altOf.filter((a) => !t.includes(a.target));
      return miss.length ? `${miss.length} 条 alt_of 没渲染，例：${miss[0].target}` : null;
    },
  },

  // ── 二、标签映射：不许把生标签甩给用户 ────────────────────────────────
  {
    name: '🔴 词性分组标题不许出现未映射的原始串',
    hit: (_e, html) => {
      const labels = new Set(Object.values(POS_LABELS));
      const raw = [...html.matchAll(/class="pos-group-label">([^<]*)</g)].map((m) => m[1]);
      const bad = raw.filter((x) => x && !labels.has(x));
      return bad.length ? `分组标题出现原始串：${[...new Set(bad)].join('、')}` : null;
    },
  },
  {
    name: '🔴 每条义项的词性都要能映射成中文标签',
    hit: (e) => {
      const bad = e.senses.map((s) => s.pos).filter((p): p is string => !!p && !POS_LABELS[p]);
      return bad.length ? `词性查不到中文标签：${[...new Set(bad)].join('、')}` : null;
    },
  },
  {
    // 🔴 2026-08-26：`FR_REGION_LABELS` 是七月按印象写的，全量取值 54 种它只覆盖一半，
    //    `North-America`/`Ancient-Rome` 这类会**生标签直接显示给用户**。
    //    这类「表不全」的缺陷数据闸查不出来 —— 只能靠把取值全查一遍，或者这条。
    // 🔴 族 C（2026-08-27）：领域标签 256,787 行是这一天才收进来的。
    //    映射不出中文，用户看到的就是 `ornithology` 这种英文原始串 ——
    //    **比不收更坏**。入库脚本已经只出版映射得出的值，这条是读取侧的复查
    //    （`[[fix-regression-and-gate]]`：闸要在写入侧和读取侧各查一次）。
    // 🔴 族 C 第二段（2026-08-27）：收了法文版标签之后，同一条义项会同时带上
    //    英语版的 `derogatory` 和法文版的 `pejorative` —— 键不同、**中文相同**。
    //    判重做在 `FrSenseChips` 里（按投影后的文字），这条闸在渲染结果上复查。
    name: '🔴 同一条义项的标签胶囊不许印出两个相同的中文',
    hit: (_e, html) => {
      const bad: string[] = [];
      for (const m of html.matchAll(/<span class="sense-chips">(.*?)<\/span><\/div>/g)) {
        const txt = Array.from(m[1].matchAll(/class="sense-chip [^"]*">([^<]*)</g))
          .map((x) => x[1]);
        const seen = new Set<string>();
        for (const t of txt) {
          if (seen.has(t)) bad.push(t);
          seen.add(t);
        }
      }
      return bad.length ? `重复胶囊：${[...new Set(bad)].join('、')}` : null;
    },
  },
  {
    name: '🔴 义项的领域标签都要能映射成中文',
    hit: (e) => {
      const bad = e.senses.flatMap((s) => (s.topics ?? []).filter((t) => !TOPIC_LABELS[t]));
      return bad.length ? `领域标签映射不出：${[...new Set(bad)].join('、')}` : null;
    },
  },
  {
    name: '🔴 义项的地区/语域标签都要能映射成中文',
    hit: (e) => {
      const bad = [
        ...e.senses.flatMap((s) => s.regions).filter((r) => !FR_REGION_LABELS[r]),
        ...e.senses.flatMap((s) => s.registers).filter((r) => !REGISTER_LABELS[r]),
      ];
      return bad.length ? `标签查不到中文：${[...new Set(bad)].join('、')}` : null;
    },
  },
  {
    // 🔴 读音的地区用的是**另一套词汇表**（fr-FR 代码），拿义项那张表查会落空
    name: '🔴 读音的地区代码都要能映射成中文',
    hit: (e) => {
      const bad = e.readings.map((r) => r.region)
        .filter((r): r is string => !!r && !FR_REGION_CODE_LABELS[r]);
      return bad.length ? `读音地区查不到中文：${[...new Set(bad)].join('、')}` : null;
    },
  },

  // ── 三、渲染出来的东西本身不许有残渣 ──────────────────────────────────
  {
    // 数据层回归闸盯的是表，这条盯的是**页面**。两边都绿才算真的没有。
    name: '🔴 页面上不许出现模板/脚注残渣',
    hit: (_e, html) => {
      const t = visibleText(html);
      const bad = ['{{', '}}', '[[', ']]', '^(['].filter((x) => t.includes(x));
      return bad.length ? `页面出现残渣：${bad.join(' ')}` : null;
    },
  },
  {
    // 🔴 我刚在 french.ts 里加的读音判重（全库 25,520 组同词同音标）。
    //    没有这条，判重被谁改回去了不会有人知道。
    // 🔴 族 D「读音归属」（2026-08-27）。判据**直接调组件用的那个函数**，
    //    不在这里另写一遍 —— `readingBelongsTo` 的注释里记着：判据分两份写，
    //    第一版闸自己算了一遍，报了 67 条假红。
    name: '🔴 每条读音恰好显示一处（词头行或某个词性组头）',
    hit: (e, html) => {
      // ⚠️ Node 里没有 DOM，只能用正则解字符串（本文件其余判据同样）。
      //    `phonetic-value` 只出现在词头那一行，`pos-group-ipa` 只出现在组头。
      const grab = (cls: string) =>
        new Set(Array.from(html.matchAll(new RegExp(`class="${cls}"[^>]*>([^<]*)<`, 'g')))
          .map((m) => m[1].replace(/^[/[]/, '').replace(/[/\]]$/, '')));
      const inHead = grab('phonetic-value');
      const inGroup = grab('pos-group-ipa');
      const poses = groupFrSenses(e.senses as never).map((g) => g.pos);
      const bad: string[] = [];
      for (const r of e.readings) {
        const slot = frReadingSlot(r as never, poses);
        // 词头行只展示 3 条、组头只展示 2 条（版面上限），所以只能断言**方向**：
        // 判为「归某个词性组」的读音，绝不许出现在词头行里。
        if (slot !== null && inHead.has(r.ipa) && !inGroup.has(r.ipa)) {
          bad.push(`${r.ipa}（属 ${slot}，却出现在词头行）`);
        }
      }
      return bad.length ? bad.join('；') : null;
    },
  },
  {
    name: '🔴 同一串音标不许在读音行里出现两次',
    hit: (e) => {
      const seen = new Set<string>();
      const dup = e.readings.filter((r) => {
        if (seen.has(r.ipa)) return true;
        seen.add(r.ipa);
        return false;
      });
      return dup.length ? `读音重复：${dup.map((r) => r.ipa).join('、')}` : null;
    },
  },
  {
    // 变形/异体的目标点不点得动，判据必须与 getEntry 的解析路径一致
    name: '🔴 标成可点的目标必须真的查得到',
    hit: (e) => {
      const bad = [...e.altOf.filter((a) => a.clickable), ...e.inflections.filter((i) => i.clickable)]
        .map((x) => ('target' in x ? x.target : x.base))
        .filter((w) => !svc.getEntry(w));
      return bad.length ? `标成可点却查不到：${[...new Set(bad)].slice(0, 3).join('、')}` : null;
    },
  },
];

/** 高风险面：阶段 8 新接的四样各自的全集 + 常用词。 */
function targets(limit: number): string[] {
  const q = (sql: string) => (db.prepare(sql).all() as Array<{ word: string }>).map((r) => r.word);
  // 🔴 `--limit` 从头切 ⇒ **必覆盖面排最前**，否则小族被整段切掉、
  //    对应的检查永远命中 0，等于一条永远通过的检查（es 那份栽过）。
  const famA = q(`SELECT DISTINCT d.word FROM dict d JOIN sense_relation r ON r.word_id=d.id
     WHERE r.kind='alt_of' LIMIT 800`);                                 // 有异体指针
  const famB = q(`SELECT DISTINCT d.word FROM dict d JOIN sense_tag t
     ON t.sense_id IN (SELECT id FROM sense WHERE word_id=d.id) LIMIT 800`);  // 有地区/语域标签
  const famC = q(`SELECT d.word FROM dict d JOIN pronunciation p ON p.word_id=d.id
     WHERE p.region IS NOT NULL GROUP BY d.id LIMIT 800`);              // 读音带地区
  const famD = q(`SELECT DISTINCT word FROM example WHERE sense_id IS NOT NULL LIMIT 800`); // 有例句
  // 🔴 四族**轮转交错**，不是首尾相接 —— 任何一个 --limit 都要同时覆盖四族。
  const must: string[] = [];
  const fams = [famA, famB, famC, famD];
  for (let i = 0; i < Math.max(...fams.map((f) => f.length)); i += 1) {
    for (const f of fams) if (i < f.length) must.push(f[i]);
  }
  const set = new Set<string>();
  for (const w of q('SELECT word FROM dict WHERE level IS NOT NULL LIMIT 3000')) set.add(w);
  for (const w of q(`SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id
     WHERE COALESCE(s.hidden,0)=0 GROUP BY d.id HAVING COUNT(*)>4 LIMIT 2000`)) set.add(w);
  for (const w of must) set.delete(w);
  const all = [...new Set([...must, ...set])];
  return limit > 0 ? all.slice(0, limit) : all;
}

function run(words: string[], quiet = false): number {
  const fails = new Map<string, string[]>();
  let n = 0;
  if (!quiet) console.log(`■ 待渲染 ${words.length.toLocaleString()} 个词条`);
  for (const w of words) {
    const entry = svc.getEntry(w) as FrenchEntry | null;
    if (!entry) continue;
    n += 1;
    if (!quiet && n % 1000 === 0) {
      console.log(`   [${n.toLocaleString()}/${words.length.toLocaleString()}] 已发现不符 `
        + `${[...fails.values()].reduce((a, b) => a + b.length, 0)}`);
    }
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
    console.log(`\n═══ 法语展示层契约闸（渲染 ${n.toLocaleString()} 个词条）═══`);
    // ⚠️ 统计口径与展示口径必须一致 —— 「渲染直接抛错」不在 CHECKS 里，
    //    只打印 CHECKS 的键会出现「全绿但总数非零」（it 那份栽过）。
    const names = [...new Set([...CHECKS.map((c) => c.name), ...fails.keys()])];
    for (const name of names) {
      const f = fails.get(name) ?? [];
      console.log(`   ${f.length ? '🔴' : '✅'} ${name.padEnd(42)} ${f.length}`);
      for (const line of f.slice(0, 3)) console.log(`        ${line}`);
    }
  }
  return [...fails.values()].reduce((a, b) => a + b.length, 0);
}

/**
 * 变异验证。🔴 **两种变异别混**（it 2026-08-18 的教训）：
 *   ① data —— 改数据，只验**只看数据**的检查
 *   ② html —— 先正常渲染，再把渲染结果**打坏**。这才是「组件漏写了一行」的真实形状，
 *      而本文件多数检查问的正是「组件有没有把这个字段渲染出来」。
 *      只做 ① 的话，改完数据组件照样忠实渲染 ⇒ 那些变异**在构造上就不可能红**。
 */
function mutate(words: string[]): void {
  type DataCase = [string, (e: FrenchEntry) => void, (e: FrenchEntry) => boolean];
  type HtmlCase = [string, (h: string) => string, (e: FrenchEntry) => boolean];

  const dataCases: DataCase[] = [
    ['给义项塞映射不出来的词性',
      (e) => { e.senses[0].pos = 'zzz_unknown'; }, (e) => e.senses.length > 0],
    ['给义项塞映射不出来的领域标签',
      (e) => { e.senses[0].topics = ['zzz_nosuchfield']; }, (e) => e.senses.length > 0],
    ['给义项塞映射不出来的地区标签',
      (e) => { e.senses[0].regions = ['Zzz-Land']; }, (e) => e.senses.length > 0],
    ['给读音塞映射不出来的地区代码',
      (e) => { e.readings[0].region = 'fr-ZZ'; }, (e) => e.readings.length > 0],
    ['造一条重复读音',
      (e) => { e.readings.push({ ...e.readings[0] }); }, (e) => e.readings.length > 0],
    // 这条守的是「alt_of 走词头那条线、不许混进相关词」。数据变异就够 ——
    //    它问的是接口形状，不是组件渲染了没有。
    ['把 alt_of 塞进 relations 分组',
      (e) => { e.relations = [{ kind: 'alt_of', total: 1,
                                targets: [{ word: 'zzz', clickable: false }] }]; }, () => true],
    ['把 alt_of 标成可点但指向不存在的词',
      (e) => { e.altOf = [{ target: 'zzzz-nope', zh: null, clickable: true }]; }, () => true],
    ['把第一条变位形式复制一份（模拟展示层漏了判重）',
      (e) => { e.inflections.push({ ...e.inflections[0] }); },
      (e) => e.inflections.length > 0],
    // 模拟 `relationsOf` 少了那一步去重：同一个目标既在近义又在下位
    ['把一个下位词同时塞进近义组',
      (e) => {
        const other = e.relations.find((g) => g.kind !== 'synonym')!;
        const syn = e.relations.find((g) => g.kind === 'synonym');
        const t = { ...other.targets[0] };
        if (syn) syn.targets.push(t);
        else e.relations.push({ kind: 'synonym', total: 1, targets: [t] });
      },
      (e) => e.relations.some((g) => g.kind !== 'synonym' && g.targets.length > 0)],
  ];
  const htmlCases: HtmlCase[] = [
    ['把「释义」区块整块抹掉', (h) => h.replace(/释义/g, ''), (e) => e.senses.length > 0],
    ['把第一条义项的中文抹掉', (h) => h, (e) => e.senses.some((s) => !!s.zh)],
    ['把法语原文定义抹掉', (h) => h, (e) => e.senses.some((s) => !!s.fr)],
    ['把音标抹掉', (h) => h, (e) => !!e.ipa],
    ['把「连诵」标签抹掉（模拟组件漏读 context 列）',
      (h) => h.replace(/连诵/g, ''),
      (e) => e.readings.some((r) => r.context === 'liaison')],
    // 🔴 关系层的变异在 HTML 层做 —— 要模拟的是「组件少写了那一段」，不是数据脏
    ['把「相关词」区块整块抹掉', (h) => h.replace(/相关词/g, ''),
      (e) => e.relations.length > 0],
    // 🔴 A2 的变异**必须在 HTML 层做**。第一版写成数据变异（把义项改成一 m 一 f）——
    //    **61 个词都没逮住**，因为那样组件就正确地不印徽标了，检查在构造上不可能红。
    //    要模拟的是「组件又跟着词形级 `entry.gender` 走」，也就是修之前的状态。
    ['给压平的词头塞回 mf 徽标（模拟组件又读了词形级值）',
      (h) => h.replace(/<div class="entry-meta-row entry-badges">/,
        '<div class="entry-meta-row entry-badges"><span class="badge g g-mf">阴阳性</span>'),
      (e) => { const g = new Set(e.senses.map((s) => s.gender).filter(Boolean));
               return g.has('m') && g.has('f'); }],
    ['页面里塞进模板残渣', (h) => `${h}<span>{{ modele }}</span>`, () => true],
    // 🔴 族 C 第二段的变异**必须在 HTML 层做**。第一版写成数据变异
    //    （给义项塞 `derogatory` + `pejorative`，中文都是「贬义」）——
    //    **61 个词都没逮住**，因为 `FrSenseChips` 已经按投影后的中文判重了，
    //    数据怎么塞都渲染不出重复。那条闸守的是「将来有人把判重从组件里去掉」，
    //    所以变异要模拟的是**组件少写了那一行**，不是数据脏。
    ['把某条义项的标签胶囊复制一份（模拟组件漏了判重）',
      (h) => h.replace(/(<span class="sense-chip [^"]*">[^<]*<\/span>)/, '$1$1'),
      (e) => e.senses.some((x) => (x.registers?.length ?? 0) + (x.topics?.length ?? 0) > 0)],
    // 🔴 族 D 的变异：把组头的读音搬回词头行 —— 等价于「组件忘了写归位那一行」，
    //    也就是 2026-08-27 之前的状态（`taper` 页头摆着名词的 /te.pœʁ/）。
    ['把归属某词性的读音搬回词头行',
      (h) => h.replace(/class="pos-group-ipa"/g, 'class="phonetic-value"'),
      (e) => {
        const poses = groupFrSenses(e.senses as never).map((g) => g.pos);
        return e.readings.some((r) => frReadingSlot(r as never, poses) !== null);
      }],
  ];

  console.log('═══ 变异验证 ═══');
  let ok = 0;
  const total = dataCases.length + htmlCases.length;
  for (const [name, fn, pre] of dataCases) {
    let caught = false; let tried = 0;
    for (const w of words) {
      const e = svc.getEntry(w) as FrenchEntry | null;
      if (!e || !pre(e)) continue;
      tried += 1;
      fn(e);
      const html = render(e);
      if (CHECKS.some((c) => c.hit(e, html))) { caught = true; break; }
      if (tried > 60) break;
    }
    console.log(`   ${caught ? '✅' : '🔴 没逮住'} [data] ${name}（试了 ${tried} 个）`);
    ok += caught ? 1 : 0;
  }
  for (const [name, breakHtml, pre] of htmlCases) {
    let caught = false; let tried = 0;
    for (const w of words) {
      const e = svc.getEntry(w) as FrenchEntry | null;
      if (!e || !pre(e)) continue;
      tried += 1;
      // 🔴 抹掉「组件应该渲染的那一段」：按字段值删，而不是删标签 ——
      //    这才等价于「组件里少写了一行」。
      let html = render(e);
      if (name.includes('义项的中文')) {
        const s = e.senses.find((x) => x.zh)!; html = html.split(s.zh!).join('');
      } else if (name.includes('法语原文')) {
        const s = e.senses.find((x) => x.fr)!; html = html.split(s.fr!).join('');
      } else if (name.includes('音标')) {
        html = html.split(e.ipa!).join('');
      } else {
        html = breakHtml(html);
      }
      if (CHECKS.some((c) => c.hit(e, html))) { caught = true; break; }
      if (tried > 60) break;
    }
    console.log(`   ${caught ? '✅' : '🔴 没逮住'} [html] ${name}（试了 ${tried} 个）`);
    ok += caught ? 1 : 0;
  }
  console.log(`\n   ${ok}/${total}`);
  process.exit(ok === total ? 0 : 1);
}

const argv = process.argv.slice(2);
const li = argv.indexOf('--limit');
const words = targets(li >= 0 ? Number(argv[li + 1]) : 0);
if (argv.includes('--mutate')) {
  mutate(words.slice(0, 3000));
} else {
  const bad = run(words);
  console.log(`\n   ${bad === 0 ? '✅ 全部通过' : `🔴 共 ${bad} 处不符`}`);
  process.exit(bad === 0 ? 0 : 1);
}
