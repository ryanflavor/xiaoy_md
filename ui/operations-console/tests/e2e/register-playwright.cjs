const Module = require("module");
const path = require("path");

const originalResolveFilename = Module._resolveFilename;
const expectStubPath = path.resolve(__dirname, "stubs/vitest-expect.cjs");
const vitestStubPath = path.resolve(__dirname, "stubs/vitest.cjs");

globalThis.__OPS_ENV__ = {
  VITE_OPS_API_BASE_URL: "/api",
  VITE_OPS_API_TOKEN: "",
};

const JEST_MATCHERS_SYMBOL = Symbol.for("$$jest-matchers-object");
const originalDefineProperty = Object.defineProperty;

Object.defineProperty = function patchedDefineProperty(target, property, descriptor) {
  if (property === JEST_MATCHERS_SYMBOL && descriptor) {
    const existing = Object.getOwnPropertyDescriptor(target, property);
    if (existing && existing.configurable === false) {
      return target;
    }
    if (descriptor.configurable === false) {
      return originalDefineProperty.call(this, target, property, {
        ...descriptor,
        configurable: true,
      });
    }
  }
  return originalDefineProperty.call(this, target, property, descriptor);
};

Module._resolveFilename = function (request, parent, isMain, options) {
  if (request && request.includes("@vitest/expect")) {
    return expectStubPath;
  }
  if (request === "vitest" || (request && request.startsWith("vitest/"))) {
    return vitestStubPath;
  }
  return originalResolveFilename.call(this, request, parent, isMain, options);
};
