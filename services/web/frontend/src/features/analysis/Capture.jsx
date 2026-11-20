// 캡처로 넣기 (예전 capPick·capBusy·capRead·capRender·capItem·capCount·capSave).
// 파일 고르기(또는 끌어 놓기) → POST /api/care/reviews/capture (저장하지 않고 후보만) → 후보마다 글 고치기·별점·개인정보 가림·이미 있는 리뷰 표시
// → '선택한 리뷰 저장'이 고른 후보를 한 건씩 POST /api/reviews {text, rating, source: "capture"} 로 저장 (붙여넣기와 같은 길) → 홈·카드·분석 다시 불러오기.
// demo(예시 결과)와 warnings 는 받은 그대로 꼭 보이고, 별점은 잘못 읽을 수 있다는 안내가 늘 붙는다 (실시간 시험에서 1~2점을 3점으로 읽은 적이 절반쯤).
// 오류는 이 칸 안(an-cap-error)에만 보이고 화면 맨 위 알림 띠는 쓰지 않는다. 진행은 모듈 상태라 메뉴를 오가도 남는다.
import { useEffect, useRef, useState } from "react";
import { Badge, Button, Panel } from "../../components/ui.jsx";
import { getState, setState } from "../../state/store.js";
import { refresh } from "../../state/boot.js";
import { careApi, CAP_WAIT_MS } from "./careApi.js";
import { RATINGS, capCheck, capFileLabel, capItems, capPickedOf, capStatusLine, capWarnings } from "./calc.js";
import { getMod, setCap, setCapItem, useMod } from "./state.js";

function capPick(file) {
  setCap({ error: "" });
  if (!file) return;
  const bad = capCheck(file);
  if (bad) { setCap({ error: bad }); return; }
  setCap({ file, fileName: capFileLabel(file) });
}

async function capRead() {
  const c = getMod().cap;
  if (!c.file || c.busy) return;
  const ep = getState().epoch, alive = () => getState().epoch === ep;
  const file = c.file;
  // 앞 캡처의 후보는 치운다 (새 캡처가 실패했을 때 옛 후보를 새 것으로 착각하지 않게)
  setCap({ error: "", saveMsg: "", result: null, items: [], status: "", reading: true, busy: true, startedAt: Date.now() });
  const form = new FormData();
  form.append("file", file, file.name || "capture.png");
  try {
    const r = await careApi("/api/care/reviews/capture", { method: "POST", body: form }, CAP_WAIT_MS);
    if (!alive()) return;
    const items = capItems(r);
    setCap((x) => {
      if (x.url) URL.revokeObjectURL(x.url);
      return { reading: false, busy: false, url: URL.createObjectURL(file), items,
        result: { demo: r?.demo === true, warnings: capWarnings(r) }, status: capStatusLine(r, items.length) };
    });
  } catch (e) {
    if (alive()) setCap({ reading: false, busy: false, error: e.message });   // 400·413·422·502·503 모두 서버(리뷰 분석 서비스·프록시) 문장 그대로
  }
}

async function capSave() {
  const c = getMod().cap;
  if (c.busy) return;
  const picks = c.items.map((x, i) => [x, i]).filter(([x]) => x.picked && !x.saved).map(([, i]) => i);
  if (!picks.length) { setCap({ saveMsg: "저장할 리뷰를 골라 주세요." }); return; }
  const ep = getState().epoch, alive = () => getState().epoch === ep;
  setCap({ busy: true });
  let ok = 0, bad = 0;
  const joined = new Set();
  for (const [k, i] of picks.entries()) {
    if (!alive()) return;
    const item = getMod().cap.items[i];   // 저장하는 동안 고친 글도 그 차례에 읽는다
    const text = item.text.trim();
    setCap({ saveMsg: `저장하는 중… (${k + 1} / ${picks.length})` });
    if (!text) { setCapItem(i, { msg: "글이 비어 있어 저장하지 않았어요." }); bad++; continue; }
    try {
      const r = await careApi("/api/reviews", { method: "POST", body: JSON.stringify({ text, rating: item.rating ? Number(item.rating) : null, source: "capture" }) });
      if (!alive()) return;
      (r.joined_issues || []).forEach((id) => joined.add(id));
      setCapItem(i, { msg: "", saved: true, picked: false });
      ok++;
    } catch (e) { if (!alive()) return; setCapItem(i, { msg: `저장하지 못했어요: ${e.message}` }); bad++; }
  }
  const tail = bad ? ` ${bad}건은 저장하지 못했어요 (후보 아래 이유).` : "";
  if (ok) {
    setState({ joined: [...joined] });
    setCap({ saveMsg: `리뷰 ${ok}건을 저장했어요. 분석 결과를 갱신하는 중…` });
    try {
      await refresh();   // 붙여넣기와 같이 홈 숫자 · 추천 카드 · 리뷰 분석(요약·묶음)을 모두 새로
      if (alive()) setCap({ saveMsg: `리뷰 ${ok}건을 저장하고 분석 결과를 갱신했어요.${tail}` });
    } catch (e) { if (alive()) setCap({ saveMsg: `리뷰 ${ok}건을 저장했지만 분석 결과는 갱신하지 못했어요: ${e.message}${tail}` }); }
  } else setCap({ saveMsg: `저장하지 못했어요.${tail}` });
  if (alive()) setCap({ busy: false });
}

// 진행 표시 (role=status): 깜박이는 점 + 글 + 걸린 초 (초는 읽기 프로그램에 읽히지 않게)
function Reading({ startedAt }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  const s = Math.floor((now - startedAt) / 1000);
  return (
    <>
      <span>{s >= 6 ? "캡처를 읽고 있어요. 긴 캡처는 20초쯤 걸릴 수 있어요" : "캡처를 읽고 있어요"}</span>
      <span className="an-cap-sec" aria-hidden="true">{s >= 2 ? `${s}초` : ""}</span>
    </>
  );
}

