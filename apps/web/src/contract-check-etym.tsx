/**
 * 词源分块契约闸：跨 en/es/it/fr/pt/de **六门**。2026-09-12。
 *
 * ═══ 起因 ═══
 * 用户看 en 的 `gore` 问「这个单词为什么有两轮名词/动词？」
 * 数据没错 —— `gore` 是**三个不同词源的同形词**（①血/污物 ②用角刺戳 ③三角形地块），
 * kaikki 按词源分块、每块各有名动。错的是展示层两件事：
 *   ① **从来没说过有多个词源** ⇒ 读者只看到「名词…动词…名词…动词」，以为是 bug；
 *   ② 「相邻同词性合组」**跨过了词源边界** ⇒ `gore` 词源①的动词（涂血于）
 *      与词源②的动词（用角刺戳）被并进同一个「动词」组；
 *      `curious` 的化学义「含三价锔的」（来自 curium）紧跟在「精心制作的」后面。
 *
 * ═══ 为什么是一份跨六门的闸，不是六个文件各抄一份 ═══
 * 判据本身与语种无关：**「页面上印出来的词源/词性分块，要和义项数据算出来的一致」**。
 * 抄六份的下场这个仓库有现成的账 —— de 那 16 个孤儿类名、五门各抄一份的搭配 JSX。
 * ⚠️ 六门的取数字段不一样（es 是 `unifiedSenses`，其余是 `senses`），
 *    分组键也不完全一样（it 还多一个 `entryId`）⇒ 闸**不复刻分组逻辑**，
 *    而是拿「词性 + 词源」这个**共同的必要条件**去比，it 多出来的细分不算错。
 *
 * ═══ 用法（仓库根目录）═══
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-etym.tsx
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-etym.tsx --mutate
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { getService } from '@synapse-dict/dict-core';
import {
  EnglishEntryView, SpanishEntryView, ItalianEntryView,
  FrenchEntryView, PortugueseEntryView, GermanEntryView,
} from './App';
import { etymologyBrief } from '@synapse-dict/dict-labels';

const mutate = process.argv.includes('--mutate');
const PER = 24;
type Lang = 'en' | 'es' | 'it' | 'fr' | 'pt' | 'de';
const LANGS: Lang[] = ['en', 'es', 'it', 'fr', 'pt', 'de'];

const VIEW: Record<Lang, unknown> = {
  en: EnglishEntryView, es: SpanishEntryView, it: ItalianEntryView,
  fr: FrenchEntryView, pt: PortugueseEntryView, de: GermanEntryView,
};
/** es 的义项在 `unifiedSenses` 里，其余五门在 `senses`。 */
const SENSE_FIELD: Record<Lang, string> = {
  en: 'senses', es: 'unifiedSenses', it: 'senses',
  fr: 'senses', pt: 'senses', de: 'senses',
};

type Sense = { pos: string | null; etymKey?: string | null };
type Entry = Record<string, unknown>;

function render(lang: Lang, entry: Entry): string {
  return renderToStaticMarkup(createElement(VIEW[lang] as never, {
    entry: entry as never, speakLocale: 'x', onWord: () => {}, speak: () => {},
  } as never));
}

const CIRCLED = '⓪①②③④⑤⑥⑦⑧⑨';

/** HTML 里实际印出来的「词源/词性」标题序列。 */
function headsInHtml(h: string): string[] {
  const out: string[] = [];
  for (const m of h.matchAll(
    /<div class="(etym-label|pos-group-label(?: pos-group-unset)?)"[^>]*>([^<]*)</g)) {
    if (m[1] === 'etym-label') {
      // ⚠️ 词源号在页面上是**圈号**（`词源 ①`）。`①` 不是 `\d`，
      //    第一版直接 `replace(/\D/g,'')` 得到空串 ⇒ 65 条假红。
      //    **闸自己的 bug 长得和真缺陷一模一样**，回去看渲染原文才分得清。
      const c = [...m[2]].find((ch) => CIRCLED.includes(ch));
      out.push(`E${c ? CIRCLED.indexOf(c) : m[2].replace(/\D/g, '') || '?'}`);
    } else out.push('P');
  }
  return out;
}

