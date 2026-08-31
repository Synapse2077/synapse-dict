// ============================================================================
// 葡萄牙语词典服务 —— 葡语专属，自包含，**不引用其它语种**（不复用 es/it/fr 服务）。
//
// 2026-08-30 阶段 8：从**老扁平版重写为 v3 多表版**。
//
// 🔴 为什么必须重写：`[[it-display-layer-stage8]]` 与 fr 2026-08-29 的复发 ——
//    数据层全绿、库里查得到，而 `french.ts` 里 `FROM audio` 出现 **0 次**
//    ⇒ 39 万条录音一个用户都看不见。**「落库成功」证明不了「到达用户」。**
//    pt 重写前的状态更彻底：287 行只读 `dict` 的扁平列，
//    v3 的 sense / sense_gloss / pronunciation / inflection / example /
//    sense_relation / audio **一张都没接** —— 阶段 0–6 做的东西用户一个字看不到。
//
// ══════ 三条 pt 独有、别的语种没有的约束 ══════
//
// ① **双读音是葡语的灵魂**：`pronunciation.region` 分 pt-BR / pt-PT / NULL(通用)。
//    读者看到 `novos ˈnɔ.vus / ˈnɔ.vuʃ` 时必须知道哪个是哪个 ——
//    元音变换让同一个词的巴葡欧葡差别不只是口音（`novo ˈno.vu → novos ˈnɔ.vus`）。
//
// ② 🔴 **查变形必须走 `inflection.word_id`，不能走 `entry`**（收尾单 C11）：
//    只在 `forms` 里出现过的词形，阶段 3 只给它建了 `dict` 行**没建 `entry` 行**，
//    实测 **132,660 条** `inflection.entry_id` 为空。走 entry 会把它们全查不出来。
//
// ③ **变形标签要去重**（收尾单 C8）：阶段 2b 把同一个变形关系按词性各存了一份
//    （`tôdas → tôda 复数` 存了 5 条：det/adj/adv/noun/noun），照渲染会把「复数」印五遍。
//
// ⚠️ 隐藏行一律不出现在读者面前：`sense.hidden=1`（变位指针 1,746 条）、
//    `example.hidden=1`。数据没删，只是不展示。
//
// IPA 全语种**存裸**，斜杠由展示层统一加（`[[ipa-bare-storage-convention]]`）。
// ============================================================================

import { DatabaseSync } from 'node:sqlite';
import { ptPartsOf } from '@synapse-dict/dict-labels';

export type PortugueseSearchItem = {
  id: number;
  word: string;
  brief: string | null;
  pos: string | null;
};

export type PortugueseSense = {
  id: number;
  zh: string | null;        // 中文释义
  pt: string | null;        // 葡语原文定义（阶段 1.5a 收回来的）
  en: string | null;        // 英文对应词（七月建库层）
  pos: string | null;       // 逐义项词性（实测 27.9% 的多义词逐义项不同）
  gender: string | null;    // 逐义项性别（rádio m 收音机 / f 镭）
  regions: string[];        // 地区 ← sense_tag kind=region（含安哥拉/莫桑比克等非洲变体）
  registers: string[];      // 语域 ← kind=register
  topics: string[];         // 领域 ← kind=topic（fr 那轮漏收过一整族，这里一开始就接）
  // 🔴 **逐义项的语义关系**（2026-08-31 接）。库里 153,452 条关系有 71,017 条
  //    带 `sense_id`，而旧版的 `rel` 查询是 `WHERE word_id = ?` —— **把义项归属整个丢掉**，
  //    多义词上所有义项的近义词拍平成一个列表：
  //        pinta（8 个义项）→ aspecto · cara · nevo（痣）… buceta（粗俗义，48+62 条）
  //    读者查「痣」看到的是一百多个别的义项的近义词。
  //    ⇒ 有 `sense_id` 的挂到义项上，`sense_id IS NULL` 的留在词条级（见 `relations`）。
  relations: PortugueseRelationGroup[];
  // 这条义项自己的异体指针（`banco` 的第 6 条义项 → `banco de dados`）。
  // 义项的中文往往已经写着「X 的截短形式」，这里的价值是**让 X 可点、并带上它的中文**。
  altOf: PortugueseAltOf[];
};

export type PortugueseCollocation = { text: string; zh: string | null };

