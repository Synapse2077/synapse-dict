// 变形层**读取路径**核对：`getEntry(word).inflNotes` 必须与旧列 `dict.infl` 逐字节相同。
// 2026-08-20。
//
// ═══ 为什么这个必须单独存在 ═══
// `tests/test_no_regression.py` 的 C2 已经比过「新表 vs 旧列」—— 那是**写入侧**。
// 但 [[fix-regression-and-gate]] 记的第二种机制是「被绕过」：数据一个字节没丢、
// 查原列永远绿，而用户看到的是另一条路径算出来的东西。
// 2026-08-20 把 `spanish.ts` 的 `inflNotes` 从 `splitLines(row.infl)` 改成了读
// `inflection` 表 —— 从那一刻起，**页面上显示什么由 TS 那段拼接决定**，
// 库里比得再对也证明不了页面对。⇒ 这里走真正的 `getEntry`。
//
// ═══ 变异验证（2026-08-20 实跑，3/3 报红）═══
//   ORDER BY i.base       → 4,000 中 286 条不同
//   ORDER BY i.seq DESC   → 1,471 条不同
//   去掉「的」两侧空格      → 4,000 条全不同
//   还原                   → 4,000/4,000 相同
// ⚠️ 变异必须打在**拼接与排序**上。改数据是没用的：C2 那道闸会先红，
//    而这道闸问的是「页面拼出来的和列里的一不一样」。
//
// 用法（在仓库根目录）：
//     node --experimental-strip-types es/probes/infl_read_path.ts
import { DatabaseSync } from 'node:sqlite';
import { SpanishDictService } from '../../packages/dict-core/src/spanish.ts';

const ROOT = new URL('../../', import.meta.url).pathname;
const DB = `${ROOT}data/db/synapse-dict-es.sqlite`;
const LIMIT = Number(process.env.LIMIT || 4000);

const d = new SpanishDictService(DB, `${ROOT}data/tts/es`);
const raw = new DatabaseSync(DB, { readOnly: true });

// 取高频的那一批：变形词形有 97 万个，全查太慢，而 `freq_zipf` 高的正是用户真会划到的。
// 🔴 **有意与旧列不同的那批**（2026-08-20 `fixes/fix_glued_reflexive_base.py`）：
// 531 个词形做了重指或隐藏，页面上**应该**与 `dict.infl` 不同 ——
// `lo` 的「él and usted 的 宾格」修成了「él 的 宾格」。
// ⇒ 这些词形改判「差异是不是预期的那种」：页面上不许再出现被修掉的那个 base 字符串。
// 不写成「跳过」，因为跳过等于这 531 个从此没人看。
const touched = new Set<number>(
  (raw.prepare(`SELECT DISTINCT word_id FROM inflection
                WHERE base_fixed IS NOT NULL OR hidden = 1`).all() as
    Array<{ word_id: number }>).map((r) => r.word_id));
const badBase = new Map<number, string[]>();
for (const r of raw.prepare(`SELECT word_id, base FROM inflection
     WHERE base_fixed IS NOT NULL OR hidden = 1`).all() as
     Array<{ word_id: number; base: string }>) {
  if (!badBase.has(r.word_id)) badBase.set(r.word_id, []);
  badBase.get(r.word_id)!.push(r.base);
}

const rows = raw.prepare(
  `SELECT id, word, infl FROM dict WHERE infl IS NOT NULL AND infl <> ''
   ORDER BY COALESCE(freq_zipf, 0) DESC LIMIT ?`).all(LIMIT) as
  Array<{ id: number; word: string; infl: string }>;

let ok = 0; let bad = 0; let fixed = 0; const samples: string[] = [];
for (const r of rows) {
  const e = d.getEntry(r.word);
  const want = r.infl.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
  const got = e ? e.inflNotes : [];
  if (touched.has(r.id)) {
    // 预期不同：页面上一个被修掉的 base 都不许剩
    const leaked = (badBase.get(r.id) ?? []).filter(
      (b) => got.some((n) => n.startsWith(b + ' 的 ')));
    if (leaked.length === 0) fixed++;
    else {
      bad++;
      if (samples.length < 5) samples.push(`${r.word}（应已修）仍显示: ${JSON.stringify(leaked)}`);
    }
    continue;
  }
  if (JSON.stringify(want) === JSON.stringify(got)) ok++;
  else {
    bad++;
    if (samples.length < 5) {
      samples.push(`${r.word}\n     列: ${JSON.stringify(want)}\n     页: ${JSON.stringify(got)}`);
    }
  }
}
console.log(`读取路径核对 ${rows.length} 个高频变形词形：`
  + `与旧列相同 ${ok} / 已修且不再泄漏 ${fixed} / 🔴 不符 ${bad}`);
for (const s of samples) console.log('  🔴 ' + s);
process.exit(bad ? 1 : 0);
