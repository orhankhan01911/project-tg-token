import { describe, expect, it } from "vitest";

import { hasReownProjectId, openAppKit } from "../appkit";

describe("appkit (no project ID in test env)", () => {
  it("hasReownProjectId is false when VITE_REOWN_PROJECT_ID is unset", () => {
    expect(import.meta.env.VITE_REOWN_PROJECT_ID).toBeUndefined();
    expect(hasReownProjectId).toBe(false);
  });

  it("openAppKit returns false (no-op) without a project ID", () => {
    expect(openAppKit()).toBe(false);
  });
});
