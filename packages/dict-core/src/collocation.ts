/**
 * 搭配详情页的**语种无关**部分。2026-09-14。
 *
 * ═══ 为什么有这个文件 ═══
 * 用户 2026-09-14：「搭配我希望也有详情页，请按照现有格式配置」。
 * 五门（es/it/fr/pt/de；**en 一条搭配都没有**）共 98,968 条短语，在此之前
 * 只是词条页上一行死文字 —— 搜得到（2026-09-12 补的反查），但点不开。
 *
 * 切词这件事五门**逐字一样**，所以抽出来放这里，SQL 留在各自的服务里
 * （`[[multilang-decoupling-essence]]`：按本质设计、按语种解耦 ——
 *  解耦的是**数据与查询**，不是纯函数；`relations.ts` 是同一种抽法）。
 */

/**
 * 把一条搭配短语切成「组成词」。**只按空白切，一个字符都不改。**
 *
 * 🔴 **不切撇号、不切连字符、不在这里剥标点。** 第一版在这里剥首尾标点，当场毁掉
 *    意语的 `'ndrangheta calabrese` —— `'ndrangheta` 是**库里真有的词形**（前接元音脱落），
 *    剥掉那个撇号就变成查不到的 `ndrangheta`，然后印成灰字。
 *    同一族还有 fr 的 `-ette`、de 的 `-%ig`（词缀词条，连字符在词形里面）。
 *    ⇒ 剥标点这件事**移到服务层、且只在原样查不到时才试**（见 `looseForms`）：
 *      能查到就说明这个写法本身是个词，没有任何理由去动它。
 *
 * ⚠️ 去重**保留首次出现的位置**：`de tal palo, de tal astilla` 里两个 `de`，
 *    印两遍是噪声；但顺序必须是读者在短语里看到的顺序。
 */
export function collocationParts(text: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of text.split(/\s+/)) {
    if (!raw) continue;
    const k = raw.toLowerCase();
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(raw);
  }
  return out;
}

/**
 * 一个组成词的**候选写法**，按「先原样、再逐步放宽」排好序。
 *
 * 服务层拿它逐个去查 `dict`，**第一个查得到的就是这个词**；全都查不到才算点不动。
 * 🔴 顺序不能反：原样能查到就用原样 —— 剥过的写法即使也能查到，也是另一个词
 *    （`ecc.` 是缩写词条，`ecc` 不是）。
 *
 * ⚠️ 撇号与连字符**不在剥除集合里**（见上）。剥的只有：引号、括号、
 *    西语的 `¡¿`、句读 `,;:!?…` 和句末点号。
 */
const EDGE_PUNCT = /^[\s"“”«»(){}\[\]¡¿]+|[\s"“”«»(){}\[\]¡¿.,;:!?…]+$/g;

export function looseForms(word: string): string[] {
  const out = [word];
  const stripped = word.replace(EDGE_PUNCT, '');
  if (stripped && stripped !== word) out.push(stripped);
  return out;
}

/** 搭配详情页的载荷。五门同一个形状 —— 页面是共用组件，形状分叉就等于组件分叉。 */
export type CollocationDetail = {
  lang: string;
  /** 短语原文（库里那一版的大小写与重音，不是读者敲进来的那一版）。 */
  text: string;
  /**
   * 这个短语**本身也是词头**时，给出词头写法，前端直接跳真词条页。
   * 用户 2026-09-14 定：「直接去真词条页」—— 真词条有音标/义项/例句/关系，
   * 搭配页在这种情况下没有存在价值（五门共 13,385 个短语是这样）。
   */
  headword: string | null;
  /** 中文释义。五门 100% 有（唯一例外：fr 有 1 条没有）。 */
  zh: string | null;
  /** 本语言的原文释义。**只有 it 从 kaikki 子条目搬来的 303 条有**，其余恒 null。 */
  srcText: string | null;
  /** 这个短语出现在哪些词条的搭配表里（都是词头，必然点得动）。 */
  owners: string[];
  /** 组成词。`clickable=false` 的是库里真没有，不做成链接。 */
  parts: { word: string; clickable: boolean }[];
};
