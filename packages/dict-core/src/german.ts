// ============================================================================
// 德语词典服务 —— 德语专属，自包含，**不引用其它语种**（不复用 es/it/fr/pt 服务）。
//
// 2026-09-04 阶段 8：从**老扁平版重写为 v3 多表版**。
//
// 🔴 为什么必须重写：`[[it-display-layer-stage8]]` 与 fr 2026-08-29 的复发 ——
//    数据层全绿、库里查得到，而 `french.ts` 里 `FROM audio` 出现 **0 次**
//    ⇒ 39 万条录音一个用户都看不见。**「落库成功」证明不了「到达用户」。**
//    de 重写前的状态：317 行只读 `dict` 的扁平列，v3 **十三张表一张都没接** ——
//    音标 1,009,462 行、例句中文 443,897 条、语义关系 1,305,005 条、
//    录音 1,013,733 条，阶段 0–7 做的东西用户一个字都看不到。
//    （回归闸的 L1 就是这笔债的计数器，接完才该变绿。）
//
// ══════ 五条 de 独有、别的语种没有的约束 ══════
//
// ① 🔴🔴 **查变形必须走 `inflection.word_id`，绝不能走 `entry`**（收尾单 C10）：
//    实测 `inflection.entry_id` 为空的有 **4,868,806 / 5,367,555 ＝ 90.7%** ——
//    比 pt 的 132,660 严重一个数量级。走 entry 会把九成变形查不出来。
//
// ② 🔴 **`alt_of` 只画在义项里，不画在词条级**：de 的 8,917 条 alt_of
//    **全部挂在义项上**（`sense_id IS NULL` 的是 **0 条**）。
//    pt 那轮 08-31 正是把义项级的话按词条级渲染，在 `banco`（银行）页顶上印出
//    「异体 → banco de dados」——**那句话本身是错的**。de 这里连词条级查询都不建，
//    从结构上杜绝。
//
// ③ 🔴 **构词（`kind='derivation'`，7,156 行）必须与变形分区渲染**（收尾单 C13）：
//    `Häuslein ← Haus 指小词` 与 `Häuser ← Haus 复数` 并排，读者会以为前者也是格形式。
//    外审两家一致点了这一条。⇒ `inflections` 与 `derivations` 是两个字段，不是一个。
//
// ④ **德语词头保留原大小写，精确匹配优先**：名词首字母大写是正字法，
//    `Die`（裸芯片）与 `die`（冠词）是两个词条。用 `COLLATE NOCASE` 会把它们混为一谈。
//    ⚠️ 而 SQLite 的 `lower()`/`upper()` **只处理 ASCII**（收尾单 C25），
//    所以大小写归一一律交给调用方，本文件不在 SQL 里做。
//
// ⑤ **地区码目前有两套**（收尾单 C31）：`audio.region` 是 `de-AT`/`de-CH`，
//    `pronunciation.region` 是 `at`/`ch`/`de-north`/`de`。**本文件原样透出，不映射** ——
//    在展示层把它们抹平就是用补丁盖住数据缺陷（`[[aim-for-perfect-not-cheap]]`），
//    修法在生成侧，已落账。
//
// ⚠️ 隐藏行一律不出现在读者面前：`example.hidden=1`、`sense_relation.hidden=1`。
//    （de 的 `sense` 表**没有** `hidden` 列 —— 别照抄 pt 的 `COALESCE(s.hidden,0)=0`，
//     那会直接 SQL 报错。）
//
// ⚠️ **`label_zh` 里已知有两族脏数据，本文件有意不打补丁**：
//    C15 变化类连写 122,356 行（`强变化弱变化混合变化阳性单数宾格`）、
//    C16 异体被标成「变形」56,332 行。两者都要重跑阶段 2b 在**生成侧**修。
//    展示层遮住它们只会让人以为已经修好了。
//
// IPA 全语种**存裸**，斜杠由展示层统一加（`[[ipa-bare-storage-convention]]`）。
// ============================================================================

import { DatabaseSync } from 'node:sqlite';

export type GermanSearchItem = {
  id: number;
  word: string;
  brief: string | null;
  pos: string | null;
};

