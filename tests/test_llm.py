import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from structured_output_agent.llm import OpenAICompatibleLLM


def test_local_openai_compatible_http_adapter():
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            size = int(self.headers["Content-Length"])
            seen["path"] = self.path
            seen["authorization"] = self.headers["Authorization"]
            seen["body"] = json.loads(self.rfile.read(size))
            body = json.dumps(
                {
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 4, "completion_tokens": 2},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = OpenAICompatibleLLM(
            "test-key", f"http://localhost:{server.server_port}/v1", "test-model"
        )
        assert client.complete([{"role": "user", "content": "hello"}]) == "ok"
        assert seen["path"] == "/v1/chat/completions"
        assert seen["authorization"] == "Bearer test-key"
        assert seen["body"]["model"] == "test-model"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_rejects_deceptive_plain_http_host():
    client = OpenAICompatibleLLM("test-key", "http://localhost.evil.example/v1")
    with pytest.raises(ValueError):
        client.complete([{"role": "user", "content": "hello"}])
