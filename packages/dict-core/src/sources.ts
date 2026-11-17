// ============================================================================
// 词条来源 —— 「这一页的数据是从哪个维基词典版本来的」。2026-11-17（B33①）。
//
// 为什么要有这个文件：
//   Wiktionary 的许可（CC BY-SA 4.0）要求署名。维基媒体条款认可的署名方式之一
//   是**链接到被复用的页面**。页面上要放这个链接，就得先知道「这个词条实际
//   用到了哪些语言版」—— 不能按「这门语言是 xx」想当然：
//     · ru `дом` 的义项同时来自 ru／zh／en／pl／fr 五个版本；
//     · en 门 242 万词条**只有 ECDICT**、没有任何维基来源（见 english.ts 文件头①）；
//     · 变形词条没有 sense_src 行，来源只在 `entry.src` 上。
//   ⇒ 判据是「数据库里这个词条真实的 src 集合」，不是词条的语种。
//
// 🔴 `[[dont-say-source-lacks-what-we-skipped]]`：映射不上的值**不许猜**。
//   映射不出语言版就返回 null、不挂链接 —— 把「我们不认识这个来源」说成
//   「它来自维基词典」，是给读者一个假出处。
// ============================================================================
import type { DatabaseSync } from 'node:sqlite';

export type SourceLink = {
  /** 维基词典语言代码（en/de/zh…）；非维基来源用固定标记（如 `ecdict`）。 */
  code: string;
  /** 给读者看的名字，如「英语维基词典」。 */
  label: string;
  /** 原页面链接；`null` 表示这条来源没有可指向的单页（如 ECDICT）。 */
  url: string | null;
};

/**
 * 来源名 → 维基词典语言代码。
 *
 * 值域来自十门 `sense_src.src` / `entry.src` 的**全量** DISTINCT（2026-11-17 实测）：
 *   en-edition｜es-edition｜it-edition｜fr-edition｜pt-edition｜de-edition
 *   de-edition-adjudicated｜de-edition-backfill｜ja-edition｜ko-edition｜vi-edition
 *   ru-edition｜pl-edition｜zh-edition｜zh-edition-simp｜zh-edition-trad
 *   frwiktionary｜itwiktionary｜eswiktionary｜ptwiktionary｜kk-en｜kk-de
 * 其中 `ecdict` / `zh-only` **不是**维基来源（ECDICT 是另一个项目；
 * `zh-only` 是我们模型补的中文，源头两版都没有原文，见 es/pipeline/build_sense_layer.py）。
 *
 * ⚠️ 不写成 `startsWith('en-edition')` 的黑名单：来源名会随时间长出新层
 *    （de 的 `-adjudicated`/`-backfill` 就是后加的），白名单式前缀匹配
 *    ＋「不认识就不挂」比「认识的全挂、不认识的全当维基」安全。
 */
export function wiktionaryLang(src: string | null | undefined): string | null {
  if (!src) return null;
  // en 门的 entry.src 是 kaikki 的文件代号，不是 edition 名：
  //   kk-en＝kaikki 英文版抽取（页面在 en.wiktionary.org）
  //   kk-de＝kaikki 德语版抽取（de 门词源表里出现）
  if (src === 'kk-en') return 'en';
  if (src === 'kk-de') return 'de';
  const w = /^([a-z]{2,3})wiktionary$/.exec(src);
  if (w) return w[1]!;
  const e = /^([a-z]{2,3})-edition(?:-|$)/.exec(src);
  if (e) return e[1]!;
  return null;
}

/** 语言代码 → 中文名。十门实测值域全覆盖；表外的代码退回「代码＋维基词典」。 */
const LANG_LABELS: Record<string, string> = {
  en: '英语', de: '德语', fr: '法语', it: '意大利语', es: '西班牙语',
  pt: '葡萄牙语', ja: '日语', ko: '韩语', vi: '越南语', ru: '俄语',
  zh: '中文', pl: '波兰语', el: '希腊语', tr: '土耳其语', nl: '荷兰语',
};

const ECDICT: SourceLink = {
  code: 'ecdict',
  label: 'ECDICT',
  url: 'https://github.com/skywind3000/ECDICT',
};

/** 维基词典页面地址。空格在 MediaWiki 标题里写作 `_`。 */
export function wiktionaryUrl(lang: string, word: string): string {
  return `https://${lang}.wiktionary.org/wiki/${encodeURIComponent(word.replace(/ /g, '_'))}`;
}

/**
 * 把一组来源名整理成页面上的来源行。
 *
 * @param srcs      数据库里的原始 `src` 值（可含 null）
 * @param word      词条写法（用于拼页面地址）
 * @param preferred 本门语言代码 —— 排在最前（ru 词条先列俄语维基词典）
 */
export function sourceLinks(
  srcs: Iterable<string | null | undefined>,
  word: string,
  preferred?: string,
): SourceLink[] {
  const langs: string[] = [];
  let hasEcdict = false;
  for (const src of srcs) {
    const lang = wiktionaryLang(src);
    if (lang) {
      if (!langs.includes(lang)) langs.push(lang);
    } else if (src === 'ecdict') {
      hasEcdict = true;
    }
    // 其余（zh-only / rule / g2p …）是我们自己生成的，不是可署名的外部页面。
  }
  langs.sort((a, b) => (a === preferred ? -1 : b === preferred ? 1 : 0));
  const out: SourceLink[] = langs.map((lang) => ({
    code: lang,
    label: `${LANG_LABELS[lang] ?? lang}维基词典`,
    url: wiktionaryUrl(lang, word),
  }));
  // ECDICT 只在这个词条真用到它时出现，且排最后。
  if (hasEcdict) out.push(ECDICT);
  return out;
}

/**
 * 从库里取一个词条的来源。
 *
 * 两条腿缺一不可：
 *   · `sense_src` —— 释义/例句的证据来源（有义项的词条都有）；
 *   · `entry`     —— 变形词条没有 `sense_src` 行，来源只在这里。
 * 两条都走 `word_id` 索引（十门实测都有 `idx_*_word`）。
 */
export function sourcesForWord(
  db: DatabaseSync,
  wordId: number,
  word: string,
  preferred?: string,
): SourceLink[] {
  const senseRows = db
    .prepare('SELECT DISTINCT src FROM sense_src WHERE word_id = ?')
    .all(wordId) as Array<{ src: string | null }>;
  // 🔴 **有义项来源时只用它，不并 `entry.src`。**
  //    `entry` 是词条级/变形级的行，一个 word_id 可以挂十几条（pt `casa` 的
  //    entry 覆盖 13 个语言版，而页面上的义项只来自 2 个）——并进来会让页脚
  //    列出一串读者根本没用到的版本。
  //    它只在**变形词条**上顶用：那些没有 sense_src 行，来源只在这里。
  const rows = senseRows.length > 0
    ? senseRows
    : db.prepare('SELECT DISTINCT src FROM entry WHERE word_id = ?')
        .all(wordId) as Array<{ src: string | null }>;
  return sourceLinks(rows.map((r) => r.src), word, preferred);
}
