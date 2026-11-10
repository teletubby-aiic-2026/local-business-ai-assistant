"""리뷰 분류 벤치마크 v1 만들기: data/benchmark/v1/source/{dev,test}.txt → reviews_*.json · labels_*.json · stores.json

services/review-insight 에서:  python -m scripts.make_benchmark
- 원본(.txt)은 사람이 읽고 고치기 쉬운 한 줄 형식입니다 (형식은 source/dev.txt 맨 위).
- 날짜·시각은 리뷰 번호로 정해서(난수 씨앗 고정) 다시 만들어도 같습니다. 글에 '점심', '저녁', '새벽'이 있으면 그 시간대로 둡니다.
- 정답이 형식에 맞는지(주제 사전, 감정과 칭찬/불만이 서로 맞는지) 검사하고, 틀리면 멈춥니다.
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "data" / "benchmark" / "v1"
KST = timezone(timedelta(hours=9))
sys.path.insert(0, str(ROOT))
from app.topics import TOPIC_IDS  # noqa: E402

STORES = {
    "hs": {"store_id": "bench_gaon", "name": "가온밥상 (가상)", "business_type": "korean", "business_type_name": "한식음식점",
           "menu": ["제육볶음", "된장찌개", "김치찌개", "불고기덮밥", "계란말이", "돈까스"]},
    "ck": {"store_id": "bench_noeul", "name": "노을치킨 (가상)", "business_type": "chicken", "business_type_name": "치킨전문점",
           "menu": ["후라이드", "양념치킨", "반반", "순살치킨", "치즈볼", "감자튀김"]},
    "cf": {"store_id": "bench_morae", "name": "모래커피 (가상)", "business_type": "cafe", "business_type_name": "커피-음료",
           "menu": ["아메리카노", "라떼", "바닐라라떼", "아인슈페너", "크로플", "마카롱", "케이크"]},
    "bs": {"store_id": "bench_ttobagi", "name": "또바기분식 (가상)", "business_type": "snack", "business_type_name": "분식전문점",
           "menu": ["떡볶이", "로제떡볶이", "김밥", "순대", "튀김", "라면", "어묵탕"]},
    "cn": {"store_id": "bench_hong", "name": "홍반점 (가상)", "business_type": "chinese", "business_type_name": "중식음식점",
           "menu": ["짜장면", "짬뽕", "탕수육", "군만두", "볶음밥", "깐풍기"]},
}
CHANNELS = {"bm": "baemin", "cp": "coupangeats", "yg": "yogiyo", "np": "naver_place"}
SENTIMENTS = {"p": "positive", "n": "negative", "m": "mixed", "u": "neutral"}
TAGS = {"plain", "multi", "mixed", "negation", "typo", "slang", "emoji", "sarcasm", "rating_mismatch", "short", "long",
        "no_topic", "compare", "visit", "request", "pii",
        "concept", "template", "platform", "question"}
SPLIT_START = {"dev": datetime(2026, 8, 1, tzinfo=KST), "test": datetime(2026, 9, 1, tzinfo=KST)}
HOURS = {"점심": (11, 13), "저녁": (18, 20), "새벽": (0, 2), "아침": (7, 9)}


class SourceError(ValueError):
    pass


def parse(path: Path) -> list[dict]:
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            head, sent, topics, tags, text = [x.strip() for x in line.split("|", 4)]
            store, rating, channel = head.split()
        except ValueError:
            raise SourceError(f"{path.name}:{n} 형식이 틀렸어요: {line}") from None
        if store not in STORES or channel not in CHANNELS or sent not in SENTIMENTS:
            raise SourceError(f"{path.name}:{n} 가게·채널·감정 값이 틀렸어요: {line}")
        hits = []
        for t in topics.split():
            topic, pol = t[:-1], t[-1]
            if topic not in TOPIC_IDS or pol not in "+-":
                raise SourceError(f"{path.name}:{n} 주제 사전에 없는 주제예요: {t}")
            hits.append({"topic": topic, "polarity": "positive" if pol == "+" else "negative"})
        tag_list = [x.strip() for x in tags.split(",") if x.strip()]
        bad = [x for x in tag_list if x not in TAGS]
        if bad:
            raise SourceError(f"{path.name}:{n} 모르는 태그예요: {bad}")
        pols = {h["polarity"] for h in hits}
        sentiment = SENTIMENTS[sent]
        ok = {"positive": pols <= {"positive"}, "negative": pols <= {"negative"},
              "mixed": pols == {"positive", "negative"}, "neutral": not pols}[sentiment]
        if not ok:
            raise SourceError(f"{path.name}:{n} 감정({sentiment})과 칭찬/불만({sorted(pols)})이 맞지 않아요: {line}")
        if ("multi" in tag_list) != (len({h['topic'] for h in hits}) >= 2) and "multi" in tag_list:
            raise SourceError(f"{path.name}:{n} multi 태그인데 주제가 2개 미만이에요: {line}")
        if "no_topic" in tag_list and hits:
            raise SourceError(f"{path.name}:{n} no_topic 인데 주제가 있어요: {line}")
        if not hits and "no_topic" not in tag_list:
            tag_list.append("no_topic")
        if "visit" in tag_list and channel != "np":
            raise SourceError(f"{path.name}:{n} visit 태그는 네이버 플레이스(np)만: {line}")
        rows.append({"store": store, "rating": None if rating == "-" else int(rating), "channel": CHANNELS[channel],
                     "sentiment": sentiment, "topics": hits, "tags": tag_list, "text": text, "line": n})
    return rows


def build(split: str) -> tuple[list[dict], list[dict]]:
    rows = parse(BENCH / "source" / f"{split}.txt")
    rng = random.Random(f"benchmark-v1-{split}")
    texts = Counter(r["text"] for r in rows)
    dup = [t for t, c in texts.items() if c > 1]
    if dup:
        raise SourceError(f"{split}: 같은 리뷰 글이 두 번 있어요: {dup[:3]}")
    reviews, labels = [], []
    counters: Counter = Counter()
    for r in rows:
        store = STORES[r["store"]]
        counters[r["store"]] += 1
        rid = f"bm_{split}_{store['store_id'].removeprefix('bench_')}_{counters[r['store']]:03d}"
        day = SPLIT_START[split] + timedelta(days=rng.randrange(0, 61))
        lo, hi = next((v for k, v in HOURS.items() if k in r["text"]), (11, 22))
        when = day.replace(hour=rng.randint(lo, hi), minute=rng.choice([0, 5, 10, 20, 30, 40, 50]))
        reviews.append({"review_id": rid, "store_id": store["store_id"], "text": r["text"], "created_at": when.isoformat(),
                        "channel": r["channel"], "rating": r["rating"], "input_method": "sample", "pii_masked": False,
                        "order_ref": None, "status": "new", "data_origin": "synthetic"})
        labels.append({"review_id": rid, "expected_sentiment": r["sentiment"], "expected_topics": r["topics"],
                       "tags": r["tags"], "source_line": f"source/{split}.txt:{r['line']}"})
    return reviews, labels


def stats(labels: list[dict]) -> dict:
    topics: Counter = Counter()
    for lab in labels:
        for h in lab["expected_topics"]:
            topics[f"{h['topic']}{'+' if h['polarity'] == 'positive' else '-'}"] += 1
    return {"n": len(labels), "sentiment": dict(Counter(lab["expected_sentiment"] for lab in labels)),
            "tags": dict(Counter(t for lab in labels for t in lab["tags"])), "topics": dict(sorted(topics.items()))}


def main() -> None:
    out = {}
    for split in ("dev", "test"):
        if not (BENCH / "source" / f"{split}.txt").exists():
            continue
        reviews, labels = build(split)
        (BENCH / f"reviews_{split}.json").write_text(json.dumps(reviews, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (BENCH / f"labels_{split}.json").write_text(json.dumps(labels, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        out[split] = stats(labels)
    if "dev" in out and "test" in out:
        dev = {r["text"] for r in build("dev")[0]}
        same = [r["text"] for r in build("test")[0] if r["text"] in dev]
        if same:
            raise SourceError(f"연습용과 시험용에 같은 글이 있어요: {same[:3]}")
    stores = [{**{k: v for k, v in s.items()}, "channels": list(CHANNELS.values()), "data_origin": "synthetic"}
              for s in STORES.values()]
    (BENCH / "stores.json").write_text(json.dumps(stores, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (BENCH / "stats.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for split, st in out.items():
        print(f"[{split}] {st['n']}건 · 감정 {st['sentiment']}")
        print("  주제", " ".join(f"{k}:{v}" for k, v in st["topics"].items()))
        print("  태그", " ".join(f"{k}:{v}" for k, v in sorted(st["tags"].items())))


if __name__ == "__main__":
    main()
