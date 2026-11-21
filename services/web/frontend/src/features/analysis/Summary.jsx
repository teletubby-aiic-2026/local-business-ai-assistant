// 요약 탭: 숫자 타일 3개(리뷰 · 불만 · 반복 불만) → 칭찬·불만 주제 (주제별 긍정·부정 수 topic_counts, 두 칸). 예전 renderAnSummary
import { Button, Panel, StatTile, TopicBar } from "../../components/ui.jsx";
import { summaryTiles, topTopics } from "./calc.js";
import { showTab } from "./state.js";

const withUnit = (v) => <>{v}<span className="an-unit">건</span></>;

function TopicColumn({ title, list, kind }) {
  return (
    <div className="an-topics">
      <h3>{title}</h3>
      {list.length
        ? <ul className="plain an-topic-list">{list.map((t) => <li key={t.name}><TopicBar name={t.name} value={`${t.n}건`} ratio={t.ratio} kind={kind} /></li>)}</ul>
        : <p className="small muted">없음</p>}
    </div>
  );
}

export default function Summary({ d }) {
  const t = summaryTiles(d);
  return (
    <div className="stack">
      <div className="tiles an-tiles">
        <StatTile label="전체 리뷰" value={withUnit(t.reviews)} sub={t.reviewsSub} />
        <StatTile label="불만 리뷰" value={withUnit(t.complaints)} sub={t.complaintsSub} />
        <StatTile label="반복 불만" value={withUnit(t.repeated)} sub={t.repeatedSub} />
      </div>
      <Panel title="칭찬·불만 주제" titleId="an-kw-title"
        actions={<Button size="small" onClick={() => showTab("issues", true)}>불만 묶음 보기</Button>}>
        <div className="grid-2 an-kw">
          <TopicColumn title="불만이 많은 주제" list={topTopics(d, "negative")} kind="complaint" />
          <TopicColumn title="칭찬이 많은 주제" list={topTopics(d, "positive")} kind="praise" />
        </div>
        <p className="small muted">리뷰 하나에 주제가 여럿이면 주제마다 1건씩 들어가요.</p>
      </Panel>
    </div>
  );
}
