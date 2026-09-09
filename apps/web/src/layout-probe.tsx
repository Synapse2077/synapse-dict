/**
 * 排版探针：**六门语言的极端词条，渲染出来会不会撑破页面。** 2026-09-06。
 *
 * ═══ 为什么需要它：现有的 100 条契约断言拦不住排版 ═══
 * 五个契约闸查的是「HTML 里有没有这个类、有没有这段文字」：
 *     hit: (e, h) => e.senses.length > 0 && !/class="sense-zh"/.test(h)
 * ⇒ 区块**没渲染**它当场红；区块**渲染了但被挤没了 / 溢出 / 挤成一坨**，它一条都不响。
 * 而 `styles.css` 的 213 条类规则里只有 24 条带语种前缀（es- 14 / de- 9 / it- 1）——
 * **89% 是共用的，改一处六门同时受影响**，正好落在现有闸的盲区里。
 *
 * ═══ 🔴 能量什么、不能量什么，先说清楚 ═══
 * 无头环境**没有浏览器引擎，拿不到真实像素布局**。所以本探针不假装量布局，
 * 它量的是**排版事故的结构性成因** —— 这些在 HTML 里就看得见：
 *
 *   ① **超长不可断词**：德语复合词、长音标、URL。CSS 不给 `overflow-wrap` 就会顶破容器。
 *   ② **单行塞了几十上百项**：`Haus` 的关系行实测一行印了 100+ 个词（近义/上位/下位/习语/谚语连排）。
 *   ③ **单个元素里的文本极长**：一个 `<span>` 装几千字，任何容器都收不住。
 *   ④ **区块数量爆炸**：一页几百个 `.rel-row`、几千个 `.de-form-grid` 单元。
 *
 * ⚠️ 量不到的（要真浏览器才行，本探针**不冒充**能查）：重叠、遮挡、实际溢出像素、
 *    窄屏断行、字体回退。⇒ 它只能证明「有这些成因」，不能证明「一定出事」，
 *    反过来也不能证明「没成因就一定没事」。**先量成因，再决定要不要上真浏览器。**
 *
 * ═══ 取样：按**极端**取，不按随机取 ═══
 * 排版事故只在长尾上发生。随机抽 100 个词，抽到的都是三五条义项的普通词，
 * 量出来一片绿 —— 那是假绿（同契约闸「按形状取样」那条理由）。
 * ⇒ 每门语言各取：义项最多 / 关系最多 / 例句最多 / 变形最多 / 词形最长。
 *
 * 用法（仓库根目录）：
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/layout-probe.tsx
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/layout-probe.tsx --lang de --top 20
 */
import { createElement, type ComponentType } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { getService } from '@synapse-dict/dict-core';
import {
  EnglishEntryView, GermanEntryView, SpanishEntryView, ItalianEntryView,
  FrenchEntryView, PortugueseEntryView,
} from './App';

type Any = Record<string, any>;
const argv = process.argv.slice(2);
const arg = (n: string) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : undefined; };
const TOP = Number(arg('--top') ?? 8);
const ONLY = arg('--lang');

/** 每门语言：服务 key、视图组件、locale。⚠️ props 与各自的契约闸保持一致。 */
const LANGS: Array<[string, any, string]> = [
  // 🔴 2026-09-08 补 en —— 这张表原本只有五门，**探针的名字叫「六门语言」但少一门**。
  //    en 阶段 8 之前用的是老扁平视图，接上 v3 视图后必须进这张表，
  //    否则英语的排版事故一条都量不到（`[[it-display-layer-stage8]]`）。
  ['en', EnglishEntryView, 'en-US'],
  ['de', GermanEntryView, 'de-DE'],
  ['es', SpanishEntryView, 'es-ES'],
  ['it', ItalianEntryView, 'it-IT'],
  ['fr', FrenchEntryView, 'fr-FR'],
  ['pt', PortugueseEntryView, 'pt-PT'],
];

/** 极端取样：每一支问的都是「哪种长尾最可能撑破页面」。 */
const ARMS: Array<[string, string]> = [
  ['义项最多', `SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id
                 GROUP BY d.id ORDER BY COUNT(*) DESC LIMIT ?`],
  ['关系最多', `SELECT d.word FROM dict d JOIN sense_relation r ON r.word_id=d.id
                 WHERE COALESCE(r.hidden,0)=0 GROUP BY d.id ORDER BY COUNT(*) DESC LIMIT ?`],
  ['例句最多', `SELECT e.word FROM example e WHERE COALESCE(e.hidden,0)=0
                 GROUP BY e.word ORDER BY COUNT(*) DESC LIMIT ?`],
  ['词形最长', `SELECT word FROM dict ORDER BY LENGTH(word) DESC LIMIT ?`],
];

