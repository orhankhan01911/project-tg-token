import { afterEach, describe, expect, it, vi } from "vitest";

import { getWebApp, isInTelegram } from "../telegram";

describe("telegram wrapper", () => {
  afterEach(() => {
    delete (window as unknown as { Telegram?: unknown }).Telegram;
  });

  it("returns a stub when window.Telegram is absent", () => {
    const wa = getWebApp();
    expect(wa.initData).toBe("");
    expect(typeof wa.ready).toBe("function");
    expect(isInTelegram()).toBe(false);
  });

  it("returns the real WebApp when Telegram injects it", () => {
    const fake = {
      initData: "auth_date=123&user=%7B%22id%22%3A1%7D&hash=abc",
      initDataUnsafe: { user: { id: 1 } },
      themeParams: {},
      ready: vi.fn(),
      expand: vi.fn(),
      close: vi.fn(),
      showAlert: vi.fn(),
    };
    (window as unknown as { Telegram: { WebApp: typeof fake } }).Telegram = {
      WebApp: fake,
    };
    expect(getWebApp().initData).toBe(fake.initData);
    expect(isInTelegram()).toBe(true);
  });
});
