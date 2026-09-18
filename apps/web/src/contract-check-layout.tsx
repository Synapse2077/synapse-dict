/**
 * 六门展示层**共同契约**闸：块序 ＋ 关系分级。跨 en/es/it/fr/pt/de。2026-09-12。
 *
 * ═══ 起因 ═══
 * 用户：「我看到英语和西语的一个不同，估计其他语言也存在。释义部分，
 *        en/es 什么的和近义/反义的展示顺序好像不一样」。
 * 一量，六个视图**六种顺序**：
 *
 *     en   中文 → 标签 → 原文定义 → 异体 → 关系 → 例句      ← 基准
 *     de   中文 → 原文定义 → 异体 → 关系 → 例句             ← 同上
 *     pt   中文 → 原文定义 → 异体 → 例句 → 关系             🔴 关系跑到例句后
 *     es   中文 → 中文副行 → 关系 → 例句 → 原文定义         🔴 原文定义排到最后
 *     it   中文 → 原文定义 → 例句
 *     fr   中文 → 原文定义 → 例句
 *
 * ═══ 判据：**子序列**，不是相等 ═══
 * 六门的**内容**本来就不一样（it/fr 目前没有义项级关系块，只有 es 有中文副行），
 * 要求"完全相等"会把正当差异判成错。⇒ 判据是
 *     渲染出来的角色序列，必须是规范序列的一个**子序列**。
 * 少一块不算错（内容差异），**换位置就算错**（顺序差异）。
 * 用户 2026-09-11 定的口径正是这个：「内容安排可以不一样，但是字体样式应该要统一」。
 *
 * ═══ 规范序列为什么是这个 ═══
 * 不是"多数服从少数"，是**读的顺序**：
 *   先说是什么（中文）→ 限定（标签/副行）→ 精确定义（原文）→
 *   这是谁的另一种写法（异体）→ 相关的词（关系）→ 怎么用（例句）。
 * 例句最长、放最后；关系是"别的词"，不该插在例句之间。
 *
 * ⚠️ **按角色比，不按类名比** —— 六门的类名本来就不同
 *   （`sense-rels` / `sense-relations` / `rel-row` 都是"关系"）。
 *   拿类名当判据就是把实现细节钉死。
 *
 * ═══ 用法（仓库根目录）═══
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-layout.tsx
 *     npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-layout.tsx --mutate
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { getService } from '@synapse-dict/dict-core';
import {
  EnglishEntryView, SpanishEntryView, ItalianEntryView,
  FrenchEntryView, PortugueseEntryView, GermanEntryView, JapaneseEntryView,
} from './App';

const mutate = process.argv.includes('--mutate');
// 🔴 2026-09-17 加 ja。**这是第三张忘了登记日语的表**（另两张：`render-dump.tsx`
//    的 `View` 分支、`css-audit.ts` 的 `VIEWS`）。三张表都是"加语言时要来加一行"，
//    三张都漏了，而**三道闸全绿** —— 因为它们查的是"登记了的那几门对不对"，
//    没有一条查"是不是所有门都登记了"（`[[lesson-must-become-mechanism]]`）。
//    ⇒ `css-audit.ts` 已经补上了"源码里有几个视图，表里就得有几行"的自检。
type Lang = 'en' | 'es' | 'it' | 'fr' | 'pt' | 'de' | 'ja';
const LANGS: Lang[] = ['en', 'es', 'it', 'fr', 'pt', 'de', 'ja'];
const VIEW: Record<Lang, unknown> = {
  en: EnglishEntryView, es: SpanishEntryView, it: ItalianEntryView,
  fr: FrenchEntryView, pt: PortugueseEntryView, de: GermanEntryView,
  ja: JapaneseEntryView,
};

/** 规范序列。角色 → 六门各自认得出它的类名（任一命中即可）。 */
const CANON: Array<[string, RegExp]> = [
  ['中文', /class="sense-zh"/],
  ['中文副行', /class="(sense-detail|sense-alt-zh)"/],
  ['原文定义', /class="sense-src"/],
  ['异体', /class="sense-altof"/],
  ['关系', /class="(rel-row|sense-relations|sense-rels|rel-group)"/],
  // ⚠️ ja 的义项内例句用的是共用的 `.example-list`（`<ul>` 容器），
  //    正文那一层是 `.example-text` —— 两个名字都要认，否则日语的例句块
  //    在本闸眼里根本不存在，序列永远"合规"。
  ['例句', /class="(sense-example|example-item|example-text)"/],
];
const ROLES = CANON.map(([n]) => n);

