#!/usr/bin/env python3
"""Small JSON-RPC client for the Tavo MCP server."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any


def load_endpoint(path: str) -> dict[str, str]:
    p = Path(path).expanduser()
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {
        "url": data.get("url") or data.get("lan_url") or data.get("local_url") or "",
        "auth": data.get("auth") or data.get("authorization") or data.get("token") or "",
    }


def rpc(url: str, auth: str, method: str, params: dict[str, Any], request_id: int = 1) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = auth if auth.lower().startswith("bearer ") else f"Bearer {auth}"
    payload = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key.lower() in {"authorization", "auth", "token", "bearer", "api_key", "apikey"}:
                result[key] = "<redacted>"
            else:
                result[key] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str) and value.lower().startswith("bearer "):
        return "Bearer <redacted>"
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Call Tavo MCP JSON-RPC.")
    parser.add_argument("--endpoint-json", default="/tmp/tavo_mcp_endpoint.json")
    parser.add_argument("--url", default=os.environ.get("TAVO_MCP_URL", ""))
    parser.add_argument("--auth", default=os.environ.get("TAVO_MCP_AUTH", ""))
    parser.add_argument("--method", default="initialize")
    parser.add_argument("--params-json", default="")
    parser.add_argument("--tool", default="", help="Call a Tavo tool through JSON-RPC tools/call.")
    parser.add_argument("--arguments-json", default="{}", help="Arguments for --tool.")
    parser.add_argument("--output", default="")
    parser.add_argument("--raw", action="store_true", help="Do not redact output.")
    args = parser.parse_args()

    endpoint = load_endpoint(args.endpoint_json)
    url = args.url or endpoint.get("url", "")
    auth = args.auth or endpoint.get("auth", "")
    if not url:
        print("No MCP URL found. Provide --url, TAVO_MCP_URL, or --endpoint-json.", file=sys.stderr)
        return 2

    if args.tool:
        method = "tools/call"
        params = {"name": args.tool, "arguments": json.loads(args.arguments_json)}
    else:
        method = args.method
        params = json.loads(args.params_json) if args.params_json else {}
        if method == "initialize" and not params:
            params = {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "codex-tavo-mcp-client", "version": "0.1"}}

    result = rpc(url, auth, method, params)
    output = result if args.raw else redact(result)
    text = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        path = Path(args.output).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if "error" not in result else 1


if __name__ == "__main__":
    raise SystemExit(main())
