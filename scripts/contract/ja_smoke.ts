import { JapaneseDictService, normJa, moraCount } from '../../packages/dict-core/src/japanese.js';
import { DatabaseSync } from 'node:sqlite';
const DB = '/Users/fangyi/demo/synapse-dict/data/db/synapse-dict-ja.sqlite';

// ① 归一一致性：TS 的 normJa 必须与库里的 word_norm 逐字节相同
const raw = new DatabaseSync(DB, { readOnly: true });
const rows = raw.prepare('SELECT word, word_norm FROM dict ORDER BY RANDOM() LIMIT 4000').all() as Array<{word:string;word_norm:string}>;
let bad = 0; const ex: string[] = [];
for (const r of rows) {
  if (normJa(r.word) !== r.word_norm) { bad++; if (ex.length < 6) ex.push(`${r.word} → TS:${normJa(r.word)} vs DB:${r.word_norm}`); }
}
console.log(`■ 归一一致性 ${rows.length - bad}/${rows.length}` + (bad ? `  🔴 不一致 ${bad}` : '  ✅'));
ex.forEach((e) => console.log('   ', e));
raw.close();

const svc = new JapaneseDictService(DB);
console.log('■ stats', JSON.stringify(svc.getStats()));
console.log('■ 搜 「あじあ」（片假名词，考归一）:', svc.search('あじあ', 3).map((x) => `${x.word}[${x.kana}] ${x.brief}`).join(' / '));
console.log('■ 搜 「いた」:', svc.search('いた', 5).map((x) => `${x.word}[${x.kana}]`).join(' / '));
for (const w of ['痛い', '日本語', '愛する', 'あいする', 'いぬ', '青', '表現']) {
  const e = svc.getEntry(w);
  if (!e) { console.log(`\n── ${w}: 🔴 查不到`); continue; }
  console.log(`\n── ${w} ── pos=${e.pos} 字种=${e.kanjiGrade ?? '-'} zipf=${e.freqZipf ?? '-'}`);
  console.log('   读音:', e.readings.slice(0, 3).map((r) => `${r.kana ?? '?'}${r.romaji ? `/${r.romaji}` : ''}${r.ipa ? ` [${r.ipa}]` : ''}${r.pitchMark ? ` ♪${r.pitchMark}` : ''}${r.pitchPos !== null ? `(核${r.pitchPos}/${r.mora}拍)` : ''}`).join(' ｜ ') || '（无）');
  console.log(`   义项 ${e.senses.length}:`, e.senses.slice(0, 3).map((s) => `${s.zh ?? s.ja ?? s.en}`).join(' / '));
  console.log(`   例句 ${e.examples.length}:`, e.examples.slice(0, 2).map((x) => `${x.text.slice(0, 22)}${x.zh ? ` → ${x.zh.slice(0, 16)}` : ''}${x.ruby.length ? ` [ruby ${x.ruby.length}]` : ''}`).join(' ｜ ') || '（无）');
  console.log(`   关系 ${e.relations.length} 组 ｜ 异体 ${e.altOf.length} ｜ 同音 ${e.seeAlso.length} ｜ 变形 ${e.inflections.length} ｜ 录音 ${e.audio.length}`);
  if (e.bases.length) console.log(`   ← 这是变形，原形 ${e.bases.map((b) => b.word).join("、")}`);
}
svc.close();
