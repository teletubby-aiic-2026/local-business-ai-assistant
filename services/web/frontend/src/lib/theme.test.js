import { afterEach, describe, expect, it } from "vitest";
import { nextTheme, setTheme, effectiveTheme, THEMES } from "./theme.js";

describe("화면 모양", () => {
  afterEach(() => setTheme("system"));

  it("시스템 → 밝게 → 어둡게 → 시스템 순서", () => {
    expect(THEMES.map(nextTheme)).toEqual(["light", "dark", "system"]);
  });

  it("밝게·어둡게는 html data-theme 과 저장값으로, 시스템은 둘 다 지움", () => {
    setTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("ic26.theme")).toBe("dark");
    expect(effectiveTheme("dark")).toBe("dark");
    setTheme("system");
    expect(document.documentElement.dataset.theme).toBeUndefined();
    expect(localStorage.getItem("ic26.theme")).toBeNull();
  });

  it("모르는 값은 무시", () => {
    setTheme("light");
    setTheme("blue");
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
