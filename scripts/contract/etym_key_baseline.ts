/**
 * `etymKeyOfSrcRef` 的**行为基线**：拿 en/de 库里真实的 src_ref 跑一遍，输出 TSV。
 *
 * 🔴 为什么不是单元测试：这个函数 en 和 de 共用，要动它就必须证明
 *    **en 的输出一个字节都没变**。用真实数据的全量形状比手写几条用例硬。
 *    用法：改动前存一份、改动后再存一份，`diff` 必须只在 de 那边有差异。
 */
import { DatabaseSync } from 'node:sqlite';
import { etymKeyOfSrcRef } from '../../packages/dict-core/src/etym.js';

const ROOT = new URL('../../', import.meta.url).pathname;
for (const lang of ['en', 'de']) {
  const db = new DatabaseSync(`${ROOT}data/db/synapse-dict-${lang}.sqlite`, { readOnly: true });
  // 每种 (前缀, 段数) 形状取若干真实样本 —— 形状全覆盖，不是随机抽
  const rows = db.prepare(`
    SELECT src_ref FROM (
      SELECT src_ref,
             ROW_NUMBER() OVER (PARTITION BY substr(src_ref,1,instr(src_ref||':',':')-1),
                                             length(src_ref)-length(replace(src_ref,':',''))
                                ORDER BY src_ref) rn
        FROM sense_src WHERE src_ref IS NOT NULL)
     WHERE rn <= 40 ORDER BY src_ref`).all() as Array<{ src_ref: string }>;
  for (const r of rows) {
    console.log(`${lang}\t${r.src_ref}\t${etymKeyOfSrcRef(r.src_ref) ?? '<null>'}`);
  }
  db.close();
}
