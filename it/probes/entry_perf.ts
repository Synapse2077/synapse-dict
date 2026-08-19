/**
 * 阶段 8 验收判据 4：**全量数据下**词条页 P95 < 200 ms。2026-08-18。
 *
 * ═══ 为什么要在"数据补齐之后"测 ═══
 * `query-perf-collation-traps` 那条记的就是这件事：性能问题**要等数据长大才咬人**。
 * es 的 `mano` 词条页跑了 6.3 秒，不是代码那天变慢的，是中文释义涨到 34 万条之后
 * 相关子查询才开始扫全表。it 这边今天刚接上四张新表（读音 120 万行、例句 3.8 万、
 * 关系 61 万、录音 1.2 万），必须重测一遍。
 *
 * ═══ 取样面：按 `freq_zipf` 取真常用词，不是随便取 ═══
 * 判据说的是"常用词词条页"。随机取样会取到一堆生僻变形形（它们没有义项、没有例句、
 * 没有关系，查起来当然快）—— 那种绿灯是假的。⇒ 高频词、多义项词、多关系词各取一批，
 * **最慢的那一类才是判据**。
 *
 * 用法（仓库根目录）：
 *     npx tsx --tsconfig apps/web/tsconfig.json it/probes/entry_perf.ts
 *     npx tsx --tsconfig apps/web/tsconfig.json it/probes/entry_perf.ts --n 500
 */
import { DatabaseSync } from 'node:sqlite';
import { getService } from '@synapse-dict/dict-core';

const DB = new URL('../../data/db/synapse-dict-it.sqlite', import.meta.url).pathname;
const svc = getService('it') as unknown as { getEntry(w: string): unknown };
const db = new DatabaseSync(DB);
db.exec('PRAGMA query_only = ON');

const argv = process.argv.slice(2);
const N = argv.includes('--n') ? Number(argv[argv.indexOf('--n') + 1]) : 300;
const BUDGET_MS = 200;

const words = (sql: string) =>
  (db.prepare(sql).all(N) as Array<{ word: string }>).map((r) => r.word);

const GROUPS: Array<[string, string[]]> = [
  ['高频词（freq_zipf 前 N）',
   words(`SELECT word FROM dict WHERE freq_zipf IS NOT NULL
          ORDER BY freq_zipf DESC LIMIT ?`)],
  ['多义项词',
   words(`SELECT d.word FROM dict d JOIN sense s ON s.word_id=d.id
          WHERE COALESCE(s.hidden,0)=0 GROUP BY d.id
          ORDER BY count(*) DESC LIMIT ?`)],
  ['多关系词（会触发 12 次存在性查询）',
   words(`SELECT d.word FROM dict d JOIN sense_relation r ON r.word_id=d.id
          GROUP BY d.id ORDER BY count(*) DESC LIMIT ?`)],
  ['多例句词',
   words(`SELECT word FROM example GROUP BY word ORDER BY count(*) DESC LIMIT ?`)],
  ['多变形形词（bases 要逐个解析）',
   words(`SELECT d.word FROM dict d JOIN inflection i ON i.word_id=d.id
          GROUP BY d.id ORDER BY count(DISTINCT i.base) DESC LIMIT ?`)],
];

const pct = (xs: number[], p: number) => xs[Math.min(xs.length - 1,
  Math.floor(xs.length * p))];

let worst = 0;
let worstWord = '';
console.log(`■ 每组 ${N} 个词，预算 P95 < ${BUDGET_MS} ms\n`);
console.log(`   ${'取样面'.padEnd(30)} ${'P50'.padStart(8)} ${'P95'.padStart(8)} ` +
  `${'最慢'.padStart(8)}  最慢的那个词`);
for (const [name, ws] of GROUPS) {
  const ms: number[] = [];
  let slowest = ['', 0] as [string, number];
  for (const w of ws) {
    const t0 = process.hrtime.bigint();
    svc.getEntry(w);
    const dt = Number(process.hrtime.bigint() - t0) / 1e6;
    ms.push(dt);
    if (dt > slowest[1]) slowest = [w, dt];
  }
  ms.sort((a, b) => a - b);
  const p95 = pct(ms, 0.95);
  if (p95 > worst) { worst = p95; worstWord = name; }
  console.log(`   ${(p95 > BUDGET_MS ? '🔴 ' : '✅ ') + name.padEnd(28)} ` +
    `${pct(ms, 0.5).toFixed(1).padStart(8)} ${p95.toFixed(1).padStart(8)} ` +
    `${slowest[1].toFixed(1).padStart(8)}  ${slowest[0]}`);
}
console.log(`\n   ${worst <= BUDGET_MS ? '✅' : '🔴'} 最差一组的 P95 = ` +
  `${worst.toFixed(1)} ms（${worstWord}），预算 ${BUDGET_MS} ms`);
process.exit(worst <= BUDGET_MS ? 0 : 1);