/** 一条义项里各角色**首次出现**的先后。 */
function rolesOf(seg: string): string[] {
  const hits: Array<[number, string]> = [];
  for (const [name, re] of CANON) {
    for (const m of seg.matchAll(new RegExp(re.source, 'g'))) hits.push([m.index!, name]);
  }
  const seen = new Set<string>();
  const out: string[] = [];
  for (const [, n] of hits.sort((a, b) => a[0] - b[0])) {
    if (!seen.has(n)) { seen.add(n); out.push(n); }
  }
  return out;
}

/** `got` 是不是 `ROLES` 的子序列。 */
function isSubsequence(got: string[]): boolean {
  let i = 0;
  for (const g of got) {
    const j = ROLES.indexOf(g, i);
    if (j < 0) return false;
    i = j + 1;
  }
  return true;
}

function render(lang: Lang, entry: unknown): string {
  return renderToStaticMarkup(createElement(VIEW[lang] as never, {
    entry: entry as never, speakLocale: 'x', onWord: () => {}, speak: () => {},
  } as never));
}

// ── 取样：**按"块数最多"取**，不是随机 ──
// 🔴 随机取到的多半是只有中文一块的义项 —— 那种义项的序列是任何序列的子序列，
//    闸就永远绿。⇒ 每门取一批常见词，只把**至少 3 个角色**的义项算进来。
const SEEDS: Record<Lang, string[]> = {
  en: ['dog', 'run', 'house', 'gore', 'curious', 'bank', 'light', 'set'],
  es: ['perro', 'casa', 'correr', 'mano', 'banco', 'luz', 'tiempo', 'pie'],
  it: ['cane', 'casa', 'correre', 'mano', 'banco', 'luce', 'tempo', 'piede'],
  fr: ['chien', 'maison', 'courir', 'main', 'banque', 'temps', 'pied', 'jour'],
  pt: ['cão', 'casa', 'correr', 'mão', 'banco', 'luz', 'tempo', 'pé'],
  de: ['Hund', 'Haus', 'laufen', 'Hand', 'Bank', 'Licht', 'Zeit', 'Fuß'],
  // 日语挑的是**块数多**的：`猫`/`桜` 关系怪物、`食べる`/`行く` 活用怪物、
  // `時間` 例句最多、`心`/`水`/`山` 义项多。
  ja: ['猫', '桜', '食べる', '行く', '時間', '心', '水', '山'],
};

const pages: Array<[string, string[]]> = [];     // [词, 角色序列]
const fullPages: Array<[string, string]> = [];   // [词, 整页 HTML]
const bucket = new Map<string, number>();
const seenOrder = new Map<Lang, Set<string>>();
for (const lang of LANGS) {
  const svc = getService(lang) as unknown as { getEntry: (w: string) => unknown };
  let n = 0;
  seenOrder.set(lang, new Set());
  for (const w of SEEDS[lang]) {
    const e = svc.getEntry(w);
    if (!e) continue;
    const html = render(lang, e);
    fullPages.push([`${lang} ${w}`, html]);
    for (const m of html.matchAll(/<li class="sense-item"[^>]*>([\s\S]*?)<\/li>/g)) {
      const roles = rolesOf(m[1]);
      if (roles.length < 3) continue;            // 块太少，测不出顺序
      pages.push([`${lang} ${w}`, roles]);
      seenOrder.get(lang)!.add(roles.join(' → '));
      n += 1;
    }
  }
  bucket.set(lang, n);
}

console.log('═══ 契约闸（义项内块序）：六门必须是同一个规范序列的子序列 ═══\n');
console.log(`  规范：${ROLES.join(' → ')}\n`);
console.log(`  取样 ${pages.length} 条义项（只算块数 ≥3 的）：`);
for (const lang of LANGS) {
  console.log(`    ${lang}  ${String(bucket.get(lang) ?? 0).padStart(3)} 条 ｜ `
    + [...(seenOrder.get(lang) ?? [])].slice(0, 2).join('  ／  '));
}

const bad: string[] = [];
for (const [w, roles] of pages) {
  if (!isSubsequence(roles)) bad.push(`${w}：${roles.join(' → ')}`);
}
console.log(bad.length
  ? `\n🔴 ${bad.length} 条义项的块序不合规范\n` + bad.slice(0, 8).map((x) => `     ${x}`).join('\n')
  : `\n✅ 块序：${pages.length} 条义项全部合规`);

