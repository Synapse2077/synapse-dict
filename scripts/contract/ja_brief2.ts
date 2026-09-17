import { getService } from '../../packages/dict-core/src/index.js';
import { DatabaseSync } from 'node:sqlite';
const svc = getService('ja') as any;
const db = new DatabaseSync('/Users/fangyi/demo/synapse-dict/data/db/synapse-dict-ja.sqlite', { readOnly: true });
const empties = svc.search('あ', 30).filter((r: any) => !r.brief);
for (const e of empties) {
  const row = db.prepare(`SELECT
     (SELECT COUNT(*) FROM sense WHERE word_id=?) s,
     (SELECT COUNT(*) FROM entry WHERE word_id=?) en,
     (SELECT COUNT(*) FROM inflection WHERE word_id=?) i,
     (SELECT COUNT(*) FROM sense_relation WHERE word_id=?) r,
     (SELECT COUNT(*) FROM example WHERE word=?) x,
     (SELECT freq_zipf FROM dict WHERE id=?) f`).get(e.id,e.id,e.id,e.id,e.word,e.id) as any;
  console.log(`   ${e.word.padEnd(8)} 义项${row.s} entry${row.en} 变形${row.i} 关系${row.r} 例句${row.x} zipf=${row.f}`);
}
// 全库：真正什么都没有的词元，有多少会出现在搜索里
const n = db.prepare(`SELECT COUNT(*) n FROM dict d WHERE d.is_lemma=1
  AND NOT EXISTS(SELECT 1 FROM sense s WHERE s.word_id=d.id)
  AND NOT EXISTS(SELECT 1 FROM inflection i WHERE i.word_id=d.id)
  AND NOT EXISTS(SELECT 1 FROM sense_relation r WHERE r.word_id=d.id)`).get() as any;
console.log(`\n全库「三样都没有」的词元：${n.n.toLocaleString()}`);
db.close();
