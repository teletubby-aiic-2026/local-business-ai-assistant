"""가게별 상권 지표(바삭치킨·몽글카페)를 서울시 공식 원본으로 다시 만들거나 확인한다 (Python 3.9+, 네트워크 없음).

온기한식의 지표(data/scenario/snapshot_2026Q2.json)는 scripts/reproduce_c4_evening_sales.py 가 만든다. 이 스크립트는
5차 회의(11/18)에서 더한 두 가게의 지표를 같은 정의로 만든다.

- 지표: 저녁 시간대(17~24시) 추정매출 = TMZON_17_21_SELNG_AMT + TMZON_21_24_SELNG_AMT, 2026Q2 vs 2025Q2 전년 동기 대비 변화율
- 범위: 상권 하나 · 업종 하나 (온기한식은 '두 분기 공통 업종' 합계라 범위가 다르다. 지표 이름에 업종을 적는다)
- 출처: 서울 열린데이터광장 '서울시 상권분석서비스(추정매출-상권)' OA-15572, 팀 자료 묶음 seoul-market-data-20261116.tar.gz 의
  services/market-analysis/data/raw/official/sales_<분기>_all_*.json

기본은 저장된 source_rows.json 으로 계산해 snapshot 파일과 같은지 확인만 한다 (원본이 없어도 됨).
--official-dir <data/raw/official> --write 를 주면 원본에서 행을 뽑아 source_rows.json 과 snapshot 파일을 새로 쓴다.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "data" / "scenario"
PERIODS = ("20252", "20262")
FIELDS = ("TMZON_17_21_SELNG_AMT", "TMZON_21_24_SELNG_AMT")
SOURCE_URL = "https://data.seoul.go.kr/dataList/OA-15572/S/1/datasetView.do"

# 가게 → (상권 코드, 상권 이름, 업종 코드, 업종 이름). 상권은 장승배기·상도 근처 동작구 상권 중 그 업종의 두 분기 행이 모두 있는 곳.
STORES = {
    "store_basak": ("3110836", "상도역 5번", "CS100007", "치킨전문점"),
    "store_mongle": ("3120154", "장승배기역", "CS100010", "커피-음료"),
}


def _row_list(data):
    """서울시 응답(그대로 저장한 것)에서 행 목록을 찾는다. 저장 모양이 겹쳐 있어도 처음 만나는 'row' 목록."""
    if isinstance(data, dict):
        if isinstance(data.get("row"), list):
            return data["row"]
        for value in data.values():
            found = _row_list(value)
            if found is not None:
                return found
    return None


def _rows(official_dir: str, period: str) -> list[dict]:
    out: list[dict] = []
    for path in sorted(glob.glob(os.path.join(official_dir, f"sales_{period}_all_*.json"))):
        out += _row_list(json.load(open(path, encoding="utf-8"))) or []
    if not out:
        raise SystemExit(f"{official_dir} 에 sales_{period}_all_*.json 이 없습니다")
    return out


def extract(official_dir: str) -> dict:
    """원본에서 두 가게에 필요한 행(분기 2개 × 상권·업종 1개)만 뽑는다."""
    picked: dict = {}
    for period in PERIODS:
        rows = _rows(official_dir, period)
        for store_id, (area, _, industry, _) in STORES.items():
            found = [r for r in rows if r.get("TRDAR_CD") == area and r.get("SVC_INDUTY_CD") == industry]
            if len(found) != 1:
                raise SystemExit(f"{store_id} {period}: 행이 {len(found)}개 (1개여야 함)")
            r = found[0]
            keep = ("STDR_YYQU_CD", "TRDAR_CD", "TRDAR_CD_NM", "SVC_INDUTY_CD", "SVC_INDUTY_CD_NM") + FIELDS
            picked.setdefault(store_id, {})[period] = {k: r.get(k) for k in keep}
    return picked


def snapshot(store_id: str, rows: dict) -> list[dict]:
    area, area_name, industry, industry_name = STORES[store_id]
    total = {p: sum(int(Decimal(str(rows[p][f]))) for f in FIELDS) for p in PERIODS}
    prev, cur = total["20252"], total["20262"]
    value = float((Decimal(cur) - Decimal(prev)) / Decimal(prev) * 100)
    return [{
        "snapshot_id": f"snap_{area}_evening_17_24_{industry}_yoy_2026Q2",
        "area_name": area_name,
        "metric_name": f"저녁 시간대(17~24시) 추정매출 전년 동기 대비 변화율 · {industry_name}",
        "value": value,
        "unit": "%",
        "basis_quarter": "2026Q2",
        "is_estimate": True,
        "source": f"서울시 상권분석서비스 · {SOURCE_URL}",
        "compared_with_quarter": "2025Q2",
        "note": (f"상권코드 {area}, 업종 {industry}({industry_name}) 한 업종. 17~21시와 21~24시 추정매출 합산: "
                 f"2025Q2 {prev:,}원 → 2026Q2 {cur:,}원. 동작구 장승배기·상도 근처 상권 중 이 업종의 두 분기 행이 모두 있는 곳에서 고름; "
                 "서울 전체 순위가 아님. 하루 전체 매출·개별 가게 실적과 구분."),
    }]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--official-dir", help="팀 자료 묶음의 services/market-analysis/data/raw/official")
    parser.add_argument("--write", action="store_true", help="원본에서 다시 뽑아 파일을 새로 쓴다 (--official-dir 필요)")
    args = parser.parse_args()
    if args.write:
        if not args.official_dir:
            parser.error("--write 에는 --official-dir 가 필요합니다")
        picked = extract(args.official_dir)
        for store_id, rows in picked.items():
            folder = SCENARIO / store_id
            folder.mkdir(parents=True, exist_ok=True)
            source = {"schema_version": "store-evening-v1", "periods": list(PERIODS), "fields": list(FIELDS),
                      "source_url": SOURCE_URL, "rows": rows}
            (folder / "source_rows.json").write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (folder / "snapshot_2026Q2.json").write_text(
                json.dumps(snapshot(store_id, rows), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"썼음: {folder}")
        return 0
    bad = 0
    for store_id in STORES:
        folder = SCENARIO / store_id
        rows = json.loads((folder / "source_rows.json").read_text(encoding="utf-8"))["rows"]
        want = snapshot(store_id, rows)
        have = json.loads((folder / "snapshot_2026Q2.json").read_text(encoding="utf-8"))
        same = want == have
        bad += not same
        print(f"{store_id}: {'같음' if same else '다름'} ({want[0]['area_name']} · {want[0]['value']:+.2f}%)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
