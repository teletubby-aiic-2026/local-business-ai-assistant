import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발 서버(npm run dev, 5173)는 /api 를 비서 화면 서버(기본 127.0.0.1:8000)로 넘긴다.
// 같은 주소에서 부르는 것처럼 보여서 쿠키(visitor_id·ic26_session)가 그대로 오간다.
const API_TARGET = process.env.VITE_API_TARGET || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  base: "/",
  server: {
    port: 5173,
    proxy: { "/api": { target: API_TARGET, changeOrigin: false } },
  },
  build: {
    outDir: "dist",
    assetsDir: "assets",   // Nginx static 모드: /assets/... 는 location / 의 root 가 찾는다 (deploy/nginx/ic26-static.conf)
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{js,jsx}"],
  },
});
