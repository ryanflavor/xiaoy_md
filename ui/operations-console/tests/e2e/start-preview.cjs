#!/usr/bin/env node
const { spawnSync, spawn } = require("node:child_process");
const path = require("node:path");

const cwd = process.cwd();
console.log(`[start-preview] working directory: ${cwd}`);

const buildResult = spawnSync("npm", ["run", "build"], {
  cwd,
  stdio: "inherit",
  env: process.env,
});

if (buildResult.status !== 0) {
  process.exit(buildResult.status ?? 1);
}

console.log("[start-preview] build completed, launching preview server");

const preview = spawn(
  "npm",
  ["run", "preview", "--", "--host", "--port", process.env.PORT ?? "4173"],
  {
    cwd,
    stdio: "inherit",
    env: process.env,
  }
);

preview.on("exit", (code, signal) => {
  const status = code ?? (signal ? 1 : 0);
  if (status !== 0) {
    console.error(
      `[start-preview] preview exited unexpectedly (code=${code ?? "null"}, signal=${signal ?? "null"})`
    );
  }
  process.exit(status);
});

preview.on("error", (error) => {
  console.error(`[start-preview] failed to launch preview: ${error.message}`);
  process.exit(1);
});

const handleTermination = (signal) => {
  if (preview) {
    preview.kill(signal);
  }
  process.exit(0);
};

process.on("SIGINT", handleTermination);
process.on("SIGTERM", handleTermination);
process.on("exit", () => {
  if (preview) {
    preview.kill();
  }
});
