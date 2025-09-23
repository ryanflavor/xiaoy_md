import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: {
    baseURL: "http://localhost:4173",
    colorScheme: "dark",
    locale: "en-US",
  },
  webServer: {
    command: "node ./tests/e2e/start-preview.cjs",
    cwd: process.cwd(),
    timeout: 120000,
    reuseExistingServer: !process.env.CI,
  },
});
