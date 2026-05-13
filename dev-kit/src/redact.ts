export function redact(text: string): string {
  return text
    .replace(/sk-[A-Za-z0-9_-]+/g, "[REDACTED_SK]")
    .replace(/vtx_[A-Za-z0-9_]+/g, "[REDACTED_VTX]")
    .replace(/(Bearer\s+)[A-Za-z0-9._~-]+/gi, "$1[REDACTED]");
}

