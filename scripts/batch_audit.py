#!/usr/bin/env python3
"""付费跑批的两道「量一遍」：花钱前量**被加工的那一列**，回收后把**异常输出逐条列出来**。2026-11-01（B21）。

六门各自的 `*/pipeline/ds_batch.py` 的 `run()` 都调这里（判据只此一份，语种无关 —— 与 `zh_t2s.py` 同一个待遇）。

═══ 为什么 ═══
vi 阶段 6e 开跑前先量了 `example.text` 自己，逮到 **256 条根本不是例句**（外语原文／关系元数据与声调范式表／只有出处）；
ko 的同一类缺陷（K15，385 条谚语「成分拆解」）是**花了钱之后**才逮到的。
而 vi 花钱之后仍逮到第二批：22 条译文「没有一个汉字」—— **模型拒绝翻译、原样返回**（`Coordinate term: mi`）。
⇒ 两次：开跑前量一次，**回收时把异常输出逐条读一次**（只看比例，判据太宽的一堆和真缺陷的一堆都看不见）。

═══ ① 花钱前 `preflight()` ═══
把每条输入的文字分桶，**全部**写进 `<答案文件>.input-audit.txt`。
本轮有**没量过的条目**（按内容 sha 记在 `<答案文件>.input-audit.json`）⇒ 写报告、停下，让人读完再跑同一条命令。
重试只送失败的那一部分 ⇒ 是量过的子集 ⇒ 直接放行。
⚠️ 桶是**形状**，不是判决：「标签式」桶里可能有正当的 `Note: …`。报告的用处是让人**读**，不是自动删。

═══ ② 回收后 `postflight()` ═══
本轮新写的行里，`zh` 字段 空／一个汉字都没有／与输入里某段文字一模一样（原样返回）的，
**逐条**写进 `<答案文件>.anomalies.tsv` 并打到屏幕上。只报不拦 —— 答案已经付过钱了，要的是有人读。
约定：翻译类输出都用 `zh` 键（vi/ja/ru/ko 的调用方实测如此）；没有 `zh` 键的行（判官类）不查。

用法：
    python3 scripts/batch_audit.py --selftest
"""
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

# 「标签: 内容」—— 维基的关系/元数据行（`Coordinate term: mi`、`Synonym: x`、`level tone: y`）
_LABEL = re.compile(r"^\s*[A-Za-z][A-Za-z -]{1,30}:\s+\S")
_WIKI = re.compile(r"\[\[|\]\]|\{\{|\}\}|<ref|'''|__[A-Z]+__")
# ❌ 有意**没有**「超长」桶：拿 vi 例句 78,235 条实测，比中位数长 5/10/20 倍的里面后来被判「不是例句」的都只占 ~5%（3,469 条里 117），
#    与随便抽差不多 —— 长短不是「这不是例句」的信号，留着只会把真东西埋进三千条正常长引文里。
REPEAT_MIN = 20          # 同一段文字出现 20 次以上


def texts_of(payload):
    """→ 一条输入里的全部文字段。payload 可以是串、dict、list（ds_batch 的调用方三种都有）。"""
    if isinstance(payload, str):
        return [payload]
    if isinstance(payload, dict):
        return [t for v in payload.values() for t in texts_of(v)]
    if isinstance(payload, (list, tuple)):
        return [t for v in payload for t in texts_of(v)]
    return []


def has_letter(s):
    return any(unicodedata.category(c).startswith("L") for c in s)


