#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import tavo_request_capture_gateway as gateway


UPSTREAM_KEY = "upstream-test-secret"
CLIENT_KEY = "client-test-secret"


class FakeUpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    calls: list[dict] = []
    redirect_url = ""
    first_sse_sent = threading.Event()
    release_sse = threading.Event()

    def log_message(self, _fmt: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        payload = json.loads(body)
        self.__class__.calls.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "payload": payload,
            }
        )
        if payload.get("redirect"):
            self.send_response(302)
            self.send_header("Location", self.__class__.redirect_url)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if payload.get("force_error"):
            encoded = b'{"error":{"message":"limited"}}'
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return
        if payload.get("stream"):
            if payload.get("delayed_stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(b'data: {"choices":[{"delta":{"content":"first"}}]}\n')
                self.wfile.flush()
                self.__class__.first_sse_sent.set()
                self.__class__.release_sse.wait(timeout=2)
                self.wfile.write(b'\ndata: [DONE]\n\n')
                self.wfile.flush()
                self.close_connection = True
                return
            encoded = b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return
        encoded = json.dumps(
            {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class RedirectSinkHandler(BaseHTTPRequestHandler):
    authorizations: list[str | None] = []

    def log_message(self, _fmt: str, *_args: object) -> None:
        return

    def _capture(self) -> None:
        self.__class__.authorizations.append(self.headers.get("Authorization"))
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = _capture  # noqa: N815
    do_POST = _capture  # noqa: N815


class GatewayTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeUpstreamHandler.calls = []
        FakeUpstreamHandler.first_sse_sent = threading.Event()
        FakeUpstreamHandler.release_sse = threading.Event()
        RedirectSinkHandler.authorizations = []
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.redirect_sink = ThreadingHTTPServer(("127.0.0.1", 0), RedirectSinkHandler)
        self.redirect_sink_thread = threading.Thread(target=self.redirect_sink.serve_forever, daemon=True)
        self.redirect_sink_thread.start()
        FakeUpstreamHandler.redirect_url = f"http://127.0.0.1:{self.redirect_sink.server_address[1]}/steal"
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstreamHandler)
        self.upstream_thread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        self.upstream_thread.start()
        upstream_base = f"http://127.0.0.1:{self.upstream.server_address[1]}/v1"
        config = gateway.GatewayConfig(
            capture_dir=self.root / "captures",
            upstream_base=upstream_base,
            upstream_key=UPSTREAM_KEY,
            client_key=CLIENT_KEY,
            upstream_model="deepseek-v4-pro",
            timeout_seconds=5,
            allowed_clients=frozenset({"127.0.0.1"}),
            allow_insecure_upstream=True,
        )
        self.server = gateway.CaptureGateway(("127.0.0.1", 0), config)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.upstream.shutdown()
        self.upstream.server_close()
        self.redirect_sink.shutdown()
        self.redirect_sink.server_close()
        self.temp.cleanup()

    def request(self, path: str, payload: dict | None = None, *, key: str = CLIENT_KEY):
        headers = {"Authorization": f"Bearer {key}"}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        return urllib.request.urlopen(urllib.request.Request(self.base + path, data=data, headers=headers), timeout=5)

    def captures(self) -> list[dict]:
        paths = [path for path in (self.root / "captures").glob("*.json") if path.name != "index.jsonl"]
        return [json.loads(path.read_text()) for path in paths]

    def test_health_and_models(self) -> None:
        with urllib.request.urlopen(self.base + "/health", timeout=5) as response:
            self.assertTrue(json.load(response)["ok"])
        with self.request("/v1/models") as response:
            self.assertEqual(json.load(response)["data"][0]["id"], "deepseek-v4-pro")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/v1/models", key="wrong")
        self.assertEqual(caught.exception.code, 401)
        caught.exception.close()

    def test_nonstream_is_forwarded_captured_and_redacted(self) -> None:
        payload = {
            "model": "client-alias",
            "messages": [{"role": "system", "content": "EJS marker"}, {"role": "user", "content": "hello"}],
            "api_key": "body-secret",
            "refresh_token": "refresh-secret",
            "note": "embedded sk-1234567890abcdefghijklmnop",
            "stream": False,
        }
        with self.request("/v1/chat/completions", payload) as response:
            self.assertEqual(json.load(response)["choices"][0]["message"]["content"], "ok")
        self.assertEqual(FakeUpstreamHandler.calls[0]["path"], "/v1/chat/completions")
        self.assertEqual(FakeUpstreamHandler.calls[0]["authorization"], f"Bearer {UPSTREAM_KEY}")
        self.assertEqual(FakeUpstreamHandler.calls[0]["payload"]["model"], "deepseek-v4-pro")
        capture = self.captures()[0]
        self.assertEqual(capture["request"]["body"]["messages"][0]["content"], "EJS marker")
        self.assertEqual(capture["request"]["body"]["api_key"], "<redacted>")
        self.assertEqual(capture["request"]["body"]["refresh_token"], "<redacted>")
        self.assertNotIn("sk-1234567890abcdefghijklmnop", json.dumps(capture))
        self.assertEqual(capture["request"]["headers"]["Authorization"], "<redacted>")
        serialized = json.dumps(capture)
        self.assertNotIn(UPSTREAM_KEY, serialized)
        self.assertNotIn(CLIENT_KEY, serialized)
        self.assertNotIn("body-secret", serialized)
        self.assertEqual(capture["status"], "completed")
        self.assertEqual(capture["response"]["status"], 200)

    def test_stream_is_relayed_and_indexed(self) -> None:
        with self.request("/chat/completions", {"model": "deepseek-v4-pro", "messages": [], "stream": True}) as response:
            body = response.read().decode()
        self.assertIn("data: [DONE]", body)
        capture = self.captures()[0]
        self.assertTrue(capture["response"]["stream"])
        self.assertEqual(capture["responseCapture"]["format"], "sse")
        self.assertEqual(capture["responseCapture"]["events"][0]["choices"][0]["delta"]["content"], "ok")
        self.assertTrue((self.root / "captures" / "index.jsonl").exists())

    def test_nonstream_response_body_is_captured(self) -> None:
        with self.request("/v1/chat/completions", {"model": "x", "messages": [], "stream": False}) as response:
            response.read()
        capture = self.captures()[0]
        self.assertEqual(capture["responseCapture"]["format"], "json")
        self.assertEqual(capture["responseCapture"]["body"]["choices"][0]["message"]["content"], "ok")

    def test_injected_request_fields_are_forwarded_and_recorded(self) -> None:
        self.server.config = gateway.GatewayConfig(
            **{
                **self.server.config.__dict__,
                "injected_request_fields": {
                    "tools": [{"type": "function", "function": {"name": "echo", "parameters": {"type": "object"}}}],
                    "tool_choice": "auto",
                },
            }
        )
        with self.request("/v1/chat/completions", {"model": "x", "messages": [], "stream": False}) as response:
            response.read()
        self.assertEqual(FakeUpstreamHandler.calls[0]["payload"]["tool_choice"], "auto")
        capture = self.captures()[0]
        self.assertEqual(capture["forward"]["injectedFields"], ["tool_choice", "tools"])

    def test_allowlisted_any_bearer_mode_still_requires_a_credential(self) -> None:
        self.server.config = gateway.GatewayConfig(
            **{**self.server.config.__dict__, "accept_any_client_bearer": True, "client_key": ""}
        )
        with self.request("/v1/models", key="phone-configured-value") as response:
            self.assertEqual(json.load(response)["data"][0]["id"], "deepseek-v4-pro")
        request = urllib.request.Request(self.base + "/v1/models")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 401)
        caught.exception.close()

    def test_stream_first_event_is_relayed_before_upstream_finishes(self) -> None:
        response = self.request(
            "/v1/chat/completions",
            {"model": "deepseek-v4-pro", "messages": [], "stream": True, "delayed_stream": True},
        )
        try:
            self.assertTrue(FakeUpstreamHandler.first_sse_sent.wait(timeout=1))
            self.assertIn(b'"first"', response.readline())
        finally:
            FakeUpstreamHandler.release_sse.set()
            response.read()
            response.close()

    def test_cross_origin_upstream_redirect_is_blocked(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request(
                "/v1/chat/completions",
                {"model": "deepseek-v4-pro", "messages": [], "redirect": True},
            )
        self.assertEqual(caught.exception.code, 502)
        caught.exception.close()
        self.assertEqual(RedirectSinkHandler.authorizations, [])
        self.assertEqual(self.captures()[0]["status"], "upstream-redirect-blocked")

    def test_upstream_http_error_is_forwarded_and_recorded(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/v1/chat/completions", {"model": "deepseek-v4-pro", "messages": [], "force_error": True})
        self.assertEqual(caught.exception.code, 429)
        caught.exception.close()
        capture = self.captures()[0]
        self.assertEqual(capture["status"], "upstream-http-error")
        self.assertEqual(capture["response"]["status"], 429)

    def test_secret_file_is_unlinked_after_read(self) -> None:
        path = self.root / "secret"
        path.write_text("value\n")
        self.assertEqual(gateway.read_secret_file(path, delete_after_read=True), "value")
        self.assertFalse(path.exists())

    def test_malformed_json_is_rejected_without_capture(self) -> None:
        request = urllib.request.Request(
            self.base + "/v1/chat/completions",
            data=b"not-json",
            headers={"Authorization": f"Bearer {CLIENT_KEY}", "Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()
        self.assertEqual(self.captures(), [])

    def test_capture_permissions_are_private(self) -> None:
        with self.request(
            "/v1/chat/completions",
            {"model": "deepseek-v4-pro", "messages": [], "stream": False},
        ) as response:
            response.read()
        capture_dir = self.root / "captures"
        self.assertEqual(os.stat(capture_dir).st_mode & 0o777, 0o700)
        for path in capture_dir.iterdir():
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
