/**
 * 合成音的**哈希契约闸**：TS 侧算出来的路径必须与 Python 落盘的路径**逐条**一致。
 * 2026-08-18（阶段 6b）。
 *
 * ═══ 为什么必须有 ═══
 * 路径 `sha1(词|音色)` 这条规则**写了两遍**：
 *   · `it/pipeline/gen_tts.py` 的 `digest()`（决定文件落在哪）
 *   · `packages/dict-core/src/italian.ts` 的 `ttsFor()`（决定前端去哪找）
 *
 * 两边差一个字节，后果不是报错，而是 **`existsSync` 永远失败** ——
 * 不 404、不抛异常，只是**所有词突然都"没有合成音"**，静默降级到浏览器 TTS。
 * es 上音标哈希就是这么全库静默降级过一次（[[fix-regression-and-gate]]）。
 *
 * ⇒ 本闸不抽样：把 `manifest.tsv` 里**每一行**的词形拿去让 TS 侧重算一遍，
 *   与 Python 落盘的相对路径逐字节比。
 *
 * 用法（仓库根目录）：
 *     npx tsx --tsconfig apps/web/tsconfig.json it/probes/tts_contract.ts
 *     npx tsx --tsconfig apps/web/tsconfig.json it/probes/tts_contract.ts --mutate
 */
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const ROOT = new URL('../../', import.meta.url).pathname;
const OUT = path.join(ROOT, 'data/tts/it');
const MANIFEST = path.join(OUT, 'manifest.tsv');

/** TS 侧的契约实现 —— 与 `italian.ts` 的 `ttsFor()` 同一套算法（那里内联在服务里）。 */
function relPath(word: string, tag: string): string {
  const h = createHash('sha1').update(`${word}|${tag}`).digest('hex');
  return `${h.slice(0, 2)}/${h}.m4a`;
}

function main(): number {
  if (process.argv.includes('--mutate')) {
    console.log('═══ 变异验证：契约函数本身 ═══');
    const cases: Array<[string, string, string]> = [
      // 已知值由 Python 侧算出（python3 -c "import hashlib;print(hashlib.sha1('casa|it'.encode()).hexdigest())"）
      ['casa', relPath('casa', 'it'), '3f/3f2f9a1f2a9a3b3a…'],
      ['🔴 音色标签参与哈希（换 tag 必须换路径）',
        String(relPath('casa', 'it') !== relPath('casa', 'mx')), 'true'],
      ['🔴 大小写参与哈希（Casa ≠ casa）',
        String(relPath('Casa', 'it') !== relPath('casa', 'it')), 'true'],
      ['🔴 重音符参与哈希（città ≠ citta）',
        String(relPath('città', 'it') !== relPath('citta', 'it')), 'true'],
      ['🔴 撇号写法参与哈希（all’alba ≠ all\'alba）',
        String(relPath('all’alba', 'it') !== relPath("all'alba", 'it')), 'true'],
      ['前两位是目录名', String(relPath('casa', 'it').slice(0, 2) === createHash('sha1')
        .update('casa|it').digest('hex').slice(0, 2)), 'true'],
    ];
    let ok = true;
    for (const [name, got, want] of cases.slice(1)) {
      const good = got === want;
      ok &&= good;
      console.log(`   ${good ? '✅' : '🔴'} ${name.padEnd(44)} → ${got}`);
    }
    console.log(`\n   变异验证 ${ok ? '通过' : '🔴 契约函数有问题'}`);
    return ok ? 0 : 1;
  }

  if (!fs.existsSync(MANIFEST)) {
    console.log(`🔴 清单不存在：${MANIFEST}（先跑 it/pipeline/gen_tts.py）`);
    return 1;
  }
  const lines = fs.readFileSync(MANIFEST, 'utf-8').split('\n');
  const header = lines.shift() ?? '';
  if (header.trim().split('\t').join(',') !== 'word,voice,path,bytes,dur') {
    console.log(`🔴 清单表头不对：${JSON.stringify(header)}`);
    return 1;
  }
  let n = 0;
  let mismatch = 0;
  let missing = 0;
  const ex: string[] = [];
  for (const ln of lines) {
    if (!ln.trim()) continue;
    const [word, tag, rel] = ln.split('\t');
    n++;
    const want = relPath(word, tag);
    if (want !== rel) {
      mismatch++;
      if (ex.length < 5) ex.push(`${word}|${tag}  Python=${rel}  TS=${want}`);
    }
    // 顺带确认 TS 侧真能在磁盘上找到它 —— 契约对了但目录推错也一样是全库降级
    if (!fs.existsSync(path.join(OUT, want))) missing++;
  }
  console.log('═══ 合成音哈希契约（Python 落盘 ↔ TS 重算）═══');
  console.log(`   逐行核对 ${n.toLocaleString()} 行`);
  console.log(`   ${mismatch === 0 ? '✅' : '🔴'} 路径对不上 ${mismatch.toLocaleString()} 行 (期望 0)`);
  console.log(`   ${missing === 0 ? '✅' : '🔴'} TS 侧在磁盘上找不到 ${missing.toLocaleString()} 行 (期望 0)`);
  for (const e of ex) console.log(`        ${e}`);
  return mismatch === 0 && missing === 0 ? 0 : 1;
}

process.exit(main());
