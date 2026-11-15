"""다국어 메뉴판: 가게 정보의 메뉴 → 외국인 손님용 메뉴판 (영어·일본어·중국어 간체) → 인쇄용 A4 페이지.

원칙
- 설명 문장을 AI 로 지어내지 않는다. 메뉴판은 인쇄해서 붙이는 글이라, 가게 정보에 있는 값(재료·맵기·알레르기·가격)만 늘어놓는다.
- 메뉴 이름: ① 한국어 그대로(손님이 가리키며 주문) ② 로마자(코드가 변환, 국어의 로마자 표기법 기본 규칙) ③ 번역 이름.
  번역 이름과 재료 낱말은 **확인한 사전 → 사장님이 고친 값 → Papago** 순서로 고른다. 사전에 없고 Papago 키도 없으면 비워 두고 checks 에 남긴다.
- 알레르기는 사장님이 등록한 것만 보여 주고, 없으면 "직원에게 물어보세요"를 쓴다 ("알레르기 없음"이라고 쓰지 않음).
- Papago 로 만든 글은 다시 한국어로 번역(back)해서 사장님이 뜻을 확인하게 한다. 인쇄 페이지 아래에 "자동 번역" 표시.
- 메뉴 이름의 기준은 계약 규칙(StoreProfile 앞 7개 필드 = 이 모듈의 store.json)에 따라 store.json 이다.
  가게 정보에만 있는 메뉴는 checks 에 "계약(store.json)에 없는 메뉴"로 알린다.
"""
from __future__ import annotations

import html
from datetime import datetime

from app import profile as prof
from app.sources.papago import LANGS, Papago, TranslateError

LANG_NAMES = {"en": "English", "ja": "日本語", "zh-CN": "简体中文"}

# ── 로마자 (국어의 로마자 표기법 기본 규칙: 받침 이어 읽기, ㄹㄹ → ll. 자음 동화 등은 하지 않음) ──
_INIT = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
_MED = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i"]
_FIN = ["", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "p", "l", "m", "p", "p", "t", "t", "ng", "t", "t", "k", "t", "p", "t"]
# 받침이 뒤 음절 'ㅇ' 자리로 넘어갈 때 (이어 읽기)
_LINK = {1: "g", 2: "kk", 4: "n", 7: "d", 8: "r", 16: "m", 17: "b", 19: "s", 20: "ss", 22: "j", 23: "ch", 24: "k", 25: "t", 26: "p", 27: ""}


def romanize(text: str) -> str:
    def word(w: str) -> str:
        sy = [ord(c) - 0xAC00 for c in w]
        out = []
        for i, c in enumerate(sy):
            if not 0 <= c < 11172:
                out.append(w[i])
                continue
            ini, med, fin = c // 588, (c % 588) // 28, c % 28
            prev_linked = out and out[-1] == "\0"
            if prev_linked:
                out.pop()
            nxt = sy[i + 1] if i + 1 < len(sy) and 0 <= sy[i + 1] < 11172 else None
            head = "" if prev_linked else _INIT[ini]
            if prev_linked:
                head = _linked.pop()
            if ini == 5 and i > 0 and 0 <= sy[i - 1] < 11172 and sy[i - 1] % 28 == 8:
                head = "l"                                # ㄹ받침 + ㄹ → ll
            tail = _FIN[fin]
            if fin and nxt is not None and nxt // 588 == 11 and fin in _LINK:
                _linked.append(_LINK[fin])
                out.append(head + _MED[med])
                out.append("\0")
                continue
            out.append(head + _MED[med] + tail)
        return "".join(x for x in out if x != "\0")
    _linked: list[str] = []
    words = [word(w) for w in text.split()]
    return " ".join(w[:1].upper() + w[1:] for w in words if w)


