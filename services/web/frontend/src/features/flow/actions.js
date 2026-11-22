// 오늘 할 일 흐름의 동작 (예전 app.js runCard·choose·runTodo·regenDraft·rerunCard·approve·copyDraft·restart·staffGo).
// 진행 결과는 store.js(results·approved·approvedLog·pending·current·draftId), 버튼 잠금·안내는 ./state.js.
import { api } from "../../lib/api.js";
import { go, navTo, currentRoute } from "../../lib/router.js";
import { draftsOf, genName } from "../../lib/domain.js";
import { getState, setState, setAlert } from "../../state/store.js";
import { emptyFlow, staffApprovals } from "../../state/boot.js";
import { forgetFlow } from "../../state/flowKeep.js";
import { waitingCount } from "../../state/staff.js";
import { getFlow, setFlow, resetFlow } from "./state.js";
import {
  RERUN_ARM_MS, REPLACES_MAX, measureIds, replacesOf, priorApprovals, regenKey, sameSlot, failedOf, checksOf,
  textOf, touchedOf, findDraft, cardIdOfDraft, cardOfDraft, mapDraft, regenNote,
} from "./calc.js";

// 카드 전체 실행마다 붙이는 번호. 늦게 온 '다시 만들기' 응답이 그사이 다시 만든 카드에 끼어들지 않게 견준다.
// 새로고침하면 0부터 다시 세므로, 되살린 진행(state/flowKeep.js)의 _run 보다 늘 크게 매긴다 (runCard)
let runSeq = 0;

// 글 id 들의 승인·고친 내용·처리 완료 기록을 뺀 상태 조각
function dropDrafts(s, gone) {
  const pending = { ...s.pending };
  gone.forEach((id) => delete pending[id]);
  return {
    approved: new Set([...s.approved].filter((id) => !gone.has(id))),
    pending,
    approvedLog: s.approvedLog.filter((x) => !gone.has(x.id)),
  };
}

const unbusy = (cardId) => setFlow((f) => { const busy = { ...f.busy }; delete busy[cardId]; return { busy }; });

// 카드 한 장의 글을 모두 만든다 (처음, 또는 '카드 전체 다시 만들기'). source: 누른 곳 (그 버튼만 '만드는 중…')
export async function runCard(cardId, source = "card") {
  const s = getState();
  if (getFlow().busy[cardId]) return false;
  const p = s.cards.find((x) => x.card.card_id === cardId);
  const epoch = s.epoch;
  setFlow((f) => ({ busy: { ...f.busy, [cardId]: source } }));
  try {
    // 점검 수칙 상자가 있는 카드만 measures 를 보낸다
    const picked = (p?.measures?.options || []).length ? { measures: measureIds(p, s.results, getFlow().picks) } : null;
    // 카드 전체 다시 만들기면 지금 글 id 를 replaces 로 더한다. 처음 만들 때는 예전과 같은 본문.
    // 이 브라우저에 진행이 없는데 서버에 이 카드의 승인 기록이 있으면(다른 기기·24시간 뒤) 그 글들을 바꾼다: 처리 완료에 같은 글이 두 번 쌓이지 않게
    const before = (s.results[cardId]?.drafts || []).map((d) => d.draft_id);
    const prior = before.length ? [] : priorApprovals(s.serverApprovals, cardId).slice(0, REPLACES_MAX);
    const replaces = before.length ? replacesOf(before, s.approved) : prior;
    const body = replaces.length ? JSON.stringify({ ...(picked || {}), replaces }) : picked ? JSON.stringify(picked) : undefined;
    const result = await api(`/api/cards/${encodeURIComponent(cardId)}/run`, { method: "POST", body });
    if (getState().epoch !== epoch) return false;   // 기다리는 동안 가게가 바뀜: 다른 가게의 글이므로 버린다
    if (result.replace_warning) setAlert(result.replace_warning);   // 새 글은 받았지만 서버의 옛 승인 기록은 못 지움
    // 바꾼 서버 기록은 안내 목록에서도 뺀다 (진행을 다시 비워도 지운 글을 '오늘 승인한 글'로 세지 않게)
    if (prior.length && !result.replace_warning) setState((now) => ({ serverApprovals: now.serverApprovals.filter((x) => !prior.includes(x.draft_id)) }));
    const run = (runSeq = Math.max(runSeq, ...Object.values(getState().results).map((r) => Number(r?._run) || 0)) + 1);
    // 다시 만들면 그 카드의 예전 글 승인·고친 내용은 버린다 (처리 완료의 승인 목록에서도 뺀다)
    setState((now) => ({
      ...dropDrafts(now, new Set((now.results[cardId]?.drafts || []).map((d) => d.draft_id))),
      results: { ...now.results, [cardId]: { ...result, _run: run } },
      current: cardId, draftId: null,
    }));
    setFlow((f) => { const picks = { ...f.picks }; delete picks[cardId]; return { note: null, picks }; });   // 카드는 이제 고른 수칙(chosen_measures)을 보인다
    go("draft");
    return true;
  } catch (e) { setAlert(e.message); return false; }
  finally { unbusy(cardId); }
}

