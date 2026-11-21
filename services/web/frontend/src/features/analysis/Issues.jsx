// 불만 묶음 탭: 흐름 한 줄 → 묶음 카드(반복·몰린 시간대·시간대 분포·근거 인용과 리뷰 ID) → 묶이지 않은 불만. 예전 renderAnIssues
import { Badge, Panel } from "../../components/ui.jsx";
import { useStore } from "../../state/store.js";
import { REPEAT_NOTE, bandRows, groupNote } from "./calc.js";

function Funnel({ d, groups, singles }) {
  const box = (n, label) => <div className="an-fbox"><div className="an-fn">{n ?? "–"}</div><div className="small muted">{label}</div></div>;
  return (
    <Panel>
      <div className="an-funnel">
        {box(d?.review_count, "리뷰")}<span className="an-arrow" aria-hidden="true">→</span>
        {box(d?.complaint_count, "불만")}<span className="an-arrow" aria-hidden="true">→</span>
        {box(d ? groups.length : null, `묶음 (반복 ${groups.filter((g) => g.is_repeated).length})`)}
        <span className="an-arrow" aria-hidden="true">+</span>
        {box(d ? singles.length : null, "묶이지 않은 불만")}
      </div>
      <p className="small muted">{REPEAT_NOTE}.</p>
    </Panel>
  );
}

function Group({ g, top, isNew }) {
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
        {(g.evidence || []).slice(0, 3).map((e, i) => <li key={`${e.review_id}-${i}`} className="an-quote">“{e.quote}” <span className="small muted an-rid">{e.review_id}</span></li>)}
      </ul>
    </article>
  );
}

export default function Issues({ d }) {
  const joinedIds = useStore((s) => s.joined);
  const joined = new Set(joinedIds || []);
  const groups = d?.groups || [], singles = d?.single_complaints || [];
  return (
    <div className="stack">
      <Funnel d={d} groups={groups} singles={singles} />
      {groups.length
        ? <div className="an-groups">{groups.map((g) => <Group key={g.issue_id} g={g} top={g.issue_id === d.top_issue_id} isNew={joined.has(g.issue_id)} />)}</div>
        : <Panel><p className="muted">묶인 불만이 없어요.</p></Panel>}
      <Panel title={d ? `묶이지 않은 불만 ${singles.length}건` : "묶이지 않은 불만"} titleId="an-singles-title">
        <ul className="plain an-quotes">
          {singles.length
            ? singles.map((s, i) => <li key={`${s.review_id}-${i}`} className="an-quote">{(s.topic_names || []).join("·")}: “{s.quote}” <span className="small muted an-rid">{s.review_id}</span></li>)
            : <li className="small muted">없어요.</li>}
        </ul>
      </Panel>
    </div>
  );
}
