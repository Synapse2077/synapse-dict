/**
 * 归一契约闸：TS 的 `itSearchNorm` 必须与库里 `word_norm`（Python 写的）**逐行**一致。
 * 2026-08-17。
 *
 * ═══ 为什么要有 ═══
 * `dict.word_norm` 由 Python 的 `it/fixes/split_case_forms.norm` 写入，
 * 由 TS 的 `itSearchNorm` 查询。**同一个契约写了两遍。**
 *
 * 这正是 es 那次的形状：音标哈希 Python 和 TS 各写一遍，差一个字节，
 * 全库静默降级 —— 不报错、不告警，只是查不到，谁也发现不了。
 *
 * ⇒ 本闸不抽样：把 149 万行全部跑一遍 `itSearchNorm(word)`，与 `word_norm` 逐字节比。
 *   两边的实现只要有一处措辞不同（大小写与 NFD 的顺序、撇号字符表、`\p{Mn}` 的范围），
 *   立刻会有成千上万行对不上。
 *
 * 用法（仓库根目录）：
 *     npx tsx --tsconfig apps/web/tsconfig.json it/probes/norm_contract.ts
 *     npx tsx --tsconfig apps/web/tsconfig.json it/probes/norm_contract.ts --mutate
 */
import { DatabaseSync } from 'node:sqlite';
import { itSearchNorm } from '../../packages/dict-core/src/italian';

const DB = new URL('../../data/db/synapse-dict-it.sqlite', import.meta.url).pathname;

function main(): number {
  if (process.argv.includes('--mutate')) {
    // 变异验证：判据必须能识破两边实现的每一种典型分歧
    console.log('═══ 变异验证：归一函数的判据 ═══');
    const cases: [string, string, string][] = [
      ['弯撇号折成直撇号', itSearchNorm('all’alba'), "all'alba"],
      ['直撇号原样', itSearchNorm("all'alba"), "all'alba"],
      ['🔴 大小写要折', itSearchNorm('ASCII'), 'ascii'],
      ['🔴 重音符要去', itSearchNorm('città'), 'citta'],
      ['🔴 撇号 + 大写 + 重音三者同时', itSearchNorm('L’Aquilà'), "l'aquila"],
      ['其它撇号变体', itSearchNorm('kupʼjansk'), "kup'jansk"],
      ['🔴 连字符不许被当撇号', itSearchNorm('labio-glosso'), 'labio-glosso'],
    ];
    let ok = true;
    for (const [name, got, want] of cases) {
      const good = got === want;
      ok &&= good;
      console.log(`   ${good ? '✅' : '🔴'} ${name.padEnd(34)} → ${JSON.stringify(got)}`);
      if (!good) console.log(`        期望 ${JSON.stringify(want)}`);
    }
    console.log(`\n   变异验证 ${ok ? '通过' : '🔴 判据有问题'}`);
    return ok ? 0 : 1;
  }

  const db = new DatabaseSync(DB);
  db.exec('PRAGMA query_only = ON');
  const rows = db.prepare('SELECT word, word_norm FROM dict').all() as unknown as
    { word: string; word_norm: string }[];
  let bad = 0;
  const ex: string[] = [];
  for (const r of rows) {
    if (itSearchNorm(r.word) !== r.word_norm) {
      bad++;
      if (ex.length < 8) ex.push(`${r.word}  TS=${itSearchNorm(r.word)}  DB=${r.word_norm}`);
    }
  }
  db.close();
  console.log(`═══ 归一契约（TS itSearchNorm ↔ DB word_norm）═══`);
  console.log(`   逐行核对 ${rows.length.toLocaleString()} 行`);
  console.log(`   ${bad === 0 ? '✅' : '🔴'} 对不上 ${bad.toLocaleString()} 行 (期望 0)`);
  for (const e of ex) console.log(`        ${e}`);
  return bad === 0 ? 0 : 1;
}

process.exit(main());
