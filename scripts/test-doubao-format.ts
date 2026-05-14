/**
 * 豆包大模型翻译格式测试脚本
 *
 * 功能：
 *   用少量单词测试豆包 API 的翻译效果和返回格式，
 *   验证 prompt 模板是否能产出符合词典格式的中文释义。
 *   用于调试和优化 fetch-translation-batch.py 的 prompt。
 *
 * 环境变量（.env）：
 *   ARK_API_KEY    - 火山引擎 API 密钥
 *   DOUBAO_MODEL   - 豆包模型 ID
 *
 * 用法：npx tsx scripts/test-doubao-format.ts
 */

import OpenAI from 'openai';
import dotenv from 'dotenv';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.resolve(__dirname, '..', '.env') });
dotenv.config({ path: path.resolve(__dirname, '..', '.env.local'), override: true });

const client = new OpenAI({
  apiKey: process.env.ARK_API_KEY,
  baseURL: 'https://ark.cn-beijing.volces.com/api/v3',
});

const prompt = `你是一个专业词典编辑。请为以下英文单词提供简洁的中文释义。

格式要求（严格遵守）：
- 格式为"词性缩写. 释义"，如：n. 苹果, 家伙
- 词性缩写标准：n. v. a. ad. prep. conj. interj. vt. vi.
- 多个词性用换行符\\n分隔，如：n. 算法\\nvt. 计算
- 同一词性的多个义项用", "分隔，如：n. 民主政治, 民主主义
- 如果是俚语加[俚]，网络用语加[网络]，专业术语加对应标签如[医]、[地质]、[史]等
- 释义简洁，每个义项不超过10个字
- 返回严格的JSON对象，key为单词原文，value为释义字符串
- 不要返回任何其他内容

参考已有词条格式：
apple → n. 苹果, 家伙
democracy → n. 民主政治, 民主主义
run → n. 跑, 赛跑, 奔跑\\nvi. 跑, 奔跑, 跑步\\nvt. 使跑, 驾驶, 管理

单词列表：
periot: A unit of weight, 9,600 of which make a grain.
brachiologia: Brevity in speech.
flowtop: The solid crust on a moving lava flow.
fyrdman: An English militiaman of the Saxon period.
fizzog: The face.
kottabos: An ancient Greek drinking game.
forshrunk: Utterly shrunk; entirely shrunk up.
jagoffs: A rude assholelike person.
skullets: A subspecies of mullet hairstyle where the top is bald.
jewdigger: Someone who dates people specifically because they are Jewish.`;

async function test() {
  const resp = await client.chat.completions.create({
    model: process.env.DOUBAO_MODEL!,
    messages: [{ role: 'user', content: prompt }],
    temperature: 0.1,
  });
  const content = resp.choices[0]?.message?.content?.trim() ?? '';
  console.log('=== Raw response ===');
  console.log(content);
  console.log('\n=== Parsed ===');
  const jsonStr = content.replace(/^```json\s*/, '').replace(/\s*```$/, '');
  const data = JSON.parse(jsonStr);
  for (const [word, translation] of Object.entries(data)) {
    console.log(`\n[${word}]`);
    console.log(translation);
  }
}

test().catch(console.error);
