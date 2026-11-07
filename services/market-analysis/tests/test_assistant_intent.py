"""Question classifier for the assistant. No network, no model, no raw statistics."""
from datetime import date
import json
from pathlib import Path
import unittest

from app.assistant.intent import DEFAULT_TOPICS, TOPIC_ORDER, classify, industry_codes, location_labels
from app.assistant.lexicon import industry_index, place_index
from app.assistant.morph import morph_enabled

try:
    import kiwipiepy  # noqa: F401
    HAS_KIWI = morph_enabled()  # ASSISTANT_MORPH=off also skips the Kiwi-only tests
except ImportError:
    HAS_KIWI = False

TODAY = date(2026, 11, 7)
CASES = Path(__file__).resolve().parent / "assistant_intent_cases.json"


def rules(text, **kwargs):
    return classify(text, today=TODAY, use_morph=False, **kwargs)


class LexiconTests(unittest.TestCase):
    def test_every_alias_points_to_an_official_place_or_industry(self):
        # Building the indexes raises on any alias that names an unknown target.
        self.assertIn("홍대", place_index())
        self.assertIn("카페", industry_index())
        for places in place_index().values():
            for place in places:
                self.assertIn(place["kind"], ("station", "neighborhood", "district"))
        for rows in industry_index().values():
            for row in rows:
                self.assertRegex(row["code"], r"^CS\d{6}$")

    def test_longest_match_prefers_the_station_over_its_bare_name(self):
        self.assertEqual(location_labels(rules("강남역 카페 매출")), ["강남역"])
        self.assertEqual(location_labels(rules("강남 카페 매출")), ["강남구", "강남역"])

    def test_numbered_neighbourhoods_are_grouped_and_duplicates_keep_their_district(self):
        self.assertEqual(location_labels(rules("망원동 매출")), ["망원1동", "망원2동"])
        self.assertEqual(location_labels(rules("신사동 매출")), ["신사동(강남구)", "신사동(관악구)"])
        self.assertEqual(location_labels(rules("역삼1동 매출")), ["역삼1동"])

    def test_common_words_that_equal_a_bare_station_name_are_not_places(self):
        self.assertEqual(rules("남성 손님이 많아?")["slots"]["locations"], [])
        # 서울역 and 서울역(경의선) are different stations in the list, so both are candidates.
        self.assertEqual(location_labels(rules("서울역 근처 카페")), ["서울역", "서울역(경의선)"])

    def test_parenthesised_station_names_and_bare_neighbourhood_names(self):
        self.assertEqual(location_labels(rules("잠실역 편의점")), ["잠실역(송파구청)"])
        self.assertEqual(location_labels(rules("을지로 호프집")), ["을지로동"])
        self.assertEqual(industry_codes(rules("할인쿠폰 문구 만들어줘")), [])
        self.assertEqual(industry_codes(rules("문구점 몇 개야")), ["CS300021"])


