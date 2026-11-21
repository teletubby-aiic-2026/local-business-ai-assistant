// 리뷰 넣기 탭: 붙여넣기(+ 분류 결과) | 캡처로 넣기 두 칸 (Figma 06 C2). 예전 paste·resetPaste·renderPasteResult
// 붙여넣기는 POST /api/reviews → 결과(감정·주제·들어간 묶음)를 보이고, 홈 숫자·추천 카드·요약·묶음을 모두 다시 불러온다 (refresh).
// 끝난 뒤 안내는 '저장하고 분석 결과를 갱신했어요' 한 줄 (다시 불러온 화면을 하나하나 늘어놓지 않음)
import { Badge, Button, Panel } from "../../components/ui.jsx";
import { api } from "../../lib/api.js";
import { getState, setState, useStore } from "../../state/store.js";
import { refresh } from "../../state/boot.js";
import { CHANNELS, PASTE_SAMPLES, RATINGS, SENTIMENT_NAMES, REPEAT_NOTE, pasteJoin, topicName, methodName } from "./calc.js";
import { getMod, setPaste, showTab, useMod } from "./state.js";
import Capture from "./Capture.jsx";

const focusText = () => document.getElementById("paste-text")?.focus();

async function paste() {
  const p = getMod().paste;
  const text = p.text.trim();
  if (!text) { setPaste({ msg: "리뷰 글을 넣어 주세요." }); focusText(); return; }
  const ep = getState().epoch, alive = () => getState().epoch === ep;   // 그 사이 가게가 바뀌면 옛 가게 결과를 버린다
  const body = { text, rating: p.rating ? Number(p.rating) : null };
  if (p.channel) body.channel = p.channel;   // 고른 경우만 (안 고르면 예전과 같은 본문)
  setPaste({ busy: true, msg: "분류하는 중…" });
  try {
    const r = await api("/api/reviews", { method: "POST", body: JSON.stringify(body) });
    if (!alive()) return;
    setState({ joined: r.joined_issues || [] });
    setPaste({ result: r, text: "", rating: "", msg: "리뷰를 저장했어요. 분석 결과를 갱신하는 중…" });
    await refresh();   // 홈 숫자 · 추천 카드 · 리뷰 분석(요약·묶음)을 모두 새로
    if (alive()) setPaste({ msg: "리뷰를 저장하고 분석 결과를 갱신했어요." });
  } catch (e) { if (alive()) setPaste({ msg: e.message }); }
  finally { if (alive()) setPaste({ busy: false }); }
}

async function resetPaste() {
  const ep = getState().epoch, alive = () => getState().epoch === ep;
  setPaste({ resetBusy: true });
  try {
    const r = await api("/api/reviews/pasted", { method: "DELETE" });
    if (!alive()) return;
    setState({ joined: [] });
    setPaste({ result: null });
    await refresh();
    if (alive()) setPaste({ msg: `붙여넣은 리뷰${Number.isFinite(r.deleted) ? ` ${r.deleted}건` : ""}을 지우고 분석 결과를 갱신했어요.` });
  } catch (e) { if (alive()) setPaste({ msg: e.message }); }
  finally { if (alive()) setPaste({ resetBusy: false }); }
}

// 분류 결과: 붙여넣기 칸 안, 버튼 아래 (분류하기 전에는 그리지 않음)
function PasteResult({ r }) {
  const insightGroups = useStore((s) => s.insight?.groups);
  if (!r) return null;
  const c = r.classification || {};
  const topics = c.topics || [];
  const { joined, negative } = pasteJoin(r, insightGroups);
  const method = methodName(c.method);
  const warns = (c.warnings || []).filter((w) => typeof w === "string" && w.trim());
  return (
    <section className="an-result" aria-labelledby="an-result-title">
      <h3 id="an-result-title">분류 결과</h3>
      {(method || r.review?.pii_masked) && (
        <p className="small muted an-result-meta">
          {method && <Badge className="an-method">{method}</Badge>}
          {r.review?.pii_masked && <Badge title="전화번호·이메일·링크를 [가림]으로 바꿨어요">개인정보 가림</Badge>}
        </p>
      )}
      <p className="an-rv-text">{r.review?.text || ""}</p>
      <p className="small">감정 <b>{SENTIMENT_NAMES[c.sentiment] || c.sentiment || "?"}</b></p>
      <div className="an-chips">
        {topics.length
          ? topics.map((t, i) => (
            <span key={`${t.topic}-${i}`} className={`an-chip ${t.polarity === "negative" ? "neg" : "pos"}`}>
              {t.polarity === "negative" ? "불만" : "칭찬"} · {topicName(t.topic)}{t.evidence ? ` “${t.evidence}”` : ""}
            </span>))
          : <span className="small muted">찾은 주제가 없어요.</span>}
      </div>
      <p className="small an-joined">
        {joined.length
          ? <>→ 불만 묶음에 들어갔어요: <b>{joined.join(", ")}</b> <Button size="small" onClick={() => showTab("issues", true)}>불만 묶음 보기</Button></>
          : negative ? `→ 아직 어느 묶음에도 들지 않았어요 (${REPEAT_NOTE}).` : "→ 불만 주제가 없어 묶음에는 들지 않아요."}
      </p>
      {warns.length > 0 && (
        <details className="an-warns">
          <summary>AI 결과를 고친 곳 {warns.length}건</summary>
          <ul>{warns.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </details>
      )}
    </section>
  );
}

export default function PasteTab() {
  const p = useMod((m) => m.paste);
  return (
    <div className="grid-2 an-paste-grid">
      <Panel title="붙여넣기" titleId="an-paste-title" className="an-paste">
        <div className="field">
          <label htmlFor="paste-text" className="sr">리뷰 글</label>
          <textarea id="paste-text" className="input" rows={4} maxLength={1000} placeholder="리뷰 글을 붙여 넣으세요 (1000자까지)"
            aria-describedby="paste-pii" value={p.text} onChange={(e) => setPaste({ text: e.target.value })} />
        </div>
        <div className="grid-2 an-paste-opts">
          <label className="field" htmlFor="paste-channel">채널
            <select id="paste-channel" className="input" value={p.channel} onChange={(e) => setPaste({ channel: e.target.value })}>
              {CHANNELS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
            </select>
          </label>
          <label className="field" htmlFor="paste-rating">별점
            <select id="paste-rating" className="input" value={p.rating} onChange={(e) => setPaste({ rating: e.target.value })}>
              {RATINGS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
            </select>
          </label>
        </div>
        <div className="btn-row an-samples">
          <span className="small muted">예시:</span>
          {PASTE_SAMPLES.map((s, i) => (
            <Button key={i} size="small" title={s.text} onClick={() => { setPaste({ text: s.text, rating: String(s.rating) }); focusText(); }}>
              {s.text.slice(0, 16)}…
            </Button>
          ))}
        </div>
        <div className="btn-row">
          <Button variant="primary" onClick={paste} disabled={p.busy}>분류하기</Button>
          <Button onClick={resetPaste} disabled={p.resetBusy}>붙여넣은 리뷰 지우기</Button>
        </div>
        <p id="paste-pii" className="small muted">개인정보(전화번호·이메일·링크)는 저장 전에 가려요.</p>
        <p className="small muted an-msg" role="status">{p.msg}</p>
        <PasteResult r={p.result} />
      </Panel>
      <Capture />
    </div>
  );
}
