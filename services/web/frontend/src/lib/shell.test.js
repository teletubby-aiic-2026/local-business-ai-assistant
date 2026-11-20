// 화면 틀이 쓰는 작은 규칙: 시험용 안내 띠·바닥 줄 문구, 창 폭 구간
import { describe, it, expect, afterEach, vi } from "vitest";
import { honestyItems, modeBandText, MODE_BAND_MOCK } from "./domain.js";
import { bandNow } from "./media.js";

describe("안내 띠·바닥 줄", () => {
  const mock = { mode: "mock", mode_notice: "시험용 실행 · …", parts: { reviews: "합성 데이터", briefing: "리뷰 분류: rule", cards: "규칙 + 고정 문장", generate: "저장본(김수현 C6 결과)" } };
  const live = { mode: "live", mode_notice: null, parts: { reviews: "합성 데이터", briefing: "리뷰 분류: HCX-DASH-002", cards: "규칙 + HCX-005 이유 문장", generate: "실시간 HCX-005" } };

  it("시험용이면 띠는 짧은 한 줄, 바닥 줄은 자료 출처만 (AI 아님은 띠 한 곳)", () => {
    expect(modeBandText(mock)).toBe(MODE_BAND_MOCK);
    expect(MODE_BAND_MOCK).toBe("시험용 예시 화면 · 실제 AI 생성 결과가 아니에요");
    expect(honestyItems(mock)).toEqual(["리뷰: 합성 데이터"]);
  });

  it("실시간이면 띠가 없고 바닥 줄에 글 생성 방식 (분류 모델·규칙 분담 같은 안쪽 사정은 빼고)", () => {
    expect(modeBandText(live)).toBe("");
    expect(honestyItems(live)).toEqual(["리뷰: 합성 데이터", "글 생성: 실시간 HCX-005"]);
  });

  it("상태를 아직 못 받았으면 둘 다 비움", () => {
    expect(modeBandText(null)).toBe("");
    expect(honestyItems(null)).toEqual([]);
  });
});

describe("창 폭 구간", () => {
  afterEach(() => { delete window.matchMedia; });
  const at = (width) => {
    window.matchMedia = vi.fn((q) => {
      const min = Number((q.match(/min-width: (\d+)px/) || [])[1] || 0);
      const max = Number((q.match(/max-width: (\d+)px/) || [])[1] || Infinity);
      return { matches: width >= min && width <= max };
    });
    return bandNow();
  };
  it("760 이하 narrow · 761~1024 mid · 그 위 wide (소수 폭 틈은 wide)", () => {
    expect(at(375)).toBe("narrow");
    expect(at(760)).toBe("narrow");
    expect(at(761)).toBe("mid");
    expect(at(900)).toBe("mid");
    expect(at(1024)).toBe("mid");
    expect(at(1024.5)).toBe("wide");
    expect(at(1280)).toBe("wide");
  });
  it("matchMedia 가 없으면 wide", () => {
    delete window.matchMedia;
    expect(bandNow()).toBe("wide");
  });
});
