// 결과 카드 (예전 mktResult·mktAdspendHtml·mktCouponHtml·mktIdea·mktNoticeOffer 가 그리던 것).
// 머리(제목·판정·데모) → 숫자 → 왜 이렇게 판단했나요 → 표·막대 → 할 일과 글 → 아이디어 → 쿠폰·슬라이더 → 측정 → 승인.
// 서버 글은 JSX 로만 넣는다. 저장된 예시(demo: true)면 머리에 '시험용 저장 예시 (실제 AI 결과 아님)' 배지를 꼭 단다
// (예시 고지는 화면 위 띠 + 이 배지 두 곳만. 카드 안에 같은 문장을 또 쓰지 않는다).
import { useEffect, useRef, useState } from "react";
import { Badge, Button } from "../../components/ui.jsx";
import { CALC_MAX_BUDGET, MKT_ADSPEND_RULE, MKT_DEMO, MKT_PROFIT, MKT_VERDICT, barPct, couponRows, draftLabel, mktKey, tilesOf, todoHeadOf, whyLinesOf, wonKo } from "./logic.js";
import { approve, askFromCard, couponGen, editDraft, editFollow, ideaAsk, ideaNext, ideaTry, nextCoupon, noticeFollow, rewrite, slide, storyLink } from "./state.js";
import { isSendEnter } from "./Ask.jsx";

function Tiles({ tiles, live }) {
  return (
    <dl className="mkt-tiles" aria-live={live ? "polite" : undefined}>
      {tiles.map(([v, l], i) => <div key={i}><dt>{l}</dt><dd>{v}</dd></div>)}
    </dl>
  );
}

// 복사: 클립보드가 막혀 있으면 글 칸을 골라 execCommand 로
function CopyButton({ text, targetId }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); }
    catch { const el = document.getElementById(targetId); el?.select(); document.execCommand("copy"); }
    setCopied(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 1500);
  };
  return <Button size="small" onClick={copy}>{copied ? "복사됨" : "복사"}</Button>;
}

// 글 상자 하나: 바로 고칠 수 있는 글 칸 + 복사. original 이 있으면 고친 표시, failed 면 점검 실패 안내
function DraftBox({ id, label, text, original, failed, readOnly, onChange }) {
  const edited = original != null && text.trim() !== original.trim();
  return (
    <div className="mkt-draft">
      <div className="mkt-draft-head"><label htmlFor={id}>{label}</label>{edited && <Badge tone="warn">고친 글</Badge>}</div>
      <textarea id={id} rows={4} value={text} readOnly={readOnly} onChange={(e) => onChange(e.target.value)} />
      {failed && failed.length > 0 && (
        <ul className="mkt-fail">{failed.map((r, i) => <li key={i}><b>점검 실패</b> {String(r)}</li>)}</ul>
      )}
      <div className="btn-row"><CopyButton text={text} targetId={id} /></div>
    </div>
  );
}
// 카드에 등록된 글 (승인할 때 같이 보내는 글)
function CardDraft({ card, k }) {
  const d = card.drafts[k];
  if (!d) return null;
  return <DraftBox id={`mkt-text-${card.n}-${mktKey(k)}`} label={d.label} text={d.text} original={d.original} failed={d.failed}
    readOnly={card.approved} onChange={(t) => editDraft(card.n, k, t)} />;
}