def has_han(s):
    # 交给 Unicode 答，不手抄码位范围（`[[criteria-from-meaning-not-form]]`：化学元素名在扩展平面）
    return any(unicodedata.name(c, "").startswith("CJK UNIFIED IDEOGRAPH") or
               unicodedata.name(c, "").startswith("CJK COMPATIBILITY IDEOGRAPH") for c in s)


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def buckets(items):
    """items：[(rid, 文字)]。→ {桶名: [(rid, 文字)]}。纯函数。"""
    out = {k: [] for k in ("空串", "一个字母都没有", "wiki 标记残渣", "「标签: 内容」式元数据",
                           "同一段文字反复出现（≥%d 次）" % REPEAT_MIN)}
    cnt = {}
    for _r, t in items:
        cnt[t] = cnt.get(t, 0) + 1
    seen_rep = set()
    for rid, t in items:
        s = t.strip()
        if not s:
            out["空串"].append((rid, t))
            continue
        if not has_letter(s):
            out["一个字母都没有"].append((rid, t))
        if _WIKI.search(s):
            out["wiki 标记残渣"].append((rid, t))
        if _LABEL.match(s):
            out["「标签: 内容」式元数据"].append((rid, t))
        if cnt[t] >= REPEAT_MIN and t not in seen_rep:
            seen_rep.add(t)
            out["同一段文字反复出现（≥%d 次）" % REPEAT_MIN].append((rid, "%s（×%d）" % (t, cnt[t])))
    return out


def _items(batches, meta):
    for i, b in enumerate(batches):
        for k, rid in meta[i]:
            for t in texts_of(b.get(k)):
                yield rid, t


def preflight(batches, meta, out_path):
    """花钱前。本轮全是量过的条目 ⇒ 一行放行；否则写报告并 `SystemExit`。"""
    out_path = Path(out_path)
    led = out_path.with_name(out_path.name + ".input-audit.json")
    rep = out_path.with_name(out_path.name + ".input-audit.txt")
    items = list(_items(batches, meta))
    try:
        known = set(json.loads(led.read_text(encoding="utf-8"))) if led.exists() else set()
    except (json.JSONDecodeError, OSError) as e:
        raise SystemExit("🔴 输入量表读不动：%s（%s）—— 别当成「量过了」" % (led, e))
    new = [(r, t) for r, t in items if sha(t) not in known]
    if not new:
        print("■ 输入量过了（%s 条，报告 %s）" % (format(len(items), ","), rep.name), flush=True)
        return
    bk = buckets(items)
    lines = ["# 花钱之前：被加工的那一列逐桶全量（B21）。桶是形状不是判决 —— 读一遍，该在调用方剔掉的剔掉，再跑同一条命令。",
             "# 共 %d 段文字（其中本轮新出现 %d 段）" % (len(items), len(new)), ""]
    print("■ 🔴 花钱之前先量被加工的那一列：%s 段文字，%s 段没量过" % (format(len(items), ","), format(len(new), ",")), flush=True)
    for name, xs in bk.items():
        print("   %-28s %s" % (name, format(len(xs), ",")), flush=True)
        lines.append("## %s：%d" % (name, len(xs)))
        lines += ["%s\t%s" % (r, t.replace("\n", "⏎")[:300]) for r, t in xs]
        lines.append("")
        for r, t in xs[:5]:
            print("      · %s  %s" % (r, t.replace("\n", "⏎")[:100]), flush=True)
    rep.parent.mkdir(parents=True, exist_ok=True)
    # 追加不覆盖：同一份答案文件分几次量（先 1% 切片、再全量）时，前一次的报告不能被冲掉
    with rep.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    led.write_text(json.dumps(sorted(known | {sha(t) for _r, t in items})), encoding="utf-8")
    raise SystemExit("■ 报告 → %s\n   读完（该剔的在调用方剔掉）再跑同一条命令；这一次一分钱没花。" % rep)


def anomalies(rows, inputs):
    """纯函数。rows：本轮新写的答案行；inputs：{rid: [输入文字]}。→ [(rid, 类别, zh)]。"""
    out = []
    for r in rows:
        if "zh" not in r:
            continue
        zh = r.get("zh")
        rid = r.get("id")
        if not isinstance(zh, str) or not zh.strip():
            out.append((rid, "空", zh))
        elif zh.strip() in {t.strip() for t in inputs.get(rid, [])}:
            out.append((rid, "原样返回", zh))
        elif not has_han(zh):
            out.append((rid, "一个汉字都没有", zh))
    return out


