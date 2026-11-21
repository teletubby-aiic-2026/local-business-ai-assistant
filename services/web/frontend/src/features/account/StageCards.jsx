// X1 오류 · X2 다시 로그인(401) · 권한 없음(403) (Figma '06 설계 기준 화면' X1·X2: 가운데 카드 하나).
// X1 은 부팅 때 신원(/api/auth/me)을 못 받았거나 서버가 notice 를 줄 때, X2 는 로그인한 동안 받은 401 login_needed · 403 not_your_store (lib/api.js).
// 그림의 '오류 번호'는 서버가 주지 않아 넣지 않았고, 상태 코드(401·403) 배지는 안쪽 사정이라 뺐다
import { useStore } from "../../state/store.js";
import { goPick, readEntered, setStage } from "../../state/stage.js";
import { boot } from "../../state/boot.js";
import { acctLogout } from "../../state/account.js";
import { Button, Icon } from "../../components/ui.jsx";
import { StageCenter, StageTitle } from "./Stage.jsx";
import "./account.css";

export function ErrorStage() {
  const msg = useStore((s) => s.stageError);
  const me = useStore((s) => s.me);
  // [가게 선택으로](그림 X1)는 로그인해 가게에 들어가 있던 탭에서만 뜻이 있다. 신원을 못 받아 me 가 비어도
  // 이 탭에 들어갔던 가게가 남아 있으면 로그인한 사장님으로 본다. 누르면 신원을 다시 받아 가게 선택에서 멈춘다(로그인이 끝났으면 로그인 화면) (11/21 QA)
  const signedIn = !!(me && me.authenticated) || !!readEntered();
  return (
    <StageCenter>
      <div className="panel stage-card center">
        <span className="stage-card-icon" aria-hidden="true"><Icon name="오류" size={28} /></span>
        <StageTitle>잠시 문제가 생겼어요</StageTitle>
        <p className="muted">{msg || "계정 정보를 불러오지 못했어요. 승인한 글은 지워지지 않았어요. 잠시 뒤 다시 시도해 주세요."}</p>
        <div className="btn-row stage-card-btns">
          <Button variant="primary" onClick={() => boot()}>다시 시도</Button>
          {signedIn && <Button onClick={() => boot({ toPick: true })}>가게 선택으로</Button>}
        </div>
      </div>
    </StageCenter>
  );
}

export function ExpiredStage() {
  return (
    <StageCenter>
      <div className="panel stage-card">
        <StageTitle>다시 로그인해 주세요</StageTitle>
        <p className="muted">로그인이 끝났어요. 다시 로그인하면 보던 화면으로 돌아가요.</p>
        <div className="btn-row">
          <Button variant="primary" onClick={() => setStage("login")}>로그인</Button>
        </div>
      </div>
    </StageCenter>
  );
}

export function ForbiddenStage() {
  const busy = useStore((s) => s.acctBusy);
  return (
    <StageCenter>
      <div className="panel stage-card">
        <StageTitle>이 가게를 볼 권한이 없어요</StageTitle>
        <p className="muted">내 가게 목록에 없는 가게예요. 다른 계정으로 로그인했거나 가게에서 빠졌을 수 있어요.</p>
        <div className="btn-row">
          <Button variant="primary" onClick={goPick}>가게 선택으로</Button>
          <Button disabled={busy} onClick={acctLogout}>로그아웃</Button>
        </div>
      </div>
    </StageCenter>
  );
}
