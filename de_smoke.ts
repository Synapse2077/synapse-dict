import { GermanDictService } from './packages/dict-core/src/german.ts';
const svc = new GermanDictService('./data/db/synapse-dict-de.sqlite');
console.log('stats', JSON.stringify(svc.getStats()));
for (const w of ['Haus','Dezember','Fussschmerze','gehen','Weissruthenen']) {
  const e = svc.getEntry(w);
  if (!e) { console.log(w, '→ 查不到'); continue; }
  console.log('\n══', e.word, '｜pos', e.pos, '｜lemma', e.isLemma, '｜zipf', e.freqZipf);
  console.log('  读音', e.readings.slice(0,3).map(r=>`/${r.ipa}/${r.region?'('+r.region+')':''}${r.primary?'*':''}`).join(' '));
  console.log('  义项', e.senses.length, e.senses.slice(0,2).map(s=>`${s.zh||'-'}｜de:${(s.de||'-').slice(0,40)}`).join(' ／ '));
  console.log('  例句', e.examples.length, e.examples[0]? `${e.examples[0].text.slice(0,44)} → ${(e.examples[0].zh||'-').slice(0,26)}`:'');
  console.log('  变形', e.inflections.length, '构词', e.derivations.length, '形式', e.forms.length, '关系', e.relations.length, '录音', e.audio.length, '搭配', e.collocations.length);
  if (e.inflections[0]) console.log('  →', e.inflections[0].base, e.inflections[0].label);
  if (e.bases[0]) console.log('  原形内联:', e.bases[0].word, e.bases[0].senses[0]?.zh);
}
svc.close();
