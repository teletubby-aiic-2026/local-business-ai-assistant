import { describe, expect, it } from "vitest";
import { barRows, condText, dataStatusText, metricValue, numKo, pctKo, qLabel, safeUrl, storeLineOf, syncText, withQuery, wonShort } from "./format.js";

describe("상권 분석 표기", () => {
  it("분기 코드와 {code,label} 을 읽는다", () => {
    expect(qLabel("20262")).toBe("2026년 2분기");
    expect(qLabel({ code: "20251" })).toBe("2025년 1분기");
    expect(qLabel({ label: "직접 이름" })).toBe("직접 이름");
    expect(qLabel(null)).toBe("");
  });

  it("원 단위를 억·만으로만 줄인다 ('원' 앞은 줄바꿈 없는 띄어쓰기)", () => {
    expect(wonShort(11777272482)).toBe("117억 7,727만\u00a0원");
    expect(wonShort(200000000)).toBe("2억\u00a0원");
    expect(wonShort(-35000)).toBe("-4만\u00a0원");
    expect(wonShort(9500)).toBe("9,500원");
    expect(wonShort(undefined)).toBe("–");
  });

  it("숫자·변화율", () => {
    expect(numKo(1234, "개")).toBe("1,234개");
    expect(numKo(null)).toBe("–");
    expect(pctKo(3.456)).toBe("+3.46%");
    expect(pctKo(-1)).toBe("-1.00%");
    expect(pctKo(0)).toBe("0.00%");
    expect(metricValue({ unit: "원" }, { value: 150000000 })).toBe("1억 5,000만\u00a0원");
    expect(metricValue({ unit: "명" }, { value: 12 })).toBe("12명");
  });

  it("비중이 없으면 값의 합으로 막대 길이만 맞춘다", () => {
    const rows = barRows({ items: [{ label: "20대 (원천 분류)", value: 30 }, { label: "30대", value: 10 }] });
    expect(rows[0]).toEqual({ label: "20대", pct: 75, shown: "30" });
    expect(rows[1].pct).toBe(25);
    expect(barRows({ items: [{ label: "점심", share_percent: 41.2 }] })[0].shown).toBe("41.20%");
    expect(barRows(null)).toEqual([]);
  });

  it("조건·자료 상태·동기화 글", () => {
    expect(condText({ area_name: "상도역", industry_name: "한식", period: "20262", home: true })).toBe("상도역 · 한식 · 2026년 2분기 · 우리 가게 기준");
    expect(dataStatusText(null)).toBe("자료 상태를 불러오지 못했어요.");
    // 11/21: 볼 수 있는 분기 범위를 사장님 말로, 원본 파일 수는 적지 않음 (실시간 확인 15)
    expect(dataStatusText({ status: "ready", message: "서버에 2024년 3분기~2026년 2분기 상권 자료 8개 분기가 준비돼 있어요.",
      periods: ["20262", "20243", "20251"], verified_files: 808, last_synced_at: "2026-11-18T21:09:00+09:00" }))
      .toBe("2024년 3분기~2026년 2분기 자료를 볼 수 있어요. · 서울시 최신 자료 확인 2026-11-18 21:09");
    expect(syncText({ message: "최신이에요", totals: { sales: 10 }, sample_only: true })).toBe("최신이에요 · 서울시 총 건수: 추정매출 10건 · 서울시 공개 샘플(1~5건)로만 확인했어요.");
    expect(syncText({ message: "최신이에요", sample_only: true, notice: "서버 안내" })).toBe("최신이에요 · 서버 안내");
  });

  it("서울시와 맞춰 본 기록이 없으면 내부 사정 없이 짧게", () => {
    expect(dataStatusText({ status: "ready", periods: ["20262"], verified_files: 808 })).toBe("2026년 2분기 자료를 볼 수 있어요.");
    expect(dataStatusText({ message: "준비됨", verified_files: 808 })).toBe("준비됨");
    // 자료가 모자라면 서버 문장 그대로 (분기 범위를 말하지 않음)
    expect(dataStatusText({ status: "source_files_missing", periods: ["20262"], message: "상권 자료 원본 3개를 서버에서 찾지 못했어요. 관리자 확인이 필요해요." }))
      .toBe("상권 자료 원본 3개를 서버에서 찾지 못했어요. 관리자 확인이 필요해요.");
    expect(dataStatusText({ message: "준비됨" })).not.toMatch(/샘플 키|인증키|원본 파일|확인 기록/);
  });

  it("머리의 가게 한 줄: 역이 없으면 등록한 위치를 짧게, 빈 칸은 빼고 'null'을 찍지 않는다 (11/21 실시간 확인 M7)", () => {
    expect(storeLineOf({ name: "온기한식", station_name: "장승배기역", business_type_name: "한식음식점" })).toBe("온기한식 · 장승배기역 · 한식음식점");
    expect(storeLineOf({ name: "동네맛김밥", station_name: null, location_label: "서울특별시 마포구 와우산로 94 학교법인홍익학원", business_type_name: "분식전문점" }))
      .toBe("동네맛김밥 · 마포구 와우산로 94 · 분식전문점");
    expect(storeLineOf({ name: "새 가게", station_name: null, location_label: null, business_type_name: "분식전문점" })).toBe("새 가게 · 분식전문점");
    expect(storeLineOf({ name: "새 가게", station_name: "null", business_type_name: undefined })).toBe("새 가게");
    expect(storeLineOf(null)).toBe("");
  });

  it("링크·쿼리", () => {
    expect(safeUrl("javascript:alert(1)")).toBeNull();
    expect(safeUrl("https://culture.seoul.go.kr/x")).toBe("https://culture.seoul.go.kr/x");
    expect(withQuery("sales", "", "expected_revision=3")).toBe("sales?expected_revision=3");
    expect(withQuery("sales", "", "")).toBe("sales");
  });
});
