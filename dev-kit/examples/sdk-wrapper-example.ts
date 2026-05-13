import { createMockTavo, createTavoSDK, defineTavoScript } from "../src/index.js";

export const script = defineTavoScript(async (tavo) => {
  const sdk = createTavoSDK(tavo);

  sdk.vars.chat.set("wrapper.ready", true);
  await sdk.memory.add("Wrapper helper example passed.");
  await sdk.messages.append("assistant", "SDK wrapper example passed.");

  return {
    ready: sdk.vars.chat.get<boolean>("wrapper.ready"),
    messages: await sdk.messages.count()
  };
});

if (import.meta.url === `file://${process.argv[1]}`) {
  const runtime = createMockTavo();
  console.log(await script(runtime.tavo));
}
