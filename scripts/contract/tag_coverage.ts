/** 标签映射覆盖率：**直接调 `enLabel()` 量落点**，不是读映射表数键。
 *  用法：npx tsx scripts/contract/tag_coverage.ts [lang] */
import { DatabaseSync } from 'node:sqlite';
import { enLabel } from '../../packages/dict-labels/src/en.js';

const ROOT = new URL('../../', import.meta.url).pathname;
const db = new DatabaseSync(`${ROOT}data/db/synapse-dict-en.sqlite`, { readOnly: true });
const rows = db.prepare(
  `SELECT kind, value, COUNT(*) n FROM sense_tag GROUP BY kind, value ORDER BY kind, n DESC`,
).all() as Array<{ kind: string; value: string; n: number }>;
db.close();

const byKind = new Map<string, { hit: number; miss: number; hitN: number; missN: number;
                                 missing: Array<[string, number]> }>();
for (const r of rows) {
  const s = byKind.get(r.kind) ?? { hit: 0, miss: 0, hitN: 0, missN: 0, missing: [] };
  if (enLabel(r.kind, r.value) === r.value) {
    s.miss += 1; s.missN += r.n; s.missing.push([r.value, r.n]);
  } else { s.hit += 1; s.hitN += r.n; }
  byKind.set(r.kind, s);
}
console.log(`${'类别'.padEnd(10)}${'取值种数'.padStart(10)}${'已映射'.padStart(8)}${'未映射'.padStart(8)}${'条数覆盖'.padStart(12)}`);
for (const [kind, s] of [...byKind].sort((a, b) => (b[1].hitN + b[1].missN) - (a[1].hitN + a[1].missN))) {
  const tot = s.hitN + s.missN;
  console.log(`${kind.padEnd(10)}${String(s.hit + s.miss).padStart(10)}${String(s.hit).padStart(8)}${String(s.miss).padStart(8)}`
    + `${(`${((100 * s.hitN) / tot).toFixed(1)}%`).padStart(12)}   (${tot.toLocaleString()} 条)`);
}
console.log('\n══ 未映射的取值，按条数排（topic 除外，它有意不映射）══');
for (const [kind, s] of byKind) {
  if (kind === 'topic' || !s.missing.length) continue;
  console.log(`\n── ${kind}：未映射 ${s.miss} 种 / ${s.missN.toLocaleString()} 条 ──`);
  for (const [v, n] of s.missing.slice(0, 40)) console.log(`   ${String(n).padStart(7)}  ${v}`);
  if (s.missing.length > 40) console.log(`   …… 另有 ${s.missing.length - 40} 种`);
}
