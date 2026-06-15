import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api 요청을 FastAPI(8000)로 프록시 → 프론트는 상대경로 /api 만 호출
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Windows에서 localhost가 IPv6(::1)로 해석되어 uvicorn(IPv4)과
      // 어긋나는 문제를 피하려고 127.0.0.1로 명시한다.
      "/api": "http://127.0.0.1:8000",
    },
  },
});