export type GermanRelationTarget = { word: string; clickable: boolean };
export type GermanRelationGroup = { kind: string; targets: GermanRelationTarget[] };
export type GermanAltOf = { target: string; zh: string | null; clickable: boolean };

export type GermanSense = {
  id: number;
  zh: string | null;
  de: string | null;          // 德语原文释义（三语方针里的「本语言」那一支）
  en: string | null;
  pos: string | null;
  gender: string | null;
  regions: string[];
  registers: string[];
  relations: GermanRelationGroup[];
  altOf: GermanAltOf[];
};

export type GermanReading = {
  ipa: string;
  notation: string | null;
  region: string | null;      // ⑤ 原样透出：at / ch / de-north / de / null
  pos: string | null;
  primary: boolean;
  src: string | null;
};

export type GermanExample = {
  senseId: number | null;
  text: string;
  zh: string | null;
  ref: string | null;
};

export type GermanInflection = { base: string; label: string | null; clickable: boolean };
export type GermanForm = { form: string; label: string | null };
export type GermanCollocation = { text: string; zh: string | null };

export type GermanAudio = {
  url: string;
  region: string | null;      // ⑤ 原样透出：de-AT / de-CH / null
  regionSrc: string | null;   // 这个地区是怎么判出来的（tag / filename）
  speaker: string | null;
};

// 多性别名词的逐性别变格束（der Band(Bandes/Bände) 卷 vs die Band(–/Bands) 乐队）。
// ⚠️ **保留这个字段**：它是德语独有的一等信息，v3 重写不该让它倒退。
export type NounVariant = { g: string; gen: string | null; pl: string | null };

export type GermanBase = {
  word: string;
  pos: string | null;
  ipa: string | null;
  gender: string | null;
  senses: GermanSense[];
};

export type GermanEntry = {
  lang: 'de';
  id: number;
  word: string;
  pos: string | null;
  isLemma: boolean;
  freqZipf: number | null;
  // 便捷字段：`readings` 里的主读音。多读音仍走 `readings`，这一条只为词头那一行。
  ipa: string | null;
  level: string | null;
  // —— 德语本质（一等字段，仍从 dict 扁平列读：它们是词条属性不是义项属性）——
  gender: string | null;        // m / f / n / mf
  genitive: string | null;      // 属格单数（des Hauses）
  plural: string | null;        // 复数（die Häuser）
  nounVariants: NounVariant[];  // 多性别名词逐性别范式束（RAM der/das、SMS die/das）
  aux: string | null;           // haben / sein
  praeteritum: string | null;
  partizip2: string | null;
  vclass: string | null;        // 强 / 弱 / 混合
  separable: boolean;
  sepPrefix: string | null;
  reflexive: boolean;
  comparative: string | null;
  superlative: string | null;
  government: string | null;
  // —— v3 多表 ——
  readings: GermanReading[];
  senses: GermanSense[];
  examples: GermanExample[];
  collocations: GermanCollocation[];
  inflections: GermanInflection[];   // ③ 这个词是谁的变形
  derivations: GermanInflection[];   // ③ 构词，**单独一区**
  forms: GermanForm[];               // 词元页反过来看：它有哪些形式
  relations: GermanRelationGroup[];  // 词条级（sense_id 为空的那 763,001 条）
  audio: GermanAudio[];
  bases: GermanBase[];
};

const HEAD = `id, word, pos, is_lemma, gender, genitive, plural, noun_variants, aux,
              praeteritum, partizip2, vclass, separable, sep_prefix, reflexive,
              comparative, superlative, government, level, freq_zipf`;

type DeRow = {
  id: number; word: string; pos: string | null; is_lemma: number;
  gender: string | null; genitive: string | null; plural: string | null;
  noun_variants: string | null;
  aux: string | null; praeteritum: string | null; partizip2: string | null;
  vclass: string | null; separable: number | null; sep_prefix: string | null;
  reflexive: number | null; comparative: string | null; superlative: string | null;
  government: string | null; level: string | null; freq_zipf: number | null;
};

function groupRelations(m: Map<string, GermanRelationTarget[]>): GermanRelationGroup[] {
  return [...m.entries()].map(([kind, targets]) => ({ kind, targets }));
}

