import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const loaderDir = path.dirname(fileURLToPath(import.meta.url));
const expectStubUrl = pathToFileURL(
  path.join(loaderDir, "stubs", "vitest-expect.mjs")
).href;
const vitestStubUrl = pathToFileURL(
  path.join(loaderDir, "stubs", "vitest.mjs")
).href;

export async function resolve(specifier, context, defaultResolve) {
  if (specifier === "@vitest/expect" || specifier.startsWith("@vitest/expect/")) {
    return { url: expectStubUrl, shortCircuit: true };
  }
  if (specifier === "vitest" || specifier.startsWith("vitest/")) {
    return { url: vitestStubUrl, shortCircuit: true };
  }
  return defaultResolve(specifier, context, defaultResolve);
}
