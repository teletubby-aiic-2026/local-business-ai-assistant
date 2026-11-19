// 3 승인할 글 (예전 renderDraft·sourceBlock·rerunPaint). 원 리뷰와 AI 초안을 위아래로, 고치고 승인.
// 고친 글은 store 의 pending 에 바로 담는다 (예전 saveEdits: 다시 그려도·다른 화면에 다녀와도 남음).
import { useEffect, useRef, useState } from "react";
import { useStore, setState } from "../../state/store.js";
import { GEN_NAMES, KIND_NAMES, KIND_AGENT, SOURCE_NAMES, praiseOf, shortBasis } from "../../lib/domain.js";
import { PageHead, Panel, Badge, Button, Empty } from "../../components/ui.jsx";
import Steps from "./Steps.jsx";
import { useFlow, setFlow } from "./state.js";
import { approve, regenDraft, rerunCard, copyText } from "./actions.js";
import { RULES_TITLE, RERUN_LABEL, failedOf, checksOf, statusOf, regenKey, textOf, touchedOf, pickCurrent, starText } from "./calc.js";
import "./flow.css";

export default function Draft() {
  const s = useStore();
  const f = useFlow();
  const { made, current, drafts, draftId } = pickCurrent(s);

  // 보이는 카드·글을 store 에도 맞춘다 (승인 뒤 '다음 미승인 글'을 이 카드에서 찾음)
  useEffect(() => {
    if (current !== s.current || draftId !== s.draftId) setState({ current, draftId });
  }, [current, draftId, s.current, s.draftId]);

  if (!made.length) {
    return (
      <div className="col narrow">
        <Steps at="draft" />
        <PageHead title="승인할 글" />
        <Panel><Empty title="아직 만든 글이 없어요.">추천 카드에서 카드를 하나 골라 주세요.</Empty>
          <div className="flow-center"><a className="btn primary" href="#/cards">추천 카드 보기</a></div></Panel>
      </div>
    );
  }

  const p = s.cards.find((x) => x.card.card_id === current);
  const r = s.results[current];
  const d = drafts.find((x) => x.draft_id === draftId);
  const done = drafts.filter((x) => s.approved.has(x.draft_id)).length;
  const armed = f.armed === current;
  const rerunBusy = f.busy[current] === "rerun";

  return (
    <div className="col narrow flow-draft">
      <Steps at="draft" />
      <PageHead owner={KIND_AGENT[p.card.kind]} title={p.title} actions={<Badge>{SOURCE_NAMES[r.source] || r.source || ""}</Badge>} />

      {made.length > 1 && (
        <div className="flow-seg" role="group" aria-label="카드">
          {made.map((q) => (
            <button key={q.card.card_id} type="button" aria-current={q.card.card_id === current ? "true" : undefined}
              onClick={() => { setFlow({ note: null }); setState({ current: q.card.card_id, draftId: null }); }}>
              {s.cards.indexOf(q) === 0 ? "ⓐ" : "ⓑ"} {KIND_NAMES[q.card.kind] || q.card.kind}
            </button>
          ))}
        </div>
      )}
      {(r.source_note || (r.chosen_measures || []).length > 0) && (
        <div className="stack-8">
          {r.source_note && <p className="small muted">{r.source_note}</p>}
          {(r.chosen_measures || []).length > 0 && (
            <p className="small">{RULES_TITLE}: {r.chosen_measures.map((m) => m.text).join(", ")} <span className="muted">· {r.source === "seed" ? "시험용 저장 예시 글은 고른 수칙과 상관없이 그대로예요" : "공지에 반영"}</span></p>
          )}
        </div>
      )}

      <div className="stack-8">
        <div className="flow-progress">
          <span>승인 {done} / {drafts.length}</span>
          <span className="flow-track" aria-hidden="true"><i style={{ width: `${drafts.length ? Math.round((done / drafts.length) * 100) : 0}%` }} /></span>
          <Button size="small" disabled={!!f.busy[current]} onClick={() => rerunCard(current)}>
            {rerunBusy ? "만드는 중…" : armed ? "한 번 더 눌러 실행" : RERUN_LABEL}
          </Button>
        </div>
        <p className="small muted" role="status">{armed ? `한 번 더 누르면 이 카드의 글을 모두 다시 만들어요. 승인했거나 고친 글 ${touchedOf(s, current)}개도 새 글로 바뀌어요.` : ""}</p>
      </div>

      {d ? <>
        <SourcePanel p={p} d={d} reviews={s.reviewsById} />
        <DraftPanel key={d.draft_id} d={d} s={s} busy={f.regen.has(regenKey(current, d))} note={f.note?.id === d.draft_id ? f.note.text : ""} />
      </> : <Panel><p className="muted">이 카드에서 만든 글이 없어요.</p></Panel>}

      <Panel title="남은 글" titleId="flow-list-title" sub={`승인 안 한 글 ${drafts.length - done}개`}>
        <ol className="plain flow-list" aria-label={`글 ${drafts.length}개`}>
          {drafts.map((x, i) => {
            const [tone, text] = statusOf(x, s.approved);
            return (
              <li key={x.draft_id}>
                <button type="button" aria-current={x.draft_id === draftId ? "true" : undefined}
                  onClick={() => { setFlow({ note: null }); setState({ draftId: x.draft_id }); }}>
                  <span>{i + 1}. {GEN_NAMES[x.generator] || x.generator}</span>
                  <Badge tone={tone}>{text}</Badge>
                </button>
              </li>
            );
          })}
        </ol>
      </Panel>
    </div>
  );
}

