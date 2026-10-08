/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  // src-tauri is Rust (watched by `tauri dev` itself): watching its build output from here makes Windows
  // refuse access to executables being compiled (EBUSY) and kills the dev server.
  server: { port: 1420, strictPort: true, host: "127.0.0.1", watch: { ignored: ["**/src-tauri/**"] } },
  test: { environment: "jsdom", setupFiles: ["./src/test-setup.ts"] },
});