// 一条读音。**双读音是 pt 的一等公民**，`region` 不是装饰。
export type PortugueseReading = {
  ipa: string;
  notation: string | null;   // phonemic（音位式）/ narrow（音值式）
  region: string | null;     // pt-BR / pt-PT / null=通用（两支相同）
  pos: string | null;        // 同形异读靠它分（`pronunciation.pos`，一开始就带的列）
  src: string | null;
};

export type PortugueseExample = {
  senseId: number | null;
  text: string;
  zh: string | null;
  en: string | null;
  ref: string | null;
  bold: Array<[number, number]>;
};

export type PortugueseInflection = {
  base: string;
  label: string | null;
  clickable: boolean;
};

export type PortugueseAltOf = { target: string; zh: string | null; clickable: boolean };
export type PortugueseForm = { form: string; label: string | null };

export type PortugueseRelationTarget = { word: string; clickable: boolean };
export type PortugueseRelationGroup = {
  kind: string; total: number; targets: PortugueseRelationTarget[];
};
const PT_REL_ORDER = ['synonym', 'antonym', 'hypernym', 'hyponym',
                      'coordinate', 'holonym', 'meronym'];
const PT_REL_CAP = 12;

// ⭐ 词条级与义项级**共用这一份**分组/排序/截断（`[[fix-regression-and-gate]]`：
//    判据只许一份 —— 两处各写一版，迟早排序或上限对不上）。
function groupRelations(
  m: Map<string, PortugueseRelationTarget[]>,
): PortugueseRelationGroup[] {
  return PT_REL_ORDER.filter((k) => m.has(k)).map((k) => ({
    kind: k, total: m.get(k)!.length, targets: m.get(k)!.slice(0, PT_REL_CAP),
  }));
}

// 一条真人录音（Commons URL，不下载字节）。`region` 与读音同一套取值。
export type PortugueseAudio = {
  url: string;
  region: string | null;
  regionSrc: string | null;   // tag / filename / speaker —— 说得出这个地区哪来的
  speaker: string | null;
};

export type PortugueseBase = {
  word: string;
  pos: string | null;
  ipaBr: string | null;
  ipaPt: string | null;
  gender: string | null;
  senses: PortugueseSense[];
};

export type PortugueseEntry = {
  lang: 'pt';
  id: number;
  word: string;
  ipaBr: string | null;         // 巴西标准音（readings 里 pt-BR 或通用的第一条）
  ipaPt: string | null;         // 欧洲标准音
  pos: string | null;
  isLemma: boolean;
  // —— 葡语本质（一等字段；无 aux）——
  vconj: string | null;
  transitivity: string | null;
  pronominal: boolean;
  pp: string | null;
  ppShort: string | null;
  gender: string | null;
  plural: string | null;
  feminine: string | null;
  comparative: string | null;
  adjPos: string | null;
  government: string | null;
  level: string | null;
  freqZipf: number | null;      // 阶段 5a 建的客观频次（NULL = 量不了，不是"罕见"）
  // —— v3 各层 ——
  senses: PortugueseSense[];
  readings: PortugueseReading[];
  examples: PortugueseExample[];
  collocations: PortugueseCollocation[];
  inflections: PortugueseInflection[];
  forms: PortugueseForm[];
  relations: PortugueseRelationGroup[];
  altOf: PortugueseAltOf[];
  audio: PortugueseAudio[];
  baseForms: string[];
  bases: PortugueseBase[];
  flag: string | null;
};

// kaikki/维基 IPA → 展示式。存裸，这里只做轻量清理：去连结弧、去音节点。
function normalizePtIpa(ipa: string | null): string | null {
  if (!ipa) return ipa;
  let s = ipa.trim();
  const slash = s.match(/\/[^/]*\//);
  if (slash) s = slash[0];
  else s = s.replace(/\s*\[[^\]]*\]\s*/g, '').trim();
  let inner = s.startsWith('/') && s.endsWith('/') ? s.slice(1, -1) : s;
  inner = inner.replace(/͡/g, '').replace(/\./g, '').trim();
  return inner || null;
}

function parseBold(raw: string | null): Array<[number, number]> {
  if (!raw) return [];
  try {
    const v = JSON.parse(raw);
    if (!Array.isArray(v)) return [];
    return v.filter((p) => Array.isArray(p) && p.length === 2) as Array<[number, number]>;
  } catch {
    return [];
  }
}

