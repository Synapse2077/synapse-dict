// ============================================================================
// 韩语词典服务。2026-09-25（阶段 9）。
//
// ═══ 🔴 五处和前七门不一样，照抄会静默出错 ═══
//
// ① **搜索一律走 `word_norm`，绝不用 `COLLATE NOCASE`。**
//    与 ja 同一个坑：SQLite 的 NOCASE / `lower()` 只折 ASCII，对谚文完全无效。
//    ko 的 `word_norm` 是 **NFC**（`criteria.norm_ko`）。实测库里
//    `word <> word_norm` 的行是 **0** —— 源头两版词头本来就是 NFC。
//    ⚠️ 所以归一在**查询侧**才有用：macOS 输入法产出 **NFD**（`한` 拆成 ㅎ+ㅏ+ㄴ），
//      长得一模一样、字节不同、`=` 匹配不上。⇒ JS 这边必须 `normalize('NFC')`。
//
// ② **四套罗马字只显示 RR。** 库里存了 revised / revised-translit / MR / Yale
//    四套（用户 2026-09-20 拍板「四套全存，页面只显示 RR」）。
//    🔴 本文件**只 SELECT `roman_rr`** —— 另三套连查都不查。
//    回归闸扫展示层源码盯这一条，所以别为了"顺手"把它们一起端出去。
//
// ③ **读音要读 `notation` 决定定界符。** 音标裸存（八语种统一约定），
//    而韩语 98.6% 是**窄式**（`[ka̠]`，带音变的实际音值），不是音位式。
//    印成 `/…/` 是错的。`notation` ∈ narrow|phonemic|bare，bare ＝源头没说，
//    **不许替源头猜**（印裸串）。
//    ⭐ 另有 `hangeul_phonetic`（发音形谚文，`읽다` 实际读作 `익따`）——
//      **拉丁七门都没有这一层**，它比 IPA 对中文读者更直观。
//
// ④ **变形块是 ko 独有的显示难题。** 实测 `걷다` 有 **169** 个活用形，
//    **5,932 个词元有 100 个以上**（近一半）。拉平列出来没法看，
//    而 de/pt 那种 `LIMIT 200` 截断对韩语是错的 —— 韩语活用表的惯例是
//    **按敬语阶×时制×语气排成表**。⇒ 本文件**按 `label_zh` 分组返回**，不截断。
//    🔴 `generated` 标出「这张表是按规则生成的」（`src='rule'`，阶段 8 后补，
//      745,037 行）—— 实测残差 ≈322 个错误词形（K18）。
//      **读者有权知道哪一格是源头给的、哪一格是我们算的**；
//      把两者印成一样就是拿生成物冒充源头。
//
// ⑤ **`sense.hidden=1` 有 200,207 条**（全库义项的 72%）。那是 K10：
//    源头挂在这些义项下的"释义"其实是**元描述**（讲这个词**怎么写**，
//    不是它**什么意思**），阶段 8 搬走之后义项成了空壳。
//    🔴 服务层一律 `hidden = 0`。⚠️ 但**不要在展示层把这件事抹平** ——
//      这些词点进去只有汉字表记和读音、没有释义，那是**真实的库存状态**，
//      `[[dont-recast-deliverables-as-junk]]` 的反面：不许用体面的兜底把缺口藏起来。
//      `it-display-layer-stage8` 的教训原话：**兜底越体面缺陷越难发现**。
//
// ⑥ **关系词有两个字段，`target` 显示、`targetNorm` 链接，别混用。**
//    源头的 target 带 wiktextract 的专名标记和汉字括号注：`^팔도`、`경마(競馬)`。
//    拿它直接比 `word_norm`，实测 **34.6% 的关系词点下去是空白页**；
//    按阶梯判据解析之后能链上的是 **68.78%**
//    （`ko/pipeline/resolve_relation_targets.py`）。
//    🔴 括号里的汉字**不许在显示里抹掉** —— `부인(婦人)` / `부인(否認)` 是两个词，
//      而我们只有**词形级**的页面，抹掉它读者就分不清点过去看哪一条（K20）。
//    🔴 `hanja_spelling` / `alt_hanja` 这两类**根本不该渲染成链接**：
//      目标是 `換面相訟` 这种多字汉字串，我们没有这种词头（51,254 条里 43,547 条
//      查不到）。那不是缺陷 —— 汉字表记是**注**不是词。
//      判据在 `dict-labels` 的 `KO_ANNOTATION_KINDS`，**不要在这儿再抄一份**
//      （`[[refactor-mindset-code-quality]]`：同一文件里两张重复映射表已经发生过）。
//    ⇒ 排掉那一族之后，真正当链接渲染的 204,185 条里空链 **17.69%**。
// ============================================================================
import { DatabaseSync } from 'node:sqlite';

