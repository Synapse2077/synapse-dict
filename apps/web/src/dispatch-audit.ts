/**
 * **分发闸**：页面真的走到那个视图了吗。2026-10-06。
 *
 * ═══ 🔴🔴🔴 为什么要有这一条 ═══
 * 用户 2026-10-06 看越南语词条页，页面上只有一行：
 *
 *     🧩 「」的展示层还没接上 —— 数据可能在库里，但这一版读不出来。
 *
 * `「」` 里是**空的**。根因是两个独立的漏：
 *   ① `vietnamese.ts` 的 `VietnameseEntry` 类型和 `getEntry()` 的返回对象
 *      **都没有 `lang` 字段**（`korean.ts` 有 `lang: 'ko'`、`japanese.ts` 有 `lang: 'ja'`）
 *      ⇒ `App.tsx` 的 `entry.lang === 'vi'` 是 `undefined === 'vi'` ⇒ 永远为假
 *      ⇒ **`VietnameseEntryView` 一次都没渲染过**，而 `「{entry.lang}」` 印成了 `「」`。
 *   ② 兜底白名单 `['en','it','fr','pt','de','ja','ko']` 里**没有 `vi`**
 *      ⇒ 即便 ① 修好，兜底那行也会跟真视图一起渲染。
 *
 * ⚠️ **而三道闸当时全绿**，每一道都有结构性的理由看不见它：
 *   · 展示层契约闸 **直接 `createElement(VietnameseEntryView, …)`**，从不走 `App.tsx`
 *     的分发 ⇒ 它测的是「视图对不对」，**不是「视图有没有被调到」**。
 *   · `css-audit` 的自检只问「`export function *EntryView` 都登记进 `VIEWS` 了吗」——
 *     `VietnameseEntryView` 登记了。
 *   · TypeScript 抓不到：`App.tsx` 本地的 `ViEntry` 是**手抄的镜像**且声明了
 *     `lang: 'vi'`，而分发处写的是 `entry as ViEntry`（强转），服务侧的真实形状
 *     与这份镜像之间**没有任何对账**。
 *
 * ⇒ `[[lesson-must-become-mechanism]]` 记的是四道独立关卡
 *   （闸存在／有入口／覆盖这门语言／真被跑），这次漏的是**第五道：页面真的走到它**。
 *
 * ═══ 两条判据 ═══
 * ① **分发的语种 ⊆ 兜底白名单 ∪ 白名单内的特例**。
 *    `App.tsx` 里每一个 `entry.lang === 'xx'` 的分发块，它的 `xx` 都必须让兜底**不**触发；
 *    否则页面上会**同时**渲染真视图和「还没接上」。
 * ② **每个服务的 `getEntry()` 返回对象里必须有 `lang: '<语种码>'`**。
 *    判据钉在源码上（`packages/dict-core/src/<lang>.ts`）而不是跑起来问 ——
 *    跑起来要九个库都在，而这道闸要能在只有一两个库的机器上跑。
 *
 * ⚠️ 判据按**含义**写，不按行号：两边都用正则在源码里找结构，源码挪位置不影响。
 * 🔴 什么会推翻：`App.tsx` 改成别的分发方式（比如查表而不是 `===` 链）——
 *    那时这道闸会报「找不到任何分发块」而**不是静默全绿**（见下面那条自检）。
 *
 * 用法（仓库根目录）：
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/dispatch-audit.ts
 */
import { readFileSync, existsSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

const ROOT = process.cwd();
const APP = join(ROOT, 'apps/web/src/App.tsx');
const CORE = join(ROOT, 'packages/dict-core/src');

const app = readFileSync(APP, 'utf8');
const stripComments = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '');
const body = stripComments(app);

// 九门的服务文件名（它们是**语种码 → 文件**的登记表，照 `getService` 的口径来）
const SERVICES: Array<[string, string]> = [
  ['en', 'english.ts'], ['es', 'spanish.ts'], ['it', 'italian.ts'],
  ['fr', 'french.ts'], ['pt', 'portuguese.ts'], ['de', 'german.ts'],
  ['ja', 'japanese.ts'], ['ko', 'korean.ts'], ['vi', 'vietnamese.ts'],
];

let bad = 0;
console.log('═══ 分发闸：页面真的走到那个视图了吗 ═══\n');