// 광고비 점검: 표 + 판정 기준 한 줄 + 앱마다 막대 두 개(건당 광고비 · 건당 남는 돈, 같은 눈금). 값은 서버가 계산한 그대로.
// 판정은 앱 바로 옆 둘째 열 — 맨 끝에 있을 때 칸이 좁으면 '괜'처럼 잘려 보였다. 숫자 열이 넘치면 그 칸만 옆으로 밀리고
// 가장자리 그림자로 밀린다는 게 보인다 (Marketing.css .mkt-table-wrap, 11/21 QA). '건당 남는 돈'은 광고비 빼기 전 값 (11/22 QA)
function Adspend({ rows }) {
  const judged = rows.filter((r) => r.cost_per_order_won != null);
  const pct = barPct(judged.flatMap((r) => [r.cost_per_order_won, r.profit_per_order_won]));
  return (
    <>
      <div className="mkt-table-wrap" tabIndex={0} role="region" aria-label="배달앱별 광고비 손익 표 (옆으로 밀어 볼 수 있어요)">
        <table className="mkt-table">
          <caption className="sr">배달앱별 광고비 손익</caption>
          <thead><tr><th scope="col">앱</th><th scope="col">판정</th><th scope="col" className="r">광고비</th><th scope="col" className="r">주문</th><th scope="col" className="r">건당 광고비</th><th scope="col" className="r">{MKT_PROFIT}</th></tr></thead>
          <tbody>
            {rows.map((r, i) => {
              const v = MKT_VERDICT[r.verdict];
              return (
                <tr key={i}>
                  <th scope="row">{r.label}</th>
                  <td className="mkt-verdict">{v ? <Badge tone={v[0]}>{v[1]}</Badge> : "–"}</td>
                  <td className="r">{wonKo(r.spend_won)}</td>
                  <td className="r">{Number(r.orders || 0).toLocaleString("ko-KR")}건</td>
                  <td className="r">{r.cost_per_order_won == null ? "–" : wonKo(r.cost_per_order_won)}</td>
                  <td className="r">{wonKo(r.profit_per_order_won)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="small muted mkt-adspend-rule">{MKT_ADSPEND_RULE}</p>
      {judged.length > 0 && (
        <div className="mkt-bars">
          {judged.map((r, i) => (
            <div key={i} className="mkt-bar-row" role="img" aria-label={`${r.label}: 건당 광고비 ${wonKo(r.cost_per_order_won)}, ${MKT_PROFIT} ${wonKo(r.profit_per_order_won)}`}>
              <p className="mkt-bar-name" aria-hidden="true">{r.label}</p>
              <Bar tone={(MKT_VERDICT[r.verdict] || ["ok"])[0]} width={pct(r.cost_per_order_won)} text={`건당 광고비 ${wonKo(r.cost_per_order_won)}`} hidden />
              <Bar tone="profit" width={pct(r.profit_per_order_won)} text={`${MKT_PROFIT} ${wonKo(r.profit_per_order_won)}`} hidden />
            </div>
          ))}
        </div>
      )}
    </>
  );
}
export function Bar({ tone, width, text, hidden }) {
  return (
    <div className="mkt-bar" aria-hidden={hidden ? "true" : undefined}>
      <span className="mkt-bar-track" aria-hidden="true"><i className={tone} style={{ width: `${width}%` }} /></span>
      <span className="small">{text}</span>
    </div>
  );
}

// 쿠폰 슬라이더: 예산·할인액 → 쿠폰 장수·최대 비용·본전 주문 수 (계산은 서버 coupon-calc)
function Calc({ card }) {
  const { n, calc, range, figs } = card;
  const fill = figs && figs.budgetAt > 0 ? Math.min(100, (figs.max_cost_won / figs.budgetAt) * 100) : 0;
  return (
    <div className="mkt-calc">
      <div className="mkt-slider">
        <label htmlFor={`mkt-budget-${n}`}><span>월 예산</span><output>{wonKo(calc.budget_won)}</output></label>
        <input type="range" id={`mkt-budget-${n}`} min={0} max={CALC_MAX_BUDGET} step={10000} value={calc.budget_won}
          aria-valuetext={wonKo(calc.budget_won)} onChange={(e) => slide(n, "budget_won", e.target.value)} />
        <p className="mkt-minmax small muted" aria-hidden="true"><span>0원</span><span>{wonKo(CALC_MAX_BUDGET)}</span></p>
      </div>
      <div className="mkt-slider">
        <label htmlFor={`mkt-discount-${n}`}><span>할인액</span><output>{wonKo(calc.discount_won)}</output></label>
        <input type="range" id={`mkt-discount-${n}`} min={range.minD} max={range.maxD} step={100} value={calc.discount_won}
          aria-valuetext={wonKo(calc.discount_won)} onChange={(e) => slide(n, "discount_won", e.target.value)} />
        <p className="mkt-minmax small muted" aria-hidden="true"><span>{wonKo(range.minD)}</span><span>{wonKo(range.maxD)}</span></p>
      </div>
      <div className="mkt-budget">
        <span className="mkt-bar-track" aria-hidden="true"><i className="ok" style={{ width: `${fill}%` }} /></span>
        <p className="small">{figs ? `쿠폰 비용 ${wonKo(figs.max_cost_won)} · 남는 예산 ${wonKo(figs.remaining_won)}` : ""}</p>
      </div>
      <Tiles live tiles={[[figs ? `${figs.count}장` : "–", "쿠폰 장수"], [figs ? wonKo(figs.max_cost_won) : "–", "최대 비용"],
        [figs && figs.breakeven_orders != null ? `${figs.breakeven_orders}건` : "–", "본전 주문 수"]]} />
      {figs && figs.discount_pct > 20 && <p className="mkt-warn">할인이 클수록 본전까지 더 많은 주문이 필요해요</p>}
      <div className="btn-row">
        <Button size="small" disabled={card.approved || card.replaced || card.work === "coupon-gen"} onClick={() => couponGen(n)}>
          {card.work === "coupon-gen" ? "만드는 중…" : "이 조건으로 쿠폰 글 만들기"}
        </Button>
      </div>
      <CardDraft card={card} k="coupon_regen" />
    </div>
  );
}

function Coupon({ c, card }) {
  return (
    <div className="mkt-coupon">
      <p className="small muted">쿠폰 이름</p>
      <p className="mkt-coupon-title">{c.menu || "대표 메뉴"} {wonKo(c.discount_won)} 할인</p>
      <dl className="mkt-kv">{couponRows(c).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
      {c.breakeven_orders != null && <p className="mkt-line">본전이 되려면 {c.breakeven_orders}건이 필요해요</p>}
      {c.calc_input && card?.calc && <Calc card={card} />}
    </div>
  );
}

// 아이디어 질문에 답하기 ('해 볼게요'를 누른 뒤에만)
function IdeaQuestion({ card }) {
  const { n, idea } = card;
  const [value, setValue] = useState("");
  const it = idea.item, off = idea.qBusy;
  return (
    <div className="mkt-q" id={`mkt-idea-${n}-q`}>
      {it.question && <p className="mkt-idea-why">{it.question}</p>}
      {it.question_type === "bool" ? (
        <div className="btn-row">
          <button type="button" className="mkt-chip" disabled={off} onClick={() => ideaTry(n, "예")}>예</button>
          <button type="button" className="mkt-chip" disabled={off} onClick={() => ideaTry(n, "아니요")}>아니요</button>
        </div>
      ) : (
        <div className="mkt-input">
          <label className="sr" htmlFor={`mkt-idea-${n}`}>아이디어 질문에 답하기</label>
          <input id={`mkt-idea-${n}`} type="text" maxLength={60} autoComplete="off" placeholder="답을 입력해 주세요" disabled={off}
            value={value} onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => { if (isSendEnter(e)) { e.preventDefault(); ideaTry(n, value.trim()); } }} />
          <Button variant="primary" size="small" disabled={off} onClick={() => ideaTry(n, value.trim())}>보내기</Button>
        </div>
      )}
    </div>
  );
}

// 추천 아이디어: 목표 하나 안에서 순서대로 (다음 아이디어). 아이디어 글은 정해 둔 틀 (AI 아님)
function Idea({ card }) {
  const { n, idea } = card;
  const it = idea.item;
  const story = it.id === "story_link";
  return (
    <div className="mkt-idea">
      <p className="mkt-idea-tag">추천 아이디어</p>
      <h4 id={`mkt-idea-${n}-title`} tabIndex={-1}>{it.title}</h4>
      {it.why && <p className="mkt-idea-why">{it.why}</p>}
      {(it.todos || []).length > 0 && <ul className="mkt-list">{it.todos.map((t, i) => <li key={i}>{t}</li>)}</ul>}
      <CardDraft card={card} k={`idea_${it.id}`} />
      {idea.asking && !idea.tried && <IdeaQuestion card={card} />}
      <div className="btn-row">
        {story ? <Button size="small" disabled={idea.storyBusy} onClick={() => storyLink(n)}>가게 이야기 글 만들기</Button>
          : it.needs_question && !idea.asking ? <Button size="small" disabled={card.approved} onClick={() => ideaAsk(n)}>해 볼게요</Button> : null}
        <Button size="small" variant="text" disabled={card.approved || idea.nextBusy} onClick={() => ideaNext(n)}>다음 아이디어</Button>
      </div>
      <p className="small muted mkt-idea-msg" role="status">{idea.msg}</p>
    </div>
  );
}

// 공지(재발 방지 공지)를 승인한 카드: 2주 뒤 같은 불만이 줄었는지 세어 보고, 줄었으면 개선 소식 글 (승인 대상 아님, 복사해서 씀)
function Follow({ card }) {
  const { n, notice } = card;
  const f = notice.result;
  return (
    <div className="mkt-follow">
      <p className="mkt-box-title">2주 뒤 개선 소식</p>
      <p className="small muted">공지 전후 2주 동안 같은 불만 리뷰 수를 비교해요 (지금은 저장된 리뷰 날짜 기준)</p>
      {!f && <div className="btn-row"><Button size="small" disabled={notice.busy} onClick={() => noticeFollow(n)}>2주 뒤 확인해 보기</Button></div>}
      {f && (
        <>
          <p className="mkt-line">공지 전후 불만 리뷰 수: 이전 {f.window_days}일 {f.before}건 → 이후 {f.window_days}일 <b>{f.after}건</b> ({f.basis || "리뷰 기준"})</p>
          {f.improved && f.text
            ? <DraftBox id={`mkt-text-${n}-notice_followup`} label={draftLabel("개선 소식", false, true)} text={notice.text} onChange={(t) => editFollow(n, t)} />
            : f.todo ? <p className="mkt-line">{f.todo}</p> : null}
        </>
      )}
      {notice.error && <p className="small mkt-card-msg bad">{notice.error}</p>}
    </div>
  );
}

export default function ResultCard({ card }) {
  const { n, data: d } = card;
  const tiles = tilesOf(d), why = whyLinesOf(d, card.why);
  const steps = Array.isArray(d.steps) ? d.steps : [];
  const todos = Array.isArray(d.todos) ? d.todos : [];
  const basics = Array.isArray(d.basic_todos) ? d.basic_todos : [];
  // 자료가 없어 못 만든 글 (반복 불만 리뷰가 없는 새 가게 등): 그 할 일 아래에 서버가 준 이유를 보인다 (빈 칸으로 두지 않음, 11/21 QA)
  const missing = Object.fromEntries((Array.isArray(d.unavailable_drafts) ? d.unavailable_drafts : []).map((u) => [u.step_id, u.message]));
  const nc = d.next_condition;
  return (
    <article className={card.approved ? "mkt-card approved" : "mkt-card"} id={`mkt-card-${n}`} aria-labelledby={`mkt-card-${n}-title`}>
      <div className="mkt-card-head">
        <h3 id={`mkt-card-${n}-title`} tabIndex={-1}>{card.title}</h3>
        {card.badge && <Badge tone={card.badge[0] || undefined}>{card.badge[1]}</Badge>}
        {card.demo && <Badge tone="warn">{MKT_DEMO}</Badge>}
        {card.approved && <Badge tone="ok">승인함</Badge>}
      </div>
      {tiles.length > 0 && <Tiles tiles={tiles} />}
      {why.length > 0 && (
        <div className="mkt-why">
          <p className="mkt-why-title">왜 이렇게 판단했나요</p>
          <ul>{why.map((t, i) => <li key={i}>{t}</li>)}</ul>
          <p className="small muted">사장님 답과 가게 데이터 기준이에요 (AI 판단 아님)</p>
        </div>
      )}
      {d.over_budget && <p className="mkt-warn">예상 비용(추정) 합계가 설문에서 답한 예산을 넘어요.</p>}
      {Array.isArray(d.table) && d.table.length > 0 && <Adspend rows={d.table} />}
      {steps.length > 0 && (
        <>
          <p className="mkt-todo-head">{todoHeadOf(d)}</p>
          <ol className="mkt-steps">
            {steps.map((s, i) => (
              <li key={s.step_id ?? i} className="mkt-step">
                <div className="mkt-step-top">
                  <span className="mkt-step-n" aria-hidden="true">{i + 1}</span><b>{s.what}</b>
                  <span className="mkt-step-meta">{s.when || ""}{s.minutes ? ` · ${s.minutes}분` : ""}{s.cost_krw ? ` · ${wonKo(s.cost_krw)}` : ""}</span>
                </div>
                {s.where && s.where !== "-" && <p className="small muted">{s.where}</p>}
                <CardDraft card={card} k={s.step_id} />
                {!card.drafts[s.step_id] && missing[s.step_id] && <p className="small muted mkt-missing">{missing[s.step_id]}</p>}
                {s.tip && <p className="small mkt-tip">체크: {s.tip}</p>}
              </li>
            ))}
          </ol>
        </>
      )}
      {todos.length > 0 && (
        <>
          <p className="mkt-todo-head">할 일 {todos.length}개</p>
          <ol className="mkt-steps">
            {todos.map((t, i) => <li key={i} className="mkt-step"><div className="mkt-step-top"><span className="mkt-step-n" aria-hidden="true">{i + 1}</span><b>{t}</b></div></li>)}
          </ol>
          {d.todo_note && <p className="small muted">{d.todo_note}</p>}
        </>
      )}
      {d.bundle && <p className="mkt-line">원래 합계 {wonKo(d.bundle.original_won)} → 세트 가격 <b>{wonKo(d.bundle.bundle_won)}</b></p>}
      {d.discount_tile && <p className="mkt-line">원래 가격 {wonKo(d.discount_tile.original_won)} → 할인 가격 <b>{wonKo(d.discount_tile.sale_won)}</b></p>}
      {basics.length > 0 && (
        <div className="mkt-box">
          <p className="mkt-box-title">기본 할 일</p>
          <ul className="mkt-list">{basics.map((t, i) => <li key={i}>{t.title}</li>)}</ul>
          {basics.map((t, i) => (t.draft ? <CardDraft key={i} card={card} k={`basic_todo_${i}`} /> : null))}
        </div>
      )}
      {card.idea && <Idea card={card} />}
      {d.coupon_card && <Coupon c={d.coupon_card} card={card} />}
      {d.breakeven_orders != null && !d.coupon_card && <p className="mkt-line">본전이 되려면 {d.breakeven_orders}건이 필요해요</p>}
      {nc && (
        <div className="mkt-box dashed">
          <p className="mkt-box-title">다음 쿠폰 조건</p>
          <p className="mkt-line">할인액 {wonKo(nc.discount_won)} · {nc.note || ""}</p>
          <div className="btn-row">
            <Button size="small" disabled={card.approved || card.replaced || card.work === "next-coupon"} onClick={() => nextCoupon(n)}>
              {card.work === "next-coupon" ? "만드는 중…" : "이 조건으로 쿠폰 글 만들기"}
            </Button>
          </div>
          {card.nextCoupon && (
            <>
              <CardDraft card={card} k="next_coupon" />
              {card.nextCoupon.coupon && <Coupon c={{ ...card.nextCoupon.coupon, calc_input: null }} />}
            </>
          )}
        </div>
      )}
      {d.measure && (
        <p className="mkt-measure">
          <svg className="icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></svg>
          <span className="mkt-measure-text">{d.measure}</span>
        </p>
      )}
      <div className="btn-row mkt-card-actions">
        <Button variant="primary" disabled={card.approved || card.replaced || card.approving} onClick={() => approve(n)}>{card.approved ? "승인함" : "승인"}</Button>
        <Button disabled={card.approved || card.replaced || card.rewriting} onClick={() => rewrite(n)}>다시 쓰기</Button>
        <Button variant="text" onClick={() => askFromCard(card)}>AI에게 이어서 묻기</Button>
        {card.done && <a className="small" href="#/done">처리 완료에서 보기</a>}
      </div>
      <p className={card.msgBad ? "small mkt-card-msg bad" : "small mkt-card-msg"} role="status">{card.msg}</p>
      {card.noticeOffer && <Follow card={card} />}
    </article>
  );
}
