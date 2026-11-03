import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import { setCsrfToken, setUnauthenticatedHandler } from "@/lib/api/client";

afterEach(() => {
  cleanup();
  setCsrfToken(null);
  setUnauthenticatedHandler(null);
});
