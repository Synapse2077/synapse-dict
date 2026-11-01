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
// 变异验证用：`CSS_AUDIT_APP_SRC` 指向一份改坏的 App.tsx 副本（真文件不动），见下面自检的注释
const app = readFileSync(process.env.CSS_AUDIT_APP_SRC || join(SRC, 'App.tsx'), 'utf8');
// 变异验证用：`CSS_AUDIT_CSS_SRC` 指向一份样式表副本（真文件不动）
const css = readFileSync(process.env.CSS_AUDIT_CSS_SRC || join(SRC, 'styles.css'), 'utf8');

const stripComments = (s: string, block: RegExp) => s.replace(block, '');

// `styles.css` 里定义过的类名（注释里写的不算定义）
const defined = new Set(
  [...stripComments(css, /\/\*[\s\S]*?\*\//g).matchAll(/\.([A-Za-z][\w-]*)/g)].map((m) => m[1]),
);

// 六个视图各自的范围：按 `export function XxxEntryView` 切段，方便把孤儿归到语种
// 🔴 2026-09-17 加 ja。**它漏登记了整整九个阶段**，而本闸照样报绿 ——
//    因为分段是「从这个视图的定义处到下一个视图」，最后一个视图的段一直延伸到文件尾，
//    于是 `JapaneseEntryView` 的类名被算进了 **de 的账上**。
//    ⭐ 结果是：缺陷**逮到了**（33 个孤儿），但**归错了语种**。
//      这比漏掉更阴险一点 —— 报告上写着「de 有 33 个孤儿」，我会去翻德语视图。
//    ⚠️ 与上面那条 `shared` 注释是同一个形状（`[[correct-steps-can-compose-a-hole]]`）：
//      分段逻辑本身没错，错在**这张表和 `App.tsx` 里实际有几个视图之间没有闸**。
//    ⇒ 下面加了一条自检：本文件里 `export function *EntryView` 有几个，这张表就得有几行。
// 🔴🔴 2026-09-26 加 ko。**而这一次自检是对的、闸是红的、没人跑过它。**
//    上面那条自检（`unlisted` → `process.exit(1)`）从 `KoreanEntryView` 进
//    `App.tsx` 那天（阶段 9，09-25）起就一直在报红，退出码 1。
//    ⇒ 漏的不再是「自检」，而是**没有任何东西逼人跑这道闸**。
//      这与 ko 的 K31 是同一个病的第三例（另两例是两道外锚闸从 09-25 红到 09-26）。
//      ⇒ 已登记进 `ko/gates.py` 的闸名单，`python3 ko/run_gates.py --all` 会跑它。
const VIEWS: Array<[string, string]> = [
  ['en', 'EnglishEntryView'], ['es', 'SpanishEntryView'], ['it', 'ItalianEntryView'],
  ['fr', 'FrenchEntryView'], ['pt', 'PortugueseEntryView'], ['de', 'GermanEntryView'],
  ['ja', 'JapaneseEntryView'], ['ko', 'KoreanEntryView'],
  // 🔴 2026-10-03 补登记。**这道闸的自检当场就逮到它没登记** ——
  //    而它在 vi 的阶段 9 里从头到尾没被跑过一次。
  //    `[[lesson-must-become-mechanism]]`：「闸存在／有入口／覆盖这门语言／真被跑」
  //    是**四道独立关卡**，vi 过了前两道就被当成过了四道。
  ['vi', 'VietnameseEntryView'],
  ['ru', 'RussianEntryView'],
];

// 🔴 登记表与源码对账：漏登记一个视图，本闸会把它的类名算到别人头上。
const declared = new Set(VIEWS.map(([, fn]) => fn));
const inSource = [...app.matchAll(/export function (\w+EntryView)\b/g)].map((m) => m[1]);
const unlisted = inSource.filter((fn) => !declared.has(fn));
// 🔴🔴 B23 那一类（2026-10-30 补）：上面只问「源码里有的都登记了」，两个方向漏了一个、空集还恒真 ——
//    ① 正则一个视图都没认出来（改成 `export const XxxEntryView =`、或视图搬出 App.tsx）⇒ `inSource` 空
//       ⇒ `unlisted` 空 ⇒ 自检静默通过，而下面的审计一门都没做；
//    ② 登记了而源码里找不到（改名／搬走）⇒ `marks` 那一步 `.filter(at >= 0)` **悄悄丢掉这一门**，照样报绿。
//    变异（`CSS_AUDIT_APP_SRC` 指向副本）：把 `export function` 全改成 `export const` ⇒ 判红；
//    把 `RussianEntryView` 改名 ⇒ 判红。
if (inSource.length === 0) {
  console.log('\n🔴 判据坏了：App.tsx 里一个 `export function XxxEntryView` 都没认出来 —— 空结果不是「全登记了」');
  process.exit(1);
}
const vanished = [...declared].filter((fn) => !inSource.includes(fn));
if (vanished.length) {
  console.log(`\n🔴 VIEWS 登记了而 App.tsx 里找不到：${vanished.join(', ')} —— 这几门的类名审计会被静默跳过`);
  process.exit(1);
}
if (unlisted.length) {
  console.log(`\n🔴 App.tsx 里有没登记进 VIEWS 的视图：${unlisted.join(', ')}`
    + '\n   —— 它们的类名会被算到上一个视图的账上，报告会指错语种。');
  process.exit(1);
}
// ══════════════════════════════════════════════════════════════════
// 🔴🔴 B15③（2026-10-31）：**按组件归属，不按位置切段**。
//    原来按 `export function XxxEntryView` 的位置切：一段从这个视图一直延伸到下一个视图 ⇒
//    **定义在两个视图之间的辅助组件，类名算到前一门头上**（`KoReadingRow` 定义在 `KoreanEntryView`
//    之前 ⇒ 它的 `badge src-note`/`badge endorsed` 被报成 **ja** 的孤儿，09-26 我照着去翻了 ja 的视图）。
//    09-17 那次（`JapaneseEntryView` 的类名算进 de）补的是「登记表要齐」的自检，**分段本身没改**。
//    ⇒ 现在：把 App.tsx 拆成顶层定义，从每门的视图出发顺着「用到了谁」走一遍；
//      只被**一门**的视图够得着的组件归那一门，被多门够得着或谁都够不着的归 `shared(共用件)`。
//      报告带组件名 —— 指到函数，不指到「某门的视图附近」。
// ══════════════════════════════════════════════════════════════════
type Def = { name: string; at: number; end: number };

function topDefs(src: string): Def[] {
  const ms = [...src.matchAll(/^(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|const|let|class)\s+([A-Za-z_$][\w$]*)/gm)];
  return ms.map((m, i) => ({ name: m[1], at: m.index!, end: i + 1 < ms.length ? ms[i + 1].index! : src.length }));
}

/** 组件 → 归属语种（只被一门的视图够得着）或 'shared(共用件)'。 */
function owners(src: string, defs: Def[]): Map<string, string> {
  const names = new Set(defs.map((d) => d.name));
  const uses = new Map<string, Set<string>>();
  for (const d of defs) {
    const body = stripComments(src.slice(d.at, d.end), /\/\*[\s\S]*?\*\//g).replace(/^\s*\/\/.*$/gm, '');
    const u = new Set<string>();
    for (const m of body.matchAll(/\b([A-Za-z_$][\w$]*)\b/g)) if (names.has(m[1]) && m[1] !== d.name) u.add(m[1]);
    uses.set(d.name, u);
  }
  const reach = new Map<string, Set<string>>();             // 组件 → 够得着它的语种
  for (const [lang, fn] of VIEWS) {
    const seen = new Set<string>([fn]);
    const stack = [fn];
    while (stack.length) {
      for (const v of uses.get(stack.pop()!) ?? []) if (!seen.has(v)) { seen.add(v); stack.push(v); }
    }
    for (const c of seen) (reach.get(c) ?? reach.set(c, new Set()).get(c)!).add(lang);
  }
  const out = new Map<string, string>();
  for (const d of defs) {
    const r = reach.get(d.name);
    out.set(d.name, r && r.size === 1 ? [...r][0] : 'shared(共用件)');
  }
  return out;
}

// 🔴 只收**静态**类名：合法 CSS 标识符，且不含模板插值。
//    第一版没做这一步，`className={`badge g-${g0}`}` 里的 `'avoir'}` `?` `:` `===`
//    这些三元片段被当成类名报出来 —— **闸自己制造的假红比漏报更浪费人**。
const STATIC = /^[A-Za-z][\w-]*$/;

/** → 每个归属下：用到的类名数、孤儿（带组件名）；以及裸包装。真跑与变异走同一个函数。 */
function audit(src: string) {
  const defs = topDefs(src);
  const own = owners(src, defs);
  const head = defs.length ? defs[0].at : src.length;      // 第一个顶层定义之前（import 等）
  const segs: Array<{ comp: string; owner: string; body: string }> = [
    { comp: '(文件头)', owner: 'shared(共用件)', body: src.slice(0, head) },
    ...defs.map((d) => ({ comp: d.name, owner: own.get(d.name)!, body: src.slice(d.at, d.end) })),
  ];
  const byOwner = new Map<string, { used: Set<string>; orphans: string[] }>();
  const naked: string[] = [];
  for (const s of segs) {
    const body = stripComments(s.body, /\/\*[\s\S]*?\*\//g);
    const slot = byOwner.get(s.owner) ?? byOwner.set(s.owner, { used: new Set(), orphans: [] }).get(s.owner)!;
    for (const m of body.matchAll(/className=(?:"([^"]+)"|\{`([^`]+)`\})/g)) {
      for (const tok of (m[1] ?? m[2] ?? '').split(/\s+/)) {
        if (!STATIC.test(tok)) continue;
        slot.used.add(tok);
        if (!defined.has(tok) && !slot.orphans.includes(`${tok}（${s.comp}）`)) slot.orphans.push(`${tok}（${s.comp}）`);
      }
    }
    // 第二条：**裸的行内包装元素**（判据与来历见下方长注释）
    for (const m of body.matchAll(/<span(?![^>]*className)[^>]*>[\s\S]{0,200}?rel-(?:link|plain)/g)) {
      if (/&&\s*'[^']+'/.test(m[0])) continue;
      naked.push(`${s.owner}（${s.comp}）: ${m[0].slice(0, 46).replace(/\s+/g, ' ')}…`);
    }
  }
  return { byOwner, naked };
}

// ══════════════════════════════════════════════════════════════════
// 第二条：**裸的行内包装元素**
//
// 🔴🔴 起因：用户看 de 的 `Frau` 页问「这个下位怎么所有的字母连在一起了」——
//    页面上是 `下位 AmmenfrauAmtfrauAufwartefrau…`。根子是 de 的关系目标写成
//    **光秃秃的 `<span key={ti}>`，一个 className 都没有**，
//    而 es/it/en/pt 用的都是 `.rel-item { margin-right: 8px }`。
//    这是 de **第三次**"少写 className"（前两次：8 处裸 `<a>`、16 个没有规则的类名）。
//
// ⚠️ **孤儿类名检查在构造上看不见它** —— 没有类名就没有孤儿。
// ⚠️ `render-dump` 也看不见：它给每个 `</span>` 补空格，快照里一直是分开的；
//    而改成"不补"会造出反方向的假象（`ENwoman`，其实 CSS 有 margin）。
//    **文本导出器在原理上看不见 CSS 间距 ⇒ 这件事只能在源码层守。**
//
// 判据：包着 `.rel-link` / `.rel-plain` 的 `<span>` 必须自己带 className。
// ⚠️ 只查这一种形状，不泛泛地禁止裸 `<span>`（`[[criteria-narrower-than-you-think]]`）。
// ⚠️ **第一版就宽了**：它把 pt 报成红的，而 pt 那处写着 `{i > 0 && '、'}` ——
//    **间距由内容给，不靠 CSS**，那是正当写法。⇒ 排除含显式分隔符的包装。
// 🔴 反向：`styles.css` 里定义了却没人用的类 —— 不在本闸（B16）。

const { byOwner, naked } = audit(app);
let bad = 0;
console.log('═══ 样式孤儿闸：视图用到的类名，styles.css 里必须有规则 ═══\n');
console.log(`  styles.css 定义了 ${defined.size} 个类；归属按组件调用关系（只被一门用到的归那一门）\n`);
for (const lang of ['shared(共用件)', ...VIEWS.map(([l]) => l)]) {
  const s = byOwner.get(lang) ?? { used: new Set<string>(), orphans: [] };
  bad += s.orphans.length;
  console.log(`   ${s.orphans.length ? '🔴' : '✅'} ${lang}  用到 ${s.used.size} 个类`
    + (s.orphans.length ? `，其中 ${s.orphans.length} 个没有规则：${s.orphans.sort().join(' ')}` : ''));
}
console.log(`\n   ${naked.length ? '🔴' : '✅'} 裸的关系项包装 ` + (naked.length ? `${naked.length} 处：` : '0 处'));
for (const x of naked) console.log(`      ${x}`);

// ── 变异（每次都跑，与真跑同一个 `audit()`；改的是内存里的副本）──
//   M1 ko 专用的辅助组件（定义在 `KoreanEntryView` **之前**）里塞一个没规则的类 ⇒ 必须记在 **ko** 名下
//      （按位置切段时它会落到 ja —— 这条就是 B15③ 本身）
//   M2 多门共用的组件（`RelationGroups`，es/it 都用）里塞一个 ⇒ 必须记在 shared
//   M3 反控制：不动 ⇒ 孤儿数与真跑相同
const MUT = 'zz-mut-orphan';
const inject = (src: string, fn: string) => {
  const at = src.search(new RegExp(`^(?:export\\s+)?function\\s+${fn}\\b`, 'm'));
  if (at < 0) throw new Error(`变异锚点没了：${fn}`);
  const k = src.indexOf('className="', at);
  return src.slice(0, k) + `className="${MUT} ` + src.slice(k + 'className="'.length);
};
const hasMut = (r: ReturnType<typeof audit>, owner: string) =>
  (r.byOwner.get(owner)?.orphans ?? []).some((o) => o.startsWith(MUT));
const muts: Array<[string, boolean]> = [
  ['M1 ko 专用辅助组件（KoReadingRow，定义在视图之前）的孤儿记在 ko 名下', hasMut(audit(inject(app, 'KoReadingRow')), 'ko')],
  ['M2 共用组件（RelationGroups）的孤儿记在 shared 名下', hasMut(audit(inject(app, 'RelationGroups')), 'shared(共用件)')],
  ['M3 反控制：不动则孤儿数不变', [...audit(app).byOwner.values()].reduce((n, s) => n + s.orphans.length, 0) === bad],
];
const mutFail = muts.filter(([, ok]) => !ok);
console.log(`\n   变异 ${muts.length - mutFail.length}/${muts.length}`);
for (const [l, ok] of muts) console.log(`      ${ok ? '✅' : '🔴 没逮到：'} ${l}`);

// ══════════════════════════════════════════════════════════════════
// 第三条（B16，2026-10-31）：**反方向 —— styles.css 里写了、页面代码里没人用的类**。
//   渲染测量（469 页 × 491 条选择器）量出 37 条这样的死规则：西语早期义项折叠 `.es-senses-*` 一整套、
//   `.definition-list`、`.freq-row`、`.sense-more`、`button.rel-link`……。死规则本身不伤读者，伤的是下一个人：
//   改样式时去改一条早就不生效的规则，页面纹丝不动。
//   判据（静态、确定）：类名在**上线的界面代码**（App.tsx ＋ main.tsx，**去掉注释**）里以整词出现，
//   或者能由源码里的动态前缀拼出来（`g-${gender}`、`aux-${…}`、`cefr-${…}`）。
//   ⚠️ 必须先去掉注释：`.section-count` 在注释里被提到过好几次，不去注释它就「在用」（判据变宽）。
//   ⚠️ 只认上线代码：`layout-probe.tsx` 这类工具提到一个类名，不说明页面在用。
//   🔴 管不到「类名都在、组合选择器嵌套对不上」的那一类（`.pos-group:first-child .etym-label` 十门从没匹配过）——
//      那要渲染才看得出，实测 491 条里只有这 1 条，有意不为它造一道带长串豁免的渲染闸。
//      翻案条件：再出现一条同类（嵌套写错、渲染测量才逮到）⇒ 把渲染测量做成闸。
const SHIPPED = ['App.tsx', 'main.tsx'];
const stripJs = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1');
function deadRules(cssText: string, srcText: string): string[] {
  const src = stripJs(srcText);
  const prefixes = [...src.matchAll(/(?<![\w-])([a-z][\w-]*-)\$\{/g)].map((m) => m[1]);
  const cls = new Set([...stripComments(cssText, /\/\*[\s\S]*?\*\//g).matchAll(/\.([A-Za-z][\w-]*)/g)].map((m) => m[1]));
  return [...cls].filter((c) => !new RegExp(`(?<![\\w-])${c.replace(/[-]/g, '\\-')}(?![\\w-])`).test(src)
    && !prefixes.some((pre) => c.startsWith(pre))).sort();
}
const shippedSrc = SHIPPED.map((f) => readFileSync(join(SRC, f), 'utf8')).join('\n');
const dead = deadRules(css, shippedSrc);
console.log(`\n   ${dead.length ? '🔴' : '✅'} styles.css 里没人用的类 ${dead.length} 个${dead.length ? '：' + dead.join(' ') : ''}`);
const m4 = deadRules(css + '\n.zz-dead-rule { color: red; }\n', shippedSrc).includes('zz-dead-rule');
const m5 = deadRules(css + '\n.zz-dead-rule { color: red; }\n', shippedSrc + '\n/* zz-dead-rule 只在注释里 */\n').includes('zz-dead-rule');
const m6 = !deadRules(css + '\n.g-zz { color: red; }\n', shippedSrc).includes('g-zz');   // 反控：动态前缀 `g-${…}` 拼得出
for (const [l, ok] of [['M4 样式表多一条没人用的类 → 报出', m4], ['M5 只在注释里提到它 → 仍报出（注释不算用）', m5],
  ['M6 反控：动态前缀拼得出的（g-…）不报', m6]] as Array<[string, boolean]>) {
  console.log(`      ${ok ? '✅' : '🔴 没逮到：'} ${l}`);
  if (!ok) mutFail.push([l, ok]);
}

const total = bad + naked.length + mutFail.length + dead.length;
console.log(total ? `\n🔴 ${bad} 个孤儿类名 ／ ${naked.length} 处裸包装 ／ ${dead.length} 个没人用的类 ／ ${mutFail.length} 条变异没逮到`
  : `\n✅ ${VIEWS.length} 门：0 孤儿类名、0 裸包装、0 死规则（归属按组件）`);
process.exit(total ? 1 : 0);
