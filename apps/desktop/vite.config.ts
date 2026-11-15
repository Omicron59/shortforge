import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Port fixe attendu par Tauri (voir src-tauri/tauri.conf.json).
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: { port: 1420, strictPort: true },
});
