import { execFile } from "node:child_process";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { config as loadDotenv } from "dotenv";
import { buildTavoAssets, type BuiltAssets } from "./assets.js";
import { redact } from "./redact.js";
import { ensureDir, writeJson } from "./fs.js";

const execFileAsync = promisify(execFile);
const root = path.resolve(".");
const tavoAdb = process.env.TAVO_ADB_BIN ?? path.join(root, "scripts", "tavo-adb");

export type ProbeStatus = "verified" | "failed" | "blocked" | "skipped";

export interface ProbeStep {
  name: string;
  status: ProbeStatus;
  detail: string;
  artifact?: string;
}

interface UiNode {
  text: string;
  contentDesc: string;
  resourceId: string;
  className: string;
  clickable: boolean;
  bounds: { x1: number; y1: number; x2: number; y2: number };
  center: { x: number; y: number };
}

interface FindNodeOptions {
  exactText?: boolean;
  exactContentDesc?: boolean;
  resourceId?: string;
  className?: string;
  xMin?: number;
  xMax?: number;
  yMin?: number;
  yMax?: number;
  preferClickable?: boolean;
  documentEntryTap?: boolean;
}

interface ProbeStepResult {
  status?: ProbeStatus;
  detail: string;
  artifact?: string;
}

async function run(command: string, args: string[], timeout = 30000): Promise<{ stdout: string; stderr: string }> {
  try {
    const result = await execFileAsync(command, args, {
      cwd: root,
      timeout,
      maxBuffer: 20 * 1024 * 1024,
      env: { ...process.env }
    });
    return { stdout: redact(result.stdout), stderr: redact(result.stderr) };
  } catch (error) {
    const err = error as Error & { stdout?: string; stderr?: string };
    throw new Error(`${command} ${args.join(" ")} failed: ${redact(err.message)}\n${redact(err.stdout ?? "")}\n${redact(err.stderr ?? "")}`);
  }
}

