// 사장님 프로필 '보관한 보고서' 칸에 끼우는 부품 (Figma 06 'A5 프로필'): 내 가게 전체의 저장된 주간 n개 · 월간 n개 타일.
// GET /api/reports/counts 를 한 번 부른다 (로그인한 사장님만 저장되므로 게스트는 안내 한 줄).
// counts 를 넘기면 부르지 않고 그 값으로 그린다 ({weekly, monthly, storage}). 칸 제목(패널)은 끼우는 쪽이 둔다.
import { useEffect, useState } from "react";
import { StatTile } from "../../components/ui.jsx";
import { careApi } from "./careApi.js";
import { NONE } from "./format.js";
import "./report.css";

export default function SavedReportCounts({ counts }) {
  const [got, setGot] = useState({ data: counts || null, msg: counts ? "" : "불러오는 중…", bad: false });
  useEffect(() => {
    if (counts) { setGot({ data: counts, msg: "", bad: false }); return undefined; }
    let live = true;
    careApi("/api/reports/counts")
      .then((data) => { if (live) setGot({ data, msg: "", bad: false }); })
      .catch((e) => { if (live) setGot({ data: null, msg: e.message, bad: true }); });
    return () => { live = false; };
  }, [counts]);
  const d = got.data;
  const n = (v) => (v == null ? NONE : `${v}개`);
  return (
    <div className="rp-counts-tiles" id="saved-report-counts">
      <p className={["rp-state", got.bad && "bad"].filter(Boolean).join(" ")} role="status">
        {got.msg || (d?.storage === "guest" ? "로그인하면 주간·월간 보고서가 이 계정에 저장돼요." : d?.storage === "unavailable" ? "지금은 저장된 보고서 수를 불러오지 못했어요." : "")}
      </p>
      {d && d.storage !== "guest" && (
        <div className="tiles">
          <StatTile id="saved-weekly" label="주간" value={n(d.weekly)} />
          <StatTile id="saved-monthly" label="월간" value={n(d.monthly)} />
        </div>
      )}
    </div>
  );
}
