#!/usr/bin/env python3
"""B35：十门例句里的 wikitext 模板残渣 —— 逐条裁决后的修复脚本。2026-11-23。

═══ 裁决口径 ═══
只处理**读者可见**（`hidden=0`）且**能唯一判定**的行：
  · `set`  —— 去掉模板外壳/未展开的标记，**保留参数里的引文**（不是改字，是展开模板）；
  · `hide` —— 只剩模板头、或 LaTeX 被截断到无法恢复 ⇒ `hidden=1` + `hidden_why`。
**不当残渣的 7 条留原样**（写在本文件末尾 `EXEMPT`，全库扫描闸按 id 白名单放行）：
  en 1056801（Tcl 代码示例）、1308705（HTML 示例）、1400383（数学式）、1411240（玩笑文本）；
  fr 1873069（在讲 MediaWiki 模板本身的句子）、1878891（原文打码的脏话）；
  de 28189（希腊语注音 `λεπτό{ν}`）。
ko 2 条与 ru 7 条**已 hidden=1**（`hidden_why` 已写），不再动。

每条写前逐字核对旧值，不符即拒绝写库（`fr/fixes/fix_example_template_residue.py` 同一条）。

用法（仓库根）：
    python3 scripts/fix_example_template_residue.py --lang en            # 只核对 + 打样
    python3 scripts/fix_example_template_residue.py --lang en --apply    # 落库
    for L in en it fr pt de ja vi; do python3 scripts/fix_example_template_residue.py --lang $L --apply; done
"""
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FIXES = {
  'en': {
    768957: ('set', '{{ux|en|Kilroy was here.', 'Kilroy was here.'),
    879611: ('set', '{{|en|to be without fellow}}', 'to be without fellow'),
    1134902: ('hide', '{{quote-book|en|year=2016|author=Jonathan M. Kane|title=Writing Proofs in Analysis|pageurl=https://books.google.com.au/books?id=Hm1BDAAAQBAJ&pg=PA74&dq=%22accumulation+point%22%7C%22accumulation+points%22&hl=en&sa=X&ved=2ahUKEwjXmIa0qoPrAhVWWysKHSMKDhAQ6AEwAnoECAYQAg#v=onepage&q=%22accumulation%20point%22%7C%22accumulation%20points%22&f=false|page=74|publisher=Springer', None),
    1145803: ('set', '{{quote-book|en|year=1836|author=Charles Macfarlane|title=The Book of Table Talk|passage=the collection of newspapers and tracts of the period, which belonged to George III , and in a few instances are postillated by his own hand}', 'the collection of newspapers and tracts of the period, which belonged to George III , and in a few instances are postillated by his own hand'),
    1197311: ('set', 'Bituminiferous and cupriferous {{long sand}}', 'Bituminiferous and cupriferous long sand'),
    1419986: ('set', '{{...} areas of weak but steady glow at the surface, bright enough in aggregate to register from orbit. The most famous of these surface events are "milky seas." Sailors have described them for centuries: nights when the ocean appears to shine with a pale, uniform radiance, sometimes as far as the horizon in all directions. Unlike the spark-like bursts produced by disturbed dinoflagellates in a ship\'s wake, a milky sea is a continuous sheen. The ship does not cut through a dark surface and leave a glowing trail; instead it moves through a luminous field. […] A sailor\'s report may be vivid, but it is also subjective, and milky seas are rare enough that few scientists ever encountered one directly. […] From space, a milky sea becomes a measurable patch, potentially hundreds of kilometers across. […]', 'areas of weak but steady glow at the surface, bright enough in aggregate to register from orbit. The most famous of these surface events are "milky seas." Sailors have described them for centuries: nights when the ocean appears to shine with a pale, uniform radiance, sometimes as far as the horizon in all directions. Unlike the spark-like bursts produced by disturbed dinoflagellates in a ship\'s wake, a milky sea is a continuous sheen. The ship does not cut through a dark surface and leave a glowing trail; instead it moves through a luminous field. […] A sailor\'s report may be vivid, but it is also subjective, and milky seas are rare enough that few scientists ever encountered one directly. […] From space, a milky sea becomes a measurable patch, potentially hundreds of kilometers across. […]'),
    1475979: ('set', "[p.s. tony-- while your posts are entertaining, followups to every posting in a thread that's basically noise doesn't make a favorable impression. keep it up and i shall hound you to the ends of the earth with my vile invective and unwarranted advice {does that sound netcoppy enough? no, really. i mena, i try, you know? but it's not easy assuming ruling status when one is at heart an anarchist.}]", "[p.s. tony-- while your posts are entertaining, followups to every posting in a thread that's basically noise doesn't make a favorable impression. keep it up and i shall hound you to the ends of the earth with my vile invective and unwarranted advice {does that sound netcoppy enough? no, really. i mena, i try, you know? but it's not easy assuming ruling status when one is at heart an anarchist."),
    1477305: ('set', '{{|author= Steve Szigethy|passage=One suburban design flaw discussed far less often than the cul-de-sac or the strip mall is the “backage” road – a road that provides vehicular access to the rear of properties that otherwise have “frontage” along an arterial road. The backage road optimizes vehicular operations on the arterial by limiting access and reducing turning movements. This improves the arterial’s capacity and, some say, its safety. Indeed, this arrangement is much safer than 1950s-era arterials, where a constant barrage of driveway openings create turning conflicts for people driving, walking and cycling.}}', 'One suburban design flaw discussed far less often than the cul-de-sac or the strip mall is the “backage” road – a road that provides vehicular access to the rear of properties that otherwise have “frontage” along an arterial road. The backage road optimizes vehicular operations on the arterial by limiting access and reducing turning movements. This improves the arterial’s capacity and, some say, its safety. Indeed, this arrangement is much safer than 1950s-era arterials, where a constant barrage of driveway openings create turning conflicts for people driving, walking and cycling.'),
  },
  'it': {
    53150: ('set', 'ha un trattore molto moderni}}', 'ha un trattore molto moderni'),
  },
  'fr': {
    1610814: ('set', '{{exemple|La bonne compagnie, ensemble des personnes distinguées par leur éducation, leur politesse, leur bon ton.', 'La bonne compagnie, ensemble des personnes distinguées par leur éducation, leur politesse, leur bon ton.'),
    1675219: ('set', "{{exemple|lang=fr|La crise elle-même et les questions qu'elle soulève en moi seront la matière des derniers fragments d'une étude que je débarrasserai du parasitisme des souvenirs insignifiants.|source=Paul Bourget, Le Disciple, 1889", "La crise elle-même et les questions qu'elle soulève en moi seront la matière des derniers fragments d'une étude que je débarrasserai du parasitisme des souvenirs insignifiants."),
    1711229: ('set', '{{exemple|lang=fr|Donner la tonsure.', 'Donner la tonsure.'),
    1841713: ('set', "À Choisey, dans le Jura, un habitat est aménagé entre le VIIᵉ et le Xᵉ siècle à proximité d'une nécropole des VIᵉ-VII{{}} siècles, elle-même installée à l’emplacement d’une villa gallo-romaine.", "À Choisey, dans le Jura, un habitat est aménagé entre le VIIᵉ et le Xᵉ siècle à proximité d'une nécropole des VIᵉ-VII siècles, elle-même installée à l’emplacement d’une villa gallo-romaine."),
    1846529: ('hide', '{{exemple |lang=fr', None),
    1926281: ('set', "« Les pistes cyclables c'est mal ça reporte le danger aux intersections »{{référence nécessaire}}", "« Les pistes cyclables c'est mal ça reporte le danger aux intersections »"),
    1989887: ('hide', '{{exemple | lang=fr', None),
    2040106: ('set', '{{exemple |Thierry Baubet est professeur de psychiatrie d’enfants et d’adolescents à l’hôpital Avicenne (AP-HP) à Bobigny et responsable de la CUMP 93, il nous explique comment les praticiens interviennent dans ce type de situations. |source=Gurvan Kristanadjaja, « Attaque dans un lycée de Nantes : “Dans ces cas, nous essayons de sortir les personnes les plus exposées de l’état de choc” », dans Libération, 2025-04-25 https://www.liberation.fr/societe/education/attaque-dans-un-lycee-de-nantes-dans-ces-cas-nous-essayons-de-sortir-les-personnes-les-plus-exposees-de-letat-de-choc-20250425_WAYG3AQJL5D6VEZ3XTZDV25THA/ texte intégral. Consulté le 2025-04-28', 'Thierry Baubet est professeur de psychiatrie d’enfants et d’adolescents à l’hôpital Avicenne (AP-HP) à Bobigny et responsable de la CUMP 93, il nous explique comment les praticiens interviennent dans ce type de situations.'),
    2095285: ('hide', '{{exemple|lang=fr', None),
    2138247: ('hide', 'Nous supposerons par la suite un équilibre entre une phase vapeur et une phase liquide, en introduisant les fractions molaires respectives { displaystyle x_i^{{g', None),
    2138260: ('hide', 'La pression de vapeur saturante de l’eau p_{{sat', None),
    2213601: ('set', '{[eg}} Je comprends que tu sois vénère. - Καταλαβαίνω ότι είσαι τσατισμένος.', 'Je comprends que tu sois vénère. - Καταλαβαίνω ότι είσαι τσατισμένος.'),
    2213734: ('set', "[…]; on monte ce châssis à l’aide d’un treuil disposé à cet effet, et on le fait passer dans l'appareil. (D. de Prat, Nouveau manuel complet de filature; 1ère partie: Fibres animales & minérales, Encyclopédie Roret, 1914}}", "[…]; on monte ce châssis à l’aide d’un treuil disposé à cet effet, et on le fait passer dans l'appareil. (D. de Prat, Nouveau manuel complet de filature; 1ère partie: Fibres animales & minérales, Encyclopédie Roret, 1914"),
    2214231: ('set', '{πχ}} ultrafin', 'ultrafin'),
    2214294: ('set', '※ Mais, après avoir fait récompenser l’abandon de cette fantaisie par un petit service de thé complet en vieux Sèvres, pâte tendre, elle garda son désir au fond de son cœur, écrit comme sur un agenda. (Ονορέ ντε Μπαλζάκ, La Cousine Bette, 1846}}', '※ Mais, après avoir fait récompenser l’abandon de cette fantaisie par un petit service de thé complet en vieux Sèvres, pâte tendre, elle garda son désir au fond de son cœur, écrit comme sur un agenda. (Ονορέ ντε Μπαλζάκ, La Cousine Bette, 1846'),
  },
  'pt': {
    3081: ('set', '{{etm|la|en}} gerará latim mais a categoria Categoria:Entrada de étimo latino (Inglês).', 'gerará latim mais a categoria Categoria:Entrada de étimo latino (Inglês).'),
    19613: ('set', 'patacão de ouro (Machado de Assis, Histórias sem Data, p. 133}}', 'patacão de ouro (Machado de Assis, Histórias sem Data, p. 133'),
    31687: ('set', '{{quote-journal|pt|date=17-12-1913|title=Echos|location=w:Rio de Janeiro|journal=O Imparcial|volume=II|issue=378|page=2|pageurl=http://memoria.bn.gov.br/DocReader/107670_01/4906|text=Tão pouco o sr. Wencesláo Braz promettera a quem quer que fosse trazer […] para o agape do Casino esse prato exquisito e tão apreciado pelos gourmets intellectuaes de outros paizes, mas na politica indigena esdruxulo, insolito, obsoleto e... indigesto.|t=Although Mr. Wencesláo Braz promised to whomever it was to bring […] , to the Casino’s agape, this exquisite dish [dindonneau au perles de Perigord highly appreciated by the intellectual gourmets of other countries, in Indigenous politics [he is] bizarre, errant, obsolete and... indigestible.]', 'Tão pouco o sr. Wencesláo Braz promettera a quem quer que fosse trazer […] para o agape do Casino esse prato exquisito e tão apreciado pelos gourmets intellectuaes de outros paizes, mas na politica indigena esdruxulo, insolito, obsoleto e... indigesto.'),
  },
  'de': {
    303490: ('set', '„‚[…] Bauern, Stadtmilizen und einfache Männer haben die viel besser bewaffneten französischen Ritter [bei der Golden Sporen Schlacht {sic!}] geschlagen, und das, weil sie beseelt waren vom Drang nach Recht und Freiheit.‘“', '„‚[…] Bauern, Stadtmilizen und einfache Männer haben die viel besser bewaffneten französischen Ritter [bei der Golden Sporen Schlacht sic!] geschlagen, und das, weil sie beseelt waren vom Drang nach Recht und Freiheit.‘“'),
  },
  'ja': {
    125149: ('set', "こ%けつ に いらずんば こ%じ を えずYou cannot catch a tiger cub without entering a tiger's lair → nothing ventured, nothing gained}}", "こ%けつ に いらずんば こ%じ を えずYou cannot catch a tiger cub without entering a tiger's lair → nothing ventured, nothing gained"),
  },
  # 🔴 vi 的 10 条**不在这个脚本里**：vi 页面读 `example.text_pub`（出版层），
  #    这 10 条的 `text_pub` 本来就干净 —— 读者从来没看到过模板残渣；
  #    而 `text` 是证据层，外锚闸逐字锚 dump（W22）。改它会把闸弄红，也已违反
  #    `[[source-typo-fix-ours-not-quote]]`。误改后已用
  #    `vi/fixes/rollback_b35_example_text.py` 还原 10 行。
}