async function sleep(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function tap(x: number, y: number, delay = 700): Promise<void> {
  await run(tavoAdb, ["tap", String(Math.round(x)), String(Math.round(y))]);
  await sleep(delay);
}

async function back(delay = 700): Promise<void> {
  await run(tavoAdb, ["back"]);
  await sleep(delay);
}

function escapeAdbShellText(text: string): string {
  return text.replace(/([\\ "'`$&|;<>(){}[\]*?!#])/g, "\\$1");
}

async function inputText(text: string): Promise<void> {
  await run(tavoAdb, ["text", escapeAdbShellText(text)], 45000);
}

async function clearFocusedText(count = 260): Promise<void> {
  await run("adb", [
    "-s",
    process.env.TAVO_DEVICE ?? "emulator-5554",
    "shell",
    `for i in $(seq 1 ${count}); do input keyevent 67; done`
  ], 45000);
}

async function tapChatSendButton(): Promise<void> {
  const xml = await dump();
  const candidates = parseUiNodes(xml)
    .filter((node) => node.clickable && node.center.x > 900 && node.center.y > 1800)
    .sort((a, b) => b.bounds.y1 - a.bounds.y1);
  const send = candidates[0];
  if (!send) throw new Error("Could not locate chat send button");
  await tap(send.center.x, send.center.y, 2500);
}

async function focusChatInput(): Promise<void> {
  const xml = await dump();
  const input = parseUiNodes(xml)
    .filter((node) => node.className === "android.widget.EditText" && node.center.y > 1600)
    .sort((a, b) => b.bounds.y1 - a.bounds.y1)[0];
  if (input) {
    await tap(input.center.x, input.center.y, 500);
    return;
  }
  await tap(540, 2222, 500);
}

async function settleChatAfterDirectProbe(): Promise<void> {
  await openTavoReady();
  try {
    await tapChatSendButton();
  } catch {
    // If no bottom-right chat action is found, continue and let the input wait fail with context.
  }
  await sleep(2000);
  await openTavoReady();
  await sleep(1000);
}

async function texts(): Promise<string> {
  const result = await run(tavoAdb, ["texts"], 45000);
  return result.stdout;
}

async function waitForVisibleText(needle: string, timeoutMs = 10000): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  let last = "";
  while (Date.now() < deadline) {
    last = await texts();
    if (last.includes(needle)) return last;
    await sleep(500);
  }
  throw new Error(`Timed out waiting for visible text: ${needle}. Last text snapshot:\n${last}`);
}

async function dump(): Promise<string> {
  const result = await run(tavoAdb, ["dump"], 45000);
  return result.stdout;
}

async function waitForUiXmlText(needle: string, timeoutMs = 10000): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  let last = "";
  while (Date.now() < deadline) {
    last = await dump();
    if (last.includes(needle)) return last;
    await sleep(500);
  }
  throw new Error(`Timed out waiting for UI XML text: ${needle}`);
}

async function openTavoReady(forceRestart = false): Promise<string> {
  if (forceRestart) {
    await run("adb", ["-s", process.env.TAVO_DEVICE ?? "emulator-5554", "shell", "am", "force-stop", "app.bitbear.tav"]);
    await sleep(1000);
  }
  await run(tavoAdb, ["open"], 45000);
  for (let attempt = 0; attempt < 6; attempt += 1) {
    await sleep(1200);
    const visible = await texts();
    if (visible.trim().length > 0) return visible;
  }
  if (!forceRestart) return openTavoReady(true);
  throw new Error("Tavo opened to a blank screen");
}

function decodeXml(value: string): string {
  return value
    .replace(/&#10;/g, "\n")
    .replace(/&quot;/g, "\"")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
}

function readAttr(attrs: string, name: string): string {
  const match = attrs.match(new RegExp(`${name}="([^"]*)"`));
  return decodeXml(match?.[1] ?? "");
}

function parseUiNodes(xml: string): UiNode[] {
  const nodes: UiNode[] = [];
  for (const match of xml.matchAll(/<node\b([^>]*)>/g)) {
    const attrs = match[1] ?? "";
    const boundsMatch = attrs.match(/bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"/);
    if (!boundsMatch) continue;
    const x1 = Number(boundsMatch[1]);
    const y1 = Number(boundsMatch[2]);
    const x2 = Number(boundsMatch[3]);
    const y2 = Number(boundsMatch[4]);
    nodes.push({
      text: readAttr(attrs, "text"),
      contentDesc: readAttr(attrs, "content-desc"),
      resourceId: readAttr(attrs, "resource-id"),
      className: readAttr(attrs, "class"),
      clickable: readAttr(attrs, "clickable") === "true",
      bounds: { x1, y1, x2, y2 },
      center: { x: (x1 + x2) / 2, y: (y1 + y2) / 2 }
    });
  }
  return nodes;
}

function nodeMatches(node: UiNode, needle: string, options: FindNodeOptions): boolean {
  if (options.resourceId && node.resourceId !== options.resourceId) return false;
  if (options.className && node.className !== options.className) return false;
  if (options.xMin !== undefined && node.center.x < options.xMin) return false;
  if (options.xMax !== undefined && node.center.x > options.xMax) return false;
  if (options.yMin !== undefined && node.center.y < options.yMin) return false;
  if (options.yMax !== undefined && node.center.y > options.yMax) return false;
  if (options.exactText && node.text !== needle) return false;
  if (options.exactContentDesc && node.contentDesc !== needle) return false;
  if (options.exactText || options.exactContentDesc) return true;
  return node.text.includes(needle) || node.contentDesc.includes(needle);
}

function findNode(xml: string, needle: string, options: FindNodeOptions = {}): UiNode | null {
  const candidates = parseUiNodes(xml).filter((node) => nodeMatches(node, needle, options));
  if (candidates.length === 0) return null;
  candidates.sort((a, b) => {
    if (options.preferClickable && a.clickable !== b.clickable) return a.clickable ? -1 : 1;
    return (a.bounds.y1 - b.bounds.y1) || (a.bounds.x1 - b.bounds.x1);
  });
  return candidates[0] ?? null;
}

async function tapVisible(needle: string, delay = 800, options: FindNodeOptions = {}): Promise<void> {
  const xml = await dump();
  const node = findNode(xml, needle, options);
  if (!node) throw new Error(`Could not find visible UI label: ${needle}`);
  await tap(node.center.x, node.center.y, delay);
}

async function scanMedia(remoteDir: string): Promise<void> {
  await run("adb", [
    "-s",
    process.env.TAVO_DEVICE ?? "emulator-5554",
    "shell",
    `for f in ${remoteDir}/*; do am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://$f >/dev/null; done`
  ]);
}

async function scrollUp(delay = 500): Promise<void> {
  await run("adb", ["-s", process.env.TAVO_DEVICE ?? "emulator-5554", "shell", "input", "swipe", "800", "750", "800", "2100", "450"]);
  await sleep(delay);
}

async function scrollDown(delay = 700): Promise<void> {
  await run("adb", ["-s", process.env.TAVO_DEVICE ?? "emulator-5554", "shell", "input", "swipe", "800", "2100", "800", "750", "550"]);
  await sleep(delay);
}

async function scrollToTop(attempts = 4): Promise<void> {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    await scrollUp(250);
  }
}

function tapPointForNode(node: UiNode, documentEntryTap = false): { x: number; y: number } {
  if (!documentEntryTap) return node.center;
  return {
    x: Math.max(80, node.bounds.x1 - 70),
    y: node.center.y
  };
}

async function ensureDocumentsListView(): Promise<void> {
  const xml = await dump();
  const listView = findNode(xml, "列表视图", { exactContentDesc: true });
  if (listView) {
    await tap(listView.center.x, listView.center.y, 700);
  }
}

async function documentPickerDownloadsRoot(): Promise<void> {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const visible = await texts();
    if (!visible.includes("显示根目录") && !visible.includes("打开文档")) {
      throw new Error("Android file picker is not visible");
    }

    const xml = await dump();
    const drawerDownload = findNode(xml, "下载", {
      exactText: true,
      resourceId: "android:id/title",
      xMax: 760,
      yMin: 600,
      yMax: 850
    });
    if (drawerDownload) {
      await tap(drawerDownload.center.x, drawerDownload.center.y, 1200);
      await ensureDocumentsListView();
      await scrollToTop();
      return;
    }

    const rootButton = findNode(xml, "显示根目录", { exactContentDesc: true }) ?? findNode(xml, "显示根目录");
    if (rootButton) {
      await tap(rootButton.center.x, rootButton.center.y, 700);
      continue;
    }
  }
  throw new Error("Could not open Android Downloads root in file picker");
}

async function searchDocumentsUi(query: string): Promise<boolean> {
  const xml = await dump();
  const search = findNode(xml, "搜索", { exactContentDesc: true }) ?? findNode(xml, "搜索");
  if (!search) return false;
  await tap(search.center.x, search.center.y, 500);
  await run(tavoAdb, ["text", query], 30000);
  await sleep(1500);
  return true;
}

function looksLikeDocumentPicker(visible: string): boolean {
  return visible.includes("显示根目录") || visible.includes("打开文档") || visible.includes("已选择");
}

async function waitForDocumentsUiToOpen(timeoutMs = 8000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let last = "";
  while (Date.now() < deadline) {
    last = await texts();
    if (looksLikeDocumentPicker(last)) return;
    await sleep(500);
  }
  throw new Error(`Timed out waiting for Android file picker. Last text snapshot:\n${last}`);
}

async function waitForDocumentsUiToClose(timeoutMs = 8000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const visible = await texts();
    if (!looksLikeDocumentPicker(visible)) return true;
    await sleep(500);
  }
  return false;
}

async function confirmDocumentsSelectionIfNeeded(): Promise<void> {
  const visible = await texts();
  if (!visible.includes("已选择") || !visible.includes("选择")) return;
  const xml = await dump();
  const choose = findNode(xml, "选择", { exactText: true, preferClickable: true }) ??
    findNode(xml, "选择", { exactContentDesc: true, preferClickable: true });
  if (!choose) throw new Error("File is selected, but DocumentsUI choose button is not visible");
  await tap(choose.center.x, choose.center.y, 1800);
}

async function tapWithScrolling(needle: string, options: FindNodeOptions, attempts = 6): Promise<boolean> {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const xml = await dump();
    const node = findNode(xml, needle, options);
    if (node) {
      const point = tapPointForNode(node, options.documentEntryTap);
      await tap(point.x, point.y, 1200);
      return true;
    }
    await scrollDown();
  }
  return false;
}