// ══ 第二组：关系分级 ══════════════════════════════════════════════════════
//
// 🔴🔴 起因：给 it/fr 补义项级关系时发现，**de 和 en 早就在印两遍了**。
//    六门都写着「词条级只取 `sense_id IS NULL`」，而那个过滤**不够** ——
//    库里同一条 (词, 类型, 目标) 可以有两行（一行带归属、一行不带），
//    两级各取一行就印两遍。实测：de 24,149 组 ／ it 9,173 ／ fr 7,153 ／
//    en 4,050 ／ es 44 ／ **pt 0**。
//    ⚠️ **pt 恰好是 0，而"同一条关系两级各印一遍"这条断言只有 pt 的闸有** ——
//      一条守着零缺陷的断言，和没有断言是一样的。这正是
//      `FRAMEWORK` 那一节说的：判据写在一门之内，缺陷长在门与门之间。
// 🔴🔴 **判据第一版太宽，当场报 23 个词条页假红。** 它数的是"同一个字面在整页
//    出现几次"，于是把两类**正当**的重复也算了进去：
//      ① 词形变化区／异体区也用 `.rel-link`（`en run` 的 `ran`、`runs`）；
//      ② **同一个近义词出现在两条不同义项下**（`en dog` 的 `canid` 在 3 条义项里）——
//         那是逐义项信息，不是重复。
//    ⇒ 收窄到我真正修的那个缺陷：**同一条 (类型, 目标) 同时出现在义项内与词条级**。
//      那一条是**不含糊的错**：词条级那句话在说"这适用于整个词"，
//      而它已经被归到某条义项上了。
//    `[[criteria-narrower-than-you-think]]`：判据比它要描述的东西宽 —— 今天第二次。

/** 把整页切成「义项内」与「义项外」两段。 */
function splitBySense(html: string): { inSense: string; outSense: string } {
  let inSense = '';
  const outSense = html.replace(/<li class="sense-item"[^>]*>[\s\S]*?<\/li>/g, (m) => {
    inSense += m;
    return '';
  });
  return { inSense, outSense };
}

/**
 * 一段 HTML 里的「关系」项，形如 `派生｜Häusle`。
 *
 * 🔴 **逐个 `class=` 扫，不按容器切、也不按 `.rel-item` 切。**
 *    按 `.rel-item` 切的那一版有个静默 bug：`rel-item` 里**嵌着** `rel-plain`，
 *    非贪婪的 `[\s\S]*?</span>` 停在内层 `</span>` ⇒ **所有不可点的目标被漏掉**，
 *    而页面上它们是实打实印着的。变异注入一条 `rel-plain` 时当场露馅（打红 0/26）。
 *    ⇒ 改成逐个类名扫描 + `kind` 在离开关系块时清空。
 * 🔴 **原来按容器类名切也不行**： 第二版拿
 *    `<div class="rel-row|rel-group|…">` 起头、非贪婪匹配到下一个块 —— 而在
 *    词条级那一段后面**没有可匹配的收尾**，正则一路贪到页尾，把 de 的**构词区**
 *    （`.de-form-cell` 里也用 `.rel-link`）整个吃了进来 ⇒ `de Haus：派生 Häusle` 假红。
 *    `.rel-item` 只出现在关系项上（六门共用的 `RelationGroups` 就是这么渲染的），
 *    构词区、词形变化区、异体区都不用它 —— **它才是这件事的判别特征**。
 * ⚠️ `kind` 取**同一个关系组内**最近的一个 `.rel-kind`：`run → antonym: rise` 与
 *    `run → hypernym: rise` 是两句不同的话，去重不能把它们并掉。
 */
function relPairs(seg: string): Set<string> {
  const out = new Set<string>();
  let kind = '';
  // 关系块**内部**允许出现的类名 —— 见到它们 `kind` 保持不变；
  // 见到别的类名（`de-form-cell`/`sense-altof`/`sense-example`/`exchange-item`…）
  // 一律把 `kind` 清空，`kind` 为空的目标**一概不算关系**。
  const INSIDE = new Set(['rel-groups', 'rel-group', 'rel-row', 'rel-targets',
    'rel-item', 'rel-more', 'sense-relations', 'sense-rels']);
  for (const m of seg.matchAll(/class="([^"]+)"[^>]*>([^<]*)/g)) {
    const cls = m[1];
    if (cls === 'rel-kind') { kind = m[2]; continue; }
    if (cls === 'rel-link' || cls === 'rel-plain') {
      if (kind && m[2]) out.add(`${kind}｜${m[2]}`);
      continue;
    }
    if (!INSIDE.has(cls)) kind = '';
  }
  return out;
}

const dupBad: string[] = [];
for (const [w, html] of fullPages) {
  const { inSense, outSense } = splitBySense(html);
  const a = relPairs(inSense);
  const both = [...relPairs(outSense)].filter((x) => a.has(x));
  if (both.length) dupBad.push(`${w}：${both.slice(0, 3).map((x) => x.replace('｜', ' ')).join('、')}`);
}
console.log(dupBad.length
  ? `\n🔴 ${dupBad.length} 个词条页有关系目标印了两遍\n`
    + dupBad.slice(0, 8).map((x) => `     ${x}`).join('\n')
  : `\n✅ 关系分级：${fullPages.length} 个词条页，没有一个目标被印两遍`);

