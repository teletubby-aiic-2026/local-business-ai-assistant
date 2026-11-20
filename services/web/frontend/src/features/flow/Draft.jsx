// 3 승인할 글 (예전 renderDraft·sourceBlock·rerunPaint. 배치는 Figma 06 B3). 원 리뷰와 AI 초안을 위아래로, 고치고 승인.
// 진행 숫자(승인 n / 전체 · 지금 글 이름)는 맨 위 진행줄 하나에만 두고, 맨 아래 '초안 목록'은 글마다 상태 배지만 보인다.
// 초안 상자: 글 칸 → 점검 칩 줄(점검 통과·확인 필요·점검 실패) → 고칠 곳 상자 → 승인·복사·다시 만들기.
// 고친 글은 store 의 pending 에 바로 담는다 (예전 saveEdits: 다시 그려도·다른 화면에 다녀와도 남음).
import { useEffect, useRef, useState } from "react";
import { useStore, setState } from "../../state/store.js";
import { genName, KIND_NAMES, KIND_AGENT, SOURCE_NAMES, praiseOf, shortBasis } from "../../lib/domain.js";
import { PageHead, Panel, Badge, Button, Empty } from "../../components/ui.jsx";
import Steps from "./Steps.jsx";
import { useFlow, setFlow } from "./state.js";
import { approve, regenDraft, rerunCard, copyText } from "./actions.js";
import { RULES_TITLE, RERUN_LABEL, FALLBACK_CHIP, failedOf, checksOf, draftStateText, isFallback, listBadges, regenKey, textOf, touchedOf, pickCurrent, starText } from "./calc.js";
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
        <Panel><Empty title="아직 만든 글이 없어요." action={<a className="btn primary" href="#/cards">추천 카드 보기</a>} /></Panel>
      </div>
    );
  }

  const p = s.cards.find((x) => x.card.card_id === current);
  const r = s.results[current];
  const d = drafts.find((x) => x.draft_id === draftId);
  const done = drafts.filter((x) => s.approved.has(x.draft_id)).length;
  const armed = f.armed === current;
  const rerunBusy = f.busy[current] === "rerun";
  const measures = r.chosen_measures || [];
  const skipped = r.pasted_reply_skipped || [];

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
      {/* 고른 수칙 · 답글을 못 만든 붙여넣은 리뷰는 늘 보이고, 서버의 글 출처 설명(source_note: 저장본 이름 등)은 접어 둔다.
          '실제 AI 결과 아님'은 머리의 출처 배지와 맨 위 시험용 띠가 이미 말한다 */}
      {(measures.length > 0 || skipped.length > 0 || r.source_note) && (
        <div className="stack-8">
          {measures.length > 0 && (
            <p className="small">{RULES_TITLE}: {measures.map((m) => m.text).join(", ")} <span className="muted">· {r.source === "seed" ? "예시 글이라 반영되지 않아요" : "안내문에 반영"}</span></p>
          )}
          {skipped.length > 0 && <p className="small flow-warn">붙여넣은 불만 리뷰 {skipped.length}건은 답글을 만들지 않았어요{skipped[0]?.reason ? ` (${skipped[0].reason})` : ""}.</p>}
          {r.source_note && (
            <details className="flow-more">
              <summary className="small">글 출처</summary>
              <p className="small muted">{r.source_note}</p>
            </details>
          )}
        </div>
      )}

      <div className="stack-8">
        <div className="flow-progress">
          <span className="flow-progress-text"><span>승인 {done} / {drafts.length}</span>{d && <span className="flow-progress-now"> · {genName(d.generator, p.title)}</span>}</span>
          <Button disabled={!!f.busy[current]} onClick={() => rerunCard(current)}>
            {rerunBusy ? "만드는 중…" : armed ? "한 번 더 눌러 실행" : RERUN_LABEL}
          </Button>
        </div>
        <p className="small muted flow-rerun-note" role="status">{armed ? `한 번 더 누르면 승인했거나 고친 글 ${touchedOf(s, current)}개까지 모두 새 글로 바뀌어요.` : ""}</p>
      </div>

      {d ? <>
        <SourcePanel p={p} d={d} reviews={s.reviewsById} />
        <DraftPanel key={d.draft_id} d={d} s={s} busy={f.regen.has(regenKey(current, d))} note={f.note?.id === d.draft_id ? f.note.text : ""} />
      </> : <Panel><p className="muted">이 카드에서 만든 글이 없어요.</p></Panel>}

      <Panel title="초안 목록" titleId="flow-list-title" sub={`${drafts.length}개`}>
        <ol className="plain flow-list" aria-labelledby="flow-list-title">
          {drafts.map((x, i) => (
            <li key={x.draft_id}>
              <button type="button" aria-current={x.draft_id === draftId ? "true" : undefined}
                onClick={() => { setFlow({ note: null }); setState({ draftId: x.draft_id }); }}>
                <span className="flow-list-name">{i + 1}. {genName(x.generator, p.title)}</span>
                <span className="flow-list-badges">{listBadges(x, s.approved).map(([tone, text]) => <Badge key={text} tone={tone || undefined}>{text}</Badge>)}</span>
              </button>
            </li>
          ))}
        </ol>
      </Panel>
    </div>
  );
}

