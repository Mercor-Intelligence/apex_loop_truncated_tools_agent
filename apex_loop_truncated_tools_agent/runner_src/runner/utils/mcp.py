"""MCP client helpers for agents using LiteLLM."""

import asyncio
import ssl
import time
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

import httpx
from fastmcp import Client as FastMCPClient
from fastmcp.client.transports import ClientTransport
from loguru import logger
from mcp.types import ContentBlock, ImageContent, TextContent

from runner.agents.models import LitellmInputMessage
from runner.utils.image_fetch import normalize_mcp_image_for_anthropic

# Grace period (seconds) to wait for a shielded MCP tool call to finish
# after the primary timeout expires, before forcibly cancelling it.
SHIELDED_TASK_GRACE_SECONDS = 5.0


async def drain_shielded_task(task: asyncio.Task[Any]) -> None:
    """Wait for a shielded MCP task to finish, cancelling if it takes too long.

    After an ``asyncio.wait_for`` timeout, the shielded inner task is still
    running and holds the MCP session open.  Attempting a new tool call on the
    same session while the old one is in-flight causes a
    ``RuntimeError("Client is not connected")`` from the streamable-http
    transport.

    This helper gives the task a short grace period to complete naturally.  If
    it doesn't finish in time, the task is cancelled so the session is released
    before the next call.
    """
    if task.done():
        return
    try:
        await asyncio.wait_for(task, timeout=SHIELDED_TASK_GRACE_SECONDS)
    except (TimeoutError, Exception):
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


