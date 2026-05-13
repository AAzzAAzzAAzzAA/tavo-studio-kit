import { spawnSync } from "node:child_process";
import { mkdir, rm } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { readFileSync } from "node:fs";

const root = process.cwd();
const pkg = JSON.parse(readFileSync(path.join(root, "package.json"), "utf8"));
const outDir = path.join(root, "dist", "packages");
const zipPath = path.join(outDir, `${pkg.name}-${pkg.version}.zip`);

const include = [
  "package.json",
  "package-lock.json",
  "README.md",
  "LICENSE",
  "CONTRIBUTING.md",
  "SECURITY.md",
  ".env.example",
  ".gitignore",
  "tsconfig.json",
  "tsconfig.build.json",
  "vitest.config.ts",
  "src",
  "tests",
  "examples",
  "dev",
  "templates",
  "docs",
  "scripts",
  ".vscode",
  "jsconfig.json",
  "dist/lib",
  "dist/widgets"
];

const exclude = [
  "node_modules/*",
  ".env.local",
  "reports/*",
  "dist/tavo-import/*",
  "dist/packages/*",
  "*.log",
  ".DS_Store"
];

await mkdir(outDir, { recursive: true });
await rm(zipPath, { force: true });

const args = [
  "-r",
  "-X",
  zipPath,
  ...include,
  ...exclude.flatMap((pattern) => ["-x", pattern])
];

const result = spawnSync("zip", args, {
  cwd: root,
  stdio: "inherit"
});

if (result.status !== 0) {
  throw new Error(`zip failed with status ${result.status ?? "unknown"}`);
}

console.log(zipPath);
