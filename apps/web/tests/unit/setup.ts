import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import { setCsrfToken, setSessionChangedHandler, setSessionUserSource, setUnauthenticatedHandler } from "@/lib/api/client";

// jsdom lacks these browser APIs that Radix primitives (Select, Dialog) call.
if (typeof Element !== "undefined") {
  Element.prototype.scrollIntoView ??= function scrollIntoView() {};
  Element.prototype.hasPointerCapture ??= function hasPointerCapture() {
    return false;
  };
  Element.prototype.releasePointerCapture ??= function releasePointerCapture() {};
}
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

afterEach(() => {
  cleanup();
  setCsrfToken(null);
  setUnauthenticatedHandler(null);
  setSessionUserSource(null);
  setSessionChangedHandler(null);
});