export class PortugueseDictService {
  readonly databasePath: string;
  readonly lang = 'pt';
  private readonly db: DatabaseSync;
  private readonly q: Record<string, ReturnType<DatabaseSync['prepare']>>;

  constructor(databasePath: string) {
    this.databasePath = databasePath;
    this.db = new DatabaseSync(databasePath);
    this.db.exec('PRAGMA query_only = ON');

    const HEAD = `id, word, ipa_br, ipa_pt, pos, is_lemma, vconj, transitivity,
                  pronominal, pp, pp_short, gender, plural, feminine, comparative,
                  adj_pos, government, level, freq_zipf, collocation, flag`;

    this.q = {
      stats: this.db.prepare(`
        SELECT (SELECT COUNT(*) FROM dict)                              AS total,
               (SELECT SUM(is_lemma) FROM dict)                         AS lemmas,
               (SELECT COUNT(DISTINCT word_id) FROM sense
                 WHERE COALESCE(hidden,0)=0)                            AS translated,
               (SELECT COUNT(DISTINCT word_id) FROM pronunciation)      AS ipa,
               (SELECT COUNT(DISTINCT word) FROM audio)                 AS audio,
               (SELECT COUNT(*) FROM example WHERE COALESCE(hidden,0)=0) AS examples`),

      head: this.db.prepare(
        `SELECT ${HEAD} FROM dict WHERE word = ? ORDER BY is_lemma DESC LIMIT 1`),
      // 精确大小写优先（阶段 3a 特意把 `Cefalópodos`/`cefalópodos` 拆成两行，
      // 用 NOCASE 会把它们混为一谈）；查不到再退回不区分大小写。
      headCI: this.db.prepare(
        `SELECT ${HEAD} FROM dict WHERE word = ? COLLATE NOCASE
          ORDER BY CASE WHEN word = ? THEN 0 ELSE 1 END, is_lemma DESC LIMIT 1`),

      // 🔴🔴 **中文摘要必须查在 LIMIT 之后。**
      //    第一版把它写成候选行上的相关子查询 —— 实测 **5,891 ms**，
      //    去掉它只剩 **28 ms**（占 99.5%）。
      //    根因是 `[[query-perf-collation-traps]]` 记过的那条：
      //    **相关子查询会从选择性最差那头入手** —— 计划里是
      //    `SEARCH g USING INDEX idx_glosslang (lang=?)`，而 `lang='zh'` 有 **34 万行**；
      //    而且它对**每个候选**都跑一次，不是只对留下的 20 条。
      //    ⇒ 拆成两步：先选出 20 条，再给这 20 条取中文（`briefs`）。
      prefix: this.db.prepare(`
        SELECT d.id, d.word, d.pos, d.is_lemma
          FROM dict d
         WHERE d.word LIKE ? COLLATE NOCASE OR d.word_norm LIKE ? COLLATE NOCASE
         ORDER BY CASE WHEN d.word = ? THEN 0
                       WHEN lower(d.word) = lower(?) THEN 1 ELSE 2 END,
                  d.is_lemma DESC, LENGTH(d.word) ASC, d.word ASC
         LIMIT ?`),

      // 🔴 短前缀走**预计算表**（阶段 9）。1–3 字符的候选有两三万条，
      //    为取 20 条要整个排一遍 —— 而 `ORDER BY` 里的 `LENGTH(word)` 与
      //    `lower(word)=lower(?)` 都不可索引，`OR` 又强制 MULTI-INDEX OR ⇒ **建索引没用**。
      //    ⚠️ **未命中 = 正确回退**：键就是调用方传进来的原串（不做大小写归一，
      //    因为 SQLite 的 `lower()` 不认非 ASCII，而葡语词头大量带重音符）。
      //    查不到就走实时查询，结果一样、只是慢一点。
      cached: this.db.prepare(`
        SELECT d.id, d.word, d.pos, d.is_lemma
          FROM search_prefix p JOIN dict d ON d.id = p.word_id
         WHERE p.prefix = ? ORDER BY p.rank LIMIT ?`),

      // 只对已选出的少数几条取中文摘要。`word_id` 上有索引，逐条命中。
      brief: this.db.prepare(`
        SELECT g.text FROM sense s
          JOIN sense_gloss g ON g.sense_id = s.id AND g.lang = 'zh'
         WHERE s.word_id = ? AND COALESCE(s.hidden,0)=0
         ORDER BY s.rank LIMIT 1`),

      senses: this.db.prepare(`
        SELECT s.id, s.pos, s.gender,
               (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='zh' LIMIT 1) AS zh,
               (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='pt' LIMIT 1) AS pt,
               (SELECT text FROM sense_gloss WHERE sense_id=s.id AND lang='en' LIMIT 1) AS en
          FROM sense s
         WHERE s.word_id = ? AND COALESCE(s.hidden,0)=0
         ORDER BY s.rank`),

      tags: this.db.prepare(
        `SELECT sense_id, kind, value FROM sense_tag WHERE sense_id IN
           (SELECT id FROM sense WHERE word_id = ?)`),

      // 🔴 双读音：按 region 取，`NULL` 表示两支相同（通用）。
      readings: this.db.prepare(`
        SELECT ipa, notation, region, pos, src FROM pronunciation
         WHERE word_id = ?
         ORDER BY CASE notation WHEN 'phonemic' THEN 0 ELSE 1 END,
                  CASE region WHEN 'pt-BR' THEN 0 WHEN 'pt-PT' THEN 1 ELSE 2 END,
                  id`),

      examples: this.db.prepare(`
        SELECT e.sense_id, e.text, e.ref, e.bold,
               (SELECT text FROM example_gloss WHERE example_id=e.id AND lang='zh') AS zh,
               (SELECT text FROM example_gloss WHERE example_id=e.id AND lang='en') AS en
          FROM example e
         WHERE e.word = ? AND COALESCE(e.hidden,0)=0
         ORDER BY CASE WHEN e.sense_id IS NULL THEN 1 ELSE 0 END, e.id
         LIMIT 40`),

      colloc: this.db.prepare(`
        SELECT c.text,
               (SELECT text FROM collocation_gloss WHERE collocation_id=c.id AND lang='zh') AS zh
          FROM collocation c WHERE c.word_id = ? ORDER BY c.rank`),

      // 🔴 C11：走 `inflection.word_id`，**不走 entry**（132,660 条 entry_id 为空）。
      // 🔴 C8：`DISTINCT base,label` —— 阶段 2b 按词性各存了一份，不去重会印五遍。
      inflOf: this.db.prepare(`
        SELECT DISTINCT i.base, i.label_zh,
               (SELECT 1 FROM dict d WHERE d.word = i.base) AS ok
          FROM inflection i WHERE i.word_id = ?
         ORDER BY i.base, i.label_zh`),

      // 词元页反过来看：这个词有哪些形式
      forms: this.db.prepare(`
        SELECT DISTINCT d.word AS form, i.label_zh AS label
          FROM inflection i JOIN dict d ON d.id = i.word_id
         WHERE i.base_id = ? ORDER BY i.label_zh, d.word LIMIT 200`),

      // ⚠️ 只取**没有义项归属**的那 82,435 条。有归属的走 `relBySense`，
      //    否则同一条会在词条级和义项级各印一遍。
      //    实测 71,017 条全部挂在**可见**义项上（挂隐藏义项的 0 条、挂不存在义项的 0 条），
      //    所以这样拆开不会让任何一条从页面上消失。
      rel: this.db.prepare(`
        SELECT kind, target,
               (SELECT 1 FROM dict d WHERE d.word = sense_relation.target) AS ok
          FROM sense_relation
         WHERE word_id = ? AND kind <> 'alt_of' AND sense_id IS NULL
           AND COALESCE(hidden,0) = 0`),

      relBySense: this.db.prepare(`
        SELECT r.sense_id, r.kind, r.target,
               (SELECT 1 FROM dict d WHERE d.word = r.target) AS ok
          FROM sense_relation r
         WHERE r.sense_id IN (SELECT id FROM sense WHERE word_id = ?)
           AND r.kind <> 'alt_of' AND COALESCE(r.hidden,0) = 0`),

      // 🔴🔴 **2026-08-31 拆级。** 旧版是 `WHERE r.word_id = ?` —— 与关系层同一个毛病，
      //    而它更伤：库里 **7,947 条 alt_of 全部挂在义项上**，一律按词条级渲染就是
      //    **把义项级的话升级成词条级的断言**。`banco` 页顶上印出「异体 → banco de dados」，
      //    而 banco 是「银行」，它不是 banco de dados 的异体 —— **这句话本身是错的**。
      //    （是我 08-31 补 altOf 渲染时造出来的：数据一直在，渲染一接就把错话摆到了最上面。）
      //    ⇒ 词条级只留 `sense_id IS NULL` 的那 2,597 条（阶段 2f 给空白页接的，
      //      那些页面上它是唯一内容）；挂义项的走 `altOfBySense`，画进它自己的义项里。
      altOf: this.db.prepare(`
        SELECT r.target,
               (SELECT g.text FROM sense s
                  JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh'
                 WHERE s.word_id = (SELECT id FROM dict WHERE word = r.target)
                   AND COALESCE(s.hidden,0)=0 ORDER BY s.rank LIMIT 1) AS zh,
               (SELECT 1 FROM dict d WHERE d.word = r.target) AS ok
          FROM sense_relation r
         WHERE r.word_id = ? AND r.kind = 'alt_of' AND r.sense_id IS NULL
           AND COALESCE(r.hidden,0) = 0`),

      altOfBySense: this.db.prepare(`
        SELECT r.sense_id, r.target,
               (SELECT g.text FROM sense s
                  JOIN sense_gloss g ON g.sense_id=s.id AND g.lang='zh'
                 WHERE s.word_id = (SELECT id FROM dict WHERE word = r.target)
                   AND COALESCE(s.hidden,0)=0 ORDER BY s.rank LIMIT 1) AS zh,
               (SELECT 1 FROM dict d WHERE d.word = r.target) AS ok
          FROM sense_relation r
         WHERE r.sense_id IN (SELECT id FROM sense WHERE word_id = ?)
           AND r.kind = 'alt_of' AND COALESCE(r.hidden,0) = 0`),

      audio: this.db.prepare(`
        SELECT COALESCE(url_ogg, url_mp3, url_wav, url_other) AS url,
               region, region_src, speaker
          FROM audio WHERE word = ?
         ORDER BY CASE region WHEN 'pt-BR' THEN 0 WHEN 'pt-PT' THEN 1 ELSE 2 END, id
         LIMIT 8`),
    };
  }

