const fallback = (..._args) => {
  throw new Error(
    "Playwright stub of @vitest/expect invoked before Playwright's expect is available"
  );
};

const exportedExpect = global.expect || fallback;
const matcherState = new WeakMap();

const MATCHERS_OBJECT = Symbol.for("matchers-object");
const JEST_MATCHERS_OBJECT = Symbol.for("$$jest-matchers-object");
const GLOBAL_EXPECT = Symbol.for("expect-global");
const ASYMMETRIC_MATCHERS_OBJECT = Symbol.for("asymmetric-matchers-object");

const spies = {
  get: () => ({}),
  set: () => {},
};

function ensureState(expectation = exportedExpect) {
  if (!matcherState.has(expectation)) {
    matcherState.set(expectation, {});
  }
  return matcherState.get(expectation);
}

function getState(expectation = exportedExpect) {
  return ensureState(expectation);
}

function setState(nextState, expectation = exportedExpect) {
  const current = ensureState(expectation);
  matcherState.set(expectation, { ...current, ...nextState });
}

class AsymmetricMatcher {
  constructor(expected) {
    this.expected = expected;
  }
  asymmetricMatch() {
    return true;
  }
  toString() {
    return this.constructor.name;
  }
}

class Any extends AsymmetricMatcher {}
class Anything extends AsymmetricMatcher {}
class ArrayContaining extends AsymmetricMatcher {}
class ObjectContaining extends AsymmetricMatcher {}
class StringContaining extends AsymmetricMatcher {}
class StringMatching extends AsymmetricMatcher {}

function arrayBufferEquality() {
  return false;
}

function sparseArrayEquality() {
  return false;
}

function subsetEquality() {
  return false;
}

function equals(a, b) {
  return Object.is(a, b);
}

function iterableEquality(a, b) {
  if (a && b && typeof a[Symbol.iterator] === "function" && typeof b[Symbol.iterator] === "function") {
    const arrA = Array.from(a);
    const arrB = Array.from(b);
    if (arrA.length !== arrB.length) {
      return false;
    }
    return arrA.every((value, index) => Object.is(value, arrB[index]));
  }
  return false;
}

function typeEquality(a, b) {
  return typeof a === typeof b;
}

function isAsymmetric(value) {
  return Boolean(value && typeof value.asymmetricMatch === "function");
}

function hasAsymmetric(value) {
  if (!value || typeof value !== "object") {
    return false;
  }
  return Object.values(value).some(isAsymmetric);
}

function isImmutableUnorderedKeyed() {
  return false;
}

function isImmutableUnorderedSet() {
  return false;
}

function isA(type, value) {
  return typeof value === type || value instanceof type;
}

function hasProperty(object, key) {
  return object != null && Object.prototype.hasOwnProperty.call(object, key);
}

function getObjectKeys(object) {
  return object ? Object.keys(object) : [];
}

function getObjectSubset(object) {
  return object ? { ...object } : {};
}

function generateToBeMessage(received, expected) {
  return `Expected ${received} to be ${expected}`;
}

function fnNameFor(fn) {
  return fn && fn.name ? fn.name : "anonymous";
}

function pluralize(word, count) {
  return count === 1 ? word : `${word}s`;
}

function addCustomEqualityTesters() {}

function JestAsymmetricMatchers(chai) {
  return chai;
}

function JestChaiExpect(chai) {
  return chai.expect;
}

function JestExtend(chai) {
  return chai;
}

module.exports = {
  default: exportedExpect,
  expect: exportedExpect,
  MATCHERS_OBJECT,
  JEST_MATCHERS_OBJECT,
  GLOBAL_EXPECT,
  ASYMMETRIC_MATCHERS_OBJECT,
  spies,
  getState,
  setState,
  Any,
  Anything,
  ArrayContaining,
  AsymmetricMatcher,
  ObjectContaining,
  StringContaining,
  StringMatching,
  arrayBufferEquality,
  sparseArrayEquality,
  subsetEquality,
  equals,
  iterableEquality,
  typeEquality,
  isAsymmetric,
  hasAsymmetric,
  isImmutableUnorderedKeyed,
  isImmutableUnorderedSet,
  isA,
  hasProperty,
  getObjectKeys,
  getObjectSubset,
  generateToBeMessage,
  fnNameFor,
  pluralize,
  addCustomEqualityTesters,
  JestAsymmetricMatchers,
  JestChaiExpect,
  JestExtend,
};