EXEMPT = {
    # (门, id) —— 含 `{{`／`}}` 但是**正当内容**，不是残渣
    ('en', 1056801),  # Tcl 代码示例：`[foreach x [array names y] {...}]`
    ('en', 1308705),  # HTML 示例：`<h2>{{ post.title|title }}</h2>`
    ('en', 1400383),  # 数学式：`FareySieve[{(2^#-1)^2-2&}]`
    ('en', 1411240),  # 玩笑文本里的 ASCII 花括号
    ('fr', 1873069),  # 正文在讲 MediaWiki 模板 `{{TALKPAGENAME}}`
    ('fr', 1878891),  # 原文打码的脏话 `@#}]`
    ('de', 28189),    # 希腊语注音 `λεπτό{ν}`
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--lang', required=True)
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    L = a.lang
    if L not in FIXES:
        raise SystemExit(f'🔴 没有 {L} 的修复计划；有：{sorted(FIXES)}')
    sys.path.insert(0, str(ROOT / L))
    import dbtool  # noqa: E402

    fixes = FIXES[L]
    c = sqlite3.connect(f'file:{dbtool.DB}?mode=ro', uri=True)
    try:
        # en/it/fr/pt/de/ja 的 `example` **没有 `hidden_why` 列**（ko/ru 有）。
        # 第一版无条件写它 ⇒ en/fr 的 hide 分支 SQL 报错、整个事务回滚，
        # 两门一条都没写进去（而且 `tail` 把错误吞了，看起来像成功）。
        has_why = 'hidden_why' in [r[1] for r in c.execute('PRAGMA table_info(example)')]
        for i, (act, old, new) in fixes.items():
            got = c.execute('SELECT text FROM example WHERE id=?', (i,)).fetchone()
            if not got or got[0] != old:
                raise SystemExit(f'🔴 {L} id={i} 当前值不是预期的旧值，拒绝写库：{got!r}'
                                 f'\n   预期：{old!r}')
        print(f'{L}: {len(fixes)} 条待处理')
        for i, (act, old, new) in sorted(fixes.items()):
            print(f'  {i} [{act}] {old[:50]!r} → {(new[:50] + "…") if new else "（隐藏）"!r}')
    finally:
        c.close()
    if not a.apply:
        print('(dry：核对通过，未写库)')
        return
    n_hide = sum(1 for act, _, _ in fixes.values() if act == 'hide')
    with dbtool.session(f'b35-{L}-example-template-residue', small=len(fixes)) as s:
        for i, (act, old, new) in fixes.items():
            if act == 'set':
                s.execute('UPDATE example SET text=? WHERE id=? AND text=?', (new, i, old))
        for i, (act, old, _) in fixes.items():
            if act == 'hide':
                if has_why:
                    s.execute("UPDATE example SET hidden=1, hidden_why='模板残渣（B35）' "
                              'WHERE id=? AND text=?', (i, old))
                else:
                    # 没有 hidden_why 列的门：隐藏原因记在本文件与 B35 账上。
                    s.execute('UPDATE example SET hidden=1 WHERE id=? AND text=?', (i, old))
    print(f'✓ {L} 已处理 {len(fixes)} 行（隐藏 {n_hide}）')


if __name__ == '__main__':
    main()
