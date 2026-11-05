"""`sense_relation` 的写入方登记表（K14，2026-11-03）。

═══ 为什么要有这一列 ═══
`sense_relation.src` 存的是**哪一版 dump**（`ko-edition`/`en-edition`…），而往这张表写行的脚本有 8 个，
填的是同一批版名 ⇒ 「例句标签那一支收了多少条边」在库里问不出来，只能靠 `src_ref` 的**形状**碰巧不同去猜
（`#` 有没有、`#k33` 结尾）—— 那是巧合不是设计，谁改一下格式就分不开了，而且不会有任何东西报错。
⇒ `sense_relation.writer` 存**写这一行的脚本名**，取值只许是下面登记过的。回归闸 R29 盯着。

🔴 新增写入方：先在这里登记一行，再在 INSERT 里写 `writer`（`WRITER = relation_writers.name(__file__)`）。
   没登记就跑 ⇒ `name()` 当场停机；登记了而 INSERT 没写这一列 ⇒ R29 红（`writer` 为空）。
"""
from pathlib import Path

# 写入方（脚本文件名去掉 .py）→ 它写的是什么
WRITERS = {
    "build_relation_layer": "阶段 2d 建关系层（各版 dump 的关系字段＋指针义项）",
    "fix_meta_gloss": "元描述迁出出版层时，多候选汉字表记进 `hanja_spelling`",
    "harvest_relations_from_examples": "阶段 6b 从例句标签里再收一轮关系",
    "topup_relations_new_words": "后补收词之后，用建库那份抽取器给新词补边",
    "backfill_alt_hanja": "英文版 forms 里的异体汉字表记",
    "intake_word_formation": "K11 构词公式（`A + B`）迁成关系边",
    "intake_idiom_components": "K15 谚语词条的成分拆解迁成关系边",
    "reclass_nonexamples": "K33 「例句」层里的词表/关系指针迁成关系边",
}


def name(file):
    """→ 调用方脚本的写入方名；没登记就停机。用法：`WRITER = relation_writers.name(__file__)`。"""
    stem = Path(file).stem
    if stem not in WRITERS:
        raise SystemExit("🔴 `%s` 没在 `relation_writers.WRITERS` 登记，不许往 sense_relation 写" % stem)
    return stem
