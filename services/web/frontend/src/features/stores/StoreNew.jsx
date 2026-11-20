// A4 새 가게 등록 (Figma '06 설계 기준 화면' A4) — 자리만. 다음 단계에서 통째로 바뀐다 (가게 기본 정보·위치와 상권·메뉴와 가격).
// 오는 길: 회원가입 직후(mode "signup"), 가게 선택·프로필의 '+ 새 가게 등록'(mode "add"), 프로필의 '정보 고치기'(mode "edit", storeId).
// 위쪽 줄과 시험용 안내 띠는 features/account/Stage.jsx 의 StageFrame 을 쓴다
import { useStore } from "../../state/store.js";
import { goPick } from "../../state/stage.js";
import { Button } from "../../components/ui.jsx";
import { StageFrame, StageTitle, WhoText } from "../account/Stage.jsx";

// eslint-disable-next-line no-unused-vars
export default function StoreNew({ mode = "add", storeId }) {
  const me = useStore((s) => s.me);
  return (
    <StageFrame right={<><WhoText me={me} /><Button size="small" onClick={goPick}>가게 선택으로</Button></>}>
      <div className="stage-col">
        <StageTitle>새 가게 등록</StageTitle>
      </div>
    </StageFrame>
  );
}