class ClassificationTests(unittest.TestCase):
    def test_result_shape_follows_team_conventions(self):
        result = rules("요즘 손님이 줄었나?")
        for key in ("schema_version", "domain", "turn_type", "topics", "slots", "signals",
                    "needs_user_choice", "needs_model", "analyzer", "reasons"):
            self.assertIn(key, result)
        self.assertEqual(set(result["slots"]["period"]), {"relative", "comparison", "period_code"})
        self.assertTrue(set(result["topics"]) <= set(TOPIC_ORDER))
        self.assertEqual(result["analyzer"], "rules")
        json.dumps(result, ensure_ascii=False)  # must be serialisable as-is

    def test_vague_market_question_gets_the_default_topic_bundle(self):
        result = rules("홍대 쪽 술집 상권 어때?")
        self.assertEqual(result["topics"], list(DEFAULT_TOPICS))
        self.assertTrue(result["topics_defaulted"])
        self.assertTrue(result["needs_user_choice"])
        self.assertEqual(industry_codes(result), ["CS100009"])

    def test_correction_keeps_only_the_new_location_and_industry(self):
        result = rules("강남역 말고 역삼역으로 바꿔줘")
        self.assertEqual(result["turn_type"], "condition_change")
        self.assertEqual(location_labels(result), ["역삼역"])
        self.assertFalse(result["needs_user_choice"])
        self.assertEqual(industry_codes(rules("카페 말고 베이커리로 볼래")), ["CS100005"])

    def test_period_expressions(self):
        self.assertEqual(rules("2025년 3분기 기준으로 보여줘")["slots"]["period"]["period_code"], "20253")
        self.assertEqual(rules("올해 1분기 매출")["slots"]["period"]["period_code"], "20261")
        last_year = rules("작년 3분기 매출")["slots"]["period"]
        self.assertEqual((last_year["period_code"], last_year["comparison"]), ("20253", None))
        self.assertEqual(rules("지난 분기보다 늘었어?")["slots"]["period"]["comparison"], "qoq")
        self.assertEqual(rules("요즘 매출")["slots"]["period"]["relative"], "latest")

    def test_area_comparison_is_not_confused_with_period_comparison_or_franchise(self):
        self.assertIn("comparison", rules("연남동이랑 서교동 비교해 줘")["topics"])
        self.assertNotIn("comparison", rules("작년이랑 비교하면 매출 어때?")["topics"])
        self.assertNotIn("comparison", rules("이 근처에 프랜차이즈가 많아?")["topics"])
        self.assertTrue(rules("옆 동네랑 비교해 줘")["needs_user_choice"])

    def test_other_domains_are_handed_off_without_market_topics(self):
        self.assertEqual(rules("리뷰에 불만 글이 달렸어")["domain"], "customer")
        marketing = rules("인스타 홍보글 써줘")
        self.assertEqual((marketing["domain"], marketing["turn_type"], marketing["topics"]), ("marketing", "handoff", []))
        self.assertEqual(rules("손님 늘릴 방법 없을까?")["turn_type"], "advice")
        self.assertEqual(rules("임대료는 얼마 정도야?")["turn_type"], "out_of_scope")

    def test_slot_markers_questions_and_venting(self):
        # '로 보여' after 요일별 is not a condition change; after a place it is.
        self.assertEqual(rules("종로구 한식 매출 요일별로 보여주세요")["turn_type"], "data_question")
        self.assertEqual(rules("역삼역으로 보여줘")["turn_type"], "condition_change")
        self.assertIn("stores_count", rules("건대입구역 미용실수 지난분기대비 늘었나요")["topics"])
        self.assertEqual(rules("강남역 카페 아메리카노 얼마 받는게 적당할까요")["turn_type"], "out_of_scope")
        self.assertEqual(rules("장사가 너무 안돼서 접을까 싶네요 대출 이자도 밀리고")["turn_type"], "smalltalk")
        mixed = rules("별점 낮은 리뷰 때문에 손님 줄은 거 같은데 쿠폰 이벤트라도 해야되나")
        self.assertEqual((mixed["domain"], mixed["needs_model"]), ("marketing", True))

    def test_followup_inherits_previous_topics(self):
        result = rules("그럼 작년이랑은?", context={"previous_topics": ["sales_weekday"]})
        self.assertEqual(result["turn_type"], "followup")
        self.assertEqual(result["topics"], ["sales_weekday", "change_yoy"])
        self.assertEqual(rules("그럼 작년이랑은?")["turn_type"], "data_question")

    def test_personal_figures_are_flagged_and_unclear_requests_go_to_the_model(self):
        own = rules("우리 가게는 지난달보다 매출이 20% 줄었어요")
        self.assertEqual(own["turn_type"], "personal_metric")
        self.assertTrue(own["signals"]["personal_metric"])
        self.assertTrue(rules("ㅁㄴㅇㄹ")["needs_model"])

    def test_ranking_questions_are_answered_by_code(self):
        where = rules("커피숍 창업하려는데 어디가 좋아?")
        self.assertEqual((where["turn_type"], where["topics"], where["needs_model"]), ("ranking", ["ranking"], False))
        for text in ("서울에서 카페 매출 제일 높은 상권 어디야?", "매출 높은 곳 알려줘", "패스트푸드 잘 되는 동네 추천해줘",
                     "어디가 장사 잘 돼?", "카페 매출 순위 보여줘", "카페 잘되는 곳"):
            self.assertEqual(rules(text)["turn_type"], "ranking", text)
        # A place inside the question limits the ranking to its 구.
        self.assertEqual(location_labels(rules("마포구에서 카페 어디가 제일 괜찮을까요")), ["마포구"])
        # Not rankings: a distribution of one market, a yes/no question, two named places, two industries.
        self.assertEqual(rules("홍대에서 매출 제일 높은 시간대 알려줘")["topics"], ["sales_time"])
        self.assertEqual(rules("요일별 매출 순위")["topics"], ["sales_weekday"])
        self.assertEqual(rules("홍대 유동인구 많은 곳이야?")["turn_type"], "data_question")
        self.assertIn("comparison", rules("홍대랑 합정 중에 어디가 좋아?")["topics"])
        self.assertEqual(rules("노원구 분식집이랑 치킨집 중에 어느 쪽이 더 많아")["turn_type"], "data_question")

    def test_places_followed_by_malgo_are_excluded_from_a_ranking(self):
        result = rules("강남 말고는 서울에 매출액 높은 곳 추천해줘")
        self.assertEqual(result["turn_type"], "ranking")
        self.assertEqual(result["slots"]["locations"], [])
        self.assertEqual([m["text"] for m in result["slots"]["excluded_locations"]], ["강남"])
        other = rules("강남역 말고 다른 데 추천해줘")
        self.assertEqual((other["turn_type"], [m["text"] for m in other["slots"]["excluded_locations"]]), ("ranking", ["강남역"]))
        scoped = rules("강남 말고 홍대 근처에서 카페 잘되는 곳")
        self.assertEqual([m["text"] for m in scoped["slots"]["locations"]], ["홍대"])
        self.assertEqual([m["text"] for m in scoped["slots"]["excluded_locations"]], ["강남"])
        # Outside a ranking '말고' is still a correction.
        self.assertEqual(rules("강남역 말고 역삼역으로 바꿔줘")["slots"]["excluded_locations"], [])

    def test_industry_recommendations_are_recognised_with_and_without_kiwi(self):
        cases = {"추천해줄만한 업종 3가지 말해줘": 3, "무슨 가게 차리면 좋아?": None, "장사 잘 되는 업종이 뭐야?": None,
                 "뭘 하면 돈이 될까": None, "유망한 업종 알려줘": None, "여기서 뭐 하면 장사 잘 될까?": None,
                 "홍대에서 추천 업종 top5": 5, "업종 두 가지만 골라줘": 2}
        for text, count in cases.items():
            result = rules(text)
            self.assertEqual((result["turn_type"], result["topics"], result["slots"]["count"]),
                             ("industry_rank", ["industry_rank"], count), text)
        self.assertEqual(location_labels(rules("홍대 가게 뭐가 잘돼?")), ["서교동", "홍대입구역"])
        excluded = rules("카페 말고 다른 업종 추천해줘")
        self.assertEqual([m["text"] for m in excluded["slots"]["excluded_industries"]], ["카페"])
        self.assertEqual(excluded["slots"]["industries"], [], "an excluded industry never becomes a condition")
        # A named industry or a plain '장사 잘 돼?' is a question about that business, not a recommendation.
        for text in ("카페 장사 잘 돼?", "장사 잘 돼?", "요즘 장사 어떤가요?", "뭐 하면 돼?"):
            self.assertNotEqual(rules(text)["turn_type"], "industry_rank", text)

    def test_complaints_and_weather_are_not_market_questions(self):
        for text in ("바보", "너 멍청하다", "그게 아니잖아"):
            self.assertEqual((rules(text)["domain"], rules(text)["turn_type"]), ("general", "smalltalk"), text)
        self.assertEqual(rules("오늘 날씨 어때?")["turn_type"], "out_of_scope")


