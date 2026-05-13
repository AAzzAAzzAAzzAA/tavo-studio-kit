#!/usr/bin/env node
import { buildTavoAssets } from "./assets.js";
import { runAndroidProbe } from "./androidProbe.js";
import { buildArWidgetFiles } from "./widget.js";

async function main(): Promise<void> {
  const command = process.argv[2] ?? "help";
  if (command === "build:assets") {
    const built = await buildTavoAssets();
    console.log(`Built ${built.files.length} Tavo import assets in ${built.outDir}`);
    console.log(`Suite: ${built.suiteId}`);
    return;
  }
  if (command === "build:widget") {
    const built = await buildArWidgetFiles();
    console.log(`Built AR widget in ${built.outDir}`);
    console.log(`HTML: ${built.htmlPath}`);
    console.log(`Regex: ${built.regexPath}`);
    return;
  }
  if (command === "probe:android") {
    const result = await runAndroidProbe();
    console.log(`Android probe report: ${result.reportPath}`);
    for (const step of result.steps) {
      console.log(`${step.status.toUpperCase()} ${step.name}: ${step.detail}`);
    }
    return;
  }
  console.log(`Usage: tavo-dev-kit <command>

Commands:
  build:assets    Generate Tavo import JSON files
  build:widget    Build standalone AR widget HTML and regex draft
  probe:android   Run emulator baseline, push assets, and endpoint probes
`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
