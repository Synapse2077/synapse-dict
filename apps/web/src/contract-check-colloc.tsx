/**
 * 搭配层契约闸：**出处标记** ＋ **反查搜索**。跨 es/it/fr/pt/de 五门。2026-09-12。
 *
 * ═══ 为什么要有这一道 ═══
 * 用户问「搭配 / 固定短语 habitante quiteño 基多居民，这种为什么直接查却没有结果呢？」
 * 查下来是两件事叠在一起：
 *   ① **搜索层压根不查 `collocation`**，页面上印出来的短语读者搜不到；
 *   ② 更要紧的是，这一层五门共 98,973 条，其中 98,294 条（99.3%）
 *      **是豆包凭记忆写的，没有任何外部出处**（各门 `pipeline/b_translate.py`
 *      里同一行 prompt 的 `col` 字段）。已确凿的错误：pt 的 `color primária 原色`
 *      （`color` 在库里两条义项都标着 archaic）、`Google Search`、混进来的专名。
 * 用户定的口径：**「既然已经有了，标记为参考」＋「需要标记他们的来源」**。
 *
 * ⇒ 出处写进了数据（`collocation.src`，`scripts/mark_collocation_src.py`）。
 *
 * ═══ 🔴 2026-09-12 下午：用户看了效果推翻「在页面上标出来」这一半 ═══
 *     「机器生成，这些标识还是不要了，用户看了只会产生不信任。
 *       要么整个搭配不展示，要么就糊弄一下用户，而且也没说一定就是错的」
 *
 * 他那句「也没说一定就是错的」用的正是我自己纠正过的口径：74.2% 是**佐证率**
 * 不是**错误率**，真实错误率至今没量过。拿一个没量过的数给每条挂警示牌，
 * 是把不确定转嫁给读者；世上没有哪本词典给每个词条标注来源。
 *
 * ⇒ **数据层照旧、展示层不印。** 本闸的 A1–A4 由「必须出现来源标记」
 *   **反向**改成「不许出现」——判据过期就改判据，留着恒红或者删掉都是错的
 *   （`[[fix-regression-and-gate]]`）。反向之后它守的是**这个决定**不被无意改回去。
 * ⚠️ B / C 两组（数据出处完整、反查搜索通）**一条不动** —— 那两件事没被推翻。
 *
 * ═══ 五门共用一个组件，所以这道闸也只写一份 ═══
 * 「搭配 / 固定短语」那一段由 `CollocationSection` 渲染，五门共用
 * （用户 2026-09-11：「字体样式应该要统一」）。**共用件出问题就是五门一起出问题**，
 * 所以闸建在共用件上，而不是每门抄一份 —— 抄五份的下场见 de 那 16 个孤儿类名。
 *
 * ⚠️ 顺带补了孤儿闸的一个洞：`css-audit.ts` 原来只扫六个 `XxxEntryView` 函数体，
 *    共用件落在扫描范围外，所以它对 `CollocationSection` 用的类名**结构性失明**。
 *    已加 `shared` 段（当场逮到 `.audio-region` 这个一直没有规则的孤儿）。
 *
 * ═══ 用法（仓库根目录）═══
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-colloc.tsx
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-colloc.tsx --mutate
 */
import { readFileSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { getService } from '@synapse-dict/dict-core';
import { SRC_LABELS } from '@synapse-dict/dict-labels';
import {
  SpanishEntryView, ItalianEntryView, FrenchEntryView,
  PortugueseEntryView, GermanEntryView, CollocationView,
} from './App';

const mutate = process.argv.includes('--mutate');
const LANGS = ['es', 'it', 'fr', 'pt', 'de'] as const;
type Lang = typeof LANGS[number];

const VIEWS: Record<Lang, unknown> = {
  es: SpanishEntryView, it: ItalianEntryView, fr: FrenchEntryView,
  pt: PortugueseEntryView, de: GermanEntryView,
};

type Colloc = { text: string; zh: string | null; src: string | null;
  srcText?: string | null };
type Entry = { word: string; collocations: Colloc[] };
type Svc = {
  getEntry: (w: string) => Entry | null;
  search: (q: string, n?: number) => Array<{
    id: number; word: string; brief: string | null;
    via?: { word: string; kind: string; src: string | null } | null;
  }>;
  raw?: unknown;
};

// ⚠️ 2026-09-14 起**必须带 `onColloc`**：不带的话 `CollocationSection` 退回纯文字
//    （那是给闸/无回调场景留的降级路径），闸就测不到生产时真正渲染的那一版 ——
//    「闸渲染的形状和用户看到的形状不是同一个」是最难发现的一类洞。
function render(lang: Lang, entry: Entry): string {
  return renderToStaticMarkup(createElement(VIEWS[lang] as never, {
    entry: entry as never, speakLocale: 'x',
    onWord: () => {}, speak: () => {}, onColloc: () => {},
  } as never));
}

// ── 取样：**按形状取，不是随机**（随机取 200 个词，混合来源的那一类一个都碰不到）──
//   三类各要有：纯 llm / 纯 kaikki / 两者混合。后两类只有 it 有。
function sample(lang: Lang, svc: Svc, db: {
  all: (sql: string) => Array<Record<string, unknown>>;
}) {
  const pick = (having: string, n: number) => db.all(`
    SELECT d.word AS w FROM collocation c JOIN dict d ON d.id = c.word_id
     GROUP BY c.word_id HAVING ${having} ORDER BY COUNT(*) DESC LIMIT ${n}`)
    .map((r) => String(r.w));
  const llm = pick("SUM(c.src LIKE 'llm:%') = COUNT(*)", 12);
  const kai = pick("SUM(c.src LIKE 'kaikki:%') = COUNT(*)", 12);
  const mix = pick("SUM(c.src LIKE 'llm:%') > 0 AND SUM(c.src LIKE 'kaikki:%') > 0", 12);
  const out: Array<[string, Entry, string, 'llm' | 'kaikki' | 'mix']> = [];
  for (const [kind, words] of [['llm', llm], ['kaikki', kai], ['mix', mix]] as const) {
    for (const w of words) {
      const e = svc.getEntry(w);
      if (e && e.collocations.length > 0) out.push([w, e, render(lang, e), kind]);
    }
  }
  return out;
}

// ══ 断言 ══════════════════════════════════════════════════════════════════
// 每条只问 HTML 里有没有，不问库里有没有。
const CHECKS: Array<{
  name: string;
  hit: (e: Entry, html: string, kind: 'llm' | 'kaikki' | 'mix') => string | null;
}> = [
  {
    // A1 **反向断言**：页面上不许出现任何来源标识。
    //    这条锁的是 2026-09-12 下午那个决定，不是锁一个实现细节 ——
    //    `[[record-the-negative-decision]]`：「决定不做」也是结论，
    //    不落成闸，下次谁（包括我）顺手加回去都没人拦。
    name: '🔴 页面上出现了来源标识（已决定不显示）',
    hit: (_e, html) => {
      const found = Object.values(SRC_LABELS).map((v) => v.short)
        .filter((w) => html.includes(w));
      if (html.includes('class="src-note"')) found.push('.src-note');
      return found.length ? `出现了 ${[...new Set(found)].join('／')}` : null;
    },
  },
  {
    // A2 有原文定义的，必须渲染出来。**只有 it 从 kaikki 子条目搬来的 303 条有。**
    // 🔴 用户问「那非生成的那些有详情吗」才查出来：那 303 条带着维基词典写的意语释义
    //    （平均 106 字符），而服务层压根没 SELECT 它；接上之后又发现 **293 条**
    //    被同文本、rank 更小的 `pseudo-sense` 行在去重时挡掉了
    //    —— **「谁在前」和「谁内容多」是两回事**。
    // ⚠️ 这一条与 A1 不冲突：去掉的是"这条哪来的"，留下的是**内容本身**。
    name: '🔴 搭配带了原文定义却没渲染出来',
    hit: (e, html) => {
      const miss = e.collocations.filter((c) => c.srcText && !html.includes(
        c.srcText.slice(0, 24).replace(/&/g, '&amp;').replace(/</g, '&lt;')
          .replace(/>/g, '&gt;').replace(/'/g, '&#x27;').replace(/"/g, '&quot;')));
      return miss.length ? `${miss.length} 条的原文定义缺席，例：${miss[0].text}` : null;
    },
  },
  {
    // A3 搭配原文必须逐条渲染出来，一条都不许少
    //    —— 用户 2026-09-10：「你不要擅自折叠信息」。
    name: '🔴 有搭配没渲染出来',
    hit: (e, html) => {
      const miss = e.collocations.filter((c) => !html.includes(
        c.text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
          .replace(/'/g, '&#x27;').replace(/"/g, '&quot;')));
      return miss.length ? `${miss.length} 条缺席，例：${miss[0].text}` : null;
    },
  },
  {
    // A5 **每一条搭配都得是可点的入口**（2026-09-14）。
    //    用户：「搭配我希望也有详情页」——「有详情页」和「进得去」是两件事，
    //    服务层把详情页做出来了、词条页上没给入口，读者照样到不了
    //    （`[[it-display-layer-stage8]]`：接上展示层是独立一道闸）。
    name: '🔴 搭配没有做成详情页入口',
    hit: (e, html) => {
      const got = (html.match(/class="colloc-text colloc-link"/g) || []).length;
      return got !== e.collocations.length
        ? `${e.collocations.length} 条搭配，只有 ${got} 条可点` : null;
    },
  },
  {
    // A4 中文译文也必须逐条出来 —— 只印外文等于没印。
    name: '🔴 有中文译文没渲染出来',
    hit: (e, html) => {
      const miss = e.collocations.filter((c) => c.zh && !html.includes(
        c.zh.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
          .replace(/'/g, '&#x27;').replace(/"/g, '&quot;')));
      return miss.length ? `${miss.length} 条的中文缺席，例：${miss[0].text}` : null;
    },
  },
];

// ══ 变异：每种缺陷造一次，必须至少打红一条断言 ════════════════════════════
// 🔴 **一次只造一种**（不像 de/fr 那两个闸把十几种一起抹掉）——
//    批量变异会互相遮盖，而且数不出「哪条断言没人管」。
const MUTS: Array<[string, (html: string, e: Entry) => string]> = [
  // 🔴 A1 是**负控型断言**（"不该出现 X"），它的变异必须是**注入 X**，不是替换 ——
  //    页面上现在一个标识都没有，"把 A 换成 B"一个字符都改不动，变异会被跳过，
  //    那条断言就成了没人守的摆设。这个坑今天上午刚踩过一次（旧 M3）。
  ['M1 把「机器生成」注入到小标题旁（标识偷偷回来了）',
    (h) => h.replace('<h3>搭配 / 固定短语',
      `<h3><span class="src-note">${SRC_LABELS['llm:doubao'].short}</span>搭配 / 固定短语`)],
  ['M2 逐条注入「词典收录」',
    (h) => h.split('</li>').join(
      `<span class="src-note">${SRC_LABELS['kaikki:subentry'].short}</span></li>`)],
  ['M3 只注入类名不注入文字（样式回来了、文案换了）',
    (h) => h.replace('<ul class="colloc-list">',
      '<ul class="colloc-list"><span class="src-note">来源</span>')],
  ['M4 折叠：只渲染第一条搭配',
    (h) => h.replace(/(<li class="colloc-item">[\s\S]*?<\/li>)[\s\S]*?(<\/ul>)/, '$1$2')],
  ['M5 抹掉原文定义块（去重留错了行的样子）',
    (h) => h.replace(/<div class="sense-src"[^>]*>[\s\S]*?<\/div>/g, '')],
  ['M6 抹掉中文译文',
    (h) => h.replace(/<span class="colloc-zh">[\s\S]*?<\/span>/g, '')],
  ['M7 搭配不再是详情页入口（退回纯文字）',
    (h) => h.replace(/class="colloc-text colloc-link"/g, 'class="colloc-text"')],
];

// ══ D 组：搭配**详情页**（2026-09-14）═══════════════════════════════════════
//
// 用户：「搭配我希望也有详情页，请按照现有格式配置」。
// 上面 A 组守的是**词条页上那一段**，这一组守的是点进去之后那一页 ——
// 两者是不同的组件（`CollocationSection` / `CollocationView`），
// A 组全绿不能说明 D 组对（`[[correct-steps-can-compose-a-hole]]`）。
type Detail = {
  lang: string; text: string; headword: string | null;
  zh: string | null; srcText: string | null;
  owners: string[]; parts: { word: string; clickable: boolean }[];
};
type SvcD = Svc & { getCollocation?: (t: string) => Detail | null };

const esc = (x: string) => x.replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/'/g, '&#x27;').replace(/"/g, '&quot;');

function renderDetail(d: Detail): string {
  return renderToStaticMarkup(createElement(CollocationView as never, {
    detail: d as never, onWord: () => {},
  } as never));
}

const DCHECKS: Array<{ name: string; hit: (d: Detail, html: string) => string | null }> = [
  {
    name: '🔴 D1 短语原文没出现在词头位置',
    hit: (d, h) => (h.includes(`class="entry-word" lang="${d.lang}">${esc(d.text)}<`)
      ? null : '词头不是这条短语'),
  },
  {
    // 中文是这一页**唯一**的实质内容（五门 100% 有），丢了整页就是空壳。
    name: '🔴 D2 中文释义没渲染出来',
    hit: (d, h) => (!d.zh || h.includes(esc(d.zh)) ? null : `「${d.zh}」缺席`),
  },
  {
    // 只有 it 那 303 条有。⚠️ 2026-09-12 刚因为服务层没 SELECT 它漏过一次。
    name: '🔴 D3 原文释义有值却没渲染',
    hit: (d, h) => (!d.srcText || h.includes(esc(d.srcText).slice(0, 24))
      ? null : '原文释义缺席'),
  },
  {
    // 🔴 `owners` 是数组：同一条短语可能挂在多个词条下，少印一个就是少一条路。
    name: '🔴 D4 所属词条没有逐个渲染成链接',
    hit: (d, h) => {
      const got = (h.match(/class="rel-link"/g) || []).length;
      const wantLinks = d.owners.length
        + (d.parts.length > 1 ? d.parts.filter((x) => x.clickable).length : 0);
      if (got !== wantLinks) return `该有 ${wantLinks} 个链接，页面上 ${got} 个`;
      const miss = d.owners.filter((w) => !h.includes(`>${esc(w)}</a>`));
      return miss.length ? `所属词条缺席：${miss.join('、')}` : null;
    },
  },
  {
    // 组成词**一个都不许少**（用户 2026-09-10：「你不要擅自折叠信息」）。
    // ⚠️ 只有一个词的短语有意不渲染这一块 —— 那时它就是词头重印一遍。
    name: '🔴 D5 组成词没有全部渲染出来',
    hit: (d, h) => {
      if (d.parts.length <= 1) {
        return h.includes('>组成词<') ? '只有一个词却渲染了「组成词」块' : null;
      }
      const miss = d.parts.filter((x) => !h.includes(`>${esc(x.word)}</a>`)
        && !h.includes(`class="rel-plain">${esc(x.word)}<`));
      return miss.length ? `${miss.length} 个组成词缺席，例：${miss[0].word}` : null;
    },
  },
];

// 数据侧负控：`headword` 必须**恰好**在「短语本身是词头」时非空 ——
// 它决定前端跳不跳真词条页，判反了要么把读者卡在降级页、要么把他扔进 404。
function checkHeadwordFlag(lang: Lang, svc: SvcD, all: (s: string) => Array<Record<string, unknown>>): string[] {
  const bad: string[] = [];
  const probe = (sql: string, want: boolean) => {
    for (const r of all(sql)) {
      const d = svc.getCollocation!(String(r.t));
      if (!d) { bad.push(`${lang}: 「${r.t}」getCollocation 返回 null`); continue; }
      if (!!d.headword !== want) {
        bad.push(`${lang}: 「${r.t}」headword=${d.headword} 但库里${want ? '有' : '没有'}这个词头`);
      }
    }
  };
  probe(`SELECT c.text AS t FROM collocation c
          WHERE EXISTS (SELECT 1 FROM dict d WHERE d.word = c.text) LIMIT 25`, true);
  probe(`SELECT c.text AS t FROM collocation c
          WHERE NOT EXISTS (SELECT 1 FROM dict d WHERE d.word = c.text COLLATE NOCASE) LIMIT 25`, false);
  return bad;
}

const DMUTS: Array<[string, (h: string) => string]> = [
  ['N1 抹掉中文释义', (h) => h.replace(/<div class="sense-zh">[\s\S]*?<\/div>/g, '')],
  ['N2 抹掉原文释义块', (h) => h.replace(/<div class="sense-src"[^>]*>[\s\S]*?<\/div>/g, '')],
  ['N3 少渲染一个链接（所属词条或组成词）', (h) => h.replace(/class="rel-link"/, 'class="x"')],
  ['N4 词头换成别的字', (h) => h.replace(/(class="entry-word"[^>]*>)[^<]*/, '$1XXX')],
  ['N5 组成词只留第一个', (h) => h.replace(/(<h3>组成词<\/h3><div class="rel-row">.*?<\/span>).*?(<\/div>)/, '$1$2')],
];

// ══ D 组：组件的**落点调用点** —— 服务层全对也救不了这一类 ═══════════════════
//
// 🔴🔴 2026-09-12 用户报：「这些短语好像没有右边详情，只有左侧搜索栏有数据」。
//    根因：`App.tsx` 里有 **5 处** `selectWord(...)`，我只改了鼠标点击那一处，
//    漏掉了「输入 200ms 后自动选中」「↑」「↓」「Enter」。搭配行的 `word` 是**短语**，
//    短语不是词头 ⇒ `getEntry` 返回 null ⇒ 右边整个空白。
//    而**自动选中那一条根本轮不到用户点**，所以搜出来的第一眼右边就是空的。
//
// ⚠️ **上面 C 组的断言全绿，因为它验的是 `svc.search()` 与 `svc.getEntry(via.word)`
//    —— 服务层一个字节没错，是组件没读那个字段**（`[[it-display-layer-stage8]]`）。
//    ⇒ 这一组只能在**源码层**守：判据是「`selectWord(` 的实参里不许出现 `.word`」。
//      当前合法的形态只有两种：`selectWord(word)`（实参本来就是词头字符串）、
//      `selectWord(targetOf(...))`（由唯一那个函数决定落点）。
// ⚠️ 剥掉注释再查 —— 上面那段说明里就原样写着 `selectWord(...)`
//    （同一天在 `redo_ecdict_core_gloss.py` 上被自己的注释骗过一次，PITFALLS 43）。
function checkSelectWordCallSites(): string[] {
  const raw = readFileSync(new URL('./App.tsx', import.meta.url), 'utf8');
  const src = raw.replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n').filter((l) => !l.trim().startsWith('//')).join('\n');
  const bad: string[] = [];
  let n = 0;
  for (const m of src.matchAll(/selectWord\(([^;]*?)\);/g)) {
    n += 1;
    if (m[1].includes('.word')) bad.push(`selectWord(${m[1].trim()})`);
  }
  // 负控：一个调用点都没找到 ＝ 判据失效（改了写法/正则过期），不是"全对"
  if (n === 0) bad.push('🔴 一个 selectWord( 调用点都没匹配到 —— 判据失效了');
  return bad;
}

/**
 * 🔴🔴 **「首页」只许在什么都没选中时出现。** 2026-09-14。
 *
 * 搭配详情页上线当天用户就截图了：点开 `serenar los ánimos`，
 * 搭配详情底下又挂了一整块欢迎页（「突触词典 / 试试这些词 hola escalera…」）。
 * 根因：那条判据只问了 `selectedWord`，而右栏的落点已经有两种。
 *
 * ⇒ 判据**从源码里自己发现有几种落点**（所有 `const [selectedXxx, setXxx]`），
 *   逐个要求出现在 `.empty-state` 的渲染条件里。将来加第三种落点，
 *   忘了改这行就当场报红 —— 而不是等用户看见（`[[lesson-must-become-mechanism]]`）。
 * ⚠️ 不写死 `['selectedWord','selectedColloc']`：写死的名单和它要描述的东西一样会过期，
 *   那正是这条闸要防的病（`[[criteria-from-meaning-not-form]]`）。
 */
function checkEmptyStateGuard(): string[] {
  const raw = readFileSync(new URL('./App.tsx', import.meta.url), 'utf8');
  const src = raw.replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n').filter((l) => !l.trim().startsWith('//')).join('\n');
  const states = [...src.matchAll(/const \[(selected\w+), set\w+\]/g)].map((m) => m[1]);
  if (states.length === 0) return ['🔴 一个 selected* 状态都没找到 —— 判据失效了'];
  const at = src.indexOf('className="empty-state"');
  if (at < 0) return ['🔴 找不到 .empty-state 的渲染点 —— 判据失效了'];
  // 🔴 **取"包住它的那个 JSX 表达式"，不是"往前数 500 个字符"。**
  //    第一版用定长窗口，而紧挨在上面的正是 `collocNotFound && selectedColloc` 那个错误块
  //    ⇒ 窗口里本来就有 `selectedColloc` ⇒ **把 `!selectedColloc` 从判据里删掉，闸照样绿**。
  //    负控当场证伪了它（`[[fix-regression-and-gate]]`：一条永远通过的检查等于没检查）。
  //    ⇒ 从锚点往回找**深度为 0 的那个 `{`**，取到锚点为止，才正好是这一处的条件表达式。
  let depth = 0;
  let start = -1;
  for (let i = at - 1; i >= 0; i -= 1) {
    const ch = src[i];
    if (ch === '}') depth += 1;
    else if (ch === '{') {
      if (depth === 0) { start = i; break; }
      depth -= 1;
    }
  }
  if (start < 0) return ['🔴 找不到包住 .empty-state 的 JSX 表达式 —— 判据失效了'];
  const guard = src.slice(start, at);
  const miss = states.filter((x) => !guard.includes(x));
  return miss.map((x) => `首页的渲染条件里没有 ${x} —— 选中它时欢迎页会跟详情叠在一起`);
}

// ══ 跑 ════════════════════════════════════════════════════════════════════
const pages: Array<[string, Entry, string, 'llm' | 'kaikki' | 'mix']> = [];
const bucket = new Map<string, number>();
const details: Array<[string, Detail, string]> = [];
const dbucket = new Map<string, number>();
const headwordFails: string[] = [];
const searchFails: string[] = [];
const labelFails: string[] = [];

for (const lang of LANGS) {
  const svc = getService(lang) as unknown as Svc;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const db = (svc as any).db as { prepare: (s: string) => { all: () => unknown[] } };
  const all = (sql: string) => db.prepare(sql).all() as Array<Record<string, unknown>>;

  // ── B 组：数据侧，只有跨五门才看得出来 ──
  // B1 每个出现过的 `src` 值，`SRC_LABELS` 里都得有名字。
  //    🔴 这一条的形状与 de 那次 `REL_LABELS` 漏了 expression/proverb 一模一样：
  //       库里长出新值、映射表没跟上 ⇒ 页面上直接印出原始码给读者看。
  for (const r of all("SELECT DISTINCT src FROM collocation WHERE src IS NOT NULL")) {
    if (!SRC_LABELS[String(r.src)]) labelFails.push(`${lang}: src=${r.src} 没有中文名`);
  }
  // B2 不许有没标出处的行。
  const nullSrc = Number(all("SELECT COUNT(*) n FROM collocation WHERE src IS NULL")[0].n);
  if (nullSrc > 0) labelFails.push(`${lang}: ${nullSrc} 行没有 src`);

  // ── C 组：反查真的通不通。**用例必须不是词头**，否则测的是词头路径 ──
  const cases = all(`
    SELECT c.text AS t FROM collocation c
     WHERE NOT EXISTS (SELECT 1 FROM dict d WHERE d.word = c.text COLLATE NOCASE)
       AND LENGTH(c.text) BETWEEN 10 AND 30
     ORDER BY c.id LIMIT 5`).map((r) => String(r.t));
  if (cases.length === 0) searchFails.push(`${lang}: 找不到"非词头"的搭配做用例`);
  for (const phrase of cases) {
    const hits = svc.search(phrase, 20);
    const via = hits.find((h) => h.via);
    if (!via) { searchFails.push(`${lang}: 搜「${phrase}」没有反查结果`); continue; }
    // C1 落点必须是真能打开的词条 —— `via.word` 是词头，`h.word` 是短语。
    if (!svc.getEntry(via.via!.word)) {
      searchFails.push(`${lang}: 「${phrase}」的落点 ${via.via!.word} 打不开`);
    }
    // ⚠️ 原 C2「反查结果必须带得出出处」已随"不显示出处"一并去掉 ——
    //    判据描述的那件事不存在了，留着就是一条永远绿的摆设。
    // C3 去掉重音也得搜得到（`text_norm` 那条路）。
    const plain = phrase.normalize('NFD').replace(/\p{M}/gu, '');
    if (plain !== phrase && svc.search(plain, 20).length === 0) {
      searchFails.push(`${lang}: 去重音「${plain}」搜不到 —— text_norm 那条路断了`);
    }
  }
  // C4 负控：词头不许被搭配挤下去。
  const top = svc.search('a', 20);
  const firstVia = top.findIndex((h) => h.via);
  const lastPlain = top.map((h) => !h.via).lastIndexOf(true);
  if (firstVia !== -1 && firstVia < lastPlain) {
    searchFails.push(`${lang}: 搭配排到了词头前面（第 ${firstVia + 1} vs 第 ${lastPlain + 1}）`);
  }

  for (const row of sample(lang, svc, { all })) {
    pages.push(row);
    bucket.set(`${lang} ${row[3]}`, (bucket.get(`${lang} ${row[3]}`) ?? 0) + 1);
  }

  // ── D 组取样：**按形状取**（随机取会整类碰不到）──
  //    ① 普通多词短语 ② 挂在多个词条下的 ③ 只有一个词的 ④ 有原文释义的（只有 it 有）
  const svcD = svc as SvcD;
  headwordFails.push(...checkHeadwordFlag(lang, svcD, all));
  const shapes: Array<[string, string]> = [
    ['普通', `SELECT c.text AS t FROM collocation c
        WHERE instr(c.text,' ')>0
          AND NOT EXISTS(SELECT 1 FROM dict d WHERE d.word=c.text COLLATE NOCASE) LIMIT 14`],
    ['多所属', `SELECT text AS t FROM collocation
        GROUP BY text HAVING COUNT(DISTINCT word_id)>1 LIMIT 8`],
    ['单词', `SELECT c.text AS t FROM collocation c WHERE instr(c.text,' ')=0 LIMIT 6`],
    ['有原文释义', `SELECT c.text AS t FROM collocation c JOIN collocation_gloss g
        ON g.collocation_id=c.id AND g.lang='${lang}' LIMIT 6`],
  ];
  for (const [shape, sql] of shapes) {
    for (const r of all(sql)) {
      const d = svcD.getCollocation!(String(r.t));
      // 🔴 本身是词头的走不到这一页（前端直接跳真词条），拿它当用例就是测了个不存在的路径。
      if (!d || d.headword) continue;
      details.push([`${lang} ${d.text}`, d, renderDetail(d)]);
      dbucket.set(`${lang} ${shape}`, (dbucket.get(`${lang} ${shape}`) ?? 0) + 1);
    }
  }
}

console.log('═══ 契约闸（搭配层）：出处标记 + 反查搜索 ═══\n');
console.log(`  取样 ${pages.length} 个词（按来源形状取，不是随机）：\n`
  + [...bucket].map(([k, v]) => `    ${k.padEnd(12)} ${v}`).join('\n') + '\n');

let red = 0;
const siteFails = checkSelectWordCallSites();
for (const [name, arr] of [['🔴 出处值没有中文名 / 没有出处', labelFails],
                           ['🔴 反查搜索不通', searchFails],
                           ['🔴 有 selectWord 调用点直接用了 .word（落点会是短语，右边必空白）',
                            siteFails],
                           ['🔴 首页的渲染条件漏了某种落点（欢迎页会跟详情叠在一起）',
                            checkEmptyStateGuard()]] as const) {
  if (arr.length === 0) { console.log(`   ✅ ${name.replace('🔴 ', '')}`); continue; }
  red++;
  console.log(`   ${name}  ${arr.length} 条`);
  for (const x of arr.slice(0, 6)) console.log(`        ${x}`);
}

const fails = new Map<string, string[]>();
const counts = new Map<string, number>();
for (const [w, e, html, kind] of pages) {
  for (const c of CHECKS) {
    const why = c.hit(e, html, kind);
    if (why) {
      const a = fails.get(c.name) ?? [];
      if (a.length < 4) a.push(`${w}：${why}`);
      fails.set(c.name, a);
      counts.set(c.name, (counts.get(c.name) ?? 0) + 1);
    }
  }
}
for (const c of CHECKS) {
  const arr = fails.get(c.name);
  if (!arr) { console.log(`   ✅ ${c.name.replace('🔴 ', '')}`); continue; }
  red++;
  console.log(`   ${c.name}  ${counts.get(c.name)} 条`);
  for (const x of arr) console.log(`        ${x}`);
}
// ── D 组报告：搭配详情页 ──
console.log(`\n  搭配详情页取样 ${details.length} 条：\n`
  + [...dbucket].map(([k, v]) => `    ${k.padEnd(16)} ${v}`).join('\n'));
if (headwordFails.length === 0) {
  console.log('   ✅ headword 标志与「短语是不是词头」一致');
} else {
  red++;
  console.log(`   🔴 headword 标志判错  ${headwordFails.length} 条`);
  for (const x of headwordFails.slice(0, 6)) console.log(`        ${x}`);
}
const dfails = new Map<string, string[]>();
for (const [name, d, html] of details) {
  for (const c of DCHECKS) {
    const why = c.hit(d, html);
    if (why) {
      const a = dfails.get(c.name) ?? [];
      if (a.length < 4) a.push(`${name}：${why}`);
      dfails.set(c.name, a);
    }
  }
}
for (const c of DCHECKS) {
  const arr = dfails.get(c.name);
  if (!arr) { console.log(`   ✅ ${c.name.replace('🔴 ', '')}`); continue; }
  red++;
  console.log(`   ${c.name}`);
  for (const x of arr) console.log(`        ${x}`);
}

console.log(red ? `\n🔴 ${red} 条红`
  : `\n✅ 全部通过（${CHECKS.length + DCHECKS.length + 5} 条断言，`
    + `${pages.length} 个词 + ${details.length} 条搭配详情页）`);

if (mutate) {
  console.log(`\n═══ 变异：${MUTS.length} 种缺陷各造一次 ═══\n`);
  const covered = new Set<string>();
  let dead = 0;
  for (const [mname, f] of MUTS) {
    const got = new Set<string>();
    let hits = 0;
    for (const [, e, html, kind] of pages) {
      let bad: string;
      try { bad = f(html, e); } catch { continue; }
      if (bad === html) continue;          // 这个词身上造不出这种缺陷，跳过
      for (const c of CHECKS) if (c.hit(e, bad, kind)) { got.add(c.name); hits++; }
    }
    if (got.size === 0) { dead++; console.log(`   🔴 ${mname}  —— 没有任何断言逮到它`); }
    else {
      for (const g of got) covered.add(g);
      console.log(`   ✅ ${mname}  → ${[...got].map((x) => x.slice(2, 14)).join('／')}`
        + `（${hits} 次命中）`);
    }
  }
  console.log(`\n═══ 变异（搭配详情页）：${DMUTS.length} 种缺陷各造一次 ═══\n`);
  const dcovered = new Set<string>();
  for (const [mname, f] of DMUTS) {
    const got = new Set<string>();
    let hits = 0;
    for (const [, d, html] of details) {
      let bad: string;
      try { bad = f(html); } catch { continue; }
      if (bad === html) continue;
      for (const c of DCHECKS) if (c.hit(d, bad)) { got.add(c.name); hits++; }
    }
    if (got.size === 0) { dead++; console.log(`   🔴 ${mname}  —— 没有任何断言逮到它`); }
    else {
      for (const g of got) dcovered.add(g);
      console.log(`   ✅ ${mname}  → ${[...got].map((x) => x.slice(2, 16)).join('／')}`
        + `（${hits} 次命中）`);
    }
  }
  for (const x of DCHECKS.map((c) => c.name).filter((y) => !dcovered.has(y))) {
    dead++;
    console.log(`   🔴 没有变异能打红：${x}`);
  }

  const naked = CHECKS.map((c) => c.name).filter((x) => !covered.has(x));
  console.log(`\n   变异 ${MUTS.length - dead}/${MUTS.length} 有效`
    + ` ｜ 断言 ${CHECKS.length - naked.length}/${CHECKS.length} 有变异守着`);
  // 🔴 「一条谁都打不红的断言」与「一个谁都逮不到的变异」是同一个病，两边都要报。
  for (const x of naked) console.log(`   🔴 没有变异能打红：${x}`);
  process.exit(dead || naked.length ? 1 : 0);
}
process.exit(red ? 1 : 0);
