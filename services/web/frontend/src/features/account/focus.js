// 창을 닫은 뒤의 포커스 (예전 app.js 의 $("acct-login")·$("acct-user")·$("acct-store").focus()).
// 상단 바(Topbar)의 버튼 id: acct-login(게스트) · acct-user(로그인) · acct-store(가게 고르기). 다시 그린 뒤(잠금이 풀린 뒤)에 옮긴다
import { later, focusFirst } from "../../lib/focus.js";

export { later };

// 상단 바의 '로그인' 또는 이름 버튼 (둘 중 있는 하나)
export const accountButton = () => document.getElementById("acct-user") || document.getElementById("acct-login");

export function focusAccountButton() { later(() => accountButton()?.focus()); }

// 로그인 뒤: 가게 고르기(가게가 둘 이상일 때만 있음), 없으면 이름 버튼
export function focusStorePick() { focusFirst("acct-store", "acct-user", "acct-login"); }
