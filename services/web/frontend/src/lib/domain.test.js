// lib/domain.js 의 화면 글자 도우미 (11/21 실시간 확인 M7·M3: 'null' 이 찍히지 않게, 주소 원문을 짧게, 직접 등록한 가게)
import { describe, expect, it } from "vitest";
import { cleanLabel, isOwnStore, shortPlace, textOr, noticeName, genName } from "./domain.js";

describe("화면 글자 도우미", () => {
  it("textOr: 빈 값과 'null'·'undefined'·'None' 글자는 빈 글자", () => {
    expect([null, undefined, "", "  ", "null", "undefined", "None", "NaN"].map(textOr)).toEqual(["", "", "", "", "", "", "", ""]);
    expect(textOr(" 장승배기역 ")).toBe("장승배기역");
    expect(textOr(0)).toBe("0");
  });
  it("shortPlace: 도로명·지번 주소는 '구 길 번호'로, 역·동네 이름은 그대로", () => {
    expect(shortPlace("서울특별시 마포구 와우산로 94 학교법인홍익학원")).toBe("마포구 와우산로 94");
    expect(shortPlace("서울특별시 동작구 상도로 지하188")).toBe("동작구 상도로");
    expect(shortPlace("서울 동작구 장승배기로10길 5-2")).toBe("동작구 장승배기로10길 5-2");
    expect(shortPlace("서울특별시 마포구 서교동 123-4")).toBe("마포구 서교동 123-4");
    expect(shortPlace("장승배기역")).toBe("장승배기역");
    expect(shortPlace("홍대입구역(홍대)")).toBe("홍대입구역(홍대)");
    expect(shortPlace("서울특별시 어딘가")).toBe("어딘가");
    expect(shortPlace(null)).toBe("");
    expect(shortPlace("null")).toBe("");
  });
  it("cleanLabel: ' · '로 이은 이름 줄에서 빈 조각은 빼고 주소는 짧게", () => {
    expect(cleanLabel("온기한식 · 장승배기역 · 한식음식점")).toBe("온기한식 · 장승배기역 · 한식음식점");
    expect(cleanLabel("동네맛김밥 · 서울특별시 마포구 와우산로 94 학교법인홍익학원 · 분식전문점")).toBe("동네맛김밥 · 마포구 와우산로 94 · 분식전문점");
    expect(cleanLabel("새 가게 · None · 분식전문점")).toBe("새 가게 · 분식전문점");
    expect(cleanLabel(null)).toBe("");
  });
  it("isOwnStore: 지금 가게가 직접 등록한 가게(sample: false)일 때만", () => {
    const me = (sample, id = "s1") => ({ store_id: id, stores: [{ store_id: "s1", sample }] });
    expect(isOwnStore(me(false))).toBe(true);
    expect(isOwnStore(me(true))).toBe(false);
    expect(isOwnStore(me(undefined))).toBe(false);
    expect(isOwnStore(me(false, "s2"))).toBe(false);
    expect(isOwnStore(null)).toBe(false);
  });
});

describe("안내문 이름: 불만 주제에 맞게 (11/21)", () => {
  it("포장 누락 카드는 '포장·주문 안내문', 다른 주제는 '안내문', 제목을 모르면 예전 이름", () => {
    expect(noticeName("포장 누락 3건 반복 → 배달앱 포장·주문 안내문 + 답글")).toBe("포장·주문 안내문");
    expect(noticeName("식감 4건 반복 → 안내문 + 답글")).toBe("안내문");
    expect(noticeName(undefined)).toBe("포장·주문 안내문");
    expect(genName("prevention_notice", "매장 대기 5건 반복 → 안내문 + 답글")).toBe("안내문");
    expect(genName("reply_draft", "식감 4건 반복 → 안내문 + 답글")).toBe("답글");
    expect(genName("coupon_promo")).toBe("쿠폰 홍보글");
  });
});
