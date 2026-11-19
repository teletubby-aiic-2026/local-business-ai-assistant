// 포커스 옮기기 도우미. 다시 그린 뒤(잠금이 풀린 뒤)에 옮기도록 한 박자 늦춘다
// (잠긴 버튼은 포커스를 받지 못해서, 그리기가 끝난 다음 프레임 + 0ms 뒤에 옮긴다)
export function later(fn) {
  const run = () => setTimeout(fn, 0);
  if (typeof requestAnimationFrame === "function") requestAnimationFrame(run); else run();
}

// ids 를 앞에서부터 보고 화면에 있는 첫 요소로 (예: focusFirst("acct-store", "acct-user"))
export function focusFirst(...ids) {
  later(() => {
    for (const id of ids) {
      const el = document.getElementById(id);
      if (el && !el.disabled) { el.focus(); return; }
    }
  });
}