// ── ① 分发的语种 vs 兜底白名单 ──────────────────────────────────────────
const dispatched = [...body.matchAll(/entry\.lang\s*===\s*'([a-z-]+)'/g)].map((m) => m[1]);
const uniq = [...new Set(dispatched)];
// 🔴 **找不到分发块就判红，不是判绿。** 分发方式改掉的话这道闸必须出声，
//    否则它就退化成一条恒绿的闸（`[[permanently-red-gate-masks-real-reds]]` 的镜像）。
if (uniq.length === 0) {
  console.log('🔴 在 App.tsx 里找不到任何 `entry.lang === \'xx\'` 分发块 ——'
    + '\n   分发方式换了？这道闸的判据要跟着换，**不许当成「没问题」**。');
  process.exit(1);
}
const guard = body.match(/!\[([^\]]*)\]\.includes\(entry\.lang\)/);
if (!guard) {
  console.log('🔴 找不到兜底白名单（`![...].includes(entry.lang)`）—— 同上，判据要跟着换。');
  process.exit(1);
}
const whitelist = [...guard[1].matchAll(/'([a-z-]+)'/g)].map((m) => m[1]);
// 白名单之外、但在兜底块里被三元特例接住的（目前只有 es）
const special = [...body.matchAll(/entry\.lang\s*===\s*'([a-z-]+)'\s*\n?\s*\?/g)].map((m) => m[1]);
const covered = new Set([...whitelist, ...special]);
const leak = uniq.filter((l) => !covered.has(l));
console.log(`   分发块里的语种  ${uniq.join(' ')}`);
console.log(`   兜底白名单      ${whitelist.join(' ')}${special.length ? `  （特例：${special.join(' ')}）` : ''}`);
if (leak.length) {
  bad += leak.length;
  console.log(`   🔴 ${leak.length} 门有自己的视图、却**同时**会印「展示层还没接上」：${leak.join(' ')}`);
} else {
  console.log('   ✅ 差集为空：每个有视图的语种都不会再触发兜底');
}

// ── ② 每个服务的 getEntry() 都要返回 lang ───────────────────────────────
console.log('\n   服务侧 `getEntry()` 的返回对象里有没有 `lang`：');
const missing: string[] = [];
for (const [lang, file] of SERVICES) {
  const p = join(CORE, file);
  if (!existsSync(p)) {
    // 🔴 文件不在也要报 —— 空结果不是证据（`[[dont-recast-deliverables-as-junk]]`）
    missing.push(`${lang}(文件不在：${file})`);
    continue;
  }
  const src = stripComments(readFileSync(p, 'utf8'));
  // 🔴🔴 **判据必须分成两条，而我第一版只写了一条、它比要描述的东西更宽。**
  //    第一版写的是 `lang:\s*'<码>'` —— 它**把类型声明也算上了**：
  //        type VietnameseEntry = { lang: 'vi'; … }   ← 分号
  //        return { lang: 'vi', … }                   ← 逗号
  //    而本次的缺陷**恰恰是「类型声明了、返回对象没给」** ⇒ 把 `lang: 'vi',`
  //    从返回对象里删掉之后这条闸照样绿。**是变异验证当场报出来的。**
  //    `[[criteria-narrower-than-you-think]]`：最高频自伤，这次栽在一个标点上。
  // ⇒ 类型成员用 `;` 结尾、对象字面量用 `,` 结尾，按这个分开查，**两条都要绿**。
  // ⚠️ 不去跑 `getEntry()` —— 那要求九个库都在本机，而这道闸要能在只有一两个库的
  //   机器上跑（恒红的闸等于没有闸）。钉在源码上是**可在任何机器上重放**的。
  const inType = new RegExp(`lang:\\s*'${lang}'\\s*;`).test(src);
  const inObject = new RegExp(`lang:\\s*'${lang}'\\s*,`).test(src);
  const ok = inType && inObject;
  console.log(`   ${ok ? '✅' : '🔴'} ${lang.padEnd(3)} ${file}`
    + (ok ? '' : `   （类型 ${inType ? '有' : '🔴 无'} ／ 返回对象 ${inObject ? '有' : '🔴 无'}）`));
  if (!ok) missing.push(`${lang}(${file}：${!inType ? '类型没声明' : '返回对象没给'})`);
}
if (missing.length) {
  bad += missing.length;
  console.log(`   🔴 ${missing.length} 门的服务不返回 \`lang\` ⇒ `
    + '它们的 `entry.lang === \'xx\'` 永远为假、视图一次都不会渲染：'
    + `\n      ${missing.join('、')}`);
}

