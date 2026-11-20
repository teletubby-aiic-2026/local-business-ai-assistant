// 공통 모양(토큰·바탕·화면 틀)을 맨 먼저 읽는다. 화면마다의 CSS(features/*/*.css)는 App 을 읽을 때 그 뒤에 붙으므로,
// 같은 무게의 규칙이면 화면 CSS 가 공통 규칙을 덮어쓴다 (예: .rp-tiles 가 .tiles 의 칸 수를 바꿈)
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/layout.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { boot } from "./state/boot.js";
import { applyTheme } from "./lib/theme.js";

applyTheme();   // index.html 의 작은 스크립트가 이미 정했지만, ?theme= 와 저장값을 한 곳(theme.js)에서 다시 맞춘다
createRoot(document.getElementById("root")).render(<StrictMode><App /></StrictMode>);
boot();
