#!/usr/bin/env python3
"""Dump read-only Tavo MCP surface metadata.

Inputs can come from --url/--auth, environment variables TAVO_MCP_URL and
TAVO_MCP_AUTH, or an endpoint JSON file containing url/auth fields. Authorization
values are redacted in saved output.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


REQUESTED_PROTOCOL_VERSION = "2025-06-18"


READ_METHODS = [
    ("initialize", {"protocolVersion": REQUESTED_PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "codex-tavo-skill", "version": "0.2"}}),
    ("tools/list", {}),
    ("resources/list", {}),
    ("resources/templates/list", {}),
    ("prompts/list", {}),
]

DOC_RESOURCES = [
    "tavo://capabilities",
    "tavo://runtime",
    "tavo://docs/overview",
    "tavo://docs/tools",
    "tavo://docs/write-safety",
    "tavo://docs/macros",
    "tavo://docs/tavojs",
    "tavo://docs/plugins",
]

RESOURCE_READ_KEYWORDS = (
    "capabilities",
    "runtime",
    "docs",
    "schema",
    "schemas",
    "readme",
    "macros",
    "tavojs",
    "plugins",
)


def load_endpoint(path: Path | None) -> dict[str, str]:
    if not path or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "url": data.get("url") or data.get("lan_url") or data.get("local_url") or "",
        "auth": data.get("auth") or data.get("authorization") or data.get("token") or "",
    }


def rpc(url: str, auth: str, method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = auth if auth.lower().startswith("bearer ") else f"Bearer {auth}"
    payload = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def scrub_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urllib.parse.urlunparse((parsed.scheme, host, parsed.path, "", "", ""))


def redact_endpoint(url: str, auth: str) -> dict[str, str]:
    return {"url": scrub_url(url), "auth": "<redacted>" if auth else ""}


def resource_uris_from_list(call_result: dict[str, Any]) -> list[str]:
    resources = ((call_result.get("result") or {}).get("resources") or [])
    uris: list[str] = []
    for resource in resources:
        uri = resource.get("uri")
        if not isinstance(uri, str):
            continue
        lowered = uri.lower()
        if any(keyword in lowered for keyword in RESOURCE_READ_KEYWORDS):
            uris.append(uri)
    return uris


def call_has_result(call: dict[str, Any]) -> bool:
    return isinstance(call, dict) and isinstance(call.get("result"), dict)


def summarize_surface(result: dict[str, Any]) -> dict[str, Any]:
    calls = result.get("calls", {})
    initialize = calls.get("initialize", {})
    tools = ((calls.get("tools/list", {}).get("result") or {}).get("tools") or [])
    resources = ((calls.get("resources/list", {}).get("result") or {}).get("resources") or [])
    templates = ((calls.get("resources/templates/list", {}).get("result") or {}).get("resourceTemplates") or [])
    prompts = ((calls.get("prompts/list", {}).get("result") or {}).get("prompts") or [])
    docs_read = {
        uri: "ok" if call_has_result(call) else "error"
        for uri, call in sorted((result.get("resource_reads") or {}).items())
    }
    server_info = (initialize.get("result") or {}).get("serverInfo") if call_has_result(initialize) else None
    negotiated_protocol = (initialize.get("result") or {}).get("protocolVersion") if call_has_result(initialize) else None
    status_call = result.get("status_tool_call") or {}
    return {
        "serverInfo": server_info or {},
        "requestedProtocolVersion": result.get("requested_protocol_version", ""),
        "negotiatedProtocolVersion": negotiated_protocol or "",
        "toolCount": len(tools),
        "resourceCount": len(resources),
        "resourceTemplateCount": len(templates),
        "promptCount": len(prompts),
        "failedCalls": sorted(method for method, call in calls.items() if not call_has_result(call)),
        "failedResourceReads": sorted(uri for uri, status in docs_read.items() if status == "error"),
        "statusToolCallOk": call_has_result(status_call),
        "docReadStatus": docs_read,
    }


def strict_failures(result: dict[str, Any]) -> list[str]:
    failures = [
        f"call:{method}"
        for method, _ in READ_METHODS
        if not call_has_result((result.get("calls") or {}).get(method, {}))
    ]
    failures.extend(
        f"resource:{uri}"
        for uri, call in sorted((result.get("resource_reads") or {}).items())
        if not call_has_result(call)
    )
    if not call_has_result(result.get("status_tool_call") or {}):
        failures.append("tool:tavo_status")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump read-only Tavo MCP surface.")
    parser.add_argument("--endpoint-json", default="/tmp/tavo_mcp_endpoint.json")
    parser.add_argument("--url", default=os.environ.get("TAVO_MCP_URL", ""))
    parser.add_argument("--auth", default=os.environ.get("TAVO_MCP_AUTH", ""))
    parser.add_argument("--output", default="")
    parser.add_argument("--require-initialize", action="store_true")
    parser.add_argument("--require-tools-list", action="store_true")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Require all five top-level reads, all selected documentation resources, and a read-only tavo_status tools/call.",
    )
    args = parser.parse_args()

    endpoint = load_endpoint(Path(args.endpoint_json).expanduser() if args.endpoint_json else None)
    url = args.url or endpoint.get("url", "")
    auth = args.auth or endpoint.get("auth", "")
    if not url:
        print("No MCP URL found. Provide --url, TAVO_MCP_URL, or --endpoint-json.", file=sys.stderr)
        return 2

    if args.output:
        output_dir = Path(args.output).expanduser()
    else:
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        output_dir = Path(f"/tmp/tavo-mcp-surface-{stamp}")
    output_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "dumped_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "requested_protocol_version": REQUESTED_PROTOCOL_VERSION,
        "endpoint": redact_endpoint(url, auth),
        "calls": {},
        "resource_reads": {},
        "status_tool_call": {},
    }

    next_id = 1
    for method, params in READ_METHODS:
        try:
            result["calls"][method] = rpc(url, auth, method, params, next_id)
        except Exception as exc:  # noqa: BLE001 - preserve diagnostic detail in artifact
            result["calls"][method] = {"error": str(exc)}
        next_id += 1

    dynamic_doc_uris = resource_uris_from_list(result["calls"].get("resources/list", {}))
    uris_to_read = []
    for uri in [*DOC_RESOURCES, *dynamic_doc_uris]:
        if uri not in uris_to_read:
            uris_to_read.append(uri)

    for uri in uris_to_read:
        try:
            result["resource_reads"][uri] = rpc(url, auth, "resources/read", {"uri": uri}, next_id)
        except Exception as exc:  # noqa: BLE001
            result["resource_reads"][uri] = {"error": str(exc)}
        next_id += 1

    if args.strict:
        try:
            result["status_tool_call"] = rpc(
                url,
                auth,
                "tools/call",
                {"name": "tavo_status", "arguments": {}},
                next_id,
            )
        except Exception as exc:  # noqa: BLE001 - preserve redacted diagnostic detail
            result["status_tool_call"] = {"error": str(exc)}

    result["summary"] = summarize_surface(result)
    output_path = output_dir / "mcp_surface.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"mcp_surface={output_path}")

    required_methods: set[str] = set()
    if args.require_initialize or args.strict:
        required_methods.add("initialize")
    if args.require_tools_list or args.strict:
        required_methods.add("tools/list")
    if args.strict:
        required_methods.update({"resources/list", "resources/templates/list", "prompts/list"})
    failed_required = [method for method in sorted(required_methods) if not call_has_result(result["calls"].get(method, {}))]
    if failed_required:
        print(f"required MCP calls failed: {', '.join(failed_required)}", file=sys.stderr)
        return 1
    if args.strict:
        failures = strict_failures(result)
        if failures:
            print(f"strict MCP gate failed: {', '.join(failures)}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