async function ensureMorePage(): Promise<void> {
  for (let i = 0; i < 6; i += 1) {
    const visible = await texts();
    if (visible.trim().length === 0) {
      await openTavoReady(true);
      continue;
    }
    if (visible.includes("主屏幕") && (visible.includes("图库") || visible.includes("拨打电话") || visible.includes("相机"))) {
      await openTavoReady();
      continue;
    }
    if (visible.includes("模型设置") && visible.includes("世界书") && visible.includes("正则")) return;
    if (visible.includes("API连接") && visible.includes("角色") && visible.includes("更多") && !visible.includes("模型设置")) {
      await tap(650, 2125, 900);
      continue;
    }
    if (visible.includes("scroll to top") || visible.includes("scroll to bottom") || visible.includes("随便聊聊") || visible.includes("维多利亚·凌")) {
      await tap(63, 127, 900);
      continue;
    }
    await back(900);
  }
  throw new Error("Could not navigate to Tavo More page");
}

async function openMoreItem(label: string, fallbackY: number): Promise<void> {
  await ensureMorePage();
  const xml = await dump();
  const node = findNode(xml, label, {
    xMin: 50,
    yMin: 250,
    yMax: 1900,
    preferClickable: true
  });
  if (node) {
    await tap(node.center.x, node.center.y, 1000);
    return;
  }
  await tap(540, fallbackY, 1000);
}

