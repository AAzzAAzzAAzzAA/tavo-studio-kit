#!/usr/bin/env python3
"""Capture and forward OpenAI-compatible requests without logging credentials."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import signal
import socket
import ssl
import stat
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_UPSTREAM_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_UPSTREAM_ERROR_BYTES = 4 * 1024 * 1024
MAX_CAPTURED_RESPONSE_EVENTS = 512
MAX_CAPTURED_RESPONSE_TEXT_BYTES = 2 * 1024 * 1024
EXACT_SENSITIVE_KEYS = {
    "api-key",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "bearer",
    "key",
    "password",
    "proxy-authorization",
    "set-cookie",
    "secret",
    "token",
    "x-api-key",
    "x-auth-token",
    "cookie",
}
SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(?:\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}\b|\btavo-cap-[A-Za-z0-9_-]{10,}\b|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
SUPPORTED_POST_PATHS = {
    "/chat/completions",
    "/completions",
    "/responses",
    "/v1/chat/completions",
    "/v1/completions",
    "/v1/responses",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, path)
    path.chmod(0o600)


def sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9_-]", "", key.lower())
    underscored = normalized.replace("-", "_")
    return bool(
        normalized in EXACT_SENSITIVE_KEYS
        or underscored.endswith("_token")
        or underscored.endswith("_secret")
        or underscored.endswith("_password")
        or underscored.endswith("_credential")
        or underscored in {"access_key", "private_key", "client_secret", "refresh_token", "access_token", "id_token"}
    )


def redact_text(value: str) -> str:
    if re.match(r"^(?:bearer|basic)\s+", value, re.IGNORECASE):
        return value.split(" ", 1)[0] + " <redacted>"
    return SECRET_VALUE_PATTERN.sub("<redacted-secret>", value)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            output[str(key)] = "<redacted>" if sensitive_key(str(key)) else redact(item)
        return output
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def captured_value_hash(value: Any) -> str:
    payload = json.dumps(redact(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(payload)


def scrub_url(raw_url: str) -> str:
    parsed = urllib.parse.urlsplit(raw_url)
    query = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        query.append((key, "<redacted>" if sensitive_key(key) else redact_text(value)))
    hostname = parsed.hostname or ""
    netloc = hostname
    if parsed.port:
        netloc = f"{hostname}:{parsed.port}"
    return urllib.parse.urlunsplit(
        (parsed.scheme, netloc, redact_text(parsed.path), urllib.parse.urlencode(query), "")
    )


def parse_json_body(raw_body: bytes) -> Any:
    try:
        return json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Request body must be valid UTF-8 JSON") from exc


def read_secret_file(path: Path, *, delete_after_read: bool) -> str:
    if path.is_symlink():
        raise ValueError(f"Secret file cannot be a symlink: {path}")
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"Secret path must be a regular file: {path}")
    raw_value = path.read_text(encoding="utf-8")
    value = raw_value.rstrip("\r\n")
    if not value:
        raise ValueError(f"Secret file is empty: {path}")
    if "\n" in value or "\r" in value or len(value) > 8192:
        raise ValueError(f"Secret file must contain exactly one bounded line: {path}")
    if delete_after_read:
        path.unlink()
    return value


def normalized_upstream_url(base: str, incoming_path: str, *, allow_insecure: bool = False) -> str:
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("--upstream-base must be an absolute HTTP(S) URL")
    if parsed.scheme != "https" and not allow_insecure:
        raise ValueError("--upstream-base must use HTTPS unless --allow-insecure-upstream is explicit")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("--upstream-base cannot contain URL credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("--upstream-base cannot contain a query or fragment")
    base_path = parsed.path.rstrip("/")
    suffix = incoming_path.split("?", 1)[0]
    if base_path.endswith("/v1") and suffix.startswith("/v1/"):
        suffix = suffix[3:]
    path = f"{base_path}/{suffix.lstrip('/')}"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


@dataclass(frozen=True)
class GatewayConfig:
    capture_dir: Path
    upstream_base: str
    upstream_key: str
    client_key: str
    upstream_model: str
    timeout_seconds: float = 300.0
    allowed_clients: frozenset[str] = frozenset()
    allow_insecure_upstream: bool = False
    accept_any_client_bearer: bool = False
    injected_request_fields: dict[str, Any] | None = None


class CaptureStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)
        for existing in self.root.iterdir():
            if existing.is_file() and not existing.is_symlink():
                existing.chmod(0o600)
        self._lock = threading.Lock()
        self._sequence = 0

    def create_path(self, request_id: str) -> Path:
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        return self.root / f"{stamp}-{sequence:06d}-{request_id}.json"

    def write(self, path: Path, record: dict[str, Any]) -> None:
        atomic_json(path, record)

    def append_index(self, row: dict[str, Any]) -> None:
        payload = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            path = self.root / "index.jsonl"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                handle.write(payload)
            path.chmod(0o600)

    def count(self) -> int:
        with self._lock:
            return self._sequence


class CaptureGateway(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], config: GatewayConfig) -> None:
        self.config = config
        self.store = CaptureStore(config.capture_dir)
        super().__init__(address, CaptureGatewayHandler)


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


class ClientDisconnected(Exception):
    pass


def upstream_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        NoRedirectHandler(),
        urllib.request.HTTPHandler(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )


class CaptureGatewayHandler(BaseHTTPRequestHandler):
    server: CaptureGateway
    protocol_version = "HTTP/1.1"
    server_version = "TavoCaptureGateway/1.0"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(20)

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        method = re.sub(r"[^A-Z]", "", getattr(self, "command", ""))[:12] or "UNKNOWN"
        path = scrub_url(getattr(self, "path", "/"))
        sys.stderr.write(f"[{utc_now()}] {self.client_address[0]} {method} {path} {code} {size}\n")

    def log_message(self, _fmt: str, *_args: Any) -> None:
        sys.stderr.write(f"[{utc_now()}] {self.client_address[0]} protocol_event\n")

    def _client_allowed(self) -> bool:
        allowed = self.server.config.allowed_clients
        return not allowed or self.client_address[0] in allowed

    def _require_allowed_client(self) -> bool:
        if self._client_allowed():
            return True
        self._json_response(HTTPStatus.FORBIDDEN, {"error": {"message": "Client address is not allowed"}})
        return False

    def _json_response(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        api_key = self.headers.get("X-Api-Key", "")
        if self.server.config.accept_any_client_bearer:
            return bool(re.match(r"^Bearer\s+\S+$", supplied, re.IGNORECASE) or api_key.strip())
        expected = f"Bearer {self.server.config.client_key}"
        return bool(self.server.config.client_key) and (
            secrets_compare(supplied, expected) or secrets_compare(api_key, self.server.config.client_key)
        )

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        self._json_response(
            HTTPStatus.UNAUTHORIZED,
            {"error": {"message": "Invalid capture-gateway API key", "type": "authentication_error"}},
        )
        return False

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._require_allowed_client():
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if not self._require_allowed_client():
            return
        path = urllib.parse.urlsplit(self.path).path.rstrip("/") or "/"
        if path == "/health":
            self._json_response(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "tavo-request-capture-gateway",
                    "upstreamBase": scrub_url(self.server.config.upstream_base),
                    "model": self.server.config.upstream_model,
                    "capturedRequests": self.server.store.count(),
                },
            )
            return
        if path in {"/models", "/v1/models"}:
            if not self._require_auth():
                return
            model = self.server.config.upstream_model
            self._json_response(
                HTTPStatus.OK,
                {"object": "list", "data": [{"id": model, "object": "model", "created": 0, "owned_by": "capture-upstream"}]},
            )
            return
        self._json_response(HTTPStatus.NOT_FOUND, {"error": {"message": "Not found", "type": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802
        if not self._require_allowed_client():
            return
        incoming_path = urllib.parse.urlsplit(self.path).path
        if incoming_path not in SUPPORTED_POST_PATHS:
            self._json_response(
                HTTPStatus.NOT_FOUND,
                {"error": {"message": f"Unsupported path: {incoming_path}", "type": "not_found"}},
            )
            return
        if not self._require_auth():
            return

        raw_length = self.headers.get("Content-Length", "")
        try:
            length = int(raw_length)
        except ValueError:
            self._json_response(HTTPStatus.LENGTH_REQUIRED, {"error": {"message": "Content-Length is required"}})
            return
        if length < 0 or length > MAX_REQUEST_BYTES:
            self._json_response(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": {"message": "Request body is too large"}})
            return

        raw_body = self.rfile.read(length)
        if len(raw_body) != length:
            self._json_response(HTTPStatus.BAD_REQUEST, {"error": {"message": "Request body ended early"}})
            return
        try:
            received_payload = parse_json_body(raw_body)
        except ValueError as exc:
            self._json_response(
                HTTPStatus.BAD_REQUEST,
                {"error": {"message": str(exc), "type": "invalid_request_error"}},
            )
            return
        if not isinstance(received_payload, dict):
            self._json_response(
                HTTPStatus.BAD_REQUEST,
                {"error": {"message": "Request JSON must be an object", "type": "invalid_request_error"}},
            )
            return
        forwarded_payload = dict(received_payload)
        forwarded_payload["model"] = self.server.config.upstream_model
        injected_fields = self.server.config.injected_request_fields or {}
        forwarded_payload.update(injected_fields)
        forwarded_body = json.dumps(forwarded_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request_id = uuid.uuid4().hex[:16]
        capture_path = self.server.store.create_path(request_id)
        upstream_url = normalized_upstream_url(
            self.server.config.upstream_base,
            incoming_path,
            allow_insecure=self.server.config.allow_insecure_upstream,
        )
        started = time.monotonic()
        record: dict[str, Any] = {
            "schemaVersion": 1,
            "gatewayRequestId": request_id,
            "receivedAt": utc_now(),
            "client": {"address": self.client_address[0]},
            "request": {
                "method": "POST",
                "path": scrub_url(self.path),
                "headers": redact(dict(self.headers.items())),
                "body": redact(received_payload),
                "bodyBytes": len(raw_body),
                "capturedBodySha256": captured_value_hash(received_payload),
            },
            "forward": {
                "url": scrub_url(upstream_url),
                "model": self.server.config.upstream_model,
                "body": redact(forwarded_payload),
                "bodyBytes": len(forwarded_body),
                "capturedBodySha256": captured_value_hash(forwarded_payload),
                "injectedFields": sorted(injected_fields),
            },
            "status": "forwarding",
        }
        self.server.store.write(capture_path, record)

        upstream_headers = {
            "Accept": self.headers.get("Accept", "application/json"),
            "Authorization": f"Bearer {self.server.config.upstream_key}",
            "Content-Type": "application/json",
            "User-Agent": "tavo-request-capture-gateway/1.0",
        }
        request = urllib.request.Request(upstream_url, data=forwarded_body, headers=upstream_headers, method="POST")
        try:
            with upstream_opener().open(request, timeout=self.server.config.timeout_seconds) as response:
                self._relay_upstream(response, record, capture_path, started)
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                body = json.dumps(
                    {"error": {"message": "Upstream redirect was blocked", "type": "upstream_redirect_error"}},
                    separators=(",", ":"),
                ).encode()
                record["upstreamResponseStatus"] = exc.code
                self._finish_record(
                    record,
                    capture_path,
                    started,
                    "upstream-redirect-blocked",
                    HTTPStatus.BAD_GATEWAY,
                    "application/json",
                    body,
                    append_index=False,
                )
                try:
                    self._relay_buffered_error(HTTPStatus.BAD_GATEWAY, "application/json", body, {})
                except ClientDisconnected:
                    self._mark_client_disconnected(record, capture_path)
                finally:
                    self._append_record_index(record, capture_path)
                return
            body = exc.read(MAX_UPSTREAM_ERROR_BYTES + 1)
            status = exc.code
            status_name = "upstream-http-error"
            content_type = exc.headers.get("Content-Type", "application/json")
            if len(body) > MAX_UPSTREAM_ERROR_BYTES:
                status = HTTPStatus.BAD_GATEWAY
                status_name = "upstream-error-too-large"
                content_type = "application/json"
                body = b'{"error":{"message":"Upstream error body exceeded the gateway limit"}}'
            self._finish_record(
                record,
                capture_path,
                started,
                status_name,
                status,
                content_type,
                body,
                append_index=False,
            )
            try:
                self._relay_buffered_error(status, content_type, body, exc.headers)
            except ClientDisconnected:
                self._mark_client_disconnected(record, capture_path)
            finally:
                self._append_record_index(record, capture_path)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            record["error"] = {"type": type(exc).__name__, "message": "Upstream transport failed"}
            self._finish_record(
                record,
                capture_path,
                started,
                "gateway-error",
                HTTPStatus.BAD_GATEWAY,
                "application/json",
                b"",
                append_index=False,
            )
            self._json_response(
                HTTPStatus.BAD_GATEWAY,
                {"error": {"message": "Capture gateway could not reach upstream", "type": "upstream_connection_error"}},
            )
            self._append_record_index(record, capture_path)

    def _relay_upstream(self, response: Any, record: dict[str, Any], capture_path: Path, started: float) -> None:
        status = int(response.status)
        content_type = response.headers.get("Content-Type", "application/octet-stream")
        streaming = "text/event-stream" in content_type.lower()
        digest = hashlib.sha256()
        total = 0
        if streaming:
            captured_events: list[Any] = []
            captured_text_bytes = 0
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                while True:
                    chunk = response.readline()
                    if not chunk:
                        break
                    if total + len(chunk) > MAX_UPSTREAM_RESPONSE_BYTES:
                        self._finish_record(
                            record,
                            capture_path,
                            started,
                            "upstream-stream-too-large",
                            status,
                            content_type,
                            None,
                            response_bytes=total,
                            response_sha256=digest.hexdigest(),
                            streaming=True,
                        )
                        self.close_connection = True
                        return
                    digest.update(chunk)
                    total += len(chunk)
                    if len(captured_events) < MAX_CAPTURED_RESPONSE_EVENTS:
                        decoded = chunk.decode("utf-8", errors="replace").strip()
                        if decoded.startswith("data:"):
                            data = decoded[5:].strip()
                            if data and data != "[DONE]":
                                encoded_size = len(data.encode("utf-8"))
                                if captured_text_bytes + encoded_size <= MAX_CAPTURED_RESPONSE_TEXT_BYTES:
                                    try:
                                        captured_events.append(redact(json.loads(data)))
                                    except json.JSONDecodeError:
                                        captured_events.append(redact_text(data))
                                    captured_text_bytes += encoded_size
                    self._write_client(chunk, flush=True)
            except ClientDisconnected:
                self._finish_record(
                    record,
                    capture_path,
                    started,
                    "client-disconnected",
                    status,
                    content_type,
                    None,
                    response_bytes=total,
                    response_sha256=digest.hexdigest(),
                    streaming=True,
                )
                self.close_connection = True
                return
            body_hash = digest.hexdigest()
            record["responseCapture"] = {
                "format": "sse",
                "events": captured_events,
                "truncated": len(captured_events) >= MAX_CAPTURED_RESPONSE_EVENTS
                or captured_text_bytes >= MAX_CAPTURED_RESPONSE_TEXT_BYTES,
            }
            self._finish_record(
                record,
                capture_path,
                started,
                "completed",
                status,
                content_type,
                None,
                response_bytes=total,
                response_sha256=body_hash,
                streaming=True,
            )
            self.close_connection = True
            return
        else:
            body = response.read(MAX_UPSTREAM_RESPONSE_BYTES + 1)
            if len(body) > MAX_UPSTREAM_RESPONSE_BYTES:
                error_body = b'{"error":{"message":"Upstream response exceeded the gateway limit"}}'
                self._finish_record(
                    record,
                    capture_path,
                    started,
                    "upstream-response-too-large",
                    HTTPStatus.BAD_GATEWAY,
                    "application/json",
                    error_body,
                    append_index=False,
                )
                self._json_response(HTTPStatus.BAD_GATEWAY, json.loads(error_body))
                self._append_record_index(record, capture_path)
                return
            digest.update(body)
            total = len(body)
            body_hash = digest.hexdigest()
            try:
                parsed_response = parse_json_body(body)
                record["responseCapture"] = {"format": "json", "body": redact(parsed_response), "truncated": False}
            except ValueError:
                if len(body) <= MAX_CAPTURED_RESPONSE_TEXT_BYTES:
                    record["responseCapture"] = {
                        "format": "text",
                        "body": redact_text(body.decode("utf-8", errors="replace")),
                        "truncated": False,
                    }
                else:
                    record["responseCapture"] = {"format": "text", "truncated": True}
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(total))
            self.end_headers()
            self._finish_record(
                record,
                capture_path,
                started,
                "completed",
                status,
                content_type,
                None,
                response_bytes=total,
                response_sha256=body_hash,
                streaming=False,
                append_index=False,
            )
            try:
                self._write_client(body)
            except ClientDisconnected:
                self._mark_client_disconnected(record, capture_path)
            finally:
                self._append_record_index(record, capture_path)

    def _relay_buffered_error(self, status: int, content_type: str, body: bytes, headers: Any) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        for key in ("Retry-After", "WWW-Authenticate", "X-Request-Id", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"):
            value = headers.get(key) if headers is not None else None
            if value:
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self._write_client(body)

    def _write_client(self, body: bytes, *, flush: bool = False) -> None:
        try:
            self.wfile.write(body)
            if flush:
                self.wfile.flush()
        except OSError as exc:
            raise ClientDisconnected from exc

    def _mark_client_disconnected(self, record: dict[str, Any], capture_path: Path) -> None:
        record["status"] = "client-disconnected"
        record["finishedAt"] = utc_now()
        self.server.store.write(capture_path, record)

    def _finish_record(
        self,
        record: dict[str, Any],
        capture_path: Path,
        started: float,
        status_name: str,
        response_status: int,
        content_type: str,
        body: bytes | None,
        *,
        response_bytes: int | None = None,
        response_sha256: str | None = None,
        streaming: bool | None = None,
        append_index: bool = True,
    ) -> None:
        if body is not None:
            response_bytes = len(body)
            response_sha256 = sha256_bytes(body)
        record.update(
            {
                "finishedAt": utc_now(),
                "elapsedMs": round((time.monotonic() - started) * 1000, 3),
                "status": status_name,
                "response": {
                    "status": int(response_status),
                    "contentType": content_type,
                    "stream": bool(streaming),
                    "bodyBytes": int(response_bytes or 0),
                    "bodySha256": response_sha256 or sha256_bytes(b""),
                },
            }
        )
        self.server.store.write(capture_path, record)
        if append_index:
            self._append_record_index(record, capture_path)

    def _append_record_index(self, record: dict[str, Any], capture_path: Path) -> None:
        self.server.store.append_index(
            {
                "gatewayRequestId": record["gatewayRequestId"],
                "receivedAt": record["receivedAt"],
                "finishedAt": record["finishedAt"],
                "path": record["request"]["path"],
                "model": record["forward"]["model"],
                "status": record["status"],
                "responseStatus": record["response"]["status"],
                "captureFile": capture_path.name,
            }
        )


def secrets_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture and forward OpenAI-compatible Tavo requests.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--capture-dir", required=True)
    parser.add_argument("--upstream-base", required=True)
    parser.add_argument("--upstream-key-file", required=True)
    parser.add_argument("--client-key-file")
    parser.add_argument("--upstream-model", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument(
        "--allow-client",
        action="append",
        default=[],
        help="Allowed source IP. Repeat for multiple clients; empty allows every source.",
    )
    parser.add_argument(
        "--allow-insecure-upstream",
        action="store_true",
        help="Allow an HTTP upstream. Never use this for a credential-bearing remote service.",
    )
    parser.add_argument(
        "--accept-any-client-bearer",
        action="store_true",
        help="Accept any non-empty Bearer/X-Api-Key from an explicitly allowlisted client.",
    )
    parser.add_argument(
        "--inject-request-fields-file",
        help="Optional JSON object merged into the forwarded request for controlled diagnostics.",
    )
    parser.add_argument(
        "--keep-secret-files",
        action="store_true",
        help="Do not unlink key files after startup. The default is to delete them immediately.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    delete_after_read = not args.keep_secret_files
    upstream_key = read_secret_file(Path(args.upstream_key_file), delete_after_read=delete_after_read)
    if args.accept_any_client_bearer:
        if not args.allow_client:
            raise SystemExit("--accept-any-client-bearer requires at least one --allow-client")
        client_key = ""
    elif args.client_key_file:
        client_key = read_secret_file(Path(args.client_key_file), delete_after_read=delete_after_read)
    else:
        raise SystemExit("--client-key-file is required unless --accept-any-client-bearer is used")
    injected_request_fields: dict[str, Any] | None = None
    if args.inject_request_fields_file:
        injected_request_fields = parse_json_body(Path(args.inject_request_fields_file).read_bytes())
        if not isinstance(injected_request_fields, dict):
            raise SystemExit("--inject-request-fields-file must contain a JSON object")
        allowed_injected_fields = {"tools", "tool_choice", "parallel_tool_calls", "stream"}
        unsupported = set(injected_request_fields) - allowed_injected_fields
        if unsupported:
            raise SystemExit(f"Unsupported injected request fields: {','.join(sorted(unsupported))}")
    config = GatewayConfig(
        capture_dir=Path(args.capture_dir).expanduser().resolve(),
        upstream_base=args.upstream_base,
        upstream_key=upstream_key,
        client_key=client_key,
        upstream_model=args.upstream_model,
        timeout_seconds=args.timeout_seconds,
        allowed_clients=frozenset(args.allow_client),
        allow_insecure_upstream=args.allow_insecure_upstream,
        accept_any_client_bearer=args.accept_any_client_bearer,
        injected_request_fields=injected_request_fields,
    )
    normalized_upstream_url(
        config.upstream_base,
        "/v1/chat/completions",
        allow_insecure=config.allow_insecure_upstream,
    )
    server = CaptureGateway((args.host, args.port), config)

    def stop(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"gateway_listen=http://{args.host}:{server.server_address[1]}/v1", flush=True)
    print(f"capture_dir={config.capture_dir}", flush=True)
    print(f"upstream_base={scrub_url(config.upstream_base)}", flush=True)
    print(f"upstream_model={config.upstream_model}", flush=True)
    print(f"allowed_clients={','.join(sorted(config.allowed_clients)) or '<any>'}", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
