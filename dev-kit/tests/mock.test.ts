import { describe, expect, it } from "vitest";
import { createMockTavo } from "../src/mock.js";
import { createTavoSDK } from "../src/sdk.js";
import { safeUpdateLorebook } from "../src/helpers.js";

describe("createMockTavo", () => {
  it("supports scoped dotted variables", () => {
    const { tavo } = createMockTavo();
    tavo.set("status.hp", 42);
    tavo.set("status.hp", 99, "global");
    expect(tavo.get("status.hp")).toBe(42);
    expect(tavo.get("status.hp", "global")).toBe(99);
    tavo.unset("status.hp");
    expect(tavo.get("status.hp")).toBeUndefined();
    expect(tavo.get("status.hp", "global")).toBe(99);
  });

  it("supports async resource CRUD", async () => {
    const { tavo } = createMockTavo();
    const created = await tavo.character.create({ name: "A", first_mes: "hi" });
    expect(created.id).toBeTruthy();
    expect(await tavo.character.find("A")).toMatchObject({ name: "A" });
    await tavo.character.update({ ...created, id: created.id!, name: "B" });
    expect(await tavo.character.find("A")).toBeNull();
    expect(await tavo.character.find("B")).toMatchObject({ name: "B" });
    expect(await tavo.character.delete(created.id!)).toBe(true);
  });

  it("supports message reads, writes, filters, and current message", async () => {
    const { tavo } = createMockTavo({
      messages: [
        { id: 1, role: "user", content: "hello" },
        { id: 2, role: "assistant", content: "hi" }
      ]
    });
    expect(await tavo.message.count()).toBe(2);
    expect(await tavo.message.current()).toMatchObject({ id: 2 });
    expect(await tavo.message.find([-1])).toEqual([expect.objectContaining({ content: "hi" })]);
    expect(await tavo.message.find(undefined, { role: "user" })).toEqual([expect.objectContaining({ content: "hello" })]);
    const id = await tavo.message.append({ role: "assistant", content: "new" });
    expect(await tavo.message.get(id!)).toMatchObject({ content: "new" });
    await tavo.message.update({ id: id!, content: "changed" });
    expect(await tavo.message.current()).toMatchObject({ content: "changed" });
    expect(await tavo.message.delete(id!)).toBe(id);
    expect(await tavo.message.count()).toBe(2);
  });

  it("supports resource import, select, app version, toast, and openUrl", async () => {
    const { tavo, toasts, openedUrls } = createMockTavo({ select: "b", appVersion: "0.81.3", appVersionNumber: 813 });
    const imported = await tavo.character.import({ data: { name: "Imported", first_mes: "hello" } });
    expect(imported.characterId).toBeTruthy();
    expect(await tavo.character.find("Imported")).toMatchObject({ name: "Imported" });
    expect(await tavo.preset.import({ name: "Preset", prompts: [] })).toBeTruthy();
    expect(await tavo.lorebook.import({ name: "Book", entries: [] })).toBeTruthy();
    expect(await tavo.regex.import({ name: "Regex", entries: [] })).toBeTruthy();
    expect(await tavo.utils.select(["a", "b"], "Pick", "a")).toBe("b");
    expect(await tavo.app.version()).toBe("0.81.3");
    expect(await tavo.app.versionNumber()).toBe(813);
    tavo.utils.toast("ok");
    tavo.utils.openUrl("https://example.invalid");
    expect(toasts).toEqual(["ok"]);
    expect(openedUrls).toEqual(["https://example.invalid"]);
  });

  it("records input, export, generate, and memory events", async () => {
    const { tavo, events, exports, sentInputs } = createMockTavo();
    tavo.input.set("hello");
    tavo.input.append(" world");
    tavo.input.send();
    expect(sentInputs).toEqual(["hello world"]);
    expect(await tavo.generate("probe")).toContain("probe");
    tavo.utils.export("x.txt", "abc");
    expect(exports).toEqual([{ name: "x.txt", data: "abc" }]);
    const memory = await tavo.memory.current();
    expect(memory).toBeTruthy();
    await tavo.memory.update({ ...memory!, enabled: true, memories: ["m1"] });
    expect(events.map((event) => event.type)).toContain("memory.update");
  });

  it("supports the optional SDK helper layer", async () => {
    const runtime = createMockTavo();
    const sdk = createTavoSDK(runtime.tavo);
    expect(sdk.vars.chat.set("ready", true)).toBe(true);
    expect(sdk.vars.chat.get("ready")).toBe(true);
    await sdk.messages.append("assistant", "hello from sdk");
    expect(await sdk.messages.count()).toBe(1);
    await sdk.chat.rename("Renamed");
    expect(await sdk.chat.current()).toMatchObject({ name: "Renamed" });
    await sdk.memory.add("m1");
    expect(await sdk.memory.current()).toMatchObject({ enabled: true, memories: ["m1"] });
    sdk.input.set("hello world");
    expect(await sdk.input.replace("world", "Tavo")).toBe("hello Tavo");
  });
});

describe("safe update helpers", () => {
  it("uses read-modify-update for lorebooks", async () => {
    const { tavo } = createMockTavo();
    const book = await tavo.lorebook.create({ name: "Book", entries: [{ name: "E", content: "old" }] });
    const updated = await safeUpdateLorebook(tavo, book.id!, (draft) => {
      if (!Array.isArray(draft.entries)) throw new Error("Expected array entries in this fixture");
      draft.entries[0]!.content = "new";
    });
    expect(Array.isArray(updated.entries) ? updated.entries[0]?.content : undefined).toBe("new");
  });
});
