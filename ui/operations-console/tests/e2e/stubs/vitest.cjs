const fallback = (..._args) => {
  throw new Error(
    "Playwright stub of vitest invoked before Playwright's expect is available"
  );
};

const exportedExpect = global.expect || fallback;
const noop = () => {};

function createExpect() {
  return exportedExpect;
}

function fn() {
  return noop;
}

const vi = new Proxy(
  {},
  {
    get: () => fn,
  }
);

module.exports = {
  default: exportedExpect,
  expect: exportedExpect,
  vi,
  beforeEach: noop,
  afterEach: noop,
  beforeAll: noop,
  afterAll: noop,
  describe: noop,
  it: noop,
  test: noop,
  suite: noop,
  createExpect,
  expectType: noop,
  assert: exportedExpect,
  assertType: noop,
};
