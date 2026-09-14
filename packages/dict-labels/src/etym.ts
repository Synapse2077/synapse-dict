// ============================================================================
// 词源正文的展示取舍。2026-09-14。
//
// 🔴🔴 **这一层只决定页面上印多少，数据一个字节不改。**
//    `etymology.text` 存的是源头原文（含那棵 "Etymology tree"）。用户 2026-09-14：
//    「线上不会放 dump，只会放 sqlite……我想看全部信息的时候能否查看」
//    ⇒ 全文永远在库里；改这里的判据不用回源重抽。
//
// ⚠️ 放在 dict-labels 而不是 dict-core：**浏览器端要用**（App.tsx 渲染时切），
//    而 dict-core 依赖 `node:sqlite`，进不了浏览器。键怎么算（`etymKeyOfSrcRef`）
//    留在 dict-core —— 那是数据层。两件事分属两层。
// ⚠️ 六门共用这一份：切句不含任何语种知识，而 kaikki 五门的 `etymology_text`
//    是同一种排版。
// ============================================================================


/** 源头正文的两部分：派生树（结构化的链）与散文。缺哪一半就是空。 */
export type EtymologyShape = { chain: string[]; prose: string };

// 一句词源散文的开头。判据取自实测：树块之后第一行匹配到它的就是散文起点，
// 2,223 个树块里 99.9% 命中（另 32 个只有树、没有散文）。
const PROSE_HEAD = /^(From|Borrowed|Inherited|Clipping|Blend|Compound|Calque|Back-formation|Backformation|Doublet|Univerbation|Abbreviation|Contraction|Shortening|Ultimately|Possibly|Perhaps|Probably|Uncertain|Unknown|Alteration|Variant|Derived|Formed|Coined|Named|Attested|Equivalent|Analogic|Of |A |An |The |In |By |After |Via |Calqued|Onomatopoe|Imitative|Eponym|Acronym|Initialism|Portmanteau|Reborrow|Semantic|Learned|Modelled|Modeled|Partly|Either|Both|Origin|Unadapted|Denominal|Deverbal|Adapted|Apocop|Apheresis|Aphetic)/i;

// 正文里的小标题：到这儿为止，后面是同源词表之类的附录。
// ⚠️ `free` 的写法是小写的 `cognates, etc` —— 判据**不能只认首字母大写**，
//    第一版就是这样漏掉的，而它恰好出现在最长的那批上。
const SECTION_HEAD = /^(cognates?[,.]?\s*(etc\.?)?|etymology tree|related terms|derived terms|descendants|see also|alternative etymolog\w*|notes?|synchronic\w*)$/i;

// 句末不是句末：缩写里的点。切第一句前必须排除，否则 `cat` 会被
// `(c. 350, Palladius)` 切成半句。
const ABBR_TAIL = /\b(c|ca|cf|e\.g|i\.e|vs|St|Mt|A\.D|B\.C|ed|pl|sg|lit|fl|Jr|Sr|Dr|Prof|approx|etc)\.$/i;

/** 把源头正文拆成「派生树 + 散文」。原文不改，只是分段。 */
export function etymologyShape(text: string | null | undefined): EtymologyShape {
  if (!text) return { chain: [], prose: '' };
  let lines = text.split('\n').map((x) => x.trim()).filter(Boolean);
  let chain: string[] = [];
  if (lines.length > 0 && lines[0].toLowerCase() === 'etymology tree') {
    const i = lines.findIndex((l, k) => k > 0 && PROSE_HEAD.test(l));
    if (i < 0) return { chain: lines.slice(1), prose: '' };   // 只有树，没有散文
    chain = lines.slice(1, i);
    lines = lines.slice(i);
  }
  const prose: string[] = [];
  for (const l of lines) {
    if (SECTION_HEAD.test(l)) break;      // 同源词表之类，到此为止
    prose.push(l);
  }
  return { chain, prose: prose.join(' ') };
}

/**
 * 页面上印的那一句 ＝ **派生链本身**。
 *
 * 用户 2026-09-14 定「只留派生链」。实测三种口径（30,443 个词源块）：
 *     全文照录   中位 62 ｜ 90% 365 ｜ 最长 3,167 ｜ 超 300 字 13.1%
 *     截到小标题 中位 53 ｜ 90% 305 ｜ 最长 2,914 ｜ 超 300 字 10.2%
 *     **只留第一句** 中位 47 ｜ 90% 194 ｜ 最长 1,458 ｜ 超 300 字 **3.3%**
 * 长出来的从来不是链，是链后面跟着的同源词表、考据讨论、被取代的古词
 * （`cat` 3,167 字里有 2,850 字在讲猫怎么随农业从近东传开）。
 * 而派生链**本来就是第一句**（`From A, from B, from C.`）⇒ 取第一句即可，
 * 一个派生信息都不丢：`cat` 3,167 → 315 字，链一级没少。
 */
/**
 * 维基残渣：脚注角标与没渲染开的模板/内链标记。**只在展示层剥，库里留原文。**
 *
 * 🔴 剥的是 `^([1])` / `^([*])` / `^([TLFi])` 这一族 —— 特征是**方括号在里面**。
 *    `^(ème)`（2ᵉ 的上标）、`^(6×4)`（指数）、`^(dans la base de données Wikidata)`
 *    是**真内容**，同样以 `^(` 开头，一个都不许碰。fr 实测：方括号族 1,013 处、
 *    非方括号族 56 处。判据窄一点，宁可漏剥（`[[criteria-narrower-than-you-think]]`）。
 * ⚠️ 这一条是 fr 契约闸「页面上不许出现模板/脚注残渣」逼出来的 ——
 *    法语版本的词源散文里带着 `^([1])`，接上之后 `rat`/`tout`/`nuit` 当场报红。
 *    六门合计：`^([` fr 839 / en 16 / it 16 / es 1；`{{`/`[[` 各几条。
 */
const WIKI_RESIDUE = /\^\(\[[^\]]*\]\)|\{\{|\}\}|\[\[|\]\]/g;

export function etymologyBrief(text: string | null | undefined): string {
  const { prose } = etymologyShape(text);
  if (!prose) return '';
  const parts = prose.split(/(?<=[.!?])\s+/);
  let out = '';
  for (const p of parts) {
    out = out ? `${out} ${p}` : p;
    const words = out.split(/\s+/);
    const tail = words[words.length - 1] ?? '';
    // 括号/引号没闭合就继续吃下一句 —— 半个括号比多一句更难看。
    if (!ABBR_TAIL.test(tail) && /[.!?]$/.test(out)
        && (out.split('(').length <= out.split(')').length)
        && (out.split('“').length <= out.split('”').length)) break;
  }
  // 剥残渣 ⇒ 会留下双空格和「空格+句点」，一并收拾干净。
  return out.replace(WIKI_RESIDUE, '')
    .replace(/\s{2,}/g, ' ')
    .replace(/\s+([.,;:!?）)])/g, '$1')
    .trim();
}
