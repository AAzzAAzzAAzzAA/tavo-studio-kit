import { runTavoScript } from "../dev/tavo-dev.mjs";

async function script(tavo) {
  const count = Number(tavo.get("example.runCount", "chat") ?? 0) + 1;
  tavo.set("example.runCount", count, "chat");

  const memory = await tavo.memory.current();
  if (memory) {
    memory.enabled = true;
    memory.memories = Array.isArray(memory.memories) ? memory.memories : [];
    memory.memories.push(`本地 mock 已运行 ${count} 次`);
    await tavo.memory.update(memory);
  }

  tavo.utils.toast(`状态脚本已运行 ${count} 次`);
  return count;
}

const { result, runtime } = await runTavoScript(script);
console.log({ result, variables: runtime.state.variables, toasts: runtime.toasts });