# ── 확인한 사전 (합성 가게 3곳 메뉴 + 흔한 재료·알레르기) ──
NAMES = {
    "제육볶음 정식": ("Spicy Stir-fried Pork Set Meal", "豚肉の甘辛炒め定食", "辣炒猪肉套餐"),
    "된장찌개": ("Soybean Paste Stew", "テンジャンチゲ（韓国味噌チゲ）", "大酱汤"),
    "김치찌개": ("Kimchi Stew", "キムチチゲ", "泡菜汤"),
    "순두부찌개": ("Soft Tofu Stew", "スンドゥブチゲ", "嫩豆腐汤"),
    "불고기 덮밥": ("Bulgogi Rice Bowl", "プルコギ丼", "韩式烤肉盖饭"),
    "계란말이": ("Rolled Omelet", "韓国風卵焼き", "鸡蛋卷"),
    "후라이드": ("Fried Chicken", "フライドチキン", "原味炸鸡"),
    "양념치킨": ("Sweet & Spicy Fried Chicken", "ヤンニョムチキン", "甜辣炸鸡"),
    "반반": ("Half & Half (Fried + Sweet & Spicy)", "ハーフ＆ハーフ（フライド＋ヤンニョム）", "半半炸鸡（原味＋甜辣）"),
    "순살 치킨": ("Boneless Fried Chicken", "骨なしフライドチキン", "无骨炸鸡"),
    "치즈볼": ("Cheese Balls", "チーズボール", "芝士球"),
    "콜라": ("Cola", "コーラ", "可乐"),
    "아메리카노": ("Americano", "アメリカーノ", "美式咖啡"),
    "바닐라라떼": ("Vanilla Latte", "バニララテ", "香草拿铁"),
    "딸기 케이크": ("Strawberry Cake", "いちごケーキ", "草莓蛋糕"),
    "소금빵": ("Salt Bread", "塩パン", "盐面包"),
    "크로플": ("Croffle (Croissant Waffle)", "クロッフル", "可颂华夫"),
}
WORDS = {
    "돼지고기": ("pork", "豚肉", "猪肉"), "소고기": ("beef", "牛肉", "牛肉"), "닭고기": ("chicken", "鶏肉", "鸡肉"),
    "고추장": ("gochujang (red chili paste)", "コチュジャン", "韩式辣椒酱"), "양파": ("onion", "玉ねぎ", "洋葱"),
    "대파": ("green onion", "長ねぎ", "大葱"), "된장": ("soybean paste", "テンジャン（韓国味噌）", "大酱"),
    "두부": ("tofu", "豆腐", "豆腐"), "애호박": ("zucchini", "ズッキーニ", "西葫芦"), "감자": ("potato", "じゃがいも", "土豆"),
    "김치": ("kimchi", "キムチ", "泡菜"), "순두부": ("soft tofu", "おぼろ豆腐", "嫩豆腐"), "바지락": ("clams", "アサリ", "蛤蜊"),
    "달걀": ("egg", "卵", "鸡蛋"), "간장": ("soy sauce", "醤油", "酱油"), "당근": ("carrot", "にんじん", "胡萝卜"),
    "밀가루": ("wheat flour", "小麦粉", "面粉"), "물엿": ("corn syrup", "水あめ", "糖稀"), "치즈": ("cheese", "チーズ", "奶酪"),
    "찹쌀가루": ("glutinous rice flour", "もち米粉", "糯米粉"), "원두": ("coffee beans", "コーヒー豆", "咖啡豆"),
    "우유": ("milk", "牛乳", "牛奶"), "바닐라 시럽": ("vanilla syrup", "バニラシロップ", "香草糖浆"),
    "딸기": ("strawberry", "いちご", "草莓"), "생크림": ("whipped cream", "生クリーム", "鲜奶油"), "버터": ("butter", "バター", "黄油"),
    "소금": ("salt", "塩", "盐"), "크루아상 반죽": ("croissant dough", "クロワッサン生地", "可颂面团"), "시럽": ("syrup", "シロップ", "糖浆"),
    # 알레르기 유발 재료 (식품 알레르기 표시 대상에서 흔한 것)
    "대두": ("soybeans", "大豆", "大豆"), "밀": ("wheat", "小麦", "小麦"), "조개류": ("shellfish", "貝類", "贝类"),
    "땅콩": ("peanuts", "落花生", "花生"), "호두": ("walnuts", "くるみ", "核桃"), "잣": ("pine nuts", "松の実", "松子"),
    "새우": ("shrimp", "えび", "虾"), "게": ("crab", "かに", "蟹"), "메밀": ("buckwheat", "そば", "荞麦"),
    "고등어": ("mackerel", "さば", "鲭鱼"), "오징어": ("squid", "いか", "鱿鱼"), "토마토": ("tomato", "トマト", "番茄"),
    "복숭아": ("peach", "もも", "桃"), "아황산류": ("sulfites", "亜硫酸塩", "亚硫酸盐"),
}
_IDX = {lang: i for i, lang in enumerate(LANGS)}
UI = {
    "en": {"ing": "Ingredients", "all": "Contains", "ask": "Allergy info not registered — please ask our staff",
           "pop": "Popular", "spicy": ["Not spicy", "Mild", "Medium", "Hot"], "phr": "Useful phrases (show this to staff)",
           "foot": "This menu was translated automatically. If anything is unclear, please ask our staff.", "title": "Menu"},
    "ja": {"ing": "材料", "all": "アレルゲン", "ask": "アレルギー情報は未登録です。スタッフにお尋ねください",
           "pop": "おすすめ", "spicy": ["辛くない", "少し辛い", "辛い", "とても辛い"], "phr": "便利なひとこと（スタッフに見せてください）",
           "foot": "このメニューは自動翻訳です。ご不明な点はスタッフにお尋ねください。", "title": "メニュー"},
    "zh-CN": {"ing": "食材", "all": "含有过敏原", "ask": "过敏信息未登记，请询问店员",
              "pop": "推荐", "spicy": ["不辣", "微辣", "中辣", "特辣"], "phr": "常用语（请出示给店员）",
              "foot": "本菜单为自动翻译，如有疑问请询问店员。", "title": "菜单"},
}
PHRASES = [
    ("덜 맵게 해 주세요", ("Less spicy, please.", "辛さ控えめでお願いします。", "请少放辣。")),
    ("안 맵게 해 주세요", ("Not spicy at all, please.", "辛くしないでください。", "请不要放辣。")),
    ("포장해 주세요", ("To go, please.", "持ち帰りでお願いします。", "请打包。")),
    ("물 좀 주세요", ("Water, please.", "お水をください。", "请给我一杯水。")),
    ("이거 주세요", ("I'd like this one, please.", "これをください。", "我要这个。")),
    ("계산할게요", ("Check, please.", "お会計お願いします。", "我要结账。")),
]


