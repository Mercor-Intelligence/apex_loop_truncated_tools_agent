"""Merge the Responses->chat bridge's split tool-call choices into one choice.

LiteLLM's chat-completions bridge turns each Responses ``message`` item into
its own choice (finish_reason "stop") and puts the accumulated tool calls in a
separate trailing choice (finish_reason "tool_calls"). The loop reads
``choices[0]``, so a preamble plus tool calls would end the run on the
preamble. This is the same merge the benchmark's leaderboard runs applied at
their LiteLLM proxy; it is a no-op unless a response has the split pattern.
Streaming already lands on one choice and is not patched.
"""

import litellm

_patched = False


def _merge_split_tool_choices(choices):
    if not isinstance(choices, list) or len(choices) < 2:
        return choices

    tool_idxs = [
        i
        for i, c in enumerate(choices)
        if getattr(c, "finish_reason", None) == "tool_calls"
        and getattr(getattr(c, "message", None), "tool_calls", None)
    ]
    stop_idxs = [
        i for i, c in enumerate(choices) if getattr(c, "finish_reason", None) == "stop"
    ]
    if len(tool_idxs) != 1 or not stop_idxs or len(tool_idxs) + len(stop_idxs) != len(
        choices
    ):
        return choices

    merged_choice = choices[tool_idxs[0]]
    merged_msg = merged_choice.message
    stop_msgs = [choices[i].message for i in stop_idxs]

    texts = [m.content for m in stop_msgs if getattr(m, "content", None)]
    merged_msg.content = "\n".join(texts) if texts else None

    for field in ("reasoning_content", "reasoning_items", "annotations"):
        if getattr(merged_msg, field, None) is None:
            for m in stop_msgs:
                value = getattr(m, field, None)
                if value is not None:
                    try:
                        setattr(merged_msg, field, value)
                    except Exception:
                        pass
                    break

    merged_choice.index = 0
    return [merged_choice]


def _apply_patch() -> None:
    global _patched
    if _patched:
        return
    try:
        from litellm.completion_extras.litellm_responses_transformation.transformation import (
            LiteLLMResponsesTransformationHandler,
        )

        _orig = LiteLLMResponsesTransformationHandler._convert_response_output_to_choices

        def _convert_and_merge(*args, **kwargs):
            choices = _orig(*args, **kwargs)
            try:
                return _merge_split_tool_choices(choices)
            except Exception:
                litellm.verbose_logger.exception(
                    "responses bridge split-choice merge failed for one response"
                )
                return choices

        LiteLLMResponsesTransformationHandler._convert_response_output_to_choices = (
            staticmethod(_convert_and_merge)
        )
        _patched = True
    except Exception:
        litellm.verbose_logger.exception(
            "responses bridge split-choice patch failed to apply; "
            "bridged tool calls stay split across choices"
        )


_apply_patch()
