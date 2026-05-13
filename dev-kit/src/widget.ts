import { readFile, rm } from "node:fs/promises";
import path from "node:path";
import { ensureDir, sha256, writeText } from "./fs.js";

export interface BuildArWidgetOptions {
  suiteId?: string;
  templateDir?: string;
  outDir?: string;
  cleanOutDir?: boolean;
}

export interface BuiltArWidget {
  suiteId: string;
  outDir: string;
  htmlPath: string;
  regexPath: string;
  htmlSha256: string;
  regexSha256: string;
}

const defaultTemplateDir = path.resolve("templates/ar-widget");
const defaultWidgetOutDir = path.resolve("dist/widgets");

function stamp(date: Date): string {
  return date.toISOString().replace(/[:.]/g, "-");
}

function replaceSuiteId(source: string, suiteId: string): string {
  return source.replaceAll("__TAVO_SUITE_ID__", suiteId);
}

export function assertPortableHtml(html: string): void {
  const banned = [
    /\bimport\s+/,
    /\brequire\s*\(/,
    /\bprocess\./,
    /\bfs\./,
    /\bnode:/,
    /<script\b[^>]*\bsrc\s*=/i,
    /<link\b[^>]*\bhref\s*=\s*["']https?:/i,
    /https?:\/\//i
  ];
  const hit = banned.find((pattern) => pattern.test(html));
  if (hit) throw new Error(`AR widget HTML is not portable: matched ${hit}`);
}

export async function buildArWidgetHtml(options: BuildArWidgetOptions = {}): Promise<{ suiteId: string; html: string }> {
  const suiteId = options.suiteId ?? `codex-devkit-widget-${stamp(new Date())}`;
  const templateDir = path.resolve(options.templateDir ?? defaultTemplateDir);
  const [html, css, js] = await Promise.all([
    readFile(path.join(templateDir, "widget.html"), "utf8"),
    readFile(path.join(templateDir, "widget.css"), "utf8"),
    readFile(path.join(templateDir, "widget.js"), "utf8")
  ]);
  const bundled = replaceSuiteId(
    html
      .replace("<!-- __TAVO_WIDGET_CSS__ -->", `<style>\n${css.trim()}\n</style>`)
      .replace("<!-- __TAVO_WIDGET_JS__ -->", `<script>\n${js.trim()}\n</script>`),
    suiteId
  );
  assertPortableHtml(bundled);
  return { suiteId, html: bundled };
}

export function makeArWidgetRegex(suiteId: string, html: string) {
  return [
    {
      id: `${suiteId}-ar-widget-regex`,
      scriptName: `${suiteId} AR Widget`,
      findRegex: "<状态面板\\s*\\/>",
      replaceString: html,
      trimStrings: [],
      placement: [2],
      placements: ["char"],
      disabled: false,
      enabled: true,
      markdownOnly: true,
      promptOnly: false,
      runOnEdit: false,
      timing: "display",
      substituteRegex: 0,
      substitution: "none",
      minDepth: null,
      maxDepth: null
    }
  ];
}

export async function buildArWidgetFiles(options: BuildArWidgetOptions = {}): Promise<BuiltArWidget> {
  const { suiteId, html } = await buildArWidgetHtml(options);
  const outDir = path.resolve(options.outDir ?? defaultWidgetOutDir);
  if (options.cleanOutDir ?? true) await rm(outDir, { recursive: true, force: true });
  await ensureDir(outDir);

  const htmlPath = path.join(outDir, `${suiteId}.ar-widget.html`);
  const regexPath = path.join(outDir, `${suiteId}.ar-widget.regex.json`);
  await writeText(htmlPath, html);
  await writeText(regexPath, `${JSON.stringify(makeArWidgetRegex(suiteId, html), null, 2)}\n`);

  return {
    suiteId,
    outDir,
    htmlPath,
    regexPath,
    htmlSha256: await sha256(htmlPath),
    regexSha256: await sha256(regexPath)
  };
}
