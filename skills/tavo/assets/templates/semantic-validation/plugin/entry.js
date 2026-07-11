const semanticRunId = "{{RUN_ID}}";
const ejsExternalKey = `semantic.${semanticRunId}.ejs.external`;
const ejsRenderCountKey = `semantic.${semanticRunId}.ejs.renderCount`;

function setAndRead(key) {
  tavo.set(key, "clicked", "chat");
  return tavo.get(key, "chat");
}

tavo.plugin.onInputAction("observe-scene", async () => {
  const state = setAndRead(`semantic.${semanticRunId}.plugin.observe`);
  await tavo.input.set(`请观察当前场景，列出三个最值得互动的线索，并解释每条线索的风险。（TPG_${semanticRunId}_OBSERVE state=${state}）`);
});

tavo.plugin.onInputAction("clarify-goal", async () => {
  const state = setAndRead(`semantic.${semanticRunId}.plugin.clarify`);
  await tavo.input.append(` 请先用一句话确认我当前最重要的目标，再提出一个真正必要的澄清问题。（TPG_${semanticRunId}_CLARIFY state=${state}）`);
});

tavo.plugin.onInputAction("check-state", async () => {
  const state = setAndRead(`semantic.${semanticRunId}.plugin.state`);
  await tavo.input.set(`请核对目前的状态，把已经确认、仍不确定和互相矛盾的信息分别列出。（TPG_${semanticRunId}_STATE state=${state}）`);
});

tavo.plugin.onInputAction("propose-next-step", async () => {
  const state = setAndRead(`semantic.${semanticRunId}.plugin.plan`);
  await tavo.input.append(` 请给出下一步行动方案，包含首选方案、备选方案和明确的停止条件。（TPG_${semanticRunId}_PLAN state=${state}）`);
});

tavo.plugin.onInputAction("summarize-evidence", async () => {
  const state = setAndRead(`semantic.${semanticRunId}.plugin.evidence`);
  await tavo.input.set(`请把本轮获得的证据压缩成五条可复核结论，并为每条结论注明依据。（TPG_${semanticRunId}_EVIDENCE state=${state}）`);
});

tavo.plugin.onInputAction("ejs-runtime-seed", async () => {
  const randomPart = (() => {
    try {
      const values = new Uint32Array(2);
      crypto.getRandomValues(values);
      return `${values[0].toString(36)}${values[1].toString(36)}`;
    } catch (_) {
      return `${Math.floor(Math.random() * 0xffffffff).toString(36)}${Date.now().toString(36)}`;
    }
  })();
  const token = `EJS_RUNTIME_${semanticRunId}_${Date.now().toString(36)}_${randomPart}`;
  const before = Number(tavo.get(ejsRenderCountKey, "chat") || 0);
  tavo.set(ejsExternalKey, token, "chat");
  const stored = tavo.get(ejsExternalKey, "chat");
  await tavo.input.set(`[EJS-SEED:${semanticRunId}] token=${stored};before=${before}`);
});

tavo.plugin.onInputAction("ejs-runtime-probe", async () => {
  const token = tavo.get(ejsExternalKey, "chat");
  const after = Number(tavo.get(ejsRenderCountKey, "chat") || 0);
  await tavo.input.set(`[EJS-PROBE:${semanticRunId}] token=${token};after=${after}`);
});
