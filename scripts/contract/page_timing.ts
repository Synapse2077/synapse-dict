/**
 * 页面计时闸（B11，读者口径）。2026-10-27。
 *
 * 服务层**真取一整页**（`getEntry`），热态取 3 次的中位数；每页不许超过 `LIMIT_MS`。
 * 🔴 为什么计划探针不够：ko 当年的病是**选错了驱动索引**——计划里写着 `SEARCH … USING INDEX`，
 *    看着走了索引，用的却是区分度极低的那个（`lang='zh'` 占 51.8%）⇒ 一页 16 秒。
 *    形状判据看不出这种病，只有耗时看得出。
 * 词表**每次从库里现查**，不写死：关系最多的 5 个词 ＋ 义项最多的 5 个词（页面最重的），再加几个常用词。
 * 2026-10-27 实测（es/fr/it，`ANALYZE` 前后都量过）：最慢 16.7 ms（it `piante`），`LIMIT_MS` 留三倍余量。
 *
 * 跑：npx tsx scripts/contract/page_timing.ts [--mutate]
 */
import { DatabaseSync } from 'node:sqlite';
import { getService } from '../../packages/dict-core/src/index.js';

const LIMIT_MS = 50;
const LANGS: Record<string, string[]> = {
  es: ['de', 'casa', 'ser', 'tener', 'agua', 'bueno', 'hablar', 'perro'],
  fr: ['de', 'maison', 'être', 'avoir', 'eau', 'bon', 'parler', 'chien'],
  it: ['di', 'casa', 'essere', 'avere', 'acqua', 'buono', 'parlare', 'cane'],
};
const ROOT = new URL('../../', import.meta.url).pathname;

function heavyWords(lang: string): string[] {
  const db = new DatabaseSync(`${ROOT}data/db/synapse-dict-${lang}.sqlite`, { readOnly: true });
  const q = (t: string) => (db.prepare(
    `SELECT d.word FROM (SELECT word_id, COUNT(*) c FROM ${t} GROUP BY 1 ORDER BY c DESC LIMIT 5) x
       JOIN dict d ON d.id = x.word_id`).all() as Array<{ word: string }>).map((r) => r.word);
  const out = [...q('sense_relation'), ...q('sense')];
  db.close();
  return out;
}

function timePage(svc: any, w: string): number {
  svc.getEntry(w);                                    // 热身
  const ts: number[] = [];
  for (let i = 0; i < 3; i++) { const t = performance.now(); svc.getEntry(w); ts.push(performance.now() - t); }
  ts.sort((a, b) => a - b);
  return ts[1];
}

function check(lang: string, svc: any, words: string[]): string[] {
  const bad: string[] = [];
  if (words.length < 10) bad.push(`${lang} 词表只有 ${words.length} 个 —— 重词没查出来，这道闸会空过`);
  let worst: [string, number] = ['', 0];
  for (const w of words) {
    const ms = timePage(svc, w);
    if (ms > worst[1]) worst = [w, ms];
    if (ms > LIMIT_MS) bad.push(`${lang} ${w} 一页 ${ms.toFixed(1)} ms（上限 ${LIMIT_MS}）—— 先 EXPLAIN 看是不是选错了驱动索引`);
  }
  console.log(`  ${bad.length ? '🔴' : '✅'} ${lang}  ${words.length} 页，最慢 ${worst[0]} ${worst[1].toFixed(1)} ms`);
  return bad;
}

const mutate = process.argv.includes('--mutate');
let bad: string[] = [];
const ctx: Record<string, { svc: any; words: string[] }> = {};
console.log(`■ 页面计时闸（热态中位数，每页上限 ${LIMIT_MS} ms）`);
for (const [lang, common] of Object.entries(LANGS)) {
  ctx[lang] = { svc: getService(lang as never), words: [...heavyWords(lang), ...common] };
  bad = bad.concat(check(lang, ctx[lang].svc, ctx[lang].words));
}
for (const b of bad) console.log('  🔴 ' + b);
console.log(bad.length ? `🔴 ${bad.length} 处` : '✅ 全绿');

if (mutate) {
  console.log('\n■ 变异');
  const { svc, words } = ctx.fr;
  const slow = new Proxy(svc, { get(t, k) {
    if (k !== 'getEntry') return Reflect.get(t, k);
    return (w: string) => { const r = t.getEntry(w); if (w === words[0]) { const e = performance.now() + LIMIT_MS + 10; while (performance.now() < e); } return r; };
  } });
  const cases: Array<[string, string[], boolean]> = [
    ['fr 最重那一页慢过上限', check('fr', slow, words), true],
    ['重词没查出来（词表只剩常用词）', check('fr', svc, LANGS.fr), true],
    ['（反控）原样', check('fr', svc, words), false],
  ];
  let dead = 0;
  for (const [name, got, want] of cases) {
    const ok = (got.length > 0) === want;
    dead += ok ? 0 : 1;
    console.log(`  ${ok ? '✅' : '🔴 没逮到'} ${name}`);
  }
  console.log(`  变异 ${cases.length - dead}/${cases.length}`);
  process.exit(dead || bad.length ? 1 : 0);
}
process.exit(bad.length ? 1 : 0);