/**
 * 两条义项能不能并进同一组 —— **与组件 `App.tsx` 的 `sameEtymGroup` 逐字一致**。
 * 🔴 `etym` 为 `null` 表示**我们不知道这条义项的词源**，不是「词源不同」。
 *    拿 `null !== 已知值` 去断组，就会凭不确定性在页面上画一条线
 *    （es 的 `pasar` 被断成两个「动词」组，17,477 个词中招）。
 * ⚠️ 闸与组件各写一份同样的规则是有风险的（两边会漂移）——
 *    这里之所以还是写一份，是因为**闸必须独立算出"应该是什么样"**，
 *    直接 import 组件的分组函数就变成了"拿实现验实现"。
 *    ⇒ 代价用注释顶住：**改了一边必须改另一边**，G1/G3 会立刻报红（这次就是）。
 */
function sameEtymGroup(prev: string | null, cur: string | null): boolean {
  if (prev === null || cur === null) return true;
  return prev === cur;
}

/** 从义项数据算出**应有的**标题序列。与组件同一套规则，但不复刻 it 的 entryId 细分。 */
function headsExpected(senses: Sense[]): string[] {
  if (senses.length === 0) return [];
  const groups: Array<{ pos: string | null; etym: string | null }> = [];
  for (const s of senses) {
    const etym = s.etymKey ?? null;
    const last = groups[groups.length - 1];
    if (last && last.pos === s.pos && sameEtymGroup(last.etym, etym)) {
      if (last.etym === null) last.etym = etym;   // 组的 etym 取第一个已知的
      continue;
    }
    groups.push({ pos: s.pos, etym });
  }
  // 词源序号：**按出场顺序重排**（两个来源的编号不是同一个命名空间，见 etym.ts）
  const order = new Map<string, number>();
  for (const g of groups) if (g.etym && !order.has(g.etym)) order.set(g.etym, order.size + 1);
  const out: string[] = [];
  groups.forEach((g, i) => {
    if (order.size > 1 && g.etym !== null && (i === 0 || groups[i - 1].etym !== g.etym)) {
      out.push(`E${order.get(g.etym)}`);
    }
    if (g.pos) out.push('P');
  });
  return out;
}

/**
 * **页面上会印出几个词源块、每块属于哪一支** —— 按出场顺序，可重复。
 *
 * 🔴 不是「去重后的键列表」。第一版那么写，it 的 `o`/`peso`/`radio` 当场报
 *    「3 支词源、页面上 4 条正文」——**同一支词源被别的支隔开后会再印一次标题**
 *    （组件的 `etymHeadOf` 判的是「与上一组不同」，不是「以前没出现过」）。
 *    ⇒ 判据必须与组件同一口径：走分组序列，每次 etym 变化就是一块。
 * ⚠️ 分组规则与上面 `headsExpected` 同源，只是返回键而不是序号 ——
 *    两处要一起改（这份闸本来就承认"独立算一遍"的代价，注释在 `sameEtymGroup` 上）。
 */
function etymBlocksOf(senses: Sense[]): string[] {
  if (senses.length === 0) return [];
  const groups: Array<{ pos: string | null; etym: string | null }> = [];
  for (const s of senses) {
    const etym = s.etymKey ?? null;
    const last = groups[groups.length - 1];
    if (last && last.pos === s.pos && sameEtymGroup(last.etym, etym)) {
      if (last.etym === null) last.etym = etym;
      continue;
    }
    groups.push({ pos: s.pos, etym });
  }
  const distinct = new Set(groups.map((g) => g.etym).filter((x) => x !== null));
  if (distinct.size <= 1) return [];            // 单词源不印标题
  const out: string[] = [];
  groups.forEach((g, i) => {
    if (g.etym !== null && (i === 0 || groups[i - 1].etym !== g.etym)) out.push(g.etym);
  });
  return out;
}

/** 不透明键 `<版>:<词源号>` 里的「版」。**从右边切** —— 版名本身可能含冒号。 */
function editionOf(key: string): string {
  return key.slice(0, key.lastIndexOf(':'));
}