async function selectGeneratedFile(suiteId: string, suffix: string): Promise<void> {
  const filename = `${suiteId}.${suffix}`;
  await documentPickerDownloadsRoot();

  let openedFolder = await tapWithScrolling(suiteId, { exactText: true, documentEntryTap: true }, 5);
  if (!openedFolder) {
    await documentPickerDownloadsRoot();
    const searched = await searchDocumentsUi(suiteId);
    if (searched) openedFolder = await tapWithScrolling(suiteId, { exactText: true, documentEntryTap: true }, 3);
  }
  if (!openedFolder) {
    throw new Error(`Could not open generated folder ${suiteId}`);
  }

  const openedFile = await tapWithScrolling(filename, { exactText: true, documentEntryTap: true }, 5);
  if (openedFile) {
    await confirmDocumentsSelectionIfNeeded();
    if (await waitForDocumentsUiToClose()) return;
  }

  const searched = await searchDocumentsUi(filename);
  if (searched) {
    const foundAfterSearch = await tapWithScrolling(filename, { exactText: true, documentEntryTap: true }, 3);
    if (foundAfterSearch) {
      await confirmDocumentsSelectionIfNeeded();
      if (await waitForDocumentsUiToClose()) return;
    }
  }
  throw new Error(`Could not select generated file ${filename}`);
}

