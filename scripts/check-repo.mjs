import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import process from "node:process";

const root = process.cwd();
const failures = [];

const requiredFiles = [
  "README.md",
  "LICENSE",
  "skills/tavo-studio/SKILL.md",
  "dev-kit/package.json",
  "dev-kit/src/index.ts"
];

for (const file of requiredFiles) {
  if (!exists(path.join(root, file))) {
    failures.push(`missing required file: ${file}`);
  }
}

const rootReadme = readText("README.md");
if (!rootReadme.includes("skills/tavo-studio")) {
  failures.push("README should present skills/tavo-studio as the main entry");
}
if (!rootReadme.includes("dev-kit")) {
  failures.push("README should mention dev-kit as the auxiliary validation tool");
}

const skill = readText("skills/tavo-studio/SKILL.md");
if (!skill.includes("dev-kit/")) {
  failures.push("tavo-studio skill should point to the bundled dev-kit");
}

const ignoredDirs = new Set([".git", "node_modules", "dist", "reports"]);
const ignoredFiles = new Set([".env", ".env.local"]);
const allowedPlaceholders = ["sk-replace-me", "sk-..."];
const privatePatterns = [
  { name: "private absolute path", pattern: /\/Users\/alex\b/g },
  { name: "generic macOS private path", pattern: /\/Users\/[A-Za-z0-9._-]+\/(?:Documents|Desktop|Downloads)\b/g },
  { name: "OpenAI-style secret", pattern: /sk-[A-Za-z0-9_-]{20,}/g },
  { name: "bearer token", pattern: /Bearer\s+[A-Za-z0-9._-]{20,}/g },
  { name: "inline API key", pattern: /(api[_-]?key|authorization)\s*[:=]\s*["']?[^"'\s]{20,}/gi }
];

walk(root);

if (failures.length > 0) {
  for (const failure of failures) {
    console.error(`repo check failed: ${failure}`);
  }
  process.exitCode = 1;
} else {
  console.log("repo check passed");
}

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
    for (const { name, pattern } of privatePatterns) {
      pattern.lastIndex = 0;
      for (const match of text.matchAll(pattern)) {
        const value = match[0];
        if (allowedPlaceholders.some((placeholder) => value.includes(placeholder))) {
          continue;
        }
        failures.push(`${name} in ${rel}: ${value.slice(0, 48)}...`);
      }
    }
  }
}

function readText(file) {
  const full = path.join(root, file);
  if (!exists(full)) return "";
  return readFileSync(full, "utf8");
}

function exists(file) {
  try {
    statSync(file);
    return true;
  } catch {
    return false;
  }
}
