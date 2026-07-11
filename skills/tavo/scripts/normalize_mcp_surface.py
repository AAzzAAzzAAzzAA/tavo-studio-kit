#!/usr/bin/env python3
"""Normalize a redacted Tavo MCP surface dump into a compact index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def result_of(data: dict[str, Any], method: str) -> dict[str, Any]:
    call = (data.get("calls") or {}).get(method) or {}
    return call.get("result") or {}


def risk_for_tool(tool: dict[str, Any]) -> str:
    name = str(tool.get("name", "")).lower()
    if any(word in name for word in ["delete", "remove", "clear", "restore"]):
        return "destructive"
    if any(word in name for word in ["create", "update", "import", "set", "send", "package", "install"]):
        return "write"
    if any(word in name for word in ["get", "list", "find", "status", "count", "validate"]):
        return "read-or-validate"
    return "unknown"


def normalize(data: dict[str, Any]) -> dict[str, Any]:
    tools = []
    for tool in result_of(data, "tools/list").get("tools", []):
        schema = tool.get("inputSchema") or {}
        props = schema.get("properties") if isinstance(schema, dict) else {}
        tools.append(
            {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "risk": risk_for_tool(tool),
                "argumentKeys": sorted(props) if isinstance(props, dict) else [],
                "hasDryRunArgument": isinstance(props, dict) and "dryRun" in props,
            }
        )
    resources = [
        {
            "uri": resource.get("uri", ""),
            "name": resource.get("name", ""),
            "mimeType": resource.get("mimeType", ""),
        }
        for resource in result_of(data, "resources/list").get("resources", [])
    ]
    templates = [
        {
            "uriTemplate": item.get("uriTemplate", ""),
            "name": item.get("name", ""),
            "mimeType": item.get("mimeType", ""),
        }
        for item in result_of(data, "resources/templates/list").get("resourceTemplates", [])
    ]
    return {
        "schemaVersion": "0.1.0",
        "dumpedAt": data.get("dumped_at", ""),
        "serverInfo": (result_of(data, "initialize").get("serverInfo") or {}),
        "summary": data.get("summary", {}),
        "tools": sorted(tools, key=lambda item: item["name"]),
        "resources": sorted(resources, key=lambda item: item["uri"]),
        "resourceTemplates": sorted(templates, key=lambda item: item["uriTemplate"]),
        "resourceReadStatus": {
            uri: "ok" if "result" in payload else "error"
            for uri, payload in sorted((data.get("resource_reads") or {}).items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize Tavo MCP surface dump.")
    parser.add_argument("mcp_surface")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    path = Path(args.mcp_surface).expanduser()
    data = json.loads(path.read_text(encoding="utf-8"))
    result = normalize(data)
    output = Path(args.output).expanduser() if args.output else path.with_name("mcp_surface_index.json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"mcp_surface_index={output}")
    print(f"tools={len(result['tools'])}")
    print(f"resources={len(result['resources'])}")
    print(f"templates={len(result['resourceTemplates'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