function CapItem({ c, i }) {
  const n = i + 1;
  return (
    <li className={["an-cap-item", c.dup && "dup", c.saved && "saved"].filter(Boolean).join(" ")}>
      <div className="an-cap-item-head">
        <label className="an-cap-check">
          <input type="checkbox" checked={c.picked} disabled={c.saved} onChange={(e) => setCapItem(i, { picked: e.target.checked })} /> 후보 {n} 저장
        </label>
        {c.pii && <Badge title="전화번호·이메일·링크를 [가림]으로 바꿨어요">개인정보 가림</Badge>}
        {c.dup && <Badge tone="warn" title="이미 저장된 리뷰와 글이 같아서 처음에는 고르지 않았어요">이미 있는 리뷰</Badge>}
        {c.saved && <Badge tone="ok">저장함</Badge>}
      </div>
      <label className="sr" htmlFor={`cap-text-${i}`}>후보 {n} 리뷰 글</label>
      <textarea id={`cap-text-${i}`} className="input an-cap-text" rows={3} maxLength={1000} value={c.text} disabled={c.saved}
        onChange={(e) => setCapItem(i, { text: e.target.value })} />
      <div className="an-cap-item-foot">
        <label className="small" htmlFor={`cap-rate-${i}`}>별점</label>
        <select id={`cap-rate-${i}`} className="an-select" value={c.rating} disabled={c.saved} onChange={(e) => setCapItem(i, { rating: e.target.value })}>
          {RATINGS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
        </select>
        <span className="small muted">AI가 읽은 별점: {Number.isInteger(c.ai) ? `${c.ai}점` : "못 읽음"}</span>
      </div>
      {c.msg && <p className="an-cap-item-msg">{c.msg}</p>}
    </li>
  );
}

export default function Capture() {
  const c = useMod((m) => m.cap);
  const fileRef = useRef(null);
  const [drop, setDrop] = useState(false);
  const n = capPickedOf(c.items).length;
  return (
    <Panel title="캡처로 넣기" titleId="cap-title" sub="png·jpg·webp 1장 · 10MB 이하" className={["an-cap", drop && "drop"].filter(Boolean).join(" ")}
      onDragOver={(e) => { e.preventDefault(); setDrop(true); }}
      onDragLeave={() => setDrop(false)}
      onDrop={(e) => { e.preventDefault(); setDrop(false); if (!getMod().cap.busy) capPick(e.dataTransfer?.files?.[0]); }}>
      {/* 점선 상자 (Figma 06 C2): 설명 한 줄 + 파일 고르기 + 고른 파일 이름. 끌어 놓기는 칸 전체가 받는다.
          '바로 저장하지 않음'은 후보 목록 위 확인 경고가 말한다 */}
      <div className="an-cap-drop">
        <p className="small muted">AI가 배달앱 리뷰 캡처에서 글과 별점을 읽어 와요.</p>
        <div className="an-cap-pick">
          {/* 파일 칸은 화면에서 숨기고(키보드 순서에서도 뺌) 옆 버튼이 click() 으로 연다. display:none 이면 일부 브라우저가 click() 을 막아서 sr 로 숨김 */}
          <input ref={fileRef} id="cap-file" className="sr" type="file" accept="image/png,image/jpeg,image/webp" tabIndex={-1} aria-hidden="true"
            onChange={(e) => { capPick(e.target.files[0]); e.target.value = ""; }} />
          <Button onClick={() => fileRef.current?.click()} disabled={c.busy}>파일 고르기</Button>
          <span className="small muted an-cap-file">{c.fileName}</span>
        </div>
      </div>
      <div className="btn-row">
        <Button variant="primary" onClick={capRead} disabled={c.busy || !c.file}>캡처 읽기</Button>
      </div>
      <p className={["an-cap-status", c.reading && "busy"].filter(Boolean).join(" ")} role="status">
        {c.reading ? <Reading startedAt={c.startedAt} /> : c.status}
      </p>
      <p className="an-cap-error" role="alert">{c.error}</p>
      {c.result && (
        <div className="an-cap-result">
          {c.result.demo && (
            <p className="an-cap-demo"><b>예시 결과 — 이미지를 실제로 읽지 않았어요</b><span>미리 정해 둔 예시 후보예요.</span></p>
          )}
          {c.result.warnings.length > 0 && <ul className="an-warns" aria-label="확인할 점">{c.result.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
          <p className="notice warn an-cap-star"><b>저장하기 전에 별점과 글이 캡처와 같은지 확인해 주세요. 고른 후보만 저장해요.</b></p>
          {c.url && <details className="an-cap-shot"><summary className="small">올린 캡처 보기</summary><img src={c.url} alt="올린 리뷰 화면 캡처" /></details>}
          <ol className="plain an-cap-list" aria-label="옮겨 적은 리뷰 후보">
            {c.items.length
              ? c.items.map((x, i) => <CapItem key={i} c={x} i={i} />)
              : <li className="small muted">옮겨 적은 리뷰가 없어요. 다시 올리거나 붙여넣기를 써 주세요.</li>}
          </ol>
          <div className="btn-row">
            <Button variant="primary" onClick={capSave} disabled={c.busy || !n}>선택한 리뷰 저장</Button>
            <span className="small muted">{n ? `${n}건 고름` : "고른 리뷰 없음"}</span>
          </div>
          <p className="small an-cap-save-msg" role="status">{c.saveMsg}</p>
        </div>
      )}
    </Panel>
  );
}