export type KoreanSearchItem = {
  id: number;
  word: string;
  /** 修正罗马字（RR）。搜索结果带它 —— 中文读者靠它认音，谚文认不出来。 */
  roman: string | null;
  brief: string | null;
  pos: string | null;
};

/** 一条读音。`notation` 决定展示层加 `[ ]` 还是 `/ /` 还是裸印。 */
export type KoreanPronunciation = {
  ipa: string;
  notation: 'narrow' | 'phonemic' | 'bare';
  /** 发音形谚文（`익따`）—— ko 独有。 */
  hangeul: string | null;
  region: string | null;
  /** 来源；`g2p` ＝ 我们按 표준발음법 算的，不是源头给的。 */
  src: string;
  /** 跨版背书：≥2 版给出同一个读音（`src` 里含 `+`）。 */
  endorsed: boolean;
};

export type KoreanRelation = {
  kind: string;
  /**
   * 🔴 **源头原文，照原样显示**（`경마(競馬)`、`^팔도`）。括号里的汉字是
   * 给读者的信息：`부인(婦人)` 与 `부인(否認)` 是两个词。**不要拿它当链接。**
   */
  target: string;
  /**
   * 链接落点：解析出来的词头（`경마` / `팔도`），查不到就 `null`。
   * 见 `ko/pipeline/resolve_relation_targets.py` 的阶梯式判据。
   */
  targetNorm: string | null;
  /** 目标的中文释义（一句），给读者判断要不要点 */
  zh: string | null;
};

export type KoreanRelationGroup = { kind: string; items: KoreanRelation[] };

export type KoreanSense = {
  id: number;
  etymNo: string | null;
  pos: string | null;
  zh: string | null;
  en: string | null;
  /** 本语言（韩语）释义 —— 三语方针里的第三种。 */
  ko: string | null;
  /** 中文释义是模型译的还是源头白送的。⚠️ 读者不必看见，验收要能分开。 */
  zhFromModel: boolean;
  relations: KoreanRelationGroup[];
};

export type KoreanExample = {
  senseId: number | null;
  text: string;
  zh: string | null;
  en: string | null;
  ref: string | null;
  roman: string | null;
};

/** 活用表的一行：一个语法位置 → 一个或多个形式。 */
export type KoreanInflectionRow = {
  label: string;
  forms: string[];
  /** 这一行是按规则生成的（`src='rule'`），不是源头给的。 */
  generated: boolean;
};

export type KoreanEntryView = {
  /** 这个词条的汉字表记（`환면상송（換面相訟）` 的 `換面相訟`）。 */
  hanja: string | null;
  pos: string | null;
  etymNo: string | null;
  roman: string | null;
  /** 活用类（여불규칙 / ㅂ불규칙 / …）。`conj_class_src` 说它是怎么来的。 */
  conjClass: string | null;
  conjClassSrc: string | null;
};

