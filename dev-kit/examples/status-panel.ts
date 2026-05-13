import { defineTavoScript } from "../src/types.js";

export default defineTavoScript(async (tavo) => {
  const visits = (tavo.get<number>("devkit.visits") ?? 0) + 1;
  tavo.set("devkit.visits", visits);
  tavo.input.set(`<div class="codex-devkit-panel">DevKit visits: ${visits}</div>`);
  tavo.utils.toast(`DevKit local script ran ${visits} time(s)`);
  return { visits };
});

