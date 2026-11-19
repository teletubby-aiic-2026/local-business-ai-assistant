// 공통 부품: 아이콘(자리 글자 없이 선 그림) · 빈 안내 · 대화상자(jsdom 에서도 닫힘 알림)
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { Icon, ICONS, Empty, Dialog, Logo } from "./ui.jsx";

afterEach(() => cleanup());

const REQUIRED = [
  // 왼쪽 메뉴 8개
  "홈", "추천 카드", "승인할 글", "처리 완료", "리뷰 분석", "상권 분석", "종합 리포트", "맞춤 마케팅",
  // 숫자 타일 6개
  "리뷰", "불만", "반복 불만", "상권 매출", "승인", "고침",
  // 맞춤 마케팅 기능 카드 6개
  "맞춤 홍보 제안", "남은 재료 팔기", "광고비 점검", "가게 이야기 글", "쿠폰 결과 확인", "마케팅 보고서",
];

describe("아이콘", () => {
  it.each(REQUIRED)("%s: 24×24 선 그림, 글자 없음", (name) => {
    expect(ICONS[name]).toBeTruthy();
    const { container } = render(<Icon name={name} size={20} />);
    const svg = container.querySelector("svg");
    expect(svg).toBeTruthy();
    expect(svg.getAttribute("viewBox")).toBe("0 0 24 24");
    expect(svg.getAttribute("fill")).toBe("none");
    expect(svg.getAttribute("stroke")).toBe("currentColor");
    expect(svg.getAttribute("stroke-linecap")).toBe("round");
    expect(svg.getAttribute("stroke-linejoin")).toBe("round");
    expect(svg.getAttribute("aria-hidden")).toBe("true");
    expect(svg.getAttribute("data-icon")).toBe(name);
    expect(svg.querySelector("text")).toBeNull();
    expect(svg.textContent).toBe("");
    expect(svg.querySelectorAll("path, rect, circle").length).toBeGreaterThan(0);
    expect(svg.style.width).toBe("20px");
  });

  it("모르는 이름은 중립 아이콘 (첫 글자를 찍지 않음)", () => {
    for (const name of ["없는 이름", "가", "", undefined]) {
      const { container, unmount } = render(<Icon name={name} />);
      const svg = container.querySelector("svg");
      expect(svg.getAttribute("data-icon")).toBe("generic");
      expect(svg.querySelector("text")).toBeNull();
      expect(container.textContent).toBe("");
      unmount();
    }
  });

  it("그림이 서로 다르다 (같은 자리 그림을 돌려쓰지 않음)", () => {
    const shapes = REQUIRED.map((name) => {
      const { container, unmount } = render(<Icon name={name} />);
      const html = container.querySelector("svg").innerHTML;
      unmount();
      return html;
    });
    expect(new Set(shapes).size).toBe(REQUIRED.length);
  });

  it("로고는 말풍선 그림 (글자 '로' 없음)", () => {
    const { container } = render(<Logo />);
    expect(container.textContent).toBe("");
    expect(container.querySelector(".logo svg path")).toBeTruthy();
  });
});

describe("빈 안내", () => {
  it("자리 글자 '빈 상태 그림' 없이 아이콘·제목·한 줄", () => {
    const { container, getByText } = render(<Empty title="아직 승인한 글이 없어요.">승인할 글에서 승인해 주세요.</Empty>);
    expect(container.textContent).not.toContain("빈 상태 그림");
    expect(container.querySelector(".empty-art")).toBeNull();
    expect(container.querySelector(".empty-icon svg[aria-hidden='true']")).toBeTruthy();
    expect(getByText("아직 승인한 글이 없어요.")).toBeTruthy();
  });
});

describe("대화상자", () => {
  it("showModal 이 없는 환경에서도 열고 닫으며, 닫히면 onClosed 를 한 번 부른다", () => {
    const onClosed = vi.fn();
    const { container, rerender } = render(<Dialog open id="d1" onClosed={onClosed} aria-busy="true"><p>안</p></Dialog>);
    const d = container.querySelector("dialog");
    expect(d.hasAttribute("open")).toBe(true);
    expect(d.id).toBe("d1");
    expect(d.getAttribute("aria-busy")).toBe("true");
    rerender(<Dialog open={false} id="d1" onClosed={onClosed}><p>안</p></Dialog>);
    expect(d.hasAttribute("open")).toBe(false);
    expect(onClosed).toHaveBeenCalledTimes(1);
  });
});