export type KoreanEntry = {
  lang: 'ko';
  id: number;
  word: string;
  isLemma: boolean;
  roman: string | null;
  entries: KoreanEntryView[];
  pronunciations: KoreanPronunciation[];
  senses: KoreanSense[];
  /** 词级关系（挂不到具体义项上的） */
  relations: KoreanRelationGroup[];
  examples: KoreanExample[];
  /** 它作为原形时的活用表 */
  inflections: KoreanInflectionRow[];
  /** 它作为变形形时，指回哪些原形 */
  baseOf: { base: string; labels: string[]; ok: boolean }[];
  /** 这个谚文音节对应的汉字音训（`주` → 主/住/注…） */
  hanjaReadings: { hanja: string; eumhun: string | null; glossEn: string | null }[];
  etymology: { edition: string; etymNo: string | null; text: string }[];
  audio: { file: string; url: string | null; kind: string; region: string | null }[];
};

/** 🔴 归一只用于**匹配**，不用于身份。macOS 输入法产出 NFD。 */
function normKo(s: string): string {
  return s.normalize('NFC');
}

export class KoreanDictService {
  readonly databasePath: string;

  readonly lang = 'ko';

  private readonly db: DatabaseSync;

  private readonly q: Record<string, ReturnType<DatabaseSync['prepare']>>;