def build_mcp_gateway_schema(
    mcp_gateway_url: str,
    mcp_gateway_auth_token: str | None,
    mcp_gateway_actor_id: str | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    """
    Build the MCP client config schema for connecting to the environment's MCP gateway.

    The gateway is a single HTTP endpoint that proxies to all configured MCP servers
    in the environment sandbox.

    Args:
        mcp_gateway_url: URL of the MCP gateway (e.g. "http://localhost:8000/mcp/")
        mcp_gateway_auth_token: Real bearer token for authenticated gateway runtimes.
        mcp_gateway_actor_id: Runtime actor ID for user tenancy.

    Returns:
        The standard schema expected by the MCP client.
    """
    gateway_config: dict[str, Any] = {
        "transport": "streamable-http",
        "url": mcp_gateway_url,
    }

    # Authorization is only set when the runner explicitly provides a token or actor ID.
    auth_value = mcp_gateway_actor_id or mcp_gateway_auth_token
    if auth_value:
        gateway_config["headers"] = {"Authorization": f"Bearer {auth_value}"}

    return {
        "mcpServers": {
            "gateway": gateway_config,
        }
    }


MCP_SESSION_ACQUISITION_TIMEOUT_SECONDS = 30.0
MCP_SESSION_ACQUISITION_MAX_ATTEMPTS = 3


def _mcp_acquisition_cause(exception: BaseException) -> BaseException:
    while isinstance(exception, RuntimeError) and (
        str(exception).startswith("Client failed to connect: ")
        or str(exception) == "Failed to initialize server session"
    ):
        if exception.__cause__ is None:
            break
        exception = exception.__cause__
    return exception


def _is_transient_mcp_acquisition_error(exception: BaseException) -> bool:
    exception = _mcp_acquisition_cause(exception)
    if isinstance(exception, BaseExceptionGroup):
        return all(_is_transient_mcp_acquisition_error(e) for e in exception.exceptions)
    if isinstance(exception, httpx.HTTPStatusError):
        return exception.response.status_code in (408, 429, 500, 502, 503, 504)
    if isinstance(exception, httpx.ConnectError) and (
        "[ssl:" in str(exception).lower()
        or "certificate verify failed" in str(exception).lower()
    ):
        return False
    cause = exception
    while cause is not None:
        if isinstance(cause, ssl.SSLError):
            return False
        cause = cause.__cause__
    return isinstance(
        exception,
        (TimeoutError, ConnectionError, httpx.NetworkError, httpx.TimeoutException),
    )


def _mcp_acquisition_error_details(exception: BaseException | None) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    pending: list[tuple[BaseException, int | None, str]] = (
        [(exception, None, "root")] if exception is not None else []
    )
    seen: set[int] = set()
    truncated = False
    while pending and len(nodes) < 16:
        current, parent, relation = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        index = len(nodes)
        node: dict[str, Any] = {
            "type": type(current).__name__[:128],
            "module": type(current).__module__[:128],
            "parent": parent,
            "relation": relation,
        }
        if isinstance(current, httpx.HTTPStatusError):
            node["http_status"] = current.response.status_code
        nodes.append(node)
        if isinstance(current, BaseExceptionGroup):
            truncated |= len(current.exceptions) > 16
            pending.extend(
                (child, index, "group") for child in reversed(current.exceptions[:16])
            )
        if current.__context__ is not None:
            pending.append((current.__context__, index, "context"))
        if current.__cause__ is not None:
            pending.append((current.__cause__, index, "cause"))
    return {
        "error_chain": nodes,
        "error_chain_truncated": truncated or bool(pending),
    }


def _log_mcp_acquisition(
    outcome: str,
    attempt: int,
    started_at: float,
    attempt_started_at: float,
    exception: BaseException | None = None,
    *,
    retry_delay_seconds: float = 0.0,
    error_type: str | None = None,
) -> None:
    try:
        now = time.monotonic()
        logger.bind(
            message_type="mcp_session",
            outcome=outcome,
            attempt=attempt,
            elapsed_seconds=now - started_at,
            attempt_elapsed_seconds=now - attempt_started_at,
            retry_delay_seconds=retry_delay_seconds,
            error_type=error_type[:128] if error_type else None,
            **_mcp_acquisition_error_details(exception),
        ).log(
            "INFO" if outcome in ("recovered", "cancelled") else "WARNING",
            "Transient MCP session acquisition failure; retrying"
            if outcome == "retrying"
            else f"MCP session acquisition {outcome}",
        )
    except Exception:
        pass


@asynccontextmanager
async def acquire_mcp_session[T: ClientTransport](
    client: FastMCPClient[T],
) -> AsyncIterator[FastMCPClient[T]]:
    async with AsyncExitStack() as stack:
        deadline = asyncio.timeout(MCP_SESSION_ACQUISITION_TIMEOUT_SECONDS)
        started_at = attempt_started_at = time.monotonic()
        attempt = 0
        try:
            async with deadline:
                while True:
                    attempt_started_at = time.monotonic()
                    try:
                        connected = await stack.enter_async_context(client)
                    except Exception as exc:
                        cause = _mcp_acquisition_cause(exc)
                        if isinstance(cause.__context__, BaseExceptionGroup):
                            cause = cause.__context__
                        exhausted = attempt + 1 >= MCP_SESSION_ACQUISITION_MAX_ATTEMPTS
                        if exhausted or not _is_transient_mcp_acquisition_error(cause):
                            _log_mcp_acquisition(
                                "attempt_limit" if exhausted else "not_retryable",
                                attempt + 1,
                                started_at,
                                attempt_started_at,
                                exc,
                                error_type=type(cause).__name__,
                            )
                            raise
                        delay = 0.5 * 2.0**attempt
                        _log_mcp_acquisition(
                            "retrying",
                            attempt + 1,
                            started_at,
                            attempt_started_at,
                            exc,
                            retry_delay_seconds=delay,
                            error_type=type(cause).__name__,
                        )
                        await asyncio.sleep(delay)
                        attempt += 1
                    else:
                        break
        except TimeoutError as exc:
            if not deadline.expired():
                raise
            _log_mcp_acquisition(
                "deadline", attempt + 1, started_at, attempt_started_at, exc
            )
            raise ConnectionError(
                f"MCP session acquisition timed out after {MCP_SESSION_ACQUISITION_TIMEOUT_SECONDS} seconds"
            ) from exc
        except asyncio.CancelledError as exc:
            _log_mcp_acquisition(
                "cancelled", attempt + 1, started_at, attempt_started_at, exc
            )
            raise
        if attempt:
            _log_mcp_acquisition(
                "recovered", attempt + 1, started_at, attempt_started_at
            )
        yield connected


def content_blocks_to_messages(
    content_blocks: list[ContentBlock],
    tool_call_id: str,
    name: str,
    model: str,
    deferred_image_messages: list[LitellmInputMessage],
    *,
    downscale_images: bool = False,
) -> list[LitellmInputMessage]:
    """
    Convert MCP content blocks to a single LiteLLM tool message.

    Each tool_use must have exactly one tool_result. This function combines all
    content blocks into a single tool message to satisfy API requirements for
    Anthropic, OpenAI, and other providers.

    For non-Anthropic models, images cannot be embedded in tool results, so they
    are appended to deferred_image_messages as user messages. The caller is
    responsible for adding them to self.messages after all tool responses.
    This list is mutated in place.

    Args:
        content_blocks: MCP content blocks from tool result
        tool_call_id: The tool call ID to associate with the result
        name: The tool name
        model: The model being used
        deferred_image_messages: Mutable list that image user messages are
            appended to (mutated in place). Callers should extend self.messages
            with this list after all tool responses are added.
        downscale_images: When True and model is Anthropic, downscale tool images
            to 2000px max dimension (for 20+ image conversations). Ignored for
            non-Anthropic models.

    Returns:
        List containing exactly one tool message.
    """
    # Anthropic supports images directly in tool results
    supports_image_tool_results = model.startswith("anthropic/")

    text_contents: list[str] = []
    image_data_uris: list[str] = []

    for content_block in content_blocks:
        match content_block:
            case TextContent():
                block = TextContent.model_validate(content_block)
                text_contents.append(block.text)

            case ImageContent():
                block = ImageContent.model_validate(content_block)
                if supports_image_tool_results:
                    data_b64, mime = normalize_mcp_image_for_anthropic(
                        block.data,
                        block.mimeType,
                        downscale=downscale_images,
                    )
                    data_uri = f"data:{mime};base64,{data_b64}"
                else:
                    data_uri = f"data:{block.mimeType};base64,{block.data}"
                image_data_uris.append(data_uri)

            case _:
                logger.warning(f"Content block type {content_block.type} not supported")
                text_contents.append("Unable to parse tool call response")

    messages: list[LitellmInputMessage] = []

    if supports_image_tool_results:
        content: list[dict[str, Any]] = []
        for text in text_contents:
            content.append({"type": "text", "text": text or " "})
        for data_uri in image_data_uris:
            content.append({"type": "image_url", "image_url": {"url": data_uri}})

        if image_data_uris and not any(
            block.get("type") == "text" for block in content
        ):
            content.insert(0, {"type": "text", "text": " "})

        tool_message: LitellmInputMessage = {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": name,
            "content": content if content else [{"type": "text", "text": " "}],
        }  # pyright: ignore[reportAssignmentType]
        messages.append(tool_message)
    else:
        content = [{"type": "text", "text": text or " "} for text in text_contents]

        if image_data_uris and not content:
            content.append(
                {"type": "text", "text": f"Image(s) returned by {name} tool"}
            )

        tool_message = {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": name,
            "content": content if content else [{"type": "text", "text": " "}],
        }  # pyright: ignore[reportAssignmentType]
        messages.append(tool_message)

        # Image workaround: non-Anthropic models don't support images in tool results,
        # so we append them to deferred_image_messages for the caller to add after all tool responses.
        for data_uri in image_data_uris:
            deferred_image_messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            )

    return messages
