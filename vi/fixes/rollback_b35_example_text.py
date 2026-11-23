#!/usr/bin/env python3
"""B35 回滚：vi 的 10 条例句 `text` 不该改。2026-11-23。

═══ 为什么回滚 ═══
vi 的页面读的是 **`example.text_pub`**（出版层，`vietnamese.ts` 的 `x.text_pub AS text`），
不是 `text`。这 10 条的 `text_pub` 本来就干净（模板残渣只留在证据层的 `text` 里）——
**读者从来没看到过它们**。
而 `text` 是「源头原文」，外锚闸（`vi/pipeline/verify_layers_vs_dump.py`）**逐字锚 dump**，
W22 结清后它的预期是「`text` 原地改过 = 0 行」。改它会把那道闸弄红，也违反
`[[source-typo-fix-ours-not-quote]]`（证据层不动）。
⇒ 把 `text` 还原成源头原文；页面继续读干净的 `text_pub`。

⚠️ 同一天对其他八门（en/it/fr/pt/de/ja）的修复**是对的**：它们没有 `text_pub`，
页面读的就是 `text`。

用法：
    python3 -u fixes/rollback_b35_example_text.py            # 只核对
    python3 -u fixes/rollback_b35_example_text.py --apply    # 落库
"""
import argparse
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "pipeline"))

import dbtool                                              # noqa: E402

