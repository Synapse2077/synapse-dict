/**
 * 将豆包 API 返回的中文释义从 JSONL 合并到 SQLite
 *
 * 功能：
 *   读取 ../data/intermediate/doubao-translation.jsonl 中的翻译结果，
 *   批量更新到 SQLite 词典的 translation 字段。
 *   只更新 translation 为空的记录，不会覆盖已有翻译。
 *
 * 配合使用：
 *   先运行 fetch-translation-batch.py 生成 JSONL，再运行本脚本合并。
 *   可多次运行，幂等安全。
 *
 * 用法：npx tsx scripts/merge-translation.ts
 */

import fs from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DICT_ROOT = path.resolve(__dirname, '..');

const DB_PATH = path.resolve(DICT_ROOT, 'data', 'synapse-dict.sqlite');
const INPUT_PATH = path.resolve(DICT_ROOT, 'data', 'intermediate', 'doubao-translation.jsonl');

function main() {
  if (!fs.existsSync(INPUT_PATH)) {
    console.error(`File not found: ${INPUT_PATH}`);
    process.exit(1);
  }

  const lines = fs.readFileSync(INPUT_PATH, 'utf-8').split('\n').filter(Boolean);
  console.log(`Loaded ${lines.length} lines from JSONL`);

  const entries: { word: string; translation: string }[] = [];
  for (const line of lines) {
    try {
      const obj = JSON.parse(line);
      if (obj.word && obj.translation) {
        entries.push({ word: obj.word, translation: obj.translation });
      }
    } catch { /* skip */ }
  }
  console.log(`Valid entries: ${entries.length}`);

  const db = new DatabaseSync(DB_PATH);
  const update = db.prepare(`
    UPDATE stardict SET translation = ?
    WHERE word = ? COLLATE NOCASE
    AND (translation IS NULL OR translation = '')
  `);

  db.exec('BEGIN');
  try {
    let updated = 0;
    for (const e of entries) {
      const result = update.run(e.translation, e.word);
      if (result.changes > 0) {
        updated++;
      }
    }
    db.exec('COMMIT');
    db.close();

    console.log(`Updated ${updated} rows in SQLite`);
  } catch (error) {
    db.exec('ROLLBACK');
    db.close();
    throw error;
  }
}

main();
