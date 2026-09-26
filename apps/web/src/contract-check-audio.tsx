/** 跨语种展示层闸：**同一个词的多条真人发音，按钮标签必须两两不同**。2026-09-26（K23）。
 *
 * ═══ 这道闸为什么必须是跨语种的 ═══
 * 八门共用 `HumanAudioRow`，而「标签重复」这个缺陷在四门上各发作过一次，
 * 每次都是用户在页面上看见的，四次都不是任何一门自己的闸报的：
 *
 *     2026-08-31  fr `chien`   八个按钮全写「法国」        → 加 `capAudios`（每地区≤2、总≤6）
 *     2026-08-31  es `banco`   两个都写「未标注」          → region 空时退到录音人
 *     2026-08-31  pt `a`       四个都写「巴西」            → 标签重复时把录音人带上
 *     2026-09-25  ko `한국`     两个又都写「未标注」        → **录音人也是空的，兜底到此为止**
 *
 * 🔴 **前三次都是「修好手边那一个形状」，第四次换个形状又发作。**
 *    `[[decision-not-propagated-across-editions]]`：一门做对了其余照旧错着，
 *    而每门自己的闸全绿。⇒ 要的不是第四个补丁，是一条**不变式**：
 *
 *        同一个词渲染出来的所有 `.audio-region` 文本，两两不同。
 *
 * ═══ 判据一条都不重写 —— 闸读的是**渲染出来的字** ═══
 * 不自己算标签（那要复刻 `capAudios`＋八门各自的 `regionLabel`＋服务层排序，
 * 复刻就会漂）。而是把各门的 EntryView 真渲染成 HTML，抠 `.audio-region` 的文本。
 * 这是**读者口径**：屏幕上印的是什么，它就查什么。
 * `[[correct-steps-can-compose-a-hole]]`：闸至少要有一条是读者口径。
 *
 * 跑（在仓库根）：
 *   npx tsx --tsconfig apps/web/tsconfig.json apps/web/src/contract-check-audio.tsx
 *   加 --full        查全部候选词（约 18 分钟；默认按「录音行签名」去重，见下）
 *   加 --lang ko,fr  只查这几门
 *   加 --dump 한국    把这个词的标签打出来读
 *
 * ⚠️ 默认模式为什么不是抽样：候选词 18.4 万，但**标签只由那几条录音的
 *    (地区, 录音人, 读音) 决定，与词本身无关** ⇒ 签名相同的词，标签必然相同。
 *    按签名去重是**行为空间的全覆盖**，不是抽样。这条假设由 `--full` 校验过一次
 *    （结论记在 `docs/BACKLOG.md`），改了服务层排序要重新校验。
 */
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { getService } from '@synapse-dict/dict-core';
import {
  EnglishEntryView, SpanishEntryView, ItalianEntryView, FrenchEntryView,
  PortugueseEntryView, GermanEntryView, JapaneseEntryView, KoreanEntryView,
} from './App';

const VIEW: Record<string, unknown> = {
  en: EnglishEntryView, es: SpanishEntryView, it: ItalianEntryView, fr: FrenchEntryView,
  pt: PortugueseEntryView, de: GermanEntryView, ja: JapaneseEntryView, ko: KoreanEntryView,
};
const LANGS = Object.keys(VIEW);

const argv = process.argv.slice(2);
const FULL = argv.includes('--full');
const DUMP = argv.includes('--dump') ? argv[argv.indexOf('--dump') + 1] : null;
const ONLY = argv.includes('--lang')
  ? new Set(argv[argv.indexOf('--lang') + 1].split(','))
  : null;

/** 渲染出来的所有 `.audio-region` 文本，按出现顺序。 */
const CHIP = /<span class="audio-region">([\s\S]*?)<\/span>/g;
function chipLabels(html: string): string[] {
  const out: string[] = [];
  for (const m of html.matchAll(CHIP)) {
    out.push(
      m[1].replace(/<[^>]*>/g, '')
        .replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&amp;/g, '&')
        .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
        .replace(/\s+/g, ' ').trim(),
    );
  }
  return out;
}

function repeats(labels: string[]): string[] {
  const n = new Map<string, number>();
  for (const l of labels) n.set(l, (n.get(l) ?? 0) + 1);
  return [...n.entries()].filter(([, c]) => c > 1).map(([l, c]) => `${l}×${c}`);
}

type Svc = {
  getEntry(w: string): unknown;
  db: { prepare(s: string): { all(...a: unknown[]): unknown[] } };
};

function render(lang: string, entry: unknown): string {
  return renderToStaticMarkup(
    createElement(VIEW[lang] as never, {
      entry, speakLocale: 'x-x', onWord: () => {}, speak: () => {}, onColloc: () => {},
    } as never),
  );
}

/** 候选词：SQL 只做**宽松预筛**（≥2 行录音），真正判定交给渲染。 */
function candidates(svc: Svc): { word: string; sig: string }[] {
  const rows = svc.db
    .prepare(
      'SELECT word, COALESCE(region, \'\') AS r, COALESCE(speaker, \'\') AS s,'
      + ' COALESCE(ipa, \'\') AS i FROM audio'
      + ' WHERE word IN (SELECT word FROM audio GROUP BY word HAVING COUNT(*) >= 2)'
      + ' ORDER BY word, id',
    )
    .all() as { word: string; r: string; s: string; i: string }[];
  const by = new Map<string, string[]>();
  for (const x of rows) {
    const a = by.get(x.word);
    const k = `${x.r}|${x.s}|${x.i}`;
    if (a) a.push(k); else by.set(x.word, [k]);
  }
  return [...by.entries()].map(([word, ks]) => ({ word, sig: ks.join('；') }));
}

