/**
 * Telegram WebApp SDK wrappers.
 *
 * The official `telegram-web-app.js` script (loaded in index.html) injects
 * `window.Telegram.WebApp` into the global scope. We expose a typed
 * surface here so the rest of the app uses TS rather than `any`.
 *
 * In dev (vite dev outside Telegram), the global is absent — we fall back
 * to a stub that returns empty initData and lets the user click through.
 * The backend will reject the empty initData, which is the right outcome.
 */

export type TelegramThemeParams = {
  bg_color?: string;
  text_color?: string;
  hint_color?: string;
  link_color?: string;
  button_color?: string;
  button_text_color?: string;
};

export interface TelegramWebApp {
  initData: string;
  initDataUnsafe: {
    user?: { id: number; first_name?: string; username?: string };
    chat?: { id: number; title?: string };
    auth_date?: number;
    hash?: string;
  };
  themeParams: TelegramThemeParams;
  ready(): void;
  expand(): void;
  close(): void;
  showAlert(message: string, callback?: () => void): void;
  HapticFeedback?: {
    notificationOccurred(type: "error" | "success" | "warning"): void;
  };
}

declare global {
  interface Window {
    Telegram?: { WebApp: TelegramWebApp };
  }
}

const stubWebApp: TelegramWebApp = {
  initData: "",
  initDataUnsafe: {},
  themeParams: {},
  ready() {},
  expand() {},
  close() {
    // eslint-disable-next-line no-console
    console.log("(stub) Telegram.WebApp.close()");
  },
  showAlert(message) {
    // eslint-disable-next-line no-console
    console.warn("(stub) Telegram.WebApp.showAlert:", message);
  },
};

export function getWebApp(): TelegramWebApp {
  return window.Telegram?.WebApp ?? stubWebApp;
}

/** True when running inside Telegram (initData present). Vite dev outside
 * Telegram is always false. */
export function isInTelegram(): boolean {
  return Boolean(window.Telegram?.WebApp?.initData);
}