export class GermanDictService {
  readonly lang = 'de';
  readonly databasePath: string;
  private readonly db: DatabaseSync;
  private readonly q: Record<string, ReturnType<DatabaseSync['prepare']>>;
  // 🔴 短前缀的**预计算表是阶段 9 才建的**，现在库里根本没有这张表。
  //    第一版无条件 `prepare` 它 ⇒ 构造函数当场抛 `no such table: search_prefix`，
  //    整个服务起不来。**「未命中回退实时查询」这条设计本来就该覆盖「表还不存在」**
  //    —— 它和「这个前缀没算过」是同一件事，不该是两种处理。
  private readonly cached: ReturnType<DatabaseSync['prepare']> | null;

  constructor(databasePath: string) {
    this.databasePath = databasePath;
    this.db = new DatabaseSync(databasePath);
    this.db.exec('PRAGMA query_only = ON');
    const hasPrefix = (this.db.prepare(
      "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' AND name='search_prefix'"
    ).get() as { n: number }).n > 0;
    this.cached = hasPrefix ? this.db.prepare(`
        SELECT d.id, d.word, d.pos, d.is_lemma
          FROM search_prefix p JOIN dict d ON d.id = p.word_id
         WHERE p.prefix = ? ORDER BY p.rank LIMIT ?`) : null;

    this.q = {
      stats: this.db.prepare(`
        SELECT (SELECT COUNT(*) FROM dict)                               AS total,
               (SELECT SUM(is_lemma) FROM dict)                          AS lemmas,
               (SELECT COUNT(DISTINCT word_id) FROM sense)               AS translated,
               (SELECT COUNT(DISTINCT word_id) FROM pronunciation)       AS ipa,
               (SELECT COUNT(DISTINCT word) FROM audio)                  AS audio,
               (SELECT COUNT(*) FROM example WHERE COALESCE(hidden,0)=0) AS examples`),

      // ④ 精确大小写优先；查不到再退回不区分大小写。
      head: this.db.prepare(
        `SELECT ${HEAD} FROM dict WHERE word = ? ORDER BY is_lemma DESC LIMIT 1`),
      headCI: this.db.prepare(
        `SELECT ${HEAD} FROM dict WHERE word = ? COLLATE NOCASE
          ORDER BY CASE WHEN word = ? THEN 0 ELSE 1 END, is_lemma DESC LIMIT 1`),

      // 🔴 **中文摘要必须查在 LIMIT 之后**（`[[query-perf-collation-traps]]`）。
      //    pt 那轮把它写成候选行上的相关子查询，实测 5,891ms → 拆开后 28ms。
      //    根因：相关子查询从选择性最差那头入手（`lang='zh'` 有几十万行），
      //    而且对**每个候选**都跑一次，不是只对留下的 20 条。
      prefix: this.db.prepare(`
        SELECT d.id, d.word, d.pos, d.is_lemma
          FROM dict d
         WHERE d.word LIKE ? COLLATE NOCASE OR d.word_norm LIKE ? COLLATE NOCASE
         ORDER BY CASE WHEN d.word = ? THEN 0 ELSE 1 END,
                  d.is_lemma DESC, LENGTH(d.word) ASC, d.word ASC
         LIMIT ?`),


      brief: this.db.prepare(`
        SELECT g.text FROM sense s
          JOIN sense_gloss g ON g.sense_id = s.id AND g.lang = 'zh'
         WHERE s.word_id = ? ORDER BY s.rank LIMIT 1`),

      // ⚠️ de 的 `sense` **没有 hidden 列**，别照抄 pt 的过滤条件。
      senses: this.db.prepare(`
        SELECT s.id, s.pos, s.gender,
               (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='zh' LIMIT 1) AS zh,
               (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='de' LIMIT 1) AS de,
               (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='en' LIMIT 1) AS en
          FROM sense s WHERE s.word_id = ? ORDER BY s.rank`),

      tags: this.db.prepare(
        `SELECT sense_id, kind, value FROM sense_tag WHERE sense_id IN
           (SELECT id FROM sense WHERE word_id = ?)`),

      // `is_primary` 先排；notation 目前全库只有 phonemic，留着排序键是为了以后加音位/音值两支。
      readings: this.db.prepare(`
        SELECT ipa, notation, region, pos, is_primary, src FROM pronunciation
         WHERE word_id = ?
         ORDER BY is_primary DESC,
                  CASE notation WHEN 'phonemic' THEN 0 ELSE 1 END,
                  CASE WHEN region IS NULL THEN 0 ELSE 1 END, id`),

      examples: this.db.prepare(`
        SELECT e.sense_id, e.text, e.ref,
               (SELECT text FROM example_gloss WHERE example_id=e.id AND lang='zh') AS zh
          FROM example e
         WHERE e.word = ? AND COALESCE(e.hidden,0)=0
         ORDER BY CASE WHEN e.sense_id IS NULL THEN 1 ELSE 0 END, e.id
         LIMIT 40`),

      colloc: this.db.prepare(`
        SELECT c.text,
               (SELECT text FROM collocation_gloss WHERE collocation_id=c.id AND lang='zh') AS zh
          FROM collocation c WHERE c.word_id = ? ORDER BY c.rank`),

      // ① 走 word_id，**不走 entry**（90.7% 的 entry_id 为空）。
      // ③ 变形与构词分开查，不是同一个列表。
      inflOf: this.db.prepare(`
        SELECT DISTINCT i.base, i.label_zh,
               (SELECT 1 FROM dict d WHERE d.word = i.base) AS ok
          FROM inflection i WHERE i.word_id = ? AND i.kind <> 'derivation'
         ORDER BY i.base, i.label_zh LIMIT 60`),
      derivOf: this.db.prepare(`
        SELECT DISTINCT i.base, i.label_zh,
               (SELECT 1 FROM dict d WHERE d.word = i.base) AS ok
          FROM inflection i WHERE i.word_id = ? AND i.kind = 'derivation'
         ORDER BY i.base, i.label_zh LIMIT 60`),

      forms: this.db.prepare(`
        SELECT DISTINCT d.word AS form, i.label_zh AS label
          FROM inflection i JOIN dict d ON d.id = i.word_id
         WHERE i.base_id = ? ORDER BY i.label_zh, d.word LIMIT 200`),

      // ⚠️ 词条级只取**没有义项归属**的（763,001 条）。有归属的走 `relBySense`，
      //    否则同一条会在词条级和义项级各印一遍。
      rel: this.db.prepare(`
        SELECT kind, target,
               (SELECT 1 FROM dict d WHERE d.word = sense_relation.target) AS ok
          FROM sense_relation
         WHERE word_id = ? AND sense_id IS NULL AND COALESCE(hidden,0) = 0
         LIMIT 200`),

      relBySense: this.db.prepare(`
        SELECT r.sense_id, r.kind, r.target,
               (SELECT 1 FROM dict d WHERE d.word = r.target) AS ok
          FROM sense_relation r
         WHERE r.sense_id IN (SELECT id FROM sense WHERE word_id = ?)
           AND r.kind <> 'alt_of' AND COALESCE(r.hidden,0) = 0`),

      // ② **只有义项级**。de 的 alt_of 一条都不挂在词条上，所以不建词条级查询。
      altOfBySense: this.db.prepare(`
        SELECT r.sense_id, r.target,
               (SELECT g.text FROM sense s
                  JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh'
                 WHERE s.word_id = (SELECT id FROM dict WHERE word = r.target)
                 ORDER BY s.rank LIMIT 1) AS zh,
               (SELECT 1 FROM dict d WHERE d.word = r.target) AS ok
          FROM sense_relation r
         WHERE r.sense_id IN (SELECT id FROM sense WHERE word_id = ?)
           AND r.kind = 'alt_of' AND COALESCE(r.hidden,0) = 0`),

      audio: this.db.prepare(`
        SELECT COALESCE(url_ogg, url_mp3, url_wav, url_other) AS url,
               region, region_src, speaker
          FROM audio WHERE word = ?
         ORDER BY CASE WHEN region IS NULL THEN 0 ELSE 1 END, id
         LIMIT 8`),
    };
  }

