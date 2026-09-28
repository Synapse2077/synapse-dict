#!/usr/bin/env python3
"""ko 写库闸门自身的**变异验证** —— `PLAYBOOK` 7.3：一条永远通过的检查等于没检查。

═══ 为什么这份文件在库还不存在的时候就有 ═══
`PLAYBOOK` 1.4 说闸门不能推后。但"闸门存在"和"闸门拦得住"是两回事 ——
ja 的 TRACK 列了 23 个字段而实际只守住 4 个，整整一个项目没人发现，
**因为从来没有人问过它「你现在拦得住什么」**。
⇒ 这份文件问的就是这个，而且它在**空库**上就能跑（M1/M2 靠的正是空库那条路径）。

跑：`python3 ko/tests/test_dbtool_gate.py`（退出码非零＝有闸没拦住）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dbtool


def check_brief():
    """→ [(编号, 说明), ...]，空列表＝全绿。给 `dbtool` 挂闸用的简报接口。"""
    red = []

    def want(cid, name, cond, detail=""):
        if not cond:
            red.append((cid, "%s %s" % (name, detail)))

    def want_lazy(cid, name, fn, detail=""):
        """条件**延迟求值**，并且求值时抛异常也算红。

        🔴🔴 这个函数是变异验证自己逼出来的（2026-09-20）：
        原来十七条检查全部写成 `want(cid, name, <直接求值的表达式>)`，于是我把
        `_ZH_SRC` 变异成「漏掉繁体片」时，`is_chinese_text` 在**参数求值阶段**
        抛了 `ValueError` —— `check_brief()` 整个崩掉，
        **后面的 M4e / M4f / M5 / M6 一条都没跑**。

        也就是说：一条判据坏掉，闸不是报「1 条红」，而是**丢掉剩下的 70% 覆盖面**，
        且对外表现成「闸自己坏了」而不是「闸逮到东西了」。
        （`[[criteria-narrower-than-you-think]]` 的又一个形状：
        清单上有 17 条，真正跑得到的只有前 12 条。）
        ⇒ 凡是**可能抛异常**的判据一律走这里。
        """
        try:
            cond = fn()
        except Exception as e:
            red.append((cid, "%s —— 求值时抛异常：%s: %s" % (name, type(e).__name__, e)))
            return
        want(cid, name, cond, detail)

    # ── M1/M2：两条**结构性**的拦截 ──
    # 🔴 M1 的意义：库被误删 / paths.DB 写错时，静默从零开始写比报错危险得多
    #    （`[[backup-retention]]` 咬过六次的都是「删数据的默认值不够保守」这个形状）。
    #
    # 🔴🔴 **必须把 DB 指到一个不存在的路径上测**，不能靠"现在库恰好还没建"。
    #    2026-09-20 建完库当天就栽了：这条原来直接 `session("fix-something")`，
    #    库不存在时它测的是拦截、**库一旦存在它就变成了一次真实写库**
    #    —— 当场打了个备份文件出来，而断言"没拦住"反而红了。
    #    一条**测试的含义随环境改变**的检查，比没有检查更坏：它在最该守的那天
    #    （库刚建好）自己调转枪口。⇒ 造一个确定不存在的路径，让它永远测同一件事。
    _real_db = dbtool.DB
    dbtool.DB = _real_db.with_name("__definitely_not_a_db__.sqlite")
    try:
        try:
            with dbtool.session("fix-something", expect={}, verbose=False):
                pass
            want("M1", "库不存在时的非建库写入", False, "**没拦住**")
        except SystemExit as e:
            want("M1", "库不存在时的非建库写入", "不是建库步骤" in str(e), str(e)[:60])
    finally:
        dbtool.DB = _real_db
    want("M1b", "测完把 dbtool.DB 还原了", dbtool.DB == _real_db)

    # 🔴 M2 的意义：同一个形状发生过三次（pt 变形层 46.2% 空白页／ja 读音层
    #    99.90%→39.8%／ja 中文覆盖 98.66%→70.77%），三次都写了教训、三次都没拦住下一次。
    #    ⚠️ ko 的收词预计是七门里最大的一次 ⇒ 这条尤其要真的拦得住。
    try:
        with dbtool.session("ingest-edition", expect={"__rows__": 150000}):
            pass
        want("M2", "插 15 万行却不声明 invalidates", False, "**没拦住**")
    except SystemExit as e:
        want("M2", "插 15 万行却不声明 invalidates", "invalidates" in str(e), str(e)[:60])

    # ── M3：`has_hangul` 按**内容**判，不按整块码位判 ──
    #    ja 在这条上栽过（`・` 落在片假名区 ⇒ 纯汉字日语被判成"带假名"）。
    # 🔴🔴 每条只许测**一段区间**，测试串里不许混进别段的字符。
    #    2026-09-20 变异验证当场逮到：M3b 原来写的是 `"ㄷ 불규칙"` ——
    #    把 `_HANGUL_RANGES` 砍成只剩音节区（兼容字母区整个删掉），
    #    **十七条检查一条都不红**，因为 `불규칙` 三个字自己就在音节区里，
    #    它替被测的那段区间**背了书**（`[[criteria-narrower-than-you-think]]`
    #    的反面：判据比它要描述的东西更宽）。
    #    ⇒ 兼容字母那条改成**孤立的单字**，它红不红只取决于那一段在不在。
    want("M3a", "谚文音节区 사람", dbtool.has_hangul("사람"))
    want("M3b", "兼容谚文字母区 —— **孤立的** `ㄷ`（`ㄷ 불규칙` 这类活用类标签的字头）",
         dbtool.has_hangul("ㄷ"))
    want("M3b2", "谚文字母区（조합형）—— 孤立的初声 `ᄀ`", dbtool.has_hangul("ᄀ"))
    want("M3b3", "半角谚文区 —— 孤立的 `ﾡ`", dbtool.has_hangul("ﾡ"))
    want("M3c", "纯汉字韩语词 符號 不算带谚文", not dbtool.has_hangul("符號"))
    want("M3d", "中文不算带谚文", not dbtool.has_hangul("中文释义"))
    want("M3e", "带括号谚文 ㈀ **有意排除**（符号不是字母）", not dbtool.has_hangul("㈀"))
    want("M3f", "带圆圈谚文 ㉠ **有意排除**", not dbtool.has_hangul("㉠"))

    # ── M4：`is_chinese_text` 三步，纯汉字必须拿到 src 才肯答 ──
    # ⚠️ 以下全部走 `want_lazy`：`is_chinese_text` **有意**会抛异常，
    #    直接求值会在参数阶段炸掉整个 check_brief（见 `want_lazy` 的文件注释）。
    want_lazy("M4a", "带谚文 ⇒ 不是中文", lambda: dbtool.is_chinese_text("사람") is False)
    want_lazy("M4b", "罗马字串 ⇒ 不是中文", lambda: dbtool.is_chinese_text("gyoga") is False)
    # 🔴 中文版**两片都要认**：少写一个名字，那一片的译文会被判成"没翻译"
    want_lazy("M4c", "纯汉字 + 简体片源 ⇒ 是中文",
              lambda: dbtool.is_chinese_text("符號", "zh-edition-simp") is True)
    want_lazy("M4d", "纯汉字 + 繁体片源 ⇒ 是中文",
              lambda: dbtool.is_chinese_text("符號", "zh-edition-trad") is True)
    want_lazy("M4e", "纯汉字 + 韩语源 ⇒ 不是中文",
              lambda: dbtool.is_chinese_text("符號", "ko-edition") is False)
    try:
        dbtool.is_chinese_text("符號")
        want("M4f", "纯汉字无 src 时**拒绝猜**", False, "**没抛异常** —— 它猜了")
    except ValueError as e:
        want("M4f", "纯汉字无 src 时**拒绝猜**", "分不出中韩" in str(e))

    # ── M5：汉字判据不许只查基本区（元素字/鸟名/鱼名在扩展区，词典里大量出现）──
    want("M5a", "扩展 F 区 𬭊（化学元素字）", dbtool.has_han_char("𬭊"))
    want("M5b", "扩展 A 区 䴙（鸟名）", dbtool.has_han_char("䴙"))
    # 🔴 2026-09-20 加：韩语汉字音里真实出现 `𰜩`（U+30729，扩展 G）。
    #    拷过来的区间表停在 U+2FA1F ⇒ 它被判成"不是汉字"。
    #    **扩展区还在往后加**，一份写死的区间表必然追不上 —— 这两条钉住上界。
    want("M5c", "扩展 G 区 𰜩（U+30729，韩语汉字音里真实出现）", dbtool.has_han_char("𰜩"))
    want("M5d", "扩展 H 区 U+31350", dbtool.has_han_char(chr(0x31350)))
    # 反向：不是汉字的东西不许被收进来（区间放宽不能放到谚文/假名头上）
    want("M5e", "谚文不算汉字", not dbtool.has_han_char("가"))
    want("M5f", "假名不算汉字", not dbtool.has_han_char("あ"))

    # ── M6：`has_han` 这个名字必须**不存在** ──
    # 🔴 从另外七门拷来的脚本必然写着 `dbtool.has_han(...)`。留着它＝静默给错答案；
    #    删掉它＝`AttributeError` 当场炸。`[[prefer-reversible-designs]]`
    want("M6", "`has_han` 这个名字不存在", not hasattr(dbtool, "has_han"),
         "**它存在了** —— 拷过来的脚本会静默拿到错答案")

    # ── M7：闸门自己的清单里不许有死条目（列 **和** 表两半都查）──
    # 🔴🔴 这条是 2026-09-20 建完库当天加的：`TRACK_TABLES` 里躺着
    #    `pronunciation_entry`，而 ko 的 schema 不建它。回头一查，**ja/en/de/pt
    #    四门的 TRACK_TABLES 里都列着它、库里都没有**（只有 it 真有，282,060 行）。
    #    ja 那次只修了「列」那一半 ⇒ **同一个洞有两半时，修一半比不修更危险**，
    #    它会让人以为这类问题已经解决了。
    if dbtool.DB.exists():
        import sqlite3
        _c = sqlite3.connect("file:%s?mode=ro" % dbtool.DB, uri=True)
        try:
            dead = dbtool._track_audit(_c, verbose=False)
            want("M7", "闸门清单（TRACK + TRACK_TABLES）里没有死条目",
                 not dead, "死条目：%s" % dead)
            # 闸自证：审计函数得真的**认得出**死条目，而不是永远返回空列表
            dbtool.TRACK_TABLES.append("__nonexistent_table__")
            dbtool.TRACK.append("__nonexistent_col__")
            try:
                probe = dbtool._track_audit(_c, verbose=False)
                want("M7b", "审计函数认得出**表**的死条目",
                     "#__nonexistent_table__" in probe, "它没认出来 —— 这道闸是死的")
                want("M7c", "审计函数认得出**列**的死条目",
                     "__nonexistent_col__" in probe, "它没认出来 —— 这道闸是死的")
            finally:
                dbtool.TRACK_TABLES.remove("__nonexistent_table__")
                dbtool.TRACK.remove("__nonexistent_col__")
        finally:
            _c.close()

    # ══════════════════════════════════════════════════════════════
    # ── M8：K31 的写后欠账机制 ──
    #
    # 🔴🔴 这一组要验的不是「机制存在」，而是**它会不会真的响**。
    #    K31 本身就是「机制不存在」造成的：09-25 修了两处数据，
    #    两道外锚闸从那天起红了整整一天，因为写库之后**什么都不说**。
    #    ⇒ 一条一条问：脏得对不对？欠账变不变红？闸红了会不会被误划掉？
    #      名单自己坏了认不认得出？
    import json as _json
    import tempfile as _tmp
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        import gates as _G
    except Exception as e:                        # noqa: BLE001
        red.append(("M8", "读不到 `ko/gates.py`（%s）—— K31 的整个机制靠它" % e))
        _G = None

    if _G is not None:
        _real_pending = _G.PENDING
        _real_ts = _G.SERVICE_TS
        _real_unclaimed = dict(_G.UNCLAIMED)
        _d = Path(_tmp.mkdtemp())
        _G.PENDING = _d / "pending.json"
        try:
            # ── M8a/M8b：依赖算得对不对（**方向两边都验**）──
            # 宽是有意的，但"宽"不等于"什么都脏" —— 只动 audio 不该脏掉义项外锚闸。
            want_lazy("M8a", "动了 `pronunciation` ⇒ 例句/变形/读音外锚闸变脏",
                      lambda: "外锚闸·例句/变形/读音"
                      in _G.dirty({"#pronunciation": 5})[0],
                      "它没脏 —— 正是 09-25 漏跑的那一道")
            want_lazy("M8b", "只动 `audio` ⇒ 录音两道脏、义项外锚闸**不脏**",
                      lambda: ("录音重复闸" in _G.dirty({"#audio": 1})[0]
                               and "外锚闸·义项" not in _G.dirty({"#audio": 1})[0]),
                      "依赖算错了（全脏＝等于没分类，人会关掉它）")
            # 裸列名属于 `dict`，而 `dict` 几乎连着所有闸 —— 这一条验键的解析
            want_lazy("M8c", "裸列名（`freq_zipf`）认得出属于 `dict`",
                      lambda: _G.table_of("freq_zipf") == "dict"
                      and _G.table_of("__rows__") == "dict"
                      and _G.table_of("#sense") == "sense"
                      and _G.table_of("entry.hanja") == "entry",
                      "键解析错了 ⇒ 脏的算不准")

            # ── M8d：欠账非空 ⇒ 账的闸 P12 必须红；划掉之后必须绿 ──
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from test_plan_ledger import p12 as _p12

            def _p12_red_on_debt():
                _G.clear_all()
                if _p12():
                    return False          # 本来就红，这条验不了（见下面的 detail）
                _G.mark(["外锚闸·义项"], "m8-fake-tag", {"sense"})
                got = [w for _c, w in _p12() if "外锚闸·义项" in w]
                _G.clear("外锚闸·义项")
                return bool(got) and not _p12()
            want_lazy("M8d", "欠账非空 ⇒ P12 红；划掉 ⇒ P12 绿", _p12_red_on_debt,
                      "🔴 欠着不跑而账的闸报绿 —— 那就回到 09-25 的状态了"
                      "（或：P12 本来就红，这条没验到东西）")

            # ── M8e：闸自己红了**不许划账** ──
            #    这是整个机制的承重点：「绿」的唯一定义是退出码 0。
            def _red_gate_keeps_debt():
                _G.clear_all()
                g = _G.by_name("录音重复闸")
                old = g["cmd"]
                g["cmd"] = "exit 3"
                try:
                    _G.mark(["录音重复闸"], "m8-fake-tag", {"audio"})
                    ok = _G.run("录音重复闸", verbose=False)
                    still = "录音重复闸" in _G.load()
                finally:
                    g["cmd"] = old
                    _G.clear_all()
                return (not ok) and still
            want_lazy("M8e", "闸退出码非 0 ⇒ 这一笔**留着**", _red_gate_keeps_debt,
                      "🔴🔴 跑红了却把账划掉 ＝ 机制反过来帮着掩盖")

            # ── M8f：欠账文件读不动 ≠ 没欠账 ──
            def _corrupt_is_not_clean():
                _G.PENDING.write_text("{ 这不是 json", encoding="utf-8")
                try:
                    _G.load()
                    return False
                except BaseException:
                    return True
                finally:
                    _G.clear_all()
            want_lazy("M8f", "欠账文件坏了 ⇒ 抛，不当成「没欠账」",
                      _corrupt_is_not_clean,
                      "静默当空 ＝ 把红伪装成绿（`[[residual-bucket-is-not-evidence]]` 同形）")

            # ── M8g：从 `korean.ts` 抠表的判据坏掉时，必须抛而不是退化成空集 ──
            def _floor_guards_scan():
                _G.SERVICE_TS = _real_ts.parent.parent.parent.parent / "package.json"
                try:
                    _G.service_tables()
                    return False
                except BaseException:
                    return True
                finally:
                    _G.SERVICE_TS = _real_ts
            want_lazy("M8g", "服务层扫描抠不到表 ⇒ 抛（不退化成「永远不脏」）",
                      _floor_guards_scan,
                      "🔴 扫空了却报没事 ＝ 契约闸永远不脏，正是 K31 要治的病本身")

            # ── M8h：追踪的表**没人盯着**时，名单自检要认出来 ──
            def _orphan_table_is_red():
                dbtool.TRACK_TABLES.append("__orphan_table__")
                try:
                    return any("__orphan_table__" in b for b in _G.self_check())
                finally:
                    dbtool.TRACK_TABLES.remove("__orphan_table__")
            want_lazy("M8h", "有表没有任何闸盯着 ⇒ 名单自检红", _orphan_table_is_red,
                      "🔴 ja 的 `sense_tag` 空了整个项目而阶段表全 ✅，就是这个形状")

            # ── M8i：UNCLAIMED 是**带锁的豁免** —— 那张表一旦有了行就得红 ──
            def _unclaimed_with_rows_is_red():
                _G.UNCLAIMED["audio"] = "（变异注入：audio 其实有行）"
                try:
                    return any("audio" in b and "UNCLAIMED" in b
                               for b in _G.self_check())
                finally:
                    _G.UNCLAIMED.clear()
                    _G.UNCLAIMED.update(_real_unclaimed)
            want_lazy("M8i", "UNCLAIMED 里的表有了行 ⇒ 名单自检红",
                      _unclaimed_with_rows_is_red,
                      "豁免没有失效条件 ＝ 永久豁免，那是记账不是闸")

            # ── M8j：npm 入口不存在 ⇒ 名单自检红（「文件在」≠「跑得起来」）──
            def _missing_npm_script_is_red():
                g = _G.by_name("词源展示契约闸")
                old = g["cmd"]
                g["cmd"] = "npm run --silent gate:__definitely_not_a_script__"
                try:
                    return any("__definitely_not_a_script__" in b
                               for b in _G.self_check())
                finally:
                    g["cmd"] = old
            want_lazy("M8j", "npm 入口在 package.json 里不存在 ⇒ 名单自检红",
                      _missing_npm_script_is_red,
                      "🔴 `contract-check-etym.tsx` 八门都写了、**没有入口**，"
                      "整整一个阶段没人跑得动 —— 这条就是为它加的")

            # ── M8k：闸文件被删 ⇒ 名单自检红 ──
            def _missing_file_is_red():
                g = _G.by_name("查询计划闸")
                old = g["file"]
                g["file"] = "ko/probes/__deleted__.py"
                try:
                    return any("__deleted__" in b for b in _G.self_check())
                finally:
                    g["file"] = old
            want_lazy("M8k", "闸文件不存在 ⇒ 名单自检红", _missing_file_is_red)

            # ── M8l：**本来不在欠账里**的闸跑出红，必须被记上 ──
            #    第一版只做「绿了划账」⇒ 一道本来就红着的闸（只读源码、没有写库
            #    弄脏过它，比如 `css-audit`）跑出红之后欠账还是空的、P12 照样绿。
            #    那正是 09-25 的处境：**红着，而没有任何东西记得它红。**
            def _red_run_creates_debt():
                _G.clear_all()
                g = _G.by_name("样式孤儿闸")
                old = g["cmd"]
                g["cmd"] = "exit 7"
                try:
                    ok = _G.run("样式孤儿闸", verbose=False)
                    got = "样式孤儿闸" in _G.load()
                finally:
                    g["cmd"] = old
                    _G.clear_all()
                return (not ok) and got
            want_lazy("M8l", "本来不欠账的闸跑出红 ⇒ 记上一笔（P12 会一直红）",
                      _red_run_creates_debt,
                      "🔴🔴 红了而没人记得它红 ＝ 回到 09-25 的处境")

            # ── M8m：**纯内容写库**（计数一个不变）也必须标脏 ──
            #    🔴🔴 这条是被真事故逼出来的：K16 重译 20 条例句译文是纯 UPDATE，
            #    所有计数一个没变 ⇒ `diff` 是空的 ⇒ 第一版机制**一道闸都没标脏**，
            #    而例句译文正是契约闸盯的东西。
            #    `[[primary-key-is-not-enough]]`：**计数型判据对内容改动结构性失明。**
            #    ⇒ 判据改成「这次写了哪张表」，由 `_S.touched` 从 SQL 里抠。
            want_lazy("M8m", "计数没变、只改了内容 ⇒ 照样按「写了哪张表」标脏",
                      lambda: _G.dirty({}, extra_tables={"example_gloss"})[0] != []
                      and "展示层契约闸·ko" in _G.dirty({}, extra_tables={"example_gloss"})[0],
                      "🔴🔴 内容改了而欠账是空的 —— 这就是 K16 那天真实发生的事")
            # 方向的另一边：SQL 抠表名不能把 SELECT 当成写
            def _select_is_not_a_write():
                s = dbtool._S.__new__(dbtool._S)
                s.touched = set()
                s._note("SELECT id, text FROM example_gloss WHERE lang='zh'")
                clean = not s.touched
                s._note("UPDATE example_gloss SET text=? WHERE example_id=?")
                got = s.touched == {"example_gloss"}
                s._note("INSERT OR IGNORE INTO sense_relation (word_id) VALUES (?)")
                return clean and got and "sense_relation" in s.touched
            want_lazy("M8n", "抠表名认得出 UPDATE/INSERT OR IGNORE，**不把 SELECT 当写**",
                      _select_is_not_a_write,
                      "把读当成写 ⇒ 每次查库都标脏一片，人会关掉这个机制")
        finally:
            _G.PENDING = _real_pending
            _G.SERVICE_TS = _real_ts
            _G.UNCLAIMED.clear()
            _G.UNCLAIMED.update(_real_unclaimed)
            _json  # noqa: B018 —— 留着给以后写欠账文件形状的检查

    return red


if __name__ == "__main__":
    red = check_brief()
    if red:
        print("🔴 闸的变异验证未通过：%d 条" % len(red))
        for cid, why in red:
            print("   %-5s %s" % (cid, why))
        sys.exit(1)
    print("■ ko 写库闸门变异验证通过 ✓（每一条都验的是「它拦得住什么」，不是「它存在」）")
