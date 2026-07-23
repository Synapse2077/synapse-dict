"""冲突分档器（纯确定性、0 模型）：把各语种 conflict_review.tsv 分成
  ① IPA 记法噪声（保守剥离纯记法符号后两侧相等）——kaikki 保留，无需裁决
  ② IPA 真残差（剥离后仍不等）——待 seed-2.1-pro 裁
  ③ 非 IPA 词法冲突（gender/aux/plural/genitive/…）——按字段分组，待裁
只读 conflict_review.tsv，产出统计 + <lang>/conflict_residual.tsv（②③ 合并，供裁决阶段消费）。

保守原则：只剥「无争议的记法符号」（重音/音节点/连接弧/tie/非音节符/括号/空格），
**不剥音长 ː、不动任何字母/音位符号**——宁可把真记法差异误留残差（多裁几个），也不把真音位差异误判噪声。

用法：python3 scripts/bucket_conflicts.py            # 分档所有语种
      python3 scripts/bucket_conflicts.py it de      # 指定语种
"""
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANGS = ["it", "pt", "de", "fr", "es"]
IPA_FIELDS = {"ipa", "ipa_br", "ipa_pt"}

# 纯记法符号（剥掉不改音位）：主/次重音、音节点、连接弧(U+0361/035C)、非音节符(U+032F)、
# 联诵/连接线(‿ U+203F、‿ liaison)、方/斜/尖括号、花括号、空格、制表。
_STRIP = str.maketrans("", "", "ˈˌ.‿̯͜͡ []/()「」{}　 \t")


def norm_ipa(s: str) -> str:
    """保守归一：取括号内内容 + 剥纯记法符号。不碰音长 ː、鼻化 ̃、字母。"""
    if not s:
        return ""
    s = s.strip()
    # 取第一个 /…/ 或 […] 内内容；无括号则原串
    m = re.search(r"[/\[]([^/\]]*)[/\]]", s)
    inner = m.group(1) if m else s
    return inner.translate(_STRIP)


def bucket_lang(lang: str):
    src = ROOT / lang / "conflict_review.tsv"
    if not src.exists():
        print(f"[{lang}] 无 conflict_review.tsv，跳过")
        return None
    noise = 0
    ipa_residual = []      # (word, field, kaikki, doubao)
    lex_residual = []      # 非 IPA
    field_ct = Counter()
    with open(src, encoding="utf-8") as f:
        header = f.readline()
        for ln in f:
            parts = ln.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            word, field, kk, db = parts[0], parts[1], parts[2], parts[3]
            field_ct[field] += 1
            if field in IPA_FIELDS:
                if norm_ipa(kk) == norm_ipa(db):
                    noise += 1
                else:
                    ipa_residual.append((word, field, kk, db))
            else:
                lex_residual.append((word, field, kk, db))
    total = sum(field_ct.values())
    # 写残差文件
    out = ROOT / lang / "conflict_residual.tsv"
    with open(out, "w", encoding="utf-8") as fo:
        fo.write("word\tfield\tkaikki\tdoubao\tbucket\n")
        for w, fl, kk, db in ipa_residual:
            fo.write(f"{w}\t{fl}\t{kk}\t{db}\tipa_residual\n")
        for w, fl, kk, db in lex_residual:
            fo.write(f"{w}\t{fl}\t{kk}\t{db}\tlex\n")
    lex_by_field = Counter(fl for _, fl, _, _ in lex_residual)
    print(f"\n[{lang}] 总冲突 {total}")
    print(f"  ① IPA 记法噪声（归一后相等，保留 kaikki 不裁）：{noise}")
    print(f"  ② IPA 真残差（待裁）：{len(ipa_residual)}")
    print(f"  ③ 非 IPA 词法（待裁）：{len(lex_residual)}  {dict(lex_by_field.most_common())}")
    print(f"  → 残差合计 {len(ipa_residual)+len(lex_residual)} 写入 {out.name}")
    return total, noise, len(ipa_residual), len(lex_residual)


def main(langs):
    tot = tn = ti = tl = 0
    for lang in langs:
        r = bucket_lang(lang)
        if r:
            tot += r[0]; tn += r[1]; ti += r[2]; tl += r[3]
    print("\n" + "=" * 50)
    print(f"合计：总冲突 {tot} | IPA 噪声(消) {tn} | IPA 残差 {ti} | 词法残差 {tl}")
    print(f"待裁总残差 {ti+tl}（占 {100*(ti+tl)//max(tot,1)}%），IPA 噪声消掉 {100*tn//max(tot,1)}%")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a in LANGS]
    main(args or LANGS)
