"""Task-agnostic APEX benchmark agent for harbor (import-path plugin).

One agent serves ALL tasks in this delivery: the per-task world slug and
world secrets reach the WORLD container via the task's compose file, and the
agent runs inside the MAIN container, reaching the world gateway over the
trial network (http://world:8000/mcp/). Everything executes in-sandbox via
env.exec — no host ports; setup() provisions only this delivery's own
vendored runner into the main container.

Run shape:
    PYTHONPATH=<delivery>/agent harbor run -p tasks/mercor-<slug> \
        -a apex_loop_truncated_tools_agent:ApexLoopTruncatedToolsAgent -m <model>

This package exposes only the canonical 250-step truncated-loop harness.
"""
from __future__ import annotations

import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

_RUNNER_DIR = "/agent_runner"
_LOG = "/logs/agent"

# Canonical system prompt recorded for this benchmark harness.
_AGENT_SYSTEM_PROMPTS = {
    "loop_truncated_tools_agent": 'You are an agent that completes tasks independently. Use the tools provided to you to complete the task to the best of your ability. You should use the code_exec tool when needed, such as when calculating values. When calculating numbers, unless specified otherwise, use the exact values without rounding them.\n\nYou must attempt to execute the task. You cannot ask for help or further clarification.\n\nFor every tool except the code_exec tool, you may assume that all relevant files are located under the root path /. For the code_exec tool, however, you must explicitly use /filesystem/ as the root path to locate all relevant files.',
}


def _env_int(name, default):
    """Integer env override; non-numeric values warn and keep the default."""
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"WARNING: ignoring non-numeric {name}={raw!r}", file=sys.stderr)
        return default


def _text(content):
    """Normalize message content to a string (handle content-parts lists)."""
    if content is None:
        return ""
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content)


def _args_obj(arguments):
    """tool_call arguments arrive as a JSON string; ATIF wants an object."""
    if isinstance(arguments, dict):
        return arguments
    try:
        v = json.loads(arguments)
        return v if isinstance(v, dict) else {"_value": v}
    except Exception:
        return {"_raw": str(arguments)}


def _metrics_from_call(c):
    if not c:
        return None
    m = {
        "prompt_tokens": c.get("prompt_tokens"),
        "completion_tokens": c.get("completion_tokens"),
        "cached_tokens": c.get("cached_tokens"),
    }
    extra = {
        k: c[k]
        for k in ("cache_creation_tokens", "reasoning_tokens", "total_tokens")
        if k in c
    }
    if extra:
        m["extra"] = extra
    return {k: v for k, v in m.items() if v is not None or k == "extra"}


def convert_trajectory(traj: dict) -> dict:
    """APEX-native trajectory -> ATIF (the harbor trajectory standard)."""
    messages = traj.get("messages") or []
    call_log = (traj.get("usage") or {}).get("call_log") or []

    steps = []
    a_idx = 0
    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get("role")
        if role in ("system", "user"):
            steps.append(
                {
                    "step_id": len(steps) + 1,
                    "source": role,
                    "message": _text(msg.get("content")),
                }
            )
            i += 1
            continue
        if role == "assistant":
            step = {
                "step_id": len(steps) + 1,
                "source": "agent",
                "message": _text(msg.get("content")),
            }
            atif_tcs = []
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                cid = tc.get("id") or fn.get("name")
                atif_tcs.append(
                    {
                        "tool_call_id": cid,
                        "function_name": fn.get("name"),
                        "arguments": _args_obj(fn.get("arguments")),
                    }
                )
            if atif_tcs:
                step["tool_calls"] = atif_tcs
            mx = _metrics_from_call(call_log[a_idx] if a_idx < len(call_log) else None)
            if mx:
                step["metrics"] = mx
            a_idx += 1
            results = []
            j = i + 1
            while j < len(messages) and messages[j].get("role") == "tool":
                tm = messages[j]
                results.append(
                    {
                        "source_call_id": tm.get("tool_call_id"),
                        "content": _text(tm.get("content")),
                    }
                )
                j += 1
            if results:
                step["observation"] = {"results": results}
            steps.append(step)
            i = j
            continue
        steps.append(
            {
                "step_id": len(steps) + 1,
                "source": "agent",
                "message": _text(msg.get("content")),
                "extra": {"native_role": role},
            }
        )
        i += 1

    u = traj.get("usage") or {}
    final_metrics = {
        k: v
        for k, v in {
            "total_prompt_tokens": u.get("prompt_tokens"),
            "total_completion_tokens": u.get("completion_tokens"),
            "total_cached_tokens": u.get("cached_tokens"),
            "total_steps": len(steps),
        }.items()
        if v is not None
    }
    return {
        "schema_version": "ATIF-v1.5",
        "session_id": traj.get("session_id") or "apex-agent",
        "agent": {"name": "apex_loop_truncated_tools_agent", "version": "1.0"},
        "steps": steps,
        "final_metrics": final_metrics,
        "extra": {
            "converted_from": "apex-native",
            "native_status": traj.get("status"),
            "time_elapsed_sec": traj.get("time_elapsed"),
            "native_output": traj.get("output"),
        },
    }


