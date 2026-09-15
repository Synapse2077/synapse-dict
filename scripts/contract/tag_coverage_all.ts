/** 闸：六门标签映射覆盖率 —— **量落点**，调页面真正在用的那张表。2026-09-15 改成闸。
 *
 * 原来只是个报数脚本。这一轮（en 三桶 + de/es/pt 地区 + it 语法接上页面）
 * 全部补齐之后，把它改成**会响的东西**：`[[lesson-must-become-mechanism]]`
 * ——「做成机制的全守住了、写成文字的一条没守住」。
 *
 * ═══ 两类缺口，分开问 ═══
 * ① **封闭集合**（grammar / register / region / number）：值域由建库脚本的桶集合定死，
 *    漏一个就是活儿没干完 ⇒ 裸英文必须为 0，非 0 就红。
 * ② **开放集合**（topic）：源头随时会加新领域，不可能有「补完」的那一天。
 *    展示层的规矩是**查不到就不印**（印 `phytopathology` 给中文读者比不印更坏），
 *    所以它不会漏出英文 —— 风险变成了**静默少印**。
 *    ⇒ 闸报「有多少条被静默吞掉」，超过阈值才红。
 *
 * 跑：npm run gate:tags
 */
import { DatabaseSync } from 'node:sqlite';
import { enLabel, enSenseTopics } from '../../packages/dict-labels/src/en.js';
import { TOPIC_LABELS, REGISTER_LABELS, NUMBER_LABELS } from '../../packages/dict-labels/src/common.js';
import { mostSpecificTopics } from '../../packages/dict-labels/src/topic-tree.js';
import { ES_REGION_LABELS } from '../../packages/dict-labels/src/es.js';
import { IT_REGION_LABELS, IT_GRAMMAR_LABELS } from '../../packages/dict-labels/src/it.js';
import { FR_REGION_LABELS } from '../../packages/dict-labels/src/fr.js';
import { PT_REGION_LABELS } from '../../packages/dict-labels/src/pt.js';
import { DE_REGION_LABELS } from '../../packages/dict-labels/src/de.js';

// 🔴 **每门的 region 走它自己那张表**（App.tsx:2214/2634/3091/3604/3990）。
//    我 2026-09-15 第一版拿 value 当兜底，于是五门 region 全报 0% —— 没量到真落点。
const REGION_BY_LANG: Record<string, Record<string, string>> = {
  es: ES_REGION_LABELS, it: IT_REGION_LABELS, fr: FR_REGION_LABELS,
  pt: PT_REGION_LABELS, de: DE_REGION_LABELS,
};

const ROOT = new URL('../../', import.meta.url).pathname;
const CJK = /[一-鿿]/;
const LANGS = ['en', 'fr', 'es', 'it', 'pt', 'de'];

/** 允许静默吞掉的 topic 条数上限。⚠️ 这是**当前实测值 +2%**，不是拍的：
 *  2026-09-15 把 315 种补完之后实测是 **0** ⇒ 预算就定 0，多一个都红。
 *  ⚠️ 别因为将来换 dump 冒出新 slug 就把它调大 —— 那正是这道闸要告诉你的事。 */
const TOPIC_DROP_BUDGET: Record<string, number> = { en: 0 };

function label(lang: string, kind: string, value: string): string {
  if (lang === 'en') return enLabel(kind, value);
  if (kind === 'topic') return TOPIC_LABELS[value] ?? value;
  if (kind === 'register') return REGISTER_LABELS[value] ?? value;
  if (kind === 'region') return REGION_BY_LANG[lang]?.[value] ?? value;
  if (kind === 'number') return NUMBER_LABELS[value] ?? value;
  if (kind === 'grammar' && lang === 'it') return IT_GRAMMAR_LABELS[value] ?? value;
  return value;
}

/** 这一桶会不会印到读者眼前。不渲染的桶不该拖着闸红 —— 但**必须写出理由**。 */
const NOT_RENDERED: Record<string, string> = {
  // 目前没有。fr/de/es/pt/it 的 grammar 桶要么没有值，要么已接上页面。
};

