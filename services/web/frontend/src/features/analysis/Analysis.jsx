// 리뷰 분석 (#/analysis): 요약 · 불만 묶음 · 리뷰 넣기 (탭 3개). 예전 app.js 699~1022줄, index.html 155~253줄.
// 데이터: 처음 불러올 때 boot.js 가 읽은 GET /api/insight (store 의 insight·insightError).
// 붙여넣기·캡처 저장·지우기는 PasteTab·Capture 가 하고, 성공하면 refresh() 로 브리핑·카드·분석을 다시 읽는다.
import { useEffect } from "react";
import { PageHead, Tabs, Notice } from "../../components/ui.jsx";
import { useStore } from "../../state/store.js";
import { AN_TABS, periodLine } from "./calc.js";
import { getMod, setMod, showTab, syncEpoch, useMod } from "./state.js";
import Summary from "./Summary.jsx";
import Issues from "./Issues.jsx";
import PasteTab from "./PasteTab.jsx";
import "./analysis.css";

const TABS = [{ id: "summary", label: "요약" }, { id: "issues", label: "불만 묶음" }, { id: "paste", label: "리뷰 넣기" }];

export default function Analysis() {
  const epoch = useStore((s) => s.epoch);
  syncEpoch(epoch);   // 가게가 바뀌었으면 붙여넣기·캡처를 처음으로 (그리기 전에)
  const insight = useStore((s) => s.insight);
  const insightError = useStore((s) => s.insightError);
  const nav = useStore((s) => s.nav);
  const tab = useMod((m) => m.tab);

  // 다른 화면이 navTo("analysis", 탭) 으로 열었으면 그 탭으로 (nav.seq 마다 한 번)
  useEffect(() => {
    if (!nav || nav.seq === getMod().navSeq) return;
    setMod({ navSeq: nav.seq });
    if (nav.name === "analysis" && AN_TABS.includes(nav.sub)) showTab(nav.sub, true);
  }, [nav]);

  return (
    <div className="col an">
      <PageHead owner="데이터 분석 비서" title="리뷰 분석" />
      {insight && <p className="an-period small muted">{periodLine(insight)}</p>}
      <Notice tone="bad">{insightError}</Notice>
      {!insight && !insightError && <p className="small muted" role="status">불러오는 중…</p>}
      <Tabs tabs={TABS} active={tab} onChange={(id) => showTab(id)} idPrefix="an" label="리뷰 분석 화면" />

      <div id="an-panel-summary" className="an-tabpanel" role="tabpanel" aria-labelledby="an-tab-summary" tabIndex={0} hidden={tab !== "summary"}>
        <Summary d={insight} />
      </div>
      <div id="an-panel-issues" className="an-tabpanel" role="tabpanel" aria-labelledby="an-tab-issues" tabIndex={0} hidden={tab !== "issues"}>
        <Issues d={insight} />
      </div>
      <div id="an-panel-paste" className="an-tabpanel" role="tabpanel" aria-labelledby="an-tab-paste" tabIndex={0} hidden={tab !== "paste"}>
        <PasteTab />
      </div>
    </div>
  );
}