// 이 글이 답하는 원 리뷰. 답글 = 그 리뷰 1건, 공지 = 카드 근거 리뷰, 홍보글 = 근거 지표 + 쿠폰 메뉴를 칭찬한 손님 리뷰
function SourcePanel({ p, d, reviews }) {
  const ev = p.evidence || [];
  const target = d.target_review_id ? reviews[d.target_review_id] : null;
  let body;
  if (target) body = <ul className="plain flow-rv-list"><ReviewItem r={target} /></ul>;
  else {
    const rs = ev.filter((e) => e.type === "review").map((e) => reviews[e.id] || { text: e.text });
    if (rs.length) body = <Block title={`근거 리뷰 ${rs.length}건`}><ul className="plain flow-rv-list">{rs.map((x, i) => <ReviewItem key={i} r={x} />)}</ul></Block>;
    else {
      const snaps = ev.filter((e) => e.type === "snapshot");
      const praise = praiseOf(p);
      const praised = praise.shown.map((e) => reviews[e.id] || { text: e.text, rating: e.rating });
      if (!snaps.length && !praised.length) return null;
      body = <>
        {snaps.length > 0 && <Block title="근거 지표">{snaps.map((e, i) => <div key={i}><p>{e.text}</p><p className="small muted">{shortBasis(e.basis)}</p></div>)}</Block>}
        {praised.length > 0 && <Block title={`손님 칭찬 리뷰 · ${praise.menu} 언급 ${praise.total}건${praise.total > praised.length ? ` 중 ${praised.length}건` : ""}`}>
          <ul className="plain flow-rv-list">{praised.map((x, i) => <ReviewItem key={i} r={x} />)}</ul></Block>}
      </>;
    }
  }
  return <Panel title="손님 리뷰" titleId="flow-rv-title">{body}</Panel>;
}

const Block = ({ title, children }) => <div className="inset stack-8"><p className="small strong muted">{title}</p>{children}</div>;

function ReviewItem({ r }) {
  const when = String(r.created_at || "").slice(5, 16).replace("T", " ");
  const stars = starText(r.rating);
  return (
    <li>
      <div className="flow-rv-meta small muted">
        {stars && <span className="flow-stars" role="img" aria-label={`별점 ${r.rating}점`}>{stars}</span>}
        {r.channel && <span>{r.channel}</span>}
        {when && <span>{when}</span>}
        {r.input_method === "paste" && <span>붙여넣음</span>}
      </div>
      <p>{r.text}</p>
    </li>
  );
}

// 초안 상자: 편집 칸, 점검 배지·목록, 승인·복사·다시 만들기
function DraftPanel({ d, s, busy, note }) {
  const box = useRef(null);
  const regenBtn = useRef(null);
  const [copied, setCopied] = useState(false);
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  const failed = failedOf(d), checks = checksOf(d);
  const approved = s.approved.has(d.draft_id);
  const [, statusText] = statusOf(d, s.approved);
  const name = GEN_NAMES[d.generator] || d.generator;
  const textId = `flow-text-${d.draft_id}`;

  const copy = async () => {
    await copyText(box.current?.value ?? textOf(s, d), box.current);
    setCopied(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 1500);
  };
  const regen = async () => {
    await regenDraft(d.draft_id);
    // 버튼이 잠겼다 풀리며 잃은 포커스를 다시 만들기 버튼으로 (기다리는 동안 다른 곳으로 옮겼으면 그대로)
    requestAnimationFrame(() => { if (!document.activeElement || document.activeElement === document.body) regenBtn.current?.focus({ preventScroll: true }); });
  };

  return (
    <Panel className={approved ? "flow-draft-box approved" : "flow-draft-box"} title={name} titleId="flow-draft-title" id={`draft-${d.draft_id}`}
      actions={<>
        {approved && <Badge tone="ok">승인 완료</Badge>}
        {failed.length > 0 && <Badge tone="bad">점검 실패 {failed.length}</Badge>}
        {checks.length > 0 && <Badge tone="warn">확인 필요 {checks.length}</Badge>}
        {!failed.length && !checks.length && !approved && <Badge tone="ok">점검 통과</Badge>}
      </>}>
      <div className="field">
        <label htmlFor={textId} className="flow-reply-label">AI {name} 초안<span className="sr"> ({statusText})</span></label>
        <textarea ref={box} id={textId} className="input flow-textarea" rows={7} readOnly={busy} value={textOf(s, d)}
          onChange={(e) => { const v = e.target.value; setState((st) => ({ pending: { ...st.pending, [d.draft_id]: v } })); }} />
      </div>
      {failed.length > 0 && <ul className="flow-issues bad">{failed.map((x, i) => <li key={i}><b>점검 실패</b> {x}</li>)}</ul>}
      {checks.length > 0 && <ul className="flow-issues">{checks.map((x, i) => <li key={i}><b>확인 필요</b> {x}</li>)}</ul>}
      <div className="btn-row">
        <Button variant="primary" disabled={busy} onClick={() => approve(d.draft_id)}>{approved ? "다시 승인" : "승인"}</Button>
        <Button onClick={copy}>{copied ? "복사됨" : "복사"}</Button>
        {/* Button 부품은 ref 를 넘기지 않아 같은 모양의 button 을 직접 쓴다 (포커스 되돌리기) */}
        <button ref={regenBtn} type="button" className="btn text" disabled={busy} onClick={regen}>{busy ? "만드는 중…" : "다시 만들기"}</button>
      </div>
      <p className="small muted" role="status">{busy ? "이 글만 다시 만들고 있어요. 다른 글의 승인과 고친 내용은 그대로예요." : note}</p>
      <p className="small muted">{d.model || ""}{d.elapsed_ms ? ` · ${(d.elapsed_ms / 1000).toFixed(1)}초` : ""}</p>
    </Panel>
  );
}