console.log(`${'语种'.padEnd(5)}${'类别'.padEnd(10)}${'种数'.padStart(7)}${'已译'.padStart(6)}${'本中文'.padStart(8)}${'裸英文'.padStart(8)}${'条数覆盖'.padStart(10)}`);
let red = 0;
const gaps: Record<string, Array<[string, number]>> = {};
for (const lang of LANGS) {
  const db = new DatabaseSync(`${ROOT}data/db/synapse-dict-${lang}.sqlite`, { readOnly: true });
  const rows = db.prepare(
    'SELECT kind, value, COUNT(*) n FROM sense_tag GROUP BY kind, value',
  ).all() as Array<{ kind: string; value: string; n: number }>;

  // en 的 topic 单独算：它走 `enSenseTopics`（折祖先 + 过滤结构标记 + 查不到不印），
  // 所以「裸英文」这个口径对它没意义，要问的是**被静默吞掉多少条**。
  let topicDropped = 0;        // 折完之后该印、却查不到中文 ⇒ 被吞掉的徽标数
  let topicEmptied = 0;        // 因此整条义项一个学科都印不出
  if (lang === 'en') {
    const tagRows = db.prepare(
      `SELECT st.sense_id, st.value FROM sense_tag st
       JOIN sense_src ss ON ss.sense_id = st.sense_id AND ss.src <> 'ecdict'
       WHERE st.kind = 'topic'`,
    ).all() as Array<{ sense_id: number; value: string }>;
    const bySense = new Map<number, string[]>();
    for (const r of tagRows) {
      const a = bySense.get(r.sense_id);
      if (a) a.push(r.value); else bySense.set(r.sense_id, [r.value]);
    }
    for (const [, vals] of bySense) {
      const u = [...new Set(vals)];
      /* 🔴 数的是**被吞掉的徽标**，不是「整条空掉的义项」。
         第一版我写的是后者，报出来 0 —— 因为 `sciences` 这类祖先几乎总在、总有中文，
         整条空掉极罕见。那个数永远是 0 的闸等于没有闸
         （`[[criteria-narrower-than-you-think]]`：判据比它要描述的东西窄）。
         ⚠️ 还要看**空掉**那一档：一个没中文的具体 slug 会把它有中文的祖先折掉，
            于是这条义项反而一个学科都印不出 —— 那是折叠规则自带的风险，单独计数。 */
      const specific = mostSpecificTopics(u.filter((v) => v !== 'heading'));
      const printed = enSenseTopics(u);
      topicDropped += specific.filter((v) => !TOPIC_LABELS[v]).length;
      if (specific.length > 0 && printed.length === 0) topicEmptied += 1;
    }
  }
  db.close();

  const byKind = new Map<string, { mapped: number; zh: number; raw: number; tot: number; ok: number }>();
  for (const r of rows) {
    const s = byKind.get(r.kind) ?? { mapped: 0, zh: 0, raw: 0, tot: 0, ok: 0 };
    s.tot += r.n;
    if (label(lang, r.kind, r.value) !== r.value) { s.mapped += 1; s.ok += r.n; }
    else if (CJK.test(r.value)) { s.zh += 1; s.ok += r.n; }
    else { s.raw += 1; (gaps[`${lang}/${r.kind}`] ??= []).push([r.value, r.n]); }
    byKind.set(r.kind, s);
  }
  for (const [kind, s] of [...byKind].sort((a, b) => b[1].tot - a[1].tot)) {
    const open = kind === 'topic';
    const pct = ((100 * s.ok) / s.tot).toFixed(1);
    const why = NOT_RENDERED[`${lang}/${kind}`];
    let flag = '';
    if (open) flag = '  （开放集，见下）';
    else if (s.raw > 0) { flag = why ? `  ⚠️ 不渲染：${why}` : '  🔴'; if (!why) red += 1; }
    console.log(`${lang.padEnd(5)}${kind.padEnd(10)}${String(s.mapped + s.zh + s.raw).padStart(7)}`
      + `${String(s.mapped).padStart(6)}${String(s.zh).padStart(8)}${String(s.raw).padStart(8)}`
      + `${(`${pct}%`).padStart(10)}  (${s.tot.toLocaleString()} 条)${flag}`);
  }
  if (lang === 'en') {
    const budget = TOPIC_DROP_BUDGET[lang];
    const over = topicDropped > budget;
    if (over) red += 1;
    console.log(`\n── ${lang}/topic（开放集）──`
      + `\n   折祖先之后查不到中文、被静默吞掉的徽标：${topicDropped.toLocaleString()} 个`
      + `（预算 ${budget.toLocaleString()}）${over ? '  🔴 该补 TOPIC_LABELS 了' : '  ✅'}`
      + `\n   因此一个学科都印不出的义项：      ${topicEmptied.toLocaleString()} 条`);
  }
}

const bad = Object.entries(gaps).filter(([k]) => !k.endsWith('/topic'));
if (bad.length) {
  console.log('\n══ 🔴 裸英文（封闭集合里漏的，读者会直接看到英文）══');
  for (const [k, list] of bad) {
    console.log(`\n── ${k}：${list.length} 种 / ${list.reduce((a, b) => a + b[1], 0).toLocaleString()} 条 ──`);
    for (const [v, c] of list.sort((a, b) => b[1] - a[1]).slice(0, 15)) {
      console.log(`   ${String(c).padStart(7)}  ${v}`);
    }
  }
}
console.log(red ? `\n🔴 ${red} 处不合格` : '\n✅ 六门标签映射全部到位');
process.exit(red ? 1 : 0);