// 카드를 고르면: 이미 만든 글이 있으면 그 글로, 없으면 만들고 초안으로
export async function choose(cardId) {
  if (getState().results[cardId]) { setState({ current: cardId, draftId: null }); go("draft"); return; }
  await runCard(cardId, "card");
}

// 홈 '오늘 할 일' 항목: 아직 안 만든 글은 만들고, 만든 글은 그 종류의 첫 미승인 글을 연다
export async function runTodo(t) {
  if (!t) return;
  const id = t.cid;
  if (!getState().results[id]) {
    await runCard(id, `todo:${t.key}`);
    if (!getState().results[id]) return;   // 실패하면 할 일 목록은 그대로 (잠금만 풀림)
  }
  const s = getState();
  const ds = draftsOf(s.results, id).filter((d) => d.generator === t.gen);
  setState({ current: id, draftId: (ds.find((d) => !s.approved.has(d.draft_id)) || ds[0] || {}).draft_id || null });
  if (currentRoute() !== "draft") go("draft");   // runCard 가 이미 초안으로 옮겼으면 다시 그리지 않는다
}

// 초안 상자의 '다시 만들기': 지금 보는 글 한 건만 새로 만든다 (같은 API 에 generator(+review_id)).
// 그 글의 승인·고친 내용만 지우고, 다른 글의 승인·고친 내용은 그대로 둔다.
export async function regenDraft(id) {
  const s = getState();
  const cardId = s.current, r = s.results[cardId];
  const p = s.cards.find((x) => x.card.card_id === cardId);
  const d = (r?.drafts || []).find((x) => x.draft_id === id);
  if (!p || !d) return;
  const key = regenKey(cardId, d);
  if (getFlow().regen.has(key)) return;
  const body = { generator: d.generator };
  if (d.target_review_id) body.review_id = d.target_review_id;
  body.replaces = [d.draft_id];   // 바뀌는 옛 글: 서버가 새 글을 만든 뒤에만 그 승인 기록을 지운다 (못 만들면 그대로)
  // 불만 카드: 처음 만들 때 고른 수칙을 그대로 보낸다. 공지는 지금 화면의 묶음 답글도 보낸다 (공지가 답글과 너무 비슷한지 서버가 견줌)
  if (p.card.kind === "complaint") body.measures = (r.chosen_measures || []).map((m) => m.id);
  if (d.generator === "prevention_notice") {
    const pasted = new Set(r.pasted_reply_review_ids || []);
    body.reply_texts = r.drafts.filter((x) => x.generator === "reply_draft" && !pasted.has(x.target_review_id)).map((x) => x.text);
  }
  setFlow((f) => ({ regen: new Set([...f.regen, key]), note: null }));
  try {
    const made = await api(`/api/cards/${encodeURIComponent(cardId)}/run`, { method: "POST", body: JSON.stringify(body) });
    const fresh = (made.drafts || [])[0];
    if (!fresh) throw new Error("새 글을 받지 못했어요. 다시 눌러 주세요.");
    if (made.replace_warning) setAlert(made.replace_warning);   // 새 글은 받았지만 서버의 옛 승인 기록은 못 지움
    const now = getState(), cur = now.results[cardId];
    const at = cur && cur._run === r._run ? cur.drafts.findIndex((x) => sameSlot(x, d)) : -1;
    if (at < 0) return;   // 기다리는 동안 카드 전체를 다시 만들었거나 카드·가게가 바뀌었다: 늦게 온 이 글은 버린다
    const gone = cur.drafts[at].draft_id;
    const drafts = cur.drafts.map((x, i) => (i === at ? fresh : x));
    setState((n) => ({
      ...dropDrafts(n, new Set([gone])),
      results: { ...n.results, [cardId]: { ...cur, drafts, flagged_count: drafts.filter((x) => failedOf(x).length || checksOf(x).length).length } },
      draftId: n.draftId === gone ? fresh.draft_id : n.draftId,
    }));
    // 같은 글·또 기본 문장이면 '새로 만들었어요'라고 하지 않고 사실대로 (11/21 실시간 확인 M2)
    setFlow({ note: { id: fresh.draft_id, text: regenNote(d, fresh, made.source) } });
  } catch (e) { setAlert(e.message); }
  finally { setFlow((f) => { const regen = new Set(f.regen); regen.delete(key); return { regen }; }); }
}

export function rerunDisarm() {
  clearTimeout(getFlow().timer);
  setFlow({ armed: null, timer: null });
}

