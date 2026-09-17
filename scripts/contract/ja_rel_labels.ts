import { relTagLabel, JA_RELATION_LABELS } from '../../packages/dict-labels/src/index.js';
import { DatabaseSync } from 'node:sqlite';
const db = new DatabaseSync('/Users/fangyi/demo/synapse-dict/data/db/synapse-dict-ja.sqlite', { readOnly: true });
const kinds = (db.prepare('SELECT kind, COUNT(*) n FROM sense_relation GROUP BY 1 ORDER BY 2 DESC').all()) as Array<{kind:string;n:number}>;
for (const { kind, n } of kinds) {
  const ja = (JA_RELATION_LABELS as Record<string,string>)[kind];
  const g = relTagLabel(kind);
  const ok = ja || g !== kind;
  console.log(`${ok ? '  ' : '🔴'} ${kind.padEnd(14)} ${String(n).padStart(8)}  ja覆盖: ${(ja ?? '-').padEnd(8)} 全局: ${g}`);
}
db.close();