// 이 글이 답하는 원 리뷰. 답글 = 그 리뷰 1건, 공지 = 카드 근거 리뷰, 홍보글 = 근거 지표 + 쿠폰 메뉴를 칭찬한 손님 리뷰
function SourcePanel({ p, d, reviews }) {
  const ev = p.evidence || [];
  const target = d.target_review_id ? reviews[d.target_review_id] : null;
  let body, sub;
  if (target) body = <ul className="plain flow-rv-list"><ReviewItem r={target} /></ul>;
  else {
    const rs = ev.filter((e) => e.type === "review").map((e) => reviews[e.id] || { text: e.text });
    if (rs.length) { sub = `근거 리뷰 ${rs.length}건`; body = <ul className="plain flow-rv-list">{rs.map((x, i) => <ReviewItem key={i} r={x} />)}</ul>; }
    else {
      const snaps = ev.filter((e) => e.type === "snapshot");
      const praise = praiseOf(p);
      const praised = praise.shown.map((e) => reviews[e.id] || { text: e.text, rating: e.rating });
      if (!snaps.length && !praised.length) return null;
      body = <>
        {snaps.length > 0 && <Block title="근거 지표">{snaps.map((e, i) => <div key={i} className="flow-rv-box"><p>{e.text}</p><p className="small muted">{shortBasis(e.basis)}</p></div>)}</Block>}
        {praised.length > 0 && <Block title={`손님 칭찬 리뷰 · ${praise.menu} 언급 ${praise.total}건${praise.total > praised.length ? ` 중 ${praised.length}건` : ""}`}>
          <ul className="plain flow-rv-list">{praised.map((x, i) => <ReviewItem key={i} r={x} />)}</ul></Block>}
      </>;
    }
  }
  return <Panel title="손님 리뷰" titleId="flow-rv-title" sub={sub}>{body}</Panel>;
}

// 근거 묶음 (홍보글: 근거 지표 · 손님 칭찬 리뷰). 리뷰·지표마다 회색 상자라 묶음 자체는 면 없이 제목만
const Block = ({ title, children }) => <div className="stack-8"><p className="small strong muted">{title}</p>{children}</div>;

function ReviewItem({ r }) {
  const when = String(r.created_at || "").slice(5, 16).replace("T", " ");
  const stars = starText(r.rating);
  return (
    <li className="flow-rv-box">
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

// 초안 상자: 편집 칸 → 점검 칩 줄 → 고칠 곳 → 승인·복사·다시 만들기.
// 칩은 색과 함께 모양(● ▲ ■)으로도 나눈다. 점검을 못 넘어 정해 둔 기본 문장으로 바꾼 글(checks.used_fallback)은
// '점검 통과'를 붙이지 않고 '기본 문장으로 바꿈' 칩(주의 색)과 이유·확인 안내 한 줄로 밝히고 모델 표시는 뺀다 (11/21 실시간 확인 M2)
function DraftPanel({ d, s, busy, note }) {
  const box = useRef(null);
  const regenBtn = useRef(null);
  const [copied, setCopied] = useState(false);
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  const failed = failedOf(d), checks = checksOf(d);
  const approved = s.approved.has(d.draft_id);
  const statusText = draftStateText(d, s.approved);
  const name = genName(d.generator, (s.cards.find((x) => x.card.card_id === (d.card_id || s.current)) || {}).title);
  const textId = `flow-text-${d.draft_id}`;
  const fallback = isFallback(d);

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
    <Panel className={approved ? "flow-draft-box approved" : "flow-draft-box"} title={name} titleId="flow-draft-title" id={`draft-${d.draft_id}`}>
      <div className="field">
        <label htmlFor={textId} className="flow-reply-label">AI {name} 초안<span className="sr"> ({statusText})</span></label>
        <textarea ref={box} id={textId} className="input flow-textarea" rows={7} readOnly={busy} value={textOf(s, d)}
          onChange={(e) => { const v = e.target.value; setState((st) => ({ pending: { ...st.pending, [d.draft_id]: v } })); }} />
      </div>
      <p className="flow-checks">
        {approved && <Badge tone="ok" className="flow-chk ok">승인 완료</Badge>}
        {!failed.length && !checks.length && !approved && !fallback && <Badge tone="ok" className="flow-chk ok">점검 통과</Badge>}
        {checks.length > 0 && <Badge tone="warn" className="flow-chk warn">확인 필요 {checks.length}</Badge>}
        {failed.length > 0 && <Badge tone="bad" className="flow-chk bad">점검 실패 {failed.length}</Badge>}
        {fallback && <Badge tone={approved ? undefined : "warn"} className="flow-chk">{FALLBACK_CHIP}</Badge>}
      </p>
      {fallback && <p className="small muted flow-fallback-note">AI 글이 점검을 넘지 못해 기본 문장으로 바꿨어요.{approved ? "" : " 리뷰 내용과 맞는지 확인하고 고쳐서 승인해 주세요."}</p>}
      {failed.length > 0 && <ul className="plain flow-issues bad">{failed.map((x, i) => <li key={i}><b>점검 실패</b> · {x}</li>)}</ul>}
      {checks.length > 0 && <ul className="plain flow-issues">{checks.map((x, i) => <li key={i}><b>확인 필요</b> · {x}</li>)}</ul>}
      <div className="btn-row">
        <Button variant="primary" disabled={busy} onClick={() => approve(d.draft_id)}>{approved ? "다시 승인" : "승인"}</Button>
        <Button onClick={copy}>{copied ? "복사됨" : "복사"}</Button>
        <Button ref={regenBtn} variant="text" disabled={busy} onClick={regen}>{busy ? "만드는 중…" : "다시 만들기"}</Button>
      </div>
      <p className="small muted" role="status">{busy ? "이 글만 다시 만들고 있어요. 다른 글은 그대로예요." : note}</p>
      {/* 기본 문장으로 바꾼 글에는 모델 이름·걸린 시간을 붙이지 않는다 (모델이 쓴 글이 아니므로, 11/20 박건영 결정) */}
      {!fallback && <p className="small muted">{d.model || ""}{d.elapsed_ms ? ` · ${(d.elapsed_ms / 1000).toFixed(1)}초` : ""}</p>}
    </Panel>
  );
}
