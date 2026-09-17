/** 展示层契约闸（ja）。2026-09-16（阶段 8）。
 *
 * ═══ 为什么数据层全绿之后还要这一道 ═══
 * `[[it-display-layer-stage8]]`：**接上展示层是独立一道闸。**
 * it 那轮三层数据全绿，真渲染出来立刻看见三个缺陷。
 * fr 那轮库里躺着 39 万条录音，而 `french.ts` 里 `FROM audio` 出现 0 次 ——
 * **"落库成功"证明不了"到达用户"**。
 *
 * ⇒ 本闸把 `JapaneseEntryView` 用 `react-dom/server` 渲染成静态 HTML，
 *   断言全部盯**去标签之后的可见文字**，不盯 DOM 结构。
 *
 * 🔴 **兜底越体面，缺陷越难发现。** 所以断言里有好几条是「这个词必须看得到 X」，
 *    而不是「渲染没报错」。
 *
 * 跑：npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-ja.tsx
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { getService } from '@synapse-dict/dict-core';
import { JapaneseEntryView } from './App';
import { JA_RELATION_LABELS, JA_POS_LABELS, POS_LABELS, relTagLabel } from '@synapse-dict/dict-labels';

const svc = getService('ja') as unknown as {
  getEntry(w: string): any;
  db: { prepare(s: string): { all(...a: unknown[]): unknown[] } };
};
const db = svc.db;

function render(entry: unknown): string {
  return renderToStaticMarkup(createElement(JapaneseEntryView, {
    entry, speakLocale: 'ja-JP', onWord: () => {}, speak: () => {},
  } as never));
}

function visibleText(html: string): string {
  return html.replace(/<[^>]*>/g, ' ').replace(/&quot;/g, '"').replace(/&#x27;/g, "'")
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/\s+/g, ' ');
}

type Check = { word: string; name: string; hit: (t: string, e: any, html: string) => string | null };

const CHECKS: Check[] = [
  // ── 日语特有字段，必须真的印出来 ──
  { word: '痛い', name: '假名读音印出来了', hit: (t) => (t.includes('いたい') ? null : '看不到假名') },
  { word: '痛い', name: '罗马字印出来了', hit: (t) => (t.includes('itai') ? null : '看不到罗马字') },
  { word: '痛い', name: '声调标记印出来了', hit: (t) => (/[ꜜ]/.test(t) ? null : '看不到声调标记') },
  {
    word: '痛い',
    name: '声调型（平板/头高/中高/尾高）印出来了',
    hit: (t) => (/(平板型|头高型|中高型|尾高型)/.test(t) ? null : '看不到声调型'),
  },
  { word: '痛い', name: '例句带振假名（<ruby>）', hit: (_t, _e, html) => (html.includes('<ruby>') ? null : '例句没有振假名') },
  { word: '痛い', name: '例句译文印出来了', hit: (t) => (t.includes('头痛') ? null : '看不到例句中文') },
  { word: '痛い', name: '活用形印出来了', hit: (t) => (t.includes('活用') ? null : '看不到活用') },

  // ── 🔴 词性名必须走日语覆盖层 ──
  {
    word: '青',
    name: '词性名不许印英文码（kanji/kana/part…）',
    hit: (t) => {
      const bad = ['kanji', 'kana', 'romaji', 'adnom', 'counter', 'unknown']
        .filter((c) => new RegExp(`(^|\\s)${c}(\\s|$)`).test(t));
      return bad.length ? `印了英文码：${bad.join(', ')}` : null;
    },
  },
  { word: '青', name: '汉字词性印成「汉字」', hit: (t) => (t.includes('汉字') ? null : '没印出「汉字」') },

  // ── 活用类（欠账 4，2026-09-16 还的）──
  {
    word: '保護',
    name: '活用类印出来了（サ行变格活用）',
    hit: (t) => (t.includes('サ行变格活用') ? null : '看不到活用类'),
  },
  {
    // 🔴 原来这一条查的是 `歩く` 要印「五段活用・カ行」—— **做不到，而且不该硬做**。
    //    日语版把词条挂在**假名词头**（`あるく`）下，`歩く` 拿不到活用类。
    //    我试过按读音传播并加「读音唯一对应一个活用类」当保险，那个保险是假的：
    //    `犬[いぬ]` 会拿到动词 `去ぬ` 的 `godan-na`。⇒ 放弃传播，见 `fill_vclass` 文件头。
    //    ⇒ 断言改成查**假名词头本身**印不印得出来。
    word: 'あるく',
    name: '五段活用的行印出来了（五段活用・カ行）',
    hit: (t) => (/五段活用・カ行/.test(t) ? null : '看不到「五段活用・カ行」'),
  },
  {
    word: '保護',
    name: '🔴 活用类不许印在每一行变形上',
    hit: (t) => {
      // 它应该只出现一次（词头旁边的徽标），不是每条活用都拖一个
      const n = (t.match(/サ行变格活用/g) || []).length;
      return n === 1 ? null : `出现了 ${n} 次（词元属性印成了每个形的属性）`;
    },
  },

  // ── 🔴🔴 异体 vs 同音，措辞必须跟着判据走 ──
  {
    word: 'いぬ',
    name: '同音索引页印成「同音词」而不是「异体写法」',
    hit: (t) => {
      if (!t.includes('同音词')) return '没印出「同音词」';
      // 它没有 alt_of，所以「异体写法」这四个字一个都不该出现
      return t.includes('异体写法') ? '把同音索引页印成了异体写法（数据层拒绝做的断言）' : null;
    },
  },
  {
    word: 'いぬ',
    name: '多个原形全部印出来，不许只印一个',
    hit: (t) => {
      const have = ['去ぬ', '寝ぬ', '射る', '率寝', '鋳る'].filter((w) => t.includes(w));
      return have.length >= 5 ? null : `只印出 ${have.length}/5 个原形：${have.join('、')}`;
    },
  },
  {
    word: 'あいする',
    name: '异表记词形不是空白页（指针必须可见）',
    hit: (t) => (t.includes('愛する') ? null : '跳转页上看不到目标词 —— 读者点进来是空白'),
  },

  // ── 通用：不许漏出未映射的原始码 ──
  {
    word: '表現',
    name: '不许漏出未映射的关系码',
    hit: (t) => {
      const bad = ['synonym', 'antonym', 'derived', 'related', 'coordinate', 'see_also', 'alt_of']
        .filter((c) => t.includes(c));
      return bad.length ? `印了原始关系码：${bad.join(', ')}` : null;
    },
  },
  // 🔴🔴 **上面那条对「空标签」结构性失明。**
  //    `relTagLabel()` 对 `related`/`synonym`/`antonym` 返回的是**空字符串** ——
  //    页面上是个空的小标签，既不是英文码也不是中文，比印英文码更难发现。
  //    实测 13 个 kind 里，上面那条只逮到 1 个（`derived`）：
  //      8 个原样返回英文码、3 个返回空串、2 个已被 ja 覆盖层接住。
  //    ⇒ 直接去**库里取全部 kind** 逐个问有没有非空中文名 ——
  //      判据锚在数据上，源头将来多一个 kind 它会自己响（`[[external-anchor-gates]]`）。
  {
    word: '表現',
    name: '库里每个关系 kind 都有非空中文名',
    hit: () => {
      const kinds = (db.prepare('SELECT DISTINCT kind FROM sense_relation')
        .all() as Array<{ kind: string }>).map((r) => r.kind);
      const bad = kinds.filter((k) => {
        const v = JA_RELATION_LABELS[k] ?? relTagLabel(k);
        return !v || v === k;
      });
      return bad.length ? `没有中文名（空标签或原码）：${bad.join(', ')}` : null;
    },
  },
  // 同样的形状，词性那边也查一遍：**库里每个 pos 都得有非空中文名**。
  {
    word: '表現',
    name: '库里每个词性码都有非空中文名',
    hit: () => {
      const codes = new Set<string>();
      for (const r of db.prepare('SELECT DISTINCT pos FROM entry WHERE pos IS NOT NULL')
        .all() as Array<{ pos: string }>) {
        for (const c of r.pos.split('/')) codes.add(c);
      }
      const bad = [...codes].filter((c) => {
        const v = JA_POS_LABELS[c] ?? POS_LABELS[c];
        return !v || v === c;
      });
      return bad.length ? `没有中文名：${bad.join(', ')}` : null;
    },
  },
];

let red = 0;
const cache = new Map<string, any>();
for (const c of CHECKS) {
  let e = cache.get(c.word);
  if (e === undefined) { e = svc.getEntry(c.word); cache.set(c.word, e); }
  if (!e) { console.log(`   🔴 ${c.name}  —— 词条 ${c.word} 查不到`); red += 1; continue; }
  let html: string;
  try {
    html = render(e);
  } catch (err) {
    console.log(`   🔴 ${c.name}  —— 渲染抛异常：${(err as Error).message.slice(0, 80)}`);
    red += 1;
    continue;
  }
  const why = c.hit(visibleText(html), e, html);
  if (why) red += 1;
  console.log(`   ${why ? '🔴' : '✅'} ${c.word.padEnd(5)} ${c.name}${why ? `  —— ${why}` : ''}`);
}
console.log(red ? `\n🔴 ${red} 条不合格` : '\n✅ 日语展示层契约全部通过');
process.exit(red ? 1 : 0);
