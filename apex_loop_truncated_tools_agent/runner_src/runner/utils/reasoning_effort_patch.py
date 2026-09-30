"""Send reasoning effort values the Responses bridge does not recognize verbatim.

LiteLLM's chat->Responses bridge maps effort strings through a fixed list and
drops anything else, so a level added after the pinned release (e.g. "max"
before LiteLLM knew it) silently ran at the default effort. Passing the value
through lets the provider accept it or reject it with a clear error.
"""

import litellm

_patched = False


def _apply_patch() -> None:
    global _patched
    if _patched:
        return
    try:
        from litellm.completion_extras.litellm_responses_transformation import (
            transformation,
        )

        handler = transformation.LiteLLMResponsesTransformationHandler
        _orig = handler._map_reasoning_effort

        def _map_or_pass_through(self, reasoning_effort):
            mapped = _orig(self, reasoning_effort)
            if mapped is None and isinstance(reasoning_effort, str) and reasoning_effort:
                return transformation.Reasoning(effort=reasoning_effort)
            return mapped

        handler._map_reasoning_effort = _map_or_pass_through
        _patched = True
    except Exception:
        litellm.verbose_logger.exception(
            "reasoning effort pass-through patch failed to apply; "
            "unrecognized effort values will be dropped by the Responses bridge"
        )


_apply_patch()