const CHECKS: Array<{
  name: string;
  // 🔴 2026-09-14 加上 `entry`：H 组要比「页面印的正文」与「库里那一支的正文」——
  //    只有义项和 HTML 是比不出**配对对不对**的。
  hit: (senses: Sense[], h: string, entry: Entry) => string | null;
}> = [
  {
    // G1 一条判据同时守住四种缺陷：少印、多印、顺序错、跨词源合组。
    // 🔴 只比**词源标题**的序号与位置；词性标题只数"有没有"，不比中文名 ——
    //    那是各门 pos 断言该管的事（判据要窄，`[[criteria-narrower-than-you-think]]`）。
    // ⚠️ it 的分组还多一个 `entryId` 细分 ⇒ 它印的 `P` 可能比这里算的多。
    //    所以比较时**只对齐词源标记**，`P` 的条数不参与 —— 否则 it 会恒红。
    name: '🔴 G1 词源标题的序号或位置与义项数据不符',
    hit: (senses, h) => {
      const want = headsExpected(senses).filter((x) => x !== 'P');
      const got = headsInHtml(h).filter((x) => x !== 'P');
      return want.join(' ') !== got.join(' ')
        ? `应为「${want.join(' ') || '（无）'}」，实为「${got.join(' ') || '（无）'}」` : null;
    },
  },
  {
    // G2 **负控**：只有一个词源（或压根没有词源号）的词，不许出现词源标题。
    //    六门里 98%+ 的词是这一支 —— 没有这条，"到处都印词源①"能让 G1 照样绿。
    name: '🔴 G2 单词源的词印出了词源标题',
    hit: (senses, h) => {
      const keys = new Set(senses.map((s) => s.etymKey ?? null).filter((x) => x !== null));
      return keys.size <= 1 && /class="etym-label"/.test(h)
        ? `只有 ${keys.size} 个词源，却印了词源标题` : null;
    },
  },
  {
    // G3 同一个词性组里不许混两个词源 —— 这是用户那一问的**根因**。
    // ⚠️ 用渲染后的 HTML 查：一个 `.pos-group` 块里若出现属于两个词源的义项，
    //    在数据上就表现为"应有的分组数 > 实际 pos-group 数"。
    //    这里用更直接的口径：**应有的组数**必须等于 HTML 里的 `pos-group` 数
    //    （it 的 entryId 细分只会让实际更多，所以判据写成"不许更少"）。
    name: '🔴 G3 实际分块比应有的少（两个词源被并进同一组）',
    hit: (senses, h) => {
      if (senses.length === 0) return null;
      // ⚠️ **es 会折叠义项**（超过 8 条只渲染前 8 条，底下一个「展开其余 N 条义项」按钮）。
      //    这条判据拿**全量**义项算"应有块数"，而组件渲染的是切片 ⇒ 必然报少。
      //    实测 `es de` 23 条义项折成 8 条：应有 3 块、实际 2 块 —— **不是缺陷**。
      //    ⇒ 页面上有折叠按钮就跳过这一条。**不是放宽判据，是这一支本来就不在它的射程里**
      //      （G1 仍然守着这些页：词源标题的序号与位置照查）。
      //    🔴 判据写成"有没有折叠按钮"而不是"是不是 es" —— 将来别的语种加折叠也自动适用。
      if (/展开其余 \d+ 条义项/.test(h)) return null;
      let want = 0;
      let prev: { pos: string | null; etym: string | null } | null = null;
      for (const s of senses) {
        const etym = s.etymKey ?? null;
        if (prev && prev.pos === s.pos && sameEtymGroup(prev.etym, etym)) {
          if (prev.etym === null) prev.etym = etym;
          continue;
        }
        want += 1;
        prev = { pos: s.pos, etym };
      }
      const got = (h.match(/<div class="pos-group"/g) ?? []).length;
      return got < want ? `应有 ${want} 块，实际 ${got} 块` : null;
    },
  },
  {
    // G4 **相邻两组的词性标题相同时，中间必须有词源标题。**
    // 🔴 用户 2026-09-12 看 es 的 `pasar`：「有两套动词，有什么含义吗？
    //    如果都是动词为什么不能合在一起，如果不能合在一起，为什么不换一个名字」
    //    —— **没有含义，是我当天造的**：断组判据写成「词性相同且词源相同」，
    //    而 `etym` 为 `null` 表示**我们不知道这条义项的词源**（es 的 `entry_id`
    //    只填了 54.7%），`null` 与任何已知词源不等 ⇒ 断组，
    //    两组都印「动词」、中间什么都不说。实测 es 17,477 个词（9.82%）中招。
    //    `[[dont-gate-facts-on-my-uncertainty]]`：**不知道就别在页面上画线。**
    // ⭐ 这条判据**直接描述用户看到的现象**，不描述实现：
    //    "两个一模一样的标题挨着出现而不解释为什么"。
    //    它与 G1/G3 互补 —— 那两条比的是词源标题的序列与块数，
    //    **对"多断了一组但两边都没有词源标题"这种情况结构性失明**。
    name: '🔴 G4 相邻两组词性标题相同，中间却没有词源标题（读者看不出为什么分成两块）',
    hit: (_senses, h) => {
      const heads = [...h.matchAll(
        /<div class="(etym-label|pos-group-label(?: pos-group-unset)?)"[^>]*>([^<]*)</g)]
        .map((m) => ({ kind: m[1] === 'etym-label' ? 'E' : 'P', text: m[2] }));
      const bad: string[] = [];
      for (let i = 1; i < heads.length; i += 1) {
        if (heads[i].kind !== 'P' || heads[i - 1].kind !== 'P') continue;
        if (heads[i].text === heads[i - 1].text) bad.push(heads[i].text);
      }
      return bad.length ? `连着两个「${bad[0]}」，中间没有词源标题` : null;
    },
  },
  {
    // ══ H 组：词源**正文**（2026-09-14）═══════════════════════════════════
    // G 组守的是「分块对不对」，H 组守的是「那一块底下说了什么」。
    // 用户看 `serene` 问「这里的词源是什么意思？」—— 序号说了「它们不一样」，
    // 说不出不一样在哪。`en/pipeline/ingest_etymology.py` 把正文抽进库之后补这一组。
    //
    // ⚠️ **判据按「这门接没接正文」走，不按语种码硬编码**：
    //    `etymologyTexts` 不存在 ⇒ 这门还没接，跳过；哪天 es/it/fr/pt/de 接上了，
    //    这三条自动开始守它们，一个字都不用改（`[[criteria-from-meaning-not-form]]`）。
    name: '🔴 H1 该说话的词源标题底下一句话都没有',
    hit: (senses, h, e) => {
      const ed = (e as { etymologyEditions?: string[] }).etymologyEditions;
      if (!ed) return null;                       // 这门还没接词源正文层
      // 🔴 **不是每个标题都该有话说。** it/fr/pt 的义项来自 2–4 个维基版，
      //    我们目前只抽了英文版那一支 —— **没抽过的版组件必须闭嘴**，
      //    说「源头未给出」就是把"我们没做"说成"源头没有"。
      //    ⇒ 期望条数 ＝ 词源支里**所属版已抽过**的那些，不是全部标题。
      //    （fr 实测 40 个词里就有 7 个这样的块，判据不区分就会恒红。）
      const want = etymBlocksOf(senses).filter((k) => ed.includes(editionOf(k))).length;
      const notes = (h.match(/class="etym-text/g) || []).length;
      return want !== notes ? `该有 ${want} 条正文/说明，页面上 ${notes} 条` : null;
    },
  },
  {
    // 🔴🔴 **这一条守的是「配对对不对」，不是「有没有」。**
    //    词源号是**位置型**键，正文贴错一支 ⇒ 数量对得上、配对全错，且看着完全合理
    //    （`[[primary-key-is-not-enough]]`：计数型闸对错配结构性失明）。
    //    ⇒ 逐块比：页面上第 k 个词源块印的那句，必须等于**第 k 个词源键**在
    //      `etymologyTexts` 里那份切出来的第一句。
    name: '🔴 H2 词源正文贴到了别的词源支上',
    hit: (senses, h, e) => {
      const texts = (e as { etymologyTexts?: Record<string, string> }).etymologyTexts;
      if (!texts) return null;
      const ed = (e as { etymologyEditions?: string[] }).etymologyEditions ?? [];
      const all = etymBlocksOf(senses);
      if (all.length < 2) return null;         // 单词源不印标题，没什么可配的
      // 只比**印得出来的那些**：没抽过的版不渲染任何块，把它算进去会整体错位。
      const keys = all.filter((k) => ed.includes(editionOf(k)));
      // ⚠️ **先把语种徽标整个元素剥掉，再剥标签。** 第一版直接 `replace(/<[^>]*>/g,'')`，
      //    于是徽标里的文字 `EN` 粘在正文前面（`ENA representation of…`），
      //    22 条真词条当场报红 —— **闸自己的 bug 长得和"贴错支"一模一样**。
      //    （同一个文件里 `headsInHtml` 的圈号那次也是这样，注释就在上面。）
      const shown = [...h.matchAll(
        /class="etym-text(?: etym-text-none)?"[^>]*>([\s\S]*?)<\/div>/g)]
        .map((m) => m[1]
          .replace(/<span class="sense-src-lang">[^<]*<\/span>/g, '')
          .replace(/<[^>]*>/g, ''));
      if (shown.length !== keys.length) {
        return `${keys.length} 支词源，页面上 ${shown.length} 条正文`;
      }
      const norm = (x: string) => x.replace(/&amp;/g, '&').replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>').replace(/&#x27;/g, "'").replace(/&quot;/g, '"').trim();
      for (let k = 0; k < keys.length; k += 1) {
        const want = etymologyBrief(texts[keys[k]]);
        const got = norm(shown[k]);
        if (!want) {
          if (!got.includes('源头未给出')) {
            return `第 ${k + 1} 支源头没正文，页面却印了「${got.slice(0, 30)}」`;
          }
          continue;
        }
        if (!got.startsWith(norm(want).slice(0, 40))) {
          return `第 ${k + 1} 支（${keys[k]}）印的不是它自己的：页面「${got.slice(0, 36)}」`
            + ` ≠ 库里「${norm(want).slice(0, 36)}」`;
        }
      }
      return null;
    },
  },
  {
    // 负控：库里明明有正文，页面却说「源头未给出」—— 把「有」说成「没有」，
    // 与 H1「留白」是一对：一个是不说话，一个是说错话。
    name: '🔴 H3 库里有词源正文，页面却说源头没给',
    hit: (senses, h, e) => {
      const texts = (e as { etymologyTexts?: Record<string, string> }).etymologyTexts;
      if (!texts) return null;
      const ed = (e as { etymologyEditions?: string[] }).etymologyEditions ?? [];
      const all = etymBlocksOf(senses);
      if (all.length < 2) return null;
      const keys = [...new Set(all.filter((k) => ed.includes(editionOf(k))))];
      const have = keys.filter((k) => etymologyBrief(texts[k])).length;
      const none = (h.match(/etym-text-none/g) || []).length;
      return none > keys.length - have
        ? `${keys.length} 支里库中 ${have} 支有正文，页面却有 ${none} 条「源头未给出」` : null;
    },
  },
];

const MUTS: Array<[string, (h: string) => string]> = [
  ['M1 抹掉所有词源标题（改前那个样子）',
    (h) => h.replace(/<div class="etym-label">[^<]*<\/div>/g, '')],
  ['M2 少印一个词源标题', (h) => h.replace(/<div class="etym-label">[^<]*<\/div>/, '')],
  ['M3 词源号印错（②印成①）', (h) => h.replace(/(<div class="etym-label">词源 )②/, '$1①')],
  // 🔴 G2 是负控型断言（"不该出现 X"），变异必须是**注入 X**：单词源的页面上
  //    一个 `etym-label` 都没有，替换型变异一个字符都改不动、会被静默跳过。
  // 🔴 G4 的变异：把一个词源标题抹掉，让两个同名的词性标题贴在一起
  //    —— 正是 `pasar` 当时在页面上的样子。
  ['M5 抹掉词源标题，制造"两个一模一样的词性标题挨着"',
    (h) => h.replace(/<div class="etym-label">[^<]*<\/div>/g, '')],
  ['M4 给单词源的词硬加上词源标题',
    (h) => h.replace('<div class="pos-group">',
      '<div class="pos-group"><div class="etym-label">词源 ①</div>')],
  ['M6 把两块并成一块（跨词源合组的样子）',
    (h) => h.replace(/<\/div><div class="pos-group">(<div class="etym-label">[^<]*<\/div>)?/, '')],
  // ── H 组的变异（2026-09-14）──
  ['M7 词源正文整块没渲染', (h) => h.replace(/class="etym-text/g, 'class="x"')],
  ['M8 正文贴错支（把第一块的正文复制到第二块）',
    (h) => {
      const m = [...h.matchAll(
        /(<div class="etym-text(?: etym-text-none)?"[^>]*>)([\s\S]*?)(<\/div>)/g)];
      return m.length > 1 ? h.replace(m[1][0], m[1][1] + m[0][2] + m[1][3]) : h;
    }],
  ['M9 有正文却印成「源头未给出」',
    (h) => h.replace(/<div class="etym-text" [^>]*>[\s\S]*?<\/div>/,
      '<div class="etym-text etym-text-none">源头未给出这一支的词源说明</div>')],
];

// ── 取样：**两支都要**，否则断言是恒真的 ──
const pages: Array<[string, Sense[], string, boolean, Entry]> = [];  // [词, 义项, html, 多词源?, entry]
const bucket = new Map<string, number>();
for (const lang of LANGS) {
  const svc = getService(lang) as unknown as {
    getEntry: (w: string) => Entry | null; db?: unknown };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const db = (svc as any).db as { prepare: (s: string) => { all: () => unknown[] } };
  const q = (sql: string) => (db.prepare(sql).all() as Array<{ word: string }>).map((r) => r.word);
  const multi = q(`SELECT d.word FROM dict d
     WHERE d.id IN (SELECT word_id FROM entry WHERE etym_no IS NOT NULL
                     GROUP BY word_id HAVING COUNT(DISTINCT etym_no)>1) LIMIT ${PER}`);
  const single = q(`SELECT d.word FROM dict d
     WHERE d.id IN (SELECT word_id FROM entry WHERE etym_no IS NOT NULL
                     GROUP BY word_id HAVING COUNT(DISTINCT etym_no)=1) LIMIT ${PER}`);
  for (const [kind, words] of [['多词源', multi], ['单词源', single]] as const) {
    let n = 0;
    for (const w of words) {
      const e = svc.getEntry(w);
      if (!e) continue;
      const senses = (e[SENSE_FIELD[lang]] ?? []) as Sense[];
      if (senses.length === 0) continue;
      pages.push([`${lang} ${w}`, senses, render(lang, e), kind === '多词源', e]);
      n += 1;
    }
    bucket.set(`${lang} ${kind}`, n);
  }
}

console.log('═══ 契约闸（词源分块）：跨六门 ═══\n');
console.log(`  取样 ${pages.length} 个词：\n`
  + [...bucket].map(([k, v]) => `    ${k.padEnd(12)} ${v}`).join('\n') + '\n');

const fails = new Map<string, string[]>();
const counts = new Map<string, number>();
for (const [w, senses, html, , entry] of pages) {
  for (const c of CHECKS) {
    const why = c.hit(senses, html, entry);
    if (why) {
      const a = fails.get(c.name) ?? [];
      if (a.length < 4) a.push(`${w}：${why}`);
      fails.set(c.name, a);
      counts.set(c.name, (counts.get(c.name) ?? 0) + 1);
    }
  }
}
let red = 0;
for (const c of CHECKS) {
  const arr = fails.get(c.name);
  if (!arr) { console.log(`   ✅ ${c.name.replace('🔴 ', '')}`); continue; }
  red += 1;
  console.log(`   ${c.name}  ${counts.get(c.name)} 条`);
  for (const x of arr) console.log(`        ${x}`);
}
console.log(red ? `\n🔴 ${red} 条红`
  : `\n✅ 全部通过（${CHECKS.length} 条断言，${pages.length} 个词）`);

if (mutate) {
  console.log(`\n═══ 变异：${MUTS.length} 种缺陷各造一次 ═══\n`);
  const covered = new Set<string>();
  let dead = 0;
  for (const [name, f] of MUTS) {
    const got = new Set<string>();
    let hits = 0;
    for (const [, senses, html, , entry] of pages) {
      let bad: string;
      try { bad = f(html); } catch { continue; }
      if (bad === html) continue;          // 这个词身上造不出这种缺陷，跳过
      for (const c of CHECKS) if (c.hit(senses, bad, entry)) { got.add(c.name); hits += 1; }
    }
    if (got.size === 0) { dead += 1; console.log(`   🔴 ${name}  —— 没有任何断言逮到它`); }
    else {
      for (const g of got) covered.add(g);
      console.log(`   ✅ ${name}  → ${[...got].map((x) => x.slice(2, 12)).join('／')}`
        + `（${hits} 次命中）`);
    }
  }
  const naked = CHECKS.map((c) => c.name).filter((x) => !covered.has(x));
  console.log(`\n   变异 ${MUTS.length - dead}/${MUTS.length} 有效`
    + ` ｜ 断言 ${CHECKS.length - naked.length}/${CHECKS.length} 有变异守着`);
  for (const x of naked) console.log(`   🔴 没有变异能打红：${x}`);
  process.exit(dead || naked.length ? 1 : 0);
}
process.exit(red ? 1 : 0);
