"""Convert a Harbor ATIF trajectory into the archipelago grading shape.

Harbor agents write ATIF to ``/logs/agent/trajectory.json``; the grading runner
takes an ``AgentTrajectoryOutput`` (litellm-style ``messages``). Keeping the
translation here means every Harbor-shaped dataset grades through the same path.
"""

import json
from typing import Any


def text_of(content: Any) -> str:
    """Normalize ATIF message content (str or content-parts) to a string."""
    if content is None:
        return ""
    if isinstance(content, list):
        parts = [
            str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in content
        ]
        return " ".join(p for p in parts if p)
    return str(content)


def _tool_calls(step: dict[str, Any]) -> list[dict[str, Any]]:
    calls = []
    for call in step.get("tool_calls") or []:
        arguments = call.get("arguments")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments or {})
        calls.append(
            {
                "id": call.get("tool_call_id"),
                "type": "function",
                "function": {"name": call.get("function_name"), "arguments": arguments},
            }
        )
    return calls


def atif_to_native(trajectory: dict[str, Any]) -> dict[str, Any]:
    """ATIF -> AgentTrajectoryOutput. A native trajectory passes through."""
    if not str(trajectory.get("schema_version", "")).startswith("ATIF"):
        # A bare-string output still fails AgentTrajectoryOutput validation.
        if isinstance(trajectory.get("output"), str):
            return dict(trajectory, output={"final_answer": trajectory["output"]})
        return trajectory

    messages: list[dict[str, Any]] = []
    for step in trajectory.get("steps") or []:
        source = step.get("source")
        text = text_of(step.get("message"))
        if source in ("system", "user"):
            messages.append({"role": source, "content": text})
            continue

        message: dict[str, Any] = {"role": "assistant", "content": text}
        if calls := _tool_calls(step):
            message["tool_calls"] = calls
        messages.append(message)

        for result in (step.get("observation") or {}).get("results") or []:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": result.get("source_call_id"),
                    "content": text_of(result.get("content")),
                }
            )

    output = None
    for message in reversed(messages):
        if message["role"] == "assistant" and message.get("content"):
            output = {"final_answer": message["content"]}
            break

    extra = trajectory.get("extra") or {}
    return {
        "messages": messages,
        "output": output,
        # Agents that round-trip a native status through ATIF extra keep it;
        # stock Harbor agents grade as completed.
        "status": str(extra.get("native_status") or "completed"),
        "time_elapsed": float(extra.get("time_elapsed_sec") or 0.0),
    }