  getStats() {
    return this.q.stats.get() as Record<string, number>;
  }

  search(query: string, limit = 20): GermanSearchItem[] {
    const kw = query.trim();
    if (!kw) return [];
    const like = `${kw}%`;
    type Row = { id: number; word: string; pos: string | null };
    let rows = (this.cached?.all(kw, limit) ?? []) as Row[];
    if (rows.length === 0) rows = this.q.prefix.all(like, like, kw, limit) as Row[];
    return rows.map((r) => ({
      id: r.id, word: r.word, pos: r.pos,
      brief: (this.q.brief.get(r.id) as { text: string } | undefined)?.text ?? null,
    }));
  }

  private sensesOf(wordId: number): GermanSense[] {
    const rows = this.q.senses.all(wordId) as Array<{
      id: number; pos: string | null; gender: string | null;
      zh: string | null; de: string | null; en: string | null;
    }>;
    const tagRows = this.q.tags.all(wordId) as Array<{
      sense_id: number; kind: string; value: string;
    }>;
    const tagBy = new Map<number, { regions: string[]; registers: string[] }>();
    for (const t of tagRows) {
      const e = tagBy.get(t.sense_id) ?? { regions: [], registers: [] };
      if (t.kind === 'region') e.regions.push(t.value);
      else if (t.kind === 'register') e.registers.push(t.value);
      tagBy.set(t.sense_id, e);
    }
    const relBy = new Map<number, Map<string, GermanRelationTarget[]>>();
    for (const r of this.q.relBySense.all(wordId) as Array<{
      sense_id: number; kind: string; target: string; ok: number | null;
    }>) {
      const m = relBy.get(r.sense_id) ?? new Map<string, GermanRelationTarget[]>();
      const arr = m.get(r.kind) ?? [];
      arr.push({ word: r.target, clickable: !!r.ok });
      m.set(r.kind, arr);
      relBy.set(r.sense_id, m);
    }
    const altBy = new Map<number, GermanAltOf[]>();
    for (const r of this.q.altOfBySense.all(wordId) as Array<{
      sense_id: number; target: string; zh: string | null; ok: number | null;
    }>) {
      const arr = altBy.get(r.sense_id) ?? [];
      arr.push({ target: r.target, zh: r.zh, clickable: !!r.ok });
      altBy.set(r.sense_id, arr);
    }
    return rows.map((r) => ({
      id: r.id, zh: r.zh, de: r.de, en: r.en, pos: r.pos, gender: r.gender,
      ...(tagBy.get(r.id) ?? { regions: [], registers: [] }),
      relations: groupRelations(relBy.get(r.id) ?? new Map()),
      altOf: altBy.get(r.id) ?? [],
    }));
  }

