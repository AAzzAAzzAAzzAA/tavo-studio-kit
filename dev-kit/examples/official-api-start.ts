import { createMockTavo, defineTavoScript } from "../src/index.js";

export const script = defineTavoScript(async (tavo) => {
  const selected = await tavo.utils.select(["observe", "write", "stop"], "Mode", "observe");
  tavo.set("examples.mode", selected, "chat");

  const messageId = await tavo.message.append({
    role: "assistant",
    content: `Official API example selected: ${selected}`
  });

  return { selected, messageId };
});

if (import.meta.url === `file://${process.argv[1]}`) {
  const runtime = createMockTavo();
  console.log(await script(runtime.tavo));
}