const text = (h: string) => h.replace(/<[^>]*>/g, ' ')
  .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
  .replace(/&quot;/g, '"').replace(/&#x27;|&#39;/g, "'");

/** 一个元素内部的纯文本（不含嵌套标签文本之外的东西）里最长的一段。 */
function longestLeafText(html: string): number {
  let max = 0;
  for (const m of html.matchAll(/>([^<]+)</g)) {
    const t = m[1].trim();
    if (t.length > max) max = t.length;
  }
  return max;
}

/** 最长的**不可断**词：连续非空白且不含常见断点的一段。德语复合词、长音标都在这里现形。 */
function longestUnbreakable(s: string): [number, string] {
  let max = 0, who = '';
  for (const tok of s.split(/[\s ]+/)) {
    // 连字符/斜杠/逗号浏览器可以断，不算不可断
    for (const piece of tok.split(/[-‐‑–—/,;、，。]/)) {
      if (piece.length > max) { max = piece.length; who = piece; }
    }
  }
  return [max, who];
}

type Row = {
  lang: string; arm: string; word: string;
  chars: number; leaf: number; unbreak: number; unbreakWho: string;
  relRow: number; relMaxItems: number; formCells: number;
};

const rows: Row[] = [];
for (const [lang, View, locale] of LANGS) {
  if (ONLY && lang !== ONLY) continue;
  const svc = getService(lang) as unknown as { getEntry(w: string): unknown; db: any };
  const seen = new Set<string>();
  for (const [arm, sql] of ARMS) {
    let got: Array<{ word: string }> = [];
    try { got = svc.db.prepare(sql).all(TOP) as Array<{ word: string }>; }
    catch { continue; }                       // 该语种没有这张表就跳过这一支
    for (const { word } of got) {
      const key = `${lang}:${word}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const e = svc.getEntry(word) as Any | null;
      if (!e) continue;
      let html = '';
      try {
        // ⚠️ 强转的是**组件**不是 props。原来写 `{...} as never` 会把泛型 P 钉成 `never`，
        //    于是 `createElement` 落到「类式组件」那个重载、返回 `CElement<never,…>`，
        //    而它缺 `children` ⇒ 不是合法的 `ReactNode`（TS2345）。
        //    六门的 View 各有各的 props 类型，这里只需要统一成 ComponentType<Any>。
        html = renderToStaticMarkup(createElement(View as ComponentType<Any>, {
          entry: e, speakLocale: locale, onWord: () => {}, speak: () => {},
        }));
      } catch (err) {
        rows.push({ lang, arm, word, chars: -1, leaf: -1, unbreak: -1,
                    unbreakWho: String(err).slice(0, 60), relRow: -1, relMaxItems: -1, formCells: -1 });
        continue;
      }
      const t = text(html);
      const [unbreak, who] = longestUnbreakable(t);
      // 一个关系行里塞了多少项：`.rel-row` 内部的目标词个数
      let relMaxItems = 0;
      for (const m of html.matchAll(/class="rel-row"[\s\S]*?(?=class="rel-row"|$)/g)) {
        // 🔴 2026-09-08 修：原兜底是「数整段文本的单词数」—— 找不到目标类就退化成
        //    数整页单词，把 en 的 `run` 报成「单行 5,041 项」（真实 1 项）。
        //    **兜底比它要近似的东西大三个数量级 ⇒ 那不是近似，是噪声。**
        //    ⇒ 改成数共用的目标类 `.rel-item`/`.rel-link`，数不到就是 0（诚实的 0）。
        const n = (m[0].match(/class="rel-target"|class="[^"]*rel[^"]*target/g) ?? []).length
          || (m[0].match(/class="rel-item"|class="rel-link"/g) ?? []).length;
        if (n > relMaxItems) relMaxItems = n;
      }
      rows.push({
        lang, arm, word,
        chars: t.length,
        leaf: longestLeafText(html),
        unbreak, unbreakWho: who,
        relRow: (html.match(/class="rel-row"/g) ?? []).length,
        relMaxItems,
        formCells: (html.match(/class="de-form-grid"|class="form-cell"|class="[^"]*form[^"]*grid/g) ?? []).length,
      });
    }
  }
}

const f = (n: number) => n.toLocaleString('en-US');
console.log('═══ 排版探针：极端词条渲染出来有多大 ═══\n');
console.log('  ⚠️ 无头环境没有浏览器引擎 —— 本探针量的是**溢出的结构性成因**，不是真实像素布局。\n');

const bad = (r: Row) => r.chars < 0;
const broken = rows.filter(bad);
if (broken.length) {
  console.log(`  🔴 渲染直接抛异常 ${broken.length} 条：`);
  for (const r of broken.slice(0, 8)) console.log(`     ${r.lang} ${r.word}  ${r.unbreakWho}`);
  console.log('');
}

for (const [lang] of LANGS) {
  if (ONLY && lang !== ONLY) continue;
  const mine = rows.filter((r) => r.lang === lang && !bad(r));
  if (!mine.length) { console.log(`── ${lang}：没取到样本\n`); continue; }
  const top = [...mine].sort((a, b) => b.chars - a.chars).slice(0, 5);
  const maxUn = [...mine].sort((a, b) => b.unbreak - a.unbreak)[0];
  const maxLeaf = [...mine].sort((a, b) => b.leaf - a.leaf)[0];
  const maxRel = [...mine].sort((a, b) => b.relMaxItems - a.relMaxItems)[0];
  console.log(`── ${lang}  取样 ${mine.length} 个极端词条`);
  console.log(`   页面最长        ${f(top[0].chars)} 字   ${top[0].word}（${top[0].arm}）`);
  console.log(`   最长不可断词    ${maxUn.unbreak} 字     ${maxUn.unbreakWho.slice(0, 40)}`);
  console.log(`   单元素最长文本  ${f(maxLeaf.leaf)} 字   ${maxLeaf.word}`);
  console.log(`   单行关系最多    ${f(maxRel.relMaxItems)} 项   ${maxRel.word}（共 ${maxRel.relRow} 行关系）`);
  console.log(`   最大的 5 页：   ${top.map((r) => `${r.word} ${f(r.chars)}`).join(' · ')}`);
  console.log('');
}
