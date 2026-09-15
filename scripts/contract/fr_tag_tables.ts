/** 闸：法文版 tag 分桶表的值**必须映射得出中文**。2026-09-15。
 *
 * ═══ 为什么要有这道闸 ═══
 * `FR_TAG_TOPIC` / `FR_TAG_REGION` / `FR_TAG_REGISTER` 住在 `dict-labels` 里，
 * 却**不被任何 TS 代码 import**，`index.ts` 也没导出它们 —— 它们的消费方是
 * **Python**：`fr/pipeline/ingest_fr_tags.py` 直接把 `fr.ts` 当文本解析。
 * 我 2026-09-15 查标签覆盖率时按 TS 的 import 图判断，把这四张表当成了死代码，
 * 差一点提议删掉。⇒ 光写注释说「它是活的」不够，得有个**会响的东西**
 * （`[[lesson-must-become-mechanism]]`：做成机制的全守住了，写成文字的一条没守住）。
 *
 * ═══ 闸问什么 ═══
 * 分桶表的**值**是规范键（英文），中文另从 `TOPIC_LABELS` / `FR_REGION_LABELS` /
 * `REGISTER_LABELS` 取。ingest 的纪律是「映射不出中文就**不出版**」——
 * 所以一个拼错的规范键不会报错，只会让那批 tag **静默地不上页面**。
 * 这条闸把「静默少收」变成「当场红」。
 */
import { readFileSync } from 'node:fs';
import { TOPIC_LABELS, REGISTER_LABELS } from '../../packages/dict-labels/src/common.js';
import { FR_REGION_LABELS } from '../../packages/dict-labels/src/fr.js';

const SRC = new URL('../../packages/dict-labels/src/fr.ts', import.meta.url).pathname;
const text = readFileSync(SRC, 'utf8');

/** 照 `ingest_fr_tags.py` 的 `table()` 一样按文本抠出表 —— 闸要走**和消费方同一条路**，
 *  直接 import 反而验不到「Python 解析得出来吗」这一半。 */
function table(name: string): Record<string, string> {
  const i = text.indexOf(`export const ${name}`);
  if (i < 0) throw new Error(`🔴 ${name} 在 fr.ts 里找不到 —— 它是 ingest_fr_tags.py 的输入，不是死代码`);
  const body = text.slice(text.indexOf('{', i) + 1, text.indexOf('\n};', i));
  const out: Record<string, string> = {};
  for (const m of body.matchAll(/(?:'([^']+)'|([A-Za-z_$][\w$]*))\s*:\s*'([^']*)'/g)) {
    out[(m[1] ?? m[2])] = m[3];
  }
  return out;
}

const CASES: Array<[string, Record<string, string>, string]> = [
  ['FR_TAG_TOPIC', TOPIC_LABELS, 'TOPIC_LABELS'],
  ['FR_TAG_REGION', FR_REGION_LABELS, 'FR_REGION_LABELS'],
  ['FR_TAG_REGISTER', REGISTER_LABELS, 'REGISTER_LABELS'],
];

let bad = 0;
for (const [name, zh, zhName] of CASES) {
  const t = table(name);
  const miss = [...new Set(Object.entries(t).filter(([, v]) => !(v in zh)).map(([k, v]) => `${k} → ${v}`))];
  const n = Object.keys(t).length;
  console.log(`${name.padEnd(17)} ${String(n).padStart(5)} 个键 → ${zhName}：`
    + (miss.length ? `🔴 ${miss.length} 个规范键查不到中文` : '✅ 全部查得到'));
  for (const m of miss.slice(0, 40)) console.log(`     ${m}`);
  if (miss.length > 40) console.log(`     …还有 ${miss.length - 40} 个`);
  bad += miss.length;
}
if (bad) {
  console.log('\n🔴 这些 tag 在 `ingest_fr_tags.py` 里会被**静默跳过、不出版**'
    + '（它的纪律是「映射不出中文就不收」）。修法二选一：'
    + '\n   ① 把规范键改成三张中文表里真有的那个；'
    + '\n   ② 给中文表补上这个规范键。');
  process.exit(1);
}
console.log('\n✅ 三张分桶表的值全部映射得出中文');
