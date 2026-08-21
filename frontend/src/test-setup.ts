import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import "@testing-library/jest-dom/vitest";

// vitest.config.ts does not set test.globals, so @testing-library/react's automatic
// afterEach(cleanup) registration (which only fires when it detects a global afterEach)
// never triggers — do it explicitly, or DOM nodes from one test leak into the next.
afterEach(cleanup);
