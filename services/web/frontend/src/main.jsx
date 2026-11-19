import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { boot } from "./state/boot.js";
import { applyTheme } from "./lib/theme.js";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/layout.css";

applyTheme();   // index.html 의 작은 스크립트가 이미 정했지만, ?theme= 와 저장값을 한 곳(theme.js)에서 다시 맞춘다
createRoot(document.getElementById("root")).render(<StrictMode><App /></StrictMode>);
boot();