def build(store: dict, p: prof.Profile, lang: str, papago: Papago | None = None) -> dict:
    """메뉴판 초안. 숫자·재료·알레르기는 가게 정보 그대로, 글자는 사전·사장님 고침·Papago 순서."""
    if lang not in LANGS:
        raise ValueError(f"lang 은 {', '.join(LANGS)} 중 하나입니다")
    papago = papago or Papago()
    i = _IDX[lang]
    ui = UI[lang]
    overrides = (p.foreign.overrides or {}).get(lang, {})
    contract_menu = set(store.get("menu") or [])
    checks: list[dict] = []
    used_papago = False

    def word(w: str, where: str) -> tuple[str, str | None]:
        nonlocal used_papago
        if w in WORDS:
            return WORDS[w][i], None
        try:
            t = papago.translate(w, lang)
            used_papago = True
            return t, papago.translate(t, "ko", source=lang)
        except TranslateError:
            checks.append({"menu": where, "kind": "untranslated", "text": f"'{w}' 번역이 없어 한국어로 둡니다 (사전·Papago 키 없음)"})
            return w, None

    items = []
    for m in p.menu:
        if m.sold_out:
            continue
        ov = overrides.get(m.name, {})
        back = None
        if ov.get("name"):
            name, src = ov["name"], "owner"
        elif m.name in NAMES:
            name, src = NAMES[m.name][i], "dictionary"
        else:
            try:
                name, src = papago.translate(m.name, lang), "papago"
                used_papago = True
                back = papago.translate(name, "ko", source=lang)
            except TranslateError:
                name, src = "", "none"
                checks.append({"menu": m.name, "kind": "untranslated", "text": "메뉴 이름 번역이 없어 로마자만 씁니다"})
        ingredients = [word(x, m.name) for x in m.ingredients]
        allergens = [word(x, m.name) for x in m.allergens]
        if m.name not in contract_menu:
            checks.append({"menu": m.name, "kind": "contract", "text": "계약(store.json) 메뉴에 없는 이름입니다. 통합 화면의 메뉴 목록에는 안 나옵니다"})
        if m.price is None:
            checks.append({"menu": m.name, "kind": "price", "text": "가격이 없어 메뉴판에 가격 칸을 비웁니다"})
        if not m.allergens:
            checks.append({"menu": m.name, "kind": "allergy", "text": "알레르기 재료가 등록되지 않아 '직원에게 물어보세요'로 씁니다"})
        items.append({
            "ko": m.name, "roman": romanize(m.name), "name": name, "name_source": src, "name_back": back,
            "price": m.price, "price_text": f"₩{m.price:,}" if m.price is not None else "",
            "spicy": m.spicy, "spicy_text": ui["spicy"][m.spicy],
            "ingredients": [t for t, _ in ingredients], "ingredients_back": [b for _, b in ingredients if b],
            "allergens": [t for t, _ in allergens], "allergy_text": (f"{ui['all']}: " + ", ".join(t for t, _ in allergens)) if allergens else ui["ask"],
            "description": (f"{ui['ing']}: " + ", ".join(t for t, _ in ingredients)) if ingredients else "",
            "description_override": ov.get("desc"), "recommended": m.recommended,
        })
    store_name = store.get("name", "").replace("(가상)", "").strip()
    return {"store_id": p.store_id, "lang": lang, "lang_name": LANG_NAMES[lang], "store_name": store_name,
            "store_roman": romanize(store_name), "title": ui["title"], "items": items,
            "phrases": [{"ko": ko, "text": t[i]} for ko, t in PHRASES], "labels": ui,
            "checks": checks, "papago_used": used_papago, "papago_available": papago.available,
            "demo": not papago.available, "data_origin": p.data_origin,
            "note": "자동 번역입니다. 인쇄 전에 메뉴 이름·가격·알레르기를 확인해 주세요"}


