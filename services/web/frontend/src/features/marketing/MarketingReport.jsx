// 마케팅 보고서 탭 (주간·월간, 예전 mktReport·mktReportDraw). 기록을 코드로 센 것이다 (AI 호출 없음).
// 기록이 없으면 서버가 데모 기록을 주고(demo: true), 그 사실을 보고서 위 안내 한 곳에서 꼭 밝힌다.
import { Button, Notice, Panel, StatTile } from "../../components/ui.jsx";
import { MKT_PERIOD, MKT_PROFIT, MKT_VERDICT, reportView, wonKo } from "./logic.js";
import { loadReport, useMkt } from "./state.js";
import { Bar } from "./ResultCard.jsx";

const TINTS = ["green", "mint", "lime", "sage"];

function ReportCard({ d, period }) {
  const v = reportView(d, period);
  const { L } = v;
  return (
    <Panel as="article" className="mkt-report-card" title={`${L.now} 마케팅 보고서`} titleId="mkt-report-title" sub={`${v.start} ~ ${v.until}`}>
      {d.demo && <Notice tone="warn" role="note">데모 기록 · 아직 쌓인 마케팅 기록이 없어 예시를 보여 줘요 (우리 가게 실제 기록 아님)</Notice>}
      {v.tiles.length > 0 && (
        <div className="tiles">{v.tiles.map(([val, label], i) => <StatTile key={i} label={label} value={val} tint={TINTS[i % TINTS.length]} />)}</div>
      )}
      {v.tried.length > 0 && (
        <div className="mkt-box"><p className="mkt-box-title">해 본 아이디어</p><ul className="mkt-list">{v.tried.map((t, i) => <li key={i}>{t}</li>)}</ul></div>
      )}
      {v.ads.length > 0 && (
        <div className="mkt-box">
          <p className="mkt-box-title">광고 앱별 판정 ({L.prev} → {L.now})</p>
          <div className="mkt-bars">
            {v.ads.map((a, i) => (
              <div key={i} className="mkt-bar-row">
                <p className="mkt-bar-name">{a.label} <span className="small muted">{L.prev} {a.prev_verdict || "기록 없음"} → {L.now} {a.verdict || "–"}</span></p>
                <Bar tone={(MKT_VERDICT[a.verdict] || ["ok"])[0]} width={v.pct(a.cost_per_order)} text={`건당 광고비 ${wonKo(a.cost_per_order)}`} />
                {a.profit_per_order != null && <Bar tone="profit" width={v.pct(a.profit_per_order)} text={`${MKT_PROFIT} ${wonKo(a.profit_per_order)}`} />}
              </div>
            ))}
          </div>
        </div>
      )}
      {v.next.length > 0 && (
        <div className="mkt-box dashed">
          <p className="mkt-box-title">{L.next} 할 것</p>
          <ul className="mkt-list">{v.next.map((x, i) => <li key={i}><b>{x.title}</b> — {x.why}</li>)}</ul>
        </div>
      )}
      {v.empty && <p className="muted">이 기간에 쌓인 기록이 아직 없어요.</p>}
    </Panel>
  );
}

export default function MarketingReport() {
  const period = useMkt((s) => s.period);
  const report = useMkt((s) => s.report);
  return (
    <div className="stack-16">
      <div className="btn-row" role="group" aria-label="보고서 기간">
        {["weekly", "monthly"].map((p) => (
          <Button key={p} size="small" variant={period === p ? "primary" : "ghost"} aria-pressed={period === p} onClick={() => loadReport(p)}>
            {MKT_PERIOD[p].name}
          </Button>
        ))}
      </div>
      <p id="mkt-report-state" className={report.bad ? "mkt-report-state bad" : "mkt-report-state"} role="status">{report.msg}</p>
      <div id="mkt-report">{report.data && <ReportCard d={report.data} period={report.period} />}</div>
    </div>
  );
}
