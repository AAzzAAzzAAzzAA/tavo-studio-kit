#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import tavo_generation_hook_fixture as fixture  # noqa: E402


CLIENT_KEY = "fixture-client-secret"


class GenerationHookFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        config = fixture.FixtureConfig(
            capture_dir=self.root / "captures",
            client_key=CLIENT_KEY,
            model="tavo-092-test-model",
            allowed_clients=frozenset({"127.0.0.1"}),
            slow_chunk_seconds=0.12,
        )
        self.server = fixture.FixtureServer(("127.0.0.1", 0), config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, path: str, payload: dict | None = None, *, key: str = CLIENT_KEY):
        headers = {"Authorization": f"Bearer {key}"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        return urllib.request.urlopen(
            urllib.request.Request(self.base + path, data=data, headers=headers),
            timeout=3,
        )

    def captures(self) -> list[dict]:
        return [json.loads(path.read_text(encoding="utf-8")) for path in sorted((self.root / "captures").glob("*.json"))]

    @staticmethod
    def next_sse_data(response) -> str:
        while True:
            line = response.readline().decode("utf-8")
            if not line:
                raise AssertionError("SSE response ended before the next data event")
            if line.startswith("data: "):
                return line.rstrip("\r\n")

    def test_health_models_auth_and_allowlist(self) -> None:
        with urllib.request.urlopen(self.base + "/health", timeout=3) as response:
            self.assertTrue(json.load(response)["ok"])
        with self.request("/v1/models") as response:
            self.assertEqual(json.load(response)["data"][0]["id"], "tavo-092-test-model")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/v1/models", key="wrong")
        self.assertEqual(caught.exception.code, 401)
        caught.exception.close()

        denied = fixture.FixtureServer(
            ("127.0.0.1", 0),
            fixture.FixtureConfig(
                capture_dir=self.root / "denied",
                client_key=CLIENT_KEY,
                allowed_clients=frozenset({"192.0.2.1"}),
            ),
        )
        denied_thread = threading.Thread(target=denied.serve_forever, daemon=True)
        denied_thread.start()
        try:
            url = f"http://127.0.0.1:{denied.server_address[1]}/health"
            with self.assertRaises(urllib.error.HTTPError) as denied_error:
                urllib.request.urlopen(url, timeout=3)
            self.assertEqual(denied_error.exception.code, 403)
            denied_error.exception.close()
        finally:
            denied.shutdown()
            denied.server_close()
            denied_thread.join(timeout=2)

    def test_json_response_capture_and_redaction(self) -> None:
        secret = "sk-1234567890abcdefghijklmnop"
        payload = {
            "model": "client-alias",
            "stream": False,
            "messages": [
                {"role": "system", "content": "SYSTEM_MARKER"},
                {"role": "user", "content": f"hello {secret}"},
            ],
            "api_key": "body-secret",
        }
        with self.request("/v1/chat/completions", payload) as response:
            body = json.load(response)
        self.assertTrue(body["choices"][0]["message"]["content"].startswith("TAVO_092_FIXTURE_OK::"))
        capture = self.captures()[0]
        self.assertEqual(capture["scenario"], "normal")
        self.assertEqual(capture["request"]["headers"]["Authorization"], "<redacted>")
        self.assertEqual(capture["request"]["body"]["api_key"], "<redacted>")
        serialized = json.dumps(capture)
        self.assertNotIn(secret, serialized)
        self.assertNotIn(CLIENT_KEY, serialized)
        self.assertNotIn("body-secret", serialized)
        self.assertEqual(stat.S_IMODE((self.root / "captures").stat().st_mode), 0o700)
        capture_path = next((self.root / "captures").glob("*.json"))
        self.assertEqual(stat.S_IMODE(capture_path.stat().st_mode), 0o600)

    def test_sse_and_slow_stream_are_deterministic(self) -> None:
        start = time.monotonic()
        payload = {
            "model": "x",
            "stream": True,
            "messages": [{"role": "user", "content": "[TAVO_FIXTURE_SCENARIO:slow_stream]"}],
        }
        with self.request("/chat/completions", payload) as response:
            text = response.read().decode("utf-8")
        self.assertGreaterEqual(time.monotonic() - start, 0.08)
        self.assertIn("TAVO_092_FIXTURE_OK", text)
        self.assertIn("data: [DONE]", text)
        capture = self.captures()[0]
        self.assertEqual(capture["scenario"], "slow_stream")
        self.assertEqual(
            capture["response"],
            {
                "status": 200,
                "format": "sse",
                "scenario": "slow_stream",
                "streamTiming": "after-each-content-chunk",
                "text": capture["response"]["text"],
                "slowChunkSeconds": 0.12,
            },
        )

    def test_explicit_slow_stream_windows_order_first_and_second_chunks(self) -> None:
        before_payload = {
            "model": "x",
            "stream": True,
            "messages": [
                {"role": "user", "content": "[TAVO_FIXTURE_SCENARIO:slow_stream_before_first]"}
            ],
        }
        with self.request("/v1/chat/completions", before_payload) as response:
            before_start = time.monotonic()
            before_first = self.next_sse_data(response)
            before_first_delay = time.monotonic() - before_start
        self.assertGreaterEqual(before_first_delay, 0.09)
        self.assertIn("chat.completion.chunk", before_first)

        after_payload = {
            "model": "x",
            "stream": True,
            "messages": [
                {"role": "user", "content": "[TAVO_FIXTURE_SCENARIO:slow_stream_after_first]"}
            ],
        }
        with self.request("/v1/chat/completions", after_payload) as response:
            after_start = time.monotonic()
            after_first = self.next_sse_data(response)
            after_first_at = time.monotonic()
            after_second = self.next_sse_data(response)
            after_second_at = time.monotonic()
        self.assertIn("chat.completion.chunk", after_first)
        self.assertIn("chat.completion.chunk", after_second)
        self.assertLess(after_first_at - after_start, after_second_at - after_start)
        self.assertGreaterEqual(after_second_at - after_first_at, 0.09)

        captures = self.captures()
        self.assertEqual(
            [item["scenario"] for item in captures],
            ["slow_stream_before_first", "slow_stream_after_first"],
        )
        self.assertEqual(
            [item["response"]["scenario"] for item in captures],
            ["slow_stream_before_first", "slow_stream_after_first"],
        )
        self.assertEqual([item["response"]["status"] for item in captures], [200, 200])
        self.assertEqual([item["response"]["format"] for item in captures], ["sse", "sse"])
        self.assertEqual(
            [item["response"]["streamTiming"] for item in captures],
            ["before-first-content-chunk", "after-first-content-chunk"],
        )

    def test_http_and_protocol_faults(self) -> None:
        for scenario, expected_status in (("http500", 500), ("protocol_error", 200)):
            payload = {
                "model": "x",
                "messages": [{"role": "user", "content": f"[TAVO_FIXTURE_SCENARIO:{scenario}]"}],
            }
            if expected_status == 500:
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    self.request("/v1/chat/completions", payload)
                self.assertEqual(caught.exception.code, 500)
                body = json.load(caught.exception)
                caught.exception.close()
                self.assertEqual(body["error"]["code"], "fixture_http_500")
            else:
                with self.request("/v1/chat/completions", payload) as response:
                    body = json.load(response)
                self.assertTrue(body["fixtureInvalidProtocol"])
        self.assertEqual([item["scenario"] for item in self.captures()], ["http500", "protocol_error"])
        self.assertEqual(
            [item["response"]["scenario"] for item in self.captures()],
            ["http500", "protocol_error"],
        )

    def test_invalid_scenario_is_rejected_without_capture(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request(
                "/v1/chat/completions",
                {"messages": [{"role": "user", "content": "[TAVO_FIXTURE_SCENARIO:unknown]"}]},
            )
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()
        self.assertEqual(self.captures(), [])

    def test_secret_file_requires_private_mode_and_can_be_deleted(self) -> None:
        path = self.root / "key"
        path.write_text("private-key\n", encoding="utf-8")
        path.chmod(0o600)
        self.assertEqual(fixture.read_secret_file(path), "private-key")
        path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "group/other"):
            fixture.read_secret_file(path)
        path.chmod(0o600)
        self.assertEqual(fixture.read_secret_file(path, delete_after_read=True), "private-key")
        self.assertFalse(path.exists())

    def test_redaction_scrubs_nested_credentials(self) -> None:
        redacted = fixture.redact(
            {
                "authorization": "Bearer hidden",
                "nested": {"refresh-token": "value", "note": "sk-1234567890abcdefghijklmnop"},
            }
        )
        self.assertEqual(redacted["authorization"], "<redacted>")
        self.assertEqual(redacted["nested"]["refresh-token"], "<redacted>")
        self.assertEqual(redacted["nested"]["note"], "<redacted-secret>")


if __name__ == "__main__":
    unittest.main()
