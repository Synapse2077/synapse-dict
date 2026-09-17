/** **诊断辅助**（不是安全网）：SQL 模板字符串被反引号截断时，说出原因。2026-09-16。
 *
 * ⚠️ **先说清它不是什么**：这个错误 `tsc` **已经会红**（`TS1005: ',' expected`）。
 *    本文件不增加任何安全性 —— 它只把那条报错翻译成原因。
 *    留着它的唯一理由是：2026-09-16 我为同一个 TS1005 查了**两次**才想起来
 *    是「SQL 注释里用反引号引了个标识符，把模板提前终结了」，
 *    而第一次修完我**就在那段注释里写了「不许出现反引号」**，二十分钟后照犯。
 *    ⇒ 警告写在旁边拦不住（`[[lesson-must-become-mechanism]]`），
 *      但这里也只能把诊断时间从「一轮」压到「一眼」，别把它当闸。
 *
 * ⚠️ 判据是**括号配对**（截断的痕迹），不是"有没有反引号"——
 *    模板体里根本不可能留下反引号，它已经把模板切断了。
 *    已验证它真的会红（注入一个反引号 ⇒ 报 japanese.ts）。
 *
 * 跑：npx tsx scripts/contract/no_backtick_in_sql.ts
 */
import { readFileSync, readdirSync } from 'node:fs';

const DIR = new URL('../../packages/dict-core/src/', import.meta.url).pathname;
let red = 0;
for (const f of readdirSync(DIR).filter((x) => x.endsWith('.ts'))) {
  const src = readFileSync(DIR + f, 'utf8');
  // 找 prepare(` … `) 与 const X = ` … ` 里含 SQL 关键字的模板
  const re = /(?:prepare\(|=\s*)`([\s\S]*?)`/g;
  let m: RegExpExecArray | null;
  let n = 0;
  while ((m = re.exec(src))) {
    const body = m[1];
    if (!/\bSELECT\b|\bINSERT\b|\bUPDATE\b/i.test(body)) continue;
    // 模板体本身不可能含反引号（含了就已经被截断了）——
    // 所以这里查的是**截断的痕迹**：体内出现未闭合的 SQL 括号/引号。
    const opens = (body.match(/\(/g) || []).length;
    const closes = (body.match(/\)/g) || []).length;
    if (opens !== closes) { n += 1; }
  }
  if (n) { red += 1; console.log(`   🔴 ${f}  ${n} 处 SQL 模板括号不配对（多半是反引号截断）`); }
  else console.log(`   ✅ ${f}`);
}
console.log(red ? `\n🔴 ${red} 个文件有问题` : '\n✅ SQL 模板都完整');
process.exit(red ? 1 : 0);