// ── ③ 这道闸自己的闸：登记表与**运行时注册表**对账 ─────────────────────
// 🔴 `SERVICES` 是手写的登记表 ⇒ 它自己也会漏。
//
// 🔴🔴🔴 **2026-10-07（开 ru 第一天）发现：这条自检从 10-06 建起就是空过的。**
//    原来它读 `apps/api/src/index.ts`、用 `/['"]([a-z]{2})['"]\s*:/` 找语种码，
//    再用写死的 `/^(en|es|it|fr|pt|de|ja|ko|vi)$/` 过滤。而**API 里根本没有语种表**
//    （`langs` 是从 dict-core 的 health 探活结果算出来的）⇒ `apiLangs` 恒为空集
//    ⇒ `unlisted` 恒为空 ⇒ **永远印 ✅**。
//    ⚠️ 逮到它的方式只有一个：**变异验证** —— 从 `SERVICES` 里摘掉 `vi`，
//      它照样印「✅ 本闸登记 8 门，API 认识的都在里面」。
//    ⭐ 两条教训在同一行代码上叠着：
//      · `[[expectation-must-be-declared]]`：两边同时为空的 `A ⊆ B` 恒真，信号量为零；
//      · 写死的九门白名单＝`[[gate-registers-status-quo-as-spec]]`，
//        第十门出现时它会把 ru **筛掉**，于是连「漏登记」都报不出来。
//      ⇒ 修的不是白名单，是**锚**：换到真正握着名单的那个文件上。
//
// ⇒ 真正的登记表是 `packages/dict-core/src/index.ts` 的 `LANGUAGES`（前端语种列表）
//   ＋ `getService()` 的 `lang === 'xx'` 链（谁有专属服务）。两份都查，口径不同：
//     · `LANGUAGES` 少登记一门 ⇒ 这道闸对它失明（本条要治的就是这个）
//     · `getService` 有专属服务而 `SERVICES` 没登记 ⇒ ②（lang 字段）漏查那一门
const corePath = join(CORE, 'index.ts');
if (!existsSync(corePath)) {
  bad += 1;
  console.log(`\n   🔴 找不到语种注册表 ${corePath} —— 本自检的锚没了，`
    + '**这不是「通过」**。');
} else {
  const core = stripComments(readFileSync(corePath, 'utf8'));
  const inLanguages = [...core.matchAll(/\bcode:\s*'([a-z]{2})'/g)].map((m) => m[1]);
  const inGetService = [...core.matchAll(/lang\s*===\s*'([a-z]{2})'/g)].map((m) => m[1]);
  const registry = new Set([...inLanguages, ...inGetService]);
  // 🔴 **一个都没找到就判红。** 空结果不是证据 —— 上面那段就是栽在这儿。
  if (registry.size === 0) {
    bad += 1;
    console.log('\n   🔴 在 `dict-core/index.ts` 里一个语种码都没认出来 ——'
      + '\n      注册表的写法变了？**本自检的判据要跟着改，不许当成「全都登记了」。**');
  } else {
    const declared = new Set(SERVICES.map(([l]) => l));
    const unlisted = [...registry].filter((l) => !declared.has(l));
    console.log(`\n   登记表自检：\`LANGUAGES\` ${inLanguages.length} 门 ／ `
      + `\`getService\` 专属服务 ${new Set(inGetService).size} 门 ／ 本闸登记 ${declared.size} 门`);
    if (unlisted.length) {
      bad += unlisted.length;
      console.log(`   🔴 注册表认识而本闸的 \`SERVICES\` 没登记的语种：${unlisted.join(' ')}`
        + '\n      —— 漏登记一门，这道闸就对那一门结构性失明。');
    } else {
      console.log('   ✅ 注册表里的每一门都在 `SERVICES` 里');
    }
  }
  // ── 第三个锚：**磁盘**。仓库里有 `<xx>/paths.py` 的目录就是一门在做的语言。
  //    它与上面两条的分工：注册表回答「上线了几门」，磁盘回答「在做几门」。
  //    🔴 差额**不判红** —— 正在做而还没上线是正常状态（ru 今天就是）。
  //    但必须**印出来**：ja 的词源层缺席三个月、ko 的 3 道闸从没人跑过，
  //    都是「没人把在做的那门和上线的那门摆在一起看」。
  const langDirs = readdirSync(ROOT, { withFileTypes: true })
    .filter((d) => d.isDirectory() && /^[a-z]{2}$/.test(d.name)
      && existsSync(join(ROOT, d.name, 'paths.py')))
    .map((d) => d.name).sort();
  const notLive = langDirs.filter((l) => !SERVICES.some(([s]) => s === l));
  console.log(`   磁盘上在做 ${langDirs.length} 门（${langDirs.join(' ')}）`
    + (notLive.length ? `；其中**还没有服务**的：${notLive.join(' ')}（在做中，不判红）` : ''));
}

console.log(bad ? `\n🔴 ${bad} 处` : `\n✅ ${SERVICES.length} 门：分发都走得到、服务都返回 lang`);
process.exit(bad ? 1 : 0);
