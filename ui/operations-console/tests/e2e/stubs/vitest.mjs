import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const cjsStub = require("./vitest.cjs");

export default cjsStub.default;
export const expect = cjsStub.expect;
export const vi = cjsStub.vi;
export const beforeEach = cjsStub.beforeEach;
export const afterEach = cjsStub.afterEach;
export const beforeAll = cjsStub.beforeAll;
export const afterAll = cjsStub.afterAll;
export const describe = cjsStub.describe;
export const it = cjsStub.it;
export const test = cjsStub.test;
export const suite = cjsStub.suite;
export const createExpect = cjsStub.createExpect;
export const expectType = cjsStub.expectType;
export const assert = cjsStub.assert;
export const assertType = cjsStub.assertType;
