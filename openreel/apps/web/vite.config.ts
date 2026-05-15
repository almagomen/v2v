import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// En dev, el frontend suele ir en :5173 y FastAPI en :8000. Las llamadas relativas a /api/*
// pegan al servidor de Vite; sin proxy no llegan a uvicorn (404 o HTML del SPA).
const v2vApiProxyTarget =
  process.env.V2V_API_PROXY_TARGET?.replace(/\/$/, "") || "http://127.0.0.1:8000";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  assetsInclude: ["**/*.wasm"],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@openreel/core": path.resolve(__dirname, "../../packages/core/src"),
    },
  },
  worker: {
    format: "es",
  },
  optimizeDeps: {
    exclude: ["@ffmpeg/ffmpeg", "@ffmpeg/util", "@ffmpeg/core", "@ffmpeg/core-mt"],
  },
  build: {
    target: "esnext",
    rollupOptions: {
      output: {
        manualChunks: (id) => {
          if (id.includes("node_modules/react") || id.includes("node_modules/react-dom")) {
            return "react";
          }
          if (id.includes("node_modules/zustand")) {
            return "zustand";
          }
          if (id.includes("node_modules/three")) {
            return "three";
          }
          if (id.includes("node_modules/@radix-ui")) {
            return "radix";
          }
        },
      },
    },
  },
  server: {
    // Colab / Codatalab: host interno cambia por sesión; sin esto Vite bloquea el Host header.
    allowedHosts: true,
    proxy: {
      "/api": {
        target: v2vApiProxyTarget,
        changeOrigin: true,
      },
    },
    headers: {
      "Cross-Origin-Opener-Policy": "same-origin",
      "Cross-Origin-Embedder-Policy": "require-corp",
    },
  },
  preview: {
    allowedHosts: true,
    proxy: {
      "/api": {
        target: v2vApiProxyTarget,
        changeOrigin: true,
      },
    },
    headers: {
      "Cross-Origin-Opener-Policy": "same-origin",
      "Cross-Origin-Embedder-Policy": "require-corp",
    },
  },
});
