import type { TavoApi, TavoId, TavoLorebook, TavoPreset, TavoRegex } from "./types.js";

export async function safeUpdatePreset(
  tavo: TavoApi,
  idOrName: TavoId,
  mutate: (preset: TavoPreset) => void | TavoPreset
): Promise<TavoPreset> {
  const existing = (await tavo.preset.get(idOrName)) ?? (typeof idOrName === "string" ? await tavo.preset.find(idOrName) : null);
  if (!existing?.id) throw new Error(`Preset not found: ${idOrName}`);
  const draft = structuredClone(existing);
  const result = mutate(draft) ?? draft;
  return tavo.preset.update({ ...result, id: existing.id });
}

export async function safeUpdateLorebook(
  tavo: TavoApi,
  idOrName: TavoId,
  mutate: (lorebook: TavoLorebook) => void | TavoLorebook
): Promise<TavoLorebook> {
  const existing = (await tavo.lorebook.get(idOrName)) ?? (typeof idOrName === "string" ? await tavo.lorebook.find(idOrName) : null);
  if (!existing?.id) throw new Error(`Lorebook not found: ${idOrName}`);
  const draft = structuredClone(existing);
  const result = mutate(draft) ?? draft;
  return tavo.lorebook.update({ ...result, id: existing.id });
}

export async function safeUpdateRegex(
  tavo: TavoApi,
  idOrName: TavoId,
  mutate: (regex: TavoRegex) => void | TavoRegex
): Promise<TavoRegex> {
  const existing = (await tavo.regex.get(idOrName)) ?? (typeof idOrName === "string" ? await tavo.regex.find(idOrName) : null);
  if (!existing?.id) throw new Error(`Regex not found: ${idOrName}`);
  const draft = structuredClone(existing);
  const result = mutate(draft) ?? draft;
  return tavo.regex.update({ ...result, id: existing.id });
}