@unittest.skipUnless(HAS_KIWI, "kiwipiepy is not installed (pip install -r requirements-assistant.txt) or ASSISTANT_MORPH=off")
class KiwiTests(unittest.TestCase):
    def kiwi(self, text, **kwargs):
        return classify(text, today=TODAY, use_morph=True, **kwargs)

    def test_kiwi_finds_the_same_industry_recommendations(self):
        for text in ("추천해줄만한 업종 3가지 말해줘", "여기서 뭐 하면 장사 잘 될까?", "무슨 가게 차리면 좋아?"):
            self.assertEqual(self.kiwi(text)["turn_type"], "industry_rank", text)
        self.assertNotEqual(self.kiwi("카페 장사 잘 돼?")["turn_type"], "industry_rank")

    def test_analyzer_is_reported(self):
        self.assertEqual(self.kiwi("매출 어때")["analyzer"], "kiwi")

    def test_verb_lemmas_separate_decrease_from_queue(self):
        self.assertTrue(self.kiwi("손님이 줄었나요?")["signals"]["change"])
        self.assertFalse(self.kiwi("줄 서는 가게가 많아?")["signals"]["change"])
        self.assertTrue(self.kiwi("경쟁 가게가 많아졌어?")["signals"]["change"])

    def test_correction_requires_the_verb_not_a_word_that_contains_it(self):
        self.assertTrue(self.kiwi("카페 말고 베이커리로 볼래")["signals"]["correction"])
        self.assertFalse(self.kiwi("말고기 집 매출 어때?")["signals"]["correction"])
        # The rule-only path cannot tell these apart; this is why Kiwi is used.
        self.assertTrue(rules("말고기 집 매출 어때?")["signals"]["correction"])


class EvaluationSetTests(unittest.TestCase):
    def test_case_file_uses_only_declared_labels(self):
        data = json.loads(CASES.read_text(encoding="utf-8"))
        labels = data["labels"]
        ids = [case["id"] for case in data["cases"]]
        self.assertEqual(len(ids), len(set(ids)))
        for case in data["cases"]:
            expect = case["expect"]
            if "domain" in expect:
                self.assertIn(expect["domain"], labels["domain"], case["id"])
            if "turn_type" in expect:
                self.assertIn(expect["turn_type"], labels["turn_type"], case["id"])
            for topic in expect.get("topics", []):
                self.assertIn(topic, labels["topics"], case["id"])


if __name__ == "__main__":
    unittest.main()
