#!/usr/bin/env python3
"""Append or update a claim in assets/evidence/registry.json."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Record a Tavo validation claim.")
    parser.add_argument("--registry", default=str(Path(__file__).resolve().parents[1] / "assets/evidence/registry.json"))
    parser.add_argument("--claim-id", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--verdict", required=True)
    parser.add_argument("--evidence-tier", required=True)
    parser.add_argument("--official-source", default="")
    parser.add_argument("--mcp-source", default="")
    parser.add_argument("--live-artifact", default="")
    parser.add_argument("--app-version", default="")
    parser.add_argument("--retention", default="leave-in-place")
    parser.add_argument("--staleness-policy", required=True)
    parser.add_argument("--notes", required=True)
    args = parser.parse_args()

    path = Path(args.registry).expanduser()
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schemaVersion": "0.1.0", "claims": []}
    claims = data.setdefault("claims", [])
    claim = {
        "claim_id": args.claim_id,
        "topic": args.topic,
        "verdict": args.verdict,
        "evidence_tier": args.evidence_tier,
        "official_source": args.official_source,
        "mcp_source": args.mcp_source,
        "live_artifact": args.live_artifact,
        "app_version": args.app_version,
        "last_verified": dt.date.today().isoformat(),
        "retention": args.retention,
        "staleness_policy": args.staleness_policy,
        "notes": args.notes,
    }
    replaced = False
    for index, existing in enumerate(claims):
        if existing.get("claim_id") == args.claim_id:
            claims[index] = claim
            replaced = True
            break
    if not replaced:
        claims.append(claim)
    data["updatedAt"] = dt.date.today().isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"registry={path}")
    print(f"claim_id={args.claim_id}")
    print(f"updated={str(replaced).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
