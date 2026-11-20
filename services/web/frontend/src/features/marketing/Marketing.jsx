// 맞춤 마케팅 (#/marketing): 탭 두 개 — 맞춤 제안(시작 모드 → 단계별 질문 → 결과 카드 → 고쳐서 승인) · 마케팅 보고서(주간·월간).
// 이 서버의 /api/marketing-survey/* 만 부른다 (가게·방문자는 서버가 붙임). 마케팅 서비스가 꺼져 있으면 이 화면 안에만 안내.
// 대화·결과 카드·보고서는 state.js 에 있어서 화면을 떠났다 와도 남는다. 처음 열 때만 시작한다 (페이지를 열 때는 부르지 않음).
import { useEffect } from "react";
import { useStore } from "../../state/store.js";
import { Button, Empty, Notice, PageHead, Panel, Tabs } from "../../components/ui.jsx";
import { AskPanel, StartView, Status } from "./Ask.jsx";
import ResultCard from "./ResultCard.jsx";
import MarketingReport from "./MarketingReport.jsx";
import { handleNav, noticeLines, open, recheck, setTab, sync, useMkt } from "./state.js";
import "./Marketing.css";

const TABS = [{ id: "chat", label: "맞춤 제안" }, { id: "report", label: "마케팅 보고서" }];

// 제안 결과: 새 카드가 붙으면 화면 낭독기가 읽게 카드 목록을 늘 그려 둔 라이브 영역(role=log, polite)으로 둔다.
// 빈 안내는 목록 밖에 둔다 (진행 안내는 질문 칸의 role=status 가 이미 읽으므로 여기서 또 읽지 않음)
function ResultsPanel() {
  const cards = useMkt((s) => s.cards);
  const busy = useMkt((s) => s.busy);
  return (
    <Panel className="mkt-results" title="제안 결과" titleId="mkt-results-title">
      {!cards.length && (
        <Empty title={busy ? "답을 정리하고 있어요" : "아직 제안 결과가 없어요"}>질문에 다 답하면 여기에 홍보 방법과 글이 나와요.</Empty>
      )}
      <div id="mkt-cards" className="mkt-cards" role="log" aria-live="polite" aria-relevant="additions" aria-labelledby="mkt-results-title">
        {cards.map((c) => <ResultCard key={c.n} card={c} />)}
      </div>
    </Panel>
  );
}

// 맞춤 제안 탭: 첫 질문이면 기능 카드 격자, 시작 모드를 고르면 바로 두 칸(질문 · 제안 결과).
// 첫 질문이 오기 전에도 고른 모드와 '처음부터'가 보이게, 사장님이 한 번이라도 답했으면 두 칸으로 넘어간다
function Chat() {
  const atStart = useMkt((s) => !s.cards.length && !s.log.some((e) => e.kind === "user") && (!s.flow || s.flow.node === "start"));
  if (atStart) return <StartView />;
  return <div className="mkt-split"><AskPanel /><ResultsPanel /></div>;
}

// 마케팅 서비스를 쓸 수 없을 때: 꺼 둠·연결 안 됨·오류 + 다시 확인 (탭·대화는 숨김)
function DownPanel({ down, checking }) {
  return (
    <Panel className="mkt-state" data-state={down.key}>
      <Notice tone={down.key === "off" ? "warn" : "bad"} role="status">
        <span className="stack-8"><b>{down.title}</b><span>{down.message}</span></span>
      </Notice>
      <div className="btn-row">
        <Button id="mkt-retry" disabled={checking} onClick={recheck}>{checking ? "확인하는 중…" : "다시 확인"}</Button>
      </div>
    </Panel>
  );
}

export default function Marketing() {
  const s = useMkt();
  const epoch = useStore((x) => x.epoch);
  const resetSeq = useStore((x) => x.mktResetSeq);
  const navSeq = useStore((x) => x.nav.seq);
  const appBand = useStore((x) => x.health?.mode_notice);   // 화면 맨 위 시험용 띠가 떠 있는가
  // 가게가 바뀌었거나 '처음부터 다시'였으면 먼저 처음으로, 그다음 열기 (처음이면 시작)
  useEffect(() => { sync(); open(); }, [epoch, resetSeq]);
  // 다른 화면이 navTo("marketing", 시작 모드)로 보냈으면 그 모드로 (nav.seq 마다 한 번)
  useEffect(() => { handleNav(); }, [navSeq]);

  const notices = noticeLines(s, !!appBand);
  const owner = `마케팅 비서${s.storeName ? ` · ${s.storeName} 기준` : ""}`;
  return (
    <div className="col wide mkt">
      <PageHead owner={owner} title="맞춤 마케팅" sub="몇 가지 질문에 답하면 우리 가게에 맞는 홍보 방법과 글을 제안해요." />
      {notices.length > 0 && <Notice tone="warn" role="note" className="mkt-notice">{notices.join(" ")}</Notice>}
      {s.down && <DownPanel down={s.down} checking={s.checking} />}
      {!s.ready && !s.down && <Panel className="mkt-loading"><Status /></Panel>}
      {s.ready && (
        <>
          <Tabs tabs={TABS} active={s.tab} onChange={setTab} idPrefix="mkt" label="맞춤 마케팅 화면" />
          <div id="mkt-panel-chat" role="tabpanel" aria-labelledby="mkt-tab-chat" hidden={s.tab !== "chat"}>
            <Chat />
          </div>
          <div id="mkt-panel-report" role="tabpanel" aria-labelledby="mkt-tab-report" hidden={s.tab !== "report"}>
            {s.tab === "report" && <MarketingReport />}
          </div>
        </>
      )}
    </div>
  );
}
