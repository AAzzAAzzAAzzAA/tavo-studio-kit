import type { TavoApi } from "../src/types.js";

declare global {
  const tavo: TavoApi;

  interface Window {
    tavo?: TavoApi;
  }
}

export {};
