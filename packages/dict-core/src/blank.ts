// ============================================================================
// 空壳词条判定 —— 「有词条，页面上什么可读内容都没有」。2026-11-17。
//
// 口径与 `scripts/test_empty_entry_gate.py` **逐条一致**（那道闸锁基线）：
//   义项 sense／词源 etymology／读音 pronunciation／词条结构 entry／
//   变形关系 inflection（两端）／关系 sense_relation／
//   已发布的 ECDICT 兜底 legacy_gloss.published=1（仅 en）／
//   汉字读音 kanji_reading（ja）／hanja_reading（ko）／han_spelling+nom_spelling（vi）。
//   全空 ⇒ blank。
//
// ⚠️ 两处口径必须一起改：本文件与 `scripts/test_empty_entry_gate.py`。
//    闸跑的是数据基线，本文件决定页面上说什么 —— 分开写是因为闸是独立脚本
//    （它要能在没有 TS 运行时的情况下跑十门），没有更便宜的共享办法。
//
// 用途（2026-11-17 用户定）：这类词条**搜索保留**（收词方针是「词全」），
// 页面上明说「暂无可发布的释义」，不给读者一个说不清原因的空白页。
// 三类成因：en＝ECDICT low 质量有意不发布；pt/de＝源头只有词形、没有定义；
// 其余门个位数。
// ============================================================================
import type { DatabaseSync } from 'node:sqlite';

const INFLECTION: Record<string, string> = {
  en: "EXISTS (SELECT 1 FROM inflection i WHERE i.word_id=d.id OR i.base_id=d.id)",
  es: "EXISTS (SELECT 1 FROM inflection i WHERE i.word_id=d.id OR i.base_id=d.id)",
  it: "EXISTS (SELECT 1 FROM inflection i WHERE i.word_id=d.id OR i.base_id=d.id)",
  fr: "EXISTS (SELECT 1 FROM inflection i WHERE i.word_id=d.id OR i.base_id=d.id)",
  pt: "EXISTS (SELECT 1 FROM inflection i WHERE i.word_id=d.id OR i.base_id=d.id)",
  de: "EXISTS (SELECT 1 FROM inflection i WHERE i.word_id=d.id OR i.base_id=d.id)",
  ja: "EXISTS (SELECT 1 FROM inflection i WHERE i.word_id=d.id OR i.base_id=d.id)",
  ko: "EXISTS (SELECT 1 FROM inflection i WHERE i.word_id=d.id OR i.base_id=d.id)",
  vi: "0",
  ru: "EXISTS (SELECT 1 FROM inflection i JOIN entry e3 ON e3.id=i.entry_id WHERE e3.word_id=d.id)",
};

const EXTRA: Record<string, string[]> = {
  en: ["EXISTS (SELECT 1 FROM legacy_gloss g WHERE g.word_id=d.id AND g.published=1)"],
  ja: ["EXISTS (SELECT 1 FROM kanji_reading k WHERE k.word_id=d.id)"],
  ko: ["EXISTS (SELECT 1 FROM hanja_reading k WHERE k.word_id=d.id)"],
  vi: ["EXISTS (SELECT 1 FROM han_spelling k WHERE k.word_id=d.id)",
       "EXISTS (SELECT 1 FROM nom_spelling k WHERE k.word_id=d.id)"],
};
for (const l of Object.keys(INFLECTION)) {
  (EXTRA[l] ??= []).push("EXISTS (SELECT 1 FROM sense_relation r WHERE r.word_id=d.id)");
}

/** 这个词条在数据层是不是全空。 */
export function isEmptyEntry(db: DatabaseSync, lang: string, wordId: number): boolean {
  const cond = [
    "NOT EXISTS (SELECT 1 FROM sense s WHERE s.word_id=d.id)",
    "NOT EXISTS (SELECT 1 FROM etymology x WHERE x.word_id=d.id)",
    "NOT EXISTS (SELECT 1 FROM pronunciation p WHERE p.word_id=d.id)",
    "NOT EXISTS (SELECT 1 FROM entry en WHERE en.word_id=d.id)",
    `NOT (${INFLECTION[lang] ?? '0'})`,
    ...(EXTRA[lang] ?? []).map((e) => `NOT (${e})`),
  ];
  const sql = `SELECT 1 FROM dict d WHERE d.id = ? AND ${cond.join(' AND ')}`;
  return db.prepare(sql).get(wordId) !== undefined;
}