  getStats() {
    return this.q.stats.get() as Record<string, number>;
  }

  search(query: string, limit = 20): PortugueseSearchItem[] {
    const kw = query.trim();
    if (!kw) return [];
    const like = `${kw}%`;
    type Row = { id: number; word: string; pos: string | null };
    // 先查预计算表；未命中（长前缀、或大小写变体没算过）回退实时查询。
    let rows = this.q.cached.all(kw, limit) as Row[];
    if (rows.length === 0) rows = this.q.prefix.all(like, like, kw, kw, limit) as Row[];
    return rows.map((r) => ({
      id: r.id, word: r.word, pos: r.pos,
      brief: (this.q.brief.get(r.id) as { text: string } | undefined)?.text ?? null,
    }));
  }

  private sensesOf(wordId: number): PortugueseSense[] {
    const rows = this.q.senses.all(wordId) as Array<{
      id: number; pos: string | null; gender: string | null;
      zh: string | null; pt: string | null; en: string | null;
    }>;
    const tagRows = this.q.tags.all(wordId) as Array<{
      sense_id: number; kind: string; value: string;
    }>;
    const byId = new Map<number, { regions: string[]; registers: string[]; topics: string[] }>();
    for (const t of tagRows) {
      const e = byId.get(t.sense_id)
        ?? { regions: [], registers: [], topics: [] };
      if (t.kind === 'region') e.regions.push(t.value);
      else if (t.kind === 'register') e.registers.push(t.value);
      else if (t.kind === 'topic') e.topics.push(t.value);
      byId.set(t.sense_id, e);
    }
    const relRows = this.q.relBySense.all(wordId) as Array<{
      sense_id: number; kind: string; target: string; ok: number | null;
    }>;
    const relBy = new Map<number, Map<string, PortugueseRelationTarget[]>>();
    for (const r of relRows) {
      const m = relBy.get(r.sense_id) ?? new Map<string, PortugueseRelationTarget[]>();
      const arr = m.get(r.kind) ?? [];
      arr.push({ word: r.target, clickable: !!r.ok });
      m.set(r.kind, arr);
      relBy.set(r.sense_id, m);
    }
    const altRows = this.q.altOfBySense.all(wordId) as Array<{
      sense_id: number; target: string; zh: string | null; ok: number | null;
    }>;
    const altBy = new Map<number, PortugueseAltOf[]>();
    for (const r of altRows) {
      const arr = altBy.get(r.sense_id) ?? [];
      arr.push({ target: r.target, zh: r.zh, clickable: !!r.ok });
      altBy.set(r.sense_id, arr);
    }
    return rows.map((r) => ({
      id: r.id, zh: r.zh, pt: r.pt, en: r.en, pos: r.pos, gender: r.gender,
      ...(byId.get(r.id) ?? { regions: [], registers: [], topics: [] }),
      relations: groupRelations(relBy.get(r.id) ?? new Map()),
      altOf: altBy.get(r.id) ?? [],
    }));
  }

