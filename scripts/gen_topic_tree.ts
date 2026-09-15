/** 从库里量出 kaikki topic 的父子层级，生成 `packages/dict-labels/src/topic-tree.ts`。2026-09-15。
 *
 * ═══ 为什么需要它 ═══
 * kaikki 的 `topics` 是**一条链**不是一个值：`google` 的板球义项挂着
 *     ball-games, cricket, games, hobbies, lifestyle, sports
 * 六个 —— 真正说事的只有 `cricket`，另外五个是它的祖先。
 * 原样印出来是「球类·板球·游戏·业余爱好·生活方式·体育」，读者要从六个里挑一个。
 * ⇒ 展示时只留**最具体**的：一个 topic 如果是同一条义项上另一个 topic 的祖先，折掉。
 *
 * ═══ 层级从哪儿来 ═══
 * 🔴 **不硬编码，从数据里量**（`[[criteria-from-meaning-not-form]]`）。
 * 判据：带 B 的义项里 ≥98% 也带 A，且 A 比 B 常见 ⇒ A 是 B 的祖先。
 * 父 = 祖先里最不常见的那个（最贴近 B 的一层）。
 * ⚠️ 98% 不是 100%：源头偶有漏标。留 2% 的余量是量出来的
 *    —— 100% 会把 `physics`→`physical-sciences` 这类真链条漏掉。
 * ⚠️ 只处理 kaikki 的英文 slug；ECDICT 的中文短码（`计`/`医`）是单层，不进这张表。
 *
 * 跑：npx tsx scripts/gen_topic_tree.ts
 */
import { DatabaseSync } from 'node:sqlite';
import { writeFileSync } from 'node:fs';

const ROOT = new URL('../', import.meta.url).pathname;
const CJK = /[一-鿿]/;
const db = new DatabaseSync(`${ROOT}data/db/synapse-dict-en.sqlite`, { readOnly: true });
const rows = db.prepare("SELECT sense_id, value FROM sense_tag WHERE kind='topic'").all() as
  Array<{ sense_id: number; value: string }>;
db.close();

const bySense = new Map<number, string[]>();
const cnt = new Map<string, number>();
for (const r of rows) {
  if (CJK.test(r.value)) continue;
  (bySense.get(r.sense_id) ?? bySense.set(r.sense_id, []).get(r.sense_id)!).push(r.value);
  cnt.set(r.value, (cnt.get(r.value) ?? 0) + 1);
}

const pair = new Map<string, number>();
for (const a of bySense.values()) {
  const u = [...new Set(a)];
  for (const x of u) for (const y of u) if (x !== y) pair.set(`${x} ${y}`, (pair.get(`${x} ${y}`) ?? 0) + 1);
}

const anc = new Map<string, string[]>();
for (const [k, c] of pair) {
  const [x, y] = k.split(' ');
  if (c / cnt.get(y)! >= 0.98 && cnt.get(x)! > cnt.get(y)!) {
    (anc.get(y) ?? anc.set(y, []).get(y)!).push(x);
  }
}

// 父 = 祖先里最不常见的那个。⚠️ 平局时按字典序定，保证重跑结果逐字节一致。
const parent = new Map<string, string>();
for (const [child, list] of anc) {
  list.sort((a, b) => (cnt.get(a)! - cnt.get(b)!) || (a < b ? -1 : 1));
  parent.set(child, list[0]);
}

// 🔴 回核：父链必须无环，且走到顶。有环说明 98% 的判据把两个同级的东西判成了父子。
for (const start of parent.keys()) {
  const seen = new Set<string>([start]);
  let cur = start;
  while (parent.has(cur)) {
    cur = parent.get(cur)!;
    if (seen.has(cur)) throw new Error(`🔴 父链成环：${[...seen].join(' → ')} → ${cur}`);
    seen.add(cur);
  }
}

