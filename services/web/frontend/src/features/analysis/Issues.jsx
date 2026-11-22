// 불만 묶음 탭: 흐름 한 줄 → 묶음 카드(반복·몰린 시간대·시간대 분포·근거 인용과 채널·날짜) → 묶이지 않은 불만. 예전 renderAnIssues
// 흐름 칸은 숫자 옆에 단위(건·개)를 붙이고 이름에 무엇을 셌는지 적는다: 리뷰 n건 → 불만 리뷰 n건 → 묶음 n개 (반복 n개) + 묶이지 않은 불만 n건 (11/22 QA)
// 인용 옆에는 내부 리뷰 id 대신 '배민 · 11-03' 같은 한 조각만. id 는 시험·디버깅용으로 data-review-id 에 남긴다 (11/22 QA)
import { Badge, Panel } from "../../components/ui.jsx";
import { useStore } from "../../state/store.js";
import { OVERLAP_NOTE, REPEAT_NOTE, bandRows, groupNote, quoteMeta } from "./calc.js";

function Funnel({ d, groups, singles }) {
  const box = (n, unit, label) => (
    <div className="an-fbox">
      <div className="an-fn">{n ?? "–"}{n != null && <span className="an-unit">{unit}</span>}</div>
      <div className="small muted">{label}</div>
    </div>
  );
  return (
    <Panel>
      <div className="an-funnel">
        {box(d?.review_count, "건", "리뷰")}<span className="an-arrow" aria-hidden="true">→</span>
        {box(d?.complaint_count, "건", "불만 리뷰")}<span className="an-arrow" aria-hidden="true">→</span>
        {box(d ? groups.length : null, "개", `묶음 (반복 ${groups.filter((g) => g.is_repeated).length}개)`)}
        <span className="an-arrow" aria-hidden="true">+</span>
        {box(d ? singles.length : null, "건", "묶이지 않은 불만")}
      </div>
      <p className="small muted">{REPEAT_NOTE}.</p>
      <p className="small muted">{OVERLAP_NOTE}</p>
    </Panel>
  );
}

// 인용 한 줄의 꼬리: 채널 · 날짜 (모르면 아무것도 붙이지 않음)
const Meta = ({ text }) => (text ? <> <span className="small muted an-qmeta">{text}</span></> : null);

function Group({ g, top, isNew, reviews }) {
  return (
    <article className={["panel", "an-group", g.is_repeated && "repeated", isNew && "new"].filter(Boolean).join(" ")}>
      <div className="an-group-head">
        <h3>{g.topic_name} {g.review_count}건</h3>
        {g.is_repeated && <Badge tone="bad">반복</Badge>}
        {top && <Badge>추천 카드 ⓐ 근거</Badge>}
        {isNew && <Badge tone="ok">방금 붙여넣은 리뷰가 들어감</Badge>}
      </div>
      <p className="small muted">{groupNote(g)}</p>
      <ul className="plain an-bands" aria-label="시간대별 건수">
        {bandRows(g).map((b) => (
          <li key={b.band} className="an-band">
            <span className="an-band-name">{b.band}</span>
            <span className="an-band-track" aria-hidden="true"><i className={b.hot ? "hot" : undefined} style={{ width: `${b.pct}%` }} /></span>
            <span className="an-band-n">{b.n}건</span>
          </li>
        ))}
      </ul>
      <ul className="plain an-quotes">
        {(g.evidence || []).slice(0, 3).map((e, i) => (
          <li key={`${e.review_id}-${i}`} className="an-quote" data-review-id={e.review_id}>“{e.quote}”<Meta text={quoteMeta(e.review_id, reviews)} /></li>
        ))}
      </ul>
    </article>
  );
}

export default function Issues({ d }) {
  const joinedIds = useStore((s) => s.joined);
  const reviews = useStore((s) => s.reviewsById);
  const joined = new Set(joinedIds || []);
  const groups = d?.groups || [], singles = d?.single_complaints || [];
  return (
    <div className="stack">
      <Funnel d={d} groups={groups} singles={singles} />
      {groups.length
        ? <div className="an-groups">{groups.map((g) => <Group key={g.issue_id} g={g} top={g.issue_id === d.top_issue_id} isNew={joined.has(g.issue_id)} reviews={reviews} />)}</div>
        : <Panel><p className="muted">묶인 불만이 없어요.</p></Panel>}
      <Panel title={d ? `묶이지 않은 불만 ${singles.length}건` : "묶이지 않은 불만"} titleId="an-singles-title">
        <ul className="plain an-quotes">
          {singles.length
            ? singles.map((s, i) => (
              <li key={`${s.review_id}-${i}`} className="an-quote" data-review-id={s.review_id}>
                {(s.topic_names || []).join("·")}: “{s.quote}”<Meta text={quoteMeta(s.review_id, reviews, s)} />
              </li>
            ))
            : <li className="small muted">없어요.</li>}
        </ul>
      </Panel>
    </div>
  );
}
