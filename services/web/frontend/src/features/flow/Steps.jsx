// 3단계 표시 (Figma 06 B2~B4): [1 추천 카드] › [2 승인할 글] › [3 처리 완료]. 단계마다 알약 모양, 지금 단계는 초록 알약 + aria-current="step"
const STEPS = [["cards", "추천 카드"], ["draft", "승인할 글"], ["done", "처리 완료"]];

export default function Steps({ at }) {
  const now = STEPS.findIndex(([k]) => k === at);
  return (
    <nav aria-label="진행 단계">
      <ol className="flow-steps">
        {STEPS.map(([k, label], i) => (
          <li key={k} className={i === now ? "on" : i < now ? "past" : undefined} aria-current={i === now ? "step" : undefined}>
            {i > 0 && <span className="flow-step-sep" aria-hidden="true">›</span>}
            <span className="flow-step-pill"><span className="flow-step-n" aria-hidden="true">{i + 1}</span><span>{label}</span></span>
          </li>
        ))}
      </ol>
    </nav>
  );
}