  private mapEntry(row: DeRow): GermanEntry {
    const inf = (rows: unknown): GermanInflection[] =>
      (rows as Array<{ base: string; label_zh: string | null; ok: number | null }>)
        .map((x) => ({ base: x.base, label: x.label_zh, clickable: !!x.ok }));
    const readings = (this.q.readings.all(row.id) as Array<{
      ipa: string; notation: string | null; region: string | null;
      pos: string | null; is_primary: number | null; src: string | null;
    }>).map((r) => ({
      ipa: r.ipa, notation: r.notation, region: r.region,
      pos: r.pos, primary: !!r.is_primary, src: r.src,
    }));
    let nounVariants: NounVariant[] = [];
    if (row.noun_variants) {
      // 坏 JSON 不该让整个词条页崩掉 —— 宁可少一个范式束，也不给读者一片白。
      try { nounVariants = JSON.parse(row.noun_variants) as NounVariant[]; } catch { /* 忽略 */ }
    }
    const relMap = new Map<string, GermanRelationTarget[]>();
    for (const r of this.q.rel.all(row.id) as Array<{
      kind: string; target: string; ok: number | null;
    }>) {
      const arr = relMap.get(r.kind) ?? [];
      arr.push({ word: r.target, clickable: !!r.ok });
      relMap.set(r.kind, arr);
    }
    return {
      lang: 'de',
      id: row.id,
      word: row.word,
      pos: row.pos,
      isLemma: !!row.is_lemma,
      freqZipf: row.freq_zipf,
      level: row.level,
      gender: row.gender,
      genitive: row.genitive,
      plural: row.plural,
      aux: row.aux,
      praeteritum: row.praeteritum,
      partizip2: row.partizip2,
      vclass: row.vclass,
      separable: !!row.separable,
      sepPrefix: row.sep_prefix,
      reflexive: !!row.reflexive,
      comparative: row.comparative,
      superlative: row.superlative,
      government: row.government,
      ipa: readings[0]?.ipa ?? null,
      nounVariants,
      readings,
      senses: this.sensesOf(row.id),
      examples: (this.q.examples.all(row.word) as Array<{
        sense_id: number | null; text: string; ref: string | null; zh: string | null;
      }>).map((e) => ({ senseId: e.sense_id, text: e.text, zh: e.zh, ref: e.ref })),
      collocations: this.q.colloc.all(row.id) as GermanCollocation[],
      inflections: inf(this.q.inflOf.all(row.id)),
      derivations: inf(this.q.derivOf.all(row.id)),
      forms: this.q.forms.all(row.id) as GermanForm[],
      relations: groupRelations(relMap),
      audio: (this.q.audio.all(row.word) as Array<{
        url: string; region: string | null; region_src: string | null; speaker: string | null;
      }>).map((a) => ({
        url: a.url, region: a.region, regionSrc: a.region_src, speaker: a.speaker,
      })),
      bases: [],
    };
  }

