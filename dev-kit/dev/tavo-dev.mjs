async function loadMock() {
  try {
    return await import("../dist/lib/mock.js");
  } catch {
    return await import("../dist/src/mock.js");
  }
}

export async function createDevRuntime(options = {}) {
  const { createMockTavo } = await loadMock();
  const runtime = createMockTavo(options);
  globalThis.tavo = runtime.tavo;
  return runtime;
}

export async function runTavoScript(script, options = {}) {
  const runtime = await createDevRuntime(options);
  const result = await script(runtime.tavo, runtime);
  return { runtime, result };
}
