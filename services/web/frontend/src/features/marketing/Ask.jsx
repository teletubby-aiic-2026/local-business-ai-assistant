// 맞춤 제안의 질문 쪽: 진행 안내·오류·시작 모드 카드·대화 기록·답 고르기 칸 (예전 #mkt-status·#mkt-error·#mkt-log·#mkt-options)
import { useEffect, useRef, useState } from "react";
import { Button, FeatureCard, Icon, Panel } from "../../components/ui.jsx";
import { MKT_MODES, MKT_PICK, MKT_REPORT_DESC, MKT_UNIT, progressLabel } from "./logic.js";
import { pickOption, restartChat, retry, sendNumber, sendPicked, sendText, setTab, skip, togglePick, useMkt } from "./state.js";

// Enter = 보내기. 한글 입력 중의 Enter 는 글자만 확정 (보내지 않음)
export const isSendEnter = (e) => e.key === "Enter" && !e.nativeEvent.isComposing && e.keyCode !== 229;

// 진행 안내 (role=status): 깜박이는 점 + 글 + 걸린 초 (초는 읽기 프로그램에 읽히지 않게)
export function Status() {
  const st = useMkt((s) => s.status);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!st) return undefined;
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [st]);
  const sec = st ? Math.max(0, Math.floor((now - st.t0) / 1000)) : 0;
  const text = st ? (st.long && sec >= 6 ? `${st.text}. AI가 글을 쓰면 30초 넘게 걸릴 수 있어요` : st.text) : "";
  return (
    <p id="mkt-status" className={st ? "mkt-status busy" : "mkt-status"} role="status">
      {st && <><span>{text}</span><span className="mkt-sec" aria-hidden="true">{sec >= 2 ? `${sec}초` : ""}</span></>}
    </p>
  );
}

// 이 화면 안의 오류 (role=alert). 서버 문장 그대로
export function ErrorLine() {
  const error = useMkt((s) => s.error);
  return <p id="mkt-error" className="mkt-error" role="alert">{error}</p>;
}

const goReport = () => { setTab("report"); setTimeout(() => document.getElementById("mkt-tab-report")?.focus(), 0); };

// 시작 모드 카드 다섯 개 + '마케팅 보고서' (보기 글자는 서버가 준 것만)
function ModeGrid({ opts, busy }) {
  return (
    <div className="feature-grid mkt-modes">
      {opts.map((o, i) => (
        <FeatureCard key={o.label} title={o.label} desc={MKT_MODES[o.label]} icon={o.label} index={i}
          onClick={() => { if (!busy) pickOption(i); }} aria-disabled={busy || undefined} />
      ))}
      <FeatureCard title="마케팅 보고서" desc={MKT_REPORT_DESC} icon="마케팅 보고서" index={opts.length} onClick={goReport} />
    </div>
  );
}

// 숫자·글 입력칸 (예시 문구는 대화 기록에). 칸마다 '보내기', 숫자는 쉼표를 넣어 보이고 숫자만 보낸다
function InputBox({ spec, withOptions }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const ref = useRef(null);
  if (spec.type === "number") {
    const unit = MKT_UNIT[spec.key] || "";
    const send = () => {
      const digits = value.replace(/[^0-9]/g, "");
      if (!digits) { setError("숫자를 입력해 주세요"); ref.current?.focus(); return; }
      sendNumber(digits);
    };
    return (
      <>
        <div className="mkt-input">
          <label className="sr" htmlFor="mkt-num">숫자로 답하기</label>
          <input ref={ref} id="mkt-num" type="text" inputMode="numeric" autoComplete="off" placeholder="숫자로 답해 주세요" value={value}
            onChange={(e) => { const d = e.target.value.replace(/[^0-9]/g, "").slice(0, 12); setValue(d ? Number(d).toLocaleString("ko-KR") : ""); setError(""); }}
            onKeyDown={(e) => { if (isSendEnter(e)) { e.preventDefault(); send(); } }} />
          {unit && <span className="mkt-unit">{unit}</span>}
          <Button variant="primary" size="small" onClick={send}>보내기</Button>
        </div>
        {spec.skip && <div className="btn-row"><button type="button" className="mkt-chip" onClick={skip}>건너뛰기</button></div>}
        <p className="mkt-input-err" role="alert">{error}</p>
      </>
    );
  }
  if (spec.skip) {   // 가게 이야기처럼 길게 쓰는 답: 여러 줄 칸 + 글자 수 + [건너뛰기][보내기] (Enter 는 줄바꿈)
    const send = () => { const v = value.trim(); if (!v) { ref.current?.focus(); return; } sendText(v); };
    return (
      <div className="mkt-free">
        <label className="sr" htmlFor="mkt-free">답 쓰기</label>
        <textarea ref={ref} id="mkt-free" rows={3} maxLength={500} placeholder="답을 입력해 주세요" value={value} onChange={(e) => setValue(e.target.value)} />
        <div className="mkt-free-bar">
          <span className="small muted" aria-hidden="true">{value.length}자</span>
          <span className="btn-row"><Button size="small" onClick={skip}>건너뛰기</Button><Button variant="primary" size="small" onClick={send}>보내기</Button></span>
        </div>
      </div>
    );
  }
  const send = () => { const v = value.trim(); if (!v) { setError("답을 입력해 주세요"); ref.current?.focus(); return; } sendText(v); };
  return (
    <>
      <div className="mkt-input">
        <label className="sr" htmlFor="mkt-text">{withOptions ? "직접 입력" : "답 쓰기"}</label>
        <input ref={ref} id="mkt-text" type="text" maxLength={100} autoComplete="off" placeholder={withOptions ? "또는 직접 입력해 주세요" : "답을 입력해 주세요"}
          value={value} onChange={(e) => { setValue(e.target.value); setError(""); }}
          onKeyDown={(e) => { if (isSendEnter(e)) { e.preventDefault(); send(); } }} />
        <Button variant="primary" size="small" onClick={send}>보내기</Button>
      </div>
      <p className="mkt-input-err" role="alert">{error}</p>
    </>
  );
}

