"""Real ACP transport -> unchanged runner -> HTTP model + MCP -> ACP events."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from acp import PROTOCOL_VERSION, RequestError, spawn_agent_process, text_block
from acp.interfaces import Client
from acp.schema import HttpMcpServer

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parents[1]


def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Collector(Client):
    def __init__(self):
        self.updates = []

    async def session_update(self, session_id, update, **kwargs):
        self.updates.append(
            update.model_dump(mode="json", by_alias=True, exclude_none=True)
        )


class Integration(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.mcp_port, cls.model_port = port(), port()
        cls.services = subprocess.Popen(
            [
                sys.executable,
                str(PROJECT / "tests/fake_services.py"),
                "--mcp-port",
                str(cls.mcp_port),
                "--model-port",
                str(cls.model_port),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", cls.mcp_port), timeout=0.1):
                    break
            except OSError:
                if cls.services.poll() is not None:
                    raise RuntimeError("Fixture failed")
                time.sleep(0.1)
        else:
            raise RuntimeError("Fixture did not start")

    @classmethod
    def tearDownClass(cls):
        cls.services.terminate()
        cls.services.wait(timeout=10)

    async def run_case(self, max_steps=100, cancel=False, direct=False):
        collector = Collector()
        with tempfile.TemporaryDirectory() as d:
            env = {
                **os.environ,
                "LITELLM_PROXY_API_KEY": "fake-test-token",
                "LITELLM_PROXY_API_BASE": f"http://127.0.0.1:{self.model_port}/v1",
                "LITELLM_LOCAL_MODEL_COST_MAP": "True",
                "APEX_LOG_DIR": d,
                "HARBOR_ACP_REQUESTED_MODEL": "openai/slow"
                if cancel
                else "openai/test",
                "MAX_STEPS": str(max_steps),
                "AGENT_TIMEOUT_SEC": "15",
            }
            if direct:
                env.pop("LITELLM_PROXY_API_BASE", None)
                env.pop("LITELLM_PROXY_API_KEY", None)
                env["OPENAI_API_KEY"] = "fake-test-token"
                env["OPENAI_API_BASE"] = f"http://127.0.0.1:{self.model_port}/v1"
                env["OPENAI_BASE_URL"] = env["OPENAI_API_BASE"]
            async with spawn_agent_process(
                collector, sys.executable, "-m", "apex_acp", env=env, cwd=PROJECT
            ) as (conn, proc):
                init = await conn.initialize(protocol_version=PROTOCOL_VERSION)
                self.assertTrue(init.agent_capabilities.mcp_capabilities.http)
                session = await conn.new_session(
                    cwd=str(ROOT),
                    mcp_servers=[
                        HttpMcpServer(
                            type="http",
                            name="world",
                            url=f"http://127.0.0.1:{self.mcp_port}/mcp",
                            headers=[],
                        )
                    ],
                )
                await conn.set_session_model(
                    session_id=session.session_id,
                    model_id=env["HARBOR_ACP_REQUESTED_MODEL"],
                )
                await conn.set_config_option(
                    session_id=session.session_id,
                    config_id="model",
                    value=env["HARBOR_ACP_REQUESTED_MODEL"],
                )
                task = asyncio.create_task(
                    conn.prompt(
                        session_id=session.session_id,
                        prompt=[text_block("Read the answer.")],
                    )
                )
                if cancel:
                    await asyncio.sleep(1)
                    await conn.cancel(session_id=session.session_id)
                    result = await asyncio.wait_for(task, 10)
                    self.assertEqual(result.stop_reason, "cancelled")
                    return
                try:
                    result = await asyncio.wait_for(task, 25)
                except Exception:
                    if max_steps != 1:
                        print(Path(d, "agent_run.log").read_text()[-10000:])
                    raise
                native = json.loads(Path(d, "trajectory.native.json").read_text())
                expected_config = json.loads(
                    (ROOT / "apex_loop_truncated_tools_agent/manifest.json").read_text()
                )["agent"]
                expected_config["agent_config_values"].update(
                    max_steps=max_steps, timeout=15
                )
                self.assertEqual(
                    json.loads(Path(d, "agent_config.json").read_text()),
                    expected_config,
                )
                self.assertEqual(native["status"], "completed")
                self.assertEqual(result.stop_reason, "end_turn")
                self.assertGreater(result.usage.total_tokens, 0)
                self.assertTrue(
                    any(u.get("rawOutput") == "42" for u in collector.updates)
                )
                self.assertEqual(
                    collector.updates[-1]["content"]["text"], "The answer is 42."
                )
                self.assertIn(
                    "You should not scattergun", native["messages"][0]["content"]
                )
                for file in Path(d).iterdir():
                    self.assertNotIn("fake-test-token", file.read_text(), file.name)
                return collector.updates, native

    async def test_tool_loop_with_litellm_proxy(self):
        await self.run_case()

    async def test_direct_provider_credentials(self):
        await self.run_case(direct=True)

    async def test_failed_native_status_is_protocol_error(self):
        with self.assertRaises(RequestError) as caught:
            await self.run_case(max_steps=1)
        self.assertIn("did not complete (failed)", str(caught.exception))

    async def test_cancel_stops_runner(self):
        await self.run_case(cancel=True)


if __name__ == "__main__":
    unittest.main()
