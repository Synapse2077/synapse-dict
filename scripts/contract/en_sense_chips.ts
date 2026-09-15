/** 契约闸：en 义项徽标**渲染出来是什么样**。2026-09-15。
 *
 * 复刻 `App.tsx` 里那段 chips 逻辑（topic 折祖先 + 查中文 + 按印出来的字去重），
 * 拿真词跑一遍 —— 数据层三层全绿不等于读者看得见对的东西
 * （`[[it-display-layer-stage8]]`）。
 *
 * 跑：npx tsx scripts/contract/en_sense_chips.ts
 */
import { EnglishDictService } from '../../packages/dict-core/src/english.js';
import { enLabel, enSenseTopics } from '../../packages/dict-labels/src/en.js';

const ROOT = new URL('../../', import.meta.url).pathname;
const svc = new EnglishDictService(`${ROOT}data/db/synapse-dict-en.sqlite`);

function chips(s: { src: string; tags: { kind: string; value: string }[] }): string[] {
  const topicVals = s.tags.filter((t) => t.kind === 'topic').map((t) => t.value);
  const topics = s.src === 'ecdict' ? topicVals : enSenseTopics(topicVals);
  const byText = new Map<string, boolean>();
  for (const t of topics) if (!byText.has(t)) byText.set(t, true);
  for (const t of s.tags) {
    if (t.kind === 'topic') continue;
    const zh = enLabel(t.kind, t.value);
    if (!byText.has(zh)) byText.set(zh, false);
  }
  return [...byText.keys()];
}

let bad = 0;
const ASCII = /^[\x20-\x7E]+$/;      // 纯 ASCII ⇒ 没映射到中文（专名 IRC/NASA/DVD 除外）
const OK_ASCII = new Set(['BDSM', 'IRC', 'NASA', 'DVD', 'CAD', 'CSS', 'Unix', 'Linux',
  'Windows', 'Lisp', 'GRE', 'Roguelike', 'demoscene']);
for (const w of ['google', 'h', 'bug', 'crow', 'blue', 'aback', 'standard', 'mri', 'fall',
  'pissed', 'brown', 'ablatitious', 'radio', 'positron', 'cricket', 'venitive']) {
  const e = svc.getEntry(w) as unknown as { senses: Array<{ zh: string | null; en: string | null; src: string; tags: { kind: string; value: string }[] }> } | null;
  if (!e) { console.log(`${w}：未收录`); continue; }
  console.log(`══ ${w}`);
  for (const s of e.senses.slice(0, 4)) {
    const c = chips(s);
    for (const t of c) {
      if (ASCII.test(t) && !OK_ASCII.has(t)) { bad += 1; console.log(`   🔴 裸英文徽标：${t}`); }
    }
    console.log(`   [${c.join('·') || '—'}]  ${String(s.zh ?? s.en ?? '').slice(0, 46)}`);
  }
}
console.log(bad ? `\n🔴 ${bad} 个徽标还是英文` : '\n✅ 没有裸英文徽标');
process.exit(bad ? 1 : 0);
