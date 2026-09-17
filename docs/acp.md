# Run the reference agent through ACP

The optional `apex_acp` adapter exposes the reference runner through the Agent
Client Protocol (ACP) over standard input/output. `harbor-agent.json` describes
the entry point for clients that support Harbor agent manifests. The existing
`ApexLoopTruncatedToolsAgent` entry point is unchanged.

## Setup

From the repository root:

```sh
uv sync --frozen --python 3.12
uv run --frozen python -m apex_acp
```

The second command starts an ACP server, not an interactive chat. Configure an
ACP client to launch that command with this repository as its working directory.
The client must initialize the connection, create a session, select a
LiteLLM-compatible `provider/model`, and submit the task instruction as text.
Both the ACP model configuration option and `session/set_model` are supported.
`HARBOR_ACP_REQUESTED_MODEL` can also provide the initial model selection.

Supply provider credentials in the process environment, such as
`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`. For a LiteLLM proxy, use its standard
`LITELLM_PROXY_API_BASE` and `LITELLM_PROXY_API_KEY` variables. The adapter does
not load `.env` itself; the client must supply the environment. Do not put keys
in the manifest or commit them to this repository.

The benchmark world must already be running and reachable from the agent
process. Pass its unauthenticated HTTP MCP endpoint as the session's server
named `world`. If no server is supplied, the adapter uses
`http://world:8000/mcp/`, which assumes the benchmark's Compose network. It does
not launch worlds or run the grader; use the existing benchmark setup and
grading configuration for those steps.

## Behavior and limits

The adapter invokes the existing `runner_cli.py` directly in a subprocess. Its
optional root project supports Python 3.12 and 3.13; the Harbor manifest selects 3.12 because
that is the runtime currently accepted by Harbor's public manifest schema. The
reference runner's own Python 3.13 project is unchanged.

The root lockfile preserves the reference runner's dependency versions and adds
`agent-client-protocol==0.8.1`. It reads the system prompt from the reference
agent module and defaults from its manifest, applying only the environment
overrides below; the runner source is unchanged.

The supported environment overrides match the reference agent:

| Variable | Default |
| --- | --- |
| `MAX_STEPS` | `100` |
| `AGENT_TIMEOUT_SEC` | `10800` |
| `MAX_OUTPUT_LINES` | `200` |
| `MAX_OUTPUT_CHARS` | `32768` |
| `TOOL_CALL_TIMEOUT` | `60` |
| `LLM_RESPONSE_TIMEOUT` | `600` |

Model-specific options such as `APEX_MODEL_EXTRA_ARGS` pass through to the
reference runner. Its internal model-call retries are unchanged.

Each process accepts one session and one task prompt. Cancellation terminates
the runner's process group. A nonzero exit or native `failed`/`error` status
becomes an ACP error so clients can distinguish it from a completed answer.
This is stricter than the reference entry point's exit-code-only check. The
adapter also allows 60 seconds of subprocess overhead beyond the configured
runner timeout, compared with the reference entry point's 900 seconds.

Logs go to `/logs/agent`, or `APEX_LOG_DIR` if set. The full transcript is
preserved as `trajectory.native.json`, alongside `agent_run.log`, `messages.json`,
and `agent_config.json`. Assistant and tool events are replayed through ACP
after the runner exits; they are not streamed live. ACP events are text-oriented:
use the native transcript for full multimodal content. Clients are responsible
for converting ACP events to their desired trajectory format.

## Test locally

```sh
uv run --frozen python -m unittest discover -s tests -v
```

The tests use the real ACP transport and reference runner against local mock
inference and MCP servers. They check tool execution, final answers, token usage,
direct and proxy credentials, cancellation, failed-status propagation, and
absence of the fake credential in generated artifacts. They need loopback socket
access but no real API keys or paid model calls. These tests do not establish
leaderboard score parity.