  constructor(databasePath: string) {
    this.databasePath = databasePath;
    this.db = new DatabaseSync(databasePath);
    this.db.exec('PRAGMA query_only = ON');

    this.q = {
      stats: this.db.prepare(`
        SELECT (SELECT COUNT(*) FROM dict)                        AS total,
               (SELECT SUM(is_lemma) FROM dict)                   AS lemmas,
               (SELECT COUNT(*) FROM sense WHERE hidden = 0)      AS senses,
               (SELECT COUNT(*) FROM example WHERE COALESCE(hidden,0)=0) AS examples,
               (SELECT COUNT(*) FROM audio)                       AS audio,
               (SELECT COUNT(*) FROM inflection)                  AS inflections
      `),

      // 🔴 前缀搜索走 `word_norm`（NFC），**不要 COLLATE NOCASE** —— 见文件头①。
      // ⚠️ 排序把**词元排在变形形前面**：库里 96% 是变形形（活用表生成之后
      //    1,232,621 行里 965,000 个不是词元），不排序的话搜 `가` 出来的全是活用形。
      search: this.db.prepare(`
        SELECT d.id, d.word,
               (SELECT e.roman_rr FROM entry e WHERE e.word_id = d.id
                 AND e.roman_rr IS NOT NULL LIMIT 1) AS roman,
               (SELECT g.text FROM sense s JOIN sense_gloss g ON g.sense_id = s.id
                 WHERE s.word_id = d.id AND s.hidden = 0 AND g.lang = 'zh'
                 ORDER BY s.rank, s.id LIMIT 1) AS brief,
               d.pos
        FROM dict d
        WHERE d.word_norm >= ? AND d.word_norm < ?
        ORDER BY d.is_lemma DESC, LENGTH(d.word), d.word
        LIMIT ?
      `),

      exact: this.db.prepare('SELECT id, word, is_lemma FROM dict WHERE word_norm = ?'),

      // 词条层。🔴 **只取 `roman_rr`**，另三套连查都不查（文件头②）。
      entries: this.db.prepare(`
        SELECT hanja, pos, etym_no AS etymNo, roman_rr AS roman,
               conj_class AS conjClass, conj_class_src AS conjClassSrc
        FROM entry WHERE word_id = ? ORDER BY etym_no, seq
      `),

      // 读音。🔴 端出 `notation` 让展示层决定定界符（文件头③）。
      // ⚠️ `entry_id IS NULL` ＝ 该词形各词条共用，**不是"取不到"** ——
      //    所以这里按词形取全，不按 entry 过滤（it 的 A57 踩过反过来的坑）。
      pronunciations: this.db.prepare(`
        SELECT ipa, notation, hangeul_phonetic AS hangeul, region, src,
               (src LIKE '%+%') AS endorsed
        FROM pronunciation WHERE word_id = ?
        ORDER BY (src = 'g2p'), is_primary DESC, id
      `),

      // 出版层义项。🔴 `hidden = 0` —— 那 200,207 条空壳是 K10（文件头⑤）。
      senses: this.db.prepare(`
        SELECT s.id, s.pos, e.etym_no AS etymNo,
               (SELECT text FROM sense_gloss WHERE sense_id = s.id AND lang='zh'
                 ORDER BY seq LIMIT 1) AS zh,
               (SELECT src  FROM sense_gloss WHERE sense_id = s.id AND lang='zh'
                 ORDER BY seq LIMIT 1) AS zhSrc,
               (SELECT text FROM sense_gloss WHERE sense_id = s.id AND lang='en'
                 ORDER BY seq LIMIT 1) AS en,
               (SELECT text FROM sense_gloss WHERE sense_id = s.id AND lang='ko'
                 ORDER BY seq LIMIT 1) AS ko
        FROM sense s LEFT JOIN entry e ON e.id = s.entry_id
        WHERE s.word_id = ? AND s.hidden = 0
        ORDER BY e.etym_no, s.rank, s.id
      `),

      // 关系。一次取全，调用方按 sense_id 分到义项级/词级。
      // 关系。一次取全，调用方按 sense_id 分到义项级/词级。
      // 🔴 链接走 `target_norm` 不走 `target`（文件头⑥）。此前这里是
      //    `word_norm = r.target`，实测 **34.6% 点下去是空白页** —— 因为源头
      //    的 target 带 `^` 专名标记和 `(漢字)` 括号注，直接拿去比对必然落空。
      relations: this.db.prepare(`
        SELECT r.sense_id AS senseId, r.kind,
               -- 🔴 「^」是 wiktextract 的**专名标记**，不是词的一部分（「^팔도」）。
               --    韩语没有大小写，它在这门语言里一个字节的信息都不带，
               --    而「(漢字)」括号注带（부인(婦人) 与 부인(否認) 是两个词）——
               --    两者都在 target 里，判据必须分开：剥前者、留后者。
               --    注：剥在这儿不在库里，sense_relation.target 要保持源头原文。
               --    全库 291 条带 ^，其中 1 条在词尾。
               --    ⚠️ 这一段**不能用反引号**：它在 JS 模板串里，反引号会当场截断字符串
               --       （第一版就是这么写的，tsc 报 TS1005 一串）。
               REPLACE(r.target, '^', '') AS target, r.target_norm AS targetNorm,
               (SELECT g.text FROM sense s2 JOIN sense_gloss g ON g.sense_id = s2.id
                 JOIN dict d2 ON d2.id = s2.word_id
                 WHERE d2.word_norm = r.target_norm AND g.lang='zh' AND s2.hidden = 0
                 ORDER BY s2.rank LIMIT 1) AS zh
        FROM sense_relation r
        WHERE r.word_id = ? AND COALESCE(r.hidden,0) = 0
        ORDER BY r.kind, r.id
      `),

      // 例句。🔴 `hidden = 0` 排掉 792 条**根本不是例句**的行
      //    （K15 成分拆解 / K11 构词公式 / 占位标签 / 多行 blob）——
      //    `hidden_why` 说得出每一条为什么不显示。
      examples: this.db.prepare(`
        SELECT x.sense_id AS senseId, x.text, x.ref, x.roman,
               (SELECT text FROM example_gloss WHERE example_id=x.id AND lang='zh') AS zh,
               (SELECT text FROM example_gloss WHERE example_id=x.id AND lang='en') AS en
        FROM example x
        WHERE x.word = ? AND COALESCE(x.hidden,0) = 0
        ORDER BY x.sense_id IS NULL, x.id
      `),

      // 它作为原形时的活用表。**按 `base` 取词形，不按 `base_id`** ——
      // 与 ja 同一条理由：`base_id` 可能悬空。
      // 🔴 **逐行取回，不在 SQL 里 GROUP BY 压标签**（ja 用 `MIN(label_zh)` 压掉了
      //    9% 的组合，而页面看起来完全正常）。归并在 JS 侧做。
      inflections: this.db.prepare(`
        SELECT i.label_zh AS label, d.word AS form, i.src
        FROM inflection i JOIN dict d ON d.id = i.word_id
        WHERE i.base = ? ORDER BY i.id
      `),

      // 它作为变形形时，指回原形。
      baseOf: this.db.prepare(`
        SELECT i.base, i.label_zh AS label,
               EXISTS(SELECT 1 FROM dict d WHERE d.word_norm = i.base) AS ok
        FROM inflection i WHERE i.word_id = ? ORDER BY i.base, i.id
      `),

      // 汉字音训（`주` → 主/住/注…）。ko 独有的一层。
      hanjaReadings: this.db.prepare(
        'SELECT hanja, eumhun, gloss_en AS glossEn FROM hanja_reading'
        + ' WHERE word_id = ? ORDER BY id'),

      etymology: this.db.prepare(
        'SELECT edition, etym_no AS etymNo, text FROM etymology'
        + ' WHERE word_id = ? ORDER BY etym_no'),

      audio: this.db.prepare(
        'SELECT file, COALESCE(url_mp3, url_ogg, url_wav, url_other) AS url,'
        + ' kind, region FROM audio WHERE word = ? ORDER BY (kind<>\'human\'), id'),
    };
  }

