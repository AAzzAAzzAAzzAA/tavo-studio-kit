import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { buildTavoAssets } from "../src/assets.js";
import { buildArWidgetFiles, buildArWidgetHtml, makeArWidgetRegex } from "../src/widget.js";
import {
  CharaCardV3Schema,
  ManifestSchema,
  PresetImportSchema,
  RegexImportSchema,
  WorldbookImportSchema
} from "../src/schemas.js";

async function readJson(file: string): Promise<unknown> {
  return JSON.parse(await readFile(file, "utf8"));
}

describe("buildTavoAssets", () => {
  it("generates validated import files and manifest", async () => {
    const dir = await mkdtemp(path.join(os.tmpdir(), "tavo-dev-kit-"));
    try {
      const built = await buildTavoAssets({
        outDir: dir,
        suiteId: "codex-devkit-test",
        now: new Date("2026-05-13T00:00:00.000Z")
      });
      expect(built.files.map((file) => file.kind)).toEqual(expect.arrayContaining([
        "character",
        "worldbook",
        "regex",
        "preset",
        "ar-direct-html",
        "ar-widget-html",
        "ar-widget-regex",
        "manifest",
        "test-report"
      ]));
      CharaCardV3Schema.parse(await readJson(path.join(dir, "codex-devkit-test.card.json")));
      WorldbookImportSchema.parse(await readJson(path.join(dir, "codex-devkit-test.worldbook.json")));
      RegexImportSchema.parse(await readJson(path.join(dir, "codex-devkit-test.regex.json")));
      RegexImportSchema.parse(await readJson(path.join(dir, "codex-devkit-test.ar-widget.regex.json")));
      PresetImportSchema.parse(await readJson(path.join(dir, "codex-devkit-test.preset.json")));
      ManifestSchema.parse(await readJson(path.join(dir, "codex-devkit-test.manifest.json")));
      const regexImport = await readJson(path.join(dir, "codex-devkit-test.regex.json")) as Array<{ findRegex: string; replaceString: string; placement?: number[] }>;
      const regexJs = regexImport.find((item) => item.findRegex.includes("CODEX_DEVKIT_REGEX_JS"));
      expect(regexJs).toBeDefined();
      expect(regexJs?.placement).toEqual([1, 2]);
      expect(regexJs?.replaceString).toContain("REGEX_JS_PENDING");
      expect(regexJs?.replaceString).not.toContain("REGEX_JS_OK");
      const widget = await readFile(path.join(dir, "codex-devkit-test.ar-widget.html"), "utf8");
      expect(widget).toContain("AR_WIDGET_PENDING");
      expect(widget).toContain("devkit.arWidget");
      expect(widget).not.toMatch(/<script\b[^>]*\bsrc=/i);
      expect(widget).not.toMatch(/\bimport\s+/);
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });

  it("builds a standalone AR widget package", async () => {
    const dir = await mkdtemp(path.join(os.tmpdir(), "tavo-widget-"));
    try {
      const { html } = await buildArWidgetHtml({ suiteId: "codex-devkit-widget-test" });
      RegexImportSchema.parse(makeArWidgetRegex("codex-devkit-widget-test", html));
      const built = await buildArWidgetFiles({ outDir: dir, suiteId: "codex-devkit-widget-test" });
      expect(await readFile(built.htmlPath, "utf8")).toContain("String.fromCharCode");
      RegexImportSchema.parse(await readJson(built.regexPath));
    } finally {
      await rm(dir, { recursive: true, force: true });
    }
  });
});