const roots = [...new Set([...parent.values()])].filter((v) => !parent.has(v)).sort();
const keys = [...parent.keys()].sort();
// 🔴 键值一律走 `JSON.stringify` —— `Rubik's-Cube` 里的撇号会把手写的单引号串截断。
const q = (v: string) => (/^[A-Za-z_$][\w$]*$/.test(v) ? v : JSON.stringify(v));
const body = keys.map((k) => `  ${q(k)}: ${JSON.stringify(parent.get(k))},`).join('\n');

writeFileSync(`${ROOT}packages/dict-labels/src/topic-tree.ts`, `// ⚠️ **本文件由 \`scripts/gen_topic_tree.ts\` 生成，不要手改。**
//    改了下次重跑就没了；要改判据改生成脚本。
//
// kaikki 的 topic 是**一条链**：\`google\` 的板球义项挂着 ball-games / cricket /
// games / hobbies / lifestyle / sports 六个，真正说事的只有 \`cricket\`。
// 展示层据此只留**最具体**的那几个（见 \`mostSpecificTopics()\`）。
//
// 层级是从库里**量出来**的，不是谁拍的：带 B 的义项里 ≥98% 也带 A 且 A 更常见
// ⇒ A 是 B 的祖先；父取祖先里最不常见的那一个。
// 生成于 ${new Date().toISOString().slice(0, 10)}：${keys.length} 个 slug 有父，${roots.length} 个顶层。

/** 子 slug → 它的直接父 slug。没有父的（顶层）不在表里。 */
export const TOPIC_PARENT: Record<string, string> = {
${body}
};

/** 顶层领域（没有父的那些）—— 也就是「按领域分群」里的那个「群」。 */
export const TOPIC_ROOTS: readonly string[] = [
${roots.map((r) => `  ${JSON.stringify(r)},`).join('\n')}
];

/** slug 的整条祖先链（不含自己）。 */
export function topicAncestors(slug: string): string[] {
  const out: string[] = [];
  let cur = TOPIC_PARENT[slug];
  while (cur && !out.includes(cur)) { out.push(cur); cur = TOPIC_PARENT[cur]; }
  return out;
}

/** slug 属于哪个顶层领域（自己就是顶层时返回自己）。 */
export function topicRoot(slug: string): string {
  const chain = topicAncestors(slug);
  return chain.length ? chain[chain.length - 1] : slug;
}

/**
 * 只留最具体的 topic：**是同组里另一个 topic 的祖先，就折掉**。
 * 🔴 判据是「有没有更具体的兄弟」，不是「常不常见」——
 *    一条义项只挂 \`sciences\` 一个的时候，\`sciences\` 就是它最具体的那个，要留。
 */
export function mostSpecificTopics(slugs: string[]): string[] {
  const set = new Set(slugs);
  const covered = new Set<string>();
  for (const s of set) for (const a of topicAncestors(s)) covered.add(a);
  return slugs.filter((s) => !covered.has(s));
}
`);
console.log(`✅ ${keys.length} 个 slug 有父，${roots.length} 个顶层：${roots.join(' ')}`);

// 折叠效果：折之前/之后每条义项挂几个
const before = new Map<number, number>(); const after = new Map<number, number>();
const anc2 = (s: string) => { const o: string[] = []; let c = parent.get(s); while (c && !o.includes(c)) { o.push(c); c = parent.get(c); } return o; };
for (const a of bySense.values()) {
  const u = [...new Set(a)];
  const cov = new Set<string>(); for (const s of u) for (const x of anc2(s)) cov.add(x);
  const keep = u.filter((s) => !cov.has(s));
  before.set(u.length, (before.get(u.length) ?? 0) + 1);
  after.set(keep.length, (after.get(keep.length) ?? 0) + 1);
}
const fmt = (m: Map<number, number>) => [...m].sort((x, y) => x[0] - y[0]).map(([k, v]) => `${k}个:${v.toLocaleString()}`).join('  ');
console.log(`折前  ${fmt(before)}`);
console.log(`折后  ${fmt(after)}`);
