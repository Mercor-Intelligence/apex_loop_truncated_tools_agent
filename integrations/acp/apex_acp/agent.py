"""ACP adapter; benchmark decisions remain in the unmodified upstream runner.

Harbor reconstructs trajectory.json from ACP events. We retain the complete
native transcript separately and replay its assistant/tool events after the
runner exits. Stdout is reserved for ACP JSON-RPC.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
import signal
import sys
from pathlib import Path
from uuid import uuid4

from acp import PROTOCOL_VERSION, Agent, RequestError, text_block
from acp.schema import (
    AgentCapabilities,
    AgentMessageChunk,
    AgentThoughtChunk,
    Implementation,
    InitializeResponse,
    McpCapabilities,
    ModelInfo,
    NewSessionResponse,
    PromptResponse,
    SessionConfigOption,
    SessionModelState,
    SetSessionConfigOptionResponse,
    SetSessionModelResponse,
    ToolCallProgress,
    ToolCallStart,
    Usage,
)

ROOT = Path(__file__).resolve().parents[3]
UPSTREAM = ROOT / "apex_loop_truncated_tools_agent"


def system_prompt() -> str:
    # Read the literal from the pinned original source without importing Harbor.
    tree = ast.parse((UPSTREAM / "apex_loop_truncated_tools_agent.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_AGENT_SYSTEM_PROMPTS"
            for t in node.targets
        ):
            return ast.literal_eval(node.value)["loop_truncated_tools_agent"]
    raise RuntimeError("Upstream system prompt not found")


def as_text(content):
    if content is None:
        return ""
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content)


def positive_env(name, default):
    value = int(os.environ.get(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


class ApexAgent(Agent):
    def __init__(self):
        self.conn = None
        self.session_id = None
        self.model = os.environ.get("HARBOR_ACP_REQUESTED_MODEL", "unconfigured")
        self.gateway = "http://world:8000/mcp/"
        self.process = None
        self.running = False
        self.used = False
        self.cancelled = False

    def on_connect(self, conn):
        self.conn = conn

    async def initialize(self, protocol_version, **kwargs):
        return InitializeResponse(
            protocol_version=PROTOCOL_VERSION,
            agent_info=Implementation(name="apex-agents-1-1", version="0.1.0"),
            agent_capabilities=AgentCapabilities(
                mcp_capabilities=McpCapabilities(http=True)
            ),
            auth_methods=[],
        )

    async def new_session(self, cwd, mcp_servers=None, **kwargs):
        if self.session_id is not None:
            raise RequestError.invalid_params(
                {"reason": "One benchmark session per process"}
            )
        servers = mcp_servers or []
        worlds = [s for s in servers if s.name == "world"]
        if servers and len(worlds) != 1:
            raise RequestError.invalid_params(
                {"reason": "Expected one HTTP MCP server named world"}
            )
        if worlds:
            server = worlds[0]
            if getattr(server, "type", None) != "http" or getattr(
                server, "headers", []
            ):
                raise RequestError.invalid_params(
                    {"reason": "APEX expects its unauthenticated HTTP world gateway"}
                )
            self.gateway = server.url
        self.session_id = str(uuid4())
        return NewSessionResponse(
            session_id=self.session_id,
            config_options=self.model_options(),
            models=SessionModelState(
                current_model_id=self.model,
                available_models=[ModelInfo(model_id=self.model, name=self.model)],
            ),
        )

    def model_options(self):
        return [
            SessionConfigOption.model_validate(
                {
                    "id": "model",
                    "name": "Model",
                    "category": "model",
                    "type": "select",
                    "currentValue": self.model,
                    "options": [{"value": self.model, "name": self.model}],
                }
            )
        ]

    async def set_config_option(self, config_id, session_id, value, **kwargs):
        if config_id != "model":
            raise RequestError.invalid_params({"reason": "Unknown config option"})
        await self.set_session_model(value, session_id)
        return SetSessionConfigOptionResponse(config_options=self.model_options())

    def check_session(self, session_id):
        if not self.session_id or session_id != self.session_id:
            raise RequestError.invalid_params({"reason": "Unknown session"})

    async def set_session_model(self, model_id, session_id, **kwargs):
        self.check_session(session_id)
        if self.running or not model_id or model_id == "unconfigured":
            raise RequestError.invalid_params(
                {"reason": "A provider/model is required before starting"}
            )
        self.model = model_id
        return SetSessionModelResponse()

    async def cancel(self, session_id, **kwargs):
        self.check_session(session_id)
        self.cancelled = True
        await self.stop_process()

    async def stop_process(self):
        process = self.process
        if process is None or process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), 5)
        except TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()

    async def replay(self, native):
        """Emit all calls in a turn before their results, preserving grouping."""
        for message in native.get("messages", []):
            role = message.get("role")
            if role == "assistant":
                reasoning = message.get("reasoning_content")
                if reasoning:
                    await self.conn.session_update(
                        session_id=self.session_id,
                        update=AgentThoughtChunk(
                            session_update="agent_thought_chunk",
                            content=text_block(reasoning),
                        ),
                    )
                content = as_text(message.get("content"))
                # Empty chunks still establish a boundary after a tool cycle.
                await self.conn.session_update(
                    session_id=self.session_id,
                    update=AgentMessageChunk(
                        session_update="agent_message_chunk",
                        content=text_block(content),
                    ),
                )
                for call in message.get("tool_calls") or []:
                    fn = call.get("function") or {}
                    arguments = fn.get("arguments", {})
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except ValueError:
                            arguments = {"_raw": arguments}
                    await self.conn.session_update(
                        session_id=self.session_id,
                        update=ToolCallStart(
                            session_update="tool_call",
                            tool_call_id=call["id"],
                            title=fn["name"],
                            kind="other",
                            status="in_progress",
                            raw_input=arguments,
                        ),
                    )
            elif role == "tool":
                await self.conn.session_update(
                    session_id=self.session_id,
                    update=ToolCallProgress(
                        session_update="tool_call_update",
                        tool_call_id=message["tool_call_id"],
                        status="completed",
                        raw_output=as_text(message.get("content")),
                    ),
                )

    async def prompt(self, prompt, session_id, **kwargs):
        self.check_session(session_id)
        if self.used or self.running:
            raise RequestError.invalid_params(
                {"reason": "One prompt per benchmark session"}
            )
        if self.model == "unconfigured":
            raise RequestError.invalid_params(
                {"reason": "Select a provider/model first"}
            )
        if not prompt or any(getattr(p, "type", None) != "text" for p in prompt):
            raise RequestError.invalid_params(
                {"reason": "APEX task instructions must be text"}
            )
        self.used = self.running = True
        logs = Path(os.environ.get("APEX_LOG_DIR", "/logs/agent"))
        logs.mkdir(parents=True, exist_ok=True)
        messages = [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": "\n".join(p.text for p in prompt)},
        ]
        config = json.loads((UPSTREAM / "manifest.json").read_text())["agent"]
        values = config["agent_config_values"]
        for key, env_name in (
            ("max_steps", "MAX_STEPS"),
            ("timeout", "AGENT_TIMEOUT_SEC"),
            ("max_output_chars", "MAX_OUTPUT_CHARS"),
            ("max_output_lines", "MAX_OUTPUT_LINES"),
            ("tool_call_timeout", "TOOL_CALL_TIMEOUT"),
            ("llm_response_timeout", "LLM_RESPONSE_TIMEOUT"),
        ):
            values[key] = positive_env(env_name, values[key])
        messages_path = logs / "messages.json"
        config_path = logs / "agent_config.json"
        native_path = logs / "trajectory.native.json"
        messages_path.write_text(json.dumps(messages))
        config_path.write_text(json.dumps(config))
        native_path.unlink(missing_ok=True)
        command = [
            sys.executable,
            str(UPSTREAM / "runner_src" / "runner_cli.py"),
            "--trajectory-id",
            session_id,
            "--initial-messages",
            str(messages_path),
            "--agent-config",
            str(config_path),
            "--mcp-gateway-url",
            self.gateway,
            "--orchestrator-model",
            self.model,
            "--output",
            str(native_path),
        ]
        try:
            with (logs / "agent_run.log").open("w") as log:
                self.process = await asyncio.create_subprocess_exec(
                    *command, cwd=ROOT, stdout=log, stderr=log, start_new_session=True
                )
                if self.cancelled:
                    await self.stop_process()
                try:
                    await asyncio.wait_for(
                        self.process.wait(),
                        config["agent_config_values"]["timeout"] + 60,
                    )
                except TimeoutError:
                    await self.stop_process()
                    raise RequestError(
                        -32603, "APEX runner exceeded its timeout; see agent_run.log"
                    )
            native = (
                json.loads(native_path.read_text()) if native_path.exists() else None
            )
            if native:
                await self.replay(native)
            if self.cancelled or (native and native.get("status") == "cancelled"):
                return PromptResponse(stop_reason="cancelled")
            if (
                self.process.returncode != 0
                or not native
                or native.get("status") != "completed"
            ):
                # The original CLI may exit 0 with status=error/failed. Surface
                # this to Harbor so infrastructure failures aren't scored zeros.
                status = native.get("status") if native else "missing trajectory"
                raise RequestError(
                    -32603,
                    f"APEX runner did not complete ({status}); see agent_run.log",
                )
            raw = native.get("usage") or {}
            input_tokens = int(raw.get("prompt_tokens") or 0)
            output_tokens = int(raw.get("completion_tokens") or 0)
            return PromptResponse(
                stop_reason="end_turn",
                usage=Usage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    cached_read_tokens=int(raw.get("cached_tokens") or 0),
                ),
            )
        finally:
            await self.stop_process()
            self.running = False
