import react from "@vitejs/plugin-react";
// defineConfig из "vitest/config", а не "vite": он расширяет тип конфигурации
// полем test, которого в обычном UserConfig нет — иначе tsc падает на блоке
// test ниже.
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: { port: 3000 },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
  },
});