if (mutate) {
  // 🔴 变异造在**角色序列**上（把两块对调），不是造在 HTML 上 ——
  //    HTML 层面"对调两个 div"的正则既难写又容易造出根本不可能出现的形状。
  //    判据吃的就是这个序列，直接喂它一个坏序列，是最贴合判据的变异。
  console.log('\n═══ 变异：每种"换位置"各造一次 ═══\n');
  const MUTS: Array<[string, (r: string[]) => string[]]> = [
    ['M1 原文定义排到例句后（es 改前那个样子）',
      (r) => (r.includes('原文定义') && r.includes('例句')
        ? [...r.filter((x) => x !== '原文定义'), '原文定义'] : r)],
    ['M2 关系排到例句后（pt 改前那个样子）',
      (r) => (r.includes('关系') && r.includes('例句')
        ? [...r.filter((x) => x !== '关系'), '关系'] : r)],
    ['M3 例句提到原文定义前',
      (r) => (r.includes('原文定义') && r.includes('例句')
        ? ['中文', '例句', ...r.filter((x) => x !== '中文' && x !== '例句')] : r)],
    ['M4 中文不在第一位',
      (r) => (r.length >= 2 ? [r[1], r[0], ...r.slice(2)] : r)],
  ];
  let dead = 0;
  for (const [name, f] of MUTS) {
    let hits = 0;
    let touched = 0;
    for (const [, roles] of pages) {
      const m = f(roles);
      if (m.join(' ') === roles.join(' ')) continue;
      touched += 1;
      if (!isSubsequence(m)) hits += 1;
    }
    if (touched === 0 || hits === 0) {
      dead += 1;
      console.log(`   🔴 ${name}  —— ${touched === 0 ? '一条都没造出来' : '造出来了但闸没红'}`);
    } else console.log(`   ✅ ${name}  → 打红 ${hits}/${touched} 条`);
  }
  console.log(`\n   变异 ${MUTS.length - dead}/${MUTS.length} 有效`);

  // ── 关系分级那条断言的变异：**注入一条重复**（负控型断言必须"往上加"）──
  // 🔴 这条断言说的是"不该出现 X"。页面上现在一条重复都没有，
  //    "把 A 换成 B" 型的变异一个字符都改不动、会被静默跳过 ⇒ 断言没人守。
  //    今天已经在搭配闸与词源闸上各踩过一次这个坑。
  console.log('\n═══ 变异（关系分级）：把义项里的一条关系复制到词条级 ═══\n');
  let injHit = 0;
  let injTouched = 0;
  for (const [, html] of fullPages) {
    const { inSense } = splitBySense(html);
    const inPairs = relPairs(inSense);
    // 义项里一条关系都没有 ⇒ 这个页面**造不出**这种缺陷，跳过（不是失败）。
    if (inPairs.size === 0) continue;
    injTouched += 1;
    // 🔴 **从解析出来的「对」反向合成一段合法 HTML**，而不是从页面上切一段来复制。
    //    第一版切 `<span class="rel-item">…</span>`：`rel-item` 里**嵌着** `rel-plain`，
    //    非贪婪匹配停在内层 `</span>` ⇒ 复制出来的是**半截标签**，闸当然逮不到
    //    （`en curious` 就是这么漏的）。另一页则是 kind 与 item 配错了组。
    //    ⇒ 变异要构造**判据认得出的、合法的**缺陷；构造本身出错，绿灯与红灯都不算数。
    const [kind, target] = [...inPairs][0].split('｜');
    const mutated = `${html}<div class="rel-group">`
      + `<span class="rel-kind">${kind}</span>`
      + `<span class="rel-item"><span class="rel-plain">${target}</span></span></div>`;
    const sp = splitBySense(mutated);
    if ([...relPairs(sp.outSense)].some((x) => relPairs(sp.inSense).has(x))) injHit += 1;
  }
  const injOk = injTouched > 0 && injHit === injTouched;
  console.log(`   ${injOk ? '✅' : '🔴'} 注入重复 → 打红 ${injHit}/${injTouched} 个页面`
    + (injTouched === 0 ? '（一个都没造出来 —— 取样里没有义项级关系）' : ''));

  process.exit(dead || bad.length || dupBad.length || !injOk ? 1 : 0);
}
process.exit(bad.length || dupBad.length ? 1 : 0);