async function importRegex(suiteId: string): Promise<void> {
  await openMoreItem("正则", 1559);
  await tapVisible("新建");
  await tapVisible("从文件导入正则");
  await selectGeneratedFile(suiteId, "regex.json");
  await tapVisible("保存", 1600);
  const visible = await texts();
  if (!visible.includes(`${suiteId}.regex`)) throw new Error("Regex import did not appear in regex list");
}

async function importWorldbook(suiteId: string): Promise<void> {
  await openMoreItem("世界书", 1412);
  await tapVisible("新建");
  await tapVisible("导入世界书");
  await selectGeneratedFile(suiteId, "worldbook.json");
  const visible = await texts();
  if (!visible.includes(`${suiteId}.worldbook`)) throw new Error("Worldbook import did not appear in worldbook list");
}

async function importPreset(suiteId: string): Promise<void> {
  await openMoreItem("预设", 1265);
  await tapVisible("新建");
  await tapVisible("导入预设");
  await selectGeneratedFile(suiteId, "preset.json");
  const visible = await texts();
  if (!visible.includes(`${suiteId}.preset`)) throw new Error("Preset import did not appear in preset list");
}

async function importCharacter(suiteId: string): Promise<void> {
  await openMoreItem("角色", 460);
  await tapVisible("新建");
  await tapVisible("从文件导入角色卡");
  await tapVisible("导入角色卡", 1200, { preferClickable: true });
  await tapVisible("文件", 1200, { exactContentDesc: true, preferClickable: true });
  await waitForDocumentsUiToOpen();
  await selectGeneratedFile(suiteId, "card.json");
  await tapVisible("导入角色", 1800);
  const maybeDialog = await texts();
  if (maybeDialog.includes("新角色")) {
    await tapVisible("新角色", 1800, { exactText: true });
  }
  const visible = await texts();
  if (!visible.includes(`${suiteId} 角色`)) throw new Error("Character import did not appear in character list");
}

function arDirectPayload(): string {
  const ok = "String.fromCharCode(84,65,86,79,95,74,83,95,65,80,73,95,79,75)";
  const noTavo = "String.fromCharCode(78,79,95,84,65,86,79)";
  const jsErr = "String.fromCharCode(74,83,95,69,82,82)";
  const key = "String.fromCharCode(100,101,118,107,105,116,46,97,114,68,105,114,101,99,116)";
  const value = "String.fromCharCode(111,107)";
  const scope = "String.fromCharCode(99,104,97,116)";
  return `<div id=codexar>pending</div><script>(function(){try{if(window.tavo&&tavo.set){tavo.set(${key},${value},${scope});codexar.textContent=${ok}}else{codexar.textContent=${noTavo}}}catch(e){codexar.textContent=${jsErr}}})()</script>`;
}

async function runArDirectProbe(suiteId: string): Promise<void> {
  await openMoreItem("角色", 460);
  await scrollToTop(2);
  await tapVisible(`${suiteId} 角色`, 1200, { preferClickable: true });
  await tapVisible("开始新聊天", 2200, { preferClickable: true });
  await focusChatInput();
  await clearFocusedText();
  await inputText(arDirectPayload());
  await sleep(700);
  await tapChatSendButton();
  const visible = await texts();
  if (visible.includes("TAVO_JS_API_OK")) return;
  if (visible.includes("NO_TAVO")) throw new Error("AR script ran, but window.tavo API was not exposed");
  if (visible.includes("JS_ERR")) throw new Error("AR script ran but threw while calling tavo.set");
  throw new Error("AR direct script did not produce the expected visible TAVO_JS_API_OK marker");
}

function compactHtmlForInput(html: string): string {
  return html.replace(/\s+/g, " ").trim();
}