def render(menu: dict, now: datetime) -> str:
    """인쇄용 A4 한 장 (브라우저 '인쇄 → PDF로 저장'). 서버에서 PDF 를 만들지 않아 일본어·중국어 글꼴 문제가 없다."""
    e = html.escape
    ui = menu["labels"]
    rows = []
    for it in menu["items"]:
        desc = it["description_override"] or it["description"]
        chili = "●" * it["spicy"] + "○" * (3 - it["spicy"])
        rows.append(f"""<article class="item">
  <div class="top"><div><div class="ko">{e(it['ko'])}</div><div class="tr">{e(it['name'] or it['roman'])}</div>
    <div class="ro">{e(it['roman'])}</div></div><div class="price">{e(it['price_text'])}</div></div>
  {f'<div class="desc">{e(desc)}</div>' if desc else ''}
  <div class="meta"><span class="sp" title="{e(it['spicy_text'])}">{chili} {e(it['spicy_text'])}</span>{f'<span class="pop">★ {e(ui["pop"])}</span>' if it['recommended'] else ''}</div>
  <div class="al{'' if it['allergens'] else ' ask'}">{e(it['allergy_text'])}</div>
</article>""")
    phrases = "".join(f'<div class="ph"><b>{e(x["text"])}</b><span>{e(x["ko"])}</span></div>' for x in menu["phrases"])
    demo = '<div class="demo">예시 번역 (Papago 키 없음) · 시연용 가상 가게</div>' if menu["demo"] else ""
    return f"""<!doctype html><html lang="{e(menu['lang'])}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(menu['store_roman'])} {e(menu['title'])}</title>
<style>
  @page {{ size: A4; margin: 12mm; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:#fff; color:#111; font:14px/1.45 -apple-system, "Noto Sans", "Noto Sans KR", "Noto Sans JP", "Noto Sans SC", "Apple SD Gothic Neo", "Malgun Gothic", "Hiragino Sans", "Microsoft YaHei", sans-serif; }}
  .page {{ max-width:186mm; margin:0 auto; padding:8px; }}
  header {{ display:flex; justify-content:space-between; align-items:flex-end; border-bottom:3px solid #111; padding-bottom:6px; margin-bottom:10px; }}
  h1 {{ font-size:26px; margin:0; letter-spacing:-0.01em; }} .sub {{ color:#555; font-size:13px; }}
  .demo {{ background:#fff3dc; color:#7a4a00; font-size:12px; padding:4px 8px; border-radius:6px; margin-bottom:8px; }}
  .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:8px 14px; }}
  .item {{ border-bottom:1px solid #ddd; padding:6px 0 8px; break-inside:avoid; }}
  .top {{ display:flex; justify-content:space-between; gap:8px; }}
  .ko {{ font-size:18px; font-weight:800; }} .tr {{ font-size:15px; font-weight:700; }} .ro {{ color:#666; font-size:12px; }}
  .price {{ font-size:17px; font-weight:800; white-space:nowrap; }}
  .desc {{ font-size:12.5px; margin-top:3px; }} .meta {{ font-size:12px; margin-top:3px; display:flex; gap:10px; }}
  .sp {{ color:#b42318; }} .pop {{ color:#0a6b43; font-weight:700; }}
  .al {{ font-size:12px; margin-top:2px; color:#333; }} .al.ask {{ color:#7a4a00; }}
  .phrases {{ margin-top:12px; border:2px solid #111; border-radius:8px; padding:8px 10px; break-inside:avoid; }}
  .phrases h2 {{ font-size:14px; margin:0 0 6px; }}
  .ph {{ display:inline-flex; flex-direction:column; width:32%; margin:2px 0; vertical-align:top; }} .ph b {{ font-size:14px; }} .ph span {{ font-size:12px; color:#555; }}
  footer {{ margin-top:10px; font-size:11px; color:#555; display:flex; justify-content:space-between; }}
  @media (max-width:600px) {{ .grid {{ grid-template-columns:1fr; }} .ph {{ width:48%; }} }}
</style></head><body><div class="page">
{demo}
<header><div><h1>{e(menu['store_roman'])} · {e(menu['title'])}</h1><div class="sub">{e(menu['store_name'])} · {e(menu['lang_name'])}</div></div><div class="sub">{e(now.strftime('%Y-%m-%d'))}</div></header>
<section class="grid">{''.join(rows)}</section>
<section class="phrases"><h2>{e(ui['phr'])}</h2>{phrases}</section>
<footer><span>{e(ui['foot'])}</span><span>자동 번역 · 가게 정보 기준</span></footer>
</div></body></html>"""
