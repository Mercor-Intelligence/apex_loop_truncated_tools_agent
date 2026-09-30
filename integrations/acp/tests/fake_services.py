"""Local MCP world and streaming OpenAI-compatible model for integration tests."""

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastmcp import FastMCP

parser = argparse.ArgumentParser()
parser.add_argument("--mcp-port", type=int, required=True)
parser.add_argument("--model-port", type=int, required=True)
args = parser.parse_args()


class Model(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.headers["Authorization"] == "Bearer fake-test-token"
        assert self.path == "/v1/chat/completions", self.path
        assert request["model"] in ("openai/test", "openai/slow", "test", "slow"), (
            request["model"]
        )
        if request["model"] in ("openai/slow", "slow"):
            time.sleep(30)
        messages = request["messages"]
        has_result = any(m["role"] == "tool" for m in messages)
        if has_result:
            assert any(
                "42" in str(m.get("content")) for m in messages if m["role"] == "tool"
            )
            delta = {"role": "assistant", "content": "The answer is 42."}
            finish = "stop"
        else:
            tool = request["tools"][0]["function"]["name"]
            delta = {
                "role": "assistant",
                "content": "I will check.",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_check",
                        "type": "function",
                        "function": {"name": tool, "arguments": "{}"},
                    }
                ],
            }
            finish = "tool_calls"
        if not request.get("stream"):
            for tc in delta.get("tool_calls", []):
                tc.pop("index", None)
            payload = json.dumps(
                {
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "created": 1,
                    "model": request["model"],
                    "choices": [
                        {"index": 0, "message": delta, "finish_reason": finish}
                    ],
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 4,
                        "total_tokens": 16,
                    },
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for d, reason, usage in [
            (delta, None, None),
            (
                {},
                finish,
                {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
            ),
        ]:
            chunk = {
                "id": "chatcmpl-test",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": request["model"],
                "choices": [{"index": 0, "delta": d, "finish_reason": reason}],
            }
            if usage:
                chunk["usage"] = usage
            self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


server = ThreadingHTTPServer(("127.0.0.1", args.model_port), Model)
threading.Thread(target=server.serve_forever, daemon=True).start()
mcp = FastMCP("test-world")


@mcp.tool()
def read_answer() -> str:
    """Read the answer from the world."""
    return "42"


mcp.run(
    transport="http",
    host="127.0.0.1",
    port=args.mcp_port,
    show_banner=False,
    log_level="error",
)
