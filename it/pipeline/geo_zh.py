#!/usr/bin/env python3
"""法语版意大利地名释义 → 中文的**确定性**模板。2026-08-14，阶段 3c 重做。

═══ 为什么重做 ═══
`PLAYBOOK` 5.3「模板在模型前面」我只做了一半（`Nom de famille.` 那 13.9 万条），
把地理这一族整批扔给了模型，后果是**同一个模式给了三种格式**：

    Cerreto Laziale  → 切雷托拉齐亚莱                  （地理信息全丢）
    Villa Fiore      → 阿尔巴阿德里亚蒂卡的村庄          （自己的名字丢了）
    Tremezzo         → 特雷梅佐，意大利科莫省分区及旧市镇  （完整）

⇒ 分工应该是：**音译只有模型能做**（专名 → 中文读音），
   **框架只有模板该做**（`（意大利X大区Y省市镇）`，必须逐条一致）。
   本文件只做后者，音译沿用模型已产出的那部分。

═══ 🔴 一个真陷阱：法语用的是法语自己的地名外来名 ═══
    Coni = Cuneo     Côme = Como      Turin = Torino
    Aoste = Aosta    Pavie = Pavia    Bergame = Bergamo    Verceil = Vercelli
所以映射链是 **法语名 → 意大利语名 → 中文**，不能法→中直接查。
下面两张表的键是**法语形**，值是中文（中间那步已在表里合并）。

⚠️ 表里没有的名字**不猜**（`PITFALLS` A4：判据改三轮就停手，残差当上界报）——
   查不到就退化成不带该层信息的短框架，绝不音译一个我没核过的地名。
"""
import re

# 意大利 20 个大区（法语形 → 中文）。这是全集，不会再增。
REGION_ZH = {
    "Lombardie": "伦巴第", "Piémont": "皮埃蒙特", "Vénétie": "威尼托",
    "Sardaigne": "撒丁", "Campanie": "坎帕尼亚", "Calabre": "卡拉布里亚",
    "Sicile": "西西里", "Trentin-Haut-Adige": "特伦蒂诺-上阿迪杰",
    "Vallée d’Aoste": "瓦莱达奥斯塔", "Vallée d'Aoste": "瓦莱达奥斯塔",
    "Émilie-Romagne": "艾米利亚-罗马涅", "Latium": "拉齐奥",
    "Frioul-Vénétie julienne": "弗留利-威尼斯朱利亚", "Toscane": "托斯卡纳",
    "Abruzzes": "阿布鲁佐", "Marches": "马尔凯", "Pouilles": "普利亚",
    "Molise": "莫利塞", "Ligurie": "利古里亚", "Basilicate": "巴西利卡塔",
    "Ombrie": "翁布里亚", "Trentino-Alto Adige": "特伦蒂诺-上阿迪杰",
    # 源头拼写笔误，实测各出现 1 次；照旧映射，不改源头
    "Ligure": "利古里亚", "Piemont": "皮埃蒙特",
}

# 省 / 广域市（法语形 → 中文）。意大利实际 107 个，这里收实测出现过的。
PROV_ZH = {
    "Turin": "都灵", "Aoste": "奥斯塔", "Coni": "库内奥", "Trente": "特伦托",
    "Pavie": "帕维亚", "Bergame": "贝尔加莫", "Cosenza": "科森扎", "Brescia": "布雷西亚",
    "Vicence": "维琴察", "Alexandrie": "亚历山德里亚", "Avellino": "阿韦利诺",
    "Cagliari": "卡利亚里", "Caserte": "卡塞塔", "Padoue": "帕多瓦", "Oristano": "奥里斯塔诺",
    "Belluno": "贝卢诺", "Salerne": "萨莱诺", "Messine": "墨西拿", "Bolzano": "博尔扎诺",
    "Trévise": "特雷维索", "Crémone": "克雷莫纳", "Vérone": "维罗纳", "Sassari": "萨萨里",
    "Milan": "米兰", "Catanzaro": "卡坦扎罗", "Côme": "科莫", "L’Aquila": "拉奎拉",
    "L'Aquila": "拉奎拉", "Reggio de Calabre": "雷焦卡拉布里亚", "Mantoue": "曼托瓦",
    "Campobasso": "坎波巴索", "Chieti": "基耶蒂", "Varèse": "瓦雷泽", "Asti": "阿斯蒂",
    "Potenza": "波坦察", "Rome Capitale": "罗马首都", "Bologne": "博洛尼亚",
    "Naples": "那不勒斯", "Nuoro": "努奥罗", "Palerme": "巴勒莫",
    "Vibo Valentia": "维博瓦伦蒂亚", "Rovigo": "罗维戈", "Lecco": "莱科", "Rieti": "列蒂",
    "Isernia": "伊塞尔尼亚", "Biella": "比耶拉", "Lecce": "莱切", "Frosinone": "弗罗西诺内",
    "Verceil": "韦尔切利", "Gênes": "热那亚", "Bénévent": "贝内文托", "Macerata": "马切拉塔",
    "Verbano-Cusio-Ossola": "韦尔巴诺-库西奥-奥索拉", "Sondrio": "松德里奥",
    "Foggia": "福贾", "Imperia": "因佩里亚", "Savone": "萨沃纳", "Novare": "诺瓦拉",
    "Lodi": "洛迪", "Udine": "乌迪内", "Trieste": "的里雅斯特", "Gorizia": "戈里齐亚",
    "Pordenone": "波代诺内", "Venise": "威尼斯", "Florence": "佛罗伦萨", "Pise": "比萨",
    "Sienne": "锡耶纳", "Livourne": "利沃诺", "Arezzo": "阿雷佐", "Grosseto": "格罗塞托",
    "Lucques": "卢卡", "Pistoia": "皮斯托亚", "Prato": "普拉托", "Massa-Carrara": "马萨-卡拉拉",
    "Pérouse": "佩鲁贾", "Terni": "特尔尼", "Ancône": "安科纳", "Pesaro et Urbino": "佩萨罗-乌尔比诺",
    "Fermo": "费尔莫", "Ascoli Piceno": "阿斯科利皮切诺", "Teramo": "泰拉莫",
    "Pescara": "佩斯卡拉", "Bari": "巴里", "Tarente": "塔兰托", "Brindisi": "布林迪西",
    "Barletta-Andria-Trani": "巴列塔-安德里亚-特拉尼", "Matera": "马泰拉",
    "Crotone": "克罗托内", "Catane": "卡塔尼亚", "Syracuse": "锡拉库萨", "Raguse": "拉古萨",
    "Trapani": "特拉帕尼", "Agrigente": "阿格里真托", "Caltanissetta": "卡尔塔尼塞塔",
    "Enna": "恩纳", "Parme": "帕尔马", "Modène": "摩德纳", "Ferrare": "费拉拉",
    "Ravenne": "拉韦纳", "Forlì-Cesena": "弗利-切塞纳", "Rimini": "里米尼",
    "Reggio d’Émilie": "雷焦艾米利亚", "Reggio d'Émilie": "雷焦艾米利亚",
    "Plaisance": "皮亚琴察", "La Spezia": "拉斯佩齐亚", "Latina": "拉蒂纳",
    "Viterbe": "维泰博", "Frosinone": "弗罗西诺内", "Nuoro": "努奥罗",
    "Sud-Sardaigne": "南撒丁", "Sardaigne du Sud": "南撒丁", "Monza et de la Brianza": "蒙扎-布里安扎",
    "Monza et Brianza": "蒙扎-布里安扎",
    # 撒丁 2016 年撤销的四个省，法语版还在用（源头是旧数据，我们照收不改）
    "Medio Campidano": "中坎皮达诺", "Olbia-Tempio": "奥尔比亚-坦皮奥",
    "Ogliastra": "奥利亚斯特拉", "Carbonia-Iglesias": "卡尔博尼亚-伊格莱西亚斯",
}