  getEntry(word: string): GermanEntry | null {
    const kw = word.trim();
    if (!kw) return null;
    // ④ 精确大小写优先（`Die` 裸芯片 ≠ `die` 冠词）
    const row = (this.q.head.get(kw) ?? this.q.headCI.get(kw, kw)) as DeRow | undefined;
    if (!row) return null;
    const entry = this.mapEntry(row);

    // 变形页：把它指向的原形内联进来，读者不必再点一次。
    //
    // 🔴🔴 **只在这一页自己没有义项时才内联** —— 判据按含义：
    //    「这一页有没有自己的内容」。第一版对所有词条都内联，渲染出来当场看见：
    //    `Haus`（房屋，4 条义项、词元）页上内联出 **`Hau` 猛击** ——
    //    因为 `Haus` 同时是 `Hau` 的单数属格，**语言学上没错**，
    //    但把「猛击」摆进「房屋」的页面里就是噪声。
    //    ⇒ 有自己的义项 = 有自己的内容 = 不需要借别人的。
    //    （`[[it-display-layer-stage8]]`：库里查不出异常，渲染出来一眼看见。）
    if (entry.senses.length > 0) return entry;

    // 🔴 **异体链要多跟一跳**：2d 补的那批是「异体 → 异体 → 词元」
    //    （`Fussschmerze → Fußschmerze → Fußschmerz`）。只跟一跳会内联出一页空白 ——
    //    第一版实测 `Fußschmerze` 自己也没有义项，内联结果是 `undefined`。
    const seen = new Set<string>([entry.word]);
    const push = (w: string, depth: number): boolean => {
      if (seen.has(w) || depth > 2) return false;
      seen.add(w);
      const br = this.q.head.get(w) as DeRow | undefined;
      if (!br) return false;
      const senses = this.sensesOf(br.id);
      if (senses.length === 0) {
        // 这一跳也是空的：继续往它的原形走，别把空页摆给读者。
        for (const nx of this.q.inflOf.all(br.id) as Array<{ base: string; ok: number | null }>) {
          if (nx.ok && push(nx.base, depth + 1)) return true;
        }
        return false;
      }
      entry.bases.push({
        word: br.word, pos: br.pos, gender: br.gender,
        ipa: (this.q.readings.all(br.id) as Array<{ ipa: string }>)[0]?.ipa ?? null,
        senses,
      });
      return true;
    };
    for (const i of entry.inflections) {
      if (!i.clickable) continue;
      push(i.base, 0);
      if (entry.bases.length >= 3) break;
    }
    return entry;
  }

  close() {
    this.db.close();
  }
}
