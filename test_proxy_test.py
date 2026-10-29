"""
/api/proxy/test 的 HTTP 层校验 —— urlopen 被桩掉，不发真实网络请求。

跑法： .venv/bin/python -m unittest test_proxy_test
"""
import io
import json
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError

import main
from fastapi import HTTPException


class FakeResponse:
    def __init__(self, body, status=200):
        self._body = body.encode("utf-8")
        self.status = status

    def read(self):
        return self._body

    def __iter__(self):
        return iter(self._body.splitlines(keepends=True))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def header(req, name):
    """urllib 会把头名 capitalize（x-api-key → X-api-key），统一小写再取。"""
    return {k.lower(): v for k, v in req.headers.items()}.get(name.lower())


ANTHROPIC_SSE = [
    b'event: message_start\n',
    b'data: {"type":"message_start","message":{"id":"msg_1"}}\n',
    b'\n',
    b'event: content_block_start\n',
    b'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n',
    b'\n',
    b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n',
    b'\n',
    b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":" there"}}\n',
    b'\n',
    b'event: message_stop\n',
    b'data: {"type":"message_stop"}\n',
]


class ProxyTestTest(unittest.TestCase):
    def _run(self, **kw):
        body = {"baseURL": "https://example.test/v1", "apiKey": "sk-x", "model": "gpt-4o"}
        body.update(kw)
        return main.proxy_test(main.ProxyTestRequest(**body))

    def test_chat_success(self):
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url
            seen["payload"] = json.loads(req.data.decode("utf-8"))
            seen["auth"] = req.headers.get("Authorization")
            seen["timeout"] = timeout
            return FakeResponse(json.dumps({"choices": [{"message": {"content": "ok"}}]}))

        with mock.patch.object(main.urllib.request, "urlopen", fake_urlopen):
            r = self._run()

        self.assertTrue(r["ok"])
        self.assertEqual(r["status"], 200)
        self.assertEqual(r["reply"], "ok")
        self.assertGreaterEqual(r["ms"], 0)
        self.assertEqual(seen["url"], "https://example.test/v1/chat/completions")
        self.assertEqual(seen["auth"], "Bearer sk-x")
        self.assertEqual(seen["payload"]["model"], "gpt-4o")
        self.assertEqual(seen["payload"]["messages"][0]["role"], "user")

    def test_responses_wire_api(self):
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url
            seen["payload"] = json.loads(req.data.decode("utf-8"))
            return FakeResponse(json.dumps({"output_text": "ok"}))

        with mock.patch.object(main.urllib.request, "urlopen", fake_urlopen):
            r = self._run(wireApi="responses")

        self.assertTrue(r["ok"])
        self.assertEqual(r["reply"], "ok")
        self.assertEqual(seen["url"], "https://example.test/v1/responses")
        self.assertIn("input", seen["payload"])

    def test_no_api_key_sends_no_auth_header(self):
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["auth"] = req.headers.get("Authorization")
            return FakeResponse(json.dumps({"choices": [{"message": {"content": "ok"}}]}))

        with mock.patch.object(main.urllib.request, "urlopen", fake_urlopen):
            self._run(apiKey="")

        self.assertIsNone(seen["auth"])

    def test_http_error_returns_detail(self):
        def fake_urlopen(req, timeout=None):
            raise HTTPError(
                req.full_url, 404, "Not Found", {},
                io.BytesIO(b'{"error":{"message":"model not found"}}'),
            )

        with mock.patch.object(main.urllib.request, "urlopen", fake_urlopen):
            r = self._run()

        self.assertFalse(r["ok"])
        self.assertEqual(r["status"], 404)
        self.assertEqual(r["detail"], "model not found")

    def test_connection_error(self):
        def fake_urlopen(req, timeout=None):
            raise URLError("Connection refused")

        with mock.patch.object(main.urllib.request, "urlopen", fake_urlopen):
            r = self._run()

        self.assertFalse(r["ok"])
        self.assertEqual(r["status"], 0)
        self.assertIn("无法连接", r["detail"])

    def test_missing_base_url(self):
        with self.assertRaises(HTTPException) as ctx:
            self._run(baseURL="")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_missing_model(self):
        with self.assertRaises(HTTPException) as ctx:
            self._run(model="  ")
        self.assertEqual(ctx.exception.status_code, 400)

    # ── Anthropic Messages 协议 ──
    def test_anthropic_request_shape(self):
        seen = {}

        def fake_urlopen(req, timeout=None):
            seen["url"] = req.full_url
            seen["payload"] = json.loads(req.data.decode("utf-8"))
            seen["headers"] = {k.lower(): v for k, v in req.headers.items()}
            seen["timeout"] = timeout
            return FakeResponse(json.dumps({"content": [{"type": "text", "text": "ok"}]}))

        with mock.patch.object(main.urllib.request, "urlopen", fake_urlopen):
            r = self._run(wireApi="anthropic")

        self.assertTrue(r["ok"])
        self.assertEqual(seen["url"], "https://example.test/v1/messages")
        self.assertEqual(seen["headers"]["authorization"], "Bearer sk-x")
        self.assertEqual(seen["headers"]["anthropic-version"], "2023-06-01")
        self.assertEqual(seen["payload"]["model"], "gpt-4o")
        self.assertEqual(seen["payload"]["max_tokens"], 1024)
        self.assertTrue(seen["payload"]["stream"])
        self.assertEqual(seen["payload"]["messages"][0]["role"], "user")

    def test_anthropic_reads_sse(self):
        def fake_urlopen(req, timeout=None):
            return FakeResponse("\n".join(x.decode() for x in ANTHROPIC_SSE))

        with mock.patch.object(main.urllib.request, "urlopen", fake_urlopen):
            r = self._run(wireApi="anthropic")

        self.assertTrue(r["ok"])
        self.assertEqual(r["reply"], "Hello there")
        self.assertGreaterEqual(r["ttfbMs"], 0)
        self.assertGreaterEqual(r["ms"], r["ttfbMs"])

    def test_anthropic_http_error(self):
        def fake_urlopen(req, timeout=None):
            raise HTTPError(
                req.full_url, 400, "Bad Request", {},
                io.BytesIO(b'{"type":"error","error":{"type":"invalid_request_error","message":"bad model"}}'),
            )

        with mock.patch.object(main.urllib.request, "urlopen", fake_urlopen):
            r = self._run(wireApi="anthropic")

        self.assertFalse(r["ok"])
        self.assertEqual(r["status"], 400)
        self.assertEqual(r["detail"], "bad model")


if __name__ == "__main__":
    unittest.main()
