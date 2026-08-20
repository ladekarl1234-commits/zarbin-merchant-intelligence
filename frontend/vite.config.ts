import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8630" } },
  build: { outDir: "../zarin/static", emptyOutDir: true },
});
