// AI에게 묻기 서랍 (오른쪽, 모든 화면에서 열림. Figma 화면 12). 넓은 화면 = 오른쪽 400px, 760px 이하 = 아래에서 올라오는 시트(layout.css).
// 위에서부터: 머리(제목·대화 지우기·닫기) → 조건 칩 줄·범위 안내 → 대화(스크롤) → 오류 → 입력줄(고정).
// 처음 열 때만 상권 채팅을 시작한다 (열기 전에는 아무 호출도 하지 않아 첫 화면 로딩에 영향이 없음)
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useStore, getState, openDrawer } from "../../state/store.js";
import { homeSnap, snapValue, marketScope } from "../../lib/domain.js";
import { Button, Notice } from "../../components/ui.jsx";
import { CHAT_TOPICS, CHAT_STATUS, chatValue, chatQuarter, chatUrl, chatCondParts, chatBlocks, chatPieces } from "./chat.js";
import {
  useChat, getChat, setDraft, chatSend, chatChoose, chatClear, chatHome, chatStart, chatRetry, chatReset, chatSeenEpoch,
  chatDisarm, chatHighlight, takeSkipFocus,
} from "./state.js";
import "./assistant.css";

const STATE_TONE = { down: "bad", error: "bad", no_data: "warn", off: undefined, disabled: undefined };

// 홈 '상권 저녁 매출'(공통 업종 17~24시)과 여기 답(고른 업종 하나, 하루 전체)의 범위가 다르다는 한 줄 (11/18, 예전 chatScopeNote)
function scopeLine(briefing) {
  const s = homeSnap(briefing);
  return s ? `홈의 '상권 저녁 매출' ${snapValue(s)}는 ${[s.area_name, marketScope(s)].filter(Boolean).join(" · ")} 기준이에요. `
    + "여기 답은 위 조건(업종 하나, 하루 전체) 기준이라 숫자가 다를 수 있어요." : "";
}