# 释义骨架
COMMUNE = re.compile(
    r"^(?P<head>.+?),\s*(?:frazione et ancienne commune|ancienne commune|commune|"
    r"ville|village)\s+d[’'](?:Italie|Italien)?\s*"
    r"(?:de la (?:province autonome|province|ville métropolitaine)\s+d[e’']\s*(?P<prov>.+?)\s+)?"
    r"dans (?:la|le|les|l’)?\s*r[ée]gion\s+(?:de la |de l’|du |des |de |d[’'])?(?P<reg>.+?)\s*\.?$",
    re.IGNORECASE)
HAMEAU_A = re.compile(r"^Hameau\s+de\s+(?P<parent>.+?)(?:,\s*localité italienne\s+"
                      r"(?:de la |de l’|du |des |de |d[’'])?(?P<reg>.+?))?\s*\.?$", re.IGNORECASE)
HAMEAU_B = re.compile(r"^(?P<head>.+?),\s*hameau\s+de\s+(?P<parent>.+?)\s*\.?$", re.IGNORECASE)

# 已有中文是否像"纯音译"（没有我们自己加的框架词）
FRAME_WORDS = re.compile(r"(村庄|市镇|大区|省|意大利|分区|旧市镇|地名|姓氏)")


def parse(fr):
    """→ dict(kind, parent, prov_zh, reg_zh, unknown) 或 None（不是地理句式）"""
    m = COMMUNE.match(fr)
    if m:
        reg = (m.group("reg") or "").strip().rstrip(",.;")
        prov = (m.group("prov") or "").strip().rstrip(",.;")
        return {"kind": "commune",
                "reg": REGION_ZH.get(reg), "reg_raw": reg,
                "prov": PROV_ZH.get(prov), "prov_raw": prov}
    m = HAMEAU_A.match(fr) or HAMEAU_B.match(fr)
    if m:
        d = m.groupdict()
        reg = (d.get("reg") or "").strip()
        return {"kind": "hameau", "parent": (d.get("parent") or "").strip(),
                "reg": REGION_ZH.get(reg), "reg_raw": reg, "prov": None, "prov_raw": ""}
    return None


def compose(info, head_zh, parent_zh=None):
    """确定性拼中文。表里查不到的层**直接省略**，绝不猜。"""
    if info["kind"] == "commune":
        bits = []
        if info["reg"]:
            bits.append(info["reg"] + "大区")
        if info["prov"]:
            bits.append(info["prov"] + ("" if info["prov"].endswith("首都") else "省"))
        inner = "意大利" + "".join(bits) + "市镇" if bits else "意大利市镇"
        return "%s（%s）" % (head_zh, inner) if head_zh else ""
    # hameau —— 只用**一个**括号，母地名优先用库里已有的中文
    p = parent_zh or info.get("parent") or ""
    bits = []
    if info["reg"]:
        bits.append("意大利" + info["reg"] + "大区")
    bits.append("%s的村庄" % p if p else "村庄")
    inner = "，".join(bits)
    return "%s（%s）" % (head_zh, inner) if head_zh else inner
