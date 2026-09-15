/** de 词源端到端：数据层灌进去的，服务层按 etymKey 查得到吗。
 *  🔴 这是独立的一道闸 —— 三层数据全绿，真取出来才知道键对不对得上。 */
import { GermanDictService } from '../../packages/dict-core/src/german.js';
import { DatabaseSync } from 'node:sqlite';

const ROOT = new URL('../../', import.meta.url).pathname;
const DB = `${ROOT}data/db/synapse-dict-de.sqlite`;
const raw = new DatabaseSync(DB, { readOnly: true });
// 挑 10 个**确实有 kk-de 词源**的词
// 🔴 取样判据：**本来拿不到键、要靠德语版才拿得到**的那批。
//    第一版挑「有 kk-de 词源的词」，结果全挑到同时有 kk-en 5 段式引用的词 ——
//    它们本来就该继续用 kk-en（ORDER BY 保证零回归），测试当场全红而代码是对的。
//    **取样判据要对准这次改动真正影响的那一群**，否则红绿都没有意义。
const words = raw.prepare(`
  SELECT DISTINCT d.word FROM etymology e
    JOIN dict d ON d.id = e.word_id
    JOIN sense s ON s.word_id = d.id
   WHERE e.edition = 'kk-de'
     AND NOT EXISTS (SELECT 1 FROM sense_src x
                      WHERE x.sense_id = s.id AND x.src_ref LIKE '%:%:%:%:%#%')
     AND EXISTS (SELECT 1 FROM sense_src x
                  WHERE x.sense_id = s.id AND x.src_ref LIKE 'kk-de:%')
   ORDER BY d.id LIMIT 10`).all() as Array<{ word: string }>;
raw.close();

const svc = new GermanDictService(DB);
let hit = 0, miss = 0;
for (const { word } of words) {
  const entry = svc.getEntry(word) as any;
  if (!entry) { console.log(`  ✗ ${word}: 查不到词条`); miss += 1; continue; }
  const keys = Object.keys(entry.etymologyTexts ?? {});
  const deKeys = keys.filter((k) => k.startsWith('kk-de:'));
  // 义项上的 etymKey 里，有没有真的指向 kk-de 的
  const senseKeys = new Set<string>();
  for (const s of entry.senses ?? []) if (s.etymKey) senseKeys.add(s.etymKey);
  const matched = [...senseKeys].filter((k) => deKeys.includes(k));
  if (matched.length) {
    hit += 1;
    const t = entry.etymologyTexts[matched[0]];
    console.log(`  ✅ ${word}  键 ${matched[0]}  → ${String(t).slice(0, 54)}`);
  } else {
    miss += 1;
    console.log(`  ✗ ${word}  数据层键 ${JSON.stringify(deKeys)} ｜ 义项键 ${JSON.stringify([...senseKeys])}`);
  }
}
console.log(`\n端到端：命中 ${hit} / 未命中 ${miss}`);
process.exit(miss ? 1 : 0);