// 진행 줄: busy 이면 점이 깜박이고 걸린 초를 보인다 (초는 읽기 프로그램에 읽히지 않게). 20초가 넘으면 '길면 1분 넘게' 덧붙임
function StatusLine({ status }) {
  const [sec, setSec] = useState(0);
  useEffect(() => {
    setSec(0);
    if (!status.text || !status.busy) return undefined;
    const t0 = Date.now();
    const t = setInterval(() => setSec(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(t);
  }, [status.seq]);   // eslint-disable-line react-hooks/exhaustive-deps
  const text = status.busy && sec >= 20 ? `${status.text}. 길면 1분 넘게 걸려요` : status.text;
  return (
    <p id="assistant-status" className={["chat-status", status.busy && "busy"].filter(Boolean).join(" ")} role="status">
      {text && <span className={status.srOnly ? "sr" : undefined}>{text}</span>}
      {status.busy && <span className="chat-sec" aria-hidden="true">{sec >= 3 ? `${sec}초` : ""}</span>}
    </p>
  );
}

// 한 줄: 글과 인용 버튼. 이 답에 없는 근거 번호는 글자 그대로
function Line({ line, cite }) {
  return chatPieces(line).map((p, i) => (p.cite ? <span key={i}>{cite(p.cite) || p.raw}</span> : <span key={i}>{p.text}</span>));
}

// 근거 카드 하나
function EvCard({ c, domId, hl }) {
  const nums = (Array.isArray(c.values) ? c.values : []).filter((v) => v && typeof v.value === "number");
  const warnings = (Array.isArray(c.warnings) ? c.warnings : []).filter((w) => typeof w === "string" && w);
  const src = c.source_ref || {};
  const href = chatUrl(src.source_url);
  return (
    <li id={domId} className={["chat-ev-card", hl && "hl"].filter(Boolean).join(" ")} tabIndex={-1}>
      <div className="chat-ev-head">
        <span className="chat-ev-id">{c.id}</span>
        <span className="chat-ev-topic">{CHAT_TOPICS[c.topic] || c.topic || ""}</span>
        {CHAT_STATUS[c.status] && <span className="chat-ev-st">{CHAT_STATUS[c.status]}</span>}
      </div>
      {c.text && <p className="chat-ev-text">{chatQuarter(c.text)}</p>}
      {nums.length > 0 && (
        <table className="chat-ev-table">
          <thead className="sr"><tr><th scope="col">항목</th><th scope="col">값</th><th scope="col">비중</th></tr></thead>
          <tbody>
            {nums.slice(0, 12).map((v, i) => (
              <tr key={i}>
                <th scope="row">{chatQuarter(v.group ? `${v.group} ${v.label}` : v.label)}</th>
                <td>{chatValue(v.value, v.unit)}</td>
                <td className="share">{typeof v.share_percent === "number" ? chatValue(v.share_percent, "%") : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {nums.length > 12 && <p className="chat-ev-more">숫자 {nums.length}개 중 12개만 보여요.</p>}
      {warnings.length > 0 && <ul className="chat-ev-warn">{warnings.map((w, i) => <li key={i}>{chatQuarter(w)}</li>)}</ul>}
      {(src.source_title || src.data_version) && (
        <p className="chat-ev-src">
          {src.source_title && <>출처: {href ? <a href={href} target="_blank" rel="noopener noreferrer">{src.source_title}</a> : src.source_title}</>}
          {src.data_version && `${src.source_title ? " · " : ""}자료 버전 ${src.data_version}`}
        </p>
      )}
    </li>
  );
}

// 비서 답 하나: 글(목록·참고·해석·다음으로) → 근거 n개 → 자료 기준 안내, 말풍선 아래 선택지. live = 마지막 답 (선택지를 누를 수 있음)
function BotMsg({ item, live, off, hl }) {
  const reply = item.data?.reply || {};
  const cards = (Array.isArray(item.data?.cards) ? item.data.cards : []).filter((c) => c && c.id);
  const [evOpen, setEvOpen] = useState(false);
  const byId = new Set(cards.map((c) => String(c.id)));
  const domId = (id) => `assistant-ev-${item.id}-${id}`;
  // 인용 [F1]을 누르면 근거를 펼치고 그 카드를 강조한다
  const show = (id) => { setEvOpen(true); chatHighlight(item.id, id, domId(id)); };
  const cite = (id) => (byId.has(id)
    ? <button type="button" className="chat-cite" aria-label={`근거 ${id} 보기`} onClick={() => show(id)}>{id}</button>
    : null);
  const actions = (Array.isArray(reply.actions) ? reply.actions : []).filter((a) => a && a.label);
  const notes = (Array.isArray(reply.notes) ? reply.notes : []).filter((n) => typeof n === "string" && n);
  return (
    <div className="chat-msg bot" data-msg={item.id}>
      <div className="chat-answer">
        <div className="chat-text">
          {chatBlocks(reply.text).map((b, i) => (b.type === "ul"
            ? <ul key={i}>{b.items.map((t, j) => <li key={j}><Line line={t} cite={cite} /></li>)}</ul>
            : (
              <p key={i} className={b.kind ? `chat-ln-${b.kind}` : undefined}>
                {b.lead && <b>{b.lead}</b>}<Line line={b.line} cite={cite} />
              </p>
            )))}
        </div>
        {cards.length > 0 && (
          <details className="chat-fold chat-ev" open={evOpen} onToggle={(e) => setEvOpen(e.currentTarget.open)}>
            <summary>근거 {cards.length}개</summary>
            <ol className="chat-ev-list">
              {cards.map((c, i) => <EvCard key={i} c={c} domId={domId(c.id)} hl={hl === `${item.id}:${c.id}`} />)}
            </ol>
            <p className="chat-ev-note">상권 통계는 상권·업종 전체의 추정치예요. 우리 가게 매출이 아니에요.</p>
          </details>
        )}
        {notes.length > 0 && (
          <details className="chat-fold chat-notes">
            <summary>자료 기준 안내</summary>
            <ul>{notes.map((n, i) => <li key={i}>{chatQuarter(n)}</li>)}</ul>
          </details>
        )}
      </div>
      {actions.length > 0 && (
        <div className="chat-actions" role="group" aria-label="선택지">
          {actions.map((a, i) => (
            <Button key={i} size="small" className="chat-pick" aria-current={item.picked === i ? "true" : undefined}
              disabled={!live || off} onClick={() => chatChoose(item.id, i, a)}>
              {chatQuarter(a.label)}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Drawer() {
  const open = useStore((s) => s.drawerOpen);
  const epoch = useStore((s) => s.epoch);
  const briefing = useStore((s) => s.briefing);
  const c = useChat();
  const [scrolled, setScrolled] = useState(false);
  const qRef = useRef(null);
  const opener = useRef(null);
  const wasOpen = useRef(false);
  const wantQ = useRef(false);      // 열었는데 아직 준비 중이라 입력칸이 막혀 있음 → 준비되면 입력칸으로
  const off = !c.ready || c.busy;

  // 가게가 바뀌면 (예전 chatReset): 대화·조건을 비우고, 서랍이 열려 있으면 새 가게로 다시 시작
  useEffect(() => {
    const seen = getChat().epoch;
    if (seen === null) { chatSeenEpoch(epoch); return; }
    if (seen !== epoch) chatReset(epoch, getState().drawerOpen);
  }, [epoch]);

  // 열기·닫기 (예전 toggleAssistant). 열면 질문 칸(준비 중이면 닫기)에 포커스, 닫으면 연 버튼(없으면 상단 'AI에게 묻기')으로 돌려준다
  useEffect(() => {
    if (open) {
      wasOpen.current = true;
      const a = document.activeElement;
      if (a && a !== document.body && !a.closest("#assistant")) opener.current = a;
      if (qRef.current && !qRef.current.disabled) qRef.current.focus();
      else { wantQ.current = true; document.getElementById("assistant-close")?.focus(); }
      if (!getChat().started) chatStart();
      return;
    }
    if (!wasOpen.current) return;
    wasOpen.current = false; wantQ.current = false;
    chatDisarm();
    if (takeSkipFocus()) return;
    const o = opener.current;
    const back = o && o.isConnected && o.offsetParent !== null ? o : document.querySelector('.top [aria-controls="assistant"]') || document.querySelector('[aria-controls="assistant"]');
    if (back && !back.hidden) back.focus();
  }, [open]);

  // 준비가 끝나면 (닫기 버튼에 머물러 있을 때만) 입력칸으로
  useEffect(() => {
    if (!wantQ.current || c.loading) return;
    wantQ.current = false;
    const a = document.activeElement;
    if (c.ready && open && (a === document.body || a?.id === "assistant-close")) qRef.current?.focus({ preventScroll: true });
  }, [c.ready, c.loading, open]);

  // Esc 로 닫기 (한글 입력 중 제외, 위에 대화상자가 떠 있으면 그 창이 먼저)
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === "Escape" && !e.isComposing && !document.querySelector("dialog[open]")) openDrawer(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  // 높이 자라는 입력칸 (최대 140px)
  useLayoutEffect(() => {
    const q = qRef.current;
    if (!q) return;
    q.style.height = "auto";
    q.style.height = Math.min(q.scrollHeight, 140) + "px";
  }, [c.draft, open]);

  const parts = chatCondParts(c.conditions);
  const note = c.conditions ? scopeLine(briefing) : "";
  const homeLabel = c.atHome ? "우리 가게 기준 적용 중" : c.homeFlash ? "✓ 맞췄어요" : "우리 가게 조건으로";
  // 좁은 서랍에서도 한 줄에 들어가게 짧게
  const placeholder = c.busy ? "답을 기다리고 있어요…" : c.ready ? "상권·리뷰·마케팅 무엇이든 물어보세요" : c.loading ? "준비하고 있어요…" : "지금은 물어볼 수 없어요";
  const chipTitle = c.chips.starters ? "이렇게 물어보세요" : "이어서 물어보기";
  const sc = c.stateCard;

  return (
    <aside id="assistant" className={["drawer", "chat-drawer", scrolled && "scrolled"].filter(Boolean).join(" ")} aria-labelledby="assistant-title" hidden={!open}>
      <div className="chat-head">
        <h2 id="assistant-title">AI에게 묻기</h2>
        <div className="chat-head-btns">
          <Button id="assistant-clear" size="small" className={["chat-clear", c.armed && "armed"].filter(Boolean).join(" ")}
            hidden={!c.ready || !c.items.length} disabled={c.busy} onClick={chatClear}>
            {c.armed ? "한 번 더 누르면 지워요" : "대화 지우기"}
          </Button>
          <Button id="assistant-close" size="small" aria-label="AI에게 묻기 닫기" onClick={() => openDrawer(false)}>닫기</Button>
        </div>
      </div>

      <div id="assistant-cond" className="chat-cond" hidden={!parts.length}>
        <div className="chat-cond-row">
          <p id="assistant-cond-text" className="chat-cond-chips">
            <span className="sr">분석 조건: </span>
            {parts.map((p) => <span key={p} className="chat-cond-chip">{p}</span>)}
          </p>
          {/* 채팅에서 다른 곳을 보고 있어도 우리 가게 조건으로 되돌림 (setup?force=1). 이미 기본 조건이면 누를 수 없음 */}
          <Button id="assistant-home" size="small" className={["chat-home", c.atHome && "on"].filter(Boolean).join(" ")}
            disabled={off || c.atHome} onClick={chatHome}>{homeLabel}</Button>
        </div>
        {note && <p id="assistant-cond-note" className="chat-cond-note">{note}</p>}
      </div>

      {/* 대화를 내리면 머리와 대화 칸 사이에 가는 선 (맨 위에서는 선 없이) */}
      <div id="assistant-scroll" className="chat-body" onScroll={(e) => setScrolled(e.currentTarget.scrollTop > 0)}>
        {sc && (
          <Notice id="assistant-state" tone={STATE_TONE[sc.key]} role="group" aria-labelledby="assistant-state-title" data-state={sc.key} className="chat-state">
            <div className="chat-state-text">
              <p id="assistant-state-title" className="strong">{sc.title}</p>
              <p id="assistant-state-msg">{sc.msg}</p>
            </div>
            <Button id="assistant-retry" size="small" disabled={c.loading} onClick={chatRetry}>{c.loading ? "확인하는 중…" : "다시 확인"}</Button>
          </Notice>
        )}
        {c.welcome && (
          <div id="assistant-welcome" className="chat-welcome">
            <h3>우리 가게 상권, 편하게 물어보세요</h3>
            <p><b>동네 상권·업종 매출 상담</b>이에요. 서울시 공개 상권 자료로 매출·점포 수·유동인구를 알려 드려요. 숫자마다 근거 번호가 붙고, 누르면 원래 자료를 볼 수 있어요.</p>
            <p>가게 이름·메뉴 같은 기본 정보와 리뷰·답글을 어디서 보는지도 답해요.</p>
            <p>불만 리뷰·쿠폰 손익·남은 재료·광고비·리포트를 물으면 지금 가게의 현황을 짚고, 버튼 하나로 그 화면으로 안내해요.</p>
            <p className="small muted">상권 통계는 상권·업종 전체의 추정치예요. 우리 가게 매출이 아니에요.</p>
          </div>
        )}
        <div id="assistant-log" className="chat-log" role="log" aria-live={c.logLive} aria-label="대화 기록">
          {c.items.map((it) => (it.type === "user"
            ? (
              <div key={it.id} className="chat-msg user" data-msg={it.id}>
                <p className="chat-bubble">{it.text}</p>
                {it.failed && <p className="chat-fail">보내지 못했어요</p>}
              </div>
            )
            : <BotMsg key={it.id} item={it} live={it.id === c.latest} off={off} hl={c.hl} />))}
        </div>
        <StatusLine status={c.status} />
        {/* 추천 질문: 대화가 비었으면 고정 질문(작은 카드), 그 뒤에는 마지막 답의 suggestions(칩 줄) */}
        <div id="assistant-chips" className={["chat-chips", c.chips.starters && "starters"].filter(Boolean).join(" ")}
          role="group" aria-label={c.chips.list.length ? chipTitle : "추천 질문"} hidden={!c.chips.list.length}>
          <p className="chat-chips-title" aria-hidden="true">{chipTitle}</p>
          <div className="chat-chips-list">
            {c.chips.list.map((q) => (
              <button key={q} type="button" className="chat-chip" disabled={off} onClick={() => chatSend(q)}>{q}</button>
            ))}
          </div>
        </div>
      </div>

      <p id="assistant-error" className="chat-error" role="alert">{c.error}</p>
      <form id="assistant-form" className="chat-input" noValidate onSubmit={(e) => { e.preventDefault(); chatSend(c.draft); }}>
        <label htmlFor="assistant-q" className="sr">질문</label>
        <textarea id="assistant-q" ref={qRef} rows={1} maxLength={1000} placeholder={placeholder} autoComplete="off" disabled={off}
          value={c.draft} onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            // 한글 입력 중의 Enter 는 글자를 확정할 뿐 보내지 않는다 (isComposing, Safari 는 keyCode 229). Shift+Enter 는 줄바꿈
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) { e.preventDefault(); chatSend(e.currentTarget.value); }
          }} />
        <Button id="assistant-send" type="submit" variant="primary" disabled={off || !c.draft.trim()}>보내기</Button>
      </form>
      <p className="chat-foot">
        <span className="chat-hint">Enter 보내기 · Shift+Enter 줄바꿈</span>
        <span id="assistant-count">{c.draft.length >= 900 ? `${c.draft.length} / 1000자` : ""}</span>
      </p>
    </aside>
  );
}
