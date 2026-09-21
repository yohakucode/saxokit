import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// ビルド成果物は Python パッケージ内 static/ に出力し、`saxokit web` がそのまま配信する。
// 開発時は /api だけを saxokit web (127.0.0.1:8787) に中継する。待ち受けは常に loopback。
const API = "http://127.0.0.1:8787";

export default defineConfig({
  base: "/",
  plugins: [react(), tailwindcss()],
  build: { outDir: "../src/saxokit/static", emptyOutDir: true },
  server: { host: "127.0.0.1", port: 5173, strictPort: true, proxy: { "/api": API } },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true, proxy: { "/api": API } },
});