// 진행줄 옆 '카드 전체 다시 만들기': 승인했거나 고치는 중인 글이 있으면 한 번 더 눌러야 실행한다 (대화상자 대신)
export async function rerunCard(cardId) {
  if (touchedOf(getState(), cardId) && getFlow().armed !== cardId) {
    rerunDisarm();
    const timer = setTimeout(() => setFlow({ armed: null, timer: null }), RERUN_ARM_MS);
    setFlow({ armed: cardId, timer });
    return;
  }
  rerunDisarm();
  await runCard(cardId, "rerun");
}

// 승인하면 이 카드의 다음 미승인 글로, 다 끝나면 처리 완료로
export async function approve(id) {
  const s = getState();
  const d = findDraft(s.results, id);
  if (!d) return;
  const text = textOf(s, d);
  const epoch = s.epoch;
  try {
    // 글 종류·카드는 늘 보낸다: 초안을 만든 WAS 와 승인을 받은 WAS 가 달라도 서버 기록에 종류가 남게 (처리 완료의 글 이름, 11/22).
    // 리뷰 답글이면 어느 리뷰의 답글인지도: 서버가 리뷰 분석 서비스에 '답글 달았음'을 기록 (응대 점수·기한). 서버가 아는 초안이면 서버 값이 먼저
    const cardId = cardIdOfDraft(s.results, id);
    const hint = { kind: d.generator, ...(cardId ? { card_id: cardId } : {}), ...(d.target_review_id ? { review_id: d.target_review_id } : {}) };
    const entry = await api(`/api/drafts/${encodeURIComponent(id)}/approve`, { method: "POST", body: JSON.stringify({ text, original: d.text, ...hint }) });
    if (getState().epoch !== epoch) return;
    setState((now) => {
      const pending = { ...now.pending };
      delete pending[id];
      const card = cardOfDraft(now.cards, now.results, id);
      const name = genName(d.generator, card ? card.title : "");
      const log = now.approvedLog.filter((x) => x.id !== id);
      log.push({ id, at: entry.approved_at || new Date().toISOString(), edited: !!entry.edited, kind: d.generator, name,
        title: card ? card.title : "", card: card ? card.title : "", text: entry.text ?? text });
      return {
        results: mapDraft(now.results, id, (x) => ({ ...x, edited_text: entry.edited ? text : null })),
        pending, approved: new Set([...now.approved, id]), approvedLog: log,
      };
    });
    const now = getState();
    const next = draftsOf(now.results, now.current).find((x) => !now.approved.has(x.draft_id));
    if (next) { setState({ draftId: next.draft_id }); window.scrollTo(0, 0); }
    else go("done");
  } catch (e) { setAlert(e.message); }
}

// 복사. 클립보드 API 가 막히면 글 칸(없으면 잠깐 만든 칸)을 골라 execCommand 로
export async function copyText(text, box) {
  try { await navigator.clipboard.writeText(text); return; } catch { /* 아래 방법으로 */ }
  const el = box || Object.assign(document.createElement("textarea"), { value: text, readOnly: true });
  if (!box) { el.style.cssText = "position:fixed;opacity:0;top:0;left:0"; document.body.appendChild(el); }
  el.select();
  try { document.execCommand("copy"); } finally { if (!box) el.remove(); }
}

// 처음부터 다시: 이 브라우저의 진행(만든 글·승인 표시·고친 내용)을 비우고, 서버에 남은 이 방문자의 승인 기록도 지운다 (DELETE /api/approvals).
// 서버는 이 방문자의 맞춤 마케팅 기록도 같이 지우고(marketing_cleared), 맞춤 마케팅의 대화·결과 카드·보고서도 처음으로 (mktResetSeq).
// 이 브라우저에 보관한 진행(localStorage)도 지운다. 서버가 못 지워도 화면은 비우고 알림 띠로 알린다
// (그때는 서버 목록을 다시 읽어 남은 승인 기록을 '오늘 승인한 글'로 안내). 진행을 그대로 두고 홈으로 가는 것은 주 버튼 '홈으로'
export async function restart() {
  let failed = "", cleared = null;
  try { const r = await api("/api/approvals", { method: "DELETE" }); cleared = r.marketing_cleared ?? null; }
  catch (e) { failed = e.message; }
  resetFlow();
  forgetFlow(getState().flowKey);
  // mktCleared: false 면 맞춤 마케팅 화면 위에만 "기록은 지우지 못했어요" 안내 (예전 mktReset(cleared))
  setState((s) => ({ ...emptyFlow(), ...(failed ? {} : { serverApprovals: [] }), mktResetSeq: s.mktResetSeq + 1, mktCleared: failed ? null : cleared }));
  go("today");
  if (failed) { setAlert(`화면은 처음으로 돌렸지만 서버의 승인 기록은 지우지 못했어요. ${failed}`); staffApprovals(); }
}

// 홈 '담당 비서 현황' 칸: 누르면 맡은 화면으로
export function staffGo(key) {
  if (key === "data") navTo("analysis", "summary");
  else if (key === "care") go(waitingCount(getState()) ? "draft" : "cards");
  else if (key === "mkt") go("marketing");
  else if (key === "market") go("market");
}