// 답 고르기 칸: 시작 모드 카드 · 보기(하나) · 여러 개 고르기 + [다음] · 입력. 오류가 나면 '다시 시도'만
export function Options() {
  const p = useMkt((s) => s.prompt);
  const hasRetry = useMkt((s) => s.hasRetry);
  const busy = useMkt((s) => s.busy);
  let body = null;
  if (hasRetry) body = <div className="btn-row"><Button variant="primary" onClick={retry}>다시 시도</Button></div>;
  else if (p) {
    const opts = p.opts;
    body = (
      <>
        {p.start ? <ModeGrid opts={opts} busy={busy} />
          : p.multi ? (
            <>
              <div className="mkt-chips" role="group" aria-label="여러 개 고르기">
                {opts.map((o, i) => (
                  <button key={i} type="button" className="mkt-chip" aria-pressed={p.picked.includes(i)} onClick={() => togglePick(i)}>{o.label}</button>
                ))}
              </div>
              <div className="btn-row">
                <Button variant="primary" disabled={!p.picked.length} onClick={sendPicked}>다음</Button>
                <span className="small muted">여러 개 고를 수 있어요</span>
              </div>
            </>
          ) : opts.length > 0 && (
            <div className="mkt-chips">
              {opts.map((o, i) => <button key={i} type="button" className="mkt-chip" onClick={() => pickOption(i)}>{o.label}</button>)}
            </div>
          )}
        {p.input && <InputBox key={p.seq} spec={p.input} withOptions={opts.length > 0} />}
      </>
    );
  }
  return <div id="mkt-options" className="mkt-options" role="group" aria-label="답 고르기">{body}</div>;
}

// 대화 한 줄 (Figma 06 M1): 비서 질문 = 테두리 상자 + '마케팅 비서' 이름표, 사장님 답 = 오른쪽 연한 초록 말풍선
function LogEntry({ e }) {
  if (e.kind === "user") return <div className="mkt-msg user"><p className="mkt-bubble">{e.text}</p></div>;
  if (e.kind === "sub") return <p className="mkt-sub">{e.text}</p>;
  if (e.kind === "example") return <p className="mkt-example">{e.text}</p>;
  return <div className="mkt-msg bot"><span className="mkt-who">마케팅 비서</span><p>{e.text}</p></div>;
}

// 기능 카드(6개)로 돌아가기: 질문 칸 머리(제목 줄 오른쪽)와 맨 아래에 같은 이름·같은 동작(restartChat). 대화만 처음으로 (11/22 QA:
// 맨 아래 작은 '처음부터'만 있어 "새로고침 말고는 못 나간다"고 보였다). 둘 다 '승인한 기록은 그대로 남아요'를 설명으로 읽는다
function Foot() {
  return (
    <div className="mkt-foot">
      <Button size="small" id="mkt-restart" aria-describedby="mkt-restart-hint" onClick={restartChat}>{MKT_PICK}</Button>
      <span id="mkt-restart-hint" className="small muted">승인한 기록은 그대로 남아요</span>
    </div>
  );
}
const PickButton = () => (
  <Button size="small" id="mkt-pick" className="mkt-pick" aria-describedby="mkt-restart-hint" onClick={restartChat}>
    <Icon name="뒤로" size={16} />{MKT_PICK}
  </Button>
);

// 첫 질문 화면: "무엇을 도와드릴까요?" 한 줄 아래 기능 카드 격자. 카드가 회색 바탕 위에 바로 놓인다 (흰 패널로 감싸지 않음, Figma 06 M1)
export function StartView() {
  const log = useMkt((s) => s.log);
  const heading = log.find((e) => e.kind === "bot")?.text || "무엇을 도와드릴까요?";
  const sub = log.find((e) => e.kind === "sub")?.text;
  return (
    <section className="mkt-start" aria-labelledby="mkt-start-title">
      <div className="mkt-start-head">
        <h2 id="mkt-start-title">{heading}</h2>
        {sub && <p className="muted">{sub}</p>}
      </div>
      <Status />
      <ErrorLine />
      <Options />
    </section>
  );
}

// 질문이 진행되는 동안 왼쪽 칸: 제목(고른 모드 · 질문 n) + '다른 기능 고르기' · 대화 기록 · 답 고르기 · 맨 아래 '다른 기능 고르기'
export function AskPanel() {
  const log = useMkt((s) => s.log);
  const questions = useMkt((s) => s.questions);
  const mode = useMkt((s) => s.mode);
  const progress = progressLabel(questions);
  const title = <>{mode || "맞춤 제안"}{progress && <span className="mkt-progress"> · {progress}</span>}</>;
  return (
    <Panel className="mkt-ask" title={title} titleId="mkt-ask-title" actions={<PickButton />}>
      <div id="mkt-log" className="mkt-log" role="log" aria-live="polite" aria-label="맞춤 마케팅 대화">
        {log.map((e) => <LogEntry key={e.id} e={e} />)}
      </div>
      <Status />
      <ErrorLine />
      <Options />
      <Foot />
    </Panel>
  );
}