  getStats() { return this.q.stats.get() as Record<string, number>; }

  /**
   * 前缀搜索。🔴 用**范围查询**而不是 `LIKE ?||'%'`：
   * 后者在 `word_norm` 上能用索引，但通配符要在应用层挡
   * （`PLAYBOOK` 九：加 SQL 的 `ESCAPE` 会从索引搜索退化成全表扫 114 万行）。
   * 范围查询 `>= p AND < p+￿` 天然不认通配符，连挡都不用挡。
   */
  search(prefix: string, limit = 30): KoreanSearchItem[] {
    const p = normKo(prefix.trim());
    if (!p) return [];
    const rows = this.q.search.all(p, `${p}￿`, Math.max(1, Math.min(limit, 100)));
    return rows as unknown as KoreanSearchItem[];
  }

  getEntry(word: string): KoreanEntry | null {
    const w = normKo(word.trim());
    const hit = this.q.exact.get(w) as { id: number; word: string; is_lemma: number } | undefined;
    if (!hit) return null;
    const id = hit.id;

    const entries = this.q.entries.all(id) as unknown as KoreanEntryView[];
    const senses = this.q.senses.all(id) as unknown as
      (KoreanSense & { zhSrc: string | null })[];

    // 关系分到义项级 / 词级
    const relRows = this.q.relations.all(id) as unknown as
      (KoreanRelation & { senseId: number | null })[];
    const bySense = new Map<number, KoreanRelation[]>();
    const wordLevel: KoreanRelation[] = [];
    for (const r of relRows) {
      const item: KoreanRelation = {
        kind: r.kind, target: r.target,
        targetNorm: r.targetNorm ?? null, zh: r.zh ?? null,
      };
      if (r.senseId == null) wordLevel.push(item);
      else {
        const a = bySense.get(r.senseId) ?? [];
        a.push(item);
        bySense.set(r.senseId, a);
      }
    }

    const senseViews: KoreanSense[] = senses.map((s) => ({
      id: s.id,
      etymNo: s.etymNo ?? null,
      pos: s.pos ?? null,
      zh: s.zh ?? null,
      en: s.en ?? null,
      ko: s.ko ?? null,
      // 🔴 判据按**来源前缀**写，不按"有没有中文"：阶段 4a 白送的和阶段 5 模型译的
      //    都是 `lang='zh'`，只有 `src` 分得开（验收要能分，读者不必看见）。
      zhFromModel: (s.zhSrc ?? '').startsWith('model:'),
      relations: groupRelations(bySense.get(s.id) ?? []),
    }));

    // 活用表：**按语法位置归并**，不截断（文件头④）
    const inflRows = this.q.inflections.all(hit.word) as unknown as
      { label: string; form: string; src: string }[];
    // 🔴 `generated` ＝ 这一行的形式**全部**来自规则生成。
    //    两个布尔分开记，别想用一个变量边走边判 —— 我第一版就是那么写的，
    //    绕且错（顺序一换结论就变）。`[[criteria-from-meaning-not-form]]`：
    //    判据写"目的"（这一格是不是我们算出来的），不写"怎么凑出这个目的"。
    const byLabel = new Map<string, { forms: Set<string>; rule: boolean; src: boolean }>();
    for (const r of inflRows) {
      const cur = byLabel.get(r.label)
        ?? { forms: new Set<string>(), rule: false, src: false };
      cur.forms.add(r.form);
      if (r.src === 'rule') cur.rule = true;
      else cur.src = true;
      byLabel.set(r.label, cur);
    }
    const inflections: KoreanInflectionRow[] = [...byLabel.entries()].map(
      ([label, v]) => ({ label, forms: [...v.forms], generated: v.rule && !v.src }));

    // 它是变形形时指回的原形（同一个原形可能有多个语法位置）
    const baseRows = this.q.baseOf.all(id) as unknown as
      { base: string; label: string; ok: number }[];
    const byBase = new Map<string, { labels: string[]; ok: boolean }>();
    for (const r of baseRows) {
      const cur = byBase.get(r.base) ?? { labels: [], ok: !!r.ok };
      if (!cur.labels.includes(r.label)) cur.labels.push(r.label);
      byBase.set(r.base, cur);
    }

    return {
      lang: 'ko',
      id,
      word: hit.word,
      isLemma: !!hit.is_lemma,
      roman: entries.find((e) => e.roman)?.roman ?? null,
      entries,
      // ⚠️ SQLite 的布尔是 0/1，端出去之前转 boolean。
      //    类型写 `Omit<…,'endorsed'> & {endorsed:number}`，不写交叉类型 ——
      //    后者会把 `boolean & number` 归约成 `never`，而报错信息看着像是别的问题。
      pronunciations: (this.q.pronunciations.all(id) as unknown as
        (Omit<KoreanPronunciation, 'endorsed'> & { endorsed: number })[])
        .map((p) => ({ ...p, endorsed: !!p.endorsed })),
      senses: senseViews,
      relations: groupRelations(wordLevel),
      examples: this.q.examples.all(hit.word) as unknown as KoreanExample[],
      inflections,
      baseOf: [...byBase.entries()].map(([base, v]) => ({ base, ...v })),
      hanjaReadings: this.q.hanjaReadings.all(id) as unknown as
        { hanja: string; eumhun: string | null; glossEn: string | null }[],
      etymology: this.q.etymology.all(id) as unknown as
        { edition: string; etymNo: string | null; text: string }[],
      audio: this.q.audio.all(hit.word) as unknown as
        { file: string; url: string | null; kind: string; region: string | null }[],
    };
  }

  close() { this.db.close(); }
}

/**
 * 按 kind 分组。🔴 **不截断** —— ko 的关系怪物是 `析`（1,279 条）。
 * 截不截是展示层的事：服务层截了，页面就永远不知道自己漏了什么
 * （`docs/DISPLAY_EXTREMES.md` §2.1）。
 */
function groupRelations(items: KoreanRelation[]): KoreanRelationGroup[] {
  const m = new Map<string, KoreanRelation[]>();
  for (const it of items) {
    const a = m.get(it.kind) ?? [];
    a.push(it);
    m.set(it.kind, a);
  }
  return [...m.entries()].map(([kind, list]) => ({ kind, items: list }));
}