class ApexLoopTruncatedToolsAgent(BaseAgent):
    @staticmethod
    def name() -> str:
        return "apex_loop_truncated_tools_agent"

    def version(self) -> str:
        return "1.0"

    def __init__(self, logs_dir, model_name=None, logger=None, mcp_servers=None,
                 skills_dir=None, *, runner_src: str | None = None,
                 gateway_url: str = "http://world:8000/mcp/",
                 max_steps: int | None = None,
                 agent_timeout_sec: int | None = None,
                 agent_config_id: str | None = None, **kwargs):
        super().__init__(logs_dir=logs_dir, model_name=model_name, logger=logger,
                         mcp_servers=mcp_servers, skills_dir=skills_dir)
        # The vendored runner ships next to this file in the delivery.
        self._runner_src = runner_src or str(
            Path(__file__).resolve().parent / "runner_src"
        )
        self._gateway_url = gateway_url
        # Canonical defaults; environment variables may override them.
        self._max_steps = (
            max_steps if max_steps is not None else _env_int("MAX_STEPS", 250)
        )
        self._agent_timeout = (
            agent_timeout_sec
            if agent_timeout_sec is not None
            else _env_int("AGENT_TIMEOUT_SEC", 10800)
        )
        # The delivery intentionally exposes only the benchmark harness.
        self._agent_config_id = (
            agent_config_id
            if agent_config_id is not None
            else "loop_truncated_tools_agent"
        )
        self._agent_name = self._agent_config_id.replace("_", " ").title()

    async def setup(self, environment: BaseEnvironment) -> None:
        # The world boots itself (compose sidecar, POST-healthcheck-gated) —
        # setup only provisions the runner project into the MAIN container.
        src = Path(self._runner_src).resolve()
        if not src.exists():
            raise FileNotFoundError(f"runner_src not found: {src}")
        with tempfile.TemporaryDirectory() as td:
            tar_path = Path(td) / "runner.tar.gz"
            with tarfile.open(tar_path, "w:gz") as tf:
                for item in src.iterdir():
                    if item.name in (".venv", "__pycache__", ".git"):
                        continue
                    tf.add(item, arcname=item.name)
            await environment.exec(command=f"mkdir -p {_RUNNER_DIR} {_LOG}")
            await environment.upload_file(source_path=str(tar_path),
                                          target_path=f"{_RUNNER_DIR}/runner.tar.gz")
        await environment.exec(
            command=f"tar xzf {_RUNNER_DIR}/runner.tar.gz -C {_RUNNER_DIR}"
        )

    async def _preflight_credentials(self, model, environment) -> None:
        """Fail in seconds when the model's provider credentials are absent
        from the MAIN container env (the runner reads container env, not the
        host's) — a missing key otherwise burns the whole agent timeout in
        LLM retries."""
        required = {
            "anthropic": ("ANTHROPIC_API_KEY",),
            "openai": ("OPENAI_API_KEY",),
            "gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
            "fireworks_ai": ("FIREWORKS_AI_API_KEY", "FIREWORKS_API_KEY"),
            "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
            "litellm_proxy": ("LITELLM_PROXY_API_KEY",),
        }.get(model.split("/", 1)[0].lower())
        if not required:
            return
        probe = await environment.exec(command="env")
        present = set()
        for line in (probe.stdout or "").splitlines():
            key, sep, value = line.partition("=")
            if sep and value:
                present.add(key)
        # The vendored runner auto-routes through the LiteLLM proxy whenever
        # the proxy pair is set, regardless of the model's provider prefix.
        if {"LITELLM_PROXY_API_BASE", "LITELLM_PROXY_API_KEY"} <= present:
            return
        if not any(key in present for key in required):
            raise ValueError(
                f"no credentials for model {model!r} in the task container:"
                f" set one of {' / '.join(required)} (or the LITELLM_PROXY_*"
                " pair) before running"
            )

    async def run(self, instruction: str, environment: BaseEnvironment,
                  context: AgentContext) -> None:
        # No hardcoded model fallback: a missing model fails loudly.
        model = self.model_name
        if not model:
            raise ValueError(
                "no agent model configured: pass -m <provider/model> to "
                "harbor run (run_task.sh resolves it from models.json)"
            )
        await self._preflight_credentials(model, environment)
        msgs = []
        system_prompt = _AGENT_SYSTEM_PROMPTS.get(self._agent_config_id)
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.append({"role": "user", "content": instruction})
        messages = json.dumps(msgs)
        agent_config = json.dumps({
            "agent_config_id": "loop_truncated_tools_agent",
            "agent_name": "Loop w/ Tool Truncation (250 max steps)",
            "agent_config_values": {
                "timeout": self._agent_timeout,
                "max_steps": self._max_steps,
                "max_output_chars": _env_int("MAX_OUTPUT_CHARS", 32768),
                "max_output_lines": _env_int("MAX_OUTPUT_LINES", 200),
                "tool_call_timeout": _env_int("TOOL_CALL_TIMEOUT", 60),
                "llm_response_timeout": _env_int("LLM_RESPONSE_TIMEOUT", 600),
            },
        })
        await environment.exec(command=(
            f"mkdir -p {_LOG}; "
            f"cat > {_LOG}/messages.json <<'EOF'\n{messages}\nEOF\n"
            f"cat > {_LOG}/agent_config.json <<'EOF'\n{agent_config}\nEOF"))
        run_cmd = f"""
set -eu
command -v uv >/dev/null 2>&1 || {{ echo "uv missing" >&2; exit 1; }}
PROJ_FILE=$(find {_RUNNER_DIR} -maxdepth 3 -name pyproject.toml | head -1)
[ -n "$PROJ_FILE" ] || {{ echo "no pyproject under {_RUNNER_DIR}" >&2; exit 1; }}
PROJ=$(dirname "$PROJ_FILE")
cd "$PROJ"
find runner -type d -exec touch {{}}/__init__.py \\; 2>/dev/null || true
UV_PYTHON="$(command -v python3)"
export UV_PYTHON
uv sync --frozen --no-install-project >&2
rc=0
uv run python -m runner_cli \
  --trajectory-id "harbor-${{WORLD_TASK_SLUG:-task}}" \
  --initial-messages {_LOG}/messages.json \
  --mcp-gateway-url {self._gateway_url} \
  --agent-config {_LOG}/agent_config.json \
  --orchestrator-model {model!r} \
  --output {_LOG}/trajectory.native.json > {_LOG}/agent_run.log 2>&1 || rc=$?
cat {_LOG}/agent_run.log
exit $rc
"""
        res = await environment.exec(command=run_cmd,
                                     timeout_sec=self._agent_timeout + 900)
        tail = "\n".join(p for p in (res.stdout, res.stderr) if p)[-2000:]
        self.logger.info(f"[apex-agent] run tail:\n{tail}")
        context.metadata = {"tail": tail, "return_code": res.return_code}
        # Preserve whatever trajectory exists before surfacing the failure —
        # a crashed runner must error the trial, not grade as empty work.
        self._write_atif_trajectory()
        if res.return_code != 0:
            raise RuntimeError(
                f"APEX runner exited {res.return_code}"
                f" (see {_LOG}/agent_run.log); tail:\n{tail}"
            )

    def populate_context_post_run(self, context: AgentContext) -> None:
        # native is authoritative; the in-run pass may have written an empty
        # placeholder before /logs synced. Re-convert once native is readable.
        if (self.logs_dir / "trajectory.native.json").exists():
            self._write_atif_trajectory()

    def _write_atif_trajectory(self) -> None:
        """Convert the runner's native trajectory to ATIF at the standard
        path; an absent or unparseable native file yields an empty-steps
        ATIF so grading judges the absence of work instead of erroring."""
        native_path = self.logs_dir / "trajectory.native.json"
        try:
            native = json.loads(native_path.read_text())
        except Exception:
            self.logger.warning(
                f"[apex-agent] native trajectory missing/unreadable at "
                f"{native_path}; writing empty ATIF"
            )
            native = {"messages": []}
        atif = convert_trajectory(native)
        (self.logs_dir / "trajectory.json").write_text(json.dumps(atif, indent=2))
