import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

const opsProxyTarget = process.env.VITE_OPS_API_PROXY_TARGET ?? "http://localhost:9180";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
    open: true,
    proxy: {
      "/api/ops": {
        target: opsProxyTarget,
        changeOrigin: true,
        secure: false,
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.{test,spec}.tsx"],
    coverage: {
      reporter: ["text", "html"],
    },
  },
});