/**
 * 🔴🔴 **闸自己的闸。** 没有这一条，`CHIP` 正则一坏（比如有人把 `audio-region`
 *    这个类名改了）闸就抠到 0 个标签 ⇒ 0 个重复 ⇒ **报全绿**，
 *    而页面上可能正排着一堆同名按钮。判据失效必须自己响。
 *    锚在**常量**上（2026-09-26 去重模式实测），不从现状推
 *    （`[[expectation-must-be-declared]]`；ko 那轮「锚在会变的行文上、
 *      `replace` 空操作而检查照样通过」的坑，这里不再踩）。
 *    数只许涨不许跌：录音层加了数据它会涨，跌了说明有东西不工作了。
 */
const EXPECT_MULTI: Record<string, number> = {
  en: 1008, es: 838, it: 552, fr: 26152, pt: 1890, de: 2758, ja: 20,
  // 🔴 ko 由 18 改 16：并掉 39 行重复录音之后，有些词从「两条」变成「一条」，
  //    不再渲出多按钮 —— **这是数据变了，不是闸坏了**。
  //    ⚠️ 改锚只许带着这种「为什么变」的理由改；为了让红变绿去调锚就是作废这道闸。
  ko: 16,
};

let bad = 0;
let scanned = 0;
const thin: string[] = [];

if (DUMP) {
  for (const lang of LANGS) {
    if (ONLY && !ONLY.has(lang)) continue;
    let svc: Svc;
    try { svc = getService(lang) as never; } catch { continue; }
    let e: unknown = null;
    try { e = svc.getEntry(DUMP); } catch { continue; }
    if (!e) continue;
    const ls = chipLabels(render(lang, e));
    if (ls.length) console.log(`  ${lang}  ${DUMP}  → ${JSON.stringify(ls)}`);
  }
  process.exit(0);
}

console.log('■ 跨语种闸：同一个词的多条真人发音，按钮标签必须两两不同');
console.log(
  `  模式：${FULL ? '全部候选词' : '按录音行签名去重（行为空间全覆盖）'}\n`,
);
console.log('  语种   候选词    实查    渲出≥2个按钮   🔴标签重复   样本');
console.log('  ' + '─'.repeat(88));

const REPORT: Record<string, { word: string; labels: string[] }[]> = {};

for (const lang of LANGS) {
  if (ONLY && !ONLY.has(lang)) continue;
  let svc: Svc;
  try {
    svc = getService(lang) as never;
  } catch {
    console.log(`  ${lang.padEnd(6)} （无服务）`);
    continue;
  }
  let cand: { word: string; sig: string }[];
  try {
    cand = candidates(svc);
  } catch (err) {
    console.log(`  ${lang.padEnd(6)} （查不到 audio：${String(err).slice(0, 40)}）`);
    continue;
  }

  let probe = cand;
  if (!FULL) {
    const seen = new Set<string>();
    probe = cand.filter((c) => (seen.has(c.sig) ? false : (seen.add(c.sig), true)));
  }

  const hits: { word: string; labels: string[] }[] = [];
  let multi = 0;
  for (const c of probe) {
    let e: unknown = null;
    try {
      e = svc.getEntry(c.word);
    } catch {
      continue;
    }
    if (!e) continue;
    scanned += 1;
    const labels = chipLabels(render(lang, e));
    if (labels.length < 2) continue;
    multi += 1;
    if (repeats(labels).length) hits.push({ word: c.word, labels });
  }
  REPORT[lang] = hits;
  bad += hits.length;
  // 闸自己的闸：渲出多按钮的词数不许低于登记（只在全覆盖的默认模式下比）
  if (!FULL && multi < (EXPECT_MULTI[lang] ?? 0)) {
    thin.push(`${lang} 只渲出 ${multi} 个多按钮词，登记 ${EXPECT_MULTI[lang]}`);
  }
  const sample = hits.slice(0, 2)
    .map((h) => `${h.word}[${repeats(h.labels).join(',')}]`).join(' ');
  console.log(
    `  ${lang.padEnd(6)} ${String(cand.length).padStart(7)} ${String(probe.length).padStart(7)}`
    + ` ${String(multi).padStart(14)} ${String(hits.length).padStart(12)}   ${sample}`,
  );
}

// 🔴 先判「闸还工作不工作」，再判「数据对不对」——
//    顺序反了就会出现「判据已经失效，而它正拿着失效的判据宣布全绿」。
if (thin.length) {
  console.log('\n🔴 闸自己的闸报警 —— 抠到的按钮比登记的少，多半是判据失效了：');
  for (const t of thin) console.log('   ' + t);
  console.log('   （`CHIP` 正则、`audio-region` 类名、`capAudios`、服务层排序，挨个查）');
  process.exit(2);
}

if (bad) {
  // `--list` 打全名单：`[[judge-output-must-be-adjudicable]]`，报不出名单就没法逐条裁决
  const LIST = argv.includes('--list');
  console.log(LIST ? '\n■ 重复清单（全部）' : '\n■ 重复样本（每门最多 6 个，全名单加 --list）');
  for (const lang of LANGS) {
    for (const h of LIST ? (REPORT[lang] || []) : (REPORT[lang] || []).slice(0, 6)) {
      console.log(`   ${lang}  ${h.word.padEnd(16)} ${JSON.stringify(h.labels)}`);
    }
  }
  console.log(`\n🔴 共 ${bad} 个词排出了标签相同的按钮 —— 读者分不清点哪个`);
  console.log(`   （实查 ${scanned} 个词）`);
  process.exit(1);
}
console.log(`\n■ 跨语种发音标签闸全绿 ✓（实查 ${scanned} 个词，无一重复）`);