  getEntry(word: string): PortugueseEntry | null {
    const kw = word.trim();
    if (!kw) return null;
    const row = (this.q.head.get(kw) ?? this.q.headCI.get(kw, kw)) as
      Record<string, unknown> | undefined;
    if (!row) return null;
    const id = row.id as number;
    const w = row.word as string;

    const readings = (this.q.readings.all(id) as Array<{
      ipa: string; notation: string | null; region: string | null;
      pos: string | null; src: string | null;
    }>).map((r) => ({ ...r, ipa: normalizePtIpa(r.ipa) ?? r.ipa }));

    // 词头单行展示用：巴葡取 pt-BR 或通用的第一条，欧葡同理。
    const pick = (reg: string) =>
      readings.find((r) => r.region === reg)?.ipa
      ?? readings.find((r) => r.region === null)?.ipa
      ?? null;

    const relRows = this.q.rel.all(id) as Array<{
      kind: string; target: string; ok: number | null;
    }>;
    // 🔴 **按 `(kind, target)` 去重** —— 外审 2026-08-30 逮到 `rotar` 的
    //    `girar`/`rotacionar` 印三遍、`bem → mal` 印七遍，全库 **14,386 组**。
    //    根因：数据层的去重键是 `(word_id, sense_id, kind, target)`，而
    //    **同一个词的不同义项指向同一个近义词**就绕过去了（`bem` 七条义项都说反义是 `mal`）。
    //    ⚠️ **不在数据层删** —— 「这条关系属于哪个义项」是有用的信息；
    //      重复只存在于"把所有义项的关系并成一列展示"这一步，就在这一步去掉。
    const relMap = new Map<string, PortugueseRelationTarget[]>();
    const relSeen = new Set<string>();
    for (const r of relRows) {
      const key = `${r.kind}\u0000${r.target}`;
      if (relSeen.has(key)) continue;
      relSeen.add(key);
      const arr = relMap.get(r.kind) ?? [];
      arr.push({ word: r.target, clickable: !!r.ok });
      relMap.set(r.kind, arr);
    }
    const relations = groupRelations(relMap);

    // 变形标签同样要去重，而且**要吃掉"泛化标签"**：
    // 外审逮到 `podaste` 同时列「陈述式第二人称单数」和「陈述式简单过去时第二人称单数」，
    // `musaranhos pigmeus` 同时列「复数」和「阳性复数」—— 后者包含前者。
    // ⇒ 同一个 base 下，若某标签是另一标签的**子串**，只留更具体的那条。
    const rawInfl = (this.q.inflOf.all(id) as Array<{
      base: string; label_zh: string | null; ok: number | null;
    }>).map((r) => ({ base: r.base, label: r.label_zh, clickable: !!r.ok }));
    // 🔴 第一版判据是「标签 A 是标签 B 的**连续子串**」—— 渲染出来当场打回：
    //    `podaste` 的「陈述式第二人称单数」不是「陈述式简单过去时第二人称单数」的连续子串
    //    （中间插了「简单过去时」）。判据比它要描述的东西**窄**。
    //    ⇒ 按含义写：把标签切成**语法成分**，若 A 的成分是 B 的子集，A 更泛，丢掉 A。
    // 🔴 **选择支按长度降序生成** —— `[[regex-alternation-order]]` 记过三次：
    //    正则选择支是**从左到右 first-match，不是最长匹配**，短的排前面就挡住长的
    //    （`分词` 排在 `过去分词` 前面时，`过去分词阴性单数` 会被切成 `分词`+…）。
    //    ⇒ 不手写顺序，由代码排。
    const inflections = rawInfl.filter((x, _i, all) => !all.some((y) => {
      if (y === x || y.base !== x.base || !x.label || !y.label) return false;
      if (y.label === x.label) return false;
      const px = ptPartsOf(x.label);
      const py = ptPartsOf(y.label);
      if (px.size === 0) return false;
      if (!([...px].every((p) => py.has(p)))) return false;   // x 的成分不全在 y 里 ⇒ 不比
      if (px.size < py.size) return true;                     // x 真子集 ⇒ x 更泛，丢
      // 成分集相等（`分词` vs `过去分词` 归一后都是 {分词}）⇒ 留字面更完整的那条。
      return y.label.length > x.label.length
        || (y.label.length === x.label.length && y.label > x.label);
    }));

    const entry: PortugueseEntry = {
      lang: 'pt', id, word: w,
      ipaBr: pick('pt-BR') ?? normalizePtIpa(row.ipa_br as string | null),
      ipaPt: pick('pt-PT') ?? normalizePtIpa(row.ipa_pt as string | null),
      pos: row.pos as string | null,
      isLemma: row.is_lemma === 1,
      vconj: row.vconj as string | null,
      transitivity: row.transitivity as string | null,
      pronominal: row.pronominal === 1,
      pp: row.pp as string | null,
      ppShort: row.pp_short as string | null,
      gender: row.gender as string | null,
      plural: row.plural as string | null,
      feminine: row.feminine as string | null,
      comparative: row.comparative as string | null,
      adjPos: row.adj_pos as string | null,
      government: row.government as string | null,
      level: row.level as string | null,
      freqZipf: (row.freq_zipf as number | null) ?? null,
      senses: this.sensesOf(id),
      readings,
      examples: (this.q.examples.all(w) as Array<{
        sense_id: number | null; text: string; ref: string | null;
        bold: string | null; zh: string | null; en: string | null;
      }>).map((e) => ({
        senseId: e.sense_id, text: e.text, zh: e.zh, en: e.en, ref: e.ref,
        bold: parseBold(e.bold),
      })),
      collocations: this.q.colloc.all(id) as PortugueseCollocation[],
      inflections,
      forms: this.q.forms.all(id) as PortugueseForm[],
      relations,
      altOf: (this.q.altOf.all(id) as Array<{
        target: string; zh: string | null; ok: number | null;
      }>).map((r) => ({ target: r.target, zh: r.zh, clickable: !!r.ok })),
      audio: (this.q.audio.all(w) as Array<{
        url: string; region: string | null; region_src: string | null;
        speaker: string | null;
      }>).map((a) => ({
        url: a.url, region: a.region, regionSrc: a.region_src, speaker: a.speaker,
      })),
      baseForms: [...new Set(inflections.map((i) => i.base))],
      bases: [],
      flag: row.flag as string | null,
    };

    // 变形页内联展示原形的词义（读者搜 `falávamos` 要看到 `falar` 的意思）
    for (const bw of entry.baseForms.slice(0, 3)) {
      if (bw === entry.word) continue;
      const br = (this.q.head.get(bw) ?? this.q.headCI.get(bw, bw)) as
        Record<string, unknown> | undefined;
      if (!br) continue;
      const bid = br.id as number;
      const brd = this.q.readings.all(bid) as Array<{ ipa: string; region: string | null }>;
      const bpick = (reg: string) =>
        normalizePtIpa(brd.find((r) => r.region === reg)?.ipa
          ?? brd.find((r) => r.region === null)?.ipa ?? null);
      entry.bases.push({
        word: br.word as string, pos: br.pos as string | null,
        ipaBr: bpick('pt-BR') ?? normalizePtIpa(br.ipa_br as string | null),
        ipaPt: bpick('pt-PT') ?? normalizePtIpa(br.ipa_pt as string | null),
        gender: br.gender as string | null,
        senses: this.sensesOf(bid),
      });
    }
    return entry;
  }

  close() {
    this.db.close();
  }
}
