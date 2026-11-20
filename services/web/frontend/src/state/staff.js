// 오늘 할 일과 AI 비서 네 명의 상태 (예전 app.js todosOf·renderStaff). 상태만 보고 계산한다 (화면을 만지지 않음).
import { draftsOf, allDrafts, praiseOf, heroProblem, homeSnap, snapValue, marketScope } from "../lib/domain.js";

// 할 일: 카드 ⓐ(불만) → 포장·주문 안내문, 답글 n개 / 카드 ⓑ(홍보) → 쿠폰 홍보글
// st: ["none","만들기"] | ["wait","승인 1 / 3"] | ["done","완료"]
export function todosOf(s) {
  const care = s.cards.find((p) => p.card.kind === "complaint");
  const mkt = s.cards.find((p) => p.card.kind === "promo");
  const items = [];
  const of = (p, gen) => draftsOf(s.results, p.card.card_id).filter((d) => d.generator === gen);
  const status = (ds, made) => !made ? ["none", "만들기"] : ds.length && ds.every((d) => s.approved.has(d.draft_id)) ? ["done", "완료"]
    : ["wait", `승인 ${ds.filter((d) => s.approved.has(d.draft_id)).length} / ${ds.length}`];
  if (care) {
    const made = !!s.results[care.card.card_id];
    const n = care.evidence.filter((e) => e.type === "review").length;
    items.push({ key: "notice", cid: care.card.card_id, gen: "prevention_notice", urgent: true, title: "포장·주문 안내문 승인", sub: heroProblem(s.briefing), agent: "고객 응대 비서", st: status(of(care, "prevention_notice"), made) });
    items.push({ key: "reply", cid: care.card.card_id, gen: "reply_draft", title: `답글 ${made ? of(care, "reply_draft").length : n}개 승인`, sub: "같은 불만을 남긴 손님에게", agent: "고객 응대 비서", st: status(of(care, "reply_draft"), made) });
  }
  if (mkt) {
    const made = !!s.results[mkt.card.card_id];
    const menu = praiseOf(mkt).menu;
    const snap = homeSnap(s.briefing);
    items.push({ key: "promo", cid: mkt.card.card_id, gen: "coupon_promo", title: "쿠폰 홍보글", sub: `상권 저녁 ${snap ? snapValue(snap) : "–"}(${marketScope(snap) || "상권 지표"}) · ${menu ? `손님이 칭찬한 ${menu} 쿠폰으로 ` : ""}저녁 손님 다시 부르기`, agent: "마케팅 비서", st: status(of(mkt, "coupon_promo"), made) });
  }
  return items;
}

export const waitingCount = (s) => allDrafts(s.results).filter((d) => !s.approved.has(d.draft_id)).length;

// AI 비서 네 명: [{key, name, ok, text}]. key 는 누르면 갈 곳 (data → 리뷰 분석, care → 초안·카드, mkt → 맞춤 마케팅, market → 상권 분석)
export function staffOf(s) {
  const items = s.cards.length ? todosOf(s) : [];
  const b = s.briefing, c = (b && b.counts) || {};
  const pasted = ((b && b.pasted) || []).length;
  const out = [];
  // 리뷰 0건(새로 등록한 가게)은 '리뷰 0건 정리 끝' 대신 '아직 리뷰 없음'
  const dataText = !b ? (s.booted ? "리뷰를 불러오지 못했어요" : "리뷰 정리 중")
    : c.review_count === 0 && !pasted ? "아직 리뷰 없음"
    : `리뷰 ${c.review_count ?? 0}건 정리 끝${pasted ? ` · 새로 붙인 리뷰 ${pasted}건` : ""}`;
  out.push({ key: "data", name: "데이터 분석 비서", ok: !!b, text: dataText });
  const care = items.filter((t) => t.agent === "고객 응대 비서");
  const mktItems = items.filter((t) => t.agent === "마케팅 비서");
  const waitOf = (list) => list.flatMap((t) => draftsOf(s.results, t.cid).filter((d) => d.generator === t.gen && !s.approved.has(d.draft_id))).length;
  const doneOf = (list) => list.length > 0 && list.every((t) => t.st[0] === "done");
  const madeOf = (list) => list.some((t) => t.st[0] !== "none");
  const replied = new Set(allDrafts(s.results).filter((d) => d.generator === "reply_draft" && s.approved.has(d.draft_id)).map((d) => d.target_review_id));
  const complaints = b ? [...new Set([...(b.groups || []).flatMap((g) => (g.reviews || []).map((r) => r.review_id)),
    ...(b.single_complaints || []).map((x) => x.review_id)].filter(Boolean))] : [];
  const open = complaints.filter((id) => !replied.has(id)).length;
  const careText = !care.length ? "오늘 할 일 없음" : doneOf(care) ? "오늘 승인 완료" : madeOf(care) ? `승인 대기 ${waitOf(care)}개` : "초안 만들기 전";
  out.push({ key: "care", name: "고객 응대 비서", ok: doneOf(care) && open === 0, text: b ? `${careText} · 답글 안 단 불만 ${open}건` : careText });
  const mktDone = Math.max(s.approvedLog.filter((x) => x.mkt).length, s.mktServer);
  const mktText = !mktItems.length ? "오늘 할 일 없음" : doneOf(mktItems) ? "오늘 승인 완료" : madeOf(mktItems) ? `승인 대기 ${waitOf(mktItems)}개` : "초안 만들기 전";
  out.push({ key: "mkt", name: "마케팅 비서", ok: doneOf(mktItems) || mktDone > 0, text: `${mktText}${mktDone ? ` · 맞춤 마케팅 승인 ${mktDone}건` : ""}` });
  const m = s.staffMarket;
  out.push({ key: "market", name: "상권 분석 비서", ok: !!m && m.state === "ready", text: !m ? "확인 중" : m.state === "ready"
    ? `상권 자료 준비${m.data && m.data.latest_period_label ? ` · ${m.data.latest_period_label}까지` : ""}` : m.state === "no_data" ? "상권 자료 준비 전" : "상권 서비스 연결 안 됨" });
  return out;
}