def postflight(batches, meta, out_path, offset):
    """回收后。`offset`：本轮开跑前答案文件的字节数（只看本轮新写的）。只报不拦。"""
    out_path = Path(out_path)
    if not out_path.exists():
        return []
    with out_path.open("rb") as fh:
        fh.seek(offset)
        rows = []
        for ln in fh.read().decode("utf-8").splitlines():
            try:
                rows.append(json.loads(ln))
            except ValueError:
                pass
    inputs = {}
    for rid, t in _items(batches, meta):
        inputs.setdefault(rid, []).append(t)
    bad = anomalies(rows, inputs)
    if not rows or not any("zh" in r for r in rows):
        return bad
    tsv = out_path.with_name(out_path.name + ".anomalies.tsv")
    if not bad:
        print("■ 回收核对：本轮 %s 行，`zh` 空／原样返回／没有汉字 0 条" % format(len(rows), ","), flush=True)
        return bad
    with tsv.open("a", encoding="utf-8") as fh:
        for rid, kind, zh in bad:
            fh.write("%s\t%s\t%s\t%s\n" % (rid, kind, json.dumps(zh, ensure_ascii=False),
                                         " ｜ ".join(t.replace("\n", "⏎")[:150] for t in inputs.get(rid, []))))
    print("■ 🔴 回收核对：本轮 %s 行里 %d 条异常 —— **逐条读**，模型拒绝翻译的往往不是句子（B21）"
          % (format(len(rows), ","), len(bad)), flush=True)
    for rid, kind, zh in bad[:30]:
        print("      · %s  [%s]  %r ← %s" % (rid, kind, zh, " ｜ ".join(t[:60] for t in inputs.get(rid, []))), flush=True)
    if len(bad) > 30:
        print("      …其余 %d 条见 %s" % (len(bad) - 30, tsv), flush=True)
    else:
        print("      全部在 %s" % tsv, flush=True)
    return bad


def selftest():
    import tempfile
    bad = []
    items = [(i, "Ordinary sentence number %d here." % i) for i in range(40)]
    items += [(100, ""), (101, "—— 123"), (102, "see [[mi]]"), (103, "Coordinate term: mi"),
              (104, "x" * 2000)] + [(200 + i, "Same line.") for i in range(REPEAT_MIN)]
    b = buckets(items)
    want = {"空串": {100}, "一个字母都没有": {101}, "wiki 标记残渣": {102}, "「标签: 内容」式元数据": {103},
            "同一段文字反复出现（≥%d 次）" % REPEAT_MIN: {200}}
    for k, ids in want.items():
        if {r for r, _t in b[k]} != ids:
            bad.append("桶「%s」判成 %s，应为 %s" % (k, sorted(r for r, _t in b[k]), sorted(ids)))
    if b["「标签: 内容」式元数据"] and any(r < 40 for r, _t in b["「标签: 内容」式元数据"]):
        bad.append("反控：普通句子进了标签桶")
    if any(r == 104 for xs in b.values() for r, _t in xs):
        bad.append("反控：超长的正常文字进了桶（长短不是信号）")
    rows = [{"id": 1, "zh": "普通的句子。"}, {"id": 2, "zh": ""}, {"id": 3, "zh": "Coordinate term: mi"},
            {"id": 4, "zh": "level tone"}, {"id": 5, "verdict": "keep"}, {"id": 6, "zh": "𬭛元素"}]
    got = {(r, k) for r, k, _z in anomalies(rows, {3: ["Coordinate term: mi"], 4: ["level tone: y"]})}
    if got != {(2, "空"), (3, "原样返回"), (4, "一个汉字都没有")}:
        bad.append("回收异常判成 %s" % sorted(got))
    # preflight：第一次停、写报告；同一批放行；子集（重试）放行；多一条新的又停
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "ans.jsonl"
        batches = [{"a": "Hello there.", "b": {"w": "x", "t": "Synonym: y"}}]
        meta = [[("a", 1), ("b", 2)]]
        stops = []
        for bs, ms in ((batches, meta), (batches, meta), ([{"a": "Hello there."}], [[("a", 1)]]),
                       ([{"a": "Brand new."}], [[("a", 3)]])):
            try:
                import contextlib, io
                with contextlib.redirect_stdout(io.StringIO()):
                    preflight(bs, ms, out)
                stops.append(False)
            except SystemExit:
                stops.append(True)
        if stops != [True, False, False, True]:
            bad.append("preflight 停/放 %s，应为 [停, 放, 放（重试子集）, 停（新条目）]" % stops)
        if "Synonym: y" not in (Path(d) / "ans.jsonl.input-audit.txt").read_text(encoding="utf-8"):
            bad.append("报告里没有标签式那一条")
        # postflight：只看 offset 之后的行
        out.write_text(json.dumps({"id": 9, "zh": ""}) + "\n", encoding="utf-8")
        off = out.stat().st_size
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": 1, "zh": "Hello there."}, ensure_ascii=False) + "\n")
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            got = postflight(batches, meta, out, off)
        if [(r, k) for r, k, _z in got] != [(1, "原样返回")]:
            bad.append("postflight 判成 %s（应只看本轮新写的那一行）" % got)
        if not (Path(d) / "ans.jsonl.anomalies.tsv").exists():
            bad.append("postflight 没写异常清单")
    for x in bad:
        print("🔴 " + x)
    print("%s 跑批量表自检%s" % ("🔴" if bad else "✅", "：%d 处失败" % len(bad) if bad else "通过（五桶＋反控（含超长句不进任何桶）／回收三类／停放四步／只看本轮）"))
    return 1 if bad else 0


