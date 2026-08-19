/**
 * 阶段 3 验收判据 4：搜小写词，首条必须是小写词本身。2026-08-17。
 *
 * ═══ 防的是什么 ═══
 * 小写普通名词与大写专名压成一行的缺陷修完之后（拆成两行），COLLATE NOCASE
 * 会同时命中两行。不把**精确大小写**排在第一位，搜小写就会命中大写专名 ——
 * es 至今如此：搜 gracias，排第一的是洪都拉斯的城镇 Gracias。
 *
 * 判据必须**走 getEntry**，不是直接查 SQL —— 这条缺陷只在"取第一条"时才存在，
 * 查全表看不出来（同 apps/web/src/contract-check.tsx 的理由）。
 *
 * 用法（仓库根目录）：
 *     npx tsx --tsconfig apps/web/tsconfig.json it/probes/case_first_hit.ts
 */
import { DatabaseSync } from 'node:sqlite';
import { getService } from '@synapse-dict/dict-core';

const DB = new URL('../../data/db/synapse-dict-it.sqlite', import.meta.url).pathname;
const svc = getService('it') as unknown as { getEntry(w: string): { word: string } | null };

const db = new DatabaseSync(DB);
db.exec('PRAGMA query_only = ON');
const rows = db.prepare(`
  SELECT d.word FROM dict d
  WHERE d.word = lower(d.word)
    AND EXISTS(SELECT 1 FROM dict u WHERE u.word <> d.word AND lower(u.word) = d.word)
    AND EXISTS(SELECT 1 FROM sense s WHERE s.word_id = d.id AND COALESCE(s.hidden,0)=0)
  ORDER BY CASE d.level WHEN 'A1' THEN 0 WHEN 'A2' THEN 1 WHEN 'B1' THEN 2
                        WHEN 'B2' THEN 3 WHEN 'C1' THEN 4 WHEN 'C2' THEN 5 ELSE 6 END,
           LENGTH(d.word) ASC
  LIMIT 200
`).all() as unknown as { word: string }[];
db.close();

let bad = 0;
const ex: string[] = [];
for (const r of rows) {
  const got = svc.getEntry(r.word);
  if (!got || got.word !== r.word) {
    bad++;
    if (ex.length < 12) ex.push(`搜 ${r.word} → 首条是 ${got ? got.word : '查不到'}`);
  }
}
console.log('═══ 阶段 3 判据 4：搜小写词，首条必须是小写词本身 ═══');
console.log(`   取样 ${rows.length} 个（有同名大写行、且自己有义项的小写词）`);
console.log(`   ${bad === 0 ? '✅' : '🔴'} 首条不对的 ${bad} 个 (期望 0)`);
for (const e of ex) console.log(`        ${e}`);
process.exit(bad === 0 ? 0 : 1);
