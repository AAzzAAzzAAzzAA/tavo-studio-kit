#!/usr/bin/env python3
"""Deterministic OpenAI-compatible fixture for Tavo 0.92 generation hooks.

The fixture never contacts an upstream provider. It exists only to prove which
request body Tavo sends and to exercise JSON, SSE, slow-stream, HTTP-error, and
protocol-error terminal paths. Captures are credential-redacted and written as
mode-0600 files inside a mode-0700 directory.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import signal
import stat
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


MAX_REQUEST_BYTES = 8 * 1024 * 1024
SUPPORTED_POST_PATHS = {"/chat/completions", "/v1/chat/completions"}
SCENARIO_PATTERN = re.compile(r"\[TAVO_FIXTURE_SCENARIO:([a-z0-9_-]+)\]")
SCENARIOS = frozenset(
    {
        "normal",
        "http500",
        "protocol_error",
        "slow_stream",
        "slow_stream_before_first",
        "slow_stream_after_first",
    }
)
SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(?:\b(?:sk|rk|pk)-[A-Za-z0-9_-]{12,}\b|\btavo-cap-[A-Za-z0-9_-]{8,}\b)"
)
SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "bearer",
        "client_secret",
        "cookie",
        "key",
        "password",
        "proxy_authorization",
        "refresh_token",
        "secret",
        "token",
        "x_api_key",
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9_]", "_", key.lower()).strip("_")
    return bool(
        normalized in SENSITIVE_KEYS
        or normalized.endswith("_token")
        or normalized.endswith("_secret")
        or normalized.endswith("_password")
        or normalized.endswith("_credential")
    )


def redact_text(value: str) -> str:
    if re.match(r"^(?:bearer|basic)\s+", value, re.IGNORECASE):
        return value.split(" ", 1)[0] + " <redacted>"
    return SECRET_VALUE_PATTERN.sub("<redacted-secret>", value)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "<redacted>" if sensitive_key(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(redact(value), ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, path)
    path.chmod(0o600)


def read_secret_file(path: Path, *, delete_after_read: bool = False) -> str:
    if path.is_symlink():
        raise ValueError(f"Secret file cannot be a symlink: {path}")
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"Secret path must be a regular file: {path}")
    if metadata.st_mode & 0o077:
        raise ValueError(f"Secret file must not be readable or writable by group/other: {path}")
    value = path.read_text(encoding="utf-8").rstrip("\r\n")
    if not value or "\n" in value or "\r" in value or len(value) > 8192:
        raise ValueError(f"Secret file must contain exactly one bounded line: {path}")
    if delete_after_read:
        path.unlink()
    return value


def canonical_hash(value: Any) -> str:
    raw = json.dumps(redact(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def iter_text(value: Any):
    if isinstance(value, dict):
        for item in value.values():
            yield from iter_text(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_text(item)
    elif isinstance(value, str):
        yield value


def request_scenario(payload: Any) -> str:
    found: set[str] = set()
    for text in iter_text(payload):
        found.update(SCENARIO_PATTERN.findall(text))
    unknown = sorted(found - SCENARIOS)
    if unknown:
        raise ValueError(f"Unknown fixture scenario: {unknown[0]}")
    if len(found) > 1:
        raise ValueError("Exactly zero or one fixture scenario marker is allowed")
    return next(iter(found), "normal")


@dataclass(frozen=True)
class FixtureConfig:
    capture_dir: Path
    client_key: str
    model: str = "tavo-092-fixture"
    allowed_clients: frozenset[str] = frozenset({"127.0.0.1", "::1"})
    slow_chunk_seconds: float = 0.15


class CaptureStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self._lock = threading.Lock()
        self._sequence = 0

    def write(self, record: dict[str, Any]) -> Path:
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
        path = self.root / f"{sequence:06d}-{record['requestId']}.json"
        atomic_json(path, record)
        return path


class FixtureServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], config: FixtureConfig) -> None:
        self.config = config
        self.store = CaptureStore(config.capture_dir)
        super().__init__(address, FixtureHandler)


class FixtureHandler(BaseHTTPRequestHandler):
    server: FixtureServer
    protocol_version = "HTTP/1.1"
    server_version = "TavoGenerationFixture/1.0"

    def log_message(self, _fmt: str, *_args: object) -> None:
        return

    def _allowed_client(self) -> bool:
        return self.client_address[0] in self.server.config.allowed_clients

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.config.client_key}"
        return bool(self.server.config.client_key and hmac.compare_digest(header, expected))

    def _json(self, status: int, payload: Any) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(encoded)
        self.close_connection = True

    def _reject_if_needed(self, *, require_auth: bool) -> bool:
        if not self._allowed_client():
            self._json(403, {"error": {"code": "fixture_client_denied", "message": "client denied"}})
            return True
        if require_auth and not self._authorized():
            self._json(401, {"error": {"code": "fixture_unauthorized", "message": "unauthorized"}})
            return True
        return False

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            if self._reject_if_needed(require_auth=False):
                return
            self._json(200, {"ok": True, "model": self.server.config.model})
            return
        if self.path in {"/models", "/v1/models"}:
            if self._reject_if_needed(require_auth=True):
                return
            self._json(
                200,
                {
                    "object": "list",
                    "data": [{"id": self.server.config.model, "object": "model", "owned_by": "fixture"}],
                },
            )
            return
        self._json(404, {"error": {"code": "fixture_not_found", "message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in SUPPORTED_POST_PATHS:
            self._json(404, {"error": {"code": "fixture_not_found", "message": "not found"}})
            return
        if self._reject_if_needed(require_auth=True):
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_REQUEST_BYTES:
            self._json(413, {"error": {"code": "fixture_body_size", "message": "invalid body size"}})
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("request must be an object")
            scenario = request_scenario(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            self._json(400, {"error": {"code": "fixture_invalid_request", "message": str(error)}})
            return

        request_id = uuid.uuid4().hex
        request_hash = canonical_hash(payload)
        record = {
            "schemaVersion": 1,
            "requestId": request_id,
            "receivedAt": utc_now(),
            "client": self.client_address[0],
            "path": self.path,
            "scenario": scenario,
            "requestHash": request_hash,
            "request": {
                "headers": {
                    "Authorization": "<redacted>",
                    "Content-Type": self.headers.get("Content-Type"),
                },
                "body": payload,
            },
        }

        if scenario == "http500":
            record["response"] = {"status": 500, "format": "json", "scenario": scenario}
            self.server.store.write(record)
            self._json(
                500,
                {"error": {"code": "fixture_http_500", "type": "fixture_error", "message": "fixture HTTP 500"}},
            )
            return
        if scenario == "protocol_error":
            record["response"] = {
                "status": 200,
                "format": "invalid-openai-json",
                "scenario": scenario,
            }
            self.server.store.write(record)
            self._json(200, {"fixtureInvalidProtocol": True, "requestId": request_id})
            return

        response_text = f"TAVO_092_FIXTURE_OK::{request_hash[:20]}"
        stream = bool(payload.get("stream"))
        slow_scenarios = {
            "slow_stream",
            "slow_stream_before_first",
            "slow_stream_after_first",
        }
        if scenario in slow_scenarios and not stream:
            time.sleep(self.server.config.slow_chunk_seconds)
        stream_timing = {
            "normal": "immediate",
            "slow_stream": "after-each-content-chunk",
            "slow_stream_before_first": "before-first-content-chunk",
            "slow_stream_after_first": "after-first-content-chunk",
        }[scenario]
        record["response"] = {
            "status": 200,
            "format": "sse" if stream else "json",
            "scenario": scenario,
            "streamTiming": stream_timing if stream else (
                "single-response-delay" if scenario in slow_scenarios else "immediate"
            ),
            "text": response_text,
        }
        if scenario in slow_scenarios:
            record["response"]["slowChunkSeconds"] = self.server.config.slow_chunk_seconds
        self.server.store.write(record)
        if stream:
            self._stream_response(request_id, response_text, scenario=scenario)
            return
        self._json(
            200,
            {
                "id": f"chatcmpl-{request_id}",
                "object": "chat.completion",
                "created": 0,
                "model": self.server.config.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": response_text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    def _stream_response(self, request_id: str, text: str, *, scenario: str) -> None:
        chunks = [text[: len(text) // 2], text[len(text) // 2 :]]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            if scenario == "slow_stream_before_first":
                time.sleep(self.server.config.slow_chunk_seconds)
            for index, chunk in enumerate(chunks):
                event = {
                    "id": f"chatcmpl-{request_id}",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": self.server.config.model,
                    "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}],
                }
                self.wfile.write(("data: " + json.dumps(event, separators=(",", ":")) + "\n\n").encode("utf-8"))
                self.wfile.flush()
                if scenario == "slow_stream":
                    # Preserve the original slow-stream behavior: pause after
                    # every content chunk, including before the terminal event.
                    time.sleep(self.server.config.slow_chunk_seconds)
                elif scenario == "slow_stream_after_first" and index == 0:
                    # Emit exactly one content chunk before opening the
                    # deterministic post-first-token cancellation window.
                    time.sleep(self.server.config.slow_chunk_seconds)
            final = {
                "id": f"chatcmpl-{request_id}",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": self.server.config.model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            self.wfile.write(("data: " + json.dumps(final, separators=(",", ":")) + "\n\n").encode("utf-8"))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # A cancellation test is expected to close the client connection
            # inside either slow window. The request capture was already
            # persisted before streaming began, so no server traceback is
            # useful here.
            pass
        self.close_connection = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18792)
    parser.add_argument("--model", default="tavo-092-fixture")
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--client-key-file", type=Path, required=True)
    parser.add_argument("--delete-client-key-file", action="store_true")
    parser.add_argument("--allowed-client", action="append", default=[])
    parser.add_argument("--slow-chunk-seconds", type=float, default=0.15)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not (0 <= args.port <= 65535):
        raise SystemExit("--port must be between 0 and 65535")
    if not (0 <= args.slow_chunk_seconds <= 10):
        raise SystemExit("--slow-chunk-seconds must be between 0 and 10")
    allowed = frozenset(args.allowed_client or ([args.bind] if args.bind in {"127.0.0.1", "::1"} else []))
    if not allowed:
        raise SystemExit("Non-loopback bind requires at least one --allowed-client")
    key = read_secret_file(args.client_key_file, delete_after_read=args.delete_client_key_file)
    config = FixtureConfig(
        capture_dir=args.capture_dir.expanduser().resolve(),
        client_key=key,
        model=args.model,
        allowed_clients=allowed,
        slow_chunk_seconds=args.slow_chunk_seconds,
    )
    server = FixtureServer((args.bind, args.port), config)
    stop = threading.Event()

    def request_stop(_signum: int, _frame: Any) -> None:
        if not stop.is_set():
            stop.set()
            threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    host, port = server.server_address[:2]
    print(
        json.dumps(
            {
                "ok": True,
                "baseUrl": f"http://{host}:{port}/v1",
                "model": args.model,
                "captureDir": str(config.capture_dir),
                "allowedClients": sorted(allowed),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
