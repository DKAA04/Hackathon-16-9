import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // demo mode reads the KBO snapshot straight from backend/data/reference
    fs: { allow: [".."] },
  },
});