_WIRING = r"""
import asyncio, json, sys, tempfile, shutil, atexit
from pathlib import Path
import httpx
sys.path.insert(0, "pipeline")
import ds_batch
calls = []
def handler(req):
    calls.append(1)
    body = json.loads(req.content)
    content = json.dumps({"a": {"zh": "你好。"}, "b": {"zh": "Synonym: y"}}, ensure_ascii=False)
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {"total_tokens": 1}})
_real = httpx.AsyncClient
httpx.AsyncClient = lambda *a, **k: _real(transport=httpx.MockTransport(handler))
d = Path(tempfile.mkdtemp()); atexit.register(shutil.rmtree, d, True)
out = d / "ans.jsonl"
batches = [{"a": "Hello there.", "b": {"w": "x", "t": "Synonym: y"}}]
meta = [[("a", 1), ("b", 2)]]
try:
    asyncio.run(ds_batch.run("sys", batches, meta, out))
    raise SystemExit("第一次没停下")
except SystemExit as e:
    if "第一次没停下" in str(e):
        raise
assert not calls, "停下之前已经发了 %d 个请求" % len(calls)
assert (d / "ans.jsonl.input-audit.txt").exists(), "没写输入报告"
asyncio.run(ds_batch.run("sys", batches, meta, out))
assert calls, "第二次没发请求"
tsv = (d / "ans.jsonl.anomalies.tsv")
assert tsv.exists() and "原样返回" in tsv.read_text(encoding="utf-8"), "原样返回那条没进异常清单"
print("OK")
"""

LANGS = ("it", "ja", "ko", "pt", "ru", "vi")


def wiring():
    """六门 `ds_batch.run()` 真的接上了：第一次停且一个请求没发／第二次放行／原样返回进清单。假传输层，不花钱。"""
    import subprocess
    root = Path(__file__).resolve().parent.parent
    bad = 0
    for l in LANGS:
        r = subprocess.run([sys.executable, "-B", "-c", _WIRING], cwd=root / l, capture_output=True, text=True)
        out = r.stdout.strip().splitlines()
        ok = r.returncode == 0 and out and out[-1] == "OK"
        bad += not ok
        print("   %s %s %s" % ("✅" if ok else "🔴", l, "停下不花钱／量过放行／原样返回进清单" if ok
                                else ((r.stderr.strip().splitlines() or out or ["无输出"])[-1])[:200]))
    print("%s 六门跑批器接线 %d/%d" % ("🔴" if bad else "✅", len(LANGS) - bad, len(LANGS)))
    return 1 if bad else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest() or wiring())
    print(__doc__)