async function runArWidgetProbe(built: BuiltAssets): Promise<void> {
  const file = built.files.find((item) => item.kind === "ar-widget-html");
  if (!file) throw new Error("Generated AR widget HTML is missing from built assets");
  const html = compactHtmlForInput(await readFile(file.path, "utf8"));
  await settleChatAfterDirectProbe();
  await waitForVisibleText(`${built.suiteId} 角色`, 10000);
  await focusChatInput();
  await inputText(html);
  await waitForUiXmlText("AR_WIDGET_PENDING", 15000);
  await tapChatSendButton();
  const visible = await waitForVisibleText("AR_WIDGET_OK", 15000);
  if (visible.includes("NO_TAVO_WIDGET")) throw new Error("AR widget rendered, but window.tavo API was not exposed");
  if (visible.includes("AR_WIDGET_ERR")) throw new Error("AR widget rendered but threw while calling tavo.set");
}

async function bindCurrentChatRegex(suiteId: string): Promise<void> {
  await openTavoReady();
  await waitForVisibleText(`${suiteId} 角色`, 10000);
  await tap(1017, 126, 900);
  await waitForVisibleText("聊天设定", 5000);
  await tapVisible("正则", 1000, { preferClickable: true });
  await scrollToTop(2);
  await tapVisible(`${suiteId}.regex`, 900, { preferClickable: true });
  await tapVisible("应用", 1000, { preferClickable: true });
  await waitForVisibleText("聊天设定", 5000);
  await back(1000);
  await waitForVisibleText(`${suiteId} 角色`, 10000);
}

async function runRegexJsProbe(suiteId: string): Promise<void> {
  await settleChatAfterDirectProbe();
  await waitForVisibleText(`${suiteId} 角色`, 10000);
  await bindCurrentChatRegex(suiteId);
  const beforeInput = await texts();
  if (beforeInput.includes("REGEX_JS_OK")) return;
  await focusChatInput();
  await clearFocusedText();
  await inputText("CODEX_DEVKIT_REGEX_JS");
  await waitForUiXmlText("CODEX_DEVKIT_REGEX_JS", 15000);
  await tapChatSendButton();
  const visible = await waitForVisibleText("REGEX_JS_OK", 15000);
  if (visible.includes("NO_TAVO_REGEX")) throw new Error("Regex replacement rendered, but window.tavo API was not exposed");
  if (visible.includes("REGEX_JS_ERR")) throw new Error("Regex replacement rendered but threw while calling tavo.set");
}

function safeArtifactName(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

async function captureFailureArtifacts(name: string, screenshots: string, logs: string): Promise<string | undefined> {
  const baseName = safeArtifactName(name);
  const textFile = path.join(logs, `${baseName}.failure-texts.txt`);
  const shotFile = path.join(screenshots, `${baseName}.failure.png`);
  try {
    const visible = await texts();
    await writeFile(textFile, visible, "utf8");
    await run(tavoAdb, ["screenshot", shotFile], 45000);
    return shotFile;
  } catch {
    return undefined;
  }
}

async function step(name: string, fn: () => Promise<ProbeStepResult>, artifacts?: { screenshots: string; logs: string }): Promise<ProbeStep> {
  try {
    const result = await fn();
    return { name, status: result.status ?? "verified", detail: result.detail, artifact: result.artifact };
  } catch (error) {
    const artifact = artifacts ? await captureFailureArtifacts(name, artifacts.screenshots, artifacts.logs) : undefined;
    return {
      name,
      status: "failed",
      detail: error instanceof Error ? error.message : String(error),
      artifact
    };
  }
}

async function fetchModels(baseUrl: string, apiKey: string): Promise<string[]> {
  const response = await fetch(`${baseUrl.replace(/\/$/, "")}/models`, {
    headers: { Authorization: `Bearer ${apiKey}` }
  });
  if (!response.ok) throw new Error(`models request failed: ${response.status}`);
  const json = await response.json() as { data?: Array<{ id?: string }> };
  return (json.data ?? []).map((item) => item.id).filter((id): id is string => Boolean(id));
}

async function chatProbe(baseUrl: string, apiKey: string, model: string): Promise<string> {
  const response = await fetch(`${baseUrl.replace(/\/$/, "")}/chat/completions`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      model,
      messages: [{ role: "user", content: "请回复一句中文，说明 Tavo Dev Kit 端点连通。" }],
      max_tokens: 1024,
      temperature: 0
    })
  });
  if (!response.ok) throw new Error(`chat request failed: ${response.status}`);
  const json = await response.json() as {
    model?: string;
    choices?: Array<{ message?: { content?: string }; finish_reason?: string }>;
    usage?: unknown;
  };
  return redact(JSON.stringify({
    model: json.model,
    contentPreview: json.choices?.[0]?.message?.content?.slice(0, 160) ?? "",
    finishReason: json.choices?.[0]?.finish_reason,
    usage: json.usage
  }, null, 2));
}

