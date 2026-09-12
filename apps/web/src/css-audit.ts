/**
 * 样式孤儿闸：视图里用到的每一个 className，`styles.css` 里必须真的有规则。2026-09-11。
 *
 * ═══ 为什么要有这一条 ═══
 * 用户 2026-09-11 看 `Curry` 页：「这一部分的字体样式略有差别」，并定下口径
 * **「内容安排可以不一样，但是字体样式应该要统一」**。
 * 一审计才发现问题比"略有差别"大得多 —— **de 的 16 个类名在 `styles.css` 里根本不存在**：
 *
 *     .example-de / .example-zh  都没有规则 ⇒ 德语原文与中文译文**同字号同颜色**
 *     .example-list              没有 `list-style:none` ⇒ 保留浏览器默认项目符号 + 40px 缩进
 *     .de-form-grid              没有规则 ⇒ 9 个变形挤成一行连排
 *     .section-count             没有规则 ⇒ `<h3>词形变化<span>9</span></h3>` 的 9 用 h3 字号印
 *     .rel-row                   **en 与 de 共缺** ⇒ 关系行没有换行、没有间距
 *
 * 🔴 这是 `PITFALLS I3`「自造类名 = 页面没样式，而且探针看不见它」最大的一次实例。
 *    它**比缺陷更难发现**：页面不报错、接口全对、六门契约闸全绿 ——
 *    那些闸问的是「这个类名出现在 HTML 里没有」，而**类名在、规则不在**时它们照样绿。
 *
 * ═══ 判据 ═══
 * 「视图里用到的 className」∖「styles.css 里定义过的类选择器」= ∅。
 * ⚠️ **注释里的类名不算用到** —— 废弃说明里常原样引用旧类名（同一天在
 *    `redo_ecdict_core_gloss.py` 上被自己的注释骗过一次，见 EN_PLAN §17.6）。
 * ⚠️ 模板字符串里的动态片段（`g-${gender}` 这种）跳过：静态查不出它的取值域，
 *    硬报会变成一条**恒红的闸**，而恒红等于没有闸。
 *
 * 用法（仓库根目录）：
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/css-audit.ts
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const SRC = join(process.cwd(), 'apps/web/src');
const app = readFileSync(join(SRC, 'App.tsx'), 'utf8');
const css = readFileSync(join(SRC, 'styles.css'), 'utf8');

const stripComments = (s: string, block: RegExp) => s.replace(block, '');

// `styles.css` 里定义过的类名（注释里写的不算定义）
const defined = new Set(
  [...stripComments(css, /\/\*[\s\S]*?\*\//g).matchAll(/\.([A-Za-z][\w-]*)/g)].map((m) => m[1]),
);

// 六个视图各自的范围：按 `export function XxxEntryView` 切段，方便把孤儿归到语种
const VIEWS: Array<[string, string]> = [
  ['en', 'EnglishEntryView'], ['es', 'SpanishEntryView'], ['it', 'ItalianEntryView'],
  ['fr', 'FrenchEntryView'], ['pt', 'PortugueseEntryView'], ['de', 'GermanEntryView'],
];
const marks = VIEWS
  .map(([lang, fn]) => ({ lang, at: app.indexOf(`export function ${fn}`) }))
  .filter((x) => x.at >= 0)
  .sort((a, b) => a.at - b.at);

// 🔴🔴 **第一个视图之前的那一段原来完全没人扫。**
//    2026-09-12 加共用组件 `CollocationSection`（五门的「搭配 / 固定短语」都由它渲染）
//    时才发现：它定义在六个视图**之前**，所以它用的 `.src-note` / `.colloc-list`
//    一个都不在扫描范围里 —— 闸报「六门 0 孤儿」，而那条规则当时根本还没写。
//    `HumanAudioRow`（六门的真人发音行）、搜索结果列表的 `.result-via` 同理。
//    ⇒ 加一个 `shared` 段，覆盖文件开头到第一个视图之间的全部代码。
//    ⚠️ 这就是 `[[correct-steps-can-compose-a-hole]]`：**每个视图都扫了、
//      共用件没人扫 —— 闸的覆盖面和它自称的「六门」之间差了一块，谁都没负责。**
if (marks.length > 0) marks.unshift({ lang: 'shared(共用件)', at: 0 });

// 🔴 只收**静态**类名：合法 CSS 标识符，且不含模板插值。
//    第一版没做这一步，`className={`badge g-${g0}`}` 里的 `'avoir'}` `?` `:` `===`
//    这些三元片段被当成类名报出来 —— **闸自己制造的假红比漏报更浪费人**。
const STATIC = /^[A-Za-z][\w-]*$/;

let bad = 0;
console.log('═══ 样式孤儿闸：视图用到的类名，styles.css 里必须有规则 ═══\n');
console.log(`  styles.css 定义了 ${defined.size} 个类\n`);
for (let i = 0; i < marks.length; i += 1) {
  const { lang, at } = marks[i];
  const end = i + 1 < marks.length ? marks[i + 1].at : app.length;
  const body = stripComments(app.slice(at, end), /\/\*[\s\S]*?\*\//g);
  const used = new Set<string>();
  for (const m of body.matchAll(/className=(?:"([^"]+)"|\{`([^`]+)`\})/g)) {
    for (const tok of (m[1] ?? m[2] ?? '').split(/\s+/)) {
      if (STATIC.test(tok)) used.add(tok);
    }
  }
  const orphans = [...used].filter((u) => !defined.has(u)).sort();
  bad += orphans.length;
  console.log(`   ${orphans.length ? '🔴' : '✅'} ${lang}  用到 ${used.size} 个类`
    + (orphans.length ? `，其中 ${orphans.length} 个没有规则：${orphans.join(' ')}` : ''));
}

// 🔴 反向：`styles.css` 里定义了却没人用的类。**只报不拦** ——
//    共用件里有一批是给别处（搜索列表、空状态、主题切换）用的，不在本文件的扫描范围内。

// ══════════════════════════════════════════════════════════════════
// 第二条：**裸的行内包装元素**
//
// 🔴🔴 起因：用户看 de 的 `Frau` 页问「这个下位怎么所有的字母连在一起了」——
//    页面上是 `下位 AmmenfrauAmtfrauAufwartefrau…`。根子是 de 的关系目标写成
//    **光秃秃的 `<span key={ti}>`，一个 className 都没有**，
//    而 es/it/en/pt 用的都是 `.rel-item { margin-right: 8px }`。
//    这是 de **第三次**"少写 className"（前两次：8 处裸 `<a>`、16 个没有规则的类名）。
//
// ⚠️ **上面那条孤儿类名检查在构造上看不见它** —— 没有类名就没有孤儿。
// ⚠️ `render-dump` 也看不见：它给每个 `</span>` 补空格，快照里一直是分开的；
//    而改成"不补"会造出反方向的假象（`ENwoman`，其实 CSS 有 margin）。
//    **文本导出器在原理上看不见 CSS 间距 ⇒ 这件事只能在源码层守。**
//
// 判据：包着 `.rel-link` / `.rel-plain` 的 `<span>` 必须自己带 className。
//   `<span key={...}>` 后面紧跟 `{...clickable ? <a className="rel-link"` 的那种。
// ⚠️ 只查这一种形状，不泛泛地禁止裸 `<span>` —— 后者会把一堆正当用法圈进来
//    （`[[criteria-narrower-than-you-think]]`：判据比它要描述的东西宽）。
// ⚠️ **第一版就宽了**：它把 pt 报成红的，而 pt 那处写着 `{i > 0 && '、'}` ——
//    **间距由内容给，不靠 CSS**，那是正当写法。⇒ 排除含显式分隔符的包装。
//    （同一天第二次：判据写完先问「它圈中的里面有没有正常的」。）
const naked: string[] = [];
for (let i = 0; i < marks.length; i += 1) {
  const { lang, at } = marks[i];
  const end = i + 1 < marks.length ? marks[i + 1].at : app.length;
  const body = stripComments(app.slice(at, end), /\/\*[\s\S]*?\*\//g);
  for (const m of body.matchAll(/<span(?![^>]*className)[^>]*>[\s\S]{0,200}?rel-(?:link|plain)/g)) {
    // 含显式分隔符（`{i > 0 && '、'}` 一类）的不算 —— 间距由内容给
    if (/&&\s*'[^']+'/.test(m[0])) continue;
    naked.push(`${lang}: ${m[0].slice(0, 46).replace(/\s+/g, ' ')}…`);
  }
}
console.log(`\n   ${naked.length ? '🔴' : '✅'} 裸的关系项包装 `
  + (naked.length ? `${naked.length} 处：` : '0 处'));
for (const x of naked) console.log(`      ${x}`);

const total = bad + naked.length;
console.log(total ? `\n🔴 ${bad} 个孤儿类名 ／ ${naked.length} 处裸包装`
  : '\n✅ 六门：0 孤儿类名、0 裸包装');
process.exit(total ? 1 : 0);
