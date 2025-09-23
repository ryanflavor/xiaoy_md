import { afterEach, beforeAll } from "vitest";
import { cleanup } from "@testing-library/react";
import ResizeObserver from "resize-observer-polyfill";

afterEach(() => {
  cleanup();
});

beforeAll(() => {
  if (!(global as unknown as { ResizeObserver?: typeof ResizeObserver }).ResizeObserver) {
    (global as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver = ResizeObserver;
  }

  const elementPrototype = HTMLElement.prototype as unknown as Record<string, unknown>;

  if (!Object.prototype.hasOwnProperty.call(elementPrototype, "offsetWidth")) {
    Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
      configurable: true,
      value: 1024,
    });
  }

  if (!Object.prototype.hasOwnProperty.call(elementPrototype, "offsetHeight")) {
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
      configurable: true,
      value: 768,
    });
  }

  const originalGetBoundingClientRect = HTMLElement.prototype.getBoundingClientRect;
  HTMLElement.prototype.getBoundingClientRect = function getBoundingClientRectMock() {
    return {
      width: 1024,
      height: 768,
      top: 0,
      left: 0,
      bottom: 768,
      right: 1024,
      toJSON() {
        return this;
      },
    } as DOMRect;
  };

  Object.defineProperty(HTMLElement.prototype, "__originalGetBoundingClientRect", {
    configurable: true,
    value: originalGetBoundingClientRect,
  });
});