export async function runAndroidProbe(): Promise<{ reportPath: string; steps: ProbeStep[] }> {
  loadDotenv({ path: ".env.local" });
  loadDotenv();
  const reportDir = path.resolve("reports/latest");
  const screenshots = path.join(reportDir, "screenshots");
  const logs = path.join(reportDir, "logs");
  await rm(reportDir, { recursive: true, force: true });
  await mkdir(screenshots, { recursive: true });
  await mkdir(logs, { recursive: true });

  const built = await buildTavoAssets();
  const remoteDir = `/sdcard/Download/${built.suiteId}`;
  const steps: ProbeStep[] = [];
  const artifactContext = { screenshots, logs };

  steps.push(await step("android baseline", async () => {
    const status = await run(tavoAdb, ["status"]);
    const file = path.join(logs, "status.txt");
    await writeFile(file, status.stdout + status.stderr, "utf8");
    if (!status.stdout.includes("versionName=0.81.3")) {
      return { detail: "Tavo is reachable, but version differs from 0.81.3 baseline", artifact: file };
    }
    return { detail: "Tavo emulator reachable; versionName=0.81.3", artifact: file };
  }, artifactContext));

  steps.push(await step("foreground and screenshot", async () => {
    await openTavoReady();
    const shot = path.join(screenshots, "baseline.png");
    await run(tavoAdb, ["screenshot", shot]);
    const texts = await run(tavoAdb, ["texts"], 45000);
    const textFile = path.join(logs, "visible-texts.txt");
    await writeFile(textFile, texts.stdout, "utf8");
    return { detail: `Captured baseline screenshot and ${texts.stdout.trim().split(/\n+/).filter(Boolean).length} visible text lines`, artifact: shot };
  }, artifactContext));

  steps.push(await step("push import assets", async () => {
    await run("adb", ["-s", process.env.TAVO_DEVICE ?? "emulator-5554", "shell", "mkdir", "-p", remoteDir]);
    for (const file of built.files) {
      if (!file.path.endsWith(".json") && !file.path.endsWith(".html")) continue;
      await run("adb", ["-s", process.env.TAVO_DEVICE ?? "emulator-5554", "push", file.path, `${remoteDir}/`], 60000);
    }
    await scanMedia(remoteDir);
    return { detail: `Pushed ${built.files.length} generated files to ${remoteDir}` };
  }, artifactContext));

  steps.push(await step("ui import regex", async () => {
    await importRegex(built.suiteId);
    const shot = path.join(screenshots, "import-regex.png");
    await run(tavoAdb, ["screenshot", shot]);
    return { detail: "Imported generated regex JSON through Tavo UI and saved it", artifact: shot };
  }, artifactContext));

  steps.push(await step("ui import worldbook", async () => {
    await importWorldbook(built.suiteId);
    const shot = path.join(screenshots, "import-worldbook.png");
    await run(tavoAdb, ["screenshot", shot]);
    return { detail: "Imported generated worldbook JSON through Tavo UI", artifact: shot };
  }, artifactContext));

  steps.push(await step("ui import preset", async () => {
    await importPreset(built.suiteId);
    const shot = path.join(screenshots, "import-preset.png");
    await run(tavoAdb, ["screenshot", shot]);
    return { detail: "Imported generated preset JSON through Tavo UI", artifact: shot };
  }, artifactContext));

  steps.push(await step("ui import character", async () => {
    await importCharacter(built.suiteId);
    const shot = path.join(screenshots, "import-character.png");
    await run(tavoAdb, ["screenshot", shot]);
    return { detail: "Imported generated character card JSON through Tavo UI", artifact: shot };
  }, artifactContext));

  steps.push(await step("ar direct js/api execution", async () => {
    await runArDirectProbe(built.suiteId);
    const shot = path.join(screenshots, "ar-direct-js-api.png");
    await run(tavoAdb, ["screenshot", shot]);
    return { detail: "Started imported character chat and verified AR JavaScript can call window.tavo/tavo.set", artifact: shot };
  }, artifactContext));

  steps.push(await step("ar widget js/api execution", async () => {
    await runArWidgetProbe(built);
    const shot = path.join(screenshots, "ar-widget-js-api.png");
    await run(tavoAdb, ["screenshot", shot]);
    return { detail: "Sent generated AR widget HTML and verified visible AR_WIDGET_OK marker", artifact: shot };
  }, artifactContext));

  steps.push(await step("regex js execution", async () => {
    await runRegexJsProbe(built.suiteId);
    const shot = path.join(screenshots, "regex-js-execution.png");
    await run(tavoAdb, ["screenshot", shot]);
    return { detail: "Bound the imported regex group to the current chat, then verified CODEX_DEVKIT_REGEX_JS was replaced with executable JS that produced REGEX_JS_OK", artifact: shot };
  }, artifactContext));

  steps.push(await step("model list probe", async () => {
    const base = process.env.TAVO_OPENAI_BASE_URL;
    const key = process.env.TAVO_OPENAI_API_KEY;
    const model = process.env.TAVO_OPENAI_MODEL ?? "glm-5.1";
    if (!base || !key) return { status: "skipped", detail: "TAVO_OPENAI_BASE_URL or TAVO_OPENAI_API_KEY not set" };
    const models = await fetchModels(base, key);
    const file = path.join(logs, "models.txt");
    await writeFile(file, models.join("\n"), "utf8");
    if (!models.includes(model)) throw new Error(`Expected model ${model} not found. Available GLM-ish models: ${models.filter((id) => /glm/i.test(id)).join(", ")}`);
    return { detail: `Found model ${model}`, artifact: file };
  }, artifactContext));

  steps.push(await step("chat endpoint probe", async () => {
    const base = process.env.TAVO_OPENAI_BASE_URL;
    const key = process.env.TAVO_OPENAI_API_KEY;
    const model = process.env.TAVO_OPENAI_MODEL ?? "glm-5.1";
    if (!base || !key) return { status: "skipped", detail: "TAVO_OPENAI_BASE_URL or TAVO_OPENAI_API_KEY not set" };
    const result = await chatProbe(base, key, model);
    const file = path.join(logs, "chat-probe.json");
    await writeFile(file, result, "utf8");
    return { detail: `Chat endpoint responded for ${model}`, artifact: file };
  }, artifactContext));

  const failed = steps.filter((item) => item.status === "failed");
  const report = {
    suiteId: built.suiteId,
    generatedAt: new Date().toISOString(),
    remoteDir,
    assetDir: built.outDir,
    summary: {
      verified: steps.filter((item) => item.status === "verified").length,
      failed: failed.length,
      blocked: steps.filter((item) => item.status === "blocked").length,
      skipped: steps.filter((item) => item.status === "skipped").length
    },
    steps
  };
  await ensureDir(reportDir);
  const reportPath = path.join(reportDir, "probe-report.json");
  await writeJson(reportPath, report);
  if (failed.length > 0) {
    throw new Error(`Android probe has failed steps. See ${reportPath}`);
  }
  return { reportPath, steps };
}