# (原文, 修复后) —— 从 B35 那次修复的清单照抄，脚本自包含（主修复脚本已移除 vi 项）。
VI = {
    74721: ('Họ thực thi công cuộc cứu tế, nhờ Ba-na-ba và Sau-lơ chuyển giao tặng phẩm cho các trưởng lão. 그들은 그대로 실행해서, 바나바와 사울 편에 그것을 장로들에게 보냈다. {{따옴|사도행전 11장 30절}', 'Họ thực thi công cuộc cứu tế, nhờ Ba-na-ba và Sau-lơ chuyển giao tặng phẩm cho các trưởng lão. 그들은 그대로 실행해서, 바나바와 사울 편에 그것을 장로들에게 보냈다.'),
    74734: ('Hãy phó các việc mình cho Ðức Giê-hô-va, Thì những mưu ý mình sẽ được thành công. 너의 행사를 여호와께 맡기라 그리하면 너의 경영하는 것이 이루리라. {{따옴|잠언 16장 3절}', 'Hãy phó các việc mình cho Ðức Giê-hô-va, Thì những mưu ý mình sẽ được thành công. 너의 행사를 여호와께 맡기라 그리하면 너의 경영하는 것이 이루리라.'),
    74832: ('Phi-e-rơ tiếp tục giảng dạy, trình bày nhiều bằng chứng rồi khích lệ: Anh chị em hãy thoát ly thế hệ gian tà này! 베드로는 이 밖에도 여러 가지 증거를 들어 그들을 설득시키고 이 사악한 세대가 받을 벌을 면하도록 하라고 권하였다. {{따옴|사도행전 2장 40절}', 'Phi-e-rơ tiếp tục giảng dạy, trình bày nhiều bằng chứng rồi khích lệ: Anh chị em hãy thoát ly thế hệ gian tà này! 베드로는 이 밖에도 여러 가지 증거를 들어 그들을 설득시키고 이 사악한 세대가 받을 벌을 면하도록 하라고 권하였다.'),
    74911: ('Vì ta là Ðức Giê-hô-va, ta không hề thay đổi bởi cớ đó, các ngươi là con trai Gia-cốp, chẳng bị diệt vong. 나는 여호와이다. 나는 변하지 않는다. 그러므로 너희 야곱의 자손은 멸망하지 않는다. {{따옴|말라기 3장 6절}', 'Vì ta là Ðức Giê-hô-va, ta không hề thay đổi bởi cớ đó, các ngươi là con trai Gia-cốp, chẳng bị diệt vong. 나는 여호와이다. 나는 변하지 않는다. 그러므로 너희 야곱의 자손은 멸망하지 않는다.'),
    75354: ('Ðức Giê-hô-va thi hành sự công bình Và sự ngay thẳng cho mọi người bị hà hiếp. 여호와께서 의로운 일을 행하시며 압박 당하는 모든 자를 위하여 판단하시는도다. {{따옴|시편 103편 6절}', 'Ðức Giê-hô-va thi hành sự công bình Và sự ngay thẳng cho mọi người bị hà hiếp. 여호와께서 의로운 일을 행하시며 압박 당하는 모든 자를 위하여 판단하시는도다.'),
    75547: ('Vậy bây giờ hỡi các con ta, hãy lắng nghe, Hãy lưu tâm đến lời ta dạy bảo.이제 아들들아 내 말을 듣고 내 입의 말에 주의하라. {{따옴|잠언 7장 24절}', 'Vậy bây giờ hỡi các con ta, hãy lắng nghe, Hãy lưu tâm đến lời ta dạy bảo.이제 아들들아 내 말을 듣고 내 입의 말에 주의하라.'),
    75778: ('Giữa thành phố có một cái tháp vững bền, hết thảy dân sự của thành, nam và nữ, đều chạy vô núp tại đó, và đóng cửa lại, rồi lên trên đỉnh tháp. 성중에 견고한 망대가 있으므로 그 성 백성의 남녀가 모두 그리로 도망하여 들어가서 문을 잠그고 망대 꼭대기로 올라간지라. {{따옴|사사기 9장 51절}', 'Giữa thành phố có một cái tháp vững bền, hết thảy dân sự của thành, nam và nữ, đều chạy vô núp tại đó, và đóng cửa lại, rồi lên trên đỉnh tháp. 성중에 견고한 망대가 있으므로 그 성 백성의 남녀가 모두 그리로 도망하여 들어가서 문을 잠그고 망대 꼭대기로 올라간지라.'),
    76298: ('Ngài sẽ khởi tố Ít-ra-ên. 주님께서 이스라엘을 고소하신다. {{따옴|미가서 6장 2절}', 'Ngài sẽ khởi tố Ít-ra-ên. 주님께서 이스라엘을 고소하신다.'),
    76502: ('Đa-vít thu hồi tất cả những gì người A-ma-léc đã cướp được, và cũng giải cứu hai vợ mình nữa. 다윗이 아말렉 사람의 취하였던 모든 것을 도로 찾고 그 두 아내를 구원하였고. {{따옴|사무엘상 30장 18절}', 'Đa-vít thu hồi tất cả những gì người A-ma-léc đã cướp được, và cũng giải cứu hai vợ mình nữa. 다윗이 아말렉 사람의 취하였던 모든 것을 도로 찾고 그 두 아내를 구원하였고.'),
    76558: ('Bản sao của chiếu chỉ được lưu hành như một đạo luật công bố cho tất cả các dân tộc trong mỗi tỉnh để họ chuẩn bị sẵn sàng cho ngày đó. 이 명령을 각 지방에 전하기 위하여 조서의 초본을 모든 민족에게 선포하여 그 날을 위하여 준비하게 하라 하였더라. {{따옴|에스더 3장 14절}', 'Bản sao của chiếu chỉ được lưu hành như một đạo luật công bố cho tất cả các dân tộc trong mỗi tỉnh để họ chuẩn bị sẵn sàng cho ngày đó. 이 명령을 각 지방에 전하기 위하여 조서의 초본을 모든 민족에게 선포하여 그 날을 위하여 준비하게 하라 하였더라.'),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(f"file:{dbtool.DB}?mode=ro", uri=True)
    try:
        for i, (old, new) in VI.items():
            got = c.execute("SELECT text FROM example WHERE id=?", (i,)).fetchone()
            if not got or got[0] != new:
                raise SystemExit(f"🔴 id={i} 当前值不是修复后的值，拒绝回滚：{got!r}")
        print(f"vi: {len(VI)} 条待还原为源头原文")
    finally:
        c.close()
    if not a.apply:
        print("(dry：核对通过，未写库)")
        return
    with dbtool.session("b35-vi-rollback-example-text", small=len(VI)) as s:
        for i, (old, new) in VI.items():
            s.execute("UPDATE example SET text=? WHERE id=? AND text=?", (old, i, new))
    print(f"✓ 已还原 {len(VI)} 行")


if __name__ == "__main__":
    main()
