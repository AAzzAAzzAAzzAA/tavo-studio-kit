import { spawnSync } from "node:child_process";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import process from "node:process";

const root = process.cwd();
const pkg = JSON.parse(readFileSync(path.join(root, "package.json"), "utf8"));
const readme = readFileSync(path.join(root, "README.md"), "utf8");

const failures = [];
const warnings = [];

function fail(message) {
  failures.push(message);
}

function warn(message) {
  warnings.push(message);
}

if (!pkg.license || pkg.license === "UNLICENSED") {
  fail("package.json must declare a shareable license");
}

if (!readme.toLowerCase().includes("not an official tavo sdk")) {
  fail("README must clearly state this is not an official Tavo SDK");
}

const ignoredDirs = new Set([".git", "node_modules", "dist", "reports"]);
const ignoredFiles = new Set([".env.local", ".env"]);
const secretPatterns = [
  /sk-[A-Za-z0-9_-]{20,}/g,
  /Bearer\s+[A-Za-z0-9._-]{20,}/g,
  /(api[_-]?key|authorization)\s*[:=]\s*["']?[^"'\s]{20,}/gi
];
const allowedSecretPlaceholders = [
  "sk-replace-me",
  "sk-..."
];

function walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    const rel = path.relative(root, full);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      if (!ignoredDirs.has(entry)) {
        walk(full);
      }
      continue;
    }
    if (ignoredFiles.has(entry) || stat.size > 1_000_000) {
      continue;
    }
    const text = readFileSync(full, "utf8");
    for (const pattern of secretPatterns) {
      pattern.lastIndex = 0;
      for (const match of text.matchAll(pattern)) {
        const value = match[0];
        if (!allowedSecretPlaceholders.some((placeholder) => value.includes(placeholder))) {
          fail(`possible secret in ${rel}: ${value.slice(0, 24)}...`);
        }
      }
    }
  }
}

walk(root);

if (statExists(path.join(root, ".env.local"))) {
  warn(".env.local exists locally; keep it untracked and rotate temporary keys before publishing");
}

const pack = spawnSync("npm", ["pack", "--dry-run", "--json"], {
  cwd: root,
  encoding: "utf8"
});

if (pack.status !== 0) {
  fail(`npm pack --dry-run failed: ${pack.stderr || pack.stdout}`);
} else {
  try {
    const data = JSON.parse(pack.stdout);
    const files = data[0]?.files?.map((file) => file.path) ?? [];
    const forbidden = files.filter((file) => (
      file.includes(".env.local") ||
      file.startsWith("reports/") ||
      file.startsWith("dist/tavo-import/") ||
      file.includes("node_modules/")
    ));
    if (forbidden.length > 0) {
      fail(`npm pack would include forbidden files: ${forbidden.join(", ")}`);
    }
    if (!files.includes("README.md")) {
      fail("npm pack would not include README.md");
    }
    if (!files.includes("LICENSE")) {
      fail("npm pack would not include LICENSE");
    }
    console.log(`npm pack dry-run ok: ${data[0]?.filename ?? "package"} (${data[0]?.size ?? "unknown"} bytes)`);
  } catch (error) {
    fail(`could not parse npm pack output: ${error instanceof Error ? error.message : String(error)}`);
  }
}

for (const message of warnings) {
  console.warn(`warning: ${message}`);
}

if (failures.length > 0) {
  for (const message of failures) {
    console.error(`release check failed: ${message}`);
  }
  process.exitCode = 1;
} else {
  console.log("release check passed");
}

function statExists(file) {
  try {
    statSync(file);
    return true;
  } catch {
    return false;
  }
}
