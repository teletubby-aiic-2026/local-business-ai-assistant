"""다국어 메뉴판 시험. Papago 는 가짜 응답으로, 키·네트워크 없이 돈다."""
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import classify, foreign_menu, profile as prof, service
from app.classify import Classifier
from app.sources import capture
from app.sources.papago import Papago

API = "/api/review-insight"


@pytest.fixture(autouse=True)
def tmp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "RUNTIME", tmp_path / "runtime")
    monkeypatch.setattr(classify, "RUNTIME_CACHE", tmp_path / "runtime.json")
    monkeypatch.setattr(capture, "USAGE_LOG", tmp_path / "logs" / "llm_usage.jsonl")
    for k in ("PAPAGO_CLIENT_ID", "PAPAGO_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def client(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "_classifier", Classifier("mock"))
    return TestClient(main.app)


@pytest.mark.parametrize("ko,roman", [("제육볶음 정식", "Jeyukbokkeum Jeongsik"), ("계란말이", "Gyeranmari"), ("설렁탕", "Seolleongtang"),
                                      ("불고기 덮밥", "Bulgogi Deopbap"), ("닭갈비", "Dakgalbi"), ("소금빵", "Sogeumppang")])
def test_romanize(ko, roman):
    assert foreign_menu.romanize(ko) == roman


def test_menu_names_follow_contract_store_json():
    """계약 규칙: StoreProfile 의 메뉴 이름은 이 모듈의 store.json 그대로 → 가게 정보 예시의 메뉴 이름도 같아야 한다."""
    for store_id in service.store_ids():
        assert [m.name for m in prof.load(store_id).menu] == service.store(store_id)["menu"]
    root = Path(__file__).resolve().parents[3]
    if (root / "shared" / "sample_scenario.py").exists():      # C1 샘플 가게의 가격(menu_prices)과도 같게
        sys.path.insert(0, str(root))
        try:
            from shared.sample_scenario import SAMPLE_STORE
        finally:
            sys.path.remove(str(root))
        ours = {m.name: m.price for m in prof.load(SAMPLE_STORE.store_id).menu}
        assert ours == SAMPLE_STORE.menu_prices


@pytest.mark.parametrize("lang", ["en", "ja", "zh-CN"])
def test_demo_menu_uses_checked_dictionary_only(lang):
    m = foreign_menu.build(service.store("store_ongi"), prof.load("store_ongi"), lang, Papago())
    assert m["demo"] and not m["papago_used"] and len(m["items"]) == 6
    assert not [c for c in m["checks"] if c["kind"] in ("untranslated", "contract", "price")]
    jeyuk = m["items"][0]
    assert jeyuk["roman"] == "Jeyukbokkeum Jeongsik" and jeyuk["price_text"] == "₩9,500" and jeyuk["spicy"] == 2
    assert jeyuk["name"] == foreign_menu.NAMES["제육볶음 정식"][foreign_menu._IDX[lang]]
    assert all("돼지고기" not in a for a in jeyuk["allergens"])          # 알레르기 이름도 번역


def test_unregistered_allergy_says_ask_staff_not_none():
    p = prof.load("store_basak")
    m = foreign_menu.build(service.store("store_basak"), p, "en", Papago())
    cola = next(i for i in m["items"] if i["ko"] == "콜라")
    assert cola["allergy_text"].startswith("Allergy info not registered") and any(c["menu"] == "콜라" and c["kind"] == "allergy" for c in m["checks"])


def test_unknown_menu_without_papago_is_romanized_and_flagged():
    p = prof.load("store_ongi")
    p.menu.append(prof.MenuItem(name="물냉면", price=9000, ingredients=["메밀"], allergens=["메밀"]))
    m = foreign_menu.build(service.store("store_ongi"), p, "en", Papago())
    item = m["items"][-1]
    assert item["roman"] == "Mulnaengmyeon" and item["name"] == "" and item["allergens"] == ["buckwheat"]
    kinds = {c["kind"] for c in m["checks"] if c["menu"] == "물냉면"}
    assert kinds == {"untranslated", "contract"}


def test_sold_out_items_are_not_printed():
    p = prof.load("store_ongi")
    p.menu[5].sold_out = True
    assert "계란말이" not in [i["ko"] for i in foreign_menu.build(service.store("store_ongi"), p, "en", Papago())["items"]]


def test_papago_used_for_unknown_words_with_back_translation_and_cache():
    calls = []

    def handle(request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.headers["X-NCP-APIGW-API-KEY-ID"] == "id" and request.headers["X-NCP-APIGW-API-KEY"] == "secret"
        out = {"물냉면": "Cold Buckwheat Noodles", "Cold Buckwheat Noodles": "차가운 메밀국수", "육수": "broth", "broth": "국물"}[body["text"]]
        return httpx.Response(200, json={"message": {"result": {"srcLangType": body["source"], "tarLangType": body["target"], "translatedText": out}}})
    pg = Papago("id", "secret", transport=httpx.MockTransport(handle))
    p = prof.load("store_ongi")
    p.menu.append(prof.MenuItem(name="물냉면", price=9000, ingredients=["육수", "메밀"], allergens=["메밀"]))
    m = foreign_menu.build(service.store("store_ongi"), p, "en", pg)
    item = m["items"][-1]
    assert item["name"] == "Cold Buckwheat Noodles" and item["name_source"] == "papago" and item["name_back"] == "차가운 메밀국수"
    assert item["description"] == "Ingredients: broth, buckwheat" and m["papago_used"] and not m["demo"]
    n = len(calls)
    foreign_menu.build(service.store("store_ongi"), p, "en", pg)
    assert len(calls) == n                                                  # 저장본을 다시 씀
    log = (service.RUNTIME.parent / "logs" / "llm_usage.jsonl").read_text(encoding="utf-8")
    assert "물냉면" not in log and '"purpose": "menu_translate"' in log     # 번역할 글은 기록에 남기지 않음


def test_owner_override_and_api(client):
    r = client.put(f"{API}/profile", json={"changes": {"foreign": {"languages": ["en"], "overrides": {"en": {"제육볶음 정식": {"name": "Jeyuk Set (spicy pork)"}}}}}})
    assert r.status_code == 200
    m = client.get(f"{API}/menu/foreign", params={"lang": "en"}).json()
    assert m["items"][0]["name"] == "Jeyuk Set (spicy pork)" and m["items"][0]["name_source"] == "owner"
    assert client.get(f"{API}/menu/foreign", params={"lang": "fr"}).status_code == 400
    bad = client.put(f"{API}/profile", json={"changes": {"foreign": {"overrides": {"fr": {}}}}})
    assert bad.status_code == 400


def test_print_page_is_a4_and_escapes(client):
    client.put(f"{API}/profile", json={"changes": {"menu": [{"name": "<script>x</script>", "price": 1000}]}})
    page = client.get(f"{API}/menu/foreign/print", params={"lang": "ja"})
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    text = page.text
    assert "size: A4" in text and "<script>x</script>" not in text and "&lt;script&gt;" in text
    assert "₩1,000" in text and "自動翻訳" in text and "예시 번역" in text
